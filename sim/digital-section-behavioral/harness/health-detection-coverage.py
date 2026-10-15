#!/usr/bin/env python3
"""Experiment I: health-test detection coverage on correlated raw streams.

Sibling of ``digital-section-campaign.py`` (experiments A-H, i.i.d. stimuli
only). This harness drives ``digital/model/health.py`` (RCT + APT at the
DR-0004 cutoffs, nothing re-derived or relaxed) with serially-correlated and
quasi-periodic streams whose per-bit min-entropy is known *analytically*, and
records for each stream: the analytic min-entropy, whether the online tests
alarm, the detection latency, and what the non-MCV SP 800-90B estimators of
``sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`` (issue #189) say.

Families (all seeded, all explicitly synthetic):

``markov``    two-state chain, P(1|1) = a, P(0|0) = b. Analytic min-entropy
              rate is -log2 of the maximum cycle geometric mean,
              max(a, b, sqrt((1-a)(1-b))).
``periodic``  a seeded balanced length-k pattern repeated, each bit flipped
              independently with probability eps. The pattern is treated as
              KNOWN to the adversary (a locked oscillator is repeatable), so
              the per-bit min-entropy is -log2(1 - eps).
``lock-mix``  alternating segments of length L: a locked segment (period-2
              pattern, flip noise eps_lock) for a fraction f of each L-bit
              period and a free-running fair-coin segment for the rest.
              Schedule treated as known: H = (1-f)*1 + f*(-log2(1-eps_lock)).

These are SYNTHETIC LOGIC STIMULI. No claim is made about sky130 silicon or
about the real source's entropy. "Caught by an estimator" means its point
estimate is below the design target H_DESIGN; the estimators are the repo's
labelled approximations, not a validated 90B implementation.

Experiment J (``--lagcount``, issue #301, DR-0015) re-runs the same stream
families through a *study* lag-k match-count monitor
(``digital/model/lagcount.py``, additive, not adopted, not wired into the
health monitor) next to the unchanged RCT/APT, over a grid of lag counts ``L``
and windows ``W_L``, and checks the monitor's false-alarm limit on seeded
i.i.d. streams. RCT/APT cutoffs are not touched by either experiment.

Usage::

    python3 sim/digital-section-behavioral/harness/health-detection-coverage.py
    python3 sim/digital-section-behavioral/harness/health-detection-coverage.py --emit-record
    python3 sim/digital-section-behavioral/harness/health-detection-coverage.py --lagcount
    python3 sim/digital-section-behavioral/harness/health-detection-coverage.py --lagcount --emit-record
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import random
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402
from model import lagcount  # noqa: E402
from model.health import HealthMonitor  # noqa: E402
from model.params import C_APT, C_RCT, H_DESIGN, STARTUP_SAMPLES, W_APT  # noqa: E402

_BATTERY = REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis" / "raw-bit-battery.py"
sys.path.insert(0, str(_BATTERY.parent))
_spec = importlib.util.spec_from_file_location("raw_bit_battery", _BATTERY)
battery = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(battery)

DEFAULT_SEED = 20261011
DEFAULT_N = 65536
RAW_RATE_BPS = 50_000.0
NON_MCV = ("collision", "markov", "compression", "t_tuple", "lrs")
SLUG = "digital-section-behavioral"


# ------------------------------------------------------------- generators

def gen_markov(rng, n, a, b):
    """P(1|1)=a, P(0|0)=b, started from the stationary distribution."""
    p1 = (1 - b) / ((1 - a) + (1 - b))
    x = 1 if rng.random() < p1 else 0
    out = [x]
    for _ in range(n - 1):
        stay = a if x else b
        if rng.random() >= stay:
            x ^= 1
        out.append(x)
    return out


def h_markov(a, b):
    return -math.log2(max(a, b, math.sqrt((1 - a) * (1 - b))))


def balanced_pattern(rng, k):
    pat = [1] * (k // 2) + [0] * (k - k // 2)
    rng.shuffle(pat)
    return pat


def gen_periodic(rng, n, k, eps, pattern=None):
    pat = pattern or balanced_pattern(rng, k)
    return [pat[i % k] ^ (1 if rng.random() < eps else 0) for i in range(n)]


def h_periodic(eps):
    return -math.log2(1 - eps) + 0.0


def gen_lockmix(rng, n, seg, frac, eps):
    locked_len = int(round(frac * seg))
    out = []
    while len(out) < n:
        out += [(i & 1) ^ (1 if rng.random() < eps else 0) for i in range(locked_len)]
        out += [rng.getrandbits(1) for _ in range(seg - locked_len)]
    return out[:n]


def h_lockmix(frac, eps):
    return (1 - frac) + frac * h_periodic(eps)


# ------------------------------------------------------------- measurement

def run_health(bits):
    hm = HealthMonitor()
    first = None
    kinds = 0
    n_alarm = 0
    for i, b in enumerate(bits):
        if hm.update(b):
            n_alarm += 1
            if first is None:
                first = i + 1
                kinds = (1 if hm.alarm_rct else 0) | (2 if hm.alarm_apt else 0)
    which = {0: "-", 1: "RCT", 2: "APT", 3: "RCT+APT"}[kinds]
    return first, which, n_alarm


def measure(label, family, params, h_true, bits):
    first, which, n_alarm = run_health(bits)
    est = battery.entropy_estimates(bits)
    ests = {k: v["h_bits"] for k, v in est["estimators"].items() if v["status"] == "OK"}
    nonmcv = {k: ests[k] for k in NON_MCV if k in ests}
    bind = min(nonmcv, key=nonmcv.get)
    catchers = sorted((k for k, v in nonmcv.items() if v < H_DESIGN), key=nonmcv.get)
    return {
        "label": label, "family": family, "params": params,
        "n": len(bits), "h_true": h_true,
        "mean_bit": sum(bits) / len(bits),
        "alarm": first is not None, "first_alarm_at": first,
        "latency_ms": None if first is None else first / RAW_RATE_BPS * 1e3,
        "alarm_kind": which, "alarm_events": n_alarm,
        "estimates": ests, "nonmcv_min": nonmcv[bind], "nonmcv_binding": bind,
        "estimator_catchers": catchers,
        "below_target": h_true < H_DESIGN,
    }


def streams(seed, n):
    """Yield ``(label, family, params, h_true, bits)`` for every experiment-I stream.

    One shared seeded ``random.Random`` drawn in a fixed order, so the same
    ``(seed, n)`` reproduces the same streams for experiments I and J.
    """
    rng = random.Random(seed)

    # control: fair coin
    yield ("control fair", "control", {}, 1.0, [rng.getrandbits(1) for _ in range(n)])

    # Markov: symmetric stay sweep, plus biased/asymmetric chains
    for s in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99):
        yield (f"markov sym stay={s}", "markov", {"a": s, "b": s}, h_markov(s, s),
               gen_markov(rng, n, s, s))
    for a, b in ((0.7, 0.5), (0.8, 0.5), (0.9, 0.6), (0.9, 0.3), (0.95, 0.5), (0.98, 0.6)):
        yield (f"markov asym a={a} b={b}", "markov", {"a": a, "b": b}, h_markov(a, b),
               gen_markov(rng, n, a, b))

    # period-k with flip noise
    for k in (2, 4, 8, 16, 64, 256):
        for eps in (0.0, 0.01, 0.05, 0.1, 0.2, 0.3):
            pat = balanced_pattern(rng, k)
            yield (f"periodic k={k} eps={eps}", "periodic", {"k": k, "eps": eps},
                   h_periodic(eps), gen_periodic(rng, n, k, 0.0 + eps, pat))

    # lock-fraction mixture
    for seg in (256, 4096):
        for eps in (0.0, 0.05):
            for f in (0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
                yield (f"lockmix L={seg} f={f} eps={eps}", "lock-mix",
                       {"segment": seg, "frac": f, "eps_lock": eps}, h_lockmix(f, eps),
                       gen_lockmix(rng, n, seg, f, eps))


def sweep(seed, n):
    return [measure(label, fam, params, h, bits)
            for label, fam, params, h, bits in streams(seed, n)]


# ------------------------------------------------------------- reporting

def fmt_h(x):
    return f"{x:.3f}"


def build_report(rows, seed, n):
    L = []
    a = L.append
    missed = [r for r in rows if r["below_target"] and not r["alarm"]]
    missed_caught = [r for r in missed if r["estimator_catchers"]]
    missed_uncaught = [r for r in missed if not r["estimator_catchers"]]
    low = [r for r in rows if r["below_target"]]
    a("## Configuration")
    a("")
    a(f"- DUT: `digital/model/health.py` `HealthMonitor` at `C_RCT` = {C_RCT}, `C_APT` = {C_APT}, "
      f"`W` = {W_APT}, start-up = {STARTUP_SAMPLES} (DR-0004; **not modified**)")
    a(f"- stimulus: **declared synthetic logic stimuli** -- seeded generators, `random.Random({seed})`, "
      f"{n:,} samples per stream. PVT-independent (no SPICE, no PDK). **No entropy claim on silicon.**")
    a(f"- `h_true` is the analytic per-bit min-entropy of the generator (adversary knows the pattern/schedule); "
      f"'below target' means `h_true` < `H_DESIGN` = {H_DESIGN}")
    a("- estimators: non-MCV SP 800-90B estimators from `raw-bit-battery.py` (#189): collision, Markov, "
      "compression, t-tuple, LRS; 'catches' = point estimate < `H_DESIGN`. Repo approximations, not validated 90B")
    a(f"- latency: samples to first alarm, ms at {RAW_RATE_BPS:,.0f} Hz")
    a("")
    a("## Summary")
    a("")
    a(f"- streams: {len(rows)}; below `H_DESIGN`: {len(low)}; alarmed by RCT/APT: "
      f"{sum(1 for r in low if r['alarm'])}")
    a(f"- **missed by online tests but below target: {len(missed)}**; of those, caught by at least one "
      f"non-MCV estimator: {len(missed_caught)}; caught by none: {len(missed_uncaught)}")
    fp = [r for r in rows if not r["below_target"] and r["alarm"]]
    a(f"- alarms on streams at/above target (informational): {len(fp)}")
    ff = [r for r in rows if not r["below_target"] and r["estimator_catchers"]]
    a(f"- streams at/above target that a non-MCV estimator nonetheless flags (conservative-estimator "
      f"false flags under this `h_true` definition): {len(ff)}"
      + (" -- " + ", ".join(f"`{r['label']}`" for r in ff) if ff else ""))
    a("")
    a("## All streams")
    a("")
    a("| stream | h_true | mean | alarm | first alarm @ | by | non-MCV min (binding) | estimator catchers |")
    a("|---|---|---|---|---|---|---|---|")
    for r in rows:
        a(f"| {r['label']} | {fmt_h(r['h_true'])} | {r['mean_bit']:.3f} | "
          f"{'YES' if r['alarm'] else 'no'} | {r['first_alarm_at'] if r['alarm'] else '-'} | "
          f"{r['alarm_kind']} | {fmt_h(r['nonmcv_min'])} ({r['nonmcv_binding']}) | "
          f"{', '.join(r['estimator_catchers']) or '-'} |")
    a("")
    a("## Missed-but-low-entropy cases (no RCT/APT alarm, `h_true` < `H_DESIGN`)")
    a("")
    if not missed:
        a("None.")
    else:
        a("| stream | h_true | non-MCV min (binding) | catching estimator(s), lowest first |")
        a("|---|---|---|---|")
        for r in missed:
            a(f"| {r['label']} | {fmt_h(r['h_true'])} | {fmt_h(r['nonmcv_min'])} ({r['nonmcv_binding']}) | "
              f"{', '.join(r['estimator_catchers']) or '**none**'} |")
    a("")
    if missed_uncaught:
        a("Missed by the online tests AND by every non-MCV estimator: "
          + ", ".join(f"`{r['label']}`" for r in missed_uncaught) + ".")
    else:
        a("Every missed-but-low-entropy stream is caught by at least one non-MCV estimator.")
    a("")
    a("## Notes")
    a("")
    a("- RCT/APT are *bias and run-length* detectors. A balanced period-k pattern has marginal bias 0.5 and run")
    a("  lengths bounded by k, so it is invisible to both regardless of how little entropy it carries; this is the")
    a("  expected, documented limit of SP 800-90B §4.4, quantified here, not a defect in the model.")
    a("- The estimators are offline (N >= 1000-12000 samples, run over a whole stream); they are not an online")
    a("  mitigation. Where they catch a case the online tests miss, the gap is in *what runs on-chip*.")
    a("- Estimator point estimates can over- or under-state `h_true`; 'catches' uses the design target as the")
    a("  threshold and is a detection statement, not an accuracy claim.")
    a("- Lock-mix streams are non-stationary, which the 90B estimators assume away: their flags on")
    a("  streams whose analytic `h_true` is at/above target reflect the repeated locked segments (a")
    a("  conservative reading), not an error in the analytic figure under the stated known-schedule model.")
    a("- Ratified cutoffs and spec text are unchanged. Any coverage hole is routed to a decision-record request.")
    return "\n".join(L)


# ------------------------------------------------------- experiment J (#301)

LAG_GRID_L = (8, 16, 32, 64, 128, 256)
LAG_GRID_W = (1024, 2048, 4096)
#: configurations whose full per-stream table is reported
LAG_REPORT = ((32, 4096), (256, 4096))
_REPLAY = REPO_ROOT / "sim" / "digital-health-test-parameters" / "analysis" / "health-test-replay.py"
#: configurations replayed over the sky130 behavioural corner streams
REPLAY_CONFIGS = ((16, 2048), (32, 4096), (256, 4096))
FA_SAMPLES = 1_000_000
FA_SEED_OFFSET = 1
#: loosened per-window alpha used only to calibrate the tail derivation empirically
CAL_ALPHA_LOG2 = 4


def run_lag(v, n, lags, window):
    first, mask = lagcount.first_alarm_packed(v, n, lags, window)
    return first, mask


def lag_sweep(seed, n):
    """Per stream: RCT/APT outcome plus the lag monitor over the (L, W_L) grid."""
    rows = []
    for label, fam, params, h, bits in streams(seed, n):
        first, which, _ = run_health(bits)
        v = lagcount.pack(bits)
        lag = {}
        for w in LAG_GRID_W:
            for lags in LAG_GRID_L:
                f, mask = run_lag(v, len(bits), lags, w)
                lag[(lags, w)] = {"alarm": f is not None, "first": f, "lag_mask": mask}
        rows.append({"label": label, "family": fam, "params": params, "h_true": h,
                     "below_target": h < H_DESIGN, "rct_apt_alarm": first is not None,
                     "rct_apt_first": first, "rct_apt_kind": which, "lag": lag})
    return rows


def coverage_by_config(rows):
    out = {}
    low = [r for r in rows if r["below_target"]]
    hi = [r for r in rows if not r["below_target"]]
    for w in LAG_GRID_W:
        for lags in LAG_GRID_L:
            key = (lags, w)
            caught = [r for r in low if r["lag"][key]["alarm"] or r["rct_apt_alarm"]]
            newly = [r for r in low if r["lag"][key]["alarm"] and not r["rct_apt_alarm"]]
            missed = [r for r in low if not (r["lag"][key]["alarm"] or r["rct_apt_alarm"])]
            fa = [r for r in hi if r["lag"][key]["alarm"]]
            out[key] = {"c_l": lagcount.c_lag(lags, w), "caught": len(caught),
                        "newly": len(newly), "missed": missed, "false_alarms": fa,
                        "n_low": len(low)}
    return out


def detect_power_table(lags, window):
    """Analytic per-window detection of a period-k stream with flip noise, at its own lag k."""
    c = lagcount.c_lag(lags, window)
    rows = []
    for eps in (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.28, 0.2929):
        rate = (1 - eps) ** 2 + eps ** 2
        rows.append({"eps": eps, "h": h_periodic(eps), "rate": rate,
                     "p_window": lagcount.tail_probability(window, rate, c)})
    return c, rows


def covered_h(lags, window, target):
    """Largest min-entropy h of a period-k + flip-noise stream (k <= L) alarmed with probability >= ``target`` per window.

    Binomial approximation of the alarm probability at the stream's own lag k (match rate
    (1-eps)^2 + eps^2), bisected over eps; the simulated grid above is the cross-check.
    """
    c = lagcount.c_lag(lags, window)
    lo, hi = 0.0, 1 - 2.0 ** -H_DESIGN
    for _ in range(50):
        mid = (lo + hi) / 2
        rate = (1 - mid) ** 2 + mid ** 2
        if lagcount.tail_probability(window, rate, c) >= target:
            lo = mid
        else:
            hi = mid
    return lo, h_periodic(lo)


def false_alarm_run(seed, lags, window, c_override=None, bias_p1=None, n=FA_SAMPLES):
    """Seeded i.i.d. stream (fair, or P(1)=bias_p1): failing windows + worst lag count seen."""
    rng = random.Random(seed)
    if bias_p1 is None:
        bits = [rng.getrandbits(1) for _ in range(n)]
    else:
        bits = [1 if rng.random() < bias_p1 else 0 for _ in range(n)]
    v = lagcount.pack(bits)
    c = lagcount.c_lag(lags, window) if c_override is None else c_override
    hits = lagcount.scan_packed(v, n, lags, window, c)
    maxes = lagcount.window_max_counts(v, n, lags, window)
    return {"lags": lags, "window": window, "cutoff": c, "n": n, "windows": len(maxes),
            "failing_windows": len(hits), "worst_count": max(maxes),
            "mean_of_window_max": sum(maxes) / len(maxes),
            "bias_p1": bias_p1}


def corner_replay():
    """Lag monitor over the 18 Ts = 20 us sky130 behavioural corner streams (hash-verified loader of the replay analysis)."""
    spec = importlib.util.spec_from_file_location("health_test_replay", _REPLAY)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(_REPLAY.parent))
    spec.loader.exec_module(mod)
    out = []
    for st in mod.load_streams():
        bits = st["bits"]
        v = lagcount.pack(bits)
        row = {"label": mod.label(st), "h_est": st["h"], "n": len(bits), "cfg": {}}
        for lags, w in REPLAY_CONFIGS:
            hits = lagcount.scan_packed(v, len(bits), lags, w)
            mx = max(lagcount.window_max_counts(v, len(bits), lags, w))
            row["cfg"][(lags, w)] = {"alarms": len(hits), "worst": mx,
                                     "cutoff": lagcount.c_lag(lags, w)}
        out.append(row)
    return out


def build_report_j(rows, seed, n, fa, cal, replay):
    L = []
    a = L.append
    low = [r for r in rows if r["below_target"]]
    cov = coverage_by_config(rows)
    a("## Configuration")
    a("")
    a(f"- DUT: `digital/model/lagcount.py` study monitor **next to** the unchanged RCT/APT "
      f"(`C_RCT` = {C_RCT}, `C_APT` = {C_APT}, `W` = {W_APT}; DR-0004 not modified). The lag monitor is "
      f"**not adopted** and not wired into `HealthMonitor`.")
    a(f"- stimulus: the experiment-I streams, **declared synthetic logic stimuli**, "
      f"`random.Random({seed})`, {n:,} samples each; identical to record `20261011-143828-a7af876`. "
      f"PVT-independent (no SPICE, no PDK). **No entropy claim on silicon; provisional until measured.**")
    a(f"- cutoff `C_L`: smallest `C` with *exact* `Pr(M_lag1 >= C) <= 2^-40 / L` for an i.i.d. source with "
      f"`P(1) = 2^-H_DESIGN` (lag-match rate {float(lagcount.match_probability(H_DESIGN)):.6f}), where the lag-1 "
      f"match count is computed by an exact Markov-chain DP (no independence assumption); Bonferroni over `L` "
      f"lags makes the per-window false-alarm bound `2^-40` for any **i.i.d.** source at or above `H_DESIGN`")
    a("- the DR-0004 §2 binomial `Bin(W_L, p^2+q^2)` treats the match indicators as independent; they are "
      "1-dependent for a biased source, so that cutoff under-covers (table below). It is reported, not used")
    a(f"- streams below `H_DESIGN`: {len(low)} of {len(rows)}")
    a("")
    a("## Coverage grid (streams below `H_DESIGN` caught by RCT/APT or the lag monitor)")
    a("")
    a("| L | W_L | C_L (exact) | C_L (binomial, not used) | caught | of which only the lag monitor | still missed | alarms on at/above-target streams |")
    a("|---|---|---|---|---|---|---|---|")
    for w in LAG_GRID_W:
        for lags in LAG_GRID_L:
            c = cov[(lags, w)]
            a(f"| {lags} | {w} | {c['c_l']} | {lagcount.c_lag_binomial(lags, w)} | {c['caught']}/{c['n_low']} | {c['newly']} | "
              f"{len(c['missed'])} | {len(c['false_alarms'])} |")
    a("")
    for lags, w in LAG_REPORT:
        c = cov[(lags, w)]
        a(f"## Per-stream table, L = {lags}, W_L = {w} (C_L = {c['c_l']})")
        a("")
        a("| stream | h_true | RCT/APT | lag monitor | lag first alarm @ | latency ms | lags failed (lowest) |")
        a("|---|---|---|---|---|---|---|")
        for r in rows:
            e = r["lag"][(lags, w)]
            first = r["rct_apt_first"]
            lowest = "-"
            if e["lag_mask"]:
                lowest = str((e["lag_mask"] & -e["lag_mask"]).bit_length())
            a(f"| {r['label']} | {fmt_h(r['h_true'])} | "
              f"{('YES @ ' + str(first)) if r['rct_apt_alarm'] else 'no'} | "
              f"{'YES' if e['alarm'] else 'no'} | {e['first'] if e['alarm'] else '-'} | "
              f"{('%.0f' % (e['first'] / RAW_RATE_BPS * 1e3)) if e['alarm'] else '-'} | {lowest} |")
        a("")
        a(f"Still missed at this configuration ({len(c['missed'])}): "
          + (", ".join(f"`{r['label']}` (h={fmt_h(r['h_true'])})" for r in c["missed"]) or "none") + ".")
        a("")
        fa_rows = c["false_alarms"]
        a("Alarms on streams at/above `H_DESIGN`: "
          + (", ".join(f"`{r['label']}` (h={fmt_h(r['h_true'])})" for r in fa_rows) or "none") + ".")
        a("")
    a("## Analytic per-window detection, period-k stream with flip noise at its own lag k")
    a("")
    for lags, w in LAG_REPORT:
        c, tab = detect_power_table(lags, w)
        a(f"L = {lags}, W_L = {w}, C_L = {c} (match rate must reach {c / w:.4f}):")
        a("")
        a("| eps | h = -log2(1-eps) | lag-k match rate | Pr(window alarms) |")
        a("|---|---|---|---|")
        for t in tab:
            a(f"| {t['eps']} | {fmt_h(t['h'])} | {t['rate']:.4f} | {t['p_window']:.3g} |")
        a("")
    a("Largest flip noise `eps` (and its `h`) a period-k stream can carry and still be alarmed with the "
      "stated probability in one window (binomial approximation; first-verdict latency = L + W_L samples):")
    a("")
    a("| L | W_L | C_L | per-window P >= 0.5: eps / h | per-window P >= 0.99: eps / h | first-verdict latency ms |")
    a("|---|---|---|---|---|---|")
    for lags, w in ((8, 1024), (16, 1024), (16, 2048), (32, 1024), (32, 4096), (256, 4096)):
        e5, h5 = covered_h(lags, w, 0.5)
        e99, h99 = covered_h(lags, w, 0.99)
        a(f"| {lags} | {w} | {lagcount.c_lag(lags, w)} | {e5:.3f} / {h5:.3f} | {e99:.3f} / {h99:.3f} | "
          f"{(lags + w) / RAW_RATE_BPS * 1e3:.1f} |")
    a("")
    a("## False-alarm check on seeded i.i.d. streams")
    a("")
    a(f"Analytic limit: per lag `2^-40 / L`, per window `<= 2^-40` for any i.i.d. source with min-entropy "
      f">= `H_DESIGN` (union bound; the lag counts are positively correlated, so this is conservative). "
      f"At 50 kHz and W_L = 4096 a stream makes ~12 windows/s, so the expected time to one false "
      f"window is ~2^40 / 12 s (~2.9e3 years); 2^-40 cannot be reached by simulation, so the sample "
      f"check below shows no failing window and the margin to `C_L`, and a loosened-alpha run "
      f"validates the tail derivation itself.")
    a("")
    a("| source | L | W_L | C_L | samples | windows | failing windows | worst lag count | mean window max |")
    a("|---|---|---|---|---|---|---|---|---|")
    for f in fa:
        src = "fair" if f["bias_p1"] is None else f"i.i.d. P(1) = {f['bias_p1']:.4f} (H = {H_DESIGN})"
        a(f"| {src} | {f['lags']} | {f['window']} | {f['cutoff']} | {f['n']:,} | {f['windows']} | "
          f"{f['failing_windows']} | {f['worst_count']} | {f['mean_of_window_max']:.1f} |")
    a("")
    a(f"Tail calibration at a loosened per-window alpha = 2^-{CAL_ALPHA_LOG2} (same code paths, `H_DESIGN` "
      f"i.i.d. source, so the expected failing-window fraction is <= 2^-{CAL_ALPHA_LOG2}). The binomial "
      f"cutoff is run alongside to show the under-coverage:")
    a("")
    a("| cutoff derivation | L | W_L | C_L (alpha 2^-%d) | windows | failing windows | observed fraction | bound | exact true tail at this C_L, per lag (target %.3g) |" % (CAL_ALPHA_LOG2, 2.0 ** -CAL_ALPHA_LOG2 / 16))
    a("|---|---|---|---|---|---|---|---|---|")
    for c in cal:
        a(f"| {c['kind']} | {c['lags']} | {c['window']} | {c['cutoff']} | {c['windows']} | {c['failing_windows']} | "
          f"{c['failing_windows'] / c['windows']:.4f} | {2.0 ** -CAL_ALPHA_LOG2:.4f} | {c['true_tail']:.3g} |")
    a("")
    a("The same under-coverage at the real operating point, analytically (exact lag-1 tail at the binomial "
      "cutoff versus its per-lag target `2^-40 / L`):")
    a("")
    a("| L | W_L | C_L binomial | exact `Pr(M >= C_L binomial)` | target `2^-40 / L` | factor over target | C_L exact |")
    a("|---|---|---|---|---|---|---|")
    for lags, w in ((8, 1024), (32, 1024), (32, 4096), (256, 4096)):
        cb = lagcount.c_lag_binomial(lags, w)
        t = lagcount.exact_tail(w, 1, 2.0 ** -H_DESIGN, cb)
        tgt = 2.0 ** -40 / lags
        a(f"| {lags} | {w} | {cb} | {t:.3g} | {tgt:.3g} | {t / tgt:.3g} | {lagcount.c_lag(lags, w)} |")
    a("")
    a("## Replay over the sky130 behavioural corner streams")
    a("")
    a("The 18 Ts = 20 us streams of the volume campaigns (131072 samples each, hash-verified by the loader of "
      "`sim/digital-health-test-parameters/analysis/health-test-replay.py`; behavioural model with independent noise "
      "increments, **not silicon**). Worst = largest lag match count over every lag and window; "
      "margin = `C_L` - worst.")
    a("")
    hdr = "| stream | H_est |" + "".join(f" L={l} W={w} (C_L {lagcount.c_lag(l, w)}): alarms / worst |" for l, w in REPLAY_CONFIGS)
    a(hdr)
    a("|---|---|" + "---|" * len(REPLAY_CONFIGS))
    for r in replay:
        a(f"| {r['label']} | {r['h_est']:.3f} |" + "".join(
            f" {r['cfg'][c]['alarms']} / {r['cfg'][c]['worst']} |" for c in REPLAY_CONFIGS))
    a("")
    for c in REPLAY_CONFIGS:
        worst = max(r["cfg"][c]["worst"] for r in replay)
        cut = replay[0]["cfg"][c]["cutoff"]
        a(f"- L={c[0]} W={c[1]}: total alarms {sum(r['cfg'][c]['alarms'] for r in replay)}; "
          f"worst count {worst} vs `C_L` {cut} (min margin {cut - worst}, {(cut - worst) / c[1]:.3f} of W)")
    a("")
    a("## Notes")
    a("")
    a("- A period-k stream has lag-k match rate 1 (less flip noise); the monitor therefore covers periods")
    a("  k <= L (and any stream with a lag-j<=L correlation above `C_L / W_L`). A period > L stays missed by")
    a("  construction: that is the documented limit, not a defect.")
    a("- The monitor is one-sided (high match rate). Anti-correlation is not a failure mode of interest here;")
    a("  a period-k stream is always caught through its lag-k (high) match rate.")
    a("- Ratified cutoffs and spec text are unchanged. Adoption, RTL and register plumbing are a separate,")
    a("  operator-ratified decision (DR-0015 is Proposed).")
    return "\n".join(L)


def main_j(args):
    rows = lag_sweep(args.seed, args.n)
    fa = []
    for lags, w in ((32, 4096), (256, 4096), (32, 1024)):
        fa.append(false_alarm_run(args.seed + FA_SEED_OFFSET, lags, w))
        fa.append(false_alarm_run(args.seed + FA_SEED_OFFSET + 1, lags, w,
                                  bias_p1=2 ** -H_DESIGN))
    cal = []
    from decimal import Decimal
    for lags, w in ((16, 1024), (16, 4096)):
        alpha_log2 = CAL_ALPHA_LOG2
        c_exact = lagcount.c_lag(lags, w, alpha_log2=alpha_log2)
        alpha = Decimal(2) ** -alpha_log2 / Decimal(lags)
        c_binom = lagcount.binomial_cutoff(w, lagcount.match_probability(H_DESIGN), alpha)
        for kind, c in (("exact (used)", c_exact), ("binomial (not used)", c_binom)):
            r = false_alarm_run(args.seed + FA_SEED_OFFSET + 2, lags, w, c_override=c,
                                bias_p1=2 ** -H_DESIGN)
            r["kind"] = kind
            r["true_tail"] = lagcount.exact_tail(w, 1, 2.0 ** -H_DESIGN, c)
            cal.append(r)
    replay = corner_replay()
    body = build_report_j(rows, args.seed, args.n, fa, cal, replay)
    print(body)
    ctrl = rows[0]
    ok = (not ctrl["rct_apt_alarm"]
          and all(not ctrl["lag"][k]["alarm"] for k in ctrl["lag"])
          and all(f["failing_windows"] == 0 for f in fa)
          and all(r["cfg"][c]["alarms"] == 0 for r in replay for c in REPLAY_CONFIGS)
          and all(c["failing_windows"] / c["windows"] <= 2.0 ** -CAL_ALPHA_LOG2 * 1.5
                  for c in cal if c["kind"].startswith("exact")))
    if not ok:
        print("\nHARNESS SANITY FAILED", file=sys.stderr)
    if args.emit_record:
        artifact = Path(tempfile.gettempdir()) / "lagcount-coverage-rows.txt"
        artifact.write_text("\n".join(
            f"{r['label']}\th_true={r['h_true']:.4f}\trct_apt={r['rct_apt_alarm']}\t"
            + "\t".join(f"L{k[0]}W{k[1]}={v['first']}" for k, v in r["lag"].items())
            for r in rows) + "\n")
        summary_rows = [{"label": r["label"], "family": r["family"], "h_true": r["h_true"],
                         "rct_apt_alarm": r["rct_apt_alarm"],
                         "lag": {f"L{k[0]}_W{k[1]}": {"alarm": v["alarm"], "first": v["first"]}
                                 for k, v in r["lag"].items()}} for r in rows]
        mint_behavioral_record(
            repo_root=REPO_ROOT, slug=SLUG,
            claim=("experiment J: detection coverage and false-alarm limit of a STUDY lag-k match-count "
                   "monitor (not adopted, additive to the unchanged DR-0004 RCT/APT) on the experiment-I "
                   "SYNTHETIC logic stimuli (no silicon entropy claim)"),
            body_md=body,
            summary={"ok": ok, "seed": args.seed, "n": args.n, "experiment": "J",
                     "h_design": H_DESIGN, "rows": summary_rows, "false_alarm": fa,
                     "calibration": cal,
                     "corner_replay": [{"label": r["label"], "h_est": r["h_est"],
                                        "cfg": {f"L{k[0]}_W{k[1]}": v for k, v in r["cfg"].items()}}
                                       for r in replay]},
            level="behavioral",
            seeds={"python_random": args.seed, "false_alarm_random": args.seed + FA_SEED_OFFSET},
            artifacts=[artifact],
        )
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--lagcount", action="store_true",
                    help="experiment J: study lag-k match-count monitor next to RCT/APT (#301)")
    args = ap.parse_args(argv)
    if args.lagcount:
        return main_j(args)

    rows = sweep(args.seed, args.n)
    body = build_report(rows, args.seed, args.n)
    print(body)

    # Sanity checks on the harness itself (not on coverage): control must not
    # alarm, a locked period-2 eps=0 stream must be zero-entropy.
    ctrl = rows[0]
    ok = (not ctrl["alarm"]
          and all(r["h_true"] >= 0 for r in rows)
          and any(r["family"] == "periodic" and r["h_true"] == 0 for r in rows))
    if not ok:
        print("\nHARNESS SANITY FAILED", file=sys.stderr)

    if args.emit_record:
        artifact = Path(tempfile.gettempdir()) / "health-detection-coverage-rows.txt"
        artifact.write_text("\n".join(
            f"{r['label']}\th_true={r['h_true']:.4f}\talarm={r['alarm']}\t"
            f"first={r['first_alarm_at']}\tcatchers={','.join(r['estimator_catchers'])}"
            for r in rows) + "\n")
        mint_behavioral_record(
            repo_root=REPO_ROOT, slug=SLUG,
            claim=("experiment I: detection coverage of the DR-0004 RCT/APT health tests, and of the "
                   "non-MCV 90B estimators, against serially-correlated, periodic and lock-mixture "
                   "SYNTHETIC logic stimuli of known analytic min-entropy (no silicon entropy claim)"),
            body_md=body,
            summary={"ok": ok, "seed": args.seed, "n": args.n, "experiment": "I",
                     "h_design": H_DESIGN, "rows": rows},
            level="behavioral",
            seeds={"python_random": args.seed},
            artifacts=[artifact],
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
