#!/usr/bin/env python3
"""Unit tests for sim/wake-up-transient/restart_matrix.py (issue #267). Standard library only, no simulator.

    python3 sim/tests/test_restart_matrix.py

Known-answer fixtures independent of the physical model: a seeded IID matrix must PASS the matrix sanity verdict, and
the same matrix with one deterministic column must FAIL the column-MCV rule naming exactly that index. Boundary
tests pin the 1000 x 2048 minimum shape and the fail-closed input checks. The last class replays one entry of the
committed behavioural record (deterministic and stationary arms at one point) and checks every entry's provenance.
"""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "wake-up-transient"))
import restart_matrix as rm  # noqa: E402

R, N = rm.MIN_ROWS, rm.MIN_COLS


def iid(rows=R, cols=N, seed=267):
    rng = random.Random(seed)
    out = []
    for _ in range(rows):
        x = rng.getrandbits(cols)
        out.append([(x >> i) & 1 for i in range(cols)])
    return out


def deterministic_column(m, index, value=1):
    return [row[:index] + [value] + row[index + 1:] for row in m]


class Contract(unittest.TestCase):
    def test_contract_numbers(self):
        self.assertEqual((rm.MIN_ROWS, rm.MIN_COLS, rm.FIRST_WINDOW), (1000, 2048, 1024))
        self.assertEqual((rm.H_FLOOR, rm.ALPHA), (0.5, 0.01))

    def test_estimator_is_the_repository_mcv(self):
        bits = iid(1, 4096, seed=5)[0]
        e = rm.mcv_estimate(bits)
        p = max(sum(bits), len(bits) - sum(bits)) / len(bits)
        pu = p + 2.5758293035489004 * math.sqrt(p * (1 - p) / (len(bits) - 1))
        self.assertAlmostEqual(e["p_u_99"], pu, places=12)
        self.assertAlmostEqual(e["h_hat_bits"], -math.log2(pu), places=12)


class KnownAnswer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = iid()
        cls.s, cls.v = rm.reduce_matrix(cls.m)

    def test_iid_passes(self):
        s = self.s
        self.assertTrue(s["verdict"]["pass"], rm.summary_text(s))
        self.assertEqual(s["shape"]["restarts"], 1000)
        self.assertEqual(s["shape"]["samples"], 2048)
        self.assertGreaterEqual(s["rows"]["h_mcv_min"], 0.5)
        self.assertGreaterEqual(s["columns"]["h_mcv_min"], 0.5)
        self.assertEqual(s["health"]["pass_count"], 1000)
        self.assertFalse(s["first_vs_baseline"]["distinguishable"])
        self.assertEqual(len(self.v["rows"]["h_mcv"]), 1000)
        self.assertEqual(len(self.v["columns"]["h_mcv"]), 2048)
        self.assertEqual(len(self.v["health"]["passed"]), 1000)

    def test_deterministic_column_fails_at_its_index(self):
        for idx in (0, 700, 1500, 2047):
            s, v = rm.reduce_matrix(deterministic_column(self.m, idx))
            self.assertFalse(s["verdict"]["pass"])
            self.assertFalse(s["verdict"]["column_mcv_ok"])
            self.assertEqual(s["verdict"]["failing_columns_mcv"], [idx])
            self.assertEqual(s["columns"]["h_mcv_min_index"], idx)
            self.assertLess(v["columns"]["h_mcv"][idx], 0.5)
            self.assertEqual(v["columns"]["h_mcv"][idx], 0.0)
            # rows and the start-up tests are unaffected by one fixed sample per row
            self.assertTrue(s["verdict"]["row_mcv_ok"])
            self.assertTrue(s["verdict"]["startup_health_ok"])
            self.assertIn(f"columns below 0.5: 1 [{idx}]", rm.summary_text(s))

    def test_deterministic_json(self):
        s2, v2 = rm.reduce_matrix(iid())
        self.assertEqual(rm.canonical(self.s), rm.canonical(s2))
        self.assertEqual(rm.canonical(self.v), rm.canonical(v2))
        json.loads(rm.canonical(self.s))

    def test_stuck_row_fails_health_with_rct(self):
        m = [list(r) for r in self.m]
        m[3][100:300] = [0] * 200
        s, v = rm.reduce_matrix(m)
        self.assertFalse(s["verdict"]["startup_health_ok"])
        self.assertFalse(s["verdict"]["pass"])
        self.assertEqual(s["health"]["failed_rows"], [3])
        self.assertEqual(v["health"]["alarm_class"][3], "RCT")
        self.assertEqual(s["health"]["alarm_classes"], {"RCT": 1})
        # the run of zeros reaches C_RCT = 81 identical samples at or before index 100 + 80
        self.assertLessEqual(v["health"]["first_trip_index"][3], 180)
        self.assertTrue(s["verdict"]["column_mcv_ok"])

    def test_biased_first_window_is_distinguishable(self):
        m = [list(r) for r in self.m]
        rng = random.Random(9)
        for row in m:
            for k in range(rm.FIRST_WINDOW):
                if rng.random() < 0.05:
                    row[k] = 1
        c = rm.reduce_matrix(m)[0]["first_vs_baseline"]
        self.assertTrue(c["distinguishable"])
        self.assertGreater(c["difference"], 0)


