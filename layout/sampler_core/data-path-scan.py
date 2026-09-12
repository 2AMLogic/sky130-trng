#!/usr/bin/env python3
"""Re-derive every geometric claim behind this increment's data-path routing.

Same discipline, and the same reason, as
``layout/ro_array_core/vss-tap-scan.py``: ``klt gen-compose`` models a placed
block as an opaque **bbox** with no obstacle model of that block's interior
conductors, so a leg that starts at an interior tap can run straight through
another net's metal and short to it *silently* -- ``unrouted_nets: []`` and
``klt drc`` clean, wrong only in ``klt extract``'s net list.  Every lane this
increment picked was picked from a measurement; this script is that
measurement, re-runnable, and it exits non-zero if any of it stops being true.

Five groups of claims:

A. ``sampler_dff``'s own ``d`` column, measured on ``route_ctrl.gds``
    The stage this increment builds on -- the six-instance bank with
    ``vdd``/``vss``/``clk``/``rst_n`` already routed, and no array yet.  For
    each of the six instances, at that instance's own ``d`` column
    (``origin_x + 6.665``, ``sampler_dff``'s own promoted ``d`` label):
    met1 is clear from ``y = 0.485`` to ``y = 6.915`` (between the in-cell
    ``clkb`` lane and the shared ``vdd`` rail), and met2 is clear above
    ``y = 5.085`` (above ``route_ctrl``'s own ``rst_n`` haul).  That is the
    whole "approach ``d`` from **above**" case: one met1 leg up the column,
    one met2 leg over the ``vdd`` rail, no weave.

    The same scan also records what is in the way *below* the pin -- the
    shared ``vss`` rail (met1, ``y = -3.5``), the shared ``clk`` lane (met2,
    ``y = -1.7``) and the in-cell ``clkb`` lane (met1, ``y = 0.4``) -- three
    obstacles on two layers, which is the "approach from **below**" case
    this floorplan rejects.

B. ``ro_array_core``'s own south escape columns, measured on
   ``../ro_array_core/ro_array_core.gds``
    For each of ``ro1``-``ro4``, every 0.05 um column over that net's own
    drawn horizontal run is tested for a met1 path from just under the run
    down past the array's own south edge.  ``ro1`` and ``ro4`` have one;
    ``ro2`` and ``ro3`` have **none** -- the three ``ro`` horizontals are
    stacked (``y`` = 8.0 / 8.5 / 9.0 / 10.0) and every column of ``ro2``'s
    own run is crossed by ``ro3``'s and/or ``ro4``'s, and every column of
    ``ro3``'s by ``ro4``'s.  That is why this increment routes two of the
    five data nets, not five.

C. The channel between the two blocks, measured on ``sampler_core.gds``
    Nothing but the data path's own legs is drawn in ``y`` 7.2..19.8 -- two
    met1 escape legs (``ro1``'s and ``ro4``'s) and exactly five met2 hauls,
    one per data net -- and each of them is where it was declared.

D. The electrical result, read from ``extract.json`` + ``sampler_core.spice``
    Each of the five data nets (``ro1``-``ro4``, ``xo``) is exactly one
    extracted net carrying the array's own promoted output label, every leg
    drawn for it, the sampler stub it ends on, and a sampler ``d`` pin; the
    ``<instance>_d_stub`` label that names the sampler end of each sits in
    that instance's own ``d`` column, so the connection lands on the intended
    instance, not merely on *an* instance.  No unconnected ``d`` net remains:
    ``sv``'s own ``d`` is tied to the sampler bank's ``vdd`` net (the
    schematic wires it to ``vdd``, not to the array), and the other five are
    driven.

E. The two margins, measured on ``route_data.gds`` -- the state *before* this
   increment drew anything
    ``ro2``/``ro3``/``xo`` cannot leave the array downward on met1 (group B),
    so they leave on met2 down one of the only two column bands that are free
    over the array's whole height (``x`` -2.1..1.65 and 215.05..220.0).  The
    east one is unreachable: the array's own east riser (met2) and ``ro4``'s
    own met1 escape leg leave a 0.605 um gap, and a met1<->met2 via needs
    0.42 + 2 x 0.14 = 0.70 um.  ``xo`` additionally has to pass *below*
    ``ro1``'s own channel haul, which only its own column (``x`` = -1.5) is
    west of; and its met2 route out of ``xa3`` has to step around ``xa2``'s
    own ``t2`` riser on met1, which is the one obstacle in that lane.

Usage (from this directory)::

    python3 data-path-scan.py            # -> data-path-scan.json
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent
ARRAY_GDS = HERE.parent / "ro_array_core" / "ro_array_core.gds"

sys.path.insert(0, str(HERE))
from _geom_common import merge_spans, merged  # noqa: E402

LI1 = (67, 20)
MET1 = (68, 20)
MET2 = (69, 20)

#: sampler_dff's own promoted ``d`` pad, in that cell's local frame.
D_LOCAL_X_UM = 6.665
D_LOCAL_Y_UM = 1.2
#: The six instance origins the ``place`` stage declared (55.66 um pitch).
INSTANCES = {
    "sb": 0.0,
    "sv": 55.66,
    "sr1": 111.32,
    "sr2": 166.98,
    "sr3": 222.64,
    "sr4": 278.3,
}
#: The met1 landing point each ``<i>_d_stub`` climbs to, under the vdd rail.
D_M1_Y_UM = 6.0

#: Half-width of the clearance window a 0.17 um wire needs: half the wire
#: plus sky130's met1/met2 minimum space (0.14 um), rounded up to 0.31 um.
CLEAR_HALF_WIDTH_UM = 0.31

#: Where ``place_array`` puts the array, and the channel that leaves.
ARRAY_ORIGIN_UM = (0.0, 23.635)
CHANNEL_Y_UM = (7.2, 19.8)

#: The four data-net horizontals ``ro_array_core``'s own ``core`` stage drew,
#: in the array's local frame: (net, y, x_start, x_end).
RO_RUNS = {
    "ro1": (8.0, -0.5, 50.5),
    "ro2": (8.5, 20.5, 105.8),
    "ro3": (9.0, 28.47, 161.1),
    "ro4": (10.0, 49.5, 216.4),
}
#: The array's own south edge; a column has to clear it to be an escape.
ARRAY_SOUTH_EDGE_UM = -3.635
ESCAPE_SCAN_FLOOR_UM = -4.0
#: The two taps the ``ro1``/``ro4`` increment used (array-local x).
CHOSEN_TAPS = {"ro1": -0.5, "ro4": 215.4}

# ---------------------------------------------------------------------------
# Constants for the second data-path increment (``xo``/``ro2``/``ro3``, and
# ``sv``'s own ``d``->``vdd`` tie).  Everything below is in the *composed*
# frame (array-local + ``ARRAY_ORIGIN_UM``), because that is the frame the
# stages that drew it are written in.
# ---------------------------------------------------------------------------

#: The band a met2 column has to be free over to leave the array at all: from
#: just under the array's own south edge up past the top of the ``xor2`` row.
ARRAY_FULL_HEIGHT_UM = (19.4, 50.0)
#: The three met2 columns this increment descends on, per net.
WEST_MARGIN_COLUMNS = {"ro2": 0.3, "ro3": 1.3, "xo": -1.5}
#: Where each net turns east out of its column, and the sampler it feeds.
CHANNEL_TURNS_UM = {"ro2": 18.6, "ro3": 19.4, "xo": 13.0}
DATA_TARGETS = {"ro1": "sr1", "ro2": "sr2", "ro3": "sr3", "ro4": "sr4", "xo": "sb"}
#: ``xa3``'s own ``y`` output (the ``xo`` label) and the met1 point the
#: ``xo_stub`` leg promotes it to -- the same 1.4 um straight-north promotion
#: ``ro_array_core``'s own ``core`` stage already declares for ``xa2``.
XO_PAD_UM = (66.375, 49.22)
XO_M1_UM = (66.375, 50.62)
#: The met1 dip that steps around ``xa2``'s own ``t2`` riser, and the two
#: met2 lanes on either side of it.
XO_DIP_Y_UM = 52.5
XO_DIP_X_UM = (36.5, 38.2)
XO_LANE_Y_UM = 53.5
#: sky130 met1/met2 minimum space, and the via landing pad ``gen-compose``
#: draws -- the two numbers the "no via fits" arithmetic below is made of.
MIN_SPACE_UM = 0.14
VIA_PAD_UM = 0.42
#: The east margin's own fence: the array's east vdd/vss riser (met2) and
#: ``ro4``'s own met1 escape leg, measured at ``ro3``'s own run height.
EAST_FENCE_Y_UM = 32.635


def occupied(region: db.Region, dbu: float, x: float, y0: float, y1: float) -> list:
    """Occupied ``y`` intervals in a clearance-wide column at ``x``."""
    window = db.Region(
        db.Box(db.DBox(x - CLEAR_HALF_WIDTH_UM, y0, x + CLEAR_HALF_WIDTH_UM, y1) * (1 / dbu))
    )
    hit = region & window
    spans = sorted(
        (round(p.bbox().bottom * dbu, 4), round(p.bbox().top * dbu, 4)) for p in hit.each()
    )
    return merge_spans(spans)


def clear(region: db.Region, dbu: float, x: float, y0: float, y1: float) -> bool:
    """Is a clearance-wide column at ``x`` free of ``region`` over y0..y1?"""
    window = db.Region(
        db.Box(db.DBox(x - CLEAR_HALF_WIDTH_UM, y0, x + CLEAR_HALF_WIDTH_UM, y1) * (1 / dbu))
    )
    return (region & window).is_empty()


def labels(layout: db.Layout, cell: db.Cell, key: tuple[int, int]) -> list[dict]:
    """Every text on ``key``, resolved to the top cell's own frame."""
    index = layout.layer(*key)
    walker = db.RecursiveShapeIterator(layout, cell, index)
    walker.shape_flags = db.Shapes.STexts
    out = []
    while not walker.at_end():
        shape = walker.shape()
        if shape.is_text():
            text = shape.text.transformed(walker.trans())
            out.append(
                {
                    "text": text.string,
                    "x_um": round(text.x * layout.dbu, 4),
                    "y_um": round(text.y * layout.dbu, 4),
                }
            )
        walker.next()
    return out


