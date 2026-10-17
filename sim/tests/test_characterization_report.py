#!/usr/bin/env python3
"""Unit tests for sim/bin/characterization_report.py (issue #291).

    python3 sim/tests/test_characterization_report.py

Standard library only; synthetic trees in temp dirs. The last case checks
the committed report is current (same as the CI staleness gate).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
import characterization_report as cr  # noqa: E402

SPEC = """# x

## Target specification (DRAFT)

| Parameter | Target | Stretch |
|---|---|---|
| Alpha | a is ok | — |
| Beta | b >= 1 | — |
| Gamma | nothing recorded | — |

after
"""


def make_root(tmp: Path, alpha_ok=True, beta=2.0, write_beta=True) -> Path:
    (tmp / "README.md").write_text(SPEC)
    d = tmp / "sim" / "s" / "records"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({"record_id": "a", "level": "L", "ok": alpha_ok}))
    if write_beta:
        (d / "b.json").write_text(json.dumps(
            {"record_id": "b", "rows": [{"corner": "tt", "temp_c": 27.0, "vdd_v": 1.8, "x": beta},
                                        {"corner": "ss", "temp_c": -40.0, "vdd_v": 1.62, "x": 3.0}]}))
    return tmp


EV = {
    "Alpha": [{"record": "sim/s/records/a.json", "check": "ok", "field": "ok", "op": "eq", "value": True, "pvt": None}],
    "Beta": [{"record": "sim/s/records/b.json", "check": "x>=1", "field": "rows[].x", "op": "ge", "value": 1.0,
              "pvt": "rows[]"}],
}


def verdicts(rep):
    return {r["parameter"]: r["verdict"] for r in rep["rows"]}


class Report(unittest.TestCase):
    def build(self, **kw):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = make_root(Path(t.name), **kw)
        return root, cr.build_report(root, EV)

    def test_met_and_unrecorded_row(self):
        _, rep = self.build()
        self.assertEqual(verdicts(rep), {"Alpha": "met", "Beta": "met", "Gamma": "not measured"})
        self.assertEqual(rep["overall"], "incomplete")
        beta = rep["rows"][1]
        self.assertEqual(beta["pvt_coverage"], ["ss -40C 1.62V", "tt 27C 1.8V"])
        self.assertEqual(beta["evidence"][0]["record_id"], "b")
        self.assertEqual(len(beta["evidence"][0]["sha256"]), 64)

    def test_negative_failing_record_is_unmet(self):
        _, rep = self.build(alpha_ok=False)
        self.assertEqual(verdicts(rep)["Alpha"], "unmet")
        self.assertEqual(rep["overall"], "fail")

    def test_negative_worst_case_row_fails_the_target(self):
        _, rep = self.build(beta=0.5)  # one corner below threshold, other above
        self.assertEqual(verdicts(rep)["Beta"], "unmet")

    def test_negative_missing_record_is_not_measured(self):
        _, rep = self.build(write_beta=False)
        self.assertEqual(verdicts(rep)["Beta"], "not measured")
        self.assertIsNone(rep["rows"][1]["evidence"][0]["sha256"])

    def test_unmet_beats_not_measured_but_never_met_beats_unmet(self):
        self.assertEqual(cr.aggregate(["met", "unmet", "not measured"]), "unmet")
        self.assertEqual(cr.aggregate(["met", "not measured"]), "not measured")
        self.assertEqual(cr.aggregate([]), "not measured")

    def test_absent_field_is_unmet_not_met(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = make_root(Path(t.name))
        ev = {"Alpha": [dict(EV["Alpha"][0], field="nope")]}
        self.assertEqual(verdicts(cr.build_report(root, ev))["Alpha"], "unmet")

    def test_negative_fanned_element_missing_field_is_unmet(self):
        # one corner lacks "x"; the other passes. Skipping it would give met.
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = make_root(Path(t.name))
        p = root / "sim/s/records/b.json"
        rec = json.loads(p.read_text())
        del rec["rows"][0]["x"]
        p.write_text(json.dumps(rec))
        rep = cr.build_report(root, EV)
        self.assertEqual(verdicts(rep)["Beta"], "unmet")
        self.assertIn("absent from 1", rep["rows"][1]["evidence"][0]["detail"])

    def test_negative_fan_over_non_list_is_unmet(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = make_root(Path(t.name))
        ev = {"Alpha": [dict(EV["Alpha"][0], field="ok[]")]}
        self.assertEqual(verdicts(cr.build_report(root, ev))["Alpha"], "unmet")

    def test_selector_and_all_detected(self):
        rec = {"inj": [{"name": "s0", "t": {"detected": 5, "runs": 5}},
                       {"name": "s1", "t": {"detected": 4, "runs": 5}},
                       {"name": "tog", "t": {"detected": 0, "runs": 5}}]}
        v, miss = cr.extract_strict(rec, "inj[name=s0].t")
        self.assertEqual((len(v), miss), (1, 0))
        self.assertTrue(cr.compare(v, "all_detected", None, miss)[0])
        # one partially-detected scenario fails the check
        v, miss = cr.extract_strict(rec, "inj[name=s0|s1].t")
        self.assertFalse(cr.compare(v, "all_detected", None, miss)[0])
        # a selected scenario that does not exist is missing, hence unmet
        v, miss = cr.extract_strict(rec, "inj[name=s0|nope].t")
        self.assertEqual(miss, 1)
        self.assertFalse(cr.compare(v, "all_detected", None, miss)[0])
        # zero runs is never "all detected"
        self.assertFalse(cr.compare([{"detected": 0, "runs": 0}], "all_detected", None)[0])

    def test_pvt_label_formats_normalised(self):
        rec = {"s": ["ss -40 C 1.62 V"], "d": {"proc": "ss", "temp": -40.0, "vnom": 1.62}}
        self.assertEqual(cr.pvt_labels(rec, "s[]"), ["ss -40C 1.62V"])
        self.assertEqual(cr.pvt_labels(rec, "d"), ["ss -40C 1.62V"])

    def test_stray_mapping_key_rejected(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = make_root(Path(t.name))
        with self.assertRaises(SystemExit):
            cr.build_report(root, {"Nonexistent": []})

    def test_all_met_is_the_only_pass(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = make_root(Path(t.name))
        rep = cr.build_report(root, {k: v for k, v in EV.items()} | {"Gamma": [EV["Alpha"][0]]})
        self.assertEqual(rep["overall"], "pass")

    def test_deterministic_bytes(self):
        root, rep = self.build()
        again = cr.build_report(root, EV)
        self.assertEqual(cr.render_json(rep), cr.render_json(again))
        self.assertEqual(cr.render_md(rep), cr.render_md(again))
        self.assertIn("**not measured**", cr.render_md(rep))

    @mock.patch.object(cr, "EVIDENCE", EV)
    def test_envelope_status_never_pass_unless_overall_pass(self):
        _, rep = self.build()
        for overall in ("fail", "incomplete"):
            env = json.loads(cr.render_envelope({**rep, "overall": overall}))
            self.assertEqual((env["kind"], env["status"]), ("generic", "fail"))
            self.assertEqual(env["metrics"]["overall"], overall)
        env = json.loads(cr.render_envelope({**rep, "overall": "pass"}))
        self.assertEqual(env["status"], "pass")

    @mock.patch.object(cr, "EVIDENCE", EV)
    def test_check_mode_detects_staleness(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        root = make_root(Path(t.name))
        self.assertEqual(cr.main(["--root", str(root), "--check"]), 1)  # nothing written yet
        (root / "signoff").mkdir()
        self.assertEqual(cr.main(["--root", str(root)]), 0)
        self.assertEqual(cr.main(["--root", str(root), "--check"]), 0)
        (root / cr.OUT_JSON).write_text("{}\n")
        self.assertEqual(cr.main(["--root", str(root), "--check"]), 1)


class Committed(unittest.TestCase):
    def test_every_spec_row_listed_and_committed_report_current(self):
        rep = cr.build_report(REPO)
        spec = [r["parameter"] for r in cr.parse_spec_table((REPO / "README.md").read_text())]
        self.assertEqual([r["parameter"] for r in rep["rows"]], spec)
        self.assertEqual(cr.main(["--check"]), 0)
        # area is stated unmet, not relaxed
        self.assertEqual(verdicts(rep)["Area"], "unmet")
        # DR-0010 row 3 is open on #221: the failing tt mismatch record keeps it unmet
        self.assertEqual(verdicts(rep)["Raw min-entropy per bit"], "unmet")
        ent = {e["record_id"]: e["verdict"] for e in rep["rows"][2]["evidence"]}
        self.assertEqual(ent["20261009-111127-e57ad27"], "unmet")
        # health tests rest on both no-false-alarm and stuck-at detection
        health = next(r for r in rep["rows"] if r["parameter"] == "Health tests")
        self.assertEqual(len(health["evidence"]), 3)
        self.assertTrue(all("#221" in e["check"] for e in health["evidence"][:2]))


if __name__ == "__main__":
    unittest.main()
