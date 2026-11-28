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

Each ``grid-*`` report is first matched against its own ``plan.json`` (#815):
the deck the report ran (``environment.netlist_sha256``) must be the deck the
plan hashed, and each corner must be one of the plan's points on all five
rails. A report that fails either is UNMET on the point it reports *and* on
the point its plan asked for; a second report claiming a point already
covered is UNMET too (never picked between). A coupled plan (``raw_source ==
"analog_sampler"``, the DR-0017 option (b) deck the matrix runs under) is
scored through the coupled oracle -- every level decoded against the point's
own rail, the sampler's strobes checked against ``program.sampler_valid`` and
the captured bits replayed through the model with them -- over the coupled
matrix measurement set; any other plan, or no plan at all, is read through
the flat-deck contract, so the archived flat ``corners/grid-*`` stay readable.

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
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOCK = HERE.parent
REPO = BLOCK.parents[1]
sys.path.insert(0, str(BLOCK))
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "layout" / "bin"))
from _hashing import sha256_file as sha256  # noqa: E402
import program as P  # noqa: E402
# the digital-response comparator (decode / response_checks) and the deck's
# measurement contract are program.py's (#642, #804): the 12-point reducer and
# the gate-model checker must score a corner through ONE implementation, or
# the unexercised copy drifts (it had: a 1-cycle off-by-one on every
# rdata_k*/odata_k*/<sig>_k* check, vdd/2 rounding to 0, and no duplicate
# measurement-name guard).
from measurement_names import duplicate_measurement_names  # noqa: E402

SLUG = "post-layout-whole-block"
GRID = [(-40.0, 1.62), (27.0, 1.8), (-40.0, 1.98), (125.0, 1.98)]
PROCESSES = ("tt", "ss", "ff")

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