def scan_d_columns() -> dict:
    """Group A -- the six ``d`` columns, on the pre-array ``route_ctrl`` stage."""
    layout = db.Layout()
    layout.read(str(HERE / "route_ctrl.gds"))
    cell = layout.top_cell()
    dbu = layout.dbu
    met1 = merged(layout, cell, MET1)
    met2 = merged(layout, cell, MET2)
    out = {}
    for name, origin in INSTANCES.items():
        x = round(origin + D_LOCAL_X_UM, 4)
        out[name] = {
            "d_column_x_um": x,
            "met1_above_pin_clear": clear(met1, dbu, x, D_LOCAL_Y_UM, 6.9),
            "met2_above_landing_clear": clear(met2, dbu, x, 5.1, 20.0),
            "met1_column_occupied": occupied(met1, dbu, x, -4.0, 7.5),
            "met2_column_occupied": occupied(met2, dbu, x, -4.0, 7.5),
            # The "from below" case, stated as the two single-layer legs it
            # would need and neither of which exists: met1 straight down to
            # just above the shared vss rail (blocked by the in-cell clkb
            # lane at y=0.4), or met2 straight down out of the row (blocked
            # by the shared clk lane at y=-1.7).
            "met1_below_pin_clear": clear(met1, dbu, x, -3.4, D_LOCAL_Y_UM),
            "met2_below_pin_clear": clear(met2, dbu, x, -4.0, D_LOCAL_Y_UM),
        }
    return out


