#!/usr/bin/env python3
"""Issue #766: the synthesis report must not claim an unproven equivalence.

    python3 sim/tests/test_synthesis_report.py

Standard library only. Drives ``synthesize-and-verify.main()`` end to end
with controlled synthesis, proof and cosimulation responses -- no klt, no
yosys, no iverilog, no PDK install -- and pins the report contract the
issue states: the per-configuration table is where the observed outcomes
appear, the printed report never asserts an equivalence the runs did not
prove (a skipped or inconclusive proof must not be followed by a fixed
"proven equivalent" paragraph), the timing/leakage/scope notes survive,
and the record writer is reached only by a fully passing run with
``--emit-record``.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "bin"))
from loadmod import load_module  # noqa: E402

SLUG = SIM / "digital-synthesis"
harness = load_module("synthesize_and_verify",
                      SLUG / "harness" / "synthesize-and-verify.py")

# The unconditional success paragraph the issue removes: main printed it
# even when the table above it said SKIPPED or inconclusive.
CLAIM_BULLET = "- It establishes that"
CLAIM_EQUIV = "equivalent to the source RTL"
OLD_HEADING = "## What this record does and does not establish"


class ControlledResponses(unittest.TestCase):
    """main() over stubbed synth/equiv/cosim responses, in a temp tree."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        # libs tree: the harness checks that the liberty it derives from the
        # fake synth response exists; the leakage parser is stubbed, so the
        # file itself can be empty.
        lib = self.tmp / "libs" / "sky130_fd_sc_hd" / "lib" / "fakesc.lib"
        lib.parent.mkdir(parents=True)
        lib.write_text("")
        for name in ("netlist.v", "stimulus.txt", "observations.txt"):
            (self.tmp / name).write_text("")

    def synth(self):
        return {
            "netlist_path": str(self.tmp / "netlist.v"),
            "instance_count": 10,
            "area_um2": 100.0,
            "sequential_area_um2": 40.0,
            "instance_counts_by_type": {"sky130_fd_sc_hd__dfxtp_1": 4},
            "engine_version": "yosys 0.0-fake",
            "timing": {"critical_path_ps": 1234},
            "provenance": {
                "klt_version": "0.0-fake",
                "input": {"content_hash": "aa"},
                "deck": {"name": "fakesc", "content_hash": "bb"},
            },
        }

    def equiv(self, status):
        return {"status": status, "engine": "yosys-sequential",
                "engine_version": "yosys 0.0-fake", "elapsed_s": 0.01}

    def cosim(self, ok=True):
        return {"ok": ok, "cycles": 64, "mismatches": 0 if ok else 3,
                "length_ok": True,
                "stimulus_path": str(self.tmp / "stimulus.txt"),
                "observations_path": str(self.tmp / "observations.txt"),
                "iverilog_version": "11 (fake)"}

    def drive(self, argv, equiv_status="equivalent"):
        """Run main(argv) under stubs; return (rc, stdout, stderr, mints).

        ``equiv_status=None`` leaves the stub's proof response None, which
        only ``--skip-equiv`` reaches (the harness never calls ``equiv``
        then). ``--keep`` is always forced into the temp tree so no
        mkdtemp()-style scratch directory leaks outside it.
        """
        mints = []
        synth = self.synth()
        eq = None if equiv_status is None else self.equiv(equiv_status)
        cosim = self.cosim()
        patches = [
            mock.patch.object(harness, "pdk_find",
                              return_value={"variant": "sky130A",
                                            "version": "fake"}),
            mock.patch.object(harness, "libs_ref_of",
                              return_value=self.tmp / "libs"),
            mock.patch.object(harness, "synthesize", return_value=synth),
            mock.patch.object(harness, "equiv", return_value=eq),
            mock.patch.object(harness, "gate_cosim",
                              SimpleNamespace(run=lambda *a, **k: cosim)),
            mock.patch.object(harness, "ll", SimpleNamespace(
                parse_cell_leakage_nw=lambda liberty: ({}, None),
                total_leakage_nw=lambda counts, by_cell: (1.0, []))),
            mock.patch.object(harness, "mint_behavioral_record",
                              side_effect=lambda **kw: mints.append(kw)
                              or "20261126-000000-0000000"),
            mock.patch("shutil.which", return_value="/usr/bin/true"),
        ]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = harness.main(
                    [*argv, "--keep", str(self.tmp / "run")])
        return rc, out.getvalue(), err.getvalue(), mints

    def test_skipped_proof_reports_the_skip_not_a_claim(self):
        rc, out, _err, mints = self.drive(["--skip-equiv"], equiv_status=None)
        self.assertEqual(rc, 0)
        for label in ("unconstrained", "50khz-constrained"):
            self.assertRegex(
                out, rf"\| {label} \|.*\| SKIPPED \| PASS \(64 cyc\) \|")
        self.assertNotIn(CLAIM_BULLET, out)
        self.assertNotIn(CLAIM_EQUIV, out)
        self.assertEqual(mints, [])

    def test_skip_equiv_still_refuses_to_mint(self):
        rc, _out, err, mints = self.drive(["--skip-equiv", "--emit-record"],
                                         equiv_status=None)
        self.assertEqual(rc, 2)
        self.assertIn("refusing to mint", err)
        self.assertEqual(mints, [])

    def test_inconclusive_proof_reports_the_outcome_not_a_claim(self):
        rc, out, err, mints = self.drive(["--emit-record"],
                                         equiv_status="inconclusive")
        self.assertEqual(rc, 1)
        for label in ("unconstrained", "50khz-constrained"):
            self.assertRegex(
                out, rf"\| {label} \|.*\| inconclusive \| PASS \(64 cyc\) \|")
        self.assertNotIn(CLAIM_BULLET, out)
        self.assertNotIn(CLAIM_EQUIV, out)
        # the record writer is reached only by a fully passing run
        self.assertEqual(mints, [])
        self.assertIn("refusing to mint", err)

    def test_passing_proof_mints_with_the_guarded_claim(self):
        rc, out, _err, mints = self.drive(["--emit-record"],
                                         equiv_status="equivalent")
        self.assertEqual(rc, 0)
        for label in ("unconstrained", "50khz-constrained"):
            self.assertRegex(
                out, rf"\| {label} \|.*\| equivalent \| PASS \(64 cyc\) \|")
        # detailed per-configuration proof result preserved
        self.assertIn("`klt equiv`: status **equivalent**", out)
        self.assertEqual(len(mints), 1)
        kw = mints[0]
        # stdout is exactly the minted body -- one report, no extra claims
        self.assertEqual(out, kw["body_md"] + "\n")
        # the guarded claim lives in the record's claim field, not in the
        # report text every iteration prints
        self.assertIn("klt-equiv-proven sequentially equivalent", kw["claim"])
        self.assertEqual(kw["level"], "gate")

    def test_scope_notes_survive_the_removal(self):
        rc, out, _err, _ = self.drive(["--skip-equiv"], equiv_status=None)
        self.assertEqual(rc, 0)
        # neutral heading for the scope notes, not the record's old one
        self.assertNotIn(OLD_HEADING, out)
        self.assertIn("## Scope", out)
        # the timing and leakage caveats and the out-of-scope list remain
        self.assertIn("`timing.critical_path_ps` is ABC's own", out)
        self.assertIn("Liberty `cell_leakage_power` sum", out)
        self.assertIn("No place-and-route, no DRC/LVS", out)


if __name__ == "__main__":
    unittest.main()
