#!/usr/bin/env python3
"""Unit tests for sim/ro-vth-drift-sensitivity/ (issue #254).

No simulator and no PDK: wrapper generation on text, the coverage manifest, the metric
derivations on synthetic crossings, fail-closed row handling, the calibration artifact and
its negative tests (missing key, schema/source-hash mismatch, forced time-zero fallback).

    python3 sim/tests/test_vth_drift.py
"""
import copy
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SLUG = REPO / "sim" / "ro-vth-drift-sensitivity"
sys.path.insert(0, str(SLUG))
sys.path.insert(0, str(SLUG / "analysis"))
import aging  # noqa: E402
import campaign as C  # noqa: E402
import sensitivity as S  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BRB = _load(REPO / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py", "brb_t")

NFET = ("XMn y a ny vss sky130_fd_pr__nfet_01v8 L=0.15 W=0.42 nf=1 ad=0.1218 as=0.1218 pd=1.42 ps=1.42 nrd=0.69047619047619\n"
        "+ nrs=0.69047619047619 sa=0 sb=0 sd=0 mult=1 m=1")
PFET = ("XMph py vss vddr vddr sky130_fd_pr__pfet_01v8 L=lstv W=wstv nf=1 ad='int((1 + 1)/2) * wstv / 1 * 0.29'\n"
        "+ as='int((1 + 2)/2) * wstv / 1 * 0.29' pd='2*int((1 + 1)/2) * (wstv / 1 + 0.29)'\n"
        "+ ps='2*int((1 + 2)/2) * (wstv / 1 + 0.29)' nrd='0.29 / wstv ' nrs='0.29 / wstv ' sa=0 sb=0 sd=0 mult=1 m=1")
SAMPLE = ".subckt t a y vddr vss\n" + NFET + "\n" + PFET + "\nCld y vss 'cld' m=1\n.ends\n"


class WrapperTests(unittest.TestCase):
    def test_signed_wrappers_and_preservation(self):
        aged, rep = aging.age_netlist(SAMPLE)
        self.assertEqual((rep["wrapped_nfet"], rep["wrapped_pfet"]), (1, 1))
        # NMOS gets +1 * dVtn knob (gate lowered), PMOS gets -1 * dVtp knob (gate raised)
        self.assertIn(f"Esh g gd {aging.KNOB_N} 0 1\n", aged)
        self.assertIn(f"Esh g gd {aging.KNOB_P} 0 -1\n", aged)
        self.assertIn("XMn y a ny vss vth_wrap_nfet L=0.15", aged)
        self.assertIn("XMph py vss vddr vddr vth_wrap_pfet L=lstv", aged)
        # every net and parameter byte survives: undoing the model-token swap gives the source back
        self.assertEqual(aging.unwrap(aged), SAMPLE)

    def test_deterministic(self):
        self.assertEqual(aging.age_netlist(SAMPLE), aging.age_netlist(SAMPLE))

    def test_committed_designs_roundtrip_and_are_untouched(self):
        for rel in ("design/ro_ring5.spice", "design/ro_array_core.spice"):
            text = (REPO / rel).read_text()
            aged, rep = aging.age_netlist(text)
            self.assertEqual(aging.unwrap(aged), text, rel)
            self.assertGreater(rep["wrapped_nfet"], 0)
            self.assertNotIn("vth_wrap", text)
            # only the two definition lines of the pinned models remain un-redirected
            self.assertEqual(aged.count("sky130_fd_pr__"), 2)

    def test_rejects_unsupported_shapes(self):
        bad = [
            SAMPLE.replace("sky130_fd_pr__nfet_01v8", "sky130_fd_pr__nfet_01v8_lvt"),          # other device
            SAMPLE.replace("sd=0 mult=1 m=1\n", "sd=0 mult=1\n", 1),                           # dropped param (m)
            SAMPLE.replace("XMn y a ny vss", "XMn y a ny"),                                    # wrong net count
            SAMPLE.replace("nf=1 ad=0.1218", "nf=1 foo=2 ad=0.1218"),                          # extra param
            ".subckt t a\nR1 a b 1k\n.ends\n",                                                # nothing to wrap
        ]
        for text in bad:
            with self.assertRaises(aging.UnsupportedDevice, msg=text[:60]):
                aging.age_netlist(text)

    def test_wrapper_definition_covers_param_set(self):
        d = aging.wrapper_definition()
        for p in aging.PARAMS:
            self.assertIn(f"{p}={p}", d)
        self.assertIn(".global vth_dvn vth_dvp", d)


class ManifestTests(unittest.TestCase):
    def test_size_and_committed_manifest(self):
        keys = C.required_keys()
        self.assertEqual(len(keys), 2 * 3 * 3 * 3 * 4 + 6)
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(json.loads((SLUG / "coverage-manifest.json").read_text()), json.loads(json.dumps(C.manifest())))
        self.assertEqual(S.check_manifest(), 0)

    def test_asymmetric_keys_present_only_for_array_at_headline(self):
        keys = set(C.required_keys())
        self.assertIn(C.key_str("array", "ss", -40.0, 1.62, 60, 0), keys)
        self.assertIn(C.key_str("array", "ff", -40.0, 1.98, 0, 60), keys)
        self.assertNotIn(C.key_str("ring5", "tt", 27.0, 1.8, 60, 0), keys)
        self.assertNotIn(C.key_str("array", "tt", -40.0, 1.8, 60, 0), keys)

    def test_missing_duplicate_unexpected_keys_fail(self):
        keys = C.required_keys()
        self.assertEqual(C.check_coverage(keys), [])
        self.assertTrue(any("missing" in p for p in C.check_coverage(keys[1:])))
        dup = keys + [keys[0]]
        self.assertTrue(any("duplicate" in p for p in C.check_coverage(dup)))
        extra = keys + ["array|tt|27C|1.8V|99|99"]
        self.assertTrue(any("unexpected" in p for p in C.check_coverage(extra)))
        # a missing shift row (one shifted point absent) must fail
        miss = [k for k in keys if k != C.key_str("ring5", "tt", 27.0, 1.8, 40, 40)]
        self.assertTrue(any("missing" in p and "|40|40" in p for p in C.check_coverage(miss)))


class DeckTests(unittest.TestCase):
    def test_build_is_deterministic_and_keeps_source_contract(self):
        a = C.build_deck("ring5", 1.8)
        b = C.build_deck("ring5", 1.8)
        self.assertEqual(a[0], b[0])
        nl, meas, info = a
        self.assertIn(".option seed=1", nl)                    # source seed kept
        self.assertIn("trnoise(2.0e-3 2e-10 0 0)", nl)         # source noise calibration kept
        self.assertEqual([m["name"] for m in meas if m["name"].startswith("tk")], [f"tk{k}" for k in range(2, 23)])
        self.assertTrue(any(m["name"] == "dvn_rb" for m in meas))
        self.assertEqual(info["tmax"], "20p")
        self.assertGreaterEqual(float(info["stop"].rstrip("n")), 115)

    def test_unwrapped_control_has_no_wrapper_or_knob(self):
        nl, meas, _ = C.build_deck("array", 1.8, wrap=False)
        self.assertNotIn("vth_wrap", nl)
        self.assertNotIn("vth_dvn", nl)
        self.assertFalse(any(m["name"].endswith("_rb") for m in meas))

    def test_request_zips_both_knobs_independently(self):
        req, nl, plan = C.make_request("array", ["ss"], -40.0, 1.62, list(C.ASYM_SHIFTS_MV))
        sv = req["corners"]["supply_v"]
        self.assertEqual(sv["Vdvn"], [0.06, 0.0])
        self.assertEqual(sv["Vdvp"], [0.0, 0.06])
        self.assertEqual(plan["keys"], [C.key_str("array", "ss", -40.0, 1.62, 60, 0), C.key_str("array", "ss", -40.0, 1.62, 0, 60)])

    def test_committed_inputs_match_generator(self):
        # shift axis is independent of the netlist: one netlist per (deck, Vdd)
        n1 = C.build_deck("ring5", 1.62)[0]
        n2 = C.build_deck("ring5", 1.98)[0]
        self.assertNotEqual(n1, n2)


def synth_ring(tbar=2.4e-9, jitter=None):
    m = {f"tk{k}": 5e-9 + (k - 2) * tbar + (jitter[k - 2] if jitter else 0.0) for k in range(2, 23)}
    m.update(vmax_ss=1.6, vmin_ss=-0.02, _vdd=1.8)
    return m


class MetricTests(unittest.TestCase):
    def test_ring_metrics_noise_free(self):
        r = S.ring_metrics(synth_ring(), None)
        self.assertAlmostEqual(r["tbar"], 2.4e-9, 18)
        self.assertLess(r["sigma_1"], 1e-18)
        self.assertAlmostEqual(r["swing_frac"], 1.62 / 1.8, 9)

    def test_sigma_and_q_ring_and_floor(self):
        j = [(-1) ** k * 1e-12 for k in range(21)]
        r = S.ring_metrics(synth_ring(jitter=j), None)
        self.assertGreater(r["sigma_1"], 1e-12)
        r2 = S.ring_metrics(synth_ring(jitter=j), 0.5e-12)
        self.assertAlmostEqual(r2["sigma_1_raw"], r["sigma_1"], 24)
        self.assertAlmostEqual(r2["sigma_1_corrected"], math.sqrt(r["sigma_1"] ** 2 - 0.25e-24), 18)
        self.assertAlmostEqual(r2["q_ring"], r2["sigma_1_corrected"] ** 2 * S.AS.T_S_TARGET / r2["tbar"] ** 3, 12)
        # floor larger than the estimate clamps at zero (array-sizing convention)
        self.assertEqual(S.ring_metrics(synth_ring(jitter=j), 1e-9)["sigma_1_corrected"], 0.0)

    def test_closeness_reports_pair_and_rational(self):
        # periods chosen so ring 1 / ring 3 is exactly 3/2
        c = S.closeness([3.0, 2.9, 2.0, 2.7])
        self.assertEqual(c["pair"], [1, 3])
        self.assertAlmostEqual(c["distance"], 0.0, 12)
        self.assertIn(c["rational"], ("3/2", "2/3"))
        far = S.closeness([2.4e-9, 2.3e-9, 2.2e-9, 2.1e-9])
        self.assertGreater(far["distance"], 0.0)
        self.assertEqual(len(far["pair"]), 2)

    def test_crossing_interpolation(self):
        pts = [{"shift_mv": s, "x": v} for s, v in zip((0, 20, 40, 60), (1.0, 0.9, 0.8, 0.7))]
        self.assertAlmostEqual(S._crossing(pts, "x", 0.85), 30.0)
        self.assertIsNone(S._crossing(pts, "x", 0.5))
        self.assertEqual(S._crossing(pts, "x", 1.5), 0.0)


def fake_resp(deck, vdd, units, status="pass", rb_error=False):
    corners = []
    for proc, dvn, dvp in units:
        meas = {} if deck == "ring5" else {}
        corners.append({"process": proc, "temperature_c": 27.0, "status": status,
                        "supply_v": {"Vdvn": dvn, "Vdvp": dvp}, "diagnostics": [],
                        "measurements": [{"name": "dvn_rb", "value": dvn + (1e-3 if rb_error else 0.0)},
                                         {"name": "dvp_rb", "value": dvp}] +
                                        [{"name": f"tk{k}", "value": 5e-9 + (k - 2) * 2.4e-9 * (1 + 2 * dvn)} for k in range(2, 23)] +
                                        [{"name": "vmax_ss", "value": 1.6}, {"name": "vmin_ss", "value": 0.0}]})
    return {"corners": corners, "environment": {"remote": {"job_id": "job-x"}}}


class SelectionTests(unittest.TestCase):
    def _row(self, key, request, ok):
        return {"key": key, "request": request, "ok": ok, "job_id": "j", "problems": [] if ok else ["no value"]}

    def test_retry_replaces_failed_original_and_is_recorded(self):
        k = C.key_str("ring5", "ss", 27.0, 1.62, 40, 40)
        acc, att, probs = S.select_rows([self._row(k, "ring5-a", False), self._row(k, "ring5-a--r1", True)])
        self.assertEqual(probs, [])
        self.assertEqual(len(acc), 1)
        self.assertEqual(acc[0]["request"], "ring5-a--r1")
        self.assertEqual(att[0]["request"], "ring5-a")

    def test_unretried_failure_stays_failed(self):
        k = C.key_str("ring5", "ss", 27.0, 1.62, 40, 40)
        acc, att, probs = S.select_rows([self._row(k, "ring5-a", False)])
        self.assertFalse(acc[0]["ok"])

    def test_duplicate_originals_and_redundant_retry_are_problems(self):
        k = C.key_str("ring5", "ss", 27.0, 1.62, 40, 40)
        _a, _t, p1 = S.select_rows([self._row(k, "ring5-a", True), self._row(k, "ring5-b", True)])
        self.assertTrue(any("duplicate" in x for x in p1))
        _a, _t, p2 = S.select_rows([self._row(k, "ring5-a", True), self._row(k, "ring5-a--r1", True)])
        self.assertTrue(any("usable" in x for x in p2))
        _a, _t, p3 = S.select_rows([self._row(k, "ring5-a--r1", True)])
        self.assertTrue(any("without an original" in x for x in p3))


class RowTests(unittest.TestCase):
    def test_rows_and_pairing_with_zero_shift(self):
        resp = fake_resp("ring5", 1.8, [("tt", 0.0, 0.0), ("tt", 0.02, 0.02)])
        rows = S.rows_from_response("r", {"deck": "ring5", "vdd_v": 1.8}, resp, None)
        self.assertTrue(all(r["ok"] for r in rows))
        self.assertEqual(S.pair_rows(rows), [])
        self.assertEqual(rows[1]["zero_shift_key"], rows[0]["key"])
        self.assertGreater(rows[1]["delta"]["tbar"]["rel"], 0)
        self.assertEqual(rows[1]["key"], C.key_str("ring5", "tt", 27.0, 1.8, 20, 20))

    def test_unapplied_shift_is_rejected(self):
        # read-back differs from the request: that row would silently be time zero
        resp = fake_resp("ring5", 1.8, [("tt", 0.02, 0.02)], rb_error=True)
        rows = S.rows_from_response("r", {"deck": "ring5", "vdd_v": 1.8}, resp, None)
        self.assertFalse(rows[0]["ok"])
        self.assertTrue(any("read-back" in p for p in rows[0]["problems"]))

    def test_failed_corner_is_recorded_not_dropped(self):
        resp = fake_resp("ring5", 1.8, [("tt", 0.0, 0.0)], status="error")
        rows = S.rows_from_response("r", {"deck": "ring5", "vdd_v": 1.8}, resp, None)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])

    def test_missing_zero_shift_row_is_a_problem(self):
        resp = fake_resp("ring5", 1.8, [("tt", 0.02, 0.02)])
        rows = S.rows_from_response("r", {"deck": "ring5", "vdd_v": 1.8}, resp, None)
        self.assertTrue(any("no zero-shift row" in p for p in S.pair_rows(rows)))