def scan_array_escapes() -> dict:
    """Group B -- which ``ro`` nets can reach the array's own south edge."""
    layout = db.Layout()
    layout.read(str(ARRAY_GDS))
    cell = layout.top_cell()
    dbu = layout.dbu
    met1 = merged(layout, cell, MET1)
    out = {}
    for net, (y, x0, x1) in RO_RUNS.items():
        free: list[list[float]] = []
        x = x0
        while x <= x1 + 1e-9:
            if clear(met1, dbu, x, ESCAPE_SCAN_FLOOR_UM, y - 0.09):
                value = round(x, 3)
                if free and abs(value - free[-1][1]) < 0.06:
                    free[-1][1] = value
                else:
                    free.append([value, value])
            x += 0.05
        entry = {
            "run_y_um": y,
            "run_x_um": [x0, x1],
            "free_south_columns_um": free,
            "has_south_escape": bool(free),
        }
        if net in CHOSEN_TAPS:
            tap = CHOSEN_TAPS[net]
            entry["tap_x_um"] = tap
            entry["tap_in_a_free_column"] = any(
                lo - 1e-9 <= tap <= hi + 1e-9 for lo, hi in free
            )
            entry["tap_clears_south_edge"] = clear(
                met1, dbu, tap, ESCAPE_SCAN_FLOOR_UM, y - 0.09
            )
        out[net] = entry
    return out


