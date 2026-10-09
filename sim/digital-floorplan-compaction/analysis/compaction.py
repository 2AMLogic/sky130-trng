#!/usr/bin/env python3
"""Reduce the issue #226 digital floorplan-compaction study into one
append-only evidence record.

Pure arithmetic over already-committed evidence (no tool is run):

- per-utilisation run directories written by `bin/run-study.sh` (harness
  `sim/digital-pnr/harness/pnr-and-verify.py --request ... --out-dir ...`);
- the committed baseline verification under `layout/trng_digital/`;
- the committed whole-block composition geometry
  `layout/trng_whole/report.json` (macro bboxes, combined bbox).

    python3 sim/digital-floorplan-compaction/analysis/compaction.py --run <RID>
    python3 sim/digital-floorplan-compaction/analysis/compaction.py --run <RID> --emit-record

A run that failed stays a failure: every metric the run did not produce is
reported as missing, never filled in.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_record, new_record_id  # noqa: E402

STUDY = REPO_ROOT / "sim" / "digital-floorplan-compaction"
BASE = REPO_ROOT / "layout" / "trng_digital"
WHOLE = REPO_ROOT / "layout" / "trng_whole" / "report.json"
COMMITTED_REQUEST = REPO_ROOT / "digital" / "flow" / "place-and-route" / "pnr-trng-digital-50khz.json"
PINS = REPO_ROOT / "digital" / "flow" / "place-and-route" / "tool-pins.json"
TARGET_MM2 = 0.05  # README "Area < 0.05 mm2" row -- unchanged, not relaxed here
N_CONTROLS = 4


def sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def sha256(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def load(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def die_dims(def_text: str) -> tuple[float, float]:
    units = float(re.search(r"UNITS DISTANCE MICRONS (\d+)", def_text).group(1))
    m = re.search(r"DIEAREA \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", def_text)
    x0, y0, x1, y1 = (float(v) / units for v in m.groups())
    return x1 - x0, y1 - y0


def congestion(eng: Path) -> dict:
    """Placement-time routability figures from the retained OpenROAD logs."""
    out = {}
    if not eng.exists():
        return {"available": False}
    text = "\n".join(p.read_text(errors="replace") for p in sorted(eng.rglob("stdout.log")))
    for key, pat in (("gpl_final_weighted_congestion", r"GPL-1005\] Routability final weighted congestion: ([\d.]+)"),
                     ("gpl_routing_overflow_last", r"GPL-0041\] Total routing overflow: ([\d.]+)"),
                     ("gpl_overflowed_tiles_last", r"GPL-0042\] Number of overflowed tiles: (\d+)"),
                     ("grt_total_overflow", r"GRT-\d+\].*[Tt]otal overflow[^\d-]*(-?\d+)")):
        vals = re.findall(pat, text)
        out[key] = float(vals[-1]) if vals else None
    rm = load(next(iter(sorted(eng.glob("*_route_metrics.json"))), Path("/nonexistent")))
    if rm:
        for k in ("global_route__wirelength", "route_pass:0__route__drc_errors__iter:0",
                  "route__drc_errors", "design__instance__area__stdcell"):
            out[k] = rm.get(k)
        it = [int(m.group(1)) for k in rm for m in [re.match(r"route_pass:0__route__drc_errors__iter:(\d+)$", k)] if m]
        out["detailed_route_pass0_iterations"] = (max(it) + 1) if it else None
        out["unrouted_net_count"] = None  # not reported by klt/OpenROAD here (klayout-tools#2994)
        out["global_route_overflow"] = None  # not reported (klayout-tools#2994)
    out["available"] = True
    return out


def summarize_run(d: Path) -> dict:
    r: dict = {"dir": str(d.relative_to(REPO_ROOT))}
    req = next(iter(sorted(d.glob("util*.json"))), None)
    verdict = load(d / "verdict.json")
    pnr = load(d / "pnr-output.json")
    r["exit"] = None
    ec = d.parent / "exit-codes.txt"
    if ec.exists():
        for line in ec.read_text().splitlines():
            if line.startswith(d.name + " "):
                r["exit"] = int(line.split()[2])
    stderr = (d / "stderr.log").read_text(errors="replace") if (d / "stderr.log").exists() else ""
    r["stderr_tail"] = stderr.strip().splitlines()[-12:]
    r["completed"] = bool(verdict and "verdict" in verdict)
    if verdict and "error" in verdict:
        r["error"] = verdict["error"]
    if pnr is None:
        r["pnr"] = None
        return r
    rs = pnr["stages"][-1] if pnr.get("stages") else {}
    r["pnr"] = {
        "status": pnr.get("status"), "stage_reached": pnr.get("stage_reached"),
        "die_area_um2": pnr.get("die_area_um2"), "core_area_um2": pnr.get("core_area_um2"),
        "utilization_pct": pnr.get("utilization_pct"), "wirelength_um": pnr.get("wirelength_um"),
        "route_drc_violation_count": pnr.get("route_drc_violation_count"),
        "antenna_violation_count": pnr.get("antenna_violation_count"),
        "worst_setup_slack_ns_inflow": pnr.get("worst_setup_slack_ns"),
        "worst_hold_slack_ns_inflow": pnr.get("worst_hold_slack_ns"),
        "max_transition_violation_count": pnr.get("max_transition_violation_count"),
        "max_capacitance_violation_count": pnr.get("max_capacitance_violation_count"),
        "estimated_power_mw": rs.get("estimated_power_mw"),
        "klt_version": pnr["provenance"]["klt_version"], "openroad": pnr.get("engine_version"),
    }
    r["libmax_by_corner"] = {
        c["name"]: [c.get("max_transition_violation_count_vs_library", c.get("max_transition_violation_count")),
                    c.get("max_capacitance_violation_count_vs_library", c.get("max_capacitance_violation_count"))]
        for c in pnr.get("corners", [])}
    defgz = d / "trng_digital.def.gz"
    if defgz.exists():
        w, h = die_dims(gzip.decompress(defgz.read_bytes()).decode())
        r["die_w_um"], r["die_h_um"] = w, h
        r["geometry_sha256"] = {n: sha256_bytes(gzip.decompress((d / f"{n}.gz").read_bytes()))
                                for n in ("trng_digital.gds", "trng_digital.def", "trng_digital.v")
                                if (d / f"{n}.gz").exists()}
    r["congestion"] = congestion(d / "pnr-engine")
    drc, lvs, sta = load(d / "drc-output.json"), load(d / "lvs-output.json"), load(d / "sta-output.json")
    if drc:
        r["drc"] = {"status": drc["status"], "violation_count": drc["violation_count"]}
    if lvs:
        r["lvs"] = {"status": lvs["status"], "error_count": lvs["error_count"],
                    "power_connectivity": (lvs.get("power_connectivity") or {}).get("status"),
                    "power_findings": [f"{f['rule']}:{f.get('pin')}" for f in
                                       (lvs.get("power_connectivity") or {}).get("findings", [])]}
    if sta:
        rows = sta["corners"]
        r["sta"] = {"corners": len(rows),
                    "all_constrained": all(x["timing_status"] == "constrained" for x in rows),
                    "worst_setup_slack_ns": min(x["worst_slack_ns"] for x in rows),
                    "worst_hold_slack_ns": min(x["worst_hold_slack_ns"] for x in rows),
                    "setup_violations": sum(x["setup_violation_count"] for x in rows),
                    "hold_violations": sum(x["hold_violation_count"] for x in rows)}
    ctl = load(d / "negative-controls.json")
    if ctl:
        r["controls_detected"] = sum(1 for v in ctl.values() if v.get("detected"))
    if verdict and "gate_cosim" in verdict:
        g = verdict["gate_cosim"]
        r["cosim"] = {"ok": g["ok"], "cycles": g["cycles"], "mismatches": g["mismatches"]}
    if verdict:
        r["verdict"] = verdict.get("verdict")
        r["tool_drift"] = verdict.get("tool_drift", verdict.get("drift"))
    if req:
        r["request"] = {"path": str(req.relative_to(REPO_ROOT)), "sha256": sha256(req),
                        "utilization_pct": json.loads(req.read_text())["floorplan"]["utilization_pct"]}
    return r


def baseline() -> dict:
    p, l, s, dr = (load(BASE / f) for f in ("pnr.json", "lvs.json", "sta.json", "drc.json"))
    rows = s["corners"]
    w, h = die_dims((BASE / "trng_digital.def").read_text())
    return {
        "die_area_um2": p["die_area_um2"], "core_area_um2": p["core_area_um2"],
        "utilization_pct": p["utilization_pct"], "wirelength_um": p["wirelength_um"],
        "die_w_um": w, "die_h_um": h,
        "drc": {"status": dr["status"], "violation_count": dr["violation_count"]},
        "lvs": {"status": l["status"], "error_count": l["error_count"],
                "power_connectivity": l["power_connectivity"]["status"]},
        "sta": {"corners": len(rows), "setup_violations": sum(x["setup_violation_count"] for x in rows),
                "hold_violations": sum(x["hold_violation_count"] for x in rows),
                "worst_setup_slack_ns": min(x["worst_slack_ns"] for x in rows),
                "worst_hold_slack_ns": min(x["worst_hold_slack_ns"] for x in rows)},
        "libmax_by_corner": {c["name"]: [c["max_transition_violation_count_vs_library"],
                                         c["max_capacitance_violation_count_vs_library"]] for c in p["corners"]},
        "klt_version": p["provenance"]["klt_version"],
        "geometry_sha256": {"trng_digital.gds": sha256(BASE / "trng_digital.gds"),
                            "trng_digital.def": sha256(BASE / "trng_digital.def"),
                            "trng_digital.v": sha256(BASE / "trng_digital.routed.v")},
        "controls_detected": N_CONTROLS, "cosim_ok": True,
    }


def coverage(run: dict, base: dict) -> dict:
    """Verification coverage of a run against the committed baseline's.
    Every item must hold for a run to be selectable."""
    lib = run.get("libmax_by_corner") or {}
    blib = base["libmax_by_corner"]
    lib_total = sum(sum(v) for v in lib.values()) if lib else None
    blib_total = sum(sum(v) for v in blib.values())
    chk = {
        "completed": run.get("completed", False),
        "route_reached": bool(run.get("pnr") and run["pnr"]["stage_reached"] == "route"),
        "route_drc_0": bool(run.get("pnr") and run["pnr"]["route_drc_violation_count"] == 0),
        "antenna_0": bool(run.get("pnr") and run["pnr"]["antenna_violation_count"] == 0),
        "drc_clean": run.get("drc", {}).get("status") == "clean",
        "lvs_match": run.get("lvs", {}).get("status") == "match" and run["lvs"]["error_count"] == 0,
        "lvs_power_connectivity_match": run.get("lvs", {}).get("power_connectivity") == base["lvs"]["power_connectivity"],
        "sta_16_corners_clean": (run.get("sta", {}).get("corners") == base["sta"]["corners"]
                                 and run["sta"]["all_constrained"]
                                 and run["sta"]["setup_violations"] == 0 and run["sta"]["hold_violations"] == 0),
        "cosim_pass": run.get("cosim", {}).get("ok") is True,
        "controls_all_detected": run.get("controls_detected") == N_CONTROLS,
        "libmax_not_worse_per_corner": bool(lib) and all(
            lib.get(k, [None, None])[i] is not None and lib[k][i] <= blib[k][i]
            for k in blib for i in (0, 1)),
    }
    return {"checks": chk, "at_least_baseline": all(chk.values()),
            "libmax_total": lib_total, "baseline_libmax_total": blib_total}


def area_model(die_w: float, die_h: float, whole: dict) -> dict:
    """Combined-area bounds for a digital macro of die_w x die_h um, using the
    committed composition (layout/trng_whole/report.json). ESTIMATES, not a
    verified composed layout."""
    dig, ana, bb = (whole["macros"]["dig"]["bbox_um"], whole["macros"]["ana"]["bbox_um"],
                    whole["area"]["bbox_um"])
    a_ana = (ana["x1"] - ana["x0"]) * (ana["y1"] - ana["y0"])
    a_dig0 = (dig["x1"] - dig["x0"]) * (dig["y1"] - dig["y0"])
    a_bb0 = (bb["x1"] - bb["x0"]) * (bb["y1"] - bb["y0"])
    overhead0 = a_bb0 - a_dig0 - a_ana
    west_escape = dig["x0"] - bb["x0"]            # VPWR escape lane outside the digital bbox
    gap = ana["y0"] - dig["y1"]                   # digital top -> analog bottom
    top = bb["y1"] - ana["y1"]                    # analog top -> pad row top
    east_edge = dig["x1"]                         # digital east (pin) edge held at the lane corridor
    a_dig = die_w * die_h

    def restack(w, h):
        x0 = min(ana["x0"], east_edge - w - west_escape)
        width = max(ana["x1"], east_edge) - x0
        height = h + gap + (ana["y1"] - ana["y0"]) + top
        return width * height, width, height

    # self-check: the restacked model reproduces the committed composition exactly
    chk, _, _ = restack(dig["x1"] - dig["x0"], dig["y1"] - dig["y0"])
    assert abs(chk - a_bb0) < 0.5, (chk, a_bb0)
    a_rs, wid, hei = restack(die_w, die_h)
    return {
        "digital_bbox_mm2": a_dig / 1e6,
        "analog_bbox_mm2": a_ana / 1e6,
        "lower_bound_macros_only_mm2": (a_dig + a_ana) / 1e6,
        "estimate_additive_overhead_mm2": (a_dig + a_ana + overhead0) / 1e6,
        "estimate_restacked_same_topology_mm2": a_rs / 1e6,
        "restacked_bbox_um": [round(wid, 3), round(hei, 3)],
        "baseline_overhead_mm2": overhead0 / 1e6,
        "composition_constants_um": {"west_escape": round(west_escape, 3), "gap": round(gap, 3),
                                     "top_pad_margin": round(top, 3), "digital_east_edge_x": east_edge,
                                     "analog_w": ana["x1"] - ana["x0"], "analog_h": round(ana["y1"] - ana["y0"], 3)},
    }


def fmt(v, nd=6):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}g}" if abs(v) < 1e5 else f"{v:.1f}"
    return str(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="run id under sim/digital-floorplan-compaction/runs/")
    ap.add_argument("--control-run", default=None,
                    help="optional earlier run id on a non-pinned klt build, reported as a tool-drift control")
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)

    run_dir = STUDY / "runs" / args.run
    whole = load(WHOLE)
    base = baseline()
    pins = load(PINS)
    runs = {d.name: summarize_run(d) for d in sorted(run_dir.glob("util*")) if d.is_dir()}
    runs = dict(sorted(runs.items(), key=lambda kv: int(kv[0][4:])))
    for name, r in runs.items():
        r["coverage"] = coverage(r, base)
        if "die_w_um" in r:
            r["area"] = area_model(r["die_w_um"], r["die_h_um"], whole)
    base["area"] = area_model(base["die_w_um"], base["die_h_um"], whole)

    # reproduction of the committed baseline by the util40 run
    r40 = runs.get("util40", {})
    repro = {
        "geometry_byte_identical": r40.get("geometry_sha256") == base["geometry_sha256"],
        "die_area_equal": (r40.get("pnr") or {}).get("die_area_um2") == base["die_area_um2"],
        "utilization_equal": (r40.get("pnr") or {}).get("utilization_pct") == base["utilization_pct"],
        "libmax_equal": r40.get("libmax_by_corner") == base["libmax_by_corner"],
        "lvs_power_connectivity_equal": (r40.get("lvs") or {}).get("power_connectivity") == base["lvs"]["power_connectivity"],
    }

    control = None
    if args.control_run:
        c40 = summarize_run(STUDY / "runs" / args.control_run / "util40")
        control = {"run": args.control_run, "klt_version": (c40.get("pnr") or {}).get("klt_version"),
                   "geometry_byte_identical_to_baseline": c40.get("geometry_sha256") == base["geometry_sha256"],
                   "lvs": c40.get("lvs"), "verdict": c40.get("verdict"), "tool_drift": c40.get("tool_drift")}

    # cell-area floor (100 % utilisation, zero composition overhead)
    # (smallest routed std-cell area over the runs = the most optimistic floor)
    cas = [ca for r in runs.values()
           for ca in [(r.get("congestion") or {}).get("design__instance__area__stdcell")] if ca]
    cell_area = min(cas) if cas else None
    if cell_area is None and r40.get("pnr"):
        cell_area = r40["pnr"]["core_area_um2"] * r40["pnr"]["utilization_pct"] / 100.0
    ana_mm2 = base["area"]["analog_bbox_mm2"]
    c = base["area"]["composition_constants_um"]
    stack_mm2 = c["analog_w"] * (c["gap"] + c["analog_h"] + c["top_pad_margin"]) / 1e6
    # estimate B in the limit of a square digital macro with no core margin at 100 % utilisation
    b_limit = area_model(cell_area ** 0.5, cell_area ** 0.5, whole) if cell_area else None
    gap0 = base["area"]["estimate_restacked_same_topology_mm2"] - TARGET_MM2
    closed_share = {n: {"estimate_B": (base["area"]["estimate_restacked_same_topology_mm2"]
                                       - r["area"]["estimate_restacked_same_topology_mm2"]) / gap0,
                        "estimate_A": (base["area"]["estimate_additive_overhead_mm2"]
                                       - r["area"]["estimate_additive_overhead_mm2"]) / gap0}
                    for n, r in runs.items() if r.get("area")}
    floors = {
        "stdcell_instance_area_um2": cell_area,
        "stdcell_instance_area_um2_by_run": {n: (r.get("congestion") or {}).get("design__instance__area__stdcell")
                                             for n, r in runs.items()},
        "estimate_B_limit_square_100pct_no_margin_mm2": b_limit["estimate_restacked_same_topology_mm2"] if b_limit else None,
        "share_of_baseline_gap_closed": closed_share,
        "absolute_floor_cells_plus_analog_mm2": (cell_area / 1e6 + ana_mm2) if cell_area else None,
        "analog_share_of_target": ana_mm2 / TARGET_MM2,
        "analog_row_full_width_stack_mm2": stack_mm2,
        "digital_area_budget_if_full_width_stacked_mm2": TARGET_MM2 - stack_mm2,
        "digital_area_budget_additive_overhead_mm2": TARGET_MM2 - ana_mm2 - base["area"]["baseline_overhead_mm2"],
        "digital_area_budget_zero_overhead_mm2": TARGET_MM2 - ana_mm2,
    }

    selectable = [n for n, r in runs.items() if n != "util40" and r["coverage"]["at_least_baseline"]]
    closes = [n for n, r in runs.items() if r.get("area") and
              r["area"]["estimate_restacked_same_topology_mm2"] < TARGET_MM2]

    # ---------------------------------------------------------------- markdown
    L = []
    a = L.append
    a(f"# Digital floorplan-compaction feasibility -- run `{args.run}` (issue #226)")
    a("")
    a("**Target status: `Area < 0.05 mm2` -- unchanged, UNMET.** This record measures how much of the gap")
    a("digital floorplan compaction can close. It is not a verified composed layout, does not replace")
    a("`layout/trng_digital/` or `layout/trng_whole/`, and promotes no candidate.")
    a("")
    a("## Inputs")
    a("")
    a(f"- committed request `{COMMITTED_REQUEST.relative_to(REPO_ROOT)}` `{sha256(COMMITTED_REQUEST)}`; study requests differ from it "
      "only in `floorplan.utilization_pct` (and the netlist path, rebased to the study directory -- same file, same sha256)")
    for n, r in runs.items():
        if r.get("request"):
            a(f"- `{r['request']['path']}` `{r['request']['sha256']}`")
    a(f"- tool pins `{PINS.relative_to(REPO_ROOT)}`: klt `{pins['klt_version']}`, OpenROAD `{pins['openroad']}`, "
      f"KLayout `{pins['klayout']}`, `{pins['open_pdks']}`; netlist `{pins['input_netlist_sha256']}`")
    a("- fixed across the study: netlist, seed 20260905, IO layers, `sky130hd` power preset, 20000 ns clock + 4000 ns IO "
      "delays, aspect ratio 1.0, 5 um core margin, `target_stage: route`, SPEF+SDF on. No SPICE.")
    a("")
    a("## Baseline reproduction (util40 vs committed `layout/trng_digital/`)")
    a("")
    for k, v in repro.items():
        a(f"- {k}: **{v}**")
    a(f"- tool drift recorded by the harness: {r40.get('tool_drift') or 'none'}")
    if control:
        a("")
        a(f"Tool-drift control: run `{control['run']}` used PyPI `klayout-tools==0.6.0` (reports `klt "
          f"{control['klt_version']}`, not the pinned git build). Its routed geometry is byte-identical to the "
          f"baseline: **{control['geometry_byte_identical_to_baseline']}**; its LVS is `{control['lvs']['status']}` "
          f"with power_connectivity **`{control['lvs']['power_connectivity']}`** "
          f"({', '.join(control['lvs']['power_findings']) or 'no findings'}) where the pinned build reports "
          f"`{base['lvs']['power_connectivity']}`. Identical geometry, different verdict: a checker difference "
          "between builds, not a layout difference. It is kept as evidence of why the exact pin is required; its "
          "util55 run was stopped part-way when the study was restarted on the pinned build, and util65 never started.")
    a("")
    a("## Physical results (pinned build)")
    a("")
    hdr = ["", "baseline (committed)"] + list(runs)
    a("| " + " | ".join(hdr) + " |")
    a("|" + "---|" * len(hdr))

    def row(label, bval, f):
        vals = []
        for r in runs.values():
            try:
                vals.append(fmt(f(r)))
            except Exception:
                vals.append("n/a")
        a(f"| {label} | {fmt(bval)} | " + " | ".join(vals) + " |")

    row("requested utilisation %", 40, lambda r: r["request"]["utilization_pct"])
    row("completed (all steps ran)", True, lambda r: r["completed"])
    row("harness exit", 0, lambda r: r["exit"])
    row("stage reached", "route", lambda r: r["pnr"]["stage_reached"])
    row("die W x H um", f"{base['die_w_um']:.2f} x {base['die_h_um']:.2f}",
        lambda r: f"{r['die_w_um']:.2f} x {r['die_h_um']:.2f}")
    row("die area um2", base["die_area_um2"], lambda r: r["pnr"]["die_area_um2"])
    row("core area um2", base["core_area_um2"], lambda r: r["pnr"]["core_area_um2"])
    row("achieved utilisation %", base["utilization_pct"], lambda r: r["pnr"]["utilization_pct"])
    row("routed wirelength um", base["wirelength_um"], lambda r: r["pnr"]["wirelength_um"])
    row("placement final weighted congestion", None, lambda r: r["congestion"]["gpl_final_weighted_congestion"])
    row("placement overflowed tiles (last routability iter)", None, lambda r: r["congestion"]["gpl_overflowed_tiles_last"])
    row("global-route wirelength um", None, lambda r: r["congestion"]["global_route__wirelength"])
    row("detailed-route violations after 1st iteration", None,
        lambda r: r["congestion"]["route_pass:0__route__drc_errors__iter:0"])
    row("detailed-route iterations (pass 0)", None, lambda r: r["congestion"]["detailed_route_pass0_iterations"])
    row("std-cell instance area um2 (routed)", None, lambda r: r["congestion"]["design__instance__area__stdcell"])
    row("route DRC violations (detailed route, final)", 0, lambda r: r["pnr"]["route_drc_violation_count"])
    row("antenna violations", 0, lambda r: r["pnr"]["antenna_violation_count"])
    row("klt DRC (sky130 deck)", f"{base['drc']['status']} / {base['drc']['violation_count']}",
        lambda r: f"{r['drc']['status']} / {r['drc']['violation_count']}")
    row("LVS (cell-level)", f"{base['lvs']['status']} / {base['lvs']['error_count']}",
        lambda r: f"{r['lvs']['status']} / {r['lvs']['error_count']}")
    row("LVS power_connectivity", base["lvs"]["power_connectivity"], lambda r: r["lvs"]["power_connectivity"])
    row("STA corners / setup viol / hold viol", f"{base['sta']['corners']} / {base['sta']['setup_violations']} / "
        f"{base['sta']['hold_violations']}",
        lambda r: f"{r['sta']['corners']} / {r['sta']['setup_violations']} / {r['sta']['hold_violations']}")
    row("worst setup slack ns (all corners)", base["sta"]["worst_setup_slack_ns"], lambda r: r["sta"]["worst_setup_slack_ns"])
    row("worst hold slack ns (all corners)", base["sta"]["worst_hold_slack_ns"], lambda r: r["sta"]["worst_hold_slack_ns"])
    row("lib max-slew + max-cap violations (sum over 16 corners)",
        sum(sum(v) for v in base["libmax_by_corner"].values()),
        lambda r: r["coverage"]["libmax_total"])
    row("routed-netlist cosim", "PASS", lambda r: f"{'PASS' if r['cosim']['ok'] else 'FAIL'} ({r['cosim']['mismatches']} mism.)")
    row("negative controls detected", f"{N_CONTROLS}/{N_CONTROLS}", lambda r: f"{r['controls_detected']}/{N_CONTROLS}")
    row("coverage >= baseline", "--", lambda r: r["coverage"]["at_least_baseline"])
    a("")
    a("Library-limit (max-slew / max-cap, in-flow global-route estimate) violations by corner, nonzero corners only:")
    a("")
    a("| corner | baseline | " + " | ".join(runs) + " |")
    a("|" + "---|" * (len(runs) + 2))
    for k, bv in base["libmax_by_corner"].items():
        rv = [tuple(r.get("libmax_by_corner", {}).get(k, [None, None])) for r in runs.values()]
        if any(bv) or any(x and any(x) for x in rv):
            a(f"| {k} | {bv[0]} / {bv[1]} | " + " | ".join(f"{x[0]} / {x[1]}" for x in rv) + " |")
    a("")
    for n, r in runs.items():
        failed = [k for k, v in r["coverage"]["checks"].items() if not v]
        if failed:
            a(f"- `{n}` coverage items not met: {', '.join(failed)}")
        if not r.get("completed"):
            a(f"- `{n}` did not complete; error `{r.get('error')}`; stderr tail:")
            a("")
            a("```")
            L.extend(r["stderr_tail"])
            a("```")
    a("")
    a("## Combined-area bounds and estimates (NOT a verified composed layout)")
    a("")
    a("Basis: axis-aligned bbox, as in `layout/trng_whole/README.md`. Analog macro `sampler_core` bbox "
      f"{ana_mm2:.6f} mm2 unchanged. Three figures per digital candidate:")
    a("")
    a("- **lower bound (macros only)**: digital bbox + analog bbox; ignores routing, pads, gaps. Not achievable.")
    a(f"- **estimate A (additive overhead)**: lower bound + the committed composition's non-macro area "
      f"({base['area']['baseline_overhead_mm2']:.6f} mm2 = 0.126116 - 0.079347), assumed constant.")
    a("- **estimate B (re-stacked, same topology)**: the committed floorplan's own geometry with the digital "
      "macro resized -- digital east (pin) edge held at the inter-macro lane corridor (x = "
      f"{c['digital_east_edge_x']}), VPWR west escape {c['west_escape']} um, digital->analog gap {c['gap']} um, "
      f"analog {c['analog_w']} x {c['analog_h']} um, pad row margin {c['top_pad_margin']} um. Reproduces the committed "
      "0.126116 mm2 exactly at the baseline size (asserted). Assumes the four inter-macro lanes, supply "
      "escapes and pads keep their current form; not composed, not DRC/LVS-checked.")
    a("")
    a("| candidate | digital bbox mm2 | lower bound mm2 | estimate A mm2 | estimate B mm2 (W x H um) | B / target | B gap to 0.05 mm2 |")
    a("|---|---|---|---|---|---|---|")
    for n, ar in [("baseline", base["area"])] + [(n, r["area"]) for n, r in runs.items() if r.get("area")]:
        b = ar["estimate_restacked_same_topology_mm2"]
        a(f"| {n} | {ar['digital_bbox_mm2']:.6f} | {ar['lower_bound_macros_only_mm2']:.6f} | "
          f"{ar['estimate_additive_overhead_mm2']:.6f} | {b:.6f} ({ar['restacked_bbox_um'][0]} x "
          f"{ar['restacked_bbox_um'][1]}) | {b / TARGET_MM2:.3f}x | +{b - TARGET_MM2:.6f} |")
    a("")
    a("Floors independent of utilisation:")
    a("")
    a(f"- analog bbox alone consumes **{floors['analog_share_of_target'] * 100:.1f} %** of the 0.05 mm2 target.")
    if cell_area:
        a(f"- routed standard-cell instance area (smallest of the runs) {cell_area:.1f} um2 = {cell_area / 1e6:.6f} mm2 "
          f"({cell_area / 1e6 / TARGET_MM2 * 100:.1f} % of target; by run: "
          + ", ".join(f"{n} {v}" for n, v in floors["stdcell_instance_area_um2_by_run"].items()) + " um2). "
          f"Cells + analog at 100 % utilisation with zero routing/composition overhead = "
          f"**{floors['absolute_floor_cells_plus_analog_mm2']:.6f} mm2**: the absolute floor for this netlist and "
          "this analog macro, below the target only because it ignores every routing, margin, gap and pad.")
        a(f"- estimate B in the limit of a square digital macro at 100 % utilisation with no core margin "
          f"({cell_area ** 0.5:.2f} um side): **{floors['estimate_B_limit_square_100pct_no_margin_mm2']:.6f} mm2** "
          f"({floors['estimate_B_limit_square_100pct_no_margin_mm2'] / TARGET_MM2:.2f}x target). No utilisation "
          "setting can get the committed topology below this.")
    a(f"- the analog row of the committed topology spans the full analog width: {c['analog_w']} um x "
      f"({c['gap']} + {c['analog_h']} + {c['top_pad_margin']}) um = {stack_mm2:.6f} mm2. Even with a digital macro "
      f"reshaped to that same width (aspect ratio is held at 1.0 in this study), the digital budget would be "
      f"{floors['digital_area_budget_if_full_width_stacked_mm2']:.6f} mm2"
      + (f", below the cell area alone ({cell_area / 1e6:.6f} mm2)." if cell_area and cell_area / 1e6 >
         floors["digital_area_budget_if_full_width_stacked_mm2"] else "."))
    a(f"- with the committed composition overhead held constant (estimate A), the digital budget is "
      f"{floors['digital_area_budget_additive_overhead_mm2']:.6f} mm2"
      + (". It is negative, so under that assumption the target is unreachable whatever the digital size." if
         floors["digital_area_budget_additive_overhead_mm2"] <= 0 else "."))
    a("- share of the baseline's gap to 0.05 mm2 (+%.6f mm2, estimate B) that each point removes: " % gap0
      + "; ".join(f"{n} {v['estimate_B'] * 100:.1f} % (B) / {v['estimate_A'] * 100:.1f} % (A)"
                  for n, v in closed_share.items()))
    a("")
    a("## Recommendation")
    a("")
    best = None
    if selectable:
        best = min(selectable, key=lambda n: runs[n]["pnr"]["die_area_um2"])
    smallest = min((n for n in runs if runs[n].get("area")),
                   key=lambda n: runs[n]["area"]["estimate_restacked_same_topology_mm2"])
    if closes:
        a(f"Estimate B closes the target for {closes}. A verified composition is needed before any claim.")
    else:
        a("**Floorplan compaction alone cannot close the area target.** No measured point gets even the "
          "re-stacked estimate under 0.05 mm2. The smallest is "
          f"`{smallest}` at {runs[smallest]['area']['estimate_restacked_same_topology_mm2']:.6f} mm2, "
          f"{runs[smallest]['area']['estimate_restacked_same_topology_mm2'] / TARGET_MM2:.2f}x the target, removing "
          f"{closed_share[smallest]['estimate_B'] * 100:.0f} % of the gap. The floors above show why: the analog "
          "row plus the standard cells exceed the target before any utilisation choice is made.")
    a("")
    if best:
        rb = runs[best]["area"]
        a(f"Of the compacted points, `{best}` is the smallest whose verification coverage matches or beats the "
          f"baseline's on every item above. Its estimate B is {rb['estimate_restacked_same_topology_mm2']:.6f} mm2, "
          f"{base['area']['estimate_restacked_same_topology_mm2'] - rb['estimate_restacked_same_topology_mm2']:.6f} "
          "mm2 below the baseline's re-stacked figure. It is recorded as the preferred floorplan **if** a later "
          "change composes and fully verifies it. It is NOT promoted here: `layout/trng_digital/` and "
          "`layout/trng_whole/` stay on the 40 % baseline.")
    else:
        a("**No candidate is selected.** The committed 40 % baseline remains the only selectable digital "
          "geometry. This is why:")
        a("")
        for n, r in runs.items():
            if n == "util40":
                continue
            failed = [k for k, v in r["coverage"]["checks"].items() if not v]
            if failed == ["libmax_not_worse_per_corner"]:
                worse = [f"{k} {r['libmax_by_corner'][k][0]}/{r['libmax_by_corner'][k][1]} vs "
                         f"{base['libmax_by_corner'][k][0]}/{base['libmax_by_corner'][k][1]}"
                         for k in base["libmax_by_corner"]
                         if any(r["libmax_by_corner"][k][i] > base["libmax_by_corner"][k][i] for i in (0, 1))]
                a(f"- `{n}` matches the baseline on route DRC, antenna, klt DRC, LVS (signal and power), "
                  "16-corner setup/hold, cosim and all four controls. It increases the unrepaired library "
                  "max-slew / max-cap violations (slew/cap, run vs baseline) at: " + "; ".join(worse)
                  + f" (16-corner total {r['coverage']['libmax_total']} vs {r['coverage']['baseline_libmax_total']}). "
                  "Those are electrical design-rule violations, so this is a degraded layout and is not promoted.")
            else:
                a(f"- `{n}` fails coverage items: {', '.join(failed)}")
        a("")
        a("Even an unconditionally accepted compacted point would leave the block at "
          f"{runs[smallest]['area']['estimate_restacked_same_topology_mm2'] / TARGET_MM2:.2f}x the target. That "
          "is too little to justify spending a composition and re-verification cycle on utilisation alone.")
    a("")
    a("Residual gap: +%.6f mm2 for the committed layout (verified, 0.126116 mm2). The best measured "
      "compaction (`%s`, estimate B, not composed) would still be +%.6f mm2. Closing the gap needs changes "
      "this study deliberately does not make. They are listed below as separate proposals, not filed by this "
      "change:" % (gap0, smallest, runs[smallest]["area"]["estimate_restacked_same_topology_mm2"] - TARGET_MM2))
    a("")
    a("1. Analog footprint / topology: the 330.96 um-wide single-row `sampler_core` sets the full-width "
      "analog row, which is %.6f mm2 with its gap and pad row. A folded (multi-row) ring/sampler arrangement "
      "or a side-by-side composition moves the floor more than any digital utilisation." % stack_mm2)
    a("2. Digital logic area: the standard cells alone are %.0f %% of the target. FIFO depth / storage style is "
      "the obvious candidate. It carries functional risk and needs its own spec / decision record." % (cell_area / 1e6 / TARGET_MM2 * 100))
    a("3. Composition overhead: the inter-macro lane corridor, VPWR west escape and pad row; met3/met4 routing "
      "roles (tool gap already recorded in `layout/trng_whole/README.md`) would allow lanes over the macros.")
    a("4. Digital aspect ratio matched to the analog width (held at 1.0 here). This only helps together "
      "with 1 or 2.")
    a("5. Library-limit repair: the request's `constraints.max_transition_ns` / `max_capacitance_pf`, which the pinned klt build accepts, could target "
      "the unrepaired low-voltage ss-corner slew/cap violations that disqualify the compacted points. Every "
      "point, the baseline included, carries them. Changing constraints is outside this fixed-constraint study.")
    a("")
    a("## What this record does and does not establish")
    a("")
    a("- Established: three P&R runs of the unchanged netlist at 40/55/65 % target utilisation on the pinned "
      "flow, each through the same DRC / cell-level LVS / 16-corner STA / routed cosim / negative-control chain as "
      "the committed baseline (`sim/digital-pnr/`), with every request, hash and failure retained under "
      f"`{run_dir.relative_to(REPO_ROOT)}/`.")
    a("- Same verification limits as `sim/digital-pnr/records/20261003-212010-fa76b17.md` (curated klt deck, not "
      "foundry signoff; cell-abstracted LVS; nominal interconnect corner; FUNCTIONAL cosim).")
    a("- Congestion: klt's P&R response carries no global-route overflow or unrouted-net count (filed generically "
      "as klayout-tools#2994). The figures above are OpenROAD's placement-time routability estimates (retained "
      "`pnr-engine/` logs) and the detailed router's per-iteration violation counts (stage metrics). Route "
      "completeness is inferred, not reported: final route DRC 0 plus an LVS signal-net match would expose an open "
      "net. The committed baseline kept no engine logs; util40's geometry is byte-identical to it, so util40's "
      "congestion figures stand for the baseline's.")
    a("- NOT established: any composed whole-block layout using a compacted macro; the combined-area figures "
      "are estimates. No power, IR or analog-coupling claim. The area target is not relaxed; it stays unmet.")
    a("")

    summary = {
        "issue": 226, "run": args.run, "target_mm2": TARGET_MM2, "target_status": "unchanged: unmet",
        "baseline": base, "baseline_reproduction": repro, "drift_control": control, "runs": runs,
        "floors": floors, "selectable": selectable, "selected": None,
        "preferred_if_later_verified": best, "estimate_b_closes_target": closes,
        "recommendation": ("floorplan compaction alone cannot close the area target; keep the 40 % baseline "
                           "geometry; pursue analog-footprint / digital-logic-area changes as separate proposals"
                           if not closes else "compose and verify the closing candidate before any claim"),
    }
    print("\n".join(L))
    if not args.emit_record:
        print(json.dumps({k: summary[k] for k in ("selectable", "preferred_if_later_verified",
                                                   "estimate_b_closes_target", "baseline_reproduction")},
                         indent=1), file=sys.stderr)
        return 0
    now, sha, rid = new_record_id(REPO_ROOT)
    summary = {"record_id": rid, "timestamp_utc": now.isoformat(), "repo_sha": sha, **summary}
    res = mint_record(STUDY / "records", REPO_ROOT, rid, L, "", summary,
                      author="Loom builder (issue #226)", now=now, sha=sha)
    return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())
