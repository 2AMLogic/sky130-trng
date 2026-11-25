#!/usr/bin/env python3
"""Unit tests for `sim/digital-conditioned-output/analysis/conditioned-output.py`.

Standard library only, no simulator::

    python3 sim/tests/test_conditioned_output.py

Pins the word serialization order (MSB-first), block/partial-block handling,
the conditioned segment policy, the input/output accounting flags, and that
the committed record's first stream still reproduces from the committed inputs.
"""

from __future__ import annotations

import json
import math
import random
import sys
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PATH = (REPO_ROOT / "sim" / "digital-conditioned-output" / "analysis"
         / "conditioned-output.py")
sys.path.insert(0, os.path.join(REPO_ROOT, "sim", "bin"))
from loadmod import load_module  # noqa: E402
sys.path.insert(0, str(REPO_ROOT))
import replay_equal  # noqa: E402
C = load_module("conditioned_output", _PATH)

from digital.model.conditioner import Crc32Conditioner  # noqa: E402


def ideal(n, seed=1):
    r = random.Random(seed)
    return [r.getrandbits(1) for _ in range(n)]


class TestSerialization(unittest.TestCase):
    def test_msb_first_pinned(self):
        self.assertEqual(C.word_bits_msb_first(0x80000001),
                         [1] + [0] * 30 + [1])
        self.assertEqual(C.word_bits_msb_first(0x00000003),
                         [0] * 30 + [1, 1])
        self.assertEqual(len(C.word_bits_msb_first(0xFFFFFFFF)), 32)

    def test_roundtrip_value(self):
        w = 0xDEADBEEF
        v = 0
        for b in C.word_bits_msb_first(w):
            v = (v << 1) | b
        self.assertEqual(v, w)


class TestConditionStream(unittest.TestCase):
    def test_matches_model_words(self):
        raw = ideal(256 * 3, seed=7)
        c = Crc32Conditioner()
        words = [w for w in (c.push(b) for b in raw) if w is not None]
        self.assertEqual(len(words), 3)
        want = [b for w in words for b in C.word_bits_msb_first(w)]
        self.assertEqual(C.condition_stream(raw), want)

    def test_partial_block_dropped_and_blocks_independent(self):
        raw = ideal(256 * 2 + 100, seed=8)
        out = C.condition_stream(raw)
        self.assertEqual(len(out), 64)
        # block-boundary re-seed: block 2's word does not depend on block 1
        self.assertEqual(out[32:], C.condition_stream(raw[256:512]))

    def test_campaign_length(self):
        self.assertEqual(len(C.condition_stream(ideal(131072))), 16384)


class TestAccounting(unittest.TestCase):
    def test_flags(self):
        self.assertEqual(C.accounting(0.5)["flag"], "ok")  # 128 bits
        self.assertAlmostEqual(C.accounting(0.5)["ratio"], 4.0)
        self.assertEqual(C.accounting(0.2)["flag"], "BELOW-32+MARGIN")  # 51.2
        self.assertEqual(C.accounting(0.1)["flag"], "BELOW-32")  # 25.6
        self.assertEqual(C.accounting(None)["flag"], "INSUFFICIENT")

    def test_design_budget(self):
        self.assertEqual(C.DESIGN_BUDGET, 128.0)


class TestAnalysis(unittest.TestCase):
    def test_segment_policy_fits(self):
        self.assertEqual(C.SEGMENT_COUNT * C.SEGMENT_LEN, 16384)
        self.assertGreaterEqual(C.SEGMENT_COUNT, C.B.MIN_SEGMENTS)

    def test_ideal_input_runs_everything(self):
        a = C.analyse_conditioned(C.condition_stream(ideal(131072, seed=3)))
        self.assertEqual(a["n"], 16384)
        self.assertEqual(a["single_sequence"]["verdict"], "PASS")
        self.assertEqual(a["segmented"]["verdict"], "PASS")
        self.assertEqual(a["estimators"]["verdict"], "ESTIMATE")

    def test_short_input_insufficient_not_pass(self):
        a = C.analyse_conditioned(C.condition_stream(ideal(256 * 4)))  # 128 bits
        self.assertNotEqual(a["segmented"]["verdict"], "PASS")
        self.assertEqual(a["estimators"]["verdict"], "INSUFFICIENT")

    def test_constant_raw_is_flagged(self):
        # all-zero raw conditions to one repeated word: must not pass.
        a = C.analyse_conditioned(C.condition_stream([0] * 131072))
        self.assertEqual(a["single_sequence"]["verdict"], "FAIL")
        self.assertLess(a["estimators"]["h_min_bits"], 0.1)


