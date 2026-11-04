#!/usr/bin/env python3
"""SDF-annotated routed-netlist verification of `trng_digital` through the
pinned native `klt functional-verification` interface (klayout-tools 0.7.0,
cocotb 2.0.1, Icarus 13.0) -- issue #227.

This is a SEPARATE campaign from `sim/digital-functional-verification` (#222),
which stays the functional / unit-delay baseline and is not touched. Here the
routed netlist `layout/trng_digital/trng_digital.routed.v` is simulated against
the sky130_fd_sc_hd *timing* (non-FUNCTIONAL, `specify`) cell models with the
post-route `layout/trng_digital/trng_digital.sdf.gz` back-annotated via
`options.sdf`, driven by the SAME directed program and the SAME independent
oracle (`digital/model`) as #222 / `sim/digital-rtl-equivalence`.

Runs (every one is a native `klt functional-verification` run, sequential):

  timed-declared      SDF, clock period 20000 ns (the 50 kHz period the P&R
                      request constrained). MUST pass 13/13, `environment.sdf`
                      an object with `annotated: true`, traces byte-identical
                      to the oracle, and a non-zero SDF-shaped output-latency
                      probe. This is the baseline the controls are judged on.
  timed-at-speed      SDF, 8 ns period (inputs launched / outputs sampled at
                      half period): MUST pass -- a stress point, not an fmax.
  Controls (each MUST be detected, i.e. NOT be accepted as timed coverage):
  ctl-sdf-removed     same models, no `options.sdf`: passes functionally but
                      `environment.sdf` is null and every probed latency is 0.
  ctl-sdf-mistargeted every instance name in the SDF renamed: the tool's own
                      diagnostic gate must refuse the run (exit != 0).
  ctl-delay-shift     +137 ps on one flop's CLK->Q arc: the oracle still passes
                      and that flop's output latency moves by EXACTLY +137 ps on
                      every observed edge (proves the annotation reached that
                      instance/arc and nothing masks a changed SDF).
  ctl-delay-fail      +15000 ns on the same arc: the oracle MUST fail.
  ctl-clock-5ns       SDF at 5 ns period MUST fail while the identical run
                      WITHOUT the SDF (ctl-clock-5ns-unannotated) passes: the
                      failure is caused by the back-annotated delays.

Fail-closed: a pin mismatch, missing tool, unclean baseline or an undetected
control refuses to mint a record. Nothing here changes the ratified spec;
timing evidence is simulation-derived and provisional.

    uv venv .venv && uv pip install --python .venv/bin/python \
        "klayout-tools==0.7.0" "cocotb==2.0.1"
    python3 sim/digital-sdf-timed-verification/harness/fv-sdf-cosim.py \
        --klt .venv/bin/klt --emit-record
"""

from __future__ import annotations

import argparse
import difflib
import gzip
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FV = _load(REPO_ROOT / "sim" / "digital-functional-verification" / "harness"
           / "fv-cosim.py", "fv_cosim_222")
rtl_cosim = _load(REPO_ROOT / "sim" / "digital-rtl-equivalence" / "harness"
                  / "rtl-cosim.py", "rtl_cosim")
sha256, rel, run_fv = FV.sha256, FV.rel, FV.run_fv
PINS, DEFAULT_SEED = FV.PINS, FV.DEFAULT_SEED

SLUG = "digital-sdf-timed-verification"
TB_DIR, TB_MODULE = FV.TB_DIR, FV.TB_MODULE
ROUTED, STA_JSON = FV.ROUTED, FV.STA_JSON
SDF_GZ = REPO_ROOT / "layout" / "trng_digital" / "trng_digital.sdf.gz"
PNR_REQ = REPO_ROOT / "digital" / "flow" / "place-and-route" / "pnr-trng-digital-50khz.json"

CLK_DECLARED_NS = 20000       # = constraints.clock_period_ns of the P&R request
CLK_FAST_NS = 8
CLK_FAIL_NS = 5
SDF_CORNER = "typ"            # the SDF carries a single value per arc (min=typ=max)
SHIFT_PS = 137
SHIFT_FAIL_NS = 15000
SHIFT_INST = "_3399_"         # dfrtp_1 whose Q is startup_done_r (-> startup_done)
SHIFT_SIGNAL = "startup_done"
PROBE_OUTPUTS = ("bus_rdata", "out_data", "startup_done")  # see COVERAGE note


# ---------------------------------------------------------------- SDF helpers
def read_sdf_gz(p: Path) -> str:
    return gzip.decompress(p.read_bytes()).decode()


def gz_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as g:
        g.write(text.encode())
    return buf.getvalue()


