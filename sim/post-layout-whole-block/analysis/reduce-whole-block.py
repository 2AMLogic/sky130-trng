#!/usr/bin/env python3
"""Reduce the whole-block campaign (issue #174) to one append-only record.

Pure arithmetic over already-produced artifacts; it never simulates.

Inputs
------
``--corners-dir`` (default ``sim/post-layout-whole-block/corners``): every
``*/report.json`` + ``*/request.json`` + ``*/plan.json`` it finds. Each
``klt sim`` report (or klt error envelope, e.g. a refused batch submit) is
matched against the **12-point matrix** this script enumerates itself:
tt/ss/ff x {(-40 C, 1.62 V), (27 C, 1.80 V), (-40 C, 1.98 V), (125 C, 1.98 V)}
(``make-requests.GRID``; the four-point grid DR-0008 and every post-layout
deck in this repo use, resolved from DR-0003 / DR-0010 row 9's 1.62/1.8/1.98 V
x -40/27/125 C axes).

A point counts as MET only if its corner exists, has status ``pass`` (no
errors, every measurement a finite number) **and** the deterministic digital
responses equal the normative model (``digital/model``) replayed with the raw
bits the transistor run captured. Anything else -- no report, a refused or
failed batch submit, a timeout, an errored corner, a missing measurement, an
oracle mismatch -- is UNMET and is named as such with its reason. Omitting a
point therefore always shows up as incomplete coverage.

``--ir-summary`` (default ``sim/post-layout-whole-block/ir/summary.json``)
supplies the static-IR section verbatim.

Usage: ``reduce-whole-block.py [--emit-record] [--points-dir ...]``.
Without ``--emit-record`` it prints the reduction as JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOCK = HERE.parent
REPO = BLOCK.parents[1]
sys.path.insert(0, str(BLOCK))
sys.path.insert(0, str(REPO / "sim" / "bin"))
import program as P  # noqa: E402
import importlib.util  # noqa: E402

_mr_spec = importlib.util.spec_from_file_location("make_requests", BLOCK / "make-requests.py")
MR = importlib.util.module_from_spec(_mr_spec)
_mr_spec.loader.exec_module(MR)

SLUG = "post-layout-whole-block"
GRID = [(-40.0, 1.62), (27.0, 1.8), (-40.0, 1.98), (125.0, 1.98)]
PROCESSES = ("tt", "ss", "ff")
RAILS = ("vdd", "vddr1", "vddr2", "vddr3", "vddr4")

#: DR-0017 claim-level wording; every reporting surface carries it verbatim
LEVEL_MIXED = ("mixed-level (analog transistor / digital gate-level), "
               "connectivity-only extract (no R/C)")
LEVEL_TRANSISTOR = "transistor-level whole-block, connectivity-only extract (no R/C)"
LEVEL_UNLABELLED = "UNLABELLED: no PROVENANCE recorded, nothing is claimed"

#: obligations DR-0017 forces UNMET by construction, whatever the numbers are
FORCED_UNMET = {
    "O5d": "digital supply current / dynamic power and the sampler's own vdd/vss current are not "
           "transistor-level evidence under DR-0017 option (b) (gate-level digital; vdd/vss mixed)",
    "O7": "static IR with a digital load: no transistor-level digital load (#308)",
    "O8": "entropy statistics at the ratified Ts: this program runs Ts = 100 ns, not 20 us",
}
OBLIGATIONS = (
    ("O1", "12-point matrix present (3 process x 4 (T, Vdd))"),
    ("O2", "register path vs normative model (rdata_k*)"),
    ("O3", "streaming port (out_valid_k*, odata_k*)"),
    ("O4", "alarm / gated / startup_done scalars"),
    ("O5a", "ring-supply currents vddr1-vddr4 (transistor-level)"),
    ("O5d", "digital supply current / dynamic power; sampler's own vdd/vss current"),
    ("O6", "throughput tap t_out_valid_first"),
    ("O7", "static IR with a digital load"),
    ("O8", "entropy statistics at the ratified Ts"),
)


def level_of(provenance: dict | None) -> str:
    """Claim-level label from ``PROVENANCE`` (DR-0017 section Claim level)."""
    if not provenance or not provenance.get("analog") or not provenance.get("digital"):
        return LEVEL_UNLABELLED
    if provenance["digital"] == "gate-level":
        return LEVEL_MIXED
    if provenance == {"analog": "transistor", "digital": "transistor"}:
        return LEVEL_TRANSISTOR
    return LEVEL_UNLABELLED


def power_provenance(provenance: dict | None) -> dict | None:
    if level_of(provenance) == LEVEL_UNLABELLED:
        return None
    return {"i_vdd_w1": "mixed", "i_vdd_w2": "mixed", "i_vss_w2": "mixed",
            "digital_delta_i_a": "mixed",
            "digital_dynamic_power_w_estimate": "gate-level"}


def expected_points() -> list[tuple[str, float, float]]:
    return [(p, t, v) for (t, v) in GRID for p in PROCESSES]


def key(proc: str, temp: float, vdd: float) -> str:
    return f"{proc}/{temp:g}C/{vdd:.2f}V"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_num(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


# --------------------------------------------------------------------------
# per-corner analysis
# --------------------------------------------------------------------------

def meas_map(corner: dict) -> dict[str, float | None]:
    return {m["name"]: m["value"] for m in corner.get("measurements", [])}


def analyse_corner(corner: dict, vdd: float) -> dict:
    """Return {'problems': [...], 'oracle': {...}, 'power': {...}, 'timing': {...}}."""
    m = meas_map(corner)
    problems: list[str] = []
    if corner.get("status") != "pass":
        problems.append(f"klt corner status {corner.get('status')!r}")
    diag = [d for d in corner.get("diagnostics", []) if d.get("code") != "measurement"]
    for d in diag[:5]:
        problems.append(f"diagnostic {d.get('code')}: {d.get('message', '')[:160]}")
    # the program's own measurement set is the contract: an entry that is
    # wholly omitted from the report is as unmet as one that is null
    required = {e["name"] for e in MR.measurement_cards(P.build_program()[0])[0]}
    omitted = sorted(required - set(m))
    if omitted:
        problems.append(f"{len(omitted)} required measurement(s) omitted from the report (first: {omitted[:3]})")
    missing = sorted(n for n, v in m.items() if not is_num(v))
    if missing:
        problems.append(f"{len(missing)} measurement(s) absent/non-finite (first: {missing[:3]})")
    if not m:
        problems.append("no measurements in the report")

    out: dict = {"problems": problems}
    if missing or omitted or not m:
        return out

    thr = vdd / 2.0
    bit = lambda name: 1 if m[name] > thr else 0  # noqa: E731

    cycles, _ = P.build_program()
    inputs = P.cycle_inputs(cycles)
    raw_bits = [bit(f"raw_bit_k{k}") for k, i in enumerate(inputs) if i["raw_valid"]]
    rows = P.model_replay(raw_bits)

    mismatches: list[str] = []
    checks = 0

    def cmp(name: str, got: int, want: int) -> None:
        nonlocal checks
        checks += 1
        if got != want:
            mismatches.append(f"{name}: transistor {got} != model {want}")

    for k, inp in enumerate(inputs):
        if inp["raw_valid"]:
            cmp(f"raw_valid_k{k}", bit(f"raw_valid_k{k}"), 1)
        if inp["re"]:
            got = sum(bit(f"rdata_k{k}_b{b}") << b for b in range(32))
            cmp(f"bus_rdata@k{k}", got, rows[k]["model"]["bus_rdata"])
    for name in m:
        if name.startswith(("alarm_k", "gated_k", "startup_done_k", "out_valid_k")):
            sig, kk = name.rsplit("_k", 1)
            k = int(kk)
            cmp(f"{sig}@k{k}", bit(name), int(rows[k - 1]["model"][sig]))
    for k in sorted({int(n.split("_k")[1].split("_")[0]) for n in m if n.startswith("odata_k")}):
        got = sum(bit(f"odata_k{k}_b{b}") << b for b in range(32))
        cmp(f"out_data@k{k}", got, rows[k - 1]["model"]["out_data"])
    out["oracle"] = {"checks": checks, "mismatches": mismatches, "match": not mismatches and checks > 0}
    if mismatches or checks == 0:
        problems.append(f"oracle: {len(mismatches)} mismatch(es) in {checks} comparison(s)")

    # supply currents: i(Vsrc) is negative when the source delivers current
    cur = {}
    for r in RAILS:
        cur[r] = {"w1_a": -m[f"i_{r}_w1"], "w2_a": -m[f"i_{r}_w2"]}
    p_active = sum(vdd * cur[r]["w2_a"] for r in RAILS)
    # W1 = rings running, digital reset-held with clk not started (leakage-dominated digital)
    d_vdd = cur["vdd"]["w2_a"] - cur["vdd"]["w1_a"]
    out["power"] = {
        "vdd_v": vdd, "currents_a": cur,
        "p_active_w": p_active,
        "digital_delta_i_a": d_vdd,
        "digital_dynamic_power_w_estimate": vdd * d_vdd,
        "basis": "W2 = every program cycle (clock running at TS); W1 = reset held, clk not started; "
                 "dynamic = (I_vdd[W2]-I_vdd[W1])*Vdd, includes the activity of THIS directed program only",
        "recompute_check_w": sum(vdd * -m[f"i_{r}_w2"] for r in RAILS),
    }
    t_first = m.get("t_out_valid_first")
    out["timing"] = {"t_out_valid_first_s": t_first,
                     "throughput_note": "time of first out_valid rise from t=0 (raw-tap word of 32 samples at TS)"}
    return out


def collect(corners_dir: Path) -> tuple[dict, list[dict]]:
    """Map expected point key -> {status, reason, ...}; plus a list of source requests."""
    found: dict[str, dict] = {}
    sources: list[dict] = []
    for rep in sorted(corners_dir.glob("*/report.json")):
        d = rep.parent
        src = {"dir": d.name, "report": str(rep.relative_to(REPO)) if rep.is_relative_to(REPO) else str(rep), "report_sha256": sha256(rep)}
        for extra in ("request.json", "plan.json"):
            if (d / extra).exists():
                src[extra] = sha256(d / extra)
        plan = json.loads((d / "plan.json").read_text()) if (d / "plan.json").exists() else {}
        src["netlist_sha256"] = plan.get("netlist_sha256")
        att = d / "submit-attempts.log"
        if att.exists():
            lines = att.read_text().splitlines()
            src["submit_attempts"] = {"count": len(lines), "capacity_refused": sum(1 for x in lines if " rc=1 " in x),
                                      "log": lines}
        try:
            doc = json.loads(rep.read_text())
        except json.JSONDecodeError:
            doc = {"error": {"message": "report.json is not valid JSON (run killed or never completed)"}}
        remote = (doc.get("environment") or {}).get("remote")
        src["remote"] = remote
        src["status"] = doc.get("status", "error-envelope" if "error" in doc else "unknown")
        if "error" in doc:
            src["error"] = doc["error"].get("message")
        sources.append(src)
        if not d.name.startswith("grid-"):
            continue   # controls/probes are listed as sources but never count toward the matrix
        for c in doc.get("corners", []) or []:
            t = c.get("temperature_c")
            v = (c.get("supply_v") or {}).get("Vvdd")
            if t is None or v is None:
                continue
            found[key(c.get("process"), float(t), float(v))] = {
                "source": d.name, "corner": c, "remote": remote}
        if "error" in doc:
            plan_c = plan.get("corners") or {}
            for proc in plan_c.get("process", []):
                for t in plan_c.get("temperature_c", []):
                    for v in (plan_c.get("supply_v", {}).get("Vvdd") or []):
                        k = key(proc, float(t), float(v))
                        found.setdefault(k, {"source": d.name, "corner": None,
                                             "reason": "klt error envelope: " + (doc["error"].get("message") or "")[:300]})
    return found, sources


_DEFAULT = object()


def obligations(points: list[dict], provenance: dict | None) -> list[dict]:
    """One row per DR-0017 obligation. Rows other than the forced ones are
    MET only when every one of the 12 points is MET *and* a PROVENANCE is
    recorded; O5d/O7/O8 are UNMET whatever the numbers are."""
    labelled = level_of(provenance) != LEVEL_UNLABELLED
    unmet_pts = [p["point"] for p in points if p["status"] != "MET"]
    rows = []
    for oid, text in OBLIGATIONS:
        row = {"id": oid, "obligation": text}
        if oid in FORCED_UNMET:
            row.update(status="UNMET", reasons=[FORCED_UNMET[oid]])
        elif not labelled:
            row.update(status="UNMET", reasons=["no PROVENANCE recorded: result level unknown"])
        elif unmet_pts:
            row.update(status="UNMET",
                       reasons=[f"{len(unmet_pts)} of {len(points)} point(s) UNMET (first: {unmet_pts[:3]})"])
        else:
            row.update(status="MET", reasons=[])
        rows.append(row)
    return rows


def reduce(corners_dir: Path, ir_summary: Path | None, provenance=_DEFAULT) -> dict:
    if provenance is _DEFAULT:
        provenance = P.PROVENANCE
    found, sources = collect(corners_dir)
    points = []
    for proc, t, v in expected_points():
        k = key(proc, t, v)
        ent = found.get(k)
        row = {"point": k, "process": proc, "temperature_c": t, "vdd_v": v}
        if ent is None:
            row.update(status="UNMET", reasons=["no report covers this point (never submitted or never returned)"])
        elif ent.get("corner") is None:
            row.update(status="UNMET", reasons=[ent["reason"]], source=ent["source"])
        else:
            res = analyse_corner(ent["corner"], v)
            row.update(source=ent["source"], remote=ent.get("remote"))
            row.update({kk: vv for kk, vv in res.items() if kk != "problems"})
            row["status"] = "MET" if not res["problems"] else "UNMET"
            row["reasons"] = res["problems"]
        row["level"] = level_of(provenance)
        if row.get("power") is not None:
            row["power"]["provenance"] = power_provenance(provenance)
        if provenance is None or level_of(provenance) == LEVEL_UNLABELLED:
            row["status"] = "UNMET"
            row["reasons"] = list(row.get("reasons") or []) + ["no PROVENANCE recorded: result level unknown"]
        points.append(row)
    met = sum(1 for p in points if p["status"] == "MET")
    ir = json.loads(ir_summary.read_text()) if ir_summary and ir_summary.exists() else None
    obs = obligations(points, provenance)
    return {
        "matrix": {"expected": len(points), "met": met, "unmet": len(points) - met,
                   "complete": met == len(points)},
        "points": points,
        "sources": sources,
        "ir": ir,
        "provenance": provenance,
        "level": level_of(provenance),
        "obligations": obs,
        # O5d / O7 / O8 are forced UNMET (DR-0017), so AC3 is never claimable here
        "ac3_claimable": False if any(o["status"] != "MET" for o in obs
                                      if o["id"] in FORCED_UNMET) else None,
    }


def render(red: dict) -> str:
    L = [f"**Level: {red['level']}.** Simulation-derived, provisional until measured on silicon; "
         "not foundry sign-off.", "",
         "## Obligations (DR-0017)", "", "| id | obligation | status | reasons |", "|---|---|---|---|"]
    for o in red["obligations"]:
        L.append(f"| {o['id']} | {o['obligation']} | {o['status']} | {'; '.join(o['reasons']) or 'all 12 points MET'} |")
    L += ["", "## 12-point matrix (tt/ss/ff x four PVT points)", "",
         f"MET {red['matrix']['met']} / {red['matrix']['expected']}; "
         f"complete = **{red['matrix']['complete']}**", "",
         "| point | status | reason |", "|---|---|---|"]
    for p in red["points"]:
        L.append(f"| {p['point']} | {p['status']} | {'; '.join(p.get('reasons') or []) or 'oracle match, finite measurements'} |")
    L += ["", "## Sources", ""]
    for s in red["sources"]:
        L.append(f"- `{s['dir']}`: status `{s['status']}`, report sha256 `{s['report_sha256'][:16]}`, "
                 f"netlist sha256 `{(s.get('netlist_sha256') or 'n/a')[:16]}`, remote `{s.get('remote')}`"
                 + (f", submit attempts {s['submit_attempts']['count']} ({s['submit_attempts']['capacity_refused']} refused rc=1)"
                    if s.get("submit_attempts") else "")
                 + (f", error: {s['error']}" if s.get("error") else ""))
    if red.get("ir"):
        ir = red["ir"]
        L += ["", "## Static IR (klt power, assumed ring loads only)", "",
              f"- worst droop **{ir['worst_case_droop_mv']} mV** (see summary.json for net/node); "
              f"EM verdict `{ir['em_verdict_status']}`",
              f"- ring load assumption: {ir['ring_current_a_assumed']} A each; {ir['ring_current_source']}",
              "- logic-supply (`vdd`/`vss`) loads NOT modelled (no valid whole-block current measurement)"]
    return "\n".join(L) + "\n"


def plan_provenance(corners_dir: Path) -> dict | None:
    """The PROVENANCE every grid ``plan.json`` records; ``None`` (=> every row
    UNMET) if any grid plan lacks it or they disagree."""
    seen = []
    for plan in sorted(corners_dir.glob("grid-*/plan.json")):
        seen.append(json.loads(plan.read_text()).get("provenance"))
    if not seen or any(x is None for x in seen) or any(x != seen[0] for x in seen):
        return None
    return seen[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corners-dir", type=Path, default=BLOCK / "corners")
    ap.add_argument("--ir-summary", type=Path, default=BLOCK / "ir" / "summary.json")
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--claim-file", type=Path, help="markdown with the record's narrative sections")
    ap.add_argument("--artifact", type=Path, action="append", default=[])
    args = ap.parse_args(argv)
    red = reduce(args.corners_dir, args.ir_summary, plan_provenance(args.corners_dir))
    if not args.emit_record:
        print(json.dumps(red, indent=2, default=str))
        return 0 if red["matrix"]["complete"] else 1
    from evidence_record import mint_behavioral_record
    narrative = args.claim_file.read_text() if args.claim_file else ""
    rid = mint_behavioral_record(
        REPO, SLUG,
        claim=(f"whole-block (layout/trng_whole) characterization, {red['level']}, over the 12-point "
               "PVT matrix, dynamic power, and static IR -- extracted-CONNECTIVITY netlist, no parasitics; "
               "unmet coverage is listed explicitly"),
        body_md=narrative + "\n" + render(red),
        summary={"reduction": red},
        level=red["level"] + " + klt power static IR",
        artifacts=args.artifact,
        tools={"klt": "see environment in sources", "script": "sim/post-layout-whole-block/analysis/reduce-whole-block.py"},
    )
    print(rid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