class TwoProportion(unittest.TestCase):
    def test_known_value(self):
        c = rm.two_proportion(600, 1000, 500, 1000)
        z = 0.1 / math.sqrt(0.55 * 0.45 * 0.002)
        self.assertAlmostEqual(c["z"], z, places=12)
        self.assertAlmostEqual(c["p_value"], math.erfc(z / math.sqrt(2)), places=15)
        self.assertTrue(c["distinguishable"])

    def test_equal(self):
        c = rm.two_proportion(500, 1000, 500, 1000)
        self.assertEqual((c["z"], c["p_value"], c["distinguishable"]), (0.0, 1.0, False))

    def test_degenerate(self):
        self.assertEqual(rm.two_proportion(0, 10, 0, 10)["p_value"], 1.0)
        c = rm.two_proportion(10, 10, 0, 10)
        self.assertTrue(c["distinguishable"])


class FailClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = iid()

    def err(self, m, fragment):
        with self.assertRaises(rm.MatrixError) as cm:
            rm.reduce_matrix(m)
        self.assertIn(fragment, str(cm.exception))

    def test_exact_minimum_shape_accepted(self):
        self.assertEqual(rm.validate_matrix(self.m), (1000, 2048))

    def test_undersized_rows(self):
        self.err(self.m[:999], "999 restarts < 1000")

    def test_undersized_cols(self):
        self.err([r[:2047] for r in self.m], "2047 samples per restart < 2048")

    def test_ragged(self):
        m = list(self.m)
        m[17] = m[17][:-1]
        self.err(m, "ragged matrix: row 17 has 2047")

    def test_non_binary(self):
        for bad in (2, -1, 0.0, True, "1", None):
            m = list(self.m)
            m[5] = list(m[5])
            m[5][9] = bad
            self.err(m, "non-binary sample at row 5, column 9")

    def test_malformed(self):
        self.err([], "empty")
        self.err("0101", "list of rows")
        self.err([list(r) for r in self.m[:999]] + ["01" * 1024], "row 999 is a str")

    def test_text_parser(self):
        txt = "# capture header\n" + "\n".join("".join(map(str, r)) for r in self.m) + "\n"
        self.assertEqual(rm.parse_matrix_text(txt), self.m)
        with self.assertRaises(rm.MatrixError) as cm:
            rm.parse_matrix_text("0101\n01x1\n")
        self.assertIn("line 2: non-binary character 'x' at column 2", str(cm.exception))
        with self.assertRaises(rm.MatrixError) as cm:
            rm.parse_matrix_text("0101\n\n0101\n")
        self.assertIn("line 2: empty line", str(cm.exception))

    def test_cli_gz_roundtrip_and_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "m.txt.gz"
            good.write_bytes(gzip.compress(("\n".join("".join(map(str, r)) for r in self.m) + "\n").encode()))
            out = Path(td) / "out.json"
            with contextlib.redirect_stdout(io.StringIO()) as so:
                rc = rm.main(["reduce", str(good), "--json", str(out)])
            self.assertEqual(rc, 0)
            self.assertIn("matrix sanity verdict **PASS**", so.getvalue())
            self.assertTrue(json.loads(out.read_text())["summary"]["verdict"]["pass"])
            small = Path(td) / "small.txt"
            small.write_text("\n".join("".join(map(str, r)) for r in self.m[:10]) + "\n")
            with contextlib.redirect_stderr(io.StringIO()) as se:
                self.assertEqual(rm.main(["reduce", str(small)]), 2)
            self.assertIn("undersized", se.getvalue())


