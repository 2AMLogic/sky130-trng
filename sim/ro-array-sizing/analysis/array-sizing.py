#!/usr/bin/env python3
"""Reduce the measured ring jitter grid to Q, find the entropy-binding corner, size N.

This is issue #10's acceptance criteria 3-5 in one deterministic step. It is
**pure arithmetic over already-committed evidence** -- it runs no simulator and
reads nothing but ``sim/ro-ring-jitter-accumulation/records/*.json`` (the
append-only records minted by ``sim/bin/corner-run.py``). Re-running it on an
unchanged record set reproduces the reduction byte-for-byte, which is what makes
the sizing decision auditable without re-simulating anything.

What it computes, and where each formula comes from
---------------------------------------------------
``spec/porting-plan.md`` §1.1 lists these as the process-*independent* half of
the gf180-trng carryover -- the laws port, the measured inputs do not:

1. Per-ring white-noise sizing law (DR-0007 §2)::

       Q_ring(T_s) = sigma_1^2 * T_s / T_0^3

   ``sigma_1`` (s) is the per-period timing jitter and ``T_0`` (s) the mean
   oscillation period, both measured per PVT point by the ring testbenches.
   ``T_s`` is the *sampler* period, set by the fixed external sample clock
   (DR-0012's topology, carried over per §1.2), NOT by the ring -- so it is a
   spec row, identical at every corner, not a measured quantity.

2. Array sizing law (DR-0007 §2)::

       Q_array(T_s) = sum_i sigma_acc,i^2(T_s) / T_0,i^2  ==  sum_i Q_ring,i

   For ``N`` nominally identical rings this is just ``N * Q_ring``. No XOR
   "piling-up" credit and no flicker/low-frequency credit is taken -- both are
   named conservative-reading requirements in §1.1, not device facts.

3. Min-entropy bound (Baudet, Lubicz, Micolod, Tassiaux, CHES 2011)::

       H >= 1 - (4 / (pi^2 ln 2)) * exp(-4 pi^2 Q)

   inverted here to give the ``Q`` needed for a target ``H``.

4. Sizing requirement (DR-0007 §2)::

       Q_array >= M * Q_H0   at the entropy-binding corner,  M = 1.5

   ``M`` is a declared design margin, explicitly NOT sized to cover the
   characterization's own uncertainty on ``Q``.

The **entropy-binding corner** is then simply ``argmin`` of ``Q_ring`` over the
measured grid. ``spec/porting-plan.md`` §1.4/§2.4 is emphatic that its direction
must be read off the measurement rather than assumed from gf180-trng's answer
(cold, DR-0012) or its later self-correction (hot, DR-0015) -- so this script
reports the argmin it found and the full sorted grid behind it, and takes no
position of its own.

Usage
-----
    python3 sim/ro-array-sizing/analysis/array-sizing.py            # print report
    python3 sim/ro-array-sizing/analysis/array-sizing.py --emit-record

``--emit-record`` mints an append-only reduction record under
``sim/ro-array-sizing/records/`` in the same ``<YYYYMMDD>-<HHMMSS>-<shortsha>``
id scheme ``sim/bin/corner-run.py`` uses, and refuses to overwrite one.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
JITTER_RECORDS = REPO_ROOT / "sim" / "ro-ring-jitter-accumulation" / "records"
GAIN_RECORDS = REPO_ROOT / "sim" / "ro-stage-small-signal-gain" / "records"
CONV_RECORDS = REPO_ROOT / "sim" / "ro-ring-timestep-convergence" / "records"
OUT_RECORDS = REPO_ROOT / "sim" / "ro-array-sizing" / "records"

sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_record, new_record_id

# --- Spec rows this reduction is evaluated against ---------------------------
# README.md "Target specification" table, Raw rate row: "> 1 Mbps sustained at
# the raw tap". One raw bit per sample clock at the raw tap (DR-0003's raw-tap
# definition, §1.1) => T_s = 1 us. This is a DRAFT target row, not a ratified
# one, and Q is linear in T_s, so the report also tabulates N(T_s).
T_S_TARGET = 1.0e-6
# README.md "Raw min-entropy per bit" row: H0 = 0.5 bit/sample as a design
# target at the entropy-binding corner.
H0_TARGET = 0.5
# DR-0007 §2 declared design margin.
MARGIN_M = 1.5

# Baudet et al. bound constant: 4 / (pi^2 ln 2)
BAUDET_A = 4.0 / (math.pi**2 * math.log(2.0))
BAUDET_B = 4.0 * math.pi**2

CONFIG_BY_TESTBENCH = {
    "tb_ro_ring5_jitter.spice": ("ro_ring5", 5),
    "tb_ro_ring11_jitter.spice": ("ro_ring11", 11),
}

HEADLINE_POINTS = {
    ("tt", 27.0, 1.8): "nominal",
    ("ff", -40.0, 1.98): "fast/cold/high-supply",
    ("ss", 125.0, 1.62): "slow/hot/low-supply",
}

# Ring swing acceptance bar (issue #10 acceptance criterion 3). "Reaches the
# rails" is read here as: the ring node's steady-state peak-to-peak excursion
# covers at least this fraction of the supply. A hard 100% is not a meaningful
# bar for a *slew-limited* node -- an oscillator whose stage delay is set by a
# starve device never dwells at either rail -- so the bar is stated numerically
# and the measured margin is reported, rather than asserted as a boolean.
SWING_BAR = 0.80


def h_from_q(q: float) -> float:
    """Baudet et al. CHES 2011 min-entropy lower bound for a given Q."""
    return 1.0 - BAUDET_A * math.exp(-BAUDET_B * q)


def q_for_h(h: float) -> float:
    """Invert the bound: the smallest Q whose guaranteed H reaches `h`."""
    return -math.log((1.0 - h) / BAUDET_A) / BAUDET_B


def q_ring(sigma_1: float, t_0: float, t_s: float) -> float:
    return sigma_1**2 * t_s / t_0**3


def load_convergence() -> tuple[list[dict], dict[str, float]]:
    """Return the timestep-convergence sweep and the per-tmax numerical floor.

    The floor is a `--noise-amp 0` run of the *same* deck, seed and timestep:
    whatever `sigma_1` it reads back was manufactured by the transient solver,
    not by device noise. Every measured `sigma_1` at that timestep is therefore
    corrected in quadrature, `sqrt(max(s^2 - floor^2, 0))`, before it reaches
    the sizing law. That correction lowers `sigma_1`, lowers `Q`, and RAISES
    the sized `N` -- i.e. it is the conservative direction, which is why it is
    applied rather than merely noted.
    """
    rows: list[dict] = []
    floors: dict[str, float] = {}
    if not CONV_RECORDS.is_dir():
        return rows, floors
    for path in sorted(CONV_RECORDS.glob("*.json")):
        rec = json.loads(path.read_text())
        tran = rec.get("tran", {})
        tmax = str(tran.get("tmax", "?"))
        na = str(tran.get("noise_amp", "2.0e-3")).strip()
        for corner in rec["corners"]:
            m = corner.get("measurements", {})
            if "sigma_1" not in m:
                continue
            row = {
                "record_id": rec["record_id"], "tmax": tmax, "noise_amp": na,
                "t_0": m["tbar"], "sigma_1": m["sigma_1"],
                "sigma_2": m.get("sigma_2"), "sigma_4": m.get("sigma_4"),
                "sigma_8": m.get("sigma_8"), "swing_frac": m.get("swing_frac"),
                "is_floor": na in ("0", "0.0", "0e0"),
            }
            rows.append(row)
            if row["is_floor"]:
                floors[tmax] = m["sigma_1"]
    rows.sort(key=lambda r: (r["is_floor"], float(r["tmax"].rstrip("p"))))
    return rows, floors


def deflate(sigma_1: float, floor: float | None) -> float:
    if not floor:
        return sigma_1
    return math.sqrt(max(sigma_1**2 - floor**2, 0.0))


def load_points(floors: dict[str, float] | None = None) -> list[dict]:
    points: list[dict] = []
    if not JITTER_RECORDS.is_dir():
        return points
    for path in sorted(JITTER_RECORDS.glob("*.json")):
        rec = json.loads(path.read_text())
        tb = Path(rec["testbench"]).name
        if tb not in CONFIG_BY_TESTBENCH:
            continue
        config, stages = CONFIG_BY_TESTBENCH[tb]
        tmax = str(rec.get("tran", {}).get("tmax", "?"))
        floor = (floors or {}).get(tmax)
        for corner in rec["corners"]:
            if not corner.get("ok"):
                continue
            m = corner["measurements"]
            if "sigma_1" not in m or "tbar" not in m:
                continue
            sigma_1_raw = m["sigma_1"]
            sigma_1 = deflate(sigma_1_raw, floor)
            points.append(
                {
                    "record_id": rec["record_id"],
                    "config": config,
                    "stages": stages,
                    "tmax": tmax,
                    "sigma_1_raw": sigma_1_raw,
                    "numerical_floor": floor,
                    "corner": corner["corner"],
                    "temp_c": rec["pvt"]["temp_c"],
                    "vdd_v": rec["pvt"]["vdd_v"],
                    "seed": rec["seed"],
                    "t_0": m["tbar"],
                    "sigma_1": sigma_1,
                    "sigma_2": m.get("sigma_2"),
                    "sigma_4": m.get("sigma_4"),
                    "sigma_8": m.get("sigma_8"),
                    "vmax_ss": m.get("vmax_ss"),
                    "vmin_ss": m.get("vmin_ss"),
                    "swing_frac": m.get("swing_frac"),
                    "q_ring": q_ring(sigma_1, m["tbar"], T_S_TARGET),
                }
            )
    points.sort(key=lambda p: (p["config"], p["corner"], p["temp_c"], p["vdd_v"]))
    return points


def load_gain() -> list[dict]:
    out: list[dict] = []
    if not GAIN_RECORDS.is_dir():
        return out
    for path in sorted(GAIN_RECORDS.glob("*.json")):
        rec = json.loads(path.read_text())
        for corner in rec["corners"]:
            m = corner.get("measurements", {})
            if "transfer_function" not in m:
                continue
            out.append(
                {
                    "record_id": rec["record_id"],
                    "corner": corner["corner"],
                    "temp_c": rec["pvt"]["temp_c"],
                    "vdd_v": rec["pvt"]["vdd_v"],
                    "gain": m["transfer_function"],
                    "vtrip": m.get("vtrip"),
                }
            )
    out.sort(key=lambda g: (g["corner"], g["temp_c"], g["vdd_v"]))
    return out


def point_label(p: dict) -> str:
    key = (p["corner"], p["temp_c"], p["vdd_v"])
    name = HEADLINE_POINTS.get(key)
    base = f"{p['corner']} / {p['temp_c']:g} degC / {p['vdd_v']:g} V"
    return f"{base} ({name})" if name else base


def sized_n(q_min: float, t_s: float, h0: float, margin: float) -> int:
    q_req = margin * q_for_h(h0)
    # Q is linear in T_s, so rescale the measured Q (computed at T_S_TARGET).
    q_at_ts = q_min * (t_s / T_S_TARGET)
    return max(1, math.ceil(q_req / q_at_ts))


def build_report(points: list[dict], gains: list[dict],
                 conv: list[dict], floors: dict[str, float]) -> tuple[str, dict]:
    lines: list[str] = []
    flagship = [p for p in points if p["config"] == "ro_ring5"]
    other = [p for p in points if p["config"] != "ro_ring5"]

    q_req = MARGIN_M * q_for_h(H0_TARGET)

    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- Sample period `T_s` = {T_S_TARGET*1e6:g} us "
                 f"(README raw-rate target row, > 1 Mbps at the raw tap; a **draft** row)")
    lines.append(f"- Min-entropy design target `H0` = {H0_TARGET} bit/sample "
                 f"(README raw-min-entropy row)")
    lines.append(f"- Declared design margin `M` = {MARGIN_M} (DR-0007 §2, carried over per "
                 f"porting-plan §1.1)")
    lines.append(f"- Therefore `Q_H0` = {q_for_h(H0_TARGET):.6g} and the array must reach "
                 f"`Q_array >= M*Q_H0` = {q_req:.6g} at the entropy-binding corner")
    lines.append("")

    lines.append("## Per-stage small-signal gain (acceptance criterion 1)")
    lines.append("")
    if not gains:
        lines.append("_no gain records found_")
    else:
        lines.append("| Point | `vtrip` (V) | open-loop gain `dV(y)/dV(a)` |")
        lines.append("|---|---|---|")
        for g in gains:
            key = (g["corner"], g["temp_c"], g["vdd_v"])
            name = HEADLINE_POINTS.get(key, "")
            label = f"{g['corner']} / {g['temp_c']:g} degC / {g['vdd_v']:g} V"
            if name:
                label += f" ({name})"
            lines.append(f"| {label} | {g['vtrip']:.4g} | {g['gain']:.4g} |")
        worst = min(gains, key=lambda g: abs(g["gain"]))
        lines.append("")
        lines.append(
            f"Smallest |gain| measured: **{abs(worst['gain']):.3g}** at "
            f"{worst['corner']} / {worst['temp_c']:g} degC / {worst['vdd_v']:g} V."
        )
    lines.append("")

    lines.append("## Estimator validity: timestep convergence and numerical floor")
    lines.append("")
    if not conv:
        lines.append("_no convergence records found_")
    else:
        lines.append("Same deck, same corner (tt / 27 degC / 1.8 V), same seed; only the "
                     "transient max timestep `@@TMAX@@` and the injected amplitude "
                     "`@@NA@@` differ.")
        lines.append("")
        lines.append("| `@@TMAX@@` | `@@NA@@` | `T_0` (ns) | `sigma_1` (ps) | `sigma_8` (ps) |")
        lines.append("|---|---|---|---|---|")
        for r in conv:
            s8 = "n/a" if r["sigma_8"] is None else f"{r['sigma_8']*1e12:.3f}"
            tag = " (floor)" if r["is_floor"] else ""
            lines.append(
                f"| {r['tmax']}{tag} | {r['noise_amp']} | {r['t_0']*1e9:.5f} | "
                f"{r['sigma_1']*1e12:.3f} | {s8} |"
            )
        lines.append("")
        real = [r for r in conv if not r["is_floor"]]
        if real:
            s1s = [r["sigma_1"] for r in real]
            t0s = [r["t_0"] for r in real]
            lines.append(
                f"`T_0` moves {(max(t0s)-min(t0s))/min(t0s)*100:.2f}% across a 8x "
                f"change in timestep -- converged. `sigma_1` scatters "
                f"{(max(s1s)-min(s1s))/min(s1s)*100:.0f}% with no monotone trend, "
                f"i.e. **no timestep dependence is resolvable above the 20-sample "
                f"estimator's own ~16% statistical error**. The campaign therefore "
                f"runs the grid at the coarsest step measured here that is still "
                f"within that scatter, which is what makes a 27-point grid "
                f"affordable at all."
            )
        lines.append("")
        if floors:
            for tmax, f in sorted(floors.items()):
                lines.append(
                    f"Numerical floor at `@@TMAX@@` = {tmax}: **{f*1e12:.3f} ps** of "
                    f"period scatter with the injected noise switched off entirely. "
                    f"Every `sigma_1` below is corrected in quadrature against it "
                    f"(`sqrt(s^2 - floor^2)`), which lowers `Q` and raises `N` -- the "
                    f"conservative direction."
                )
        else:
            lines.append("**No numerical-floor control was measured**, so no "
                         "quadrature correction is applied and every `sigma_1` below "
                         "is an upper bound.")
    lines.append("")
    summary_conv = {"convergence": conv, "numerical_floors": floors}

    lines.append("## Measured ring grid, reduced to Q")
    lines.append("")
    lines.append(f"`Q_ring = sigma_1^2 * T_s / T_0^3` at `T_s` = {T_S_TARGET*1e6:g} us.")
    lines.append("")
    for label, group in (("`ro_ring5` (flagship, full grid)", flagship),
                         ("`ro_ring11` (headline points only)", other)):
        if not group:
            continue
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| Corner | T (degC) | Vdd (V) | `T_0` (ns) | `sigma_1` (ps) | "
                     "`sigma_1`/`T_0` | swing frac | `Q_ring` | record |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for p in sorted(group, key=lambda x: x["q_ring"]):
            sw = "n/a" if p["swing_frac"] is None else f"{p['swing_frac']:.3f}"
            lines.append(
                f"| `{p['corner']}` | {p['temp_c']:g} | {p['vdd_v']:g} | "
                f"{p['t_0']*1e9:.3f} | {p['sigma_1']*1e12:.3f} | "
                f"{p['sigma_1']/p['t_0']:.3e} | {sw} | {p['q_ring']:.4g} | "
                f"`{p['record_id']}` |"
            )
        lines.append("")
        lines.append("_sorted by `Q_ring` ascending: the first row is this "
                     "configuration's own entropy-binding corner._")
        lines.append("")

    binding = min(flagship, key=lambda p: p["q_ring"]) if flagship else None
    summary: dict = {
        "t_s_s": T_S_TARGET,
        "h0_target": H0_TARGET,
        "margin_m": MARGIN_M,
        "q_h0": q_for_h(H0_TARGET),
        "q_required": q_req,
        "swing_bar": SWING_BAR,
        "points": points,
        "gain": gains,
        **summary_conv,
    }

    lines.append("## Entropy-binding corner (acceptance criterion 4)")
    lines.append("")
    if binding is None:
        lines.append("_no flagship grid points found_")
    else:
        hottest = max(flagship, key=lambda p: p["temp_c"])
        coldest = min(flagship, key=lambda p: p["temp_c"])
        worst_q = max(flagship, key=lambda p: p["q_ring"])
        lines.append(
            f"Minimum `Q_ring` over the measured `ro_ring5` grid "
            f"({len(flagship)} points) is **{binding['q_ring']:.4g}** at "
            f"**{point_label(binding)}**."
        )
        lines.append("")
        lines.append(
            f"Spread across the grid: max `Q_ring` = {worst_q['q_ring']:.4g} at "
            f"{point_label(worst_q)}, i.e. a "
            f"{worst_q['q_ring']/binding['q_ring']:.2f}x range."
        )
        lines.append("")
        lines.append(
            f"Direction on temperature, read off the measurement rather than assumed: "
            f"the binding corner sits at **{binding['temp_c']:g} degC**."
        )
        summary["entropy_binding_corner"] = {
            "config": binding["config"],
            "corner": binding["corner"],
            "temp_c": binding["temp_c"],
            "vdd_v": binding["vdd_v"],
            "q_ring": binding["q_ring"],
            "t_0_s": binding["t_0"],
            "sigma_1_s": binding["sigma_1"],
            "record_id": binding["record_id"],
        }
        _ = hottest, coldest
    lines.append("")

    lines.append("## Ring swing (acceptance criterion 3)")
    lines.append("")
    swings = [p for p in points if p["swing_frac"] is not None]
    if not swings:
        lines.append("_no swing measurements found_")
    else:
        worst_sw = min(swings, key=lambda p: p["swing_frac"])
        lines.append(
            f"| bar | worst measured | at | verdict |"
        )
        lines.append("|---|---|---|---|")
        verdict = "CONFIRMED" if worst_sw["swing_frac"] >= SWING_BAR else "REFUTED"
        lines.append(
            f"| >= {SWING_BAR:.2f} x Vdd peak-to-peak | "
            f"{worst_sw['swing_frac']:.3f} | "
            f"`{worst_sw['config']}` {point_label(worst_sw)} | **{verdict}** |"
        )
        summary["swing"] = {
            "bar": SWING_BAR,
            "worst_frac": worst_sw["swing_frac"],
            "worst_point": point_label(worst_sw),
            "worst_config": worst_sw["config"],
            "verdict": verdict,
        }
    lines.append("")

    lines.append("## Sized N (acceptance criterion 5)")
    lines.append("")
    if binding is not None:
        n = sized_n(binding["q_ring"], T_S_TARGET, H0_TARGET, MARGIN_M)
        summary["sized_n"] = n
        lines.append(
            f"`N = ceil(M*Q_H0 / Q_ring(binding))` = "
            f"ceil({q_req:.4g} / {binding['q_ring']:.4g}) = **{n}** "
            f"`ro_ring5` rings at `T_s` = {T_S_TARGET*1e6:g} us."
        )
        lines.append("")
        lines.append("`Q` is linear in `T_s`, and `N` is inversely linear in it, so the "
                     "sizing is entirely hostage to the raw-rate row:")
        lines.append("")
        lines.append("| raw rate | `T_s` | `Q_array` per ring | sized `N` (`ro_ring5`) |")
        lines.append("|---|---|---|---|")
        rate_table = []
        for rate, label in ((1e7, "10 Mbps"), (1e6, "1 Mbps"), (1e5, "100 kbps"),
                            (1e4, "10 kbps"), (2e3, "2 kbps (gf180-trng's own proposed row)")):
            t_s = 1.0 / rate
            q_at = binding["q_ring"] * (t_s / T_S_TARGET)
            nn = sized_n(binding["q_ring"], t_s, H0_TARGET, MARGIN_M)
            lines.append(f"| {label} | {t_s*1e6:g} us | {q_at:.4g} | **{nn}** |")
            rate_table.append({"rate_bps": rate, "t_s_s": t_s, "q_ring": q_at, "n": nn})
        summary["n_vs_rate"] = rate_table
        lines.append("")
        # stage-count comparison
        if other:
            b5 = binding
            r11 = [p for p in other]
            best11 = min(r11, key=lambda p: p["q_ring"])
            same5 = [p for p in flagship
                     if (p["corner"], p["temp_c"], p["vdd_v"])
                     == (best11["corner"], best11["temp_c"], best11["vdd_v"])]
            lines.append("### Stage count, measured rather than inherited")
            lines.append("")
            lines.append("| point | `ro_ring5` `Q_ring` | `ro_ring11` `Q_ring` | ratio |")
            lines.append("|---|---|---|---|")
            for p11 in sorted(r11, key=lambda x: x["q_ring"]):
                match = [p for p in flagship
                         if (p["corner"], p["temp_c"], p["vdd_v"])
                         == (p11["corner"], p11["temp_c"], p11["vdd_v"])]
                if not match:
                    continue
                p5 = match[0]
                lines.append(
                    f"| {point_label(p11)} | {p5['q_ring']:.4g} | {p11['q_ring']:.4g} | "
                    f"{p5['q_ring']/p11['q_ring']:.2f}x |"
                )
            lines.append("")
            lines.append(
                "The naive expectation from the sizing law alone is that `sigma_1^2` "
                "grows with the stage count while `T_0` grows with it too, giving "
                "`Q ~ 1/n^2`. Using the *measured* `T_0` ratio at nominal "
                f"({[p['t_0'] for p in flagship if (p['corner'],p['temp_c'],p['vdd_v'])==('tt',27.0,1.8)][0]*1e9:.3f} ns "
                f"vs {[p['t_0'] for p in other if (p['corner'],p['temp_c'],p['vdd_v'])==('tt',27.0,1.8)][0]*1e9:.3f} ns) "
                "and `sigma_1^2 ~ n`, the predicted `Q` ratio at nominal is ~8.5x. "
                "The measured ratio is ~28x, i.e. ~3.3x more penalty than the law "
                "predicts, because the measured `sigma_1` *fell* going from 5 to 11 "
                "stages instead of rising as `sqrt(n)`. That discrepancy is real and "
                "consistent in sign at all three headline points, and this campaign "
                "does NOT explain it -- it is recorded as an open question, not "
                "smoothed over. Its direction is conservative for the conclusion "
                "drawn here (it makes the 11-stage ring look worse, and the "
                "conclusion is that 11 stages is expensive), so it does not soften "
                "the sizing verdict; it does mean the `ro_ring5`-vs-`ro_ring11` "
                "ratio itself should not be quoted as a device-physics constant."
            )
            lines.append("")
            summary["stage_count_comparison"] = [
                {
                    "corner": p11["corner"], "temp_c": p11["temp_c"], "vdd_v": p11["vdd_v"],
                    "q_ring5": next((p["q_ring"] for p in flagship
                                     if (p["corner"], p["temp_c"], p["vdd_v"])
                                     == (p11["corner"], p11["temp_c"], p11["vdd_v"])), None),
                    "q_ring11": p11["q_ring"],
                }
                for p11 in r11
            ]
            _ = b5, same5
            lines.append("")
            lines.append("### Sized N per configuration")
            lines.append("")
            lines.append("| configuration | worst measured `Q_ring` | at | sized `N` "
                         "at 1 Mbps | grid coverage |")
            lines.append("|---|---|---|---|---|")
            per_config = []
            for cfgname, group, cov in (("`ro_ring5`", flagship, f"{len(flagship)}-point full grid"),
                                        ("`ro_ring11` (as drawn in `ro_array_core.sch`)",
                                         other, f"{len(other)} headline points only")):
                if not group:
                    continue
                w = min(group, key=lambda p: p["q_ring"])
                nn = sized_n(w["q_ring"], T_S_TARGET, H0_TARGET, MARGIN_M)
                lines.append(f"| {cfgname} | {w['q_ring']:.4g} | {point_label(w)} | "
                             f"**{nn}** | {cov} |")
                per_config.append({"config": w["config"], "q_min": w["q_ring"],
                                   "corner": w["corner"], "temp_c": w["temp_c"],
                                   "vdd_v": w["vdd_v"], "n": nn, "coverage": cov})
            summary["sized_n_per_config"] = per_config
            lines.append("")
            lines.append("`ro_ring11`'s number is a *lower bound on N*: it is sized "
                         "from the best of only three headline points, and its own "
                         "grid minimum was not searched.")
            lines.append("")

        # What the committed placeholder actually delivers
        lines.append("### What the committed placeholder `N = 2` actually delivers")
        lines.append("")
        lines.append("`H` below is the Baudet et al. bound evaluated at "
                     "`Q_array = N * Q_ring(binding corner)`, i.e. the min-entropy "
                     "per raw bit the **sizing model is willing to guarantee** at a "
                     f"{T_S_TARGET*1e6:g} us sample period -- not a measured entropy "
                     "and not an upper bound on the source's real behaviour.")
        lines.append("")
        lines.append("Read the shape of the bound before reading the numbers: it "
                     "saturates at `1 - 4/(pi^2 ln 2)` = "
                     f"{h_from_q(0.0):.4f} as `Q -> 0`, so a badly undersized array "
                     "does not read as `H = 0` here. The operative sizing statement "
                     "is the `Q` requirement, not the `H` column.")
        lines.append("")
        n_h_rows = []
        if flagship:
            qb = min(flagship, key=lambda p: p["q_ring"])["q_ring"]
            n_bare = sized_n(qb, T_S_TARGET, H0_TARGET, 1.0)
            n_marg = sized_n(qb, T_S_TARGET, H0_TARGET, MARGIN_M)
            lines.append("| `N` (`ro_ring5`) | `Q_array` | guaranteed `H` | meets "
                         f"`H0` = {H0_TARGET}? | meets `M*Q_H0`? |")
            lines.append("|---|---|---|---|---|")
            for n in sorted({1, 2, 4, 8, 16, 32, n_bare, n_marg}):
                qa = n * qb
                h = h_from_q(qa)
                lines.append(
                    f"| {n}{' <- committed placeholder' if n == 2 else ''}"
                    f"{' <- bare `H0`' if n == n_bare else ''}"
                    f"{' <- **sized, with margin**' if n == n_marg else ''} | "
                    f"{qa:.4g} | {h:.4f} | {'yes' if h >= H0_TARGET else 'no'} | "
                    f"{'yes' if qa >= q_req else 'no'} |"
                )
                n_h_rows.append({"n": n, "q_array": qa, "h": h})
            lines.append("")
            lines.append(
                f"So the committed `N = 2` is **refuted, quantitatively**: at the "
                f"measured entropy-binding corner it guarantees `H` = "
                f"{h_from_q(2*qb):.4f} bit/raw-bit against a declared `H0` = "
                f"{H0_TARGET} design target, and its `Q_array` = {2*qb:.4g} is "
                f"{q_req/(2*qb):.0f}x short of the `M*Q_H0` = {q_req:.4g} the sizing "
                f"law asks for. Reaching `H0` at all needs `N` = {n_bare}; reaching "
                f"it with DR-0007's declared `M` = {MARGIN_M} margin needs `N` = "
                f"{n_marg}. What `N = 2` is *not* is off by orders of magnitude in "
                f"entropy -- the bound's saturation means the entropy shortfall is "
                f"{H0_TARGET - h_from_q(2*qb):.3f} bit, not 0.5 bit. Both statements "
                f"are true and the second is the one that makes this a design "
                f"trade rather than a failure."
            )
        summary["n_vs_h"] = n_h_rows
        lines.append("")
    else:
        lines.append("_not derivable: no flagship grid points_")

    return "\n".join(lines), summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true",
                    help="mint an append-only reduction record under sim/ro-array-sizing/records/")
    ap.add_argument("--author", default="loom-builder@sky130-trng")
    args = ap.parse_args(argv)

    conv, floors = load_convergence()
    points = load_points(floors)
    gains = load_gain()
    if not points:
        print("error: no ring jitter records found under "
              f"{JITTER_RECORDS.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1

    body, summary = build_report(points, gains, conv, floors)
    print(body)

    if not args.emit_record:
        return 0

    now, sha, rid = new_record_id(REPO_ROOT)

    src_records = sorted({p["record_id"] for p in points})
    header = [
        f"# {rid} -- ro-array-sizing",
        "",
        "**Claim**: reduction of the measured ro_ring5/ro_ring11 jitter grid to "
        "`Q` via the array sizing law; identification of the entropy-binding "
        "corner; the resulting sized array size `N`.",
        "",
        "**Level**: transistor (derived -- this record introduces no new simulation; "
        "it is arithmetic over the cited transistor-level records)",
        "**Seed**: N/A (deterministic reduction; the underlying runs state their own seeds)",
        f"**Analysis**: `sim/ro-array-sizing/analysis/array-sizing.py` (re-run to reproduce)",
        "",
        "## Source records",
        "",
        "Jitter grid (`sim/ro-ring-jitter-accumulation/records/`):",
        "",
    ]
    header += [f"- `{r}`" for r in src_records]
    header += ["", "Per-stage gain (`sim/ro-stage-small-signal-gain/records/`):", ""]
    header += [f"- `{r}`" for r in sorted({g['record_id'] for g in gains})] or ["- (none)"]
    header += ["", "---", ""]

    summary_out = {
        "record_id": rid,
        "slug": "ro-array-sizing",
        "level": "transistor (derived)",
        "analysis": "sim/ro-array-sizing/analysis/array-sizing.py",
        "source_records": src_records,
        "gain_records": sorted({g["record_id"] for g in gains}),
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
