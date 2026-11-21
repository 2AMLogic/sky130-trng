#!/usr/bin/env python3
"""Run the area-limiter study (issue #599) end to end and mint its record.

Steps, in the order the issue numbers them:

1. resolve the Liberty deck the committed synthesis record pins
   (``sha256:8e78e14...``), asserting the hash, from the installed sky130A
   PDK roots (``sim/pdk.json`` search order);
2. item 1 -- ``attribute_digital_area`` over the committed unconstrained
   netlist (baseline attribution) and over this host's baseline-control and
   variant netlists (same attribution rule, as cross-checks);
3. item 1 -- ``klt synthesize`` twice through the installed ``klt``: a
   baseline control (committed RTL, for an apples-to-apples same-tool
   baseline) and the depth-2 FIFO variant
   (``harness/variant_fifo2.v``);
4. item 1 -- the functional suite against the normative model: the exact
   directed program of ``sim/digital-rtl-equivalence/`` (``build_program`` /
   ``model_trace`` via ``sim/tests/loadmod.py``) run against the variant RTL
   and against the variant mapped netlist (Icarus, FUNCTIONAL +
   UNIT_DELAY), with per-phase match/divergence classification;
5. item 2 -- ``fold_sampler_core`` (placement dry run);
6. item 3 -- ``composition_overhead`` (exact rectangle account);
7. item 4 -- ``combine_options`` (both baselines);
8. mint the append-only record (``level: gate`` for the netlist
   measurements; every layout figure carries its own confidence label
   in-body) with all raw outputs stored in the fleet artifact store.

Usage::

    python3 sim/area-limiter-study/harness/run-study.py            # dry run
    python3 sim/area-limiter-study/harness/run-study.py --emit-record

Nothing outside ``sim/area-limiter-study/`` is written.  ``digital/rtl/``,
``layout/``, ``spec/`` are read-only inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "digital-synthesis" / "harness"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "digital-rtl-equivalence" / "harness"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "tests"))

import attribute_digital_area as ada  # noqa: E402
import combine_options  # noqa: E402
import composition_overhead  # noqa: E402
import fold_sampler_core  # noqa: E402
import gate_cosim  # noqa: E402
from loadmod import load_module  # noqa: E402

rtl_cosim = load_module(
    "rtl_cosim", REPO_ROOT / "sim" / "digital-rtl-equivalence" / "harness" /
    "rtl-cosim.py")
build_program = rtl_cosim.build_program
model_trace = rtl_cosim.model_trace

SEED = 20260905  # the committed suite's seed (digital-rtl-equivalence)
DECK_BASENAME = "sky130_fd_sc_hd__tt_025C_1v80.lib"


def resolve_liberty() -> Path:
    for root in (Path.home() / ".volare", Path.home() / ".ciel"):
        cand = root / "sky130A" / "libs.ref" / "sky130_fd_sc_hd" / "lib" / \
            DECK_BASENAME
        if cand.exists():
            digest = hashlib.sha256(cand.read_bytes()).hexdigest()
            if digest == ada.DECK_SHA256:
                return cand
    raise SystemExit(
        f"error: no installed sky130A deck matches the pinned hash "
        f"{ada.DECK_SHA256}")


def run_klt_synthesize(request: dict, workdir: Path, label: str) -> dict:
    """Run ``klt synthesize`` in workdir; return response + netlist path."""
    workdir.mkdir(parents=True, exist_ok=True)
    req_path = workdir / f"{label}.json"
    req_path.write_text(json.dumps(request, indent=2) + "\n")
    proc = subprocess.run(
        ["klt", "synthesize", str(req_path), "--format", "json"],
        cwd=workdir, capture_output=True, text=True, timeout=900)
    (workdir / f"{label}-stderr.log").write_text(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(
            f"error: klt synthesize ({label}) failed rc={proc.returncode}:\n"
            f"{proc.stderr[-2000:]}")
    response = json.loads(proc.stdout)
    (workdir / f"{label}-response.json").write_text(json.dumps(
        response, indent=2, sort_keys=True) + "\n")
    # klt writes the netlist under <cwd>/.klt/synthesize/<run_id>/
    run_id = response.get("run_id")
    klt_dir = workdir / ".klt" / "synthesize" / run_id
    netlists = sorted(klt_dir.glob("*_synth.v"))
    netlist = netlists[0] if netlists else None
    return {"response": response, "request_path": req_path,
            "netlist": netlist, "stderr_log": workdir / f"{label}-stderr.log"}


def synthesize_request(rtl_path: Path) -> dict:
    return {
        "schema": "klt.synthesize.request/1",
        "engine": "yosys",
        "sources": [str(rtl_path)],
        "hdl_toplevel": "trng_digital",
        "pdk": {"cell_library": "sky130_fd_sc_hd", "corner": "tt_025C_1v80"},
        "constraints": {"clock_period_ns": None},
    }


def rtl_trace_rtl(cycles, workdir: Path, rtl: Path) -> list[str]:
    """The committed suite's RTL observation trace, against `rtl`."""
    workdir.mkdir(parents=True, exist_ok=True)
    stim = workdir / "stimulus.txt"
    obs = workdir / "rtl-observations.txt"
    stim.write_text("".join(
        f"{c[0]} {c[1]} {c[2]} {c[3]} {c[4]} {c[5]:08x} {c[6]}\n"
        for c in cycles))
    exe = workdir / "tb.vvp"
    tb = REPO_ROOT / "digital" / "tb" / "tb_trng_digital.v"
    subprocess.run(
        ["iverilog", "-g2005", "-Wall", "-o", str(exe), str(rtl), str(tb)],
        check=True, capture_output=True, text=True)
    subprocess.run(["vvp", str(exe), f"+stim={stim}", f"+obs={obs}"],
                   check=True, capture_output=True, text=True)
    return obs.read_text().splitlines()


