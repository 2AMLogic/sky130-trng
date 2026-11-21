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
# used only when combine_options.py is run standalone (no live synthesis)
STANDALONE_VARIANT_SYNTH_UM2 = 16129.2192


def restack(dig_side: float, ana_w: float, ana_h: float) -> dict:
    """Estimate-B re-stack: committed topology, resized macros."""
    west_extreme = min(0.0, DIG_EAST_EDGE_UM - dig_side - VPWR_ESCAPE_UM)
    east = max(ana_w, DIG_EAST_EDGE_UM)
    width = east - west_extreme
    height = dig_side + LANE_BAND_UM + ana_h + PAD_STRIP_UM
    return {"width_um": round(width, 3), "height_um": round(height, 3),
            "area_um2": round(width * height, 3),
            "area_mm2": round(width * height / 1e6, 6)}


def restack_aligned(dig_side: float, ana_w: float, ana_h: float) -> dict:
    """Edge-aligned variant of the re-stack (item 3's proposal): the analog
    row's west edge is aligned to the digital macro's, so neither stacking
    artifact (south-east corridor, west-of-analog strip) exists.  Keeps the
    lane band, pad strip and west escape.  A geometric estimate only: it
    assumes the digital east pin edge can sit at the analog row's east edge
    (a pin-access / lane-routing check is required before it is a layout)."""
    width = VPWR_ESCAPE_UM + max(dig_side, ana_w)
    height = dig_side + LANE_BAND_UM + ana_h + PAD_STRIP_UM
    return {"width_um": round(width, 3), "height_um": round(height, 3),
            "area_um2": round(width * height, 3),
            "area_mm2": round(width * height / 1e6, 6)}


