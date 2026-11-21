#!/usr/bin/env python3
"""Combine the studied options into whole-block figures on both baselines
(issue #599, item 4).

Every row is labelled with its confidence:

* ``composed, verified`` -- the committed whole block (#172/#173).
* ``measured inputs, estimated composition`` -- estimate B of #226/#251:
  the committed floorplan's own geometry re-stacked around a resized
  digital macro (digital east pin edge held at x = 200, VPWR west escape
  2.15 um, digital->analog lane band 20.005 um, pad strip 10.14 um).
  Reproduces the committed 0.126116 mm2 exactly at the baseline size
  (asserted here).
* ``estimated`` -- the same re-stack arithmetic fed with this study's
  estimates (folded analog dry-run bbox; variant digital die scaled from
  the rep65 repaired run by the variant's synthesized cell-area ratio and
  the repaired/unrepaired routed-cell factor, both stated).

Inputs: ``layout/trng_whole/report.json`` (committed bboxes),
``sim/digital-repaired-compaction/records/20261010-105914-824542d.md``
(rep65 die 194.39 um side, repaired std-cell 23431.2 um2), the committed
synthesis response (22,203.7952 um2), and this study's measurements.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# committed, measured inputs
COMMITTED_WHOLE_MM2 = 0.126116
DIG_BASELINE_SIDE_UM = 245.05          # committed 40% floorplan
REP65_SIDE_UM = 194.39                 # rep65-slew0531 die (#251, actual)
REP65_REPAIRED_CELLS_UM2 = 23431.2     # rep65 repaired std-cell area (#251)
BASELINE_SYNTH_CELLS_UM2 = 22203.7952  # committed unconstrained synthesis
LANE_BAND_UM = 20.005                  # #226 estimate-B geometry
PAD_STRIP_UM = 10.14
VPWR_ESCAPE_UM = 2.15
DIG_EAST_EDGE_UM = 200.0               # inter-macro lane corridor
COMMITTED_ANA_W_UM = 330.96
COMMITTED_ANA_H_UM = 58.305
TARGET_MM2 = 0.05


def restack(dig_side: float, ana_w: float, ana_h: float) -> dict:
    """Estimate-B re-stack: committed topology, resized macros."""
    west_extreme = min(0.0, DIG_EAST_EDGE_UM - dig_side - VPWR_ESCAPE_UM)
    east = max(ana_w, DIG_EAST_EDGE_UM)
    width = east - west_extreme
    height = dig_side + LANE_BAND_UM + ana_h + PAD_STRIP_UM
    return {"width_um": round(width, 3), "height_um": round(height, 3),
            "area_um2": round(width * height, 3),
            "area_mm2": round(width * height / 1e6, 6)}


def main() -> dict:
    # assertion: the re-stack formula reproduces the committed whole block
    baseline_check = restack(DIG_BASELINE_SIDE_UM, COMMITTED_ANA_W_UM,
                             COMMITTED_ANA_H_UM)
    assert abs(baseline_check["area_mm2"] - COMMITTED_WHOLE_MM2) < 2e-6, \
        f"re-stack no longer reproduces the committed figure: {baseline_check}"

    folds = json.loads(json.dumps(__import__("fold_sampler_core").main()))
    f1, f2 = folds["fold_f1"], folds["fold_f2"]

    def variant_die_side(variant_synth_cells_um2: float,
                         ref_side: float = REP65_SIDE_UM,
                         ref_cells: float = REP65_REPAIRED_CELLS_UM2
                         ) -> tuple[float, dict]:
        routed = variant_synth_cells_um2 * (ref_cells /
                                            BASELINE_SYNTH_CELLS_UM2)
        die = ref_side ** 2 * (routed / ref_cells)
        return math.sqrt(die), {
            "variant_synth_cells_um2": variant_synth_cells_um2,
            "variant_routed_cells_est_um2": round(routed, 1),
            "scaling": "reference die x (variant routed cells / reference "
                       "repaired cells); routed cells = variant synthesized "
                       "cells x the committed repaired/unconstrained ratio "
                       f"({ref_cells:.1f}/"
                       f"{BASELINE_SYNTH_CELLS_UM2:.4f})",
        }

    var_side, var_basis = variant_die_side(16129.2192)  # this study's run
    var40_side, var40_basis = variant_die_side(
        16129.2192, ref_side=DIG_BASELINE_SIDE_UM,
        ref_cells=24000.5)  # rep40 repaired std-cell area (#251)

    rows = []

    def add(label, baseline, r, confidence, note):
        rows.append({
            "option": label, "on_baseline": baseline, **r,
            "confidence": confidence, "note": note,
            "ratio_to_target": round(r["area_mm2"] / TARGET_MM2, 3),
            "gap_mm2": round(r["area_mm2"] - TARGET_MM2, 6),
        })

    add("committed composition", "committed 40%",
        {"area_mm2": COMMITTED_WHOLE_MM2},
        "composed, verified",
        "layout/trng_whole/report.json; the only non-estimate row")
    r = restack(REP65_SIDE_UM, COMMITTED_ANA_W_UM, COMMITTED_ANA_H_UM)
    add("rep65-slew0531 digital, committed analog (estimate B of #251)",
        "rep65", r, "measured inputs, estimated composition",
        "reproduces #251's 0.093609 mm2")
    r = restack(REP65_SIDE_UM, f1["width_um"], f1["height_um"])
    add("rep65 digital + folded analog F1", "rep65", r, "estimated",
        "fold F1 dry-run bbox 218.675 x 81.94 um")
    r = restack(var_side, f1["width_um"], f1["height_um"])
    add("variant FIFO-2 digital (die est) + folded analog F1", "rep65", r,
        "estimated",
        f"variant die side {var_side:.2f} um; {var_basis['scaling']}")
    r = restack(REP65_SIDE_UM, f2["width_um"], f2["height_um"])
    add("rep65 digital + folded analog F2 (2x2 rings)", "rep65", r,
        "estimated",
        "recorded for completeness: narrower row but taller macro and "
        "unresolved ring-adjacency risk; worse than F1 here")
    r = restack(var_side, f2["width_um"], f2["height_um"])
    add("variant FIFO-2 digital (die est) + folded analog F2", "rep65", r,
        "estimated", "still worse than the F1 row; same risk caveat")

    # the same options on the committed 40% baseline (the AC asks for both)
    r = restack(DIG_BASELINE_SIDE_UM, f1["width_um"], f1["height_um"])
    add("committed 40% digital + folded analog F1", "committed 40%", r,
        "estimated", "fold F1 on the committed digital baseline")
    r = restack(var40_side, f1["width_um"], f1["height_um"])
    add("variant FIFO-2 digital (40% die est) + folded analog F1",
        "committed 40%", r, "estimated",
        f"variant die side {var40_side:.2f} um at rep40's utilisation; "
        f"{var40_basis['scaling']}")

    best = min((row for row in rows if row["confidence"] != "composed, verified"
                and row["option"] != "committed composition"),
               key=lambda row: row["area_mm2"])

    # what the target would demand at the best option's width
    w = restack(var_side, f1["width_um"], f1["height_um"])["width_um"]
    max_h = TARGET_MM2 * 1e6 / w
    dig_budget = max_h - LANE_BAND_UM - f1["height_um"] - PAD_STRIP_UM

    return {
        "target_mm2": TARGET_MM2,
        "restack_assertion": baseline_check,
        "rows": rows,
        "best_option": best["option"],
        "best_area_mm2": best["area_mm2"],
        "best_shortfall_mm2": round(best["area_mm2"] - TARGET_MM2, 6),
        "reaches_target": best["area_mm2"] < TARGET_MM2,
        "at_best_width_um": w,
        "digital_height_budget_to_reach_target_um": round(dig_budget, 2),
        "verdict_text": (
            "No combination of the studied options reaches 0.05 mm2. The "
            f"best is {best['area_mm2']:.6f} mm2 ({best['ratio_to_target']}x "
            "target), short by "
            f"{best['area_mm2'] - TARGET_MM2:.6f} mm2. Holding the F1 width "
            f"({w} um), the whole-block height budget for 0.05 mm2 leaves a "
            f"digital macro at most {dig_budget:.1f} um tall -- vs the "
            f"{var_side:.1f} um the FIFO-2 variant already estimates, so the "
            "target needs a digital section roughly half today's cell area "
            "AND an analog row narrower than F1, not a floorplan change."
        ),
        "largest_remaining_limiter": (
            "the routed digital macro: even with the FIFO-2 variant its "
            f"estimated die is ~{var_side ** 2:.0f} um2 at the achieved 62% "
            "utilisation of #251's repaired 65% point -- the largest single "
            "contributor of the best row; the analog F1 bbox (17,918 um2) is "
            "second, the functional composition overhead (lane band + pads + "
            "escape, scaling with width) third"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
