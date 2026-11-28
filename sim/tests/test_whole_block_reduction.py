"""Issue #174: the whole-block reducer must count coverage honestly.

Builds synthetic ``klt sim`` reports whose digital measurements are generated
from the normative model itself, then checks: a complete matrix is MET, an
omitted point is UNMET (incomplete coverage named), a flipped bus bit is an
oracle mismatch, a klt error envelope / errored corner stays UNMET, and an
absent measurement never passes.
"""
import json
import sys
import tempfile
import os
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BLOCK = REPO / "sim" / "post-layout-whole-block"
sys.path.insert(0, str(BLOCK))
sys.path.insert(0, str(REPO / "sim" / "bin"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loadmod import load_module  # noqa: E402
R = load_module("reduce_wb", BLOCK / "analysis" / "reduce-whole-block.py")
P = R.P

_MR = None


def make_requests():
    """``make-requests.py`` loaded by path, once. Only the tests that exercise
    that CLI's own code pay for it: the card set and the PWL stimulus it
    emits are program.py's and are reached through ``P`` (#804)."""
    global _MR
    if _MR is None:
        _MR = load_module("make_requests", BLOCK / "make-requests.py")
    return _MR


BITS = [(i * 7 + 3) % 5 % 2 for i in range(64)]


def synth_corner(proc, temp, vdd, flip=None, drop=None, omit=None, status="pass", bits=None):
    cycles, _ = P.build_program()
    meas_entries, _ = P.whole_block_measurement_cards(cycles)
    rows = P.model_replay(list(bits) if bits is not None else BITS)
    inputs = P.cycle_inputs(cycles)
    hi = vdd
    vals = {}
    bit_i = 0
    for k, inp in enumerate(inputs):
        if inp["raw_valid"]:
            vals[f"raw_bit_k{k}"] = hi * (list(bits) if bits is not None else BITS)[bit_i]
            vals[f"raw_valid_k{k}"] = hi
            bit_i += 1
    for e in meas_entries:
        n = e["name"]
        if n in vals:
            continue
        if n.startswith("rdata_k"):
            k, b = n[len("rdata_k"):].split("_b")
            k = int(k)
            # rdata_k<k> is sampled during cycle k+1 (the read's data is
            # visible the cycle AFTER the read); the k=74 word is sampled
            # at t_stop and has no row to observe it in (response_checks
            # skips it), so any rail value fits
            v = (rows[k + 1]["model"]["bus_rdata"] >> int(b)) & 1 if k + 1 < len(rows) else 0
            vals[n] = hi * v
        elif n.startswith("odata_k"):
            k, b = n[len("odata_k"):].split("_b")
            vals[n] = hi * ((rows[int(k)]["model"]["out_data"] >> int(b)) & 1)
        elif n.startswith(("alarm_k", "gated_k", "startup_done_k", "out_valid_k")):
            sig, k = n.rsplit("_k", 1)
            vals[n] = hi * int(rows[int(k)]["model"][sig])
        elif n.startswith("i_") and n.endswith("_w1"):
            vals[n] = -1e-6
        elif n.startswith("i_") and n.endswith("_w2"):
            vals[n] = -3e-6
        elif n.startswith("q_"):
            vals[n] = -1e-12
        else:
            vals[n] = 1e-6
    if flip:
        vals[flip] = hi - vals[flip]
    if drop:
        vals[drop] = None
    if omit:
        del vals[omit]
    return {"process": proc, "temperature_c": temp, "supply_v": {"Vvdd": vdd}, "status": status,
            "diagnostics": [], "measurements": [{"name": k, "value": v} for k, v in vals.items()]}


def write_report(d: Path, name, corners, extra=None):
    (d / name).mkdir(parents=True)
    doc = {"status": "pass", "corners": corners}
    doc.update(extra or {})
    (d / name / "report.json").write_text(json.dumps(doc))
    return d / name


class WholeBlockReduction(unittest.TestCase):
    def tmpdir(self):
        td = tempfile.TemporaryDirectory(prefix="wbred-")
        self.addCleanup(td.cleanup)
        return Path(td.name)

    def test_complete_matrix_met(self):
        tmp_path = self.tmpdir()
        for t, v in R.GRID:
            write_report(tmp_path, f"grid-{t}-{v}", [synth_corner(p, t, v) for p in R.PROCESSES])
        red = R.reduce(tmp_path, None)
        self.assertTrue(red["matrix"] == {"expected": 12, "met": 12, "unmet": 0, "complete": True})
        pw = red["points"][0]["power"]
        self.assertTrue(abs(pw["p_active_w"] - pw["recompute_check_w"]) < 1e-18)
        self.assertTrue(abs(pw["p_active_w"] - 1.62 * 5 * 3e-6) < 1e-12)  # independent V*I recompute


    def test_omitted_point_is_unmet(self):
        tmp_path = self.tmpdir()
        for t, v in R.GRID[:3]:
            write_report(tmp_path, f"grid-{t}-{v}", [synth_corner(p, t, v) for p in R.PROCESSES])
        red = R.reduce(tmp_path, None)
        self.assertTrue(not red["matrix"]["complete"] and red["matrix"]["unmet"] == 3)
        self.assertTrue(all("no report covers" in p["reasons"][0] for p in red["points"] if p["status"] == "UNMET"))


    def test_oracle_mismatch_and_absent_measurement(self):
        tmp_path = self.tmpdir()
        t, v = R.GRID[1]
        write_report(tmp_path, "grid-a", [synth_corner("tt", t, v, flip="rdata_k0_b0"),
                                     synth_corner("ss", t, v, drop="i_vdd_w2"),
                                     synth_corner("ff", t, v, status="error")])
        red = R.reduce(tmp_path, None)
        by = {p["process"]: p for p in red["points"] if p["temperature_c"] == t}
        self.assertTrue(by["tt"]["status"] == "UNMET" and any("oracle" in r for r in by["tt"]["reasons"]))
        self.assertTrue(by["ss"]["status"] == "UNMET" and any("absent" in r for r in by["ss"]["reasons"]))
        self.assertTrue(by["ff"]["status"] == "UNMET")
        self.assertTrue(red["ac3_claimable"] is False)


    def test_omitted_measurement_is_unmet(self):
        tmp_path = self.tmpdir()
        t, v = R.GRID[1]
        write_report(tmp_path, "grid-a", [synth_corner("tt", t, v, omit="i_vdd_w2"),
                                          synth_corner("ss", t, v, omit="rdata_k0_b0"),
                                          synth_corner("ff", t, v)])
        red = R.reduce(tmp_path, None)
        by = {p["process"]: p for p in red["points"] if p["temperature_c"] == t}
        for proc in ("tt", "ss"):
            self.assertTrue(by[proc]["status"] == "UNMET" and any("omitted" in r for r in by[proc]["reasons"]))
        self.assertTrue(by["ff"]["status"] == "MET")

    def test_nonfinite_measurement_is_unmet(self):
        tmp_path = self.tmpdir()
        t, v = R.GRID[1]
        c = synth_corner("tt", t, v)
        c["measurements"][0]["value"] = float("nan")
        write_report(tmp_path, "grid-a", [c])
        red = R.reduce(tmp_path, None)
        pt = next(p for p in red["points"] if p["process"] == "tt" and p["temperature_c"] == t)
        self.assertTrue(pt["status"] == "UNMET")

    def test_midrail_sample_is_unmet(self):
        # an XSPICE out_undef X (vdd/2) must not round to logical 0: the
        # shared rail-bounded decode makes it a named oracle failure
        tmp_path = self.tmpdir()
        t, v = R.GRID[1]
        c = synth_corner("tt", t, v)
        for e in c["measurements"]:
            if e["name"] == "rdata_k36_b0":
                e["value"] = v / 2.0
        write_report(tmp_path, "grid-a", [c])
        red = R.reduce(tmp_path, None)
        pt = next(p for p in red["points"] if p["process"] == "tt" and p["temperature_c"] == t)
        self.assertTrue(pt["status"] == "UNMET" and any("oracle" in r for r in pt["reasons"]))
        self.assertFalse(pt["oracle"]["match"])
        self.assertTrue(any("not a resolved rail" in mm for mm in pt["oracle"]["mismatches"]))

    def test_duplicate_measurement_name_is_unmet(self):
        # a repeated name displaces the entry it duplicates in every
        # name-keyed read, so the reducer must refuse the oracle (#642,
        # the guard #548 gave the gate-model comparator)
        tmp_path = self.tmpdir()
        t, v = R.GRID[1]
        c = synth_corner("tt", t, v)
        c["measurements"].append({"name": "i_vdd_w2", "value": -9e-6})
        write_report(tmp_path, "grid-a", [c])
        red = R.reduce(tmp_path, None)
        pt = next(p for p in red["points"] if p["process"] == "tt" and p["temperature_c"] == t)
        self.assertTrue(pt["status"] == "UNMET" and any("duplicate" in r for r in pt["reasons"]))

    def test_real_gate_model_report_cross_check(self):
        # the committed 75-cycle gate-model run's REAL ngspice voltages fed
        # through the 12-point reducer's corner analysis must match the
        # shared oracle. The bespoke block this replaces misrowed 8 bus
        # reads on exactly this report (issue #642): same comparator, same
        # verdict as runs/20261114-gate-model-full/compare.json (311/311).
        MG = load_module("make_gate_model", BLOCK / "make-gate-model.py")
        report = json.loads((BLOCK / "runs" / "20261114-gate-model-full" / "report.json").read_text())
        real = {e["name"]: e["value"] for e in report["corners"][0]["measurements"]}
        c = synth_corner("tt", 27.0, 1.8, bits=[int(b) for b in MG.RAW_BIT_PATTERN])
        n_real = 0
        for e in c["measurements"]:
            if e["name"] in real:
                e["value"] = real[e["name"]]
                n_real += 1
        # every digital name the 610-measurement contract shares with the
        # report is now a real voltage; only the deck-driven sampler strobes
        # and the t_stop-clipped k=74 rdata word stay synthetic
        self.assertGreater(n_real, 400)
        res = R.analyse_corner(c, 1.8)
        self.assertEqual(res["problems"], [])
        self.assertTrue(res["oracle"]["match"] is True and res["oracle"]["checks"] > 0)

    def test_pwl_highs_use_declared_vih(self):
        cycles, _ = P.build_program()
        cards = P.input_cards(cycles, len(cycles), P.VIH)
        peaks = [max(float(x) for x in c.split("PWL(")[1].rstrip(")").split()[1::2]) for c in cards]
        self.assertTrue(max(peaks) == P.VIH and all(p in (0.0, P.VIH) for p in peaks))

    def test_probe_measurements_within_stop_time(self):
        cycles, _ = P.build_program(limit=6)
        t_stop = P.t_stop_ns(cycles)
        meas, _ = P.whole_block_measurement_cards(cycles)
        import re
        for e in meas:
            mt = re.search(r"AT=([0-9.]+)n", e["spice"])
            if mt:
                self.assertTrue(float(mt.group(1)) <= t_stop, e["name"])

    def test_rate_probe_measurements_within_stop_time(self):
        import re
        mr = make_requests()
        stop = mr.RATE_PROBE_STOP_NS
        self.assertTrue(stop < P.T0_NS)  # no clock-dependent measurement possible
        meas, save = mr.rate_probe_measurements(stop)
        self.assertTrue(len(meas) > 0 and len(save) > 0)
        for e in meas:
            times = [float(x) for x in re.findall(r"(?:AT|TO)=([0-9.]+)n", e["spice"])]
            self.assertTrue(times and max(times) <= stop, e["name"])

    def test_analog_probe_netlist_partition(self):
        text = make_requests().analog_netlist_text()
        self.assertEqual(text.count("sky130_fd_pr__"), 264)
        # every port reaches the body under its canonical name (the committed
        # body has carried canonical names since #435's body rename)
        for port in ("en2", "vddr3", "vdd", "vss", "clk", "ring_bit1"):
            self.assertRegex(text.split("* device instance", 1)[1], r"(?<!\S)%s(?!\S)" % port)
        self.assertNotIn("en|en2|g_en", text)

    def test_analog_probe_stop_covers_clock(self):
        self.assertTrue(make_requests().ANALOG_PROBE_STOP_NS > P.T0_NS)

    def test_error_envelope_stays_unmet(self):
        tmp_path = self.tmpdir()
        d = tmp_path / "grid-b"
        d.mkdir()
        (d / "report.json").write_text(json.dumps({"error": {"message": "launch failed: cap"}}))
        (d / "plan.json").write_text(json.dumps({"corners": {"process": ["tt", "ss", "ff"],
                                                             "temperature_c": [27.0],
                                                             "supply_v": {"Vvdd": [1.8]}}}))
        red = R.reduce(tmp_path, None)
        um = [p for p in red["points"] if p["temperature_c"] == 27.0]
        self.assertTrue(all(p["status"] == "UNMET" and "launch failed" in p["reasons"][0] for p in um))

    def test_probe_dirs_do_not_count(self):
        tmp_path = self.tmpdir()
        write_report(tmp_path, "startup-probe", [synth_corner("tt", 27.0, 1.8)])
        red = R.reduce(tmp_path, None)
        self.assertTrue(red["matrix"]["met"] == 0 and len(red["sources"]) == 1)

    def _complete(self):
        tmp_path = self.tmpdir()
        for t, v in R.GRID:
            write_report(tmp_path, f"grid-{t}-{v}", [synth_corner(p, t, v) for p in R.PROCESSES])
        return tmp_path

    def test_o5d_unmet_with_clean_corner_and_oracle_match(self):
        red = R.reduce(self._complete(), None)
        self.assertTrue(red["matrix"]["complete"])
        obs = {o["id"]: o for o in red["obligations"]}
        self.assertEqual(sorted(obs), ["O1", "O2", "O3", "O4", "O5a", "O5d", "O6", "O7", "O8"])
        for oid in ("O5d", "O7", "O8"):
            self.assertEqual(obs[oid]["status"], "UNMET")
        for oid in ("O1", "O2", "O3", "O4", "O5a", "O6"):
            self.assertEqual(obs[oid]["status"], "MET")
        self.assertIs(red["ac3_claimable"], False)

    def test_power_provenance_and_level_labels(self):
        red = R.reduce(self._complete(), None)
        self.assertEqual(red["level"], R.LEVEL_MIXED)
        self.assertEqual(red["provenance"], {"analog": "transistor", "digital": "gate-level"})
        for pt in red["points"]:
            self.assertEqual(pt["level"], R.LEVEL_MIXED)
            pp = pt["power"]["provenance"]
            self.assertEqual(pp["digital_dynamic_power_w_estimate"], "gate-level")
            for k in ("i_vdd_w1", "i_vdd_w2", "i_vss_w2", "digital_delta_i_a"):
                self.assertEqual(pp[k], "mixed")

    def test_absent_provenance_makes_every_row_unmet(self):
        red = R.reduce(self._complete(), None, provenance=None)
        self.assertTrue(all(o["status"] == "UNMET" for o in red["obligations"]))
        self.assertTrue(all(p["status"] == "UNMET" for p in red["points"]))
        self.assertFalse(red["matrix"]["complete"])
        self.assertIs(red["ac3_claimable"], False)
        self.assertEqual(red["level"], R.LEVEL_UNLABELLED)

    def test_gate_level_never_emits_unqualified_transistor_label(self):
        red = R.reduce(self._complete(), None)
        text = R.render(red) + json.dumps(red, default=str)
        self.assertIn("mixed-level (analog transistor / digital gate-level), connectivity-only extract (no R/C)", text)
        self.assertNotIn(R.LEVEL_TRANSISTOR, text)
        self.assertNotIn("transistor-level whole-block", text)
        self.assertNotIn("post-layout PVT", text)

    def test_plan_provenance_requires_every_grid_plan(self):
        tmp = self.tmpdir()
        for n, prov in (("grid-a", P.PROVENANCE), ("grid-b", P.PROVENANCE)):
            (tmp / n).mkdir()
            (tmp / n / "plan.json").write_text(json.dumps({"provenance": prov}))
        self.assertEqual(R.plan_provenance(tmp), P.PROVENANCE)
        (tmp / "grid-b" / "plan.json").write_text(json.dumps({}))
        self.assertIsNone(R.plan_provenance(tmp))
        self.assertIsNone(R.plan_provenance(self.tmpdir()))

    def test_boundary_signals_match_ports(self):
        ports = json.loads((BLOCK / "trng_whole.sim.ports.json").read_text())["ports"]
        import re
        names = {re.sub(r"\[\d+\]$", "", p["canonical"]) for p in ports}
        b = P.boundary_signals()
        inter = {n for n, v in b.items() if v["dir"] == "analog->digital"}  # internal nets
        self.assertEqual(set(b) - inter, names)
        self.assertEqual(sum(v["width"] for n, v in b.items() if n not in inter), len(ports))
        self.assertEqual(b["raw_bit"]["dir"], "analog->digital")
        self.assertEqual(b["en1"]["dir"], "tb->analog")

    def test_digital_stimulus_has_no_analog_sources(self):
        cycles, _ = P.build_program()
        st = P.digital_stimulus(cycles)
        self.assertEqual(len(st), 75)
        self.assertNotIn("raw_bit", st[0])
        self.assertEqual(st[4]["t_edge_ns"], P.t_edge_ns(4))

    def test_clis_reach_program_by_import_not_by_executing_a_sibling_cli(self):
        """#804: the request generator and the two analysis CLIs reach
        program.py's card sets and oracle by import; none may go back to
        executing a sibling CLI (loadmod) for them."""
        import re
        for rel in ("make-requests.py", "analysis/compare-gate-model.py",
                    "analysis/reduce-whole-block.py"):
            with self.subTest(cli=rel):
                text = (BLOCK / rel).read_text()
                self.assertIsNone(re.search(r"\bload_module\b|\bloadmod\b", text), rel)

    def test_plan_hashes_and_partition_counts(self):
        part = make_requests().partition_check()
        self.assertEqual(part["analog_transistors"] + part["digital_transistors"], 25355)
        self.assertEqual(part["analog_transistors"], 264)
        self.assertEqual(part["diode_instances"], 1)
        self.assertEqual(part["total_instances"], 25356)
        self.assertEqual(len({part["flat_whole_netlist_sha256"], part["analog_partition_sha256"],
                              part["digital_gate_netlist_sha256"]}), 3)


if __name__ == "__main__":
    unittest.main()
