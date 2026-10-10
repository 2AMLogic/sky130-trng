#!/usr/bin/env python3
"""Restart-matrix reduction (SP 800-90B restart-test shape) and its behavioural known-answer record (issue #267).

Standard library only; no simulator, no PDK.

    restart_matrix.py reduce MATRIX [--json OUT]   # reduce one R x N capture; summary on stdout, JSON to OUT ('-' = stdout)
    restart_matrix.py --emit-record                 # mint the behavioural known-answer record (18 points x 2 arms)
    restart_matrix.py --check RECORD [--entry KEY]  # replay a record (all entries, or the named ones); writes nothing

MATRIX is a text file (optionally .gz): one restart per line, each line a string of '0'/'1' characters, sample 0 = the
first sample after the restart. Lines starting with '#' are comments. Anything else fails closed (MatrixError).

The reduction contract (fixed; not a parameter)
-----------------------------------------------
- shape: R >= 1000 restarts x N >= 2048 samples per restart, rectangular, binary. Samples 0..1023 are the first
  (start-up) window, samples 1024..2047 the equal-length baseline (steady-state comparison) segment. Samples beyond
  2047, if any, enter the row and column MCV estimates but not the first/baseline comparison.
- row and column MCV: every row (one restart, all N samples) and every column (one sample index, across all R
  restarts) goes through `sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py:mcv_estimate` -- SP 800-90B 6.3.1,
  p_u_99 = min(1, p_hat + 2.576 sqrt(p_hat (1 - p_hat) / (n - 1))), H_MCV = -log2(p_u_99).
- first window vs baseline: pooled one-fraction of samples 0..1023 over all rows against that of samples
  1024..2047, two-sided two-proportion z test (pooled variance), alpha = 0.01; "not distinguishable" means
  p >= 0.01. Pooling within restarts assumes the samples are independent: this is a model diagnostic, not a
  silicon confidence statement.
- start-up health test: `digital.model.health.HealthMonitor` (the normative DR-0004 model) from reset over the first
  1024 samples of every row; a row passes when the start-up test completes with no alarm raised.
- matrix sanity verdict: PASS only when (a) every row AND every column has H_MCV >= 0.5 and (b) every row's start-up
  test passes. The first/baseline comparison is reported, not part of the verdict.

The behavioural known-answer record runs that reduction over matrices from the ONE calibrated phase-diffusion model
of `wakeup.py` (`wake_stream` + `calibration`): rings started from phase zero (deterministic arm) or uniform random
phases (stationary arm), advanced by independent white period-jitter increments. See MODEL_BOUNDARY.

Simulation-derived; provisional until silicon.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import math
import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SLUG = "wake-up-transient"
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO))

FIRST_WINDOW = 1024             # DR-0004 start-up test length = the first window
MIN_ROWS = 1000                 # spec/silicon-characterization-plan.md: 1000 independent restarts
MIN_COLS = 2 * FIRST_WINDOW     # first window + equal-length baseline (analysis choice, >= the plan's 1000+)
H_FLOOR = 0.5                   # DR-0004 H design floor (per-sample min-entropy)
ALPHA = 0.01                    # first-window vs baseline comparison
PROV = "simulation-derived; provisional until silicon"
LEG = "restart-matrix"

# behavioural record
REC_ROWS = 1000
REC_COLS = 2048
ARMS = ("deterministic", "stationary")
CORNERS = ("tt", "ss", "ff")
MASTER_SEED = 267
SEED_RULE = "int.from_bytes(sha256(f'267:{arm}:{corner}:{T:g}C:{V:g}V:{restart}').digest()[:8], 'big')"
VALUES_ARTIFACT = "restart-matrix-values.json.gz"

MODEL_BOUNDARY = (
    "Behavioural model boundary: the phase-diffusion source of sim/wake-up-transient/wakeup.py starts the four rings "
    "from phase zero after their measured start delays (deterministic arm) or from uniform random phases (stationary "
    "reference arm) and advances them with independent white period-jitter increments calibrated from committed "
    "records. It does NOT model physical supply-ramp dynamics, enable settling, sampler aperture/metastability, "
    "inter-ring coupling, 1/f noise, or silicon process behaviour. This record is simulation-derived and provisional "
    "until silicon; it validates the restart-matrix plumbing and diagnostic rules only. It is not transistor-level "
    "wake-up verification, not evidence of physical C5 compliance, and not an SP 800-90B validation. Analog wake-up "
    "and settling work is issue #216.")
POOLING_CAVEAT = ("Pooling samples within restarts assumes they are independent; the first-window vs baseline z test "
                  "is a model diagnostic, not silicon confidence evidence.")


class MatrixError(ValueError):
    """A restart matrix that the reduction refuses (malformed, ragged, undersized or non-binary)."""


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ENTROPY = None


def mcv_estimate(bits):
    """The repository's MCV estimator (raw-bit-entropy.py), loaded once."""
    global _ENTROPY
    if _ENTROPY is None:
        _ENTROPY = _load("raw_bit_entropy", REPO / "sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py")
    return _ENTROPY.mcv_estimate(bits)


