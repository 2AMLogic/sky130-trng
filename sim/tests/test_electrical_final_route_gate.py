#!/usr/bin/env python3
"""Final-route electrical gate controls for the digital P&R harness (issue #250).

    python3 sim/tests/test_electrical_final_route_gate.py

No tool is run. The OpenSTA sessions of the committed #236 study are REPLAYED
from their retained raw per-corner logs
(sim/digital-electrical-repair/runs/*/electrical-audit/*.log.gz) through the
real ``final_route_audit.audit`` and the real reducer, then through the
harness' ``electrical_check`` / ``assemble_verdict``:

* unrepaired control: passes DRC/LVS/STA/cosim/negative controls (recorded
  verdict.json) but FAILS the electrical verdict (1512 slew + 50 cap);
* slew0531 candidate: all 16 expected corners audited, clean, passes;
* missing / unsupported corners, injected violations, a raising audit: fail,
  never zero.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS = REPO_ROOT / "sim/digital-electrical-repair/runs"
CONTROL = RUNS / "20261010-control/control"
CAND = RUNS / "20261010-cand1/slew0531"


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


fra = _load("final_route_audit", REPO_ROOT / "sim/digital-electrical-repair/analysis/final_route_audit.py")
harness = _load("pnr_and_verify_under_test", REPO_ROOT / "sim/digital-pnr/harness/pnr-and-verify.py")


def corners_of(run: Path) -> list[str]:
    return [c["name"] for c in json.loads((run / "pnr-output.json").read_text())["corners"]]


class Replay:
    """Stands in for subprocess.run: returns the recorded session of the
    corner named in the tcl script. ``mutate(corner, stdout) -> stdout|None``
    (None = session failure)."""

    def __init__(self, run: Path, mutate=None):
        self.run, self.mutate = run, mutate
        self.audit = json.loads((run / "electrical-audit.json").read_text())

    def __call__(self, cmd, **kw):
        corner = Path(cmd[-1]).stem.removeprefix("audit_")
        f = self.run / "electrical-audit" / f"{corner}.log.gz"
        if not f.exists():
            return SimpleNamespace(returncode=1, stdout="", stderr="no session")
        out = gzip.decompress(f.read_bytes()).decode().split("\n--stderr--\n")[0]
        # the retained log omits the ~7400 sensitivity rows; restore their count
        n = self.audit["corners"][corner]["sensitivity_pins_listed"]
        rows = "\n".join(f"p{i}/A 0.0001 0.1000 -0.0999 (VIOLATED)" for i in range(n))
        out = out.replace("<pin rows omitted; count recorded in electrical-audit.json>", rows)
        if self.mutate:
            out = self.mutate(corner, out)
            if out is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(returncode=0, stdout=out, stderr="")


def run_audit(run: Path, corners=None, mutate=None):
    with tempfile.TemporaryDirectory() as d:
        return fra.audit(run / "trng_digital.def.gz", run / "trng_digital_route.spef.gz",
                         REPO_ROOT / "sim/digital-electrical-repair/requests" / f"{run.name}.json",
                         corners or corners_of(run), Path(d) / "logs",
                         {"PDK_ROOT": "/nonexistent"}, runner=Replay(run, mutate))


class RecordedEvidence(unittest.TestCase):
    def test_control_fails_with_recorded_totals(self):
        res = run_audit(CONTROL)
        r = res["reduction"]
        self.assertEqual(r["verdict"], "violations")
        self.assertEqual(r["totals"], {"max_slew": 1512, "max_capacitance": 50})
        self.assertEqual(r["corners_audited"], 16)
        rec = json.loads((CONTROL / "electrical-audit.json").read_text())
        self.assertEqual(r, rec["reduction"])
        self.assertEqual(res["corners"], rec["corners"])

    def test_candidate_clean_all_16_corners(self):
        res = run_audit(CAND)
        r = res["reduction"]
        self.assertEqual((r["verdict"], r["corners_expected"], r["corners_audited"]), ("clean", 16, 16))
        self.assertEqual(r["totals"], {"max_slew": 0, "max_capacitance": 0})

    def test_result_records_input_hashes_and_coverage(self):
        res = run_audit(CAND)
        self.assertEqual(set(res["input_hashes"]), {"request", "routed_def", "post_route_spef"})
        text = " ".join(res["coverage_disclosure"])
        for needle in ("`nom` only", "set_load", "extracted post-route SPEF"):
            self.assertIn(needle, text)

    def test_raw_logs_retained(self):
        with tempfile.TemporaryDirectory() as d:
            fra.audit(CAND / "trng_digital.def.gz", CAND / "trng_digital_route.spef.gz",
                      REPO_ROOT / "sim/digital-electrical-repair/requests/slew0531.json",
                      corners_of(CAND), Path(d) / "logs", {"PDK_ROOT": "/x"}, runner=Replay(CAND))
            self.assertEqual(len(list((Path(d) / "logs").glob("*.log.gz"))), 16)


class FailureModes(unittest.TestCase):
    def test_failed_session_is_unsupported_not_zero(self):
        res = run_audit(CAND, mutate=lambda c, o: None if c == "ss_n40C_1v28" else o)
        r = res["reduction"]
        self.assertEqual(r["verdict"], "incomplete")
        self.assertEqual(r["coverage"]["ss_n40C_1v28"], "unsupported")

    def test_missing_corner_session(self):
        cs = corners_of(CAND) + ["tt_not_shipped"]
        r = run_audit(CAND, corners=cs)["reduction"]
        self.assertEqual(r["verdict"], "incomplete")
        self.assertEqual(r["coverage"]["tt_not_shipped"], "unsupported")

    def test_blind_session_is_unsupported(self):
        def blind(c, o):
            return o.split("===KLT_AUDIT_SENS_BEGIN===")[0] + "===KLT_AUDIT_SENS_BEGIN===\n===KLT_AUDIT_SENS_END===\n===KLT_AUDIT_DONE===\n"
        r = run_audit(CAND, mutate=lambda c, o: blind(c, o) if c == "tt_025C_1v80" else o)["reduction"]
        self.assertEqual(r["verdict"], "incomplete")
        self.assertEqual(r["coverage"]["tt_025C_1v80"], "unsupported")

    def test_injected_violation_fails(self):
        row = "_9999_/Y  1.5000  1.7000  -0.2000 (VIOLATED)\n"
        r = run_audit(CAND, mutate=lambda c, o: o.replace(
            "===KLT_AUDIT_SLEW_END===", row + "===KLT_AUDIT_SLEW_END===", 1) if c == "ff_100C_1v95" else o)["reduction"]
        self.assertEqual(r["verdict"], "violations")
        self.assertEqual(r["totals"]["max_slew"], 1)

    def test_unparsed_violated_row_is_unsupported(self):
        row = "garbage (VIOLATED)\n"
        r = run_audit(CAND, mutate=lambda c, o: o.replace(
            "===KLT_AUDIT_CAP_END===", row + "===KLT_AUDIT_CAP_END===", 1) if c == "ss_100C_1v40" else o)["reduction"]
        self.assertEqual(r["verdict"], "incomplete")


class HarnessGate(unittest.TestCase):
    def checks(self, run):
        return json.loads((run / "verdict.json").read_text())["verdict"]

    def elec(self, run, **kw):
        audit = lambda *a, **k: run_audit(run)  # noqa: E731
        return harness.electrical_check(None, None, None, corners_of(run), None, {}, audit=audit)

    def test_control_fails_electrical_and_preserves_other_checks(self):
        base = self.checks(CONTROL)
        self.assertTrue(all(base.values()), "control passes the pre-existing chain")
        elec = self.elec(CONTROL)
        verdict, ok = harness.assemble_verdict(base, elec)
        self.assertFalse(ok)
        self.assertFalse(verdict["electrical_final_route"])
        for k, v in base.items():
            self.assertEqual(verdict[k], v, f"{k} result preserved")
        self.assertEqual(elec["audit"]["reduction"]["totals"]["max_slew"], 1512)

    def test_candidate_passes_everything(self):
        verdict, ok = harness.assemble_verdict(self.checks(CAND), self.elec(CAND))
        self.assertTrue(ok)
        self.assertTrue(verdict["electrical_final_route"])

    def test_other_failure_still_fails_with_clean_electrical(self):
        base = {**self.checks(CAND), "lvs": False}
        verdict, ok = harness.assemble_verdict(base, self.elec(CAND))
        self.assertFalse(ok)
        self.assertTrue(verdict["electrical_final_route"])
        self.assertFalse(verdict["lvs"])

    def test_raising_audit_is_failure_with_diagnostics(self):
        def boom(*a, **k):
            raise RuntimeError("openroad missing")
        elec = harness.electrical_check(None, None, None, ["c0", "c1"], None, {}, audit=boom)
        self.assertFalse(elec["ok"])
        self.assertEqual(elec["audit"]["reduction"]["verdict"], "incomplete")
        self.assertIn("openroad missing", elec["audit"]["error"])
        self.assertEqual(elec["audit"]["reduction"]["totals"], {"max_slew": 0, "max_capacitance": 0})
        _, ok = harness.assemble_verdict({"drc": True}, elec)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
