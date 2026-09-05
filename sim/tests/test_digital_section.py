#!/usr/bin/env python3
"""Unit tests for the digital section's behavioural model.

Runs with the standard library only, no simulator and no PDK::

    python3 sim/tests/test_digital_section.py

These are the fast, always-runnable checks. The evidence records under
``sim/digital-*/`` are the slower campaign runs that produce citable
numbers; this file is what keeps a refactor from silently breaking the
model those records describe. Following ``design/test_netlist_erc.py``'s
convention, it is a standalone script rather than part of a pytest suite --
this repository has no pytest configuration.
"""

from __future__ import annotations

import random
import sys
import unittest
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "digital"))

from model import params, regmap as rm  # noqa: E402
from model.conditioner import (Crc32Conditioner, bit_reverse32,  # noqa: E402
                               crc32_polynomial_remainder, lfsr_over_bits)
from model.digital_top import TrngDigital  # noqa: E402
from model.health import (AdaptiveProportionTest, HealthMonitor,  # noqa: E402
                          RepetitionCountTest)


def healthy(n: int, seed: int = 1234) -> list[int]:
    rng = random.Random(seed)
    return [rng.getrandbits(1) for _ in range(n)]


class TestCutoffFormulas(unittest.TestCase):
    """SP 800-90B §4.4.1/§4.4.2, evaluated rather than asserted."""

    def test_adopted_cutoffs_match_the_formulas(self):
        # The committed constants must BE the formula evaluation at the
        # committed H, not a number someone typed in.
        self.assertEqual(params.C_RCT, params.c_rct(params.H_DESIGN))
        self.assertEqual(params.C_APT, params.c_apt(params.H_DESIGN))

    def test_rct_formula(self):
        self.assertEqual(params.c_rct(0.5), 81)     # 1 + ceil(40/0.5)
        self.assertEqual(params.c_rct(1.0), 41)
        self.assertEqual(params.c_rct(0.5, alpha_log2=30), 61)

    def test_apt_tail_brackets_the_cutoff(self):
        # The cutoff is the SMALLEST C with Pr(X >= C) <= alpha, so C-1 must
        # exceed alpha. This is the property, not the value.
        from decimal import Decimal
        w, alpha_log2 = params.W_APT, params.ALPHA_LOG2
        alpha = Decimal(2) ** -alpha_log2
        for h in (0.3, 0.5, 1.0):
            c = params.c_apt(h, w, alpha_log2)
            p = Decimal(2) ** Decimal(str(-h))
            self.assertLessEqual(params.binomial_upper_tail(w, p, c), alpha)
            self.assertGreater(params.binomial_upper_tail(w, p, c - 1), alpha)

    def test_cutoffs_are_monotone_in_h(self):
        grid = [0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]
        rct = [params.c_rct(h) for h in grid]
        apt = [params.c_apt(h) for h in grid]
        self.assertEqual(rct, sorted(rct, reverse=True))
        self.assertEqual(apt, sorted(apt, reverse=True))

    def test_apt_degeneracy_floor_is_exact(self):
        floor = params.apt_degeneracy_floor()
        self.assertAlmostEqual(floor, 40 / 1024, places=12)
        self.assertIsNone(params.c_apt(floor - 0.001))
        self.assertIsNotNone(params.c_apt(floor + 0.001))

    def test_design_target_is_clear_of_the_degeneracy_floor(self):
        # DR-0004 §2.4: the risk is that a measured H lands near the floor.
        self.assertGreater(params.H_DESIGN, 10 * params.apt_degeneracy_floor())
        self.assertLess(params.C_APT, params.W_APT - 100)


