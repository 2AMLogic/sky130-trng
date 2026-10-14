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
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "sim" / "digital-floorplan-compaction"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HarnessGuard(unittest.TestCase):
    def test_emit_record_refused_for_study_request(self):
        h = _load("pnr_and_verify", ROOT / "sim" / "digital-pnr" / "harness" / "pnr-and-verify.py")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = h.main(["--request", str(STUDY / "requests" / "util55.json"), "--emit-record"])
        self.assertEqual(rc, 2)
        self.assertIn("refused", err.getvalue())
        # default target unchanged
        self.assertEqual(h.REQUEST, ROOT / "digital" / "flow" / "place-and-route" / "pnr-trng-digital-50khz.json")


class AreaModel(unittest.TestCase):
    def setUp(self):
        self.m = _load("compaction", STUDY / "analysis" / "compaction.py")
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


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