def free_columns(
    region: db.Region, dbu: float, y0: float, y1: float, x0: float, x1: float
) -> list[list[float]]:
    """Every 0.05 um column in ``x0..x1`` that is free of ``region`` over y."""
    free: list[list[float]] = []
    x = x0
    while x <= x1 + 1e-9:
        if clear(region, dbu, x, y0, y1):
            value = round(x, 3)
            if free and abs(value - free[-1][1]) < 0.06:
                free[-1][1] = value
            else:
                free.append([value, value])
        x += 0.05
    return free


def scan_margins() -> dict:
    """Group E -- why ``xo``/``ro2``/``ro3`` all leave on the *west* margin.

    Measured on ``route_data.gds`` -- the state *before* this increment drew
    anything, so the lanes it picks are picked from the geometry that was
    actually in the way, not from the answer.
    """
    layout = db.Layout()
    layout.read(str(HERE / "route_data.gds"))
    cell = layout.top_cell()
    dbu = layout.dbu
    met1 = merged(layout, cell, MET1)
    met2 = merged(layout, cell, MET2)

    y0, y1 = ARRAY_FULL_HEIGHT_UM
    bands = free_columns(met2, dbu, y0, y1, -2.1, 220.0)
    west = [b for b in bands if b[1] < 100.0]
    east = [b for b in bands if b[0] > 100.0]

    # ro1's own channel haul (met2, y=17.0) runs east from its west end; any
    # column that has to reach BELOW y=17 must sit west of that end.
    haul = met2 & db.Region(db.Box(db.DBox(-5.0, 16.8, 340.0, 17.2) * (1 / dbu)))
    haul_west_edge = min(round(p.bbox().left * dbu, 4) for p in haul.each())

    # The east margin is free but unreachable: the array's own east riser
    # (met2) and ro4's own met1 escape leg leave a gap too narrow for the
    # met1<->met2 via a route would have to drop between them.
    riser = met2 & db.Region(
        db.Box(db.DBox(210.0, EAST_FENCE_Y_UM - 0.05, 215.0, EAST_FENCE_Y_UM + 0.05) * (1 / dbu))
    )
    riser_east_edge = max(round(p.bbox().right * dbu, 4) for p in riser.each())
    leg = met1 & db.Region(
        db.Box(db.DBox(215.0, EAST_FENCE_Y_UM - 0.05, 216.0, EAST_FENCE_Y_UM + 0.05) * (1 / dbu))
    )
    leg_west_edge = min(round(p.bbox().left * dbu, 4) for p in leg.each())
    gap = round(leg_west_edge - riser_east_edge, 4)
    needed = round(VIA_PAD_UM + 2 * MIN_SPACE_UM, 4)

    # xa3's own y output is fenced on met2 by xa2's t2 riser (west) and the
    # t2 bridge (north); met1 at the dip's own height is what gets past it.
    dip_lane_met2 = lane_occupied(met2, dbu, XO_DIP_Y_UM, 30.0, XO_PAD_UM[0])
    dip_lane_met1 = lane_occupied(met1, dbu, XO_DIP_Y_UM, 30.0, XO_PAD_UM[0])
    riser_between_dip_ends = [
        span
        for span in dip_lane_met2
        if XO_DIP_X_UM[0] < span[0] and span[1] < XO_DIP_X_UM[1]
    ]
    return {
        "scanned_stage": "route_data.gds",
        "met2_free_column_bands_um": bands,
        "west_margin_band_um": west,
        "east_margin_band_um": east,
        "ro1_channel_haul_west_edge_um": haul_west_edge,
        "east_riser_east_edge_um": riser_east_edge,
        "ro4_escape_leg_west_edge_um": leg_west_edge,
        "east_margin_via_gap_um": gap,
        "east_margin_via_needs_um": needed,
        "xo_dip_lane_met2_occupied": dip_lane_met2,
        "xo_dip_lane_met1_occupied": dip_lane_met1,
        "t2_riser_sits_between_the_dip_ends": riser_between_dip_ends,
        "met1_clear_across_the_dip": lane_clear(
            met1, dbu, XO_DIP_Y_UM, XO_DIP_X_UM[0] - 0.3, XO_DIP_X_UM[1] + 0.3
        ),
        "met2_westbound_lane_clear": lane_clear(
            met2, dbu, XO_LANE_Y_UM, -1.8, XO_DIP_X_UM[0]
        ),
        "columns_in_west_band": {
            net: any(lo - 1e-9 <= x <= hi + 1e-9 for lo, hi in west)
            for net, x in WEST_MARGIN_COLUMNS.items()
        },
        "columns_clear_over_full_height": {
            net: clear(met2, dbu, x, y0, y1) for net, x in WEST_MARGIN_COLUMNS.items()
        },
        "columns_that_clear_ro1s_haul": {
            net: clear(met2, dbu, x, CHANNEL_TURNS_UM[net], 19.0)
            and x + CLEAR_HALF_WIDTH_UM < haul_west_edge
            for net, x in WEST_MARGIN_COLUMNS.items()
        },
    }


