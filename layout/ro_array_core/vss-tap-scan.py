#!/usr/bin/env python3
"""Measure every ``vss`` tap the ``vssstub``/``vssbus`` stages draw.

Same discipline, and the same reason, as
``layout/ro_array_core-placement-poc/vdd-tap-scan.py``: ``klt gen-compose``
models a placed block as an opaque **bbox** with no obstacle model of that
block's interior conductors, so a stub that starts at an interior tap can run
straight through another net's metal and short to it *silently* --
``unrouted_nets: []`` and ``klt drc`` clean, wrong only in ``klt extract``'s
net list (the PoC directory's Increment 6, finding 1).  Nothing about that
changes when the request moves from a hand-maintained PoC file into
``cell.json``, so the measurement moves with it.

This script measures against ``vddbus.gds`` -- the stage the ``vss`` work is
composed on top of, i.e. the array with **every** committed inter-cell
backbone already drawn (``rn1``-``rn4``, ``ro1``-``ro4``, the buffer ``vss``
bus, ``t1``/``t2``, and the whole seven-tap ``vdd`` bus).  A per-leaf-cell
scan cannot see any of those.

Three groups, each checked for what can actually go wrong with it:

``xor2`` li1 taps (``xa1``/``xa2``/``xa3``)
    ``pst``'s own ``TAP_S`` port, block-local ``(3.92, -1.29)`` -- the south
    edge of ``xor2``'s p-substrate tap ring, i.e. the ``vss`` counterpart of
    the ``nwt1`` ``vdd`` tap Increment 8 measured.  Checked: the tap point
    lies inside one merged li1 polygon whose area matches ``xor2``'s own
    ``vss`` component; an ``mcon``-sized square centred on it lies wholly
    inside that polygon; and the drawn met1 stub down to the tip, grown by
    half its width plus sky130's ``met1.space``, touches **no** met1 anywhere
    in the composite.  ``xor2``'s ``vss`` carries no met1 of its own, so any
    met1 contact at all would be a foreign net.  The tips are deliberately
    *not* all at the same ``y``: ``ro4``'s own met1 backbone runs at
    ``y = 10.0`` across ``x in [49.5, 216.4]``, which is directly under
    ``xa3`` but not under ``xa1``/``xa2``, so ``xa3``'s stub has to stop
    above it.

``ro_ring5`` met2 rail ports (``ring1``-``ring4``)
    Each ring already carries its own full-width met2 ``vss`` rail (its
    fourth ``gen-compose`` stage, ``layout/ro_ring5/README.md``), so the
    array-level strap needs no promotion stub at all -- it taps the rail's
    own two end pads directly and routes met2-on-met2.  Checked: the port
    lies inside one merged met2 polygon whose area matches that ring's own
    rail.

The buffer ``vss`` met1 backbone port
    The one point where the row-1 strap joins the four-buffer ``vss`` bus
    the PoC's Increment 5 drew (met1, ``y = -3.425``).  Checked: the port
    lies inside one merged met1 polygon whose area matches that bus.

Usage (from this directory)::

    python3 vss-tap-scan.py            # -> vss-tap-scan.json
"""

from __future__ import annotations

import json
import pathlib
import sys

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))
from _geom_common import dbox_region, merged  # noqa: E402

GDS = HERE / "vddbus.gds"
CELL = "vddbus"
OUT = HERE / "vss-tap-scan.json"

LI1 = (67, 20)
MET1 = (68, 20)
MET2 = (69, 20)

#: sky130 ``met1.space`` minimum same-layer spacing.
MET1_SPACING_UM = 0.14

#: Half-side of the square that must sit wholly inside li1 under the tap, so
#: the ``mcon`` via ``gen-compose`` drops there is fully landed.  0.085 um is
#: half sky130's own 0.17 um ``mcon`` size; ``pst``'s south bar is 0.42 um
#: wide, so each ``xor2`` tap clears 0.21 um.
VIA_LANDING_HALO_UM = 0.085

#: ``(tap_x, tap_y, tip_y, stub_width)`` in composed-array absolute microns.
XOR_TAPS = {
    "xa1": (10.805, 11.295, 9.6, 0.42),
    "xa2": (39.775, 11.295, 9.6, 0.42),
    "xa3": (68.745, 11.295, 10.8, 0.42),
}

#: ``xor2``'s own ``vss`` li1 component area, identical in all three
#: instances (one merged island: ``pst``, the ``y = 2.0`` basement route and
#: both inverters' own tap columns).
XOR_VSS_LI1_AREA_UM2 = 12.9004

#: The eight ``ro_ring5`` met2 ``vss`` rail end pads, two per ring:
#: ``(ring origin x) + 0.5`` (``g_vss_m1``) and ``+ 34.325`` (``s4_vss_m1``),
#: both at ``y = -3.0`` -- the rail lane ``layout/ro_ring5/``'s own final
#: stage routes.
RING_ORIGIN_X = {"ring1": 2.19, "ring2": 57.49, "ring3": 112.79, "ring4": 168.09}
RING_RAIL_Y = -3.0
RING_VSS_MET2_AREA_UM2 = 10.66

