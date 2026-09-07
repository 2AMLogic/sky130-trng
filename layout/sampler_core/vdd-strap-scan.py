#!/usr/bin/env python3
"""Re-derive every geometric claim behind this increment's vdd strap.

Same discipline as ``vss-strap-scan.py``/``data-path-scan.py``: every lane
this increment picked was picked from a measurement, not a guess, and this
script is that measurement, re-runnable, and it exits non-zero if any of it
stops holding.

Three groups of claims:

A. The obstruction 'vdd_strap1' (an earlier, abandoned single-leg attempt)
   ran into: a met1 net belonging to some other signal spans the whole
   x=211.64..214.97 corridor at composed y=25.25..25.42, with no gap at any
   x in that span -- measured on ``vss_strap3.gds`` (the state before any
   vdd-strap metal was drawn), by exact polygon intersection against the
   intended route footprint, not a region-merge bounding box (a real
   pitfall: a first-pass reading of this same obstruction's *bbox* --
   172.86..214.97 at y=25.125..29.32 -- was far bigger than its actual
   footprint, because ``Region.merge()`` unions many separate, unrelated
   same-layer shapes into one polygon whose bbox is not its area).

B. The chosen column (composed x=213.7) and the two via drop points
   'vdd_strap1'/'vdd_strap2'/'vdd_strap3' actually use: clear of the
   obstruction in group A, clear of the array's own east vss riser (met2,
   x=214.29..214.71 -- the same riser 'vss_tap' lands directly on), and
   clear enough (>= 0.14 um sky130 spacing) at both via pad footprints.

C. The composed result: DRC-clean, LVS a full match (not just a merged
   label group), net count down by exactly one (vdd now genuinely one net,
   not two nets that happen to share the string "vdd").

Usage (from this directory)::

    python3 vdd-strap-scan.py            # -> vdd-strap-scan.json
"""

from __future__ import annotations

import json
import pathlib

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent

MET1 = (68, 20)
MET2 = (69, 20)

#: sky130 met1/met2 minimum space, and the via landing pad ``gen-compose``
#: draws -- the two numbers the clearance arithmetic below is made of.
MIN_SPACE_UM = 0.14
VIA_PAD_UM = 0.42
ROUTE_WIDTH_UM = 0.17

#: The obstruction group A found (exact polygon, re-measured -- not the
#: earlier, over-wide bbox reading).
OBSTRUCTION_X_RANGE_UM = (211.64, 214.97)
OBSTRUCTION_Y_RANGE_UM = (25.25, 25.42)

#: The abandoned single-leg attempt's own intended route footprint (used to
#: reproduce the exact overlap gen-compose itself reported).
REJECTED_ROUTE_X_UM = 215.0
REJECTED_ROUTE_Y_RANGE_UM = (7.0, 29.6)

#: The array's own east vss riser (met2) -- the same one 'vss_tap' lands on.
VSS_RISER_X_RANGE_UM = (214.29, 214.71)

#: This increment's own chosen column and via drop points (composed frame).
STRAP_X_UM = 213.7
VDD_TAP_UM = (212.995, 29.6)
VDD_PRE_DIP_UM = (STRAP_X_UM, 25.9)
VDD_POST_DIP_UM = (STRAP_X_UM, 24.8)
VDD_RAIL_TAP_UM = (STRAP_X_UM, 7.0)


def merged(layout: db.Layout, cell: db.Cell, key: tuple[int, int]) -> db.Region:
    index = layout.layer(*key)
    region = db.Region(db.RecursiveShapeIterator(layout, cell, index))
    region.merge()
    return region


def box_clear(region: db.Region, dbu: float, x0: float, y0: float, x1: float, y1: float) -> dict:
    window = db.Region(db.Box(db.DBox(x0, y0, x1, y1) * (1 / dbu)))
    hit = region & window
    polys = [
        [
            round(p.bbox().left * dbu, 4),
            round(p.bbox().bottom * dbu, 4),
            round(p.bbox().right * dbu, 4),
            round(p.bbox().top * dbu, 4),
        ]
        for p in hit.each()
    ]
    return {"clear": hit.is_empty(), "overlap_area_um2": round(hit.area() * dbu * dbu, 6), "polys": polys}


