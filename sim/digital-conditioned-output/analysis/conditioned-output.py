#!/usr/bin/env python3
"""Conditioned-output (DATA) statistical evidence over the volume-campaign streams.

Feeds every committed raw-bit volume-campaign stream (`raw-bit-volume-campaign`)
through the committed bit-exact CRC-32 conditioner model
(`digital/model/conditioner.py`, K = 8, 256-bit blocks, block-boundary re-seed,
DR-0004 section 3.2) and runs the *existing* reduced SP 800-22-style battery and
non-IID SP 800-90B estimators (`raw-bit-min-entropy/analysis/raw-bit-battery.py`)
on the resulting DATA stream, per PVT corner and per Ts group.

Pinned conventions
------------------
* Word serialization: each 32-bit conditioned word is emitted MSB-first
  (bit 31 first), and words in block order.  The conditioner model does not
  define this; it is fixed here and pinned by the unit test.
* A 131072-bit raw stream gives 512 words = 16384 conditioned bits.  The
  raw battery's segmented policy (16 x 8192) does not fit; the conditioned
  segmented policy is 16 non-overlapping segments of 1024 bits (covers 16384).
* Input/output accounting: raw min-over-estimators H (recomputed here, not
  parsed) x 256 raw bits per block vs the 32 output bits.  A corner is flagged
  when that budget is below 32 + MARGIN_BITS.  The design margin of
  DR-0004 / DR-0003 is 256 x 0.5 = 128 bits (4x).

Claim boundary: simulation-derived, provisional until measured on silicon.
This is NOT a SP 800-90B validation of a non-vetted conditioner and makes no
full-entropy claim (DR-0004 section 3.3 keeps the entropy claim at the raw
tap).  Nothing here changes the conditioner, DR-0004 or any health cutoff.

Usage::

    python3 sim/digital-conditioned-output/analysis/conditioned-output.py \\
        [--volume-record SOURCE.json] [--emit-record]
    python3 sim/digital-conditioned-output/analysis/conditioned-output.py \\
        --check sim/digital-conditioned-output/records/<id>.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from digital.model.conditioner import Crc32Conditioner  # noqa: E402
from digital.model.params import COND_BLOCK_BITS, H_DESIGN  # noqa: E402
from evidence_record import mint_record, new_record_id  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "raw_bit_battery",
    REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis" / "raw-bit-battery.py")
assert _spec is not None and _spec.loader is not None
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

SLUG = "digital-conditioned-output"
RECORDS_DIR = REPO_ROOT / "sim" / SLUG / "records"
ANALYSIS = "sim/digital-conditioned-output/analysis/conditioned-output.py"
DEFAULT_SOURCE = (REPO_ROOT / "sim" / "raw-bit-volume-campaign" / "records"
                  / "20261008-135454-847b454.json")
WORD_BITS = 32
SEGMENT_COUNT = 16
SEGMENT_LEN = 1024  # 16 x 1024 = 16384 conditioned bits per 131072-bit stream
MARGIN_BITS = 32.0  # flag when 256*H < 32 + MARGIN_BITS (i.e. under 2x cover)
DESIGN_BUDGET = COND_BLOCK_BITS * H_DESIGN  # 128 bits (4x)
CAVEAT = ("simulation-derived, provisional until measured on silicon; not a "
          "90B validation of a non-vetted conditioner; no full-entropy claim")


def word_bits_msb_first(word: int) -> list[int]:
    """Serialize one 32-bit word MSB-first (bit 31 first)."""
    return [(word >> i) & 1 for i in range(WORD_BITS - 1, -1, -1)]


def condition_stream(raw: list[int]) -> list[int]:
    """Condition a raw stream; a trailing partial block is dropped (flush)."""
    c = Crc32Conditioner()
    out: list[int] = []
    for bit in raw:
        w = c.push(bit)
        if w is not None:
            out.extend(word_bits_msb_first(w))
    return out


def accounting(h_raw: float | None) -> dict:
    if h_raw is None:
        return {"h_raw": None, "budget_bits": None, "ratio": None,
                "flag": "INSUFFICIENT"}
    budget = h_raw * COND_BLOCK_BITS
    flag = ("BELOW-32" if budget < WORD_BITS
            else "BELOW-32+MARGIN" if budget < WORD_BITS + MARGIN_BITS
            else "ok")
    return {"h_raw": h_raw, "budget_bits": budget,
            "ratio": budget / WORD_BITS, "flag": flag}


def analyse_conditioned(bits: list[int]) -> dict:
    est = B.entropy_estimates(bits)
    h = est["h_min_bits"]
    est["binding_ties"] = [k for k, v in est["estimators"].items()
                           if v["status"] == "OK" and v["h_bits"] == h]
    return {"n": len(bits), "ones": sum(bits),
            "single_sequence": B.run_battery(bits),
            "segmented": B.run_battery(bits, segment_len=SEGMENT_LEN),
            "estimators": est}


def payload_for(source_json: Path) -> dict:
    rec, streams, src_sha = B.load_volume_source(source_json)
    rows = []
    for row, raw in streams:
        cond = condition_stream(raw)
        raw_h = B.entropy_estimates(raw)["h_min_bits"]
        rows.append({"corner": row["corner"], "temp_c": row["temp_c"],
                     "vdd_v": row["vdd_v"], "ts_s": row["ts_s"],
                     "ts_name": row["ts_name"], "seed": row["seed"],
                     "source_file": row["file"],
                     "source_sha256_hex": row["sha256_hex"],
                     "raw_n": len(raw), "words": len(cond) // WORD_BITS,
                     "accounting": accounting(raw_h),
                     "conditioned": analyse_conditioned(cond)})
    return {"source_record": rec["record_id"], "source_level": rec["level"],
            "source_json_sha256": src_sha,
            "serialization": "MSB-first per 32-bit word, words in block order",
            "segment_policy": {"count": SEGMENT_COUNT, "len": SEGMENT_LEN,
                               "non_overlapping": True,
                               "covers_bits": SEGMENT_COUNT * SEGMENT_LEN},
            "margin_bits": MARGIN_BITS, "design_budget_bits": DESIGN_BUDGET,
            "alpha": B.ALPHA, "per_stream": rows}


def _failed(block: dict) -> str:
    f = [k for k, v in block["tests"].items() if v["status"] == "FAIL"]
    return ", ".join(f) if f else "-"


def render(payload: dict) -> str:
    rows = payload["per_stream"]
    pol = payload["segment_policy"]
    n_raw = rows[0]["raw_n"]
    n_out = rows[0]["conditioned"]["n"]
    out = [f"Source record: `{payload['source_record']}` (level "
           f"`{payload['source_level']}`; source JSON sha256 "
           f"`{payload['source_json_sha256']}`).", "",
           "## Method and statistical power", "",
           f"- Each raw stream ({n_raw} bits) is conditioned by the committed "
           f"`Crc32Conditioner` ({COND_BLOCK_BITS}-bit blocks, re-seed at "
           f"every block boundary) into {n_out // WORD_BITS} words = {n_out} "
           "DATA bits.",
           f"- Word serialization: {payload['serialization']}.",
           f"- Power is length-limited: n = {n_out} clears every battery floor "
           "and every estimator floor (compression needs 12000), so the "
           "single-sequence battery and all six estimators run. It is only "
           f"{n_out} bits per stream: a defect smaller than a few percent "
           "bias or serial correlation is not resolvable, and the 90B "
           "estimator bounds are loose at this n.",
           f"- Segmented policy: the raw 16 x 8192 policy does not fit; the "
           f"conditioned policy is {pol['count']} non-overlapping segments of "
           f"{pol['len']} bits ({pol['covers_bits']} bits), SP 800-22 "
           f"pass-proportion (alpha = {payload['alpha']}). Segments and PVT "
           "streams are not independent silicon trials.",
           "- A FAIL in any row is reported as found; no row is excluded.", ""]
    for ts_s, ts_name in sorted({(r["ts_s"], r["ts_name"]) for r in rows},
                                reverse=True):
        grp = [r for r in rows if r["ts_name"] == ts_name]
        tag = ("DR-0003 design point" if ts_name == "Ts20us"
               else "cross-check only")
        out += [f"## {ts_name} (Ts = {ts_s:g} s) -- {tag}", "",
                "### Input/output entropy accounting (raw H x 256 vs 32 output bits)",
                "",
                f"Design budget {payload['design_budget_bits']:g} bits (4x). "
                f"Flag: below 32 + {payload['margin_bits']:g} = "
                f"{32 + payload['margin_bits']:g} bits.", "",
                "| corner | T (C) | Vdd (V) | raw min H (bit/bit) | "
                "256 x H (bits) | ratio to 32 | flag |",
                "|---|---|---|---|---|---|---|"]
        for r in grp:
            a = r["accounting"]
            if a["h_raw"] is None:
                cells = "- | - | - | INSUFFICIENT"
            else:
                cells = (f"{a['h_raw']:.4f} | {a['budget_bits']:.1f} | "
                         f"{a['ratio']:.2f}x | {a['flag']}")
            out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                       f"{cells} |")
        out += ["", "### DATA verdicts and min-over-estimators H", "",
                "| corner | T (C) | Vdd (V) | seed | words | n | ones | "
                "single-seq | single-seq FAIL | segmented | segmented FAIL | "
                "min H (bit/bit) | binding |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in grp:
            c = r["conditioned"]
            e = c["estimators"]
            h = e["h_min_bits"]
            bind = e["binding_estimator"] or "-"
            if len(e["binding_ties"]) > 1:
                bind += " (tie: " + ", ".join(e["binding_ties"]) + ")"
            out.append(
                f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                f"{r['seed']} | {r['words']} | {c['n']} | {c['ones']} | "
                f"{c['single_sequence']['verdict']} | "
                f"{_failed(c['single_sequence'])} | {c['segmented']['verdict']}"
                f" | {_failed(c['segmented'])} | "
                f"{'-' if h is None else f'{h:.4f}'} | {bind} |")
        out += ["", "### DATA 90B estimators (bit/bit, full conditioned stream)",
                "", "| corner | T (C) | Vdd (V) | "
                + " | ".join(B.ESTIMATOR_MIN_N) + " |",
                "|---|---|---|" + "---|" * len(B.ESTIMATOR_MIN_N)]
        for r in grp:
            ev = r["conditioned"]["estimators"]["estimators"]
            cells = [f"{ev[k]['h_bits']:.4f}" if ev[k]["status"] == "OK"
                     else "INSUFFICIENT" for k in B.ESTIMATOR_MIN_N]
            out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                       + " | ".join(cells) + " |")
        out += ["", "### DATA single-sequence p-values", "",
                "| corner | T (C) | Vdd (V) | " + " | ".join(B.BATTERY) + " |",
                "|---|---|---|" + "---|" * len(B.BATTERY)]
        for r in grp:
            t = r["conditioned"]["single_sequence"]["tests"]
            cells = [("%.4g%s" % (t[k]["p_values"][0],
                                  "" if t[k]["status"] == "PASS" else " F"))
                     if "p_values" in t[k] else "INSUFFICIENT" for k in B.BATTERY]
            out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                       + " | ".join(cells) + " |")
        out += ["", f"### DATA segmented pass proportions (passing / "
                f"{pol['count']}; F = below criterion)", "",
                "| corner | T (C) | Vdd (V) | " + " | ".join(B.BATTERY) + " |",
                "|---|---|---|" + "---|" * len(B.BATTERY)]
        for r in grp:
            t = r["conditioned"]["segmented"]["tests"]
            cells = [("%.4f%s" % (t[k]["proportion"],
                                  "" if t[k]["status"] == "PASS" else " F"))
                     if "proportion" in t[k] else "INSUFFICIENT" for k in B.BATTERY]
            out.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                       + " | ".join(cells) + " |")
        out.append("")
    flagged = [r for r in rows if r["accounting"]["flag"] not in ("ok",)]
    out += ["## Flagged corners", ""]
    if flagged:
        out += [f"- {r['ts_name']} {r['corner']} {r['temp_c']:g} C "
                f"{r['vdd_v']:g} V: {r['accounting']['flag']}"
                + ("" if r["accounting"]["budget_bits"] is None else
                   f" (256 x H = {r['accounting']['budget_bits']:.1f} bits)")
                for r in flagged]
    else:
        out.append("- none: every stream's 256 x H is at or above "
                   f"{32 + payload['margin_bits']:g} bits.")
    out += ["", "## Caveats that bound how this result may be cited", "",
            "- **Simulation-derived, provisional until measured on silicon** "
            "(root `CLAUDE.md`). Behavioral-level source streams.",
            "- **No full-entropy claim.** This is not a SP 800-90B validation "
            "of a non-vetted conditioner; DR-0004 section 3.3 keeps the entropy "
            "claim at the raw tap. A CRC-32 output passing a battery is "
            "expected for almost any input with enough raw entropy and is not "
            "by itself evidence of entropy. Conversely, the conditioned-"
            "stream min H values below 1 (about 0.57-0.82) are dominated by "
            "the loose bounds of the non-IID estimators at n = 16384 (the "
            "compression estimator binds), not by a measured output deficit; "
            "they are reported as found and are not a per-bit entropy "
            "figure for DATA.",
            "- **The accounting is a heuristic.** `256 x H` treats the raw "
            "H as a per-bit figure holding across a block; it ignores "
            "inter-bit dependence the estimators may not resolve, and the raw "
            "H is itself a reduced-estimator, length-limited bound.",
            "- **Reduced battery/estimators.** The reused SP 800-22-style "
            "battery omits rank, DFT, templates, Maurer, and excursions; the "
            "estimators are the repo's approximations, not a formal NIST "
            "assessment.",
            "- No change is made to the conditioner, DR-0004 or any "
            "health-test cutoff.", ""]
    return "\n".join(out)


def header(rid: str, payload: dict, source_json: Path) -> list[str]:
    rel = source_json.resolve().relative_to(REPO_ROOT).as_posix()
    return [
        f"# {rid} -- {SLUG} (CRC-32 DATA stream battery + estimators)",
        "",
        "**Claim**: reduced SP 800-22-style battery and SP 800-90B non-IID "
        "estimators over the CRC-32-conditioned DATA stream derived from the "
        f"{len(payload['per_stream'])} raw streams of "
        f"`{payload['source_record']}`, with a raw-H x 256 vs 32-bit "
        "accounting table; no full-entropy claim.",
        "",
        "**Level**: behavioral (derived -- arithmetic over the cited streams "
        "and the bit-exact conditioner model)",
        "**Seed**: N/A (deterministic; per-stream source seeds in the tables)",
        f"**Analysis**: `{ANALYSIS}`",
        "",
        "## Source record and replay",
        "",
        f"- `{payload['source_record']}` (`{rel}`)",
        f"- Input: `python3 {ANALYSIS} --volume-record {rel}`",
        f"- Replay (no minting, nonzero exit on any change): "
        f"`python3 {ANALYSIS} --check sim/{SLUG}/records/{rid}.json`",
        "",
        "---",
        "",
    ]


REPLAY_REL_TOL = 1e-9  # float noise across Python/libm versions is ~1e-15


def replay_diff(want, got, path: str = "$") -> list[str]:
    """Recursive replay comparison of a committed vs a recomputed payload.

    Exact equality for everything that is not a float (ints, strings,
    verdicts, statuses, word/ones counts, None, bools, keys, list lengths);
    floats compare with math.isclose(rel_tol=REPLAY_REL_TOL), since trailing
    digits differ across Python/libm versions. Returns mismatch paths
    (empty list == reproduces).
    """
    if isinstance(want, float) or isinstance(got, float):
        if (type(want) is float and type(got) is float
                and math.isclose(want, got, rel_tol=REPLAY_REL_TOL,
                                 abs_tol=0.0)):
            return []
        if (type(want) is float and type(got) is float
                and math.isnan(want) and math.isnan(got)):
            return []
        return [f"{path}: {want!r} != {got!r}"]
    if type(want) is not type(got):
        return [f"{path}: type {type(want).__name__} != {type(got).__name__}"]
    if isinstance(want, dict):
        if want.keys() != got.keys():
            return [f"{path}: keys differ "
                    f"{sorted(set(want) ^ set(got))}"]
        out: list[str] = []
        for k in want:
            out += replay_diff(want[k], got[k], f"{path}.{k}")
        return out
    if isinstance(want, list):
        if len(want) != len(got):
            return [f"{path}: length {len(want)} != {len(got)}"]
        out = []
        for i, (w, g) in enumerate(zip(want, got)):
            out += replay_diff(w, g, f"{path}[{i}]")
        return out
    return [] if want == got else [f"{path}: {want!r} != {got!r}"]


def check(record_json: Path) -> int:
    try:
        committed = json.loads(record_json.read_text())
        md_text = record_json.with_suffix(".md").read_text()
        src = REPO_ROOT / committed["source_json"]
        want = committed["analysis_payload"]
        got = json.loads(json.dumps(payload_for(src)))
    except (OSError, ValueError, KeyError, B.VolumeInputError) as exc:
        print(f"CHECK FAILED: {exc}", file=sys.stderr)
        return 1
    rc = 0
    diffs = replay_diff(want, got, "analysis_payload")
    if diffs:
        rc = 1
        print(f"CHECK FAILED: analysis payload differs ({len(diffs)} "
              "mismatches, first 10):", file=sys.stderr)
        for d in diffs[:10]:
            print(f"  {d}", file=sys.stderr)
    # The markdown is rendered from the committed payload; the recomputed
    # payload is tied to it by replay_diff above (float-tolerant), so the
    # markdown is compared against render(want) only.
    if render(want) not in md_text:
        rc = 1
        print("CHECK FAILED: committed markdown differs from payload",
              file=sys.stderr)
    if rc == 0:
        print(f"CHECK OK: {record_json.name} reproduces "
              f"({len(got['per_stream'])} streams)")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--volume-record", type=Path, default=DEFAULT_SOURCE,
                    metavar="SOURCE.json")
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--check", type=Path, metavar="RECORD.json")
    ap.add_argument("--author", default="loom-builder@sky130-trng")
    args = ap.parse_args(argv)
    if args.check:
        return check(args.check)
    src = args.volume_record.resolve()
    try:
        payload = json.loads(json.dumps(payload_for(src)))
    except B.VolumeInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    body = render(payload)
    print(body)
    if not args.emit_record:
        return 0
    now, sha, rid = new_record_id(REPO_ROOT)
    rel = src.relative_to(REPO_ROOT).as_posix()
    flagged = [{"ts_name": r["ts_name"], "corner": r["corner"],
                "temp_c": r["temp_c"], "vdd_v": r["vdd_v"],
                "flag": r["accounting"]["flag"]}
               for r in payload["per_stream"]
               if r["accounting"]["flag"] != "ok"]
    out = {"record_id": rid, "slug": SLUG, "level": "behavioral (derived)",
           "analysis": ANALYSIS, "source_record": payload["source_record"],
           "source_json": rel, "author": args.author,
           "timestamp_utc": now.isoformat(), "repo_sha": sha,
           "caveat": CAVEAT, "flagged_corners": flagged,
           "analysis_payload": payload}
    result = mint_record(RECORDS_DIR, REPO_ROOT, rid,
                         header(rid, payload, src), body, out,
                         author=args.author, now=now, sha=sha)
    return 0 if result is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
