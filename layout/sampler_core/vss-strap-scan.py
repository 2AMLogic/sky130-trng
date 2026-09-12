#!/usr/bin/env python3
"""Re-derive every geometric claim behind this increment's vss strap.

Same discipline as ``data-path-scan.py``: every lane this increment picked
was picked from a measurement, not a guess, and this script is that
measurement, re-runnable, and it exits non-zero if any of it stops holding.

Two groups of claims:

A. The superseded sb->sv attempt, measured on ``route_data2.gds`` (the state
   before this increment drew anything). Column x=52.0 sits inside the
   sb->sv inter-instance gap and has a clean vdd/vss/clk/rst_n/ro1/ro2/ro3
   profile below y=21.0 -- EXCEPT for an array-internal met1 bar
   (x 47.01..213.08, y 20.125..20.295) this increment had not anticipated,
   which sits only 0.64 um below ro3's own y=19.4 leg -- too narrow for a
   0.42 um via pad plus 0.14 um clearance on both sides (0.70 um needed).
   That is why the strap this increment actually drew moves east instead of
   hunting for a narrower via at the same column.

B. The chosen sr2->sr3 gap, measured on the same pre-increment stream. x=214.5
   is on the array's own east vdd/vss riser (verified against
   ``layout/ro_array_core/cell.json``'s own ``vssbus`` stage coordinates, not
   by visual inspection); x=218.0 sits inside the sr2->sr3 inter-instance gap,
   east of the array-internal met1 bar and of ro1's/ro2's own channel hauls
   entirely, with a clean profile the whole way down to the vss rail.

Usage (from this directory)::

    python3 vss-strap-scan.py            # -> vss-strap-scan.json
"""

from __future__ import annotations

import json
import pathlib
import sys

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent
ARRAY_CELL_JSON = HERE.parent / "ro_array_core" / "cell.json"

sys.path.insert(0, str(HERE))
from _geom_common import merge_spans, merged  # noqa: E402

MET1 = (68, 20)
MET2 = (69, 20)

#: sky130 met1/met2 minimum space, and the via landing pad ``gen-compose``
#: draws -- the two numbers the "no via fits" arithmetic below is made of.
MIN_SPACE_UM = 0.14
VIA_PAD_UM = 0.42

#: The array's own y offset in this cell (``place_array``'s own origin).
ARRAY_ORIGIN_Y_UM = 23.635

#: The superseded attempt's own column (sb->sv gap) and what it expected /
#: what it actually found.
GAP1_X_UM = 52.0
GAP1_EXPECTED_MET1 = [(-3.585, -3.415), (6.915, 7.085)]
GAP1_EXPECTED_MET2 = [(-1.785, -1.615), (4.915, 5.085), (16.915, 17.085), (18.515, 18.685), (19.315, 19.485)]
GAP1_ARRAY_BAR_MET1 = (20.125, 20.295)
GAP1_ARRAY_BAR_X_RANGE_UM = (47.01, 213.08)
GAP1_RO3_TOP_EDGE_UM = 19.485

#: The chosen column (sr2->sr3 gap) and its tap on the array's own riser.
GAP4_X_UM = 218.0
GAP4_TAP_X_UM = 214.5
GAP4_EXPECTED_MET1 = [(-3.585, -3.415), (6.915, 7.085)]
GAP4_EXPECTED_MET2 = [(-1.785, -1.615), (4.915, 5.085), (13.515, 13.685), (14.915, 15.085)]

#: The strap's own port coordinates (composed frame), per stage.
VSS_TAP_UM = (214.5, 25.0)
VSS_DIP_UM = (218.0, 19.9)
VSS_PRE_VDD_UM = (218.0, 7.65)
VSS_POST_VDD_UM = (218.0, 6.35)
VSS_RAIL_TAP_UM = (218.0, -3.5)


def column_spans(region: db.Region, dbu: float, x: float, y0: float, y1: float) -> list:
    """Merged occupied y-intervals in a thin column at ``x``."""
    window = db.Region(db.Box(db.DBox(x - 0.005, y0, x + 0.005, y1) * (1 / dbu)))
    hit = region & window
    spans = sorted(
        (round(p.bbox().bottom * dbu, 4), round(p.bbox().top * dbu, 4)) for p in hit.each()
    )
    return merge_spans(spans)


