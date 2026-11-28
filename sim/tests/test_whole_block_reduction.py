"""Issue #174: the whole-block reducer must count coverage honestly.

Builds synthetic ``klt sim`` reports whose digital measurements are generated
from the normative model itself, then checks: a complete matrix is MET, an
omitted point is UNMET (incomplete coverage named), a flipped bus bit is an
oracle mismatch, a klt error envelope / errored corner stays UNMET, and an
absent measurement never passes.

Issue #815 adds the coupled matrix (DR-0017 option (b), one single-process
request per point): the committed nominal coupled report
(``runs/20261128-coupled-full``, augmented with finite ring-rail and timing
scalars the matrix set adds) replays as a positive digital control -- 75
sampler strobes, 311 matching responses -- and each failure mode is a
negative control: a corrupted capture, an omitted required current, a report
associated with the wrong point, a report of another deck, a duplicate point.
The archived flat-deck ``corners/grid-*`` inputs stay readable throughout.
"""
import copy
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
import pvt_deck_map as PVT  # noqa: E402

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


# --------------------------------------------------------------------------
# Issue #815: the coupled 12-point matrix, matched to its plan / deck / point
# --------------------------------------------------------------------------

COUPLED_RUN = BLOCK / "runs" / "20261128-coupled-full"
COUPLED_PLAN = json.loads((COUPLED_RUN / "requests" / "coupled-full" / "plan.json").read_text())
#: the point the committed coupled run measured
NOMINAL = ("tt", 27.0, 1.8)

#: finite stand-ins for the matrix-only measurements (the ring-rail W1/W2
#: currents and the throughput tap) the committed 900-measurement report
#: predates; values are placeholders with no characterisation credit
MATRIX_SCALARS = {**{f"i_{r}_w1": -1.2e-5 for r in P.RAILS},
                  **{f"i_{r}_w2": -1.3e-5 for r in P.RAILS},
                  **{f"q_{r}_w2": -1.0e-10 for r in P.RAILS},
                  "i_vss_w2": -2.0e-6, "t_out_valid_first": 3.7e-6}


def committed_coupled_report() -> dict:
    """The real nominal coupled report, augmented with the matrix set's
    ring-rail and timing scalars (every committed measurement untouched)."""
    doc = json.loads((COUPLED_RUN / "report.json").read_text())
    have = {m["name"] for m in doc["corners"][0]["measurements"]}
    for e in P.coupled_matrix_measurements(P.build_program()[0], 1.8)[0]:
        if e["name"] not in have:
            doc["corners"][0]["measurements"].append({"name": e["name"], "value": MATRIX_SCALARS[e["name"]]})
    return doc


def coupled_plan(proc: str, temp: float, vdd: float, name: str, netlist_sha256: str | None = None,
                 with_deck: bool = True) -> dict:
    """A coupled single-point plan in the shape ``--set grid`` writes."""
    plan = copy.deepcopy(COUPLED_PLAN)
    plan["name"] = name
    plan["corners"] = {"process": [proc], "temperature_c": [temp],
                       "supply_v": {f"V{r}": [vdd] for r in P.RAILS}}
    plan["reductions"]["supply_v"] = vdd
    plan["reductions"]["dac_bridge_out_high_v"] = vdd
    if netlist_sha256 is not None:
        plan["netlist_sha256"] = netlist_sha256
    if with_deck:
        row = PVT.deck_row(proc, temp, vdd)
        plan["gate_model_pvt"] = {
            "boundary_load": PVT.boundary_load_block(),
            "decks": {proc: {**{k: row[k] for k in ("exact", "dT_K", "dV_V", "delay_direction",
                                                    "est_delay_error_pct", "power_direction")},
                             "liberty_deck": f"<libs.ref>/{row['liberty_deck']}",
                             "liberty_sha256": row["liberty_sha256"]}},
            "deck_path_form": "test"}
        plan["liberty_sha256"] = row["liberty_sha256"]
    return plan


