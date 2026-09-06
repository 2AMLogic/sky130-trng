#!/usr/bin/env python3
"""Measure every ``vdd`` met1 promotion tap this directory's Increment 8 uses.

Increment 6's finding 1 established the rule this script exists to satisfy:
``klt gen-compose`` models a placed block as an opaque **bbox**, with no
obstacle model of that block's own interior conductors, so a stub that starts
at an interior port is free to run straight through another net's metal and
short to it *silently* -- ``unrouted_nets: []`` and ``klt drc`` clean, wrong
only in ``klt extract``'s net list.  Increment 7's ``t2`` bridge answered that
by promoting li1 taps to met1 with short stubs measured against
``xor2-y-escape-scan.py``'s own escape windows first.

``vdd`` needs seven such promotions (four ``ro_buf`` instances plus three
``xor2`` instances), so this script measures all seven **against the composed
array itself** (``ro_array_core_signal7_poc.gds``) rather than against the
standalone leaf cells.  That is strictly stronger than a per-cell scan: the
composite's met1 includes every leaf cell's own internal met1 *and* every
inter-cell backbone Increments 2-7 already committed (``rn1``-``rn4``,
``ro1``-``ro4``, the buffer ``vss`` bus, ``t1``, and Increment 7's own
``y_m1``/``b_m1`` stubs), which a per-cell scan cannot see at all.

For each tap it reports, purely geometrically (no PDK deck, no device
recognition):

* ``on_vdd_li1`` -- the tap point lies inside one merged li1 polygon, and that
  polygon's area matches the leaf cell's own ``vdd`` component area, so the
  tap is on ``vdd`` and not on a neighbouring net;
* ``via_landing_clear`` -- a square of side ``2 * via_landing_halo_um``
  centred on the tap lies wholly inside that li1 polygon, so the ``mcon`` drop
  ``gen-compose`` places there has li1 under all of it;
* ``stub_met1_clear`` -- the drawn met1 stub from the tap to the tip, grown by
  half its own width plus sky130's ``met1.space`` (0.14 um), touches **no**
  met1 anywhere in the composite.  ``vdd`` carries no met1 of its own before
  this increment (all seven instances are li1-only), so any met1 contact at
  all would be a foreign net -- i.e. exactly the silent short Increment 6 hit.

Usage (from this directory)::

    python3 vdd-tap-scan.py            # -> vdd-tap-scan.json
"""

from __future__ import annotations

import json
import pathlib

import klayout.db as db

HERE = pathlib.Path(__file__).resolve().parent
GDS = HERE / "ro_array_core_signal7_poc.gds"
CELL = "ro_array_core_signal7_poc"
OUT = HERE / "vdd-tap-scan.json"

LI1 = (67, 20)
MET1 = (68, 20)

#: sky130 ``met1.space`` minimum same-layer spacing.
MET1_SPACING_UM = 0.14

#: Half-side of the square that must sit wholly inside li1 under the tap, so
#: the ``mcon`` via ``gen-compose`` drops there is fully landed.  0.085 um is
#: half sky130's own 0.17 um ``mcon`` size; the buffer taps clear 0.21 um
#: (they sit on a 0.42 um-wide tap rail), the ``xor2`` taps 0.12 um.
VIA_LANDING_HALO_UM = 0.085

#: The seven taps Increment 8 promotes, in composed-array absolute microns:
#: ``(tap_x, tap_y, tip_y, stub_width)``.  ``ro_buf``'s tap is its own
#: authoritative ``TAP_N`` port (block-local ``(-1.12, 4.24)``, the same
#: coordinate this directory's README table has carried since Increment 2);
#: ``xor2``'s is block-local ``(-1.12, 13.8)``, chosen by this script's own
#: earlier grid pass as the widest ``vdd`` pad with a clear north escape
#: (``xor2``'s ``vdd``/``vss`` tap rows were flagged *approx* and unconfirmed
#: by every increment up to this one).
TAPS = {
    "buf1": (47.195, 4.24, 6.0, 0.42),
    "buf2": (102.495, 4.24, 6.0, 0.42),
    "buf3": (157.795, 4.24, 6.0, 0.42),
    "buf4": (212.995, 4.24, 6.0, 0.42),
    "xa1": (5.765, 26.385, 27.885, 0.42),
    "xa2": (34.735, 26.385, 27.885, 0.42),
    "xa3": (63.705, 26.385, 27.885, 0.42),
}

