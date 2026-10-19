#!/usr/bin/env python3
"""Lag-k match-count monitor: STUDY model for DR-0015 (issue #301). Not adopted.

Additive to :mod:`digital.model.health`: nothing here is imported by, or
changes, the RCT/APT tests, ``C_RCT``, ``C_APT``, ``W`` or DR-0004. The
monitor is not wired into :class:`~digital.model.health.HealthMonitor`, the
register map or the RTL; it exists so ``spec/decision-records/
DR-0015-lag-count-monitor-study.md`` can derive its coverage, false-alarm
limit and cost against a bit-exact reference rather than a sketch.

What it detects. RCT and APT see bias and run length. A balanced period-k
stream has marginal bias 1/2 and runs bounded by k, so both pass it. The
lag-j match count ``M_j = #{i in window : x[i] == x[i-j]}`` sees it: for a
period dividing j the match rate is 1 (less flip noise), for an ideal i.i.d.
source it is 1/2.

Definition (the contract the RTL would have to meet):

* a history register holds the last ``lags`` samples; the first ``lags``
  samples after reset only fill it (warm-up, no comparisons);
* from then on every sample is compared with each of the ``lags`` older
  samples ``x[i-1] .. x[i-lags]``, and ``lags`` counters count matches;
* the verdict is taken once per ``window`` comparisons: lag ``j`` fails when
  its count is ``>= cutoff``; the window then restarts (counters cleared,
  history register carried over);
* the alarm is sticky. Latency to the first possible verdict is
  ``lags + window`` samples.

The cutoff is derived, never copied, in the manner of DR-0004 §2.1-2.3: the
smallest ``C`` whose exact upper tail is at most ``alpha`` for an i.i.d.
source at the min-entropy floor ``H_DESIGN``. For a binary i.i.d. source with
``p = 2**-H`` the match probability at any lag is ``p**2 + (1-p)**2``
(0.5858 at ``H`` = 0.5), and the per-lag ``alpha`` is the per-window
``2**-ALPHA_LOG2`` divided by the number of lags (Bonferroni: the union
bound over lags, conservative because the lag counts are positively
correlated).

Two derivations are provided and the difference matters:

* :func:`c_lag_binomial` -- the DR-0004 §2 method verbatim, ``Bin(W, p**2 +
  q**2)``. It treats the ``W`` match indicators as independent. They are not
  for a biased source: at lag ``j`` the indicators ``[x[i] == x[i-j]]`` and
  ``[x[i+j] == x[i]]`` share ``x[i]``, so they are 1-dependent, with
  covariance ``p**3 + q**3 - (p**2 + q**2)**2`` (0.0356 against a variance
  of 0.2427 at ``H`` = 0.5, a 29 % variance excess). The binomial is exact
  only for a fair coin. **Under-covers at the H floor** (see the loosened-alpha
  calibration in the experiment-J record).
* :func:`c_lag` -- the cutoff the monitor uses: the exact distribution of
  the lag-1 match count of an i.i.d. biased source (a Markov-chain DP, no
  independence assumption). Lag 1 is one chain of ``W`` dependent pairs;
  lag ``j`` is ``j`` interleaved shorter chains with the same total
  variance, and the lag-1 tail is the heaviest (checked by
  ``sim/tests/test_health_detection_coverage.py``).
"""

from __future__ import annotations

import math
from decimal import Decimal, getcontext

from .params import ALPHA_LOG2, H_DESIGN

getcontext().prec = 80

#: Candidate window, in comparisons. 1024 mirrors W_APT; the DR tabulates others.
STUDY_WINDOW = 1024


def match_probability(h: float) -> Decimal:
    """``p**2 + (1-p)**2`` with ``p = 2**-h``: lag match rate of an i.i.d. source at min-entropy ``h``."""
    p = Decimal(2) ** Decimal(str(-h))
    q = Decimal(1) - p
    return p * p + q * q


def binomial_cutoff(w: int, p: Decimal, alpha: Decimal) -> int | None:
    """Smallest ``C`` with ``Pr(Binomial(w, p) >= C) <= alpha``; ``None`` if none ``<= w``.

    Same exact-tail walk as :func:`digital.model.params.c_apt`, generalised
    to an arbitrary ``p`` and ``alpha`` so the two can be cross-checked.
    """
    q = Decimal(1) - p
    tail = p ** w
    if tail > alpha:
        return None
    best = w
    coeff = Decimal(1)
    k = w
    while k > 0:
        coeff = coeff * Decimal(k) / Decimal(w - k + 1)
        tail = tail + coeff * (p ** (k - 1)) * (q ** (w - k + 1))
        if tail > alpha:
            break
        best = k - 1
        k -= 1
    return best


