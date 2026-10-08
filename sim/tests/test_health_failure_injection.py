#!/usr/bin/env python3
"""Unit tests for the health-test failure injector (issue #196).

Runs with the standard library only, no simulator and no PDK::

    python3 sim/tests/test_health_failure_injection.py

Exercises ``inject`` / ``detection_latency`` from
``sim/digital-health-test-parameters/analysis/health-test-replay.py`` against
the behavioural model in ``digital/model/health.py``. Standalone script in
the style of ``test_digital_section.py``.
"""

from __future__ import annotations

import importlib.util
import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "digital"))

from model import params  # noqa: E402
from model.health import HealthMonitor  # noqa: E402

_PATH = (REPO_ROOT / "sim" / "digital-health-test-parameters" / "analysis"
         / "health-test-replay.py")
_spec = importlib.util.spec_from_file_location("health_test_replay", _PATH)
R = importlib.util.module_from_spec(_spec)
sys.modules["health_test_replay"] = R
_spec.loader.exec_module(R)


def healthy(n: int, seed: int = 1234) -> list[int]:
    rng = random.Random(seed)
    return [rng.getrandbits(1) for _ in range(n)]


def healthy_ending_in(n: int, last: int, seed: int = 1234) -> list[int]:
    """Healthy data whose sample just before index ``n`` differs from ``last``."""
    b = healthy(n + 4096, seed)
    b[n - 1] = 1 - last
    return b


class TestInjector(unittest.TestCase):
    def test_deterministic_for_fixed_seed(self):
        base = healthy(8192)
        for kw in ({"kind": "stuck", "value": 1},
                   {"kind": "toggle", "pattern": (0, 0, 1)},
                   {"kind": "bias", "p0": 0.5, "p1": 0.9, "ramp_len": 500},
                   {"kind": "bias", "p1": 0.8}):
            a, ia = R.inject(base, 1000, length=3000, seed=7, **kw)
            b, ib = R.inject(base, 1000, length=3000, seed=7, **kw)
            self.assertEqual(a, b)
            self.assertEqual(ia, ib)
        c, _ = R.inject(base, 1000, "bias", 3000, seed=8, p1=0.8)
        d, _ = R.inject(base, 1000, "bias", 3000, seed=7, p1=0.8)
        self.assertNotEqual(c, d)

    def test_length_and_splice_positions(self):
        base = healthy(8192)
        orig = list(base)
        out, info = R.inject(base, 1500, "stuck", 700, seed=1, value=0)
        self.assertEqual(base, orig)                  # input not mutated
        self.assertEqual(len(out), len(base))
        self.assertEqual(out[:1500], base[:1500])     # prefix untouched
        self.assertEqual(out[2200:], base[2200:])     # suffix untouched
        self.assertEqual(out[1500:2200], [0] * 700)
        self.assertEqual((info["onset"], info["end"], info["length"]),
                         (1500, 2200, 700))

    def test_splice_clamps_at_stream_end(self):
        out, info = R.inject(healthy(1000), 900, "stuck", 500, seed=1, value=1)
        self.assertEqual(len(out), 1000)
        self.assertEqual(info["length"], 100)
        self.assertEqual(out[900:], [1] * 100)

    def test_toggle_pattern(self):
        out, _ = R.inject(healthy(200), 10, "toggle", 12, seed=1,
                          pattern=(0, 0, 1))
        self.assertEqual(out[10:22], [0, 0, 1] * 4)

    def test_bias_statistics(self):
        base = [0] * 40000
        out, _ = R.inject(base, 0, "bias", 40000, seed=3, p1=0.8)
        self.assertAlmostEqual(sum(out) / 40000, 0.8, delta=0.01)
        ramp, _ = R.inject(base, 0, "bias", 40000, seed=3, p0=0.5, p1=0.9,
                           ramp_len=20000)
        first, second = sum(ramp[:10000]) / 10000, sum(ramp[30000:]) / 10000
        self.assertLess(first, 0.7)                   # still ramping
        self.assertAlmostEqual(second, 0.9, delta=0.02)  # held at p1

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            R.inject(healthy(100), 10, "nonsense", 5, seed=1)
        with self.assertRaises(ValueError):
            R.inject(healthy(100), 200, "stuck", 5, seed=1)
        with self.assertRaises(ValueError):
            R.inject(healthy(100), 10, "stuck", 5, seed=1, value=2)


class TestDetection(unittest.TestCase):
    def test_stuck_run_trips_rct_at_exactly_c_rct(self):
        onset = 3000
        for value in (0, 1):
            base = healthy_ending_in(onset, value)
            out, _ = R.inject(base, onset, "stuck", 4096, seed=1, value=value)
            d = R.detection_latency(out, onset, 4096)
            self.assertEqual(d["rct"], params.C_RCT)
            self.assertEqual(d["pre_onset_trips"], {"rct": 0, "apt": 0})

    def test_constant_stream_trips_apt_at_first_window_end(self):
        d = R.detection_latency([1] * 4096, 0, 4096)
        self.assertEqual(d["apt"], params.W_APT)
        self.assertEqual(d["rct"], params.C_RCT)

    def test_apt_latency_quantised_to_window_end(self):
        onset = 1500    # mid-window; the first full-stuck window ends at 3072
        base = healthy_ending_in(onset, 0)
        out, _ = R.inject(base, onset, "stuck", 4096, seed=1, value=0)
        d = R.detection_latency(out, onset, 4096)
        # window [1024, 2048) is half healthy/half stuck -> may or may not
        # trip; the window ending at 3072 is fully stuck -> certainly trips.
        self.assertIsNotNone(d["apt"])
        self.assertLessEqual(d["apt"], 3072 - onset)
        self.assertEqual((onset + d["apt"]) % params.W_APT, 0)

    def test_healthy_prng_data_raises_no_alarms(self):
        bits = healthy(131072)
        self.assertEqual(R.count_trips(bits, params.C_RCT, params.C_APT),
                         (0, 0))
        mon = R.monitor_replay(bits)
        self.assertEqual(mon["raised"], 0)
        self.assertFalse(mon["alarm_rct"] or mon["alarm_apt"]
                         or mon["alarm_startup"])

    def test_clean_toggling_does_not_trip_rct(self):
        out, _ = R.inject(healthy(20000), 2000, "toggle", 16384, seed=1)
        d = R.detection_latency(out, 2000, 16384)
        self.assertIsNone(d["rct"])
        self.assertIsNone(d["apt"])   # a 50/50 toggle is invisible to APT too

    def test_non_detection_is_reported_as_none(self):
        out, _ = R.inject(healthy(20000), 2000, "bias", 16384, seed=5, p1=0.7)
        d = R.detection_latency(out, 2000, 16384)
        self.assertIsNone(d["rct"])
        self.assertIsNone(d["apt"])   # p = 0.7 stays below 824/1024

    def test_monitor_agrees_with_individual_tests_on_stuck(self):
        onset = 3000
        out, _ = R.inject(healthy_ending_in(onset, 0), onset, "stuck", 2000,
                          seed=1, value=0)
        mon = HealthMonitor()
        first = None
        for i, b in enumerate(out):
            if mon.update(b) and first is None:
                first = i - onset + 1
        self.assertEqual(first, params.C_RCT)
        self.assertTrue(mon.alarm_rct)


if __name__ == "__main__":
    unittest.main()
