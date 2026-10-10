#!/usr/bin/env python3
"""Matched-seed behavioral replay of the Vth-shift calibration (issue #254).

    behavioral_replay.py [--artifact PATH] [--nbits N] [--emit-record]
    behavioral_replay.py --regenerate-check RECORD.json

`level: behavioral`. NOT a fresh transistor simulation and NOT silicon evidence. For every
common-mode grid point it feeds the zero-shift and the shifted entry of the vth-drift
calibration artifact (explicitly, via `behavioral_raw_bit.calibration(..., artifact=, shift_mv=)`;
there is no fallback to the historical time-zero records) to the EXISTING behavioral generator
`sim/raw-bit-volume-campaign/behavioral_raw_bit.py` with IDENTICAL seeds and sample counts, then
runs that campaign's existing reduction (`stats()` -> `raw-bit-entropy.py` `mcv_estimate`, context
predictor) and reports the movement relative to the matched zero-shift stream as MODEL output.

The stream seed label deliberately does not contain the shift, so the zero and shifted streams
share one `random.Random` seed and one length; only the calibration differs.

This is a sensitivity bound, not a lifetime prediction. Provisional until silicon.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUGDIR = HERE.parent
REPO = SLUGDIR.parents[1]
sys.path.insert(0, str(SLUGDIR))
sys.path.insert(0, str(REPO / "sim" / "bin"))
import campaign as C  # noqa: E402
from evidence_record import mint_behavioral_record  # noqa: E402

_s = importlib.util.spec_from_file_location("behavioral_raw_bit", REPO / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py")
brb = importlib.util.module_from_spec(_s)
_s.loader.exec_module(brb)

SLUG = C.SLUG
NBITS = 1 << 17                 # same per-stream size as the #188 record
TS = brb.TS_DR0003              # DR-0003's literal 20 us sample clock
SENTENCE = "This is a sensitivity bound, not a lifetime prediction."


def label(corner, temp, vdd) -> str:
    return f"vthdrift:stream:{corner}:{temp:g}C:{vdd:g}V:Ts20us"          # NO shift in the label: matched seeds


def latest_artifact() -> Path:
    c = sorted(glob.glob(str(SLUGDIR / "records" / "*.calibration.json")))
    if not c:
        raise SystemExit("error: no calibration artifact under records/")
    return Path(c[-1])


def one_stream(art: Path, corner, temp, vdd, shift_mv, nbits, ts=TS):
    cal = brb.calibration(temp, vdd, corner, shift_mv=shift_mv, artifact=art)
    lab = label(corner, temp, vdd)
    seed = brb.sub_seed(lab)
    bits = brb.stream(cal["periods_s"], cal["sigma"][1], ts, nbits, random.Random(seed))
    return bits, cal, lab, seed


def run(art: Path, nbits: int):
    rows = []
    for c in C.PROCESSES:
        for t in C.TEMPS:
            for v in C.VDDS:
                zero = None
                for s in C.CM_SHIFTS_MV:
                    bits, cal, lab, seed = one_stream(art, c, t, v, (s, s), nbits)
                    st = brb.stats(bits, lab + f":{s}")
                    row = {"corner": c, "temp_c": t, "vdd_v": v, "shift_mv": [s, s], "n": nbits, "ts_s": TS, "seed_label": lab, "seed": seed,
                           "sha256_hex": hashlib.sha256(brb.pack_hex(bits).encode()).hexdigest(),
                           "calibration": {k: cal[k] for k in ("periods_s", "sigma", "q_ring", "combining_record", "combining_job_id", "jitter_job_id")},
                           **{k: st[k] for k in ("p_hat", "p_u_99", "h_hat_bits", "z_monobit", "autocorr", "best_context_len",
                                                 "best_context_acc", "best_context_acc_shuffled_null", "h_context_min_bits")}}
                    if s == 0:
                        zero = row
                    se = math.sqrt(2) * 0.5 / math.sqrt(nbits)             # matched-stream difference, p near 0.5
                    row["delta_vs_zero"] = {"h_hat_bits": row["h_hat_bits"] - zero["h_hat_bits"], "p_hat": row["p_hat"] - zero["p_hat"],
                                            "h_context_min_bits": row["h_context_min_bits"] - zero["h_context_min_bits"],
                                            "p_hat_z": (row["p_hat"] - zero["p_hat"]) / se, "p_hat_se": se}
                    rows.append(row)
    return rows


def body(rows, art: Path, art_sha: str, nbits):
    L = ["## What this is", "",
         f"{len(rows)} behavioral raw-bit streams of {nbits} bits (Ts = 20 us, DR-0003's literal sample clock), one per (process x PVT x common-mode "
         "shift 0/20/40/60 mV). **`level: behavioral` -- not a transistor simulation, not silicon evidence.** Each shifted stream uses the "
         "shifted entry of the vth-drift calibration artifact "
         f"(`{art.relative_to(REPO)}`, sha256 `{art_sha}`) and is generated with the SAME seed and sample count as its matched zero-shift stream "
         "(the seed label carries no shift), then reduced with the existing `behavioral_raw_bit.stats()` (MCV via `raw-bit-entropy.py`, plus the "
         "context predictor). Reported movement is relative to the matched zero-shift stream.", "",
         SENTENCE, "",
         "## Model limits", "",
         "- Inherits every limit of `sim/raw-bit-volume-campaign/` (white period jitter, no XOR-tree pulse loss, no sampler aperture, no coupling, "
         "no 1/f, no supply noise). Calibration inputs are single-seed 20-period `sigma_1` (~16 % 1-sigma) and the ring periods of the shifted array.",
         "- At Ts = 20 us every ring accumulates ~0.1 cycle of phase noise per sample, so the model's marginal bit is near-unbiased for any "
         "calibration in this range; a null movement here is a property of the model at DR-0003's Ts, **not** evidence that silicon is insensitive to threshold drift.",
         f"- MCV resolution at n = {nbits}: SE(p_hat difference between matched streams) = {math.sqrt(2)*0.5/math.sqrt(nbits):.4f}.",
         "- Streams are not stored; each is reproduced by `behavioral_replay.py --regenerate-check` (sha256 per stream in the JSON).", "",
         "## Movement vs the matched zero-shift stream", "",
         "| corner | T (C) | Vdd | shift (mV) | p_hat | H_MCV | dH_MCV | dp_hat (z) | H_ctx | dH_ctx |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        d = r["delta_vs_zero"]
        L.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | {r['shift_mv'][0]} | {r['p_hat']:.4f} | {r['h_hat_bits']:.4f} | "
                 f"{d['h_hat_bits']:+.4f} | {d['p_hat']:+.4f} ({d['p_hat_z']:+.1f}) | {r['h_context_min_bits']:.4f} | {d['h_context_min_bits']:+.4f} |")
    sh = [r for r in rows if r["shift_mv"][0] != 0]
    mz = max(abs(r["delta_vs_zero"]["p_hat_z"]) for r in sh)
    L += ["", f"Largest |z| of the matched p_hat difference over the {len(sh)} shifted streams: {mz:.2f} "
          f"(minimum H_MCV over all streams {min(r['h_hat_bits'] for r in rows):.4f}; minimum H_ctx {min(r['h_context_min_bits'] for r in rows):.4f}).", ""]
    L += ["## Serial structure the marginal MCV does not see (context predictor vs its shuffled null)", "",
          "`excess` = best context-predictor accuracy minus its accuracy on the shuffled stream at the same context length (c = 0..8). A "
          "shuffled-null excess above ~0.02 at n = 131072 is serial predictability in the model stream; MCV on the marginal cannot see it "
          "(`raw-bit-volume-campaign/` caveat).", "",
          "| shift (mV) | streams | max excess | mean excess | streams with excess > 0.05 | min H_ctx |", "|---|---|---|---|---|---|"]
    by_shift = {}
    for r in rows:
        by_shift.setdefault(r["shift_mv"][0], []).append(r)
    ctx = {}
    for k_, rs_ in by_shift.items():
        ex = [r["best_context_acc"] - r["best_context_acc_shuffled_null"] for r in rs_]
        ctx[str(k_)] = {"n": len(rs_), "max_excess": max(ex), "mean_excess": sum(ex) / len(ex),
                        "n_gt_0p05": sum(e > 0.05 for e in ex), "min_h_ctx": min(r["h_context_min_bits"] for r in rs_)}
        L.append(f"| {k_} | {len(rs_)} | {max(ex):.3f} | {sum(ex)/len(ex):.3f} | {sum(e > 0.05 for e in ex)} | {min(r['h_context_min_bits'] for r in rs_):.4f} |")
    L += ["", "This is a model output on the calibration inputs, including single-seed `sigma_1` realization noise; it is reported, not tuned, and no "
          "threshold is derived from it. It does not change DR-0003/DR-0004 and is not a silicon measurement.", ""]
    return "\n".join(L), {"context_excess_by_shift": ctx, "max_abs_z_p_hat": mz, "min_h_mcv": min(r["h_hat_bits"] for r in rows),
                          "min_h_ctx": min(r["h_context_min_bits"] for r in rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact")
    ap.add_argument("--nbits", type=int, default=NBITS)
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--regenerate-check")
    a = ap.parse_args(argv)
    if a.regenerate_check:
        rec = json.loads(Path(a.regenerate_check).read_text())
        art = REPO / rec["calibration_artifact"]["path"]
        if hashlib.sha256(art.read_bytes()).hexdigest() != rec["calibration_artifact"]["file_sha256"]:
            print("FAIL calibration artifact bytes changed")
            return 1
        bad = 0
        for r in rec["streams"]:
            bits, _, _, _ = one_stream(art, r["corner"], r["temp_c"], r["vdd_v"], tuple(r["shift_mv"]), r["n"])
            ok = hashlib.sha256(brb.pack_hex(bits).encode()).hexdigest() == r["sha256_hex"]
            bad += not ok
            if not ok:
                print("FAIL", r["corner"], r["temp_c"], r["vdd_v"], r["shift_mv"])
        print("replay", "MATCHES" if not bad else f"DIFFERS ({bad})", len(rec["streams"]), "streams")
        return 1 if bad else 0
    art = Path(a.artifact) if a.artifact else latest_artifact()
    rows = run(art, a.nbits)
    art_sha = hashlib.sha256(art.read_bytes()).hexdigest()
    md, summ = body(rows, art, art_sha, a.nbits)
    print(md)
    if not a.emit_record:
        return 0
    src = json.loads(art.read_text())["source_record"]
    rid = mint_behavioral_record(
        REPO, SLUG,
        "matched-seed behavioral replay of the zero-shift and Vth-shifted calibration through the existing raw-bit min-entropy reduction "
        "(model output, not silicon evidence). " + SENTENCE,
        md + f"\n\nSource sensitivity record: `{src}`. Calibration artifact: `{art.relative_to(REPO)}`.\n",
        {"kind": "behavioral-replay", "streams": rows, "summary": summ, "source_record": src,
         "calibration_artifact": {"path": str(art.relative_to(REPO)), "file_sha256": art_sha, "schema": brb.VTH_DRIFT_SCHEMA}},
        level="behavioral", seeds={"master": brb.MASTER_SEED, "policy": "per-stream seed = sha256(master:label)[:8]; label carries no shift (matched)"},
        tools={"model": "sim/raw-bit-volume-campaign/behavioral_raw_bit.py", "replay": "sim/ro-vth-drift-sensitivity/analysis/behavioral_replay.py"})
    print(rid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
