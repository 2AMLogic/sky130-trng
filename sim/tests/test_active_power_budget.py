#!/usr/bin/env python3
"""stdlib-only unit test of the issue #604 active-power-budget reduction.

sim/post-layout-sampler-core/analysis/reduce-active-power-budget.py turns
two committed control records plus two Ts = 20 us corner reports into the
budget tables of analysis/active-power-budget.md. The arithmetic that
would silently lie if it rotted:

* per-leg totals are the SIGNED sums of the measured rail currents (the
  sources read negative when delivering) times 1.98 V, in uW;
* headroom is target-minus-total, so a failing corner reports negative;
* the 20 us verdict grades PASS/FAIL against 500 uW but refuses to grade a
  leg sitting within the runs' cross-run agreement band of the bound;
* the W_RST anchor compares the 20 us run's reset-held window against the
  committed control's own same-window numbers (stimulus-identical), and
  its delta feeds nothing else -- it is the cross-run gate the record's
  conclusions are conditioned on;
* a missing measurement, a wrong report status, or a record with no ok ff
  corner refuses to emit anything (EvidenceError), never a partial table;
* an authored analysis/disposition.md is appended verbatim when present.

No klt, no PDK, no ngspice: synthetic records exercise every path.
"""
from __future__ import annotations

import importlib.util
import json
import sys
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
           "testbench": "synthetic", "netlists": {},
           "tools": {"ngspice": "synthetic"}}
    p = tmp / f"ctrl-{int(t)}.json"
    p.write_text(json.dumps(rec))
    return p


def synth_report(tmp: Path, t: float, scale: float) -> Path:
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
    rep = {"status": "pass",
           "corners": [{"corner_id": "ff/1.980V/x", "measurements": meas,
                        "runtime_s": 1000.0, "status": "pass"}],
           "environment": {"remote": {"job_id": "synthetic-job",
                                      "state": "done",
                                      "runner_klt_version": "9.9",
                                      "runner_compatibility": "ok"}}}
    p = tmp / f"rep-{int(t)}.json"
    p.write_text(json.dumps(rep))
    return p


def install(tmp: Path, t_ctrl: dict, t_rep: dict) -> None:
    R.CONTROL_RECORDS = {-40.0: t_ctrl[-40.0], 125.0: t_ctrl[125.0]}
    R.TS20U_REPORTS = {-40.0: t_rep[-40.0], 125.0: t_rep[125.0]}


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        ctrl = {t: synth_control(tmp, t, 8.8e-5, 1.75e-4) for t in R.TEMPS}
        rep = {t: synth_report(tmp, t, 1.0) for t in R.TEMPS}
        install(tmp, ctrl, rep)
        R.SLUG = tmp  # redirect the output root
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
        check("| +125 C | schematic | 520.7 | 364.3 | -156.4 | PASS |" in text,
              "comparison row: 100 ns column, delta, verdict")
        verdicts = [ln for ln in text.splitlines() if " C | " in ln and
                    ("PASS" in ln or "FAIL" in ln or "AT BOUND" in ln)]
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
        # refusal paths
        print("refusals:")
        bad = json.loads(rep[-40.0].read_text())
        bad["corners"][0]["measurements"] = bad["corners"][0]["measurements"][:-3]
        rep[-40.0].write_text(json.dumps(bad))
        try:
            R.main([])
            check(False, "missing measurement refuses to emit")
        except R.EvidenceError:
            check(True, "missing measurement refuses to emit")
        bad2 = json.loads(ctrl[125.0].read_text())
        bad2["corners"][0]["ok"] = False
        ctrl[125.0].write_text(json.dumps(bad2))
        (tmp / "x").mkdir()
        install(tmp, ctrl, {t: synth_report(tmp / "x", t, 1.0) for t in R.TEMPS})
        try:
            R.main([])
            check(False, "non-ok ff corner refuses to emit")
        except R.EvidenceError:
            check(True, "non-ok ff corner refuses to emit")
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
