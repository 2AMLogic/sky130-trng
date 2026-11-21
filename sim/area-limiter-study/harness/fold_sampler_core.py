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


def _port_map() -> dict:
    """Every named port in the committed recipe -> (x, y) in the composed
    cell's own frame (later stages' declarations win; coordinates agree)."""
    ports = {}
    for stage in SAMPLER_CORE["stages"]:
        for blk in stage["blocks"]:
            for p in blk["cell"].get("ports", []):
                ports[p["name"]] = (p["x_um"], p["y_um"])
    return ports


def _polyline_len(pts: list) -> float:
    return sum(abs(b[0] - a[0]) + abs(b[1] - a[1])
               for a, b in zip(pts, pts[1:]))


def _manhattan(a: tuple, b: tuple) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# F1 placement: row A = sb, sv, sr1 (origins unchanged, y = 0); row B =
# sr2, sr3, sr4 moved to the row-A x origins 0 / 55.66 / 111.32 at y = one
# committed row offset; the ring array moves up by one more row offset.
F1_SAMPLER_MOVE = {          # instance -> (dx, dy) applied to its own ports
    "sr2": (0.0 - 166.98, ARRAY_OFFSET_Y_UM),
    "sr3": (55.66 - 222.64, ARRAY_OFFSET_Y_UM),
    "sr4": (111.32 - 278.3, ARRAY_OFFSET_Y_UM),
}
F1_ARRAY_MOVE = (0.0, ARRAY_OFFSET_Y_UM)

# data hauls: (net, array-side port, sampler-side port, sampler instance;
# None = row A / unmoved), taken from the route_data / route_data2 stages.
DATA_NETS = (
    ("ro1", "ro1_esc_m1", "sr1_d_m1", None),
    ("ro2", "ro2_esc_m1", "sr2_d_m1", "sr2"),
    ("ro3", "ro3_esc_m1", "sr3_d_m1", "sr3"),
    ("ro4", "ro4_esc_m1", "sr4_d_m1", "sr4"),
    ("xo", "xo_dip_w", "sb_d_m1", None),
)
# the one detour the folded endpoints force that the unfolded recipe did
# not need: ro1's array tap now sits above row B, so its descent moves from
# the committed x = -0.5 lane to the free west margin lane (x = -2.0, the
# only met2 band clear over the array height, route_data2 comment) and back:
ASSUMED_DETOUR_RO1_UM = 2 * 1.5


def f1_routing() -> dict:
    """Recompute F1's added routing from the folded net endpoints.

    Each haul's length is modelled as the Manhattan distance between its
    (moved) endpoints plus the detour excess the committed polyline already
    carried over its own endpoint Manhattan distance (only ``xo`` has one).
    """
    ports = _port_map()
    waypoints = {}
    for stage in SAMPLER_CORE["stages"]:
        for net in stage["connectivity"]:
            if "waypoints_um" in net and net["net"] in {n[0] for n in DATA_NETS}:
                waypoints[net["net"]] = net["waypoints_um"]
    nets = []
    for name, arr_port, smp_port, inst in DATA_NETS:
        a0, s0 = ports[arr_port], ports[smp_port]
        a1 = (a0[0] + F1_ARRAY_MOVE[0], a0[1] + F1_ARRAY_MOVE[1])
        dx, dy = F1_SAMPLER_MOVE.get(inst, (0.0, 0.0))
        s1 = (s0[0] + dx, s0[1] + dy)
        orig = _polyline_len(waypoints[name])
        excess = orig - _manhattan(a0, s0)
        folded = _manhattan(a1, s1) + excess
        assumed = ASSUMED_DETOUR_RO1_UM if name == "ro1" else 0.0
        nets.append({
            "net": name,
            "unfolded_um": round(orig, 3),
            "unfolded_vertical_um": round(abs(a0[1] - s0[1]), 3),
            "unfolded_horizontal_um": round(abs(a0[0] - s0[0]), 3),
            "folded_vertical_um": round(abs(a1[1] - s1[1]), 3),
            "folded_horizontal_um": round(abs(a1[0] - s1[0]), 3),
            "retained_detour_excess_um": round(excess, 3),
            "folded_um": round(folded, 3),
            "assumed_detour_um": assumed,
            "delta_um": round(folded - orig + assumed, 3),
        })
    data_delta = round(sum(n["delta_um"] for n in nets), 3)

    # supplies / control. Row-B rails and clk/rst_n runs each need a riser to
    # row A (one row offset per net: vdd, vss, clk, rst_n); the committed
    # array supply straps land on the sampler rails at x = 213.7 / 218.0,
    # east of the folded rows' rail end (row A: 111.32 + sampler_dff x1), so
    # they re-tap row B's rails (same vertical span as before, because the
    # array and row B move together) and gain the horizontal run to that end.
    rail_end = SAMPLER_ORIGINS[2] + _bbox(SAMPLER_DFF_RESP)["x1"]
    strap_east = round(
        (ports["vdd_rail_tap"][0] - rail_end)
        + (ports["vss_rail_tap"][0] - rail_end), 3)
    risers = round(4 * ARRAY_OFFSET_Y_UM, 3)
    # the six-sampler rail / clk / rst_n chains (4 nets x 5 legs) become two
    # chains of 2 legs: one 55.66 um leg fewer per net
    chain_saved = round(-4 * SAMPLER_PITCH_UM, 3)
    gross_added = round(
        sum(n["delta_um"] for n in nets if n["delta_um"] > 0)
        + strap_east + risers, 3)
    net_total = round(data_delta + strap_east + risers + chain_saved, 3)
    return {
        "model": "per-net Manhattan length between the folded endpoints "
                 "(committed port coordinates; sampler row B moved to the "
                 "row-A x origins one row offset up, array one more row "
                 "offset up) plus the committed polyline's own detour excess",
        "nets": nets,
        "data_nets_net_delta_um": data_delta,
        "supply_strap_horizontal_extension_um": strap_east,
        "row_risers_um": risers,
        "rail_and_control_chain_saving_um": chain_saved,
        "gross_added_um": gross_added,
        "net_total_um": net_total,
        "assumed_detours": [
            f"ro1 descends the west margin lane (x = -2.0) instead of the "
            f"committed x = -0.5 column, +{ASSUMED_DETOUR_RO1_UM} um",
            "the supply straps re-tap row B's rails at their east end "
            f"(x = {rail_end:.2f}); a vss/vdd rail extension beyond the row "
            "end is assumed legal -- no DRC was run",
        ],
        "not_modelled": "via counts, layer-change delays, track congestion "
                        "in the new row-A/row-B gap, and timing/coupling "
                        "effects of the shorter or longer data hauls",
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
        "routing": f1_routing(),
        "ring_row_unchanged": True,
        "symmetry_verdict": "survives by construction: the four rings keep "
                            "their committed single-row arrangement, pitch and "
                            "per-ring vddr1..vddr4 rails byte-for-byte",
        "supply_verdict": "vddr1..vddr4 per-ring rails unchanged; the shared "
                          "vdd/vss straps and the clk/rst_n lanes need one "
                          "extra horizontal run per folded row plus two "
                          "vertical risers each (met1/met2, same style as the "
                          "committed strap stages)",
        "added_routing_estimate": "see routing (recomputed from the folded "
                                  "endpoints)",
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