def latest_record():
    recs = []
    for p in sorted((REPO / "sim" / rm.SLUG / "records").glob("*.json")):
        r = json.loads(p.read_text())
        if r.get("leg") == rm.LEG:
            recs.append(p)
    return recs[-1] if recs else None


class BehavioralRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = latest_record()
        if cls.path is None:
            raise AssertionError("no committed restart-matrix record under sim/wake-up-transient/records/")
        cls.rec = json.loads(cls.path.read_text())

    def test_covers_18_points_both_arms(self):
        es = self.rec["entries"]
        self.assertEqual(len(es), 36)
        pts = {(e["corner"], e["temp_c"], e["vdd_v"]) for e in es}
        self.assertEqual(len(pts), 18)
        self.assertEqual(sorted(pts), sorted(set(rm.record_points())))
        for p in pts:
            self.assertEqual(sorted(e["arm"] for e in es if (e["corner"], e["temp_c"], e["vdd_v"]) == p),
                             ["deterministic", "stationary"])

    def test_every_entry_identifies_itself(self):
        for e in self.rec["entries"]:
            self.assertEqual(e["key"], rm.entry_key(e["corner"], e["temp_c"], e["vdd_v"], e["arm"]))
            sp = e["seed_policy"]
            self.assertEqual(sp["master_seed"], rm.MASTER_SEED)
            self.assertEqual(sp["first_seed"], rm.restart_seed(e["arm"], e["corner"], e["temp_c"], e["vdd_v"], 0))
            for k in ("sigma1", "periods_s", "delays_s", "jitter_record", "combining_record", "period_source"):
                self.assertIsNotNone(e["calibration"][k], (e["key"], k))
            self.assertIn("provisional until silicon", e["model_caveats"])
            self.assertIn("not an SP 800-90B validation", e["model_caveats"])
            self.assertEqual(e["status"], rm.PROV)
            self.assertEqual(e["reduction"]["shape"]["restarts"], 1000)
            self.assertEqual(e["reduction"]["shape"]["samples"], 2048)

    def test_markdown_caveats(self):
        md = self.path.with_suffix(".md").read_text()
        self.assertIn("provisional until silicon", md)
        self.assertIn("not evidence of physical C5 compliance", md)

    def test_replay_one_point_writes_nothing(self):
        def status():
            try:
                return subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=all"],
                                      capture_output=True, text=True, check=True).stdout
            except (OSError, subprocess.CalledProcessError):
                return None
        before = status()
        keys = [rm.entry_key("ss", -40.0, 1.62, a) for a in rm.ARMS]
        with contextlib.redirect_stdout(io.StringIO()) as so:
            rc = rm.check(self.path, only=keys)
        self.assertEqual(rc, 0, so.getvalue())
        self.assertEqual(so.getvalue().count("MATCHES"), 3)
        self.assertEqual(status(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
