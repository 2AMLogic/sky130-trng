#!/usr/bin/env python3
"""Digital-section parameters, and the arithmetic that derives them.

Every constant in this module is either

* a **structural** choice (window size, compression ratio, polynomial),
  carried over from ``gf180-trng`` as process-independent methodology per
  ``spec/porting-plan.md`` §1.1, or
* a **derived** number computed here from a stated min-entropy assumption
  ``H``, by exactly the SP 800-90B §4.4.1/§4.4.2 formulas -- never a number
  copied across from the sibling repository.

The distinction is the whole point of this file: ``C_RCT`` and ``C_APT`` are
*formula evaluations*, and this module keeps the formula next to the value so
that re-evaluating at a different ``H`` is a one-line change rather than an
archaeology exercise. See
``spec/decision-records/DR-0004-sky130-digital-section-architecture.md`` §2
for the decision this implements and for why ``H`` is currently a *design
target*, not a measurement.

The cutoff computation uses :mod:`decimal` at 80 significant digits rather
than floats, because the binomial tail being solved for is ``2**-40`` -- far
below the point where a float-accumulated sum of 1024 terms is trustworthy.

Run it directly for the cutoff table over an ``H`` grid::

    python3 digital/model/params.py
"""

from __future__ import annotations

import math
from decimal import Decimal, getcontext

getcontext().prec = 80

# --------------------------------------------------------------------------
# Structural parameters (carried over as methodology, not as measurements)
# --------------------------------------------------------------------------

#: False-alarm probability per test decision, as the negative log2. SP 800-90B
#: recommends 2**-20 ... 2**-40; DR-0004 §2.2 re-derives the choice against
#: *this* repository's own 50 kbps raw rate (DR-0003) rather than inheriting
#: gf180-trng's 1 Mbps-era justification.
ALPHA_LOG2 = 40

#: Adaptive Proportion Test window, in samples. SP 800-90B §4.4.2 fixes 1024
#: for a binary source.
W_APT = 1024

#: Start-up health test length, in samples (SP 800-90B §4.3: at least 1024
#: consecutive samples must pass the continuous tests before any conditioned
#: output is released).
STARTUP_SAMPLES = 1024

#: Conditioner compression ratio: ``K`` raw bits per output bit, i.e.
#: ``32 * K`` raw bits in, one 32-bit word out.
K_COMPRESS = 8

#: Output word width, both paths.
WORD_BITS = 32

#: Raw bits absorbed per conditioned output word.
COND_BLOCK_BITS = WORD_BITS * K_COMPRESS  # 256

#: CRC-32 (ISO 3309 / IEEE 802.3) generator polynomial, non-reflected form.
CRC32_POLY = 0x04C11DB7

#: CRC-32 register initial value, applied at every block boundary.
CRC32_INIT = 0xFFFFFFFF

#: Output FIFO depth, in 32-bit words, for each of the two paths.
FIFO_DEPTH = 4


# --------------------------------------------------------------------------
# Derived parameters: the SP 800-90B cutoff formulas
# --------------------------------------------------------------------------

def c_rct(h: float, alpha_log2: int = ALPHA_LOG2) -> int:
    """Repetition Count Test cutoff (SP 800-90B §4.4.1).

    ``C = 1 + ceil(-log2(alpha) / H)``. The test fails when ``C`` consecutive
    identical samples are observed.
    """
    if h <= 0:
        raise ValueError("H must be positive")
    return 1 + math.ceil(alpha_log2 / h)


def binomial_upper_tail(w: int, p: Decimal, c: int) -> Decimal:
    """``Pr(X >= c)`` for ``X ~ Binomial(w, p)``, exact to the Decimal context."""
    q = Decimal(1) - p
    total = Decimal(0)
    coeff = Decimal(1)  # C(w, w)
    for k in range(w, c - 1, -1):
        total += coeff * (p ** k) * (q ** (w - k))
        # C(w, k-1) = C(w, k) * k / (w - k + 1)
        coeff = coeff * Decimal(k) / Decimal(w - k + 1)
    return total