def main(variant_synth_cells_um2: float | None = None) -> dict:
    """``variant_synth_cells_um2``: the FIFO-2 variant's synthesized cell
    area from the CURRENT run.  Omitted only for standalone inspection, where
    the committed #599 measurement is used and flagged in the output."""
    measured = variant_synth_cells_um2 is not None
    if variant_synth_cells_um2 is None:
        variant_synth_cells_um2 = STANDALONE_VARIANT_SYNTH_UM2
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

    var_side, var_basis = variant_die_side(variant_synth_cells_um2)
    var40_side, var40_basis = variant_die_side(
        variant_synth_cells_um2, ref_side=DIG_BASELINE_SIDE_UM,
        ref_cells=24000.5)  # rep40 repaired std-cell area (#251)

    rows = []
    # the whole-block figure each baseline column is compared against
    base_mm2 = {"committed 40%": COMMITTED_WHOLE_MM2,
                "rep65": restack(REP65_SIDE_UM, COMMITTED_ANA_W_UM,
                                 COMMITTED_ANA_H_UM)["area_mm2"]}

    def add(label, baseline, r, confidence, note, topology="fixed pin edge",
            risk="none beyond the committed composition"):
        rows.append({
            "option": label, "on_baseline": baseline, **r,
            "topology": topology,
            "confidence": confidence, "note": note, "risk": risk,
            "delta_vs_baseline_mm2": round(
                r["area_mm2"] - base_mm2[baseline], 6),
            "ratio_to_target": round(r["area_mm2"] / TARGET_MM2, 3),
            "gap_mm2": round(r["area_mm2"] - TARGET_MM2, 6),
        })

    R_F1 = ("F1 re-routes the sampler/array data hauls, supply straps and "
            "ctrl lanes (fold_f1.routing); needs a composed + DRC/LVS pass")
    R_F2 = ("F2 puts a vertical neighbour on every ring (DR-0003 section 8 "
            "decorrelation caveat, unmeasured) and grows the macro")
    R_VAR = ("variant digital die is scaled from the synthesized cell-area "
             "ratio, not routed; adoption needs the DR-0004 4.4 depth "
             "decision (#610)")
    R_ALIGN = ("assumes the digital east pin edge can be aligned with the "
               "analog row's east edge; the lane band's pin access is "
               "unchecked")

    add("committed composition", "committed 40%",
        {"area_mm2": COMMITTED_WHOLE_MM2},
        "composed, verified",
        "layout/trng_whole/report.json; the only non-estimate row")
    r = restack(REP65_SIDE_UM, COMMITTED_ANA_W_UM, COMMITTED_ANA_H_UM)
    add("rep65-slew0531 digital, committed analog (estimate B of #251)",
        "rep65", r, "measured inputs, estimated composition",
        "reproduces #251's 0.093609 mm2")
    f1_note = (f"fold F1 dry-run bbox {f1['width_um']} x "
               f"{f1['height_um']} um")
    f2_note = (f"fold F2 dry-run bbox {f2['width_um']} x "
               f"{f2['height_um']} um: narrower row, taller macro")
    for dig_label, dig_side, base in (
            ("rep65 digital", REP65_SIDE_UM, "rep65"),
            ("variant FIFO-2 digital (die est)", var_side, "rep65"),
            ("committed 40% digital", DIG_BASELINE_SIDE_UM, "committed 40%"),
            ("variant FIFO-2 digital (40% die est)", var40_side,
             "committed 40%")):
        is_var = dig_label.startswith("variant")
        for fold_label, fold, note, frisk in (
                ("F1", f1, f1_note, R_F1), ("F2 (2x2 rings)", f2, f2_note,
                                            R_F2)):
            add(f"{dig_label} + folded analog {fold_label}", base,
                restack(dig_side, fold["width_um"], fold["height_um"]),
                "estimated",
                note + (f"; die side {dig_side:.2f} um" if is_var else ""),
                risk=frisk + ("; " + R_VAR if is_var else ""))
    # edge-aligned topology (a different floorplan, geometric estimate only)
    for dig_label, dig_side, base in (
            ("rep65 digital", REP65_SIDE_UM, "rep65"),
            ("variant FIFO-2 digital (die est)", var_side, "rep65"),
            ("committed 40% digital", DIG_BASELINE_SIDE_UM, "committed 40%"),
            ("variant FIFO-2 digital (40% die est)", var40_side,
             "committed 40%")):
        is_var = dig_label.startswith("variant")
        for fold_label, fold, frisk in (("F1", f1, R_F1),
                                        ("F2 (2x2 rings)", f2, R_F2)):
            add(f"{dig_label} + folded analog {fold_label}, edge-aligned",
                base,
                restack_aligned(dig_side, fold["width_um"],
                                fold["height_um"]),
                "geometric estimate (floorplan change)",
                "west edges aligned: stacking artifacts removed; lane band, "
                "pad strip and west escape kept",
                topology="edge-aligned",
                risk=R_ALIGN + "; " + frisk + ("; " + R_VAR if is_var
                                               else ""))

    # headline = the best row of the FIXED pin-edge topology only
    est = [row for row in rows if row["confidence"] == "estimated"]
    best = min(est, key=lambda row: row["area_mm2"])
    aligned = [row for row in rows if row["topology"] == "edge-aligned"]
    best_aligned = min(aligned, key=lambda row: row["area_mm2"])

    # what the target would demand at the best option's width: this holds
    # the F1 analog dimensions fixed and solves for the digital macro, so it
    # is a trade-off figure, not a statement that the analog row must shrink
    w = restack(var_side, f1["width_um"], f1["height_um"])["width_um"]
    max_h = TARGET_MM2 * 1e6 / w
    dig_budget = max_h - LANE_BAND_UM - f1["height_um"] - PAD_STRIP_UM
    hypo = restack(dig_budget, f1["width_um"], f1["height_um"])
    area_ratio_needed = (dig_budget / var_side) ** 2

    return {
        "target_mm2": TARGET_MM2,
        "variant_synth_cells_um2": variant_synth_cells_um2,
        "variant_synth_source": "this run's synthesis" if measured else
                                "standalone default (committed #599 value)",
        "variant_die_side_um": round(var_side, 3),
        "variant_die_side_40pct_um": round(var40_side, 3),
        "restack_assertion": baseline_check,
        "rows": rows,
        "best_option": best["option"],
        "best_area_mm2": best["area_mm2"],
        "best_topology": best["topology"],
        "best_shortfall_mm2": round(best["area_mm2"] - TARGET_MM2, 6),
        "reaches_target": best["area_mm2"] < TARGET_MM2,
        "best_edge_aligned_option": best_aligned["option"],
        "best_edge_aligned_area_mm2": best_aligned["area_mm2"],
        "best_edge_aligned_reaches_target":
            best_aligned["area_mm2"] < TARGET_MM2,
        "at_best_width_um": w,
        "digital_height_budget_to_reach_target_um": round(dig_budget, 2),
        "hypothetical_restack_at_budget": hypo,
        "verdict_text": (
            f"Within the fixed pin-edge topology (digital east pin edge "
            f"held, as committed) no studied combination reaches 0.05 mm2: "
            f"the best is {best['area_mm2']:.6f} mm2 "
            f"({best['ratio_to_target']}x target), short by "
            f"{best['area_mm2'] - TARGET_MM2:.6f} mm2. The best "
            f"edge-aligned geometric estimate -- a floorplan change that "
            f"also needs a pin-access check -- is "
            f"{best_aligned['area_mm2']:.6f} mm2 "
            f"({best_aligned['option']}); it "
            f"{'reaches' if best_aligned['area_mm2'] < TARGET_MM2 else 'does not reach'}"
            f" the target. Trade-off, not a requirement: holding the F1 "
            f"analog width ({w} um) and dimensions, the digital macro would "
            f"have to be at most {dig_budget:.1f} um tall (a hypothetical "
            f"re-stack at that size is {hypo['area_mm2']:.6f} mm2) vs the "
            f"{var_side:.1f} um the FIFO-2 variant estimates -- about "
            f"{100 * area_ratio_needed:.0f}% of its die area; narrowing the "
            f"analog row or aligning edges relaxes that digital budget."
        ),
        "largest_remaining_limiter": (
            "the routed digital macro: even with the FIFO-2 variant its "
            f"estimated die is ~{var_side ** 2:.0f} um2 at the achieved 62% "
            "utilisation of #251's repaired 65% point -- the largest single "
            "contributor of the best row; the analog F1 bbox "
            f"({f1['area_um2']:.0f} um2) is second, the functional "
            "composition overhead (lane band + pads + escape, scaling with "
            "width) third"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
