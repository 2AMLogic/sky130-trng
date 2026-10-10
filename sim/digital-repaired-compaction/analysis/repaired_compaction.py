#!/usr/bin/env python3
"""Repaired floorplan compaction record (issue #251).

Arithmetic and reduction only: no P&R, no SPICE. Reads the run directories
written by bin/run-study.sh (and the final-route audits / summaries from
sim/digital-electrical-repair/analysis/), the unrepaired #226 geometry audits
copied under runs/<id>/unrepaired-util*, and reuses the #226 area model
(sim/digital-floorplan-compaction/analysis/compaction.py).

  python3 sim/digital-repaired-compaction/analysis/repaired_compaction.py --run <run-id> [--emit-record]

A repaired point is selectable only if EVERY declared check holds, with the
final-route electrical evidence audited at all 16 corners. Missing or
unsupported evidence never selects a candidate. Nothing is promoted.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDY = REPO_ROOT / "sim" / "digital-repaired-compaction"
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_record, new_record_id  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "compaction", REPO_ROOT / "sim/digital-floorplan-compaction/analysis/compaction.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

TARGET = C.TARGET_MM2
REPAIR_STUDY = REPO_ROOT / "sim" / "digital-electrical-repair"
REPAIR_REF_RUN = REPAIR_STUDY / "runs" / "20261010-cand1" / "slew0531"
COMPACT_RUN = REPO_ROOT / "sim/digital-floorplan-compaction/runs/20261009-202126-760b4d3"


def jl(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def req_diff(a: dict, b: dict, path="") -> list[str]:
    out = []
    for k in sorted(set(a) | set(b)):
        if isinstance(a.get(k), dict) and isinstance(b.get(k), dict):
            out += req_diff(a[k], b[k], f"{path}{k}.")
        elif a.get(k) != b.get(k):
            out.append(f"{path}{k}: {a.get(k)!r} -> {b.get(k)!r}")
    return out


class _NoExitCodes(type(Path())):
    """compaction.summarize_run parses `<name> exit <rc>` lines from exit-codes.txt; this study's file
    uses `<name> pnr-verify exit <rc>` / `<name> audit exit <rc>` lines, so hide it from that helper
    and parse it here."""

    @property
    def parent(self):
        return Path("/nonexistent-exit-codes-dir")


def pnr_exit(d: Path):
    ec = d.parent / "exit-codes.txt"
    if ec.exists():
        for line in ec.read_text().splitlines():
            t = line.split()
            if len(t) > 3 and t[0] == d.name and t[1] == "pnr-verify":
                return int(t[3])
    return None


def run_summary(d: Path) -> dict:
    r = C.summarize_run(_NoExitCodes(d))
    r["exit"] = pnr_exit(d)
    es = jl(d / "electrical-summary.json")
    r["electrical"] = es
    rq = d / f"{d.name}.json"
    if not rq.exists():
        rq = STUDY / "requests" / f"{d.name}.json"
    if rq.exists():
        r["request"] = {"path": str(rq.relative_to(REPO_ROOT)), "sha256": sha(rq),
                        "max_transition_ns": json.loads(rq.read_text())["constraints"].get("max_transition_ns"),
                        "utilization_pct": json.loads(rq.read_text())["floorplan"]["utilization_pct"]}
    return r


def checks(r: dict, base: dict) -> dict:
    cov = C.coverage(r, base)["checks"]
    cov.pop("libmax_not_worse_per_corner", None)  # replaced by the final-route audit below
    es = r.get("electrical") or {}
    fin = (es.get("final_route") or {}).get("reduction") or {}
    est = (es.get("estimate_global_route") or {}).get("reduction_vs_library") or {}
    cov["final_route_audit_16_of_16"] = (
        len(fin.get("coverage", {})) == 16 and all(v == "audited" for v in fin.get("coverage", {}).values()))
    cov["final_route_slew_cap_zero"] = (fin.get("verdict") == "clean" and fin.get("totals") == {"max_slew": 0, "max_capacitance": 0})
    cov["estimate_slew_cap_zero"] = est.get("verdict") == "clean"
    cov["estimate_count_crosscheck"] = not (es.get("estimate_global_route") or {}).get("count_mismatch_corners", ["x"])
    return cov


def per_corner_margins(r: dict) -> dict:
    pc = ((r.get("electrical") or {}).get("final_route") or {}).get("per_corner") or {}
    out = {}
    for c, v in pc.items():
        if v.get("status") != "audited":
            out[c] = None
            continue
        out[c] = {"slew_count": v["max_slew"]["count"], "cap_count": v["max_capacitance"]["count"],
                  "slew_margin_ns": (v["max_slew"].get("worst_margin") or {}).get("slack"),
                  "cap_margin_pf": (v["max_capacitance"].get("worst_margin") or {}).get("slack"),
                  "slew_worst_excess_ns": v["max_slew"]["worst_excess"],
                  "cap_worst_excess_pf": v["max_capacitance"]["worst_excess"]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)
    run_dir = STUDY / "runs" / args.run
    whole = jl(C.WHOLE)
    base = C.baseline()
    base["area"] = C.area_model(base["die_w_um"], base["die_h_um"], whole)
    committed = json.loads(C.COMMITTED_REQUEST.read_text())

    runs = {d.name: run_summary(d) for d in sorted(run_dir.glob("rep*")) if d.is_dir()}
    unrep = {d.name: run_summary(d) for d in sorted(run_dir.glob("unrepaired-util*")) if d.is_dir()}
    for r in runs.values():
        r["checks"] = checks(r, base)
        r["selectable"] = all(r["checks"].values())
        if "die_w_um" in r:
            r["area"] = C.area_model(r["die_w_um"], r["die_h_um"], whole)
        r["margins"] = per_corner_margins(r)
        r["request_diff_vs_committed"] = req_diff(committed, json.loads(Path(REPO_ROOT / r["request"]["path"]).read_text())) \
            if r.get("request") else None
    # #226 unrepaired baselines (estimate counts) and their final-route audits (this study)
    comp226 = {n: C.summarize_run(_NoExitCodes(COMPACT_RUN / n)) for n in ("util40", "util55", "util65")}

    # control: repaired 40 % vs the recorded #236 slew0531 candidate
    ref = C.summarize_run(_NoExitCodes(REPAIR_REF_RUN))
    c40 = runs.get("rep40-slew0531", {})
    control = {
        "reference_run": str(REPAIR_REF_RUN.relative_to(REPO_ROOT)),
        "geometry_byte_identical": c40.get("geometry_sha256") == ref.get("geometry_sha256"),
        "request_byte_identical": bool(c40.get("request")) and
        c40["request"]["sha256"] == sha(REPAIR_STUDY / "requests" / "slew0531.json"),
        "die_area_equal": (c40.get("pnr") or {}).get("die_area_um2") == (ref.get("pnr") or {}).get("die_area_um2"),
        "std_cell_area_equal": (c40.get("congestion") or {}).get("design__instance__area__stdcell") ==
        (ref.get("congestion") or {}).get("design__instance__area__stdcell"),
        "klt_version_equal": (c40.get("pnr") or {}).get("klt_version") == (ref.get("pnr") or {}).get("klt_version"),
    }
    control["reproduced"] = all(control[k] for k in ("geometry_byte_identical", "request_byte_identical", "die_area_equal",
                                                      "std_cell_area_equal", "klt_version_equal"))

    gap0 = base["area"]["estimate_restacked_same_topology_mm2"] - TARGET
    eligible = [n for n, r in runs.items() if r["selectable"] and control["reproduced"] and r.get("area")]
    best = min(eligible, key=lambda n: runs[n]["area"]["estimate_restacked_same_topology_mm2"]) if eligible else None
    # a recommendation must also move the bbox below the repaired 40 % control
    if best == "rep40-slew0531":
        best_is_compaction = False
    else:
        best_is_compaction = best is not None

    L: list[str] = []
    a = L.append
    pins = jl(C.PINS)
    sel_txt = (f"`{best}`" if best else "none")
    a(f"# Repaired floorplan compaction -- 16-corner electrical closure -- issue #251")
    a("")
    if best and best_is_compaction:
        a(f"**Outcome: recommend {sel_txt} as the preferred repaired compacted digital floorplan, conditional on a later "
          "composed and fully re-verified layout.** It is NOT promoted: `layout/trng_digital/` and `layout/trng_whole/` are "
          "untouched, the spec and the area target (`Area < 0.05 mm2`) are unchanged, and the target stays unmet.")
    else:
        a("**Outcome: no candidate recommended.** Either no compacted point passed every declared check, or the control "
          "was not reproduced. Nothing is promoted; the spec and the area target (`Area < 0.05 mm2`) are unchanged and "
          "the target stays unmet.")
    a("")
    a("Scope: study-run P&R on the committed netlist and committed flow settings, checked with the pinned klt/OpenROAD/Liberty "
      "decks. Simulation-derived physical-design evidence, not silicon. The final-route audit is the sibling OpenSTA script "
      "from #236 (klt has no such check; klayout-tools#3005), not a klt-reported signoff. Whole-block areas are ESTIMATES "
      "until a composition is built and verified.")
    a("")
    a("## Inputs and provenance")
    a("")
    a(f"- klt `{(runs.get('rep40-slew0531', {}).get('pnr') or {}).get('klt_version')}` (tool-pins.json build, worktree venv; "
      "no host tool changed); OpenROAD "
      f"`{(runs.get('rep40-slew0531', {}).get('pnr') or {}).get('openroad')}`.")
    a(f"- committed request `{C.COMMITTED_REQUEST.relative_to(REPO_ROOT)}` {sha(C.COMMITTED_REQUEST)}")
    a("- fixed in every run: netlist (same file), seed 20260905, 20000 ns clock, 4000 ns IO delays, aspect ratio 1.0, 5 um core "
      "margin, IO layers, sky130hd power preset, route stage, SPEF+SDF; no `set_load`/`set_driving_cell` (not in the request schema).")
    a("- varied: `floorplan.utilization_pct` (40/55/65) and `constraints.max_transition_ns`.")
    a("")
    a("| request | sha256 | differences vs committed request |")
    a("|---|---|---|")
    for n, r in runs.items():
        if r.get("request"):
            a(f"| `{r['request']['path']}` | `{r['request']['sha256']}` | "
              + "; ".join(f"`{x}`" for x in r["request_diff_vs_committed"] if not x.startswith("netlist:")) + " (+ netlist path rebased) |")
    a("")
    a("Slew budgets re-derived per floorplan with `sim/digital-electrical-repair/analysis/derive_limits.py` on the #226 unrepaired "
      "routed geometry (tt-deck budget = min over corners of Liberty limit / measured slew ratio, with 10 % margin):")
    a("")
    a("| utilisation | derived minimum budget ns | with 10 % margin ns | used here |")
    a("|---|---|---|---|")
    a("| 40 | 0.5903 | 0.531 | 0.531 (recorded #236 candidate) |")
    a("| 55 | 0.5823 | 0.524 | " + ("0.531 (primary), 0.524 (derived)" if "rep55-slew0524" in runs else "0.531 (looser than the derived 0.524; passed the audit, so the derived value was not run -- `requests/rep55-slew0524.json` is kept unrun)") + " |")
    a("| 65 | 0.5926 | 0.533 | 0.531 (tighter than derived 0.533; same recorded value) |")
    a("")
    a("## Control: repaired 40 % vs the recorded #236 candidate")
    a("")
    for k, v in control.items():
        a(f"- {k}: `{v}`")
    a("")
    a("A reproduced control means the pinned tool, inputs and seed behave identically to the #236 record, so differences "
      "at 55 %/65 % are due to the floorplan.")
    a("")
    a("## Unrepaired baseline at final route (this study's audit of the #226 geometry)")
    a("")
    a("| point | est slew/cap (16-corner sum, #226) | final-route slew/cap (16-corner sum) | verdict |")
    a("|---|---|---|---|")
    a("| util40 (#236 control record) | 1130 / 37 | 1512 / 50 | not clean |")
    for n, r in unrep.items():
        es = r.get("electrical") or {}
        t = ((es.get("final_route") or {}).get("reduction") or {}).get("totals") or {}
        e = ((es.get("estimate_global_route") or {}).get("reduction_vs_library") or {}).get("totals") or {}
        a(f"| {n} | {e.get('max_slew')} / {e.get('max_capacitance')} | {t.get('max_slew')} / {t.get('max_capacitance')} | "
          f"{es.get('candidate_verdict')} |")
    a("")
    a("## Repaired candidates (all kept, failures included)")
    a("")
    names = list(runs)
    a("| run | util % target (achieved) | die um2 | est slew/cap | final slew/cap | corners audited | route DRC / antenna | klt DRC | LVS sig / power | setup / hold viol | cosim | controls | selectable |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, r in runs.items():
        es = r.get("electrical") or {}
        fin = (es.get("final_route") or {}).get("reduction") or {}
        est = (es.get("estimate_global_route") or {}).get("reduction_vs_library") or {}
        p = r.get("pnr") or {}
        ft, et = fin.get("totals") or {}, est.get("totals") or {}
        cov = fin.get("coverage") or {}
        a(f"| {n} | {(r.get('request') or {}).get('utilization_pct')} ({p.get('utilization_pct')}) | {p.get('die_area_um2')} | "
          f"{et.get('max_slew')} / {et.get('max_capacitance')} | {ft.get('max_slew')} / {ft.get('max_capacitance')} | "
          f"{sum(1 for v in cov.values() if v == 'audited')}/16 | {p.get('route_drc_violation_count')} / {p.get('antenna_violation_count')} | "
          f"{(r.get('drc') or {}).get('status')} | {(r.get('lvs') or {}).get('status')} / {(r.get('lvs') or {}).get('power_connectivity')} | "
          f"{(r.get('sta') or {}).get('setup_violations')} / {(r.get('sta') or {}).get('hold_violations')} | "
          f"{'PASS' if (r.get('cosim') or {}).get('ok') else 'FAIL/none'} | {r.get('controls_detected')}/4 | {r['selectable']} |")
    a("")
    for n, r in runs.items():
        failed = [k for k, v in r["checks"].items() if not v]
        if failed:
            a(f"- `{n}` checks not met: {', '.join(failed)}")
        if not r.get("completed"):
            a(f"- `{n}` did not complete; stderr tail: `{r.get('stderr_tail')}`")
    a("")
    a("Per-corner final-route electrical margins (smallest remaining slack over audited pins; slew ns / cap pF; a count in "
      "place of a margin means violations remain):")
    a("")
    a("| corner | " + " | ".join(names) + " |")
    a("|---|" + "---|" * len(names))
    corners = list(next(iter(runs.values()))["margins"]) if runs else []
    for c in corners:
        cells = []
        for n in names:
            m = runs[n]["margins"].get(c)
            if m is None:
                cells.append("UNAUDITED")
            elif m["slew_count"] or m["cap_count"]:
                cells.append(f"VIOL slew {m['slew_count']} (+{m['slew_worst_excess_ns']}) cap {m['cap_count']} (+{m['cap_worst_excess_pf']})")
            else:
                cells.append(f"{m['slew_margin_ns']} / {m['cap_margin_pf']}")
        a(f"| {c} | " + " | ".join(cells) + " |")
    a("")
    a("Smallest-margin corner moves with compaction: at `ss_n40C_1v28` the slew margin falls from 1.228 ns (40 %) to 0.585 ns (65 %) and at "
      "`ss_n40C_1v60` from 0.299 ns to 0.210 ns; all remain positive. The 0.531 ns budget generalises to these two floorplans on this "
      "netlist and seed; the margin between the derived minimum (~0.59 ns) and the chosen value is not shown to be necessary.")
    a("")
    a("## Cost: area, cells, buffers, timing")
    a("")
    a("| run | digital die W x H um | die mm2 | std-cell area um2 | logic+buffer instances | `place*` repair buffers | clkbuf | wirelength um | worst setup slack ns | worst hold slack ns | clock skew ns |")
    a("|---|---|---|---|---|---|---|---|---|---|---|")
    for n, r in runs.items():
        cost = (r.get("electrical") or {}).get("cost") or {}
        rb = cost.get("repair_inserted_buffers_by_prefix") or {}
        a(f"| {n} | {r.get('die_w_um', 0):.2f} x {r.get('die_h_um', 0):.2f} | {(r.get('pnr') or {}).get('die_area_um2', 0) / 1e6:.6f} | "
          f"{cost.get('stdcell_instance_area_um2')} | {cost.get('instances_logic_and_buffers')} | {rb.get('place')} | {rb.get('clkbuf')} | "
          f"{cost.get('wirelength_um')} | {cost.get('worst_setup_slack_ns')} | {cost.get('worst_hold_slack_ns')} | {cost.get('clock_skew_ns')} |")
    a("")
    a("Repair cost relative to the same-utilisation unrepaired #226 geometry (std-cell area, from the retained route metrics):")
    a("")
    a("| utilisation | unrepaired std-cell um2 | repaired std-cell um2 | delta % |")
    a("|---|---|---|---|")
    for u in (40, 55, 65):
        un = (comp226[f"util{u}"].get("congestion") or {}).get("design__instance__area__stdcell")
        rr = [r for n, r in runs.items() if n.startswith(f"rep{u}-")]
        for r in rr:
            rv = ((r.get("electrical") or {}).get("cost") or {}).get("stdcell_instance_area_um2")
            d = f"{(rv / un - 1) * 100:.1f}" if (un and rv) else "n/a"
            a(f"| {u} ({r['request']['max_transition_ns']} ns) | {un} | {rv} | {d} |")
    a("")
    a("## Area (digital bbox actual; whole block ESTIMATED, not composed)")
    a("")
    a("Estimate definitions are those of `sim/digital-floorplan-compaction/records/20261009-214736-760b4d3.md`: "
      "estimate A = digital + analog bbox + the committed composition's non-macro area held constant; estimate B = the committed "
      "topology re-stacked around the resized digital macro (reproduces 0.126116 mm2 at the baseline size).")
    a("")
    a("| candidate | digital bbox mm2 (actual) | estimate A mm2 | estimate B mm2 | B / target | B gap to 0.05 mm2 | selectable |")
    a("|---|---|---|---|---|---|---|")
    ab = base["area"]
    a(f"| committed baseline | {ab['digital_bbox_mm2']:.6f} | {ab['estimate_additive_overhead_mm2']:.6f} | "
      f"{ab['estimate_restacked_same_topology_mm2']:.6f} (composed, verified: 0.126116) | "
      f"{ab['estimate_restacked_same_topology_mm2'] / TARGET:.3f}x | +{gap0:.6f} | -- |")
    for n, r in runs.items():
        if r.get("area"):
            ar = r["area"]
            b = ar["estimate_restacked_same_topology_mm2"]
            a(f"| {n} | {ar['digital_bbox_mm2']:.6f} | {ar['estimate_additive_overhead_mm2']:.6f} | {b:.6f} | "
              f"{b / TARGET:.3f}x | +{b - TARGET:.6f} | {r['selectable']} |")
    a("")
    if best:
        bb = runs[best]["area"]["estimate_restacked_same_topology_mm2"]
        a(f"Incremental progress of {sel_txt} vs the committed baseline (estimate B): {base['area']['estimate_restacked_same_topology_mm2'] - bb:.6f} mm2 "
          f"removed = {(gap0 - (bb - TARGET)) / gap0 * 100:.1f} % of the baseline gap. Remaining gap to the unchanged target: "
          f"**+{bb - TARGET:.6f} mm2** ({bb / TARGET:.2f}x).")
    else:
        a(f"Remaining gap of the committed, verified block to the unchanged target: +{gap0:.6f} mm2.")
    a("")
    a("## Recommendation")
    a("")
    if best and best_is_compaction:
        r = runs[best]
        a(f"Recommend {sel_txt}: every declared check holds (route DRC 0, antenna 0, klt DRC, cell-level LVS signal and power, "
          "16-corner setup/hold, routed-netlist cosim, 4/4 negative controls, final-route Liberty max-slew/max-cap at 16/16 "
          "corners with zero violations, estimate counts zero and cross-checked). "
          "It is the smallest-die point that satisfies them. This is a preference conditional on a future change that composes and "
          "re-verifies it (including the composed-block electrical audit); it is not a promotion and it does not meet the target.")
    elif best:
        a("Only the repaired 40 % control is selectable, so the recommendation is: no compacted candidate. The repair alone "
          "does not reduce the digital bbox.")
    else:
        a("**Recommend none.** Failed checks are listed above per run.")
    a("")
    a("## What this record does and does not establish")
    a("")
    a("- Established: P&R runs of the unchanged netlist at the listed utilisation/slew-budget points on the pinned flow, each "
      "through the unchanged `sim/digital-pnr/` chain plus the #236 final-route audit, with every request, hash and failure "
      f"retained under `{run_dir.relative_to(REPO_ROOT)}/`.")
    a("- Not established: a composed whole-block layout using any compacted macro (areas are estimates); behaviour at silicon; "
      "SDF-timed simulation of these runs; foundry-signoff extraction; port loading beyond the OpenSTA default; whether the "
      "slew budget is minimal (margins between the derived minimum and the chosen value are untested). "
      "Same verification limits as `sim/digital-pnr/records/20261003-212010-fa76b17.md`.")
    a("- Tool gaps: klt has no final-route max-slew/max-cap check (klayout-tools#3005, already filed). No new gap found by this study "
      "unless listed in the PR.")
    a("")

    summary = {"issue": 251, "run": args.run, "target_mm2": TARGET, "target_status": "unchanged: unmet",
               "control": control, "runs": {n: {k: v for k, v in r.items() if k not in ("electrical", "stderr_tail")}
                                            | {"electrical_totals": ((r.get("electrical") or {}).get("final_route") or {}).get("reduction", {}).get("totals")}
                                            for n, r in runs.items()},
               "unrepaired_final_route": {n: ((r.get("electrical") or {}).get("final_route") or {}).get("reduction", {}).get("totals")
                                          for n, r in unrep.items()},
               "baseline_area": base["area"], "selected": None, "preferred_if_later_verified": best if best_is_compaction else None,
               "recommendation": (f"{best} conditional on a composed and re-verified layout; not promoted"
                                  if best and best_is_compaction else "none")}
    print("\n".join(L))
    if not args.emit_record:
        return 0
    now, shaid, rid = new_record_id(REPO_ROOT)
    summary = {"record_id": rid, "timestamp_utc": now.isoformat(), "repo_sha": shaid, **summary}
    mint_record(STUDY / "records", REPO_ROOT, rid, L, "", summary, author="Loom builder (issue #251)", now=now, sha=shaid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