def c_lag_binomial(lags: int, window: int = STUDY_WINDOW, h: float = H_DESIGN,
                   alpha_log2: int = ALPHA_LOG2) -> int:
    """DR-0004 §2-style cutoff, ``Bin(W, p**2+q**2)``: valid only for independent indicators (fair coin)."""
    alpha = Decimal(2) ** -alpha_log2 / Decimal(lags)
    c = binomial_cutoff(window, match_probability(h), alpha)
    if c is None:
        raise ValueError("no valid cutoff for this window/lags/alpha")
    return c


#: probability mass below this is dropped from the DP; total error << any alpha used here
_PRUNE = 1e-32


def chain_match_pmf(pairs: int, p1: float):
    """Exact PMF of the number of adjacent equal pairs among ``pairs + 1`` i.i.d. Bernoulli(``p1``) bits.

    Returns ``(offset, pmf)`` with ``pmf[i] = Pr(count == offset + i)``; mass
    below ``_PRUNE`` per cell is dropped (at most ``pairs * width * _PRUNE``
    in total, ~1e-24 for the windows used here). Probabilities are positive
    sums, so float64 keeps ~1e-13 relative accuracy down to ~1e-300.
    """
    q1 = 1.0 - p1
    # a[k]: last bit 0, k matches so far; b[k]: last bit 1
    lo = 0
    a, b = [q1], [p1]
    for _ in range(pairs):
        n = len(a)
        na = [0.0] * (n + 1)
        nb = [0.0] * (n + 1)
        for k in range(n):
            ak, bk = a[k], b[k]
            # next bit 0 (prob q1): from a it matches (k+1), from b it does not (k)
            na[k + 1] += q1 * ak
            na[k] += q1 * bk
            # next bit 1 (prob p1): from b it matches (k+1), from a it does not (k)
            nb[k + 1] += p1 * bk
            nb[k] += p1 * ak
        # prune the negligible low and high ends
        first = 0
        while first < len(na) - 1 and na[first] + nb[first] < _PRUNE:
            first += 1
        last = len(na) - 1
        while last > first and na[last] + nb[last] < _PRUNE:
            last -= 1
        a, b = na[first:last + 1], nb[first:last + 1]
        lo += first
    return lo, [x + y for x, y in zip(a, b)]


def _convolve(x, y):
    out = [0.0] * (len(x) + len(y) - 1)
    for i, xi in enumerate(x):
        if xi:
            for j, yj in enumerate(y):
                out[i + j] += xi * yj
    return out


def match_count_pmf(window: int, lag: int, p1: float):
    """Exact PMF of the lag-``lag`` match count over ``window`` comparisons of an i.i.d. Bernoulli(``p1``) stream.

    ``lag`` interleaved chains (residues of ``i mod lag``), independent of one another.
    """
    base, extra = divmod(window, lag)
    offset = 0
    pmf = [1.0]
    for r in range(lag):
        m = base + (1 if r < extra else 0)
        o, c = chain_match_pmf(m, p1)
        offset += o
        pmf = _convolve(pmf, c)
    return offset, pmf


def exact_tail(window: int, lag: int, p1: float, cutoff: int) -> float:
    """``Pr(M_lag >= cutoff)`` for an i.i.d. Bernoulli(``p1``) source, no independence assumption."""
    off, pmf = match_count_pmf(window, lag, p1)
    return sum(pmf[max(0, cutoff - off):])


_TAIL_CACHE: dict = {}


def _lag1_tail_table(window: int, h: float):
    """``(offset, suffix)`` with ``suffix[i] = Pr(M_1 >= offset + i)`` at the ``H``-floor source."""
    key = (window, h)
    if key not in _TAIL_CACHE:
        p1 = 2.0 ** -h
        off, pmf = chain_match_pmf(window, p1)
        suffix = [0.0] * (len(pmf) + 1)
        for i in range(len(pmf) - 1, -1, -1):
            suffix[i] = suffix[i + 1] + pmf[i]
        _TAIL_CACHE[key] = (off, suffix)
    return _TAIL_CACHE[key]


def c_lag(lags: int, window: int = STUDY_WINDOW, h: float = H_DESIGN,
          alpha_log2: int = ALPHA_LOG2) -> int:
    """Per-lag cutoff ``C_L``: smallest ``C`` with exact (dependence-aware) ``Pr(M >= C) <= 2**-alpha_log2 / lags``.

    Evaluated at lag 1 of an i.i.d. source with ``P(1) = 2**-h`` (the heaviest
    tail over lags, asserted in the tests) -- the min-entropy floor, as in
    DR-0004 §2.3.
    """
    alpha = 2.0 ** -alpha_log2 / lags
    off, suffix = _lag1_tail_table(window, h)
    for i in range(len(suffix) - 1):
        if suffix[i] <= alpha:
            return off + i
    raise ValueError("no valid cutoff for this window/lags/alpha")


