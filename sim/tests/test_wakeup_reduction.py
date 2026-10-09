#!/usr/bin/env python3
"""Unit tests for sim/wake-up-transient/wakeup.py (issue #216). Standard library only.

    python3 sim/tests/test_wakeup_reduction.py
"""
import importlib.util
import math
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("wakeup", REPO / "sim/wake-up-transient/wakeup.py")
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)


def edge_train(p_final, n, first=1.0e-9, slow=0.0, tau=3.0):
    """Edges of a ring whose period starts (1+slow)x long and relaxes with time constant tau periods."""
    t = [first]
    for k in range(n):
        t.append(t[-1] + p_final * (1 + slow * math.exp(-k / tau)))
    return t


class Settle(unittest.TestCase):
    def test_already_steady(self):
        s = w.settle(edge_train(5e-9, 40), 0.01)
        self.assertEqual(s["k_settle"], 0)
        self.assertAlmostEqual(s["t_settle"], 1e-9)
        self.assertAlmostEqual(s["p_ref"], 5e-9, delta=1e-15)

    def test_relaxing_start(self):
        # period 20 % long at first, relaxing with tau = 3 periods: within 1 % once 0.2 e^-k/3 <= 0.01, k >= 9
        e = edge_train(5e-9, 40, slow=0.2)
        s = w.settle(e, 0.01)
        self.assertEqual(s["k_settle"], 9)
        self.assertAlmostEqual(s["t_settle"], e[9])
        self.assertGreater(s["first_period_err"], 0.19)
        # tighter tolerance settles later
        self.assertGreater(w.settle(e, 0.002)["k_settle"], 9)

    def test_never_settles(self):
        # a period that keeps drifting by 0.5 % per period never stays within 0.2 % of the final mean
        t = [0.0]
        for k in range(40):
            t.append(t[-1] + 5e-9 * (1 + 0.005 * (k % 2)))
        s = w.settle(t, 0.002)
        self.assertIsNone(s["t_settle"])

    def test_too_short(self):
        self.assertIsNone(w.settle([0, 1, 2, 3], 0.01))


class BiasModel(unittest.TestCase):
    def test_bound_dominates_exact(self):
        for s2 in (1e-3, 5e-3, 0.02, 0.05, 0.1, 0.3):
            b = w.ring_bias_bound(s2)
            ex = max(abs(w.ring_bias(s2, m / 400)) for m in range(400))
            self.assertGreaterEqual(b + 1e-12, ex, s2)
            if s2 >= 0.05:  # tight once the n >= 3 harmonics are negligible (they alternate in sign at mu = 1/4)
                self.assertAlmostEqual(b, ex, delta=2e-3)

    def test_exact_bias_matches_monte_carlo(self):
        rng = random.Random(1)
        s2, mu = 0.03, 0.31
        n = 200000
        ones = sum(int(2 * ((mu + rng.gauss(0, math.sqrt(s2))) % 1.0)) for _ in range(n))
        self.assertAlmostEqual(ones / n - 0.5, w.ring_bias(s2, mu), delta=4 * 0.5 / math.sqrt(n))

    def test_piling_up(self):
        # XOR of four independent biased bits: bias = 8 * prod(e_i) (sign: (-2)^3 prod e_i ... magnitude)
        rng = random.Random(2)
        e = [0.3, -0.2, 0.25, 0.15]
        n = 400000
        ones = 0
        for _ in range(n):
            x = 0
            for ei in e:
                x ^= int(rng.random() < 0.5 + ei)
            ones += x
        self.assertAlmostEqual(abs(ones / n - 0.5), 8 * abs(math.prod(e)), delta=4 * 0.5 / math.sqrt(n))

    def test_deterministic_and_large_spread(self):
        self.assertEqual(w.ring_bias_bound(0.0), 0.5)
        self.assertLess(w.ring_bias_bound(1.0), 1e-8)

    def test_t_mix_monotone_and_consistent(self):
        cal = {"sigma1": 3e-12, "periods_s": [5.4e-9, 5.2e-9, 5.0e-9, 4.8e-9], "delays_s": [2.6e-9] * 4}
        ts = [w.t_mix(cal, e) for e in (0.2, 2 ** -10, 2 ** -20, 2 ** -40)]
        self.assertTrue(all(a < b for a, b in zip(ts, ts[1:])))
        for e, t in zip((0.2, 2 ** -10, 2 ** -20, 2 ** -40), ts):
            self.assertLessEqual(w.xor_bias_bound(t, cal), e)
            self.assertGreater(w.xor_bias_bound(t * 0.99, cal), e)
        # mixing time scales as 1/sigma_1^2
        cal2 = dict(cal, sigma1=1.5e-12)
        self.assertAlmostEqual(w.t_mix(cal2, 2 ** -40) / ts[-1], 4.0, delta=0.05)

    def test_bound_covers_wake_stream(self):
        # the MC wake-up stream's per-index bias stays under the analytic bound (+ sampling noise)
        cal = {"sigma1": 3e-12, "periods_s": [5.4e-9, 5.2e-9, 5.0e-9, 4.8e-9], "delays_s": [2.6e-9] * 4}
        rng = random.Random(3)
        n = 2000
        streams = [w.wake_stream(cal, 20e-6, 40, rng, 10e-6) for _ in range(n)]
        _, p1 = w.agreement(streams)
        for k in range(40):
            bound = w.xor_bias_bound(10e-6 + k * 20e-6, cal)
            self.assertLessEqual(abs(p1[k] - 0.5), bound + 5 * 0.5 / math.sqrt(n), k)

    def test_stationary_arm_is_unbiased(self):
        cal = {"sigma1": 3e-12, "periods_s": [5.4e-9, 5.2e-9, 5.0e-9, 4.8e-9], "delays_s": [0.0] * 4}
        rng = random.Random(4)
        n = 4000
        streams = [w.wake_stream(cal, 20e-6, 4, rng, 10e-6, stationary=True) for _ in range(n)]
        _, p1 = w.agreement(streams)
        for p in p1:
            self.assertAlmostEqual(p, 0.5, delta=5 * 0.5 / math.sqrt(n))


class Agreement(unittest.TestCase):
    def test_identical_and_split(self):
        d, p = w.agreement([[0, 1, 1], [0, 1, 0], [0, 1, 1], [0, 1, 0]])
        self.assertEqual(d[:2], [0.0, 0.0])
        self.assertAlmostEqual(d[2], 2 * 2 * 2 / (4 * 3))
        self.assertEqual(p, [0.0, 1.0, 0.5])


class StartupTest(unittest.TestCase):
    def test_constant_source_trips(self):
        r = w.startup_test([1] * 1024)
        self.assertFalse(r["passed"])
        self.assertIsNotNone(r["first_trip_index"])

    def test_fair_source_passes(self):
        rng = random.Random(5)
        r = w.startup_test([rng.getrandbits(1) for _ in range(1024)])
        self.assertTrue(r["passed"])
        self.assertIsNone(r["first_trip_index"])


if __name__ == "__main__":
    unittest.main()
