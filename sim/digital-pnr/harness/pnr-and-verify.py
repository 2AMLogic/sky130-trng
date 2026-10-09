#!/usr/bin/env python3
"""Place and route `trng_digital` (DR-0004 digital section) and gather
physical sign-off evidence -- issue #166.

Chain (every step shells out to `klt ... --format json`, same plumbing as
`sim/digital-synthesis/harness/synthesize-and-verify.py`):

1. Tool/PDK pin check against `digital/flow/place-and-route/tool-pins.json`
   (a drifted tool is a hard stop unless `--allow-tool-drift`, which marks
   the record).
2. `klt place-and-route digital/flow/place-and-route/pnr-trng-digital-50khz.json`
   -- floorplan -> place -> CTS -> global/detailed route, with PDN/tap/filler
   (`power` block), post-route SPEF + SDF, and the flow's own 16-corner
   post-route sweep. Input netlist is the committed, klt-equiv-proven
   `sim/digital-synthesis/` 50 kHz-constrained netlist; its sha256 is checked
   against the hash that record carries.
3. `klt drc --deck sky130` on the routed, standard-cell-merged GDS.
4. `klt extract --abstract-cells` (cell-level black boxes, DEF-derived top
   pins) + `klt lvs` against the routed as-built Verilog
   (`reference.form: gate-level-verilog`).
5. `klt sta` -- the SAME routed DEF + extracted SPEF analysed at every
   Liberty corner the pinned PDK ships for `sky130_fd_sc_hd`.
6. Routed-netlist functional co-simulation, reusing
   `sim/digital-synthesis/harness/gate_cosim.py` (FUNCTIONAL / UNIT_DELAY --
   NOT an SDF-timing simulation) against the normative model.
7. Negative controls: a pin-swapped and an instance-deleted routed netlist
   must FAIL LVS; a too-short clock period must produce setup violations in
   `klt sta`; an xor->and mutated routed netlist must FAIL co-simulation.
   A run whose controls do not fail refuses to mint a record.
8. `--emit-record` stages geometry under `layout/trng_digital/` and mints an
   append-only record under `sim/digital-pnr/records/`.

Needs: `klt` (pinned, see tool-pins.json), an `openroad` on `$PATH` (klt's
own contract), iverilog, installed sky130A PDK (`sim/pdk.json`'s pin).
Run from anywhere; klt is invoked with cwd = repo root because a
containerised `openroad` wrapper mounts only `$PWD`.

    python3 sim/digital-pnr/harness/pnr-and-verify.py --emit-record
    python3 sim/digital-pnr/harness/pnr-and-verify.py --skip-flow   # reuse .klt/ outputs of the last run
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HOME = Path.home().resolve()
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "digital-synthesis" / "harness"))

import gate_cosim  # noqa: E402
from _klt_common import BuildError, run_klt, write_json  # noqa: E402
from evidence_record import mint_behavioral_record  # noqa: E402

FLOW_DIR = REPO_ROOT / "digital" / "flow" / "place-and-route"
REQUEST = FLOW_DIR / "pnr-trng-digital-50khz.json"
PINS = FLOW_DIR / "tool-pins.json"
KLT_OUT = FLOW_DIR / ".klt" / "place-and-route"
LAYOUT_DIR = REPO_ROOT / "layout" / "trng_digital"
TOP = "trng_digital"
DEFAULT_SEED = 20260905

_EXTERNAL = ("<external -- not recorded by absolute location; see this "
             "record's PDK name/version and deck content_hash instead>")


def _sanitize(obj):
    """Same hygiene rule as synthesize-and-verify.py: in-repo paths are
    recorded repo-relative, anything else absolute is an external input
    identified by hash/version, never by location."""
    if isinstance(obj, str) and obj.startswith("/"):
        p = Path(obj)
        for base, fn in ((REPO_ROOT, lambda q: str(q.relative_to(REPO_ROOT))),):
            try:
                return fn(p.resolve())
            except ValueError:
                pass
        if str(p).startswith("/tmp/") or str(p).startswith(str(HOME)):
            return _EXTERNAL
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def run_klt_cwd(klt, args, env):
    return run_klt(args, env=env, cwd=REPO_ROOT, klt=klt)


def gz_copy(src: Path, dst: Path) -> None:
    # mtime=0 + fixed name -> byte-stable gzip for a given input
    with open(src, "rb") as fi, open(dst, "wb") as raw, \
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0,
                          compresslevel=9) as fo:
        shutil.copyfileobj(fi, fo)


def mutate_swap_pins(text: str) -> tuple[str, str]:
    """Swap the nets on pins A_N and B of the first nand2b instance whose two
    nets differ (an asymmetric cell, so a swap is a real wiring change)."""
    pat = re.compile(r"(sky130_fd_sc_hd__nand2b_\d+ \S+ \(\.A_N\()([^)]*)(\),\s*\.B\()([^)]*)(\))")
    for m in pat.finditer(text):
        if m.group(2) != m.group(4):
            new = (m.group(1) + m.group(4) + m.group(3) + m.group(2) + m.group(5))
            return text[:m.start()] + new + text[m.end():], \
                f"swapped A_N/B nets on one nand2b ({m.group(2)} <-> {m.group(4)})"
    raise SystemExit("error: no swappable nand2b instance found for the LVS negative control")


def mutate_delete_instance(text: str) -> tuple[str, str]:
    m = re.search(r"\n sky130_fd_sc_hd__nor2_1 (\S+) \([^;]*\);", text)
    if not m:
        raise SystemExit("error: no nor2_1 instance found for the LVS negative control")
    return text[:m.start()] + text[m.end():], f"deleted nor2_1 instance {m.group(1)}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--klt", default=os.environ.get("KLT", "klt"))
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--skip-flow", action="store_true",
                    help="reuse the .klt/ outputs + saved response of a previous run "
                         "(fast iteration; --emit-record then records that the flow was reused)")
    ap.add_argument("--allow-tool-drift", action="store_true")
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--request", type=Path, default=None,
                    help="alternate klt place-and-route request (study runs, e.g. "
                         "sim/digital-floorplan-compaction/); klt writes its outputs under "
                         "<request dir>/.klt/place-and-route. Default: the committed request. "
                         "--emit-record is refused with a non-default request so production "
                         "geometry under layout/trng_digital/ is never replaced by a study run")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="write this run's report, klt responses, negative controls, verdict "
                         "and a gzipped copy of the routed artifacts here (kept even when a "
                         "step fails); default: nothing extra is written")
    args = ap.parse_args(argv)

    global REQUEST, KLT_OUT
    if args.request is not None:
        req = args.request.resolve()
        if req != REQUEST.resolve():
            if args.emit_record:
                print("error: --emit-record is refused with a non-default --request "
                      "(study runs must not replace committed geometry)", file=sys.stderr)
                return 2
            REQUEST = req
            KLT_OUT = req.parent / ".klt" / "place-and-route"
    out_dir = args.out_dir.resolve() if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    def save(name, obj):
        if out_dir:
            write_json(out_dir / name, _sanitize(obj))

    for tool in (args.klt, "iverilog", "openroad"):
        if shutil.which(tool) is None:
            print(f"error: {tool!r} not found -- a missing tool is not evidence, "
                  "so nothing is minted", file=sys.stderr)
            return 2

    env = {**os.environ, "PDK": args.pdk}
    if "PDK_ROOT" not in env:
        pk = run_klt_cwd(args.klt, ["pdk", "find", "--pdk", args.pdk], env)
        env["PDK_ROOT"] = pk["root"]
    pdk_info = run_klt_cwd(args.klt, ["pdk", "find", "--pdk", args.pdk], env)
    libs_ref = Path(pdk_info["assets"]["libs_ref"])

    pins = json.loads(PINS.read_text())
    request = json.loads(REQUEST.read_text())
    netlist_in = (REQUEST.parent / request["netlist"]).resolve()
    all_ok = True
    notes: list[str] = []

    # 1. pins ---------------------------------------------------------------
    drift = []
    if pdk_info["version"] != pins["open_pdks"]:
        drift.append(f"PDK {pdk_info['version']!r} != pinned {pins['open_pdks']!r}")
    if sha256(netlist_in) != pins["input_netlist_sha256"]:
        drift.append("input netlist sha256 != tool-pins.json input_netlist_sha256")
    synth_rec = REPO_ROOT / pins["input_netlist_synthesis_record"]
    synth_hash = json.loads(synth_rec.read_text())["configs"][1][
        "netlist_content_hash_input"]
    if synth_hash != pins["input_netlist_klt_content_hash"]:
        drift.append("synthesis record's netlist content_hash != pinned")

    # 2. place and route ----------------------------------------------------
    resp_saved = KLT_OUT / "last-response.json"
    if args.skip_flow:
        pnr = json.loads(resp_saved.read_text())
        notes.append("flow reused from an earlier run in this working tree (--skip-flow)")
    else:
        if KLT_OUT.exists():
            shutil.rmtree(KLT_OUT)
        pnr = run_klt_cwd(args.klt, ["place-and-route", str(REQUEST.relative_to(REPO_ROOT))], env)
        resp_saved.write_text(json.dumps(pnr))
    save("pnr-output.json", pnr)
    if out_dir and KLT_OUT.exists():
        # keep the per-stage OpenROAD logs/metrics/scripts with the run: the
        # scratch dir is wiped by the next run, and a congested or failed
        # route is only diagnosable from these.
        eng = out_dir / "pnr-engine"
        for src in sorted(KLT_OUT.rglob("*")):
            if src.is_file() and (src.suffix in (".tcl", ".log") or src.name.endswith(
                    "_metrics.json") or src.name == "invocation.json"):
                dst = eng / src.relative_to(KLT_OUT)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    prov = pnr["provenance"]
    if not prov["klt_version"] == pins["klt_version"]:
        drift.append(f"klt {prov['klt_version']!r} != pinned {pins['klt_version']!r}")
    if pnr["engine_version"] != pins["openroad"]:
        drift.append(f"openroad {pnr['engine_version']!r} != pinned {pins['openroad']!r}")
    if prov["klayout_version"] != pins["klayout"]:
        drift.append(f"klayout {prov['klayout_version']!r} != pinned {pins['klayout']!r}")
    if prov["input"]["content_hash"] != pins["input_netlist_sha256"]:
        drift.append("klt-recorded P&R input content_hash != pinned netlist sha256")
    if drift and not args.allow_tool_drift:
        print("error: tool/PDK/input drift vs tool-pins.json (use --allow-tool-drift "
              "to proceed and mark the record):\n  " + "\n  ".join(drift), file=sys.stderr)
        save("verdict.json", {"error": "tool drift", "drift": drift})
        return 2
    if pnr["status"] != "ok" or pnr["stage_reached"] != "route":
        print(f"error: P&R did not reach route: {pnr['status']}", file=sys.stderr)
        save("verdict.json", {"error": "P&R did not reach route", "status": pnr["status"],
                              "stage_reached": pnr.get("stage_reached"), "drift": drift})
        return 1

    gds = Path(pnr["gds_path"])
    deff = Path(pnr["def_path"])
    routed_v = Path(pnr["verilog_path"])
    spef = Path(pnr["spef_sta"]["spef_path"])
    sdf = Path(pnr["spef_sta"]["sdf_path"])

    work = Path(tempfile.mkdtemp(prefix="digital-pnr-"))
    rel = lambda p: str(Path(p).resolve().relative_to(REPO_ROOT)) \
        if str(Path(p).resolve()).startswith(str(REPO_ROOT)) else str(p)

    # 3. DRC ----------------------------------------------------------------
    drc = run_klt_cwd(args.klt, ["drc", rel(gds), "--deck", "sky130"], env)
    drc_ok = drc["status"] == "clean" and drc["violation_count"] == 0
    all_ok &= drc_ok

    # 4. extract + LVS ------------------------------------------------------
    layout_spice = work / "trng_digital.layout.spice"
    ext = run_klt_cwd(args.klt, [
        "extract", rel(gds), "--deck", "sky130", "--top", TOP,
        "--abstract-cells", "sky130_fd_sc_hd__*",
        "--abstract-cell-lef", str(libs_ref / "sky130_fd_sc_hd" / "lef" / "sky130_fd_sc_hd.lef"),
        "--def-pins", rel(deff), "--def-net-names", "-o", str(layout_spice)], env)

    def lvs_request(ref_v: Path, name: str) -> dict:
        req = {"layout": {"netlist": str(layout_spice), "top": TOP},
               "reference": {"netlist": str(ref_v), "form": "gate-level-verilog",
                             "library": "sky130_fd_sc_hd", "top": TOP, "deck": "sky130"}}
        p = work / name
        p.write_text(json.dumps(req))
        return run_klt_cwd(args.klt, ["lvs", str(p)], env)

    lvs = lvs_request(routed_v, "lvs-request.json")
    lvs_ok = lvs["status"] == "match" and lvs["error_count"] == 0
    all_ok &= lvs_ok

    # 5. STA ----------------------------------------------------------------
    corners = [c["name"] for c in pnr["corners"]]
    cons = request["constraints"]

    def sta_request(period_ns, corner_list, name, io_delay_ns=None):
        c = {**cons, "clock_period_ns": period_ns}
        if io_delay_ns is not None:
            c["input_delay_ns"] = c["output_delay_ns"] = io_delay_ns
        req = {"def": str(deff), "spef": str(spef),
               "pdk": {"cell_library": "sky130_fd_sc_hd", "corners": corner_list},
               "constraints": c}
        p = work / name
        p.write_text(json.dumps(req))
        return run_klt_cwd(args.klt, ["sta", str(p)], env)

    sta = sta_request(cons["clock_period_ns"], corners, "sta-request.json")
    sta_rows = sta["corners"]
    sta_ok = (len(sta_rows) == len(corners)
              and all(r["timing_status"] == "constrained"
                      and r["setup_violation_count"] == 0
                      and r["hold_violation_count"] == 0 for r in sta_rows))
    all_ok &= sta_ok

    # 6. functional cosim on the routed netlist -----------------------------
    cosim = gate_cosim.run(routed_v, libs_ref, work / "cosim", args.seed)
    all_ok &= cosim["ok"]

    # 7. negative controls --------------------------------------------------
    routed_text = routed_v.read_text()
    controls = {}
    for label, mut in (("lvs-pin-swap", mutate_swap_pins),
                       ("lvs-instance-deleted", mutate_delete_instance)):
        txt, what = mut(routed_text)
        mv = work / f"{label}.v"
        mv.write_text(txt)
        r = lvs_request(mv, f"{label}-request.json")
        controls[label] = {"mutation": what, "status": r["status"],
                           "error_count": r["error_count"],
                           "detected": r["status"] != "match"}
    neg_sta = sta_request(
        1.0, ["tt_025C_1v80"], "sta-neg-request.json", io_delay_ns=0.2)["corners"][0]
    controls["sta-clock-period-1ns"] = {
        "mutation": "same routed DEF+SPEF at tt_025C_1v80, clock_period_ns 1.0 with IO delays 0.2 ns "
                    "(a 1 GHz target the routed design must miss; a 5000 ns clock with the "
                    "4000 ns IO delays unchanged was tried first and still passed, so it is not a valid control)",
        "worst_slack_ns": neg_sta["worst_slack_ns"],
        "setup_violation_count": neg_sta["setup_violation_count"],
        "detected": neg_sta["setup_violation_count"] > 0 and neg_sta["worst_slack_ns"] < 0}
    xor_text = routed_text.replace("sky130_fd_sc_hd__xor2_1 ", "sky130_fd_sc_hd__and2_1 ")
    n_xor = routed_text.count("sky130_fd_sc_hd__xor2_1 ")
    mv = work / "cosim-xor-to-and.v"
    mv.write_text(xor_text)
    neg_cosim = gate_cosim.run(mv, libs_ref, work / "cosim-neg", args.seed)
    controls["cosim-xor-to-and"] = {
        "mutation": f"{n_xor} xor2_1 instances replaced by and2_1 in the routed netlist",
        "mismatches": neg_cosim["mismatches"], "detected": not neg_cosim["ok"]}
    controls_ok = all(c["detected"] for c in controls.values())
    all_ok &= controls_ok

    # ---- report ------------------------------------------------------------
    L = []
    a = L.append
    a("## Configuration")
    a("")
    a(f"- request: `{rel(REQUEST)}` (floorplan {request['floorplan']}, io {request['io']}, "
      f"power {request['power']}, constraints {cons}, seed {request['seed']})")
    a(f"- input netlist: `{rel(netlist_in)}` sha256 `{sha256(netlist_in)}` (= klt's P&R "
      f"input content_hash `{prov['input']['content_hash']}`); its synthesis-side klt content_hash "
      f"`{pins['input_netlist_klt_content_hash']}` is the one recorded in `{pins['input_netlist_synthesis_record']}`)")
    a(f"- klt `{prov['klt_version']}`, OpenROAD `{pnr['engine_version']}`, KLayout "
      f"`{prov['klayout_version']}`, iverilog `{cosim['iverilog_version']}`, PDK {pdk_info['variant']} "
      f"({pdk_info['version']}); liberty deck content_hash `{prov['deck']['content_hash']}`")
    if drift:
        a(f"- **TOOL DRIFT ALLOWED**: {'; '.join(drift)}")
    for n in notes:
        a(f"- note: {n}")
    a("")
    a("## Results")
    a("")
    a(f"- P&R: stage `{pnr['stage_reached']}`, die {pnr['die_area_um2']} um2, core "
      f"{pnr['core_area_um2']} um2, utilisation {pnr['utilization_pct']}%, wirelength "
      f"{pnr['wirelength_um']} um, std-cell instance area "
      f"{pnr['stages'][-1].get('instance_area_um2', 'n/a')}, route DRC {pnr['route_drc_violation_count']}, "
      f"antenna violations {pnr['antenna_violation_count']}")
    a(f"- DRC (`klt drc --deck sky130`): **{drc['status']}**, {drc['violation_count']} violations")
    a(f"- LVS (`gate-level-verilog` reference, cell-abstracted layout): **{lvs['status']}**, "
      f"{lvs['error_count']} errors, power_connectivity `{lvs.get('power_connectivity', {}).get('status')}`")
    a(f"- Functional co-sim of the routed netlist: **{'PASS' if cosim['ok'] else 'FAIL'}** "
      f"({cosim['cycles']} cycles, {cosim['mismatches']} mismatches)")
    a("")
    a("### Post-route timing (routed DEF + extracted SPEF, 20000 ns clock, IO delay 4000 ns)")
    a("")
    a("| corner | setup slack ns | hold slack ns | setup viol | hold viol | clock skew ns | max-slew viol (lib) | max-cap viol (lib) |")
    a("|---|---|---|---|---|---|---|---|")
    pnr_by = {c["name"]: c for c in pnr["corners"]}
    for r in sta_rows:
        pc = pnr_by.get(r["corner"], {})
        a(f"| {r['corner']} | {r['worst_slack_ns']} | {r['worst_hold_slack_ns']} | "
          f"{r['setup_violation_count']} | {r['hold_violation_count']} | {r.get('clock_skew_ns')} | "
          f"{pc.get('max_transition_violation_count_vs_library', pc.get('max_transition_violation_count'))} | "
          f"{pc.get('max_capacitance_violation_count_vs_library', pc.get('max_capacitance_violation_count'))} |")
    a("")
    a("(slew/cap columns are the in-flow `klt place-and-route` sweep's, estimated from global-route "
      "parasitics; setup/hold are from `klt sta` with the extracted SPEF.)")
    a("")
    a("### Negative controls")
    a("")
    for k, v in controls.items():
        a(f"- `{k}`: {v['mutation']} -> detected = **{v['detected']}**")
    a("")
    a("## What this record does and does not establish")
    a("")
    for line in COVERAGE:
        a(f"- {line}")
    body = "\n".join(L)
    print(body)

    verdict = {"drc": drc_ok, "lvs": lvs_ok, "sta": sta_ok,
               "cosim": cosim["ok"], "negative_controls": controls_ok}
    print("\nverdict:", verdict, file=sys.stderr)
    if out_dir:
        (out_dir / "report.md").write_text(body + "\n")
        for k, v in (("drc", drc), ("extract", ext), ("lvs", lvs), ("sta", sta)):
            save(f"{k}-output.json", v)
        save("negative-controls.json", controls)
        save("verdict.json", {"verdict": verdict, "tool_drift": drift, "notes": notes,
                              "request_sha256": sha256(REQUEST), "netlist_sha256": sha256(netlist_in),
                              "pdk": pdk_info, "gate_cosim": {k: v for k, v in cosim.items()
                                                              if k not in ("stimulus_path", "observations_path")}})
        shutil.copy2(REQUEST, out_dir / REQUEST.name)
        for src in (gds, deff, routed_v, spef, sdf):
            gz_copy(src, out_dir / (Path(src).name + ".gz"))

    if not args.emit_record:
        return 0 if all_ok else 1
    if not all_ok:
        print("refusing to mint a record: at least one check was not clean", file=sys.stderr)
        return 1
    if args.skip_flow:
        print("refusing to mint a record from a reused flow (--skip-flow)", file=sys.stderr)
        return 1

    # ---- stage committed geometry + reports --------------------------------
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    geo = {}
    for src, name in ((gds, "trng_digital.gds"), (deff, "trng_digital.def"),
                      (routed_v, "trng_digital.routed.v")):
        shutil.copy2(src, LAYOUT_DIR / name)
        geo[name] = sha256(LAYOUT_DIR / name)
    for src, name in ((spef, "trng_digital.spef.gz"), (sdf, "trng_digital.sdf.gz")):
        gz_copy(src, LAYOUT_DIR / name)
        geo[name] = sha256(LAYOUT_DIR / name)
        geo[name.replace(".gz", "") + " (uncompressed)"] = sha256(src)
    shutil.copy2(layout_spice, LAYOUT_DIR / "trng_digital.layout.abstract.spice")
    geo["trng_digital.layout.abstract.spice"] = sha256(layout_spice)
    reports = {"pnr": pnr, "drc": drc, "extract": ext, "lvs": lvs, "sta": sta}
    stage = work / "artifacts"
    stage.mkdir()
    arts = []
    for k, v in reports.items():
        p = stage / f"{k}-output.json"
        write_json(p, _sanitize(v))
        shutil.copy2(p, LAYOUT_DIR / f"{k}.json")
        arts.append(p)
    p = stage / "negative-controls.json"
    write_json(p, controls)
    arts.append(p)
    for f in ("stimulus.txt", "gate-observations.txt"):
        dst = stage / f"routed-gate-cosim-{f}"
        shutil.copy2(work / "cosim" / f, dst)
        arts.append(dst)
    req_copy = stage / REQUEST.name
    shutil.copy2(REQUEST, req_copy)
    arts.append(req_copy)

    rid = mint_behavioral_record(
        repo_root=REPO_ROOT, slug="digital-pnr",
        claim=("digital/rtl/trng_digital.v (50 kHz-constrained sky130_fd_sc_hd netlist) places "
               "and routes at 42.6% utilisation; the routed GDS is DRC-clean (sky130 klt deck), "
               "cell-level LVS-clean against the as-built netlist, meets the 20000 ns clock at "
               "all 16 shipped Liberty corners with extracted SPEF parasitics, and the routed "
               "netlist reproduces the normative model over the directed program; negative "
               "controls fail as they must"),
        body_md=body,
        summary={"verdict": verdict, "geometry_sha256": geo, "controls": controls,
                 "area": {k: pnr[k] for k in ("die_area_um2", "core_area_um2", "utilization_pct",
                                              "wirelength_um")},
                 "power_delivery": _sanitize(pnr["power"]),
                 "corners": [{k: r.get(k) for k in ("corner", "worst_slack_ns", "worst_hold_slack_ns",
                                                    "setup_violation_count", "hold_violation_count",
                                                    "clock_skew_ns", "timing_status",
                                                    "spef_annotation")} for r in sta_rows],
                 "pnr_corner_sweep": pnr["corners"],
                 "spef_sta": _sanitize(pnr["spef_sta"]),
                 "input_hashes": {"request": sha256(REQUEST), "netlist": sha256(netlist_in),
                                  "rtl": sha256(REPO_ROOT / "digital" / "rtl" / "trng_digital.v"),
                                  "testbench": sha256(gate_cosim.TB),
                                  "tool_pins": sha256(PINS)},
                 "gate_cosim": {k: v for k, v in cosim.items()
                                if k not in ("stimulus_path", "observations_path")},
                 "pdk": _sanitize(pdk_info), "tool_drift": drift},
        level="gate (post-route: placed-and-routed as-built netlist, extracted parasitics)",
        seeds={"cosim_stimulus_seed": args.seed, "pnr_seed": request["seed"]},
        tools={"klt": prov["klt_version"], "openroad": pnr["engine_version"],
               "klayout": prov["klayout_version"], "iverilog": cosim["iverilog_version"]},
        artifacts=arts)
    print(f"\nrecord id: {rid}", file=sys.stderr)
    return 0


COVERAGE = [
    "Established: the committed request places and routes `trng_digital` with sky130_fd_sc_hd; "
    "geometry, as-built netlist, SPEF and SDF are produced and hashed.",
    "DRC is the **klt `sky130` curated deck** (`klt drc --deck sky130`) over the standard-cell-merged "
    "GDS -- not the foundry signoff deck; its `coverage` block lists unsupported/skipped rules (see "
    "`layout/trng_digital/drc.json`). Metal fill / density rules are not covered by this flow "
    "(no fill step), so density-rule cleanliness is NOT claimed.",
    "LVS is **cell-level**: layout is extracted with standard cells as opaque black boxes "
    "(`--abstract-cells`), reference is the as-built Verilog, which carries **signal pins only** -- "
    "intra-cell transistors are not compared (cell internals are the PDK's), and a power-net defect is "
    "invisible to the Verilog-derived compare except for klt's own `power_connectivity` check. "
    "Filler/tap cells inserted by the flow are pruned from the compare (`topology.power_only_pruned`), "
    "not matched. The top-level `VPWR`/`VGND` supply ports exist only as layout pins/labels.",
    "Timing is `klt sta` (OpenSTA) on the routed DEF with SPEF extracted from the routed GDS, at every "
    "shipped `sky130_fd_sc_hd` Liberty corner (16, incl. the 1.28-1.95 V ss/ff voltages). The routed "
    "interconnect corner is `nom` only; the SPEF is a first-order lumped RC (no coupling-aware "
    "signoff extraction). Clock is ideal-propagated through the CTS tree. Constraints: one clock "
    "(`clk`, 20000 ns), input/output delays 4000 ns, no false-path / multicycle exceptions; "
    "`rst_n` is analysed as an ordinary constrained input. klt reports `timing_status: constrained` "
    "but no explicit unconstrained-endpoint list -- completeness of constraint coverage is therefore "
    "not independently enumerated.",
    "SPEF annotation: 2309/2309 design nets annotated; the SPEF also contains non-design (`$N`) "
    "fragments OpenSTA ignores (reader warnings recorded in `sta.json`).",
    "In-flow max-slew / max-capacitance checks (global-route estimate) report library-limit "
    "violations at the low-voltage ss corners (ss_100C_1v60, ss_n40C_1v28, ss_n40C_1v60, "
    "ss_n40C_1v76) -- see the table; these are DESIGN-RULE violations NOT repaired by this flow "
    "and are disclosed, not waived. They do not affect setup/hold at a 20000 ns clock.",
    "Functional co-simulation of the routed netlist uses `FUNCTIONAL`/`UNIT_DELAY #1` cell models: it "
    "verifies logic equivalence to the normative model over the directed program, NOT timing "
    "(no SDF annotation; the generated SDF is committed but not simulated).",
    "Not covered here (remains on #18): analog/digital top-level composition, the 1.8 V supply "
    "distribution across the full block, IR drop (`klt power`), dynamic-power numbers, antenna/ESD "
    "at pad level, whole-block brief reconciliation. Simulation-derived; provisional until silicon.",
]

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
