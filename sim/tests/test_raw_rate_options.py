#!/usr/bin/env python3
"""Unit tests for sim/raw-rate-row-options/ (issue #600).

No simulator and no PDK: synthetic measurements, the COMMITTED baseline
records, and this campaign's own committed corners bundle only.

    python3 sim/tests/test_raw_rate_options.py
"""
import json
import math
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "raw-rate-row-options")
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
from loadmod import load_module  # noqa: E402

MR = load_module("rrro_mr", os.path.join(D, "make-requests.py"))
RD = load_module("rrro_rd", os.path.join(D, "reduce.py"))


def perfect_clock(t0, n=21, t_start=20e-9):
    return [t_start + i * t0 for i in range(n)]


class Estimator(unittest.TestCase):
    def test_perfect_clock_gives_zero_sigma_and_exact_tbar(self):
        est = RD.estimator(perfect_clock(2.4e-9))
        self.assertAlmostEqual(est["tbar"], 2.4e-9, 20)
        for n in (1, 2, 4, 8):
            # exactly zero to double-precision cancellation (~1e-24 s on 20 ns)
            self.assertLess(est[f"sigma_{n}"], 1e-22)

    def test_quadratic_drift_matches_closed_form(self):
        # tc[i] = i*T + c*i^2 (in seconds, i = 0..20 measured from 20 ns):
        # r_n[i] = c*(2*i*n + n^2 - 20n) exactly as in the committed .control
        T, c, t0 = 2.0e-9, 1.0e-18, 20e-9
        tc = [t0 + i * T + c * i * i for i in range(21)]
        est = RD.estimator(tc)
        for n in (1, 2, 4, 8):
            r = [c * (2 * i * n + n * n - 20 * n) for i in range(21 - n)]
            want = math.sqrt(sum(x * x for x in r) / len(r) / (1 - n / 20))
            self.assertAlmostEqual(est[f"sigma_{n}"], want,
                                   delta=abs(want) * 1e-7 + 1e-24)

    def test_non_monotone_crossings_fail_closed(self):
        with self.assertRaises(RD.ReductionError):
            RD.estimator(list(reversed(perfect_clock(2.4e-9))))

    def test_wrong_count_fails_closed(self):
        with self.assertRaises(RD.ReductionError):
            RD.estimator(perfect_clock(2.4e-9)[:-1])


class QuadCorrect(unittest.TestCase):
    def test_committed_ss_value_reproduces(self):
        # committed record 20260825-060208 ss row: raw 3.6062e-12 -> corrected 3.5479e-12
        self.assertAlmostEqual(RD.quad_correct(3.6062e-12), 3.5479e-12, delta=2e-16)

    def test_inside_floor_fails_closed(self):
        with self.assertRaises(RD.ReductionError):
            RD.quad_correct(0.1e-12)


class ScDerive(unittest.TestCase):
    def test_committed_example(self):
        # committed 20260825-085537 tt/-40C/1.98V row shape
        raw = {"tc3": 20e-9, "tc11": 20e-9 + 8 * 1.945e-9, "tc4": 21.9e-9,
               "tfall3": 20.9e-9,
               "vmax_ring": 1.65, "vmin_ring": 0.0, "vmax_buf": 2.0, "vmin_buf": 0.0,
               "iddr_run": -16.8e-6, "iddr_stop": -1e-9, "ibuf": -2.3e-6}
        d = RD.sc_derive(raw, 1.98)
        self.assertAlmostEqual(d["t0_loaded_s"], 1.945e-9, 20)
        self.assertAlmostEqual(d["swing_frac_ring"], 1.65 / 1.98, 12)
        self.assertAlmostEqual(d["i_ring_run_a"], 16.8e-6, 20)
        self.assertAlmostEqual(d["i_buf_a"], 2.3e-6, 20)

    def test_nonpositive_period_fails_closed(self):
        raw = {"tc3": 20e-9, "tc11": 20e-9, "tc4": 21e-9, "tfall3": 20.9e-9,
               "vmax_ring": 1.0, "vmin_ring": 0.0, "vmax_buf": 1.0, "vmin_buf": 0.0,
               "iddr_run": -1e-6, "iddr_stop": -1e-9, "ibuf": -1e-6}
        with self.assertRaises(RD.ReductionError):
            RD.sc_derive(raw, 1.8)


