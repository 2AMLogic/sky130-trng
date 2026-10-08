#!/usr/bin/env python3
"""Re-derive, replay and fault-inject the RCT/APT health tests (issue #196).

**This runs no simulator.** It is pure Python over streams that are already
committed (the ``raw-bit-volume-campaign`` behavioural streams) and over the
min-entropy estimates already derived from them
(``sim/raw-bit-min-entropy/records/``). It extends
``health-test-cutoffs.py``, whose record evaluates the cutoffs at the
*design target* H = 0.5 and defers "the lookup once H is measured" -- this is
that lookup, plus the two things the arithmetic record never did:

1. **Re-derive.** ``params.c_rct``/``params.c_apt`` evaluated at each Ts =
   20 us stream's estimated min-entropy ``h_min_bits``, with an explicit
   verdict on the ratified ``C_RCT = 81`` / ``C_APT = 824``
   (conservative / tight / violated). Read-only: ``params.py`` and ``spec/``
   are never edited here.
2. **Replay.** Every Ts = 20 us stream through ``HealthMonitor`` at the
   ratified cutoffs, and through ``RepetitionCountTest`` /
   ``AdaptiveProportionTest`` individually. Counting convention: after each
   trip the individual test is ``reset()`` (restart) and counting continues;
   ``HealthMonitor`` is left to apply its own policy (a mid-run trip re-arms
   start-up and resets RCT/APT), and its ``update()`` returns are counted.
   Any alarm is reported as a finding, never filtered.
3. **Failure injection.** :func:`inject` splices a deterministic, seeded
   failure (stuck-at, bias step/ramp, short-period toggling) into a healthy
   stream; :func:`detection_latency` reports, per test, how many samples
   after onset the first trip happens (or that there was none within the
   horizon). Onsets are deliberately not aligned to the 1024-sample APT
   window.

Ts = 100 ns streams are not the design point and are excluded throughout.

Usage::

    python3 sim/digital-health-test-parameters/analysis/health-test-replay.py
    python3 sim/digital-health-test-parameters/analysis/health-test-replay.py --emit-record
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import statistics
import sys
import zlib
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402
from model import params  # noqa: E402
from model.health import (AdaptiveProportionTest, HealthMonitor,  # noqa: E402
                          RepetitionCountTest)

#: DR-0003 §2: the raw rate the health tests run at (20 us per sample).
RAW_RATE_BPS = 50_000.0

TS_NAME = "Ts20us"

#: (volume-campaign record, min-entropy record derived from it). Explicit,
#: never auto-selected: the 24-sample transistor streams and the 20260905/06
#: records must not be picked up by a glob.
SOURCES = [
    ("sim/raw-bit-volume-campaign/records/20261008-061809-56e0fb7.json",
     "sim/raw-bit-min-entropy/records/20261008-124312-5d44390.json"),
    # 125 C hot corner (#197); min-entropy record minted by this PR with the
    # existing --volume-record adapter (derived, no simulator).
    ("sim/raw-bit-volume-campaign/records/20261008-135454-847b454.json",
     "sim/raw-bit-min-entropy/records/20261008-150026-cd45d91.json"),
]

#: Injection offsets (sample index of the first injected sample). Chosen not
#: to be multiples of the 1024-sample APT window.
ONSETS = (2_000, 3_333, 5_117, 7_001, 9_500, 11_777)
#: Detection horizon, samples after onset (16 APT windows).
HORIZON = 16_384

#: Verdict thresholds on estimated H versus the H = 0.5 design target.
H_TIGHT_BAND = 0.05


# --------------------------------------------------------------------------
# Failure injector
# --------------------------------------------------------------------------

def _scenario_seed(*parts) -> int:
    """Stable (process-independent) seed from a scenario description."""
    return zlib.crc32("|".join(str(p) for p in parts).encode())


def inject(base: list[int], onset: int, kind: str, length: int, seed: int,
           *, value: int = 0, pattern: tuple[int, ...] = (0, 1),
           p0: float = 0.5, p1: float = 0.7,
           ramp_len: int = 0) -> tuple[list[int], dict]:
    """Return ``(spliced, info)``: ``base`` with ``[onset, onset+length)``
    replaced by a synthetic failure. ``base`` is not modified; the result has
    the same length. Deterministic in all arguments (``seed`` drives the only
    random draws, a private ``random.Random``).

    Kinds:

    * ``"stuck"``   -- constant ``value`` (0 or 1).
    * ``"toggle"``  -- ``pattern`` repeated (``(0, 1)`` is 0101...).
    * ``"bias"``    -- i.i.d. Bernoulli with ``Pr(1) = p(t)``: linear from
      ``p0`` to ``p1`` over ``ramp_len`` injected samples, then held at
      ``p1`` (``ramp_len = 0`` is a fixed-bias step to ``p1``; ``p0`` is
      unused then).
    """
    if not 0 <= onset <= len(base):
        raise ValueError("onset outside the stream")
    end = min(len(base), onset + length)
    n = end - onset
    out = list(base)
    rng = random.Random(seed)
    if kind == "stuck":
        if value not in (0, 1):
            raise ValueError("stuck value must be 0 or 1")
        seg = [value] * n
    elif kind == "toggle":
        if not pattern or any(b not in (0, 1) for b in pattern):
            raise ValueError("toggle pattern must be a non-empty 0/1 tuple")
        seg = [pattern[i % len(pattern)] for i in range(n)]
    elif kind == "bias":
        seg = []
        for i in range(n):
            p = p1 if ramp_len <= 0 or i >= ramp_len \
                else p0 + (p1 - p0) * i / ramp_len
            seg.append(1 if rng.random() < p else 0)
    else:
        raise ValueError(f"unknown injection kind {kind!r}")
    out[onset:end] = seg
    info = {"kind": kind, "onset": onset, "end": end, "length": n,
            "seed": seed}
    return out, info


def detection_latency(bits: list[int], onset: int, horizon: int,
                      c_rct: int = params.C_RCT, c_apt: int = params.C_APT,
                      w: int = params.W_APT) -> dict:
    """First trip of each test at or after ``onset`` (individual tests).

    Latency is ``index_of_failing_sample - onset + 1``, i.e. the number of
    injected samples consumed up to and including the failing one; ``None``
    means no trip within ``horizon`` samples. Trips *before* onset (healthy
    false alarms) are counted separately, each test restarting after a trip.
    """
    rct = RepetitionCountTest(c_rct)
    apt = AdaptiveProportionTest(w, c_apt)
    first = {"rct": None, "apt": None}
    pre = {"rct": 0, "apt": 0}
    stop = min(len(bits), onset + horizon)
    for i in range(stop):
        b = bits[i]
        for name, t in (("rct", rct), ("apt", apt)):
            if t.update(b):
                if i < onset:
                    pre[name] += 1
                elif first[name] is None:
                    first[name] = i - onset + 1
                t.reset()
    return {"rct": first["rct"], "apt": first["apt"], "pre_onset_trips": pre}


# --------------------------------------------------------------------------
# Replay helpers
# --------------------------------------------------------------------------

def longest_run(bits: list[int]) -> int:
    best = cur = 0
    prev = None
    for b in bits:
        cur = cur + 1 if b == prev else 1
        prev = b
        best = max(best, cur)
    return best


def max_apt_matches(bits: list[int], w: int = params.W_APT) -> int:
    """Largest per-window reference-value match count (APT's statistic)."""
    best = 0
    for s in range(0, len(bits) - w + 1, w):
        win = bits[s:s + w]
        best = max(best, win.count(win[0]))
    return best


def count_trips(bits: list[int], c_rct: int, c_apt: int,
                w: int = params.W_APT) -> tuple[int, int]:
    rct = RepetitionCountTest(c_rct)
    apt = AdaptiveProportionTest(w, c_apt)
    nr = na = 0
    for b in bits:
        if rct.update(b):
            nr += 1
            rct.reset()
        if apt.update(b):
            na += 1
            apt.reset()
    return nr, na


def monitor_replay(bits: list[int]) -> dict:
    mon = HealthMonitor()
    raised = 0
    for b in bits:
        if mon.update(b):
            raised += 1
    return {"raised": raised, "alarm_rct": mon.alarm_rct,
            "alarm_apt": mon.alarm_apt, "alarm_startup": mon.alarm_startup}


def log2_decimal(x: Decimal) -> float:
    return float(x.ln() / Decimal(2).ln()) if x > 0 else float("-inf")


def verdict(h: float) -> str:
    if h < params.H_DESIGN:
        return "VIOLATED (cutoffs under-alarm)"
    if h < params.H_DESIGN + H_TIGHT_BAND:
        return "tight"
    return "conservative"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def _load_battery_module():
    path = (REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis"
            / "raw-bit-battery.py")
    spec = importlib.util.spec_from_file_location("raw_bit_battery", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["raw_bit_battery"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_streams() -> list[dict]:
    """Ts = 20 us streams (hash-verified) joined to their min-H estimate."""
    battery = _load_battery_module()
    out = []
    for vol_rel, h_rel in SOURCES:
        hrec = json.loads((REPO_ROOT / h_rel).read_text())
        if hrec["source_json"] != vol_rel:
            raise SystemExit(f"{h_rel} was not derived from {vol_rel}")
        hmap = {(r["corner"], r["temp_c"], r["vdd_v"]): r
                for r in hrec["ts20us_min_entropy"]}
        fails = {}
        for r in hrec["analysis_payload"]["per_stream"]:
            if r["ts_name"] == TS_NAME:
                fails[(r["corner"], r["temp_c"], r["vdd_v"])] = [
                    k for k, v in r["single_sequence"]["tests"].items()
                    if v["status"] == "FAIL"]
        _, streams, _ = battery.load_volume_source(REPO_ROOT / vol_rel)
        for row, bits in streams:
            if row["ts_name"] != TS_NAME:
                continue
            key = (row["corner"], row["temp_c"], row["vdd_v"])
            est = hmap[key]
            out.append({"corner": key[0], "temp_c": key[1], "vdd_v": key[2],
                        "h": est["h_min_bits"],
                        "binding": est["binding_estimator"],
                        "battery_fails": fails[key],
                        "volume_record": hrec["source_record"],
                        "h_record": hrec["record_id"], "bits": bits})
    return out


def label(s: dict) -> str:
    return f"{s['corner']} {s['temp_c']:g} C {s['vdd_v']:g} V"


# --------------------------------------------------------------------------
# Injection scenarios
# --------------------------------------------------------------------------

def scenarios() -> list[dict]:
    sc = [
        {"name": "stuck-at-0", "kind": "stuck", "value": 0},
        {"name": "stuck-at-1", "kind": "stuck", "value": 1},
        {"name": "toggle 01 (period 2)", "kind": "toggle", "pattern": (0, 1)},
        {"name": "toggle 001 (period 3)", "kind": "toggle",
         "pattern": (0, 0, 1)},
        {"name": "toggle 0011 (period 4)", "kind": "toggle",
         "pattern": (0, 0, 1, 1)},
        {"name": "toggle 0001 (period 4)", "kind": "toggle",
         "pattern": (0, 0, 0, 1)},
    ]
    for p in (0.7, 0.8, 0.85, 0.9, 0.95):
        sc.append({"name": f"bias step to p={p}", "kind": "bias",
                   "p1": p, "ramp_len": 0})
    for p in (0.7, 0.9):
        sc.append({"name": f"bias ramp 0.5->{p} over 8192, then held",
                   "kind": "bias", "p0": 0.5, "p1": p, "ramp_len": 8192})
    return sc


def run_injections(streams: list[dict]) -> list[dict]:
    rows = []
    for sc in scenarios():
        kw = {k: v for k, v in sc.items() if k not in ("name", "kind")}
        lat = {"rct": [], "apt": []}
        pre = 0
        for s in streams:
            for onset in ONSETS:
                seed = _scenario_seed(sc["name"], label(s), onset)
                spliced, _ = inject(s["bits"], onset, sc["kind"], HORIZON,
                                    seed, **kw)
                d = detection_latency(spliced, onset, HORIZON)
                pre += sum(d["pre_onset_trips"].values())
                for t in ("rct", "apt"):
                    lat[t].append(d[t])
        row = {"name": sc["name"], "runs": len(lat["rct"]),
               "pre_onset_trips": pre}
        for t in ("rct", "apt"):
            hit = [x for x in lat[t] if x is not None]
            row[t] = {"detected": len(hit), "runs": len(lat[t]),
                      "min": min(hit) if hit else None,
                      "median": statistics.median(hit) if hit else None,
                      "max": max(hit) if hit else None}
        rows.append(row)
    return rows


def fmt_lat(d: dict) -> str:
    if d["detected"] == 0:
        return f"not detected within {HORIZON} samples (0/{d['runs']})"
    def one(x):
        return f"{x:g} ({x / RAW_RATE_BPS * 1e3:.2f} ms)"
    s = f"min {one(d['min'])} / median {one(d['median'])} / max {one(d['max'])}"
    if d["detected"] < d["runs"]:
        s += f"; detected {d['detected']}/{d['runs']}, rest not within {HORIZON}"
    return s


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def build_report() -> tuple[str, dict]:
    streams = load_streams()
    w = params.W_APT
    alpha_log2 = params.ALPHA_LOG2
    lines: list[str] = []
    a = lines.append

    a("## Scope and inputs")
    a("")
    a("Streams: the Ts = 20 us (design point) behavioural streams of the")
    a("volume campaign, 131072 samples each, hash-verified by the loader.")
    a("Ts = 100 ns streams are **not** the design point and are excluded.")
    a("`H` is `h_min_bits`, the minimum over the SP 800-90B non-IID")
    a("estimators implemented in `raw-bit-battery.py`, taken from the cited")
    a("min-entropy records.")
    a("")
    srcs = sorted({(s["volume_record"], s["h_record"]) for s in streams})
    for v, h in srcs:
        a(f"- volume campaign `{v}` -> min-entropy `{h}`")
    a("")
    a("**Caveats that bound every conclusion below.** The streams come from")
    a("a behavioural model with independent noise increments, not from")
    a("silicon; estimated `H` is a model number and is **provisional until")
    a("measured on silicon**. A replay with zero alarms on such data is weak")
    a("evidence for the real device, and `H` = 0.5 versus 0.65 on the model")
    a("does not exercise real-world bias, correlation or supply coupling.")
    a("The cited battery record reports single-sequence FAILs on most of")
    a("these streams (listed in section 2) -- the estimated `H` and the")
    a("replay must be read alongside them, not instead of them.")
    a("")

    # ---- 1. re-derive
    a("## 1. Cutoffs re-derived at the estimated H")
    a("")
    a(f"`C_RCT` = {params.C_RCT} and `C_APT` = {params.C_APT} are the ratified")
    a(f"values at `H` = {params.H_DESIGN}. Verdict rule: **violated** if")
    a(f"`H_est` < {params.H_DESIGN} (the cutoffs would under-alarm), **tight** if")
    a(f"{params.H_DESIGN} <= `H_est` < {params.H_DESIGN + H_TIGHT_BAND}, otherwise")
    a("**conservative** (false alarms rarer than designed). Lookups are")
    a("`params.c_rct(H)` / `params.c_apt(H)`, not retyped.")
    a("")
    a("`log2 FA` columns: the false-alarm probability of the *ratified*")
    a("cutoff if the source really had `H_est` and were i.i.d. at")
    a("`p = 2^-H` (design: `-40`). RCT is per sample, APT per window.")
    a("The sensitivity paragraph below uses `-log2(C_APT / W)`, the")
    a("min-entropy of an i.i.d. biased source whose *typical* window just")
    a("reaches the cutoff.")
    a("")
    a("| stream | `H_est` | binding | `c_rct(H)` | d vs 81 | `c_apt(H)` | d vs 824 | log2 FA RCT | log2 FA APT | verdict |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    derive = []
    for s in sorted(streams, key=lambda x: x["h"]):
        h = s["h"]
        cr, ca = params.c_rct(h), params.c_apt(h)
        fa_rct = -h * (params.C_RCT - 1)
        p = Decimal(2) ** Decimal(str(-h))
        fa_apt = log2_decimal(params.binomial_upper_tail(w, p, params.C_APT))
        v = verdict(h)
        derive.append({"stream": label(s), "h": h, "c_rct": cr, "c_apt": ca,
                       "d_rct": cr - params.C_RCT, "d_apt": ca - params.C_APT,
                       "log2_fa_rct": fa_rct, "log2_fa_apt": fa_apt,
                       "verdict": v})
        a(f"| {label(s)} | {h:.4f} | {s['binding']} | {cr} | {cr - params.C_RCT:+d} | "
          f"{ca} | {ca - params.C_APT:+d} | {fa_rct:.1f} | {fa_apt:.1f} | {v} |")
    worst = min(streams, key=lambda x: x["h"])
    best = max(streams, key=lambda x: x["h"])
    a("")
    a(f"**Worst case (minimum H)**: {label(worst)}, `H_est` = {worst['h']:.4f}"
      f" ({worst['binding']}): `c_rct` = {params.c_rct(worst['h'])},"
      f" `c_apt` = {params.c_apt(worst['h'])}.")
    a(f"**Best case**: {label(best)}, `H_est` = {best['h']:.4f}.")
    a("")
    h_det_ratified = -math.log2(params.C_APT / w)
    h_det_worst = -math.log2(params.c_apt(worst["h"]) / w)
    a(f"Sensitivity implication: the ratified APT cutoff {params.C_APT}/{w}"
      f" only fires on a typical window when the source's min-entropy is"
      f" about {h_det_ratified:.3f} bit/sample or lower, whereas a cutoff"
      f" evaluated at the worst-case estimate would fire near"
      f" {h_det_worst:.3f}. Likewise the RCT trips after"
      f" {params.C_RCT} identical samples ({params.C_RCT / RAW_RATE_BPS * 1e3:.2f} ms)"
      f" versus {params.c_rct(worst['h'])} at the worst-case estimate"
      f" ({params.c_rct(worst['h']) / RAW_RATE_BPS * 1e3:.2f} ms).")
    a("")
    all_ok = all(s["h"] >= params.H_DESIGN for s in streams)
    n_cons = sum(1 for d in derive if d["verdict"] == "conservative")
    a(f"**Conclusion.** {n_cons}/{len(streams)} streams are *conservative*,"
      f" {sum(1 for d in derive if d['verdict'] == 'tight')} tight,"
      f" {sum(1 for d in derive if d['verdict'].startswith('VIOLATED'))} violated."
      + (" The ratified H = 0.5 cutoffs therefore do **not** under-alarm at"
         " the estimated H: they are conservative against false alarms and"
         " correspondingly less sensitive than cutoffs at the measured H"
         " would be. This is a statement about a provisional, behavioural-"
         "model H; it is not a reason to change the ratified values, and no"
         " change is made or proposed here." if all_ok else
         " At least one stream is below the design target: the ratified"
         " cutoffs under-alarm there, and a decision-record issue is"
         " warranted."))
    a("")

    # ---- 2. replay
    a("## 2. Replay of the streams through the health tests")
    a("")
    a("Counting convention: individual tests are `reset()` after every trip")
    a("and keep counting. `HealthMonitor` applies its own policy (a mid-run")
    a("trip re-arms start-up and resets RCT/APT), and the number of")
    a("`update()` calls that returned True is reported, plus its sticky alarm")
    a("bits at end of stream. Each stream is also run through the individual")
    a("tests at the cutoffs evaluated at that stream's own `H_est`, to show")
    a("the margin the ratified cutoffs leave. 'Longest run' and 'max APT")
    a("matches' are the raw statistics the cutoffs are compared against.")
    a("")
    a("| stream | n | longest run (RCT < 81) | max APT matches (< 824) | RCT trips @81 | APT trips @824 | Monitor raised | alarm RCT/APT/start-up | trips @ own-H cutoffs (RCT/APT) | battery FAILs (single-seq, cited) |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    replay = []
    total_alarms = 0
    for s in sorted(streams, key=lambda x: x["h"]):
        bits = s["bits"]
        lr = longest_run(bits)
        ma = max_apt_matches(bits)
        nr, na = count_trips(bits, params.C_RCT, params.C_APT)
        mon = monitor_replay(bits)
        nr_h, na_h = count_trips(bits, params.c_rct(s["h"]),
                                 params.c_apt(s["h"]))
        total_alarms += nr + na + mon["raised"]
        fl = ", ".join(s["battery_fails"]) or "-"
        replay.append({"stream": label(s), "n": len(bits), "longest_run": lr,
                       "max_apt_matches": ma, "rct_trips": nr,
                       "apt_trips": na, "monitor": mon,
                       "rct_trips_own_h": nr_h, "apt_trips_own_h": na_h,
                       "battery_fails": s["battery_fails"]})
        a(f"| {label(s)} | {len(bits)} | {lr} | {ma} | {nr} | {na} | "
          f"{mon['raised']} | {int(mon['alarm_rct'])}/{int(mon['alarm_apt'])}/"
          f"{int(mon['alarm_startup'])} | {nr_h}/{na_h} | {fl} |")
    a("")
    a(f"**Total alarms across {len(streams)} streams at the ratified cutoffs:"
      f" {total_alarms}** (expected 0 at alpha = 2^-{alpha_log2}"
      + ("; none observed" if total_alarms == 0 else
         "; **every alarm is a finding**") + ").")
    a("")

    # ---- 3. injection
    a("## 3. Failure injection and detection latency")
    a("")
    a(f"Healthy base: each of the {len(streams)} streams above. A failure of")
    a(f"{HORIZON} samples is spliced in at onsets {list(ONSETS)} (none a")
    a(f"multiple of {w}); the injector replaces the healthy samples, same")
    a(f"stream length, deterministic via per-scenario CRC32 seeds. Each of the")
    a(f"{len(streams) * len(ONSETS)} runs per scenario feeds RCT and APT")
    a("(ratified cutoffs, individual tests, restart after a trip) from sample")
    a("0 and records the first trip at or after onset (a stuck run can trip")
    a("RCT a few samples early when the preceding healthy sample already")
    a("equals the stuck value). Latency = injected")
    a("samples consumed up to and including the failing one; seconds at")
    a(f"{RAW_RATE_BPS:,.0f} bps (20 us/sample). APT latency is quantised to")
    a(f"{w}-sample window ends measured from stream start, so it depends on")
    a("onset alignment. 'Not detected' is a result, not an omission.")
    a("")
    a("| scenario | RCT latency, samples (time) | APT latency, samples (time) |")
    a("|---|---|---|")
    inj = run_injections(streams)
    pre_total = 0
    for r in inj:
        pre_total += r["pre_onset_trips"]
        a(f"| {r['name']} | {fmt_lat(r['rct'])} | {fmt_lat(r['apt'])} |")
    a("")
    a(f"Pre-onset (healthy-prefix) trips across all injection runs:"
      f" {pre_total} (expected 0).")
    a("")
    a("Reading the table: RCT is the only test that catches a stuck source")
    a(f"quickly ({params.C_RCT} samples = {params.C_RCT / RAW_RATE_BPS * 1e3:.2f} ms) and cannot see any")
    a("toggling or bias that keeps runs short. APT needs a window whose")
    a(f"reference value fills >= {params.C_APT}/{w} = {params.C_APT / w:.3f} of the window, so a")
    a("fixed bias below roughly p = 0.8 -- including p = 0.7, the 'plausible")
    a("drift' value, which still carries "
      f"{-math.log2(0.7):.3f} bit/sample -- is **not** flagged at the ratified")
    a("cutoff, and a period-3 or period-4 pattern with <= 75% of one symbol is")
    a("invisible to both tests. Those are properties of the SP 800-90B")
    a("continuous tests at this alpha, not defects of the model; the")
    a("statistical battery and the estimators, not RCT/APT, are what cover")
    a("them.")

    summary = {
        "ts_name": TS_NAME,
        "raw_rate_bps": RAW_RATE_BPS,
        "c_rct_ratified": params.C_RCT,
        "c_apt_ratified": params.C_APT,
        "h_design": params.H_DESIGN,
        "sources": [{"volume_record": v, "min_entropy_record": h}
                    for v, h in srcs],
        "worst_case": {"stream": label(worst), "h": worst["h"],
                       "c_rct": params.c_rct(worst["h"]),
                       "c_apt": params.c_apt(worst["h"])},
        "rederive": derive,
        "replay": replay,
        "replay_total_alarms": total_alarms,
        "injection": {"onsets": list(ONSETS), "horizon": HORIZON,
                      "runs_per_scenario": len(streams) * len(ONSETS),
                      "pre_onset_trips": pre_total, "scenarios": inj},
        "caveat": "simulation-derived H, behavioural model; provisional "
                  "until measured on silicon",
    }
    return "\n".join(lines), summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true",
                    help="mint an append-only record under "
                         "sim/digital-health-test-parameters/records/")
    args = ap.parse_args(argv)

    body, summary = build_report()
    print(body)

    if args.emit_record:
        mint_behavioral_record(
            repo_root=REPO_ROOT,
            slug="digital-health-test-parameters",
            claim=("the ratified RCT/APT cutoffs (81/824, H = 0.5) re-derived "
                   "at the estimated Ts = 20 us min-entropy, replayed over "
                   "the volume streams, and checked by deterministic failure "
                   "injection (detection latency per test); simulation-"
                   "derived H, provisional until silicon"),
            body_md=body,
            summary=summary,
            level="behavioral (derived -- no simulator)",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
