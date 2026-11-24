#!/usr/bin/env python3
"""Shared klayout-geometry helpers for the layout tree's scan scripts.

Four functions -- :func:`merged`, :func:`dbox_region`, :func:`merge_spans`
and :func:`carrying` -- that this tree's measurement scripts share *across*
subdirectories. They arrived here in three extractions that each stopped
short of the other directories' copies: ``layout/sampler_core``'s own
``_geom_common.py`` (issues #122/#124/#129/#141),
``layout/ro_array_core``'s own ``_geom_common.py`` (issue #131), and
``layout/ro_array_core-placement-poc/xor2-y-escape-scan.py``'s inline
``merged_region()`` -- each carve-out justified by a docstring claim that
the implementations differed in a way that mattered. Issue #490 measured
that claim and found it false; the operator ruling of 2026-11-23 retired
the carve-outs and consolidated all three copies into this module.

The measured equivalence (klayout 0.30.10, four committed GDS streams:
``layout/ro_array_core/ro_array_core.gds``, ``layout/ro_array_core/vddbus.gds``,
``layout/sampler_core/sampler_core.gds``, ``layout/sampler_core/place.gds``):
``Region(cell.begin_shapes_rec(layout.layer(*key)))`` and
``Region(db.RecursiveShapeIterator(layout, cell, layout.layer(*key)))``
produce byte-identical geometry -- 28 non-empty layer comparisons, 0
differences, under exact boolean difference in both directions plus
polygon count and area. ``Cell#begin_shapes_rec`` *returns* a
``RecursiveShapeIterator`` over that cell's hierarchy on that layer, i.e.
the same object the explicit constructor builds. The only differences
between the former copies were the parameter name (``spec`` vs ``key``)
and, for ``merged_region()``, whether the ``(layer, datatype)`` pair
arrived packed as a tuple or unpacked as two parameters. The surviving
spelling is the explicit ``RecursiveShapeIterator`` form with the
parameter named ``key``.

Import it the way ``_klt_common`` / ``_hashing`` / ``_gds_geometry`` are
imported -- these are scripts, not an installed package, so the importer
puts this file's directory on ``sys.path`` and imports it by bare module
name::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))      # elsewhere
    from _geom_common import carrying, merge_spans, merged  # noqa: E402
"""

from __future__ import annotations

import klayout.db as db


def merged(layout: db.Layout, cell: db.Cell, key: tuple[int, int]) -> db.Region:
    """Every shape on ``key``, flattened out of the hierarchy and merged."""
    index = layout.layer(*key)
    region = db.Region(db.RecursiveShapeIterator(layout, cell, index))
    region.merge()
    return region


def dbox_region(box: db.DBox, dbu: float) -> db.Region:
    """Convert a micron-space ``db.DBox`` into a database-unit ``db.Region``."""
    return db.Region(
        db.Box(
            int(round(box.left / dbu)),
            int(round(box.bottom / dbu)),
            int(round(box.right / dbu)),
            int(round(box.top / dbu)),
        )
    )


def merge_spans(spans: list[tuple[float, float]]) -> list[list[float]]:
    """Merge a sorted list of ``(lo, hi)`` intervals, coalescing touching ones."""
    out: list[list[float]] = []
    for lo, hi in spans:
        if out and lo <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def carrying(nets: list[str], *tokens: str) -> list[str]:
    """Every net in ``nets`` whose ``|``-joined label carries all ``tokens``."""
    return [n for n in nets if all(token in n.split("|") for token in tokens)]
