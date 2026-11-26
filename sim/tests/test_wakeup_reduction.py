#!/usr/bin/env python3
"""Unit tests for sim/wake-up-transient/wakeup.py (issue #216). Standard library only.

    python3 sim/tests/test_wakeup_reduction.py
"""
import math
import random
import sys
import os
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from loadmod import load_module  # noqa: E402
import replay_equal  # noqa: E402
w = load_module("wakeup", REPO / "sim/wake-up-transient/wakeup.py")


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


# ------------------------------------------------- shared four-ring phase model (issue #785)
#: distinct periods and delays per ring, so a swapped ring or a dropped draw changes the bits
WAKE_CAL = {"sigma1": 3e-12, "periods_s": [5.4e-9, 5.2e-9, 5.0e-9, 4.8e-9],
            "delays_s": [1.0e-9, 2.6e-9, 0.5e-9, 4.0e-9]}
#: the issue's comparison grid: seeds x sample intervals x first sample times x stream lengths
WAKE_GRID = [(seed, ts, tau, n) for seed in range(8) for ts in (100e-9, 20e-6) for tau in (0.0, 2e-9, 10e-6)
             for n in (0, 1, 24, 1024)]


def ref_wake_stream(cal, ts, n, rng, tau, stationary=False):
    """wakeup.py's wake_stream as it stood before issue #785 (6a2681f2), minus one unused local."""
    th, adv, sd = [], [], []
    for T, d in zip(cal["periods_s"], cal["delays_s"]):
        if stationary:
            th.append(rng.random())
        else:
            dt = max(tau - d, 0.0)
            th.append(((dt / T) + rng.gauss(0.0, cal["sigma1"] * math.sqrt(dt / T) / T)) % 1.0)
        adv.append((ts / T) % 1.0)
        sd.append(cal["sigma1"] * math.sqrt(ts / T) / T)
    out = []
    gauss = rng.gauss
    for _ in range(n):
        out.append((int(2 * th[0]) ^ int(2 * th[1]) ^ int(2 * th[2]) ^ int(2 * th[3])) & 1)
        for i in range(4):
            th[i] = (th[i] + adv[i] + gauss(0.0, sd[i])) % 1.0
    return out


def ref_wake_ring_bits(cal, ts, n, rng, tau):
    """wakeup.py's wake_ring_bits as it stood before issue #785 (6a2681f2)."""
    th, adv, sd = [], [], []
    for T, d in zip(cal["periods_s"], cal["delays_s"]):
        dt = max(tau - d, 0.0)
        th.append(((dt / T) + rng.gauss(0.0, cal["sigma1"] * math.sqrt(dt / T) / T)) % 1.0)
        adv.append((ts / T) % 1.0)
        sd.append(cal["sigma1"] * math.sqrt(ts / T) / T)
    xs, rs = [], [[] for _ in range(4)]
    for _ in range(n):
        rb = [int(2 * x) for x in th]
        for i in range(4):
            rs[i].append(rb[i])
        xs.append(rb[0] ^ rb[1] ^ rb[2] ^ rb[3])
        for i in range(4):
            th[i] = (th[i] + adv[i] + rng.gauss(0.0, sd[i])) % 1.0
    return xs, rs