def lane_clear(region: db.Region, dbu: float, y: float, x0: float, x1: float) -> bool:
    """Is a clearance-high lane at ``y`` free of ``region`` over x0..x1?"""
    window = db.Region(
        db.Box(db.DBox(x0, y - CLEAR_HALF_WIDTH_UM, x1, y + CLEAR_HALF_WIDTH_UM) * (1 / dbu))
    )
    return (region & window).is_empty()


def lane_occupied(
    region: db.Region, dbu: float, y: float, x0: float, x1: float
) -> list[list[float]]:
    """Occupied ``x`` intervals in a clearance-high lane at ``y``."""
    window = db.Region(
        db.Box(db.DBox(x0, y - CLEAR_HALF_WIDTH_UM, x1, y + CLEAR_HALF_WIDTH_UM) * (1 / dbu))
    )
    hit = region & window
    spans = sorted(
        (round(p.bbox().left * dbu, 4), round(p.bbox().right * dbu, 4)) for p in hit.each()
    )
    return merge_spans(spans)


def scan_channel() -> dict:
    """Group C -- what is drawn in the channel between the two blocks."""
    layout = db.Layout()
    layout.read(str(HERE / "sampler_core.gds"))
    cell = layout.top_cell()
    dbu = layout.dbu
    band = db.Region(db.Box(db.DBox(-10.0, CHANNEL_Y_UM[0], 340.0, CHANNEL_Y_UM[1]) * (1 / dbu)))
    out = {"bbox_um": [
        round(cell.dbbox().left, 4),
        round(cell.dbbox().bottom, 4),
        round(cell.dbbox().right, 4),
        round(cell.dbbox().top, 4),
    ]}
    for name, key in (("li1", LI1), ("met1", MET1), ("met2", MET2)):
        hit = merged(layout, cell, key) & band
        out[f"{name}_shapes_in_channel"] = [
            [
                round(p.bbox().left * dbu, 4),
                round(p.bbox().bottom * dbu, 4),
                round(p.bbox().right * dbu, 4),
                round(p.bbox().top * dbu, 4),
            ]
            for p in hit.each()
        ]
    out["li1_channel_empty"] = not out["li1_shapes_in_channel"]
    out["met1_leg_count"] = len(out["met1_shapes_in_channel"])
    out["met2_leg_count"] = len(out["met2_shapes_in_channel"])
    return out