def touches(region: db.Region, dbu: float, x: float, y: float) -> bool:
    """Is ``(x, y)`` inside (or on the edge of) ``region``?"""
    point = db.Region(db.Box(db.DBox(x - 0.001, y - 0.001, x + 0.001, y + 0.001) * (1 / dbu)))
    return not (region & point).is_empty()


def scan_array_riser_port() -> dict:
    """The array's own ``vssbus`` stage: confirm x=214.5 is really on it."""
    spec = json.loads(ARRAY_CELL_JSON.read_text())
    vssbus = next(s for s in spec["stages"] if s["name"] == "vssbus")
    legs = [
        (leg["net"], leg.get("waypoints_um"))
        for leg in vssbus["connectivity"]
        if leg["net"] == "vss"
    ]
    on_riser_leg = None
    for _, waypoints in legs:
        if not waypoints or len(waypoints) < 2:
            continue
        xs = {p[0] for p in waypoints}
        if GAP4_TAP_X_UM in xs:
            on_riser_leg = waypoints
    return {
        "vss_legs": legs,
        "tap_x_um": GAP4_TAP_X_UM,
        "tap_is_on_a_declared_vss_leg": on_riser_leg is not None,
        "leg_waypoints_um": on_riser_leg,
        "array_origin_y_um": ARRAY_ORIGIN_Y_UM,
        "composed_y_range_um": (
            [round(w[1] + ARRAY_ORIGIN_Y_UM, 4) for w in on_riser_leg]
            if on_riser_leg
            else None
        ),
    }


def scan_gap1() -> dict:
    """Group A -- the superseded sb->sv attempt, on ``route_data2.gds``."""
    layout = db.Layout()
    layout.read(str(HERE / "route_data2.gds"))
    cell = layout.top_cell()
    dbu = layout.dbu
    met1 = merged(layout, cell, MET1)
    met2 = merged(layout, cell, MET2)

    m1 = column_spans(met1, dbu, GAP1_X_UM, -4.0, 21.0)
    m2 = column_spans(met2, dbu, GAP1_X_UM, -4.0, 21.0)
    bar_region = met1 & db.Region(
        db.Box(
            db.DBox(GAP1_ARRAY_BAR_X_RANGE_UM[0], 19.9, GAP1_ARRAY_BAR_X_RANGE_UM[1] + 5.0, 20.6)
            * (1 / dbu)
        )
    )
    bar_extent = (
        [round(bar_region.bbox().left * dbu, 4), round(bar_region.bbox().right * dbu, 4)]
        if not bar_region.is_empty()
        else None
    )
    window_um = round(20.125 - GAP1_RO3_TOP_EDGE_UM, 4)
    via_needs_um = round(VIA_PAD_UM + 2 * MIN_SPACE_UM, 4)

    return {
        "x_um": GAP1_X_UM,
        "met1_spans": m1,
        "met2_spans": m2,
        "met1_matches_expected_plus_one_bar": (
            len(m1) == len(GAP1_EXPECTED_MET1) + 1
            and all(a == list(b) for a, b in zip(sorted(m1[:2]), sorted(GAP1_EXPECTED_MET1)))
        ),
        "met2_matches_expected": [list(x) for x in GAP1_EXPECTED_MET2] == m2[: len(GAP1_EXPECTED_MET2)],
        "array_bar_present": GAP1_ARRAY_BAR_MET1 in [tuple(x) for x in m1],
        "array_bar_x_extent_um": bar_extent,
        "array_bar_spans_the_whole_gap": bar_extent is not None
        and bar_extent[0] <= GAP1_ARRAY_BAR_X_RANGE_UM[0] + 0.1
        and bar_extent[1] >= GAP1_ARRAY_BAR_X_RANGE_UM[1] - 0.1,
        "window_between_ro3_and_bar_um": window_um,
        "via_pad_plus_clearance_needed_um": via_needs_um,
        "window_too_narrow_for_a_via": window_um < via_needs_um,
    }