class TestConditioner(unittest.TestCase):

    def test_matches_polynomial_long_division(self):
        rng = random.Random(99)
        for _ in range(8):
            bits = [rng.getrandbits(1) for _ in range(params.COND_BLOCK_BITS)]
            cond = Crc32Conditioner()
            words = [w for w in (cond.push(b) for b in bits) if w is not None]
            self.assertEqual(len(words), 1)
            self.assertEqual(words[0], crc32_polynomial_remainder(bits))

    def test_polynomial_is_really_crc32(self):
        rng = random.Random(100)
        for n in (0, 1, 7, 32, 100):
            data = bytes(rng.getrandbits(8) for _ in range(n))
            bits = [(byte >> i) & 1 for byte in data for i in range(8)]
            got = bit_reverse32(lfsr_over_bits(bits)) ^ 0xFFFFFFFF
            self.assertEqual(got, zlib.crc32(data) & 0xFFFFFFFF)

    def test_emits_one_word_per_block_and_nothing_between(self):
        cond = Crc32Conditioner()
        out = [cond.push(1) for _ in range(3 * params.COND_BLOCK_BITS)]
        emitted = [i for i, w in enumerate(out) if w is not None]
        self.assertEqual(emitted, [params.COND_BLOCK_BITS - 1,
                                   2 * params.COND_BLOCK_BITS - 1,
                                   3 * params.COND_BLOCK_BITS - 1])

    def test_reset_discards_a_partial_block(self):
        bits = healthy(params.COND_BLOCK_BITS, seed=5)
        cond = Crc32Conditioner()
        for b in bits[:57]:
            cond.push(b)
        cond.reset()
        words = [w for w in (cond.push(b) for b in bits) if w is not None]
        ref = Crc32Conditioner()
        expect = [w for w in (ref.push(b) for b in bits) if w is not None]
        self.assertEqual(words, expect)


class TestHealthTests(unittest.TestCase):

    def test_rct_trips_exactly_at_the_cutoff(self):
        rct = RepetitionCountTest(params.C_RCT)
        for i in range(params.C_RCT - 1):
            self.assertFalse(rct.update(1), f"tripped early at {i + 1}")
        self.assertTrue(rct.update(1))

    def test_rct_run_restarts_on_a_change(self):
        rct = RepetitionCountTest(params.C_RCT)
        for _ in range(params.C_RCT - 1):
            rct.update(1)
        self.assertFalse(rct.update(0))
        for _ in range(params.C_RCT - 2):
            self.assertFalse(rct.update(0))
        self.assertTrue(rct.update(0))

    def test_rct_never_trips_on_alternating(self):
        rct = RepetitionCountTest(params.C_RCT)
        for i in range(10_000):
            self.assertFalse(rct.update(i & 1))

    def test_apt_decides_only_on_a_window_boundary(self):
        apt = AdaptiveProportionTest(params.W_APT, params.C_APT)
        results = [apt.update(1) for _ in range(params.W_APT)]
        self.assertTrue(results[-1])
        self.assertFalse(any(results[:-1]))

    def test_apt_passes_a_balanced_window(self):
        apt = AdaptiveProportionTest(params.W_APT, params.C_APT)
        for i in range(4 * params.W_APT):
            self.assertFalse(apt.update(i & 1))

    def test_apt_cutoff_is_the_boundary(self):
        # exactly C_APT-1 matches passes; exactly C_APT fails.
        for matches, expect_fail in ((params.C_APT - 1, False),
                                     (params.C_APT, True)):
            apt = AdaptiveProportionTest(params.W_APT, params.C_APT)
            seq = [1] * matches + [0] * (params.W_APT - matches)
            fails = [apt.update(b) for b in seq]
            self.assertEqual(fails[-1], expect_fail, f"matches={matches}")

    def test_startup_completes_at_the_specified_length(self):
        mon = HealthMonitor()
        bits = healthy(params.STARTUP_SAMPLES)
        for bit in bits[:-1]:
            mon.update(bit)
            self.assertFalse(mon.startup_done)
            self.assertTrue(mon.gated)
        mon.update(bits[-1])
        self.assertTrue(mon.startup_done)
        self.assertFalse(mon.gated)

    def test_alarm_is_sticky_and_write_one_to_clear(self):
        mon = HealthMonitor()
        for bit in healthy(params.STARTUP_SAMPLES):
            mon.update(bit)
        self.assertFalse(mon.gated)
        for _ in range(params.C_RCT):
            mon.update(1)
        self.assertTrue(mon.alarm_rct)
        self.assertTrue(mon.gated)
        # a healthy stream alone does not clear it
        for bit in healthy(2 * params.STARTUP_SAMPLES, seed=7):
            mon.update(bit)
        self.assertTrue(mon.alarm_rct)
        self.assertTrue(mon.gated)
        mon.clear_alarm(rm.AL_MASK)
        self.assertFalse(mon.alarm)
        self.assertFalse(mon.gated)


