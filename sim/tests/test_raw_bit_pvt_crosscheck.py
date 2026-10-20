#!/usr/bin/env python3
"""Fast checks for sim/raw-bit-volume-campaign/transistor_pvt_crosscheck.py and
`make-requests.py --pvt` (issue #289). Stdlib only, no simulator.

    python3 sim/tests/test_raw_bit_pvt_crosscheck.py

The responses used here are SYNTHETIC fixtures written to a temp dir to exercise the
reducer's controls; they are never evidence and never committed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from loadmod import load_module  # noqa: E402


x = load_module("transistor_pvt_crosscheck", REPO_ROOT / "sim/raw-bit-volume-campaign/transistor_pvt_crosscheck.py")
mr = load_module("make_requests_pvt", REPO_ROOT / "sim/raw-bit-volume-campaign/make-requests.py")

POINTS = x.DECLARED_POINTS
SEEDS = x.DECLARED_SEEDS


def _nl(key):
    return hashlib.sha256(("netlist:" + key).encode()).hexdigest()


def fake_unit(d: Path, t, v, seed, *, bits=None, state="done", exit_code="0", corner_status="pass",
              resp_temp=None, resp_vdd=None, drop_process=None, key=None, nl_key=None):
    key = key or x.pvt_key(t, v, seed)
    man = {"schema": x.MANIFEST_SCHEMA, "key": key, "temp_c": t, "vdd_v": v, "seed": seed, "ts_ns": 100,
           "nbits": 24, "processes": ["tt", "ss", "ff"], "netlist_sha256": _nl(nl_key or key)}
    rng = random.Random(seed * 1000 + int(t) + int(v * 100))
    rv = v if resp_vdd is None else resp_vdd
    corners = []
    for p in ("tt", "ss", "ff"):
        if p == drop_process:
            continue
        b = bits if bits is not None else [rng.randint(0, 1) for _ in range(24)]
        meas = []
        for k in range(24):
            meas.append({"name": f"bit{k}", "value": rv if b[k] else 1e-6, "status": "pass"})
            meas.append({"name": f"valid{k}", "value": rv, "status": "pass"})
        corners.append({"process": p, "temperature_c": t if resp_temp is None else resp_temp,
                        "status": corner_status, "measurements": meas})
    resp = {"status": "pass", "environment": {"netlist_sha256": _nl(nl_key or key), "models_lib_sha256": "ab" * 32,
                                              "remote": {"job_id": f"klt-sim-{key[-8:]}", "state": state,
                                                         "exit_code": exit_code}},
            "corners": corners}
    (d / f"{key}.manifest.json").write_text(json.dumps(man))
    (d / f"{key}.klt-sim.json").write_text(json.dumps(resp))


def full_matrix(d: Path):
    for t, v in POINTS:
        for s in SEEDS:
            fake_unit(d, t, v, s)


def reduce_dir(d, **kw):
    return x.reduce_units(x.load_units(d), ensemble=40, **kw)


class RequestTests(unittest.TestCase):
    def test_default_pvt_set_is_the_calibrated_non_nominal_set(self):
        self.assertEqual(mr.parse_points(mr.DEFAULT_PVT), list(POINTS))

    def test_keys_unique_and_encode_pvt_seed_ts(self):
        keys = [mr.pvt_key(t, v, s) for t, v in POINTS for s in SEEDS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(mr.pvt_key(-40.0, 1.62, 101), "pvt_-40C_1.62V_Ts100ns_seed101")
        self.assertEqual(mr.pvt_key(125.0, 1.8, 7), x.pvt_key(125.0, 1.8, 7))

    def test_netlist_carries_the_requested_pvt(self):
        a, _ = mr.build(101, 125.0, 1.62)
        self.assertIn("dc 1.62", a)
        self.assertNotIn("dc 1.8\n", a)
        n_default, _ = mr.build(101)
        n_explicit, _ = mr.build(101, mr.TEMP, mr.VDD)
        self.assertEqual(n_default, n_explicit)

    def test_generated_requests_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            ns = type("A", (), {"outdir": td, "pvt": "125:1.62,-40:1.98", "seeds": "101,102"})
            mr.main_pvt(ns)
            dirs = sorted(p.name for p in Path(td).iterdir())
            self.assertEqual(len(dirs), 4)
            m = json.loads((Path(td) / dirs[0] / "manifest.json").read_text())
            req = json.loads((Path(td) / dirs[0] / "request.json").read_text())
            self.assertEqual(req["corners"]["temperature_c"], [m["temp_c"]])
            self.assertEqual(m["key"], dirs[0])
            self.assertEqual(m["netlist_sha256"],
                             hashlib.sha256((Path(td) / dirs[0] / "netlist.cir").read_bytes()).hexdigest())


class ReducerTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_full_matrix_is_complete(self):
        full_matrix(self.d)
        red = reduce_dir(self.d)
        self.assertEqual(len(red["cells"]), len(POINTS) * 3)
        self.assertTrue(all(c["status"] in ("inside", "outside") for c in red["cells"]))
        self.assertTrue(red["matrix_complete"])
        self.assertEqual(red["n_rows_unsuccessful"], 0)

    def test_empty_directory_is_not_complete(self):
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        self.assertTrue(all(c["status"] == "no_data" for c in red["cells"]))

    def test_missing_seed_is_not_complete(self):
        full_matrix(self.d)
        for suf in (".manifest.json", ".klt-sim.json"):
            (self.d / (x.pvt_key(125.0, 1.8, 104) + suf)).unlink()
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        c = next(c for c in red["cells"] if (c["temp_c"], c["vdd_v"], c["corner"]) == (125.0, 1.8, "tt"))
        self.assertEqual(c["missing_seeds"], [104])
        self.assertEqual(c["status"], "insufficient_seeds")   # 3 usable seeds < MIN_SEEDS

    def test_too_few_seeds_has_no_hamming(self):
        for s in SEEDS[:3]:
            fake_unit(self.d, 125.0, 1.8, s)
        red = reduce_dir(self.d)
        c = next(c for c in red["cells"] if (c["temp_c"], c["vdd_v"], c["corner"]) == (125.0, 1.8, "tt"))
        self.assertEqual(c["status"], "insufficient_seeds")
        self.assertIsNone(c["hamming"])

    def test_missing_corner_is_reported(self):
        full_matrix(self.d)
        # rewrite one unit without its ss corner
        key = x.pvt_key(-40.0, 1.62, 101)
        resp = json.loads((self.d / f"{key}.klt-sim.json").read_text())
        resp["corners"] = [c for c in resp["corners"] if c["process"] != "ss"]
        (self.d / f"{key}.klt-sim.json").write_text(json.dumps(resp))
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        self.assertTrue(any(r["status"] == "corner_missing" and r["process"] == "ss" for r in red["rows"]))

    def test_swapped_pvt_response_rejected(self):
        full_matrix(self.d)
        # response of (125 C, 1.62 V, seed 101) stored under (125 C, 1.98 V, seed 101)'s key
        a, b = x.pvt_key(125.0, 1.62, 101), x.pvt_key(125.0, 1.98, 101)
        (self.d / f"{b}.klt-sim.json").write_text((self.d / f"{a}.klt-sim.json").read_text())
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        bad = [r for r in red["rows"] if r["unit"] == b]
        self.assertTrue(bad and all(r["status"] == "pvt_mismatch" for r in bad))

    def test_swapped_temperature_rejected(self):
        full_matrix(self.d)
        key = x.pvt_key(125.0, 1.8, 101)
        resp = json.loads((self.d / f"{key}.klt-sim.json").read_text())
        for c in resp["corners"]:
            c["temperature_c"] = -40.0
        (self.d / f"{key}.klt-sim.json").write_text(json.dumps(resp))
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        self.assertTrue(any(r["unit"] == key and r["status"] == "pvt_mismatch" for r in red["rows"]))

    def test_wrong_supply_levels_rejected(self):
        full_matrix(self.d)
        # the deck really ran at 1.8 V but the manifest declares 1.62 V
        fake_unit(self.d, 125.0, 1.62, 101, resp_vdd=1.8)
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        self.assertTrue(any(r["unit"] == x.pvt_key(125.0, 1.62, 101) and r["status"] == "supply_mismatch"
                            for r in red["rows"]))

    def test_wrong_supply_threshold_extraction_is_not_silent(self):
        # a 1.62 V run read against a 1.8 V declaration must not yield bits
        with tempfile.TemporaryDirectory() as td:
            fake_unit(Path(td), 125.0, 1.8, 101, resp_vdd=1.62, nl_key=None)
            u = x.load_units(Path(td))[0]
            self.assertEqual(x.classify(u, "tt")["status"], "supply_mismatch")

    def test_failed_tool_responses(self):
        full_matrix(self.d)
        fake_unit(self.d, 125.0, 1.98, 102, state="failed", exit_code="87")
        fake_unit(self.d, 125.0, 1.98, 103, corner_status="error")
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        k2, k3 = x.pvt_key(125.0, 1.98, 102), x.pvt_key(125.0, 1.98, 103)
        self.assertTrue(all(r["status"] == "tool_fail" for r in red["rows"] if r["unit"] in (k2, k3)))
        c = next(c for c in red["cells"] if (c["temp_c"], c["vdd_v"], c["corner"]) == (125.0, 1.98, "tt"))
        self.assertEqual({u["seed"] for u in c["unsuccessful"]}, {102, 103})

    def test_missing_measurements_and_nonfinite(self):
        full_matrix(self.d)
        key = x.pvt_key(-40.0, 1.98, 101)
        resp = json.loads((self.d / f"{key}.klt-sim.json").read_text())
        resp["corners"][0]["measurements"][4]["value"] = None
        (self.d / f"{key}.klt-sim.json").write_text(json.dumps(resp))
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        self.assertTrue(any(r["unit"] == key and r["process"] == "tt" and r["status"] == "measurement_missing"
                            for r in red["rows"]))

    def test_invalid_samples_counted_and_too_few_valid(self):
        full_matrix(self.d)
        key = x.pvt_key(-40.0, 1.62, 102)
        resp = json.loads((self.d / f"{key}.klt-sim.json").read_text())
        for m in resp["corners"][0]["measurements"]:          # tt: one invalid sample -> 23 usable, still ok
            if m["name"] == "valid0":
                m["value"] = 0.0
        for m in resp["corners"][1]["measurements"]:          # ss: five invalid -> 19 usable < 23
            if m["name"].startswith("valid") and int(m["name"][5:]) < 5:
                m["value"] = 0.0
        (self.d / f"{key}.klt-sim.json").write_text(json.dumps(resp))
        red = reduce_dir(self.d)
        rows = {r["process"]: r for r in red["rows"] if r["unit"] == key}
        self.assertEqual(rows["tt"]["status"], "ok")
        self.assertEqual(rows["tt"]["n_invalid"], 1)
        self.assertEqual(rows["ss"]["status"], "too_few_valid")
        self.assertEqual(rows["ss"]["n_invalid"], 5)
        self.assertFalse(red["matrix_complete"])
        c = next(c for c in red["cells"] if (c["temp_c"], c["vdd_v"], c["corner"]) == (-40.0, 1.62, "ss"))
        self.assertEqual(c["n_invalid_samples"], 5)
        self.assertEqual(c["missing_seeds"], [102])

    def test_missing_manifest_response_and_collision(self):
        full_matrix(self.d)
        key = x.pvt_key(125.0, 1.62, 101)
        (self.d / f"{key}.manifest.json").unlink()
        k2 = x.pvt_key(125.0, 1.8, 101)
        (self.d / f"{k2}.klt-sim.json").unlink()
        # same identity under another file name
        fake_unit(self.d, 125.0, 1.98, 101, key="pvt_125C_1.98V_Ts100ns_seed101")
        man = json.loads((self.d / "pvt_125C_1.98V_Ts100ns_seed101.manifest.json").read_text())
        man["key"] = "pvt_alias"
        (self.d / "pvt_alias.manifest.json").write_text(json.dumps(man))
        (self.d / "pvt_alias.klt-sim.json").write_text((self.d / "pvt_125C_1.98V_Ts100ns_seed101.klt-sim.json").read_text())
        red = reduce_dir(self.d)
        self.assertFalse(red["matrix_complete"])
        st = {(r["unit"]): r["status"] for r in red["rows"] if r["process"] == "tt"}
        self.assertEqual(st[key], "bad_unit")
        self.assertEqual(st[k2], "bad_unit")

    def test_undeclared_point_cannot_be_pooled_into_complete(self):
        full_matrix(self.d)
        for s in SEEDS:
            fake_unit(self.d, 27.0, 1.8, s)
        red = reduce_dir(self.d)
        self.assertEqual(red["undeclared_points"], [(27.0, 1.8)])
        self.assertFalse(red["matrix_complete"])

    def test_cells_are_keyed_by_pvt(self):
        full_matrix(self.d)
        red = reduce_dir(self.d)
        keys = {(c["corner"], c["temp_c"], c["vdd_v"]) for c in red["cells"]}
        self.assertEqual(len(keys), len(red["cells"]))
        c = next(c for c in red["cells"] if (c["temp_c"], c["vdd_v"], c["corner"]) == (125.0, 1.62, "tt"))
        self.assertEqual(c["usable_seeds"], list(SEEDS))
        self.assertEqual(c["calibration_records"]["combining"],
                         x.brb.calibration(125.0, 1.62, "tt")["combining_record"])

    def test_reduction_is_deterministic(self):
        full_matrix(self.d)
        a = json.dumps(reduce_dir(self.d), sort_keys=True, default=list)
        b = json.dumps(reduce_dir(self.d), sort_keys=True, default=list)
        self.assertEqual(a, b)

    def test_ingest_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as rq:
            u = Path(rq) / "pvt_125C_1.8V_Ts100ns_seed101"
            u.mkdir()
            (u / "manifest.json").write_text("{}")
            (u / "resp.json").write_text("{}")
            x.ingest(Path(rq), self.d)
            with self.assertRaises(SystemExit):
                x.ingest(Path(rq), self.d)

    def test_committed_pvt_directory_never_reports_complete_without_all_units(self):
        red = x.reduce_units(x.load_units(), ensemble=20)
        n_ok = sum(r["status"] == "ok" for r in red["rows"])
        if n_ok < len(POINTS) * len(SEEDS) * 3:
            self.assertFalse(red["matrix_complete"])


class ExistingEvidenceUntouched(unittest.TestCase):
    def test_nominal_loader_ignores_pvt_directory(self):
        # the nominal cross-check globs transistor/seed*.klt-sim.json only
        self.assertEqual(x.brb.XCHECK_PVT, (27.0, 1.8))
        self.assertTrue(x.PVT_DIR.parent == x.brb.TRANSISTOR_DIR)


if __name__ == "__main__":
    unittest.main()