def tail_probability(window: int, rate: float, cutoff: int) -> float:
    """``Pr(Binomial(window, rate) >= cutoff)`` in floats (log-space; for detection power, not cutoffs)."""
    if rate <= 0.0:
        return 0.0 if cutoff > 0 else 1.0
    if rate >= 1.0:
        return 1.0
    lr, lq = math.log(rate), math.log1p(-rate)
    logs = [math.lgamma(window + 1) - math.lgamma(k + 1) - math.lgamma(window - k + 1)
            + k * lr + (window - k) * lq for k in range(cutoff, window + 1)]
    m = max(logs)
    return min(1.0, math.exp(m) * sum(math.exp(x - m) for x in logs))


class LagCountMonitor:
    """Bit-exact sequential reference model (one sample per :meth:`update`)."""

    def __init__(self, lags: int, window: int = STUDY_WINDOW,
                 cutoff: int | None = None) -> None:
        if lags < 1:
            raise ValueError("lags must be >= 1")
        self.lags = lags
        self.window = window
        self.cutoff = c_lag(lags, window) if cutoff is None else cutoff
        self.reset()

    def reset(self) -> None:
        self.hist = 0       # bit j-1 holds x[i-j]
        self.filled = 0
        self.index = 0
        self.counts = [0] * self.lags
        self.failed_lags = 0  # sticky bitmask, bit j-1 = lag j
        self.failed = False

    def update(self, bit: int) -> bool:
        """Feed one raw sample. Returns True on the sample that ends a failing window."""
        bit &= 1
        mask = (1 << self.lags) - 1
        fail = False
        if self.filled < self.lags:
            self.filled += 1
        else:
            h = self.hist
            for j in range(self.lags):
                if ((h >> j) & 1) == bit:
                    self.counts[j] += 1
            self.index += 1
            if self.index == self.window:
                for j in range(self.lags):
                    if self.counts[j] >= self.cutoff:
                        self.failed_lags |= 1 << j
                        fail = True
                self.counts = [0] * self.lags
                self.index = 0
        self.hist = ((self.hist << 1) | bit) & mask
        self.failed = self.failed or fail
        return fail


def pack(bits) -> int:
    """Pack a bit list into one int, ``x[i]`` at bit ``i`` (for :func:`scan_packed`)."""
    return int("".join("1" if b & 1 else "0" for b in reversed(bits)) or "0", 2)


def scan_packed(v: int, n: int, lags: int, window: int = STUDY_WINDOW,
                cutoff: int | None = None):
    """Fast batch equivalent of feeding an ``n``-sample packed stream to :class:`LagCountMonitor`.

    Returns ``[(end_index_1based, failed_lag_mask), ...]`` for every complete
    window that fails (empty if none). Equality with the sequential model is
    asserted by ``sim/tests/test_health_detection_coverage.py``.
    """
    if cutoff is None:
        cutoff = c_lag(lags, window)
    wmask = (1 << window) - 1
    out = []
    s = lags
    while s + window <= n:
        cur = (v >> s) & wmask
        fm = 0
        for j in range(1, lags + 1):
            diff = (cur ^ ((v >> (s - j)) & wmask)).bit_count()
            if window - diff >= cutoff:
                fm |= 1 << (j - 1)
        if fm:
            out.append((s + window, fm))
        s += window
    return out


def window_max_counts(v: int, n: int, lags: int, window: int = STUDY_WINDOW):
    """Per complete window, the largest lag match count (for false-alarm margin reporting)."""
    wmask = (1 << window) - 1
    out = []
    s = lags
    while s + window <= n:
        cur = (v >> s) & wmask
        out.append(max(window - (cur ^ ((v >> (s - j)) & wmask)).bit_count()
                       for j in range(1, lags + 1)))
        s += window
    return out


def scan(bits, lags: int, window: int = STUDY_WINDOW, cutoff: int | None = None):
    """:func:`scan_packed` over a bit list."""
    return scan_packed(pack(bits), len(bits), lags, window, cutoff)


def first_alarm_packed(v: int, n: int, lags: int, window: int = STUDY_WINDOW,
                       cutoff: int | None = None):
    """``(first_alarm_sample_1based or None, union_of_failed_lag_masks)``."""
    hits = scan_packed(v, n, lags, window, cutoff)
    if not hits:
        return None, 0
    mask = 0
    for _, m in hits:
        mask |= m
    return hits[0][0], mask


def first_alarm(bits, lags: int, window: int = STUDY_WINDOW, cutoff: int | None = None):
    return first_alarm_packed(pack(bits), len(bits), lags, window, cutoff)


def main() -> int:
    print(f"alpha per window = 2^-{ALPHA_LOG2}, H = {H_DESIGN}, "
          f"lag match rate at H = {float(match_probability(H_DESIGN)):.6f}")
    print("| lags L | window | C_L (exact) | C_L/window | C_L (binomial, under-covers) |")
    print("|---|---|---|---|---|")
    for w in (512, 1024, 2048, 4096):
        for lags in (8, 16, 32, 64, 128, 256):
            c = c_lag(lags, w)
            print(f"| {lags} | {w} | {c} | {c / w:.4f} | {c_lag_binomial(lags, w)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