def synth_coupled_corner(proc, temp, vdd, bits=None, status="pass"):
    """A coupled-deck corner whose every measurement is the normative model's
    own answer to the sampler captures ``bits`` (one per strobed cycle), at
    ``vdd`` rails -- the coupled counterpart of ``synth_corner``."""
    cycles, _ = P.build_program()
    entries, _ = P.coupled_matrix_measurements(cycles, vdd)
    bits = list(bits) if bits is not None else BITS
    strobes = P.sampler_valid(cycles)
    rows = P.model_replay(bits, captured_valid=strobes)
    hi = vdd
    vals = {}
    bit_i = 0
    for k, valid in enumerate(strobes):
        vals[f"raw_valid_k{k}"] = hi * valid
        if valid:
            vals[f"raw_bit_k{k}"] = hi * bits[bit_i]
            bit_i += 1
    for e in entries:
        n = e["name"]
        if n in vals:
            continue
        if n.startswith("rdata_k"):
            k, b = n[len("rdata_k"):].split("_b")
            k = int(k)
            v = (rows[k + 1]["model"]["bus_rdata"] >> int(b)) & 1 if k + 1 < len(rows) else 0
            vals[n] = hi * v
        elif n.startswith("odata_k"):
            k, b = n[len("odata_k"):].split("_b")
            vals[n] = hi * ((rows[int(k)]["model"]["out_data"] >> int(b)) & 1)
        elif n.startswith(("alarm_k", "gated_k", "startup_done_k", "out_valid_k")):
            sig, k = n.rsplit("_k", 1)
            vals[n] = hi * int(rows[int(k)]["model"][sig])
        elif n in MATRIX_SCALARS:
            vals[n] = MATRIX_SCALARS[n]
        else:                       # clk_at_stop, t_clk_first
            vals[n] = 1e-12
    return {"process": proc, "temperature_c": temp, "supply_v": {f"V{r}": vdd for r in P.RAILS},
            "status": status, "diagnostics": [], "runtime_s": 431.63,
            "measurements": [{"name": k, "value": v} for k, v in vals.items()]}


def write_coupled(root: Path, dirname: str, plan: dict, report: dict) -> Path:
    d = root / dirname
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps(plan))
    (d / "report.json").write_text(json.dumps(report))
    return d


def coupled_report_doc(corner: dict, netlist_sha256: str) -> dict:
    return {"status": "pass", "environment": {"netlist_sha256": netlist_sha256,
                                               "remote": {"state": "done"}},
            "corners": [corner]}


def point_row(red: dict, proc: str, temp: float, vdd: float) -> dict:
    return next(p for p in red["points"] if p["point"] == R.key(proc, temp, vdd))


