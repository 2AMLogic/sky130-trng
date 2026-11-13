#!/usr/bin/env python3
"""The one definition of "closest approach of a ring pair to a mutual-injection-lock rational".

DR-0003 section 8 names the small rationals a `wstv` ring ladder has to stay
clear of, and DR-0005 section 2
(``spec/decision-records/DR-0005-post-layout-parasitics-and-wstv-decorrelation.md``)
fixes both the set and the convention for reporting the distance:

    "The closest approach of any ring pair to any locking rational ... is 9.3%
    (... 1.2096 against 4/3)"

i.e. the ratio is formed **slower period over faster period**, so it is always
>= 1, and it is compared against a rational that is also written >= 1.  The
figure is therefore symmetric in the two rings: a mismatch-induced swap of two
rings' order does not change it, and there is exactly one answer per pair.

Why this module exists (issue #467)
-----------------------------------
This quantity used to be implemented five separate times, each with its own
copy of the rational set:

* ``sim/local-mismatch-monte-carlo/reduce.py``          -- symmetric
* ``sim/post-layout-parasitic-impact/analysis/parasitic-impact.py`` -- symmetric
* ``sim/post-layout-sampler-core/analysis/substrate-bracket.py``    -- symmetric
* ``sim/ro-array-supply-perturbation/ripple.py``        -- **order-dependent**
* ``sim/ro-vth-drift-sensitivity/analysis/sensitivity.py`` -- **order-dependent**

The last two took ``r = Tj / Ti`` in the order the caller passed the rings and
searched both ``p/q`` and ``q/p``, which is *not* the same number as the
symmetric form: ``|r/x - 1|`` and ``|(1/r)/(1/x) - 1|`` differ whenever the
pair is not an exact hit.  Their docstring claimed "Order-free"; it was not.
Because their callers pass the rings in index order rather than period order,
the committed records carried the other convention -- always reporting *more*
margin from the lock rational than DR-0005's own definition gives (e.g. span
1.2096 against 4/3 as 10.23 % rather than DR-0005's 9.3 %).

Both now call this module, so there is one convention, one rational set, and
one place to change either.  The arithmetic below is byte-for-byte the form
``reduce.py`` already used, so the records of the three already-symmetric
callers replay unchanged.

Use :func:`closeness` when you hold two periods (or two frequencies -- the
ratio of the larger to the smaller is the same quantity either way), and
:func:`closeness_ratio` when a caller has already formed the ratio.
"""

from __future__ import annotations

#: The small rationals DR-0003 section 8 / DR-0005 section 2 name as the
#: mutual-injection-lock hazard.  Written ``(p, q)`` with ``p > q``.
DR5_RATIOS = ((2, 1), (3, 2), (4, 3))

#: The same set plus 1:1, for the "closest approach to *any* small rational,
#: including two rings running together" question.
ANY_RATIOS = ((1, 1), (2, 1), (3, 2), (4, 3))


def closeness_ratio(r, ratios=DR5_RATIOS):
    """Closest approach of a single period/frequency ratio to ``ratios``.

    ``r`` may be given either way up; it is normalized to ``>= 1`` first, which
    is what makes the result symmetric.  Returns ``(distance, p, q)`` with
    ``p >= q``, where ``distance`` is the relative distance ``|R/(p/q) - 1|``
    of the normalized ratio ``R`` from the nearest rational in the set.
    """
    if r <= 0:
        raise ValueError(f"ratio must be positive, got {r!r}")
    R = r if r >= 1 else 1 / r
    best = None
    for p, q in ratios:
        hi, lo = (p, q) if p >= q else (q, p)
        d = abs(R / (hi / lo) - 1)
        if best is None or d < best[0]:
            best = (d, hi, lo)
    return best


def closeness(Ti, Tj, ratios=DR5_RATIOS):
    """Closest approach of the ring pair ``(Ti, Tj)`` to ``ratios``.

    ``Ti``/``Tj`` are periods (seconds, or any consistent unit).  The ratio is
    formed slower-over-faster per DR-0005 section 2, so the result does not
    depend on the order the two rings are passed in.  Returns
    ``(distance, p, q)`` with ``p >= q`` -- e.g. ``(0.0928, 4, 3)`` for periods
    1.0 and 1.2096 in either order.
    """
    if Ti <= 0 or Tj <= 0:
        raise ValueError(f"periods must be positive, got {Ti!r}, {Tj!r}")
    return closeness_ratio(max(Ti, Tj) / min(Ti, Tj), ratios)


def ratio_label(p, q):
    """``"4/3"`` -- the slower/faster spelling the records store."""
    return f"{p}/{q}"


def pair_closeness(T, ratios=DR5_RATIOS):
    """Closest approach over every unordered pair of the periods in ``T``.

    Returns ``(distance, "i-j", "p/q")`` with 1-based ring indices in the order
    they appear in ``T``.
    """
    best = None
    for i in range(len(T)):
        for j in range(i + 1, len(T)):
            d, p, q = closeness(T[i], T[j], ratios)
            if best is None or d < best[0]:
                best = (d, f"{i + 1}-{j + 1}", ratio_label(p, q))
    return best
