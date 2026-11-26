#!/usr/bin/env python3
"""stdlib-only unit test of the issue #604 active-power-budget reduction.

sim/post-layout-sampler-core/analysis/reduce-active-power-budget.py turns
two committed control records plus two Ts = 20 us corner reports into the
budget tables of analysis/active-power-budget.md. The arithmetic that
would silently lie if it rotted:

* per-leg totals are the SIGNED sums of the measured rail currents (the
  sources read negative when delivering) times 1.98 V, in uW;
* headroom is target-minus-total, so a failing corner reports negative;
* the 20 us verdict grades the unrounded total against the strict < 500 uW bound;
* runner-reported initialization must agree with the request and the other run;
* the W_RST anchor compares the 20 us run's reset-held window against the
  committed control's own same-window numbers (stimulus-identical), and
  its delta feeds nothing else; only matched fleet pairs enter rate deltas;
* a missing measurement, a wrong report status, or a record with no ok ff
  corner refuses to emit anything (EvidenceError), never a partial table;
* an authored analysis/disposition.md is appended verbatim when present.

No klt, no PDK, no ngspice: synthetic records exercise every path.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REDUCER_PATH = (HERE.parent / "post-layout-sampler-core" / "analysis" /
                "reduce-active-power-budget.py")

spec = importlib.util.spec_from_file_location("reduce_active_power_budget",
                                              REDUCER_PATH)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'ok' if cond else 'FAIL'}: {msg}")
    if not cond:
        FAILURES.append(msg)


def synth_control(tmp: Path, t: float, rings_a: float, block_a: float) -> Path:
    m = {"i_rings_act": rings_a, "i_block_act": block_a,
         "i_total_act": rings_a + block_a,
         "i_rings_rst": 0.6 * rings_a, "i_block_rst": 0.9 * block_a,
         "p_i_rings_act": 0.85 * rings_a, "p_i_block_act": 1.25 * block_a,
         "p_i_total_act": 0.85 * rings_a + 1.25 * block_a,
         "p_i_rings_rst": 0.6 * 0.85 * rings_a,
         "p_i_block_rst": 0.9 * 1.25 * block_a}
    rec = {"record_id": f"synthetic-{'m40' if t < 0 else 'hot'}",
           "corners": [{"corner": "ff", "ok": True, "measurements": m}],
           "testbench": "synthetic",
           "netlists": {"RO_RING5": {"path": "design/sampler_core.spice", "sha256": "a" * 64},
                        "PEX_LIB": {"path": "layout/pex-sampler-core/"
                                            "sampler_core_pex.spice", "sha256": "b" * 64}},
           "tools": {"ngspice": "synthetic"}}
    p = tmp / f"ctrl-{int(t)}.json"
    p.write_text(json.dumps(rec))
    return p


def synth_report(tmp: Path, t: float, period: str, scale: float) -> Path:
    got = {}
    for p in ("x", "s"):
        for i in (1, 2, 3, 4):
            got[f"{p}_ir{i}_rst"] = -(1e-5) * scale
            got[f"{p}_ir{i}_act"] = -(1.1e-5) * scale
            got[f"{p}_ir{i}_lo"] = got[f"{p}_ir{i}_hi"] = got[f"{p}_ir{i}_act"]
        got[f"{p}_ib_rst"] = -(1.5e-4) * scale
        got[f"{p}_ib_act"] = -(1.4e-4) * scale
        got[f"{p}_ib_lo"] = got[f"{p}_ib_hi"] = got[f"{p}_ib_act"]
    meas = [{"name": k, "value": v, "status": "pass"} for k, v in got.items()]
    tag = "m40C" if t < 0 else "125C"
    name = f"ts{period}-{tag}-1.98V"
    source = REDUCER_PATH.parents[1] / "corners"
    dest = tmp / "corners" / name
    dest.mkdir(parents=True, exist_ok=True)
    for filename in ("request.json", "plan.json"):
        shutil.copyfile(source / name / filename, dest / filename)
    plan = json.loads((dest / "plan.json").read_text())
    # Use the fleet envelope shape for this temperature, with synthetic measurements.
    rep = json.loads((source / f"ts20u-{tag}-1.98V" / "report.json").read_text())
    rep["corners"][0]["measurements"] = meas
    rep["environment"]["netlist_sha256"] = plan["netlist_sha256"]
    rep["environment"]["remote"]["job_id"] = "synthetic-job"
    p = dest / "report.json"
    p.write_text(json.dumps(rep))
    return p


def check_refusal(message: str) -> None:
    try:
        R.main([])
    except R.EvidenceError as exc:
        check(message in str(exc), f"refused with {message}")
    else:
        check(False, f"expected refusal for {message}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        ctrl = {t: synth_control(tmp, t, 8.8e-5, 1.75e-4) for t in R.TEMPS}
        rep = {t: synth_report(tmp, t, "20u", 1.0) for t in R.TEMPS}
        matched = {t: synth_report(tmp, t, "100n", 1.1) for t in R.TEMPS}
        R.CONTROL_RECORDS = ctrl
        R.SLUG = tmp
        (tmp / "analysis").mkdir()
        out = tmp / "analysis" / "active-power-budget.md"
        rc = R.main([])
        check(rc == 0 and out.is_file(), "budget emitted")
        text = out.read_text()
        print("tables:")
        # schematic 20us total: 4*11u + 140u = 184 uA * 1.98 = 364.32 uW -> PASS
        check("| schematic | 87.1 | 277.2 | 364.3 | 135.7 |" in text,
              "schematic 20 us row: signed sums x 1.98 V, headroom positive")
        check("| schematic | 174.2 | 346.5 | 520.7 | -20.7 |" in text,
              "schematic 100 ns control row: negative headroom on a failing corner")
        # extracted leg: 4*11 + 140 = same scale -> also 364.3 in this synth
        check(text.count("| 364.3 | 135.7 |") == 2 * 2,
              "both legs x both temps share the synthetic totals")
        check("| +125 C | schematic | 400.8 | 364.3 | -36.4 | PASS |" in text,
              "comparison row: 100 ns column, delta, verdict")
        verdicts = [ln for ln in text.splitlines() if " C | " in ln and
                    ("PASS" in ln or "FAIL" in ln)]
        check(len(verdicts) == 4 and all("PASS" in v for v in verdicts),
              "four comparison verdicts, synthetic all PASS")
        check("synthetic-job" in text, "run references carried into the record")
        # anchor: ctrl rst total = 0.6*88u + 0.9*175u = 210.3 uA; ts rst = 190 uA
        # delta = (190-210.3)/210.3 = -9.65 %
        check("(-9.65 %)" in text, "W_RST anchor delta computed")
        # disposition appended verbatim
        (tmp / "analysis" / "disposition.md").write_text(
            "## 5. Proposed disposition\n\nAUTHORED TEXT\n")
        rc = R.main([])
        check("AUTHORED TEXT" in out.read_text(),
              "authored disposition appended verbatim")
        # Exercise the raw verdict through the report and rendered row, including
        # two powers which round to the same displayed value on opposite sides.
        hot_long = rep[125.0]
        original_long = hot_long.read_bytes()
        for power, verdict in ((499.0, "PASS"), (499.99, "PASS"), (500.0, "FAIL"),
                               (500.01, "FAIL"), (501.0, "FAIL")):
            report = json.loads(original_long)
            for m in report["corners"][0]["measurements"]:
                if m["name"].startswith("s_ir") and m["name"].endswith("_act"):
                    m["value"] = 0.0
                if m["name"] == "s_ib_act":
                    m["value"] = -power / (R.VDD * 1e6)
            hot_long.write_text(json.dumps(report))
            R.main([])
            row = next(line for line in out.read_text().splitlines()
                       if line.startswith("| +125 C | schematic |"))
            check(row.endswith(f"| {verdict} |"), f"strict verdict at {power} uW")
        hot_long.write_bytes(original_long)

        hot = matched[125.0]
        original_short = hot.read_bytes()
        declared = json.loads(hot.with_name("request.json").read_text())["options"]["ngspice_init"]
        digest = "sha256:" + hashlib.sha256(("\n".join(declared) + "\n").encode()).hexdigest()
        short = json.loads(original_short)
        long = json.loads(original_long)
        worker = short["environment"]["remote"]["worker_environment"]
        worker["ngspice_init"] = {"source": "request", "lines": declared, "sha256": digest}
        hot.write_text(json.dumps(short))
        R.main([])
        check("100 ns verified, 20 us requested only" in out.read_text(),
              "mixed runner coverage is visible for the pair")
        long["environment"]["ngspice_init"] = {"source": "runner", "lines": None, "sha256": digest}
        hot_long.write_text(json.dumps(long))
        R.main([])
        check("100 ns verified, 20 us verified" in out.read_text(),
              "worker lines and report digest confirm the requested settings")
        worker["ngspice_init"]["lines"] = ["set measureprec=4", "set numdgt=12"]
        hot.write_text(json.dumps(short))
        check_refusal("ngspice_init")
        worker["ngspice_init"] = {"source": "request", "lines": None, "sha256": "9" * 64}
        hot.write_text(json.dumps(short))
        check_refusal("ngspice_init")
        # Both files can match a request, yet differ in klt's optional thread pin.
        worker["threads_per_worker"] = 1
        worker["ngspice_init"] = {"source": "request", "lines": ["set num_threads=1", *declared]}
        hot.write_text(json.dumps(short))
        check_refusal("differ in effective ngspice_init")
        hot.write_bytes(original_short)
        long["environment"]["ngspice_init"]["lines"] = ["set measureprec=4"]
        hot_long.write_text(json.dumps(long))
        check_refusal("ngspice_init")
        hot_long.write_bytes(original_long)
        # refusal paths
        print("refusals:")
        plan_path = hot.with_name("plan.json")
        original_plan = plan_path.read_bytes()
        for key in ("design_lib", "pex_lib"):
            plan = json.loads(original_plan)
            plan[key]["sha256"] = "9" * 64
            plan_path.write_text(json.dumps(plan))
            check_refusal(key)
        plan_path.write_bytes(original_plan)
        report = json.loads(hot.read_text())
        report["environment"]["remote"]["runner_models_lib_sha256"] = "9" * 64
        hot.write_text(json.dumps(report))
        check_refusal("models_lib")
        hot.write_bytes(rep[125.0].read_bytes())  # a 20 us report in the 100 ns slot
        check_refusal("netlist hashes differ")
        hot.unlink()
        R.main([])
        check("| +125 C | extracted | pending | 364.3 | pending | PASS |" in out.read_text(),
              "missing short control preserves 20 us verdict without a historical fallback")
        bad = json.loads(rep[-40.0].read_text())
        bad["corners"][0]["measurements"] = bad["corners"][0]["measurements"][:-3]
        rep[-40.0].write_text(json.dumps(bad))
        check_refusal("measurement")
        synth_report(tmp, -40.0, "20u", 1.0)
        bad2 = json.loads(ctrl[125.0].read_text())
        bad2["corners"][0]["ok"] = False
        ctrl[125.0].write_text(json.dumps(bad2))
        check_refusal("no ok ff corner")
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
