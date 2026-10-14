#!/usr/bin/env python3
"""Deterministic aggregated characterization report (T1 item 8, issue #291).

Reads the spec target table in ``README.md`` and the minted
``sim/*/records/*.json`` evidence records and writes

    signoff/characterization-report.md
    signoff/characterization-report.json

one row per spec target, with a verdict (``met`` / ``unmet`` /
``not measured``), the PVT conditions covered, and the record id plus
sha256 content hash each verdict rests on.

Rules this script holds itself to:

* It only aggregates. A verdict is computed from a field of a committed
  record by a declared comparison (``EVIDENCE`` below); it is never more
  favourable than that comparison. A failing comparison, or a record whose
  field is absent (including on any one element of a fanned-out list), is
  ``unmet``. A spec row with no evidence declared, or
  whose declared record file does not exist, is ``not measured``.
* Row precedence is unmet > not measured > met: one failing piece of
  evidence makes the row unmet; one missing piece keeps it from being met.
* Targets are read from the spec table, never altered. A spec row with no
  ``EVIDENCE`` entry renders ``not measured``; an ``EVIDENCE`` key that is
  not a spec row is an error (the mapping drifted from the spec).
* Output is byte-deterministic: no timestamps, no host data, sorted keys.
* ``overall`` is ``fail`` while any row is unmet, ``incomplete`` while any
  is not measured (and none unmet), ``pass`` only if every row is met.
  Every verdict is simulation-derived and provisional until silicon.

Usage::

    python3 sim/bin/characterization_report.py            # (re)write
    python3 sim/bin/characterization_report.py --check    # exit 1 if stale

Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_MD = "signoff/characterization-report.md"
OUT_JSON = "signoff/characterization-report.json"
SPEC_FILE = "README.md"
SPEC_HEADING = "## Target specification"

MET, UNMET, NOT_MEASURED = "met", "unmet", "not measured"

# spec parameter -> list of evidence entries. Each entry names one committed
# record, one comparison on one field ("a.b[].c": "[]" takes the worst case
# over the list), and where its PVT coverage is read from.
EVIDENCE: dict[str, list[dict]] = {
    "Raw rate": [{
        "record": "sim/ro-array-operating-point/records/20260825-093740-53f1f7a.json",
        "check": "chosen sampling period t_s <= 1e-6 s (>= 1 Mbps)",
        "field": "chosen.t_s_chosen_s", "op": "le", "value": 1e-6,
        "pvt": "combining.rows[]",
    }],
    # DR-0010 row 3: "not settled by evidence; three non-comparable sources",
    # deferred to #221. Every committed source at the design point is declared
    # here, so one failing source makes the row unmet. (The transistor-level
    # 20260906-003407-6b86c9c record is at Ts = 100 ns, not the 20 us design
    # point, so it is not compared against the design-point target.)
    "Raw min-entropy per bit": [
        {
            "record": "sim/raw-bit-min-entropy/records/20261010-102516-3966094.json",
            "check": "worst-corner h_min >= 0.5 bit/sample at Ts = 20 us (behavioural model, "
                     "independence assumed by construction; DR-0010 row 3 open on #221)",
            "field": "ts20us_min_entropy[].h_min_bits", "op": "ge", "value": 0.5,
            "pvt": "ts20us_min_entropy[]",
        },
    ] + [
        {
            "record": f"sim/local-mismatch-monte-carlo/records/{rid}.json",
            "check": "worst array x sampler pairing H_bias >= 0.5 bit/sample "
                     "(transistor-level local-mismatch MC, static bias only; DR-0010 row 3 open on #221)",
            "field": "summary.raw_bit.h_bias_min", "op": "ge", "value": 0.5,
            "pvt": "pvt",
        }
        for rid in ("20261009-111125-e57ad27", "20261009-111126-e57ad27", "20261009-111127-e57ad27")
    ],
    "Conditioning": [{
        "record": "sim/digital-conditioner-equivalence/records/20260905-192506-2ecb0a3.json",
        "check": "CRC-32 LFSR model bit-exact vs independent references (ok == true)",
        "field": "ok", "op": "eq", "value": True,
        "pvt": None,
    }],
    # DR-0010 row 6: the cutoff values are conditional on row 3 (#221). The
    # record replays the 20261008-061809-56e0fb7 streams, since superseded by
    # 20261010-095913-3966094. Both caveats are carried in the check text.
    "Health tests": [
        {
            "record": "sim/digital-health-test-parameters/records/20261008-150251-cd45d91.json",
            "check": "no false alarms: ratified RCT/APT cutoffs raise 0 alarms replayed over the "
                     "simulated streams (CONDITIONAL: cutoffs depend on DR-0010 row 3 / #221; replays "
                     "streams 20261008-061809-56e0fb7, superseded by 20261010-095913-3966094)",
            "field": "replay_total_alarms", "op": "le", "value": 0,
            "pvt": "replay[].stream",
        },
        {
            "record": "sim/digital-health-test-parameters/records/20261008-150251-cd45d91.json",
            "check": "detects stuck-at: RCT detects every stuck-at-0 / stuck-at-1 fault-injection "
                     "run (detected == runs; same DR-0010 row 3 / #221 condition)",
            "field": "injection.scenarios[name=stuck-at-0|stuck-at-1].rct", "op": "all_detected",
            "pvt": None,
        },
        {
            "record": "sim/digital-health-test-parameters/records/20261008-150251-cd45d91.json",
            "check": "detects stuck-at: APT detects every stuck-at-0 / stuck-at-1 fault-injection "
                     "run (detected == runs; same DR-0010 row 3 / #221 condition)",
            "field": "injection.scenarios[name=stuck-at-0|stuck-at-1].apt", "op": "all_detected",
            "pvt": None,
        },
    ],
    "Area": [
        {
            "record": "sim/digital-floorplan-compaction/records/20261009-214736-760b4d3.json",
            "check": "target_status == met (target 0.05 mm2)",
            "field": "target_status", "op": "eq", "value": "met", "pvt": None,
        },
        {
            "record": "sim/digital-repaired-compaction/records/20261010-105914-824542d.json",
            "check": "target_status == met (target 0.05 mm2)",
            "field": "target_status", "op": "eq", "value": "met", "pvt": None,
        },
    ],
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def parse_spec_table(text: str) -> list[dict]:
    """Rows of the first pipe table after the target-specification heading."""
    i = text.find(SPEC_HEADING)
    if i < 0:
        raise SystemExit(f"{SPEC_FILE}: heading {SPEC_HEADING!r} not found")
    rows, started = [], False
    for line in text[i:].splitlines()[1:]:
        if line.startswith("|"):
            started = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= set("-: ") or cells[0] == "Parameter":
                continue
            rows.append({"parameter": cells[0], "target": cells[1],
                         "stretch": cells[2] if len(cells) > 2 else ""})
        elif started:
            break
    if not rows:
        raise SystemExit(f"{SPEC_FILE}: no spec table rows found")
    return rows


_PART = re.compile(r"^([^\[\]]*)(?:\[([^\]]*)\])?$")


def extract_strict(obj, path: str) -> tuple[list, int]:
    """(values, n_missing) at a dotted path.

    ``a[]`` fans out over the list ``a``; ``a[k=v1|v2]`` fans out over the
    elements of ``a`` whose ``k`` is one of the listed values, and every
    listed value must match at least one element. Anything the path expects
    but does not find -- an absent key (at top level or on any fanned-out
    element), a non-list where a list is expected, a selector value no
    element carries -- counts as missing. Missing is never skipped silently:
    ``compare`` treats any missing value as a failure.
    """
    cur, missing = [obj], 0
    for part in path.split("."):
        m = _PART.match(part)
        if not m:
            raise SystemExit(f"bad path segment {part!r} in {path!r}")
        key, sel = m.group(1), m.group(2)
        nxt = []
        for c in cur:
            if key:
                if not isinstance(c, dict) or key not in c:
                    missing += 1
                    continue
                c = c[key]
            if sel is None:
                nxt.append(c)
                continue
            if not isinstance(c, list):
                missing += 1
                continue
            if not sel:
                nxt.extend(c)
                continue
            skey, _, svals = sel.partition("=")
            wanted = svals.split("|")
            for w in wanted:
                hits = [e for e in c if isinstance(e, dict) and str(e.get(skey)) == w]
                if not hits:
                    missing += 1
                nxt.extend(hits)
        cur = nxt
    return cur, missing


def extract(obj, path: str) -> list:
    """Values found at a dotted path (see ``extract_strict``)."""
    return extract_strict(obj, path)[0]


def compare(values: list, op: str, want, missing: int = 0) -> tuple[bool, str]:
    """True only if nothing is missing, values is non-empty, and every value satisfies op."""
    if missing:
        return False, f"field absent from {missing} expected element(s)"
    if not values:
        return False, "field absent from record"
    try:
        if op == "all_detected":
            # each value is {"detected": int, "runs": int}; met only if detected == runs > 0
            pairs = [(v["detected"], v["runs"]) for v in values]
            bad = [p for p in pairs if not (isinstance(p[1], int) and p[1] > 0 and p[0] == p[1])]
            ok = not bad
            observed = f"{sum(d for d, _ in pairs)}/{sum(r for _, r in pairs)} detected"
            return ok, f"observed {observed}"
        if op == "eq":
            ok, observed = all(v == want for v in values), values[0] if len(set(map(repr, values))) == 1 else values
        elif op == "ge":
            observed = min(values); ok = observed >= want
        elif op == "le":
            observed = max(values); ok = observed <= want
        else:
            raise SystemExit(f"unknown op {op!r}")
    except (TypeError, KeyError):
        return False, "field not comparable"
    return ok, f"observed {observed!r}"


def pvt_labels(rec: dict, path: str | None) -> list[str]:
    if not path:
        return []
    out = set()
    for v in extract(rec, path):
        if isinstance(v, str):
            # normalise "ss -40 C 1.62 V" to the dict form "ss -40C 1.62V"
            out.add(_UNIT_GAP.sub(r"\1\2", v))
        elif isinstance(v, dict):
            corner = next((v[k] for k in ("corner", "proc") if k in v), None)
            temp = next((v[k] for k in ("temp_c", "temp") if k in v), None)
            vdd = next((v[k] for k in ("vdd_v", "vnom") if k in v), None)
            parts = [str(corner)] if corner is not None else []
            if temp is not None:
                parts.append(f"{temp:g}C")
            if vdd is not None:
                parts.append(f"{vdd:g}V")
            if parts:
                out.add(" ".join(parts))
    return sorted(out)


_UNIT_GAP = re.compile(r"(-?\d+(?:\.\d+)?) ([CV])\b")


def evaluate(root: Path, entry: dict) -> dict:
    rel = entry["record"]
    res = {"record_path": rel, "check": entry["check"]}
    p = root / rel
    if not p.is_file():
        res.update(verdict=NOT_MEASURED, detail="record file not found",
                   record_id=None, sha256=None, level=None, pvt=[])
        return res
    raw = p.read_bytes()
    rec = json.loads(raw)
    values, missing = extract_strict(rec, entry["field"])
    ok, detail = compare(values, entry["op"], entry.get("value"), missing)
    res.update(verdict=MET if ok else UNMET, detail=detail,
               record_id=rec.get("record_id"), sha256=sha256_bytes(raw),
               level=rec.get("level"), pvt=pvt_labels(rec, entry.get("pvt")))
    return res


def aggregate(verdicts: list[str]) -> str:
    if not verdicts:
        return NOT_MEASURED
    if UNMET in verdicts:
        return UNMET
    if NOT_MEASURED in verdicts:
        return NOT_MEASURED
    return MET


def build_report(root: Path, evidence: dict[str, list[dict]] | None = None) -> dict:
    evidence = EVIDENCE if evidence is None else evidence
    spec = parse_spec_table((root / SPEC_FILE).read_text())
    names = {r["parameter"] for r in spec}
    stray = sorted(set(evidence) - names)
    if stray:
        raise SystemExit(f"EVIDENCE keys not in the spec table: {stray}")
    rows = []
    for r in spec:
        ev = [evaluate(root, e) for e in evidence.get(r["parameter"], [])]
        pvt = sorted({x for e in ev for x in e["pvt"]})
        rows.append({**r, "verdict": aggregate([e["verdict"] for e in ev]),
                     "pvt_coverage": pvt, "evidence": ev})
    counts = {v: sum(r["verdict"] == v for r in rows) for v in (MET, UNMET, NOT_MEASURED)}
    overall = "fail" if counts[UNMET] else ("incomplete" if counts[NOT_MEASURED] else "pass")
    return {
        "schema": "sky130-trng/characterization-report/1",
        "generator": "sim/bin/characterization_report.py",
        "spec_source": SPEC_FILE,
        "caveat": "Simulation-derived and provisional until measured on silicon. "
                  "Aggregates committed records only; never upgrades a verdict.",
        "overall": overall,
        "counts": counts,
        "rows": rows,
    }


def render_json(rep: dict) -> str:
    return json.dumps(rep, indent=2, sort_keys=True) + "\n"


def _esc(s: str) -> str:
    return s.replace("|", "\\|")


def render_md(rep: dict) -> str:
    c = rep["counts"]
    L = ["# Characterization report (T1 item 8)", "",
         "GENERATED by `sim/bin/characterization_report.py` -- do not edit; "
         "CI regenerates and byte-diffs it.", "",
         rep["caveat"], "",
         f"**Overall: {rep['overall']}** -- {c[MET]} met, {c[UNMET]} unmet, "
         f"{c[NOT_MEASURED]} not measured of {len(rep['rows'])} spec targets.", "",
         "| Parameter | Target | Verdict | PVT coverage | Evidence (record id, sha256) |",
         "|---|---|---|---|---|"]
    for r in rep["rows"]:
        ev = "<br>".join(
            f"`{e['record_id']}` `{e['sha256'][:16]}` {e['verdict']}" if e["record_id"]
            else f"{e['verdict']}: `{e['record_path']}` missing" for e in r["evidence"]) or "none"
        pvt = _esc(", ".join(r["pvt_coverage"])) or "none"
        L.append(f"| {_esc(r['parameter'])} | {_esc(r['target'])} | **{r['verdict']}** | {pvt} | {ev} |")
    L += ["", "## Per-row evidence", ""]
    for r in rep["rows"]:
        L.append(f"### {r['parameter']}: {r['verdict']}")
        L.append("")
        if not r["evidence"]:
            L += ["No evidence mapping declared for this target yet; rendered `not measured`.", ""]
        for e in r["evidence"]:
            L.append(f"- `{e['record_path']}`")
            L.append(f"  - check: {e['check']}")
            L.append(f"  - verdict: {e['verdict']} ({e['detail']})")
            if e["record_id"]:
                L.append(f"  - record id `{e['record_id']}`, level {e['level']!r}, sha256 `{e['sha256']}`")
        if r["evidence"]:
            L.append("")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--check", action="store_true", help="exit 1 if committed outputs are stale")
    a = ap.parse_args(argv)
    rep = build_report(a.root)
    outs = {OUT_MD: render_md(rep), OUT_JSON: render_json(rep)}
    if a.check:
        stale = [p for p, t in outs.items()
                 if not (a.root / p).is_file() or (a.root / p).read_bytes() != t.encode()]
        for p in stale:
            print(f"STALE: {p} differs from a fresh render; run sim/bin/characterization_report.py", file=sys.stderr)
        return 1 if stale else 0
    for p, t in outs.items():
        (a.root / p).write_bytes(t.encode())
    print(f"overall={rep['overall']} {rep['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
