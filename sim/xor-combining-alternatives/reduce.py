#!/usr/bin/env python3
"""Reduction for the XOR combining-gate alternatives (issue #282).

    reduce.py --emit-record REQDIR   # REQDIR/<name>/{resp.json,plan.json,request.json,netlist.cir}
    reduce.py --check RECORD.json    # replay a record from its committed raw responses
    reduce.py --known-answer         # feed the COMMITTED baseline records through the reducer

Pure arithmetic over `klt sim` responses plus the committed baseline evidence;
it runs no simulator. It FAILS CLOSED: a missing grid point, a missing or
non-finite measurement, a failed unit, or a baseline control outside tolerance
raises `ReductionError` and no record is emitted.

Definitions (all inherited from the committed reduction,
sim/ro-array-operating-point/analysis/operating-point.py, which is imported,
not copied, for the w_90 interpolation rule and the committed-evidence loaders):

  w_90                  interpolated width where the fanout-1 swing crosses
                        0.90 x Vdd, from the pulse-width bench (component).
  T_0_loaded(point)     the period of ring 1 (wstv = 0.42, the reference ring
                        of sim/ro-ring5-swing-and-current/) measured INSIDE the
                        complete N = 4 array deck of that variant, i.e. with the
                        variant's own first-stage XOR input on its ro_buf. The
                        other three periods are recorded; they differ only by
                        the starve-device ladder.
  N_max_combine(point)  floor(T_0_loaded / (2 w_90)), minimised over the grid.
  N_min_entropy(T_s)    ceil(M Q_H0 / Q_ring(T_s)),
                        Q_ring(T_s) = sigma_1^2 T_s / T_0_loaded^3, with T_0_loaded
                        of the VARIANT at ss / -40 C / 1.62 V. sigma_1 and
                        M Q_H0 are DR-0002's (sim/ro-array-sizing/); they are
                        device-noise inputs of the ring, not of the XOR.
  highest raw rate      for integer N <= N_max_combine the smallest T_s with
                        N_min_entropy(T_s) <= N is M Q_H0 / (N k), k = sigma_1^2 /
                        T_0^3; the rate is 1 / T_s. It rises with N, so the
                        unconstrained answer is at N = N_max_combine; the
                        committed-N = 4 answer is reported separately.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import importlib.util
import json
import math
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SLUG = "xor-combining-alternatives"
sys.path.insert(0, str(REPO / "sim" / "bin"))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OP = _load(REPO / "sim" / "ro-array-operating-point" / "analysis" / "operating-point.py", "operating_point")
MR = _load(HERE / "make-requests.py", "xor_alt_make_requests")
from evidence_record import mint_record, new_record_id  # noqa: E402

TOL_W90 = 0.05            # baseline control vs committed w_90
TOL_T0 = 0.02             # baseline control vs committed loaded ring period
BINDING_KEY = (-40.0, 1.62, "ss")     # DR-0002/DR-0003 entropy-binding corner
COMMITTED_N = 4
EXPECTED_JOBS = 18
VARIANTS = ("base", "w2x")
GRID = [(t, v, c) for (t, v) in MR.PVT_POINTS for c in MR.PROCESSES]
RATE_TABLE_BPS = [1.0e7, 1.0e6, 1.0e5, 5.0e4, 1.0e4]
CLAIM = ("Complete-tree and component measurements of the committed minimum-width xor2 combining gate "
         "(baseline control) against one 2x-device-width variant, on DR-0003's nine-point PVT grid, "
         "reduced to per-point N_max_combine and the entropy-replayed raw-rate ceiling. Evidence for "
         "DR-0010's operator-owned rate decision; no target is amended.")


class ReductionError(Exception):
    """A fail-closed condition: the reduction refuses to produce a result."""


def key_of(t, v, c):
    return (round(float(t), 6), round(float(v), 6), c)


# ---------------------------------------------------------------------------
# one job (variant, T, Vdd, process) from raw klt-sim measurements
# ---------------------------------------------------------------------------
PW_NAMES = [f"{p}{i}" for i in range(1, 10) for p in ("vx", "vn")]
ARR_NAMES = (["t%d%s" % (r, s) for r in range(1, 5) for s in "ab"]
             + [n for n in ("vxo_max", "vxo_min", "vxo_avg", "vt1_avg", "txo_a", "txo_b", "tt1a", "tt1b",
                                      "i1", "i2", "i3", "i4", "ib", "qa", "qb", "qs")])


def _need(raw, names, ident):
    missing = [n for n in names if n not in raw or raw[n] is None]
    if missing:
        raise ReductionError(f"{ident}: missing measurement(s) {missing}")
    bad = [n for n in names if not math.isfinite(float(raw[n]))]
    if bad:
        raise ReductionError(f"{ident}: non-finite measurement(s) {bad}")


def derive_job(raw: dict, vdd: float, area_um2: float, ident: str = "job") -> dict:
    """Turn the raw measurements of one unit into the per-point record."""
    _need(raw, PW_NAMES + ARR_NAMES, ident)
    m = {}
    for w, i in zip(OP.WIDTHS_DESC, range(1, 10)):
        m[OP.SWING_KEY[w]] = (raw[f"vx{i}"] - raw[f"vn{i}"]) / vdd
    w90_ps = OP.interpolate_w90(m)
    if w90_ps is None:
        raise ReductionError(f"{ident}: w_90 not bracketed by the swept widths (swing never crosses 0.90)")
    tr = [(raw[f"t{r}b"] - raw[f"t{r}a"]) / 10 for r in range(1, 5)]
    if any(t <= 0 for t in tr):
        raise ReductionError(f"{ident}: non-positive ring period {tr}")
    f_ideal = sum(1 / t for t in tr)
    f_ideal2 = 1 / tr[0] + 1 / tr[1]
    f_xo = 48 / (raw["txo_b"] - raw["txo_a"])
    f_t1 = 48 / (raw["tt1b"] - raw["tt1a"])
    i_rings = -(raw["i1"] + raw["i2"] + raw["i3"] + raw["i4"])
    i_block = -raw["ib"]
    i_total = i_rings + i_block
    out = {
        "swing_by_width": {str(w): m[OP.SWING_KEY[w]] for w in OP.WIDTHS_DESC},
        "w90_ps": w90_ps,
        "ring_periods_ns": [t * 1e9 for t in tr],
        "t0_loaded_ns": tr[0] * 1e9,
        "swing_frac_xo": (raw["vxo_max"] - raw["vxo_min"]) / vdd,
        "edge_retention_n4": f_xo / f_ideal,
        "edge_retention_n2": f_t1 / f_ideal2,
        "bias_xo": raw["vxo_avg"] / vdd,
        "bias_t1": raw["vt1_avg"] / vdd,
        "i_rings_ua": i_rings * 1e6,
        "i_xor_buf_ua": i_block * 1e6,
        "i_total_ua": i_total * 1e6,
        "p_total_uw": i_total * vdd * 1e6,
        "xor_area_proxy_um2": area_um2,
        "c_in_first_stage_pin_a_ff": -raw["qa"] / vdd * 1e15,
        "c_in_first_stage_pin_b_ff": -raw["qb"] / vdd * 1e15,
        "c_in_root_sampler_ff": -raw["qs"] / vdd * 1e15,
    }
    for k in ("i_rings_ua", "i_xor_buf_ua", "i_total_ua", "p_total_uw", "c_in_first_stage_pin_a_ff",
              "c_in_first_stage_pin_b_ff", "c_in_root_sampler_ff", "swing_frac_xo", "edge_retention_n4"):
        if not math.isfinite(out[k]):
            raise ReductionError(f"{ident}: derived {k} is not finite")
    for k in ("c_in_first_stage_pin_a_ff", "c_in_first_stage_pin_b_ff", "c_in_root_sampler_ff"):
        if out[k] <= 0:
            raise ReductionError(f"{ident}: {k} = {out[k]:.4g} fF is not a positive capacitance")
    return out


# ---------------------------------------------------------------------------
# grid completeness and the baseline control
# ---------------------------------------------------------------------------
def check_grid(points: dict, what: str = "variant") -> None:
    """`points`: {(T, Vdd, corner): {...}}; require exactly the nine DR-0003 points."""
    have = {key_of(*k) for k in points}
    want = {key_of(*k) for k in GRID}
    if have != want:
        raise ReductionError(
            f"{what}: grid mismatch; missing {sorted(want - have)} unexpected {sorted(have - want)}")


def check_baseline(points: dict, ref_w90_s: dict, ref_t0_s: dict,
                   tol_w90: float = TOL_W90, tol_t0: float = TOL_T0) -> list[dict]:
    """Compare the baseline control with the committed evidence; raise if any point is out of tolerance.

    `points` carries `w90_ps` and `t0_loaded_ns`; `ref_*` are the committed values in seconds.
    """
    rows, bad = [], []
    for k in GRID:
        kk = key_of(*k)
        p = {key_of(*a): b for a, b in points.items()}.get(kk)
        r_w = {key_of(*a): b for a, b in ref_w90_s.items()}.get(kk)
        r_t = {key_of(*a): b for a, b in ref_t0_s.items()}.get(kk)
        if p is None or r_w is None or r_t is None:
            raise ReductionError(f"baseline control: no data for {kk} (point {p is not None}, "
                                 f"committed w90 {r_w is not None}, committed T0 {r_t is not None})")
        dw = p["w90_ps"] * 1e-12 / r_w - 1
        dt = p["t0_loaded_ns"] * 1e-9 / r_t - 1
        row = {"temp_c": kk[0], "vdd_v": kk[1], "corner": kk[2],
               "w90_ps": p["w90_ps"], "w90_committed_ps": r_w * 1e12, "w90_dev": dw,
               "t0_ns": p["t0_loaded_ns"], "t0_committed_ns": r_t * 1e9, "t0_dev": dt,
               "ok": abs(dw) <= tol_w90 and abs(dt) <= tol_t0}
        rows.append(row)
        if not row["ok"]:
            bad.append(row)
    if bad:
        msg = "; ".join(f"{b['corner']}/{b['temp_c']:g}C/{b['vdd_v']:g}V w90 {b['w90_dev']:+.2%} "
                        f"(tol {tol_w90:.0%}) T0 {b['t0_dev']:+.2%} (tol {tol_t0:.0%})" for b in bad)
        raise ReductionError(f"baseline control outside tolerance at {len(bad)} point(s): {msg}")
    return rows


# ---------------------------------------------------------------------------
# the rate reduction
# ---------------------------------------------------------------------------
def reduce_variant(points: dict, sigma1_s: float, q_required: float) -> dict:
    """Per-point N_max_combine, the binding point, and the entropy replay.

    `points`: {(T, Vdd, corner): {"w90_ps", "t0_loaded_ns"}}; every point is required.
    """
    check_grid(points)
    pts = {key_of(*k): v for k, v in points.items()}
    rows = []
    for k in GRID:
        t, v, c = key_of(*k)
        p = pts[(t, v, c)]
        w90 = p["w90_ps"] * 1e-12
        t0 = p["t0_loaded_ns"] * 1e-9
        if not (w90 > 0 and t0 > 0):
            raise ReductionError(f"non-positive w90/T0 at {(t, v, c)}")
        ratio = t0 / (2 * w90)
        rows.append({"temp_c": t, "vdd_v": v, "corner": c, "w90_ps": p["w90_ps"],
                     "t0_loaded_ns": p["t0_loaded_ns"], "n_max_combine_real": ratio,
                     "n_max_combine": math.floor(ratio)})
    worst = min(rows, key=lambda r: r["n_max_combine_real"])
    n_max = worst["n_max_combine"]
    bk = key_of(*BINDING_KEY)
    t0_bind = pts[bk]["t0_loaded_ns"] * 1e-9
    k = sigma1_s ** 2 / t0_bind ** 3
    entropy = {"binding_corner": {"temp_c": bk[0], "vdd_v": bk[1], "corner": bk[2]}, "sigma_1_s": sigma1_s,
               "t0_loaded_ns": pts[bk]["t0_loaded_ns"], "k_per_s": k, "q_required": q_required,
               "n_min_entropy_by_rate": []}
    for rate in RATE_TABLE_BPS:
        entropy["n_min_entropy_by_rate"].append(
            {"rate_bps": rate, "t_s_s": 1 / rate, "n_min_entropy": max(1, math.ceil(q_required / (k / rate)))})

    def at_n(n):
        t_s = q_required / (n * k)
        return {"n": n, "t_s_min_s": t_s, "rate_bps": 1 / t_s}

    result = {
        "rows": rows,
        "binding": worst,
        "n_max_combine": n_max,
        "n_max_combine_fastest_ring_info": None,
        "entropy": entropy,
        "ceiling_any_n": at_n(n_max) if n_max >= 1 else None,
        "committed_n4": dict(at_n(COMMITTED_N), clears_combining=(COMMITTED_N <= n_max)),
    }
    return result


# ---------------------------------------------------------------------------
# committed baseline fixtures (known-answer path)
# ---------------------------------------------------------------------------
def committed_baseline():
    """{(T,Vdd,corner): {"w90_ps","t0_loaded_ns"}} from the committed DR-0003 evidence, plus sizing inputs."""
    xor_pts = OP.load_xor_points()
    ring_pts = OP.load_ring5_points()
    sizing = OP.load_sizing()
    if not xor_pts or not ring_pts or sizing is None:
        raise ReductionError("committed baseline evidence not found")
    pts = {}
    for k in GRID:
        kk = key_of(*k)
        xk = {key_of(*a): b for a, b in xor_pts.items()}.get(kk)
        rk = {key_of(*a): b for a, b in ring_pts.items()}.get(kk)
        if xk is None or rk is None or xk["w90_s"] is None:
            raise ReductionError(f"committed baseline lacks {kk}")
        pts[kk] = {"w90_ps": xk["w90_s"] * 1e12, "t0_loaded_ns": rk["t0_loaded_s"] * 1e9}
    return pts, sizing["entropy_binding_corner"]["sigma_1_s"], sizing["q_required"], sizing


# ---------------------------------------------------------------------------
# klt-sim responses -> jobs
# ---------------------------------------------------------------------------
def corner_raw(corner: dict) -> dict:
    return {m["name"]: m["value"] for m in corner["measurements"]}


def jobs_from_responses(chunks):
    """chunks: [(name, plan, response)] -> {variant: {(T,V,c): derived}} plus job ids.

    Raises on any failed unit, wrong count, duplicate identity.
    """
    out = {v: {} for v in VARIANTS}
    jobs, remotes, seen = [], [], set()
    for name, plan, resp in chunks:
        variant, vdd, temp = plan["variant"], plan["vdd_v"], plan["temp_c"]
        if resp.get("status") != "pass" and resp.get("status") != "ok":
            bad = [c for c in resp.get("corners", []) if c.get("status") not in ("pass", "ok")]
            if bad or resp.get("status") in ("error", "fail"):
                raise ReductionError(f"{name}: klt sim status {resp.get('status')!r}, "
                                     f"{len(bad)} unit(s) not passing")
        rem = (resp.get("environment") or {}).get("remote")
        if not rem or not rem.get("job_id"):
            raise ReductionError(f"{name}: response has no environment.remote.job_id (not a batch run)")
        jobs.append(rem["job_id"])
        remotes.append(rem)
        for c in resp["corners"]:
            if c.get("status") not in ("pass", "ok"):
                raise ReductionError(f"{name}: unit {c.get('corner_id')} status {c.get('status')!r}")
            if abs(float(c["temperature_c"]) - temp) > 1e-9:
                raise ReductionError(f"{name}: unit temperature {c['temperature_c']} != plan {temp}")
            ident = f"{name}/{c['process']}"
            k = key_of(temp, vdd, c["process"])
            if (variant, k) in seen:
                raise ReductionError(f"{ident}: duplicate job identity")
            seen.add((variant, k))
            out[variant][k] = derive_job(corner_raw(c), vdd, plan["xor_area_proxy_um2"], ident)
    if len(seen) != EXPECTED_JOBS:
        raise ReductionError(f"expected {EXPECTED_JOBS} jobs, got {len(seen)}")
    for v in VARIANTS:
        check_grid(out[v], v)
    return out, jobs, remotes


def full_reduction(variants_pts: dict) -> dict:
    ref_w90 = {k: v["w90_s"] for k, v in OP.load_xor_points().items() if v["w90_s"] is not None}
    ref_t0 = {k: v["t0_loaded_s"] for k, v in OP.load_ring5_points().items()}
    sizing = OP.load_sizing()
    if sizing is None:
        raise ReductionError("sim/ro-array-sizing record not found")
    sigma1 = sizing["entropy_binding_corner"]["sigma_1_s"]
    q_req = sizing["q_required"]
    control = check_baseline(variants_pts["base"], ref_w90, ref_t0)
    res = {"baseline_control": {"tolerance_w90": TOL_W90, "tolerance_t0": TOL_T0, "rows": control, "ok": True},
           "sizing_record": sizing["record_id"], "variants": {}}
    for v in VARIANTS:
        r = reduce_variant(variants_pts[v], sigma1, q_req)
        fastest = min(min(p["ring_periods_ns"]) for p in variants_pts[v].values())
        # informational: the same bound using the fastest of the four rings at each point
        info = []
        for k, p in variants_pts[v].items():
            info.append(math.floor(min(p["ring_periods_ns"]) * 1e-9 / (2 * p["w90_ps"] * 1e-12)))
        r["n_max_combine_fastest_ring_info"] = min(info)
        r["fastest_ring_period_ns_anywhere"] = fastest
        res["variants"][v] = r
    return res


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def _fmt(x, nd=3):
    return f"{x:.{nd}f}"


def render_body(data: dict, red: dict, jobs: list[str]) -> str:
    L = []
    pv = data["variants"]
    L.append("## Baseline control (committed evidence reproduced)")
    L.append("")
    L.append(f"Tolerance: `w_90` within +-{TOL_W90:.0%} of `sim/xor-combining-bandwidth/`, loaded ring period "
             f"within +-{TOL_T0:.0%} of `sim/ro-ring5-swing-and-current/` (`tbar`), at every one of the nine points. "
             "The reduction fails closed outside either band.")
    L.append("")
    L.append("| T (C) | Vdd (V) | corner | `w_90` (ps) | committed | dev | `T_0` ring 1 (ns) | committed | dev |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in red["baseline_control"]["rows"]:
        L.append(f"| {r['temp_c']:g} | {r['vdd_v']:g} | `{r['corner']}` | {r['w90_ps']:.2f} | "
                 f"{r['w90_committed_ps']:.2f} | {r['w90_dev']:+.2%} | {r['t0_ns']:.4f} | "
                 f"{r['t0_committed_ns']:.4f} | {r['t0_dev']:+.2%} |")
    L.append("")
    for v, title in (("base", "Baseline (minimum-width xor2)"), ("w2x", "2x XOR device width")):
        L.append(f"## {title}: every grid point")
        L.append("")
        L.append("| T (C) | Vdd | corner | `w_90` (ps) | `T_0` rings 1..4 (ns) | xo swing / Vdd | retention N=4 | "
                 "DC xo/Vdd | I rings (uA) | I XOR+buf (uA) | I total (uA) | P (uW) | C_in pin a / b (fF) | "
                 "C_sampler (fF) | area proxy (um2) | `N_max_combine` |")
        L.append("|" + "---|" * 16)
        rows_by = {key_of(r["temp_c"], r["vdd_v"], r["corner"]): r for r in red["variants"][v]["rows"]}
        for k in GRID:
            kk = key_of(*k)
            p = pv[v][kk]
            nr = rows_by[kk]
            L.append(
                f"| {kk[0]:g} | {kk[1]:g} | `{kk[2]}` | {p['w90_ps']:.2f} | "
                + " / ".join(f"{x:.4f}" for x in p["ring_periods_ns"])
                + f" | {p['swing_frac_xo']:.3f} | {p['edge_retention_n4']:.3f} | {p['bias_xo']:.3f} | "
                f"{p['i_rings_ua']:.2f} | {p['i_xor_buf_ua']:.2f} | {p['i_total_ua']:.2f} | {p['p_total_uw']:.2f} | "
                f"{p['c_in_first_stage_pin_a_ff']:.3f} / {p['c_in_first_stage_pin_b_ff']:.3f} | "
                f"{p['c_in_root_sampler_ff']:.3f} | {p['xor_area_proxy_um2']:.3f} | "
                f"{nr['n_max_combine_real']:.3f} (floor **{nr['n_max_combine']}**) |")
        L.append("")
        r = red["variants"][v]
        b = r["binding"]
        L.append(f"**Binding point**: `N_max_combine = {r['n_max_combine']}` at "
                 f"{b['corner']} / {b['temp_c']:g} C / {b['vdd_v']:g} V "
                 f"(`w_90` {b['w90_ps']:.2f} ps, `T_0` {b['t0_loaded_ns']:.4f} ns). Informational, using the "
                 f"fastest of the four rings at each point instead of ring 1: `{r['n_max_combine_fastest_ring_info']}`.")
        e = r["entropy"]
        L.append("")
        L.append(f"Entropy replay at {e['binding_corner']['corner']} / {e['binding_corner']['temp_c']:g} C / "
                 f"{e['binding_corner']['vdd_v']:g} V with this variant's loaded `T_0` = {e['t0_loaded_ns']:.4f} ns "
                 f"(`sigma_1` = {e['sigma_1_s']*1e12:.4f} ps, `M*Q_H0` = {e['q_required']:.4g}):")
        L.append("")
        L.append("| raw rate | `T_s` (us) | `N_min_entropy` |")
        L.append("|---|---|---|")
        for x in e["n_min_entropy_by_rate"]:
            L.append(f"| {x['rate_bps']:.3g} bps | {x['t_s_s']*1e6:.3f} | {x['n_min_entropy']} |")
        L.append("")
        c = r["ceiling_any_n"]
        n4 = r["committed_n4"]
        if c:
            L.append(f"- **Highest raw rate at any integer `N`** (`N = {c['n']}`): `T_s` >= {c['t_s_min_s']*1e6:.3f} us, "
                     f"**{c['rate_bps']/1e3:.2f} kbps**.")
        L.append(f"- **Constrained to the committed `N = 4`**: `T_s` >= {n4['t_s_min_s']*1e6:.3f} us, "
                 f"**{n4['rate_bps']/1e3:.2f} kbps** (clears the combining bound: {n4['clears_combining']}).")
        L.append("")
    # comparison
    L.append("## Variant comparison (2x relative to baseline)")
    L.append("")
    L.append("| layer | quantity | baseline | 2x | change |")
    L.append("|---|---|---|---|---|")
    rb, rw = red["variants"]["base"], red["variants"]["w2x"]
    L.append(f"| single-gate pulse resolution | worst-case `w_90` (ps) | "
             f"{max(p['w90_ps'] for p in pv['base'].values()):.2f} | "
             f"{max(p['w90_ps'] for p in pv['w2x'].values()):.2f} | |")
    bk = key_of(-40, 1.98, "ff")
    L.append(f"| single-gate pulse resolution | `w_90` at ff/-40C/1.98V (ps) | {pv['base'][bk]['w90_ps']:.2f} | "
             f"{pv['w2x'][bk]['w90_ps']:.2f} | {pv['w2x'][bk]['w90_ps']/pv['base'][bk]['w90_ps']-1:+.1%} |")
    L.append(f"| upstream ring-driver loading | `T_0` ring 1 at ff/-40C/1.98V (ns) | {pv['base'][bk]['t0_loaded_ns']:.4f} | "
             f"{pv['w2x'][bk]['t0_loaded_ns']:.4f} | {pv['w2x'][bk]['t0_loaded_ns']/pv['base'][bk]['t0_loaded_ns']-1:+.1%} |")
    L.append(f"| upstream ring-driver loading | `T_0` ring 1 at ss/-40C/1.62V (ns) | "
             f"{pv['base'][key_of(*BINDING_KEY)]['t0_loaded_ns']:.4f} | {pv['w2x'][key_of(*BINDING_KEY)]['t0_loaded_ns']:.4f} | "
             f"{pv['w2x'][key_of(*BINDING_KEY)]['t0_loaded_ns']/pv['base'][key_of(*BINDING_KEY)]['t0_loaded_ns']-1:+.1%} |")
    for pin in ("a", "b"):
        f = f"c_in_first_stage_pin_{pin}_ff"
        L.append(f"| upstream ring-driver loading | first-stage input pin {pin}, mean over grid (fF) | "
                 f"{_mean(pv['base'], f):.3f} | {_mean(pv['w2x'], f):.3f} | {_mean(pv['w2x'], f)/_mean(pv['base'], f)-1:+.1%} |")
    L.append(f"| complete-tree behaviour | min edge retention N=4 over grid | "
             f"{min(p['edge_retention_n4'] for p in pv['base'].values()):.3f} | "
             f"{min(p['edge_retention_n4'] for p in pv['w2x'].values()):.3f} | |")
    L.append(f"| complete-tree behaviour | `N_max_combine` (binding) | {rb['n_max_combine']} | {rw['n_max_combine']} | |")
    L.append(f"| complete-tree behaviour | total active power, mean over grid (uW) | {_mean(pv['base'], 'p_total_uw'):.2f} | "
             f"{_mean(pv['w2x'], 'p_total_uw'):.2f} | {_mean(pv['w2x'], 'p_total_uw')/_mean(pv['base'], 'p_total_uw')-1:+.1%} |")
    L.append(f"| device area (proxy, not layout) | three xor2 W x L x mult (um2) | "
             f"{next(iter(pv['base'].values()))['xor_area_proxy_um2']:.3f} | "
             f"{next(iter(pv['w2x'].values()))['xor_area_proxy_um2']:.3f} | +100% |")
    L.append(f"| downstream sampler loading | `sampler_dff` D input, mean over grid (fF), unchanged cell | "
             f"{_mean(pv['base'], 'c_in_root_sampler_ff'):.3f} | {_mean(pv['w2x'], 'c_in_root_sampler_ff'):.3f} | |")
    cb, cw = rb["ceiling_any_n"], rw["ceiling_any_n"]
    L.append(f"| rate | highest raw rate, any integer `N` (kbps) | {cb['rate_bps']/1e3:.2f} | {cw['rate_bps']/1e3:.2f} | "
             f"{cw['rate_bps']/cb['rate_bps']-1:+.1%} |" if cb and cw else "| rate | (no integer N clears) | | | |")
    L.append(f"| rate | rate at the committed `N = 4` (kbps) | {rb['committed_n4']['rate_bps']/1e3:.2f} | "
             f"{rw['committed_n4']['rate_bps']/1e3:.2f} | "
             f"{rw['committed_n4']['rate_bps']/rb['committed_n4']['rate_bps']-1:+.1%} |")
    L.append("")
    L.append("Layers: the single-gate `w_90` is a fanout-1 component measurement (optimistic 8 ps input edges); upstream "
             "loading is what each `ro_buf` sees from its first-stage XOR input and shows up as the shift in the "
             "in-array ring period; complete-tree behaviour is measured on the full `N = 4` array deck; the sampler "
             "load is the unchanged `sampler_dff` D input on `xo`, reported separately and never added to the "
             "first-stage load. Capacitances are effective switched capacitances (`-integral(i dt) / Vdd` over a "
             "0 -> Vdd ramp, other XOR pin low, output driving one further `xor2`; sampler clk low = transparent).")
    L.append("")
    L.append("This record is evidence for DR-0010's operator-owned rate row. It does not amend any target and does "
             "not change DR-0010's Proposed status.")
    L.append("")
    return "\n".join(L) + "\n"


def _mean(pts, f):
    v = [p[f] for p in pts.values()]
    return sum(v) / len(v)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def load_reqdir(reqdir):
    chunks = []
    for d in sorted(glob.glob(os.path.join(reqdir, "*", "resp.json"))):
        dd = os.path.dirname(d)
        plan = json.load(open(os.path.join(dd, "plan.json")))
        resp = json.load(open(d))
        chunks.append((plan["name"], plan, resp))
    if len(chunks) != 6:
        raise ReductionError(f"expected 6 requests under {reqdir}, found {len(chunks)}")
    return chunks


def _data_from_points(pts):
    return {"variants": pts}


def emit_record(reqdir, author="loom-builder@sky130-trng"):
    chunks = load_reqdir(reqdir)
    pts, jobs, remotes = jobs_from_responses(chunks)
    red = full_reduction(pts)
    now, sha, rid = new_record_id(REPO)
    body = render_body({"variants": {v: {key_of(*k): p for k, p in pts[v].items()} for v in VARIANTS}}, red, jobs)
    src_x = sorted({d["record_id"] for d in OP.load_xor_points().values()})
    src_r = sorted({d["record_id"] for d in OP.load_ring5_points().values()})
    header = [
        f"# {rid} -- {SLUG}", "",
        f"**Claim**: {CLAIM}", "",
        "**Level**: transistor (`klt sim` batch, 18 units = 2 variants x 9 PVT points)",
        "**Status**: simulation-derived; provisional until silicon",
        "**Seed**: N/A (deterministic transients, no injected noise)",
        f"**Analysis**: `sim/{SLUG}/reduce.py` (replay with `--check`)",
        f"**Requests**: `sim/{SLUG}/make-requests.py`; testbench `sim/{SLUG}/testbench/tb_xor_alternatives.spice`",
        f"**Batch jobs**: {', '.join(f'`{j}`' for j in jobs)}", "",
        "## Source records for the baseline control", "",
        "Committed `w_90` (`sim/xor-combining-bandwidth/records/`): " + ", ".join(f"`{x}`" for x in src_x), "",
        "Committed loaded period (`sim/ro-ring5-swing-and-current/records/`): " + ", ".join(f"`{x}`" for x in src_r), "",
        f"Entropy-sizing inputs (`sim/ro-array-sizing/records/`): `{red['sizing_record']}`", "", "---", "",
    ]
    cdir = REPO / "sim" / SLUG / "corners" / rid
    if cdir.exists():
        raise ReductionError(f"{cdir} exists")
    cdir.mkdir(parents=True)
    try:
        for name, plan, resp in chunks:
            with gzip.open(cdir / f"{name}.klt-sim.json.gz", "wt") as fh:
                json.dump(resp, fh, indent=1)
            json.dump(plan, open(cdir / f"{name}.plan.json", "w"), indent=1)
            for src, dst in (("request.json", f"{name}.request.json"), ("netlist.cir", f"{name}.netlist.cir")):
                shutil.copyfile(os.path.join(reqdir, name, src), cdir / dst)
        summary = {
            "record_id": rid, "slug": SLUG, "claim": CLAIM, "level": "transistor",
            "status": "simulation-derived; provisional until silicon",
            "seed": "N/A (deterministic transient, no injected noise)",
            "testbench": f"sim/{SLUG}/testbench/tb_xor_alternatives.spice (via sim/{SLUG}/make-requests.py)",
            "analysis": f"sim/{SLUG}/reduce.py",
            "klt_sim": {"jobs": jobs, "backend": "batch", "remote": remotes,
                        "submitter_klt": chunks[0][2].get("provenance", {}).get("klt_version"),
                        "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"},
            "tolerances": {"w90": TOL_W90, "t0": TOL_T0},
            "points": {v: [dict(temp_c=k[0], vdd_v=k[1], corner=k[2], **p) for k, p in pts[v].items()] for v in VARIANTS},
            "reduction": json.loads(json.dumps(red, default=str)),
            "supersedes": "(none)", "author": author, "timestamp_utc": now.isoformat(), "repo_sha": sha,
        }
        out = mint_record(REPO / "sim" / SLUG / "records", REPO, rid, header, body, summary,
                          author=author, now=now, sha=sha)
        if out is None:
            raise ReductionError("record id collision")
    except BaseException:
        shutil.rmtree(cdir, ignore_errors=True)
        raise
    print(rid)
    return rid


def check(recpath):
    rec = json.load(open(recpath))
    cdir = REPO / "sim" / SLUG / "corners" / rec["record_id"]
    chunks = []
    for f in sorted(glob.glob(str(cdir / "*.klt-sim.json.gz"))):
        nm = os.path.basename(f)[:-len(".klt-sim.json.gz")]
        with gzip.open(f, "rt") as fh:
            chunks.append((nm, json.load(open(cdir / f"{nm}.plan.json")), json.load(fh)))
    pts, _jobs, _rem = jobs_from_responses(chunks)
    red = full_reduction(pts)
    same = (json.loads(json.dumps(red, default=str)) == rec["reduction"]
            and json.loads(json.dumps({v: [dict(temp_c=k[0], vdd_v=k[1], corner=k[2], **p) for k, p in pts[v].items()]
                                       for v in VARIANTS}, default=str)) == rec["points"])
    print("replay", "MATCHES" if same else "DIFFERS", recpath)
    return 0 if same else 1


def known_answer():
    pts, sigma1, q_req, _s = committed_baseline()
    r = reduce_variant(pts, sigma1, q_req)
    print(f"committed baseline: N_max_combine = {r['n_max_combine']} at "
          f"{r['binding']['corner']}/{r['binding']['temp_c']:g}C/{r['binding']['vdd_v']:g}V; "
          f"ceiling {r['ceiling_any_n']['rate_bps']/1e3:.2f} kbps; N=4 {r['committed_n4']['rate_bps']/1e3:.2f} kbps")
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", metavar="REQDIR")
    ap.add_argument("--check", metavar="RECORD")
    ap.add_argument("--known-answer", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.known_answer:
            known_answer()
        elif a.emit_record:
            emit_record(a.emit_record)
        elif a.check:
            return check(a.check)
        else:
            ap.print_help()
            return 2
    except ReductionError as e:
        print(f"FAIL-CLOSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