class SharedWakeModel(unittest.TestCase):
    """Issue #785: wake_stream and wake_ring_bits are one four-ring phase model.

    Successive wake-ups of a study share a generator, so the merged model has to draw exactly what the two
    separate ones drew -- four Gaussians for the phases, four per sample, and four more after the last sample
    of a stream -- and leave the generator in the same state."""

    def grid(self, fn, **opt):
        """(case, fn's result, fn's final generator state) over WAKE_GRID, each from a fresh Random(seed)."""
        for case in WAKE_GRID:
            seed, ts, tau, n = case
            rng = random.Random(seed)
            yield case, fn(WAKE_CAL, ts, n, rng, tau, **opt), rng.getstate()

    def assert_matches_reference(self, fn, ref, **opt):
        for (case, got, st), (_, want, ref_st) in zip(self.grid(fn, **opt), self.grid(ref, **opt)):
            self.assertEqual(got, want, (opt, case))
            self.assertEqual(st, ref_st, (opt, case))

    def test_wake_stream_matches_the_reference_in_both_modes(self):
        for stationary in (False, True):
            self.assert_matches_reference(w.wake_stream, ref_wake_stream, stationary=stationary)

    def test_wake_ring_bits_matches_the_reference(self):
        self.assert_matches_reference(w.wake_ring_bits, ref_wake_ring_bits)

    def test_stationary_ring_bits_are_wake_stream_bits(self):
        # no per-ring reference exists for the stationary start: the bits and the final state are wake_stream's
        self.assert_matches_reference(lambda *a, **k: w.wake_ring_bits(*a, **k)[0], ref_wake_stream,
                                      stationary=True)

    def test_xor_bit_is_the_parity_of_the_ring_bits(self):
        for stationary in (False, True):
            for case, (xs, rs), _ in self.grid(w.wake_ring_bits, stationary=stationary):
                self.assertEqual(([a ^ b ^ c ^ d for a, b, c, d in zip(*rs)], [len(r) for r in rs]),
                                 (xs, [case[3]] * 4), (stationary,) + case)

    def test_draw_count_includes_the_last_advance(self):
        # four Gaussian draws start the phases (also where tau - d <= 0 makes their sigma 0), each sample draws
        # four more, and so does the advance after the last sample: n samples cost 4 (n + 1) draws
        for tau in (0.0, 10e-6):
            for n in (0, 1, 24, 1024):
                rng, ref = random.Random(11), random.Random(11)
                w.wake_stream(WAKE_CAL, 20e-6, n, rng, tau)
                for _ in range(4 * (n + 1)):
                    ref.gauss(0.0, 1.0)
                self.assertEqual(rng.getstate(), ref.getstate(), (tau, n))
                # the stationary start replaces the four phase draws with four uniform ones
                rng, ref = random.Random(11), random.Random(11)
                w.wake_stream(WAKE_CAL, 20e-6, n, rng, tau, stationary=True)
                for _ in range(4):
                    ref.random()
                for _ in range(4 * n):
                    ref.gauss(0.0, 1.0)
                self.assertEqual(rng.getstate(), ref.getstate(), (tau, n))

    def test_both_callers_run_the_shared_core(self):
        from unittest import mock
        core = getattr(w, "_wake_core", None)
        self.assertIsNotNone(core, "wake_stream and wake_ring_bits must run one shared phase model")
        rng = random.Random(5)
        with mock.patch.object(w, "_wake_core", wraps=core) as spy:
            w.wake_stream(WAKE_CAL, 20e-6, 3, rng, 10e-6, stationary=True)
            w.wake_ring_bits(WAKE_CAL, 20e-6, 3, rng, 10e-6)
        self.assertEqual([(c.args, c.kwargs) for c in spy.call_args_list],
                         [((WAKE_CAL, 20e-6, 3, rng, 10e-6), {"stationary": True, "rings": False}),
                          ((WAKE_CAL, 20e-6, 3, rng, 10e-6), {"stationary": False, "rings": True})])

    def test_ring_histories_are_collected_only_on_request(self):
        rng, ref = random.Random(5), random.Random(5)
        xs, rs = w._wake_core(WAKE_CAL, 20e-6, 4, rng, 10e-6)
        self.assertIsNone(rs)
        xs2, rs2 = w._wake_core(WAKE_CAL, 20e-6, 4, ref, 10e-6, rings=True)
        self.assertEqual((xs, rng.getstate()), (xs2, ref.getstate()))
        self.assertEqual([len(r) for r in rs2], [4] * 4)

    def test_ring_bit_is_a_bit_when_a_phase_wraps_to_exactly_one(self):
        # x - nextafter(x) is a hair below zero for x < 0.5, and `% 1.0` of that is exactly 1.0, i.e. phase zero:
        # its ring bit is 0, where an unmasked int(2 * phase) would make it 2
        tau = 2e-9
        x = (tau - WAKE_CAL["delays_s"][0]) / WAKE_CAL["periods_s"][0]
        self.assertEqual((x - math.nextafter(x, math.inf)) % 1.0, 1.0)

        class Scripted:
            """A real generator whose first Gaussian is prescribed."""
            def __init__(self, first):
                self.inner, self.first, self.drawn = random.Random(9), first, 0

            def gauss(self, mu, sigma):
                self.drawn += 1
                return self.first if self.drawn == 1 else self.inner.gauss(mu, sigma)

            def random(self):
                return self.inner.random()

        xs, rs = w._wake_core(WAKE_CAL, 20e-6, 8, Scripted(-math.nextafter(x, math.inf)), tau, rings=True)
        self.assertEqual(rs[0][0], 0)
        self.assertEqual(xs, [a ^ b ^ c ^ d for a, b, c, d in zip(*rs)])
        self.assertTrue({b for r in rs for b in r} <= {0, 1})


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