def synth_artifact(tmp: Path):
    """A minimal record + artifact pair in a temp repo root, for the behavioral consumer."""
    rid = "20260101-000000-test"
    rows = []
    ent = {}
    for s in (0, 20):
        rr = {"key": C.key_str("ring5", "tt", 27.0, 1.8, s, s), "job_id": "j1", "metrics": {"x": s}}
        ra = {"key": C.key_str("array", "tt", 27.0, 1.8, s, s), "job_id": "j2",
              "metrics": {"edge_retention": 0.6, "tr1": 2.5e-9}}
        rows += [rr, ra]
        ent[S.cal_key("tt", 27.0, 1.8, s, s)] = {
            "T_0": 2.4e-9 * (1 + s / 100), "sigma_1_raw": 3e-12, "sigma_1_corrected": 2.5e-12, "numerical_floor": 6e-13,
            "q_ring": 1e-3, "q_ring_t_s": 1e-6, "array_periods_s": [2.9e-9, 2.7e-9, 2.6e-9, 2.4e-9],
            "lock_proximity": {"pair": [1, 4], "rational": "3/4", "distance": 0.1},
            "source_rows": {"ring5": {"key": rr["key"], "row_sha256": S.sha256_json(rr), "job_id": "j1"},
                            "array": {"key": ra["key"], "row_sha256": S.sha256_json(ra), "job_id": "j2"}}}
    art = {"schema": S.CAL_SCHEMA, "source_record": rid, "entries": ent}
    rec_dir = tmp / "sim" / "ro-vth-drift-sensitivity" / "records"
    rec_dir.mkdir(parents=True)
    (rec_dir / f"{rid}.json").write_text(json.dumps({"rows": rows}))
    ap = tmp / "art.json"
    ap.write_text(json.dumps(art))
    return ap, rid, rec_dir / f"{rid}.json"


class CalibrationConsumerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = Path(self.td.name)
        self.art, self.rid, self.rec = synth_artifact(self.tmp)
        self._old = BRB.REPO_ROOT
        BRB.REPO_ROOT = self.tmp

    def tearDown(self):
        BRB.REPO_ROOT = self._old
        self.td.cleanup()

    def test_consumes_matching_key(self):
        cal = BRB.calibration(27.0, 1.8, "tt", shift_mv=(20, 20), artifact=self.art)
        self.assertEqual(cal["periods_s"], [2.9e-9, 2.7e-9, 2.6e-9, 2.4e-9])
        self.assertEqual(cal["sigma"][1], 2.5e-12)
        self.assertEqual(cal["shift_mv"], [20.0, 20.0])
        self.assertAlmostEqual(cal["tbar_ring5_s"], 2.4e-9 * 1.2)
        # the zero-shift entry is a different, explicit entry (not the historical records)
        z = BRB.calibration(27.0, 1.8, "tt", shift_mv=(0, 0), artifact=self.art)
        self.assertEqual(z["combining_record"], self.rid)

    def test_missing_shift_key_rejected(self):
        for shift in ((40, 40), (60, 0), (20, 0)):
            with self.assertRaises(SystemExit) as cm:
                BRB.calibration(27.0, 1.8, "tt", shift_mv=shift, artifact=self.art)
            self.assertIn("no entry for shift key", str(cm.exception))
        with self.assertRaises(SystemExit):
            BRB.calibration(27.0, 1.8, "ss", shift_mv=(20, 20), artifact=self.art)        # other corner
        with self.assertRaises(SystemExit):
            BRB.calibration(-40.0, 1.8, "tt", shift_mv=(20, 20), artifact=self.art)       # other PVT

    def test_forced_time_zero_fallback_rejected(self):
        with self.assertRaises(SystemExit):
            BRB.calibration(27.0, 1.8, "tt", artifact=self.art)                           # artifact, no shift
        with self.assertRaises(SystemExit):
            BRB.calibration(27.0, 1.8, "tt", shift_mv=(20, 20))                           # shift, no artifact
        with self.assertRaises(SystemExit):
            BRB.calibration(27.0, 1.8, "tt", shift_mv=(20, 20), artifact=self.tmp / "nope.json")

    def test_source_hash_mismatch_rejected(self):
        rec = json.loads(self.rec.read_text())
        rec["rows"][2]["metrics"]["x"] = 999                                              # tamper with a cited row
        self.rec.write_text(json.dumps(rec))
        with self.assertRaises(SystemExit) as cm:
            BRB.calibration(27.0, 1.8, "tt", shift_mv=(20, 20), artifact=self.art)
        self.assertIn("source-hash mismatch", str(cm.exception))

    def test_schema_mismatch_rejected(self):
        a = json.loads(self.art.read_text())
        a["schema"] = "vth-drift-calibration/0"
        self.art.write_text(json.dumps(a))
        with self.assertRaises(SystemExit):
            BRB.calibration(27.0, 1.8, "tt", shift_mv=(0, 0), artifact=self.art)

    def test_entry_citing_wrong_source_row_rejected(self):
        a = json.loads(self.art.read_text())
        k = S.cal_key("tt", 27.0, 1.8, 20, 20)
        a["entries"][k]["source_rows"]["ring5"]["key"] = C.key_str("ring5", "tt", 27.0, 1.8, 0, 0)    # points at time zero
        self.art.write_text(json.dumps(a))
        with self.assertRaises(SystemExit):
            BRB.calibration(27.0, 1.8, "tt", shift_mv=(20, 20), artifact=self.art)

    def test_unshifted_historical_path_unchanged(self):
        # without artifact/shift the original signature and behaviour are untouched
        BRB.REPO_ROOT = self._old
        cal = BRB.calibration(27.0, 1.8, "tt")
        self.assertIn("20260825", cal["combining_record"])