_PORT_SRC = re.compile(
    r"^\s*\(INTERCONNECT\s+(\w+)\[(\d+)\]\s+\S+\s+\(0\.000:0\.000:0\.000\)\)\s*$")


def drop_zero_port_source_interconnects(text: str, ports: tuple[str, ...]):
    """Drop `INTERCONNECT <bus>[i] <inst>.<pin> (0:0:0)` entries whose SOURCE is a
    bit-selected top-level input bus bit. Icarus 13.0 cannot resolve those as
    intermodpath sources (klt functional-verification finding 9b: unfixable,
    left loud), so the tool refuses the run. Only entries whose every value is
    0.000 are dropped -- by construction they carry no delay."""
    out, dropped = [], []
    for ln in text.split("\n"):
        m = _PORT_SRC.match(ln)
        if m and m.group(1) in ports:
            dropped.append(ln.strip())
            continue
        out.append(ln)
    return "\n".join(out), dropped


def shift_iopath(text: str, inst: str, d_ns: float) -> str:
    """Add d_ns to every value of the `IOPATH CLK Q` arc of `inst`."""
    i = text.index(f"(INSTANCE {inst})")
    j = text.index("(IOPATH CLK Q", i)
    k = text.index("\n", j)
    line = text[j:k]

    def bump(m):
        return f"{float(m.group(0)) + d_ns:.3f}"
    new = re.sub(r"-?\d+\.\d+", bump, line)
    return text[:j] + new + text[k:]


def mistarget(text: str) -> str:
    return text.replace("(INSTANCE _", "(INSTANCE _zz")


def unified(a: str, b: str, name: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                        f"a/{name}", f"b/{name}", n=1))


def sdf_census(text: str, netlist_text: str) -> dict:
    """Independent (non-tool) account of what the SDF covers vs the netlist."""
    cells = re.findall(r'\(CELLTYPE "([^"]+)"\)\s*\(INSTANCE ([^)\s]+)\)', text)
    sdf_inst = {i: t for t, i in cells}
    net = {m.group(2): m.group(1) for m in re.finditer(
        r"^\s*(sky130_fd_sc_hd__\w+)\s+(\S+)\s*\(", netlist_text, re.M)}
    both = [i for i in net if i in sdf_inst]
    mism = [i for i in both if net[i] != sdf_inst[i]]
    return {
        "sdf_iopath_entries": len(re.findall(r"\(IOPATH ", text)),
        "sdf_interconnect_entries": len(re.findall(r"\(INTERCONNECT ", text)),
        "sdf_interconnect_nonzero": len([l for l in text.split("\n")
                                         if "(INTERCONNECT" in l
                                         and "(0.000:0.000:0.000)" not in l]),
        "sdf_timingcheck_sections": text.count("(TIMINGCHECK"),
        "sdf_cell_instances": len(sdf_inst),
        "netlist_cell_instances": len(net),
        "netlist_instances_present_in_sdf": len(both),
        "celltype_mismatches": len(mism),
        "netlist_instances_absent_from_sdf": sorted(set(net) - set(sdf_inst))[:5]
        + (["..."] if len(set(net) - set(sdf_inst)) > 5 else []),
        "netlist_instances_absent_count": len(set(net) - set(sdf_inst)),
        "sdf_instances_absent_from_netlist": len(set(sdf_inst) - set(net)),
    }