def scan_gap4() -> dict:
    """Group B -- the chosen sr2->sr3 column, on the same pre-increment stream."""
    layout = db.Layout()
    layout.read(str(HERE / "route_data2.gds"))
    cell = layout.top_cell()
    dbu = layout.dbu
    met1 = merged(layout, cell, MET1)
    met2 = merged(layout, cell, MET2)

    m1 = column_spans(met1, dbu, GAP4_X_UM, -4.0, 21.0)
    m2 = column_spans(met2, dbu, GAP4_X_UM, -4.0, 21.0)

    riser_hit = touches(met2, dbu, *VSS_TAP_UM)
    riser_region = merged(layout, cell, MET2) & db.Region(
        db.Box(db.DBox(213.0, 20.0, 216.0, 35.0) * (1 / dbu))
    )
    riser_extent = (
        [
            round(riser_region.bbox().bottom * dbu, 4),
            round(riser_region.bbox().top * dbu, 4),
        ]
        if not riser_region.is_empty()
        else None
    )

    return {
        "x_um": GAP4_X_UM,
        "met1_spans": m1,
        "met2_spans": m2,
        "met1_matches_expected": [list(x) for x in GAP4_EXPECTED_MET1] == m1,
        "met2_matches_expected": [list(x) for x in GAP4_EXPECTED_MET2] == m2,
        "no_array_bar_here": GAP1_ARRAY_BAR_MET1 not in [tuple(x) for x in m1],
        "vss_tap_lands_on_the_risers_own_metal": riser_hit,
        "riser_composed_y_extent_um": riser_extent,
    }


def scan_final() -> dict:
    """The composed result: DRC-clean, device count stable, strap merged."""
    drc = json.loads((HERE / "drc.json").read_text())
    extract = json.loads((HERE / "extract.json").read_text())
    nets = [n if isinstance(n, str) else n.get("name") for n in extract["nets"]]

    def carrying(*tokens: str) -> list[str]:
        return [n for n in nets if all(token in n.split("|") for token in tokens)]

    return {
        "drc_status": drc["status"],
        "drc_violation_count": drc["violation_count"],
        "device_count": extract["device_count"],
        "net_count": extract["net_count"],
        "strap_segments_on_the_merged_vss_net": carrying("vss_link"),
        "sampler_vss_on_the_same_net_as_the_strap": carrying("vss_link", "sb_vss"),
        "array_vss_tap_on_the_same_net_as_the_strap": carrying("vss_link", "vss_x3"),
    }


def main() -> int:
    riser_port = scan_array_riser_port()
    gap1 = scan_gap1()
    gap4 = scan_gap4()
    final = scan_final()

    claims = {
        "riser_tap_x_is_on_a_declared_vss_leg": riser_port["tap_is_on_a_declared_vss_leg"],
        "gap1_has_the_array_internal_met1_bar": gap1["array_bar_present"],
        "gap1_bar_spans_the_whole_gap": gap1["array_bar_spans_the_whole_gap"],
        "gap1_window_too_narrow_for_a_via": gap1["window_too_narrow_for_a_via"],
        "gap4_has_no_array_internal_bar": gap4["no_array_bar_here"],
        "gap4_met1_matches_expected": gap4["met1_matches_expected"],
        "gap4_met2_matches_expected": gap4["met2_matches_expected"],
        "vss_tap_lands_on_the_risers_own_metal": gap4["vss_tap_lands_on_the_risers_own_metal"],
        "drc_clean": final["drc_status"] == "clean" and final["drc_violation_count"] == 0,
        "device_count_unchanged_at_264": final["device_count"] == 264,
        # 153 until the vdd strap (PR #113) merged the array's and the sampler's
        # `vdd` into one net; 152 is the current intentional baseline.
        "net_count_is_152_after_the_vdd_strap": final["net_count"] == 152,
        "strap_is_part_of_the_merged_vss_net": (
            len(final["strap_segments_on_the_merged_vss_net"]) == 1
            and final["strap_segments_on_the_merged_vss_net"]
            == final["sampler_vss_on_the_same_net_as_the_strap"]
            == final["array_vss_tap_on_the_same_net_as_the_strap"]
        ),
    }

    report = {
        "all_claims_hold": all(claims.values()),
        "claims": claims,
        "array_riser_port": riser_port,
        "gap1_superseded_attempt": gap1,
        "gap4_chosen_column": gap4,
        "strap_ports_composed_frame_um": {
            "vss_tap": VSS_TAP_UM,
            "vss_dip": VSS_DIP_UM,
            "vss_pre_vdd": VSS_PRE_VDD_UM,
            "vss_post_vdd": VSS_POST_VDD_UM,
            "vss_rail_tap": VSS_RAIL_TAP_UM,
        },
        "final_result": final,
    }
    (HERE / "vss-strap-scan.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_claims_hold": report["all_claims_hold"], "claims": claims}, indent=2))
    return 0 if report["all_claims_hold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
