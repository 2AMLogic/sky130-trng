#!/usr/bin/env python3
"""Unit tests for `sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`.

Standard library only, no simulator::

    python3 sim/tests/test_raw_bit_battery.py

Synthetic streams: ideal (seeded PRNG), biased, serially correlated,
periodic.  Each battery test must reject its targeted defect and pass ideal
input at alpha = 0.01; short input must be INSUFFICIENT, never PASS.
"""

from __future__ import annotations

import importlib.util
import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis" / "raw-bit-battery.py"
_spec = importlib.util.spec_from_file_location("raw_bit_battery", _PATH)
assert _spec is not None and _spec.loader is not None
B = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
_spec.loader.exec_module(B)


def ideal(n, seed=1):
    r = random.Random(seed)
    return [r.getrandbits(1) for _ in range(n)]


def biased(n, p1=0.6, seed=2):
    r = random.Random(seed)
    return [1 if r.random() < p1 else 0 for _ in range(n)]


def correlated(n, stay=0.8, seed=3):
    r = random.Random(seed)
    out = [0]
    for _ in range(n - 1):
        out.append(out[-1] if r.random() < stay else 1 - out[-1])
    return out


def periodic(n, pat=(1, 1, 0, 1, 0, 0, 1, 0)):
    return [pat[i % len(pat)] for i in range(n)]


class TestSpecialFunctions(unittest.TestCase):
    def test_igamc_known(self):
        # Q(1, x) = exp(-x); Q(0.5, x) = erfc(sqrt(x))
        import math
        for x in (0.3, 1.0, 5.0, 20.0):
            self.assertAlmostEqual(B.igamc(1.0, x), math.exp(-x), places=10)
            self.assertAlmostEqual(B.igamc(0.5, x), math.erfc(math.sqrt(x)),
                                   places=10)

    def test_sp80022_example_monobit(self):
        # SP 800-22 section 2.1.8 example: 1100100100001111110110101010001000
        # 100001011010001100001000110100110001001100011001100010100010111000
        bits = [int(c) for c in
                "11001001000011111101101010100010001000010110100011000010001101"
                "00110001001100011001100010100010111000"]
        self.assertEqual(len(bits), 100)
        self.assertAlmostEqual(B.t_monobit(bits), 0.109599, places=5)
        self.assertAlmostEqual(B.t_runs(bits), 0.500798, places=5)


