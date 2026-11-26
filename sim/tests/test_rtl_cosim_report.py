#!/usr/bin/env python3
"""Issue #767: the RTL-cosim report must not claim an unproven equivalence.

    python3 sim/tests/test_rtl_cosim_report.py

Standard library only.  Drives ``rtl-cosim.main()`` end to end over a
stubbed ``rtl_trace`` -- no iverilog, no vvp, no PDK -- and pins the
report contract the issue states: the pass/fail section is where the
observed outcome appears, the printed report never asserts the fixed
"It **does** establish ..." equivalence bullet (a FAIL run used to print
it right after the mismatch table), the directed-program and
RTL-simulation-only caveats survive under a neutral heading, and the
record writer is reached only by a fully passing ``--emit-record`` run,
whose guarded claim lives in the minted record's ``claim`` field.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "bin"))
from loadmod import load_module  # noqa: E402

SLUG = SIM / "digital-rtl-equivalence"
harness = load_module("rtl_cosim", SLUG / "harness" / "rtl-cosim.py")

# The unconditional success bullet the issue removes: main printed it
# even when the table above it reported FAIL with mismatched cycles.
CLAIM_BULLET = "- It **does** establish"
CLAIM_EQUIV = "implements the committed behavioural model"
OLD_HEADING = "## What this record does and does not establish"


def flip_out_valid(row: str) -> str:
    """Return ``row`` with the ``out_valid`` field toggled, so the row is
    guaranteed to differ from the model's observation of the same cycle."""
    fields = row.split()
    fields[1] = "1" if fields[1] == "0" else "0"
    return " ".join(fields)


class StubbedTraces(unittest.TestCase):
    """main() over a stubbed rtl_trace, in a temp tree."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.cycles, self.phases = harness.build_program(harness.DEFAULT_SEED)

    def drive(self, argv, corrupt_row=None):
        """Run main(argv) with rtl_trace stubbed to the model trace
        (optionally with one row changed); return (rc, stdout, stderr, mints).

        ``--keep`` is always forced into the temp tree so no run artifact
        leaks outside it.  ``shutil.which`` is stubbed so the suite does not
        need a real iverilog (the stubbed rtl_trace never invokes one).
        """
        actual = harness.model_trace(self.cycles)
        if corrupt_row is not None:
            actual = list(actual)
            actual[corrupt_row] = flip_out_valid(actual[corrupt_row])
        mints = []
        patches = [
            mock.patch.object(harness, "rtl_trace",
                              return_value=(actual, "")),
            mock.patch.object(harness, "iverilog_version",
                              return_value="Icarus Verilog (fake)"),
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
                rc = harness.main([*argv, "--keep", str(self.tmp / "run")])
        return rc, out.getvalue(), err.getvalue(), mints

    def test_fail_report_reports_the_mismatch_not_a_claim(self):
        rc, out, err, mints = self.drive(["--emit-record"], corrupt_row=0)
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"\*\*FAIL\*\* -- 1 mismatched cycle")
        # the phase table counts the mismatch and the diff table shows row 0
        self.assertRegex(
            out, r"\| 0-\d+ \| post-reset idle \+ ID/parameter reads \| 1 \|")
        self.assertRegex(
            out, r"\| 0 \| post-reset idle \+ ID/parameter reads \|")
        self.assertNotIn(CLAIM_BULLET, out)
        self.assertNotIn(CLAIM_EQUIV, out)
        # a failing run mints nothing
        self.assertEqual(mints, [])
        self.assertIn("refusing to mint", err)

    def test_pass_report_keeps_the_agreement_wording(self):
        rc, out, _err, mints = self.drive([])
        self.assertEqual(rc, 0)
        n = len(self.cycles)
        self.assertIn(f"**PASS** -- {n} of {n} cycles identical", out)
        self.assertIn("cycle-for-cycle equivalent over this program", out)
        self.assertNotIn(CLAIM_BULLET, out)
        # no --emit-record: nothing is minted
        self.assertEqual(mints, [])

    def test_scope_notes_survive_the_removal(self):
        for corrupt_row in (None, 0):
            with self.subTest(corrupt_row=corrupt_row):
                _rc, out, _err, _ = self.drive([], corrupt_row=corrupt_row)
                # neutral heading for the caveats, not the record's old one
                self.assertNotIn(OLD_HEADING, out)
                self.assertIn("## Scope and caveats", out)
                # the directed-program and RTL-simulation-only caveats remain
                self.assertIn("It is **not** exhaustive: it is a directed program", out)
                self.assertIn("It is **RTL simulation only**", out)
                self.assertNotIn(CLAIM_BULLET, out)

    def test_passing_run_mints_with_the_guarded_claim(self):
        rc, out, _err, mints = self.drive(["--emit-record"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(mints), 1)
        kw = mints[0]
        # stdout is exactly the minted body -- one report, no extra claims
        self.assertEqual(out, kw["body_md"] + "\n")
        # the guarded claim lives in the record's claim field, not in the
        # report text every iteration prints
        self.assertIn("cycle-for-cycle", kw["claim"])
        self.assertNotIn(CLAIM_BULLET, out)


if __name__ == "__main__":
    unittest.main()