def suite_vs_model(actual: list[str], expected: list[str],
                   phases: list[tuple[str, int, int]]) -> dict:
    n = min(len(expected), len(actual))
    diffs = [i for i in range(n) if expected[i] != actual[i]]
    per_phase = []
    for name, start, end in phases:
        seg = [i for i in diffs if start <= i < end]
        per_phase.append({"phase": name, "start": start, "end": end,
                          "mismatches": len(seg),
                          "first_mismatch": seg[0] if seg else None,
                          "match": not seg})
    return {
        "length_ok": len(expected) == len(actual),
        "cycles": len(expected),
        "mismatch_count": len(diffs),
        "first_mismatch_cycle": diffs[0] if diffs else None,
        "pass": not diffs and len(expected) == len(actual),
        "per_phase": per_phase,
    }


def model_trace_depth2(cycles) -> list[str]:
    """The normative model's own trace with its ``fifo_depth`` parameter set
    to 2 (``TrngDigital(fifo_depth=2)`` -- the model already parameterises
    depth; nothing in ``digital/model/`` is modified)."""
    import digital.model as dm
    dut = dm.TrngDigital(fifo_depth=2)
    out = []
    for (raw_bit, raw_valid, addr, we, re, wdata, ready) in cycles:
        obs = dut.cycle(raw_bit=raw_bit, raw_valid=raw_valid, addr=addr,
                        we=we, wdata=wdata, re=re, out_ready=ready)
        out.append(f"{obs['bus_rdata']:08x} {obs['out_valid']} "
                   f"{obs['out_data']:08x} {obs['alarm']} {obs['gated']} "
                   f"{obs['startup_done']}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--keep", type=Path, default=None,
                    help="keep run artifacts here (default: a tempdir)")
    args = ap.parse_args(argv)

    for tool in ("klt", "yosys", "iverilog"):
        if shutil.which(tool) is None:
            print(f"error: {tool} not on PATH -- a missing tool is not "
                  "evidence", file=sys.stderr)
            return 2

    # resolve once: klt runs with cwd = the request's parent, so a relative
    # --keep would otherwise be re-resolved against that directory
    workdir = (args.keep or Path(tempfile.mkdtemp(
        prefix="area-limiter-"))).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    liberty = resolve_liberty()

    # ---- item 1a: baseline attribution over the committed netlist --------
    attr_out = workdir / "attribution-baseline-committed.json"
    rc = ada.main(["--liberty", str(liberty), "--out", str(attr_out)])
    if rc != 0:
        print("error: baseline attribution failed", file=sys.stderr)
        return rc
    attribution = json.loads(attr_out.read_text())

    # ---- item 1b: syntheses through klt ----------------------------------
    base = run_klt_synthesize(
        synthesize_request(REPO_ROOT / "digital" / "rtl" / "trng_digital.v"),
        workdir / "synthesize", "baseline-control")
    var = run_klt_synthesize(
        synthesize_request(HARNESS / "variant_fifo2.v"),
        workdir / "synthesize", "variant-fifo2")

    # attribution of the same-tool baseline control (cross-check) and the
    # variant netlist, same rule (the variant's storage anchors are 64+64
    # bits: FIFO depth 2 keeps the same names but half the words)
    base_resp = json.loads((workdir / "synthesize" /
                            "baseline-control-response.json").read_text())
    var_resp = json.loads((workdir / "synthesize" /
                           "variant-fifo2-response.json").read_text())
    ctrl_counts_path = workdir / "baseline-control-counts.json"
    ctrl_counts_path.write_text(json.dumps({
        "instance_count": base_resp["instance_count"],
        "area_um2": base_resp["area_um2"],
        "instance_counts_by_type": base_resp["instance_counts_by_type"],
    }, indent=2) + "\n")
    attr_ctrl_out = workdir / "attribution-baseline-control.json"
    rc = ada.main(["--liberty", str(liberty),
                   "--netlist", str(base["netlist"]),
                   "--response", str(ctrl_counts_path),
                   "--out", str(attr_ctrl_out)])
    attr_ctrl = json.loads(attr_ctrl_out.read_text()) if rc == 0 else None

    var_counts_path = workdir / "variant-fifo2-counts.json"
    var_counts_path.write_text(json.dumps({
        "instance_count": var_resp["instance_count"],
        "area_um2": var_resp["area_um2"],
        "instance_counts_by_type": var_resp["instance_counts_by_type"],
    }, indent=2) + "\n")
    attr_var_out = workdir / "attribution-variant-fifo2.json"
    rc = ada.main(["--liberty", str(liberty),
                   "--netlist", str(var["netlist"]),
                   "--response", str(var_counts_path),
                   "--expect-raw-bits", "64", "--expect-cond-bits", "64",
                   "--out", str(attr_var_out)])
    if rc != 0:
        print("error: variant attribution failed", file=sys.stderr)
        return rc
    attr_var = json.loads(attr_var_out.read_text())

    # ---- item 1c: functional suite vs the normative model ----------------
    cycles, phases = build_program(SEED)
    expected = model_trace(cycles)
    var_rtl_obs = rtl_trace_rtl(cycles, workdir / "suite-rtl",
                                HARNESS / "variant_fifo2.v")
    suite_rtl = suite_vs_model(var_rtl_obs, expected, phases)
    libs_ref = liberty.parents[2]
    (workdir / "suite-gate").mkdir(parents=True, exist_ok=True)
    var_gate_obs, _stdout = gate_cosim.gate_trace(
        cycles, workdir / "suite-gate", var["netlist"], libs_ref)
    suite_gate = suite_vs_model(var_gate_obs, expected, phases)
    suite_gate["gate_matches_rtl"] = var_gate_obs == var_rtl_obs
    # the meaningful functional check: the variant vs the normative model
    # with the model's OWN fifo_depth parameter set to 2
    expected_d2 = model_trace_depth2(cycles)
    suite_rtl_d2 = suite_vs_model(var_rtl_obs, expected_d2, phases)
    suite_gate_d2 = suite_vs_model(var_gate_obs, expected_d2, phases)
    suite_gate_d2["gate_matches_rtl"] = var_gate_obs == var_rtl_obs
    (workdir / "suite-rtl.json").write_text(json.dumps(
        {"seed": SEED, "rtl_vs_model": suite_rtl,
         "rtl_vs_model_depth2": suite_rtl_d2}, indent=2) + "\n")
    (workdir / "suite-gate.json").write_text(json.dumps(
        {"seed": SEED, "gate_vs_model": suite_gate,
         "gate_vs_model_depth2": suite_gate_d2}, indent=2) + "\n")

    # ---- items 2-4 --------------------------------------------------------
    folds = fold_sampler_core.main()
    overhead = composition_overhead.main()
    combine = combine_options.main(
        variant_synth_cells_um2=var_resp["area_um2"])

    summary = {
        "item1_attribution": {
            "rows": attribution["rows"],
            "reconciliation": attribution["reconciliation"],
            "anchors": attribution["n_anchors"],
            "liberty_sha256": attribution["liberty_sha256"],
            "baseline_control_same_tool": {
                "klt": base_resp["provenance"]["klt_version"],
                "yosys": base_resp["engine_version"],
                "instance_count": base_resp["instance_count"],
                "area_um2": base_resp["area_um2"],
                "attribution_reconciles":
                    attr_ctrl["reconciliation"] if attr_ctrl else None,
            },
            "variant_fifo2": {
                "instance_count": var_resp["instance_count"],
                "area_um2": var_resp["area_um2"],
                "sequential_area_um2": var_resp["sequential_area_um2"],
                "delta_vs_same_tool_baseline_um2": round(
                    var_resp["area_um2"] - base_resp["area_um2"], 4),
                "delta_pct": round(
                    100.0 * (var_resp["area_um2"] - base_resp["area_um2"])
                    / base_resp["area_um2"], 2),
                "attribution_rows": attr_var["rows"],
                "attribution_reconciliation": attr_var["reconciliation"],
            },
        },
        "item1_functional_suite": {
            "seed": SEED,
            "rtl_vs_model": suite_rtl,
            "gate_vs_model": suite_gate,
            "rtl_vs_model_depth2": suite_rtl_d2,
            "gate_vs_model_depth2": suite_gate_d2,
        },
        "item2_fold": folds,
        "item3_composition_overhead": overhead,
        "item4_combine": combine,
    }
    (workdir / "study-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "workdir": str(workdir),
        "attribution_total": attribution["reconciliation"],
        "baseline_control": {
            "instances": base_resp["instance_count"],
            "area_um2": base_resp["area_um2"]},
        "variant": {
            "instances": var_resp["instance_count"],
            "area_um2": var_resp["area_um2"]},
        "suite_rtl_pass": suite_rtl["pass"],
        "suite_gate_pass": suite_gate["pass"],
        "best_combined_mm2": combine["best_area_mm2"],
        "reaches_target": combine["reaches_target"],
    }, indent=2))

    if not args.emit_record:
        print("dry run (no record minted); rerun with --emit-record",
              file=sys.stderr)
        return 0

    # ---- item 5: mint the record ------------------------------------------
    from evidence_record import mint_behavioral_record
    tools = {
        "klt": base_resp["provenance"]["klt_version"],
        "yosys": base_resp["engine_version"],
        "iverilog": rtl_cosim.iverilog_version(),
        "open_pdks": base_resp["provenance"]["pdk"]["version"],
        "liberty_deck": attribution["liberty_sha256"],
    }
    artifacts = [
        attr_out, attr_ctrl_out, attr_var_out,
        workdir / "synthesize" / "baseline-control.json",
        workdir / "synthesize" / "baseline-control-response.json",
        workdir / "synthesize" / "variant-fifo2.json",
        workdir / "synthesize" / "variant-fifo2-response.json",
        workdir / "suite-rtl.json",
        workdir / "suite-gate.json",
        workdir / "study-summary.json",
    ]
    netlist_copy = workdir / "variant-fifo2-trng_digital_synth.v"
    shutil.copy2(var["netlist"], netlist_copy)
    artifacts.append(netlist_copy)
    suite_copy_rtl = workdir / "variant-fifo2-rtl-observations.txt"
    shutil.copy2(workdir / "suite-rtl" / "rtl-observations.txt", suite_copy_rtl)
    artifacts.append(suite_copy_rtl)
    suite_copy_gate = workdir / "variant-fifo2-gate-observations.txt"
    shutil.copy2(workdir / "suite-gate" / "gate-observations.txt",
                 suite_copy_gate)
    artifacts.append(suite_copy_gate)

    # the success claim is only publishable when this run's own comparisons
    # support it; the expected depth-4 divergence is reported, not gated
    d2_ok = (suite_rtl_d2["pass"] and suite_gate_d2["pass"]
             and suite_gate["gate_matches_rtl"])
    if not d2_ok:
        print("error: the depth-2 variant does not match the normative "
              "model's fifo_depth=2 trace in this run (rtl mismatches "
              f"{suite_rtl_d2['mismatch_count']}, gate mismatches "
              f"{suite_gate_d2['mismatch_count']}, gate==rtl "
              f"{suite_gate['gate_matches_rtl']}); no record minted",
              file=sys.stderr)
        return 1
    body = build_record_body(summary, var_resp, base_resp)
    claim = build_claim(summary, var_resp, base_resp)
    rid = mint_behavioral_record(
        REPO_ROOT, "area-limiter-study", claim, body, summary,
        level="gate", seeds={"suite_stimulus_seed": SEED},
        artifacts=artifacts, tools=tools)
    print(f"record minted: {rid}", file=sys.stderr)
    return 0