def is_num(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


# --------------------------------------------------------------------------
# per-corner analysis
# --------------------------------------------------------------------------

def analyse_corner(corner: dict, vdd: float, coupled: bool = False) -> dict:
    """Return {'problems': [...], 'oracle': {...}, 'power': {...}, 'timing': {...}}.

    ``coupled`` scores a DR-0017 option (b) coupled deck (``plan.raw_source ==
    "analog_sampler"``): the contract is the coupled MATRIX measurement set
    and the oracle is the sampler's -- every cycle's strobe against
    ``program.sampler_valid``, the captured bits replayed through the model
    with those strobes (#815). Otherwise it is the flat-deck contract the
    archived ``corners/grid-*`` and every report without a plan are read
    through. Both decode against ``vdd``, the point's own rail.
    """
    measurements = corner.get("measurements", [])
    # duplicate names displace the entries they repeat in every name-keyed
    # read below (#548's guard, shared with compare-gate-model.py): a
    # displaced measurement silently shrinks the oracle instead of failing
    duplicates = duplicate_measurement_names(measurements)
    if duplicates:
        return {"problems": [f"{len(duplicates)} duplicate measurement name(s) "
                             f"(first: {duplicates[:3]}) displace the entries they repeat, "
                             "refusing the oracle"]}
    m = {e["name"]: e["value"] for e in measurements}
    problems: list[str] = []
    if corner.get("status") != "pass":
        problems.append(f"klt corner status {corner.get('status')!r}")
    diag = [d for d in corner.get("diagnostics", []) if d.get("code") != "measurement"]
    for d in diag[:5]:
        problems.append(f"diagnostic {d.get('code')}: {d.get('message', '')[:160]}")
    # the program's own measurement set is the contract: an entry that is
    # wholly omitted from the report is as unmet as one that is null
    cycles, _ = P.build_program()
    if coupled:
        cards = P.coupled_matrix_measurements(cycles, vdd)[0]
    else:
        cards = P.whole_block_measurement_cards(cycles)[0]
    required = {e["name"] for e in cards}
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

    if coupled:
        # -- the sampler's oracle, through the SHARED coupled decode (#815):
        # the strobes the sampler put on its pins against its documented
        # raw_valid, and the bits of every strobed cycle replayed with them
        cap = P.coupled_capture_decode(m, vdd, cycles)
        strobes, bits = cap["strobes"], cap["bits"]
        captured_valid = dict(zip(cap["strobe_cycles"], strobes, strict=True))
        expected_valid = P.sampler_valid(cycles)
        checks = len(strobes) + len(bits)
        responses = 0
        mismatches: list[str] = [
            f"raw_valid_k{k}: captured {captured_valid[k]} != the sampler's documented {expected_valid[k]}"
            for k in cap["valid_mismatches"]]
        mismatches += [f"{u['measurement']}: level {u['value']!r} V is not a resolved rail"
                       for u in cap["undecodable"]]
        if not cap["undecodable"]:
            rows = P.model_replay(bits, captured_valid=strobes)
            resp, undecodable = P.response_checks(m, rows, vdd, len(cycles))
            compared = [c for c in resp if not c.get("not_compared")]
            responses = len(compared)
            checks += responses
            mismatches += [f"{c['measurement']}: transistor {c['simulated']} != model {c['model']}"
                           for c in compared if not c["match"]]
            mismatches += [f"{u['measurement']}: level {u['value']!r} V is not a resolved rail"
                           for u in undecodable]
        out["oracle"] = {"checks": checks, "strobes": len(strobes), "bits": len(bits),
                         "responses": responses, "mismatches": mismatches,
                         "match": not mismatches and checks > 0}
    else:
        # -- digital response, through the SHARED comparator (#642): decode the
        # transistor deck's sampler strobes rail-bounded (an XSPICE out_undef
        # X at vdd/2 is a named problem, never a silent 0), replay the
        # normative model exactly as compare-gate-model.py does, and score the
        # rdata_k*/odata_k*/<sig>_k* checks with its cycle mapping.
        inputs = P.cycle_inputs(cycles)
        captured: list[int] = []
        mismatches = []
        checks = 0
        for k, inp in enumerate(inputs):
            if not inp["raw_valid"]:
                continue
            checks += 1
            valid = P.decode(m[f"raw_valid_k{k}"], vdd)
            if valid != 1:
                mismatches.append(f"raw_valid_k{k}: transistor {valid} != model 1")
            bit = P.decode(m[f"raw_bit_k{k}"], vdd)
            if bit is None:
                mismatches.append(f"raw_bit_k{k}: level {m[f'raw_bit_k{k}']!r} V is not a resolved rail")
                bit = 0  # keep the replay's bit budget; the corner is already UNMET
            captured.append(bit)
        rows = P.model_replay(captured)
        resp, undecodable = P.response_checks(m, rows, vdd, len(cycles))
        compared = [c for c in resp if not c.get("not_compared")]
        checks += len(compared)
        mismatches += [f"{c['measurement']}: transistor {c['simulated']} != model {c['model']}"
                       for c in compared if not c["match"]]
        mismatches += [f"{u['measurement']}: level {u['value']!r} V is not a resolved rail"
                       for u in undecodable]
        out["oracle"] = {"checks": checks, "mismatches": mismatches, "match": not mismatches and checks > 0}
    if mismatches or checks == 0:
        problems.append(f"oracle: {len(mismatches)} mismatch(es) in {checks} comparison(s)"
                        + (f"; first: {mismatches[0][:160]}" if mismatches else ""))

    # supply currents: i(Vsrc) is negative when the source delivers current
    cur = {}
    for r in P.RAILS:
        cur[r] = {"w1_a": -m[f"i_{r}_w1"], "w2_a": -m[f"i_{r}_w2"]}
    p_active = sum(vdd * cur[r]["w2_a"] for r in P.RAILS)
    # W1 = rings running, digital reset-held with clk not started (leakage-dominated digital)
    d_vdd = cur["vdd"]["w2_a"] - cur["vdd"]["w1_a"]
    out["power"] = {
        "vdd_v": vdd, "currents_a": cur,
        "p_active_w": p_active,
        "digital_delta_i_a": d_vdd,
        "digital_dynamic_power_w_estimate": vdd * d_vdd,
        "basis": "W2 = every program cycle (clock running at TS); W1 = reset held, clk not started; "
                 "dynamic = (I_vdd[W2]-I_vdd[W1])*Vdd, includes the activity of THIS directed program only",
        "recompute_check_w": sum(vdd * -m[f"i_{r}_w2"] for r in P.RAILS),
    }
    t_first = m.get("t_out_valid_first")
    out["timing"] = {"t_out_valid_first_s": t_first,
                     "throughput_note": "time of first out_valid rise from t=0 (raw-tap word of 32 samples at TS)"}
    return out


def planned_points(plan_corners: dict) -> list[tuple[str, float, float]]:
    """The (process, T, Vdd) points a plan's ``corners`` axes enumerate."""
    procs = plan_corners.get("process") or []
    temps = plan_corners.get("temperature_c") or []
    vdds = (plan_corners.get("supply_v") or {}).get("Vvdd") or []
    return [(p, float(t), float(v)) for p in procs for t in temps for v in vdds]


def corner_plan_mismatch(corner: dict, plan_corners: dict) -> str | None:
    """``None`` when the report's corner is one of the plan's points on every
    rail of ``RAILS``; else why it is not (#815)."""
    proc, temp = corner.get("process"), corner.get("temperature_c")
    supply = corner.get("supply_v") or {}
    if proc not in (plan_corners.get("process") or []):
        return f"process {proc!r} is not one of the plan's {plan_corners.get('process')}"
    if temp is None or float(temp) not in [float(t) for t in plan_corners.get("temperature_c") or []]:
        return f"temperature {temp!r} C is not one of the plan's {plan_corners.get('temperature_c')}"
    for rail in P.RAILS:
        axis = [float(x) for x in (plan_corners.get("supply_v") or {}).get(f"V{rail}") or []]
        v = supply.get(f"V{rail}")
        if v is None or float(v) not in axis:
            return f"{rail} at {v!r} V is not one of the plan's {axis} V"
    return None


def collect(corners_dir: Path) -> tuple[dict, list[dict]]:
    """Map point key -> the report entries claiming it; plus the source requests.

    Every ``grid-*`` report is matched against its own ``plan.json`` /
    ``request.json`` first (#815): the deck the report ran must be the one the
    plan hashed, and each corner must be one of the plan's points on all five
    rails. A report that fails either is kept as an entry carrying its
    ``problems`` -- on the point it *reports* and on the point its plan
    *asked for* -- so both show UNMET with the reason, and nothing is
    silently re-assigned. No entry is ever overwritten: a second report
    claiming a point is a second entry, which :func:`reduce` refuses.
    """
    found: dict[str, list[dict]] = {}
    sources: list[dict] = []
    for rep in sorted(corners_dir.glob("*/report.json")):
        d = rep.parent
        src = {"dir": d.name, "report": str(rep.relative_to(REPO)) if rep.is_relative_to(REPO) else str(rep), "report_sha256": sha256(rep)}
        for extra in ("request.json", "plan.json"):
            if (d / extra).exists():
                src[extra] = sha256(d / extra)
        plan = json.loads((d / "plan.json").read_text()) if (d / "plan.json").exists() else {}
        request = json.loads((d / "request.json").read_text()) if (d / "request.json").exists() else None
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
        coupled = plan.get("raw_source") == "analog_sampler"
        src["deck"] = "coupled (analog sampler -> gate model)" if coupled else "flat transistor-level"
        if not d.name.startswith("grid-"):
            continue   # controls/probes are listed as sources but never count toward the matrix
        plan_c = plan.get("corners") or {}
        decks = (plan.get("gate_model_pvt") or {}).get("decks") or {}
        # problems that disqualify every corner of this report: the report
        # did not run the deck its plan hashed, or request and plan disagree
        pre: list[str] = []
        env_sha = (doc.get("environment") or {}).get("netlist_sha256")
        if env_sha is not None and plan.get("netlist_sha256") is not None and env_sha != plan["netlist_sha256"]:
            pre.append(f"report netlist sha256 {env_sha[:16]} != its plan's {plan['netlist_sha256'][:16]}: "
                       "the report did not run the planned deck")
        if request is not None and request.get("corners") != plan_c:
            pre.append("request.json corners differ from plan.json corners")
        matched: set[str] = set()
        for c in doc.get("corners", []) or []:
            t = c.get("temperature_c")
            v = (c.get("supply_v") or {}).get("Vvdd")
            if t is None or v is None:
                continue
            k = key(c.get("process"), float(t), float(v))
            problems = list(pre)
            if plan_c:
                why = corner_plan_mismatch(c, plan_c)
                if why is None:
                    matched.add(k)
                else:
                    problems.append(f"report corner {k} does not match its plan: {why}")
            found.setdefault(k, []).append({
                "source": d.name, "corner": c, "remote": remote, "problems": problems,
                "coupled": coupled, "gate_model_sha256": plan.get("gate_model_sha256"),
                "digital_deck": decks.get(c.get("process"))})
        for pp in planned_points(plan_c):
            k = key(*pp)
            if k in matched:
                continue
            if "error" in doc:
                why = "klt error envelope: " + (doc["error"].get("message") or "")[:300]
            elif pre:
                why = "its report did not run the planned request: " + "; ".join(pre)
            else:
                why = "no corner of its report covers this planned point"
            why = f"planned point {k}: {why}"
            # the report's own mismatched corner already claims this key (it
            # reports the point but not as planned): the same report's two
            # findings belong to one entry, not to a second claimant
            same = [e for e in found.get(k, []) if e["source"] == d.name]
            if same:
                for e in same:
                    e["problems"].append(why)
            else:
                found.setdefault(k, []).append({"source": d.name, "corner": None, "remote": remote,
                                                "problems": [why], "coupled": coupled})
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


#: the per-point Liberty mapping row a coupled point's result carries (#815)
_DECK_FIELDS = ("liberty_deck", "liberty_sha256", "exact", "dT_K", "dV_V", "delay_direction",
                "est_delay_error_pct", "power_direction")


def reduce(corners_dir: Path, ir_summary: Path | None, provenance=_DEFAULT) -> dict:
    if provenance is _DEFAULT:
        provenance = P.PROVENANCE
    found, sources = collect(corners_dir)
    points = []
    for proc, t, v in expected_points():
        k = key(proc, t, v)
        cands = found.get(k, [])
        row = {"point": k, "process": proc, "temperature_c": t, "vdd_v": v}
        if not cands:
            row.update(status="UNMET", reasons=["no report covers this point (never submitted or never returned)"])
        elif len(cands) > 1:
            # never pick one: two reports claiming one point is a filing error
            # until a human resolves it, whichever of them would pass
            srcs = sorted({c["source"] for c in cands})
            row.update(status="UNMET", source=srcs[0], sources=srcs,
                       reasons=[f"{len(cands)} report entries from {srcs} claim this point: "
                                "refusing to pick one"])
        else:
            ent = cands[0]
            pre = ent["problems"]
            if ent.get("corner") is None or pre:
                # no corner of this report, or one that is not the planned
                # point on the planned deck: nothing here is this point's
                # evidence, so nothing is scored -- the reasons say why
                row.update(status="UNMET", reasons=list(pre), source=ent["source"], remote=ent.get("remote"))
            else:
                res = analyse_corner(ent["corner"], v, coupled=ent.get("coupled", False))
                row.update(source=ent["source"], remote=ent.get("remote"))
                row.update({kk: vv for kk, vv in res.items() if kk != "problems"})
                row["status"] = "MET" if not res["problems"] else "UNMET"
                row["reasons"] = res["problems"]
                if ent.get("coupled"):
                    row["gate_model_sha256"] = ent.get("gate_model_sha256")
                    deck = ent.get("digital_deck")
                    if deck:
                        row["digital_deck"] = {f: deck[f] for f in _DECK_FIELDS if f in deck}
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
        L.append(f"- `{s['dir']}`: status `{s['status']}`, deck `{s.get('deck', 'n/a')}`, "
                 f"report sha256 `{s['report_sha256'][:16]}`, "
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
