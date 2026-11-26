"""Shared bitstream statistics: the reduced SP 800-22-style battery, the
SP 800-90B non-IID min-entropy estimators and the stream-battery reporting
helpers.  Standard library only.

Pure arithmetic over a 0/1 `bits` list.  This module imports no campaign
CLI, record or evidence module, so a campaign that needs the math imports
it directly instead of executing `raw-bit-battery.py` or `raw-bit-entropy.py`
by path (issue #794; the seam `raw_bit_volume.py` opened for the stream
reader in #790).

Part 1 -- reduced SP 800-22 battery (`run_battery`)
    monobit, block frequency, runs, longest-run-in-block, cumulative sums
    (forward + backward), serial (2 p-values) and approximate entropy, each
    with a p-value and a significance level alpha = 0.01.  Given several
    equal-length segments, the standard pass-proportion criterion
    (p_hat +/- 3 sqrt(p_hat (1-p_hat)/s), p_hat = 1 - alpha) is applied per
    test.  Not implemented (deliberately reduced): rank, DFT, templates,
    Maurer, random excursions, and the p-value uniformity check.

Part 2 -- SP 800-90B non-IID estimators (`entropy_estimates`)
    MCV, collision, Markov, compression (Maurer-style) and t-tuple / LRS,
    binary-alphabet forms, each reported in bit/sample; the headline figure
    is the MINIMUM across estimators.  The Markov confidence interval is a
    conservative Hoeffding variant, and the t-tuple/LRS window length is
    capped at `TUPLE_CAP`; both are labelled approximations of the
    standard, not a validated implementation of it.

Minimum-length guards
---------------------
Every test and estimator has a minimum n (`BATTERY_MIN_N`, `ESTIMATOR_MIN_N`).
Below it the item reports status `INSUFFICIENT` with no p-value / estimate,
and the overall verdict is `INSUFFICIENT`, never PASS.  These are
statistical-sanity floors, NOT the 10^6-sample volume SP 800-90B asks of a
formal assessment.  The committed 24-sample-per-corner campaign record is far
below every floor; conclusions about the real source are gated on a
longer-bitstream campaign.

Caveats (kept in every record): Tier 2 labelled design estimate, not an
SP 800-90B validation; **simulation-derived entropy claims are provisional
until measured on silicon**; one noise trajectory (seed) per corner, so
samples are not independent trials.

`mcv_estimate` is the SP 800-90B section 6.3.1 Most-Common-Value point
estimate `raw-bit-entropy.py` reports per corner.  Its naive per-sample
standard error assumes independent samples, so it is an UNDER-estimate of
the true uncertainty wherever a corner's samples share one noise trajectory.
"""

from __future__ import annotations

import math
from collections import Counter

ALPHA = 0.01
#: SP 800-90B section 6.3.1's 99%-confidence one-sided normal-approximation
#: multiplier (the z-score whose upper tail is 1%).
Z_99 = 2.5758293035489004
MIN_SEGMENTS = 10  # pass-proportion criterion is meaningless below this
TUPLE_CAP = 64

BATTERY_MIN_N = {
    "monobit": 100,
    "block_frequency": 100,
    "runs": 100,
    "longest_run": 128,
    "cusum_forward": 100,
    "cusum_backward": 100,
    "serial_1": 128,
    "serial_2": 128,
    "approximate_entropy": 256,
}
ESTIMATOR_MIN_N = {
    "mcv": 1000,
    "collision": 1000,
    "markov": 1000,
    "compression": 12000,  # 6-bit blocks: 1000 dictionary + >=1000 test blocks
    "t_tuple": 1000,
    "lrs": 1000,
}
SOURCE_NOTE = "provisional until measured on silicon"


# ---------------------------------------------------------------- special fns

