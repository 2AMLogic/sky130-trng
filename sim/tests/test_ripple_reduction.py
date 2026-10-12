#!/usr/bin/env python3
"""Unit tests for sim/ro-array-supply-perturbation/ripple.py (issue #200).

Synthetic edge trains only -- no simulator, no PDK. The point is that the lock
detector is shown to FIRE on data that is locked by construction and to stay
quiet on data that is not, independent of any SPICE run.

    python3 sim/tests/test_ripple_reduction.py
"""
import importlib.util
import math
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_p = os.path.join(HERE, "..", "ro-array-supply-perturbation", "ripple.py")
_s = importlib.util.spec_from_file_location("ripple", _p)
rp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(rp)


def train(T, n=rp.NEDGE, t0=9e-9, mod=0.0, fmod=None):
    out = []
    for k in range(n):
        t = t0 + k * T
        if mod and fmod:
            t += mod * T / (2 * math.pi * fmod * T) * math.sin(2 * math.pi * fmod * (t0 + k * T))
        out.append(t)
    return out


class Tests(unittest.TestCase):
    def test_period_and_modulation(self):
        e = rp.analyze_edges(train(5e-9))
        self.assertAlmostEqual(e["T"], 5e-9, 15)
        self.assertLess(e["mod_pk"], 1e-9)
        P = [5e-9 * (1 + 0.01 * (-1) ** k) for k in range(39)]
        t = [0.0]
        for p in P:
            t.append(t[-1] + p)
        self.assertAlmostEqual(rp.analyze_edges(t)["mod_pk"], 0.01, 4)

    def test_tone_lock_fires_on_locked_train(self):
        T = 5e-9
        f = 1 / T                                  # tone exactly at the ring frequency
        p, q, d = rp.tone_lock(train(T), f)
        self.assertEqual((p, q), (1, 1))
        self.assertLess(abs(d), 1e-6)

    def test_tone_lock_2_to_1_subharmonic(self):
        T = 5e-9
        p, q, d = rp.tone_lock(train(T), 1 / (2 * T))     # tone at half the ring frequency
        self.assertEqual((p, q), (2, 1))
        self.assertLess(abs(d), 1e-6)

    def test_tone_lock_quiet_when_free_running(self):
        T = 5e-9
        f = 1.05 / T                               # 5% off: ~2 cycles slip over 39 edges
        p, q, d = rp.tone_lock(train(T), f)
        self.assertGreater(abs(d), rp.DRIFT_LOCK * 5)

    def test_pair_lock(self):
        a = train(5e-9, t0=9e-9)
        b = train(5e-9, t0=11e-9)                  # same frequency: 1:1 locked pair
        p, q, d = rp.pair_lock(a, b)
        self.assertEqual((p, q), (1, 1))
        self.assertLess(abs(d), 1e-6)
        c = train(5.2e-9, t0=9e-9)                 # 4% apart: slips ~1.5 cycles
        self.assertGreater(abs(rp.pair_lock(a, c)[2]), 1.0)

    def test_closeness(self):
        d, p, q = rp.closeness(5e-9, 3.75e-9, rp.DR5_RATIOS)     # 4/3 exactly
        self.assertAlmostEqual(d, 0.0, 12)
        self.assertEqual((p, q), (4, 3))

    def _metrics(self, edges, clean, f_rip=None, xo=0.8, vnom=1.62, dv=0.0):
        return rp.row_metrics(edges, clean, vnom, dv, xo, f_rip)

    def test_row_flags_locked_ring_and_passes_clean(self):
        clean = [train(5.4e-9), train(5.2e-9), train(5.0e-9), train(4.8e-9)]
        m = self._metrics(clean, clean, f_rip=1 / 7.7e-9, xo=0.5 * 1.62)
        ok, why = rp.row_verdict(m)
        self.assertTrue(ok, why)
        locked = [train(5.2e-9)] + clean[1:]       # ring 1 dragged to ring 2's period, tone there too
        m = self._metrics(locked, clean, f_rip=1 / 5.2e-9, xo=0.5 * 1.62)
        ok, why = rp.row_verdict(m)
        self.assertFalse(ok)
        self.assertTrue(any("LOCK" in w for w in why), why)
        self.assertEqual(m["tone"][0]["state"], "LOCKED")

    def test_coincident_is_reported_not_hidden(self):
        clean = [train(5.0e-9)] * 4
        m = self._metrics(clean, clean, f_rip=1 / 5.0e-9, xo=0.8)
        self.assertEqual(m["tone"][0]["state"], "COINCIDENT")
        self.assertTrue(rp.row_verdict(m)[0])      # unresolved, not failed (flagged separately)

    def test_q_and_bias_criteria(self):
        clean = [train(5e-9)] * 4
        slow = [train(5e-9 * 1.02)] * 4            # +2% period -> Q ratio 0.942 < 0.965
        m = self._metrics(slow, clean, xo=0.8)
        self.assertLess(m["Q_ratio"], 1 / rp.Q_MARGIN)
        self.assertTrue(any(w.startswith("Q:") for w in rp.row_verdict(m)[1]))
        m = self._metrics(clean, clean, xo=0.2 * 1.62)       # bias 0.2 outside the band
        self.assertTrue(any(w.startswith("BIAS:") for w in rp.row_verdict(m)[1]))

    def test_tolerance_statement(self):
        rows = [{"amp": 0.01, "ok": True}, {"amp": 0.05, "ok": True}]
        self.assertIn(">= 50 mV", rp.tolerance(rows))
        rows = [{"amp": 0.01, "ok": True}, {"amp": 0.05, "ok": False}]
        self.assertIn(">= 10 mV pk, < 50 mV", rp.tolerance(rows))
        rows = [{"amp": 0.01, "ok": False}, {"amp": 0.05, "ok": False}]
        self.assertEqual(rp.tolerance(rows), "no tolerance found at 10 mV")
        rows = [{"amp": 0.01, "ok": True}, {"amp": 0.05, "ok": True}, {"amp": 0.05, "ok": False}]
        self.assertIn("< 50", rp.tolerance(rows))

    # ---- issue #288 lock-resolution campaign: window resolution and controls ----

    def test_near_detuned_free_at_200_edges(self):
        # +0.1 % detuning slips 0.001*(200-1) = 0.199 ring cycles across the
        # 200-edge window, above the 0.1-cycle DRIFT_LOCK: a free-running ring
        # must read free at the claimed resolution.
        T = 5e-9
        f = 1.001 / T
        clean = [train(T, n=200) for _ in range(4)]
        m = self._metrics(clean, clean, f_rip=f)
        self.assertTrue(all(t["state"] == "free" for t in m["tone"]))
        self.assertAlmostEqual(abs(m["tone"][0]["drift_cycles"]), 0.001 * 199, 3)
        ok, why = rp.row_verdict(m)
        self.assertTrue(ok, why)

    def test_insufficient_window_control_40_edges(self):
        # The SAME +0.1 %-detuned situation over the #200 40-edge window slips
        # only 0.039 cycles: the detector cannot separate the free ring from the
        # tone and reports COINCIDENT (unresolved) -- the window, not the physics.
        T = 5e-9
        f = 1.001 / T
        clean = [train(T, n=40) for _ in range(4)]
        m = self._metrics(clean, clean, f_rip=f)
        self.assertTrue(all(t["state"] == "COINCIDENT" for t in m["tone"]))

    def test_locked_ring_flagged_at_200_edges(self):
        # Resolution must not come at the cost of missing a true lock: a ring
        # dragged to the tone period is still LOCKED at the 200-edge window.
        T0, T1 = 5e-9, 5.1e-9
        f = 1 / T1
        clean = [train(T0, n=200) for _ in range(4)]
        locked = [train(T1, n=200)] + clean[1:]
        m = self._metrics(locked, clean, f_rip=f)
        self.assertEqual(m["tone"][0]["state"], "LOCKED")
        self.assertAlmostEqual(m["tone"][0]["pull_fraction"], 1.0, 6)
        ok, why = rp.row_verdict(m)
        self.assertFalse(ok)
        self.assertTrue(any("LOCK" in w for w in why), why)

    def test_missing_edge_never_reads_locked(self):
        # A dropped .meas edge must not be readable as a lock: the index shift
        # puts a ~1-cycle step into the phase residual, so the detector goes
        # conservative (no LOCKED) and the modulation metric blows up as a flag.
        T = 5e-9
        f = 1 / T
        clean = [train(T, n=200) for _ in range(4)]
        gapped = train(T, n=201)
        del gapped[100]
        m = self._metrics([gapped] + clean[1:], clean, f_rip=f)
        self.assertNotEqual(m["tone"][0]["state"], "LOCKED")
        self.assertGreater(m["mod_pk_pct"][0], 40.0)

    def test_longer_window_converges(self):
        # Same free-running ring, 200 vs 400 edges: the slip doubles as
        # delta*(N-1) predicts and the verdict is identical -- the convergence
        # check the lrc subset runs on real data.
        T = 5e-9
        f = 1.0025 / T
        _, _, d200 = rp.tone_lock(train(T, n=200), f)
        _, _, d400 = rp.tone_lock(train(T, n=400), f)
        self.assertAlmostEqual(d400, d200 * 399 / 199, 3)   # slip = delta*(N-1)
        self.assertAlmostEqual(abs(d400), 0.0025 * 399, 3)
        self.assertGreater(abs(d200), rp.DRIFT_LOCK)
        self.assertGreater(abs(d400), rp.DRIFT_LOCK)

    # ---- issue #288 evidence handling: missing / truncated / window-matched rows ----

    TR = [5.4e-9, 5.2e-9, 5.0e-9, 4.8e-9]

    def _corner(self, nedge, periods=None, drop_after=None, status="pass", cid="c"):
        periods = periods or self.TR
        ms = []
        for r, T in enumerate(periods, 1):
            for i, t in enumerate(train(T, n=nedge)):
                k = 3 + i
                ms.append({"name": f"t{r}_{k}",
                           "value": None if (drop_after is not None and i >= drop_after) else t})
        for n, v in (("xo_avg", 0.8), ("xo_max", 1.6), ("xo_min", 0.0), ("txo_a", 1e-8), ("txo_b", 2e-7),
                     ("vdd_min", 1.6), ("vdd_max", 1.64)):
            ms.append({"name": n, "value": v})
        return {"status": status, "corner_id": cid, "measurements": ms}

    def _plan(self, nedge, units, corner="ss"):
        return {"corner": corner, "group": "lr", "chunk": 1, "campaign": rp.LR, "nedge": nedge,
                "pvt": {"vnom": 1.62}, "units": units}

    @staticmethod
    def _unit(kind, tone="-", rf=1e6, ra=0.0, detune=None):
        u = {"kind": kind, "tone": tone, "dv": 0.0, "ra": ra, "rf": rf, "ri": 0.0}
        if detune is not None:
            u["detune"] = detune
        return u

    def test_missing_and_not_returned_units_are_rows(self):
        f2 = 1 / self.TR[1]
        units = [self._unit("baseline"), self._unit("tone", "f2+0.1%", f2 * 1.001, 0.02, 0.001),
                 self._unit("tone", "f2-0.1%", f2 * 0.999, 0.02, -0.001)]
        resp = {"corners": [self._corner(200), self._corner(200)]}        # third unit never returned
        miss_plan = self._plan(200, [self._unit("tone", "f3+0.1%", 1 / self.TR[2] * 1.001, 0.02, 0.001)])
        rows = rp.build_rows([("ss-lr-1", self._plan(200, units), resp)],
                             [("ss-lr-2", miss_plan, "batch backend failed: no capacity")])["ss"]
        self.assertEqual(len(rows), 4)                                     # every planned unit is a row
        st = {r["tone"]: r["klt_status"] for r in rows}
        self.assertEqual(st["f2-0.1%"], "not-returned")
        self.assertEqual(st["f3+0.1%"], "missing")
        self.assertIn("no capacity", next(r for r in rows if r["tone"] == "f3+0.1%")["why"][0])
        s = rp.summarize_lr(rows)
        self.assertEqual((s["rows_planned"], s["rows_usable"]), (4, 2))
        self.assertEqual(len(s["rows_unusable"]), 2)
        self.assertEqual(s["verdict_counts"]["tone_rows_unusable"], 2)

    def test_truncated_window_is_unusable_and_visible(self):
        # insufficient-window control on real-shaped data: a unit whose rings stop
        # before the requested 200 edges is unusable, and its observed window says why
        f2 = 1 / self.TR[1]
        units = [self._unit("baseline"), self._unit("tone", "f2+0.1%", f2 * 1.001, 0.02, 0.001)]
        resp = {"corners": [self._corner(200), self._corner(200, drop_after=150)]}
        rows = rp.build_rows([("ss-lr-1", self._plan(200, units), resp)])["ss"]
        r = rows[1]
        self.assertIsNone(r["metrics"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["window"]["edges_requested"], 200)
        self.assertEqual(r["window"]["edges_observed"], [150] * 4)
        self.assertEqual(rows[0]["window"]["edges_observed"], [200] * 4)

    def test_window_matched_baseline(self):
        # a 400-edge row is compared with the 400-edge baseline only; with none it
        # is reported unusable rather than compared against a 200-edge window
        f2 = 1 / self.TR[1]
        u200 = [self._unit("baseline"), self._unit("tone", "f2+0.25%", f2 * 1.0025, 0.05, 0.0025)]
        u400 = [self._unit("baseline"), self._unit("tone", "f2+0.25%", f2 * 1.0025, 0.05, 0.0025)]
        c200 = ("ss-lr-1", self._plan(200, u200), {"corners": [self._corner(200), self._corner(200)]})
        c400 = ("ss-lrc-1", self._plan(400, u400), {"corners": [self._corner(400), self._corner(400)]})
        rows = rp.build_rows([c200, c400])["ss"]
        r4 = next(r for r in rows if r["nedge"] == 400 and r["kind"] == "tone")
        self.assertAlmostEqual(r4["metrics"]["tone"][1]["clean_drift_cycles"], 0.0025 * 399, 3)
        s = rp.summarize_lr(rows)
        self.assertTrue(s["converged_all"])
        self.assertAlmostEqual(s["convergence_200_vs_400"][0]["drift_ratio_400_over_200"], 399 / 199, 3)
        c400_nobase = ("ss-lrc-1", self._plan(400, u400[1:]), {"corners": [self._corner(400)]})
        rows = rp.build_rows([c200, c400_nobase])["ss"]
        r4 = next(r for r in rows if r["nedge"] == 400)
        self.assertIsNone(r4["metrics"])
        self.assertIn("no passing clean baseline at the 400-edge window", r4["why"][0])
        self.assertEqual(rp.summarize_lr(rows)["convergence_unpaired"][0]["have_400"], False)

    def test_lock_bracket_statement(self):
        # ring 2 locked at +0.1 %, free at +0.25/+0.4 %  ->  edge bracketed in (0.1, 0.25]
        f2 = 1 / self.TR[1]
        T_lock = 1 / (f2 * 1.001)
        units = [self._unit("baseline")] + [self._unit("tone", f"f2+{d * 100:g}%", f2 * (1 + d), 0.05, d)
                                            for d in (0.001, 0.0025, 0.004)]
        locked = [self.TR[0], T_lock, self.TR[2], self.TR[3]]
        resp = {"corners": [self._corner(200), self._corner(200, periods=locked),
                            self._corner(200), self._corner(200)]}
        rows = rp.build_rows([("ss-lr-1", self._plan(200, units), resp)])["ss"]
        b = rp.summarize_lr(rows)["lock_brackets"]
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["states"], {"0.1%": "LOCKED", "0.25%": "free", "0.4%": "free"})
        self.assertEqual(b[0]["bracket"], "lock-range edge in (0.1, 0.25] %")

    def test_legacy_records_replay_unchanged(self):
        # the #200 records must keep replaying from their committed responses
        for rid in ("20261009-000459-28d3690", "20261009-000500-28d3690"):
            p = os.path.join(rp.REPO, "sim", rp.SLUG, "records", rid + ".json")
            self.assertEqual(rp.check(p), 0, rid)


if __name__ == "__main__":
    unittest.main()
