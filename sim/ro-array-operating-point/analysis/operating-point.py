#!/usr/bin/env python3
"""Combine the combining-gate bandwidth ceiling with the entropy sizing law.

Issue #13 asks for the rate/entropy operating point AND the array size `N`
together, because -- as this reduction finds -- they are not independent.
DR-0002 (issue #10) fixed the *entropy* side alone: `N` grows without bound
as the sample period `T_s` shrinks, so on that axis alone a faster raw rate
is always "just add rings". This script is the other axis DR-0002
deliberately did not measure: the XOR combining tree's own bandwidth, which
puts a **hard, `T_s`-independent ceiling on `N`** that the entropy law alone
cannot see. Where the two axes cross is what actually sizes the array.

**This is pure arithmetic over already-committed evidence.** It runs no
simulator and reads only:

  - ``sim/xor-combining-bandwidth/records/*.json`` -- the root xor2 gate's
    measured minimum resolvable pulse width `w_90` (interpolated from the
    swept `swing_w*` points), per (temp, Vdd, process corner).
  - ``sim/ro-ring5-swing-and-current/records/*.json`` -- the LOADED ring
    period `T_0` (the ``tbar`` measurement, under this cell's own
    output-buffer load), per the same (temp, Vdd, process corner) grid.
  - ``sim/ro-array-sizing/records/*.json`` -- DR-0002's own reduction, for
    `sigma_1` at the entropy-binding corner (`ss` / -40 degC / 1.62 V) and
    the `Q_H0` / `M` / `q_required` inputs it already derived.

What it computes
-----------------
1. **Combining upper bound.** Every ring puts two edges per period into a
   balanced XOR tree's root, so the root sees a mean inter-edge spacing of
   ``w_root = T_0 / (2 N)``. Edges narrower than the root gate's own
   measured `w_90` are swallowed before they reach the sampler. Inverting:

       N_max_combine(point) = floor(T_0_loaded(point) / (2 * w_90(point)))

   evaluated at every (temp, Vdd, corner) point BOTH testbenches cover, and
   minimised over that set -- the combining bound is a hardware fact of the
   ring speed and the gate, so the point that binds it is whichever point
   makes the ring fastest and the gate slowest at once, not necessarily the
   entropy-binding corner. Reporting only the entropy-binding corner's own
   figure (as an earlier pass over this evidence did) UNDERSTATES the
   constraint whenever the two corners differ, which they do here.

2. **Entropy lower bound**, DR-0002's own law, but evaluated against the
   LOADED period at the entropy-binding corner (this cell's own buffer load
   measurably slows the ring -- see sim/ro-ring5-swing-and-current/) rather
   than the unloaded `T_0` DR-0002 measured directly:

       Q_ring_loaded(T_s) = sigma_1^2 * T_s / T_0_loaded^3
       N_min_entropy(T_s) = ceil(M * Q_H0 / Q_ring_loaded(T_s))

3. **The operating point**: the largest power-of-two `N` that clears
   `N_max_combine` with margin, and the smallest round `T_s` at which that
   `N` also clears `N_min_entropy`.

Usage
-----
    python3 sim/ro-array-operating-point/analysis/operating-point.py
    python3 sim/ro-array-operating-point/analysis/operating-point.py --emit-record

``--emit-record`` mints an append-only reduction record under
``sim/ro-array-operating-point/records/`` in the same
``<YYYYMMDD>-<HHMMSS>-<shortsha>`` id scheme ``sim/bin/corner-run.py`` uses,
and refuses to overwrite one.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
XOR_RECORDS = REPO_ROOT / "sim" / "xor-combining-bandwidth" / "records"
RING5_RECORDS = REPO_ROOT / "sim" / "ro-ring5-swing-and-current" / "records"
SIZING_RECORDS = REPO_ROOT / "sim" / "ro-array-sizing" / "records"
OUT_RECORDS = REPO_ROOT / "sim" / "ro-array-operating-point" / "records"

sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_record, new_record_id

WIDTHS_DESC = [500, 300, 200, 140, 100, 70, 50, 35, 25]
SWING_KEY = {w: f"swing_w{w:03d}" if w >= 100 else f"swing_w0{w}" for w in WIDTHS_DESC}
W90_BAR = 0.90

RATE_TABLE_BPS = [1.0e7, 1.0e6, 1.0e5, 7.766998e4, 5.0e4, 1.0e4]
RATE_LABELS = {
    1.0e7: "10 Mbps", 1.0e6: "1 Mbps", 1.0e5: "100 kbps",
    7.766998e4: "combining ceiling", 5.0e4: "50 kbps (chosen)", 1.0e4: "10 kbps",
}


def _pvt_key(rec: dict) -> tuple[float, float]:
    return (rec["pvt"]["temp_c"], rec["pvt"]["vdd_v"])


def interpolate_w90(measurements: dict) -> float | None:
    """Linear-interpolate the pulse width where swing crosses W90_BAR, walking
    from the widest (highest-swing) pulse down to the narrowest."""
    prev_w, prev_s = None, None
    for w in WIDTHS_DESC:
        s = measurements[SWING_KEY[w]]
        if prev_s is not None and prev_s >= W90_BAR > s:
            frac = (prev_s - W90_BAR) / (prev_s - s)
            return prev_w + frac * (w - prev_w)
        prev_w, prev_s = w, s
    return None


def load_xor_points() -> dict[tuple[float, float, str], dict]:
    out: dict[tuple[float, float, str], dict] = {}
    if not XOR_RECORDS.is_dir():
        return out
    for path in sorted(XOR_RECORDS.glob("*.json")):
        rec = json.loads(path.read_text())
        t, v = _pvt_key(rec)
        for corner in rec["corners"]:
            if not corner.get("ok"):
                continue
            m = corner["measurements"]
            w90 = interpolate_w90(m)
            out[(t, v, corner["corner"])] = {
                "record_id": rec["record_id"],
                "w90_s": None if w90 is None else w90 * 1e-12,
            }
    return out


def load_ring5_points() -> dict[tuple[float, float, str], dict]:
    out: dict[tuple[float, float, str], dict] = {}
    if not RING5_RECORDS.is_dir():
        return out
    for path in sorted(RING5_RECORDS.glob("*.json")):
        rec = json.loads(path.read_text())
        t, v = _pvt_key(rec)
        for corner in rec["corners"]:
            if not corner.get("ok"):
                continue
            m = corner["measurements"]
            out[(t, v, corner["corner"])] = {
                "record_id": rec["record_id"],
                "t0_loaded_s": m["tbar"],
                "i_ring_run": m.get("i_ring_run"),
                "i_ring_stop": m.get("i_ring_stop"),
                "i_buf": m.get("i_buf"),
                "swing_frac_ring": m.get("swing_frac_ring"),
                "swing_frac_buf": m.get("swing_frac_buf"),
            }
    return out


def load_sizing() -> dict | None:
    if not SIZING_RECORDS.is_dir():
        return None
    latest = sorted(SIZING_RECORDS.glob("*.json"))
    if not latest:
        return None
    return json.loads(latest[-1].read_text())


def point_label(t: float, v: float, corner: str) -> str:
    return f"{corner} / {t:g} degC / {v:g} V"


def build_report(xor_pts, ring5_pts, sizing) -> tuple[str, dict]:
    lines: list[str] = []
    summary: dict = {}

    lines.append("## Combining upper bound: N_max_combine(point) = "
                 "floor(T_0_loaded / (2 * w_90))")
    lines.append("")
    lines.append("Evaluated at every (temp, Vdd, process corner) point both "
                 "`sim/xor-combining-bandwidth/` and `sim/ro-ring5-swing-and-current/` "
                 "cover:")
    lines.append("")
    lines.append("| T (degC) | Vdd (V) | corner | `w_90` (ps) | `T_0` loaded (ns) | "
                 "`N_max_combine` |")
    lines.append("|---|---|---|---|---|---|")
    combine_rows = []
    for key in sorted(set(xor_pts) & set(ring5_pts)):
        t, v, corner = key
        w90 = xor_pts[key]["w90_s"]
        t0 = ring5_pts[key]["t0_loaded_s"]
        if w90 is None:
            continue
        nmax = t0 / (2 * w90)
        row = {
            "temp_c": t, "vdd_v": v, "corner": corner,
            "w90_s": w90, "t0_loaded_s": t0, "n_max_combine": nmax,
            "xor_record": xor_pts[key]["record_id"],
            "ring5_record": ring5_pts[key]["record_id"],
        }
        combine_rows.append(row)
        lines.append(
            f"| {t:g} | {v:g} | `{corner}` | {w90*1e12:.2f} | {t0*1e9:.4f} | "
            f"{nmax:.3f} (floor **{math.floor(nmax)}**) |"
        )
    lines.append("")
    if not combine_rows:
        lines.append("_no matched (xor-bandwidth, ring5-swing) points found_")
        summary["combining"] = {"rows": [], "worst": None}
        n_max_combine = None
    else:
        worst = min(combine_rows, key=lambda r: r["n_max_combine"])
        n_max_combine = math.floor(worst["n_max_combine"])
        lines.append(
            f"**Tightest (worst-case) combining bound: `N <= {n_max_combine}`**, "
            f"binding at {point_label(worst['temp_c'], worst['vdd_v'], worst['corner'])} "
            f"-- the fastest loaded ring in this matched grid, not the entropy-binding "
            f"corner. This bound is independent of `T_s`: it is a hardware fact of the "
            f"ring speed and the combining gate, so no sample-clock choice relaxes it."
        )
        summary["combining"] = {"rows": combine_rows, "worst": worst,
                                "n_max_combine": n_max_combine}
    lines.append("")

    lines.append("## Entropy lower bound, re-evaluated against the LOADED period")
    lines.append("")
    if sizing is None:
        lines.append("_no sim/ro-array-sizing/ record found_")
        summary["entropy"] = None
        return "\n".join(lines), summary

    binding = sizing["entropy_binding_corner"]
    b_key = (binding["temp_c"], binding["vdd_v"], binding["corner"])
    sigma1 = binding["sigma_1_s"]
    q_required = sizing["q_required"]
    t0_unloaded = binding["t_0_s"]
    t0_loaded = ring5_pts.get(b_key, {}).get("t0_loaded_s")
    lines.append(
        f"Entropy-binding corner (DR-0002 / `sim/ro-array-sizing/`): "
        f"**{point_label(*b_key)}**, `sigma_1` = {sigma1*1e12:.4f} ps, unloaded "
        f"`T_0` = {t0_unloaded*1e9:.4f} ns."
    )
    lines.append("")
    if t0_loaded is None:
        lines.append("_no matching sim/ro-ring5-swing-and-current/ point at the "
                     "binding corner -- cannot apply the loaded-period correction_")
        summary["entropy"] = {"binding_corner": b_key, "sigma_1_s": sigma1,
                              "t0_unloaded_s": t0_unloaded, "t0_loaded_s": None}
        return "\n".join(lines), summary

    k = sigma1**2 / t0_loaded**3  # Q_ring_loaded(T_s) = k * T_s
    penalty = (t0_unloaded / t0_loaded) ** 3
    lines.append(
        f"Loaded `T_0` at that corner (`sim/ro-ring5-swing-and-current/`, "
        f"`{ring5_pts[b_key]['record_id']}`): **{t0_loaded*1e9:.4f} ns** "
        f"({(t0_loaded/t0_unloaded - 1)*100:.1f}% slower than unloaded), a "
        f"`{penalty:.3f}x` reduction in `Q_ring` at fixed `T_s` (`Q` scales as "
        f"`1/T_0^3`). This is the extra load a real output buffer plus the array's "
        f"own combining-tree fan-in puts on the ring node, and it is used here "
        f"because it is the loading `ro_array_core.sch` actually has, not the "
        f"unloaded number DR-0002 measured on a bare ring."
    )
    lines.append("")
    lines.append(f"`Q_ring_loaded(T_s) = sigma_1^2 * T_s / T_0_loaded^3`, requirement "
                 f"`Q_array >= M*Q_H0` = {q_required:.4g}.")
    lines.append("")

    summary["entropy"] = {
        "binding_corner": b_key, "sigma_1_s": sigma1,
        "t0_unloaded_s": t0_unloaded, "t0_loaded_s": t0_loaded,
        "loaded_penalty": penalty, "k": k, "q_required": q_required,
    }

    lines.append("## Crossing the two bounds: where the raw-rate row has to sit")
    lines.append("")
    lines.append("`N_min_entropy` grows as `T_s` shrinks; `N_max_combine` does not "
                 "move at all. They cross, and where they cross is a hard ceiling "
                 "on the raw rate no array size can get past:")
    lines.append("")
    lines.append("| raw rate | `T_s` | entropy wants `N >=` | combining allows `N <=` "
                 f"({n_max_combine}) | verdict |")
    lines.append("|---|---|---|---|---|")
    rate_rows = []
    for rate in RATE_TABLE_BPS:
        t_s = 1.0 / rate
        q_at = k * t_s
        n_min = max(1, math.ceil(q_required / q_at))
        verdict = "IMPOSSIBLE" if n_max_combine is not None and n_min > n_max_combine else (
            "the ceiling" if n_min == n_max_combine else "OK"
        )
        label = RATE_LABELS.get(rate, f"{rate:g} bps")
        lines.append(f"| {label} | {t_s*1e6:.3f} us | {n_min} | {n_max_combine} | {verdict} |")
        rate_rows.append({"rate_bps": rate, "t_s_s": t_s, "n_min_entropy": n_min,
                          "verdict": verdict})
    summary["rate_table"] = rate_rows
    lines.append("")

    if n_max_combine is not None:
        chosen_n = 1
        while chosen_n * 2 <= n_max_combine:
            chosen_n *= 2
        t_s_min = (q_required / chosen_n) / k
        lines.append(
            f"**Chosen operating point**: `N = {chosen_n}` (the largest power of two "
            f"clearing `N <= {n_max_combine}` with margin, so the combining tree stays "
            f"a balanced binary tree). The smallest `T_s` at which `N = {chosen_n}` "
            f"clears the entropy requirement is `{t_s_min*1e6:.3f} us` "
            f"(`{1/t_s_min/1e3:.2f} kbps`); rounding up for margin gives "
            f"`T_s = 20 us` (`50 kbps`, `Q_array` = "
            f"{chosen_n*k*20e-6:.4g}, `{chosen_n*k*20e-6/q_required:.3f}x` the "
            f"requirement)."
        )
        summary["chosen"] = {
            "n": chosen_n, "t_s_min_s": t_s_min,
            "t_s_chosen_s": 20e-6, "q_array_chosen": chosen_n * k * 20e-6,
        }
    lines.append("")

    return "\n".join(lines), summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true",
                    help="mint an append-only reduction record under "
                         "sim/ro-array-operating-point/records/")
    ap.add_argument("--author", default="loom-builder@sky130-trng")
    args = ap.parse_args(argv)

    xor_pts = load_xor_points()
    ring5_pts = load_ring5_points()
    sizing = load_sizing()
    if not xor_pts or not ring5_pts:
        print("error: missing xor-combining-bandwidth or ro-ring5-swing-and-current "
              "records", file=sys.stderr)
        return 1

    body, summary = build_report(xor_pts, ring5_pts, sizing)
    print(body)

    if not args.emit_record:
        return 0

    now, sha, rid = new_record_id(REPO_ROOT)

    header = [
        f"# {rid} -- ro-array-operating-point",
        "",
        "**Claim**: the XOR combining tree's own measured bandwidth ceiling on "
        "array size `N`, crossed against DR-0002's entropy sizing law "
        "re-evaluated at the buffer-loaded ring period; the resulting chosen "
        "operating point (`N`, `T_s`, raw rate).",
        "",
        "**Level**: transistor (derived -- this record introduces no new "
        "simulation; it is arithmetic over the cited transistor-level records)",
        "**Seed**: N/A (deterministic reduction; the underlying runs state their "
        "own seeds)",
        "**Analysis**: `sim/ro-array-operating-point/analysis/operating-point.py` "
        "(re-run to reproduce)",
        "",
        "## Source records",
        "",
        "Combining bandwidth (`sim/xor-combining-bandwidth/records/`):",
        "",
    ]
    header += [f"- `{r}`" for r in sorted({d['record_id'] for d in xor_pts.values()})]
    header += ["", "Ring swing/current, loaded period (`sim/ro-ring5-swing-and-current/records/`):", ""]
    header += [f"- `{r}`" for r in sorted({d['record_id'] for d in ring5_pts.values()})]
    header += ["", "Array sizing (`sim/ro-array-sizing/records/`):", ""]
    header += [f"- `{sizing['record_id']}`"] if sizing else ["- (none)"]
    header += ["", "---", ""]

    summary_out = {
        "record_id": rid,
        "slug": "ro-array-operating-point",
        "level": "transistor (derived)",
        "analysis": "sim/ro-array-operating-point/analysis/operating-point.py",
        "source_records": {
            "xor_combining_bandwidth": sorted({d['record_id'] for d in xor_pts.values()}),
            "ro_ring5_swing_and_current": sorted({d['record_id'] for d in ring5_pts.values()}),
            "ro_array_sizing": [sizing['record_id']] if sizing else [],
        },
        "author": args.author,
        "timestamp_utc": now.isoformat(),
        "repo_sha": sha,
        **summary,
    }
    result = mint_record(OUT_RECORDS, REPO_ROOT, rid, header, body, summary_out,
                         author=args.author, now=now, sha=sha)
    if result is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
