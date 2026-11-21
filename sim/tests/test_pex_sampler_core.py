#!/usr/bin/env python3
"""Replay the append-only sampler_core PEX evidence and exercise incomplete responses."""
import json
import sys
import unittest
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "bin"))
from loadmod import load_module

SLUG = SIM / "pex-sampler-core"
RUN = SLUG / "runs/20261121-001303-7330672"
harness = load_module("pex_measure", SLUG / "harness/pex-measure.py")


class SamplerCorePEX(unittest.TestCase):
    def setUp(self):
        point = RUN / "pex/measure/schematic"
        self.report = json.loads((point / "resp-27c-1.8v.json").read_text())
        self.request = json.loads((point / "req-27c-1.8v.json").read_text())
        self.corners = self.report["corners"]

    def test_recorded_legs_match_every_delta(self):
        delta = json.loads((RUN / "pex-report.json").read_text())["delta"]
        for side in ("schematic", "extracted"):
            expected = {(d["corner_id"], d["spec_row"]): (d[f"{side}_value"], d[f"{side}_status"])
                        for d in delta}
            actual = {}
            point = RUN / "pex/measure" / side
            for temp, vdd in harness.DEFAULT_POINTS:
                stem = f"{temp:g}c-{vdd:g}v.json"
                request = json.loads((point / f"req-{stem}").read_text())
                report = json.loads((point / f"resp-{stem}").read_text())
                for corner in harness.response_corners(report, request, vdd):
                    for m in corner["measurements"]:
                        key = (corner["corner_id"], m["name"])
                        self.assertNotIn(key, actual)
                        actual[key] = (m["value"], m["status"])
            self.assertEqual(len(actual), 132)
            self.assertEqual(actual, expected)

    def assert_rejected(self, reason):
        with self.assertRaisesRegex(harness.HarnessError, reason):
            harness.response_corners(self.report, self.request, 1.8)

    def test_missing_corner(self):
        self.corners.pop()
        self.assert_rejected("missing process corners.*ff")

    def test_duplicate_corner(self):
        self.corners[-1] = self.corners[0]
        self.assert_rejected("duplicate corner")

    def test_unrequested_process(self):
        self.corners[0].update(process="sf", corner_id="sf/novdd/27C")
        self.assert_rejected("unexpected corner")

    def test_unrequested_temperature(self):
        self.corners[0].update(temperature_c=125, corner_id="tt/novdd/125C")
        self.assert_rejected("unexpected corner")

    def test_missing_ring_crossing(self):
        c = self.corners[0]
        c["measurements"] = [m for m in c["measurements"] if m["name"] != "t4b"]
        self.assert_rejected("missing measurements.*t4b")

    def test_duplicate_raw_measurement(self):
        measurements = self.corners[0]["measurements"]
        measurements.append(measurements[0])
        self.assert_rejected("duplicate measurement")

    def test_strict_power_bound(self):
        values = {m["name"]: m["value"] for m in self.corners[0]["measurements"]}
        for i in range(1, 5):
            values[f"i{i}a"] = 0.0
        for power, status in [(499.0, "pass"), (500.0, "fail"), (501.0, "fail")]:
            with self.subTest(power=power):
                values["iba"] = -power / 2e6
                rows = harness.derive_rows(values, 2.0)
                [active] = [m for m in rows if m["name"] == "active_power_uw"]
                self.assertAlmostEqual(active["value"], power)
                self.assertEqual(active["status"], status)


if __name__ == "__main__":
    unittest.main()
