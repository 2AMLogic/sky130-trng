#!/usr/bin/env python3
"""The one definition of the committed-record replay equality (issue #519).

Python 3.12 made builtin float ``sum()`` compensated (Neumaier), so a record
emitted on 3.12 replays ~1-ulp different on 3.11 (the CI interpreter) and vice
versa.  Reducers that replay committed records compare with ``replay_equal`` --
floats to a relative tolerance, everything else bit-for-bit -- instead of exact
equality: the ``sum()`` split is ~1e-16 relative, well inside the gate
``|a-b| <= max(1e-9*|v|, 1e-12)``.  That is a *relative* bound only where the
relative term dominates: below ~1e-12 in magnitude the absolute floor takes
over and the effective relative sensitivity degrades to ``1e-12/|v|`` -- a
study replaying sub-1e-12-scale metrics must quantify the floor per field
before claiming a 1e-9 bound (measured example: issue #547).  Hash-based
integrity pins (``sha256`` over committed bytes) stay exact; no tolerance
bridges a hash.

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


def replay_equal(a, b, rel=1e-9):
    """Structural equality where floats match to `rel` (relative) instead of bit-for-bit.
    Python 3.12 made float `sum()` compensated, so a record emitted on 3.12 replays
    1-ulp different on 3.11 (the CI interpreter); anything above 1e-9 is a real change."""
    if isinstance(a, float) or isinstance(b, float):
        return (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool)
                and not isinstance(b, bool) and (a == b or math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(replay_equal(a[k], b[k], rel) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(replay_equal(x, y, rel) for x, y in zip(a, b))
    return a == b
