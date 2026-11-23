#!/usr/bin/env python3
"""Replay the append-only sampler_core PEX evidence and exercise incomplete responses."""
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "bin"))
from loadmod import load_module

SLUG = SIM / "pex-sampler-core"
RUN = SLUG / "runs/20261121-001303-7330672"
harness = load_module("pex_measure", SLUG / "harness/pex-measure.py")


class KltVersionRead(unittest.TestCase):
    """issue #653: the manifest's ``klt`` value comes from the shared
    ``_klt_common.klt_version`` reader -- BARE, and fail-closed -- not the
    ``klt --version`` banner scrape #597 regrew, which recorded a
    ``"klt "-prefixed`` string and failed OPEN (a failing klt left ``""``
    in harness-manifest.json instead of aborting the run)."""

    def _fake_klt(self, body):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        exe = Path(td.name) / "klt"
        exe.write_text("#!/usr/bin/env python3\n"
                       "import json, sys\n"
                       "argv = sys.argv[1:]\n" + body)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        return str(exe)

    def test_records_the_bare_version(self):
        klt = self._fake_klt(
            'if argv[:1] != ["version"]:\n'
            '    sys.exit(2)\n'
            'print(json.dumps({"version": "0.8.0"}))\n')
        self.assertEqual(harness.read_klt_version(klt), "0.8.0")

    def test_a_failing_klt_version_aborts_the_run(self):
        klt = self._fake_klt('print("klt 0.9.3")\nsys.exit(1)\n')
        with self.assertRaisesRegex(harness.HarnessError,
                                    "no JSON response"):
            harness.read_klt_version(klt)


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


class RenameExtractedNetlist(unittest.TestCase):
    """issue #638: the extracted leg's rename is the SAME code as the
    library builder's (layout/bin/_pex_rewrite.py), so it must reproduce
    the committed dut.spice byte for byte and reject the two
    silent-corruption shapes the pre-#638 harness fork let through."""

    # The exact bytes klt pex measured the extracted leg on (pinned by the
    # run's input-hashes.json), and the alias-renamed netlist the committed
    # run wrote from them.
    RAW = RUN / "sampler_core.extracted.spice"
    DUT = RUN / "pex/measure/extracted/dut.spice"
    #: One complete single-line device card from RAW, the mutation anchor.
    ANCHOR = ("X$1 \\$17__t1 rst_n__t0 vss__t0 vss__t86 "
              "sky130_fd_pr__nfet_01v8 L=0.15 W=0.84")

    def test_reproduces_the_committed_dut_spice(self):
        self.assertEqual(
            harness.rename_extracted_netlist(self.RAW.read_text()),
            self.DUT.read_text(),
        )

    def _rejects(self, raw, fragment):
        with self.assertRaisesRegex(harness.HarnessError, fragment):
            harness.rename_extracted_netlist(raw)

    def test_unit_suffixed_geometry_is_rejected(self):
        """A stray `U` suffix mis-scales the device by 1e-6 under
        .option scale=1u and simulates cleanly -- it must be an error."""
        raw = self.RAW.read_text()
        self.assertIn(self.ANCHOR, raw)
        self._rejects(
            raw.replace(self.ANCHOR, self.ANCHOR.replace("W=0.84", "W=0.84U"), 1),
            "not a bare unitless number",
        )

    def test_raw_m_card_is_rejected(self):
        """A deck-native M card (an extraction run without --pdk) must be
        an error, not a silently accepted card. The card reuses the
        anchor's own node names so the rejection can only come from the
        device-card contract, not from a rename collision."""
        raw = self.RAW.read_text()
        self.assertIn(self.ANCHOR, raw)
        mcard = ("M0 \\$17__t1 rst_n__t0 vss__t0 vss__t86 "
                 "sky130_fd_pr__pfet_01v8 W=0.84 L=0.15")
        self._rejects(raw.replace(self.ANCHOR, self.ANCHOR + "\n" + mcard, 1),
                      "is not a subcircuit call")

    def test_net_aliases_match_the_layout_descriptor(self):
        """net-aliases.json must stay the verbatim copy of the layout
        descriptor's cells[0].net_aliases it documents itself as (its
        retirement waits for the #371/#372 PEX re-mint, so drift is
        guarded here instead)."""
        layout_aliases = json.loads(
            (SIM.parent / "layout" / "pex-sampler-core" / "pex.json").read_text()
        )["cells"][0]["net_aliases"]
        committed = json.loads((SLUG / "net-aliases.json").read_text())["aliases"]
        self.assertEqual(committed, layout_aliases)


if __name__ == "__main__":
    unittest.main()