class CoupledMatrixReduction(unittest.TestCase):
    """#815: a coupled matrix point is matched to its plan, deck and PVT
    point, decoded against its own rail and replayed through the sampler's
    oracle; every failure mode leaves a reasoned UNMET."""

    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="wbred-coupled-")
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)

    def nominal_case(self, report=None, plan=None, dirname="grid-tt-27C-1.80V", root=None):
        """The committed nominal run filed as the tt / 27 C / 1.8 V point."""
        report = committed_coupled_report() if report is None else report
        plan = coupled_plan(*NOMINAL, name=dirname) if plan is None else plan
        return write_coupled(root or self.root, dirname, plan, report)

    def fresh(self, name: str) -> Path:
        """A separate corners directory for one sub-case of a test."""
        return self.root / name
    @staticmethod
    def measurement(doc: dict, name: str) -> dict:
        return next(m for m in doc["corners"][0]["measurements"] if m["name"] == name)

    def test_committed_nominal_replay_is_met(self):
        """The positive digital control: the real capture replays to 75
        sampler strobes and 311 matching responses, and the point is MET."""
        self.nominal_case()
        red = R.reduce(self.root, None)
        pt = point_row(red, *NOMINAL)
        self.assertEqual(pt["status"], "MET", pt["reasons"])
        self.assertEqual(pt["reasons"], [])
        self.assertEqual(pt["oracle"], {"checks": 75 + 75 + 311, "strobes": 75, "bits": 75,
                                        "responses": 311, "mismatches": [], "match": True})
        self.assertEqual(pt["level"], R.LEVEL_MIXED)
        self.assertEqual(pt["gate_model_sha256"], COUPLED_PLAN["gate_model_sha256"])
        self.assertEqual(pt["timing"]["t_out_valid_first_s"], MATRIX_SCALARS["t_out_valid_first"])
        self.assertEqual(pt["power"]["provenance"]["digital_dynamic_power_w_estimate"], "gate-level")
        self.assertEqual((red["matrix"]["met"], red["matrix"]["unmet"]), (1, 11))
        obs = {o["id"]: o for o in red["obligations"]}
        for oid in ("O5d", "O7", "O8"):
            self.assertEqual(obs[oid]["status"], "UNMET")          # forced, whatever the numbers
        self.assertEqual(obs["O1"]["reasons"], ["11 of 12 point(s) UNMET (first: ['tt/-40C/1.62V', 'ss/-40C/1.62V', 'ff/-40C/1.62V'])"])
        self.assertIs(red["ac3_claimable"], False)
        self.assertEqual(red["provenance"], P.PROVENANCE)

    def test_corrupted_capture_is_unmet(self):
        cases = []
        # a mid-rail raw_bit (an X) is never rounded to a rail
        doc = committed_coupled_report()
        self.measurement(doc, "raw_bit_k4")["value"] = 0.9
        cases.append((doc, "raw_bit_k4: level 0.9 V is not a resolved rail"))
        # a strobe the sampler cannot produce
        doc = committed_coupled_report()
        self.measurement(doc, "raw_valid_k36")["value"] = 0.0
        cases.append((doc, "raw_valid_k36: captured 0 != the sampler's documented 1"))
        # a flipped sampler bit: the responses no longer follow the capture
        doc = committed_coupled_report()
        m = self.measurement(doc, "raw_bit_k4")
        m["value"] = 1.8 - m["value"]
        cases.append((doc, None))
        for i, (doc, needle) in enumerate(cases):
            with self.subTest(case=i):
                self.nominal_case(report=doc, root=self.fresh(f"case{i}"))
                pt = point_row(R.reduce(self.fresh(f"case{i}"), None), *NOMINAL)
                self.assertEqual(pt["status"], "UNMET")
                self.assertFalse(pt["oracle"]["match"])
                if needle is not None:
                    self.assertIn(needle, pt["oracle"]["mismatches"])
                    self.assertTrue(any("oracle" in r and needle[:40] in r for r in pt["reasons"]))
                else:
                    self.assertTrue(any("transistor" in mm and "model" in mm for mm in pt["oracle"]["mismatches"]))
        # the deasserted strobe still decodes: 75 strobes, one fewer bit consumed
        pt = point_row(R.reduce(self.fresh("case1"), None), *NOMINAL)
        self.assertEqual((pt["oracle"]["strobes"], pt["oracle"]["bits"]), (75, 74))

    def test_omitted_required_current_is_unmet(self):
        doc = committed_coupled_report()
        doc["corners"][0]["measurements"] = [m for m in doc["corners"][0]["measurements"]
                                             if m["name"] != "i_vddr3_w1"]
        self.nominal_case(report=doc, root=self.fresh("omitted"))
        pt = point_row(R.reduce(self.fresh("omitted"), None), *NOMINAL)
        self.assertEqual(pt["status"], "UNMET")
        self.assertEqual(pt["reasons"], ["1 required measurement(s) omitted from the report (first: ['i_vddr3_w1'])"])
        self.assertNotIn("oracle", pt)       # no oracle without the full contract
        # absent / non-finite is the same refusal
        doc = committed_coupled_report()
        self.measurement(doc, "i_vss_w2")["value"] = float("nan")
        self.nominal_case(report=doc, root=self.fresh("nonfinite"))
        pt = point_row(R.reduce(self.fresh("nonfinite"), None), *NOMINAL)
        self.assertEqual(pt["status"], "UNMET")
        self.assertTrue(any("absent/non-finite" in r and "i_vss_w2" in r for r in pt["reasons"]))
        # the control: the unmodified augmentation is complete
        self.nominal_case(root=self.fresh("control"))
        self.assertEqual(point_row(R.reduce(self.fresh("control"), None), *NOMINAL)["status"], "MET")

    def test_failed_unit_is_unmet(self):
        doc = committed_coupled_report()
        doc["corners"][0]["status"] = "timeout"
        doc["corners"][0]["diagnostics"] = [{"code": "timeout", "message": "unit killed at 864 s"}]
        self.nominal_case(report=doc)
        pt = point_row(R.reduce(self.root, None), *NOMINAL)
        self.assertEqual(pt["status"], "UNMET")
        self.assertEqual(pt["reasons"][:2], ["klt corner status 'timeout'", "diagnostic timeout: unit killed at 864 s"])

    def test_report_associated_with_the_wrong_point_is_unmet_on_both_points(self):
        """A tt report filed under an ss request: the point it reports and
        the point its plan asked for are both UNMET, neither scored."""
        doc = committed_coupled_report()
        plan = coupled_plan("ss", 27.0, 1.8, name="grid-ss-27C-1.80V")
        write_coupled(self.root, "grid-ss-27C-1.80V", plan, doc)
        red = R.reduce(self.root, None)
        reported = point_row(red, *NOMINAL)
        planned = point_row(red, "ss", 27.0, 1.8)
        self.assertEqual(reported["status"], "UNMET")
        self.assertEqual(reported["reasons"], [
            "report corner tt/27C/1.80V does not match its plan: process 'tt' is not one of the plan's ['ss']"])
        self.assertNotIn("oracle", reported)
        self.assertEqual((planned["status"], planned["reasons"]), (
            "UNMET", ["planned point ss/27C/1.80V: no corner of its report covers this planned point"]))
        self.assertEqual(red["matrix"]["met"], 0)
        # the same report under its own point IS scored -- the control
        self.root.joinpath("grid-ss-27C-1.80V").rename(self.root / "grid-tt-27C-1.80V")
        (self.root / "grid-tt-27C-1.80V" / "plan.json").write_text(json.dumps(coupled_plan(*NOMINAL, name="grid-tt-27C-1.80V")))
        self.assertEqual(point_row(R.reduce(self.root, None), *NOMINAL)["status"], "MET")

    def test_rail_mismatch_against_the_plan_is_unmet(self):
        """A corner at 1.8 V rails filed under a 1.62 V plan: all five rails
        are checked, and the levels are not this point's."""
        doc = committed_coupled_report()
        doc["corners"][0]["process"], doc["corners"][0]["temperature_c"] = "ss", -40.0
        for r in P.RAILS:
            doc["corners"][0]["supply_v"][f"V{r}"] = 1.62
        doc["corners"][0]["supply_v"]["Vvddr3"] = 1.8       # one rail off the plan
        write_coupled(self.root, "grid-ss-m40C-1.62V", coupled_plan("ss", -40.0, 1.62, name="grid-ss-m40C-1.62V"), doc)
        pt = point_row(R.reduce(self.root, None), "ss", -40.0, 1.62)
        self.assertEqual(pt["status"], "UNMET")
        self.assertEqual(pt["reasons"][0], "report corner ss/-40C/1.62V does not match its plan: "
                                           "vddr3 at 1.8 V is not one of the plan's [1.62] V")
        self.assertTrue(any("planned point ss/-40C/1.62V" in r for r in pt["reasons"]))

    def test_report_of_another_deck_is_unmet(self):
        doc = committed_coupled_report()
        doc["environment"]["netlist_sha256"] = "0" * 64
        self.nominal_case(report=doc)
        pt = point_row(R.reduce(self.root, None), *NOMINAL)
        self.assertEqual(pt["status"], "UNMET")
        self.assertEqual(pt["reasons"][0], "report netlist sha256 0000000000000000 != its plan's "
                                           f"{COUPLED_PLAN['netlist_sha256'][:16]}: the report did not run the planned deck")
        self.assertNotIn("oracle", pt)

    def test_request_disagreeing_with_its_plan_is_unmet(self):
        self.nominal_case()
        d = self.root / "grid-tt-27C-1.80V"
        request = {"corners": {"process": ["ss"], "temperature_c": [27.0],
                               "supply_v": {f"V{r}": [1.8] for r in P.RAILS}}}
        (d / "request.json").write_text(json.dumps(request))
        pt = point_row(R.reduce(self.root, None), *NOMINAL)
        self.assertEqual(pt["status"], "UNMET")
        self.assertIn("request.json corners differ from plan.json corners", pt["reasons"])

    def test_duplicate_point_report_is_unmet(self):
        self.nominal_case()
        write_coupled(self.root, "grid-tt-27C-1.80V-retry", coupled_plan(*NOMINAL, name="grid-tt-27C-1.80V-retry"),
                      committed_coupled_report())
        red = R.reduce(self.root, None)
        pt = point_row(red, *NOMINAL)
        self.assertEqual(pt["status"], "UNMET")
        self.assertEqual(pt["reasons"], ["2 report entries from ['grid-tt-27C-1.80V', 'grid-tt-27C-1.80V-retry'] "
                                         "claim this point: refusing to pick one"])
        self.assertEqual(pt["sources"], ["grid-tt-27C-1.80V", "grid-tt-27C-1.80V-retry"])
        self.assertNotIn("oracle", pt)      # neither is scored
        self.assertEqual(red["matrix"]["met"], 0)

    def test_non_nominal_point_decodes_against_its_own_rail(self):
        bits = [(i * 5 + 1) % 3 % 2 for i in range(75)]
        proc, temp, vdd = "ss", -40.0, 1.62
        corner = synth_coupled_corner(proc, temp, vdd, bits)
        self.assertEqual(R.analyse_corner(corner, vdd, coupled=True)["problems"], [])
        # the same levels at another point's rail are not rails at all
        res = R.analyse_corner(corner, 1.8, coupled=True)
        self.assertTrue(res["problems"] and not res["oracle"]["match"])
        self.assertIn("raw_valid_k0: level 1.62 V is not a resolved rail", res["oracle"]["mismatches"])
        plan = coupled_plan(proc, temp, vdd, name="grid-ss-m40C-1.62V")
        plan["gate_model_sha256"] = "b" * 64
        write_coupled(self.root, "grid-ss-m40C-1.62V", plan, coupled_report_doc(corner, plan["netlist_sha256"]))
        red = R.reduce(self.root, None)
        pt = point_row(red, proc, temp, vdd)
        self.assertEqual(pt["status"], "MET", pt["reasons"])
        self.assertEqual((pt["oracle"]["strobes"], pt["oracle"]["responses"]), (75, 311))
        self.assertEqual(pt["gate_model_sha256"], "b" * 64)
        row = PVT.deck_row(proc, temp, vdd)
        self.assertEqual(pt["digital_deck"], {
            **{k: row[k] for k in ("exact", "dT_K", "dV_V", "delay_direction", "est_delay_error_pct", "power_direction")},
            "liberty_deck": f"<libs.ref>/{row['liberty_deck']}", "liberty_sha256": row["liberty_sha256"]})
        self.assertEqual(pt["power"]["vdd_v"], 1.62)
        self.assertEqual(sorted(s["dir"] for s in red["sources"]), ["grid-ss-m40C-1.62V"])
        self.assertEqual(red["sources"][0]["deck"], "coupled (analog sampler -> gate model)")

    def test_a_plan_without_raw_source_keeps_the_flat_contract(self):
        """The routing key is the plan's ``raw_source``: a plan that does not
        say ``analog_sampler`` is read through the flat-deck contract."""
        t, v = R.GRID[1]
        corner = synth_corner("tt", t, v)
        corner["supply_v"] = {f"V{r}": v for r in P.RAILS}
        write_report(self.root, "grid-tt-27C-1.80V", [corner])
        (self.root / "grid-tt-27C-1.80V" / "plan.json").write_text(json.dumps({
            "corners": {"process": ["tt"], "temperature_c": [t], "supply_v": {f"V{r}": [v] for r in P.RAILS}},
            "raw_source": "transistor"}))
        pt = point_row(R.reduce(self.root, None, R.plan_provenance(self.root)), "tt", t, v)
        self.assertEqual(pt["status"], "UNMET")        # no PROVENANCE in this plan
        self.assertEqual(pt["reasons"], ["no PROVENANCE recorded: result level unknown"])
        self.assertIn("oracle", pt)                     # scored through the flat oracle
        self.assertNotIn("strobes", pt["oracle"])       # ... not the coupled one
        # a corner missing a rail the plan steps cannot be matched to its point
        corner["supply_v"] = {"Vvdd": v}
        root2 = self.root / "second"
        write_report(root2, "grid-tt-27C-1.80V", [corner])
        (root2 / "grid-tt-27C-1.80V" / "plan.json").write_text(json.dumps({
            "corners": {"process": ["tt"], "temperature_c": [t], "supply_v": {f"V{r}": [v] for r in P.RAILS}},
            "provenance": P.PROVENANCE}))
        pt = point_row(R.reduce(root2, None), "tt", t, v)
        self.assertEqual(pt["reasons"][0], "report corner tt/27C/1.80V does not match its plan: "
                                           "vddr1 at None V is not one of the plan's [1.8] V")