class TestRegisterInterface(unittest.TestCase):

    def enabled_dut(self, conditioned: bool = False) -> TrngDigital:
        dut = TrngDigital()
        dut.write(rm.CTRL, rm.CTRL_EN | (rm.CTRL_OUT_MODE if conditioned else 0))
        return dut

    def feed(self, dut: TrngDigital, bits) -> None:
        for bit in bits:
            dut.cycle(raw_bit=bit, raw_valid=1)

    def test_identification_and_parameter_registers(self):
        dut = TrngDigital()
        self.assertEqual(dut.read(rm.ID), rm.ID_VALUE)
        self.assertEqual(dut.read(rm.HT_RCT_CUTOFF), params.C_RCT)
        self.assertEqual(dut.read(rm.HT_APT_CUTOFF), params.C_APT)
        self.assertEqual(dut.read(rm.HT_APT_WINDOW), params.W_APT)
        self.assertEqual(dut.read(rm.HT_STARTUP), params.STARTUP_SAMPLES)
        self.assertEqual(dut.read(rm.HT_COND_BLOCK), params.COND_BLOCK_BITS)

    def test_disabled_block_consumes_nothing(self):
        dut = TrngDigital()
        self.feed(dut, healthy(4096))
        self.assertEqual(dut.read(rm.STATUS) & rm.ST_STARTUP_DONE, 0)
        self.assertEqual(dut.raw_fifo.level, 0)

    def test_raw_word_packing_is_lsb_first(self):
        dut = self.enabled_dut()
        pattern = [1, 0, 1, 1] + [0] * 28          # 0b1101 -> 0x0000000D
        self.feed(dut, pattern)
        self.assertEqual(dut.read(rm.RAW_DATA), 0x0000000D)

    def test_conditioned_word_is_the_crc_of_the_bits_that_produced_it(self):
        dut = self.enabled_dut(conditioned=True)
        self.feed(dut, healthy(params.STARTUP_SAMPLES))     # clear the gate
        block = healthy(params.COND_BLOCK_BITS, seed=42)
        self.feed(dut, block)
        self.assertEqual(dut.read(rm.DATA), crc32_polynomial_remainder(block))

    def test_conditioned_path_is_gated_until_startup_completes(self):
        dut = self.enabled_dut(conditioned=True)
        self.feed(dut, healthy(params.STARTUP_SAMPLES - 1))
        self.assertTrue(dut.read(rm.STATUS) & rm.ST_GATED)
        self.assertEqual(dut.read(rm.DATA), 0)

    def test_raw_path_is_never_gated(self):
        dut = self.enabled_dut()
        self.feed(dut, [1] * (params.C_RCT + 3 * params.WORD_BITS))
        status = dut.read(rm.STATUS)
        self.assertTrue(status & rm.ST_GATED)
        self.assertTrue(status & rm.ST_ALARM)
        self.assertTrue(status & rm.ST_RAW_FIFO_VALID)
        self.assertNotEqual(dut.read(rm.RAW_DATA), 0)   # stuck-at-1 -> 0xFFFFFFFF
        self.assertEqual(dut.read(rm.DATA), 0)

    def test_alarm_register_is_write_one_to_clear(self):
        dut = self.enabled_dut()
        self.feed(dut, [1] * params.C_RCT)
        # A trip inside the start-up window raises BOTH bits: the RCT bit
        # says which test failed, the START-UP bit says the block never
        # reached a state where conditioned output was permissible.
        self.assertEqual(dut.read(rm.ALARM), rm.AL_RCT | rm.AL_STARTUP)
        dut.write(rm.ALARM, rm.AL_APT)          # clearing a different bit
        self.assertEqual(dut.read(rm.ALARM), rm.AL_RCT | rm.AL_STARTUP)
        dut.write(rm.ALARM, rm.AL_RCT)
        self.assertEqual(dut.read(rm.ALARM), rm.AL_STARTUP)
        dut.write(rm.ALARM, rm.AL_MASK)
        self.assertEqual(dut.read(rm.ALARM), 0)

    def test_mid_run_trip_raises_only_the_failing_test_bit(self):
        dut = self.enabled_dut()
        self.feed(dut, healthy(params.STARTUP_SAMPLES))   # start-up passes
        self.feed(dut, [1] * params.C_RCT)                # then trip
        self.assertEqual(dut.read(rm.ALARM), rm.AL_RCT)

    def test_mode_switch_flushes_both_paths(self):
        dut = self.enabled_dut()
        self.feed(dut, healthy(params.STARTUP_SAMPLES + 2 * params.COND_BLOCK_BITS))
        self.assertTrue(dut.raw_fifo.level > 0 and dut.cond_fifo.level > 0)
        dut.write(rm.CTRL, rm.CTRL_EN | rm.CTRL_OUT_MODE)
        self.assertEqual(dut.raw_fifo.level, 0)
        self.assertEqual(dut.cond_fifo.level, 0)
        self.assertEqual(dut.cond.count, 0)
        self.assertEqual(dut.cond.state, params.CRC32_INIT)

    def test_gate_flushes_the_conditioned_path_but_not_the_raw_one(self):
        dut = self.enabled_dut()
        self.feed(dut, healthy(params.STARTUP_SAMPLES + params.COND_BLOCK_BITS))
        self.assertTrue(dut.cond_fifo.level > 0)
        raw_level = dut.raw_fifo.level
        self.feed(dut, [1] * params.C_RCT)      # trip
        self.assertEqual(dut.cond_fifo.level, 0)
        self.assertGreaterEqual(dut.raw_fifo.level, raw_level)

    def test_streaming_port_follows_out_mode(self):
        dut = self.enabled_dut()
        self.feed(dut, healthy(params.STARTUP_SAMPLES + params.COND_BLOCK_BITS))
        obs = dut.observe()
        self.assertEqual(obs["out_valid"], 1)
        self.assertEqual(obs["out_data"], dut.raw_fifo.head)
        # a stream pop removes exactly one word
        level = dut.raw_fifo.level
        dut.cycle(out_ready=1)
        self.assertEqual(dut.raw_fifo.level, level - 1)

    def test_soft_reset_clears_the_datapath_but_not_the_mode(self):
        dut = self.enabled_dut(conditioned=True)
        self.feed(dut, healthy(params.STARTUP_SAMPLES + params.COND_BLOCK_BITS))
        dut.write(rm.CTRL, rm.CTRL_EN | rm.CTRL_OUT_MODE | rm.CTRL_SOFT_RST)
        self.assertEqual(dut.ctrl, rm.CTRL_EN | rm.CTRL_OUT_MODE)
        self.assertFalse(dut.health.startup_done)
        self.assertEqual(dut.cond_fifo.level, 0)
        self.assertEqual(dut.raw_fifo.level, 0)

    def test_fifo_overflow_is_reported_not_hidden(self):
        dut = self.enabled_dut()
        self.feed(dut, healthy(params.WORD_BITS * (params.FIFO_DEPTH + 2)))
        self.assertTrue(dut.read(rm.STATUS) & rm.ST_RAW_OVF)
        self.assertEqual(dut.raw_fifo.level, params.FIFO_DEPTH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
