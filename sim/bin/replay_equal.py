#!/usr/bin/env python3
"""The one definition of the committed-record replay equality (issue #519).

Python 3.12 made builtin float ``sum()`` compensated (Neumaier), so a record
emitted on 3.12 replays ~1-ulp different on 3.11 (the CI interpreter) and vice
versa.  Reducers that replay committed records compare with ``replay_equal`` --
floats to a relative tolerance, everything else bit-for-bit -- instead of exact
equality: the ``sum()`` split is ~1e-16 relative, well inside the gate
``|a-b| <= 1e-9*|v|`` (DR-0020).  There is **no absolute floor**: exact
equality (``a == b``, which also makes ``0.0`` equal to ``-0.0``) is the only
special case, so zero versus any non-zero float -- however tiny, down to the
smallest subnormal -- is a difference.  That is what keeps the advertised
1e-9 relative bound meaningful on sub-picosecond-scale metrics (``sigma_1_raw``
~1.4e-12, ``numerical_floor`` ~6.5e-13, ``pull_fraction`` ~2e-15) whose whole
magnitude once sat below the 1e-12 absolute floor this comparator carried
until DR-0020 removed it -- up to a 155 % relative drift read MATCH there
(measured exposure: issue #547).  Hash-based integrity pins (``sha256`` over
committed bytes) stay exact; no tolerance bridges a hash.

Why this module exists (issue #519)
-----------------------------------
``_replay_equal`` used to live only in
``sim/ro-array-supply-perturbation/ripple.py``; every other reducer replayed
with exact float equality, so ``sensitivity.py --check`` returned MATCHES on
the interpreter that happened to mint a record and DIFFERS on the other.
This is the ``sim/bin/lock_proximity.py`` pattern from issue #467: one shared
rule, no per-reducer re-fork.

Standard library only.
"""
from __future__ import annotations

import math

REPLAY_REL_TOL = 1e-9  # DR-0020: the one relative gate every sim/ replay uses


def _float_leaf_equal(a, b, rel, nan_equal):
    """The single DR-0020 float rule every replay comparator shares: relative-only
    (`a == b or math.isclose(a, b, rel_tol=rel, abs_tol=0.0)`; no absolute floor,
    so 0.0 versus any non-zero float is a difference), plus the optional
    `(NaN, NaN)` acceptance `replay_diff(..., nan_equal=True)` pins for callers
    whose payloads legitimately carry NaN."""
    if nan_equal and isinstance(a, float) and isinstance(b, float) \
            and math.isnan(a) and math.isnan(b):
        return True
    return a == b or math.isclose(a, b, rel_tol=rel, abs_tol=0.0)


def replay_equal(a, b, rel=REPLAY_REL_TOL):
    """Structural equality where floats match to `rel` (relative) instead of bit-for-bit.
    The CPython <= 3.11 vs >= 3.12 builtin `sum()` split re-derives a committed
    record ~1-ulp (~1e-16 relative) apart, well inside `rel`.  There is no
    absolute floor (DR-0020): exact equality is the only special case, and
    anything above `rel` relative -- including exactly 0.0 versus any non-zero
    value, however tiny -- is a real change."""
    if isinstance(a, float) or isinstance(b, float):
        return (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool)
                and not isinstance(b, bool) and _float_leaf_equal(a, b, rel, False))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(replay_equal(a[k], b[k], rel) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(replay_equal(x, y, rel) for x, y in zip(a, b))
    return a == b


def replay_diff(want, got, path="$", *, rel=REPLAY_REL_TOL, strict_types=False,
                nan_equal=False):
    """Diff-style twin of `replay_equal` (issue #659): same tree walk, same
    DR-0020 relative-only float rule, but returns the list of mismatch paths
    (empty list == reproduces) instead of a bool, for reducers that report
    *where* a replay differs.  Non-float leaves are exact.

    `strict_types=True` rejects cross-type pairs everywhere (notably `1` vs
    `1.0`, which plain `replay_equal` accepts); `nan_equal=True` accepts a
    `(NaN, NaN)` float pair (which plain `replay_equal` never does)."""
    if strict_types and type(want) is not type(got):
        return [f"{path}: type {type(want).__name__} != {type(got).__name__}"]
    if isinstance(want, float) or isinstance(got, float):
        if strict_types:
            ok = type(want) is float and type(got) is float
        else:
            ok = (isinstance(want, (int, float)) and isinstance(got, (int, float))
                  and not isinstance(want, bool) and not isinstance(got, bool))
        if ok and _float_leaf_equal(want, got, rel, nan_equal):
            return []
        return [f"{path}: {want!r} != {got!r}"]
    if isinstance(want, dict) and isinstance(got, dict):
        if want.keys() != got.keys():
            return [f"{path}: keys differ "
                    f"{sorted(set(want) ^ set(got))}"]
        out: list[str] = []
        for k in want:
            out += replay_diff(want[k], got[k], f"{path}.{k}", rel=rel,
                               strict_types=strict_types, nan_equal=nan_equal)
        return out
    if isinstance(want, list) and isinstance(got, list):
        if len(want) != len(got):
            return [f"{path}: length {len(want)} != {len(got)}"]
        out = []
        for i, (w, g) in enumerate(zip(want, got)):
            out += replay_diff(w, g, f"{path}[{i}]", rel=rel,
                               strict_types=strict_types, nan_equal=nan_equal)
        return out
    if want == got:
        return []
    return [f"{path}: {want!r} != {got!r}"]