# ---------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--klt", default=os.environ.get("KLT", "klt"))
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)

    for tool in (args.klt, "iverilog"):
        if shutil.which(tool) is None:
            print(f"error: {tool!r} not found -- a missing tool is not evidence",
                  file=sys.stderr)
            return 2
    ver = subprocess.run([args.klt, "--version"], capture_output=True, text=True)
    klt_version = ver.stdout.strip() or ver.stderr.strip()
    if klt_version != PINS["klt"]:
        print(f"error: klt {klt_version!r} != pinned {PINS['klt']!r}; use a venv "
              "with klayout-tools==0.7.0, never change the host tool.",
              file=sys.stderr)
        return 2
    env = {**os.environ, "PDK": args.pdk}
    pk = subprocess.run([args.klt, "pdk", "find", "--pdk", args.pdk, "--format",
                         "json"], capture_output=True, text=True, env=env)
    if pk.returncode != 0:
        print(f"error: klt pdk find failed: {pk.stderr.strip()}", file=sys.stderr)
        return 2
    pdk_info = json.loads(pk.stdout)
    libs_ref = Path(pdk_info["assets"]["libs_ref"])
    prim = libs_ref / "sky130_fd_sc_hd" / "verilog" / "primitives.v"
    cells = libs_ref / "sky130_fd_sc_hd" / "verilog" / "sky130_fd_sc_hd.v"
    for f in (prim, cells):
        if not f.exists():
            print(f"error: PDK Verilog source missing: {f}", file=sys.stderr)
            return 2

    work = Path(tempfile.mkdtemp(prefix="digital-sdf-fv-"))
    san = FV.Sanitizer(libs_ref, work)
    problems: list[str] = []

    cycles, phases = rtl_cosim.build_program(args.seed)
    n_cycles, n_phases = len(cycles), len(phases)
    expected_tests = n_phases + 2

    # -- SDF inputs ---------------------------------------------------------
    sdf_src = read_sdf_gz(SDF_GZ)
    routed_text = ROUTED.read_text()
    census = sdf_census(sdf_src, routed_text)
    pnr_req = json.loads(PNR_REQ.read_text())
    if not pnr_req.get("post_route_sdf"):
        problems.append("P&R request does not declare post_route_sdf")
    sdf_base, dropped = drop_zero_port_source_interconnects(
        sdf_src, ("bus_addr", "bus_wdata"))
    sdf_variants = {
        "baseline": sdf_base,
        "mistargeted": mistarget(sdf_base),
        "delay-shift": shift_iopath(sdf_base, SHIFT_INST, SHIFT_PS / 1000.0),
        "delay-fail": shift_iopath(sdf_base, SHIFT_INST, float(SHIFT_FAIL_NS)),
    }
    sdf_paths = {}
    for k, t in sdf_variants.items():
        p = work / "sdf" / f"trng_digital.{k}.sdf"
        p.parent.mkdir(exist_ok=True)
        p.write_text(t)
        sdf_paths[k] = p
    if len(dropped) == 0 or any("0.000:0.000:0.000" not in d for d in dropped):
        problems.append("derived-SDF drop set is empty or not all zero-delay")

    base_env = {"TRNG_FV_SEED": str(args.seed)}

    def request(sdf_key: str | None) -> dict:
        r = {
            "schema": "klt.functional_verification.request/1",
            "engine": PINS["engine"],
            # NO defines file: the non-FUNCTIONAL (specify) cell models are the
            # annotatable ones; `options.sdf` + `FUNCTIONAL` is rejected.
            "sources": [str(prim), str(cells), str(ROUTED)],
            "hdl_toplevel": "trng_digital",
            "testbench": {"module": TB_MODULE, "search_path": str(TB_DIR)},
            "options": {"random_seed": 1},
        }
        if sdf_key:
            r["options"]["sdf"] = {"file": str(sdf_paths[sdf_key]),
                                   "corner": SDF_CORNER}
        return r

    def go(label: str, sdf_key: str | None, clk_ns: int) -> dict:
        rdir = work / label
        obs = rdir / "traces"
        probe = rdir / "timing-probe.json"
        run = run_fv(args.klt, request(sdf_key), rdir, env_extra={
            **base_env, "TRNG_FV_CLK_NS": str(clk_ns),
            "TRNG_FV_OBS_OUT": str(obs), "TRNG_FV_TIMING_OUT": str(probe)})
        r = run["report"] or {}
        envr = r.get("environment") or {}
        s = FV.summarize(run)
        lens = {}
        for nm in ("stimulus", "observations", "model-observations"):
            f = obs / f"{nm}.txt"
            lens[nm] = len(f.read_text().splitlines()) if f.exists() else None
        ident = (obs / "observations.txt").exists() and \
            (obs / "observations.txt").read_bytes() == \
            (obs / "model-observations.txt").read_bytes()
        pr = json.loads(probe.read_text())["probe"] if probe.exists() else {}
        pstat = {k: {c: {"n": len(v), "min_ps": min(v), "max_ps": max(v)}
                     for c, v in d.items() if v} for k, d in pr.items()}
        return {"label": label, "run": run, "summary": s, "env": envr,
                "sdf": envr.get("sdf"), "clk_ns": clk_ns, "lens": lens,
                "identical": ident, "probe": pr, "probe_stat": pstat,
                "traces": obs, "probe_path": probe, "sdf_key": sdf_key,
                "cocotb": envr.get("cocotb_version"),
                "icarus": envr.get("engine_version")}

    def probe_nonzero(x: dict) -> bool:
        """Every probed registered output has events and ALL latencies > 0."""
        for sig in PROBE_OUTPUTS:
            lst = (x["probe"].get(sig) or {}).get("clk_to_out_ps") or []
            if not lst or min(lst) <= 0:
                return False
        return True

    def timed_ok(x: dict) -> bool:
        """The acceptance gate for 'SDF-timed, passing coverage'."""
        s, sdf = x["summary"], x["sdf"]
        return bool(
            x["run"]["rc"] == 0 and s["status"] == "pass"
            and s["test_count"] == expected_tests and s["passed"] == expected_tests
            and s["failed"] == 0 and s["skipped"] == 0
            and isinstance(sdf, dict) and sdf.get("annotated") is True
            and sdf.get("corner") == SDF_CORNER
            and x["lens"]["stimulus"] == x["lens"]["observations"]
            == x["lens"]["model-observations"] == n_cycles and x["identical"]
            and probe_nonzero(x)
            and x["cocotb"] == PINS["cocotb"] and x["icarus"] == PINS["icarus"])

    # -- baselines -----------------------------------------------------------
    declared = go("timed-declared", "baseline", CLK_DECLARED_NS)
    fast = go("timed-at-speed", "baseline", CLK_FAST_NS)
    for x in (declared, fast):
        if not timed_ok(x):
            problems.append(f"{x['label']}: not a clean SDF-timed pass "
                            f"({x['summary']}, sdf={x['sdf'] and x['sdf'].get('annotated')})")

    # -- controls -------------------------------------------------------------
    controls: dict[str, dict] = {}

    def record(name, desc, x, detected, why):
        controls[name] = {"description": desc, "detected": bool(detected),
                          "evidence": why, "run": x,
                          **{k: x["summary"][k] for k in
                             ("rc", "status", "test_count", "passed", "failed",
                              "failed_tests")}}
        if not detected:
            problems.append(f"control {name}: NOT detected ({why})")

    removed = go("ctl-sdf-removed", None, CLK_DECLARED_NS)
    record("sdf-removed",
           "identical models/netlist/testbench/period, `options.sdf` omitted",
           removed,
           removed["summary"]["status"] == "pass" and removed["sdf"] is None
           and not timed_ok(removed) and not probe_nonzero(removed),
           f"functional verdict {removed['summary']['status']}, "
           f"environment.sdf={removed['sdf']}, output latencies all 0 ps "
           f"-> the timed-coverage gate rejects it")

    mis = go("ctl-sdf-mistargeted", "mistargeted", CLK_DECLARED_NS)
    try:       # the tool prints its error envelope on stderr (stdout is empty)
        err = json.loads(mis["run"]["stderr"]).get("error", {}).get("message", "")
    except json.JSONDecodeError:
        err = mis["run"]["stderr"]
    record("sdf-mistargeted",
           "every `(INSTANCE _N_)` in the SDF renamed `_zzN_` (no instance matches)",
           mis, mis["run"]["rc"] != 0 and "did not fully apply" in err
           and not timed_ok(mis),
           f"tool exit {mis['run']['rc']} (error envelope on stderr, preserved as "
           f"`ctl-sdf-mistargeted.stderr.json`): {err[:230]}...")

    # exact delay-shift: oracle still passes, latency moves by exactly SHIFT_PS
    shift = go("ctl-delay-shift", "delay-shift", CLK_DECLARED_NS)
    b_l = (declared["probe"].get(SHIFT_SIGNAL) or {}).get("clk_to_out_ps") or []
    s_l = (shift["probe"].get(SHIFT_SIGNAL) or {}).get("clk_to_out_ps") or []
    deltas = [b - a for a, b in zip(b_l, s_l)]
    exact = (len(b_l) == len(s_l) > 0 and set(deltas) == {SHIFT_PS})
    other_same = all(
        (declared["probe"].get(sg) or {}).get("clk_to_out_ps")
        == (shift["probe"].get(sg) or {}).get("clk_to_out_ps")
        for sg in ("bus_rdata", "out_data"))
    record("delay-shift-exact",
           f"+{SHIFT_PS} ps on the `IOPATH CLK Q` arc of {SHIFT_INST} "
           f"(the flop driving `{SHIFT_SIGNAL}`)",
           shift, timed_ok(shift) and exact and other_same,
           f"oracle {shift['summary']['status']}; {SHIFT_SIGNAL} clk->out "
           f"latencies {b_l} -> {s_l} (deltas {sorted(set(deltas))}); "
           f"bus_rdata/out_data latencies unchanged: {other_same}")

    fail = go("ctl-delay-fail", "delay-fail", CLK_DECLARED_NS)
    record("delay-fail",
           f"+{SHIFT_FAIL_NS} ns on the same arc (output settles after the sample point)",
           fail, fail["run"]["rc"] == 3 and fail["summary"]["status"] == "fail"
           and fail["summary"]["failed"] > 0
           and (fail["sdf"] or {}).get("annotated") is True,
           f"exit {fail['run']['rc']}, {fail['summary']['failed']}/"
           f"{fail['summary']['test_count']} tests failed: "
           f"{fail['summary']['failed_tests']}")

    f5 = go("ctl-clock-5ns", "baseline", CLK_FAIL_NS)
    f5n = go("ctl-clock-5ns-unannotated", None, CLK_FAIL_NS)
    record("clock-5ns",
           f"SDF baseline at {CLK_FAIL_NS} ns period (half period shorter than the annotated output paths)",
           f5, f5["run"]["rc"] == 3 and f5["summary"]["failed"] > 0
           and (f5["sdf"] or {}).get("annotated") is True
           and f5n["run"]["rc"] == 0 and f5n["summary"]["status"] == "pass"
           and f5n["sdf"] is None,
           f"annotated: exit {f5['run']['rc']}, {f5['summary']['failed']}/"
           f"{f5['summary']['test_count']} failed {f5['summary']['failed_tests']}; "
           f"same run without SDF: exit {f5n['run']['rc']} "
           f"{f5n['summary']['status']} (zero-delay)")

    # -- item-7 review --------------------------------------------------------
    sdf_env = declared["sdf"] or {}
    dr_text = FV.DR0004.read_text()
    m = re.search(r"^status:\s*(\S+)", dr_text, re.M)
    dr_status = m.group(1) if m else "unknown"
    item7 = {
        "report_has_annotated_sdf_object": sdf_env.get("annotated") is True,
        "annotation_partial": sdf_env.get("partial"),
        "dropped_classes": {k: v.get("count") for k, v in
                            (sdf_env.get("dropped") or {}).items()},
        "single_sdf_corner": "tt_025C_1v80 (the P&R request's corner); not a PVT sweep",
        "dr_0004_status": dr_status,
    }
    pnr_rec = None
    for pth in sorted(REPO_ROOT.glob(FV.PNR_RECORD_GLOB)):
        pnr_rec = json.loads(pth.read_text())
    routed_hash = sha256(ROUTED)
    if not (pnr_rec and pnr_rec.get("geometry_sha256", {}).get(
            "trng_digital.routed.v") == routed_hash):
        problems.append("routed netlist sha256 != latest digital-pnr record's geometry hash")

    # -- hashes ---------------------------------------------------------------
    sdf_plain_hash = "sha256:" + __import__("hashlib").sha256(sdf_src.encode()).hexdigest()
    input_hashes = {rel(p): sha256(p) for p in
                    [ROUTED, SDF_GZ, STA_JSON, PNR_REQ, TB_DIR / f"{TB_MODULE}.py",
                     FV.RTL_COSIM, Path(__file__).resolve(), *FV.MODEL_FILES]}
    input_hashes["layout/trng_digital/trng_digital.sdf (decompressed)"] = sdf_plain_hash
    for k, p in sdf_paths.items():
        input_hashes[f"derived SDF: {k} (uncompressed)"] = sha256(p)
    input_hashes["$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/primitives.v"] = sha256(prim)
    input_hashes["$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"] = sha256(cells)
    input_hashes["model-observations.txt (oracle trace)"] = \
        sha256(declared["traces"] / "model-observations.txt")

    iverilog_v = rtl_cosim.iverilog_version()
    repro = ("uv venv .venv && uv pip install --python .venv/bin/python "
             "\"klayout-tools==0.7.0\" \"cocotb==2.0.1\" && "
             "python3 sim/digital-sdf-timed-verification/harness/fv-sdf-cosim.py "
             "--klt .venv/bin/klt --emit-record")
    all_ok = not problems
    verdict = {"timed_declared_baseline": timed_ok(declared),
               "timed_at_speed_baseline": timed_ok(fast),
               "controls_detected": all(c["detected"] for c in controls.values()),
               "sdf_annotated": item7["report_has_annotated_sdf_object"]}

    # -- body -----------------------------------------------------------------
    L: list[str] = []
    a = L.append
    a("## Configuration")
    a("")
    a(f"- native interface: `klt functional-verification` ({klt_version}), engine `icarus` "
      f"{PINS['icarus']}, cocotb {PINS['cocotb']}, simulator transcript tool `{iverilog_v}`; "
      "all numbers are read from the tool's own JSON reports (preserved per run).")
    a("- DUT: `layout/trng_digital/trng_digital.routed.v` (sha256 "
      f"`{routed_hash}`, bound to the committed digital-pnr record) against the "
      "sky130_fd_sc_hd **timing** (`specify`, non-`FUNCTIONAL`, no `UNIT_DELAY`) Verilog "
      "cell models, with `layout/trng_digital/trng_digital.sdf.gz` back-annotated "
      f"(`options.sdf`, corner selector `{SDF_CORNER}`, `entries: all`).")
    a(f"- stimulus/oracle: the #222 directed program (seed {args.seed}, {n_cycles} cycles, "
      f"{n_phases} phases), the independent normative model, {expected_tests} tests per run "
      "(drive + phases + exact length). Clock period is parameterised by "
      "`TRNG_FV_CLK_NS` in `digital/tb/cocotb/test_trng_digital_fv.py` (default 10 -> the "
      "#222 records are unaffected).")
    a("- declared timing: clock period 20000 ns (the 50 kHz period of "
      "`pnr-trng-digital-50khz.json`); inputs are launched at the falling edge "
      "(period/2 after the capturing edge) and outputs are sampled the next falling edge "
      "(period/2 after launch); reset asserted before the first rising edge and released "
      "at the first falling edge. The P&R SDC's 4000 ns input/output delays are inside "
      "that window (10000 ns).")
    a(f"- reproduction: `{repro}`")
    a("")
    a("## SDF provenance and annotation coverage")
    a("")
    a(f"- source SDF: `layout/trng_digital/trng_digital.sdf.gz` sha256 `{sha256(SDF_GZ)}`; "
      f"decompressed `{sdf_plain_hash}`. Corner: the P&R request's `tt_025C_1v80`, "
      "`INTERCONNECT` all zero, SDF carries one value per arc (min=typ=max for most arcs).")
    a(f"- independent census (not the tool's): {census['sdf_iopath_entries']} IOPATH, "
      f"{census['sdf_interconnect_entries']} INTERCONNECT "
      f"({census['sdf_interconnect_nonzero']} non-zero), {census['sdf_timingcheck_sections']} TIMINGCHECK "
      f"sections; {census['sdf_cell_instances']} SDF cell instances vs "
      f"{census['netlist_cell_instances']} netlist cell instances, "
      f"{census['netlist_instances_present_in_sdf']} present in both with "
      f"{census['celltype_mismatches']} cell-type mismatches; "
      f"{census['netlist_instances_absent_count']} netlist instances absent from the SDF "
      f"(e.g. {census['netlist_instances_absent_from_sdf'][:4]}), "
      f"{census['sdf_instances_absent_from_netlist']} SDF instances absent from the netlist.")
    a(f"- one preprocessing step, disclosed: {len(dropped)} `INTERCONNECT <bus_addr|bus_wdata>[i] "
      "<inst>.<pin> (0.000:0.000:0.000)` entries (bit-selected top-level input as source) were "
      "removed before handing the SDF to the tool, because Icarus 13.0 cannot resolve a "
      "bit-selected port as an intermodpath source (klt documents this as unfixable, "
      "functional_verification finding 9b) and the tool correctly refuses the run otherwise "
      "(31 `Could not find intermodpath!`). Every dropped entry is zero-delay, so no delay is lost. "
      "The unmodified SDF is not accepted by the tool; the derived SDF is hashed above and each "
      "report's `environment.sdf.file` names it.")
    a(f"- tool-reported (`timed-declared`, `environment.sdf`): annotated={sdf_env.get('annotated')}, "
      f"partial={sdf_env.get('partial')}, corner={sdf_env.get('corner')}, entries={sdf_env.get('entries')}, "
      f"dropped classes {item7['dropped_classes']}. **`partial: true`** because Icarus 13.0 does not "
      "implement SDF `TIMINGCHECK` (all 455 sections dropped: setup/hold/recovery/removal limits are NOT "
      "checked in simulation) and 33 zero-delay `INTERCONNECT` entries onto assign-aliased output "
      "ports are dropped. No `SDF WARNING`/`ERROR` remained actionable in any accepted run.")
    a("")
    a("## Timed baselines (must pass; byte-compared to the oracle)")
    a("")
    a("| Run | period | status | tests | sdf annotated | stimulus / observed / model lines | observed == model | probe latencies (ps, min..max) |")
    a("|---|---|---|---|---|---|---|---|")
    for x in (declared, fast):
        s, ln = x["summary"], x["lens"]
        pl = ", ".join(f"{k} {v['clk_to_out_ps']['min_ps']}..{v['clk_to_out_ps']['max_ps']} "
                       f"(n={v['clk_to_out_ps']['n']})"
                       for k, v in x["probe_stat"].items() if "clk_to_out_ps" in v)
        a(f"| {x['label']} | {x['clk_ns']} ns | **{s['status']}** | {s['passed']}/{s['test_count']} | "
          f"{(x['sdf'] or {}).get('annotated')} | {ln['stimulus']} / {ln['observations']} / "
          f"{ln['model-observations']} | {x['identical']} | {pl} |")
    a("")
    a("Per-test results (timed-declared):")
    a("")
    for t in (declared["run"]["report"] or {}).get("tests", []):
        a(f"- `{t['name']}`: {t['status']}")
    a("")
    a("## Annotation / timing controls (each must be detected)")
    a("")
    for name, c in controls.items():
        a(f"- `{name}`: {c['description']} -> **detected = {c['detected']}**. {c['evidence']}")
    a("")
    a("## T1 item 7 (digital) review")
    a("")
    a("- The checklist's digital item 7 accepts a `klt functional-verification` report with an "
      "`environment.sdf` object with `annotated: true` (a null `sdf` renders `not_post_layout`). "
      "`timed-declared.report.json` is such a report: "
      f"annotated={item7['report_has_annotated_sdf_object']}, partial={item7['annotation_partial']}.")
    a("- Eligibility caveats that travel with any citation: the report is `partial` (no TIMINGCHECK, "
      "derived SDF with 39 zero-delay entries removed); one SDF corner only (tt_025C_1v80); the SDF "
      "carries no wire delay; DR-0004 (digital section) is "
      f"`status: {dr_status}`, so the verdict is against a Proposed specification and provisional. "
      "See `signoff/README.md` for the resulting citation decision.")
    a("")
    a("## What this record does and does not establish")
    a("")
    for line in COVERAGE:
        a(f"- {line}")
    body = san("\n".join(L))
    print(body)
    print("\nverdict:", verdict, file=sys.stderr)
    for p_ in problems:
        print("problem:", p_, file=sys.stderr)
    if not args.emit_record:
        return 0 if all_ok else 1
    if not all_ok:
        print("refusing to mint a record: at least one check was not clean",
              file=sys.stderr)
        return 1

    # -- stage + mint ----------------------------------------------------------
    stage = work / "stage"
    stage.mkdir()
    arts: list[Path] = []

    def stage_text(name: str, text: str) -> None:
        p = stage / name
        p.write_text(san(text))
        arts.append(p)

    def stage_run(x: dict) -> None:
        d, lab = x["run"]["dir"], x["label"]
        stage_text(f"{lab}.request.json", (d / "request.json").read_text())
        stage_text(f"{lab}.report.json", (d / "report.json").read_text())
        xml = d / ".klt" / "functional-verification" / "results_icarus.xml"
        if xml.exists():
            stage_text(f"{lab}.results.xml", xml.read_text())
        if not (x["run"]["report"] or None) and x["run"]["stderr"]:
            stage_text(f"{lab}.stderr.json", x["run"]["stderr"] + "\n")
        if x["probe_path"].exists():
            stage_text(f"{lab}.timing-probe.json", x["probe_path"].read_text())
        if (x["traces"] / "observations.txt").exists():
            for nm in ("stimulus", "observations", "model-observations"):
                shutil.copy2(x["traces"] / f"{nm}.txt", stage / f"{lab}.{nm}.txt")
                arts.append(stage / f"{lab}.{nm}.txt")

    for x in (declared, fast, removed, mis, shift, fail, f5, f5n):
        stage_run(x)
    sdf_gz = stage / "trng_digital.baseline.sdf.gz"
    sdf_gz.write_bytes(gz_bytes(sdf_base))
    arts.append(sdf_gz)
    for k in ("mistargeted", "delay-shift", "delay-fail"):
        d = unified(sdf_base, sdf_variants[k], f"trng_digital.{k}.sdf")
        stage_text(f"sdf-{k}.diff.txt", d if d else "(no difference)\n")
    stage_text("sdf-baseline-dropped-entries.diff.txt",
               unified(sdf_src, sdf_base, "trng_digital.baseline.sdf"))
    stage_text("sdf-census.json", json.dumps(census, indent=2) + "\n")
    stage_text("input-hashes.json", json.dumps(input_hashes, indent=2) + "\n")

    summary = {
        "verdict": verdict,
        "native_report": "klt functional-verification --format json; one report.json per run, preserved (paths sanitised)",
        "coverage_class": "SDF-annotated (partial: no TIMINGCHECK), single corner tt_025C_1v80, routed netlist; provisional",
        "timed_runs": {x["label"]: {**x["summary"], "clock_period_ns": x["clk_ns"],
                                    "trace_lines": x["lens"], "sdf": x["sdf"],
                                    "probe": x["probe_stat"]}
                       for x in (declared, fast)},
        "controls": {k: {kk: v for kk, v in c.items() if kk != "run"}
                     for k, c in controls.items()},
        "sdf_census": census,
        "sdf_derivation": {"dropped_zero_delay_port_source_interconnects": len(dropped)},
        "item7_review": item7,
        "input_hashes": input_hashes,
        "pins": {**PINS, "klt_version_reported": klt_version,
                 "pdk": {"variant": pdk_info.get("variant"), "version": pdk_info.get("version")}},
        "program": {"seed": args.seed, "cycles": n_cycles,
                    "phases": [{"name": n_, "start": s_, "end": e_} for n_, s_, e_ in phases]},
        "reproduction": repro,
    }
    summary = json.loads(san(json.dumps(summary)))
    rid = mint_behavioral_record(
        repo_root=REPO_ROOT, slug=SLUG,
        claim=("The directed bit-exact trng_digital suite ({} cycles, {} phases) passes through the pinned "
               "native `klt functional-verification` interface on the routed sky130_fd_sc_hd netlist with the "
               "post-route SDF back-annotated (Icarus 13.0, single corner tt_025C_1v80, 20000 ns and 8 ns "
               "periods; annotation partial: no TIMINGCHECK), with a mistargeted SDF, an unannotated run, an "
               "exact +{} ps instance-level delay shift, a +{} ns delay shift and a 5 ns clock all behaving as "
               "controls. Not a PVT sweep; simulation-derived and provisional; DR-0004 remains Proposed."
               ).format(n_cycles, n_phases, SHIFT_PS, SHIFT_FAIL_NS),
        body_md=body, summary=summary,
        level="gate (post-route as-built netlist, SDF-annotated, single corner)",
        seeds={"cosim_stimulus_seed": args.seed, "cocotb_random_seed": 1},
        tools={"klt": klt_version, "cocotb": PINS["cocotb"], "iverilog": iverilog_v},
        artifacts=arts)
    print(f"\nrecord id: {rid}", file=sys.stderr)
    return 0


