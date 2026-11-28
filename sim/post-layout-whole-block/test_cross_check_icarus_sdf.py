#!/usr/bin/env python3
"""Unit tests for the Icarus + SDF vs gate-model cross-check comparison (issue #812).

Standard library only -- no klt, no PDK, no ngspice, no Icarus::

    python3 sim/post-layout-whole-block/test_cross_check_icarus_sdf.py

Covers:
1. Synthetic matching trace across all 75 cycles (gate, Icarus, model agree;
   first ``out_valid`` at cycle 36 reports ``"match"``; exit code 0).
2. Injected one-cycle ``out_valid`` shift (both delayed to 37 and advanced to 35):
   must report ``first_out_valid.status == "mismatch"``, record disagreements,
   and fail with non-zero verdict.
3. Injected word-value disagreement (``bus_rdata`` bit flip on the RAW_DATA pop;
   ``out_data`` mismatch at cycle 36): must report exact cycle/signal/values and fail.
4. Injected unresolvable X/Z literal from Icarus: never coerced to 0; fails.
5. Short prefix ``N = 6`` (shorter than first ``out_valid`` at cycle 36):
   ``first_out_valid.status`` MUST be ``"not_reached"`` (never ``"match"``),
   and stimulus card hashes match ``test_standalone_waveform_bytes``.
6. Full ``N = 75`` stimulus card hashes match ``test_standalone_waveform_bytes``'s
   pinned SHA-256 digests.
7. Extraction from the committed ``20261114-gate-model-full`` report + plan
   decodes all 749 measurements with zero undecodable entries and matches a
   synthetic model-equivalent Icarus trace.
8. Fail-closed guards: duplicate measurement names in the gate report and
   truncated Icarus traces refuse loudly.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim" / "bin"))

import program as P
from loadmod import load_module

CROSS_CHECK_PATH = HERE / "analysis" / "cross-check-icarus-sdf.py"
COMMITTED_REPORT = HERE / "runs" / "20261114-gate-model-full" / "report.json"
COMMITTED_PLAN = HERE / "corners" / "gate-model-full" / "plan.json"


def _load_cc():
    return load_module("cross_check_icarus_sdf", CROSS_CHECK_PATH)


def _model_rows_for_pattern(pattern: str) -> list[dict]:
    bits = [int(c) for c in pattern]
    full_bits = bits + [0] * (P.N_SAMPLES_REG + P.N_SAMPLES_STREAM - len(bits))
    return P.model_replay(full_bits)


def _synthetic_icarus_rows(model_rows: list[dict], n_cycles: int) -> list[dict]:
    rows = []
    for k in range(n_cycles):
        m = model_rows[k]["model"]
        rows.append({
            "cycle": k,
            "bus_rdata": int(m["bus_rdata"]),
            "out_valid": int(m["out_valid"]),
            "out_data": int(m["out_data"]),
            "alarm": int(m["alarm"]),
            "gated": int(m["gated"]),
            "startup_done": int(m["startup_done"]),
        })
    return rows


def _synthetic_gate_obs(model_rows: list[dict], n_cycles: int, pattern: str) -> dict:
    cycles, _ = P.build_program(limit=n_cycles)
    inputs = P.cycle_inputs(cycles)
    rdata = {}
    for k, inp in enumerate(inputs[:-1]):
        if inp["re"]:
            rdata[k] = int(model_rows[k + 1]["model"]["bus_rdata"])
    odata = {}
    for k in P.streaming_word_cycles(n_cycles):
        odata[k] = int(model_rows[k]["model"]["out_data"])
    scalars = {}
    for k in range(n_cycles):
        m = model_rows[k]["model"]
        scalars[k] = {
            "out_valid": int(m["out_valid"]),
            "alarm": int(m["alarm"]),
            "gated": int(m["gated"]),
            "startup_done": int(m["startup_done"]),
        }
    return {
        "n_cycles": n_cycles,
        "corner_id": "tt_27C",
        "corner_status": "pass",
        "supply_v": 1.8,
        "ngspice_version": "ngspice-47",
        "liberty_deck": "sky130_fd_sc_hd__tt_025C_1v80.lib",
        "liberty_sha256": "8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135",
        "routed_netlist_sha256": "9f3956848e6e75223f75bd154df905fecbb4e988593e78d1a92e347969fbf37f",
        "raw_bit_pattern": pattern,
        "rdata": rdata,
        "odata": odata,
        "scalars": scalars,
        "undecodable": [],
    }


class TestCrossCheckComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cc = _load_cc()
        cls.plan = json.loads(COMMITTED_PLAN.read_text())
        cls.pattern = cls.plan["raw_bit_pattern"]
        cls.model_rows = _model_rows_for_pattern(cls.pattern)

    def test_synthetic_matching_trace_passes(self) -> None:
        n = 75
        gate = _synthetic_gate_obs(self.model_rows, n, self.pattern)
        icarus = _synthetic_icarus_rows(self.model_rows, n)
        res = self.cc.compare_traces(gate, icarus, self.model_rows, n)
        self.assertEqual(res["verdict"], "pass")
        self.assertEqual(res["disagreements"], [])
        self.assertEqual(res["first_out_valid"], {
            "gate": 36, "icarus": 36, "model": 36, "status": "match",
        })
        self.assertEqual(res["counts"]["words_compared"], 11)
        self.assertEqual(res["counts"]["words_matched"], 11)
        self.assertEqual(res["counts"]["words_not_compared"], 3)
        self.assertEqual(res["counts"]["scalars_compared"], 300)
        self.assertEqual(res["counts"]["scalars_matched"], 300)
        self.assertEqual(res["counts"]["gate_vs_icarus_total"], 311)
        self.assertEqual(res["counts"]["gate_vs_icarus_matched"], 311)

    def test_injected_one_cycle_out_valid_shift_delayed_fails(self) -> None:
        n = 75
        gate = _synthetic_gate_obs(self.model_rows, n, self.pattern)
        icarus = _synthetic_icarus_rows(self.model_rows, n)
        # Shift Icarus out_valid one cycle later: 36 -> 0, 37 -> 1, 38 -> 1
        icarus[36]["out_valid"] = 0
        icarus[38]["out_valid"] = 1
        res = self.cc.compare_traces(gate, icarus, self.model_rows, n)
        self.assertEqual(res["verdict"], "fail")
        self.assertEqual(res["first_out_valid"]["status"], "mismatch")
        self.assertEqual(res["first_out_valid"]["gate"], 36)
        self.assertEqual(res["first_out_valid"]["icarus"], 37)
        self.assertEqual(res["first_out_valid"]["model"], 36)
        kinds = {d["kind"] for d in res["disagreements"]}
        self.assertIn("first_out_valid", kinds)
        self.assertIn("scalar", kinds)
        ov_cycles = {
            d["cycle"] for d in res["disagreements"]
            if d["kind"] == "scalar" and d["signal"] == "out_valid"
        }
        self.assertEqual(ov_cycles, {36, 38})

    def test_injected_one_cycle_out_valid_shift_early_fails(self) -> None:
        n = 75
        gate = _synthetic_gate_obs(self.model_rows, n, self.pattern)
        icarus = _synthetic_icarus_rows(self.model_rows, n)
        icarus[35]["out_valid"] = 1
        res = self.cc.compare_traces(gate, icarus, self.model_rows, n)
        self.assertEqual(res["verdict"], "fail")
        self.assertEqual(res["first_out_valid"]["status"], "mismatch")
        self.assertEqual(res["first_out_valid"]["icarus"], 35)

    def test_injected_bus_rdata_and_out_data_mismatch_fails(self) -> None:
        n = 75
        gate = _synthetic_gate_obs(self.model_rows, n, self.pattern)
        icarus = _synthetic_icarus_rows(self.model_rows, n)
        # Flip LSB of RAW_DATA pop (read cycle 37 -> observed in cycle 38)
        icarus[38]["bus_rdata"] ^= 1
        # Flip MSB of streaming word at cycle 36
        icarus[36]["out_data"] ^= 0x80000000
        res = self.cc.compare_traces(gate, icarus, self.model_rows, n)
        self.assertEqual(res["verdict"], "fail")
        word_dis = [d for d in res["disagreements"] if d["kind"] == "word"]
        self.assertEqual({(d["signal"], d["cycle"]) for d in word_dis},
                         {("bus_rdata", 38), ("out_data", 36)})

    def test_unresolvable_xz_in_icarus_fails_never_coerced(self) -> None:
        n = 75
        gate = _synthetic_gate_obs(self.model_rows, n, self.pattern)
        icarus = _synthetic_icarus_rows(self.model_rows, n)
        icarus[40]["bus_rdata"] = "0000000x"  # model expects 0; must NOT coerce to 0
        icarus[10]["alarm"] = "x"             # model expects 0; must NOT coerce to 0
        res = self.cc.compare_traces(gate, icarus, self.model_rows, n)
        self.assertEqual(res["verdict"], "fail")
        self.assertTrue(any(d["cycle"] == 40 and d["signal"] == "bus_rdata"
                            for d in res["disagreements"]))
        self.assertTrue(any(d["cycle"] == 10 and d["signal"] == "alarm"
                            for d in res["disagreements"]))

    def test_short_prefix_reports_not_reached_not_match(self) -> None:
        n = 6
        gate = _synthetic_gate_obs(self.model_rows, n, self.pattern[:2])
        icarus = _synthetic_icarus_rows(self.model_rows, n)
        res = self.cc.compare_traces(gate, icarus, self.model_rows, n)
        self.assertEqual(res["verdict"], "pass")
        self.assertEqual(res["first_out_valid"], {
            "gate": None, "icarus": None, "model": None, "status": "not_reached",
        })
        self.assertNotEqual(res["first_out_valid"]["status"], "match")

    def test_stimulus_hashes_match_pinned_standalone_waveform_bytes(self) -> None:
        # Pinned in test_make_requests.py::test_standalone_waveform_bytes
        for count, req_sha, gate_sha in (
            (6, "d9d8ae12bab9f3d0898a2c95f6409ff65e329961bf97dbec3e0a6aa022f1f276",
             "656f1a1faf32cea1dd71d27c4dd9f4764e19304170eaa4d31b347307f8893a3f"),
            (75, "6fe44c0b0bab82a0b81f6eb83a052c3042d4b16d2145e7f81d2da07bf2a9333d",
             "d16a420004f83722abf1e03af3e11e7509e8bf1a3a47add9c86eed2a36a0b0c9"),
        ):
            stim = self.cc.build_stimulus_vectors(count)
            self.assertEqual(stim["shared_input_cards_sha256"], req_sha)
            self.assertEqual(stim["gate_stimulus_cards_sha256"], gate_sha)
            self.assertEqual(len(stim["vectors"]), count)

    def test_committed_gate_model_report_decodes_and_matches_synthetic_icarus(self) -> None:
        report = json.loads(COMMITTED_REPORT.read_text())
        gate = self.cc.extract_gate_model_trace(report, self.plan, 75)
        self.assertEqual(gate["undecodable"], [])
        self.assertEqual(gate["rdata"][37], 0x5C6A78E9)
        self.assertEqual(gate["odata"][36], 0x5C6A78E9)
        icarus = _synthetic_icarus_rows(self.model_rows, 75)
        res = self.cc.compare_traces(gate, icarus, self.model_rows, 75)
        self.assertEqual(res["verdict"], "pass")
        self.assertEqual(res["first_out_valid"]["status"], "match")
        self.assertEqual(res["first_out_valid"]["gate"], 36)

    def test_duplicate_gate_measurement_refused(self) -> None:
        report = json.loads(COMMITTED_REPORT.read_text())
        bad = copy.deepcopy(report)
        bad["corners"][0]["measurements"][-1]["name"] = bad["corners"][0]["measurements"][0]["name"]
        with self.assertRaises(self.cc.CrossCheckError):
            self.cc.extract_gate_model_trace(bad, self.plan, 75)

    def test_truncated_icarus_trace_fails_closed(self) -> None:
        gate = _synthetic_gate_obs(self.model_rows, 75, self.pattern)
        icarus = _synthetic_icarus_rows(self.model_rows, 40)  # truncated
        with self.assertRaises(self.cc.CrossCheckError):
            self.cc.compare_traces(gate, icarus, self.model_rows, 75)

    def test_cli_exits_nonzero_on_disagreement(self) -> None:
        stim = self.cc.build_stimulus_vectors(75, raw_bit_pattern=self.pattern)
        bad_obs = _synthetic_icarus_rows(self.model_rows, 75)
        bad_obs[36]["out_valid"] = 0
        bad_obs[38]["out_valid"] = 1
        fake_icarus = {
            "observations": bad_obs,
            "observations_txt": "",
            "stimulus_txt": stim["stimulus_text"],
            "stimulus_txt_sha256": stim["stimulus_text_sha256"],
            "observations_txt_sha256": "0" * 64,
            "clk_ns": 100,
            "klt_version": "0.8.0",
            "engine_version": "13.0",
            "cocotb_version": "2.0.1",
            "iverilog_banner": "Icarus Verilog version 13.0 (stable) (v13_0)",
            "sdf_env": {"annotated": True, "corner": "typ", "partial": True},
            "sdf_gz_sha256": "0" * 64,
            "sdf_plain_sha256": "0" * 64,
            "sdf_clean_sha256": "0" * 64,
            "sdf_dropped_count": 39,
            "sdf_census": {},
            "routed_netlist_sha256": self.plan["routed_netlist_sha256"],
            "primitives_v_sha256": "0" * 64,
            "cells_v_sha256": "0" * 64,
            "tb_sha256": "0" * 64,
            "probe_stats": {},
            "fv_report_status": "pass",
            "fv_test_count": 1,
            "fv_passed_count": 1,
        }
        with (
            mock.patch.object(self.cc.shutil, "which", return_value="/usr/bin/fake"),
            mock.patch.object(self.cc, "_run_icarus_sdf", return_value=fake_icarus),
        ):
            rc = self.cc.main(["--klt", "fake-klt", "--cycles", "75"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
