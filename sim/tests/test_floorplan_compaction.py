#!/usr/bin/env python3
"""Contract tests for the issue #226 floorplan-compaction study (no klt,
no OpenROAD needed):

- the harness refuses `--emit-record` with a non-default `--request`, so a
  study run can never replace `layout/trng_digital/`;
- the re-stacked area model reproduces the committed whole-block bbox
  exactly at the baseline digital size, and shrinks monotonically;
- the study requests differ from the committed request only in
  `floorplan.utilization_pct` (netlist path rebased to the same file).
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from loadmod import load_module  # noqa: E402
STUDY = ROOT / "sim" / "digital-floorplan-compaction"


class HarnessGuard(unittest.TestCase):
    def test_emit_record_refused_for_study_request(self):
        h = load_module("pnr_and_verify", ROOT / "sim" / "digital-pnr" / "harness" / "pnr-and-verify.py")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = h.main(["--request", str(STUDY / "requests" / "util55.json"), "--emit-record"])
        self.assertEqual(rc, 2)
        self.assertIn("refused", err.getvalue())
        # default target unchanged
        self.assertEqual(h.REQUEST, ROOT / "digital" / "flow" / "place-and-route" / "pnr-trng-digital-50khz.json")


class AreaModel(unittest.TestCase):
    def setUp(self):
        self.m = load_module("compaction", STUDY / "analysis" / "compaction.py")
        self.whole = json.loads((ROOT / "layout" / "trng_whole" / "report.json").read_text())

    def test_reproduces_committed_bbox(self):
        a = self.m.area_model(245.05, 245.05, self.whole)
        self.assertAlmostEqual(a["estimate_restacked_same_topology_mm2"], self.whole["area"]["area_mm2"], places=5)
        self.assertAlmostEqual(a["estimate_additive_overhead_mm2"], self.whole["area"]["area_mm2"], places=5)

    def test_monotone(self):
        sizes = [245.05, 210.0, 190.0, 150.0]
        b = [self.m.area_model(s, s, self.whole)["estimate_restacked_same_topology_mm2"] for s in sizes]
        self.assertEqual(b, sorted(b, reverse=True))
        for s in sizes:
            a = self.m.area_model(s, s, self.whole)
            self.assertLessEqual(a["lower_bound_macros_only_mm2"], a["estimate_restacked_same_topology_mm2"])


class Requests(unittest.TestCase):
    def test_only_utilization_differs(self):
        committed = json.loads((ROOT / "digital" / "flow" / "place-and-route" / "pnr-trng-digital-50khz.json").read_text())
        net_c = (ROOT / "digital" / "flow" / "place-and-route" / committed["netlist"]).resolve()
        for u in (40, 55, 65):
            p = STUDY / "requests" / f"util{u}.json"
            r = json.loads(p.read_text())
            self.assertEqual((p.parent / r["netlist"]).resolve(), net_c)
            self.assertEqual(r["floorplan"]["utilization_pct"], u)
            a, b = dict(committed), dict(r)
            for d in (a, b):
                d.pop("netlist")
                d["floorplan"] = {k: v for k, v in d["floorplan"].items() if k != "utilization_pct"}
            self.assertEqual(a, b)


class ExitFromCodes(unittest.TestCase):
    """Regression (issue #501 review): exit-codes.txt is append-only, so a
    retried run name appears twice; the LAST matching line is the final rc."""

    def setUp(self):
        self.m = load_module("compaction", STUDY / "analysis" / "compaction.py")

    def test_last_match_wins_on_retry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "util40"
            run.mkdir()
            (Path(t) / "exit-codes.txt").write_text(
                "util40 exit 1 start 2026-01-01T00:00:00Z end 2026-01-01T00:10:00Z\n"
                "util40 exit 0 start 2026-01-01T01:00:00Z end 2026-01-01T01:10:00Z\n"
            )
            self.assertEqual(self.m._exit_from_codes(run), 0)

    def test_single_match_and_missing_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "util55"
            run.mkdir()
            (Path(t) / "exit-codes.txt").write_text(
                "util40 exit 1 start 2026-01-01T00:00:00Z end 2026-01-01T00:10:00Z\n"
                "util55 exit 3 start 2026-01-01T01:00:00Z end 2026-01-01T01:10:00Z\n"
            )
            self.assertEqual(self.m._exit_from_codes(run), 3)
            self.assertIsNone(self.m._exit_from_codes(Path(t) / "util65"))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
