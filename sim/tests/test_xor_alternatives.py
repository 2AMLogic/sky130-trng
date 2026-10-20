#!/usr/bin/env python3
"""Unit tests for sim/xor-combining-alternatives/ (issue #282).

No simulator and no PDK: synthetic measurements and the COMMITTED baseline
records only.

    python3 sim/tests/test_xor_alternatives.py
"""
import copy
import math
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "xor-combining-alternatives")
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
from loadmod import load_module  # noqa: E402


MR = load_module("xa_mr", os.path.join(D, "make-requests.py"))
RD = load_module("xa_rd", os.path.join(D, "reduce.py"))


def swing_curve(w90_target, vdd=1.8):
    """Raw vx*/vn* for a gate whose swing falls linearly across the 0.90 bar at w90_target."""
    raw = {}
    for i, w in enumerate(RD.OP.WIDTHS_DESC, 1):
        s = 1.0 if w >= w90_target + 50 else 0.0
        if w < w90_target + 50:
            s = 0.90 + (w - w90_target) / 50.0 * 0.10     # 1.0 at w90+50, 0.9 at w90
            s = min(1.0, s) if w >= w90_target else max(0.0, 0.9 * (w / w90_target) ** 2)
        raw[f"vx{i}"] = s * vdd
        raw[f"vn{i}"] = 0.0
    return raw


class Interpolation(unittest.TestCase):
    def test_w90_interpolation_matches_committed_rule(self):
        m = {RD.OP.SWING_KEY[w]: s for w, s in zip(RD.OP.WIDTHS_DESC, [1.06, 1.05, 0.94, 0.68, 0.48, 0.38, 0.13, 0.13, 0.1])}
        # between 200 ps (0.94) and 140 ps (0.68): 0.90 is (0.94-0.90)/(0.94-0.68) of the way down
        want = 200 + (0.94 - 0.90) / (0.94 - 0.68) * (140 - 200)
        self.assertAlmostEqual(RD.OP.interpolate_w90(m), want, 9)

    def test_never_crossing_is_failure(self):
        raw = {f"vx{i}": 1.8 for i in range(1, 10)}
        raw.update({f"vn{i}": 0.0 for i in range(1, 10)})
        raw.update({k: 1.0 for k in RD.ARR_NAMES})
        with self.assertRaises(RD.ReductionError):
            RD.derive_job(raw, 1.8, 5.67)


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pts, cls.sigma1, cls.q_req, _ = RD.committed_baseline()

    def test_known_answer_dr0003(self):
        r = RD.reduce_variant(self.pts, self.sigma1, self.q_req)
        self.assertEqual(r["n_max_combine"], 6)
        b = r["binding"]
        self.assertEqual((b["temp_c"], b["vdd_v"], b["corner"]), (-40.0, 1.98, "ff"))
        self.assertAlmostEqual(r["ceiling_any_n"]["rate_bps"] / 1e3, 77.67, delta=0.05)    # ~78 kbps
        self.assertEqual(r["ceiling_any_n"]["n"], 6)
        self.assertAlmostEqual(r["committed_n4"]["rate_bps"] / 1e3, 51.78, delta=0.05)
        self.assertAlmostEqual(r["committed_n4"]["t_s_min_s"] * 1e6, 19.31, delta=0.01)
        self.assertTrue(r["committed_n4"]["clears_combining"])

    def test_known_answer_per_point_table(self):
        r = RD.reduce_variant(self.pts, self.sigma1, self.q_req)
        got = {(x["temp_c"], x["vdd_v"], x["corner"]): x["n_max_combine"] for x in r["rows"]}
        want = {(-40.0, 1.62, "ff"): 10, (-40.0, 1.62, "ss"): 11, (-40.0, 1.62, "tt"): 11,
                (-40.0, 1.98, "ff"): 6, (-40.0, 1.98, "ss"): 7, (-40.0, 1.98, "tt"): 7,
                (27.0, 1.8, "ff"): 9, (27.0, 1.8, "ss"): 9, (27.0, 1.8, "tt"): 8}
        self.assertEqual(got, want)
        self.assertEqual(len(r["rows"]), 9)

    def test_entropy_uses_variant_period_not_baseline(self):
        slow = copy.deepcopy(self.pts)
        bk = RD.key_of(*RD.BINDING_KEY)
        slow[bk]["t0_loaded_ns"] *= 1.10
        a = RD.reduce_variant(self.pts, self.sigma1, self.q_req)
        b = RD.reduce_variant(slow, self.sigma1, self.q_req)
        # Q ~ T0^-3: a 10% slower binding-corner ring needs 1.1^3 longer T_s for the same N
        self.assertAlmostEqual(b["committed_n4"]["t_s_min_s"] / a["committed_n4"]["t_s_min_s"], 1.1 ** 3, 9)

    def test_missing_grid_point_rejected(self):
        for drop in list(self.pts):
            p = {k: v for k, v in self.pts.items() if k != drop}
            with self.assertRaises(RD.ReductionError):
                RD.reduce_variant(p, self.sigma1, self.q_req)

    def test_baseline_control_passes_on_committed_values(self):
        xo = {k: v["w90_s"] for k, v in RD.OP.load_xor_points().items()}
        rg = {k: v["t0_loaded_s"] for k, v in RD.OP.load_ring5_points().items()}
        rows = RD.check_baseline(self.pts, xo, rg)
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(r["ok"] for r in rows))

    def _refs(self):
        xo = {k: v["w90_s"] for k, v in RD.OP.load_xor_points().items()}
        rg = {k: v["t0_loaded_s"] for k, v in RD.OP.load_ring5_points().items()}
        return xo, rg

    def test_baseline_w90_tolerance_enforced(self):
        xo, rg = self._refs()
        ok = copy.deepcopy(self.pts)
        k = RD.key_of(-40.0, 1.98, "ff")
        ok[k]["w90_ps"] *= 1.049
        RD.check_baseline(ok, xo, rg)                      # just inside +5%
        bad = copy.deepcopy(self.pts)
        bad[k]["w90_ps"] *= 1.051
        with self.assertRaises(RD.ReductionError):
            RD.check_baseline(bad, xo, rg)
        bad[k]["w90_ps"] = self.pts[k]["w90_ps"] * 0.951
        RD.check_baseline(bad, xo, rg)
        bad[k]["w90_ps"] = self.pts[k]["w90_ps"] * 0.94
        with self.assertRaises(RD.ReductionError):
            RD.check_baseline(bad, xo, rg)

    def test_baseline_period_tolerance_enforced(self):
        xo, rg = self._refs()
        k = RD.key_of(27.0, 1.8, "tt")
        ok = copy.deepcopy(self.pts)
        ok[k]["t0_loaded_ns"] *= 1.019
        RD.check_baseline(ok, xo, rg)                      # just inside +2%
        bad = copy.deepcopy(self.pts)
        bad[k]["t0_loaded_ns"] *= 1.021
        with self.assertRaises(RD.ReductionError):
            RD.check_baseline(bad, xo, rg)
        bad[k]["t0_loaded_ns"] = self.pts[k]["t0_loaded_ns"] * 0.97
        with self.assertRaises(RD.ReductionError):
            RD.check_baseline(bad, xo, rg)

    def test_baseline_control_missing_point_rejected(self):
        xo, rg = self._refs()
        p = {k: v for k, v in self.pts.items() if k != RD.key_of(27.0, 1.8, "ss")}
        with self.assertRaises(RD.ReductionError):
            RD.check_baseline(p, xo, rg)


