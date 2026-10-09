#!/usr/bin/env python3
"""Unit tests for sim/ro-array-supply-perturbation/ripple.py (issue #200).

Synthetic edge trains only -- no simulator, no PDK. The point is that the lock
detector is shown to FIRE on data that is locked by construction and to stay
quiet on data that is not, independent of any SPICE run.

    python3 sim/tests/test_ripple_reduction.py
"""
import importlib.util
import math
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_p = os.path.join(HERE, "..", "ro-array-supply-perturbation", "ripple.py")
_s = importlib.util.spec_from_file_location("ripple", _p)
rp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(rp)


def train(T, n=rp.NEDGE, t0=9e-9, mod=0.0, fmod=None):
    out = []
    for k in range(n):
        t = t0 + k * T
        if mod and fmod:
            t += mod * T / (2 * math.pi * fmod * T) * math.sin(2 * math.pi * fmod * (t0 + k * T))
        out.append(t)
    return out


class Tests(unittest.TestCase):
    def test_period_and_modulation(self):
        e = rp.analyze_edges(train(5e-9))
        self.assertAlmostEqual(e["T"], 5e-9, 15)
        self.assertLess(e["mod_pk"], 1e-9)
        P = [5e-9 * (1 + 0.01 * (-1) ** k) for k in range(39)]
        t = [0.0]
        for p in P:
            t.append(t[-1] + p)
        self.assertAlmostEqual(rp.analyze_edges(t)["mod_pk"], 0.01, 4)

    def test_tone_lock_fires_on_locked_train(self):
        T = 5e-9
        f = 1 / T                                  # tone exactly at the ring frequency
        p, q, d = rp.tone_lock(train(T), f)
        self.assertEqual((p, q), (1, 1))
        self.assertLess(abs(d), 1e-6)

    def test_tone_lock_2_to_1_subharmonic(self):
        T = 5e-9
        p, q, d = rp.tone_lock(train(T), 1 / (2 * T))     # tone at half the ring frequency
        self.assertEqual((p, q), (2, 1))
        self.assertLess(abs(d), 1e-6)

    def test_tone_lock_quiet_when_free_running(self):
        T = 5e-9
        f = 1.05 / T                               # 5% off: ~2 cycles slip over 39 edges
        p, q, d = rp.tone_lock(train(T), f)
        self.assertGreater(abs(d), rp.DRIFT_LOCK * 5)

    def test_pair_lock(self):
        a = train(5e-9, t0=9e-9)
        b = train(5e-9, t0=11e-9)                  # same frequency: 1:1 locked pair
        p, q, d = rp.pair_lock(a, b)
        self.assertEqual((p, q), (1, 1))
        self.assertLess(abs(d), 1e-6)
        c = train(5.2e-9, t0=9e-9)                 # 4% apart: slips ~1.5 cycles
        self.assertGreater(abs(rp.pair_lock(a, c)[2]), 1.0)

    def test_closeness(self):
        d, p, q = rp.closeness(5e-9, 3.75e-9, rp.DR5_RATIOS)     # 4/3 exactly
        self.assertAlmostEqual(d, 0.0, 12)
        self.assertEqual((p, q), (4, 3))

    def _metrics(self, edges, clean, f_rip=None, xo=0.8, vnom=1.62, dv=0.0):
        return rp.row_metrics(edges, clean, vnom, dv, xo, f_rip)

    def test_row_flags_locked_ring_and_passes_clean(self):
        clean = [train(5.4e-9), train(5.2e-9), train(5.0e-9), train(4.8e-9)]
        m = self._metrics(clean, clean, f_rip=1 / 7.7e-9, xo=0.5 * 1.62)
        ok, why = rp.row_verdict(m)
        self.assertTrue(ok, why)
        locked = [train(5.2e-9)] + clean[1:]       # ring 1 dragged to ring 2's period, tone there too
        m = self._metrics(locked, clean, f_rip=1 / 5.2e-9, xo=0.5 * 1.62)
        ok, why = rp.row_verdict(m)
        self.assertFalse(ok)
        self.assertTrue(any("LOCK" in w for w in why), why)
        self.assertEqual(m["tone"][0]["state"], "LOCKED")

    def test_coincident_is_reported_not_hidden(self):
        clean = [train(5.0e-9)] * 4
        m = self._metrics(clean, clean, f_rip=1 / 5.0e-9, xo=0.8)
        self.assertEqual(m["tone"][0]["state"], "COINCIDENT")
        self.assertTrue(rp.row_verdict(m)[0])      # unresolved, not failed (flagged separately)

    def test_q_and_bias_criteria(self):
        clean = [train(5e-9)] * 4
        slow = [train(5e-9 * 1.02)] * 4            # +2% period -> Q ratio 0.942 < 0.965
        m = self._metrics(slow, clean, xo=0.8)
        self.assertLess(m["Q_ratio"], 1 / rp.Q_MARGIN)
        self.assertTrue(any(w.startswith("Q:") for w in rp.row_verdict(m)[1]))
        m = self._metrics(clean, clean, xo=0.2 * 1.62)       # bias 0.2 outside the band
        self.assertTrue(any(w.startswith("BIAS:") for w in rp.row_verdict(m)[1]))

    def test_tolerance_statement(self):
        rows = [{"amp": 0.01, "ok": True}, {"amp": 0.05, "ok": True}]
        self.assertIn(">= 50 mV", rp.tolerance(rows))
        rows = [{"amp": 0.01, "ok": True}, {"amp": 0.05, "ok": False}]
        self.assertIn(">= 10 mV pk, < 50 mV", rp.tolerance(rows))
        rows = [{"amp": 0.01, "ok": False}, {"amp": 0.05, "ok": False}]
        self.assertEqual(rp.tolerance(rows), "no tolerance found at 10 mV")
        rows = [{"amp": 0.01, "ok": True}, {"amp": 0.05, "ok": True}, {"amp": 0.05, "ok": False}]
        self.assertIn("< 50", rp.tolerance(rows))


if __name__ == "__main__":
    unittest.main()