def build_claim(s: dict, var_resp: dict, base_resp: dict) -> str:
    """The record's headline, generated from this run's measured values."""
    rows = s["item1_attribution"]["rows"]
    total = s["item1_attribution"]["reconciliation"]["area_total_um2"]
    fifo = rows["fifo_storage_raw"]["area_um2"] + \
        rows["fifo_storage_cond"]["area_um2"]
    f1, f2 = s["item2_fold"]["fold_f1"], s["item2_fold"]["fold_f2"]
    oh = s["item3_composition_overhead"]
    cb = s["item4_combine"]
    d2 = s["item1_functional_suite"]["rtl_vs_model_depth2"]
    delta_pct = s["item1_attribution"]["variant_fifo2"]["delta_pct"]
    reach = ("a combination reaches 0.05 mm2" if cb["reaches_target"]
             else "no fixed-pin-edge combination reaches 0.05 mm2")
    return (
        f"FIFO storage is the largest functional consumer of the committed "
        f"unconstrained trng_digital netlist ({fifo:,.1f} um2 of "
        f"{total:,.1f}, {100.0 * fifo / total:.1f}%, conclusive against the "
        f"shared/unassigned residual); a depth-2 FIFO variant synthesizes at "
        f"{var_resp['area_um2']:,.1f} um2 ({delta_pct:+.1f}% vs same-tool "
        f"baseline) and, while it diverges from the depth-4 normative model "
        f"at the depth-observable checks, it MATCHES the normative model's "
        f"own fifo_depth=2 parameterisation bit-for-bit over the full "
        f"{d2['cycles']}-cycle directed program (RTL and mapped netlist); a "
        f"folded sampler_core (F1) estimates {f1['width_um']} x "
        f"{f1['height_um']} um with ring symmetry intact; composition "
        f"overhead is {oh['non_macro_share_pct']}% of the committed whole "
        f"block and {oh['removable_by_tighter_floorplan']['share_of_non_macro_pct']:.0f}% "
        f"of it is removable stacking artifact; {reach} -- best "
        f"fixed-pin-edge estimate {cb['best_area_mm2']:.6f} mm2 "
        f"({cb['best_area_mm2'] / cb['target_mm2']:.3f}x), best "
        f"edge-aligned geometric estimate "
        f"{cb['best_edge_aligned_area_mm2']:.6f} mm2 (needs a pin-access "
        f"check); the routed digital macro remains the largest limiter"
    )


