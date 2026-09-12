#!/usr/bin/env python3
"""Shared klayout-geometry helpers for ``ro_array_core``'s scan scripts.

``merged()`` and ``dbox_region()`` were hand-rolled, byte-identical, in
``layout/ro_array_core/vss-tap-scan.py`` and
``layout/ro_array_core-placement-poc/vdd-tap-scan.py``.  Extracted per
issue #131, following ``layout/sampler_core/_geom_common.py``'s own
precedent (issues #122/#124/#129) and ``layout/bin/_klt_common.py``'s
(issues #49/#52): shared plumbing lives here once instead of as a copy
per script.

This ``merged()`` uses ``cell.begin_shapes_rec`` -- a different
implementation from ``layout/sampler_core/_geom_common.py``'s own
``merged()``, which uses ``db.RecursiveShapeIterator`` directly. The two
are not interchangeable call-for-call, which is why that module's
docstring explicitly carves this one out as out of scope for its own
extraction.

Not ``layout/ro_array_core-placement-poc/xor2-y-escape-scan.py``'s own
``merged_region()`` -- that one has a different signature (``layer``,
``datatype`` parameters instead of a ``spec``/``key`` tuple) and is out
of scope for this extraction.
"""

from __future__ import annotations

import klayout.db as db


def merged(layout: db.Layout, cell: db.Cell, spec: tuple[int, int]) -> db.Region:
    """Every shape on ``spec``, flattened out of the hierarchy and merged."""
    region = db.Region(cell.begin_shapes_rec(layout.layer(*spec)))
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
