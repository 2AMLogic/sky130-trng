#!/usr/bin/env python3
"""Run the bit-exact directed `trng_digital` suite through the pinned
`klt functional-verification` interface (klayout-tools 0.7.0) and preserve
the tool's NATIVE report -- issue #222.

What runs (every run is `klt functional-verification <request> --format json`,
Icarus engine, cocotb 2.0.1; the testbench is
`digital/tb/cocotb/test_trng_digital_fv.py`):

1. `rtl`            -- digital/rtl/trng_digital.v, the same directed program and
                       the same independent oracle (digital/model, via
                       rtl-cosim.py) as sim/digital-rtl-equivalence.
2. `routed-gate`    -- layout/trng_digital/trng_digital.routed.v (the netlist
                       the committed STA/SPEF belong to) against the sky130_fd_sc_hd
                       Verilog cell models with FUNCTIONAL + UNIT_DELAY #1.
                       FUNCTIONAL / UNIT-DELAY ONLY: no `options.sdf`, so this is
                       NOT the SDF-timed item-7 evidence (`environment.sdf` is
                       null in the native report).
3. Negative controls on the new reporting path -- each MUST exit 3 /
   `status: fail`, with the exact-length test failing where observations are
   missing:
     * every xor2_1 of the routed netlist rewritten to and2_1 (the existing
       #166 mutation);
     * truncated observation record (stops after K cycles);
     * one dropped observation (a hole in the record);
     * no observations at all.
4. `klt functional-verification --mutations`: single-point xor->and mutants of
   the RTL (the two `^` operators that matter) and of each of the routed
   netlist's xor2_1 instances. The native mutation score is recorded as-is;
   survivors are disclosed, not hidden.

Fail-closed: a pin mismatch (klt, cocotb, Icarus), a missing tool, a
non-passing baseline, a control that is not detected, or a result whose
test/trace counts disagree with the program, refuses to mint a record.

    # cold start (nothing host-wide is touched):
    uv venv .venv && uv pip install --python .venv/bin/python \
        "klayout-tools==0.7.0" "cocotb==2.0.1"
    python3 sim/digital-functional-verification/harness/fv-cosim.py \
        --klt .venv/bin/klt --emit-record
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HOME = Path.home().resolve()
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402

PINS = {"klt": "klt 0.7.0", "cocotb": "2.0.1", "icarus": "13.0",
        "engine": "icarus"}
DEFAULT_SEED = 20260905

TB_DIR = REPO_ROOT / "digital" / "tb" / "cocotb"
TB_MODULE = "test_trng_digital_fv"
DEFINES_V = TB_DIR / "sky130_fd_sc_hd_sim_defines.v"
RTL = REPO_ROOT / "digital" / "rtl" / "trng_digital.v"
ROUTED = REPO_ROOT / "layout" / "trng_digital" / "trng_digital.routed.v"
STA_JSON = REPO_ROOT / "layout" / "trng_digital" / "sta.json"
PNR_RECORD_GLOB = "sim/digital-pnr/records/*.json"
DR0004 = (REPO_ROOT / "spec" / "decision-records"
          / "DR-0004-sky130-digital-section-architecture.md")
MODEL_FILES = sorted((REPO_ROOT / "digital" / "model").glob("*.py"))
RTL_COSIM = REPO_ROOT / "sim" / "digital-rtl-equivalence" / "harness" / "rtl-cosim.py"

XOR = "sky130_fd_sc_hd__xor2_1"
AND = "sky130_fd_sc_hd__and2_1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


class Sanitizer:
    """In-repo absolute paths -> repo-relative; the PDK libs.ref tree ->
    ``$PDK_LIBS_REF``; any other host-local path -> ``<host>``. Records name
    external inputs by hash and version, never by location."""

    def __init__(self, libs_ref: Path, work: Path):
        self.pairs = [(str(libs_ref.resolve()), "$PDK_LIBS_REF"),
                      (str(libs_ref), "$PDK_LIBS_REF"),
                      (str(work.resolve()), "<work>"),
                      (str(REPO_ROOT), "."),
                      (str(HOME), "<home>")]

    def __call__(self, text: str) -> str:
        for a, b in self.pairs:
            text = text.replace(a, b)
        return text


def run_fv(klt: str, request: dict, rdir: Path, *, env_extra=None,
           mutations: dict | None = None) -> dict:
    """Write request (+ proposals) into rdir, run the native verb, return
    {request_path, rc, report, stdout, stderr}. Never interprets the exit code
    as the verdict: the caller reads `report["status"]`."""
    rdir.mkdir(parents=True, exist_ok=True)
    req_path = rdir / "request.json"
    req_path.write_text(json.dumps(request, indent=2) + "\n")
    cmd = [klt, "functional-verification", str(req_path), "--format", "json"]
    if mutations is not None:
        prop = rdir / "proposals.json"
        prop.write_text(json.dumps(mutations, indent=2) + "\n")
        cmd += ["--mutations", str(prop)]
    # an ambient TRNG_FV_FAULT must never leak into a run that did not ask for it
    env = {k: v for k, v in os.environ.items() if k != "TRNG_FV_FAULT"}
    env.update(env_extra or {})
    p = subprocess.run(cmd, cwd=rdir, env=env, capture_output=True, text=True)
    report = None
    try:
        report = json.loads(p.stdout)
    except json.JSONDecodeError:
        pass
    (rdir / "report.json").write_text(p.stdout if report is None
                                      else json.dumps(report, indent=2) + "\n")
    return {"request_path": req_path, "rc": p.returncode, "report": report,
            "stderr": p.stderr.strip(), "cmd": cmd, "dir": rdir}


def request_for(sources: list[Path], seed_dir: Path) -> dict:
    return {
        "schema": "klt.functional_verification.request/1",
        "engine": PINS["engine"],
        "sources": [str(s) for s in sources],
        "hdl_toplevel": "trng_digital",
        "testbench": {"module": TB_MODULE, "search_path": str(TB_DIR)},
        "options": {"random_seed": 1},
    }


def summarize(run: dict) -> dict:
    r = run["report"] or {}
    return {
        "rc": run["rc"],
        "status": r.get("status"),
        "test_count": r.get("test_count"),
        "passed": r.get("passed_count"),
        "failed": r.get("failed_count"),
        "skipped": r.get("skipped_count"),
        "failed_tests": [t["name"] for t in r.get("tests", [])
                         if t["status"] == "failed"],
        "sdf": (r.get("environment") or {}).get("sdf"),
        "stderr": run["stderr"][-400:] if run["rc"] not in (0, 3) else "",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--klt", default=os.environ.get("KLT", "klt"))
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)

    for tool in (args.klt, "iverilog"):
        if shutil.which(tool) is None:
            print(f"error: {tool!r} not found -- a missing tool is not "
                  "evidence, so nothing is minted", file=sys.stderr)
            return 2

    # -- pins --------------------------------------------------------------
    ver = subprocess.run([args.klt, "--version"], capture_output=True, text=True)
    klt_version = ver.stdout.strip() or ver.stderr.strip()
    if klt_version != PINS["klt"]:
        print(f"error: klt {klt_version!r} != pinned {PINS['klt']!r}. Use a "
              "venv with klayout-tools==0.7.0 (see this file's docstring); "
              "never change the host tool.", file=sys.stderr)
        return 2

    env = {**os.environ, "PDK": args.pdk}
    pk = subprocess.run([args.klt, "pdk", "find", "--pdk", args.pdk,
                         "--format", "json"], capture_output=True, text=True,
                        env=env)
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

    work = Path(tempfile.mkdtemp(prefix="digital-fv-"))
    san = Sanitizer(libs_ref, work)

    # -- program shape (the oracle's own account of what must run) ---------
    import importlib.util
    spec = importlib.util.spec_from_file_location("rtl_cosim", RTL_COSIM)
    rtl_cosim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rtl_cosim)
    cycles, phases = rtl_cosim.build_program(args.seed)
    n_cycles, n_phases = len(cycles), len(phases)
    expected_tests = n_phases + 2        # drive + one per phase + length

    base_env = {"TRNG_FV_SEED": str(args.seed)}
    problems: list[str] = []

    def baseline(label: str, sources: list[Path]) -> dict:
        obs_dir = work / label / "traces"
        run = run_fv(args.klt, request_for(sources, work / label),
                     work / label,
                     env_extra={**base_env, "TRNG_FV_OBS_OUT": str(obs_dir)})
        s = summarize(run)
        r = run["report"] or {}
        envr = r.get("environment") or {}
        if r:
            if envr.get("cocotb_version") != PINS["cocotb"]:
                problems.append(f"{label}: cocotb {envr.get('cocotb_version')!r} != pinned {PINS['cocotb']!r}")
            if envr.get("engine_version") != PINS["icarus"]:
                problems.append(f"{label}: icarus {envr.get('engine_version')!r} != pinned {PINS['icarus']!r}")
        ok = (run["rc"] == 0 and s["status"] == "pass"
              and s["test_count"] == expected_tests
              and s["passed"] == expected_tests and s["failed"] == 0
              and s["skipped"] == 0 and envr.get("sdf") is None)
        # exact trace lengths, straight from the preserved traces
        lens = {}
        for name in ("stimulus", "observations", "model-observations"):
            f = obs_dir / f"{name}.txt"
            lens[name] = len(f.read_text().splitlines()) if f.exists() else None
        lens_ok = (lens["stimulus"] == lens["observations"]
                   == lens["model-observations"] == n_cycles)
        ident = (obs_dir / "observations.txt").exists() and \
            (obs_dir / "observations.txt").read_bytes() == \
            (obs_dir / "model-observations.txt").read_bytes()
        if not (ok and lens_ok and ident):
            problems.append(f"{label}: baseline not clean "
                            f"(ok={ok}, lens={lens}, identical={ident}, {s})")
        return {"run": run, "summary": s, "lens": lens, "ok": ok and lens_ok and ident,
                "traces": obs_dir}

    rtl = baseline("rtl", [RTL])
    gate_sources = [DEFINES_V, prim, cells, ROUTED]
    gate = baseline("routed-gate", gate_sources)

    # -- negative controls on the routed-gate path -------------------------
    controls: dict[str, dict] = {}

    def control(label: str, mutation: str, sources: list[Path],
                fault: str = "", must_fail: tuple[str, ...] = ()) -> None:
        e = {**base_env}
        if fault:
            e["TRNG_FV_FAULT"] = fault
        run = run_fv(args.klt, request_for(sources, work / label),
                     work / label, env_extra=e)
        s = summarize(run)
        detected = (run["rc"] == 3 and s["status"] == "fail"
                    and s["failed"] > 0
                    and all(any(n.startswith(m) for n in s["failed_tests"])
                            for m in must_fail))
        controls[label] = {"mutation": mutation, "detected": detected,
                           "run": run, **{k: s[k] for k in
                           ("rc", "status", "test_count", "passed", "failed",
                            "failed_tests")}}
        if not detected:
            problems.append(f"control {label}: NOT detected ({s})")

    routed_text = ROUTED.read_text()
    n_xor = routed_text.count(XOR + " ")
    mut_netlist = work / "mutants" / "trng_digital.routed.xor2_to_and2.v"
    mut_netlist.parent.mkdir(parents=True)
    mut_netlist.write_text(routed_text.replace(XOR + " ", AND + " "))
    control("xor-to-and-all", f"{n_xor} xor2_1 instances rewritten to and2_1 in the routed netlist",
            [DEFINES_V, prim, cells, mut_netlist],
            must_fail=("test_zz_trace_length_exact",))
    k = n_cycles * 9 // 10
    control("truncated-observations",
            f"observation record stops after {k} of {n_cycles} cycles (TRNG_FV_FAULT=truncate:{k})",
            gate_sources, fault=f"truncate:{k}",
            must_fail=("test_00_drive_program", "test_zz_trace_length_exact"))
    d = n_cycles // 3
    control("dropped-observation",
            f"cycle {d}'s observation omitted from the record (TRNG_FV_FAULT=drop:{d})",
            gate_sources, fault=f"drop:{d}",
            must_fail=("test_00_drive_program", "test_zz_trace_length_exact"))
    control("no-observations",
            "no observation recorded at all (TRNG_FV_FAULT=truncate:0)",
            gate_sources, fault="truncate:0",
            must_fail=("test_00_drive_program", "test_zz_trace_length_exact"))

    # -- native mutation testing -------------------------------------------
    def proposals(path: Path, scope_key: str, items: list[tuple[str, int, str, str, str]]):
        return {"schema": "klt.functional_verification.mutation_proposals/1",
                "scope": [scope_key],
                "proposals": [{"index": i + 1, "category": cat, "file": scope_key,
                               "line": ln, "original_code": o, "mutated_code": m,
                               "detectability_argument": arg}
                              for i, (cat, ln, o, m, arg) in enumerate(items)]}

    rtl_lines = RTL.read_text().splitlines()
    rtl_items = []
    for needle, new, arg in (
            ("(s[31] ^ b)", "(s[31] & b)",
             "CRC-32 feedback XOR -> AND: every conditioned word changes"),
            ("(new_ctrl[1] ^ ctrl[1])", "(new_ctrl[1] & ctrl[1])",
             "OUT_MODE change detect XOR -> AND: the mode-switch flush never fires")):
        hits = [i + 1 for i, l in enumerate(rtl_lines) if needle in l]
        if len(hits) != 1:
            problems.append(f"mutation anchor {needle!r} found on {hits} RTL lines")
            continue
        rtl_items.append(("operator_change", hits[0], needle, new, arg))
    rtl_req = request_for([RTL], work / "mut-rtl")
    mut_runs = {}
    mut_runs["rtl"] = run_fv(
        args.klt, rtl_req, work / "mut-rtl",
        env_extra=base_env,
        mutations=proposals(RTL, str(RTL), rtl_items))

    gl = routed_text.splitlines()
    gate_items = []
    for i, l in enumerate(gl):
        m = re.match(rf"\s*{XOR} (\S+) \(", l)
        if m:
            gate_items.append(("operator_change", i + 1, f"{XOR} {m.group(1)}",
                               f"{AND} {m.group(1)}",
                               "xor2 -> and2 on one routed instance (same pin names)"))
    mut_runs["routed-gate"] = run_fv(
        args.klt, request_for(gate_sources, work / "mut-routed"),
        work / "mut-routed", env_extra=base_env,
        mutations=proposals(ROUTED, str(ROUTED), gate_items))
    mutation = {}
    for k_, run in mut_runs.items():
        mt = (run["report"] or {}).get("mutation_testing")
        if run["rc"] not in (0, 3) or mt is None:
            problems.append(f"mutation run {k_}: no mutation_testing block (rc={run['rc']}) {run['stderr'][-300:]}")
            continue
        mutation[k_] = {kk: mt[kk] for kk in
                        ("proposal_count", "valid_count", "rejected_count",
                         "killed_count", "survived_count", "mutation_score")}
        mutation[k_]["survivors"] = [f"{r['file'].split('/')[-1]}:{r['line']}"
                                     for r in mt["results"] if r["status"] == "survived"]
        if mt["rejected_count"] or mt["killed_count"] == 0:
            problems.append(f"mutation run {k_}: rejected={mt['rejected_count']} killed={mt['killed_count']}")

    # -- item-5 condition review (read from the committed artifacts) -------
    sta = json.loads(STA_JSON.read_text())
    sta_ok = (sta.get("status") is not None and len(sta["corners"]) > 0 and all(
        c["timing_status"] == "constrained" and c["setup_violation_count"] == 0
        and c["hold_violation_count"] == 0 and c["worst_slack_ns"] >= 0
        and c["worst_hold_slack_ns"] >= 0 for c in sta["corners"]))
    dr_text = DR0004.read_text()
    m = re.search(r"^status:\s*(\S+)", dr_text, re.M)
    dr_status = m.group(1) if m else "unknown"
    ratified = dr_status.lower() in ("ratified", "accepted")
    pnr_rec = None
    for pth in sorted(REPO_ROOT.glob(PNR_RECORD_GLOB)):
        pnr_rec = json.loads(pth.read_text())
    routed_hash = sha256(ROUTED)
    pnr_bound = bool(pnr_rec) and \
        pnr_rec.get("geometry_sha256", {}).get("trng_digital.routed.v") == routed_hash
    if not pnr_bound:
        problems.append("routed netlist sha256 != latest digital-pnr record's geometry hash")

    item5 = {
        "sta_half": {"met": sta_ok, "corners": len(sta["corners"]),
                     "evidence": "layout/trng_digital/sta.json"},
        "functional_half": {"met": gate["ok"] and rtl["ok"],
                            "evidence": "this record (native klt functional-verification reports)"},
        "spec_ratification": {"met": ratified, "dr_0004_status": dr_status},
        "compound_citation_allowed": sta_ok and gate["ok"] and rtl["ok"] and ratified,
    }

    # -- hashes / pins ------------------------------------------------------
    input_hashes = {rel(p): sha256(p) for p in
                    [RTL, ROUTED, STA_JSON, DEFINES_V, TB_DIR / f"{TB_MODULE}.py",
                     RTL_COSIM, *MODEL_FILES]}
    input_hashes["$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/primitives.v"] = sha256(prim)
    input_hashes["$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"] = sha256(cells)
    input_hashes["stimulus.txt (generated, seed %d)" % args.seed] = \
        sha256(gate["traces"] / "stimulus.txt") if (gate["traces"] / "stimulus.txt").exists() else None
    input_hashes["model-observations.txt (oracle trace)"] = \
        sha256(gate["traces"] / "model-observations.txt") if (gate["traces"] / "model-observations.txt").exists() else None

    iverilog_v = rtl_cosim.iverilog_version()
    repro = ("uv venv .venv && uv pip install --python .venv/bin/python "
             "\"klayout-tools==0.7.0\" \"cocotb==2.0.1\" && "
             "python3 sim/digital-functional-verification/harness/fv-cosim.py "
             "--klt .venv/bin/klt --emit-record")
    native_cmd = (f"TRNG_FV_SEED={args.seed} .venv/bin/klt functional-verification "
                  "<run>/request.json --format json   "
                  "# (+ --mutations <run>/proposals.json for the mutation runs; "
                  "TRNG_FV_FAULT=<mode> for the observation-record controls)")

    all_ok = not problems
    verdict = {"rtl_baseline": rtl["ok"], "routed_gate_baseline": gate["ok"],
               "negative_controls_detected": all(c["detected"] for c in controls.values()),
               "item5_compound_citation_allowed": item5["compound_citation_allowed"]}

    # -- report -------------------------------------------------------------
    L = []
    a = L.append
    a("## Configuration")
    a("")
    a(f"- native interface: `klt functional-verification` ({klt_version}), engine "
      f"`icarus` {PINS['icarus']}, cocotb {PINS['cocotb']}; every number below is read "
      "from the tool's own JSON report (`report.json` per run, preserved), whose "
      "verdict is derived by the tool from cocotb's `results.xml` (preserved).")
    a(f"- testbench: `digital/tb/cocotb/{TB_MODULE}.py` -- the SAME directed program "
      f"(`rtl-cosim.py::build_program`, seed {args.seed}, {n_cycles} cycles, {n_phases} phases) "
      "and the SAME independent oracle (`digital/model`, via `rtl-cosim.py::model_trace`) as "
      "`sim/digital-rtl-equivalence`; it holds no golden vectors of its own.")
    a(f"- tests per run: 1 drive + {n_phases} phase tests + 1 exact-length test = {expected_tests}.")
    a(f"- simulator transcript tool: `{iverilog_v}`")
    a(f"- reproduction: `{repro}`")
    a(f"- native command shape: `{native_cmd}`")
    a("")
    a("## Baselines (must pass; trace lengths and bytes checked independently of the tool)")
    a("")
    a("| Run | DUT | status | tests | stimulus / observed / model lines | observed == model (bytes) |")
    a("|---|---|---|---|---|---|")
    for lab, b, dut in (("rtl", rtl, "digital/rtl/trng_digital.v"),
                        ("routed-gate", gate, "layout/trng_digital/trng_digital.routed.v + sky130_fd_sc_hd FUNCTIONAL/UNIT_DELAY #1")):
        s = b["summary"]
        ln = b["lens"]
        a(f"| {lab} | `{dut}` | **{s['status']}** | {s['passed']}/{s['test_count']} passed | "
          f"{ln['stimulus']} / {ln['observations']} / {ln['model-observations']} (program {n_cycles}) | "
          f"{b['ok']} |")
    a("")
    a("Per-test results (routed-gate):")
    a("")
    for t in (gate["run"]["report"] or {}).get("tests", []):
        a(f"- `{t['name']}`: {t['status']}")
    a("")
    a("## Negative controls (the new reporting path must reject each)")
    a("")
    for lab, c in controls.items():
        a(f"- `{lab}`: {c['mutation']} -> exit {c['rc']}, status `{c['status']}`, "
          f"{c['failed']}/{c['test_count']} tests failed -- detected = **{c['detected']}**")
    a("")
    a("## Native mutation testing (`--mutations`, single-point xor->and mutants)")
    a("")
    for k_, mm in mutation.items():
        a(f"- `{k_}`: {mm['killed_count']} killed / {mm['valid_count']} valid "
          f"({mm['rejected_count']} rejected), mutation score {mm['mutation_score']}; "
          f"survivors: {mm['survivors'] or 'none'}")
    a("")
    a("## T1 item 5 (digital) condition review")
    a("")
    a(f"- multi-corner STA half: `layout/trng_digital/sta.json`, {item5['sta_half']['corners']} corners, "
      f"all constrained with non-negative setup/hold: **{sta_ok}**.")
    a(f"- bit-exact functional half: native reports above, RTL and routed netlist: "
      f"**{item5['functional_half']['met']}**.")
    a(f"- specification ratification: DR-0004 `status: {dr_status}` -> **{'met' if ratified else 'UNMET'}**. "
      "The digital section is still **Proposed**; verdicts against a Proposed spec are provisional by "
      "construction (the item's own note), so the compound item-5 citation is "
      + ("allowed." if item5["compound_citation_allowed"] else
         "**NOT made** and `signoff/block-manifest.json` keeps `5.digital` uncited/unmet.")
      )
    a(f"- routed netlist bound to the committed P&R record: sha256 `{routed_hash}` equals the "
      f"`geometry_sha256` of `{pnr_rec and pnr_rec.get('record_id')}`: **{pnr_bound}**.")
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
        print("refusing to mint a record: at least one check was not clean", file=sys.stderr)
        return 1

    # -- stage + mint -------------------------------------------------------
    stage = work / "stage"
    stage.mkdir()
    arts: list[Path] = []

    def stage_text(name: str, text: str) -> None:
        p = stage / name
        p.write_text(san(text))
        arts.append(p)

    def stage_run(label: str, run: dict, xml: bool = True) -> None:
        d = run["dir"]
        stage_text(f"{label}.request.json", (d / "request.json").read_text())
        stage_text(f"{label}.report.json", (d / "report.json").read_text())
        if (d / "proposals.json").exists():
            stage_text(f"{label}.proposals.json", (d / "proposals.json").read_text())
        x = d / ".klt" / "functional-verification" / "results_icarus.xml"
        if xml and x.exists():
            stage_text(f"{label}.results.xml", x.read_text())

    stage_run("rtl", rtl["run"])
    stage_run("routed-gate", gate["run"])
    for lab, c in controls.items():
        stage_run(f"control-{lab}", c["run"])
    for lab, run in mut_runs.items():
        stage_run(f"mutation-{lab}", run, xml=True)
    for lab, b in (("rtl", rtl), ("routed-gate", gate)):
        for nm in ("stimulus", "observations", "model-observations"):
            shutil.copy2(b["traces"] / f"{nm}.txt", stage / f"{lab}.{nm}.txt")
            arts.append(stage / f"{lab}.{nm}.txt")
    stage_text("input-hashes.json", json.dumps(input_hashes, indent=2) + "\n")

    summary = {
        "verdict": verdict,
        "native_report": "klt functional-verification --format json; one report.json per run, preserved verbatim (paths sanitised)",
        "coverage_class": "functional / unit-delay (FUNCTIONAL + UNIT_DELAY #1); NOT SDF-timed; NOT item-7 evidence",
        "baselines": {k_: {**b["summary"], "trace_lines": b["lens"]}
                      for k_, b in (("rtl", rtl), ("routed-gate", gate))},
        "negative_controls": {k_: {kk: v for kk, v in c.items() if kk != "run"}
                              for k_, c in controls.items()},
        "mutation_testing": mutation,
        "item5_review": item5,
        "input_hashes": input_hashes,
        "pins": {**PINS, "klt_version_reported": klt_version,
                 "pdk": {"variant": pdk_info.get("variant"), "version": pdk_info.get("version")}},
        "program": {"seed": args.seed, "cycles": n_cycles,
                    "phases": [{"name": n_, "start": s_, "end": e_} for n_, s_, e_ in phases]},
        "reproduction": repro,
    }
    rid = mint_behavioral_record(
        repo_root=REPO_ROOT, slug="digital-functional-verification",
        claim=("The directed bit-exact trng_digital suite ({} cycles, {} phases) passes through the "
               "pinned native `klt functional-verification` interface (klayout-tools 0.7.0, cocotb 2.0.1, "
               "Icarus 13.0) on both the RTL and the routed sky130_fd_sc_hd netlist at functional/unit-delay "
               "level against the independent behavioural model; an xor->and routed netlist, truncated, "
               "dropped and missing observations all fail the same path. Not SDF-timed (not item 7); the "
               "digital specification is still Proposed (item 5 not claimed).").format(n_cycles, n_phases),
        body_md=body, summary=summary,
        level="gate (post-route as-built netlist, functional/unit-delay -- NOT SDF-timed)",
        seeds={"cosim_stimulus_seed": args.seed, "cocotb_random_seed": 1},
        tools={"klt": klt_version, "cocotb": PINS["cocotb"], "iverilog": iverilog_v},
        artifacts=arts)
    print(f"\nrecord id: {rid}", file=sys.stderr)
    return 0


COVERAGE = [
    "Established: the committed directed program (the per-phase tests listed above), driven by a cocotb "
    "testbench, produces a trace identical to the independent normative model "
    "(`digital/model/digital_top.py`) on all six observed outputs every cycle, for the RTL and for the "
    "routed as-built netlist, with exact stimulus/observation/model trace-length equality; the "
    "tool-native per-test report, request, `results.xml`, traces, input hashes and tool pins are "
    "preserved with this record.",
    "**Functional / unit-delay only.** The routed run uses `FUNCTIONAL` zero-delay cell models plus "
    "`UNIT_DELAY #1` on sequential UDPs (a race-avoidance device, not a timing model); `options.sdf` "
    "is not set and `environment.sdf` is null in every native report. This is NOT the SDF-annotated "
    "run T1 item 7 requires and must not be counted as post-layout timed evidence.",
    "The oracle is the same behavioural model the RTL-equivalence and gate-cosim records use. The "
    "directed program is not exhaustive (no formal equivalence, no constrained-random campaign); the "
    "mutation score above is the honest measure of what it notices, and any survivor is a disclosed "
    "gap in the program, not a pass.",
    "The negative controls prove the new reporting path fails on a wrong netlist and on missing or "
    "truncated observations. The observation-record faults are injected in the testbench's record "
    "(`TRNG_FV_FAULT`), a test-of-the-test hook that is unset in every baseline.",
    "The pinned tool derives pass/fail from cocotb's `results.xml`; this harness additionally checks "
    "trace line counts and byte-equality of the preserved traces itself.",
    "**Item 5 (digital) is NOT claimed.** The STA half (`layout/trng_digital/sta.json`) and the "
    "functional half now both exist as evidence, but the item's own note requires a ratified "
    "specification and the digital section (DR-0004) is still `Proposed`; the manifest citation stays "
    "withheld and the item stays unmet.",
    "Simulation-derived; provisional until silicon. No entropy claim is made here (the entropy "
    "source is not part of this digital-only suite).",
]

if __name__ == "__main__":
    raise SystemExit(main())