class Derive(unittest.TestCase):
    def raw(self, vdd=1.8):
        r = swing_curve(150.0, vdd)
        for k in range(1, 5):
            r[f"t{k}a"] = 10e-9
            r[f"t{k}b"] = 10e-9 + 10 * (3e-9 + k * 1e-10)
        r.update({"vxo_max": 2.1, "vxo_min": 0.0, "vxo_avg": 0.9 * vdd / 1.8,
                  "vt1_avg": 0.9, "txo_a": 70e-9, "txo_b": 70e-9 + 48 / 5e8,
                  "tt1a": 70e-9, "tt1b": 70e-9 + 48 / 3e8,
                  "i1": -10e-6, "i2": -10e-6, "i3": -10e-6, "i4": -10e-6, "ib": -20e-6,
                  "qa": -1.8 * 3e-15, "qb": -1.8 * 4e-15, "qs": -1.8 * 5e-15})
        return r

    def test_units_and_values(self):
        d = RD.derive_job(self.raw(), 1.8, 5.67)
        self.assertAlmostEqual(d["t0_loaded_ns"], 3.1, 9)
        self.assertEqual(len(d["ring_periods_ns"]), 4)
        self.assertAlmostEqual(d["i_rings_ua"], 40.0, 9)
        self.assertAlmostEqual(d["i_xor_buf_ua"], 20.0, 9)
        self.assertAlmostEqual(d["i_total_ua"], 60.0, 9)
        self.assertAlmostEqual(d["p_total_uw"], 108.0, 9)
        self.assertAlmostEqual(d["c_in_first_stage_pin_a_ff"], 3.0, 9)
        self.assertAlmostEqual(d["c_in_first_stage_pin_b_ff"], 4.0, 9)
        self.assertAlmostEqual(d["c_in_root_sampler_ff"], 5.0, 9)
        self.assertAlmostEqual(d["swing_frac_xo"], 2.1 / 1.8, 9)
        self.assertAlmostEqual(d["xor_area_proxy_um2"], 5.67, 9)

    def test_missing_or_nonfinite_measurement_fails_closed(self):
        for name in RD.PW_NAMES + RD.ARR_NAMES:
            r = self.raw()
            r.pop(name)
            with self.assertRaises(RD.ReductionError, msg=name):
                RD.derive_job(r, 1.8, 5.67)
        r = self.raw()
        r["i1"] = None
        with self.assertRaises(RD.ReductionError):
            RD.derive_job(r, 1.8, 5.67)
        r = self.raw()
        r["i1"] = float("nan")
        with self.assertRaises(RD.ReductionError):
            RD.derive_job(r, 1.8, 5.67)

    def test_nonpositive_capacitance_rejected(self):
        r = self.raw()
        r["qs"] = +1e-15
        with self.assertRaises(RD.ReductionError):
            RD.derive_job(r, 1.8, 5.67)


