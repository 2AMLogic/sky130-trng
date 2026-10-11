#!/usr/bin/env python3
"""Seeded transistor raw-bit cross-check at calibrated NON-NOMINAL PVT (issue #289).

Extends the 27 C / 1.8 V short-window cross-check of `behavioral_raw_bit.py` (issue #188)
to the calibrated -40 C and 125 C points.  Same #21 testbench (unmodified), same sampler,
same Ts = 100 ns / 24-sample window, same 99 % model-band decision rule.  The bands are
the ones the nominal cross-check uses and are NOT retuned after seeing results.

Scope: a short-window model check.  It is NOT a million-bit transistor run and NOT a
validation at DR-0003's Ts = 20 us (the 50 kbps operating point stays an extrapolation).
Provisional, simulation-derived, not silicon.

Inputs (committed, append-only): `transistor/pvt/<key>.manifest.json` (declared identity of
a request: process list, temperature, supply, seed, Ts, netlist/request hashes, written by
`make-requests.py --pvt`) and `transistor/pvt/<key>.klt-sim.json` (the `klt sim` batch
response).  `<key>` = `pvt_<T>C_<V>V_Ts<ns>ns_seed<S>`.

Every unit is reduced to one row per process corner with an explicit status; nothing is
dropped.  Cells are keyed by (process, temp, supply) so distinct PVT points can never be
pooled.  `matrix_complete` is true only when EVERY declared (point, process, seed) unit is
usable; anything else is reported as incomplete with the reason per row.

    transistor_pvt_crosscheck.py                       # print the reduction
    transistor_pvt_crosscheck.py --ingest REQDIR       # copy resp.json + manifest.json of each unit
                                                       #   (no overwrite) into transistor/pvt/
    transistor_pvt_crosscheck.py --emit-record         # mint an append-only record
    transistor_pvt_crosscheck.py --check RECORD_JSON   # replay: exit 1 if the reduction differs
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_behavioral_record  # noqa: E402

_spec = importlib.util.spec_from_file_location("behavioral_raw_bit", HERE / "behavioral_raw_bit.py")
brb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brb)
rbe = brb.rbe

SLUG = brb.SLUG
PVT_DIR = HERE / "transistor" / "pvt"
MANIFEST_SCHEMA = "raw-bit-pvt-request/1"

# Bounded matrix, declared BEFORE any run (issue #289): the calibrated non-nominal points.
DECLARED_POINTS = ((-40.0, 1.62), (-40.0, 1.98), (125.0, 1.62), (125.0, 1.8), (125.0, 1.98))
DECLARED_SEEDS = (101, 102, 103, 104)
CORNERS = brb.CORNERS
TS_NS = 100
MIN_SEEDS = 4            # usable independent seeds required for a Hamming comparison (6 pairs)
MIN_SAMPLES = 23         # same as the nominal cross-check (ss loses its start-up sample)
SUPPLY_TOL = 0.05        # the highest valid-high level must be within 5 % of the declared supply
RAIL_TOL = 0.20          # a sample must be within 20 % of vdd of a rail, else indeterminate
NBITS = 24


def pvt_key(temp, vdd, seed, ts_ns=TS_NS):
    return f"pvt_{temp:g}C_{vdd:g}V_Ts{ts_ns}ns_seed{seed}"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ----------------------------------------------------------------------- load
def load_units(pvt_dir: Path = PVT_DIR) -> list[dict]:
    """One unit per manifest, plus a unit per response that has no manifest. Never raises on
    a bad file: the problem is attached to the unit and surfaces as row statuses."""
    units, seen = [], {}
    pvt_dir = Path(pvt_dir)
    names = set()
    if pvt_dir.is_dir():
        for p in pvt_dir.glob("*.manifest.json"):
            names.add(p.name[:-len(".manifest.json")])
        for p in pvt_dir.glob("*.klt-sim.json"):
            names.add(p.name[:-len(".klt-sim.json")])
    for name in sorted(names):
        mp, rp = pvt_dir / f"{name}.manifest.json", pvt_dir / f"{name}.klt-sim.json"
        u = {"name": name, "manifest": None, "resp": None, "problems": [],
             "manifest_sha256": None, "response_sha256": None}
        if mp.is_file():
            u["manifest_sha256"] = sha256_file(mp)
            try:
                u["manifest"] = json.loads(mp.read_text())
            except ValueError:
                u["problems"].append("bad_manifest: not JSON")
        else:
            u["problems"].append("manifest_missing")
        if rp.is_file():
            u["response_sha256"] = sha256_file(rp)
            try:
                u["resp"] = json.loads(rp.read_text())
            except ValueError:
                u["problems"].append("bad_response: not JSON")
        else:
            u["problems"].append("response_missing")
        m = u["manifest"]
        if m is not None:
            try:
                ok = (m.get("schema") == MANIFEST_SCHEMA
                      and m["key"] == name
                      and m["key"] == pvt_key(m["temp_c"], m["vdd_v"], m["seed"], m["ts_ns"]))
            except (KeyError, TypeError, ValueError):
                ok = False
            if not ok:
                u["problems"].append("bad_manifest: schema/key does not match its own PVT/seed/Ts fields or file name")
            else:
                ident = (m["temp_c"], m["vdd_v"], m["seed"], m["ts_ns"])
                if ident in seen:
                    u["problems"].append(f"collision: same (T,V,seed,Ts) as {seen[ident]}")
                    for o in units:
                        if o["name"] == seen[ident] and not any(x.startswith("collision") for x in o["problems"]):
                            o["problems"].append(f"collision: same (T,V,seed,Ts) as {name}")
                else:
                    seen[ident] = name
        units.append(u)
    return units


# ------------------------------------------------------------------- classify
def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def classify(unit: dict, process: str) -> dict:
    """Row for one (unit, process). status 'ok' only if every check passes; otherwise a
    machine-readable reason. `bits` is present only for 'ok' rows."""
    m, r = unit["manifest"], unit["resp"]
    row = {"unit": unit["name"], "process": process,
           "temp_c": m.get("temp_c") if m else None, "vdd_v": m.get("vdd_v") if m else None,
           "seed": m.get("seed") if m else None, "ts_ns": m.get("ts_ns") if m else None,
           "status": None, "reason": "", "n_total": 0, "n_invalid": 0, "n_indeterminate": 0,
           "job_id": None, "manifest_sha256": unit["manifest_sha256"], "response_sha256": unit["response_sha256"]}

    def bad(status, reason):
        row["status"], row["reason"] = status, reason
        return row

    if unit["problems"]:
        return bad("bad_unit", "; ".join(unit["problems"]))
    env = r.get("environment", {}) or {}
    remote = env.get("remote") or {}
    row["job_id"] = remote.get("job_id")
    row["netlist_sha256"] = env.get("netlist_sha256")
    row["models_lib_sha256"] = env.get("models_lib_sha256")
    row["engine_version"] = env.get("engine_version")
    if remote and (remote.get("state") not in (None, "done") or str(remote.get("exit_code", "0")) != "0"):
        return bad("tool_fail", f"batch job state={remote.get('state')} exit_code={remote.get('exit_code')}")
    if env.get("netlist_sha256") != m.get("netlist_sha256"):
        return bad("pvt_mismatch", "response netlist_sha256 differs from the request manifest "
                   "(response belongs to a different PVT/seed/deck)")
    cs = [c for c in r.get("corners", []) if c.get("process") == process]
    if len(cs) != 1:
        return bad("corner_missing" if not cs else "corner_duplicated",
                   f"{len(cs)} responses for process {process}")
    c = cs[0]
    if not _num(c.get("temperature_c")) or abs(c["temperature_c"] - m["temp_c"]) > 1e-9:
        return bad("pvt_mismatch", f"response temperature_c={c.get('temperature_c')} != manifest {m['temp_c']}")
    if c.get("status") != "pass":
        return bad("tool_fail", f"corner status={c.get('status')}")
    meas = {x.get("name"): x.get("value") for x in c.get("measurements", [])}
    names = [f"bit{k}" for k in range(NBITS)] + [f"valid{k}" for k in range(NBITS)]
    miss = [n for n in names if not _num(meas.get(n))]
    if miss:
        return bad("measurement_missing", f"{len(miss)} bit/valid measurements absent or non-numeric (e.g. {miss[0]})")
    vdd = float(m["vdd_v"])
    hi = max(meas[f"valid{k}"] for k in range(NBITS))
    if abs(hi - vdd) > SUPPLY_TOL * vdd:
        return bad("supply_mismatch", f"highest valid level {hi:.3f} V is not within "
                   f"{SUPPLY_TOL:.0%} of the declared supply {vdd:g} V")
    thr = 0.5 * vdd
    bits, invalid, indet = [], 0, 0
    for k in range(NBITS):
        b, v = meas[f"bit{k}"], meas[f"valid{k}"]
        if any(min(abs(x), abs(x - vdd)) > RAIL_TOL * vdd for x in (b, v)):
            indet += 1
            continue
        if v <= thr:
            invalid += 1
            continue
        bits.append(1 if b > thr else 0)
    row.update(n_total=NBITS, n_invalid=invalid, n_indeterminate=indet)
    if len(bits) < MIN_SAMPLES:
        return bad("too_few_valid", f"{len(bits)} usable samples < {MIN_SAMPLES}")
    row["status"], row["bits"] = "ok", bits
    return row


# --------------------------------------------------------------------- reduce
def reduce_units(units, points=DECLARED_POINTS, seeds=DECLARED_SEEDS, corners=CORNERS,
                 ensemble: int = brb.ENSEMBLE) -> dict:
    rows = []
    for u in units:
        procs = (u["manifest"] or {}).get("processes") or list(corners)
        for p in procs:
            rows.append(classify(u, p))
    index = {}
    for r in rows:
        if r["status"] == "ok":
            index.setdefault((r["process"], r["temp_c"], r["vdd_v"]), []).append(r)
    undeclared = sorted({(r["temp_c"], r["vdd_v"]) for r in rows if r["temp_c"] is not None}
                        - {(t, v) for t, v in points})
    cells = []
    for (t, v) in points:
        for corner in corners:
            cell = {"corner": corner, "temp_c": t, "vdd_v": v, "declared_seeds": list(seeds)}
            mine = [r for r in rows if r["process"] == corner and r["temp_c"] == t and r["vdd_v"] == v]
            ok = sorted(index.get((corner, t, v), []), key=lambda r: r["seed"])
            ok = [r for r in ok if r["seed"] in seeds]
            have = {r["seed"] for r in ok}
            cell["usable_seeds"] = sorted(have)
            cell["missing_seeds"] = [s for s in seeds if s not in have]
            cell["unsuccessful"] = [{k: r[k] for k in ("unit", "seed", "status", "reason", "job_id")}
                                    for r in mine if r["status"] != "ok"]
            cell["n_invalid_samples"] = sum(r["n_invalid"] for r in mine)
            cell["n_indeterminate_samples"] = sum(r["n_indeterminate"] for r in mine)
            cell["sample_counts"] = {str(r["seed"]): len(r["bits"]) for r in ok}
            try:
                cal = brb.calibration(t, v, corner)
            except SystemExit as e:
                cell.update(status="no_calibration", reason=str(e))
                cells.append(cell)
                continue
            if not ok:
                cell["status"] = "no_data"
                cells.append(cell)
                continue
            W = NBITS if all(len(r["bits"]) == NBITS for r in ok) else MIN_SAMPLES
            seqs = [r["bits"][-W:] for r in ok]
            tp = [max(sum(b), W - sum(b)) / W for b in seqs]
            n = len(seqs)
            rng = random.Random(brb.sub_seed(f"xchkpvt:{corner}:{t:g}:{v:g}:{n}:{W}"))
            phats, hams = [], []
            for _ in range(ensemble):
                per = [T * (1 + rng.gauss(0, brb.PERIOD_REL_UNC)) for T in cal["periods_s"]]
                ens = [brb.stream(per, cal["sigma"][1], brb.TS_TRANSISTOR_LEVEL, NBITS, rng)[NBITS - W:]
                       for _ in range(max(n, 2))]
                phats.append([max(sum(s), W - sum(s)) / W for s in ens])
                hams.append(brb.hamming_mean(ens))
            flat = [x for rr in phats for x in rr]
            plo, phi = brb._quantile(flat, 0.005), brb._quantile(flat, 0.995)
            cell.update(window=W, n_sequences=n, transistor_phat=tp, phat_band99=[plo, phi],
                        phat_model_median=brb._quantile(flat, 0.5),
                        phat_inside=all(plo <= x <= phi for x in tp),
                        calibration_records={"combining": cal["combining_record"], "jitter": cal["jitter_record"]})
            if n >= MIN_SEEDS:
                th = brb.hamming_mean(seqs)
                hlo, hhi = brb._quantile(hams, 0.005), brb._quantile(hams, 0.995)
                cell.update(hamming=th, hamming_band99=[hlo, hhi], hamming_model_median=brb._quantile(hams, 0.5),
                            hamming_inside=hlo <= th <= hhi)
            else:
                cell.update(hamming=None, hamming_inside=None,
                            hamming_note=f"{n} usable seeds < {MIN_SEEDS}: no Hamming comparison made")
            full = not cell["missing_seeds"]
            if not full:
                cell["status"] = "incomplete" if n >= MIN_SEEDS else "insufficient_seeds"
            else:
                cell["status"] = "inside" if (cell["phat_inside"] and cell["hamming_inside"]) else "outside"
            cells.append(cell)
    complete = bool(cells) and all(c["status"] in ("inside", "outside") for c in cells) and not undeclared
    failing = [c for c in cells if c["status"] == "outside"]
    return {"rows": [{k: v for k, v in r.items() if k != "bits"} for r in rows], "cells": cells,
            "matrix_complete": complete, "undeclared_points": undeclared,
            "n_units": len(units), "n_rows_unsuccessful": sum(r["status"] != "ok" for r in rows),
            "failing_cells": [(c["corner"], c["temp_c"], c["vdd_v"]) for c in failing],
            "declared": {"points": [list(p) for p in points], "seeds": list(seeds), "corners": list(corners),
                         "ts_ns": TS_NS, "min_seeds": MIN_SEEDS, "min_samples": MIN_SAMPLES,
                         "supply_tol": SUPPLY_TOL, "rail_tol": RAIL_TOL, "band": "99% model ensemble (as #188)"}}


# --------------------------------------------------------------------- render
def _band(b):
    return f"[{b[0]:.3f}, {b[1]:.3f}]"


def render(red: dict) -> str:
    L = ["## Seeded transistor raw-bit cross-check at non-nominal PVT (issue #289)", "",
         "`level: behavioral model vs transistor`. Short-window (24 samples, Ts = 100 ns) check of the calibrated "
         "model against the #21 testbench run through `klt sim` batch. NOT a million-bit transistor run and NOT a "
         "validation at DR-0003's Ts = 20 us: the 50 kbps operating point remains an extrapolation. Bands are the "
         "#188 99 % model-ensemble bands, not retuned.", ""]
    d = red["declared"]
    L.append(f"Declared matrix: {len(d['points'])} PVT points x {len(d['corners'])} process corners x "
             f"{len(d['seeds'])} seeds ({', '.join(map(str, d['seeds']))}); Hamming needs >= {d['min_seeds']} usable seeds.")
    L.append("")
    L.append(f"**Matrix status: {'COMPLETE' if red['matrix_complete'] else 'INCOMPLETE'}** "
             f"({red['n_units']} units, {red['n_rows_unsuccessful']} unsuccessful rows, "
             f"{len(red['failing_cells'])} failing cells).")
    if red["undeclared_points"]:
        L.append(f"Undeclared PVT points present (matrix cannot be complete): {red['undeclared_points']}")
    L += ["", "| process | T (C) | Vdd (V) | usable seeds | missing seeds | status | transistor p_hat | p_hat 99% band | Hamming | Hamming 99% band |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for c in red["cells"]:
        tp = ", ".join(f"{x:.3f}" for x in c.get("transistor_phat", [])) or "-"
        pb = _band(c["phat_band99"]) if "phat_band99" in c else "-"
        h = f"{c['hamming']:.4f}" if c.get("hamming") is not None else "-"
        hb = _band(c["hamming_band99"]) if c.get("hamming") is not None else "-"
        L.append(f"| {c['corner']} | {c['temp_c']:g} | {c['vdd_v']:g} | {c['usable_seeds']} | {c['missing_seeds']} | "
                 f"{c['status']} | {tp} | {pb} | {h} | {hb} |")
    L += ["", "### Unsuccessful rows (every one listed)", ""]
    bad = [r for r in red["rows"] if r["status"] != "ok"]
    if not bad:
        L.append("(none)")
    for r in bad:
        L.append(f"- `{r['unit']}` {r['process']}: **{r['status']}** {r['reason']} (job `{r['job_id']}`)")
    L += ["", "### Input provenance", ""]
    for r in red["rows"]:
        if r["process"] == CORNERS[0] or r["status"] == "bad_unit":
            L.append(f"- `{r['unit']}`: manifest `{(r['manifest_sha256'] or '-')[:12]}`, response "
                     f"`{(r['response_sha256'] or '-')[:12]}`, netlist `{(r.get('netlist_sha256') or '-')[:12]}`, "
                     f"models_lib `{(r.get('models_lib_sha256') or '-')[:12]}`, job `{r['job_id']}`")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------- main
def ingest(reqdir: Path, pvt_dir: Path = PVT_DIR) -> int:
    """Copy each unit's manifest.json + resp.json (append-only: refuses to overwrite)."""
    n = 0
    pvt_dir.mkdir(parents=True, exist_ok=True)
    for d in sorted(Path(reqdir).glob("pvt_*")):
        man, resp = d / "manifest.json", d / "resp.json"
        if not man.is_file() or not resp.is_file() or resp.stat().st_size == 0:
            print(f"skip {d.name}: no manifest/response")
            continue
        for src, suffix in ((man, ".manifest.json"), (resp, ".klt-sim.json")):
            dst = pvt_dir / f"{d.name}{suffix}"
            if dst.exists():
                raise SystemExit(f"error: {dst} exists; records are append-only (mint a new key, never overwrite)")
        shutil.copyfile(man, pvt_dir / f"{d.name}.manifest.json")
        shutil.copyfile(resp, pvt_dir / f"{d.name}.klt-sim.json")
        n += 1
    print(f"ingested {n} units")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ingest", metavar="REQDIR")
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--check", metavar="RECORD_JSON")
    ap.add_argument("--author", default="loom-builder@sky130-trng")
    a = ap.parse_args(argv)
    if a.ingest:
        return ingest(Path(a.ingest))
    red = reduce_units(load_units())
    if a.check:
        rec = json.loads(Path(a.check).read_text())
        same = rec.get("reduction") == json.loads(json.dumps(red))
        print("OK   reduction replays identically" if same else "FAIL reduction differs from the record")
        return 0 if same else 1
    body = render(red)
    print(body)
    if not a.emit_record:
        return 0
    if red["n_units"] == 0:
        raise SystemExit("error: no transistor/pvt units committed; refusing to mint an empty record")
    status = "complete" if red["matrix_complete"] else "INCOMPLETE"
    mint_behavioral_record(
        REPO_ROOT, SLUG,
        f"seeded 24-sample transistor raw-bit cross-check of the calibrated model at non-nominal PVT "
        f"(-40/125 C) at Ts = 100 ns; matrix {status}; issue #289",
        body, {"reduction": json.loads(json.dumps(red))},
        level="behavioral model vs transistor (derived)",
        seeds={"declared": list(DECLARED_SEEDS), "model_ensemble": "sha256(master:xchkpvt:...)[:8]"},
        tools={"reducer": "sim/raw-bit-volume-campaign/transistor_pvt_crosscheck.py",
               "requests": "sim/raw-bit-volume-campaign/make-requests.py --pvt"},
        author=a.author)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