class BatchSharding(unittest.TestCase):
    """Every generated request must stay under the fleet's whole-job ceiling (issue #216)."""

    @classmethod
    def setUpClass(cls):
        import json
        import subprocess
        import tempfile
        cls.reqs = {}
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, "-I", str(REPO / "sim/wake-up-transient/make-requests.py"), d],
                           check=True, capture_output=True)
            for name in os.listdir(d):
                cls.reqs[name] = json.load(open(os.path.join(d, name, "request.json")))

    def test_job_bound_under_ceiling(self):
        self.assertTrue(self.reqs)
        for name, r in self.reqs.items():
            b = r["batch"]
            # klt sim_batch bound = per-job overhead (120 s) + units x per-unit timeout
            self.assertLessEqual(120 + b["max_units_per_job"] * r["options"]["timeout_s"], 3600, name)
            self.assertLessEqual(b["max_concurrent_jobs"], 4, name)


class JobIds(unittest.TestCase):
    def test_sharded_fleet_and_single_job(self):
        sharded = ("a", {}, {"environment": {"remote": {"fleet": [{"job_id": "j1"}, {"job_id": "j2"}]}}})
        single = ("b", {}, {"environment": {"remote": {"job_id": "j3"}}})
        self.assertEqual(w._jobs([sharded, single]), ["j1", "j2", "j3"])


class ReplayTolerance(unittest.TestCase):
    """Issue #659: `--check` replays the det/noisy/margin legs through
    sim/bin/replay_equal.py.

    `det_ring`'s reference window and `window_mean` are float `sum()`s;
    builtin `sum()` is naive on CPython <= 3.11 and compensated on >= 3.12,
    so the noisy-leg records minted on 3.12 failed their own replay under
    3.11 semantics (xcheck and summary float leaves) before this."""

    #: Ring periods (s) sized like `det_ring`'s reference-window sums so the
    #: naive and compensated reductions of the same list differ.
    P = [2.4737964627091892e-09, 2.5044229225295953e-09, 2.486995516654808e-09,
         2.5103920038596196e-09, 2.5125720304108055e-09, 2.4565528859239815e-09,
         2.4513167991554875e-09, 2.533746908209646e-09, 2.4759354014328007e-09,
         2.4734330961046696e-09]

    def test_uses_the_shared_rule(self):
        self.assertIs(w._replay_equal, replay_equal.replay_equal)

    def test_replay_gate_absorbs_the_cpython_sum_split_and_still_bites(self):
        s_naive = 0.0
        for x in self.P:
            s_naive += x
        s_fsum = math.fsum(self.P)
        self.assertNotEqual(s_naive, s_fsum)
        self.assertTrue(w._replay_equal(s_naive, s_fsum))
        self.assertFalse(w._replay_equal(s_fsum, s_fsum * (1 + 1e-6)))
        self.assertTrue(w._replay_equal(s_fsum, s_fsum * (1 + 1e-12)))

    def test_zero_versus_tiny_is_a_difference_no_absolute_floor(self):
        self.assertFalse(w._replay_equal(0.0, 5e-324))
        self.assertFalse(w._replay_equal(0.0, 1e-20))
        self.assertFalse(w._replay_equal(1e-20, 0.0))
        self.assertTrue(w._replay_equal(0.0, -0.0))


if __name__ == "__main__":
    unittest.main()
