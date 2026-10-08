#!/usr/bin/env python3
"""Fast checks for sim/raw-bit-volume-campaign/behavioral_raw_bit.py (stdlib only).

    python3 sim/tests/test_raw_bit_volume_model.py
"""
from __future__ import annotations

import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "behavioral_raw_bit", REPO_ROOT / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


mr = _load("make_requests", "sim/raw-bit-volume-campaign/make-requests.py")
dc = _load("derive_combining", "sim/raw-bit-volume-campaign/derive-combining.py")

PER = [2.88e-9, 2.72e-9, 2.57e-9, 2.43e-9]


HOT = unittest.skipUnless(
    m._hot_combining_present(),
    "125 C ro-array-core-combining records not yet minted (klt sim batch fleet refused the jobs; "
    "2AMLogic/klayout-tools#2851); this skip disappears the moment they are committed")


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

    def test_hot_pvt_points_declared(self):
        self.assertEqual(set(m.PVT_POINTS_HOT), {(125.0, v) for v in (1.62, 1.8, 1.98)})
        # Once the hot combining records exist the hot points MUST be in the calibration set.
        if m._hot_combining_present():
            self.assertTrue(set(m.PVT_POINTS_HOT) <= set(m.PVT_POINTS))
            self.assertEqual(len(m.PVT_POINTS), 6)
        else:
            self.assertEqual(m.PVT_POINTS, m.PVT_POINTS_BASE)

    @HOT
    def test_all_9_hot_pairs_resolve_from_combining_plus_jitter(self):
        n = 0
        for t, v in m.PVT_POINTS_HOT:
            for corner in m.CORNERS:
                cal = m.calibration(t, v, corner)
                self.assertTrue(cal["combining_record"] and cal["jitter_record"])
                self.assertNotEqual(cal["combining_record"], cal["jitter_record"])
                self.assertTrue(cal["combining_job_id"], "hot combining record must carry its batch job id")
                self.assertTrue(all(T > 0 for T in cal["periods_s"]))
                n += 1
        self.assertEqual(n, 9)   # 3 process x 3 supplies; x 2 Ts = the 18 hot streams

    def test_missing_calibration_fails_loudly(self):
        with self.assertRaises(SystemExit):
            m.calibration(150.0, 1.8, "tt")          # no record at this PVT
        with self.assertRaises(SystemExit):
            m.calibration(125.0, 1.8, "sf")          # corner not in the records

    @HOT
    def test_hot_campaign_has_18_streams_with_provenance(self):
        old = m.NBITS
        m.NBITS = 256                                 # structure only; full size is the record's job
        try:
            with tempfile.TemporaryDirectory() as td:
                rows = m.run_campaign(Path(td), m.PVT_POINTS_HOT)
        finally:
            m.NBITS = old
        self.assertEqual(len(rows), 18)
        self.assertEqual({r["ts_name"] for r in rows}, {"Ts100ns", "Ts20us"})
        for r in rows:
            self.assertEqual(r["temp_c"], 125.0)
            for k in ("seed", "sha256_hex", "n", "file"):
                self.assertIn(k, r)
            for k in ("combining_record", "jitter_record", "combining_job_id"):
                self.assertTrue(r["calibration"][k])
        self.assertEqual(len({r["seed"] for r in rows}), 18)

    def test_findings_never_drop_failing_rows(self):
        xc = {"jitter": [{"temp_c": 125.0, "vdd_v": 1.8, "corner": "tt", "ratios": {
                  "8": {"record": 9.0, "model_median": 3.0, "band99": [1.0, 5.0], "inside": False}}}],
              "phat": [{"corner": "ss", "transistor_phat": [0.99], "model_band99": [0.5, 0.8], "inside_all": False}],
              "hamming": [{"corner": "ff", "transistor_mean_pairwise_hamming": 0.0,
                           "model_band99": [0.1, 0.2], "inside": False}]}
        self.assertEqual(len(m.findings(xc)), 3)


class RequestGenerationTests(unittest.TestCase):
    def test_combining_requests_cover_hot_grid(self):
        with tempfile.TemporaryDirectory() as td:
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                mr.main_combining(type("A", (), {"outdir": td, "points": "125:1.62,125:1.8,125:1.98"})())
            seen = []
            for n, v in enumerate((1.62, 1.8, 1.98), 1):
                req = json.loads((Path(td) / f"p{n}" / "request.json").read_text())
                net = (Path(td) / f"p{n}" / "netlist.cir").read_text()
                self.assertEqual(req["backend"], "batch")
                self.assertEqual(req["engine"], "ngspice")
                self.assertEqual(req["corners"]["process"], ["tt", "ss", "ff"])
                self.assertEqual(req["corners"]["temperature_c"], [125.0])
                self.assertIn(f"dc {v}", net)
                self.assertIn("ro_array_core.spice", net)
                self.assertNotIn("@@VDD@@", net)
                names = {x["name"] for x in req["measurements"]}
                self.assertTrue({"t1a", "t4b", "txo_a", "txo_b", "tt1a", "vxo_avg", "ib"} <= names)
                seen.append((125.0, v))
            self.assertEqual(seen, list(m.PVT_POINTS_HOT))

    def test_combining_measurements_match_the_deck(self):
        deck = (REPO_ROOT / "sim/ro-array-core-combining/testbench/tb_ro_array_core.spice").read_text()
        _, meas = mr.build_combining(125.0, 1.8)
        self.assertEqual(len(meas), sum(1 for l in deck.splitlines() if l.strip().startswith("meas tran ")))

    def test_deck_not_modified_by_generation(self):
        deck = REPO_ROOT / "sim/ro-array-core-combining/testbench/tb_ro_array_core.spice"
        before = deck.read_bytes()
        mr.build_combining(125.0, 1.62)
        self.assertEqual(deck.read_bytes(), before)

    def test_derive_reproduces_committed_record_figures(self):
        rec = json.loads((REPO_ROOT / "sim/ro-array-core-combining/records/20260825-094718-53f1f7a.json").read_text())
        for c in rec["corners"]:
            raw = {k: v for k, v in c["measurements"].items() if k[:2] in ("t1", "t2", "t3", "t4", "tx", "tt") and k[-1] in "ab"}
            raw.update(vxo_max=0, vxo_min=0, vxo_avg=0, vt1_avg=0, i1=0, i2=0, i3=0, i4=0, ib=0)
            d = dc.derive(raw, rec["pvt"]["vdd_v"])
            for k in ("tr1", "tr4", "edge_retention", "retention_n2", "skew_span", "f_ideal"):
                self.assertAlmostEqual(d[k] / c["measurements"][k], 1.0, places=5, msg=k)

    def test_derive_fails_loudly_on_missing_measurement(self):
        with self.assertRaises(KeyError):
            dc.derive({"t1a": 1.0}, 1.8)


if __name__ == "__main__":
    unittest.main()
