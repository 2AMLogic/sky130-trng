#!/usr/bin/env python3
"""Where two record bodies differ, as a set of dotted field paths (issue #467).

A superseding record is only a correction if it changes *the field the
correction is about* and nothing else.  ``field_diff`` answers that question
precisely -- it walks two JSON-shaped record bodies in parallel and returns the
dotted paths at which they differ, with list indices collapsed to ``[]`` so a
per-row/per-pair field reports once rather than 1764 times.

``eq`` is the equality the owning reducer's own replay uses (``ripple.py``
compares floats to a relative tolerance; ``sensitivity.py`` compares exactly),
so a "differs" here means exactly what a failed ``--check`` would mean there.

Shared by sim/tests/test_ripple_reduction.py and sim/tests/test_vth_drift.py.
Standard library only.
"""
from __future__ import annotations

import operator


def field_diff(a, b, eq=operator.eq, prefix=""):
    """-> sorted list of dotted paths where `a` and `b` differ under `eq`.

    A differing *shape* (different dict keys, different list length) reports the
    containing path rather than descending, so a structural change is never
    silently attributed to one leaf field.
    """
    return sorted(set(_walk(a, b, eq, prefix)))


def _walk(a, b, eq, prefix):
    if isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
        for k in a:
            yield from _walk(a[k], b[k], eq, f"{prefix}.{k}" if prefix else k)
        return
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for x, y in zip(a, b):
            yield from _walk(x, y, eq, f"{prefix}[]")
        return
    if not eq(a, b):
        yield prefix