COVERAGE = [
    "Established: with the post-route SDF back-annotated through the native tool, the routed netlist "
    "reproduces the independent model on all six outputs every cycle of the directed program (startup/"
    "reset, health-test trip and recovery, bus read/write, raw/stream pop arbitration and out_ready "
    "backpressure, mode flush, soft reset) at the declared 20000 ns period and at an 8 ns stress period.",
    "Annotation reach is shown three ways beyond the tool's own diagnostic gate: an independent census of "
    "SDF vs netlist instances; the output-latency probe (registered outputs bus_rdata, out_data, "
    "startup_done show SDF-shaped non-zero ps latencies; the unannotated run shows 0); and an exact "
    "+137 ps shift on one named flop's CLK->Q arc that moves exactly that output's latency by 137 ps while "
    "leaving the other probed outputs untouched. The latency probe covers registered outputs only: with "
    "SDF module paths active, cocotb value-change callbacks do not fire on the combinational outputs "
    "(out_valid, alarm, gated); those are covered by the oracle comparison, the 5 ns clock control and "
    "the delay-fail control, not by the probe.",
    "**Not a PVT sweep.** One SDF, one corner (the P&R request's tt_025C_1v80), typ selector; nothing here "
    "says anything about ss/ff, voltage or temperature. The 16-corner STA remains the multi-corner timing "
    "evidence (`layout/trng_digital/sta.json`); STA is not replaced by this and this is not a replacement "
    "for it.",
    "**Setup/hold are not simulated.** Icarus 13.0 does not implement SDF TIMINGCHECK (all sections "
    "dropped; reported by the tool as `partial: true`). Metastability/violations of the characterised "
    "limits are therefore invisible here; only the delay arcs (IOPATH) are exercised. The 8 ns pass and "
    "5 ns fail points are functional stress points under half-period launch/sample, not an fmax.",
    "The SDF carries zero INTERCONNECT (wire) delay at the committed corner: only cell arcs are timed. "
    "39 zero-delay bit-selected-input-source INTERCONNECT entries were removed (Icarus limitation, "
    "disclosed above) and the tool drops 33 more zero-delay alias-port entries itself.",
    "Same directed, non-exhaustive program as #222; the declared 20000 ns period leaves ~10 us of margin "
    "against ~2 ns of annotated path delay, so the declared run proves annotation and function at the "
    "constrained clock, while the 8 ns / 5 ns pair brackets where the annotated delays start to matter.",
    "Functional / unit-delay records (#222) are untouched and remain the functional baseline.",
    "Simulation-derived; provisional until silicon. DR-0004 (digital section) is still Proposed, so no "
    "ratification-dependent claim (item 5) is made. No entropy claim.",
]

if __name__ == "__main__":
    raise SystemExit(main())