class CommittedLaws(unittest.TestCase):
    def test_operating_point_replay(self):
        op = RD.load_op_record()
        k5, q = op["entropy"]["k"], op["entropy"]["q_required"]
        self.assertEqual(RD.entropy_n(k5, q, 1e6), 78)
        self.assertEqual(RD.entropy_n(k5, q, 5e4), 4)
        self.assertTrue(77.0e3 < RD.rate_ceiling_at_n(6, k5, q) < 78.5e3)

    def test_control_targets_hard_copies(self):
        t = RD.load_control_targets()
        self.assertAlmostEqual(t["ss"]["sigma_1_corrected"], 3.5479e-12, delta=2e-16)
        self.assertAlmostEqual(t["ss"]["tbar"], 4.822537e-9, delta=1e-18)

    def test_ring5_grid_is_27_points(self):
        self.assertEqual(len(RD.load_ring5_grid()), 27)

    def test_alpha_fit_direction(self):
        fit = RD.sigma1_vs_t0_alpha(RD.load_ring5_grid())
        self.assertTrue(0.0 < fit["alpha"] < 1.0, fit)
        self.assertLess(fit["ceiling_exponent"], 0.0)


class Models(unittest.TestCase):
    def test_area_anchors(self):
        # DR-0003 Sec 7 raw density and the sampler_core macro density
        self.assertAlmostEqual(RD.ARRAY_RAW_UM2_N4 / RD.ARRAY_DEVICES_N4, 880 / 132)
        self.assertAlmostEqual(
            RD.SAMPLER_CORE_MACRO_UM2 / RD.SAMPLER_CORE_DEVICES, 19297 / 264)
        a = RD.area_estimate_um2(78, RD.DEVICES_RING5)
        self.assertEqual(a["devices"], 78 * (22 + 2 + 22))
        self.assertGreater(a["macro_density_um2"], RD.ROW_AREA_UM2)

    def test_idle_uses_microamps(self):
        # 78 stopped rings at 0.255 uA must contribute ~39 uW at 1.98 V,
        # not ~0.04 uW (guards the nA/uA regression)
        d = RD.idle_power_uw(78, 0.255, 0.0, 1.98, 0.0)
        self.assertAlmostEqual(d["analog_uw"], 78 * 0.255 * 1.98, places=6)

    def test_lock_proximity(self):
        locks = RD.lock_proximity(78, 1.1686, 2.74)
        self.assertGreater(locks["expected_pairs_within_2pct_unspaced"], 100)
        self.assertLess(locks["adjacent_spacing_in_span"], 1.02)
        # the characterized span admits ~8 rings spaced >= 2% apart
        n = 2
        while 1.02 ** (n - 1) <= 1.1686:
            n += 1
        self.assertEqual(n - 1, 8)

    def test_draw_sensitivity_shape(self):
        # a +50% sigma draw must not reach 1 Mbps at the all-rows N cap
        k3 = 300.0
        rate = RD.rate_ceiling_at_n(5, k3 * 1.5 * 1.5, RD.load_op_record()["entropy"]["q_required"])
        self.assertLess(rate, 1e6)


