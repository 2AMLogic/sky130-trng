#!/usr/bin/env python3
"""Unit tests for `sim/digital-section-behavioral/harness/health-detection-coverage.py`.

Standard library only, no simulator::

    python3 sim/tests/test_health_detection_coverage.py

Checks the analytic min-entropy formulas and the headline detection facts on
small synthetic streams (experiment I's building blocks).
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = REPO_ROOT / "sim" / "digital-section-behavioral" / "harness" / "health-detection-coverage.py"
_spec = importlib.util.spec_from_file_location("health_detection_coverage", _PATH)
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


class Analytic(unittest.TestCase):
    def test_markov_symmetric(self):
        self.assertAlmostEqual(H.h_markov(0.5, 0.5), 1.0)
        self.assertAlmostEqual(H.h_markov(0.9, 0.9), -math.log2(0.9))

    def test_markov_asymmetric_cycle(self):
        # alternation cycle (1->0->1) has geometric mean sqrt(0.1*0.1)=0.1 < stay 0.9
        self.assertAlmostEqual(H.h_markov(0.9, 0.5), -math.log2(0.9))
        # strongly alternating chain: the 2-cycle dominates
        self.assertAlmostEqual(H.h_markov(0.05, 0.05), -math.log2(0.95))

    def test_periodic_and_lockmix(self):
        self.assertEqual(H.h_periodic(0.0), 0.0)
        self.assertAlmostEqual(H.h_lockmix(0.5, 0.0), 0.5)
        self.assertAlmostEqual(H.h_lockmix(0.0, 0.3), 1.0)


class Detection(unittest.TestCase):
    def test_alternating_is_missed_by_online_tests(self):
        bits = H.gen_periodic(random.Random(1), 8192, 2, 0.0, [0, 1])
        first, _, n = H.run_health(bits)
        self.assertIsNone(first)
        self.assertEqual(n, 0)

    def test_stuck_trips_rct_at_cutoff(self):
        first, which, _ = H.run_health([1] * 200)
        self.assertEqual(first, H.C_RCT)
        self.assertEqual(which, "RCT")

    def test_fair_coin_no_alarm_and_generators_seeded(self):
        a = H.gen_markov(random.Random(7), 4096, 0.7, 0.7)
        b = H.gen_markov(random.Random(7), 4096, 0.7, 0.7)
        self.assertEqual(a, b)
        self.assertIsNone(H.run_health(H.gen_markov(random.Random(3), 8192, 0.5, 0.5))[0])

    def test_measure_flags_estimator_catch_for_alternating(self):
        bits = [i & 1 for i in range(16384)]
        r = H.measure("alt", "periodic", {}, 0.0, bits)
        self.assertFalse(r["alarm"])
        self.assertTrue(r["below_target"])
        self.assertTrue(r["estimator_catchers"])


if __name__ == "__main__":
    unittest.main()
