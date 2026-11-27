"""Calibrated four-ring phase-diffusion behavioral model of the raw bit: the
model, its calibration loader and the shared stream statistics.  Standard
library only.

This is the reusable half of the raw-bit volume campaign (issue #188), which
was defined inside that campaign's CLI
(`sim/raw-bit-volume-campaign/behavioral_raw_bit.py`) next to the report,
record and cross-check code.  Pure model and calibration: it mints nothing,
imports no campaign CLI, record or evidence module, and reads no record until
a calibration is asked for.  The campaigns that share the model import it
directly instead of executing the CLI by path (issue #797; the seam
`raw_bit_volume.py` opened for the stream reader in #790 and
`bitstream_stats.py` for the estimators in #794).

Model
-----
ring i has phase theta_i (cycles).  Over one sample interval Ts it advances
Ts/T_i cycles with Gaussian noise of std sigma_1*sqrt(Ts/T_i)/T_i cycles
(white period jitter => edge-time variance linear in the number of periods).
bit = XOR_i floor(2*frac(theta_i)).  All four rings start at phase 0 (the
transistor deck's identical `.ic` start-up).  `calibration()` gives the ring
periods and sigma_k per (process corner, PVT point) from the committed
`ro-array-core-combining` and `ro-ring-jitter-accumulation` records, or, for
a threshold shift, from an explicit versioned artifact only.

Unmodeled (stated in every record): XOR-tree edge/pulse loss, sampler
aperture/metastability, supply/substrate coupling between rings, flicker (1/f)
phase noise, and the fixed-injection-level caveat of the transistor noise
decks.  Simulation-derived; provisional until silicon.

Repo root
---------
Record paths resolve against this module's ``REPO_ROOT`` unless a caller
passes ``repo_root=``.  The campaign CLI wraps the two calibration entry
points to pass its own ``REPO_ROOT`` at call time.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hashing import sha256_json  # noqa: E402
from bitstream_stats import mcv_estimate  # noqa: E402

MASTER_SEED = 188
TS_TRANSISTOR_LEVEL = 100e-9        # #21 testbench Ts
TS_DR0003 = 20e-6                   # DR-0003 literal 50 kHz sample clock
CORNERS = ("tt", "ss", "ff")
# PVT points for which BOTH calibration inputs exist in the repo.
PVT_POINTS_BASE = ((27.0, 1.8), (-40.0, 1.62), (-40.0, 1.98))      # issue #188 record
# Issue #197: the 125 C end of the README operating envelope. The ring5 jitter
# records at these points already existed (20260825-0611/0619/0622-54f5715); the
# combining records were minted under #197 from `klt sim` batch jobs.
PVT_POINTS_HOT = ((125.0, 1.62), (125.0, 1.8), (125.0, 1.98))
PVT_SETS = {"base": PVT_POINTS_BASE, "hot": PVT_POINTS_HOT,
            "all": PVT_POINTS_BASE + PVT_POINTS_HOT}
PERIOD_REL_UNC = 0.01               # declared 1-sigma relative period uncertainty
ENSEMBLE = 2000
VTH_DRIFT_SLUG = "ro-vth-drift-sensitivity"
VTH_DRIFT_SCHEMA = "vth-drift-calibration/1"


# --------------------------------------------------------------------- inputs
def _latest(glob_dir: Path, pred):
    best = None
    for p in sorted(glob_dir.glob("*.json")):
        r = json.loads(p.read_text())
        if pred(r):
            best = r
    return best


def calibration_from_artifact(artifact, temp: float, vdd: float, corner: str, shift_mv, *,
                              repo_root=None) -> dict:
    """Calibration for one (PVT point, corner, (dVtn, d|Vtp|) mV) from an EXPLICIT versioned artifact
    (sim/ro-vth-drift-sensitivity/, issue #254). Never falls back to the historical time-zero records:
    a missing artifact entry, a schema mismatch, or a source-record/row-hash mismatch is a hard error.
    Returns the same shape as :func:`calibration`, plus ``shift_mv`` and ``q_ring``.

    The cited source record is read under ``repo_root`` (default: this module's ``REPO_ROOT``)."""
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
    root = REPO_ROOT if repo_root is None else Path(repo_root)
    rec_path = root / "sim" / VTH_DRIFT_SLUG / "records" / f"{art['source_record']}.json"
    if not rec_path.is_file():
        raise SystemExit(f"error: calibration source record {art['source_record']} not found")
    by_key = {r["key"]: r for r in json.loads(rec_path.read_text())["rows"]}
    for deck in ("ring5", "array"):
        src = ent["source_rows"][deck]
        want_key = f"{deck}|{corner}|{float(temp):g}C|{float(vdd):g}V|{dvn:g}|{dvp:g}"
        if src["key"] != want_key:
            raise SystemExit(f"error: artifact entry {key!r} cites source row {src['key']!r}, expected {want_key!r}")
        row = by_key.get(src["key"])
        if row is None or sha256_json(row) != src["row_sha256"]:
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


def calibration(temp: float, vdd: float, corner: str, *, shift_mv=None, artifact=None,
                repo_root=None) -> dict:
    """Ring periods and sigma_k for one (PVT point, corner) from committed records.

    With ``artifact`` (a vth-drift calibration artifact path) the shift key ``shift_mv`` = (dVtn, d|Vtp|)
    in mV is REQUIRED and the historical records are not consulted; ``shift_mv`` without ``artifact`` is
    rejected too, so a shifted request can never silently run on the time-zero calibration.

    Records are read under ``repo_root`` (default: this module's ``REPO_ROOT``)."""
    if artifact is not None or shift_mv is not None:
        if artifact is None or shift_mv is None:
            raise SystemExit("error: a shifted calibration needs BOTH an explicit artifact and a shift key "
                             "(no silent time-zero fallback)")
        return calibration_from_artifact(artifact, temp, vdd, corner, shift_mv, repo_root=repo_root)
    root = REPO_ROOT if repo_root is None else Path(repo_root)
    pvt = {"temp_c": temp, "vdd_v": vdd}
    comb = _latest(root / "sim/ro-array-core-combining/records", lambda r: r.get("pvt") == pvt)
    jit = _latest(root / "sim/ro-ring-jitter-accumulation/records",
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


def stats(bits: list[int], seed_label: str) -> dict:
    est = mcv_estimate(bits)
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


def hamming_mean(seqs):
    d, m = 0, 0
    for i in range(len(seqs)):
        for j in range(i + 1, len(seqs)):
            d += sum(a != b for a, b in zip(seqs[i], seqs[j]))
            m += 1
    return d / (m * len(seqs[0])) if m else float("nan")
