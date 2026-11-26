#!/usr/bin/env python3
"""Unit tests for sim/local-mismatch-monte-carlo/yield_reports.py (issue #598).

Synthetic inputs only -- no simulator, no PDK, no fleet, no `klt` (the pieces
under test are the pure derivation; the live replay is yield_reports.py --check
against the committed campaign).

    python3 sim/tests/test_yield_reports.py
"""
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_p = os.path.join(HERE, "..", "local-mismatch-monte-carlo", "yield_reports.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
from loadmod import load_module  # noqa: E402

yr = load_module("mm_yield_reports", _p)
red = yr.red  # the reducer this harness must reuse, never copy


def duty(scale):
    """A plausible nine-threshold duty curve (monotone up), scaled."""
    base = {30: 0.10, 35: 0.25, 40: 0.40, 45: 0.50, 50: 0.62,
            55: 0.72, 60: 0.80, 65: 0.88, 70: 0.95}
    return {k: min(1.0, v * scale) for k, v in base.items()}


ROWS = [
    {"ok": True, "duty": duty(1.0)},                      # array draw 1
    {"ok": True, "duty": duty(0.8)},                      # array draw 2
    {"ok": False, "duty": duty(1.2), "error": "KeyError"},  # excluded
    {"ok": True, "vtrip_v": 0.90},                        # sampler draw 1
    {"ok": True, "vtrip_v": 0.72},                        # sampler draw 2
    {"ok": True, "vtrip_v": 1.02},                        # sampler draw 3
]
VNOM = 1.8


class TestPairingSamples(unittest.TestCase):
    def test_matches_reduce_composition_and_order(self):
        p_all, h_all = yr.pairing_samples(ROWS, VNOM)
        good_a = [r for r in ROWS if "duty" in r and r.get("ok")]
        good_s = [r for r in ROWS if "vtrip_v" in r and r.get("ok")]
        self.assertEqual(len(p_all), len(good_a) * len(good_s))
        k = 0
        for a in good_a:                                  # array outer ...
            d = {int(x): v for x, v in a["duty"].items()}
            for s in good_s:                              # ... sampler inner
                self.assertAlmostEqual(p_all[k], red.duty_at(d, s["vtrip_v"] / VNOM))
                self.assertAlmostEqual(h_all[k], red.h_bias(p_all[k]))
                k += 1

    def test_uses_reduces_own_functions(self):
        self.assertIs(yr.red.duty_at, red.duty_at)
        self.assertIs(yr.red.h_bias, red.h_bias)
        self.assertEqual(yr.H_FLOOR, red.H_FLOOR)         # the spec row's own floor


class TestCrosscheck(unittest.TestCase):
    def setUp(self):
        self.p_all, self.h_all = yr.pairing_samples(ROWS, VNOM)
        worst = max(self.p_all, key=lambda p: abs(p - 0.5))
        self.S = {"raw_bit": {
            "n_pairings": len(self.p_all),
            "h_bias_min": min(self.h_all),
            "n_pairings_below_floor": sum(h < yr.H_FLOOR for h in self.h_all),
            "worst_case": {"p1": worst},
            "p1_all": {"min": min(self.p_all), "max": max(self.p_all)},
        }}

    def test_consistent_summary_passes(self):
        yr.crosscheck("synthetic", self.p_all, self.h_all, self.S)

    def _tamper(self, *path, value):
        S = json.loads(json.dumps(self.S))
        obj = S
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value
        with self.assertRaises(SystemExit):
            yr.crosscheck("synthetic", self.p_all, self.h_all, S)

    def test_refuses_every_tampered_statistic(self):
        self._tamper("raw_bit", "n_pairings", value=5)
        self._tamper("raw_bit", "h_bias_min", value=1.0)
        self._tamper("raw_bit", "n_pairings_below_floor", value=0)
        self._tamper("raw_bit", "worst_case", "p1", value=0.5)
        self._tamper("raw_bit", "p1_all", "min", value=0.0)
        self._tamper("raw_bit", "p1_all", "max", value=1.0)


class TestBuildDoc(unittest.TestCase):
    def setUp(self):
        self.p_all, self.h_all = yr.pairing_samples(ROWS, VNOM)
        self.S = {"pvt": {"proc": "tt", "temp": 27.0, "vnom": 1.8},
                  "seeds_array": [215, 216, 217], "seeds_sampler": [215, 216],
                  "n_array_ok": 2, "n_sampler_ok": 3}
        self.doc = yr.build_doc("synthetic-record", {"seed": {"rule": "seed0 + i - 1"}},
                                self.S, self.h_all)

    def test_measurement_shape_and_limits(self):
        (m,) = self.doc["measurements"]
        self.assertEqual(m["name"], yr.MEAS)
        self.assertEqual(m["unit"], "bit")
        self.assertEqual(m["samples"], self.h_all)
        self.assertEqual(m["limits"], {"min": yr.H_FLOOR})   # the row as written ...
        self.assertNotIn("target_yield", m["limits"])        # ... and no invented target
        self.assertEqual(m["source_corners"], ["tt/1.8V/27C"])

    def test_derivation_records_provenance(self):
        d = self.doc["derivation"]
        self.assertEqual(d["n_pairings"], len(self.h_all))
        self.assertEqual(d["seeds"]["array"], [215, 216, 217])
        self.assertIsNone(d["spec_row"]["target_yield"])
        self.assertIn("UPPER bound", d["quantity"])
        self.assertIn("arr0/smp0", d["negative_control"])
        for key in ("campaign_record", "raw_responses"):
            self.assertTrue(d[key].startswith(f"sim/{red.SLUG}/"), d[key])

    def test_dump_is_deterministic_json(self):
        b1, b2 = yr.dump(self.doc), yr.dump(self.doc)
        self.assertEqual(b1, b2)
        self.assertEqual(json.loads(b1), self.doc)


if __name__ == "__main__":
    unittest.main()
