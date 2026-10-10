#!/usr/bin/env python3
"""Reduced SP 800-22-style battery + SP 800-90B non-IID estimators over the
digitized `raw_bit` sequence, per corner.  Standard library only.

**This runs no simulator.**  Like `raw-bit-entropy.py` (the MCV-only
reduction this module extends) it is pure arithmetic over an already-
committed `sim/raw-bit-min-entropy/records/*.json` campaign record, and
`--emit-record` mints an append-only *derived* record citing that source
record via `sim/bin/evidence_record.py`.

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

Usage
-----
    python3 sim/raw-bit-min-entropy/analysis/raw-bit-battery.py
    python3 sim/raw-bit-min-entropy/analysis/raw-bit-battery.py --emit-record

Volume-record input (issue #195)
--------------------------------
`--volume-record SOURCE.json` selects an explicit `raw-bit-volume-campaign`
record instead of the legacy transistor campaign records.  Every manifest
stream is read from the source's `runs/<record_id>/` directory, decoded MSB
first, and checked against its declared `n` and `sha256_hex` (SHA-256 of the
hex text without its trailing newline) before analysis; any missing,
malformed, truncated or mismatched stream aborts the run.  Each stream gets a
full-stream single-sequence battery, a segmented pass-proportion battery
(`n // SEGMENT_LEN` non-overlapping segments of `SEGMENT_LEN` bits, so the
count follows the stream length), and the six 90B estimators on the full stream.  Segments and PVT
streams are NOT independent silicon trials.

    python3 .../raw-bit-battery.py --volume-record sim/raw-bit-volume-campaign/records/<id>.json
    python3 .../raw-bit-battery.py --volume-record <src.json> --emit-record
    python3 .../raw-bit-battery.py --check sim/raw-bit-min-entropy/records/<rid>.json

`--check` recomputes the analysis from the input streams and compares it, and
the rendered tables, with the committed record; it exits nonzero on any
difference and never mints or writes anything.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDS_DIR = REPO_ROOT / "sim" / "raw-bit-min-entropy" / "records"

sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_record, new_record_id  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "raw_bit_entropy", Path(__file__).with_name("raw-bit-entropy.py"))
assert _spec is not None and _spec.loader is not None
raw_bit_entropy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(raw_bit_entropy)

ALPHA = 0.01
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
SEGMENT_LEN = 8192  # volume adapter: non-overlapping segments of 8192 bits;
# the segment count is derived per stream as n // SEGMENT_LEN (16 at 2^17,
# 128 at 2^20), so any stream length works (a ragged tail is not segmented).
H_DESIGN = 0.5  # DR-0004 design min-entropy the ratified C_RCT = 81 / C_APT = 824 are evaluated at
VOLUME_SLUG = "raw-bit-volume-campaign"
VOLUME_CAVEATS_HEADING = "## Caveats that bound how this record may be cited"


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


def t_serial_1(bits):
    return _serial(bits)[0]


def t_serial_2(bits):
    return _serial(bits)[1]


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
    "serial_1": t_serial_1,
    "serial_2": t_serial_2,
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
    for name, fn in BATTERY.items():
        min_n = BATTERY_MIN_N[name]
        entry: dict = {"min_n": min_n}
        if seg_n < min_n or (segment_len and s < MIN_SEGMENTS):
            entry["status"] = "INSUFFICIENT"
            tests[name] = entry
            continue
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


def est_mcv(bits):
    return raw_bit_entropy.mcv_estimate(bits)["h_hat_bits"]


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


# ------------------------------------------------------------------ reporting

def analyse_record(rec: dict) -> tuple[str, dict]:
    lines = [f"Source campaign record: `{rec['record_id']}` (`{rec['testbench']}`)",
             "",
             "| Corner | n | battery | 90B estimators | min H (bit/sample) | binding |",
             "|---|---|---|---|---|---|"]
    out = []
    for corner in rec["corners"]:
        bits, n_total, n_excl = raw_bit_entropy.extract_sequence(
            corner.get("measurements", {}), rec["pvt"]["vdd_v"])
        if not bits:
            lines.append(f"| `{corner['corner']}` | 0 | SKIP | SKIP | - | - |")
            continue
        bat = run_battery(bits)
        est = entropy_estimates(bits)
        h = est["h_min_bits"]
        lines.append(
            f"| `{corner['corner']}` | {len(bits)} | {bat['verdict']} | "
            f"{est['verdict']} | {'-' if h is None else f'{h:.4f}'} | "
            f"{est['binding_estimator'] or '-'} |")
        out.append({"corner": corner["corner"], "temp_c": rec["pvt"]["temp_c"],
                    "vdd_v": rec["pvt"]["vdd_v"], "n": len(bits),
                    "battery": bat, "estimators": est})
    lines += [
        "",
        "`INSUFFICIENT` means n is below at least one test's / estimator's "
        "minimum length (battery floors 100-256 bits, estimator floors "
        "1000-12000 bits); no pass verdict and no entropy claim is made. "
        "The committed campaign records carry tens of samples per corner, so "
        "nothing here supports any conclusion about the real source until a "
        "longer-bitstream campaign exists.",
        "",
        "## Caveats that bound how this result may be cited",
        "",
        "- **Design estimate, not an SP 800-90B validation or an SP 800-22 "
        "certification.** Reduced battery, binary-alphabet estimators, "
        "Tier 2 labelled estimate.",
        "- **Simulation-derived entropy claims are provisional until "
        "measured on silicon** (root `CLAUDE.md`).",
        "- **One noise trajectory (seed) per corner**; samples are not "
        "independent trials.",
        "- **Not DR-0003's operating point** (campaign runs Ts = 100 ns).",
    ]
    return "\n".join(lines), {"per_corner": out}

# --------------------------------------------------- volume-record adapter

class VolumeInputError(ValueError):
    """A volume-record stream is missing, malformed, truncated or mismatched."""


_HEX_RE = re.compile(r"[0-9a-f]*")


def decode_packed_hex(text: str) -> list[int]:
    """Decode packed lowercase hex, MSB of each byte first (as `pack_hex`)."""
    if len(text) % 2 or not _HEX_RE.fullmatch(text):
        raise VolumeInputError("not an even-length lowercase hex string")
    return [int(c) for byte in bytes.fromhex(text) for c in f"{byte:08b}"]


def load_stream(path: Path, n: int, sha256_hex: str) -> list[int]:
    """Read one packed-hex stream file and verify declared n and hash.

    The source hashes the hex characters without the writer's single
    trailing newline (not the decoded bytes).
    """
    try:
        raw = path.read_text()
    except OSError as exc:
        raise VolumeInputError(f"cannot read {path}: {exc}") from exc
    text = raw[:-1] if raw.endswith("\n") else raw
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest != sha256_hex:
        raise VolumeInputError(
            f"{path.name}: sha256 mismatch (declared {sha256_hex}, got {digest})")
    try:
        bits = decode_packed_hex(text)
    except VolumeInputError as exc:
        raise VolumeInputError(f"{path.name}: {exc}") from exc
    if len(bits) != n:
        raise VolumeInputError(
            f"{path.name}: length mismatch (declared n={n}, decoded {len(bits)})")
    return bits


def load_volume_source(source_json: Path) -> tuple[dict, list[tuple[dict, list[int]]], str]:
    """Return (source record, [(manifest row, bits)], sha256 of source JSON)."""
    source_json = Path(source_json)
    try:
        raw = source_json.read_bytes()
        rec = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise VolumeInputError(f"cannot read source record {source_json}: {exc}") from exc
    for key in ("record_id", "slug", "level", "streams"):
        if key not in rec:
            raise VolumeInputError(f"source record lacks `{key}`")
    if rec["slug"] != VOLUME_SLUG:
        raise VolumeInputError(f"source slug {rec['slug']!r} is not {VOLUME_SLUG!r}")
    if source_json.stem != rec["record_id"]:
        raise VolumeInputError("source file name does not match its record_id")
    if not rec["streams"]:
        raise VolumeInputError("source record has an empty stream manifest")
    runs_dir = source_json.parent.parent / "runs" / rec["record_id"]
    streams = []
    for row in rec["streams"]:
        for key in ("corner", "temp_c", "vdd_v", "ts_s", "ts_name", "seed",
                    "file", "n", "sha256_hex"):
            if key not in row:
                raise VolumeInputError(f"manifest row lacks `{key}`: {row.get('file')}")
        if Path(row["file"]).name != row["file"]:
            raise VolumeInputError(f"manifest file {row['file']!r} is not a bare name")
        streams.append((row, load_stream(runs_dir / row["file"], row["n"],
                                         row["sha256_hex"])))
    return rec, streams, hashlib.sha256(raw).hexdigest()


def source_caveats(source_json: Path) -> list[str]:
    """Verbatim bullet lines of the source .md caveats section."""
    md = Path(source_json).with_suffix(".md")
    try:
        lines = md.read_text().splitlines()
    except OSError as exc:
        raise VolumeInputError(f"cannot read source markdown {md}: {exc}") from exc
    if VOLUME_CAVEATS_HEADING not in lines:
        raise VolumeInputError(f"{md.name} lacks the caveats section")
    out = []
    for ln in lines[lines.index(VOLUME_CAVEATS_HEADING) + 1:]:
        if ln.startswith("---") or ln.startswith("## "):
            break
        if ln.strip():
            out.append(ln)
    if not out:
        raise VolumeInputError(f"{md.name} caveats section is empty")
    return out


def analyse_stream(bits: list[int]) -> dict:
    """Full-stream battery + estimators and the segmented battery."""
    est = entropy_estimates(bits)
    h = est["h_min_bits"]
    ties = [k for k, v in est["estimators"].items()
            if v["status"] == "OK" and v["h_bits"] == h]
    est["binding_ties"] = ties
    return {"n": len(bits),
            "single_sequence": run_battery(bits),
            "segmented": run_battery(bits, segment_len=SEGMENT_LEN),
            "estimators": est}


def min_h_shift(rows: list[dict], compare_rels: list[str]) -> dict:
    """Per-point min-H change versus earlier derived volume records.

    Matches on (corner, T, Vdd, Ts name).  The cutoffs C_RCT/C_APT (DR-0004)
    are evaluated at H_DESIGN; they stay conservative at a point iff the
    measured min-H there is >= H_DESIGN (the cutoff for a larger true H would
    only be smaller).  Nothing is relaxed here; this only reports.
    """
    old = {}
    for rel in compare_rels:
        prev = json.loads((REPO_ROOT / rel).read_text())
        for r in prev["analysis_payload"]["per_stream"]:
            old[(r["corner"], r["temp_c"], r["vdd_v"], r["ts_name"])] = (
                prev["record_id"], r)
    out = []
    for r in rows:
        key = (r["corner"], r["temp_c"], r["vdd_v"], r["ts_name"])
        e = r["estimators"]
        row = {"corner": r["corner"], "temp_c": r["temp_c"], "vdd_v": r["vdd_v"],
               "ts_name": r["ts_name"], "n_new": r["n"],
               "h_new": e["h_min_bits"], "binding_new": e["binding_estimator"],
               "h_design_ok": (e["h_min_bits"] is not None
                               and e["h_min_bits"] >= H_DESIGN)}
        if key in old:
            rid, o = old[key]
            oe = o["estimators"]
            row.update(old_record=rid, n_old=o["n"], h_old=oe["h_min_bits"],
                       binding_old=oe["binding_estimator"],
                       delta=(e["h_min_bits"] - oe["h_min_bits"]
                              if e["h_min_bits"] is not None
                              and oe["h_min_bits"] is not None else None))
        out.append(row)
    return {"compare_records": list(compare_rels), "h_design": H_DESIGN,
            "rows": out}


def volume_payload(source_json: Path, compare_rels: list[str] | None = None) -> dict:
    """Deterministic, mint-time-field-free analysis payload."""
    rec, streams, src_sha = load_volume_source(source_json)
    rows = []
    # Segment count is derived from the stream length (smallest stream if the
    # record mixes lengths; per-stream counts are in each row's `segmented`).
    seg_count = min(len(bits) for _, bits in streams) // SEGMENT_LEN
    for row, bits in streams:
        a = analyse_stream(bits)
        rows.append({"corner": row["corner"], "temp_c": row["temp_c"],
                     "vdd_v": row["vdd_v"], "ts_s": row["ts_s"],
                     "ts_name": row["ts_name"], "seed": row["seed"],
                     "source_file": row["file"],
                     "source_sha256_hex": row["sha256_hex"], **a})
    extra = ({"min_h_shift": min_h_shift(rows, compare_rels)}
             if compare_rels else {})
    return {**extra, "source_record": rec["record_id"],
            "source_level": rec["level"],
            "source_json_sha256": src_sha,
            "segment_policy": {"count": seg_count, "len": SEGMENT_LEN,
                               "non_overlapping": True,
                               "covers_bits": seg_count * SEGMENT_LEN},
            "alpha": ALPHA,
            "per_stream": rows}


def _failed(block: dict) -> str:
    f = [k for k, v in block["tests"].items() if v["status"] == "FAIL"]
    return ", ".join(f) if f else "-"


def render_shift(sh: dict) -> list[str]:
    rows = sh["rows"]
    out = ["## Shift versus the 2^17 records (same generator, calibration and "
           "seed labels; first 2^17 bits of each stream are identical)", "",
           "Compared records: " + ", ".join(f"`{c}`" for c in sh["compare_records"])
           + ". min H = minimum over the six 90B estimators on the full "
           "stream; delta = new - old (positive = the larger sample tightened "
           "the bound upward).", ""]
    for ts_name in sorted({r["ts_name"] for r in rows}, reverse=True):
        grp = [r for r in rows if r["ts_name"] == ts_name]
        out += [f"### {ts_name}", "",
                "| corner | T (C) | Vdd (V) | n old | n new | min H old | "
                "min H new | delta | binding old | binding new | "
                f"min H new >= {sh['h_design']:g} |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in grp:
            def f(x):
                return "-" if x is None else f"{x:.4f}"
            d = r.get("delta")
            out.append(
                f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                f"{r.get('n_old', '-')} | {r['n_new']} | {f(r.get('h_old'))} | "
                f"{f(r['h_new'])} | {'-' if d is None else f'{d:+.4f}'} | "
                f"{r.get('binding_old') or '-'} | {r['binding_new'] or '-'} | "
                f"{'yes' if r['h_design_ok'] else 'NO'} |")
        ds = [r["delta"] for r in grp if r.get("delta") is not None]
        hn = [r["h_new"] for r in grp if r["h_new"] is not None]
        if ds:
            out += ["", f"{ts_name}: delta min {min(ds):+.4f}, mean "
                    f"{sum(ds) / len(ds):+.4f}, max {max(ds):+.4f}; new min H "
                    f"range [{min(hn):.4f}, {max(hn):.4f}]."]
        out.append("")
    ok20 = [r for r in rows if r["ts_name"] == "Ts20us"]
    n_ok = sum(r["h_design_ok"] for r in ok20)
    out += ["### DR-0004 cutoffs (C_RCT = 81, C_APT = 824, evaluated at "
            f"H = {sh['h_design']:g})", "",
            f"At the DR-0003 design point (Ts = 20 us), {n_ok} of {len(ok20)} "
            f"PVT x corner points have min H >= {sh['h_design']:g}"
            + (": the provisional cutoffs still hold at every point (a "
               "measured H at or above the design H makes them conservative)."
               if n_ok == len(ok20) else
               "; the points marked NO are below the design H and the "
               "cutoffs are NOT conservative there (reported, nothing "
               "relaxed or changed).")
            + " Ts = 100 ns is cross-check only and is not the design point. "
            "The cutoffs are not modified by this record.", ""]
    return out


def render_volume(payload: dict, caveats: list[str]) -> str:
    """Stable markdown body, streams grouped by Ts (design point first)."""
    rows = payload["per_stream"]
    ts_groups = sorted({(r["ts_s"], r["ts_name"]) for r in rows}, reverse=True)
    pol = payload["segment_policy"]
    out = [f"Source record: `{payload['source_record']}` "
           f"(level `{payload['source_level']}`; source JSON sha256 "
           f"`{payload['source_json_sha256']}`).", "",
           f"Segment policy: {pol['count']} non-overlapping segments of "
           f"{pol['len']} bits ({pol['covers_bits']} bits). Segments and PVT "
           "streams are not independent silicon trials. Single-sequence "
           "verdict = full stream, each test PASS iff p >= alpha "
           f"({payload['alpha']}); segmented verdict = SP 800-22 "
           "pass-proportion over the segments. A FAIL in either is reported "
           "as found; no row is excluded.", ""]
    for ts_s, ts_name in ts_groups:
        grp = [r for r in rows if r["ts_name"] == ts_name]
        tag = ("DR-0003 design point" if ts_name == "Ts20us"
               else "cross-check only")
        out += [f"## {ts_name} (Ts = {ts_s:g} s) -- {tag}", "",
                "### Verdicts and min-over-estimators H", "",
                "| corner | T (C) | Vdd (V) | seed | n | single-seq | "
                "single-seq FAIL | segmented | segmented FAIL | min H (bit/sample) | "
                "binding | source file | source sha256 |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in grp:
            e = r["estimators"]
            h = e["h_min_bits"]
            bind = e["binding_estimator"] or "-"
            if len(e["binding_ties"]) > 1:
                bind += " (tie: " + ", ".join(e["binding_ties"]) + ")"
            out.append(
                f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                f"{r['seed']} | {r['n']} | {r['single_sequence']['verdict']} | "
                f"{_failed(r['single_sequence'])} | {r['segmented']['verdict']} | "
                f"{_failed(r['segmented'])} | "
                f"{'-' if h is None else f'{h:.4f}'} | {bind} | "
                f"`{r['source_file']}` | `{r['source_sha256_hex']}` |")
        out += ["", "### 90B estimators (bit/sample, full stream)", "",
                "| corner | T (C) | Vdd (V) | " + " | ".join(ESTIMATOR_MIN_N) + " |",
                "|---|---|---|" + "---|" * len(ESTIMATOR_MIN_N)]
        for r in grp:
            ev = r["estimators"]["estimators"]
            cells = [f"{ev[k]['h_bits']:.4f}" if ev[k]["status"] == "OK"
                     else "INSUFFICIENT" for k in ESTIMATOR_MIN_N]
            out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                       + " | ".join(cells) + " |")
        out += ["", "### Single-sequence p-values (full stream)", "",
                "| corner | T (C) | Vdd (V) | " + " | ".join(BATTERY) + " |",
                "|---|---|---|" + "---|" * len(BATTERY)]
        for r in grp:
            t = r["single_sequence"]["tests"]
            cells = [("%.4g%s" % (t[k]["p_values"][0],
                                  "" if t[k]["status"] == "PASS" else " F"))
                     if "p_values" in t[k] else "INSUFFICIENT" for k in BATTERY]
            out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                       + " | ".join(cells) + " |")
        out += ["", "### Segmented pass proportions "
                f"(passing segments / {pol['count']}; F = below criterion)", "",
                "| corner | T (C) | Vdd (V) | " + " | ".join(BATTERY) + " |",
                "|---|---|---|" + "---|" * len(BATTERY)]
        for r in grp:
            t = r["segmented"]["tests"]
            cells = [("%.4f%s" % (t[k]["proportion"],
                                  "" if t[k]["status"] == "PASS" else " F"))
                     if "proportion" in t[k] else "INSUFFICIENT" for k in BATTERY]
            out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                       + " | ".join(cells) + " |")
        out.append("")
    if "min_h_shift" in payload:
        out += render_shift(payload["min_h_shift"])
    out += ["`INSUFFICIENT` would mean n or the segment count/length is below a "
            "test's or estimator's floor (battery floors 100-256 bits, "
            "estimator floors 1000-12000 bits, segmented criterion >= "
            f"{MIN_SEGMENTS} segments). Ts groups are reported separately and "
            "are not averaged. The Ts = 100 ns streams are a cross-check, and "
            "their serial structure (source H_ctx 0.4-0.75) is expected to "
            "fail serial tests; whatever the battery found is shown above, "
            "not excluded.", "",
            "## Caveats that bound how this result may be cited", "",
            "Carried verbatim from the source record:", ""]
    out += caveats
    out += ["",
            "Added by this derived record:", "",
            "- **Behavioral level.** Derived from behavioral-model streams; "
            "not transistor-level and not silicon. The Ts = 20 us streams are "
            "the model's DR-0003 design point; Ts = 100 ns is cross-check only.",
            "- **Reduced, approximate battery and estimators.** Reduced "
            "SP 800-22-style battery (no rank, DFT, templates, Maurer, random "
            "excursions, or p-value uniformity check); the 90B Markov "
            "interval is a conservative Hoeffding variant and the t-tuple/LRS "
            "window is capped at "
            f"{TUPLE_CAP}. This is no formal NIST assessment and no silicon "
            "entropy certification.",
            "- **Simulation-derived entropy claims are provisional until "
            "measured on silicon** (root `CLAUDE.md`). No spec value or "
            "decision record is changed by this record.",
            ""]
    return "\n".join(out)


def volume_header(rid: str, payload: dict, source_json: Path) -> list[str]:
    rel = Path(source_json).resolve().relative_to(REPO_ROOT).as_posix()
    return [
        f"# {rid} -- raw-bit-min-entropy (battery + 90B estimators, volume streams)",
        "",
        "**Claim**: reduced SP 800-22-style battery (single-sequence and "
        "segmented) and SP 800-90B non-IID estimators (min across estimators) "
        f"over the {len(payload['per_stream'])} behavioral raw-bit streams of "
        f"`{payload['source_record']}`, reported per stream and grouped by Ts.",
        "",
        "**Level**: behavioral (derived -- arithmetic over the cited "
        "behavioral streams)",
        "**Seed**: N/A (deterministic reduction; per-stream source seeds are "
        "in the tables)",
        "**Analysis**: `sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`",
        "",
        "## Source record and replay",
        "",
        f"- `{payload['source_record']}` (`{rel}`)",
        "- Input: `python3 sim/raw-bit-min-entropy/analysis/raw-bit-battery.py "
        f"--volume-record {rel}`",
        "- Replay (no minting, nonzero exit on any change in results or input "
        "hashes): `python3 sim/raw-bit-min-entropy/analysis/raw-bit-battery.py "
        f"--check sim/raw-bit-min-entropy/records/{rid}.json`",
        "",
        "---",
        "",
    ]


def check_volume_record(record_json: Path) -> int:
    """Recompute and compare against a committed record; never writes."""
    record_json = Path(record_json)
    try:
        committed = json.loads(record_json.read_text())
        md_text = record_json.with_suffix(".md").read_text()
        src = REPO_ROOT / committed["source_json"]
        want = committed["analysis_payload"]
        payload = volume_payload(src, committed.get("compare_records") or None)
        caveats = source_caveats(src)
    except (OSError, ValueError, KeyError) as exc:
        print(f"CHECK FAILED: {exc}", file=sys.stderr)
        return 1
    got = json.loads(json.dumps(payload))
    rc = 0
    if got != want:
        rc = 1
        diffs = [r["source_file"] for r, w in zip(got["per_stream"],
                 want.get("per_stream", [])) if r != w]
        print("CHECK FAILED: analysis payload differs"
              + (f" (streams: {', '.join(diffs)})" if diffs else ""),
              file=sys.stderr)
    if render_volume(want, caveats) not in md_text:
        rc = 1
        print("CHECK FAILED: committed markdown tables differ from the "
              "committed payload or source caveats", file=sys.stderr)
    if render_volume(payload, caveats) not in md_text:
        rc = 1
        print("CHECK FAILED: recomputed tables differ from committed markdown",
              file=sys.stderr)
    if rc == 0:
        print(f"CHECK OK: {record_json.name} reproduces byte-for-byte "
              f"({len(got['per_stream'])} streams)")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--author", default="loom-builder@sky130-trng")
    ap.add_argument("--volume-record", type=Path, metavar="SOURCE.json",
                    help="analyse the streams of this raw-bit-volume-campaign "
                    "record (explicit; never auto-selected)")
    ap.add_argument("--compare", type=Path, action="append", default=[],
                    metavar="DERIVED.json",
                    help="earlier derived volume record(s) to report the min-H "
                    "shift against (repeatable; matched on corner/T/Vdd/Ts)")
    ap.add_argument("--check", type=Path, metavar="RECORD.json",
                    help="recompute and compare a committed volume-derived "
                    "record; exit nonzero on difference; writes nothing")
    args = ap.parse_args(argv)

    if args.check:
        return check_volume_record(args.check)
    if args.volume_record:
        return main_volume(args)

    records = raw_bit_entropy.campaign_records(RECORDS_DIR)
    if not records:
        print("error: no campaign records found", file=sys.stderr)
        return 1
    rec = records[-1]
    body, summary = analyse_record(rec)
    print(body)
    if not args.emit_record:
        return 0

    now, sha, rid = new_record_id(REPO_ROOT)
    header = [
        f"# {rid} -- raw-bit-min-entropy (battery + 90B estimators)",
        "",
        "**Claim**: reduced SP 800-22-style battery and SP 800-90B non-IID "
        f"estimators (min across estimators) over campaign record "
        f"`{rec['record_id']}`, per PVT corner; INSUFFICIENT where n is "
        "below the minimum length.",
        "",
        "**Level**: transistor (derived -- arithmetic over the cited record)",
        "**Seed**: N/A (deterministic reduction)",
        "**Analysis**: `sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`",
        "",
        "## Source record",
        "",
        f"- `{rec['record_id']}` (`{rec['testbench']}`)",
        "",
        "---",
        "",
    ]
    out = {"record_id": rid, "slug": "raw-bit-min-entropy",
           "level": "transistor (derived)",
           "analysis": "sim/raw-bit-min-entropy/analysis/raw-bit-battery.py",
           "source_record": rec["record_id"], "author": args.author,
           "timestamp_utc": now.isoformat(), "repo_sha": sha,
           "caveat": SOURCE_NOTE, **summary}
    result = mint_record(RECORDS_DIR, REPO_ROOT, rid, header, body, out,
                         author=args.author, now=now, sha=sha)
    return 0 if result is not None else 1


def main_volume(args) -> int:
    src = args.volume_record.resolve()
    try:
        rels = [c.resolve().relative_to(REPO_ROOT).as_posix()
                for c in args.compare]
        payload = json.loads(json.dumps(volume_payload(src, rels or None)))
        caveats = source_caveats(src)
    except VolumeInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    body = render_volume(payload, caveats)
    print(body)
    if not args.emit_record:
        return 0
    now, sha, rid = new_record_id(REPO_ROOT)
    rel = src.relative_to(REPO_ROOT).as_posix()
    out = {"record_id": rid, "slug": "raw-bit-min-entropy",
           "level": "behavioral (derived)",
           "analysis": "sim/raw-bit-min-entropy/analysis/raw-bit-battery.py",
           "source_record": payload["source_record"], "source_json": rel,
           "author": args.author, "timestamp_utc": now.isoformat(),
           "repo_sha": sha, "caveat": SOURCE_NOTE,
           "compare_records": rels,
           "ts20us_min_entropy": [
               {"corner": r["corner"], "temp_c": r["temp_c"],
                "vdd_v": r["vdd_v"], "seed": r["seed"],
                "h_min_bits": r["estimators"]["h_min_bits"],
                "binding_estimator": r["estimators"]["binding_estimator"],
                "binding_ties": r["estimators"]["binding_ties"]}
               for r in payload["per_stream"] if r["ts_name"] == "Ts20us"],
           "analysis_payload": payload}
    result = mint_record(RECORDS_DIR, REPO_ROOT, rid,
                         volume_header(rid, payload, src), body, out,
                         author=args.author, now=now, sha=sha)
    return 0 if result is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