def igamc(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x)."""
    if x <= 0:
        return 1.0
    if x < a + 1.0:  # series for P, return 1 - P
        term = s = 1.0 / a
        ap = a
        for _ in range(10000):
            ap += 1.0
            term *= x / ap
            s += term
            if abs(term) < abs(s) * 1e-16:
                break
        return max(0.0, 1.0 - s * math.exp(-x + a * math.log(x) - math.lgamma(a)))
    tiny = 1e-300  # Lentz continued fraction
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return min(1.0, h * math.exp(-x + a * math.log(x) - math.lgamma(a)))


def _phi(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


# ------------------------------------------------------------ SP 800-22 tests

def t_monobit(bits):
    n = len(bits)
    s = abs(2 * sum(bits) - n) / math.sqrt(n)
    return math.erfc(s / math.sqrt(2.0))


def t_block_frequency(bits):
    n = len(bits)
    m = max(20, n // 50)  # M >= 20, M > 0.01 n, N < 100
    nb = n // m
    chi = 4.0 * m * sum((sum(bits[i * m:(i + 1) * m]) / m - 0.5) ** 2
                        for i in range(nb))
    return igamc(nb / 2.0, chi / 2.0)


def t_runs(bits):
    n = len(bits)
    pi = sum(bits) / n
    if abs(pi - 0.5) >= 2.0 / math.sqrt(n):
        return 0.0  # SP 800-22 frequency prerequisite failed
    v = 1 + sum(1 for i in range(n - 1) if bits[i] != bits[i + 1])
    return math.erfc(abs(v - 2.0 * n * pi * (1 - pi))
                     / (2.0 * math.sqrt(2.0 * n) * pi * (1 - pi)))


_LONGEST = {  # M: (K, lo, hi, probabilities)
    8: (3, 1, 4, [0.2148, 0.3672, 0.2305, 0.1875]),
    128: (5, 4, 9, [0.1174, 0.2430, 0.2493, 0.1752, 0.1027, 0.1124]),
    10000: (6, 10, 16, [0.0882, 0.2092, 0.2483, 0.1933, 0.1208, 0.0675, 0.0727]),
}


def t_longest_run(bits):
    n = len(bits)
    m = 10000 if n >= 750000 else 128 if n >= 6272 else 8
    k, lo, hi, probs = _LONGEST[m]
    nb = n // m
    counts = [0] * (k + 1)
    for b in range(nb):
        best = run = 0
        for x in bits[b * m:(b + 1) * m]:
            run = run + 1 if x else 0
            best = max(best, run)
        counts[min(max(best, lo), hi) - lo] += 1
    chi = sum((c - nb * p) ** 2 / (nb * p) for c, p in zip(counts, probs))
    return igamc(k / 2.0, chi / 2.0)


def _cusum(bits):
    n = len(bits)
    s = 0
    z = 0
    for b in bits:
        s += 2 * b - 1
        z = max(z, abs(s))
    if z == 0:
        return 1.0
    sq = math.sqrt(n)
    t1 = sum(_phi((4 * k + 1) * z / sq) - _phi((4 * k - 1) * z / sq)
             for k in range(int((-n / z + 1) // 4), int((n / z - 1) // 4) + 1))
    t2 = sum(_phi((4 * k + 3) * z / sq) - _phi((4 * k + 1) * z / sq)
             for k in range(int((-n / z - 3) // 4), int((n / z - 1) // 4) + 1))
    return max(0.0, min(1.0, 1.0 - t1 + t2))


def t_cusum_forward(bits):
    return _cusum(bits)


def t_cusum_backward(bits):
    return _cusum(bits[::-1])


def _psi2(bits, m):
    n = len(bits)
    if m == 0:
        return 0.0
    ext = bits + bits[:m - 1]
    c = Counter(tuple(ext[i:i + m]) for i in range(n))
    return sum(v * v for v in c.values()) * 2 ** m / n - n


def _serial_m(n):
    return max(3, min(5, int(math.log2(n)) - 3))


def _serial(bits):
    m = _serial_m(len(bits))
    p0, p1, p2 = _psi2(bits, m), _psi2(bits, m - 1), _psi2(bits, m - 2)
    d1, d2 = p0 - p1, p0 - 2 * p1 + p2
    return (igamc(2 ** (m - 2), d1 / 2.0), igamc(2 ** (m - 3), d2 / 2.0))


# The two serial rows are the columns of one `_serial` evaluation: it
# computes both p-values from the same three pattern histograms, so
# `run_battery` evaluates the pair once per eligible segment and feeds each
# column through the row verdict logic instead of calling a single-result
# wrapper per row (issue #765).
SERIAL_ROWS = ("serial_1", "serial_2")


def t_approximate_entropy(bits):
    n = len(bits)
    m = max(2, min(10, int(math.log2(n)) - 6))

    def phi(mm):
        ext = bits + bits[:mm - 1]
        c = Counter(tuple(ext[i:i + mm]) for i in range(n))
        return sum(v / n * math.log(v / n) for v in c.values())

    apen = phi(m) - phi(m + 1)
    chi = 2.0 * n * (math.log(2) - apen)
    return igamc(2 ** (m - 1), chi / 2.0)


BATTERY = {
    "monobit": t_monobit,
    "block_frequency": t_block_frequency,
    "runs": t_runs,
    "longest_run": t_longest_run,
    "cusum_forward": t_cusum_forward,
    "cusum_backward": t_cusum_backward,
    "serial_1": _serial,
    "serial_2": _serial,
    "approximate_entropy": t_approximate_entropy,
}


def proportion_bounds(s: int, alpha: float = ALPHA) -> tuple[float, float]:
    ph = 1.0 - alpha
    d = 3.0 * math.sqrt(ph * (1.0 - ph) / s)
    return ph - d, ph + d


def run_battery(bits: list[int], segment_len: int | None = None,
                alpha: float = ALPHA) -> dict:
    """Run the battery.

    Without `segment_len`: one sequence, each test PASS iff p >= alpha.
    With `segment_len`: the stream is cut into whole segments; each test is
    PASS iff the fraction of segments with p >= alpha meets the SP 800-22
    pass-proportion criterion.  Fewer than MIN_SEGMENTS segments, or any
    test below its minimum n, gives INSUFFICIENT.  Overall verdict is never
    PASS while anything is INSUFFICIENT.
    """
    n = len(bits)
    if segment_len:
        segs = [bits[i:i + segment_len]
                for i in range(0, n - segment_len + 1, segment_len)]
    else:
        segs = [bits]
    s = len(segs)
    seg_n = len(segs[0]) if segs else 0
    tests = {}
    # Both serial rows are columns of one `_serial` pair evaluation: compute
    # the pair once per segment (only after the eligibility checks) and
    # split it into the rows (issue #765).
    serial_pairs = None
    for name, fn in BATTERY.items():
        min_n = BATTERY_MIN_N[name]
        entry: dict = {"min_n": min_n}
        if seg_n < min_n or (segment_len and s < MIN_SEGMENTS):
            entry["status"] = "INSUFFICIENT"
            tests[name] = entry
            continue
        if name in SERIAL_ROWS:
            col = SERIAL_ROWS.index(name)
            if serial_pairs is None:
                serial_pairs = [_serial(x) for x in segs]
            ps = [p[col] for p in serial_pairs]
        else:
            ps = [fn(x) for x in segs]
        entry["p_values"] = ps
        if segment_len:
            frac = sum(p >= alpha for p in ps) / s
            lo, hi = proportion_bounds(s, alpha)
            entry.update(proportion=frac, proportion_lo=lo, proportion_hi=hi)
            entry["status"] = "PASS" if frac >= lo else "FAIL"
        else:
            entry["status"] = "PASS" if ps[0] >= alpha else "FAIL"
        tests[name] = entry
    sts = [t["status"] for t in tests.values()]
    verdict = ("INSUFFICIENT" if "INSUFFICIENT" in sts
               else "FAIL" if "FAIL" in sts else "PASS")
    return {"n": n, "segments": s, "segment_len": seg_n, "alpha": alpha,
            "mode": "pass-proportion" if segment_len else "single-sequence",
            "tests": tests, "verdict": verdict, "caveat": SOURCE_NOTE}


# ----------------------------------------------------- SP 800-90B estimators

def _h_from_p(p: float, per: int = 1) -> float:
    return 0.0 if p >= 1.0 else min(1.0, -math.log2(p) / per)


def mcv_estimate(bits: list[int]) -> dict:
    """SP 800-90B section 6.3.1 Most-Common-Value estimate over `bits`."""
    n = len(bits)
    if n == 0:
        raise ValueError("mcv_estimate: empty bit sequence")
    ones = sum(bits)
    zeros = n - ones
    mode_count = max(ones, zeros)
    p_hat = mode_count / n
    # Naive per-sample SE -- an UNDER-estimate when the samples share one
    # noise trajectory; see module docstring.
    se_naive = math.sqrt(p_hat * (1.0 - p_hat) / n) if n > 0 else float("nan")
    if n > 1:
        p_u = min(1.0, p_hat + Z_99 * math.sqrt(p_hat * (1.0 - p_hat) / (n - 1)))
    else:
        p_u = 1.0
    h_hat = 0.0 if p_u >= 1.0 else -math.log2(p_u)
    return {
        "n": n,
        "ones": ones,
        "zeros": zeros,
        "p_hat": p_hat,
        "p_u_99": p_u,
        "h_hat_bits": h_hat,
        "se_naive": se_naive,
    }


def est_mcv(bits):
    return mcv_estimate(bits)["h_hat_bits"]


def est_collision(bits):
    n = len(bits)
    ts = []
    i = 0
    while i + 2 < n:
        if bits[i] == bits[i + 1]:
            ts.append(2)
            i += 2
        else:
            ts.append(3)
            i += 3
    v = len(ts)
    mean = sum(ts) / v
    sd = math.sqrt(sum((t - mean) ** 2 for t in ts) / (v - 1)) if v > 1 else 0.0
    lower = mean - Z_99 * sd / math.sqrt(v)
    # E[t] = 2 + 2pq  =>  pq = (E - 2) / 2
    pq = min(0.25, max(0.0, (lower - 2.0) / 2.0))
    if lower <= 2.0:
        return 0.0
    return _h_from_p(0.5 + math.sqrt(0.25 - pq))


def est_markov(bits, k: int = 128):
    n = len(bits)
    ones = sum(bits)
    eps = math.sqrt(math.log(2.0 / (1.0 - 0.99 ** 4)) / (2.0 * n))
    p = [min(1.0, (n - ones) / n + eps), min(1.0, ones / n + eps)]
    cnt = [[0, 0], [0, 0]]
    for a, b in zip(bits, bits[1:]):
        cnt[a][b] += 1
    t = [[0.0, 0.0], [0.0, 0.0]]
    for i in (0, 1):
        tot = cnt[i][0] + cnt[i][1]
        for j in (0, 1):
            t[i][j] = min(1.0, (cnt[i][j] / tot + eps) if tot else 1.0)
    best = [math.log2(p[0]), math.log2(p[1])]
    for _ in range(k - 1):
        best = [max(best[i] + math.log2(t[i][j]) for i in (0, 1)) for j in (0, 1)]
    return min(1.0, -max(best) / k)


def est_compression(bits, b: int = 6, d: int = 1000):
    nb = len(bits) // b
    blocks = [int("".join(map(str, bits[i * b:(i + 1) * b])), 2)
              for i in range(nb)]
    last: dict[int, int] = {}
    for i in range(d):
        last[blocks[i]] = i + 1
    logs = []
    for i in range(d, nb):
        pos = i + 1
        logs.append(math.log2(pos - last.get(blocks[i], 0)))
        last[blocks[i]] = pos
    v = len(logs)
    mean = sum(logs) / v
    sd = math.sqrt(sum((x - mean) ** 2 for x in logs) / (v - 1))
    c = 0.7 - 0.8 / b + (4 + 32 / b) * v ** (-3 / b) / 15
    lower = mean - Z_99 * c * sd / math.sqrt(v)
    big = 2 ** b
    l2 = [0.0] + [math.log2(u) for u in range(1, nb + 2)]

    def g(p):
        q = (1.0 - p) / (big - 1)
        # accumulate sum_{u<t} log2(u) (p^2 (1-p)^(u-1) + (big-1) q^2 (1-q)^(u-1))
        acc = 0.0
        tot = 0.0
        pw_p, pw_q = 1.0, 1.0  # (1-p)^(u-1), (1-q)^(u-1)
        for t in range(1, nb + 1):
            # acc currently covers u < t
            if t > d:
                tot += acc + l2[t] * (p * pw_p + (big - 1) * q * pw_q)
            acc += l2[t] * (p * p * pw_p + (big - 1) * q * q * pw_q)
            pw_p *= (1.0 - p)
            pw_q *= (1.0 - q)
        return tot / v

    lo, hi = 1.0 / big, 1.0
    if lower >= g(lo):
        return 1.0
    if lower <= g(hi):
        return 0.0
    for _ in range(40):  # g decreasing in p
        mid = 0.5 * (lo + hi)
        if g(mid) > lower:
            lo = mid
        else:
            hi = mid
    return _h_from_p(0.5 * (lo + hi), b)


def _tuple_counts(bits, cap: int = TUPLE_CAP):
    """Yield (t, Counter of t-windows) until no window repeats (or cap)."""
    codes = list(bits)
    for t in range(1, cap + 1):
        if t > 1:
            codes = [(codes[i] << 1) | bits[i + t - 1]
                     for i in range(len(bits) - t + 1)]
        c = Counter(codes)
        yield t, c
        if max(c.values()) < 2:
            return


def _bound(phat, n):
    pu = min(1.0, phat + Z_99 * math.sqrt(phat * (1 - phat) / (n - 1)))
    return _h_from_p(pu)


def est_t_tuple_lrs(bits):
    """Return (H_t_tuple, H_lrs)."""
    n = len(bits)
    qs = {}
    pmax_t = []
    pmax_l = {}
    for t, c in _tuple_counts(bits):
        q = max(c.values())
        qs[t] = q
        if q >= 35:
            pmax_t.append((q / (n - t + 1)) ** (1.0 / t))
        if q >= 2:
            pw = sum(v * (v - 1) // 2 for v in c.values()) / (
                (n - t + 1) * (n - t) / 2.0)
            pmax_l[t] = pw ** (1.0 / t)
    ph_t = max(pmax_t) if pmax_t else 0.5
    u = min((t for t, q in qs.items() if q < 35), default=max(qs))  # cap hit: use longest window
    lr = [p for t, p in pmax_l.items() if t >= u]
    ph_l = max(lr) if lr else 0.5
    return _bound(max(ph_t, 0.5), n), _bound(max(ph_l, 0.5), n)


def entropy_estimates(bits: list[int]) -> dict:
    n = len(bits)
    res: dict = {}
    tt = None
    for name in ESTIMATOR_MIN_N:
        e: dict = {"min_n": ESTIMATOR_MIN_N[name]}
        if n < ESTIMATOR_MIN_N[name]:
            e["status"] = "INSUFFICIENT"
        else:
            if name == "mcv":
                h = est_mcv(bits)
            elif name == "collision":
                h = est_collision(bits)
            elif name == "markov":
                h = est_markov(bits)
            elif name == "compression":
                h = est_compression(bits)
            else:
                tt = tt or est_t_tuple_lrs(bits)
                h = tt[0] if name == "t_tuple" else tt[1]
            e.update(status="OK", h_bits=h)
        res[name] = e
    ok = {k: v["h_bits"] for k, v in res.items() if v["status"] == "OK"}
    insufficient = [k for k, v in res.items() if v["status"] != "OK"]
    binding = min(ok, key=ok.get) if ok else None
    return {"n": n, "estimators": res,
            "h_min_bits": ok[binding] if binding else None,
            "binding_estimator": binding,
            "verdict": "INSUFFICIENT" if insufficient else "ESTIMATE",
            "insufficient": insufficient, "caveat": SOURCE_NOTE}


# ------------------------------------------------- shared stream reporting

def analyse_stream(bits: list[int], segment_len: int) -> dict:
    """Full-stream battery + estimators and the segmented battery."""
    est = entropy_estimates(bits)
    h = est["h_min_bits"]
    ties = [k for k, v in est["estimators"].items()
            if v["status"] == "OK" and v["h_bits"] == h]
    est["binding_ties"] = ties
    return {"n": len(bits),
            "single_sequence": run_battery(bits),
            "segmented": run_battery(bits, segment_len=segment_len),
            "estimators": est}


def _failed(block: dict) -> str:
    f = [k for k, v in block["tests"].items() if v["status"] == "FAIL"]
    return ", ".join(f) if f else "-"


def format_binding(est: dict) -> str:
    """`binding_estimator` with its binding-tie annotation (shared renderer)."""
    bind = est["binding_estimator"] or "-"
    if len(est["binding_ties"]) > 1:
        bind += " (tie: " + ", ".join(est["binding_ties"]) + ")"
    return bind


def render_detail_tables(grp: list[dict], *, est_heading: str,
                         seq_heading: str, seg_heading: str,
                         key: str | None = None) -> list[str]:
    """The three per-group detail tables shared by the volume and
    conditioned-output renderers.

    `key=None` reads the reduction dict straight off each row (volume
    records); `key="conditioned"` reads it from `r["conditioned"]`
    (conditioned-output records). Headings differ per caller; columns, cell
    formatting and INSUFFICIENT fallbacks are pinned here.
    """
    def red(r: dict) -> dict:
        return r if key is None else r[key]

    out = ["", est_heading, "",
           "| corner | T (C) | Vdd (V) | " + " | ".join(ESTIMATOR_MIN_N) + " |",
           "|---|---|---|" + "---|" * len(ESTIMATOR_MIN_N)]
    for r in grp:
        ev = red(r)["estimators"]["estimators"]
        cells = [f"{ev[k]['h_bits']:.4f}" if ev[k]["status"] == "OK"
                 else "INSUFFICIENT" for k in ESTIMATOR_MIN_N]
        out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                   + " | ".join(cells) + " |")
    out += ["", seq_heading, "",
            "| corner | T (C) | Vdd (V) | " + " | ".join(BATTERY) + " |",
            "|---|---|---|" + "---|" * len(BATTERY)]
    for r in grp:
        t = red(r)["single_sequence"]["tests"]
        cells = [("%.4g%s" % (t[k]["p_values"][0],
                              "" if t[k]["status"] == "PASS" else " F"))
                 if "p_values" in t[k] else "INSUFFICIENT" for k in BATTERY]
        out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                   + " | ".join(cells) + " |")
    out += ["", seg_heading, "",
            "| corner | T (C) | Vdd (V) | " + " | ".join(BATTERY) + " |",
            "|---|---|---|" + "---|" * len(BATTERY)]
    for r in grp:
        t = red(r)["segmented"]["tests"]
        cells = [("%.4f%s" % (t[k]["proportion"],
                              "" if t[k]["status"] == "PASS" else " F"))
                 if "proportion" in t[k] else "INSUFFICIENT" for k in BATTERY]
        out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                   + " | ".join(cells) + " |")
    return out