class ReplayTests(unittest.TestCase):
    def test_matched_seed_label_carries_no_shift(self):
        rp = _load(SLUG / "analysis/behavioral_replay.py", "rp_t")
        self.assertNotIn("20", rp.label("tt", 27.0, 1.8).replace("27", "").replace("1.8", "").replace("Ts20us", ""))
        self.assertEqual(rp.label("tt", 27.0, 1.8), rp.label("tt", 27.0, 1.8))
        self.assertEqual(BRB.sub_seed(rp.label("tt", 27.0, 1.8)), BRB.sub_seed(rp.label("tt", 27.0, 1.8)))


class RecordImmutabilityTests(unittest.TestCase):
    def test_existing_records_untouched(self):
        script = REPO / "sim/bin/check_records_append_only.py"
        have = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", "-q", "origin/main"], capture_output=True)
        if have.returncode != 0:
            self.skipTest("origin/main not available")
        r = subprocess.run([sys.executable, str(script), "origin/main"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class DocTests(unittest.TestCase):
    def test_claim_sentence_in_readme_and_analysis(self):
        self.assertIn(S.SENTENCE, (SLUG / "README.md").read_text())
        self.assertIn(S.SENTENCE, (SLUG / "analysis/sensitivity.py").read_text())


if __name__ == "__main__":
    unittest.main()