def scan_electrical() -> dict:
    """Group D -- the extracted result, and where the stub labels landed."""
    extract = json.loads((HERE / "extract.json").read_text())
    nets = [n if isinstance(n, str) else n.get("name") for n in extract["nets"]]

    def carrying(*tokens: str) -> list[str]:
        return [
            n
            for n in nets
            if all(token in n.split("|") for token in tokens)
        ]

    layout = db.Layout()
    layout.read(str(HERE / "sampler_core.gds"))
    cell = layout.top_cell()
    found = {}
    for key in (LI1, MET1, MET2):
        for entry in labels(layout, cell, (key[0], 5)):
            found.setdefault(entry["text"], []).append((entry["x_um"], entry["y_um"]))

    stub_columns = {}
    for instance in ("sb", "sr1", "sr2", "sr3", "sr4"):
        name = f"{instance}_d_stub"
        positions = found.get(name, [])
        expected = round(INSTANCES[instance] + D_LOCAL_X_UM, 4)
        stub_columns[name] = {
            "label_positions_um": positions,
            "expected_column_x_um": expected,
            "in_expected_column": bool(positions)
            and all(abs(x - expected) < 1e-6 for x, _ in positions),
        }
    # sv's own d is the odd one out: it is tied to vdd, so its leg carries
    # the sv_d_vdd_tie label rather than a <instance>_d_stub one.
    sv_tie = found.get("sv_d_vdd_tie", [])
    sv_expected = round(INSTANCES["sv"] + D_LOCAL_X_UM, 4)

    # Each of the five data nets, by the labels that have to be on it: the
    # array's own promoted output name, every leg this repo drew for it, the
    # sampler stub it ends on, and a sampler d pin (tg_d_a).
    data_net_tokens = {
        "ro1": ("ro1", "ro1_esc", "sr1_d_stub", "tg_d_a"),
        "ro2": ("ro2", "ro2_esc", "sr2_d_stub", "tg_d_a"),
        "ro3": ("ro3", "ro3_esc_e", "ro3_esc_w", "ro3_hop", "sr3_d_stub", "tg_d_a"),
        "ro4": ("ro4", "ro4_esc", "sr4_d_stub", "tg_d_a"),
        "xo": ("xo", "xo_stub", "xo_hop", "xo_dip", "sb_d_stub", "tg_d_a"),
    }

    return {
        "device_count": extract["device_count"],
        "net_count": extract["net_count"],
        "data_nets": {net: carrying(*tokens) for net, tokens in data_net_tokens.items()},
        "ro1_net": carrying("ro1", "ro1_esc", "sr1_d_stub", "tg_d_a"),
        "ro4_net": carrying("ro4", "ro4_esc", "sr4_d_stub", "tg_d_a"),
        "unconnected_d_nets": [n for n in nets if re.fullmatch(r"a\|d\|tg_d_a(\$\d+)?", n)],
        "sv_d_on_the_sampler_vdd_net": carrying("sv_d_vdd_tie", "tg_d_vdd", "tg_d_a", "vdd"),
        "sv_tie_label_positions_um": sv_tie,
        "sv_tie_expected_column_x_um": sv_expected,
        "sv_tie_in_expected_column": bool(sv_tie)
        and all(abs(x - sv_expected) < 1e-6 for x, _ in sv_tie),
        "stub_label_columns": stub_columns,
        # The one merge nobody drew: the array's own vss and the sampler
        # bank's own vss come out as ONE extracted net although no metal
        # joins them (see the channel scan -- the only conductors crossing
        # the channel are this increment's two data legs). They share the
        # p-substrate, which sky130's extraction deck models as a real
        # conductor. vdd, which has no such shared body, stays two nets --
        # so this is a substrate path, not klt merging same-named nets.
        "shared_vss_nets": carrying("tg_d_vss", "vss_x1"),
        "array_vdd_nets": carrying("vdd_x1"),
        "sampler_vdd_nets": carrying("tg_d_vdd"),
    }


