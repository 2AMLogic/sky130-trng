#!/usr/bin/env python3
"""Fast checks for sim/raw-bit-volume-campaign/behavioral_raw_bit.py (stdlib only).

    python3 sim/tests/test_raw_bit_volume_model.py
"""
from __future__ import annotations

import importlib.util
import random
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "behavioral_raw_bit", REPO_ROOT / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

PER = [2.88e-9, 2.72e-9, 2.57e-9, 2.43e-9]


class ModelTests(unittest.TestCase):
    def test_hex_roundtrip(self):
        bits = [random.Random(1).randint(0, 1) for _ in range(64)]
        self.assertEqual(m.unpack_hex(m.pack_hex(bits)), bits)

    def test_deterministic_given_seed(self):
        a = m.stream(PER, 3e-12, 20e-6, 512, random.Random(5))
        b = m.stream(PER, 3e-12, 20e-6, 512, random.Random(5))
        self.assertEqual(a, b)

    def test_noise_free_is_deterministic_and_seed_independent(self):
        a = m.stream(PER, 0.0, 100e-9, 64, random.Random(1))
        b = m.stream(PER, 0.0, 100e-9, 64, random.Random(2))
        self.assertEqual(a, b)

    def test_large_jitter_is_unbiased(self):
        bits = m.stream(PER, 3e-12, 20e-6, 20000, random.Random(3))
        self.assertLess(abs(sum(bits) / len(bits) - 0.5), 0.02)

    def test_jitter_estimator_ratio_near_sqrt_k(self):
        rng = random.Random(9)
        r = [m.jitter_estimator(rng, 3e-12)[4] / m.jitter_estimator(rng, 3e-12)[1] for _ in range(400)]
        self.assertTrue(0.5 < sorted(r)[200] < 4.0)

    def test_calibration_inputs_present(self):
        for corner in m.CORNERS:
            for t, v in m.PVT_POINTS:
                cal = m.calibration(t, v, corner)
                self.assertEqual(len(cal["periods_s"]), 4)
                self.assertGreater(cal["sigma"][1], 0)


if __name__ == "__main__":
    unittest.main()
