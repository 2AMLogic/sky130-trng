#!/usr/bin/env python3
"""Scan every legal met1 escape from ``xor2``'s ``y`` output net.

Increment 6's measurement (see this directory's README).  ``xor2`` exposes
no ``y`` pin of its own: the array-level request taps ``y`` by *coordinate*
on the cell's own internal li1 wire and lets ``klt gen-compose`` drop a via
and escape on the request's ``routing.layer_role`` (met1).  ``gen-compose``
models a placed block as an opaque **bbox** -- it has no obstacle model of
that block's internal conductors -- so a leg that starts *inside* a block
is free to run straight through that block's own metal.  It does exactly
that silently: a first ``t1`` probe (``xa1.y`` at local ``(4.5, 8.0)``,
escaping north) reported ``unrouted_nets: []`` and stayed ``klt drc`` clean
at 0 violations while shorting ``xa1``'s internal ``bn`` node to its own
``y`` output -- visible only in ``klt extract``'s net list.

This script answers the question that probe should have asked first: from
which points on ``xor2``'s ``y`` net, in which of the four cardinal
directions, can a met1 stub of the request's own width reach the cell
boundary without touching (or violating spacing to) another net's met1?

Geometry only -- no PDK deck, no device recognition.  ``y`` carries no met1
of its own inside ``xor2`` (``klt components`` reports it li1-only), so
*every* met1 shape in the cell belongs to another net and any contact is a
short.

Usage (from this directory)::

    python3 xor2-y-escape-scan.py            # -> xor2-y-escape-scan.json
"""

from __future__ import annotations

import json
import pathlib
import sys

import klayout.db as db

GDS = pathlib.Path(__file__).with_name("..") / "xor2" / "xor2.gds"
CELL = "xor2"
OUT = pathlib.Path(__file__).with_name("xor2-y-escape-scan.json")

# The array request's own routing width, and sky130's met1 minimum spacing
# (``m1.space`` = 0.14 um).  A stub is legal only if its drawn extent plus
# that spacing halo touches no other net's met1.
WIDTH_UM = 0.17
SPACING_UM = 0.14

# A point known to sit on ``y`` -- the tap the first (shorting) ``t1`` probe
# used.  Its own coordinate was never the bug; the escape direction was.
Y_SEED_UM = (4.5, 8.0)

# Scan step.  0.005 um = 1 dbu * 5; fine enough that a legal window narrower
# than a drawable wire cannot be missed, coarse enough to stay quick.
STEP_UM = 0.005

DIRECTIONS = {
    "north": (0, 1),
    "south": (0, -1),
    "east": (1, 0),
    "west": (-1, 0),
}


def merged_region(layout: db.Layout, cell: db.Cell, layer: int, datatype: int) -> db.Region:
    region = db.Region(cell.begin_shapes_rec(layout.layer(layer, datatype)))
    region.merge()
    return region


def main() -> int:
    layout = db.Layout()
    layout.read(str(GDS.resolve()))
    cell = layout.cell(CELL)
    dbu = layout.dbu

    li = merged_region(layout, cell, 67, 20)
    m1 = merged_region(layout, cell, 68, 20)
    bbox = cell.dbbox()

    seed = db.Point(int(round(Y_SEED_UM[0] / dbu)), int(round(Y_SEED_UM[1] / dbu)))
    y_net = db.Region()
    for poly in li.each():
        if poly.inside(seed):
            y_net.insert(poly)
    if y_net.is_empty():
        print(f"seed {Y_SEED_UM} is not on any li1 shape", file=sys.stderr)
        return 1
    y_bbox = y_net.bbox()

    # Halo: half the drawn width plus the spacing rule, applied to the stub
    # rectangle, so "touches" and "is too close to" are one test.
    halo = WIDTH_UM / 2.0 + SPACING_UM
    margin = 1.0  # push the stub a full micron past the cell boundary

    results: dict[str, dict] = {}
    for name, (dx, dy) in DIRECTIONS.items():
        legal: list[float] = []
        if dx == 0:
            lo, hi = y_bbox.left * dbu, y_bbox.right * dbu
        else:
            lo, hi = y_bbox.bottom * dbu, y_bbox.top * dbu
        steps = int(round((hi - lo) / STEP_UM)) + 1
        for i in range(steps):
            coord = lo + i * STEP_UM
            # Take the y net's own extreme point on this scan line, in the
            # escape direction, as the stub's start.
            if dx == 0:
                line = db.Region(
                    db.Box(
                        int(round((coord - dbu) / dbu)),
                        y_bbox.bottom,
                        int(round((coord + dbu) / dbu)),
                        y_bbox.top,
                    )
                ) & y_net
                if line.is_empty():
                    continue
                start = line.bbox().top * dbu if dy > 0 else line.bbox().bottom * dbu
                end = (bbox.top + margin) if dy > 0 else (bbox.bottom - margin)
                stub = db.DBox(coord - halo, min(start, end) - halo, coord + halo, max(start, end) + halo)
            else:
                line = db.Region(
                    db.Box(
                        y_bbox.left,
                        int(round((coord - dbu) / dbu)),
                        y_bbox.right,
                        int(round((coord + dbu) / dbu)),
                    )
                ) & y_net
                if line.is_empty():
                    continue
                start = line.bbox().right * dbu if dx > 0 else line.bbox().left * dbu
                end = (bbox.right + margin) if dx > 0 else (bbox.left - margin)
                stub = db.DBox(min(start, end) - halo, coord - halo, max(start, end) + halo, coord + halo)
            probe = db.Region(db.Box(
                int(round(stub.left / dbu)),
                int(round(stub.bottom / dbu)),
                int(round(stub.right / dbu)),
                int(round(stub.top / dbu)),
            ))
            if (probe & m1).is_empty():
                legal.append(round(coord, 4))

        # Collapse the legal scan coordinates into contiguous windows.
        windows: list[list[float]] = []
        for coord in legal:
            if windows and abs(coord - windows[-1][1]) <= STEP_UM * 1.5:
                windows[-1][1] = coord
            else:
                windows.append([coord, coord])
        results[name] = {
            "scan_axis": "x" if dx == 0 else "y",
            "legal_window_count": len(windows),
            "legal_windows_um": [[round(a, 4), round(b, 4)] for a, b in windows],
            "widest_window_um": round(max((b - a for a, b in windows), default=0.0), 4),
        }

    report = {
        "gds": str(GDS.resolve().relative_to(pathlib.Path(__file__).resolve().parents[2])),
        "cell": CELL,
        "y_net_seed_um": list(Y_SEED_UM),
        "y_net_bbox_um": [
            round(y_bbox.left * dbu, 4),
            round(y_bbox.bottom * dbu, 4),
            round(y_bbox.right * dbu, 4),
            round(y_bbox.top * dbu, 4),
        ],
        "cell_bbox_um": [
            round(bbox.left, 4),
            round(bbox.bottom, 4),
            round(bbox.right, 4),
            round(bbox.top, 4),
        ],
        "met1_polygon_count": m1.count(),
        "stub_width_um": WIDTH_UM,
        "met1_spacing_um": SPACING_UM,
        "scan_step_um": STEP_UM,
        "escapes": results,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
