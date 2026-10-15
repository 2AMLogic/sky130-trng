#!/usr/bin/env python3
"""Unit tests for `sim/digital-section-behavioral/harness/health-detection-coverage.py`.

Standard library only, no simulator::

    python3 sim/tests/test_health_detection_coverage.py

Checks the analytic min-entropy formulas and the headline detection facts on
small synthetic streams (experiment I's building blocks), and the DR-0015
study lag-count monitor (``digital/model/lagcount.py``, experiment J, #301):
cutoff derivation, the sequential-vs-batch model, window/cutoff edge cases,
and (when Icarus is installed) RTL-vs-model agreement of the synthesis
prototype.
"""

from __future__ import annotations

import importlib.util
import itertools
import math
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = REPO_ROOT / "sim" / "digital-section-behavioral" / "harness" / "health-detection-coverage.py"
_spec = importlib.util.spec_from_file_location("health_detection_coverage", _PATH)
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

from model import lagcount as LC  # noqa: E402  (H put digital/ on sys.path)
from model.params import C_APT  # noqa: E402


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


def _balanced_low_autocorr_pattern(k, max_rate):
    """A balanced length-k pattern whose cyclic lag-1..k-1 self-match rate stays <= max_rate."""
    for ones in itertools.combinations(range(k), k // 2):
        pat = [1 if i in ones else 0 for i in range(k)]
        if all(sum(pat[i] == pat[(i + j) % k] for i in range(k)) / k <= max_rate
               for j in range(1, k)):
            return pat
    raise AssertionError("no low-autocorrelation pattern")


class LagCountCutoff(unittest.TestCase):
    def test_binomial_routine_reproduces_c_apt(self):
        # same method as DR-0004 s2: p = 2**-H, alpha = 2**-40, W = 1024
        c = LC.binomial_cutoff(1024, Decimal(2) ** Decimal("-0.5"), Decimal(2) ** -40)
        self.assertEqual(c, C_APT)

    def test_match_probability_at_floor(self):
        p = 2 ** -0.5
        self.assertAlmostEqual(float(LC.match_probability(0.5)), p * p + (1 - p) ** 2, places=12)
        self.assertAlmostEqual(float(LC.match_probability(1.0)), 0.5, places=12)

    def test_exact_dp_matches_enumeration(self):
        def brute(w, j, p1):
            dist = {}
            for bits in itertools.product((0, 1), repeat=w + j):
                pr = 1.0
                for b in bits:
                    pr *= p1 if b else 1 - p1
                m = sum(bits[i] == bits[i - j] for i in range(j, w + j))
                dist[m] = dist.get(m, 0.0) + pr
            return dist
        for w, j, p1 in ((8, 1, 2 ** -0.5), (9, 3, 2 ** -0.5), (10, 2, 0.6)):
            d = brute(w, j, p1)
            off, pmf = LC.match_count_pmf(w, j, p1)
            for k in range(w + 1):
                got = pmf[k - off] if 0 <= k - off < len(pmf) else 0.0
                self.assertAlmostEqual(got, d.get(k, 0.0), places=12)

    def test_fair_coin_is_exactly_binomial(self):
        off, pmf = LC.match_count_pmf(64, 1, 0.5)
        for k in range(off, off + len(pmf)):
            self.assertAlmostEqual(pmf[k - off], math.comb(64, k) / 2 ** 64, places=15)

    def test_binomial_cutoff_undercovers_a_biased_source_exact_does_not(self):
        p1 = 2 ** -H_DESIGN_VALUE
        for lags, w in ((8, 1024), (32, 1024)):
            target = 2.0 ** -40 / lags
            cb = LC.c_lag_binomial(lags, w)
            ce = LC.c_lag(lags, w)
            self.assertGreater(ce, cb)
            self.assertGreater(LC.exact_tail(w, 1, p1, cb), 100 * target)
            self.assertLessEqual(LC.exact_tail(w, 1, p1, ce), target)
            self.assertGreater(LC.exact_tail(w, 1, p1, ce - 1), target)

    def test_lag_one_is_the_heaviest_tail(self):
        w, lags = 256, 16
        c = LC.c_lag(lags, w)
        tails = [LC.exact_tail(w, j, 2 ** -H_DESIGN_VALUE, c) for j in (1, 2, 3, 4, 8, 16, 32)]
        self.assertEqual(tails, sorted(tails, reverse=True))
        self.assertLessEqual(tails[0], 2.0 ** -40 / lags)

    def test_cutoff_grows_with_lag_bank_and_shrinks_in_rate_with_window(self):
        self.assertLessEqual(LC.c_lag(8, 1024), LC.c_lag(256, 1024))
        self.assertGreater(LC.c_lag(32, 1024) / 1024, LC.c_lag(32, 4096) / 4096)


H_DESIGN_VALUE = 0.5


class LagCountMonitorBehaviour(unittest.TestCase):
    def test_period_k_stream_alarms_for_k_le_L_with_floor_latency(self):
        for lags in (4, 8):
            w = 256
            for k in range(2, lags + 1):
                pat = _balanced_low_autocorr_pattern(k, 1.0) if k > 2 else [0, 1]
                bits = [pat[i % k] for i in range(4 * w)]
                m = LC.LagCountMonitor(lags, w)
                first = next((i + 1 for i, b in enumerate(bits) if m.update(b)), None)
                self.assertEqual(first, lags + w, (lags, k))
                self.assertTrue(m.failed_lags >> (k - 1) & 1)

    def test_period_L_plus_1_with_flat_spectrum_is_missed(self):
        lags, w = 4, 256
        cut = LC.c_lag(lags, w)
        pat = _balanced_low_autocorr_pattern(lags + 1, (cut - 1) / w)
        bits = [pat[i % (lags + 1)] for i in range(8 * w)]
        self.assertEqual(LC.scan(bits, lags, w), [])
        # ... and the same pattern at period exactly L is caught
        pat4 = [1, 1, 0, 0]
        self.assertTrue(LC.scan([pat4[i % 4] for i in range(8 * w)], lags, w))

    def test_iid_streams_do_not_alarm(self):
        rng = random.Random(11)
        for lags, w in ((8, 256), (16, 1024)):
            fair = [rng.getrandbits(1) for _ in range(40 * w)]
            biased = [1 if rng.random() < 2 ** -0.5 else 0 for _ in range(40 * w)]
            self.assertEqual(LC.scan(fair, lags, w), [])
            self.assertEqual(LC.scan(biased, lags, w), [])

    def test_sticky_markov_alarms_at_lag_one(self):
        bits = H.gen_markov(random.Random(2), 3000, 0.85, 0.85)
        first, mask = LC.first_alarm(bits, 4, 256)
        self.assertEqual(first, 4 + 256)
        self.assertTrue(mask & 1)

    def test_batch_scan_equals_sequential_model(self):
        rng = random.Random(5)
        for lags, w, cutoff in ((5, 100, 70), (8, 64, 45), (3, 33, 25)):
            for kind in range(4):
                if kind == 0:
                    bits = [rng.getrandbits(1) for _ in range(900)]
                elif kind == 1:
                    bits = [(i % 3 == 0) * 1 for i in range(900)]
                elif kind == 2:
                    bits = H.gen_lockmix(rng, 900, 150, 0.6, 0.05)
                else:
                    bits = H.gen_markov(rng, 900, 0.8, 0.8)
                m = LC.LagCountMonitor(lags, w, cutoff)
                seq = [i + 1 for i, b in enumerate(bits) if m.update(b)]
                batch = LC.scan(bits, lags, w, cutoff)
                self.assertEqual(seq, [i for i, _ in batch])
                union = 0
                for _, mask in batch:
                    union |= mask
                self.assertEqual(m.failed_lags, union)

    def test_cutoff_edge_is_inclusive_and_window_restarts(self):
        # alternating stream: lag-2 matches everywhere; flip isolated bits to remove 2 matches each
        lags, w = 2, 256
        c = LC.c_lag(lags, w)
        flips = (w - c) // 2          # lag-2 count = w - 2*flips in {c, c+1}  -> alarms
        def stream(n_flips):
            bits = [i & 1 for i in range(lags + w)]
            for t in range(n_flips):
                bits[lags + 3 + 7 * t] ^= 1
            return bits
        hit = LC.scan(stream(flips), lags, w)
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0][0], lags + w)
        miss = LC.scan(stream(flips + 1), lags, w)   # count = w - 2*(flips+1) < c
        self.assertEqual(miss, [])
        # a second full-lock window after a clean one alarms at the second boundary, not earlier
        clean = [rr for rr in H.gen_markov(random.Random(9), lags + w, 0.5, 0.5)]
        locked = [(len(clean) + i) & 1 for i in range(w)]
        hit2 = LC.scan(clean + locked, lags, w)
        self.assertEqual([i for i, _ in hit2][-1], lags + 2 * w)

    def test_lock_mixture_alarm_threshold_tracks_locked_fraction(self):
        lags, w = 4, 1024
        cut = LC.c_lag(lags, w)
        # expected lag-2 rate = f + (1-f)/2 ; alarm needs it above cut/w (~0.715)  ->  f > ~0.43
        rng = random.Random(3)
        lo = H.gen_lockmix(rng, 40 * w, 1024, 0.25, 0.0)
        hi = H.gen_lockmix(rng, 40 * w, 1024, 0.75, 0.0)
        self.assertGreater(cut / w, 0.25 + 0.75 / 2)
        self.assertEqual(LC.scan(lo, lags, w), [])
        self.assertTrue(LC.scan(hi, lags, w))


@unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"),
                     "iverilog/vvp not installed: RTL-vs-model check NOT run")
class PrototypeRtlMatchesModel(unittest.TestCase):
    PROTO = REPO_ROOT / "sim" / "digital-synthesis" / "prototypes"

    def test_first_alarm_sample_matches_model(self):
        lags, win_bits, cutoff, nbits = 8, 6, 40, 1024
        w = 1 << win_bits
        rng = random.Random(21)
        streams = {
            "fair": [rng.getrandbits(1) for _ in range(nbits)],
            "period3": [(i % 3 == 0) * 1 for i in range(nbits)],
            "period8": [(i % 8 in (0, 1, 4, 6)) * 1 for i in range(nbits)],
            "markov": H.gen_markov(rng, nbits, 0.9, 0.9),
            "late-lock": [rng.getrandbits(1) for _ in range(300)]
                         + [i & 1 for i in range(nbits - 300)],
        }
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / "tb"
            subprocess.run(
                ["iverilog", "-g2012", "-o", str(exe),
                 f"-Ptb_lagcount_monitor.LAGS={lags}", f"-Ptb_lagcount_monitor.WIN_BITS={win_bits}",
                 f"-Ptb_lagcount_monitor.CUTOFF={cutoff}", f"-Ptb_lagcount_monitor.NBITS={nbits}",
                 str(self.PROTO / "lagcount_monitor.v"), str(self.PROTO / "tb_lagcount_monitor.v")],
                check=True, capture_output=True)
            for name, bits in streams.items():
                stim = Path(td) / f"{name}.txt"
                stim.write_text("\n".join(map(str, bits)) + "\n")
                out = subprocess.run(["vvp", str(exe), f"+STIM={stim}"], check=True,
                                     capture_output=True, text=True).stdout
                rtl = int(next(l for l in out.splitlines() if l.startswith("FIRST_ALARM")).split()[1])
                model, _ = LC.first_alarm(bits, lags, w, cutoff)
                self.assertEqual(rtl, model or 0, name)


class Experiment_J_Streams(unittest.TestCase):
    def test_streams_generator_is_seeded_and_sweep_is_built_on_it(self):
        a = [(l, f, h, sum(b)) for l, f, _, h, b in H.streams(7, 512)]
        b = [(l, f, h, sum(b)) for l, f, _, h, b in H.streams(7, 512)]
        self.assertEqual(a, b)
        self.assertEqual(len(a), 75)
        self.assertEqual(a[0][0], "control fair")


if __name__ == "__main__":
    unittest.main()