#: The join into the four-buffer ``vss`` met1 bus (PoC Increment 5), directly
#: below ``ring2``'s own west rail pad.
BUF_BUS_TAP = (57.99, -3.425)
BUF_VSS_MET1_AREA_UM2 = 31.6915


def owner_of(region: db.Region, x: float, y: float, dbu: float):
    point = db.Point(int(round(x / dbu)), int(round(y / dbu)))
    for poly in region.each():
        if poly.inside(point):
            return poly
    return None


def describe(poly, dbu: float) -> dict:
    bbox = poly.bbox().to_dtype(dbu)
    return {
        "component_bbox_um": [
            round(bbox.left, 4),
            round(bbox.bottom, 4),
            round(bbox.right, 4),
            round(bbox.top, 4),
        ],
        "component_area_um2": round(poly.area() * dbu * dbu, 5),
    }


def main() -> int:
    layout = db.Layout()
    layout.read(str(GDS))
    cell = layout.cell(CELL)
    dbu = layout.dbu

    li1 = merged(layout, cell, LI1)
    met1 = merged(layout, cell, MET1)
    met2 = merged(layout, cell, MET2)

    xor_taps: dict[str, dict] = {}
    for name, (x, tap_y, tip_y, width) in XOR_TAPS.items():
        owner = owner_of(li1, x, tap_y, dbu)
        entry: dict = {
            "tap_um": [x, tap_y],
            "tip_um": [x, tip_y],
            "stub_length_um": round(tap_y - tip_y, 4),
            "stub_width_um": width,
            "on_vss_li1": owner is not None,
        }
        if owner is not None:
            entry.update(describe(owner, dbu))
            entry["li1_component_area_matches_cell_vss"] = (
                abs(entry["component_area_um2"] - XOR_VSS_LI1_AREA_UM2) < 1e-3
            )
            landing = db.DBox(
                x - VIA_LANDING_HALO_UM,
                tap_y - VIA_LANDING_HALO_UM,
                x + VIA_LANDING_HALO_UM,
                tap_y + VIA_LANDING_HALO_UM,
            )
            entry["via_landing_halo_um"] = VIA_LANDING_HALO_UM
            entry["via_landing_clear"] = (
                dbox_region(landing, dbu) - db.Region(owner)
            ).is_empty()
        halo = width / 2.0 + MET1_SPACING_UM
        stub = db.DBox(
            x - halo, tip_y - halo, x + halo, tap_y + MET1_SPACING_UM
        )
        clash = dbox_region(stub, dbu) & met1
        entry["stub_halo_um"] = round(halo, 4)
        entry["stub_met1_clear"] = clash.is_empty()
        if not clash.is_empty():
            bbox = clash.bbox().to_dtype(dbu)
            entry["stub_met1_clash_bbox_um"] = [
                round(bbox.left, 4),
                round(bbox.bottom, 4),
                round(bbox.right, 4),
                round(bbox.top, 4),
            ]
        xor_taps[name] = entry

    ring_taps: dict[str, dict] = {}
    for ring, origin_x in RING_ORIGIN_X.items():
        for side, offset in (("w", 0.5), ("e", 34.325)):
            x = round(origin_x + offset, 4)
            owner = owner_of(met2, x, RING_RAIL_Y, dbu)
            entry = {"tap_um": [x, RING_RAIL_Y], "on_vss_met2": owner is not None}
            if owner is not None:
                entry.update(describe(owner, dbu))
                entry["met2_component_area_matches_ring_vss_rail"] = (
                    abs(entry["component_area_um2"] - RING_VSS_MET2_AREA_UM2) < 1e-2
                )
            ring_taps[f"{ring}_{side}"] = entry

    x, y = BUF_BUS_TAP
    owner = owner_of(met1, x, y, dbu)
    buf_tap = {"tap_um": [x, y], "on_vss_met1": owner is not None}
    if owner is not None:
        buf_tap.update(describe(owner, dbu))
        buf_tap["met1_component_area_matches_buffer_vss_bus"] = (
            abs(buf_tap["component_area_um2"] - BUF_VSS_MET1_AREA_UM2) < 1e-2
        )

    report = {
        "gds": GDS.name,
        "cell": CELL,
        "met1_spacing_um": MET1_SPACING_UM,
        "li1_polygon_count": li1.count(),
        "met1_polygon_count": met1.count(),
        "met2_polygon_count": met2.count(),
        "all_taps_clear": (
            all(
                entry["on_vss_li1"]
                and entry.get("li1_component_area_matches_cell_vss", False)
                and entry.get("via_landing_clear", False)
                and entry["stub_met1_clear"]
                for entry in xor_taps.values()
            )
            and all(
                entry["on_vss_met2"]
                and entry.get("met2_component_area_matches_ring_vss_rail", False)
                for entry in ring_taps.values()
            )
            and buf_tap["on_vss_met1"]
            and buf_tap.get("met1_component_area_matches_buffer_vss_bus", False)
        ),
        "xor_li1_taps": xor_taps,
        "ring_met2_rail_taps": ring_taps,
        "buffer_bus_met1_tap": buf_tap,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["all_taps_clear"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