class TestSharedReduction(unittest.TestCase):
    def test_no_local_fork_of_shared_helpers(self):
        self.assertFalse(hasattr(C, "_failed"))
        for name in ("analyse_stream", "format_binding", "render_detail_tables"):
            self.assertTrue(hasattr(C.B, name), name)

    def test_analyse_conditioned_matches_shared_reduction(self):
        bits = C.condition_stream(ideal(131072, seed=11))
        want = {"ones": sum(bits),
                **C.B.analyse_stream(bits, segment_len=C.SEGMENT_LEN)}
        self.assertEqual(C.analyse_conditioned(bits), want)


class TestReplayDiff(unittest.TestCase):
    def test_float_noise_tolerated(self):
        a = {"p": 0.12345678990242483, "xs": [1.0, 2.5]}
        b = {"p": 0.12345678990242344, "xs": [1.0, 2.5]}
        self.assertEqual(C.replay_diff(a, b), [])

    def test_real_float_change_caught(self):
        self.assertNotEqual(C.replay_diff({"p": 0.5}, {"p": 0.5001}), [])

    def test_exact_for_non_floats(self):
        self.assertNotEqual(C.replay_diff({"n": 16384}, {"n": 16385}), [])
        self.assertNotEqual(C.replay_diff({"v": "PASS"}, {"v": "FAIL"}), [])
        self.assertNotEqual(C.replay_diff({"h": None}, {"h": 0.5}), [])
        self.assertNotEqual(C.replay_diff({"n": 1}, {"n": 1.0}), [])
        self.assertNotEqual(C.replay_diff([1, 2], [1, 2, 3]), [])
        self.assertNotEqual(C.replay_diff({"a": 1}, {"b": 1}), [])

    def test_uses_the_shared_comparator(self):
        self.assertIs(C._replay_diff, replay_equal.replay_diff)
        self.assertFalse(hasattr(C, "REPLAY_REL_TOL"),
                         "conditioned-output.py re-declared a private replay "
                         "tolerance; the rule lives in sim/bin/replay_equal.py (DR-0020)")

    def test_cpython_sum_split_absorbed_and_real_changes_still_bite(self):
        # Operand mix on which the naive `+=` and compensated reductions
        # differ -- the two sides of the CPython 3.11/3.12 builtin sum() split.
        xs = [0.12345678901234568, -0.09876543210987654,
              0.0456789012345679, -0.012345678901234567] * 6
        s_naive = 0.0
        for x in xs:
            s_naive += x
        s_fsum = math.fsum(xs)
        self.assertNotEqual(s_naive, s_fsum)
        self.assertEqual(C.replay_diff({"p": s_fsum}, {"p": s_naive}), [])
        self.assertNotEqual(C.replay_diff({"p": s_fsum},
                                          {"p": s_fsum * (1 + 1e-6)}), [])
        self.assertEqual(C.replay_diff({"p": s_fsum},
                                       {"p": s_fsum * (1 + 1e-12)}), [])

    def test_zero_versus_tiny_is_a_difference_no_absolute_floor(self):
        self.assertNotEqual(C.replay_diff({"z": 0.0}, {"z": 5e-324}), [])
        self.assertNotEqual(C.replay_diff({"z": 0.0}, {"z": 1e-20}), [])
        self.assertNotEqual(C.replay_diff({"z": 1e-20}, {"z": 0.0}), [])
        self.assertEqual(C.replay_diff({"z": 0.0}, {"z": -0.0}), [])

    def test_nan_pair_accepted_via_shared_option(self):
        nan = float("nan")
        self.assertEqual(C.replay_diff({"p": nan}, {"p": nan}), [])
        self.assertNotEqual(C.replay_diff({"p": nan}, {"p": 0.0}), [])


class TestCommittedRecord(unittest.TestCase):
    def test_first_stream_reproduces(self):
        recs = sorted((REPO_ROOT / "sim" / "digital-conditioned-output"
                       / "records").glob("*.json"))
        if not recs:
            self.skipTest("no committed record")
        committed = json.loads(recs[-1].read_text())
        src = REPO_ROOT / committed["source_json"]
        _rec, streams, _sha = C.B.load_volume_source(src)
        row, raw = streams[0]
        want = committed["analysis_payload"]["per_stream"][0]
        self.assertEqual(want["source_file"], row["file"])
        got = json.loads(json.dumps(C.analyse_conditioned(
            C.condition_stream(raw))))
        # Float-tolerant replay: exact for ints/strings/verdicts/counts,
        # math.isclose for floats (record minted on another Python/libm).
        self.assertEqual(C.replay_diff(want["conditioned"], got), [])
        self.assertEqual(committed["analysis_payload"]["serialization"],
                         "MSB-first per 32-bit word, words in block order")


if __name__ == "__main__":
    unittest.main()