def c_apt(h: float, w: int = W_APT, alpha_log2: int = ALPHA_LOG2) -> int | None:
    """Adaptive Proportion Test cutoff (SP 800-90B §4.4.2).

    The smallest ``C`` for which ``Pr(X >= C) <= alpha``, with
    ``X ~ Binomial(w, 2**-H)``. Returns ``None`` when no such ``C <= w``
    exists -- the *degeneracy* case DR-0004 §2.4 calls out, which happens
    below :func:`apt_degeneracy_floor`.
    """
    alpha = Decimal(2) ** -alpha_log2
    p = Decimal(2) ** Decimal(str(-h))
    q = Decimal(1) - p
    coeff = Decimal(1)
    tail = p ** w  # Pr(X >= w)
    if tail > alpha:
        return None
    best = w
    k = w
    while k > 0:
        coeff = coeff * Decimal(k) / Decimal(w - k + 1)
        tail = tail + coeff * (p ** (k - 1)) * (q ** (w - k + 1))
        if tail > alpha:
            break
        best = k - 1
        k -= 1
    return best


def apt_degeneracy_floor(w: int = W_APT, alpha_log2: int = ALPHA_LOG2) -> float:
    """The ``H`` below which the APT has no valid cutoff at all.

    ``Pr(X >= w) = p**w = 2**(-H*w)``, so a cutoff exists only while
    ``2**(-H*w) <= 2**-alpha_log2``, i.e. ``H >= alpha_log2 / w``. For this
    block's ``alpha = 2**-40, W = 1024`` that floor is exactly ``0.0390625``.

    Exactly *at* the floor the tail equals ``alpha`` to the last bit, which
    :func:`c_apt` reports as degenerate (its 80-digit evaluation lands a
    fraction above ``alpha``); the floor is therefore an open bound in
    practice, and the test is meaningless well above it -- ``C_APT`` is still
    1022 of 1024 at ``H = 0.05``.
    """
    return alpha_log2 / w


# --------------------------------------------------------------------------
# The adopted operating parameters (DR-0004 §2)
# --------------------------------------------------------------------------

#: The min-entropy the cutoffs below are evaluated at. This is the README's
#: *design target* row (``H0 = 0.5`` bit/sample), deliberately NOT the
#: model-derived ``H = 0.5415`` DR-0003 §3 reports for the chosen operating
#: point -- see DR-0004 §2.3 for why the floor, not the model value, sets the
#: cutoffs. **Provisional**: no sky130 raw bitstream has been simulated yet
#: (issue #21), so no measured ``H`` exists for this process.
H_DESIGN = 0.5

#: Repetition Count Test cutoff at ``H_DESIGN``. Asserted against
#: :func:`c_rct` by ``sim/tests/test_digital_section.py``.
C_RCT = 81

#: Adaptive Proportion Test cutoff at ``H_DESIGN``. Asserted against
#: :func:`c_apt` by ``sim/tests/test_digital_section.py``.
C_APT = 824


def cutoff_table(h_grid) -> list[dict]:
    """``[{h, c_rct, c_apt}, ...]`` over an ``H`` grid, for the record trail."""
    rows = []
    for h in h_grid:
        rows.append({
            "h": h,
            "c_rct": c_rct(h),
            "c_apt": c_apt(h),
        })
    return rows


#: The grid the evidence record tabulates: the degeneracy floor and just above
#: it, the design target, the DR-0003 model-derived value, and the extremes.
H_GRID = [0.0390625, 0.04, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.5415,
          0.6, 0.7, 0.8, 0.9, 1.0]


def main() -> int:
    print(f"alpha = 2^-{ALPHA_LOG2}, W = {W_APT}")
    print(f"APT degeneracy floor: H = {apt_degeneracy_floor():.7f}")
    print()
    print("| H | C_RCT | C_APT |")
    print("|---|---|---|")
    for row in cutoff_table(H_GRID):
        apt = row["c_apt"]
        print(f"| {row['h']:.7g} | {row['c_rct']} | "
              f"{'none (degenerate)' if apt is None else apt} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
