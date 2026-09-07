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

Four groups of claims:

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
    Nothing but this increment's own four legs is drawn in ``y`` 7.2..19.8,
    and each of them is where it was declared.

D. The electrical result, read from ``extract.json`` + ``sampler_core.spice``
    Exactly two extracted nets merge an array output with a sampler ``d``
    pin, they are ``ro1``/``ro4``, and the ``sr1_d_stub``/``sr4_d_stub``
    labels that name the sampler end of each sit in ``sr1``'s and ``sr4``'s
    own ``d`` column respectively -- so the connection lands on the intended
    instance, not merely on *an* instance.  Four unconnected ``d`` nets
    remain, one per still-unrouted data net (``xo``, ``ro2``, ``ro3``) plus
    ``sv``'s own ``d`` (which is tied to ``vdd`` in the schematic, not to the
    array).

Usage (from this directory)::

    python3 data-path-scan.py            # -> data-path-scan.json
"""

from __future__ import annotations

import json
import pathlib
import re

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent
ARRAY_GDS = HERE.parent / "ro_array_core" / "ro_array_core.gds"

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
#: The two taps this increment actually used (array-local x).
CHOSEN_TAPS = {"ro1": -0.5, "ro4": 215.4}


def merged(layout: db.Layout, cell: db.Cell, key: tuple[int, int]) -> db.Region:
    """Every shape on ``key``, flattened out of the hierarchy and merged."""
    index = layout.layer(*key)
    region = db.Region(db.RecursiveShapeIterator(layout, cell, index))
    region.merge()
    return region


def occupied(region: db.Region, dbu: float, x: float, y0: float, y1: float) -> list:
    """Occupied ``y`` intervals in a clearance-wide column at ``x``."""
    window = db.Region(
        db.Box(db.DBox(x - CLEAR_HALF_WIDTH_UM, y0, x + CLEAR_HALF_WIDTH_UM, y1) * (1 / dbu))
    )
    hit = region & window
    spans = sorted(
        (round(p.bbox().bottom * dbu, 4), round(p.bbox().top * dbu, 4)) for p in hit.each()
    )
    out: list[list[float]] = []
    for lo, hi in spans:
        if out and lo <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


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
    for instance in ("sr1", "sr4"):
        name = f"{instance}_d_stub"
        positions = found.get(name, [])
        expected = round(INSTANCES[instance] + D_LOCAL_X_UM, 4)
        stub_columns[name] = {
            "label_positions_um": positions,
            "expected_column_x_um": expected,
            "in_expected_column": bool(positions)
            and all(abs(x - expected) < 1e-6 for x, _ in positions),
        }

    return {
        "device_count": extract["device_count"],
        "net_count": extract["net_count"],
        "ro1_net": carrying("ro1", "ro1_esc", "sr1_d_stub", "tg_d_a"),
        "ro4_net": carrying("ro4", "ro4_esc", "sr4_d_stub", "tg_d_a"),
        "unconnected_d_nets": [n for n in nets if re.fullmatch(r"a\|d\|tg_d_a(\$\d+)?", n)],
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
        "channel_carries_only_this_increments_legs": (
            channel["li1_channel_empty"]
            and channel["met1_leg_count"] == 2
            and channel["met2_leg_count"] == 2
        ),
        "exactly_one_net_joins_ro1_to_a_sampler_d": len(electrical["ro1_net"]) == 1,
        "exactly_one_net_joins_ro4_to_a_sampler_d": len(electrical["ro4_net"]) == 1,
        "four_sampler_d_pins_remain_unconnected": len(electrical["unconnected_d_nets"]) == 4,
        "stub_labels_land_in_their_own_instance_column": all(
            entry["in_expected_column"] for entry in electrical["stub_label_columns"].values()
        ),
        "whole_device_population_present": electrical["device_count"] == 264,
        "array_and_sampler_vss_are_one_net_via_the_substrate": (
            len(electrical["shared_vss_nets"]) == 1
        ),
        "array_and_sampler_vdd_are_still_two_nets": (
            len(electrical["array_vdd_nets"]) == 1
            and len(electrical["sampler_vdd_nets"]) == 1
            and electrical["array_vdd_nets"] != electrical["sampler_vdd_nets"]
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
        "channel": channel,
        "electrical": electrical,
    }
    (HERE / "data-path-scan.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_claims_hold": report["all_claims_hold"], "claims": claims}, indent=2))
    return 0 if report["all_claims_hold"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
