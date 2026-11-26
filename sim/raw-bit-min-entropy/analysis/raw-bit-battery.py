#!/usr/bin/env python3
"""Reduced SP 800-22-style battery + SP 800-90B non-IID estimators over the
digitized `raw_bit` sequence, per corner.  Standard library only.

**This runs no simulator.**  Like `raw-bit-entropy.py` (the MCV-only
reduction this module extends) it is pure arithmetic over an already-
committed `sim/raw-bit-min-entropy/records/*.json` campaign record, and
`--emit-record` mints an append-only *derived* record citing that source
record via `sim/bin/evidence_record.py`.

The battery, the estimators, their minimum-length guards and their caveats
are the shared library `sim/bin/bitstream_stats.py` (issue #794); what
stays here is the campaign CLI around them.

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
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDS_DIR = REPO_ROOT / "sim" / "raw-bit-min-entropy" / "records"

sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from bitstream_stats import (  # noqa: E402
    ALPHA,
    MIN_SEGMENTS,
    SOURCE_NOTE,
    TUPLE_CAP,
    _LONGEST as _LONGEST,
    _failed,
    _serial as _serial,
    analyse_stream as _analyse_stream,
    entropy_estimates,
    format_binding,
    igamc as igamc,
    render_detail_tables,
    run_battery,
    t_monobit as t_monobit,
    t_runs as t_runs,
)
from evidence_record import mint_record, new_record_id  # noqa: E402
from loadmod import load_module  # noqa: E402
from raw_bit_volume import (  # noqa: E402
    VOLUME_SLUG as VOLUME_SLUG,
    VolumeInputError,
    decode_packed_hex as decode_packed_hex,
    load_stream as load_stream,
    load_volume_source,
)
from replay_equal import replay_equal  # noqa: E402  (issue #519/#659: one shared replay equality)

raw_bit_entropy = load_module(
    "raw_bit_entropy", Path(__file__).with_name("raw-bit-entropy.py"))

SEGMENT_LEN = 8192  # volume adapter: non-overlapping segments of 8192 bits;
# the segment count is derived per stream as n // SEGMENT_LEN (16 at 2^17,
# 128 at 2^20), so any stream length works (a ragged tail is not segmented).
H_DESIGN = 0.5  # DR-0004 design min-entropy the ratified C_RCT = 81 / C_APT = 824 are evaluated at
VOLUME_CAVEATS_HEADING = "## Caveats that bound how this record may be cited"

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


def analyse_stream(bits: list[int], segment_len: int | None = None) -> dict:
    """Full-stream battery + estimators and the segmented battery.

    `segment_len=None` segments with this module's `SEGMENT_LEN` read at call
    time (so patching `B.SEGMENT_LEN` in tests keeps working, like
    `run_battery`); any other `segment_len` is the caller's own policy.
    """
    if segment_len is None:
        segment_len = SEGMENT_LEN
    return _analyse_stream(bits, segment_len)


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
            out.append(
                f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | "
                f"{r['seed']} | {r['n']} | {r['single_sequence']['verdict']} | "
                f"{_failed(r['single_sequence'])} | {r['segmented']['verdict']} | "
                f"{_failed(r['segmented'])} | "
                f"{'-' if h is None else f'{h:.4f}'} | {format_binding(e)} | "
                f"`{r['source_file']}` | `{r['source_sha256_hex']}` |")
        out += render_detail_tables(
            grp,
            est_heading="### 90B estimators (bit/sample, full stream)",
            seq_heading="### Single-sequence p-values (full stream)",
            seg_heading=("### Segmented pass proportions (passing segments / "
                         f"{pol['count']}; F = below criterion)"))
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
    if not replay_equal(got, want):
        rc = 1
        diffs = [r["source_file"] for r, w in zip(got["per_stream"],
                 want.get("per_stream", [])) if not replay_equal(r, w)]
        print("CHECK FAILED: analysis payload differs"
              + (f" (streams: {', '.join(diffs)})" if diffs else ""),
              file=sys.stderr)
    # The markdown is rendered from the committed payload; the recomputed
    # payload is tied to it by the replay comparison above (float-tolerant),
    # so the markdown is compared against render(want) only -- a 1-ulp
    # re-derivation shift can straddle a :.4f rounding midpoint and would
    # false-diff here (same rule as conditioned-output.py).
    if render_volume(want, caveats) not in md_text:
        rc = 1
        print("CHECK FAILED: committed markdown tables differ from the "
              "committed payload or source caveats", file=sys.stderr)
    if rc == 0:
        print(f"CHECK OK: {record_json.name} reproduces "
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
