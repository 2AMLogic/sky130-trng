#!/usr/bin/env python3
"""Unit tests for `sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py`.

Runs with the standard library only, no simulator and no PDK::

    python3 sim/tests/test_raw_bit_entropy.py

Following `design/test_netlist_erc.py`'s and `sim/tests/
test_digital_section.py`'s convention: a standalone unittest script, not
part of a pytest suite (this repository has no pytest configuration).
These are the fast, always-runnable checks against SYNTHETIC bitstreams
with a known entropy; the evidence record under
`sim/raw-bit-min-entropy/records/` is the slower, real ngspice-derived
campaign this module's arithmetic reduces.
"""

from __future__ import annotations

import importlib.util
import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = (
    REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis" / "raw-bit-entropy.py"
)

# The analysis script's filename has a hyphen, so it cannot be `import`ed by
# module path -- load it explicitly, same workaround this repository's other
# hyphenated-filename analysis scripts need if ever imported rather than run.
_spec = importlib.util.spec_from_file_location("raw_bit_entropy", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
raw_bit_entropy = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
_spec.loader.exec_module(raw_bit_entropy)


VDD = 1.8
HIGH = VDD  # a clean rail sample
LOW = 0.0


def measurements_for(bits: list[int], *, valid: list[int] | None = None) -> dict:
    """Build a `corner-run.py`-style measurements dict for a known sequence."""
    valid = valid if valid is not None else [1] * len(bits)
    m = {}
    for i, (b, v) in enumerate(zip(bits, valid)):
        m[f"bit{i}"] = HIGH if b else LOW
        m[f"valid{i}"] = HIGH if v else LOW
    return m


class TestExtractSequence(unittest.TestCase):
    def test_recovers_known_pattern(self):
        bits = [0, 1, 1, 0, 1]
        m = measurements_for(bits)
        got, n_total, n_excl = raw_bit_entropy.extract_sequence(m, VDD)
        self.assertEqual(got, bits)
        self.assertEqual(n_total, len(bits))
        self.assertEqual(n_excl, 0)

    def test_excludes_invalid_samples(self):
        bits = [1, 1, 0, 1]
        valid = [1, 0, 1, 1]
        m = measurements_for(bits, valid=valid)
        got, n_total, n_excl = raw_bit_entropy.extract_sequence(m, VDD)
        self.assertEqual(got, [1, 0, 1])  # index 1 dropped
        self.assertEqual(n_total, 4)
        self.assertEqual(n_excl, 1)

    def test_threshold_is_half_vdd(self):
        m = {
            "bit0": 0.4 * VDD, "valid0": HIGH,   # below threshold -> 0
            "bit1": 0.6 * VDD, "valid1": HIGH,   # above threshold -> 1
        }
        got, _, _ = raw_bit_entropy.extract_sequence(m, VDD)
        self.assertEqual(got, [0, 1])

    def test_handles_non_contiguous_and_unordered_keys(self):
        m = {"bit2": HIGH, "valid2": HIGH, "bit0": LOW, "valid0": HIGH}
        got, n_total, _ = raw_bit_entropy.extract_sequence(m, VDD)
        # index 1 is missing entirely -- only bit0/bit2 exist.
        self.assertEqual(got, [0, 1])
        self.assertEqual(n_total, 2)


class TestMcvEstimate(unittest.TestCase):
    def test_all_same_bit_is_zero_entropy(self):
        est = raw_bit_entropy.mcv_estimate([0] * 100)
        self.assertEqual(est["p_hat"], 1.0)
        self.assertEqual(est["p_u_99"], 1.0)
        self.assertEqual(est["h_hat_bits"], 0.0)

    def test_unbiased_large_sample_is_near_max_entropy(self):
        rng = random.Random(1234)
        bits = [rng.getrandbits(1) for _ in range(200_000)]
        est = raw_bit_entropy.mcv_estimate(bits)
        # p_hat should sit close to 0.5 for a large unbiased sample, and the
        # resulting H_hat should be close to (but, by construction of the
        # upper confidence bound, at or below) 1 bit/sample.
        self.assertAlmostEqual(est["p_hat"], 0.5, delta=0.01)
        self.assertGreater(est["h_hat_bits"], 0.9)
        self.assertLessEqual(est["h_hat_bits"], 1.0 + 1e-9)

    def test_known_biased_sequence_matches_hand_computed_formula(self):
        # 8 ones, 2 zeros -- deterministic, no RNG needed for a bit-for-bit
        # reproducible expected value.
        bits = [1] * 8 + [0] * 2
        est = raw_bit_entropy.mcv_estimate(bits)
        n = 10
        p_hat = 0.8
        se = (p_hat * (1 - p_hat) / n) ** 0.5
        p_u = min(1.0, p_hat + raw_bit_entropy.Z_99 *
                   (p_hat * (1 - p_hat) / (n - 1)) ** 0.5)
        import math
        h_expected = -math.log2(p_u)
        self.assertEqual(est["n"], n)
        self.assertEqual(est["ones"], 8)
        self.assertEqual(est["zeros"], 2)
        self.assertAlmostEqual(est["p_hat"], p_hat)
        self.assertAlmostEqual(est["se_naive"], se)
        self.assertAlmostEqual(est["p_u_99"], p_u)
        self.assertAlmostEqual(est["h_hat_bits"], h_expected)

    def test_more_bias_gives_lower_or_equal_entropy(self):
        rng = random.Random(42)
        n = 5000

        def biased(p_one: float) -> list[int]:
            return [1 if rng.random() < p_one else 0 for _ in range(n)]

        h_fair = raw_bit_entropy.mcv_estimate(biased(0.5))["h_hat_bits"]
        h_mild = raw_bit_entropy.mcv_estimate(biased(0.7))["h_hat_bits"]
        h_severe = raw_bit_entropy.mcv_estimate(biased(0.95))["h_hat_bits"]
        self.assertGreaterEqual(h_fair, h_mild)
        self.assertGreaterEqual(h_mild, h_severe)

    def test_p_u_never_below_p_hat(self):
        # The upper confidence bound must never undershoot the point
        # estimate it is bounding -- that would silently overstate entropy.
        for bits in ([1, 0, 1, 1, 0], [1] * 3 + [0] * 17, [0, 1] * 50):
            est = raw_bit_entropy.mcv_estimate(bits)
            self.assertGreaterEqual(est["p_u_99"] + 1e-12, est["p_hat"])

    def test_empty_sequence_raises(self):
        with self.assertRaises(ValueError):
            raw_bit_entropy.mcv_estimate([])


class TestCampaignRecordSelection(unittest.TestCase):
    def test_ignores_derived_records(self):
        # A corner-run.py record always carries a `testbench` key; this
        # script's own derived (--emit-record) output never does (it has
        # `analysis` instead) -- campaign_records() must not pick up its
        # own prior output as if it were a fresh simulation run.
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp)
            (records_dir / "20260101-000000-abc0000.json").write_text(json.dumps({
                "record_id": "20260101-000000-abc0000",
                "testbench": "sim/raw-bit-min-entropy/testbench/tb_raw_bit_stream.spice",
                "corners": [],
            }))
            (records_dir / "20260101-000100-abc0000.json").write_text(json.dumps({
                "record_id": "20260101-000100-abc0000",
                "analysis": "sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py",
                "per_corner": [],
            }))
            recs = raw_bit_entropy.campaign_records(records_dir)
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["record_id"], "20260101-000000-abc0000")


if __name__ == "__main__":
    unittest.main()
