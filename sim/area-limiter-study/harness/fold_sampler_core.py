#!/usr/bin/env python3
"""Estimate a two-row (folded) sampler_core arrangement from the committed
cell recipe's own geometry (issue #599, item 2).

This is a **placement dry run**: pure bbox arithmetic over the committed
compose geometry (``layout/sampler_core/cell.json``'s place/place_array
origins, ``layout/sampler_dff/compose.response.json``'s and
``layout/ro_array_core/compose.response.json``'s bboxes).  No GDS is
composed, no DRC/LVS run -- every figure is labelled an estimate in the
record.

Fold F1 (the recommended estimate): the six-sampler bank -- the width
driver at 55.66 um pitch -- is folded into two rows of three; the
ro_array_core ring row keeps its committed internal geometry byte-for-byte
(all four rings in one row at the 55.3 um pitch DR-0003 draws), so the
ring-to-ring arrangement the decision records describe survives by
construction.  Inter-row offsets reuse the recipe's own committed
inter-row separation (the array sits 23.635 um above the sampler row).

Fold F2 (secondary, risk-flagged): also fold the ring array into a 2x2
grid.  Recorded because it halves the analog width further, but the
vertical ring adjacency it introduces is new coupling geometry no record
measures; DR-0003 section 8's decorrelation caveat applies unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

SAMPLER_CORE = json.loads(
    (REPO_ROOT / "layout" / "sampler_core" / "cell.json").read_text())
SAMPLER_DFF_RESP = json.loads(
    (REPO_ROOT / "layout" / "sampler_dff" / "compose.response.json").read_text())
ARRAY_RESP = json.loads(
    (REPO_ROOT / "layout" / "ro_array_core" / "compose.response.json").read_text())

SAMPLER_PITCH_UM = 55.66          # cell.json 'place' stage
SAMPLER_ORIGINS = [0.0, 55.66, 111.32, 166.98, 222.64, 278.3]
ARRAY_OFFSET_Y_UM = 23.635        # cell.json 'place_array' stage


def _bbox(resp: dict) -> dict:
    b = resp["bbox_um"]
    return {"x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"]}


def _span(b: dict) -> tuple[float, float]:
    return b["x1"] - b["x0"], b["y1"] - b["y0"]


def current_arrangement() -> dict:
    dff = _bbox(SAMPLER_DFF_RESP)
    arr = _bbox(ARRAY_RESP)
    core_w = SAMPLER_ORIGINS[-1] + dff["x1"] - dff["x0"] - 0 + abs(dff["x0"])
    # committed sampler_core bbox (compose.response.json of sampler_core):
    core_resp = json.loads((REPO_ROOT / "layout" / "sampler_core" /
                            "compose.response.json").read_text())
    core = _bbox(core_resp)
    return {
        "sampler_dff_bbox": dff,
        "ro_array_core_bbox": arr,
        "sampler_core_bbox": core,
        "width_um": round(core["x1"] - core["x0"], 3),
        "height_um": round(core["y1"] - core["y0"], 3),
        "area_um2": round((core["x1"] - core["x0"]) * (core["y1"] - core["y0"]), 3),
    }


def fold_f1() -> dict:
    """Samplers in two rows of three; ring array row unchanged on top."""
    dff = _bbox(SAMPLER_DFF_RESP)
    arr = _bbox(ARRAY_RESP)
    offset = ARRAY_OFFSET_Y_UM
    # row A: sb, sv, sr1 at origins 0 / 55.66 / 111.32
    row_a_x1 = SAMPLER_ORIGINS[2] + dff["x1"]
    x0 = min(dff["x0"], arr["x0"], 0.0)
    x1 = max(row_a_x1, arr["x1"])
    width = x1 - x0
    # rows: A at y=0, B at y=offset, array at y=2*offset (the recipe's own
    # committed inter-row separation, reused verbatim)
    y0 = min(dff["y0"], arr["y0"], 0.0)
    array_top = 2 * offset + arr["y1"]
    height = array_top - y0
    return {
        "description": "six samplers folded into two rows of three; "
                       "ro_array_core ring row geometry unchanged (all four "
                       "rings in one committed row, 55.3 um pitch)",
        "width_um": round(width, 3),
        "height_um": round(height, 3),
        "area_um2": round(width * height, 3),
        "row_a_x1": round(row_a_x1, 3),
        "array_offset_y_um": 2 * ARRAY_OFFSET_Y_UM,
        "ring_row_unchanged": True,
        "symmetry_verdict": "survives by construction: the four rings keep "
                            "their committed single-row arrangement, pitch and "
                            "per-ring vddr1..vddr4 rails byte-for-byte",
        "supply_verdict": "vddr1..vddr4 per-ring rails unchanged; the shared "
                          "vdd/vss straps and the clk/rst_n lanes need one "
                          "extra horizontal run per folded row plus two "
                          "vertical risers each (met1/met2, same style as the "
                          "committed strap stages)",
        "added_routing_estimate": "+~50 um (strap risers) +~24 um (clk lane "
                                  "riser) +~24 um (rst_n riser) +~120 um "
                                  "(sr2..sr4 d/q routes lengthen by the "
                                  "23.635 um row offset) = +~220 um total, no "
                                  "new routing role",
    }


def fold_f2() -> dict:
    """Also fold the ring array into a 2x2 grid (risk-flagged secondary).

    Vertical ring pitch = the committed horizontal pitch (55.3 um), so the
    grid's spacing is uniform; buffers and the xor tree sit beside the grid
    in the space the committed row already reserved for them.
    """
    dff = _bbox(SAMPLER_DFF_RESP)
    arr = _bbox(ARRAY_RESP)
    offset = ARRAY_OFFSET_Y_UM
    ring_pitch = 55.3
    ring_w = arr["x1"] - 168.09          # committed ring extent in the row
    ring_h = arr["y1"] - arr["y0"]
    grid_w = ring_pitch + ring_w
    samplers_w = SAMPLER_ORIGINS[2] + dff["x1"] - min(dff["x0"], 0.0)
    width = max(grid_w, samplers_w)
    # samplers (two rows) then the ring grid above the same committed gap
    row_b_top = offset + dff["y1"]
    committed_gap = offset + arr["y0"] - dff["y1"]   # 13.04 um
    grid_bottom = row_b_top + committed_gap
    grid_top = grid_bottom + ring_pitch + ring_h
    y0 = min(dff["y0"], 0.0)
    height = grid_top - y0
    return {
        "description": "samplers 3+3 AND the four rings in a 2x2 grid (equal "
                       "55.3 um pitch both axes); buffers and xor tree beside "
                       "the grid",
        "width_um": round(width, 3),
        "height_um": round(height, 3),
        "area_um2": round(width * height, 3),
        "ring_row_unchanged": False,
        "symmetry_verdict": "does NOT survive verbatim: every ring gains a "
                            "vertical neighbour no committed record measures; "
                            "DR-0003 section 8's decorrelation caveat applies "
                            "to the new adjacency",
        "supply_verdict": "vddr rails per ring unchanged, but the rail routing "
                          "and the well/strap pattern between grid rows are "
                          "new geometry",
        "added_routing_estimate": "strap/lane doubling as F1 plus re-plumbed "
                                  "ring-to-xor routes; not derived further -- "
                                  "recorded as the wider/lower-confidence "
                                  "alternative",
    }


def main() -> dict:
    cur = current_arrangement()
    f1 = fold_f1()
    f2 = fold_f2()
    for fold in (f1, f2):
        fold["delta_area_um2"] = round(
            fold["area_um2"] - cur["area_um2"], 3)
        fold["delta_width_um"] = round(
            fold["width_um"] - cur["width_um"], 3)
        fold["delta_height_um"] = round(
            fold["height_um"] - cur["height_um"], 3)
        fold["area_mm2"] = round(fold["area_um2"] / 1e6, 6)
    return {
        "committed_sampler_core": cur,
        "fold_f1": f1,
        "fold_f2": f2,
        "basis": "placement dry run: bbox arithmetic over the committed "
                 "compose geometry (cell.json origins, compose.response.json "
                 "bboxes); no GDS composed, no DRC/LVS run",
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
