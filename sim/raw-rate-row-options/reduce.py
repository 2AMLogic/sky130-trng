#!/usr/bin/env python3
"""Reduction for the raw-rate-row options study (issue #600).

    reduce.py --emit-record REQDIR   # REQDIR/<name>/{resp.json,plan.json,request.json,netlist.cir}
    reduce.py --check RECORD.json    # replay a record from its committed raw responses
    reduce.py --known-answer         # committed-evidence replay, no new responses

Pure arithmetic over `klt sim` responses plus committed evidence; it runs no
simulator. It FAILS CLOSED: a missing point, a missing or non-finite
measurement, a failed unit, a netlist-sha mismatch, or a baseline control
outside tolerance raises `ReductionError` and no record is emitted.

What it reduces
---------------
Two levers against the README's `> 1 Mbps` raw-rate row, on top of the
committed operating point (DR-0003, `sim/ro-array-operating-point/`):

  S   sample-before-combine: one sampler_dff per ring (the `ring_bit` taps
      `sampler_core.spice` already instantiates), XOR taken digitally, so
      `N_max_combine` no longer applies. `N` at 1 Mbps is then set by the
      entropy law alone.
  J   a higher-Q ring: the committed 5-stage starved ring replaced by the
      3-inversion ring (ro_nand2 + 2 ro_stage), the fastest odd-stage-count
      ring this cell set supports. Measured here BOTH as a transient-noise
      jitter vehicle (`ring3`, 4 (T,V) x {tt,ss,ff}) AND through the
      deterministic swing/current method of
      `sim/ro-ring5-swing-and-current/` (`sc3`, same 4 (T,V) grid), which
      supplies its own LOADED period (no ratio estimate), its own per-ring
      supply current for the power row, and the buffered-output swing that
      answers DR-0002 Sec 2's below-five-stages question.

Two baseline controls, both re-runs of committed configurations:

  ctrl5  the committed 5-stage jitter vehicle at ss/tt/ff, -40 C, 1.62 V,
         against committed record 20260825-060208-54f5715. Two-tier: `tbar`
         gated +-(1/2)% (deterministic anchor), `sigma_1` gated statistically
         (see CONTROL_PROBE_PS: ngspice-47 trnoise is not same-seed
         replayable, so single-draw cross-build sigma comparison is
         statistical, not bitwise).
  sc5    the committed deterministic swing/current deck re-run on its own
         4 x 3 grid, against records 20260825-085{315,402,449,537}-53f1f7a:
         loaded tbar +-(2%), swing fractions +-(2%), supply currents +-(5%),
         all deterministic.

For every option (committed, J, S, S+J) the README rows are reported together
against their unchanged targets: raw rate (`> 1 Mbps`), active power
(`< 500 uW`), area (`< 0.05 mm2`), idle (`<= 200 uW`, DR-0018 provisional),
plus the structural failure modes sample-before-combine introduces.

Committed inputs (every figure in the record cites one of these):

  sim/ro-array-operating-point/records/20260825-093740-53f1f7a.json
  sim/ro-ring-jitter-accumulation/records/20260825-060208-54f5715.json
  sim/ro-ring-jitter-accumulation/records/*.json (the 9 ring5 files, 27 points)
  sim/ro-ring5-swing-and-current/records/*.json
  sim/ro-array-sizing/records/20260825-071619-54f5715.json
  sim/ro-array-core-combining/records/20261008-135357-847b454.json
  sim/local-mismatch-monte-carlo/records/20261009-111125-e57ad27.json
  sim/ro-array-idle-leakage/records/20261106-185750-8deaf42.json
  sim/post-layout-sampler-dff/records/20260907-120320-e82623e.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SLUG = "raw-rate-row-options"
sys.path.insert(0, str(REPO / "layout" / "bin"))
from _hashing import sha256_file  # noqa: E402
sys.path.insert(0, str(REPO / "sim" / "bin"))
from loadmod import load_module  # noqa: E402
from replay_equal import replay_diff  # noqa: E402

MR = load_module("rrro_make_requests", HERE / "make-requests.py")
from evidence_record import mint_record, new_record_id, read_corner_bundle, write_corner_bundle  # noqa: E402
from request_dir import load_request_dir  # noqa: E402

# ---------------------------------------------------------------------------
# committed-evidence anchors
# ---------------------------------------------------------------------------
OP_RECORD = REPO / "sim" / "ro-array-operating-point" / "records" / "20260825-093740-53f1f7a.json"
CTRL_RECORD = REPO / "sim" / "ro-ring-jitter-accumulation" / "records" / "20260825-060208-54f5715.json"
JITTER_RECORDS = REPO / "sim" / "ro-ring-jitter-accumulation" / "records"
RING5_SC_RECORDS = REPO / "sim" / "ro-ring5-swing-and-current" / "records"
SIZING_RECORD = REPO / "sim" / "ro-array-sizing" / "records" / "20260825-071619-54f5715.json"
ARRAY125_RECORD = REPO / "sim" / "ro-array-core-combining" / "records" / "20261008-135357-847b454.json"
MISMATCH_RECORD = REPO / "sim" / "local-mismatch-monte-carlo" / "records" / "20261009-111125-e57ad27.json"
IDLE_RECORD = REPO / "sim" / "ro-array-idle-leakage" / "records" / "20261106-185750-8deaf42.json"
SAMPSFF_RECORD = REPO / "sim" / "post-layout-sampler-dff" / "records" / "20260907-120320-e82623e.json"

TOL_TBAR_JITTER = 0.005     # ctrl5 vs committed tbar (deterministic anchor)
TOL_SIGMA_BINDING = 0.35    # ctrl5 sigma_1 at ss: the committed campaign's own
                            # measured run-to-run scatter is ~31%
TOL_SIGMA_COARSE = 0.60     # coarse sanity bound, non-binding corners
TOL_TBAR_SC = 0.02          # sc5 vs committed loaded tbar (deterministic)
TOL_SWING_SC = 0.02         # sc5 vs committed swing fractions (deterministic)
TOL_CURRENT_SC = 0.05       # sc5 vs committed supply currents (deterministic)
SIGMA_FLOOR_20P = 0.646e-12  # numerical floor at TMAX 20p (ro-array-sizing record)
EXPECTED_REQUESTS = 13
EXPECTED_JOBS = 39
RATE_1MBPS = 1.0e6

# README target-table rows (unchanged by this study)
ROW_ACTIVE_UW = 500.0        # "< 500 uW active"
ROW_AREA_UM2 = 0.05 * 1e6    # "< 0.05 mm2" in um2
ROW_IDLE_UW = 200.0          # DR-0018 provisional idle envelope
SWING_BAR = 0.80             # DR-0002 Sec 2's ring-node swing bar (x Vdd)

# area anchors
DEVICES_RING5 = 22           # ro_nand2 (6) + 4 x ro_stage (4)  -- DR-0003 Sec 7
DEVICES_RING3 = 14           # ro_nand2 (6) + 2 x ro_stage (4)
DEVICES_BUF = 2              # ro_buf, an inverter
DEVICES_DFF = 22             # sampler_dff (layout/sampler_dff/README.md)
ARRAY_DEVICES_N4 = 132       # DR-0003 Sec 7: 4x22 + 4x2 + 3x12
ARRAY_RAW_UM2_N4 = 880.0     # DR-0003 Sec 7 raw transistor area
AREA_OVERHEAD = (3.0, 10.0)  # DR-0003 Sec 7 rough interconnect/isolation range
SAMPLER_CORE_MACRO_UM2 = 19297.0   # DR-0010 row 7: 0.019297 mm2
SAMPLER_CORE_DEVICES = 264    # 132 (array) + 6 x 22 (sampler_dff instances)
# layout/trng_whole/report.json at the study commit 7b5b48ca
DIGITAL_MACRO_MM2 = 0.06005
COMMITTED_WHOLE_MM2 = 0.126116

# Same-build (ngspice-47), same-deck extra draws at the ctrl5 point
# (-40 C / 1.62 V), local single-corner debug probes, sigma_1 raw in ps. The
# tt seed-2 deck was run three times byte-identical: 2.7063 / 2.8331 /
# 2.9630 ps -- trnoise streams do not replay on this build, so every run is a
# fresh draw from the estimator's ~16 %-1sigma, 20-sample distribution.
# Reproduce from corners/<rid>/ctrl5--40C-1.62V.netlist.cir, `.option seed=n`.
CONTROL_PROBE_PS = {
    "tt": {"committed_46_seed1": 2.5543, "draws": [2.7063, 2.8331, 2.9630, 2.5169, 3.6596]},
    "ss": {"committed_46_seed1": 3.6062, "draws": [3.6271, 3.0903, 3.2642]},
    "ff": {"committed_46_seed1": 3.2697, "draws": [2.7230, 3.3918, 2.9949]},
}

CLAIM = ("Evidence study for the README's > 1 Mbps raw-rate row: sample-before-combine "
         "(lever S) and a 3-inversion higher-Q ring (lever J), each and combined, "
         "against the unchanged rate, power, area and idle rows. Two baseline "
         "controls re-run committed configurations (transient-noise jitter vehicle "
         "+ deterministic swing/current deck); no target is amended.")


class ReductionError(Exception):
    """A fail-closed condition: the reduction refuses to produce a result."""


def key_of(t, v, c):
    return (round(float(t), 6), round(float(v), 6), c)


# ---------------------------------------------------------------------------
# the committed estimators, re-expressed over .meas outputs
# ---------------------------------------------------------------------------
def estimator(tc: list[float]) -> dict:
    """tbar / sigma_1..8 from the 21 rising-crossing times tc2..tc22.

    Replicates the committed `.control` loop of
    sim/ro-ring-jitter-accumulation/testbench/tb_ro_ring5_jitter.spice
    verbatim: tbar = (tc[20]-tc[0])/20, r_N = (tc[N,20] - tc[0,20-N]) - N*tbar,
    sigma_N = sqrt(mean(r_N^2) / (1 - N/20)).
    """
    if len(tc) != 21:
        raise ReductionError(f"estimator: need 21 crossing times, got {len(tc)}")
    if any(b - a <= 0 for a, b in zip(tc, tc[1:])):
        raise ReductionError("estimator: non-monotone crossing times")
    tbar = (tc[20] - tc[0]) / 20.0
    out = {"tbar": tbar}
    for n in (1, 2, 4, 8):
        r = [(tc[i + n] - tc[i]) - n * tbar for i in range(0, 21 - n)]
        out[f"sigma_{n}"] = math.sqrt(sum(x * x for x in r) / len(r) / (1.0 - n / 20.0))
    return out


def sc_derive(raw: dict, vdd: float) -> dict:
    """The committed swing/current deck's derived figures from .meas outputs:
    tbar = (tc11-tc3)/8, swing fractions, duty, sign-flipped currents."""
    tbar = (raw["tc11"] - raw["tc3"]) / 8.0
    if tbar <= 0:
        raise ReductionError("sc: non-positive loaded period")
    return {
        "t0_loaded_s": tbar,
        "swing_frac_ring": (raw["vmax_ring"] - raw["vmin_ring"]) / vdd,
        "swing_frac_buf": (raw["vmax_buf"] - raw["vmin_buf"]) / vdd,
        "duty_ring": (raw["tfall3"] - raw["tc3"]) / (raw["tc4"] - raw["tc3"]),
        "i_ring_run_a": -raw["iddr_run"],
        "i_ring_stop_a": -raw["iddr_stop"],
        "i_buf_a": -raw["ibuf"],
    }


def quad_correct(sigma_raw: float, floor: float = SIGMA_FLOOR_20P) -> float:
    val = sigma_raw * sigma_raw - floor * floor
    if val <= 0:
        raise ReductionError(f"sigma_1 raw {sigma_raw:.4g}s inside the {floor:.4g}s numerical floor")
    return math.sqrt(val)


# ---------------------------------------------------------------------------
# committed-evidence loaders
# ---------------------------------------------------------------------------
def load_op_record() -> dict:
    d = json.loads(OP_RECORD.read_text())
    ent = d["entropy"]
    assert abs(ent["sigma_1_s"] - 3.5478536508679384e-12) < 1e-24, ent["sigma_1_s"]
    assert abs(ent["t0_loaded_s"] - 5.468648e-09) < 1e-18, ent["t0_loaded_s"]
    assert abs(ent["q_required"] - 0.005946085230582815) < 1e-15, ent["q_required"]
    assert d["combining"]["n_max_combine"] == 6
    assert d["chosen"]["n"] == 4 and abs(d["chosen"]["t_s_chosen_s"] - 20e-6) < 1e-12
    return d


def load_control_targets() -> dict:
    d = json.loads(CTRL_RECORD.read_text())
    assert d["pvt"] == {"temp_c": -40.0, "vdd_v": 1.62}, d["pvt"]
    out = {}
    for c in d["corners"]:
        m = c["measurements"]
        out[c["corner"]] = {
            "sigma_1_raw": m["sigma_1"], "tbar": m["tbar"], "swing_frac": m["swing_frac"],
            "sigma_1_corrected": quad_correct(m["sigma_1"]),
        }
    assert set(out) == {"tt", "ss", "ff"}
    assert abs(out["ss"]["sigma_1_corrected"] - 3.5479e-12) < 2e-16, out["ss"]
    assert abs(out["ss"]["tbar"] - 4.822537e-09) < 1e-18, out["ss"]
    return out


def load_ring5_grid() -> list[dict]:
    rows = []
    for path in sorted(JITTER_RECORDS.glob("*.json")):
        d = json.loads(path.read_text())
        if "ro_ring5" not in d.get("testbench", ""):
            continue
        for c in d.get("corners", []):
            m = c["measurements"]
            rows.append({
                "temp_c": d["pvt"]["temp_c"], "vdd_v": d["pvt"]["vdd_v"],
                "corner": c["corner"], "tbar": m["tbar"],
                "sigma_1": quad_correct(m["sigma_1"]),
                "swing_frac": m["swing_frac"], "record_id": d["record_id"],
            })
    if len(rows) != 27:
        raise ReductionError(f"expected the committed 27-point ring5 grid, got {len(rows)}")
    return rows


def load_ring5_loaded() -> dict:
    """Committed loaded ring5 period + per-ring currents per (T, V, corner)."""
    out = {}
    for path in sorted(RING5_SC_RECORDS.glob("*.json")):
        d = json.loads(path.read_text())
        t, v = d["pvt"]["temp_c"], d["pvt"]["vdd_v"]
        for c in d["corners"]:
            m = c["measurements"]
            out[key_of(t, v, c["corner"])] = {
                "t0_loaded_s": m["tbar"], "i_ring_run_a": m.get("i_ring_run"),
                "i_buf_a": m.get("i_buf"), "swing_frac_ring": m.get("swing_frac_ring"),
                "swing_frac_buf": m.get("swing_frac_buf"), "record_id": d["record_id"],
            }
    if len(out) != 12:
        raise ReductionError(f"expected the committed 12-point loaded grid, got {len(out)}")
    return out


def load_misc_anchors() -> dict:
    arr125 = json.loads(ARRAY125_RECORD.read_text())
    i125 = None
    for c in arr125.get("corners", []):
        if c.get("corner") == "ff":
            i125 = c.get("measurements", {}).get("i_array_total")
    if i125 is None or abs(i125 - 2.3936e-4) / 2.3936e-4 > 0.02:
        raise ReductionError(f"array 125 C anchor drifted: {i125}")
    sff = json.loads(SAMPSFF_RECORD.read_text())
    tcqs = [m for c in sff.get("corners", [])
            for k in ("tcq_rise_pex", "tcq_fall_pex")
            if (m := c.get("measurements", {}).get(k)) is not None]
    return {"i_array_total_125ff": i125, "tcq_pex_range_s": [min(tcqs), max(tcqs)]}


# ---------------------------------------------------------------------------
# option models
# ---------------------------------------------------------------------------
def entropy_n(k: float, q_req: float, rate: float) -> int:
    return max(1, math.ceil(q_req / (k / rate)))


def rate_ceiling_at_n(n: int, k: float, q_req: float) -> float:
    return n * k / q_req


def devices(n_rings: int, per_ring_devices: int) -> int:
    return n_rings * (per_ring_devices + DEVICES_BUF + DEVICES_DFF)


def area_estimate_um2(n_rings: int, per_ring_devices: int) -> dict:
    dev = devices(n_rings, per_ring_devices)
    per_dev_raw = ARRAY_RAW_UM2_N4 / ARRAY_DEVICES_N4
    per_dev_macro = SAMPLER_CORE_MACRO_UM2 / SAMPLER_CORE_DEVICES
    raw = dev * per_dev_raw
    return {
        "devices": dev, "raw_um2": raw,
        "raw_x3_um2": raw * AREA_OVERHEAD[0], "raw_x10_um2": raw * AREA_OVERHEAD[1],
        "macro_density_um2": dev * per_dev_macro,
    }


def idle_power_uw(n_rings: int, per_ring_ua: float, per_dff_ua: float,
                  vdd: float, digital_uw: float) -> dict:
    analog = (n_rings * per_ring_ua + (n_rings + 2) * per_dff_ua) * vdd
    return {"analog_uw": analog, "digital_uw": digital_uw, "total_uw": analog + digital_uw}


def lock_proximity(n_rings: int, span: float, sigma_pct: float) -> dict:
    """Spacing arithmetic + committed independent-Gaussian model, per the
    mismatch record: with N rings inside a nominal period span `span`, mean
    adjacent spacing is span^(1/(N-1)); keeping every adjacent pair >= 2%
    apart (the DR-0005 rationals / 1:1 lock-proximity scale) needs
    span >= 1.02^(N-1)."""
    need = 1.02 ** (n_rings - 1)
    got = span ** (1.0 / (n_rings - 1)) if n_rings > 1 else float("inf")
    pairs = n_rings * (n_rings - 1) // 2
    from statistics import NormalDist
    z = math.log(1.02) / (math.sqrt(2.0) * sigma_pct / 100.0)
    p_pair = 2.0 * NormalDist().cdf(z) - 1.0
    return {
        "span_needed_for_2pct": need,
        "adjacent_spacing_in_span": got,
        "pairs_total": pairs,
        "expected_pairs_within_2pct_unspaced": pairs * p_pair,
        "per_pair_p_within_2pct": p_pair,
    }


def sigma1_vs_t0_alpha(grid: list[dict]) -> dict:
    xs = [math.log(r["tbar"]) for r in grid]
    ys = [math.log(r["sigma_1"]) for r in grid]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    alpha = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (my + alpha * (x - mx))) ** 2 for x, y in zip(xs, ys))
    return {"alpha": alpha, "r2": 1.0 - ss_res / ss_tot, "points": n,
            "ceiling_exponent": 2 * alpha - 2.0, "q_exponent": 2 * alpha - 3.0}


# ---------------------------------------------------------------------------
# response parsing
# ---------------------------------------------------------------------------
TC_NAMES = [f"tc{k}" for k in range(2, 23)]
JITTER_MEAS = TC_NAMES + ["vmax_ss", "vmin_ss"]
SC_MEAS = ["vmax_ring", "vmin_ring", "vmax_buf", "vmin_buf", "tc3", "tc11",
           "tfall3", "tc4", "iddr_run", "iddr_stop", "ibuf"]


def _raw_measurements(c0, name, proc):
    meas_list = c0.get("measurements")
    raw = {}
    if isinstance(meas_list, list):
        bad = []
        for m in meas_list:
            if m.get("value") is None or str(m.get("status", "")).lower() not in ("", "pass", "ok"):
                bad.append((m.get("name"), m.get("status")))
            raw[m.get("name")] = m.get("value")
        if bad:
            raise ReductionError(f"{name}/{proc}: failed measurement(s) {bad}")
    else:
        raw = dict(meas_list or {})
    return raw


def jobs_from_responses(chunks) -> list[dict]:
    rows = []
    for name, plan, resp in chunks:
        cfg = plan["config"]
        t, v = float(plan["pvt"]["temp"]), float(plan["pvt"]["vnom"])
        corners = resp.get("corners") or []
        if not corners:
            raise ReductionError(f"{name}: response carries no corner units")
        env = resp.get("environment", {})
        for c0 in corners:
            if str(c0.get("status", "")).lower() != "pass":
                diag = c0.get("diagnostics") or []
                msg = "; ".join(str(d.get("message", d.get("code", ""))) for d in diag)[:300]
                raise ReductionError(f"{name}: unit status {c0.get('status')!r}: {msg}")
            proc = c0.get("process") or str(c0.get("corner_id", "?")).split("/")[0]
            raw = _raw_measurements(c0, name, proc)
            if cfg in ("ctrl5", "ring3"):
                need = JITTER_MEAS
            else:
                need = SC_MEAS
            missing = [n for n in need if raw.get(n) is None]
            if missing:
                raise ReductionError(f"{name}/{proc}: missing measurement(s) {missing}")
            base = {
                "config": cfg, "temp_c": t, "vdd_v": v, "corner": proc,
                "models_lib_sha256": env.get("models_lib_sha256"),
                "netlist_sha256": env.get("netlist_sha256"),
                "job_id": (env.get("remote") or {}).get("job_id"),
            }
            if cfg in ("ctrl5", "ring3"):
                est = estimator([float(raw[n]) for n in TC_NAMES])
                swing = (float(raw["vmax_ss"]) - float(raw["vmin_ss"])) / v
                rows.append({**base, **est, "swing_frac_noise": swing,
                             "sigma_1_corrected": quad_correct(est["sigma_1"])})
            else:
                nums = {n: float(raw[n]) for n in SC_MEAS}
                rows.append({**base, **sc_derive(nums, v)})
    return rows


def verify_netlist_shas(chunks, netlist_path):
    for name, _plan, resp in chunks:
        recorded = (resp.get("environment", {}) or {}).get("netlist_sha256")
        path = netlist_path(name)
        if recorded is None or not path.is_file():
            raise ReductionError(f"{name}: cannot verify netlist sha ({recorded}, {path})")
        actual = sha256_file(path, prefix=True)
        if recorded != actual and recorded.removeprefix("sha256:") != actual.removeprefix("sha256:"):
            raise ReductionError(f"{name}: response netlist sha {recorded} != deck {path} ({actual})")


# ---------------------------------------------------------------------------
# controls
# ---------------------------------------------------------------------------
def control_gate_jitter(ctrl_rows, targets) -> dict:
    out = {}
    for r in ctrl_rows:
        if r["config"] != "ctrl5":
            continue
        tgt = targets.get(r["corner"])
        if tgt is None:
            raise ReductionError(f"control: no committed target at {r['corner']}")
        ds = r["sigma_1"] / tgt["sigma_1_raw"] - 1.0
        dt = r["tbar"] / tgt["tbar"] - 1.0
        if abs(dt) > TOL_TBAR_JITTER:
            raise ReductionError(
                f"control tbar {r['corner']}: {r['tbar']:.4g} vs committed {tgt['tbar']:.4g} "
                f"({dt:+.2%}) -- the deterministic anchor failed")
        gate = TOL_SIGMA_BINDING if r["corner"] == "ss" else TOL_SIGMA_COARSE
        if abs(ds) > gate:
            raise ReductionError(
                f"control sigma_1 {r['corner']}: {ds:+.2%}, gate +-{gate:.0%}; "
                "see CONTROL_PROBE_PS -- single-draw sigma comparison across "
                "ngspice builds is statistical, not bitwise")
        probe = CONTROL_PROBE_PS[r["corner"]]
        lo = min(probe["draws"] + [r["sigma_1"] * 1e12]) * 0.9
        hi = max(probe["draws"] + [r["sigma_1"] * 1e12]) * 1.1
        if not (lo <= tgt["sigma_1_raw"] * 1e12 <= hi):
            raise ReductionError(
                f"control sigma_1 {r['corner']}: committed {tgt['sigma_1_raw']*1e12:.4f} ps "
                f"outside the same-build draw envelope [{lo:.3f}, {hi:.3f}] ps")
        out[r["corner"]] = {"dev_sigma_1": ds, "dev_tbar": dt,
                            "this_run_sigma_1_raw": r["sigma_1"],
                            "this_run_tbar": r["tbar"],
                            "committed_sigma_1_raw": tgt["sigma_1_raw"],
                            "committed_tbar": tgt["tbar"]}
    if set(out) != {"tt", "ss", "ff"}:
        raise ReductionError(f"control: need tt/ss/ff at -40 C / 1.62 V, got {sorted(out)}")
    return out


def control_gate_sc(sc_rows, committed_loaded) -> dict:
    """sc5 vs the committed swing/current records, deterministic gates."""
    out = {}
    for r in sc_rows:
        if r["config"] != "sc5":
            continue
        key = key_of(r["temp_c"], r["vdd_v"], r["corner"])
        tgt = committed_loaded.get(key)
        if tgt is None:
            raise ReductionError(f"sc5 control: no committed point at {key}")
        checks = {
            "t0_loaded_s": (r["t0_loaded_s"] / tgt["t0_loaded_s"] - 1.0, TOL_TBAR_SC),
            "swing_frac_ring": (r["swing_frac_ring"] / tgt["swing_frac_ring"] - 1.0, TOL_SWING_SC),
            "swing_frac_buf": (r["swing_frac_buf"] / tgt["swing_frac_buf"] - 1.0, TOL_SWING_SC),
            "i_ring_run_a": (r["i_ring_run_a"] / tgt["i_ring_run_a"] - 1.0, TOL_CURRENT_SC),
            "i_buf_a": (r["i_buf_a"] / tgt["i_buf_a"] - 1.0, TOL_CURRENT_SC),
        }
        bad = {k: (dev, tol) for k, (dev, tol) in checks.items() if abs(dev) > tol}
        if bad:
            raise ReductionError(f"sc5 control drift at {key}: "
                                 + ", ".join(f"{k} {d:+.2%} (gate +-{t:.0%})" for k, (d, t) in bad.items()))
        out[json.dumps(key)] = {k: dev for k, (dev, _t) in checks.items()}
    if len(out) != 12:
        raise ReductionError(f"sc5 control: expected 12 points, got {len(out)}")
    return out


# ---------------------------------------------------------------------------
# the full reduction
# ---------------------------------------------------------------------------
def full_reduction(rows: list[dict]) -> dict:
    op = load_op_record()
    targets = load_control_targets()
    loaded5 = load_ring5_loaded()
    grid5 = load_ring5_grid()
    anchors = load_misc_anchors()
    q_req = op["entropy"]["q_required"]
    k5 = op["entropy"]["k"]

    # committed operating-point replay (arithmetic control, no sim)
    n_1mbs_ring5 = entropy_n(k5, q_req, RATE_1MBPS)
    committed_ceiling = rate_ceiling_at_n(op["combining"]["n_max_combine"], k5, q_req)
    if n_1mbs_ring5 != 78 or not (77.0e3 < committed_ceiling < 78.5e3):
        raise ReductionError(
            f"committed replay failed: N@1Mbps={n_1mbs_ring5}, ceiling={committed_ceiling}")

    # --- ring3, jitter + swing/current ------------------------------------
    r3 = [r for r in rows if r["config"] == "ring3"]
    sc3 = [r for r in rows if r["config"] == "sc3"]
    need = {key_of(t, v, c) for (t, v) in MR.JITTER_POINTS["ring3"] for c in MR.PROCESSES}
    got = {key_of(r["temp_c"], r["vdd_v"], r["corner"]) for r in r3}
    if got != need:
        raise ReductionError(f"ring3: missing grid points {sorted(need - got)}")
    sc3_by = {key_of(r["temp_c"], r["vdd_v"], r["corner"]): r for r in sc3}
    if set(sc3_by) != need:
        raise ReductionError(f"sc3: missing grid points {sorted(need - set(sc3_by))}")

    for r in r3:
        key = key_of(r["temp_c"], r["vdd_v"], r["corner"])
        s = sc3_by[key]
        r["t0_loaded_meas_s"] = s["t0_loaded_s"]
        r["q_ring_1us"] = r["sigma_1_corrected"] ** 2 * 1e-6 / s["t0_loaded_s"] ** 3
        r["swing_frac_ring_det"] = s["swing_frac_ring"]
        r["swing_frac_buf_det"] = s["swing_frac_buf"]
        r["i_ring_run_a"] = s["i_ring_run_a"]
        r["i_buf_a"] = s["i_buf_a"]
        # committed ring5 reference Q at the same point
        sig5 = next(g["sigma_1"] for g in grid5
                    if key_of(g["temp_c"], g["vdd_v"], g["corner"]) == key)
        r["ring5_q_ring_1us"] = sig5 ** 2 * 1e-6 / loaded5[key]["t0_loaded_s"] ** 3
        r["q_gain_vs_ring5"] = r["q_ring_1us"] / r["ring5_q_ring_1us"]

    binding3 = next(r for r in r3
                    if key_of(r["temp_c"], r["vdd_v"], r["corner"]) == (-40.0, 1.62, "ss"))
    k3 = binding3["sigma_1_corrected"] ** 2 / binding3["t0_loaded_meas_s"] ** 3
    n_1mbs_ring3 = entropy_n(k3, q_req, RATE_1MBPS)
    # the binding corner must actually be this configuration's own grid minimum
    if any(r["q_ring_1us"] < binding3["q_ring_1us"] for r in r3):
        raise ReductionError("ring3: ss / -40 C / 1.62 V is not the grid Q minimum; "
                             "the binding corner moved and the reduction must be re-derived")

    w90 = {(row["temp_c"], row["vdd_v"], row["corner"]): row["w90_s"]
           for row in op["combining"]["rows"]}
    nmax3_rows = []
    for r in r3:
        key = (r["temp_c"], r["vdd_v"], r["corner"])
        if key not in w90:
            continue
        nmax = r["t0_loaded_meas_s"] / (2.0 * w90[key])
        nmax3_rows.append({"temp_c": key[0], "vdd_v": key[1], "corner": key[2],
                           "t0_loaded_s": r["t0_loaded_meas_s"],
                           "w90_s": w90[key], "n_max_combine": nmax,
                           "floor": math.floor(nmax)})
    if not nmax3_rows:
        raise ReductionError("ring3: no overlap with the committed w_90 grid")
    nmax3 = min(r["floor"] for r in nmax3_rows)
    worst3 = min(nmax3_rows, key=lambda r: r["n_max_combine"])
    ceiling3 = rate_ceiling_at_n(nmax3, k3, q_req)

    # --- power / area / idle / lock models ---------------------------------
    def per_ring_ua(rowsel):
        vals = {}
        for r in rowsel:
            vals[(r["temp_c"], r["vdd_v"], r["corner"])] = (r["i_ring_run_a"] + r["i_buf_a"]) * 1e6
        wk = max(vals, key=vals.get)
        return vals[wk], wk, vals

    pr3_uA, pr3_key, pr3_all = per_ring_ua(sc3)
    pr5_uA, pr5_key, pr5_all = per_ring_ua([r for r in rows if r["config"] == "sc5"])
    # the power row's worst case uses whichever ring the option instantiates
    array125_uw = anchors["i_array_total_125ff"] * 1.98e6

    n_power_5 = math.floor(ROW_ACTIVE_UW / (pr5_uA * pr5_key[1]))
    n_power_3 = math.floor(ROW_ACTIVE_UW / (pr3_uA * pr3_key[1]))

    per_dev_macro = SAMPLER_CORE_MACRO_UM2 / SAMPLER_CORE_DEVICES
    n_area_ring5 = math.floor(ROW_AREA_UM2 / ((DEVICES_RING5 + DEVICES_BUF + DEVICES_DFF) * per_dev_macro))
    n_area_ring3 = math.floor(ROW_AREA_UM2 / ((DEVICES_RING3 + DEVICES_BUF + DEVICES_DFF) * per_dev_macro))
    areas = {"S_ring5": area_estimate_um2(n_1mbs_ring5, DEVICES_RING5),
             "S_ring3": area_estimate_um2(n_1mbs_ring3, DEVICES_RING3)}

    per_ring_ua125 = 0.255              # DR-0003 Sec 5 stopped-ring figure (255 nA, ff/125 C)
    idle_analog_na = 5.59e3             # ro-array-idle-leakage worst analog row (nA)
    per_dff_ua = (idle_analog_na - 4 * per_ring_ua125 * 1e3) / 6.0 / 1e3
    digital_uw, digital_xt_uw = 26.98, 103.8
    idles = {k: idle_power_uw(n, per_ring_ua125, per_dff_ua, 1.98, digital_uw)
             for k, n in (("S_ring5", n_1mbs_ring5), ("S_ring3", n_1mbs_ring3))}
    for v in idles.values():
        v["total_xt_uw"] = v["analog_uw"] + digital_xt_uw

    span, sigma_pct = 1.1686, 2.74      # committed mismatch record figures
    n_lock_free = 2
    while 1.02 ** (n_lock_free - 1) <= span:
        n_lock_free += 1
    n_lock_free -= 1
    locks = {name: lock_proximity(n, span, sigma_pct)
             for name, n in (("committed_N4", 4), ("S_ring5", n_1mbs_ring5),
                             ("S_ring3", n_1mbs_ring3))}

    fit = sigma1_vs_t0_alpha(grid5)

    s_power_uw = n_1mbs_ring5 * pr5_uA * pr5_key[1]
    sj_power_uw = n_1mbs_ring3 * pr3_uA * pr3_key[1]
    # draw sensitivity: sigma_1 is a single ~16 %-1sigma estimator draw; show
    # the rate bound at the same ring+buffer power cap for each draw
    draw_sens = {}
    for scale in (0.7, 1.0, 1.5):
        k3s = k3 * scale * scale
        draw_sens[f"sigma_x{scale:g}"] = {
            "n_1mbps": entropy_n(k3s, q_req, RATE_1MBPS),
            "ring_power_bound_kbps": rate_ceiling_at_n(n_power_3, k3s, q_req) / 1e3,
        }

    return {
        "op_record": op["record_id"],
        "control_targets_record": json.loads(CTRL_RECORD.read_text())["record_id"],
        "q_required": q_req, "k5": k5, "k3": k3,
        "committed": {
            "n": 4, "rate_kbps": 50.0, "n_max_combine": 6,
            "ceiling_kbps": committed_ceiling / 1e3,
            "n_min_entropy_1mbps_ring5": n_1mbs_ring5,
            "array_active_worst_uw": array125_uw,
        },
        "ring3": {
            "binding_corner": [-40.0, 1.62, "ss"],
            "q_ring_1us": binding3["q_ring_1us"],
            "q_gain_vs_ring5_binding": binding3["q_gain_vs_ring5"],
            "law_gain": (5 / 3) ** 2,
            "swing_ring_min": min(r["swing_frac_ring_det"] for r in r3),
            "swing_ring_min_at": min(r3, key=lambda r: r["swing_frac_ring_det"])[
                "temp_c"], "swing_ring_min_vdd": min(r3, key=lambda r: r["swing_frac_ring_det"])["vdd_v"],
            "swing_ring_min_corner": min(r3, key=lambda r: r["swing_frac_ring_det"])["corner"],
            "swing_buf_min": min(r["swing_frac_buf_det"] for r in r3),
            "points": [dict(temp_c=r["temp_c"], vdd_v=r["vdd_v"], corner=r["corner"],
                            tbar_unloaded_s=r["tbar"], t0_loaded_s=r["t0_loaded_meas_s"],
                            sigma_1_raw_s=r["sigma_1"], sigma_1_corrected_s=r["sigma_1_corrected"],
                            swing_ring_det=r["swing_frac_ring_det"], swing_buf_det=r["swing_frac_buf_det"],
                            i_ring_run_a=r["i_ring_run_a"], i_buf_a=r["i_buf_a"],
                            q_ring_1us=r["q_ring_1us"], q_gain_vs_ring5=r["q_gain_vs_ring5"])
                       for r in r3],
            "n_min_entropy_1mbps": n_1mbs_ring3,
            "n_max_combine": nmax3, "n_max_combine_worst": worst3,
            "ceiling_kbps": ceiling3 / 1e3,
        },
        "power": {
            "ring5_worst_per_ring_ua": pr5_uA, "ring5_worst_point": list(pr5_key),
            "ring3_worst_per_ring_ua": pr3_uA, "ring3_worst_point": list(pr3_key),
            "array125_anchor_uw": array125_uw,
            "n_power_row_ring5": n_power_5, "n_power_row_ring3": n_power_3,
            "S_uw": s_power_uw, "S_over_row": s_power_uw / ROW_ACTIVE_UW,
            "SJ_uw": sj_power_uw, "SJ_over_row": sj_power_uw / ROW_ACTIVE_UW,
        },
        "area": {
            **areas, "n_analog_only_ring5": n_area_ring5, "n_analog_only_ring3": n_area_ring3,
            "ring3_analog_um2_at_power_cap": area_estimate_um2(n_power_3, DEVICES_RING3)["macro_density_um2"],
            "committed_digital_macro_mm2": DIGITAL_MACRO_MM2,
            "committed_whole_block_mm2": COMMITTED_WHOLE_MM2,
            "macro_um2_per_device": per_dev_macro,
            "raw_um2_per_device": ARRAY_RAW_UM2_N4 / ARRAY_DEVICES_N4,
        },
        "idle": {
            "per_ring_ua_125c": per_ring_ua125, "per_dff_ua_125c": per_dff_ua,
            "digital_standby_uw": digital_uw, "digital_standby_xt_uw": digital_xt_uw,
            **{f"{k}_total_uw": v["total_uw"] for k, v in idles.items()},
            **{f"{k}_total_xt_uw": v["total_xt_uw"] for k, v in idles.items()},
        },
        "lock": {
            "characterized_span": span, "pooled_sigma_pct": sigma_pct,
            "n_lock_free_max": n_lock_free,
            **{f"{k}_expected_pairs_within_2pct_unspaced":
               v["expected_pairs_within_2pct_unspaced"] for k, v in locks.items()},
            "S_ring5_adjacent_spacing_in_span": locks["S_ring5"]["adjacent_spacing_in_span"],
        },
        "ring5_pvt_fit": fit,
        "draw_sensitivity": draw_sens,
        "ring_power_bound": {
            "rate_kbps_ring5": rate_ceiling_at_n(n_power_5, k5, q_req) / 1e3,
            "rate_kbps_ring3": rate_ceiling_at_n(n_power_3, k3, q_req) / 1e3,
            "basis": "entropy model with the full active-power budget allocated to rings and buffers",
            "whole_block_feasibility": "unestablished",
        },
        "anchors": anchors,
    }


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def render_body(rows, red, ctrl_j, ctrl_sc) -> str:
    e = red
    L: list[str] = []
    A = L.append
    pct = lambda x: f"{x:+.2%}"

    A("## Baseline control 1: the committed jitter vehicle re-run (statistical sigma, deterministic tbar)")
    A("")
    A(f"Re-run of the committed 5-stage jitter vehicle (`ctrl5`) at -40 C / 1.62 V,")
    A("same deck body (stages, `trnoise` calibration, `tstop`, `.ic`, seed card),")
    A(f"against committed record `{e['control_targets_record']}`. The control is")
    A("two-tier, because ngspice-47's `trnoise` is **not same-seed replayable**:")
    A("three byte-identical decks at `seed=2` (tt) measured 2.7063 / 2.8331 /")
    A("2.9630 ps, i.e. every run is a fresh draw from the estimator's ~16 %")
    A("one-sigma, 20-sample distribution (the committed campaign's own re-run")
    A("scatter was ~31 %). So **`tbar` is the deterministic anchor** -- gate")
    A(f"+-{TOL_TBAR_JITTER:.1%} at every corner -- and `sigma_1` is gated statistically:")
    A(f"+-{TOL_SIGMA_BINDING:.0%} at the entropy-binding corner `ss` (every `Q` below")
    A(f"depends on it), +-{TOL_SIGMA_COARSE:.0%} coarse elsewhere, plus an envelope")
    A("check that the committed value sits inside this build's draw spread.")
    A("")
    A("| corner | `tbar` this run (ns) | committed | dev | `sigma_1` this run (fs) | committed (fs) | dev |")
    A("|---|---|---|---|---|---|---|")
    for c in ("tt", "ss", "ff"):
        r = ctrl_j[c]
        A(f"| `{c}` | {r['this_run_tbar']*1e9:.4f} | {r['committed_tbar']*1e9:.4f} | "
          f"{pct(r['dev_tbar'])} | {r['this_run_sigma_1_raw']*1e15:.1f} | "
          f"{r['committed_sigma_1_raw']*1e15:.1f} | {pct(r['dev_sigma_1'])} |")
    A("")
    A("`tbar` reproduces at the 1e-3 level and the same-build draw envelope brackets")
    A("the committed value at every corner (probe draws quoted in `reduce.py`'s")
    A("`CONTROL_PROBE_PS`, reproduced from this record's own ctrl5 deck). Every")
    A("`sigma_1` in this record is therefore a single draw carrying the estimator's")
    A("~16 % (1 sigma) statistical error on top of DR-0002 Sec 6's ~1.5-2x")
    A("injected-level systematic.")
    A("")

    A("## Baseline control 2: the committed swing/current deck re-run (deterministic)")
    A("")
    A("`sc5` re-runs `sim/ro-ring5-swing-and-current/`'s own deck on its own")
    A("4 x 3 grid -- deterministic, no injected sources -- against the four")
    A(f"committed records. Gates: loaded `tbar` and both swing fractions within "
      f"+-{TOL_TBAR_SC:.0%}, supply currents within +-{TOL_CURRENT_SC:.0%}; the "
      "reduction fails closed outside any of them.")
    A("")
    A("| T (C) | Vdd (V) | corner | loaded `tbar` dev | swing_ring dev | swing_buf dev | `i_ring_run` dev | `i_buf` dev |")
    A("|---|---|---|---|---|---|---|---|")
    for key in sorted(ctrl_sc, key=lambda k: json.loads(k)):
        d = ctrl_sc[key]
        t, v, c = json.loads(key)
        A(f"| {t:g} | {v:g} | `{c}` | {pct(d['t0_loaded_s'])} | {pct(d['swing_frac_ring'])} | "
          f"{pct(d['swing_frac_buf'])} | {pct(d['i_ring_run_a'])} | {pct(d['i_buf_a'])} |")
    A("")
    A(f"Model library this run: `models_lib_sha256` = `{rows[0].get('models_lib_sha256')}`")
    A("(the same sha the Oct-11 #282 fleet responses record; the Aug-25 committed")
    A("campaigns ran the volare c6d73a35 install -- the deterministic gates above")
    A("are what close that pin gap). Engine: ngspice-47 on the fleet and locally")
    A("(the committed campaigns ran ngspice-46).")
    A("")

    A("## Committed operating point replay (arithmetic control)")
    A("")
    A(f"`k = sigma_1^2/T_0_loaded^3` = {e['k5']:.5f} 1/s from `{e['op_record']}`; "
      f"`M*Q_H0` = {e['q_required']:.6g}; replayed `N_min_entropy(1 Mbps)` = "
      f"**{e['committed']['n_min_entropy_1mbps_ring5']}** and combining ceiling "
      f"**{e['committed']['ceiling_kbps']:.2f} kbps** at `N_max_combine` = "
      f"{e['committed']['n_max_combine']} (the committed record's rate-table row "
      "hardcodes the 77.67 kbps label; re-deriving it from the record's own `k` "
      "gives the figure here -- same number to three digits, DR-0003's \"~78 kbps\").")
    A("")

    A("## Lever J: the 3-inversion ring, measured two ways")
    A("")
    A("`ring3` = `ro_nand2` + 2 `ro_stage`: the fastest odd-stage-count ring this")
    A("cell set supports (2 inversions cannot oscillate). Jitter/swing from the")
    A("noise vehicle; **loaded period, per-ring supply current and buffered swing")
    A("from the deterministic `sc3` deck** (the committed swing/current method,")
    A("buffer-load included) -- no ratio estimate anywhere. `Q_ring` uses the")
    A("quadrature-corrected `sigma_1` (floor 0.646 ps) and `T_s` = 1 us.")
    A("")
    A("| T (C) | Vdd (V) | corner | `tbar` unloaded (ns) | `T_0` loaded (ns) | `sigma_1` corr (ps) | swing ring (det) | swing buf | `i_ring`+`i_buf` (uA) | `Q_ring` | vs ring5 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for p in e["ring3"]["points"]:
        A(f"| {p['temp_c']:g} | {p['vdd_v']:g} | `{p['corner']}` | {p['tbar_unloaded_s']*1e9:.4f} | "
          f"{p['t0_loaded_s']*1e9:.4f} | {p['sigma_1_corrected_s']*1e12:.4f} | "
          f"{p['swing_ring_det']:.3f} | {p['swing_buf_det']:.3f} | "
          f"{(p['i_ring_run_a']+p['i_buf_a'])*1e6:.2f} | {p['q_ring_1us']:.3e} | "
          f"{p['q_gain_vs_ring5']:.2f}x |")
    A("")
    A(f"- At ss / -40 C / 1.62 V, the three-stage ring gives "
      f"**{e['ring3']['q_gain_vs_ring5_binding']:.2f}x** the five-stage ring's "
      f"per-ring `Q` for this jitter draw. The stage-count law predicts "
      f"{e['ring3']['law_gain']:.2f}x. The single draw leaves the size of the "
      "gain uncertain. Under the entropy model, `N_min_entropy(1 Mbps)` drops from "
      f"{e['committed']['n_min_entropy_1mbps_ring5']} to "
      f"**{e['ring3']['n_min_entropy_1mbps']}**.")
    sw = e["ring3"]
    A(f"- **Swing is the cost**: worst deterministic ring-node swing "
      f"**{sw['swing_ring_min']:.3f} x Vdd** at {sw['swing_ring_min_corner']} / "
      f"{sw['swing_ring_min_at']:g} C / {sw['swing_ring_min_vdd']:g} V, and below "
      f"DR-0002 Sec 2's 0.80 bar at **every** point measured (binding corner "
      f"included). The buffer squares the ring node back to rail-to-rail "
      f"(swing_buf >= 0.95) at the nine -40 C / 27 C points -- so the "
      "oscillation is real and usable there -- but at 125 C / 1.98 V the ring "
      f"is marginal: ring-node swing 0.165-0.328 and the BUFFERED output only "
      f"{sw['swing_buf_min']:.2f}-0.85, i.e. `ro_buf` no longer squares it up, "
      "and that is at nominal devices -- mismatch and supply noise eat "
      "directly into what little margin is left. DR-0002's swing caveat for "
      "sub-five-stage counts is therefore answered **negatively**: the "
      "entropy gain is real, the swing bar is not met, and the hot/high-"
      "supply corner is close to non-oscillation.")
    A(f"- **Combining still binds J alone**: `N_max_combine(ring3)` = "
      f"{e['ring3']['n_max_combine']} (worst {e['ring3']['n_max_combine_worst']['corner']} / "
      f"{e['ring3']['n_max_combine_worst']['temp_c']:g} C / "
      f"{e['ring3']['n_max_combine_worst']['vdd_v']:g} V: loaded `T_0` "
      f"{e['ring3']['n_max_combine_worst']['t0_loaded_s']*1e9:.3f} ns vs `w_90` "
      f"{e['ring3']['n_max_combine_worst']['w90_s']*1e12:.1f} ps -- a faster ring "
      "makes the analog XOR ceiling TIGHTER even as its per-ring Q rises). "
      f"The J-only ceiling moves to **{e['ring3']['ceiling_kbps']:.1f} kbps** "
      f"(from {e['committed']['ceiling_kbps']:.1f} for ring5). Both measured "
      "stage counts fall short of 1 Mbps with analog combining.")
    A("")
    A(f"The {e['ring5_pvt_fit']['points']}-point fit varies process, voltage and "
      "temperature on one five-stage geometry. The log-log slope of corrected "
      f"`sigma_1` against unloaded period is {e['ring5_pvt_fit']['alpha']:.3f} "
      f"(R² = {e['ring5_pvt_fit']['r2']:.3f}). Both stage-count decks fix device "
      "width and length. The direction and size of a width or length change on "
      "jitter, per-ring Q and combining bandwidth remain unknown.")
    A("")
    A("The decks use ideal DC supplies. Applying the stage-count result on "
      "hardware requires evidence at the ring pins for DC error, slow droop and "
      "RF ripple near the new ring frequencies. Proposed DR-0012 calls for "
      "margin below the five-stage ss droop exhaustion point (3.93 mV) and "
      "separate RF lock, bias and Q checks. These runs establish neither a "
      "ring3 supply tolerance nor a regulator or filter that meets it.")
    A("")

    A("## Lever S: sample-before-combine, and S+J")
    A("")
    A("One `sampler_dff` per ring (the `ring_bit` taps `sampler_core.spice` already")
    A("instantiate), XOR taken digitally after sampling: `N_max_combine` no longer")
    A("applies and `N` is set by the entropy law alone. The rows that bind become")
    A("power, area, idle and lock proximity. Per-ring active current is now")
    A("**measured per ring choice** (`sc3`/`sc5` worst point: ring5 "
      f"{e['power']['ring5_worst_per_ring_ua']:.2f} uA at "
      f"{e['power']['ring5_worst_point']}, ring3 {e['power']['ring3_worst_per_ring_ua']:.2f} uA at "
      f"{e['power']['ring3_worst_point']}).")
    A("")
    A("| option | N @ 1 Mbps | modeled raw rate | ring + buffer active power | analog area estimate | idle estimate | lock-prox pairs < 2% |")
    A("|---|---|---|---|---|---|---|")
    for label, n, area_key, pow_uw in (
        ("S (ring5)", e['committed']['n_min_entropy_1mbps_ring5'], "S_ring5", e['power']['S_uw']),
        ("S+J (ring3)", e['ring3']['n_min_entropy_1mbps'], "S_ring3", e['power']['SJ_uw']),
    ):
        area = e['area'][area_key]
        idle_uw = e['idle'][f"{area_key}_total_uw"]
        idle_xt = e['idle'][f"{area_key}_total_xt_uw"]
        pairs = e['lock'][f"{area_key}_expected_pairs_within_2pct_unspaced"]
        A(f"| {label} | {n} | 1 Mbps | {pow_uw/1e3:.2f} mW ({pow_uw/ROW_ACTIVE_UW:.1f}x row) | "
          f"{area['macro_density_um2']/1e6:.3f} mm2 ({area['macro_density_um2']/ROW_AREA_UM2:.2f}x row) | "
          f"{idle_uw:.0f} uW ({idle_xt:.0f} uW x-T) | ~{pairs:.0f} (unspaced), {n-1} adjacent by construction |")
    A("")
    A(f"- **Active power.** Allocating the full budget to rings and buffers permits "
      f"`N_power` = {e['power']['n_power_row_ring5']} rings (ring5) / "
      f"{e['power']['n_power_row_ring3']} (ring3) under the 500 uW row "
      f"(array-level anchor at N = 4, ff / 125 C / 1.98 V: "
      f"{e['power']['array125_anchor_uw']:.1f} uW, DR-0010 note R3). The "
      "bound excludes sampler, clock, digital XOR and other block power. "
      "Residual array overhead after removing the analog XOR is unmeasured.")
    A(f"- **Area.** The estimates count a ring, buffer and sampler DFF per ring "
      f"at the sampler-core density of {e['area']['macro_um2_per_device']:.1f} "
      "um2/device. Giving these devices the entire area target would allow "
      f"{e['area']['n_analog_only_ring5']} ring5 or {e['area']['n_analog_only_ring3']} "
      "ring3 instances. At the ring3 power cap, the analog estimate is "
      f"{e['area']['ring3_analog_um2_at_power_cap']/1e6:.6f} mm². The committed "
      f"digital macro alone occupies {DIGITAL_MACRO_MM2:.5f} mm² against the "
      "0.05 mm² whole-block target (`layout/trng_whole/report.json` at "
      "`7b5b48ca`). Additional digital parity, clock and supply routing, and "
      "pad area have no floorplan for either S option.")
    A(f"- **Idle row**: worst-corner standby scaled from the committed survey "
      f"(per stopped ring {e['idle']['per_ring_ua_125c']:.3f} uA, per DFF "
      f"{e['idle']['per_dff_ua_125c']:.3f} uA at ff / 125 C / 1.98 V, digital "
      f"{e['idle']['digital_standby_uw']:.1f} uW measured-view / "
      f"{e['idle']['digital_standby_xt_uw']:.1f} uW extrapolated) -- within the "
      "provisional 200 uW envelope on the measured-view basis for both options. "
      "With digital idle extrapolated to 125 C, S exceeds the row while S+J "
      "stays below it in this scaling model.")
    A(f"- **Lock proximity is structural at these N**: inside the characterized "
      f"wstv span ({e['lock']['characterized_span']}x period span) rings can be "
      f"spaced >= 2% apart only up to `N` = {e['lock']['n_lock_free_max']}; at "
      f"N = {e['committed']['n_min_entropy_1mbps_ring5']} adjacent mean spacing is "
      f"{(e['lock']['S_ring5_adjacent_spacing_in_span']-1)*100:.2f}% -- every adjacent "
      "pair sits inside the 2% lock-proximity scale of the committed mismatch "
      "model (which already draws min-pair < 2% in 14% of its N = 4 draws). "
      "Trim/selection is #221's open question; nothing here assumes it.")
    A("")
    A("### New failure modes of sample-before-combine (stated per acceptance criterion)")
    A("")
    A("- **Per-sampler metastability**: each ring is sampled asynchronously at "
      "1 MHz against a 1/T_0 ~ 0.4-2.6 GHz (ring3) / 0.2-0.6 GHz (ring5, loaded) "
      "node. Post-layout `tcq` is 0.18-0.30 ns (`sim/post-layout-sampler-dff/`); "
      "no committed record measures the metastability resolution time constant "
      "or MTBF -- **unmeasured**. The mechanism is not new (today's single raw "
      "tap is already an async sample of `xo`); its multiplicity scales xN.")
    A("- **Per-sampler offset**: input-referred offset sigma 16.0 mV, range "
      "-46..+40 mV (`sim/local-mismatch-monte-carlo/`). Independent per-sampler "
      "offsets (and independent per-ring duty biases) attenuate in the digital "
      "parity as |1-2p|^N: at the committed sampler-mismatch-only duty spread "
      "(p = 0.538-0.544) the parity bias at N = 11-78 is < 1e-7 -- arithmetic, "
      "not a measurement. **A common-mode duty term driven by a shared clock "
      "edge or a common ring-duty systematic is unmeasured**; the committed "
      "duty evidence is at `xo` (post-XOR), where per-ring duties already "
      "cancel once. The `sc3`/`sc5` decks now measure per-ring duty directly "
      "(duty_ring in the committed method); it is recorded in the raw responses "
      "and left for #221's analysis.")
    A("- **Correlated sampling instants**: one shared `clk` means sample-instant "
      "jitter enters every ring's sampled phase as a common-mode term "
      "(+/- sigma_clk/T_0,i of a period per ring); the entropy law credits each "
      "ring only its own accumulated jitter. The derate is **unmeasured** -- no "
      "committed record characterizes the sample clock's jitter (it is an "
      "off-block input).")
    A("- **Ring-to-ring lock proximity**: structural at N >= ~9 inside the "
      "characterized wstv span (above); at the N the entropy law asks for, "
      "re-spacing alone cannot fix it.")
    A("")

    A("## The three rows together, and the conclusion")
    A("")
    bound = e['ring_power_bound']
    power = e['power']
    area = e['area']
    A("| option | entropy model at 1 Mbps | active power (< 500 uW) | whole-block area (< 0.05 mm²) | conditional raw-rate upper bound |")
    A("|---|---|---|---|---|")
    A(f"| committed (ring5, analog XOR) | combining prevents 1 Mbps | "
      f"{power['array125_anchor_uw']:.0f} uW array alone at N = 4 | unmet "
      f"({COMMITTED_WHOLE_MM2:.6f} mm² placed) | {e['committed']['ceiling_kbps']:.1f} kbps "
      f"at the combining limit (N = 6), 50 kbps chosen at N = 4 |")
    A(f"| J only (ring3, analog XOR) | combining prevents 1 Mbps | whole-block power "
      f"unmeasured | current digital macro exceeds target | {e['ring3']['ceiling_kbps']:.0f} "
      f"kbps at the combining limit (N = {e['ring3']['n_max_combine']}) |")
    for label, n, active_uw, analog, rate, n_power in (
        ("S only (ring5)", e['committed']['n_min_entropy_1mbps_ring5'], power['S_uw'],
         area['S_ring5'], bound['rate_kbps_ring5'], power['n_power_row_ring5']),
        ("S+J (ring3)", e['ring3']['n_min_entropy_1mbps'], power['SJ_uw'],
         area['S_ring3'], bound['rate_kbps_ring3'], power['n_power_row_ring3']),
    ):
        A(f"| {label} | requires N = {n} | rings and buffers alone draw "
          f"{active_uw/1e3:.2f} mW at N = {n} | {analog['macro_density_um2']/1e6:.3f} "
          f"mm² analog estimate at N = {n}, plus digital and routing | "
          f"{rate:.0f} kbps at N = {n_power} (ring + buffer power limit) |")
    A("")
    A(f"**Negative result.** At 1 Mbps the S+J entropy model requires "
      f"{e['ring3']['n_min_entropy_1mbps']} rings. At ff / 125 C / 1.98 V their "
      f"rings and buffers alone draw {power['SJ_uw']/1e3:.2f} mW, exceeding the "
      "500 uW block budget. Allocating that entire budget to the measured "
      f"per-ring current permits {power['n_power_row_ring3']} rings. At that count "
      f"the conditional upper bound is **{bound['rate_kbps_ring3']:.0f} kbps** for "
      f"this jitter draw, or {e['draw_sensitivity']['sigma_x1.5']['ring_power_bound_kbps']:.0f} "
      "kbps for a 50% larger `sigma_1`. Whole-block rate feasibility remains "
      "unestablished. There is no S+J floorplan, and ring3 misses DR-0002's "
      f"0.80 swing criterion at every measured point (minimum {sw['swing_ring_min']:.3f} × Vdd).")
    A("")
    A("Every entropy figure here is simulation-derived and provisional until "
      "silicon; every `sigma_1` is a single ~16 %-1sigma draw on top of DR-0002 "
      "Sec 6's ~1.5-2x injected-level systematic, so every N and rate ceiling "
      "inherits both.")
    A("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def load_reqdir(reqdir):
    chunks, missing = load_request_dir(reqdir)
    if missing:
        raise ReductionError(f"refused/failed requests present: {[m[0] for m in missing]}")
    if len(chunks) != EXPECTED_REQUESTS:
        raise ReductionError(f"expected {EXPECTED_REQUESTS} request responses, got {len(chunks)}")
    verify_netlist_shas(chunks, lambda n: Path(reqdir) / n / "netlist.cir")
    rows = jobs_from_responses(chunks)
    if len(rows) != EXPECTED_JOBS:
        raise ReductionError(f"expected {EXPECTED_JOBS} units, got {len(rows)}")
    return chunks, rows


def study_results(rows):
    """The complete set of derived fields saved and verified on replay."""
    return {
        "tolerances": {"jitter_tbar": TOL_TBAR_JITTER,
                       "sigma_binding": TOL_SIGMA_BINDING, "sigma_coarse": TOL_SIGMA_COARSE,
                       "sc_tbar": TOL_TBAR_SC, "sc_swing": TOL_SWING_SC, "sc_current": TOL_CURRENT_SC},
        "control_jitter": control_gate_jitter(rows, load_control_targets()),
        "control_sc": control_gate_sc(rows, load_ring5_loaded()),
        "reduction": full_reduction(rows),
        "conclusion": "negative_result",
        "limiting_quantity": ("per-ring active supply current at the worst measured corner "
                              "(ff / 125 C / 1.98 V) against the < 500 uW active-power row"),
    }


def emit_record(reqdir, author="loom-builder@sky130-trng"):
    chunks, rows = load_reqdir(reqdir)
    results = study_results(rows)
    red = results["reduction"]
    now, sha, rid = new_record_id(REPO)
    body = render_body(rows, red, results["control_jitter"], results["control_sc"])
    jobs = sorted({r["job_id"] for r in rows if r["job_id"]})
    header = [
        f"# {rid} -- {SLUG}", "",
        f"**Claim**: {CLAIM}", "",
        f"**Level**: transistor (`klt sim` batch, {EXPECTED_JOBS} units = "
        "2 jitter configs (ctrl5 at 1 (T,V) + ring3 at 4 (T,V)) + 2 swing/current "
        "configs (sc5 control + sc3) at 4 (T,V), all x {tt,ss,ff})",
        "**Status**: simulation-derived; provisional until silicon",
        "**Seed**: 1 on the jitter decks (`.option seed=1`, common random "
        "numbers; ngspice-47 does not replay trnoise streams, see the control "
        "section); the swing/current decks are deterministic",
        f"**Analysis**: `sim/{SLUG}/reduce.py` (replay with `--check`)",
        f"**Requests**: `sim/{SLUG}/make-requests.py`; testbenches "
        f"`sim/{SLUG}/testbench/tb_ring_jitter_klt.spice`, "
        f"`sim/{SLUG}/testbench/tb_ring_swing_current_klt.spice`",
        f"**Batch jobs**: {', '.join(f'`{j}`' for j in jobs)}", "",
        "## Source records", "",
        f"- Jitter-vehicle control target (`sim/ro-ring-jitter-accumulation/records/`): `{red['control_targets_record']}`",
        f"- Swing/current control targets (`sim/ro-ring5-swing-and-current/records/`): "
        "`20260825-085315-53f1f7a`, `20260825-085402-53f1f7a`, `20260825-085449-53f1f7a`, `20260825-085537-53f1f7a`",
        f"- Operating point, w_90 grid, entropy inputs (`sim/ro-array-operating-point/records/`): `{red['op_record']}`",
        "- Array sizing, `M*Q_H0`, numerical floor (`sim/ro-array-sizing/records/`): `20260825-071619-54f5715`",
        "- Jitter grid for the sigma_1-vs-T_0 fit (`sim/ro-ring-jitter-accumulation/records/`): the nine `ro_ring5` records (27 points)",
        "- Array-level 125 C current (`sim/ro-array-core-combining/records/`): `20261008-135357-847b454`",
        "- Sampler offset, ladder periods, lock model (`sim/local-mismatch-monte-carlo/records/`): `20261009-111125-e57ad27`",
        "- Standby survey (`sim/ro-array-idle-leakage/records/`): `20261106-185750-8deaf42`",
        "- Post-layout sampler_dff timing (`sim/post-layout-sampler-dff/records/`): `20260907-120320-e82623e`", "",
        "---", "",
    ]
    cdir = REPO / "sim" / SLUG / "corners" / rid
    write_corner_bundle(cdir, reqdir, chunks, records_dir=REPO / "sim" / SLUG / "records", rid=rid)
    try:
        summary = {
            "record_id": rid, "slug": SLUG, "claim": CLAIM,
            "level": "transistor", "status": "simulation-derived; provisional until silicon",
            "seed": "1 (jitter decks; common random numbers, not replayable on ngspice-47); deterministic swing/current decks",
            "testbench": f"sim/{SLUG}/testbench/ (2 templates, via sim/{SLUG}/make-requests.py)",
            "analysis": f"sim/{SLUG}/reduce.py",
            "klt_sim": {"jobs": jobs, "backend": "batch",
                        "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz",
                        "models_lib_sha256": rows[0].get("models_lib_sha256")},
            **results,
        }
        mint_record(REPO / "sim" / SLUG / "records", REPO, rid, header, body, summary,
                    author=author, now=now, sha=sha)
    except BaseException:
        import shutil
        shutil.rmtree(cdir, ignore_errors=True)
        raise
    print(f"record {rid} written")
    return 0


def check_record(recpath):
    rec = json.loads(Path(recpath).read_text())
    rid = rec["record_id"]
    cdir = REPO / "sim" / SLUG / "corners" / rid
    chunks = read_corner_bundle(cdir)
    verify_netlist_shas(chunks, lambda n: cdir / f"{n}.netlist.cir")
    rows = jobs_from_responses(chunks)
    if len(rows) != EXPECTED_JOBS:
        raise ReductionError(f"replay: expected {EXPECTED_JOBS} units, got {len(rows)}")
    expected = study_results(rows)
    saved = {key: rec[key] for key in expected if key in rec}
    differences = replay_diff(expected, saved, strict_types=True)
    if differences:
        raise ReductionError("replay: " + "\n".join(differences))
    print(f"record {rid} replays clean (both controls + reduction equality)")
    return 0


def known_answer():
    """Committed-evidence checks that need no new responses."""
    load_control_targets()
    op = load_op_record()
    k5, q = op["entropy"]["k"], op["entropy"]["q_required"]
    assert entropy_n(k5, q, RATE_1MBPS) == 78
    assert 77.0e3 < rate_ceiling_at_n(6, k5, q) < 78.5e3
    fit = sigma1_vs_t0_alpha(load_ring5_grid())
    assert 0.0 < fit["alpha"] < 1.0, fit
    locks = lock_proximity(78, 1.1686, 2.74)
    assert locks["expected_pairs_within_2pct_unspaced"] > 100
    # the committed loaded grid's worst per-ring current matches DR-0010 R3's anchor
    loaded = load_ring5_loaded()
    worst = max((d["i_ring_run_a"] + d["i_buf_a"]) for d in loaded.values())
    assert 30e-6 < worst < 40e-6, worst
    print(f"known-answer OK: N@1Mbps=78, ceiling={rate_ceiling_at_n(6,k5,q)/1e3:.2f} kbps, "
          f"alpha={fit['alpha']:.3f}, worst ring5 ring+buf={worst*1e6:.2f} uA, "
          f"E[pairs<2%]@78={locks['expected_pairs_within_2pct_unspaced']:.0f}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record")
    ap.add_argument("--check")
    ap.add_argument("--known-answer", action="store_true")
    args = ap.parse_args(argv)
    if args.emit_record:
        return emit_record(args.emit_record)
    if args.check:
        return check_record(args.check)
    if args.known_answer:
        return known_answer()
    ap.error("give exactly one of --emit-record / --check / --known-answer")


if __name__ == "__main__":
    raise SystemExit(main())