class TestBatteryRejectsDefects(unittest.TestCase):
    N = 20000

    def test_ideal_passes_every_test(self):
        res = B.run_battery(ideal(self.N))
        for name, t in res["tests"].items():
            self.assertEqual(t["status"], "PASS", (name, t))
        self.assertEqual(res["verdict"], "PASS")

    def test_biased_fails_frequency_tests(self):
        res = B.run_battery(biased(self.N))
        for name in ("monobit", "block_frequency", "cusum_forward"):
            self.assertEqual(res["tests"][name]["status"], "FAIL", name)
        self.assertEqual(res["verdict"], "FAIL")

    def test_correlated_fails_runs_and_serial(self):
        res = B.run_battery(correlated(self.N))
        for name in ("runs", "serial_1", "approximate_entropy"):
            self.assertEqual(res["tests"][name]["status"], "FAIL", name)

    def test_periodic_fails_pattern_tests(self):
        res = B.run_battery(periodic(self.N))
        for name in ("serial_1", "approximate_entropy"):
            self.assertEqual(res["tests"][name]["status"], "FAIL", name)

    def test_long_runs_fail_longest_run(self):
        bits = []
        r = random.Random(5)
        for _ in range(self.N // 40):
            blk = [r.getrandbits(1) for _ in range(40)]
            blk[10:30] = [1] * 20
            bits += blk
        self.assertEqual(B.run_battery(bits)["tests"]["longest_run"]["status"],
                         "FAIL")

    def test_pass_proportion_ideal_and_biased(self):
        ok = B.run_battery(ideal(40 * 1000, seed=9), segment_len=1000)
        self.assertEqual(ok["mode"], "pass-proportion")
        self.assertEqual(ok["verdict"], "PASS", ok["tests"])
        bad = B.run_battery(biased(40 * 1000, seed=9), segment_len=1000)
        self.assertEqual(bad["tests"]["monobit"]["status"], "FAIL")


class TestMinimumLengthGuards(unittest.TestCase):
    def test_short_input_insufficient_not_pass(self):
        res = B.run_battery(ideal(24))
        self.assertEqual(res["verdict"], "INSUFFICIENT")
        for t in res["tests"].values():
            self.assertEqual(t["status"], "INSUFFICIENT")
            self.assertNotIn("p_values", t)

    def test_each_test_has_its_own_floor(self):
        res = B.run_battery(ideal(150))
        st = {k: v["status"] for k, v in res["tests"].items()}
        self.assertEqual(st["monobit"], "PASS")
        self.assertEqual(st["approximate_entropy"], "INSUFFICIENT")
        self.assertEqual(res["verdict"], "INSUFFICIENT")

    def test_too_few_segments_insufficient(self):
        res = B.run_battery(ideal(3000), segment_len=1000)
        self.assertEqual(res["verdict"], "INSUFFICIENT")

    def test_estimators_refuse_short_input(self):
        res = B.entropy_estimates(ideal(24))
        self.assertEqual(res["verdict"], "INSUFFICIENT")
        self.assertIsNone(res["h_min_bits"])
        mid = B.entropy_estimates(ideal(2000))
        self.assertEqual(mid["estimators"]["compression"]["status"],
                         "INSUFFICIENT")
        self.assertEqual(mid["verdict"], "INSUFFICIENT")


class TestEstimators(unittest.TestCase):
    N = 20000

    def test_ideal_high_entropy(self):
        res = B.entropy_estimates(ideal(self.N))
        self.assertEqual(res["verdict"], "ESTIMATE")
        for name, e in res["estimators"].items():
            self.assertGreater(e["h_bits"], 0.6, name)  # collision/compression CIs are wide at this n
            self.assertLessEqual(e["h_bits"], 1.0, name)
        self.assertGreater(res["h_min_bits"], 0.6)

    def test_biased_mcv_matches_theory(self):
        res = B.entropy_estimates(biased(self.N, 0.8))
        mcv = res["estimators"]["mcv"]["h_bits"]
        self.assertLess(mcv, 0.35)  # -log2(0.8)=0.32
        self.assertGreater(mcv, 0.28)
        self.assertLessEqual(res["h_min_bits"], mcv)
        self.assertGreater(res["h_min_bits"], 0.1)

    def test_correlated_caught_beyond_mcv(self):
        # Marginally balanced but sticky: MCV is blind, others are not.
        bits = correlated(self.N, stay=0.9)
        res = B.entropy_estimates(bits)
        e = res["estimators"]
        self.assertGreater(e["mcv"]["h_bits"], 0.9)
        self.assertLess(e["markov"]["h_bits"], 0.6)  # true ~0.47
        self.assertLess(e["collision"]["h_bits"], 0.9)
        self.assertLess(res["h_min_bits"], e["mcv"]["h_bits"] - 0.3)
        self.assertNotEqual(res["binding_estimator"], "mcv")

    def test_periodic_collapses(self):
        res = B.entropy_estimates(periodic(self.N))
        e = res["estimators"]
        self.assertLess(e["markov"]["h_bits"], 0.5)
        self.assertLess(e["lrs"]["h_bits"], 0.1)
        self.assertLess(e["t_tuple"]["h_bits"], 0.1)
        self.assertLess(e["compression"]["h_bits"], 0.2)
        self.assertLess(res["h_min_bits"], 0.1)

    def test_constant_stream_zero(self):
        res = B.entropy_estimates([1] * 13000)
        self.assertEqual(res["h_min_bits"], 0.0)


class TestRecordCaveat(unittest.TestCase):
    def test_results_carry_provisional_caveat(self):
        self.assertIn("provisional until measured on silicon",
                      B.run_battery(ideal(10))["caveat"])
        self.assertIn("provisional until measured on silicon",
                      B.entropy_estimates(ideal(10))["caveat"])

    def test_report_on_real_record_is_insufficient(self):
        recs = B.raw_bit_entropy.campaign_records(B.RECORDS_DIR)
        if not recs:
            self.skipTest("no campaign record")
        body, summary = B.analyse_record(recs[-1])
        self.assertIn("provisional until measured on silicon", body)
        for c in summary["per_corner"]:
            self.assertEqual(c["battery"]["verdict"], "INSUFFICIENT")


if __name__ == "__main__":
    unittest.main()