class Requests(unittest.TestCase):
    def test_matrix_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            MR.main([tmp])
            names = sorted(os.listdir(tmp))
            self.assertEqual(len(names), RD.EXPECTED_REQUESTS)
            jobs = 0
            for n in names:
                with open(os.path.join(tmp, n, "request.json")) as fh:
                    r = json.load(fh)
                with open(os.path.join(tmp, n, "plan.json")) as fh:
                    plan = json.load(fh)
                jobs += len(r["corners"]["process"])
                self.assertEqual(r["corners"]["temperature_c"], [plan["pvt"]["temp"]])
                self.assertIn("uic", r["analysis"]["args"])
            self.assertEqual(jobs, RD.EXPECTED_JOBS)

    def test_ring3_deck_has_two_stages_and_ctrl5_has_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            MR.main([tmp])
            with open(os.path.join(tmp, "ctrl5--40C-1.62V", "netlist.cir")) as fh:
                c5 = fh.read()
            with open(os.path.join(tmp, "ring3--40C-1.62V", "netlist.cir")) as fh:
                r3 = fh.read()
            # circuit-body instances only: lines starting with x and ending
            # exactly in ro_stage (the inlined .subckt bodies pass parameters,
            # so they do not match)
            stages = lambda deck: sum(
                1 for ln in deck.splitlines()
                if ln.startswith("x") and ln.rstrip().endswith("ro_stage"))
            self.assertEqual(stages(c5), 4)
            self.assertEqual(stages(r3), 2)
            for deck in (c5, r3):
                self.assertIn(".option seed=1", deck)
                # no .control/.temp CARDS (comments may mention them)
                self.assertFalse([ln for ln in deck.splitlines()
                                  if ln.lstrip().startswith((".control", ".temp"))])
                self.assertIn("trnoise(2.0e-3 2e-10 0 0)", deck)

    def test_sc_decks_carry_both_rings_and_the_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            MR.main([tmp])
            for cfg in ("sc5", "sc3"):
                with open(os.path.join(tmp, f"{cfg}--40C-1.62V", "netlist.cir")) as fh:
                    deck = fh.read()
                self.assertIn("xbA roA robA vdd 0 ro_buf", deck)
                self.assertIn("VenB enB 0 dc 0", deck)  # stopped ring
                self.assertNotIn("trnoise", deck)       # deterministic


class ControlGates(unittest.TestCase):
    def make_row(self, corner, sigma, tbar):
        return {"config": "ctrl5", "temp_c": -40.0, "vdd_v": 1.62, "corner": corner,
                "tbar": tbar, "sigma_1": sigma, "sigma_1_corrected": RD.quad_correct(sigma)}

    def test_jitter_gate_passes_near_committed(self):
        targets = RD.load_control_targets()
        rows = [self.make_row(c, t["sigma_1_raw"] * (1.02 if c == "ss" else 1.05),
                              t["tbar"] * 1.001)
                for c, t in targets.items()]
        out = RD.control_gate_jitter(rows, targets)
        self.assertEqual(set(out), {"tt", "ss", "ff"})

    def test_jitter_gate_fails_on_tbar_drift(self):
        targets = RD.load_control_targets()
        rows = [self.make_row(c, t["sigma_1_raw"], t["tbar"] * 1.02)
                for c, t in targets.items()]
        with self.assertRaises(RD.ReductionError):
            RD.control_gate_jitter(rows, targets)

    def test_jitter_gate_fails_on_binding_sigma_drift(self):
        targets = RD.load_control_targets()
        rows = [self.make_row(c, t["sigma_1_raw"] * (0.5 if c == "ss" else 1.05),
                              t["tbar"])
                for c, t in targets.items()]
        with self.assertRaises(RD.ReductionError):
            RD.control_gate_jitter(rows, targets)


class CommittedRecordReplay(unittest.TestCase):
    """The committed record must replay from its corners bundle (no simulator)."""

    def test_check_replays(self):
        import glob
        recs = sorted(glob.glob(os.path.join(D, "records", "*.json")))
        self.assertTrue(recs, "no committed record found")
        self.assertEqual(RD.check_record(recs[-1]), 0)

    def test_known_answer(self):
        self.assertEqual(RD.known_answer(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