# ================================================================= input
def validate_matrix(m):
    """Return (R, N) or raise MatrixError with an actionable message. Fails closed on anything not a
    rectangular list of lists of the ints 0/1 of at least MIN_ROWS x MIN_COLS."""
    if not isinstance(m, (list, tuple)):
        raise MatrixError(f"restart matrix must be a list of rows, got {type(m).__name__}")
    if len(m) == 0:
        raise MatrixError("restart matrix is empty (0 restarts)")
    for i, row in enumerate(m):
        if not isinstance(row, (list, tuple)):
            raise MatrixError(f"row {i} is a {type(row).__name__}, not a list of samples")
    n = len(m[0])
    for i, row in enumerate(m):
        if len(row) != n:
            raise MatrixError(f"ragged matrix: row {i} has {len(row)} samples, row 0 has {n}; every restart must "
                              "carry the same number of samples")
    for i, row in enumerate(m):
        if set(map(type, row)) - {int} or set(row) - {0, 1}:
            j = next(j for j, x in enumerate(row) if type(x) is not int or x not in (0, 1))
            raise MatrixError(f"non-binary sample at row {i}, column {j}: {row[j]!r} (samples must be the ints 0 or 1)")
    r = len(m)
    if r < MIN_ROWS:
        raise MatrixError(f"undersized: {r} restarts < {MIN_ROWS} required (silicon-characterization plan restart dataset)")
    if n < MIN_COLS:
        raise MatrixError(f"undersized: {n} samples per restart < {MIN_COLS} required "
                          f"({FIRST_WINDOW}-sample first window + {FIRST_WINDOW}-sample baseline)")
    return r, n


def parse_matrix_text(text):
    """One restart per line of '0'/'1' characters; '#' lines are comments. Raises MatrixError on anything else."""
    rows = []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for ln, line in enumerate(lines, 1):
        line = line.rstrip("\r")
        if line.startswith("#"):
            continue
        if not line:
            raise MatrixError(f"line {ln}: empty line (a restart with no samples)")
        bad = next((c for c in line if c not in "01"), None)
        if bad is not None:
            raise MatrixError(f"line {ln}: non-binary character {bad!r} at column {line.index(bad)} "
                              "(each line must be only '0'/'1')")
        rows.append([1 if c == "1" else 0 for c in line])
    return rows


