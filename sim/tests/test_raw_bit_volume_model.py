#!/usr/bin/env python3
"""Fast checks for sim/raw-bit-volume-campaign/behavioral_raw_bit.py and the shared model
library it re-exports, sim/bin/raw_bit_model.py (stdlib only).

    python3 sim/tests/test_raw_bit_volume_model.py
"""
from __future__ import annotations

import ast
import json
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from loadmod import load_module  # noqa: E402
import bitstream_stats  # noqa: E402
import raw_bit_model  # noqa: E402
from raw_bit_volume import decode_packed_hex  # noqa: E402

CLI = "sim/raw-bit-volume-campaign/behavioral_raw_bit.py"
m = load_module("behavioral_raw_bit", REPO_ROOT / CLI)

mr = load_module("make_requests", REPO_ROOT / "sim/raw-bit-volume-campaign/make-requests.py")
dc = load_module("derive_combining", REPO_ROOT / "sim/raw-bit-volume-campaign/derive-combining.py")

PER = [2.88e-9, 2.72e-9, 2.57e-9, 2.43e-9]


HOT = unittest.skipUnless(
    m._hot_combining_present(),
    "125 C ro-array-core-combining records not yet minted (klt sim batch fleet refused the jobs; "
    "2AMLogic/klayout-tools#2851); this skip disappears the moment they are committed")


class ModelTests(unittest.TestCase):
    def test_hex_roundtrip(self):
        rng = random.Random(1)
        bits = [rng.randint(0, 1) for _ in range(64)]
        self.assertEqual(decode_packed_hex(m.pack_hex(bits)), bits)

    def test_dead_unpack_hex_fork_removed(self):
        self.assertFalse(hasattr(m, "unpack_hex"))

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


