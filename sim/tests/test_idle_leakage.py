#!/usr/bin/env python3
"""Unit tests for sim/ro-array-idle-leakage/analysis/idle_leakage.py (issue #201). Standard library only.

    python3 sim/tests/test_idle_leakage.py
"""
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loadmod import load_module  # noqa: E402
m = load_module("idle_leakage", REPO / "sim/ro-array-idle-leakage/analysis/idle_leakage.py")

GRID = [(p, t, v) for p in ("tt", "ss", "ff") for t in (-40.0, 27.0, 125.0) for v in (1.62, 1.8, 1.98)]


class Mapping(unittest.TestCase):
    def test_all_27_points_map_to_a_listed_view(self):
        self.assertEqual(len(GRID), 27)
        listed = set(m.needed_views())
        for p, t, v in GRID:
            self.assertIn(m.map_view(p, t, v)["view"], listed, (p, t, v))

    def test_hot_points_are_flagged_extrapolated(self):
        for p, t, v in GRID:
            if t == 125.0:
                r = m.map_view(p, t, v)
                self.assertTrue(r["temp_extrapolated"], (p, t, v))
                self.assertEqual(r["view_temp_c"], 100.0)

    def test_tt_cold_falls_back_to_025C(self):
        r = m.map_view("tt", -40.0, 1.8)
        self.assertEqual(r["view"], "sky130_fd_sc_hd__tt_025C_1v80")
        self.assertTrue(r["temp_extrapolated"])

    def test_tt_room_is_exact_at_1v8_only(self):
        self.assertFalse(m.map_view("tt", 27.0, 1.8)["temp_extrapolated"])
        self.assertFalse(m.map_view("tt", 27.0, 1.8)["supply_extrapolated"])
        self.assertTrue(m.map_view("tt", 27.0, 1.62)["supply_extrapolated"])

    def test_ff_takes_supply_at_or_above(self):
        self.assertEqual(m.map_view("ff", -40.0, 1.62)["view_vdd"], 1.65)
        self.assertEqual(m.map_view("ff", -40.0, 1.8)["view_vdd"], 1.95)
        self.assertEqual(m.map_view("ff", -40.0, 1.98)["view_vdd"], 1.95)   # none above: highest listed
        self.assertTrue(m.map_view("ff", -40.0, 1.98)["supply_extrapolated"])

    def test_ss_takes_nearest_supply(self):
        self.assertEqual(m.map_view("ss", -40.0, 1.62)["view_vdd"], 1.60)
        self.assertEqual(m.map_view("ss", -40.0, 1.8)["view_vdd"], 1.76)
        self.assertEqual(m.map_view("ss", 125.0, 1.98)["view_vdd"], 1.60)

    def test_room_temperature_ff_ss_use_the_cold_view(self):
        # 27 C is 67 C from the -40 C view and 73 C from the 100 C view
        self.assertEqual(m.map_view("ff", 27.0, 1.8)["view_temp_c"], -40.0)
        self.assertTrue(m.map_view("ss", 27.0, 1.8)["temp_extrapolated"])

    def test_unknown_process(self):
        with self.assertRaises(ValueError):
            m.map_view("fs", 27.0, 1.8)


class Extrapolation(unittest.TestCase):
    def test_exponential_in_t_and_only_beyond_the_hottest_view(self):
        p = {m.view_name("tt", 25.0, 1.8): 10.0, m.view_name("tt", 100.0, 1.8): 40.0}
        v = m.map_view("tt", 125.0, 1.8)
        # 25 C -> 100 C is x4 over 75 C; +25 C more is x4^(1/3)
        self.assertAlmostEqual(m.extrapolate_digital_nw(p, "tt", 125.0, v), 40.0 * 4 ** (25 / 75))
        self.assertIsNone(m.extrapolate_digital_nw(p, "tt", 100.0, m.map_view("tt", 100.0, 1.8)))


def unit(i_each, **extra):
    d = {f"i_{r}": i_each for r in m.RAILS}
    d.update({"v_xo": 0.0, "v_ro1": 0.0, "v_rn1": 1.8})
    d.update(extra)
    return d