def load_matrix(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as e:
        raise MatrixError(f"{path}: not ASCII text ({e})") from None
    return parse_matrix_text(text)


# ================================================================= statistics
def _dist(xs):
    s = sorted(xs)
    n = len(s)

    def q(p):                      # nearest-rank quantile
        return s[min(n - 1, max(0, math.ceil(p * n) - 1))]
    return {"min": s[0], "p01": q(0.01), "p05": q(0.05), "p25": q(0.25), "median": q(0.5),
            "mean": sum(s) / n, "max": s[-1]}


def two_proportion(x1, n1, x2, n2, alpha=ALPHA):
    """Two-sided two-proportion z test with pooled variance."""
    p1, p2 = x1 / n1, x2 / n2
    pp = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    if se == 0:
        z, pv = (0.0, 1.0) if p1 == p2 else (None, 0.0)
    else:
        z = (p1 - p2) / se
        pv = math.erfc(abs(z) / math.sqrt(2))
    return {"first_ones": x1, "first_n": n1, "baseline_ones": x2, "baseline_n": n2,
            "p_first": p1, "p_baseline": p2, "difference": p1 - p2, "z": z, "p_value": pv, "alpha": alpha,
            "distinguishable": pv < alpha, "test": "two-sided two-proportion z, pooled variance",
            "caveat": POOLING_CAVEAT}


def startup_health(row):
    """HealthMonitor from reset over row[:FIRST_WINDOW]: pass, first trip index, alarm class at the first trip."""
    from digital.model.health import HealthMonitor
    hm = HealthMonitor()
    first, cls, trips = None, "none", 0
    for i, b in enumerate(row[:FIRST_WINDOW]):
        if hm.update(b):
            trips += 1
            if first is None:
                first = i
                cls = "+".join(n for n, f in (("RCT", hm.alarm_rct), ("APT", hm.alarm_apt)) if f) or "startup"
    return {"passed": hm.startup_done and not hm.alarm, "first_trip_index": first, "alarm_class": cls,
            "trips": trips}


def _axis(ests, what):
    h = [e["h_hat_bits"] for e in ests]
    low = [i for i, x in enumerate(h) if x < H_FLOOR]
    i_min = min(range(len(h)), key=lambda i: (h[i], i))
    return {"count": len(h), "h_mcv_min": h[i_min], "h_mcv_min_index": i_min, "h_mcv_dist": _dist(h),
            "n_below_floor": len(low), "below_floor_indices": low,
            "ok": not low, "what": what}, {"h_mcv": h, "ones": [e["ones"] for e in ests],
                                           "p_u_99": [e["p_u_99"] for e in ests]}


def reduce_matrix(m):
    """Reduce one restart matrix. Returns (summary, values): `summary` is the deterministic, JSON-ready result
    (everything but the per-row/per-column arrays), `values` the full per-row/per-column/per-restart arrays."""
    r, n = validate_matrix(m)
    rows_s, rows_v = _axis([mcv_estimate(list(row)) for row in m], "one restart, all samples")
    cols_s, cols_v = _axis([mcv_estimate(list(col)) for col in zip(*m)], "one sample index, all restarts")
    x1 = sum(sum(row[:FIRST_WINDOW]) for row in m)
    x2 = sum(sum(row[FIRST_WINDOW:2 * FIRST_WINDOW]) for row in m)
    cmp_ = two_proportion(x1, r * FIRST_WINDOW, x2, r * FIRST_WINDOW)
    hs = [startup_health(row) for row in m]
    failed = [i for i, h in enumerate(hs) if not h["passed"]]
    classes = {}
    for h in hs:
        if h["alarm_class"] != "none":
            classes[h["alarm_class"]] = classes.get(h["alarm_class"], 0) + 1
    trips = [h["first_trip_index"] for h in hs if h["first_trip_index"] is not None]
    health = {"monitor": "digital.model.health.HealthMonitor (from reset, first 1024 samples of every row)",
              "pass_count": r - len(failed), "rows": r, "failed_rows": failed,
              "first_trip_index_min": min(trips) if trips else None, "alarm_classes": classes,
              "ok": not failed}
    verdict = {"pass": rows_s["ok"] and cols_s["ok"] and health["ok"],
               "row_mcv_ok": rows_s["ok"], "column_mcv_ok": cols_s["ok"], "startup_health_ok": health["ok"],
               "failing_rows_mcv": rows_s["below_floor_indices"], "failing_columns_mcv": cols_s["below_floor_indices"],
               "failing_rows_health": failed,
               "rule": f"PASS iff every row and column has H_MCV >= {H_FLOOR} (99 % upper-confidence MCV) and every "
                       "row's start-up health test passes"}
    summary = {"shape": {"restarts": r, "samples": n, "first_window": [0, FIRST_WINDOW - 1],
                         "baseline_window": [FIRST_WINDOW, 2 * FIRST_WINDOW - 1]},
               "estimator": "raw-bit-entropy.py:mcv_estimate (SP 800-90B 6.3.1, p_u_99, H = -log2 p_u_99)",
               "rows": rows_s, "columns": cols_s, "first_vs_baseline": cmp_, "health": health, "verdict": verdict}
    values = {"rows": rows_v, "columns": cols_v,
              "health": {"passed": [h["passed"] for h in hs], "first_trip_index": [h["first_trip_index"] for h in hs],
                         "alarm_class": [h["alarm_class"] for h in hs], "trips": [h["trips"] for h in hs]}}
    return summary, values


def canonical(obj):
    """Deterministic JSON text (sorted keys, no whitespace) -- the form hashed and replay-compared."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _idx(xs, k=8):
    return ", ".join(map(str, xs[:k])) + (f", ... ({len(xs)} total)" if len(xs) > k else "") if xs else "none"


def summary_text(s, title="restart matrix"):
    v, c, h = s["verdict"], s["first_vs_baseline"], s["health"]
    rw, cl = s["rows"], s["columns"]
    z = "n/a" if c["z"] is None else f"{c['z']:+.3f}"
    L = [f"{title}: {s['shape']['restarts']} restarts x {s['shape']['samples']} samples -- "
         f"matrix sanity verdict **{'PASS' if v['pass'] else 'FAIL'}**",
         f"- row H_MCV (99 % UB): min {rw['h_mcv_min']:.4f} (row {rw['h_mcv_min_index']}), median "
         f"{rw['h_mcv_dist']['median']:.4f}; rows below {H_FLOOR}: {rw['n_below_floor']} [{_idx(rw['below_floor_indices'])}]",
         f"- column H_MCV (99 % UB): min {cl['h_mcv_min']:.4f} (column {cl['h_mcv_min_index']}), median "
         f"{cl['h_mcv_dist']['median']:.4f}; columns below {H_FLOOR}: {cl['n_below_floor']} "
         f"[{_idx(cl['below_floor_indices'])}]",
         f"- first window vs baseline: p1 {c['p_first']:.5f} vs {c['p_baseline']:.5f}, diff {c['difference']:+.5f}, "
         f"z {z}, p {c['p_value']:.4g} -> {'DISTINGUISHABLE' if c['distinguishable'] else 'not distinguishable'} "
         f"at alpha {c['alpha']:g} (model diagnostic; pooling assumes independent samples)",
         f"- start-up health test: {h['pass_count']}/{h['rows']} rows pass; first trip index min "
         f"{h['first_trip_index_min'] if h['first_trip_index_min'] is not None else '-'}; alarm classes "
         f"{h['alarm_classes'] or 'none'}"]
    return "\n".join(L) + "\n"


# ================================================================= behavioural record
def wakeup_module():
    return _load("wakeup", HERE / "wakeup.py")


def record_points():
    """The 18 calibrated points: process corners x behavioral_raw_bit.PVT_SETS['all'] (re-counted at run time)."""
    vc = _load("behavioral_raw_bit", REPO / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py")
    return [(proc, t, v) for (t, v) in vc.PVT_SETS["all"] for proc in CORNERS]


def entry_key(proc, temp, vdd, arm):
    return f"{proc}:{temp:g}C:{vdd:g}V:{arm}"


def restart_seed(arm, proc, temp, vdd, restart):
    return int.from_bytes(hashlib.sha256(f"{MASTER_SEED}:{arm}:{proc}:{temp:g}C:{vdd:g}V:{restart}".encode())
                          .digest()[:8], "big")


CAL_KEYS = ("sigma1", "periods_s", "delays_s", "jitter_record", "combining_record", "det_record", "period_source")


def behavioral_matrix(w, cal, arm, proc, temp, vdd, rows=REC_ROWS, cols=REC_COLS):
    """rows independent restarts of the calibrated model, each from its own derived seed."""
    seeds = [restart_seed(arm, proc, temp, vdd, i) for i in range(rows)]
    tau = 0.5 * w.TS
    m = [w.wake_stream(cal, w.TS, cols, random.Random(s), tau, stationary=(arm == "stationary")) for s in seeds]
    return m, seeds


def compute_entry(w, cal, proc, temp, vdd, arm):
    m, seeds = behavioral_matrix(w, cal, arm, proc, temp, vdd)
    summary, values = reduce_matrix(m)
    values["seeds"] = seeds
    entry = {"key": entry_key(proc, temp, vdd, arm), "corner": proc, "temp_c": temp, "vdd_v": vdd, "arm": arm,
             "start": ("phase zero after the measured per-ring start delays, first sample Ts/2 after the enable"
                       if arm == "deterministic" else "uniform random ring phases (stationary reference)"),
             "seed_policy": {"master_seed": MASTER_SEED, "rule": SEED_RULE, "per_restart": True,
                             "first_seed": seeds[0], "last_seed": seeds[-1],
                             "seeds_sha256": hashlib.sha256(canonical(seeds).encode()).hexdigest(),
                             "full_list": f"{VALUES_ARTIFACT}[{entry_key(proc, temp, vdd, arm)}].seeds"},
             "calibration": {k: cal.get(k) for k in CAL_KEYS},
             "model_caveats": MODEL_BOUNDARY, "status": PROV,
             "reduction": summary,
             "values_sha256": hashlib.sha256(canonical(values).encode()).hexdigest()}
    return entry, values


def record_body(entries):
    L = ["## What this is", "",
         "The pre-silicon reference run of the restart-matrix reduction (`sim/wake-up-transient/restart_matrix.py`) that "
         "the silicon restart dataset of `spec/silicon-characterization-plan.md` C5 will go through. Each entry is "
         f"R = {REC_ROWS} independent restarts x N = {REC_COLS} samples at Ts = 20 us from the calibrated "
         "phase-diffusion model of `wakeup.py`; samples 0..1023 are the first window, 1024..2047 the baseline.", "",
         f"**Status**: {PROV}.", "", f"**Model boundary**: {MODEL_BOUNDARY}", "",
         "**Reduction**: row/column MCV with the 99 % upper-confidence convention of "
         "`raw-bit-entropy.py:mcv_estimate`; pooled first-window vs baseline two-sided two-proportion z test at "
         f"alpha = {ALPHA:g} ({POOLING_CAVEAT}); DR-0004 start-up test (`digital.model.health.HealthMonitor`, from "
         "reset) on the first 1024 samples of every restart. Matrix sanity verdict = every row and column H_MCV >= 0.5 "
         "AND every start-up test passes. A FAIL here is a defined diagnostic outcome of the model, not a forced result.",
         "",
         f"**Seeds**: one seed per restart, `{SEED_RULE}`; every seed is in the values artifact and hashed per entry "
         "(`seed_policy.seeds_sha256`).", "",
         "## Per point and arm", "",
         "| corner | T C | Vdd | arm | verdict | row H_MCV min | column H_MCV min (index) | columns < 0.5 | "
         "p1 first / baseline | z | p | start-up pass |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in entries:
        s = e["reduction"]
        c = s["first_vs_baseline"]
        z = "n/a" if c["z"] is None else f"{c['z']:+.2f}"
        L.append(f"| {e['corner']} | {e['temp_c']:g} | {e['vdd_v']:g} | {e['arm']} | "
                 f"{'PASS' if s['verdict']['pass'] else 'FAIL'} | {s['rows']['h_mcv_min']:.4f} | "
                 f"{s['columns']['h_mcv_min']:.4f} ({s['columns']['h_mcv_min_index']}) | "
                 f"{s['columns']['n_below_floor']} [{_idx(s['columns']['below_floor_indices'], 6)}] | "
                 f"{c['p_first']:.4f} / {c['p_baseline']:.4f} | {z} | {c['p_value']:.3g} | "
                 f"{s['health']['pass_count']}/{s['health']['rows']} |")
    for arm in ARMS:
        es = [e for e in entries if e["arm"] == arm]
        npass = sum(e["reduction"]["verdict"]["pass"] for e in es)
        L += ["", f"**{arm} arm**: matrix sanity verdict PASS at {npass} of {len(es)} points; "
              f"start-up tests passed {sum(e['reduction']['health']['pass_count'] for e in es)} of "
              f"{sum(e['reduction']['health']['rows'] for e in es)} restarts; first window distinguishable from "
              f"baseline (p < {ALPHA:g}) at {sum(e['reduction']['first_vs_baseline']['distinguishable'] for e in es)} "
              "points."]
    L += ["", "Reading: the deterministic arm restarts every ring from the same phase, so the earliest sample indices "
          "carry little entropy across restarts; the column-MCV rule names those indices. The DR-0004 start-up test "
          "(RCT/APT) is not designed to see that cross-restart structure. The stationary arm is the steady-state "
          "reference of the same model.", "",
          "## Per-entry summaries", ""]
    for e in entries:
        L.append(summary_text(e["reduction"], f"`{e['key']}`"))
    L += ["## Calibration provenance", "",
          "| corner | T C | Vdd | sigma_1 (s) | jitter record | combining record | period source |",
          "|---|---|---|---|---|---|---|"]
    for e in entries:
        if e["arm"] != ARMS[0]:
            continue
        c = e["calibration"]
        L.append(f"| {e['corner']} | {e['temp_c']:g} | {e['vdd_v']:g} | {c['sigma1']:.4e} | {c['jitter_record']} | "
                 f"{c['combining_record']} | {c['period_source']} |")
    L += ["", "Replay: `python3 sim/wake-up-transient/restart_matrix.py --check sim/wake-up-transient/records/<id>.json` "
          "regenerates every matrix from the recorded calibration values and seeds and compares the summaries, the "
          "full-values hash and this body; it writes nothing.", ""]
    return "\n".join(L) + "\n"


CLAIM = ("Restart-matrix reduction (SP 800-90B restart-test shape; issue #267) exercised on behavioural known-answer "
         "matrices: 1000 restarts x 2048 samples at each of the 18 calibrated PVT points, deterministic-start and "
         "stationary-start arms reported separately; row/column 99 % MCV, first-window vs baseline two-proportion z "
         "test, DR-0004 start-up test per restart, matrix sanity verdict. Validates the analysis path only; "
         "simulation-derived, provisional until silicon")


def compute_record(log=True):
    w = wakeup_module()
    pts = record_points()
    if len(pts) != 18:
        raise SystemExit(f"error: expected 18 calibrated points, the tree declares {len(pts)}")
    entries, values = [], {}
    for proc, temp, vdd in pts:
        cal = w.calibration(temp, vdd, proc)
        for arm in ARMS:
            e, v = compute_entry(w, cal, proc, temp, vdd, arm)
            entries.append(e)
            values[e["key"]] = v
            if log:
                print(e["key"], "PASS" if e["reduction"]["verdict"]["pass"] else "FAIL", file=sys.stderr)
    return entries, values


def emit_record():
    import time
    from evidence_record import mint_behavioral_record
    t0 = time.time()
    entries, values = compute_record()
    runtime = time.time() - t0
    body = record_body(entries)
    with tempfile.TemporaryDirectory() as td:
        art = Path(td) / VALUES_ARTIFACT
        art.write_bytes(gzip.compress(canonical(values).encode(), compresslevel=9, mtime=0))
        rid = mint_behavioral_record(
            REPO, SLUG, CLAIM, body,
            {"leg": LEG, "status": PROV, "claim": CLAIM, "model_boundary": MODEL_BOUNDARY,
             "contract": {"rows": REC_ROWS, "cols": REC_COLS, "first_window": FIRST_WINDOW, "min_rows": MIN_ROWS,
                          "min_cols": MIN_COLS, "h_floor": H_FLOOR, "alpha": ALPHA, "ts_s": 20e-6},
             "points": len(entries) // len(ARMS), "arms": list(ARMS),
             "seed_policy": {"master_seed": MASTER_SEED, "rule": SEED_RULE},
             "values_artifact": VALUES_ARTIFACT, "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
             "generation_runtime_s": round(runtime, 1), "entries": entries,
             "model": "sim/wake-up-transient/wakeup.py wake_stream/calibration (phase-diffusion model of "
                      "sim/raw-bit-volume-campaign/)"},
            level="behavioral (calibrated on transistor records)",
            seeds={"master_seed": MASTER_SEED, "rule": SEED_RULE, "per_restart": "every seed listed in the values artifact"},
            artifacts=[art], tools={"script": "sim/wake-up-transient/restart_matrix.py --emit-record"})
    print(rid)
    print(f"runtime {runtime:.1f} s", file=sys.stderr)
    return rid


def check(path, only=None, provenance=True):
    """Replay a record from its recorded calibration values and seed rule. Writes nothing. Returns 0 on match."""
    path = Path(path)
    rec = json.loads(path.read_text())
    if rec.get("leg") != LEG:
        raise SystemExit(f"{path}: not a {LEG} record")
    w = wakeup_module()
    art = path.parent.parent / "runs" / rec["record_id"] / VALUES_ARTIFACT
    stored = json.loads(gzip.decompress(art.read_bytes()))
    ok = True
    recomputed = []
    for e in rec["entries"]:
        if only and e["key"] not in only:
            continue
        cal = dict(e["calibration"])
        ne, nv = compute_entry(w, cal, e["corner"], e["temp_c"], e["vdd_v"], e["arm"])
        same = (canonical(ne) == canonical(e) and canonical(nv) == canonical(stored[e["key"]]))
        ok &= same
        recomputed.append(ne)
        print("replay", "MATCHES" if same else "DIFFERS", e["key"])
    if only:
        missing = set(only) - {e["key"] for e in recomputed}
        if missing:
            print("unknown entries:", sorted(missing))
            ok = False
    else:
        body = record_body(recomputed)
        same_body = (hashlib.sha256(body.encode()).hexdigest() == rec["body_sha256"]
                     and body.rstrip("\n") in path.with_suffix(".md").read_text())
        print("replay", "MATCHES" if same_body else "DIFFERS", "record body (markdown summary)")
        ok &= same_body
        if provenance:
            drift = []
            for e in rec["entries"]:
                if e["arm"] == ARMS[0]:
                    cur = w.calibration(e["temp_c"], e["vdd_v"], e["corner"])
                    if canonical({k: cur.get(k) for k in CAL_KEYS}) != canonical(e["calibration"]):
                        drift.append(e["key"])
            print("calibration provenance:", "current tree reproduces every recorded calibration" if not drift else
                  f"current tree calibration DIFFERS at {drift} (newer calibration records; the replay above used the "
                  "recorded values)")
    print("replay", "MATCHES" if ok else "DIFFERS", path)
    return 0 if ok else 1


def main(a):
    if len(a) >= 2 and a[0] == "reduce":
        out = None
        if len(a) == 4 and a[2] == "--json":
            out = a[3]
        elif len(a) != 2:
            print(__doc__)
            return 2
        try:
            s, v = reduce_matrix(load_matrix(a[1]))
        except MatrixError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        sys.stdout.write(summary_text(s, a[1]) if out != "-" else "")
        if out:
            txt = json.dumps({"summary": s, "values": v}, sort_keys=True, indent=1, allow_nan=False) + "\n"
            if out == "-":
                sys.stdout.write(txt)
            else:
                Path(out).write_text(txt)
        return 0 if s["verdict"]["pass"] else 1
    if a == ["--emit-record"]:
        emit_record()
        return 0
    if len(a) >= 2 and a[0] == "--check":
        only = [a[i + 1] for i in range(2, len(a) - 1, 2) if a[i] == "--entry"]
        return check(a[1], only or None)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