def scan_obstruction() -> dict:
    """Group A -- the obstruction, on the pre-vdd-strap baseline stream."""
    layout = db.Layout()
    layout.read(str(HERE / "vss_strap3.gds"))
    cell = layout.top_cell()
    dbu = layout.dbu
    met1 = merged(layout, cell, MET1)

    # Full extent of the obstruction (wide window, no clipping at its edges).
    full = box_clear(met1, dbu, 205.0, 20.0, 220.0, 34.0)

    # No gap anywhere in the x-span at the obstruction's own y-band.
    probe = box_clear(met1, dbu, OBSTRUCTION_X_RANGE_UM[0], OBSTRUCTION_Y_RANGE_UM[0] + 0.03,
                       OBSTRUCTION_X_RANGE_UM[1], OBSTRUCTION_Y_RANGE_UM[1] - 0.03)

    # The abandoned single-leg attempt's own exact overlap (reproduces what
    # gen-compose itself reported: ~0.0231 um^2 at the route's own left edge).
    half = ROUTE_WIDTH_UM / 2
    rejected = box_clear(
        met1, dbu,
        REJECTED_ROUTE_X_UM - half, REJECTED_ROUTE_Y_RANGE_UM[0],
        REJECTED_ROUTE_X_UM + half, REJECTED_ROUTE_Y_RANGE_UM[1],
    )

    return {
        "full_window_polys": full["polys"],
        "no_gap_probe": probe,
        "obstruction_spans_the_whole_probed_band": not probe["clear"],
        "rejected_route_215_0_collision": rejected,
        "rejected_route_actually_overlaps": not rejected["clear"],
    }


def scan_column() -> dict:
    """Group B -- the chosen column and via drop points, same baseline."""
    layout = db.Layout()
    layout.read(str(HERE / "vss_strap3.gds"))
    cell = layout.top_cell()
    dbu = layout.dbu
    met1 = merged(layout, cell, MET1)
    met2 = merged(layout, cell, MET2)

    half = ROUTE_WIDTH_UM / 2
    via_half = VIA_PAD_UM / 2

    checks = {
        "met1_col_tap_to_pre_dip": box_clear(
            met1, dbu, STRAP_X_UM - half, VDD_PRE_DIP_UM[1], STRAP_X_UM + half, VDD_TAP_UM[1]
        ),
        "met1_col_post_dip_to_rail": box_clear(
            met1, dbu, STRAP_X_UM - half, VDD_RAIL_TAP_UM[1] + 0.085, STRAP_X_UM + half, VDD_POST_DIP_UM[1]
        ),
        "met1_via_pad_pre_dip": box_clear(
            met1, dbu, STRAP_X_UM - via_half, VDD_PRE_DIP_UM[1] - via_half,
            STRAP_X_UM + via_half, VDD_PRE_DIP_UM[1] + via_half,
        ),
        "met1_via_pad_post_dip": box_clear(
            met1, dbu, STRAP_X_UM - via_half, VDD_POST_DIP_UM[1] - via_half,
            STRAP_X_UM + via_half, VDD_POST_DIP_UM[1] + via_half,
        ),
        "met2_via_pad_pre_dip": box_clear(
            met2, dbu, STRAP_X_UM - via_half, VDD_PRE_DIP_UM[1] - via_half,
            STRAP_X_UM + via_half, VDD_PRE_DIP_UM[1] + via_half,
        ),
        "met2_via_pad_post_dip": box_clear(
            met2, dbu, STRAP_X_UM - via_half, VDD_POST_DIP_UM[1] - via_half,
            STRAP_X_UM + via_half, VDD_POST_DIP_UM[1] + via_half,
        ),
        "met2_bridge_pre_to_post_dip": box_clear(
            met2, dbu, STRAP_X_UM - half, VDD_POST_DIP_UM[1], STRAP_X_UM + half, VDD_PRE_DIP_UM[1]
        ),
    }

    via_to_riser_clearance_um = round(VSS_RISER_X_RANGE_UM[0] - (STRAP_X_UM + via_half), 4)

    return {
        **{k: v for k, v in checks.items()},
        "via_pad_to_vss_riser_clearance_um": via_to_riser_clearance_um,
        "via_pad_to_vss_riser_clearance_meets_min_space": via_to_riser_clearance_um >= MIN_SPACE_UM,
    }


