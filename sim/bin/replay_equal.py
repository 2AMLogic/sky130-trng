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


def replay_equal(a, b, rel=1e-9):
    """Structural equality where floats match to `rel` (relative) instead of bit-for-bit.
    The CPython <= 3.11 vs >= 3.12 builtin `sum()` split re-derives a committed
    record ~1-ulp (~1e-16 relative) apart, well inside `rel`.  There is no
    absolute floor (DR-0020): exact equality is the only special case, and
    anything above `rel` relative -- including exactly 0.0 versus any non-zero
    value, however tiny -- is a real change."""
    if isinstance(a, float) or isinstance(b, float):
        return (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool)
                and not isinstance(b, bool) and (a == b or math.isclose(a, b, rel_tol=rel, abs_tol=0.0)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(replay_equal(a[k], b[k], rel) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(replay_equal(x, y, rel) for x, y in zip(a, b))
    return a == b
