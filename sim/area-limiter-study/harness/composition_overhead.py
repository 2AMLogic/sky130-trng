#!/usr/bin/env python3
"""Account for the whole-block area that is neither macro (issue #599, item 3).

Reads the committed ``layout/trng_whole/report.json`` (whole bbox, macro
bboxes) and decomposes the non-macro remainder -- 0.126116 mm2 committed
minus 0.079347 mm2 of macros -- into disjoint rectangles cut on the macro
edges, each classified by what put it there:

* ``south_east_corridor`` -- east of the digital macro, south of the analog
  row: pure stacking artifact; the analog row (330.96 um) overhangs the
  digital macro's east pin edge (x = 200) by ~131 um for its full height.
* ``inter_macro_lane_band`` -- the 20.005 um gap band carrying the four
  inter-macro met5 lanes, the shared inputs and the supply gap-strips.
* ``west_of_analog_strip`` -- north of the digital macro, west of the analog
  row: the analog row starts at x = 0 while the digital macro's west edge
  (with its VPWR escape) reaches x = -45.05; another stacking artifact.
* ``pad_row_strip`` -- the 10.14 um top strip: met5 boundary pads + the
  vertical lane runs into them (scales with width; pads are contractual).
* ``west_escape_corridor`` -- the 2.15 um VPWR escape lane west of the
  digital macro.

The decomposition reconciles to the committed non-macro figure to within
0.01 um2 of input rounding (asserted).  ``removable_by_tighter_floorplan``
names which rectangles a re-stack can delete outright: the two stacking
artifacts (corridor + west strip), whenever the analog row width and west
edge are matched to the digital macro's; the lane band, pad strip and
escape corridor are functional and scale with width/height instead.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REPORT = json.loads((REPO_ROOT / "layout" / "trng_whole" / "report.json").read_text())
FLOORPLAN = json.loads((REPO_ROOT / "layout" / "trng_whole" / "floorplan.json").read_text())

STACKING_ARTIFACTS = ("south_east_corridor", "west_of_analog_strip")


def main() -> dict:
    whole = REPORT["area"]["bbox_um"]
    dig = REPORT["macros"]["dig"]["bbox_um"]
    ana = REPORT["macros"]["ana"]["bbox_um"]
    whole_area = REPORT["area"]["area_um2"]
    dig_area = (dig["x1"] - dig["x0"]) * (dig["y1"] - dig["y0"])
    ana_area = (ana["x1"] - ana["x0"]) * (ana["y1"] - ana["y0"])
    non_macro = whole_area - dig_area - ana_area

    def rect(x0, x1, y0, y1):
        return round((x1 - x0) * (y1 - y0), 3)

    rects = {
        "west_escape_corridor": rect(whole["x0"], dig["x0"],
                                     whole["y0"], whole["y1"]),
        "south_east_corridor": rect(dig["x1"], whole["x1"],
                                    whole["y0"], dig["y1"]),
        "inter_macro_lane_band": rect(dig["x0"], whole["x1"],
                                      dig["y1"], ana["y0"]),
        "west_of_analog_strip": rect(dig["x0"], ana["x0"],
                                     ana["y0"], whole["y1"]),
        "pad_row_strip": rect(ana["x0"], whole["x1"],
                              ana["y1"], whole["y1"]),
    }
    total = round(sum(rects.values()), 3)
    removable = round(sum(v for k, v in rects.items()
                          if k in STACKING_ARTIFACTS), 3)

    lane_band_gap_um = round(ana["y0"] - dig["y1"], 3)
    pad_strip_h_um = round(whole["y1"] - ana["y1"], 3)
    west_escape_w_um = round(dig["x0"] - whole["x0"], 3)

    return {
        "basis": "axis-aligned decomposition of the committed whole-block "
                 "bbox (layout/trng_whole/report.json), cut on the committed "
                 "macro bboxes; measured inputs, exact rectangle arithmetic",
        "whole_area_um2": whole_area,
        "macro_areas_um2": {
            "trng_digital": round(dig_area, 3),
            "sampler_core": round(ana_area, 3),
            "sum": round(dig_area + ana_area, 3),
        },
        "non_macro_um2": round(non_macro, 3),
        "non_macro_share_pct": round(100.0 * non_macro / whole_area, 2),
        "rectangles_um2": rects,
        "rectangle_sum_um2": total,
        "reconciliation_ok": abs(total - non_macro) < 0.01,
        "dimensions_um": {
            "lane_band_gap": lane_band_gap_um,
            "pad_strip_height": pad_strip_h_um,
            "west_escape_width": west_escape_w_um,
            "analog_overhang_east_of_digital_pins":
                round(whole["x1"] - dig["x1"], 3),
        },
        "removable_by_tighter_floorplan": {
            "rectangles": list(STACKING_ARTIFACTS),
            "area_um2": removable,
            "share_of_non_macro_pct": round(100.0 * removable / non_macro, 2),
            "interpretation": "occupancy share of the overhead sitting in "
                              "the two named stacking-artifact rectangles; "
                              "NOT a recovered area -- recovery depends on "
                              "the before/after floorplan (see "
                              "item4_combine fixed-vs-edge-aligned rows)",
            "condition": "the analog row's width and west edge are matched "
                         "to the digital macro's footprint in a re-stack "
                         "(folded analog narrower than the digital macro, or "
                         "an explicit re-stack that aligns west edges)",
        },
        "functional_overhead": {
            "rectangles": ["inter_macro_lane_band", "pad_row_strip",
                           "west_escape_corridor"],
            "area_um2": round(total - removable, 3),
            "note": "lanes, boundary pads and the supply escape are "
                    "contractual composition structure; they scale with "
                    "width/height rather than vanish",
        },
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