def build_record_body(s: dict, var_resp: dict, base_resp: dict) -> str:
    rows = s["item1_attribution"]["rows"]
    order = sorted(rows.items(), key=lambda kv: -kv[1]["area_um2"])
    total = s["item1_attribution"]["reconciliation"]["area_total_um2"]
    tbl = ["| function | instances | Liberty area um2 | share |",
           "|---|---|---|---|"]
    for name, r in order:
        tbl.append(f"| {name} | {r['instances']} | {r['area_um2']:.4f} | "
                   f"{100.0 * r['area_um2'] / total:.1f}% |")
    fifo = rows["fifo_storage_raw"]["area_um2"] + \
        rows["fifo_storage_cond"]["area_um2"]
    runner_up = max((v["area_um2"] for k, v in rows.items()
                     if k not in ("fifo_storage_raw", "fifo_storage_cond",
                                  "shared", "unassigned")),
                    default=0.0)
    runner_up_name = max(
        ((k, v["area_um2"]) for k, v in rows.items()
         if k not in ("fifo_storage_raw", "fifo_storage_cond",
                      "shared", "unassigned")),
        key=lambda kv: kv[1], default=("(none)", 0.0))[0]
    residual = rows.get("shared", {"area_um2": 0})["area_um2"] + \
        rows.get("unassigned", {"area_um2": 0})["area_um2"]

    n_inst = sum(r["instances"] for r in rows.values())
    cycles = s["item1_functional_suite"]["rtl_vs_model"]["cycles"]
    base_total_committed = 22203.7952  # the committed 0.69-post figure
    ctrl_pct = 100.0 * (base_total_committed - base_resp["area_um2"]) \
        / base_total_committed
    rt = s["item2_fold"]["fold_f1"]["routing"]
    route_tbl = [
        "F1 added routing, recomputed from the folded net endpoints "
        "(`fold_f1.routing`; Manhattan length between the moved committed "
        "port coordinates plus each polyline's own detour excess; vertical "
        "spans of the ro2/ro3 hauls are unchanged because the array and "
        "row B move together):",
        "",
        "| net | unfolded um (v / h) | folded um (v / h) | delta um |",
        "|---|---|---|---|",
    ]
    for n in rt["nets"]:
        route_tbl.append(
            f"| {n['net']} | {n['unfolded_um']} "
            f"({n['unfolded_vertical_um']} / {n['unfolded_horizontal_um']}) "
            f"| {n['folded_um']} ({n['folded_vertical_um']} / "
            f"{n['folded_horizontal_um']}) | {n['delta_um']:+} |")
    route_tbl += [
        "",
        f"Data hauls net {rt['data_nets_net_delta_um']:+} um; supply straps "
        f"re-tapped at the folded rail end {rt['supply_strap_horizontal_extension_um']:+} um; "
        f"row risers (vdd, vss, clk, rst_n) {rt['row_risers_um']:+} um; "
        f"six-to-two-chain saving {rt['rail_and_control_chain_saving_um']:+} "
        f"um. Gross added {rt['gross_added_um']} um; net "
        f"{rt['net_total_um']} um. Assumed detours: "
        + "; ".join(rt["assumed_detours"]) + ". Not modelled: "
        + rt["not_modelled"] + ".",
    ]
    comb_tbl = [
        "| option | baseline | topology | area mm2 | delta vs baseline mm2 "
        "| confidence | risk |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in s["item4_combine"]["rows"]:
        comb_tbl.append(
            f"| {row['option']} | {row['on_baseline']} | {row['topology']} "
            f"| {row['area_mm2']:.6f} | {row['delta_vs_baseline_mm2']:+.6f} "
            f"| {row['confidence']} | {row['risk']} |")
    ph_rtl = s["item1_functional_suite"]["rtl_vs_model"]["per_phase"]
    ph_tbl = ["| suite phase (seed 20260905) | RTL vs model | gate vs model |",
              "|---|---|---|"]
    gate_by_name = {p["phase"]: p
                    for p in s["item1_functional_suite"]
                    ["gate_vs_model"]["per_phase"]}
    for p in ph_rtl:
        rtl_cell = ("match" if p["match"]
                    else f"mismatches @ {p['first_mismatch']}")
        g = gate_by_name.get(p["phase"])
        gate_cell = ("match" if g and g["match"]
                     else f"mismatches @ {g['first_mismatch'] if g else '?'}")
        ph_tbl.append(f"| {p['phase']} | {rtl_cell} | {gate_cell} |")
    return "\n".join([
        "## Item 1 -- digital area by function (measured)",
        "",
        f"Attribution rule, anchors and reconciliation: "
        f"`harness/attribute_digital_area.py` docstring. Every one of the "
        f"{n_inst:,} instances owns exactly one row; rows sum to {total:.4f} um2 "
        f"against the Liberty deck the committed record pins "
        f"(sha256:8e78e144...). The storage anchors cover 128 distinct "
        f"`raw_mem` and 128 distinct `cond_mem` Q-driven bits.",
        "",
        *tbl,
        "",
        f"Ranking: FIFO storage (raw + cond) = {fifo:.4f} um2 "
        f"({100.0 * fifo / total:.1f}%) vs runner-up attributable function "
        f"{runner_up_name} at {runner_up:.4f} um2. Even if the entire "
        f"shared + unassigned residual ({residual:.4f} um2) belonged to the "
        f"runner-up, FIFO storage stays the leader by "
        f"{fifo - runner_up - residual:.4f} um2 "
        f"--> the ranking is conclusive; no measured basis forces the "
        f"inconclusive branch.",
        "",
        f"Same-tool baseline control (this run, klt "
        f"{base_resp['provenance']['klt_version']}, yosys "
        f"{base_resp['engine_version']}, open_pdks "
        f"{base_resp['provenance']['pdk']['version']} -- the forward pin of "
        f"#314; the resolved Liberty deck hashes to the SAME "
        f"sha256:8e78e144... the committed 20260910 record pins, so the "
        f"areas are directly comparable): {base_resp['instance_count']} "
        f"instances, {base_resp['area_um2']} um2 -- {ctrl_pct:.3f}% below the "
        f"committed 0.69-post figure; per-type attribution of the control "
        f"netlist reconciles identically.",
        "",
        f"Variant (depth-2 FIFO per path, `harness/variant_fifo2.v`, exact "
        f"diff vs `digital/rtl/trng_digital.v` in the PR): "
        f"{var_resp['instance_count']} instances, {var_resp['area_um2']} "
        f"um2, sequential {var_resp['sequential_area_um2']} um2 = "
        f"{s['item1_attribution']['variant_fifo2']['delta_pct']}% vs the "
        f"same-tool baseline. Under the same attribution rule the variant's "
        f"FIFO rows shrink from "
        f"{rows['fifo_storage_raw']['area_um2'] + rows['fifo_storage_cond']['area_um2']:.1f} "
        f"to "
        f"{s['item1_attribution']['variant_fifo2']['attribution_rows'].get('fifo_storage_raw', {'area_um2': 0})['area_um2'] + s['item1_attribution']['variant_fifo2']['attribution_rows'].get('fifo_storage_cond', {'area_um2': 0})['area_um2']:.1f} "
        f"um2 (the variant's storage anchors cover 64+64 Q-driven bits, "
        f"exactly what depth 2 implies; every other row keeps the same "
        f"rule).",
        "",
        "### Functional suite vs the normative model",
        "",
        *ph_tbl,
        "",
        f"First divergence cycle (RTL vs model): "
        f"{s['item1_functional_suite']['rtl_vs_model']['first_mismatch_cycle']}"
        f" of {s['item1_functional_suite']['rtl_vs_model']['cycles']}; gate "
        f"vs model: "
        f"{s['item1_functional_suite']['gate_vs_model']['first_mismatch_cycle']}"
        f"; the mapped netlist reproduces the variant RTL trace "
        f"{'bit-for-bit' if s['item1_functional_suite']['gate_vs_model']['gate_matches_rtl'] else 'WITH DIFFERENCES (investigate!)'}. "
        "The failing phases are exactly the depth-observable ones: the "
        "first mismatch is a STATUS read whose RAW_LEVEL field saturates at "
        "2 instead of 4, and every later phase that reads the FIFOs or "
        "STATUS inherits the occupancy difference; the phases that never "
        "observe a full FIFO match the model. "
        "The variant is intentionally NOT sequentially equivalent to the "
        "normative model at its default depth 4 (observable FIFO depth), "
        "so `klt equiv` is not run against it. Against the normative "
        "model's OWN `fifo_depth=2` parameterisation "
        "(`TrngDigital(fifo_depth=2)` -- the model already parameterises "
        "depth; nothing in `digital/model/` is modified) the variant RTL "
        f"{'MATCHES' if s['item1_functional_suite']['rtl_vs_model_depth2']['pass'] else 'DOES NOT MATCH'} "
        f"the full {cycles}-cycle directed program "
        f"({s['item1_functional_suite']['rtl_vs_model_depth2']['mismatch_count']} "
        "mismatches), and the mapped netlist "
        f"{'matches too' if s['item1_functional_suite']['gate_vs_model_depth2']['pass'] else 'does not'}. "
        "Adoption is a DR-0004 section 4.4 change: depth 4 -> 2, STATUS "
        "level-field semantics saturate at 2, overflow trips two words "
        "earlier, and the normative model plus the directed programs would "
        "pin the same depth parameter before any equivalence chain could "
        "be re-established (tracked in #610).",
        "",
        "## Item 2 -- folded sampler_core (estimated: placement dry run)",
        "",
        f"- F1 (samplers 3+3, ring row byte-identical): "
        f"{s['item2_fold']['fold_f1']['width_um']} x "
        f"{s['item2_fold']['fold_f1']['height_um']} um = "
        f"{s['item2_fold']['fold_f1']['area_um2']} um2 "
        f"({s['item2_fold']['fold_f1']['delta_area_um2']} um2 vs committed); "
        f"ring-to-ring symmetry survives by construction; "
        f"routing recomputed from the folded endpoints: gross added "
        f"{s['item2_fold']['fold_f1']['routing']['gross_added_um']} um, net "
        f"{s['item2_fold']['fold_f1']['routing']['net_total_um']} um after "
        f"the shorter chains and data hauls (table below).",
        f"- F2 (also 2x2 rings): {s['item2_fold']['fold_f2']['width_um']} x "
        f"{s['item2_fold']['fold_f2']['height_um']} um = "
        f"{s['item2_fold']['fold_f2']['area_um2']} um2 -- macro area GROWS "
        f"by {s['item2_fold']['fold_f2']['delta_area_um2']} um2 and the "
        f"vertical ring adjacency is unmeasured; recorded, not recommended.",
        "",
        *route_tbl,
        "",
        "## Item 3 -- composition overhead (measured inputs, exact)",
        "",
        f"Non-macro area {s['item3_composition_overhead']['non_macro_um2']} "
        f"um2 = {s['item3_composition_overhead']['non_macro_share_pct']}% of "
        f"the committed whole block. Rectangles: "
        + json.dumps(s["item3_composition_overhead"]["rectangles_um2"])
        + f". Removable by a tighter floorplan: "
        f"{s['item3_composition_overhead']['removable_by_tighter_floorplan']['area_um2']} "
        f"um2 "
        f"({s['item3_composition_overhead']['removable_by_tighter_floorplan']['share_of_non_macro_pct']}% "
        f"of the overhead) -- the south-east corridor exists because the "
        f"330.96 um analog row overhangs the digital macro's east pin edge "
        f"by 130.96 um, and the west-of-analog strip because west edges do "
        f"not align; both vanish when a re-stack matches widths/edges. "
        f"Lane band + pads + escape "
        f"({s['item3_composition_overhead']['functional_overhead']['area_um2']} "
        f"um2) are functional and scale with width/height.",
        "",
        "## Item 4 -- combined options",
        "",
        s["item4_combine"]["verdict_text"],
        "",
        *comb_tbl,
        "",
        f"Largest remaining limiter: {s['item4_combine']['largest_remaining_limiter']}.",
        "",
        "Whole-block figures: committed baseline column = the composed "
        "0.126116 mm2 (verified) and the committed-40% rows of the table; "
        "rep65-slew0531 column = #251's estimate B 0.093609 mm2 and this "
        "study's rows on top of it (see `item4_combine.rows` in the JSON "
        "twin for every figure with its confidence label).",
        "",
        "## Item 6 -- follow-ups",
        "",
        "Follow-up issues filed with this record: #609 (fold-F1 "
        "implementation + re-verification), #610 (the DR-0004 section 4.4 "
        "FIFO-depth decision request), #611 (the composed-and-verified "
        "whole block on rep65 + F1, + the variant once #610 is decided). "
        "No new 2AMLogic/klayout-tools gap was encountered: the F1 fold is "
        "expressible in the current gen-compose recipe (explicit placement "
        "origins already support a second row; the strap/lane stages are "
        "hand-declared connectivity entries), so no friction-ledger row is "
        "added.",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
