#!/usr/bin/env python3
"""Reduction controls for sim/digital-electrical-repair/ (issue #236). stdlib only.

    python3 sim/tests/test_electrical_reduction.py

Proves that the electrical-limit reduction cannot turn absent data, an
unsupported check, or a setup/hold pass into electrical success.
"""
from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_sp = importlib.util.spec_from_file_location(
    "electrical", REPO_ROOT / "sim/digital-electrical-repair/analysis/electrical.py")
e = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(e)

CORNERS = [f"c{i}" for i in range(16)]


def zero():
    return {"count": 0, "unique_pins": 0, "worst_excess": 0.0, "worst_pin": None, "limits": []}


def good():
    return {c: {"status": "audited", "max_slew": zero(), "max_capacitance": zero()} for c in CORNERS}


SLEW_TXT = """max slew

Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_1_/A                                   1.5000    2.7900   -1.2900 (VIOLATED)
_2_/B1                                  1.5000    1.5600   -0.0600 (VIOLATED)
"""


class Parse(unittest.TestCase):
    def test_rows_and_summary(self):
        rows = e.parse_violators(SLEW_TXT)
        self.assertEqual(len(rows), 2)
        s = e.summarise(rows)
        self.assertEqual((s["count"], s["worst_pin"]), (2, "_1_/A"))
        self.assertAlmostEqual(s["worst_excess"], 1.29)

    def test_absent_block_is_none_not_zero(self):
        self.assertIsNone(e.block("no markers here", "AUDIT_SLEW"))
        self.assertEqual(e.block("===KLT_X_BEGIN===\nabc\n===KLT_X_END===", "X"), "abc\n")


class Reduction(unittest.TestCase):
    def test_all_zero_final_is_clean(self):
        r = e.reduce_evidence(CORNERS, good(), "final")
        self.assertEqual(r["verdict"], "clean")
        self.assertEqual(r["corners_audited"], 16)

    def test_missing_corner_is_not_clean(self):
        d = good()
        del d["c7"]
        r = e.reduce_evidence(CORNERS, d, "final")
        self.assertEqual(r["verdict"], "incomplete")
        self.assertEqual(r["coverage"]["c7"], "missing")

    def test_surplus_corner_cannot_replace_missing(self):
        d = good()
        d["extra"] = d.pop("c3")
        r = e.reduce_evidence(CORNERS, d, "final")
        self.assertEqual(r["verdict"], "incomplete")
        self.assertEqual(r["surplus_corners"], ["extra"])

    def test_injected_violation_in_one_corner_and_class(self):
        for cls in e.CLASSES:
            d = good()
            d["c9"][cls] = e.summarise(e.parse_violators(SLEW_TXT))
            r = e.reduce_evidence(CORNERS, d, "final")
            self.assertEqual(r["verdict"], "violations", cls)
            self.assertEqual(r["totals"][cls], 2)
            other = [c for c in e.CLASSES if c != cls][0]
            self.assertEqual(r["totals"][other], 0)

    def test_unsupported_corner_blocks_clean(self):
        d = good()
        d["c0"] = {"status": "unsupported", "reason": "session failed"}
        r = e.reduce_evidence(CORNERS, d, "final")
        self.assertEqual(r["verdict"], "incomplete")
        self.assertEqual(r["coverage"]["c0"], "unsupported")

    def test_malformed_class_is_missing(self):
        d = good()
        del d["c5"]["max_capacitance"]
        r = e.reduce_evidence(CORNERS, d, "final")
        self.assertEqual(r["verdict"], "incomplete")

    def test_no_data_is_never_success(self):
        for pc in (None, {}):
            self.assertEqual(e.reduce_evidence(CORNERS, pc, "final")["verdict"], "incomplete")
        self.assertEqual(e.reduce_evidence([], good(), "final")["verdict"], "incomplete")

    def test_violation_wins_over_missing(self):
        d = good()
        del d["c1"]
        d["c2"]["max_slew"] = e.summarise(e.parse_violators(SLEW_TXT))
        self.assertEqual(e.reduce_evidence(CORNERS, d, "final")["verdict"], "violations")

    def test_estimate_clean_is_labelled_and_not_a_clean_candidate(self):
        est = e.reduce_evidence(CORNERS, good(), "estimate")
        self.assertEqual(est["label"], "estimate-clean, final-route unaudited")
        fin = e.reduce_evidence(CORNERS, None, "final")
        self.assertEqual(e.candidate_verdict(est, fin), "estimate-clean, final-route unaudited")

    def test_clean_candidate_needs_final(self):
        est = e.reduce_evidence(CORNERS, good(), "estimate")
        fin = e.reduce_evidence(CORNERS, good(), "final")
        self.assertTrue(e.candidate_verdict(est, fin).startswith("clean candidate"))
        bad = copy.deepcopy(good())
        bad["c4"]["max_slew"] = e.summarise(e.parse_violators(SLEW_TXT))
        fin2 = e.reduce_evidence(CORNERS, bad, "final")
        self.assertTrue(e.candidate_verdict(est, fin2).startswith("not clean"))

    def test_setup_hold_pass_is_not_an_input(self):
        # The reducer takes only electrical per-corner summaries; a record
        # holding perfect setup/hold slack but no electrical fields is
        # 'missing', never 'audited'.
        sta_only = {c: {"setup_slack_ns": 1.0, "hold_slack_ns": 1.0, "timing_status": "constrained"}
                    for c in CORNERS}
        r = e.reduce_evidence(CORNERS, sta_only, "final")
        self.assertEqual(r["verdict"], "incomplete")
        self.assertEqual(r["corners_audited"], 0)

    def test_bad_kind_rejected(self):
        with self.assertRaises(ValueError):
            e.reduce_evidence(CORNERS, good(), "sta")


if __name__ == "__main__":
    unittest.main()