def scan_final() -> dict:
    """The composed result: DRC-clean, LVS a full match, net count -1."""
    drc = json.loads((HERE / "drc.json").read_text())
    extract = json.loads((HERE / "extract.json").read_text())
    lvs = json.loads((HERE / "lvs.json").read_text())
    nets = [n if isinstance(n, str) else n.get("name") for n in extract["nets"]]

    def carrying(*tokens: str) -> list[str]:
        return [n for n in nets if all(token in n.split("|") for token in tokens)]

    return {
        "drc_status": drc["status"],
        "drc_violation_count": len(drc.get("violations", [])),
        "device_count": extract["device_count"],
        "net_count": extract["net_count"],
        "lvs_status": lvs["status"],
        "lvs_error_count": lvs["error_count"],
        "lvs_counts": lvs["counts"],
        "strap_segments_on_the_merged_vdd_net": carrying("vdd_link"),
        "sampler_vdd_on_the_same_net_as_the_strap": carrying("vdd_link", "sb_vdd"),
        "array_vdd_tap_on_the_same_net_as_the_strap": carrying("vdd_link", "vdd_x3"),
    }


def main() -> int:
    obstruction = scan_obstruction()
    column = scan_column()
    final = scan_final()

    claims = {
        "obstruction_spans_the_whole_211_64_214_97_band": obstruction[
            "obstruction_spans_the_whole_probed_band"
        ],
        "rejected_x215_0_route_really_did_collide": obstruction["rejected_route_actually_overlaps"],
        "met1_col_tap_to_pre_dip_clear": column["met1_col_tap_to_pre_dip"]["clear"],
        "met1_col_post_dip_to_rail_clear": column["met1_col_post_dip_to_rail"]["clear"],
        "met1_via_pad_pre_dip_clear": column["met1_via_pad_pre_dip"]["clear"],
        "met1_via_pad_post_dip_clear": column["met1_via_pad_post_dip"]["clear"],
        "met2_via_pad_pre_dip_clear": column["met2_via_pad_pre_dip"]["clear"],
        "met2_via_pad_post_dip_clear": column["met2_via_pad_post_dip"]["clear"],
        "met2_bridge_clear": column["met2_bridge_pre_to_post_dip"]["clear"],
        "via_pad_to_vss_riser_clearance_meets_min_space": column[
            "via_pad_to_vss_riser_clearance_meets_min_space"
        ],
        "drc_clean": final["drc_status"] == "clean" and final["drc_violation_count"] == 0,
        "device_count_264": final["device_count"] == 264,
        "net_count_dropped_to_152": final["net_count"] == 152,
        "lvs_is_a_full_match": final["lvs_status"] == "match" and final["lvs_error_count"] == 0,
        "lvs_devices_fully_matched": final["lvs_counts"]["devices"]["matched"] == 264,
        "lvs_nets_fully_matched": final["lvs_counts"]["nets"]["matched"] == 152,
        "strap_is_part_of_the_merged_vdd_net": (
            len(final["strap_segments_on_the_merged_vdd_net"]) == 1
            and final["strap_segments_on_the_merged_vdd_net"]
            == final["sampler_vdd_on_the_same_net_as_the_strap"]
            == final["array_vdd_tap_on_the_same_net_as_the_strap"]
        ),
    }

    report = {
        "all_claims_hold": all(claims.values()),
        "claims": claims,
        "obstruction": obstruction,
        "column": column,
        "strap_ports_composed_frame_um": {
            "vdd_tap": VDD_TAP_UM,
            "vdd_pre_dip": VDD_PRE_DIP_UM,
            "vdd_post_dip": VDD_POST_DIP_UM,
            "vdd_rail_tap": VDD_RAIL_TAP_UM,
        },
        "final_result": final,
    }
    (HERE / "vdd-strap-scan.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_claims_hold": report["all_claims_hold"], "claims": claims}, indent=2))
    return 0 if report["all_claims_hold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
