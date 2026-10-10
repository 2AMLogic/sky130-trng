#!/usr/bin/env python3
"""Behavioral raw-bit volume campaign (issue #188): >= 1e5 raw bits per PVT corner.

`level: behavioral`.  NOT transistor-level.  Standard library only, no
simulator, no PDK.

Why a behavioral model
----------------------
`sim/raw-bit-min-entropy/testbench/tb_raw_bit_stream.spice` costs ~46 s fixed
plus ~0.12 s of wall clock per simulated nanosecond (its own header).  At its
Ts = 100 ns that is ~12 s/bit; 1e5 bits per corner is ~1.4e6 s per corner, and
at DR-0003's literal Ts = 20 us it is ~2400 s/bit.  The cost is in simulated
time, so splitting into many short seeds does not reduce it.  This model
replaces the ring array + sampler by its first-order physics and is
**calibrated against, and cross-checked with, the transistor-level records**:

* ring periods T_1..T_4 per (process corner, PVT point) from
  `sim/ro-array-core-combining/records/` (`tr1..tr4`, the buffer-loaded N = 4
  array's own ladder);
* per-period jitter sigma_1 per (corner, PVT) from
  `sim/ro-ring-jitter-accumulation/records/` (`ro_ring5`);
* the sampler is an ideal edge sampler of the XOR of four 50 % duty square
  waves.

Model: ring i has phase theta_i (cycles).  Over one sample interval Ts it
advances Ts/T_i cycles with Gaussian noise of std sigma_1*sqrt(Ts/T_i)/T_i
cycles (white period jitter => edge-time variance linear in the number of
periods).  bit = XOR_i floor(2*frac(theta_i)).  All four rings start at phase 0
(the transistor deck's identical `.ic` start-up).

Unmodeled (stated in every record): XOR-tree edge/pulse loss (the combining
records measure `edge_retention` 0.55-0.68), sampler aperture/metastability,
supply/substrate coupling between rings, flicker (1/f) phase noise beyond
what sigma_k already shows, and the fixed-injection-level caveat of the
transistor noise decks.  Cross-check bounds are in `cross_checks()`.

Usage
-----
    python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py              # print only
    python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --emit-record
    python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --regenerate-check RECORD_JSON

Transistor-level cross-check inputs are `klt sim` batch responses committed
under `sim/raw-bit-volume-campaign/transistor/` (see `make-requests.py`).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SLUG = "raw-bit-volume-campaign"
SLUG_DIR = REPO_ROOT / "sim" / SLUG
TRANSISTOR_DIR = SLUG_DIR / "transistor"
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_behavioral_record  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "raw_bit_entropy",
    REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis" / "raw-bit-entropy.py")
rbe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rbe)

MASTER_SEED = 188
NBITS = 131072                      # 2**17 >= 1e5 per stream (#188/#197 records; default)
NBITS_STD = 1 << 20                 # 1048576 >= SP 800-90B conventional 1e6 samples (issue #253)
TS_TRANSISTOR_LEVEL = 100e-9        # #21 testbench Ts
TS_DR0003 = 20e-6                   # DR-0003 literal 50 kHz sample clock
CORNERS = ("tt", "ss", "ff")
# PVT points for which BOTH calibration inputs exist in the repo.
PVT_POINTS_BASE = ((27.0, 1.8), (-40.0, 1.62), (-40.0, 1.98))      # issue #188 record
# Issue #197: the 125 C end of the README operating envelope. The ring5 jitter
# records at these points already existed (20260825-0611/0619/0622-54f5715); the
# combining records were minted under #197 from `klt sim` batch jobs.
PVT_POINTS_HOT = ((125.0, 1.62), (125.0, 1.8), (125.0, 1.98))
def _hot_combining_present() -> bool:
    d = REPO_ROOT / "sim/ro-array-core-combining/records"
    return all(any(json.loads(p.read_text()).get("pvt") == {"temp_c": t, "vdd_v": v} for p in d.glob("*.json"))
               for t, v in PVT_POINTS_HOT)


# The explicit calibration/cross-check set. The hot points join it only once their combining
# records are committed, so the tree never declares a PVT point it cannot calibrate (the hot
# `klt sim` batch jobs for #197 were refused by the fleet: see the PR / klayout-tools#2851).
PVT_POINTS = PVT_POINTS_BASE + (PVT_POINTS_HOT if _hot_combining_present() else ())
PVT_SETS = {"base": PVT_POINTS_BASE, "hot": PVT_POINTS_HOT,
            "all": PVT_POINTS_BASE + PVT_POINTS_HOT}
XCHECK_PVT = (27.0, 1.8)            # PVT of the transistor-level cross-check
PERIOD_REL_UNC = 0.01               # declared 1-sigma relative period uncertainty
ENSEMBLE = 2000


# --------------------------------------------------------------------- inputs
def _latest(glob_dir: Path, pred):
    best = None
    for p in sorted(glob_dir.glob("*.json")):
        r = json.loads(p.read_text())
        if pred(r):
            best = r
    return best


VTH_DRIFT_SLUG = "ro-vth-drift-sensitivity"
VTH_DRIFT_SCHEMA = "vth-drift-calibration/1"


def _row_sha256(row) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def calibration_from_artifact(artifact, temp: float, vdd: float, corner: str, shift_mv) -> dict:
    """Calibration for one (PVT point, corner, (dVtn, d|Vtp|) mV) from an EXPLICIT versioned artifact
    (sim/ro-vth-drift-sensitivity/, issue #254). Never falls back to the historical time-zero records:
    a missing artifact entry, a schema mismatch, or a source-record/row-hash mismatch is a hard error.
    Returns the same shape as :func:`calibration`, plus ``shift_mv`` and ``q_ring``."""
    path = Path(artifact)
    if not path.is_file():
        raise SystemExit(f"error: calibration artifact {path} not found (no fallback to historical calibration)")
    art = json.loads(path.read_text())
    if art.get("schema") != VTH_DRIFT_SCHEMA:
        raise SystemExit(f"error: calibration artifact schema {art.get('schema')!r} != {VTH_DRIFT_SCHEMA!r}")
    dvn, dvp = float(shift_mv[0]), float(shift_mv[1])
    key = f"{corner}|{float(temp):g}C|{float(vdd):g}V|{dvn:g}|{dvp:g}"
    ent = art.get("entries", {}).get(key)
    if ent is None:
        raise SystemExit(f"error: calibration artifact has no entry for shift key {key!r} "
                         "(refusing to fall back to the historical time-zero calibration)")
    rec_path = REPO_ROOT / "sim" / VTH_DRIFT_SLUG / "records" / f"{art['source_record']}.json"
    if not rec_path.is_file():
        raise SystemExit(f"error: calibration source record {art['source_record']} not found")
    by_key = {r["key"]: r for r in json.loads(rec_path.read_text())["rows"]}
    for deck in ("ring5", "array"):
        src = ent["source_rows"][deck]
        want_key = f"{deck}|{corner}|{float(temp):g}C|{float(vdd):g}V|{dvn:g}|{dvp:g}"
        if src["key"] != want_key:
            raise SystemExit(f"error: artifact entry {key!r} cites source row {src['key']!r}, expected {want_key!r}")
        row = by_key.get(src["key"])
        if row is None or _row_sha256(row) != src["row_sha256"]:
            raise SystemExit(f"error: source-hash mismatch for {src['key']!r} in record {art['source_record']}")
    return {
        "temp_c": temp, "vdd_v": vdd, "corner": corner, "shift_mv": [dvn, dvp],
        "periods_s": list(ent["array_periods_s"]),
        "sigma": {1: ent["sigma_1_corrected"]},
        "tbar_ring5_s": ent["T_0"], "q_ring": ent["q_ring"],
        "combining_record": art["source_record"], "jitter_record": art["source_record"],
        "combining_job_id": ent["source_rows"]["array"]["job_id"], "jitter_job_id": ent["source_rows"]["ring5"]["job_id"],
        "edge_retention": by_key[ent["source_rows"]["array"]["key"]]["metrics"]["edge_retention"],
    }


def calibration(temp: float, vdd: float, corner: str, *, shift_mv=None, artifact=None) -> dict:
    """Ring periods and sigma_k for one (PVT point, corner) from committed records.

    With ``artifact`` (a vth-drift calibration artifact path) the shift key ``shift_mv`` = (dVtn, d|Vtp|)
    in mV is REQUIRED and the historical records are not consulted; ``shift_mv`` without ``artifact`` is
    rejected too, so a shifted request can never silently run on the time-zero calibration."""
    if artifact is not None or shift_mv is not None:
        if artifact is None or shift_mv is None:
            raise SystemExit("error: a shifted calibration needs BOTH an explicit artifact and a shift key "
                             "(no silent time-zero fallback)")
        return calibration_from_artifact(artifact, temp, vdd, corner, shift_mv)
    pvt = {"temp_c": temp, "vdd_v": vdd}
    comb = _latest(REPO_ROOT / "sim/ro-array-core-combining/records", lambda r: r.get("pvt") == pvt)
    jit = _latest(REPO_ROOT / "sim/ro-ring-jitter-accumulation/records",
                  lambda r: r.get("pvt") == pvt and "ring5" in r.get("testbench", ""))
    if comb is None or jit is None:
        raise SystemExit(f"error: no calibration records for {pvt}")
    cc = next((c for c in comb["corners"] if c["corner"] == corner), None)
    jc = next((c for c in jit["corners"] if c["corner"] == corner), None)
    for what, rec_, c in (("combining", comb, cc), ("jitter", jit, jc)):
        if c is None or not c.get("ok", False):
            raise SystemExit(f"error: {what} record {rec_['record_id']} has no passing {corner} corner at {pvt}")
    cm, jm = cc["measurements"], jc["measurements"]
    return {
        "temp_c": temp, "vdd_v": vdd, "corner": corner,
        "periods_s": [cm[f"tr{i}"] for i in (1, 2, 3, 4)],
        "sigma": {k: jm[f"sigma_{k}"] for k in (1, 2, 4, 8)},
        "tbar_ring5_s": jm["tbar"],
        "combining_record": comb["record_id"], "jitter_record": jit["record_id"],
        # batch job ids (None for records that predate `klt sim` batch runs)
        "combining_job_id": (comb.get("klt_sim") or {}).get("job_id"),
        "jitter_job_id": (jit.get("klt_sim") or {}).get("job_id"),
        "edge_retention": cm.get("edge_retention"),
    }


# ---------------------------------------------------------------------- model
def sub_seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{MASTER_SEED}:{label}".encode()).digest()[:8], "big")


def stream(periods, sigma1, ts, n, rng, theta0=(0.0, 0.0, 0.0, 0.0)) -> list[int]:
    adv = [(ts / T) % 1.0 for T in periods]
    sd = [sigma1 * math.sqrt(ts / T) / T for T in periods]
    th = list(theta0)
    gauss = rng.gauss
    out = []
    for _ in range(n):
        out.append((int(2 * th[0]) ^ int(2 * th[1]) ^ int(2 * th[2]) ^ int(2 * th[3])) & 1)
        for i in range(4):
            th[i] = (th[i] + adv[i] + gauss(0.0, sd[i])) % 1.0
    return out


def pack_hex(bits: list[int]) -> str:
    assert len(bits) % 8 == 0
    return "".join(f"{int(''.join(map(str, bits[i:i + 8])), 2):02x}" for i in range(0, len(bits), 8))


def unpack_hex(h: str) -> list[int]:
    return [int(c) for byte in bytes.fromhex(h) for c in f"{byte:08b}"]


def stats(bits: list[int], seed_label: str) -> dict:
    est = rbe.mcv_estimate(bits)
    n = len(bits)
    mean = est["ones"] / n
    var = mean * (1 - mean) or 1e-12
    ac = {}
    for lag in (1, 2, 3, 4, 8):
        ac[lag] = sum((bits[i] - mean) * (bits[i + lag] - mean) for i in range(n - lag)) / ((n - lag) * var)
    z_mono = (est["ones"] - n / 2) / math.sqrt(n / 4)

    def ctx_acc(seq, c):
        counts = {}
        for i in range(c, len(seq)):
            ctx = 0
            for b in seq[i - c:i]:
                ctx = (ctx << 1) | b
            cnt = counts.setdefault(ctx, [0, 0])
            cnt[seq[i]] += 1
        return sum(max(v) for v in counts.values()) / (len(seq) - c)

    shuf = bits[:]
    random.Random(sub_seed("shuffle:" + seed_label)).shuffle(shuf)
    best_c, best_acc = 0, 0.0
    for c in range(0, 9):
        a = ctx_acc(bits, c)
        if a > best_acc:
            best_c, best_acc = c, a
    null_acc = ctx_acc(shuf, best_c)
    return {
        **est, "z_monobit": z_mono, "autocorr": {str(k): v for k, v in ac.items()},
        "best_context_len": best_c, "best_context_acc": best_acc,
        "best_context_acc_shuffled_null": null_acc,
        "h_context_min_bits": -math.log2(best_acc),
    }


# ----------------------------------------------------------------- cross-check
def _quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def jitter_estimator(rng, sigma1, tbar=2.4e-9):
    """The testbench's own sigma_k estimator on 21 model edge times."""
    tc = [0.0]
    for _ in range(20):
        tc.append(tc[-1] + tbar + rng.gauss(0.0, sigma1))
    tb = (tc[20] - tc[0]) / 20
    out = {}
    for k in (1, 2, 4, 8):
        r = [(tc[j + k] - tc[j]) - k * tb for j in range(21 - k)]
        out[k] = math.sqrt((sum(x * x for x in r) / len(r)) / (1 - k / 20))
    return out


def load_transistor_sequences() -> dict:
    """{corner: [(label, bits)]} from committed klt-sim batch responses + the #21 record."""
    out = {c: [] for c in CORNERS}
    jobs = []
    if TRANSISTOR_DIR.is_dir():
        for p in sorted(TRANSISTOR_DIR.glob("seed*.klt-sim.json")):
            resp = json.loads(p.read_text())
            job = resp["environment"].get("remote", {}).get("job_id")
            jobs.append({"file": p.name, "job_id": job, "status": resp.get("status")})
            for c in resp["corners"]:
                if c["status"] != "pass":
                    continue
                m = {x["name"]: x["value"] for x in c["measurements"]}
                bits, _, _ = rbe.extract_sequence(m, 1.8)
                if len(bits) >= 23:  # ss: bit 0 is the start-up invalid sample (as in #21)
                    out[c["process"]].append((p.name.split(".")[0], bits))
    old = REPO_ROOT / "sim/raw-bit-min-entropy/records/20260905-231908-6b86c9c.json"
    rec = json.loads(old.read_text())
    for c in rec["corners"]:
        bits, n_tot, _ = rbe.extract_sequence(c["measurements"], rec["pvt"]["vdd_v"])
        if len(bits) >= 23:
            out[c["corner"]].append(("20260905-231908-6b86c9c(seed1)", bits))
    # Window length per corner: if any sequence lost its (start-up) first sample, compare all
    # sequences over the last 23 samples so Hamming/p_hat windows are aligned and equal-length.
    for c in CORNERS:
        if any(len(b) < 24 for _, b in out[c]):
            out[c] = [(l, b[-23:]) for l, b in out[c]]
    return out, jobs


def hamming_mean(seqs):
    d, m = 0, 0
    for i in range(len(seqs)):
        for j in range(i + 1, len(seqs)):
            d += sum(a != b for a, b in zip(seqs[i], seqs[j]))
            m += 1
    return d / (m * len(seqs[0])) if m else float("nan")


def cross_checks() -> dict:
    res = {"jitter": [], "phat": [], "hamming": [], "transistor_jobs": []}
    # (1) jitter accumulation: record sigma_k/sigma_1 vs the SAME estimator on the model
    for (temp, vdd) in PVT_POINTS:
        for corner in CORNERS:
            cal = calibration(temp, vdd, corner)
            rng = random.Random(sub_seed(f"jit:{temp}:{vdd}:{corner}"))
            reps = [jitter_estimator(rng, cal["sigma"][1], cal["tbar_ring5_s"]) for _ in range(ENSEMBLE)]
            row = {"temp_c": temp, "vdd_v": vdd, "corner": corner, "ratios": {}}
            for k in (2, 4, 8):
                dist = [r[k] / r[1] for r in reps]
                lo, hi = _quantile(dist, 0.005), _quantile(dist, 0.995)
                rec_ratio = cal["sigma"][k] / cal["sigma"][1]
                row["ratios"][str(k)] = {"record": rec_ratio, "model_median": _quantile(dist, 0.5),
                                         "band99": [lo, hi], "inside": lo <= rec_ratio <= hi}
            res["jitter"].append(row)
    # (2)+(3) p_hat of 24-sample windows and seed-to-seed Hamming at Ts = 100 ns, 27C/1.8V
    seqs, jobs = load_transistor_sequences()
    res["transistor_jobs"] = jobs
    for corner in CORNERS:
        cal = calibration(*XCHECK_PVT, corner)
        rng = random.Random(sub_seed(f"xchk:{corner}"))
        phats, hams = [], []
        n_seeds = max(len(seqs[corner]), 2)
        W = len(seqs[corner][0][1]) if seqs[corner] else 24
        for _ in range(ENSEMBLE):
            per = [T * (1 + rng.gauss(0, PERIOD_REL_UNC)) for T in cal["periods_s"]]
            ens = [stream(per, cal["sigma"][1], TS_TRANSISTOR_LEVEL, 24, rng)[24 - W:] for _ in range(n_seeds)]
            phats.append([max(sum(s), W - sum(s)) / W for s in ens])
            hams.append(hamming_mean(ens))
        flat = [x for row in phats for x in row]
        plo, phi = _quantile(flat, 0.005), _quantile(flat, 0.995)
        t = seqs[corner]
        tp = [max(sum(b), len(b) - sum(b)) / len(b) for _, b in t]
        res["phat"].append({
            "corner": corner, "n_transistor_sequences": len(t),
            "transistor_phat": tp, "model_band99": [plo, phi],
            "model_median": _quantile(flat, 0.5),
            "inside_all": all(plo <= x <= phi for x in tp) if tp else None})
        hlo, hhi = _quantile(hams, 0.005), _quantile(hams, 0.995)
        th = hamming_mean([b for _, b in t]) if len(t) >= 2 else None
        res["hamming"].append({
            "corner": corner, "n_transistor_sequences": len(t),
            "transistor_mean_pairwise_hamming": th,
            "model_median": _quantile(hams, 0.5), "model_band99": [hlo, hhi],
            "inside": (hlo <= th <= hhi) if th is not None else None})
    return res


# -------------------------------------------------------------------- campaign
def run_campaign(outdir: Path, points=PVT_POINTS_BASE, nbits: int = NBITS) -> list[dict]:
    rows = []
    for (temp, vdd) in points:
        for corner in CORNERS:
            cal = calibration(temp, vdd, corner)
            for ts_name, ts in (("Ts100ns", TS_TRANSISTOR_LEVEL), ("Ts20us", TS_DR0003)):
                label = f"stream:{corner}:{temp:g}C:{vdd:g}V:{ts_name}"
                bits = stream(cal["periods_s"], cal["sigma"][1], ts, nbits, random.Random(sub_seed(label)))
                hx = pack_hex(bits)
                fname = f"bits_{corner}_{temp:g}C_{vdd:g}V_{ts_name}.hex.txt"
                (outdir / fname).write_text(hx + "\n")
                st = stats(bits, label)
                rows.append({"corner": corner, "temp_c": temp, "vdd_v": vdd, "ts_s": ts,
                             "ts_name": ts_name, "seed_label": label, "seed": sub_seed(label),
                             "file": fname, "sha256_hex": hashlib.sha256(hx.encode()).hexdigest(),
                             "calibration": {k: cal[k] for k in ("periods_s", "sigma", "combining_record", "jitter_record", "combining_job_id", "jitter_job_id")},
                             **st})
    return rows


def robustness(rows, nbits: int = NBITS) -> list[dict]:
    """Sensitivity of the DR-0003-Ts result to the (unknowable) exact periods."""
    out = []
    for corner in CORNERS:
        cal = calibration(*XCHECK_PVT, corner)
        for d in range(8):
            rng = random.Random(sub_seed(f"robust:{corner}:{d}"))
            per = [T * (1 + rng.gauss(0, PERIOD_REL_UNC)) for T in cal["periods_s"]]
            bits = stream(per, cal["sigma"][1], TS_DR0003, nbits, rng)
            st = stats(bits, f"robust:{corner}:{d}")
            out.append({"corner": corner, "draw": d, "p_hat": st["p_hat"], "h_hat_bits": st["h_hat_bits"],
                        "h_context_min_bits": st["h_context_min_bits"],
                        "best_context_len": st["best_context_len"]})
    return out


def fmt_band(b):
    return f"[{b[0]:.3f}, {b[1]:.3f}]"


HOT_RECORD = "20261008-135454-847b454"      # the #197 record (never modified)
BASE_RECORD = "20261008-061809-56e0fb7"   # the #188 record the hot set extends (never modified)


def findings(xc) -> list[str]:
    """Every failing cross-check row, listed explicitly (never filtered out)."""
    out = []
    for row in xc["jitter"]:
        for k, v in row["ratios"].items():
            if not v["inside"]:
                out.append(f"jitter sigma_{k}/sigma_1 at {row['temp_c']:g} C / {row['vdd_v']:g} V / "
                           f"{row['corner']}: record {v['record']:.2f} outside model 99% band {fmt_band(v['band99'])}")
    for r in xc["phat"]:
        if r["inside_all"] is False:
            out.append(f"p_hat (24-sample, Ts = 100 ns) {r['corner']}: transistor "
                       f"{', '.join(f'{x:.3f}' for x in r['transistor_phat'])} outside model 99% band {fmt_band(r['model_band99'])}")
    for r in xc["hamming"]:
        if r["inside"] is False:
            out.append(f"seed-to-seed Hamming {r['corner']}: transistor {r['transistor_mean_pairwise_hamming']:.4f} "
                       f"outside model 99% band {fmt_band(r['model_band99'])}")
    return out


def build_body(rows, xc, rob, point_set="base", nbits: int = NBITS) -> tuple[str, dict]:
    L = []
    if point_set == "all":
        L.append("## Scope of this record (issue #253)")
        L.append("")
        L.append(f"Standards-sized re-mint of the #188 (`{BASE_RECORD}`) and #197 (`{HOT_RECORD}`) volume streams: "
                 f"all 36 streams (3 process x 6 PVT points x 2 Ts) at {nbits} bits (2^20) each, so SP 800-90B "
                 "non-IID estimators run at their conventional >= 1e6-sample size. Same generator, calibration, "
                 "master seed and per-stream seed labels as #188/#197 (no model change), so the first 131072 "
                 "bits of each stream equal the corresponding 2^17 stream. This record SUPERSEDES the two "
                 "records by name for new citations; neither is edited and both still replay with "
                 "`--regenerate-check`. Calibration pairs per (process, supply) are listed below; the jitter "
                 "cross-check covers all six PVT points. The sensitivity table (period-uncertainty draws) is "
                 "unchanged from #188: it stays at 2^17 samples per draw and was not re-run at 2^20.")
        L.append("")
        L.append("| T (C) | Vdd | combining record | combining batch job | jitter record (local run, no batch job) |")
        L.append("|---|---|---|---|---|")
        seen = set()
        for r in rows:
            c = r["calibration"]
            key = (r["temp_c"], r["vdd_v"])
            if key in seen:
                continue
            seen.add(key)
            L.append(f"| {r['temp_c']:g} | {r['vdd_v']:g} | `{c['combining_record']}` | `{c['combining_job_id']}` | `{c['jitter_record']}` |")
        L.append("")
    if point_set == "hot":
        L.append("## Scope of this record (issue #197)")
        L.append("")
        L.append(f"Extends `{BASE_RECORD}` (issue #188; unmodified, not superseded) to the 125 degC end of the "
                 "README operating envelope. This record contains ONLY the 18 hot streams (3 process x 3 "
                 "supplies x 2 Ts). Calibration pairs, per (process, supply): the new `ro-array-core-combining` "
                 "125 degC records (transistor level, `klt sim` batch jobs listed below) with the pre-existing "
                 "125 degC `ro-ring-jitter-accumulation` ring5 records. The jitter cross-check below covers "
                 "ALL six PVT points (the three #188 points are recomputed and expected to match that record).")
        L.append("")
        L.append("| T (C) | Vdd | combining record | combining batch job | jitter record (local run, no batch job) |")
        L.append("|---|---|---|---|---|")
        seen = set()
        for r in rows:
            c = r["calibration"]
            key = (r["temp_c"], r["vdd_v"])
            if key in seen:
                continue
            seen.add(key)
            L.append(f"| {r['temp_c']:g} | {r['vdd_v']:g} | `{c['combining_record']}` | `{c['combining_job_id']}` | `{c['jitter_record']}` |")
        L.append("")
    L.append("## What this is")
    L.append("")
    L.append(f"{len(rows)} behavioral raw-bit streams of {nbits} bits each (>= 1e5), one per "
             "(process corner x PVT point x Ts), from `sim/raw-bit-volume-campaign/behavioral_raw_bit.py`. "
             "**`level: behavioral` -- not transistor-level.** The model replaces the 4-ring array + "
             "sampler by white-period-jitter phase diffusion of four rings XOR-ed and edge-sampled, "
             "calibrated from committed transistor records (ring periods: `ro-array-core-combining`; "
             "sigma_1: `ro-ring-jitter-accumulation`). A transistor-level run of this volume is not "
             "tractable: the #21 testbench costs ~46 s + ~0.12 s per simulated ns, i.e. ~1.4e6 s per "
             "corner for 1e5 bits at Ts = 100 ns and ~2400 s per bit at Ts = 20 us.")
    L.append("")
    L.append("## Ts used vs DR-0003")
    L.append("")
    L.append("- `Ts20us` streams use **DR-0003's literal Ts = 20 us (50 kHz)**. These are the streams that "
             "speak to the design point (as a model).")
    L.append("- `Ts100ns` streams use the #21 transistor testbench's Ts = 100 ns, 200x shorter than "
             "DR-0003. They exist only so the model can be cross-checked against transistor-level data; "
             "do not cite them for the design point.")
    L.append("")
    L.append("## Seed policy")
    L.append("")
    L.append(f"Master seed {MASTER_SEED}; each stream's `random.Random` seed is the first 8 bytes of "
             f"sha256(`\"{MASTER_SEED}:<label>\"`) (label and seed listed per stream in the JSON). One "
             "continuous noise trajectory per stream. Unlike the transistor deck, the model's noise "
             "increments are independent between samples by construction, so this is a model "
             "assumption, not evidence of independence of the silicon. Streams are stored as packed hex "
             "(`.hex.txt`, MSB first, sha256 in the JSON) and reproducible with "
             "`python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --regenerate-check <record json>` "
             f"(Python {sys.version.split()[0]}; `random.gauss` stream).")
    L.append("")
    L.append("## Streams (MCV via `raw-bit-entropy.py`'s `mcv_estimate`; context = most-common-next-bit given previous c bits)")
    L.append("")
    L.append("| corner | T (C) | Vdd | Ts | n | p_hat | p_u (99%) | H_MCV | z_mono | lag-1 ac | best c | ctx acc (null) | H_ctx |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | {r['ts_name']} | {r['n']} | "
                 f"{r['p_hat']:.4f} | {r['p_u_99']:.4f} | {r['h_hat_bits']:.4f} | {r['z_monobit']:+.2f} | "
                 f"{r['autocorr']['1']:+.4f} | {r['best_context_len']} | "
                 f"{r['best_context_acc']:.4f} ({r['best_context_acc_shuffled_null']:.4f}) | "
                 f"{r['h_context_min_bits']:.4f} |")
    L.append("")
    L.append("`H_ctx` = -log2(best-context prediction accuracy), c = 0..8. The shuffled-null accuracy at "
             "the same c shows the finite-sample overfit bias. These are quick diagnostics, not the "
             "SP 800-22 battery or the non-MCV 90B estimators (filed as the companion issue).")
    L.append("")
    L.append("## Cross-checks against transistor-level evidence (27 degC / 1.8 V)")
    L.append("")
    L.append("### (1) Jitter accumulation: sigma_k/sigma_1, record vs the testbench's own estimator run on the model")
    L.append("")
    L.append("The model is calibrated on sigma_1 only. The ring-jitter testbench's estimator (21 edges, "
             "finite-sample-corrected) is replayed on the model "
             f"({ENSEMBLE} draws); the record's sigma_k/sigma_1 must fall inside the model's central 99% band.")
    L.append("")
    L.append("| T (C) | Vdd | corner | k | record ratio | model median | model 99% band | inside |")
    L.append("|---|---|---|---|---|---|---|---|")
    n_in = n_tot = 0
    for row in xc["jitter"]:
        for k, v in row["ratios"].items():
            n_tot += 1
            n_in += v["inside"]
            L.append(f"| {row['temp_c']:g} | {row['vdd_v']:g} | {row['corner']} | {k} | {v['record']:.2f} | "
                     f"{v['model_median']:.2f} | {fmt_band(v['band99'])} | {'yes' if v['inside'] else '**NO**'} |")
    L.append("")
    L.append(f"**{n_in}/{n_tot} ratios inside the 99% band.** Low discriminating power: the record's "
             "sigma_k are single-seed 20-period estimates, so the estimator's own sampling band is wide "
             "(for k = 8 it spans roughly 1x to 5.5x sigma_1). Read this as 'the transistor jitter record "
             "is statistically consistent with white period jitter', not as a proof that jitter is white; "
             "a trend toward faster-than-sqrt(k) accumulation (e.g. 1/f) is not excluded.")
    L.append("")
    L.append("### (2) p_hat of 24-sample windows at Ts = 100 ns")
    L.append("")
    L.append("Model band = central 99% of MCV p_hat over 24-sample windows, with each ring period "
             f"perturbed by N(0, {PERIOD_REL_UNC:.0%}) (declared; the transistor tb differs from the "
             f"combining tb) and {ENSEMBLE} draws.")
    L.append("")
    L.append("| corner | transistor sequences | transistor p_hat (each) | model median | model 99% band | all inside |")
    L.append("|---|---|---|---|---|---|")
    for r in xc["phat"]:
        L.append(f"| {r['corner']} | {r['n_transistor_sequences']} | "
                 f"{', '.join(f'{x:.3f}' for x in r['transistor_phat'])} | {r['model_median']:.3f} | "
                 f"{fmt_band(r['model_band99'])} | {r['inside_all']} |")
    L.append("")
    L.append("### (3) Seed-to-seed bit disagreement at Ts = 100 ns (jitter -> bit coupling)")
    L.append("")
    L.append("Mean pairwise Hamming fraction between independent-seed 24-bit sequences. At Ts = 100 ns the "
             "rings accumulate only ~0.03 cycle of jitter in 24 samples, so the sequences are nearly "
             "deterministic and the noise only flips bits that land near an edge; this fraction tests the "
             "model's jitter-to-bit conversion directly.")
    L.append("")
    L.append("| corner | transistor sequences | transistor mean Hamming | model median | model 99% band | inside |")
    L.append("|---|---|---|---|---|---|")
    for r in xc["hamming"]:
        th = r["transistor_mean_pairwise_hamming"]
        L.append(f"| {r['corner']} | {r['n_transistor_sequences']} | "
                 f"{'n/a' if th is None else f'{th:.4f}'} | {r['model_median']:.4f} | "
                 f"{fmt_band(r['model_band99'])} | {r['inside']} |")
    L.append("")
    fnd = findings(xc)
    L.append("### Findings (every failing cross-check row; none suppressed, no threshold relaxed)")
    L.append("")
    if fnd:
        L += [f"- {f}" for f in fnd]
    else:
        L.append("- none: all rows of (1)-(3) fall inside their declared bands.")
    L.append("")
    L.append("Transistor-level batch jobs (`klt sim`, backend `batch`, request generator "
             "`sim/raw-bit-volume-campaign/make-requests.py`):")
    L.append("")
    if xc["transistor_jobs"]:
        for j in xc["transistor_jobs"]:
            L.append(f"- `{j['file']}`: job `{j['job_id']}`, status `{j['status']}`")
    else:
        L.append("- **none available**: the transistor leg is absent from this record; only the #21 "
                 "single-seed sequences were used. See the PR for the submit error.")
    L.append("")
    nj = len(xc["transistor_jobs"])
    L.append(f"Transistor leg size: {nj} batch seed file(s) (tt/ss/ff, 24 samples each, Ts = 100 ns) plus the "
             "#21 record's seed-1 sequences (ss: 23 usable samples; all ss sequences compared over their last "
             "23 samples, the first sample being the start-up invalid one). That is 2 sequences per corner, so "
             "checks (2) and (3) are weak (wide bands) -- they rule out gross disagreement only. No "
             "transistor-level run at Ts = 20 us exists. Independence caveat: no stream here is a "
             "concatenation of short runs; each behavioral stream is one continuous trajectory, and the "
             "transistor sequences are separate short runs, each its own noise trajectory (never joined).")
    L.append("")
    L.append("## Sensitivity of the DR-0003-Ts result to exact ring periods (27 degC / 1.8 V)")
    L.append("")
    L.append("The deterministic phase advance per sample (Ts/T_i mod 1) is unknowable at 1e-4 cycles "
             f"from the records. 8 draws per corner of {PERIOD_REL_UNC:.0%} period error, Ts = 20 us:")
    L.append("")
    L.append("| corner | min H_MCV | max p_hat | min H_ctx | max best c |")
    L.append("|---|---|---|---|---|")
    for c in CORNERS:
        rr = [x for x in rob if x["corner"] == c]
        L.append(f"| {c} | {min(x['h_hat_bits'] for x in rr):.4f} | {max(x['p_hat'] for x in rr):.4f} | "
                 f"{min(x['h_context_min_bits'] for x in rr):.4f} | {max(x['best_context_len'] for x in rr)} |")
    L.append("")
    L.append("## Caveats that bound how this record may be cited")
    L.append("")
    L.append("- **Behavioral model, not transistor-level.** Valid only to the extent of the cross-checks "
             "above; the Ts = 20 us streams are an extrapolation of those checks across 200x in Ts that "
             "no transistor run has covered.")
    L.append("- **Unmodeled:** XOR-tree pulse loss (`edge_retention` 0.55-0.68 in the combining records), "
             "sampler aperture/metastability, inter-ring coupling, 1/f phase noise, supply noise, "
             "temperature drift over a run. Injection level of the underlying noise decks is fixed and "
             "good to ~1.5-2x (their own caveat).")
    L.append("- **High marginal MCV entropy at Ts = 20 us is a model output, not a ratified H.** Each ring "
             "diffuses ~0.1 cycle per sample, so the hidden phases randomize over ~100 samples and the "
             "marginal is unbiased; that follows from the model's assumptions (white jitter, free-running "
             "rings, no coupling) and must be measured on silicon. No spec threshold is changed by this "
             "record (DR-0003/DR-0004 untouched).")
    L.append("- **MCV on the marginal hides serial structure.** At Ts = 100 ns the same marginal reads "
             "H_MCV ~ 0.98 while the context predictor reaches H_ctx 0.4-0.75: the sequence is "
             "quasi-deterministic. The #21 record's H_hat at Ts = 100 ns therefore does not measure "
             "entropy rate in either direction. At Ts = 20 us the context predictor beats its shuffled "
             "null only slightly (see table); the battery issue should quantify this.")
    L.append("- **Not an SP 800-90B assessment and not the SP 800-22 battery.** Provisional until silicon.")
    if point_set in ("hot", "all"):
        L.append("- **Calibration PVT coverage:** the six PVT points that have both combining and ring5-jitter "
                 "records: the three #188 points plus 125 C at 1.62/1.8/1.98 V. The transistor-level p_hat and "
                 "Hamming cross-checks (2)-(3) exist ONLY at 27 C/1.8 V; there is no transistor-level "
                 "raw-bit run at 125 C, so the hot streams are validated only through the jitter-accumulation "
                 "check and the calibration provenance. The sensitivity table is the #188 27 C/1.8 V one, "
                 "unchanged; it was not re-derived for the hot points.")
    else:
        L.append("- **Calibration PVT coverage:** only the three PVT points that have both combining and "
                 "ring5-jitter records (27 C/1.8 V, -40 C/1.62 V, -40 C/1.98 V). 125 C points have no "
                 "combining record and are not run (extended by issue #197, see its own record).")
    summary = {"streams": rows, "cross_checks": xc, "robustness": rob,
               "jitter_ratios_inside": [n_in, n_tot], "findings": fnd, "point_set": point_set,
               "calibration_jobs": sorted({(r["temp_c"], r["vdd_v"], r["calibration"]["combining_record"],
                                            r["calibration"]["combining_job_id"]) for r in rows})}
    return "\n".join(L), summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--regenerate-check", metavar="RECORD_JSON")
    ap.add_argument("--set", choices=sorted(PVT_SETS), default="base", dest="point_set",
                    help="PVT points whose streams are generated: base (#188 record), hot (125 C, #197), "
                    "or all (both; issue #253)")
    ap.add_argument("--nbits", type=int, default=NBITS,
                    help=f"bits per stream (default {NBITS} = #188/#197; {NBITS_STD} for issue #253); multiple of 8")
    ap.add_argument("--author", default="loom-builder@sky130-trng")
    args = ap.parse_args(argv)

    if args.regenerate_check:
        rec = json.loads(Path(args.regenerate_check).read_text())
        bad = 0
        for r in rec["streams"]:
            cal = calibration(r["temp_c"], r["vdd_v"], r["corner"])
            bits = stream(cal["periods_s"], cal["sigma"][1], r["ts_s"], r.get("n", NBITS), random.Random(r["seed"]))
            ok = hashlib.sha256(pack_hex(bits).encode()).hexdigest() == r["sha256_hex"]
            bad += not ok
            print(("OK  " if ok else "FAIL"), r["file"])
        return 1 if bad else 0

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if args.nbits % 8 or args.nbits < 1000:
            ap.error("--nbits must be a multiple of 8 and >= 1000")
        rows = run_campaign(tmp, PVT_SETS[args.point_set], args.nbits)
        xc = cross_checks()
        rob = robustness(rows)      # always the #188 2^17-per-draw sensitivity (see body)
        body, summary = build_body(rows, xc, rob, args.point_set, args.nbits)
        print(body)
        if not args.emit_record:
            return 0
        rid = mint_behavioral_record(
            REPO_ROOT, SLUG,
            (f"behavioral (calibrated, cross-checked) raw-bit streams of {args.nbits} bits (>= 1e6, SP 800-90B "
             "standard size) per tt/ss/ff corner at all six PVT points (27/-40/125 degC), at DR-0003's literal "
             "Ts = 20 us and at the #21 testbench's Ts = 100 ns; supersedes the 2^17 records "
             f"{BASE_RECORD} and {HOT_RECORD} by name; issue #253")
            if args.point_set == "all" else
            ("behavioral (calibrated, cross-checked) raw-bit streams of >= 1e5 bits per tt/ss/ff corner at "
             "125 degC x 1.62/1.8/1.98 V, at DR-0003's literal Ts = 20 us and at the #21 testbench's Ts = "
             "100 ns; extends the #188 record to the hot end of the envelope; issue #197")
            if args.point_set == "hot" else
            ("behavioral (calibrated, cross-checked) raw-bit streams of >= 1e5 bits per tt/ss/ff corner at "
             "three PVT points, at DR-0003's literal Ts = 20 us and at the #21 testbench's Ts = 100 ns; "
             "issue #188"),
            body, summary, level="behavioral",
            supersedes=f"{BASE_RECORD}, {HOT_RECORD} (by name; neither edited)" if args.point_set == "all" else None,
            seeds={"master": MASTER_SEED, "policy": "per-stream seed = sha256(master:label)[:8]"},
            artifacts=[tmp / r["file"] for r in rows],
            tools={"model": "sim/raw-bit-volume-campaign/behavioral_raw_bit.py"},
            author=args.author)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
