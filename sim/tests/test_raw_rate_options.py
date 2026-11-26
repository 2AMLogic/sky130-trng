#!/usr/bin/env python3
"""Unit tests for sim/raw-rate-row-options/ (issue #600).

No simulator and no PDK: synthetic measurements, the COMMITTED baseline
records, and this campaign's own committed corners bundle only.

    python3 sim/tests/test_raw_rate_options.py
"""
import gzip
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_ring5_pvt_fit(self):
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
        # A +50% sigma draw must not reach 1 Mbps at the ring+buffer power cap.
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

    def test_docstring_matches_request_matrix_and_client_pin(self):
        self.assertIn('klayout-tools==0.9.1', MR.__doc__)
        self.assertIn("39-unit matrix", MR.__doc__)
        self.assertIn("13 `klt sim`", MR.__doc__)


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

    record = Path(D, "records", "20261121-115332-7b5b48ca.json")

    def test_check_replays(self):
        records = sorted(self.record.parent.glob("*.json"))
        self.assertIn(self.record, records)
        for record in records:
            with self.subTest(record=record.name):
                self.assertEqual(RD.check_record(record), 0)

    def test_altered_rate_fails_replay(self):
        rec = json.loads(self.record.read_text())
        rec["reduction"]["ring_power_bound"]["rate_kbps_ring3"] = 1001.0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "altered.json")
            path.write_text(json.dumps(rec))
            with self.assertRaisesRegex(RD.ReductionError, r"ring_power_bound\.rate_kbps_ring3"):
                RD.check_record(path)

    def test_missing_control_or_reduction_field_fails_replay(self):
        for section, field in (("control_sc", None), ("control_jitter", "ss"),
                               ("reduction", "draw_sensitivity")):
            with self.subTest(section=section), tempfile.TemporaryDirectory() as tmp:
                rec = json.loads(self.record.read_text())
                if field is None:
                    del rec[section]
                else:
                    del rec[section][field]
                path = Path(tmp, "incomplete.json")
                path.write_text(json.dumps(rec))
                with self.assertRaisesRegex(RD.ReductionError, field or section):
                    RD.check_record(path)

    def test_cold_response_in_hot_slot_fails_emit_and_replay(self):
        rec = json.loads(self.record.read_text())
        src_cdir = Path(D, "corners", rec["record_id"])
        with tempfile.TemporaryDirectory() as tmp:
            reqdir = Path(tmp, "reqdir")
            cdir = Path(tmp, "corners")
            shutil.copytree(src_cdir, cdir)
            for gz in sorted(src_cdir.glob("*.klt-sim.json.gz")):
                nm = gz.name[: -len(".klt-sim.json.gz")]
                sub = reqdir / nm
                sub.mkdir(parents=True)
                shutil.copyfile(src_cdir / f"{nm}.netlist.cir", sub / "netlist.cir")
                shutil.copyfile(src_cdir / f"{nm}.request.json", sub / "request.json")
                shutil.copyfile(src_cdir / f"{nm}.plan.json", sub / "plan.json")
                with gzip.open(gz, "rt") as fh:
                    (sub / "resp.json").write_text(fh.read())
            _, clean_rows = RD.load_reqdir(reqdir)
            self.assertEqual(len(clean_rows), RD.EXPECTED_JOBS)

            shutil.copyfile(reqdir / "sc3--40C-1.98V" / "resp.json",
                            reqdir / "sc3-125C-1.98V" / "resp.json")
            with self.assertRaisesRegex(RD.ReductionError, r"sc3-125C-1\.98V.*process/temperature"):
                RD.load_reqdir(reqdir)

            shutil.copyfile(cdir / "sc3--40C-1.98V.klt-sim.json.gz",
                            cdir / "sc3-125C-1.98V.klt-sim.json.gz")
            with self.assertRaisesRegex(RD.ReductionError, r"sc3-125C-1\.98V.*process/temperature"):
                RD.check_record(self.record, corners_dir=cdir)

            bad_resp = json.loads((reqdir / "sc3--40C-1.98V" / "resp.json").read_text())
            bad_resp["corners"][0]["process"] = "sf"
            with gzip.open(cdir / "sc3--40C-1.98V.klt-sim.json.gz", "wt") as fh:
                json.dump(bad_resp, fh)
            shutil.copyfile(src_cdir / "sc3-125C-1.98V.klt-sim.json.gz",
                            cdir / "sc3-125C-1.98V.klt-sim.json.gz")
            with self.assertRaisesRegex(RD.ReductionError, r"sc3--40C-1\.98V.*process/temperature"):
                RD.check_record(self.record, corners_dir=cdir)

    def test_appended_later_baseline_runs_still_replay_original_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            jdir = Path(tmp, "jitter")
            scdir = Path(tmp, "sc")
            shutil.copytree(RD.JITTER_RECORDS, jdir)
            shutil.copytree(RD.RING5_SC_RECORDS, scdir)

            extra_j = json.loads((jdir / "20260825-060208-54f5715.json").read_text())
            extra_j["record_id"] = "20261201-000000-deadbeef"
            for c in extra_j["corners"]:
                c["measurements"]["sigma_1"] *= 2.0
            (jdir / "20261201-000000-deadbeef.json").write_text(json.dumps(extra_j))

            extra_sc = json.loads((scdir / "20260825-085449-53f1f7a.json").read_text())
            extra_sc["record_id"] = "20261201-000001-deadbeef"
            for c in extra_sc["corners"]:
                c["measurements"]["i_ring_run"] *= 2.0
                c["measurements"]["tbar"] *= 1.5
            (scdir / "20261201-000001-deadbeef.json").write_text(json.dumps(extra_sc))

            with patch.object(RD, "JITTER_RECORDS", jdir), patch.object(RD, "RING5_SC_RECORDS", scdir):
                self.assertEqual(len(RD.load_ring5_grid()), 27)
                self.assertEqual(len(RD.load_ring5_loaded()), 12)
                self.assertEqual(RD.check_record(self.record), 0)
                self.assertEqual(RD.known_answer(), 0)

    def test_markdown_body_matches_committed_record_including_tcq_range(self):
        rec = json.loads(self.record.read_text())
        cdir = Path(D, "corners", rec["record_id"])
        chunks = RD.read_corner_bundle(cdir)
        rows = RD.load_verified_rows(
            chunks,
            netlist_path=lambda n: cdir / f"{n}.netlist.cir",
            request_path=lambda n: cdir / f"{n}.request.json",
        )
        res = RD.study_results(rows)
        body = RD.render_body(rows, res["reduction"], res["control_jitter"], res["control_sc"])
        self.assertIn("Post-layout `tcq` is 0.138-0.299 ns", body)
        md_text = self.record.with_suffix(".md").read_text()
        md_body = md_text.split("---\n", 1)[1].rsplit("\n---\n", 1)[0]
        self.assertEqual(body, md_body)

    def test_known_answer(self):
        self.assertEqual(RD.known_answer(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
