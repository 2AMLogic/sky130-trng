#!/usr/bin/env python3
"""Per-run electrical summary (issue #236). Reads one run directory written
by bin/run-study.sh (pnr-output.json, pnr-engine/, electrical-audit.json,
verdict.json, trng_digital.def.gz) and writes <run-dir>/electrical-summary.json.

Three separately labelled things, never merged into one number:

  estimate : in-flow `report_check_types` after `estimate_parasitics
             -global_routing` (a global-route ESTIMATE), parsed per pin from
             the retained OpenROAD logs, with its counts cross-checked against
             the pnr response `corners[]` counts (a mismatch is recorded).
             Both the "vs library" block (taken before the request's
             constraint override) and the post-override block are kept.
  final    : electrical-audit.json (routed DEF + post-route SPEF).
  cost     : area / instance / buffer / timing effect.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import electrical as E  # noqa: E402

ROOT = HERE.parents[2]


def estimate_from_logs(run: Path, corners: list[str]) -> dict:
    eng = run / "pnr-engine" / "openroad-logs"
    out = {c: {"status": "missing"} for c in corners}
    if not eng.exists():
        return out
    for inv in sorted(eng.glob("*/invocation.json")):
        meta = json.loads(inv.read_text())
        m = re.match(r"pnr_trng_digital_route_corner_(.+)\.tcl$", meta.get("script_name", ""))
        if not m or m[1] not in out:
            continue
        txt = (inv.parent / "stdout.log").read_text(errors="replace")
        rec = {"status": "audited"}
        for tag, prefix in (("vs_library", "LIBRARY_"), ("after_constraints", "")):
            sl = E.block(txt, f"MAX_TRANSITION_{prefix}VIOLATIONS")
            cp = E.block(txt, f"MAX_CAPACITANCE_{prefix}VIOLATIONS")
            if sl is None or cp is None:
                rec = {"status": "missing"}
                break
            rec[tag] = {"max_slew": E.summarise(E.parse_violators(sl)),
                        "max_capacitance": E.summarise(E.parse_violators(cp))}
        out[m[1]] = rec
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    run = a.run_dir.resolve()
    pnr = json.loads((run / "pnr-output.json").read_text())
    corners = [c["name"] for c in pnr["corners"]]
    est = estimate_from_logs(run, corners)
    # cross-check parsed counts against the klt response
    xcheck, mism = {}, []
    for c in pnr["corners"]:
        r = est[c["name"]]
        if r["status"] != "audited":
            continue
        a_ = (r["vs_library"]["max_slew"]["count"], r["vs_library"]["max_capacitance"]["count"])
        k_ = (c["max_transition_violation_count_vs_library"], c["max_capacitance_violation_count_vs_library"])
        xcheck[c["name"]] = {"parsed": a_, "klt": k_, "equal": a_ == k_}
        if a_ != k_:
            mism.append(c["name"])
    est_view = {c: ({"status": "audited", **r["vs_library"]} if r["status"] == "audited" else r)
                for c, r in est.items()}
    est_red = E.reduce_evidence(corners, est_view, "estimate")
    audit_p = run / "electrical-audit.json"
    audit = json.loads(audit_p.read_text()) if audit_p.exists() else None
    fin_red = E.reduce_evidence(corners, audit["corners"] if audit else None, "final")
    # cost
    cost = {k: pnr.get(k) for k in ("die_area_um2", "core_area_um2", "utilization_pct", "wirelength_um",
                                     "worst_slack_ns", "worst_setup_slack_ns", "worst_hold_slack_ns",
                                     "clock_skew_ns", "setup_violation_count", "hold_violation_count",
                                     "route_drc_violation_count", "antenna_violation_count")}
    rm = list((run / "pnr-engine").glob("*_route_metrics.json"))
    if rm:
        cost["stdcell_instance_area_um2"] = json.loads(rm[0].read_text()).get("design__instance__area__stdcell")
    defp = run / "trng_digital.def.gz"
    if defp.exists():
        names = re.findall(r"^\s*- (\S+) (sky130_fd_sc_hd__\w+)", gzip.open(defp, "rt").read(), re.M)
        by_kind = Counter()
        for n, cell in names:
            kind = re.match(r"([a-zA-Z_]+?)(?:\d+|_)?[0-9]*$", n)
            by_kind[re.sub(r"[\d_$\\]+$", "", n) or "synth"] += 1
        phys = ("tap", "TAP", "PHY", "FILLER", "filler", "decap")
        logic = [(n, c) for n, c in names if not any(p in c or n.startswith(p) for p in ("tapvpwrvgnd", "decap", "fill", "TAP", "PHY"))]
        cost["instances_total"] = len(names)
        cost["instances_logic_and_buffers"] = len(logic)
        cost["instances_by_name_prefix"] = {k: v for k, v in by_kind.most_common(12)}
        cost["repair_inserted_buffers_by_prefix"] = {
            p: sum(1 for n, _ in logic if n.startswith(p))
            for p in ("input", "output", "place", "rebuffer", "wire", "max_cap", "split", "clkbuf", "clkload", "fanout", "max_length")}
    verdict_p = run / "verdict.json"
    res = {"schema": "sky130-trng.electrical-summary/1", "run_dir": str(run.relative_to(ROOT)),
           "corners": corners,
           "estimate_global_route": {
               "stage": "in-flow report_check_types after estimate_parasitics -global_routing (ESTIMATE, not final route)",
               "per_corner": est, "reduction_vs_library": est_red,
               "count_crosscheck_vs_klt_response": xcheck, "count_mismatch_corners": mism,
               "klt_response_totals": {k: pnr.get(k) for k in (
                   "max_transition_violation_count", "max_capacitance_violation_count",
                   "max_transition_violation_count_vs_library", "max_capacitance_violation_count_vs_library")}},
           "final_route": {"audit_present": audit is not None, "reduction": fin_red,
                           "per_corner": audit["corners"] if audit else None},
           "cost": cost,
           "chain_verdict": json.loads(verdict_p.read_text()) if verdict_p.exists() else None,
           "candidate_verdict": E.candidate_verdict(est_red, fin_red)}
    (run / "electrical-summary.json").write_text(json.dumps(res, indent=1) + "\n")
    print(res["candidate_verdict"], "| est", est_red["totals"], "| final", fin_red["totals"],
          "| xcheck mismatches", mism)


if __name__ == "__main__":
    main()