class Matrix(unittest.TestCase):
    def test_exactly_18_unique_jobs_and_batch_contract(self):
        m = MR.build_matrix()
        self.assertEqual(len(m), 6)
        jobs = MR.jobs_of(m)
        self.assertEqual(len(jobs), 18)
        self.assertEqual(len(set(jobs)), 18)
        self.assertEqual({j[0] for j in jobs}, {"base", "w2x"})
        grid = {(j[1], j[2], j[3]) for j in jobs}
        self.assertEqual(grid, {(t, v, c) for (t, v) in [(-40.0, 1.62), (27.0, 1.80), (-40.0, 1.98)]
                                for c in ("tt", "ss", "ff")})
        for name, variant, t, v, req in m:
            self.assertEqual(req["backend"], "batch")
            self.assertEqual(req["models"]["pdk"], "sky130A")
            self.assertEqual(req["corners"]["process"], ["tt", "ss", "ff"])    # 3 units each -> never single-unit local
            self.assertEqual(req["corners"]["temperature_c"], [t])
            self.assertEqual(req["analysis"], {"kind": "tran", "args": "5p 200n"})
            self.assertNotIn("analysis_steps", req)    # the batch fleet's runner has no step support
        self.assertEqual(len({n for n, *_ in m}), 6)

    def test_measurement_names_match_the_reducer(self):
        req = MR.build_request("base", -40.0, 1.62)
        names = [x["name"] for x in req["measurements"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(RD.PW_NAMES + RD.ARR_NAMES))
        for x in req["measurements"]:
            self.assertTrue(x["spice"].startswith(f".meas tran {x['name']} "), x)
        # the 60-200 ns window and the 0.90 x Vdd (here 0.81 V) half-level of the committed deck
        self.assertTrue(any("from=60n to=200n" in x["spice"] for x in req["measurements"]))
        self.assertTrue(any("=0.81 rise" in x["spice"] for x in req["measurements"]))


class Deck(unittest.TestCase):
    def test_w2x_doubles_every_xor_width_only(self):
        base, a1, _ = MR.build_deck("base", 1.8)
        two, a2, _ = MR.build_deck("w2x", 1.8)
        bx = MR._block(base, "xor2")
        tx = MR._block(two, "xor2")
        bd, td = MR.mos_devices(bx), MR.mos_devices(tx)
        self.assertEqual(len(bd), len(td))
        self.assertEqual(len(bd), 12)
        for (n1, w1, l1, m1, _), (n2, w2, l2, m2, _) in zip(bd, td):
            self.assertEqual(n1, n2)
            self.assertAlmostEqual(w2, 2 * w1, 12)
            self.assertEqual(l1, l2)
            self.assertEqual(m1, m2)
        self.assertAlmostEqual(a2, 2 * a1, 9)
        self.assertAlmostEqual(a1, 5.67, 9)
        # nothing outside the xor2 block changes
        self.assertEqual(base.replace(bx, ""), two.replace(tx, ""))

    def test_baseline_deck_embeds_committed_netlist_verbatim(self):
        design = MR.read(MR.DESIGN)
        deck, _, _ = MR.build_deck("base", 1.62)
        self.assertIn(design.rstrip(), deck)
        self.assertEqual(len(re.findall(r"^\.subckt ", deck, re.M)), len(re.findall(r"^\.ends", deck, re.M)))
        self.assertNotIn("@@", deck)
        self.assertIn("Vdd vdd 0 dc 1.62", deck)

    def test_topology_unchanged(self):
        design = MR.read(MR.DESIGN)
        two, _, _ = MR.build_deck("w2x", 1.8)
        for line in ("xa1 ro1 ro2 t1 vdd vss xor2", "xa2 ro3 ro4 t2 vdd vss xor2", "xa3 t1 t2 xo vdd vss xor2"):
            self.assertIn(line, design)
            self.assertIn(line, two)


class CommittedRecord(unittest.TestCase):
    def test_every_committed_record_replays_from_its_raw_responses(self):
        import glob
        recs = sorted(glob.glob(os.path.join(D, "records", "*.json")))
        self.assertTrue(recs)
        for r in recs:
            self.assertEqual(RD.check(r), 0, r)


if __name__ == "__main__":
    unittest.main()