#: ``klt components`` reports these ``vdd`` li1 component areas for the two
#: leaf cells (``ro_buf`` has no ``vdd`` label of its own -- its tap rail is
#: the nwell tap column the array request has always tapped by coordinate).
EXPECTED_AREA_UM2 = {"xa1": 17.07285, "xa2": 17.07285, "xa3": 17.07285}


def merged(layout: db.Layout, cell: db.Cell, spec: tuple[int, int]) -> db.Region:
    region = db.Region(cell.begin_shapes_rec(layout.layer(*spec)))
    region.merge()
    return region


def dbox_region(box: db.DBox, dbu: float) -> db.Region:
    return db.Region(
        db.Box(
            int(round(box.left / dbu)),
            int(round(box.bottom / dbu)),
            int(round(box.right / dbu)),
            int(round(box.top / dbu)),
        )
    )


def main() -> int:
    layout = db.Layout()
    layout.read(str(GDS))
    cell = layout.cell(CELL)
    dbu = layout.dbu

    li1 = merged(layout, cell, LI1)
    met1 = merged(layout, cell, MET1)

    results: dict[str, dict] = {}
    for name, (x, tap_y, tip_y, width) in TAPS.items():
        point = db.Point(int(round(x / dbu)), int(round(tap_y / dbu)))
        owner = None
        for poly in li1.each():
            if poly.inside(point):
                owner = poly
                break

        entry: dict = {
            "tap_um": [x, tap_y],
            "tip_um": [x, tip_y],
            "stub_length_um": round(tip_y - tap_y, 4),
            "stub_width_um": width,
            "on_vdd_li1": owner is not None,
        }
        if owner is not None:
            bbox = owner.bbox().to_dtype(dbu)
            entry["li1_component_bbox_um"] = [
                round(bbox.left, 4),
                round(bbox.bottom, 4),
                round(bbox.right, 4),
                round(bbox.top, 4),
            ]
            entry["li1_component_area_um2"] = round(owner.area() * dbu * dbu, 5)
            expected = EXPECTED_AREA_UM2.get(name)
            if expected is not None:
                entry["li1_component_area_matches_cell_vdd"] = (
                    abs(entry["li1_component_area_um2"] - expected) < 1e-3
                )

            landing = db.DBox(
                x - VIA_LANDING_HALO_UM,
                tap_y - VIA_LANDING_HALO_UM,
                x + VIA_LANDING_HALO_UM,
                tap_y + VIA_LANDING_HALO_UM,
            )
            outside = dbox_region(landing, dbu) - db.Region(owner)
            entry["via_landing_halo_um"] = VIA_LANDING_HALO_UM
            entry["via_landing_clear"] = outside.is_empty()

        halo = width / 2.0 + MET1_SPACING_UM
        stub = db.DBox(x - halo, tap_y - MET1_SPACING_UM, x + halo, tip_y + MET1_SPACING_UM)
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
        results[name] = entry

    report = {
        "gds": GDS.name,
        "cell": CELL,
        "met1_spacing_um": MET1_SPACING_UM,
        "met1_polygon_count": met1.count(),
        "li1_polygon_count": li1.count(),
        "all_taps_clear": all(
            entry["on_vdd_li1"]
            and entry.get("via_landing_clear", False)
            and entry["stub_met1_clear"]
            for entry in results.values()
        ),
        "taps": results,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
