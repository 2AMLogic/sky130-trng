#!/usr/bin/env python3
"""Unit tests for `sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`.

Standard library only, no simulator::

    python3 sim/tests/test_raw_bit_battery.py

Synthetic streams: ideal (seeded PRNG), biased, serially correlated,
periodic.  Each battery test must reject its targeted defect and pass ideal
input at alpha = 0.01; short input must be INSUFFICIENT, never PASS.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis" / "raw-bit-battery.py"
_spec = importlib.util.spec_from_file_location("raw_bit_battery", _PATH)
assert _spec is not None and _spec.loader is not None
B = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
_spec.loader.exec_module(B)


def ideal(n, seed=1):
    r = random.Random(seed)
    return [r.getrandbits(1) for _ in range(n)]


def biased(n, p1=0.6, seed=2):
    r = random.Random(seed)
    return [1 if r.random() < p1 else 0 for _ in range(n)]


def correlated(n, stay=0.8, seed=3):
    r = random.Random(seed)
    out = [0]
    for _ in range(n - 1):
        out.append(out[-1] if r.random() < stay else 1 - out[-1])
    return out


def periodic(n, pat=(1, 1, 0, 1, 0, 0, 1, 0)):
    return [pat[i % len(pat)] for i in range(n)]


class TestSpecialFunctions(unittest.TestCase):
    def test_igamc_known(self):
        # Q(1, x) = exp(-x); Q(0.5, x) = erfc(sqrt(x))
        import math
        for x in (0.3, 1.0, 5.0, 20.0):
            self.assertAlmostEqual(B.igamc(1.0, x), math.exp(-x), places=10)
            self.assertAlmostEqual(B.igamc(0.5, x), math.erfc(math.sqrt(x)),
                                   places=10)

    def test_sp80022_example_monobit(self):
        # SP 800-22 section 2.1.8 example: 1100100100001111110110101010001000
        # 100001011010001100001000110100110001001100011001100010100010111000
        bits = [int(c) for c in
                "11001001000011111101101010100010001000010110100011000010001101"
                "00110001001100011001100010100010111000"]
        self.assertEqual(len(bits), 100)
        self.assertAlmostEqual(B.t_monobit(bits), 0.109599, places=5)
        self.assertAlmostEqual(B.t_runs(bits), 0.500798, places=5)


class TestBatteryRejectsDefects(unittest.TestCase):
    N = 20000

    def test_ideal_passes_every_test(self):
        res = B.run_battery(ideal(self.N))
        for name, t in res["tests"].items():
            self.assertEqual(t["status"], "PASS", (name, t))
        self.assertEqual(res["verdict"], "PASS")

    def test_biased_fails_frequency_tests(self):
        res = B.run_battery(biased(self.N))
        for name in ("monobit", "block_frequency", "cusum_forward"):
            self.assertEqual(res["tests"][name]["status"], "FAIL", name)
        self.assertEqual(res["verdict"], "FAIL")

    def test_correlated_fails_runs_and_serial(self):
        res = B.run_battery(correlated(self.N))
        for name in ("runs", "serial_1", "approximate_entropy"):
            self.assertEqual(res["tests"][name]["status"], "FAIL", name)

    def test_periodic_fails_pattern_tests(self):
        res = B.run_battery(periodic(self.N))
        for name in ("serial_1", "approximate_entropy"):
            self.assertEqual(res["tests"][name]["status"], "FAIL", name)

    def test_long_runs_fail_longest_run(self):
        bits = []
        r = random.Random(5)
        for _ in range(self.N // 40):
            blk = [r.getrandbits(1) for _ in range(40)]
            blk[10:30] = [1] * 20
            bits += blk
        self.assertEqual(B.run_battery(bits)["tests"]["longest_run"]["status"],
                         "FAIL")

    def test_pass_proportion_ideal_and_biased(self):
        ok = B.run_battery(ideal(40 * 1000, seed=9), segment_len=1000)
        self.assertEqual(ok["mode"], "pass-proportion")
        self.assertEqual(ok["verdict"], "PASS", ok["tests"])
        bad = B.run_battery(biased(40 * 1000, seed=9), segment_len=1000)
        self.assertEqual(bad["tests"]["monobit"]["status"], "FAIL")


class TestMinimumLengthGuards(unittest.TestCase):
    def test_short_input_insufficient_not_pass(self):
        res = B.run_battery(ideal(24))
        self.assertEqual(res["verdict"], "INSUFFICIENT")
        for t in res["tests"].values():
            self.assertEqual(t["status"], "INSUFFICIENT")
            self.assertNotIn("p_values", t)

    def test_each_test_has_its_own_floor(self):
        res = B.run_battery(ideal(150))
        st = {k: v["status"] for k, v in res["tests"].items()}
        self.assertEqual(st["monobit"], "PASS")
        self.assertEqual(st["approximate_entropy"], "INSUFFICIENT")
        self.assertEqual(res["verdict"], "INSUFFICIENT")

    def test_too_few_segments_insufficient(self):
        res = B.run_battery(ideal(3000), segment_len=1000)
        self.assertEqual(res["verdict"], "INSUFFICIENT")

    def test_estimators_refuse_short_input(self):
        res = B.entropy_estimates(ideal(24))
        self.assertEqual(res["verdict"], "INSUFFICIENT")
        self.assertIsNone(res["h_min_bits"])
        mid = B.entropy_estimates(ideal(2000))
        self.assertEqual(mid["estimators"]["compression"]["status"],
                         "INSUFFICIENT")
        self.assertEqual(mid["verdict"], "INSUFFICIENT")


class TestEstimators(unittest.TestCase):
    N = 20000

    def test_ideal_high_entropy(self):
        res = B.entropy_estimates(ideal(self.N))
        self.assertEqual(res["verdict"], "ESTIMATE")
        for name, e in res["estimators"].items():
            self.assertGreater(e["h_bits"], 0.6, name)  # collision/compression CIs are wide at this n
            self.assertLessEqual(e["h_bits"], 1.0, name)
        self.assertGreater(res["h_min_bits"], 0.6)

    def test_biased_mcv_matches_theory(self):
        res = B.entropy_estimates(biased(self.N, 0.8))
        mcv = res["estimators"]["mcv"]["h_bits"]
        self.assertLess(mcv, 0.35)  # -log2(0.8)=0.32
        self.assertGreater(mcv, 0.28)
        self.assertLessEqual(res["h_min_bits"], mcv)
        self.assertGreater(res["h_min_bits"], 0.1)

    def test_correlated_caught_beyond_mcv(self):
        # Marginally balanced but sticky: MCV is blind, others are not.
        bits = correlated(self.N, stay=0.9)
        res = B.entropy_estimates(bits)
        e = res["estimators"]
        self.assertGreater(e["mcv"]["h_bits"], 0.9)
        self.assertLess(e["markov"]["h_bits"], 0.6)  # true ~0.47
        self.assertLess(e["collision"]["h_bits"], 0.9)
        self.assertLess(res["h_min_bits"], e["mcv"]["h_bits"] - 0.3)
        self.assertNotEqual(res["binding_estimator"], "mcv")

    def test_periodic_collapses(self):
        res = B.entropy_estimates(periodic(self.N))
        e = res["estimators"]
        self.assertLess(e["markov"]["h_bits"], 0.5)
        self.assertLess(e["lrs"]["h_bits"], 0.1)
        self.assertLess(e["t_tuple"]["h_bits"], 0.1)
        self.assertLess(e["compression"]["h_bits"], 0.2)
        self.assertLess(res["h_min_bits"], 0.1)

    def test_constant_stream_zero(self):
        res = B.entropy_estimates([1] * 13000)
        self.assertEqual(res["h_min_bits"], 0.0)


class TestRecordCaveat(unittest.TestCase):
    def test_results_carry_provisional_caveat(self):
        self.assertIn("provisional until measured on silicon",
                      B.run_battery(ideal(10))["caveat"])
        self.assertIn("provisional until measured on silicon",
                      B.entropy_estimates(ideal(10))["caveat"])

    def test_report_on_real_record_is_insufficient(self):
        recs = B.raw_bit_entropy.campaign_records(B.RECORDS_DIR)
        if not recs:
            self.skipTest("no campaign record")
        body, summary = B.analyse_record(recs[-1])
        self.assertIn("provisional until measured on silicon", body)
        for c in summary["per_corner"]:
            self.assertEqual(c["battery"]["verdict"], "INSUFFICIENT")


def pack(bits):
    return "".join(f"{int(''.join(map(str, bits[i:i + 8])), 2):02x}"
                   for i in range(0, len(bits), 8))


class TestVolumeAdapter(unittest.TestCase):
    N = 5120  # 10 segments of 512 (SEGMENT_LEN patched below)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._saved = (B.SEGMENT_LEN, B.SEGMENT_COUNT, B.REPO_ROOT,
                       B.RECORDS_DIR)
        B.SEGMENT_LEN, B.SEGMENT_COUNT = 512, 10
        B.REPO_ROOT = self.root
        B.RECORDS_DIR = self.root / "sim" / "raw-bit-min-entropy" / "records"
        self.addCleanup(self._restore)
        base = self.root / "sim" / B.VOLUME_SLUG
        self.rid = "20260101-000000-abc1234"
        (base / "records").mkdir(parents=True)
        self.runs = base / "runs" / self.rid
        self.runs.mkdir(parents=True)
        self.src = base / "records" / f"{self.rid}.json"
        self.streams = []
        for i, ts in enumerate(("Ts20us", "Ts100ns")):
            bits = ideal(self.N, seed=10 + i)
            text = pack(bits)
            name = f"bits_tt_{ts}.hex.txt"
            (self.runs / name).write_text(text + "\n")
            self.streams.append({
                "corner": "tt", "temp_c": 27.0, "vdd_v": 1.8,
                "ts_s": 2e-5 if i == 0 else 1e-7, "ts_name": ts,
                "seed": 100 + i, "file": name, "n": self.N,
                "sha256_hex": hashlib.sha256(text.encode()).hexdigest()})
        self.write_source()
        self.src.with_suffix(".md").write_text(
            "# x\n\n" + B.VOLUME_CAVEATS_HEADING + "\n\n"
            "- **Behavioral model, not transistor-level.** Provisional.\n"
            "- **Not an SP 800-90B assessment.**\n\n---\n\n## Provenance\n")

    def _restore(self):
        (B.SEGMENT_LEN, B.SEGMENT_COUNT, B.REPO_ROOT, B.RECORDS_DIR) = self._saved

    def write_source(self):
        self.src.write_text(json.dumps({
            "record_id": self.rid, "slug": B.VOLUME_SLUG,
            "level": "behavioral", "streams": self.streams}))

    def mint(self):
        args = ["--volume-record", str(self.src), "--emit-record"]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(B.main(args), 0)
        recs = sorted(B.RECORDS_DIR.glob("*.json"))
        self.assertEqual(len(recs), 1)
        return recs[0]

    def check(self, rec):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = B.main(["--check", str(rec)])
        return rc, err.getvalue()

    def test_msb_first(self):
        self.assertEqual(B.decode_packed_hex("80"), [1, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(B.decode_packed_hex("01a5"),
                         [0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1])

    def test_malformed_hex_rejected(self):
        for bad in ("abc", "zz", "AB", "a b"):
            with self.assertRaises(B.VolumeInputError):
                B.decode_packed_hex(bad)

    def test_trailing_newline_and_hash(self):
        row = self.streams[0]
        bits = B.load_stream(self.runs / row["file"], row["n"], row["sha256_hex"])
        self.assertEqual(len(bits), self.N)
        self.assertEqual(pack(bits) + "\n", (self.runs / row["file"]).read_text())
        # same text without the newline hashes identically (newline excluded)
        f = self.runs / "nonl.txt"
        f.write_text(pack(bits))
        self.assertEqual(B.load_stream(f, row["n"], row["sha256_hex"]), bits)

    def test_rejections(self):
        row = self.streams[0]
        f = self.runs / row["file"]
        with self.assertRaises(B.VolumeInputError):   # absent
            B.load_stream(self.runs / "nope.txt", row["n"], row["sha256_hex"])
        with self.assertRaises(B.VolumeInputError):   # length mismatch
            B.load_stream(f, row["n"] + 8, row["sha256_hex"])
        with self.assertRaises(B.VolumeInputError):   # hash mismatch
            B.load_stream(f, row["n"], "0" * 64)
        trunc = self.runs / "trunc.txt"
        trunc.write_text(f.read_text()[:-5])
        with self.assertRaises(B.VolumeInputError):   # truncated
            B.load_stream(trunc, row["n"], row["sha256_hex"])
        bad = "zz" + f.read_text()[2:-1]
        g = self.runs / "bad.txt"
        g.write_text(bad)
        with self.assertRaises(B.VolumeInputError):   # malformed, hash matches
            B.load_stream(g, row["n"], hashlib.sha256(bad.encode()).hexdigest())

    def test_source_missing_stream_aborts(self):
        (self.runs / self.streams[1]["file"]).unlink()
        with self.assertRaises(B.VolumeInputError):
            B.load_volume_source(self.src)

    def test_source_wrong_slug_or_path_traversal(self):
        self.streams[0]["file"] = "../x.txt"
        self.write_source()
        with self.assertRaises(B.VolumeInputError):
            B.load_volume_source(self.src)

    def test_payload_provenance_and_min_h(self):
        pl = B.volume_payload(self.src)
        self.assertEqual(pl["segment_policy"]["len"], 512)
        for row, src in zip(pl["per_stream"], self.streams):
            for k in ("corner", "temp_c", "vdd_v", "ts_s", "seed"):
                self.assertEqual(row[k], src[k])
            self.assertEqual(row["source_file"], src["file"])
            self.assertEqual(row["source_sha256_hex"], src["sha256_hex"])
            e = row["estimators"]
            hs = [v["h_bits"] for v in e["estimators"].values()
                  if v["status"] == "OK"]
            self.assertEqual(e["h_min_bits"], min(hs))
            self.assertIn(e["binding_estimator"], e["binding_ties"])
            for t in e["binding_ties"]:
                self.assertEqual(e["estimators"][t]["h_bits"], min(hs))
            self.assertEqual(row["segmented"]["segments"], 10)
            self.assertEqual(row["single_sequence"]["segments"], 1)

    def test_binding_with_zero_estimate_and_ties(self):
        a = B.analyse_stream([1] * 13000)
        self.assertEqual(a["estimators"]["h_min_bits"], 0.0)
        self.assertIn(a["estimators"]["binding_estimator"],
                      a["estimators"]["binding_ties"])
        self.assertGreater(len(a["estimators"]["binding_ties"]), 1)

    def test_failures_visible_and_ts_separate_and_caveats(self):
        pl = B.volume_payload(self.src)
        pl["per_stream"][1]["single_sequence"]["tests"]["serial_1"]["status"] = "FAIL"
        body = B.render_volume(pl, B.source_caveats(self.src))
        self.assertIn("serial_1", body)
        self.assertLess(body.index("## Ts20us"), body.index("## Ts100ns"))
        self.assertIn("- **Behavioral model, not transistor-level.** Provisional.",
                      body)
        self.assertIn("provisional until measured on silicon", body)
        self.assertIn("no formal NIST assessment", body)

    def test_check_roundtrip_and_failures(self):
        rec = self.mint()
        committed = json.loads(rec.read_text())
        self.assertEqual(committed["level"], "behavioral (derived)")
        self.assertEqual(len(committed["ts20us_min_entropy"]), 1)
        before = {p: p.read_bytes() for p in B.RECORDS_DIR.iterdir()}
        rc, _ = self.check(rec)
        self.assertEqual(rc, 0)
        self.assertEqual(before, {p: p.read_bytes() for p in B.RECORDS_DIR.iterdir()})
        # altered expected result
        bad = json.loads(rec.read_text())
        bad["analysis_payload"]["per_stream"][0]["estimators"]["h_min_bits"] = 0.5
        rec.write_text(json.dumps(bad))
        rc, err = self.check(rec)
        self.assertNotEqual(rc, 0)
        self.assertIn("CHECK FAILED", err)
        rec.write_text(json.dumps(committed))
        # altered markdown table
        md = rec.with_suffix(".md")
        good_md = md.read_text()
        md.write_text(good_md.replace("| PASS |", "| FAIL |", 1)
                      if "| PASS |" in good_md else good_md + "x")
        self.assertNotEqual(self.check(rec)[0], 0)
        md.write_text(good_md)
        self.assertEqual(self.check(rec)[0], 0)
        # altered input stream (hash no longer matches)
        f = self.runs / self.streams[0]["file"]
        f.write_text(("00" + f.read_text()[2:]))
        self.assertNotEqual(self.check(rec)[0], 0)
        self.assertEqual(len(list(B.RECORDS_DIR.glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
