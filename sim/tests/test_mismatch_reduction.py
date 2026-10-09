#!/usr/bin/env python3
"""Unit tests for sim/local-mismatch-monte-carlo/reduce.py (issue #215).

Synthetic inputs only -- no simulator, no PDK, no fleet.

    python3 sim/tests/test_mismatch_reduction.py
"""
import importlib.util
import math
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_p = os.path.join(HERE, "..", "local-mismatch-monte-carlo", "reduce.py")
_s = importlib.util.spec_from_file_location("mm_reduce", _p)
mm = importlib.util.module_from_spec(_s)
_s.loader.exec_module(mm)


class TestStats(unittest.TestCase):
    def test_std_and_quantile(self):
        self.assertAlmostEqual(mm.std([1, 2, 3, 4]), math.sqrt(5 / 3))
        self.assertEqual(mm.std([5.0]), 0.0)
        self.assertEqual(mm.quantile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertAlmostEqual(mm.quantile([0, 10], 0.25), 2.5)

    def test_ring_period(self):
        t = [1e-9 + k * 2.5e-9 for k in range(40)]
        self.assertAlmostEqual(mm.ring_period(t), 2.5e-9)


class TestCloseness(unittest.TestCase):
    def test_exact_rational_is_zero(self):
        d, p, q = mm.closeness(1.0, 1.5, mm.DR5_RATIOS)      # period ratio 1.5 -> 3/2
        self.assertAlmostEqual(d, 0.0)
        self.assertEqual((p, q), (3, 2))

    def test_order_free(self):
        self.assertAlmostEqual(mm.closeness(1.0, 1.1, mm.ANY_RATIOS)[0], mm.closeness(1.1, 1.0, mm.ANY_RATIOS)[0])

    def test_one_to_one_only_in_any(self):
        T = [1.0, 1.02, 3.0, 5.0]           # rings 1,2 are 2 % apart (1:1); no small rational otherwise close
        self.assertAlmostEqual(mm.pair_closeness(T, mm.ANY_RATIOS)[0], 0.02, places=6)
        self.assertGreater(mm.pair_closeness(T, mm.DR5_RATIOS)[0], 0.02)
        self.assertEqual(mm.pair_closeness(T, mm.ANY_RATIOS)[1], "1-2")

    def test_q_ratio_identity_and_slowdown(self):
        T0 = [1.0, 1.1, 1.2, 1.3]
        self.assertAlmostEqual(mm.q_ratio(T0, T0), 1.0)
        self.assertLess(mm.q_ratio([t * 1.01 for t in T0], T0), 1.0)


    def test_dr0005_figure(self):
        # DR-0005: ladder span 1.2096 against 4/3 -> 9.3 %
        self.assertAlmostEqual(mm.closeness(1.0, 1.2096, mm.DR5_RATIOS)[0] * 100, 9.28, places=1)


class TestBias(unittest.TestCase):
    DUTY = {30: 0.40, 35: 0.38, 40: 0.36, 45: 0.34, 50: 0.32, 55: 0.30, 60: 0.28, 65: 0.26, 70: 0.24}

    def test_duty_interpolates_and_extrapolates(self):
        self.assertAlmostEqual(mm.duty_at(self.DUTY, 0.50), 0.32)
        self.assertAlmostEqual(mm.duty_at(self.DUTY, 0.475), 0.33)
        self.assertAlmostEqual(mm.duty_at(self.DUTY, 0.75), 0.24 - 0.10 * 0.0 - 0.02 * 1.0, places=6)
        self.assertEqual(mm.duty_at({30: 0.01, 70: 0.0}, 0.9), 0.0)    # clamped

    def test_h_bias(self):
        self.assertAlmostEqual(mm.h_bias(0.5), 1.0)
        self.assertAlmostEqual(mm.h_bias(0.5 ** 0.5 / 2 * 0 + 1 / math.sqrt(2) ), 0.5, places=6)   # the DR-0004 floor
        self.assertEqual(mm.h_bias(1.0), 0.0)
        self.assertAlmostEqual(mm.h_bias(0.3), mm.h_bias(0.7))

    def test_mcv_on_fair_and_biased_stream(self):
        fair = mm.mcv_on_bernoulli(0.5, n=20000, seed=1)
        biased = mm.mcv_on_bernoulli(0.9, n=20000, seed=1)
        self.assertGreater(fair["h_hat_bits"], 0.9)
        self.assertLess(biased["h_hat_bits"], 0.2)


class TestExtrapolation(unittest.TestCase):
    def test_locked_by_construction_fires(self):
        # rings 1 and 2 nominally 0.5 % apart with a tiny spread: 1:1 closeness is < 1 % in nearly every draw
        T = [[1.0 * (1 + 1e-4 * k), 1.005, 1.3, 1.7] for k in range(-3, 4)]
        ext, _, _ = mm.extrapolate_closeness(T, n_draws=2000, seed=3)
        self.assertGreater(ext["1.0"]["any"], 0.9)

    def test_well_separated_does_not_fire(self):
        T = [[1.0 * (1 + 1e-4 * k), 1.0 * 1.04 * (1 - 1e-4 * k), 2.9, 4.4] for k in range(-3, 4)]
        ext, _, _ = mm.extrapolate_closeness(T, n_draws=2000, seed=3)
        self.assertEqual(ext["1.0"]["any"], 0.0)

    def test_seeded_deterministic(self):
        T = [[1.0 + 0.01 * k, 1.1, 1.3, 1.5] for k in range(5)]
        self.assertEqual(mm.extrapolate_closeness(T, 500, 7)[0], mm.extrapolate_closeness(T, 500, 7)[0])


def _arr_resp(T_ns, xo_avg, duty, status="pass"):
    ms = []
    for r in range(4):
        for k in range(mm.E0, mm.E0 + mm.NEDGE):
            ms.append({"name": f"t{r + 1}_{k}", "value": (k * T_ns[r]) * 1e-9})
    ms += [{"name": f"duty{f}", "value": duty} for f in mm.THRS]
    ms.append({"name": "xo_avg", "value": xo_avg})
    return {"status": status, "corner_id": "x", "measurements": ms, "monte_carlo": {"sample_index": 0}}


class TestUnits(unittest.TestCase):
    PLAN = {"pvt": {"vnom": 1.8}}

    def test_array_unit(self):
        row = mm.array_unit(_arr_resp([2.5, 2.6, 2.7, 2.8], 0.9, 0.5), self.PLAN)
        self.assertTrue(row["ok"])
        self.assertAlmostEqual(row["T_ns"][0], 2.5)
        self.assertAlmostEqual(row["bias_xo"], 0.5)

    def test_failed_unit_kept_not_dropped(self):
        row = mm.array_unit({"status": "fail", "measurements": []}, self.PLAN)
        self.assertFalse(row["ok"])

    def test_sampler_unit_mean_trip(self):
        row = mm.sampler_unit({"status": "pass", "measurements": [
            {"name": "vtrip_up", "value": 0.86}, {"name": "vtrip_dn", "value": 0.82}]}, self.PLAN)
        self.assertAlmostEqual(row["vtrip_v"], 0.84)


if __name__ == "__main__":
    unittest.main()