class LegacyFlatGridInputs(unittest.TestCase):
    """The archived flat-deck ``corners/grid-*`` stay readable (#815): three
    processes per report, no ``raw_source``, no PROVENANCE."""

    def test_committed_flat_grid_archives_stay_readable(self):
        red = R.reduce(BLOCK / "corners", None, R.plan_provenance(BLOCK / "corners"))
        self.assertEqual((red["matrix"]["expected"], red["matrix"]["met"]), (12, 0))
        self.assertEqual(red["level"], R.LEVEL_UNLABELLED)
        grids = {s["dir"]: s for s in red["sources"] if s["dir"].startswith("grid-")}
        self.assertEqual(sorted(grids), ["grid-125C-1.98V", "grid-27C-1.80V", "grid-m40C-1.62V", "grid-m40C-1.98V"])
        self.assertEqual([s["deck"] for s in red["sources"]], ["flat transistor-level"] * len(red["sources"]))
        self.assertTrue(all(s["status"] == "error" for s in grids.values()))
        for pt in red["points"]:
            self.assertEqual(pt["status"], "UNMET")
            self.assertEqual(pt["reasons"][0], "klt corner status 'error'", pt["point"])
            self.assertTrue(any("fleet runner runs klt 0.5.0" in r for r in pt["reasons"]), pt["point"])
            self.assertTrue(any("absent/non-finite" in r for r in pt["reasons"]), pt["point"])
            self.assertTrue(pt["reasons"][-1].startswith("no PROVENANCE recorded"))
            self.assertNotIn("digital_deck", pt)
            self.assertIn(pt["source"], grids)
        self.assertIn("`grid-27C-1.80V`: status `error`, deck `flat transistor-level`", R.render(red))

    def test_flat_grid_dirs_never_collide_with_the_coupled_ones(self):
        """``grid-<proc>-<T>-<V>`` (coupled, one process) against the archived
        ``grid-<T>-<V>`` (flat, three processes): both start with ``grid-``,
        which the reducer requires, and no name is shared."""
        mr = make_requests()
        coupled = {mr.grid_name(p, t, v) for (t, v) in R.GRID for p in R.PROCESSES}
        listed = {s["dir"] for s in R.reduce(BLOCK / "corners", None)["sources"]}
        flat = {n for n in listed if n.startswith("grid-")}
        self.assertEqual(len(coupled), 12)
        self.assertEqual(flat, {"grid-125C-1.98V", "grid-27C-1.80V", "grid-m40C-1.62V", "grid-m40C-1.98V"})
        self.assertFalse(coupled & flat)
        self.assertEqual(mr.GRID, R.GRID)
        self.assertEqual({(p, t, v) for p, t, v in R.expected_points()},
                         {(p, t, v) for (t, v) in mr.GRID for p in PVT.MATRIX_PROCESSES})


if __name__ == "__main__":
    unittest.main()
