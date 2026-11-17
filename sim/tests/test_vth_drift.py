#!/usr/bin/env python3
"""Unit tests for sim/ro-vth-drift-sensitivity/ (issue #254).

No simulator and no PDK: wrapper generation on text, the coverage manifest, the metric
derivations on synthetic crossings, fail-closed row handling, the calibration artifact and
its negative tests (missing key, schema/source-hash mismatch, forced time-zero fallback),
and the controls-pin refusal (issue #498): both digests reported at runtime, the
discriminating checks named, the kind/pass gate still firing first.

    python3 sim/tests/test_vth_drift.py
"""
import copy
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(REPO / "sim" / "bin"))
from loadmod import load_module  # noqa: E402
from recorddiff import field_diff  # noqa: E402
import lock_proximity as LP  # noqa: E402


BRB = load_module("brb_t", REPO / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py")

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
        self.assertEqual(c["rational"], "3/2")          # issue #467: slower/faster, never "2/3"
        far = S.closeness([2.4e-9, 2.3e-9, 2.2e-9, 2.1e-9])
        self.assertGreater(far["distance"], 0.0)
        self.assertEqual(len(far["pair"]), 2)

    def test_closeness_is_the_shared_dr0005_rule(self):
        """Issue #467: this analysis used an order-dependent form of its own, and
        enumerated pairs in ring-index order, so the stored `lock_proximity`
        carried a convention that is not DR-0005's.  The rule itself is pinned
        in sim/tests/test_lock_proximity.py; what is asserted here is that
        sensitivity.py uses it, end to end."""
        self.assertIs(S.lock_closeness, LP.closeness)
        T = [2.4e-9, 2.9e-9, 2.1e-9, 2.7e-9]            # deliberately not ascending
        self.assertAlmostEqual(S.closeness(T)["distance"], S.closeness(list(reversed(T)))["distance"])
        # every reported rational is written slower/faster
        for periods in (T, [3.0, 2.9, 2.0, 2.7], [2.4e-9, 2.3e-9, 2.2e-9, 2.1e-9]):
            p_, q_ = (int(x) for x in S.closeness(periods)["rational"].split("/"))
            self.assertGreaterEqual(p_, q_)

    def test_dr0005_known_answer_end_to_end(self):
        # DR-0005 section 2: span 1.2096 against 4/3 -> 9.3 %, whichever ring is first
        for T in ([1.0, 1.2096, 9.0, 31.0], [1.2096, 1.0, 9.0, 31.0]):
            c = S.closeness(T)
            self.assertAlmostEqual(c["distance"] * 100, 9.28, places=1)
            self.assertEqual(c["rational"], "4/3")

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
        rp = load_module("rp_t", SLUG / "analysis/behavioral_replay.py")
        self.assertNotIn("20", rp.label("tt", 27.0, 1.8).replace("27", "").replace("1.8", "").replace("Ts20us", ""))
        self.assertEqual(rp.label("tt", 27.0, 1.8), rp.label("tt", 27.0, 1.8))
        self.assertEqual(BRB.sub_seed(rp.label("tt", 27.0, 1.8)), BRB.sub_seed(rp.label("tt", 27.0, 1.8)))


class LockProximityCorrectionTests(unittest.TestCase):
    """The DR-0005 convention correction and its superseding record (issue #467)."""

    SUPERSEDED = "20261010-175052-7e279ab"
    SUPERSEDING = "20261113-150554-fb302c35"
    #: The ONLY fields the DR-0005 convention correction may move -- every one of
    #: them is the lock-proximity figure or a direct copy of it.  Anything else
    #: appearing in the diff is a regression, not a correction.
    LOCK_FIELDS = {
        "rows[].metrics.lock_proximity.distance",
        "rows[].metrics.lock_proximity.rational",
        "rows[].metrics.lock_proximity.meaning",
        "rows[].delta.lock_distance.abs",
        "summary.envelope.rows[].points[].lock_distance",
        "summary.asymmetric[].lock_distance.zero",
        "summary.asymmetric[].lock_distance.n60",
        "summary.asymmetric[].lock_distance.p60",
        "summary.asymmetric[].lock_distance.both60",
    } | {f"summary.lock_by_shift.{s}.{f}" for s in (0, 20, 40, 60)
         for f in ("distance", "rational", "pair", "corner", "temp_c", "vdd_v")}

    @classmethod
    def _rec(cls, rid):
        return SLUG / "records" / f"{rid}.json"

    def _rereduce(self, rid):
        rec = json.load(open(self._rec(rid)))
        chunks = S.load_committed(str(SLUG / "corners" / rid))
        rows, summ = S.build(chunks, rec["controls_record"])
        return rec, json.loads(json.dumps(rows, default=str)), json.loads(json.dumps(summ, default=str))

    def test_superseding_record_replays_and_names_its_original(self):
        rec = json.load(open(self._rec(self.SUPERSEDING)))
        self.assertEqual(rec["supersedes"], self.SUPERSEDED)
        self.assertEqual(S.check(str(self._rec(self.SUPERSEDING))), 0)
        self.assertIn(f"- Supersedes: {self.SUPERSEDED}",
                      (SLUG / "records" / f"{self.SUPERSEDING}.md").read_text())

    def test_correction_moves_only_the_lock_proximity_fields(self):
        """Re-reducing the superseded record's own committed responses differs
        from what is stored ONLY in the lock-proximity fields -- and does differ
        in at least one of them.  The superseded record itself is never edited,
        so its own `--check` now reports DIFFER by design."""
        rec, rows, summ = self._rereduce(self.SUPERSEDED)
        diff = set(field_diff(rows, rec["rows"], S._replay_equal, "rows")) | \
            set(field_diff(summ, json.loads(json.dumps(rec["summary"], default=str)),
                           S._replay_equal, "summary"))
        self.assertTrue(diff, "nothing changed; the correction did not reach this record")
        self.assertEqual(diff - self.LOCK_FIELDS, set(),
                         "the correction moved fields outside the lock-proximity set")
        self.assertEqual(S.check(str(self._rec(self.SUPERSEDED))), 1,
                         "the superseded record must no longer replay; it carries the old convention")

    def test_the_grid_minimum_moved_to_the_dr0005_convention(self):
        """Issue #467's stated outcome: 6.55 % -> 6.15 %, rational 3/4 -> 4/3."""
        def grid_min(rid):
            rec = json.load(open(self._rec(rid)))
            return min((r["metrics"]["lock_proximity"]["distance"], r["metrics"]["lock_proximity"]["rational"])
                       for r in rec["rows"] if "lock_proximity" in r.get("metrics", {}))
        self.assertEqual(len(grid_min(self.SUPERSEDED)), 2)
        self.assertAlmostEqual(grid_min(self.SUPERSEDED)[0] * 100, 6.55, places=2)
        self.assertEqual(grid_min(self.SUPERSEDED)[1], "3/4")
        self.assertAlmostEqual(grid_min(self.SUPERSEDING)[0] * 100, 6.15, places=2)
        self.assertEqual(grid_min(self.SUPERSEDING)[1], "4/3")
        # sim/ro-vth-drift-sensitivity/README.md's "stays above 6 %" still holds.
        self.assertGreater(grid_min(self.SUPERSEDING)[0], 0.06)

    def test_controls_and_behavioral_records_are_not_superseded(self):
        """They carry no lock-proximity field, so the correction does not reach them."""
        for rid in ("20261010-164921-7e279ab", "20261010-175419-7e279ab"):
            with self.subTest(record=rid):
                body = self._rec(rid).read_text()
                self.assertNotIn("lock_proximity", body)
                self.assertIn(json.loads(body).get("supersedes"), (None, "(none)"))
        self.assertEqual(S.check(str(self._rec("20261010-164921-7e279ab"))), 0)


class ControlsPinRefusalTests(unittest.TestCase):
    """Issue #498: the controls-pin refusal in emit_record names both digests it
    compared and the checks that discriminate a bytes-only refactor from a
    behaviour change, and refuses on exactly the same inputs as the old one-line
    guard (comparison, accepted ctl_rid set, non-zero exit all unchanged)."""

    OTHER = "not the bytes any pinned file ever had\n"

    def _temp_slugdir(self, *, aging_pin=None, campaign_pin=None):
        """A temp SLUGDIR holding synthetic campaign.py/aging.py and a PASSing
        kind: controls record citing the given pins; None pins the file's real
        current digest.  Every digest is derived at runtime, never a literal."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "records").mkdir()
        (root / "campaign.py").write_text("# synthetic campaign.py for the controls-pin refusal test\n")
        (root / "aging.py").write_text("# synthetic aging.py for the controls-pin refusal test\n")
        rid = "20990101-000000-synthpin"
        rec = {"kind": "controls", "pass": True, "provenance": {
            "generator_sha256": campaign_pin if campaign_pin is not None else aging.sha256_file(root / "campaign.py"),
            "aging_sha256": aging_pin if aging_pin is not None else aging.sha256_file(root / "aging.py")}}
        (root / "records" / f"{rid}.json").write_text(json.dumps(rec))
        return root, rid

    def _emit(self, root, rid):
        prev = S.SLUGDIR
        S.SLUGDIR = root
        self.addCleanup(setattr, S, "SLUGDIR", prev)
        with self.assertRaises(SystemExit) as cm:           # the guard raises before load_reqdir
            S.emit_record("/nonexistent-request-dir", rid)  # so a missing reqdir writes nothing
        return str(cm.exception.code)

    def test_aging_mismatch_reports_both_digests_and_the_discriminating_checks(self):
        wrong = aging.sha256_text(self.OTHER)
        root, rid = self._temp_slugdir(aging_pin=wrong)
        msg = self._emit(root, rid)
        self.assertIn(f"pinned by {rid}: {wrong}", msg)
        self.assertIn(f"current aging.py: {aging.sha256_file(root / 'aging.py')}", msg)
        self.assertNotIn("current campaign.py:", msg)       # only the failing leg is reported
        self.assertIn("does not by itself mean the generator's behaviour changed", msg)
        self.assertIn("sensitivity.py --check RECORD.json", msg)
        self.assertIn("layout/test_hashing.py", msg)
        self.assertIn("this study's README.md", msg)         # -> the pin-history section
        self.assertIn("re-run the controls campaign", msg)   # the behaviour-changed remedy
        self.assertIn("controls re-run is needed for a bytes-only move", msg)

    def test_matching_pins_pass_the_digest_leg(self):
        root, rid = self._temp_slugdir()                    # pins = the real current digests
        msg = self._emit(root, rid)
        # past the digest leg, the empty synthetic reqdir refuses much later, with
        # the incomplete-grid message -- pinning "refuses on the same inputs as
        # before", not just the new wording
        self.assertNotIn("bytes differ from the digest pinned", msg)
        self.assertIn("grid incomplete or has failed rows", msg)

    def test_campaign_mismatch_names_campaign_not_aging(self):
        wrong = aging.sha256_text(self.OTHER)
        root, rid = self._temp_slugdir(campaign_pin=wrong)
        msg = self._emit(root, rid)
        self.assertIn(f"pinned by {rid}: {wrong}", msg)
        self.assertIn(f"current campaign.py: {aging.sha256_file(root / 'campaign.py')}", msg)
        self.assertNotIn("current aging.py:", msg)

    def test_non_controls_ctl_rid_is_refused_before_the_digest_leg(self):
        # a sensitivity record as ctl_rid is refused one check earlier, with the
        # kind/pass message, never the digest one (real records; read-only)
        with self.assertRaises(SystemExit) as cm:
            S.emit_record("/nonexistent-request-dir", "20261113-150554-fb302c35")
        msg = str(cm.exception.code)
        self.assertIn("not a PASSing controls record", msg)
        self.assertNotIn("bytes differ", msg)


class ReplayToleranceTests(unittest.TestCase):
    """Issue #519: the replay equality and the cross-version property it must keep.

    `sensitivity.py --check` compares floats through the shared `replay_equal`
    (sim/bin/replay_equal.py, rel=1e-9) instead of exact equality: builtin float
    `sum()` is naive on CPython <= 3.11 and compensated on >= 3.12, so a record
    minted on one side of the split re-derives ~1-ulp different on the other and
    an exact replay verdict was a function of the interpreter.
    """

    #: Residual operands of `ring_metrics`' sigma construct (`sum(x * x for x in r)`,
    #: sensitivity.py's `sigma_k` line), sized so the naive and the compensated
    #: reductions of the same crossings differ.
    R = [0.0001234567890123, -0.00009876543210987, 0.000045678901234, -0.000012345678901] * 7

    @classmethod
    def _sigma(cls, s):
        """`ring_metrics`' sigma line verbatim for k = 1."""
        return math.sqrt((s / len(cls.R)) / (1 - 1 / 20))

    def test_replay_gate_absorbs_the_cpython_sum_split_and_still_bites(self):
        """The delta the version split produces -- ~1 ulp in sigma -- is inside the
        replay gate on any interpreter, while a >= 1e-6 relative change is still a
        difference and 1e-12 relative is not (the measured gate boundary).

        The naive `+=` reduction and `math.fsum` ARE the two sides the split
        produces (builtin `sum()` equals the former on <= 3.11 and the latter on
        >= 3.12), so comparing them here exercises the exact cross-version delta
        without relying on which interpreter happens to run the test."""
        s_naive = 0.0
        for x in self.R:
            s_naive += x * x
        s_fsum = math.fsum(x * x for x in self.R)
        self.assertNotEqual(s_naive, s_fsum)
        self.assertTrue(S._replay_equal(self._sigma(s_naive), self._sigma(s_fsum)))
        self.assertFalse(S._replay_equal(self._sigma(s_fsum), self._sigma(s_fsum) * (1 + 1e-6)))
        self.assertTrue(S._replay_equal(self._sigma(s_fsum), self._sigma(s_fsum) * (1 + 1e-12)))


class CalibrationPinTests(unittest.TestCase):
    """Issue #519: the record<->artifact integrity pins stay hash-exact *and bite*.

    The tolerance comparator reaches only the re-derived metrics.  The artifact's
    own sha256 pin and every `source_rows.*.row_sha256` (under `cal["entries"]`)
    are `==` on a SHA-256 against the record's own committed rows -- no tolerance
    bridges a hash, so a tampered artifact or row still fails closed.
    """

    TIP = "20261113-150554-fb302c35"

    @classmethod
    def _tip(cls):
        rec = json.load(open(SLUG / "records" / f"{cls.TIP}.json"))
        chunks = S.load_committed(str(SLUG / "corners" / cls.TIP))
        rows, _summ = S.build(chunks, rec["controls_record"])
        cal = S.calibration_artifact(cls.TIP, rows)
        cal_committed = json.load(open(REPO / rec["calibration_artifact"]["path"]))
        return rec, cal, cal_committed

    @classmethod
    def _first_entry(cls, cal):
        return next(iter(cal["entries"]))

    def test_pins_are_actually_walked(self):
        """Not a vacuous pass: the pin count equals two per entry (ring5 + array)
        over every committed entry, and the leg passes on committed data."""
        rec, cal, cal_committed = self._tip()
        ok, n = S.calibration_leg(rec, cal, cal_committed)
        self.assertEqual(n, 2 * rec["calibration_artifact"]["n_entries"])
        self.assertEqual(n, 216)
        self.assertTrue(ok)

    def test_a_tampered_pinned_row_fails_the_hash_exact_leg(self):
        rec, cal, cal_committed = self._tip()
        rec_t = copy.deepcopy(rec)
        key0 = cal_committed["entries"][self._first_entry(cal_committed)]["source_rows"]["ring5"]["key"]
        row0 = next(r for r in rec_t["rows"] if r["key"] == key0)
        fk = next(k for k, v in row0["metrics"].items() if isinstance(v, float) and v != 0.0)
        row0["metrics"][fk] *= 1 + 1e-6
        ok, n = S.calibration_leg(rec_t, cal, cal_committed)
        self.assertEqual(n, 216)
        self.assertFalse(ok)

    def test_a_corrupted_committed_artifact_fails_the_sha256_pin(self):
        """Perturb the committed artifact far below the replay gate (1e-12): the
        tolerance half still passes, so failing can only be the hash-exact
        sha256 pin biting."""
        rec, cal, cal_committed = self._tip()
        bad = copy.deepcopy(cal_committed)
        e0 = self._first_entry(bad)
        bad["entries"][e0]["lock_proximity"]["distance"] *= 1 + 1e-12
        ok, n = S.calibration_leg(rec, cal, bad)
        self.assertEqual(n, 216)
        self.assertFalse(ok)

    def test_rederived_metric_injection_at_the_gate_boundary(self):
        """The measured gate boundary, on the artifact's re-derived half: a
        1e-6-relative metric change is a real change (DIFFER), 1e-12-relative
        is not (MATCH).  Injected into `lock_proximity.distance` (~6e-2 in
        magnitude) -- the O(1)-magnitude regime where the advertised ~1e-9
        relative gate actually holds.  It does NOT hold on this artifact's
        sub-1e-12-magnitude fields (sigma jitter, numerical_floor), where the
        abs_tol=1e-12 floor is the operative gate; that blind spot is pinned
        by `test_sigma_field_drift_passes_under_the_absolute_floor` below."""
        rec, cal, cal_committed = self._tip()
        for factor, expect_ok in ((1 + 1e-6, False), (1 + 1e-12, True)):
            with self.subTest(factor=factor):
                bad = copy.deepcopy(cal)
                bad["entries"][self._first_entry(bad)]["lock_proximity"]["distance"] *= factor
                ok, _n = S.calibration_leg(rec, bad, cal_committed)
                self.assertEqual(ok, expect_ok)

    def test_sigma_field_drift_passes_under_the_absolute_floor(self):
        """The floor pinned where it binds, on the artifact's real sigma fields:
        a ~50 % relative re-derivation drift in `sigma_1_raw` (smallest tip
        entry ~1.4e-12) still passes the tolerance leg, because below ~1e-12
        magnitude the comparator's absolute floor IS the gate (effective
        relative sensitivity 1e-12/|v| ~ 0.7).  Recorded as a tested, visible
        property so the 1e-9 claim cannot be re-derived from this code; issue
        #547 routes whether that floor is tight enough for the entropy claim."""
        rec, cal, cal_committed = self._tip()
        key = min(cal["entries"], key=lambda k: abs(cal["entries"][k]["sigma_1_raw"]))
        v = cal["entries"][key]["sigma_1_raw"]
        self.assertLess(abs(v), 1e-12 * 10)
        self.assertTrue(S._replay_equal(v, v * 1.5))
        bad = copy.deepcopy(cal)
        bad["entries"][key]["sigma_1_raw"] = v * 1.5
        ok, _n = S.calibration_leg(rec, bad, cal_committed)
        self.assertTrue(ok)


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
