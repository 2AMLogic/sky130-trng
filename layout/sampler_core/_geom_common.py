#!/usr/bin/env python3
"""Shared klayout-geometry helper for ``layout/sampler_core``'s scan scripts.

``merged()`` was hand-rolled, byte-identical (modulo one docstring), in
``vss-strap-scan.py``, ``vdd-strap-scan.py``, and ``data-path-scan.py``.
Extracted per issue #122, following ``design/_pdk_search.py``'s own
precedent (issue #25) and ``layout/bin/_klt_common.py``'s (issues #49/#52):
shared plumbing lives here once instead of as a copy per script.

Not ``layout/ro_array_core/vss-tap-scan.py``'s own ``merged()`` -- that one
is a different implementation (``cell.begin_shapes_rec`` instead of
``db.RecursiveShapeIterator``) and out of scope for this extraction.
"""

from __future__ import annotations

import klayout.db as db


def merged(layout: db.Layout, cell: db.Cell, key: tuple[int, int]) -> db.Region:
    """Every shape on ``key``, flattened out of the hierarchy and merged."""
    index = layout.layer(*key)
    region = db.Region(db.RecursiveShapeIterator(layout, cell, index))
    region.merge()
    return region