class SharedLibrarySeam(unittest.TestCase):
    """Issue #797: the model, calibration loader and stream statistics live in
    `sim/bin/raw_bit_model.py`; the CLI re-exports them and no campaign executes
    the CLI by path for them."""

    LIBRARY = "sim/bin/raw_bit_model.py"
    #: every moved symbol the CLI keeps available to its own callers
    MOVED = ("MASTER_SEED", "TS_TRANSISTOR_LEVEL", "TS_DR0003", "CORNERS", "PVT_POINTS_BASE",
             "PVT_POINTS_HOT", "PVT_SETS", "PERIOD_REL_UNC", "ENSEMBLE", "VTH_DRIFT_SLUG",
             "VTH_DRIFT_SCHEMA", "sub_seed", "stream", "pack_hex", "stats", "_quantile",
             "hamming_mean")
    #: calibration consumers that used to execute the whole CLI for these symbols
    CALLERS = (
        "sim/wake-up-transient/wakeup.py",
        "sim/wake-up-transient/restart_matrix.py",
        "sim/ro-vth-drift-sensitivity/analysis/behavioral_replay.py",
        "sim/raw-bit-volume-campaign/transistor_pvt_crosscheck.py",
    )
    BY_PATH = re.compile(r"load_module\(\s*['\"]behavioral_raw_bit['\"]")

    def test_cli_reexports_the_library(self):
        for name in self.MOVED:
            self.assertIs(getattr(m, name), getattr(raw_bit_model, name), name)
        self.assertIs(raw_bit_model.mcv_estimate, bitstream_stats.mcv_estimate)

    def test_cli_calibration_entry_points_are_repo_root_wrappers(self):
        # They stay CLI wrappers on purpose: each passes the CLI's own REPO_ROOT at CALL time,
        # so patching `BRB.REPO_ROOT` (sim/tests/test_vth_drift.py) still redirects them.
        self.assertIsNot(m.calibration, raw_bit_model.calibration)
        self.assertIsNot(m.calibration_from_artifact, raw_bit_model.calibration_from_artifact)
        self.assertEqual(m.calibration(27.0, 1.8, "tt"),
                         raw_bit_model.calibration(27.0, 1.8, "tt", repo_root=m.REPO_ROOT))
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(m, "REPO_ROOT", Path(td)):
                with self.assertRaises(SystemExit) as cm:
                    m.calibration(27.0, 1.8, "tt")
            self.assertIn("no calibration records", str(cm.exception))
        self.assertIn("20260825", m.calibration(27.0, 1.8, "tt")["combining_record"])   # restored

    def test_stats_goes_straight_to_the_shared_mcv_estimator(self):
        bits = [random.Random(7).randint(0, 1) for _ in range(2048)]
        seen = []
        real = raw_bit_model.mcv_estimate

        def spy(b):
            seen.append(len(b))
            return real(b)

        with mock.patch.object(raw_bit_model, "mcv_estimate", spy):
            st = raw_bit_model.stats(bits, "seam")
        self.assertEqual(seen, [len(bits)])
        for k, v in real(bits).items():                             # the estimator's fields, verbatim
            self.assertEqual(st[k], v, k)
        self.assertEqual(st, m.stats(bits, "seam"))                 # the CLI's name is the same function

    def test_library_imports_only_stdlib_and_its_seam_siblings(self):
        tree = ast.parse((REPO_ROOT / self.LIBRARY).read_text())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {"__future__", "hashlib", "json", "math", "random", "sys",
                                   "pathlib", "_hashing", "bitstream_stats"})

    def test_library_executes_nothing_by_path(self):
        src = (REPO_ROOT / self.LIBRARY).read_text()
        for needle in ("load_module", "evidence_record", "mint_behavioral_record"):
            self.assertNotIn(needle, src, needle)

    def test_library_import_scans_no_records(self):
        fresh = self._import_with_file_access_poisoned(REPO_ROOT / self.LIBRARY)
        self.assertIs(fresh.mcv_estimate, bitstream_stats.mcv_estimate)

    def test_the_import_probe_would_catch_a_record_scan(self):
        with tempfile.TemporaryDirectory() as td:
            scanning = Path(td) / "scanning.py"
            scanning.write_text("from pathlib import Path\nlist(Path('records').glob('*.json'))\n")
            with self.assertRaises(AssertionError):
                self._import_with_file_access_poisoned(scanning)

    @staticmethod
    def _import_with_file_access_poisoned(path: Path):
        """A fresh import of `path` with glob / read_text / open poisoned to fail loudly."""
        why = f"import-time file access in {path.name}"
        with mock.patch.object(Path, "glob", side_effect=AssertionError(why)), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError(why)), \
                mock.patch("builtins.open", side_effect=AssertionError(why)):
            return load_module(path.stem + "_import_probe", path)

    def test_cli_reaches_raw_bit_entropy_only_from_the_transistor_loader(self):
        tree = ast.parse((REPO_ROOT / CLI).read_text())
        loader = next(n for n in tree.body
                      if isinstance(n, ast.FunctionDef) and n.name == "load_transistor_sequences")
        reach = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "rbe"]
        self.assertTrue(reach)
        self.assertTrue(all(loader.lineno <= ln <= loader.end_lineno for ln in reach), reach)

    def test_every_migrated_caller_imports_the_library(self):
        for rel in self.CALLERS:
            with self.subTest(caller=rel):
                self.assertRegex((REPO_ROOT / rel).read_text(), r"(?m)^from raw_bit_model import ")

    def test_no_campaign_executes_the_cli_by_path(self):
        for path in sorted((REPO_ROOT / "sim").rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith("sim/tests/"):
                continue
            with self.subTest(script=rel):
                self.assertIsNone(self.BY_PATH.search(path.read_text()), rel)

    def test_the_by_path_scan_would_catch_a_re_fork(self):
        for src in ('brb = load_module("behavioral_raw_bit", p)\n',
                    "load_module('behavioral_raw_bit', REPO / 'x.py')\n",
                    'brb = load_module(\n    "behavioral_raw_bit", _CLI)\n'):
            self.assertIsNotNone(self.BY_PATH.search(src), src)


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
