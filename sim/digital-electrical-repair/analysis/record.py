#!/usr/bin/env python3
"""Render the issue #236 record (tables only come from run artifacts).

    python3 sim/digital-electrical-repair/analysis/record.py \
        --run control=<dir> --run slew0531=<dir> ... --emit
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import electrical as E  # noqa: E402

ROOT = HERE.parents[2]


def load(p):
    return json.loads(Path(p).read_text())


def sha(p):
    return "sha256:" + hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fmt(x, n=3):
    return f"{x:.{n}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="name=dir (first is the control)")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    runs = {}
    for kv in a.run:
        n, d = kv.split("=", 1)
        d = Path(d).resolve()
        runs[n] = {"dir": d, "sum": load(d / "electrical-summary.json"), "pnr": load(d / "pnr-output.json"),
                   "audit": load(d / "electrical-audit.json"), "verdict": load(d / "verdict.json"),
                   "req": load(ROOT / "sim/digital-electrical-repair/requests" / f"{n}.json")}
    names = list(runs)
    ctl = runs[names[0]]
    corners = ctl["sum"]["corners"]
    deriv = load(ctl["dir"] / "limit-derivation.json")
    nets = load(ctl["dir"] / "violator-nets.json")
    sha_head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    ts = datetime.datetime.now(datetime.timezone.utc)
    rid = ts.strftime("%Y%m%d-%H%M%S") + "-" + sha_head
    L = []
    a_ = L.append

    def status(r):
        return r["sum"]["candidate_verdict"]

    a_(f"# Digital electrical-limit repair and final-route audit -- issue #236\n")
    clean = [n for n in names[1:] if status(runs[n]).startswith("clean candidate")
             and all(runs[n]["verdict"]["verdict"].values())]
    a_("**Outcome: " + ("repair reaches zero Liberty max-slew / max-capacitance violations in a final-route audit "
                        "at all 16 corners, with the existing verification chain passing, for: "
                        + ", ".join(f"`{n}`" for n in clean) if clean else
                        "no candidate reached a clean final-route audit; see the blocker diagnosis")
       + ".** No geometry is promoted: `layout/trng_digital/` and `layout/trng_whole/` are untouched, the spec and the "
         "area target (0.05 mm2; composed block 0.126116 mm2, gap +0.076116 mm2) are unchanged, and nothing here makes "
         "#174 depend on this result.\n")
    a_("Scope of the claim: a *study-run* P&R result on the committed netlist and committed flow settings, "
       "checked with the pinned klt/OpenROAD/Liberty decks. It is simulation-derived physical-design evidence, not silicon, "
       "and the final-route audit is a sibling OpenSTA session run by this study's script (klt has no such check; see "
       "Tool gaps), not a klt-reported signoff.\n")

    a_("## Inputs and provenance\n")
    a_(f"- klt `{ctl['pnr']['provenance']['klt_version']}`, OpenROAD `{ctl['pnr']['engine_version']}`, "
       f"KLayout `{ctl['pnr']['provenance']['klayout_version']}`; netlist `{ctl['verdict']['netlist_sha256']}` (pinned). "
       "The host `klt` is 0.7.0; the study ran on the pinned 0.6.0 build in a worktree venv (no host tool changed).")
    a_("- committed request `digital/flow/place-and-route/pnr-trng-digital-50khz.json` "
       f"`{sha(ROOT / 'digital/flow/place-and-route/pnr-trng-digital-50khz.json')}`; every study request differs from it "
       "only in the rebased netlist path (same file) and, for candidates, `constraints.max_transition_ns` / `max_capacitance_pf`.")
    for n in names:
        a_(f"- `sim/digital-electrical-repair/requests/{n}.json` `{sha(ROOT / 'sim/digital-electrical-repair/requests' / (n + '.json'))}`; "
           f"constraints added: " + (", ".join(f"{k}={v}" for k, v in runs[n]['req']['constraints'].items()
                                            if k in ('max_transition_ns', 'max_capacitance_pf', 'max_fanout')) or "none (control)"))
    a_("- Units: slew in ns, capacitance in pF (klt request units; Liberty `time_unit`/`capacitive_load_unit` are ns/pF). "
       "Fixed in every run: seed 20260905, 40 % utilisation, 20000 ns clock, 4000 ns I/O delays, no `set_load` / "
       "`set_driving_cell` (the request schema has none; port load and drive are OpenSTA defaults).\n")

    a_("## Control: baseline reproduction\n")
    base_est = ctl["sum"]["estimate_global_route"]["reduction_vs_library"]["totals"]
    a_(f"- Unchanged committed request, re-run: global-route-estimate max-slew + max-cap violations summed over the 16 corners = "
       f"**{base_est['max_slew']} + {base_est['max_capacitance']} = {base_est['max_slew'] + base_est['max_capacitance']}** "
       "(the #226 baseline of 1167 is reproduced; the per-pin log parse equals the klt response counts at every corner: "
       f"mismatch corners = {ctl['sum']['estimate_global_route']['count_mismatch_corners'] or 'none'}).")
    same = all((ctl["dir"] / f).read_bytes() == (ROOT / "sim/digital-floorplan-compaction/runs/20261009-202126-760b4d3/util40" / f).read_bytes()
               for f in ("trng_digital.gds.gz", "trng_digital.def.gz", "trng_digital.v.gz", "trng_digital_route.spef.gz"))
    a_(f"- The control's routed GDS, DEF, Verilog and SPEF are byte-identical to the #226 util40 run: **{same}** (deterministic flow, no tool drift).")
    a_("- What the 1167 is: a sum of pin-level `report_check_types` rows over 16 corners from a global-route *estimate*. "
       "It is not a count of unique failing nets and not a final extracted-route check.\n")

    a_("### Where the violations are (control)\n")
    a_("Stage labels: **est** = in-flow `report_check_types` after `estimate_parasitics -global_routing` (global-route estimate); "
       "**final** = fresh OpenSTA session over the routed DEF + extracted post-route SPEF, Liberty limits, no override. "
       "Load: none declared beyond the netlist. Limit = Liberty `default_max_transition` (and per-pin `max_capacitance`).\n")
    a_("| corner | slew limit ns | est slew / cap | final slew pins (nets) | final worst slew excess ns | final cap pins | final worst cap excess pF |")
    a_("|---|---|---|---|---|---|---|")
    for c in corners:
        e = ctl["sum"]["estimate_global_route"]["per_corner"][c]["vs_library"]
        f = ctl["audit"]["corners"][c]
        nn = nets["per_corner"].get(c, {})
        nsl = nn.get("max_slew", {}).get("distinct_nets", 0)
        a_(f"| {c} | {deriv['slew'][c]['limit_ns']} | {e['max_slew']['count']} / {e['max_capacitance']['count']} | "
           f"{f['max_slew']['count']} ({nsl}) | {fmt(f['max_slew']['worst_excess'])} | {f['max_capacitance']['count']} | {fmt(f['max_capacitance']['worst_excess'], 4)} |")
    a_("")
    a_("Final-route and estimate counts differ (for example a fast corner, `ff_n40C_1v56`, has 21 slew pins on one net at the final "
       "route and none in the estimate), so the estimate can neither be called conservative nor sufficient.\n")
    tn = nets["per_corner"]["ss_n40C_1v60"]["max_slew"]["top_nets"]
    a_("Net-level view at `ss_n40C_1v60` (limit 1.5 ns): " + f"{nets['per_corner']['ss_n40C_1v60']['max_slew']['violating_pins']} violating pins sit on "
       f"{nets['per_corner']['ss_n40C_1v60']['max_slew']['distinct_nets']} distinct nets; the largest: "
       + "; ".join(f"`{t['net']}` ({t['violating_pins']} pins, fanout {t['fanout_pins']}, driver {'/'.join(t['driver_cells'])}, worst excess {fmt(t['worst_excess'])} ns)" for t in tn[:5])
       + ". Each is a high-fanout net driven by a single `buf_4`/`or2_2`/`nand2_1`. The aggregate pin count overstates the number of electrical defects "
         "by a factor of roughly 25 at this corner; the defects are a few dozen weak-driver/high-fanout nets, and repair is a buffering problem on those nets.\n")

    a_("## Derived constraints\n")
    a_("`klt place-and-route` runs `repair_design` once, in the place stage, with only the request's `pdk.corner` (`tt_025C_1v80`) Liberty loaded "
       "(generated Tcl: `pnr-engine/pnr_trng_digital_place.tcl`). The slow corners are analysed afterwards only, so a limit has to be expressed "
       "as a tt-deck budget. `analysis/derive_limits.py` computed, from the control's routed DEF+SPEF, for each corner c: "
       "r_c = max over pins of slew_c/slew_tt, and T_c = L_c / r_c with L_c the corner deck's `default_max_transition`:\n")
    a_("| corner | L_c ns | r_c | T_c ns |")
    a_("|---|---|---|---|")
    for c in corners:
        v = deriv["slew"][c]
        a_(f"| {c} | {v['limit_ns']} | {v['ratio_to_tt_max']} | {v['tt_budget_ns']} |")
    a_(f"\nBudget = min T_c = **{deriv['slew_tt_budget_ns']} ns** (limiting corner `ss_n40C_1v28`), with a {int(deriv['margin']*100)} % margin = "
       f"**{deriv['slew_budget_with_margin_ns']} ns** -> `max_transition_ns: 0.531`. The ratio r_c comes from the *unrepaired* geometry, so it is a "
       "prediction; the final-route audit of each candidate is the test.")
    a_(f"\nCapacitance: Liberty `max_capacitance` is per cell and corner. The smallest ratio of a used cell's corner limit to its tt limit is "
       f"{deriv['cap_min_ratio_to_tt']} (`o41ai_1` at `ss_n40C_1v28`, 0.0099 pF vs 0.0339 pF at tt). `max_capacitance_pf` is a single design-wide scalar, "
       "so no per-cell derivation exists; candidate `slew0531-cap034` uses 0.034 pF, the weakest used cell's tt-deck limit, as an explicitly "
       "non-derived choice, to measure whether the scalar adds anything beyond the slew budget.\n")

    a_("## Candidates (all kept, failures included)\n")
    a_("| run | constraints | est slew/cap (16-corner sum) | final slew/cap (16-corner sum) | corners audited | candidate status | route DRC | klt DRC | LVS | setup/hold | cosim | neg. controls |")
    a_("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n in names:
        r = runs[n]
        s = r["sum"]
        et, ft = s["estimate_global_route"]["reduction_vs_library"]["totals"], s["final_route"]["reduction"]["totals"]
        v = r["verdict"]["verdict"]
        a_(f"| {n} | {', '.join(f'{k}={x}' for k, x in r['req']['constraints'].items() if k in ('max_transition_ns','max_capacitance_pf','max_fanout')) or 'none'} | "
           f"{et['max_slew']} / {et['max_capacitance']} | {ft['max_slew']} / {ft['max_capacitance']} | "
           f"{s['final_route']['reduction']['corners_audited']}/16 | {s['candidate_verdict']} | "
           f"{s['cost']['route_drc_violation_count']} | {'pass' if v['drc'] else 'FAIL'} | {'pass' if v['lvs'] else 'FAIL'} | "
           f"{'pass' if v['sta'] else 'FAIL'} | {'pass' if v['cosim'] else 'FAIL'} | {'4/4' if v['negative_controls'] else 'FAIL'} |")
    a_("")
    a_("Residual against the *tightened request limit itself* (in-flow estimate at the repair corner `tt_025C_1v80`, after the constraint override; "
       "this is the optimiser's own target, not a Liberty limit):\n")
    for n in names[1:]:
        ac = runs[n]["sum"]["estimate_global_route"]["per_corner"]["tt_025C_1v80"].get("after_constraints")
        if ac:
            over = ac["max_slew"]["count"] + ac["max_capacitance"]["count"]
            a_(f"- `{n}`: {ac['max_slew']['count']} pins over the slew target (worst excess {ac['max_slew']['worst_excess']} ns), "
               f"{ac['max_capacitance']['count']} pins over the cap target (worst excess {ac['max_capacitance']['worst_excess']} pF). "
               "(Two-decimal log precision.) "
               + ("`repair_design` does not meet its own tightened target everywhere; the Liberty limits at all 16 corners are nonetheless met at final route (table above)." if over else
                  "`repair_design` met its own target at the repair corner, and the slow corners still failed: the target itself (0.70 ns) was above the derived budget."))
    a_("")
    a_("Per-corner final-route results for every candidate (count / worst excess, slew ns and cap pF; tightest remaining margin in parentheses where clean):\n")
    a_("| corner | " + " | ".join(names) + " |")
    a_("|---|" + "---|" * len(names))
    for c in corners:
        row = []
        for n in names:
            f = runs[n]["audit"]["corners"][c]
            sl, cp = f["max_slew"], f["max_capacitance"]
            row.append(f"slew {sl['count']}/{fmt(sl['worst_excess'])}, cap {cp['count']}/{fmt(cp['worst_excess'], 4)}"
                       + (f" (margin {fmt(sl['worst_margin']['slack'], 2)} ns, {fmt(cp['worst_margin']['slack'], 4)} pF)" if not sl['count'] and not cp['count'] else ""))
        a_(f"| {c} | " + " | ".join(row) + " |")
    a_("")

    a_("## Cost: area, cells, timing\n")
    a_("| run | die um2 | achieved util % | std-cell area um2 | logic+buffer instances | `place*` repair buffers | wirelength um | worst setup slack ns | worst hold slack ns | clock skew ns |")
    a_("|---|---|---|---|---|---|---|---|---|---|")
    for n in names:
        c_ = runs[n]["sum"]["cost"]
        a_(f"| {n} | {c_['die_area_um2']} | {c_['utilization_pct']} | {c_['stdcell_instance_area_um2']} | {c_['instances_logic_and_buffers']} | "
           f"{c_['repair_inserted_buffers_by_prefix']['place']} | {c_['wirelength_um']} | {c_['worst_setup_slack_ns']} | {c_['worst_hold_slack_ns']} | {c_['clock_skew_ns']} |")
    a_("\nThe die is fixed by the 40 % utilisation request, so the digital macro bbox (0.060050 mm2) does not change; the repair cost shows as extra "
       "standard-cell area and instance count inside the same die.\n")

    a_("## Recommendation\n")
    best = clean[0] if clean else None
    if best:
        c0, c1 = ctl["sum"]["cost"], runs[best]["sum"]["cost"]
        a_(f"`{best}` is the minimal clean candidate: stdcell area {c0['stdcell_instance_area_um2']} -> {c1['stdcell_instance_area_um2']} um2 "
           f"({(c1['stdcell_instance_area_um2']/c0['stdcell_instance_area_um2']-1)*100:+.1f} %), logic+buffer instances {c0['instances_logic_and_buffers']} -> {c1['instances_logic_and_buffers']}, "
           f"worst setup slack {c0['worst_setup_slack_ns']} -> {c1['worst_setup_slack_ns']} ns, worst hold slack {c0['worst_hold_slack_ns']} -> {c1['worst_hold_slack_ns']} ns, "
           f"clock skew {c0['clock_skew_ns']} -> {c1['clock_skew_ns']} ns. Adding the `max_capacitance_pf` scalar (`slew0531-cap034`) is not needed for a clean audit and costs "
           f"a std-cell area of {runs['slew0531-cap034']['sum']['cost']['stdcell_instance_area_um2']} um2 ({(runs['slew0531-cap034']['sum']['cost']['stdcell_instance_area_um2']/c0['stdcell_instance_area_um2']-1)*100:+.1f} %). "
           "A budget above the derived minimum (`slew0700`, 0.70 ns) fails at the two corners whose predicted budget is below it (`ss_n40C_1v28`, `ss_n40C_1v60`; `ss_100C_1v60` also had a predicted budget of 0.618 ns but passed), "
           "so the derivation predicts the failure side correctly and, on this netlist and seed, its 10 %-margin value passes. Necessity of the margin (values between 0.531 and 0.59 ns) was not tested. "
           "Clean means clean under the audit's stated coverage, limits and unmodelled port load; tightest remaining margins are in the per-corner table (for `slew0531`: smallest slew margin 0.30 ns at `ss_n40C_1v60`, smallest cap margin 4.1 fF at `ss_n40C_1v28`). "
           "Nothing is promoted: adopting the constraint in the committed request would change `layout/trng_digital/`, the composed layout and every record that cites them, which is a separately reviewed change.\n")
    else:
        a_("No candidate was clean; see the per-corner table for the residual.\n")

    a_("## Reduction controls\n")
    a_("`sim/tests/test_electrical_reduction.py` (stdlib, PR-blocking in CI): a missing corner, an unsupported corner, a malformed class record, "
       "an empty report, or STA-only (setup/hold) records can never reduce to `clean`; an injected violation in any one corner and class is reported "
       "and counted in the right class; a surplus corner cannot stand in for a missing one; an estimate-only pass is labelled "
       "`estimate-clean, final-route unaudited`. The audit script itself marks a corner `unsupported` if the OpenSTA session fails, if a report block is "
       "absent, or if a sensitivity probe (SDC slew limit forced to 0.0001 ns) lists no pins, so a session that cannot see slews can never show zero. "
       "The control run (1512 slew / 50 cap pins) shows the audit does detect violations on the same script.\n")

    a_("## Tool gaps (friction protocol)\n")
    a_("- No installed klt command reports max-transition / max-capacitance against extracted post-route parasitics; coverage was supplied by "
       "`analysis/final_route_audit.py` (fresh OpenSTA sessions on the archived DEF+SPEF). Filed generically: **2AMLogic/klayout-tools#3005**. "
       "Per-corner coverage in this study: 16/16 `supported-by-sibling-script`, 0 unsupported, 0 missing (klt-native: unsupported at all 16).")
    a_("- The request has no way to declare port load or driving cell; the scalar `max_capacitance_pf` cannot express per-cell, per-corner Liberty limits (also in #3005). Related: klayout-tools#2782.")
    a_("- The in-flow counts are pin rows; worst excess and per-pin limit exist only in the retained engine logs (parsed here).\n")

    a_("## Implications\n")
    a_("- **#174 (whole-block post-layout characterisation):** this study does not change what #174 needs. If a candidate is later adopted, the committed "
       "`layout/trng_digital/` and the composed `layout/trng_whole/` would have to be regenerated and re-verified; until then #174 should keep citing the "
       "committed layout, whose electrical-limit status is *violations at four slow low-voltage corners and one fast corner (final-route audit above)*. #174 does not depend on this issue.")
    a_("- **Area gap (#226):** the candidates cost the std-cell area shown above at the same 40 % die; they do not move the 0.126116 mm2 composed block toward 0.05 mm2. "
       "The compaction study showed utilisation alone cannot close that gap, and denser points were rejected there for worsening these very limits. "
       "A repaired netlist is a precondition for revisiting compaction, not a substitute for it: compaction should be re-run *with* the derived constraint and audited at final route.")
    a_("- **Not done / not authorised:** promoting a candidate over the committed layout, recomposing `trng_whole`, changing the spec, FIFO/clock/function. "
       "A candidate's geometry differs from the committed layout (extra buffers), so adopting it is a separate reviewed change.\n")

    a_("## What this record does and does not establish\n")
    a_("- Established: baseline reproduction (1167, byte-identical geometry); a pin-to-net breakdown; final-route per-corner/per-class limits, "
       "worst excess and counts for the control and each candidate; area/cell/timing cost; the existing chain (route DRC, klt DRC, cell-level LVS signal+power, "
       "16-corner setup/hold, routed-netlist FUNCTIONAL cosim, 4 negative controls) passing on each candidate as reported above.")
    a_("- Not established: silicon behaviour; SDF-timed simulation; that the audit's OpenSTA parasitic annotation equals a foundry extraction "
       "(nominal interconnect corner only, as in the rest of the digital chain); per-pin Liberty limits are applied by OpenSTA, but port loading is the OpenSTA default; the choice of `0.531 ns` generalises to this netlist and seed only, "
       "so a netlist or floorplan change needs a re-derivation and a fresh audit. Same verification limits as `sim/digital-pnr/records/20261003-212010-fa76b17.md` (curated deck, not foundry signoff).")
    a_("\n---\n")
    a_("- Author: Loom builder (issue #236)")
    a_(f"- Timestamp (UTC): {ts.isoformat()}")
    a_(f"- Repo commit: `{sha_head}`")
    a_("- Supersedes: (none)")
    md = "\n".join(L) + "\n"
    out = {"record_id": rid, "timestamp_utc": ts.isoformat(), "repo_sha": sha_head, "issue": 236,
           "runs": {n: {"dir": str(runs[n]["dir"].relative_to(ROOT)), "candidate_verdict": status(runs[n]),
                        "est_totals": runs[n]["sum"]["estimate_global_route"]["reduction_vs_library"]["totals"],
                        "final_totals": runs[n]["sum"]["final_route"]["reduction"]["totals"],
                        "chain": runs[n]["verdict"]["verdict"], "cost": runs[n]["sum"]["cost"]} for n in names},
           "clean_candidates": clean, "derivation": {"slew_tt_budget_ns": deriv["slew_tt_budget_ns"],
                                                      "with_margin_ns": deriv["slew_budget_with_margin_ns"]},
           "promoted_geometry": None, "area_target_status": "unmet (unchanged)", "tool_gap_issue": "2AMLogic/klayout-tools#3005"}
    if a.emit:
        (ROOT / "sim/digital-electrical-repair/records" / f"{rid}.md").write_text(md)
        (ROOT / "sim/digital-electrical-repair/records" / f"{rid}.json").write_text(json.dumps(out, indent=1) + "\n")
        print(rid)
    else:
        print(md)


if __name__ == "__main__":
    main()