class Rows(unittest.TestCase):
    def _units(self, leaf_scale=1.0, hot_scale=10.0):
        u = {}
        for p, t, v in GRID:
            i = 1e-10 * (hot_scale if t == 125.0 else 1.0)
            u[("idle", p, t, v)] = unit(i)
            u[("leaf", p, t, v)] = unit(i * leaf_scale)
        return u

    def _pv(self):
        return {n: 1.0 for n in m.needed_views()}

    def test_aggregation_is_vdd_times_current_plus_digital(self):
        rows = m.build_rows(self._units(), self._pv())
        r = next(x for x in rows if (x["process"], x["temp_c"], x["vdd_v"]) == ("tt", 27.0, 1.8))
        self.assertAlmostEqual(r["p_analog_uw"], 1.8 * 5e-10 * 1e6)
        self.assertAlmostEqual(r["p_digital_uw"], 1.0e-3)
        self.assertAlmostEqual(r["p_standby_uw"], r["p_analog_uw"] + r["p_digital_uw"])

    def test_clean_data_has_no_flags_and_worst_is_hot(self):
        rows = m.build_rows(self._units(), self._pv())
        fl = m.flags(rows)
        self.assertEqual(fl["non_monotone_in_temperature"], [])
        self.assertEqual(fl["exceeds_leaf_sum"], [])
        self.assertEqual(m.worst(rows)["analog"]["corner"].split("/")[1], "125C")

    def test_non_monotone_and_leaf_exceedance_are_flagged(self):
        u = self._units(leaf_scale=0.5)               # assembled = 2x leaf sum
        u[("idle", "ss", 27.0, 1.8)] = unit(1e-8)     # 27 C above 125 C at ss / 1.8 V
        fl = m.flags(m.build_rows(u, self._pv()))
        self.assertTrue(any(f["process"] == "ss" and f["vdd_v"] == 1.8 for f in fl["non_monotone_in_temperature"]))
        self.assertEqual(len(fl["exceeds_leaf_sum"]), 27)

    def test_wrong_idle_state_is_flagged(self):
        u = self._units()
        u[("idle", "tt", 27.0, 1.8)]["v_rn1"] = 0.9
        fl = m.flags(m.build_rows(u, self._pv()))
        self.assertEqual(fl["idle_state_violations"], ["tt/27C/1.8V"])

    def test_clamp_share_is_flagged(self):
        u = self._units()
        u[("idle", "tt", 27.0, 1.8)]["i_cl_xsb"] = 5e-10        # as large as the block current
        fl = m.flags(m.build_rows(u, self._pv()))
        self.assertEqual([f["corner"] for f in fl["clamp_share_above"]], ["tt/27C/1.8V"])

    def test_missing_unit_is_reported_not_dropped(self):
        u = self._units()
        del u[("idle", "ff", -40.0, 1.62)]
        fl = m.flags(m.build_rows(u, self._pv()))
        self.assertEqual(fl["missing_units"], ["ff/-40C/1.62V"])


class Collect(unittest.TestCase):
    def _chunk(self, leg, status="pass", diag=(), i=1e-10):
        meas = [{"name": f"i_{r}", "value": i} for r in m.RAILS]
        c = {"process": "tt", "temperature_c": 27.0, "supply_v": {"Vk": 1.8}, "status": status,
             "measurements": meas, "diagnostics": [{"code": d} for d in diag]}
        return ("n", {"leg": leg}, {"corners": [c]})

    def test_valid_unit_is_kept(self):
        units, bad = m.collect_units([self._chunk("idle")])
        self.assertEqual(len(units), 1)
        self.assertEqual(bad, [])

    def test_nonconvergence_diagnostic_is_rejected_even_when_status_is_pass(self):
        units, bad = m.collect_units([self._chunk("idle", diag=("nonconvergence",))])
        self.assertEqual(units, {})
        self.assertEqual(len(bad), 1)

    def test_negative_supply_current_is_rejected(self):
        units, bad = m.collect_units([self._chunk("leaf", i=-1e-6)])
        self.assertEqual(units, {})
        self.assertTrue(bad[0][1].startswith("('leaf'"))


class Recommend(unittest.TestCase):
    def test_rounds_up_to_1_2_5(self):
        self.assertEqual(m.recommend_idle_target_uw(100.0, 1.0), 100.0)
        self.assertEqual(m.recommend_idle_target_uw(114.9, 1.5), 200.0)
        self.assertEqual(m.recommend_idle_target_uw(30.0, 1.5), 50.0)
        self.assertEqual(m.recommend_idle_target_uw(0.0), None)


if __name__ == "__main__":
    unittest.main()