def main() -> int:
    d_columns = scan_d_columns()
    escapes = scan_array_escapes()
    margins = scan_margins()
    channel = scan_channel()
    electrical = scan_electrical()

    claims = {
        "every_d_column_reachable_from_above": all(
            entry["met1_above_pin_clear"] and entry["met2_above_landing_clear"]
            for entry in d_columns.values()
        ),
        "no_single_layer_leg_leaves_any_d_column_downward": all(
            not entry["met1_below_pin_clear"] and not entry["met2_below_pin_clear"]
            for entry in d_columns.values()
        ),
        "ro1_and_ro4_have_south_escapes": (
            escapes["ro1"]["has_south_escape"] and escapes["ro4"]["has_south_escape"]
        ),
        "ro2_and_ro3_have_none": not (
            escapes["ro2"]["has_south_escape"] or escapes["ro3"]["has_south_escape"]
        ),
        "chosen_taps_are_free_columns": all(
            escapes[net]["tap_in_a_free_column"] and escapes[net]["tap_clears_south_edge"]
            for net in CHOSEN_TAPS
        ),
        # Was met1=2 / met2=5 before the vdd strap (PR #113); the strap's routing
        # crosses this same channel band and adds two legs on each layer.
        "channel_carries_only_the_data_path_and_vdd_strap_legs": (
            channel["li1_channel_empty"]
            and channel["met1_leg_count"] == 4
            and channel["met2_leg_count"] == 7
        ),
        "exactly_one_net_joins_ro1_to_a_sampler_d": len(electrical["ro1_net"]) == 1,
        "exactly_one_net_joins_ro4_to_a_sampler_d": len(electrical["ro4_net"]) == 1,
        "each_data_net_joins_exactly_one_sampler_d": all(
            len(found) == 1 for found in electrical["data_nets"].values()
        ),
        "every_sampler_d_pin_is_driven": len(electrical["unconnected_d_nets"]) == 0,
        "sv_d_is_tied_to_the_sampler_vdd_net": (
            len(electrical["sv_d_on_the_sampler_vdd_net"]) == 1
            and electrical["sv_tie_in_expected_column"]
        ),
        "stub_labels_land_in_their_own_instance_column": all(
            entry["in_expected_column"] for entry in electrical["stub_label_columns"].values()
        ),
        "west_margin_is_the_only_reachable_met2_column_band": (
            len(margins["west_margin_band_um"]) == 1
            and len(margins["east_margin_band_um"]) == 1
            and all(margins["columns_in_west_band"].values())
            and all(margins["columns_clear_over_full_height"].values())
        ),
        "no_via_fits_between_the_east_riser_and_ro4s_escape_leg": (
            margins["east_margin_via_gap_um"] < margins["east_margin_via_needs_um"]
        ),
        "only_xos_column_clears_ro1s_own_channel_haul": (
            margins["columns_that_clear_ro1s_haul"]["xo"]
            and not margins["columns_that_clear_ro1s_haul"]["ro2"]
            and not margins["columns_that_clear_ro1s_haul"]["ro3"]
        ),
        "the_t2_riser_is_what_the_xo_dip_steps_around": (
            len(margins["t2_riser_sits_between_the_dip_ends"]) == 1
            and margins["met1_clear_across_the_dip"]
            and margins["met2_westbound_lane_clear"]
        ),
        "whole_device_population_present": electrical["device_count"] == 264,
        "array_and_sampler_vss_are_one_net_via_the_substrate": (
            len(electrical["shared_vss_nets"]) == 1
        ),
        # Two separate nets until the vdd strap (PR #113) tied them together on
        # purpose. Keep asserting it as a real claim, inverted: a regression that
        # un-merges them again must still trip.
        "array_and_sampler_vdd_are_one_net_via_the_strap": (
            len(electrical["array_vdd_nets"]) == 1
            and len(electrical["sampler_vdd_nets"]) == 1
            and electrical["array_vdd_nets"] == electrical["sampler_vdd_nets"]
        ),
    }

    report = {
        "array_origin_um": {"x": ARRAY_ORIGIN_UM[0], "y": ARRAY_ORIGIN_UM[1]},
        "array_south_edge_in_composed_frame_um": round(
            ARRAY_ORIGIN_UM[1] + ARRAY_SOUTH_EDGE_UM, 4
        ),
        "clearance_half_width_um": CLEAR_HALF_WIDTH_UM,
        "all_claims_hold": all(claims.values()),
        "claims": claims,
        "d_columns": d_columns,
        "array_south_escapes": escapes,
        "margins": margins,
        "channel": channel,
        "electrical": electrical,
    }
    (HERE / "data-path-scan.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_claims_hold": report["all_claims_hold"], "claims": claims}, indent=2))
    return 0 if report["all_claims_hold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
