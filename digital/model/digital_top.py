#!/usr/bin/env python3
"""The assembled digital section, as a cycle-accurate behavioural model.

This is the **normative** description of the block: ``digital/rtl/*.v`` is an
implementation of it, and ``sim/digital-rtl-equivalence/`` is the record that
the two agree cycle for cycle. Everything here sits downstream of the raw tap,
so per ``spec/porting-plan.md`` §1.1 (gf180-trng DR-0009) it is verified
behaviourally and never in SPICE.

Cycle contract
--------------
One :meth:`TrngDigital.cycle` call is one rising edge of the 50 kHz sample
clock (``design/README.md``'s ``clk`` pin, DR-0003's operating point). Within
a cycle, in this order -- the RTL implements the same order, which is what
makes the two comparable:

1. **Observe.** ``bus_rdata`` (registered from the previous cycle's read),
   ``out_valid`` / ``out_data`` and the status pins are read off the
   *start-of-cycle* state.
2. **Sample.** If ``CTRL.EN`` and ``raw_valid``: the raw bit goes to the
   health tests, the raw packer, and -- only while the conditioned path is
   ungated -- the conditioner.
3. **Gate.** If this sample raised an alarm, the conditioner and the
   conditioned FIFO are flushed.
4. **Bus write.** ``CTRL`` (a mode change flushes both paths), ``ALARM``
   write-1-to-clear.
5. **Bus read.** ``RAW_DATA`` / ``DATA`` pop; the value lands in
   ``bus_rdata`` for the next cycle.
6. **Stream pop.** ``out_ready & out_valid`` pops the mode-selected FIFO,
   unless a register read already popped that FIFO this cycle.
"""

from __future__ import annotations

from . import regmap as rm
from .conditioner import Crc32Conditioner
from .health import HealthMonitor
from .params import (C_APT, C_RCT, COND_BLOCK_BITS, FIFO_DEPTH, STARTUP_SAMPLES,
                     W_APT, WORD_BITS)


class Fifo:
    """A tiny word FIFO. A full FIFO drops the *incoming* word and says so."""

    def __init__(self, depth: int = FIFO_DEPTH) -> None:
        self.depth = depth
        self.items: list[int] = []

    def clear(self) -> None:
        self.items.clear()

    def push(self, word: int) -> bool:
        """Returns False if the word was dropped because the FIFO was full."""
        if len(self.items) >= self.depth:
            return False
        self.items.append(word & 0xFFFFFFFF)
        return True

    def pop(self) -> int:
        return self.items.pop(0) if self.items else 0

    @property
    def valid(self) -> bool:
        return bool(self.items)

    @property
    def head(self) -> int:
        return self.items[0] if self.items else 0

    @property
    def level(self) -> int:
        return len(self.items)


class TrngDigital:
    """Health tests + conditioner + register/streaming interface."""

    def __init__(self, c_rct: int = C_RCT, c_apt: int = C_APT,
                 window: int = W_APT, startup: int = STARTUP_SAMPLES,
                 fifo_depth: int = FIFO_DEPTH) -> None:
        self.c_rct = c_rct
        self.c_apt = c_apt
        self.window = window
        self.startup = startup
        self.health = HealthMonitor(c_rct, c_apt, window, startup)
        self.cond = Crc32Conditioner()
        self.raw_fifo = Fifo(fifo_depth)
        self.cond_fifo = Fifo(fifo_depth)
        self.reset()

    # -- reset ------------------------------------------------------------

    def reset(self) -> None:
        """Hard reset (``rst_n`` asserted): CTRL included."""
        self.ctrl = 0
        self._soft_reset()

    def _soft_reset(self) -> None:
        """Datapath + health-test reset; CTRL.EN / CTRL.OUT_MODE survive."""
        self.health.reset()
        self.cond.reset()
        self.raw_fifo.clear()
        self.cond_fifo.clear()
        self.raw_sr = 0
        self.raw_count = 0
        self.bus_rdata = 0
        self.raw_ovf = False
        self.cond_ovf = False
        self.raw_tap_valid = False

    def _flush_paths(self) -> None:
        """Mode-switch / gate flush: no pre-event bit reaches a post-event word."""
        self.cond.reset()
        self.cond_fifo.clear()
        self.raw_fifo.clear()
        self.raw_sr = 0
        self.raw_count = 0

    # -- combinational view ----------------------------------------------

    @property
    def out_mode_conditioned(self) -> bool:
        return bool(self.ctrl & rm.CTRL_OUT_MODE)

    def _sel_fifo(self) -> Fifo:
        return self.cond_fifo if self.out_mode_conditioned else self.raw_fifo

    def status(self) -> int:
        st = 0
        if self.health.startup_done:
            st |= rm.ST_STARTUP_DONE
        if self.health.gated:
            st |= rm.ST_GATED
        if self.raw_tap_valid:
            st |= rm.ST_RAW_TAP_VALID
        if self.raw_fifo.valid:
            st |= rm.ST_RAW_FIFO_VALID
        if self.cond_fifo.valid:
            st |= rm.ST_COND_FIFO_VALID
        if self.health.alarm:
            st |= rm.ST_ALARM
        st |= (self.raw_fifo.level & 0xF) << rm.ST_RAW_LEVEL_SHIFT
        st |= (self.cond_fifo.level & 0xF) << rm.ST_COND_LEVEL_SHIFT
        if self.raw_ovf:
            st |= rm.ST_RAW_OVF
        if self.cond_ovf:
            st |= rm.ST_COND_OVF
        return st

    def alarm_word(self) -> int:
        word = 0
        if self.health.alarm_rct:
            word |= rm.AL_RCT
        if self.health.alarm_apt:
            word |= rm.AL_APT
        if self.health.alarm_startup:
            word |= rm.AL_STARTUP
        return word

    def observe(self) -> dict:
        """Outputs visible *during* this cycle (start-of-cycle registers)."""
        sel = self._sel_fifo()
        return {
            "bus_rdata": self.bus_rdata,
            "out_valid": int(sel.valid),
            "out_data": sel.head,
            "alarm": int(self.health.alarm),
            "gated": int(self.health.gated),
            "startup_done": int(self.health.startup_done),
        }

    # -- register read side ------------------------------------------------

    def _read(self, addr: int) -> tuple[int, str | None]:
        """Returns ``(value, popped_path)`` -- reads of the data registers pop."""
        addr &= 0xF
        if addr == rm.CTRL:
            return self.ctrl, None
        if addr == rm.STATUS:
            return self.status(), None
        if addr == rm.RAW_DATA:
            # Raw access is ALWAYS available and never gated (SP 800-90B
            # requires it, and DR-0004 §4.2 makes it a hard invariant).
            if self.raw_fifo.valid:
                return self.raw_fifo.head, "raw"
            return 0, None
        if addr == rm.DATA:
            if self.health.gated:
                return 0, None
            if self.cond_fifo.valid:
                return self.cond_fifo.head, "cond"
            return 0, None
        if addr == rm.ALARM:
            return self.alarm_word(), None
        if addr == rm.HT_RCT_CUTOFF:
            return self.c_rct, None
        if addr == rm.HT_APT_CUTOFF:
            return self.c_apt, None
        if addr == rm.HT_APT_WINDOW:
            return self.window, None
        if addr == rm.HT_STARTUP:
            return self.startup, None
        if addr == rm.HT_COND_BLOCK:
            return COND_BLOCK_BITS, None
        if addr == rm.ID:
            return rm.ID_VALUE, None
        return 0, None

    # -- the edge ----------------------------------------------------------

    def cycle(self, raw_bit: int = 0, raw_valid: int = 0, addr: int = 0,
              we: int = 0, wdata: int = 0, re: int = 0,
              out_ready: int = 0) -> dict:
        """Apply one clock edge; returns the outputs seen during the cycle."""
        obs = self.observe()

        # 2/3. sample + gate
        self.raw_tap_valid = bool(raw_valid)
        if (self.ctrl & rm.CTRL_EN) and raw_valid:
            bit = raw_bit & 1
            gated_before = self.health.gated
            raised = self.health.update(bit)

            # raw packer: LSB-first packing, 32 bits per word
            self.raw_sr = (self.raw_sr | (bit << self.raw_count)) & 0xFFFFFFFF
            self.raw_count += 1
            if self.raw_count == WORD_BITS:
                if not self.raw_fifo.push(self.raw_sr):
                    self.raw_ovf = True
                self.raw_sr = 0
                self.raw_count = 0

            if not gated_before:
                word = self.cond.push(bit)
                if word is not None:
                    if not self.cond_fifo.push(word):
                        self.cond_ovf = True

            if raised:
                # gate: flush the conditioned path only; the raw FIFO keeps
                # its contents so software can read the samples that failed.
                self.cond.reset()
                self.cond_fifo.clear()

        # 4. bus write
        if we:
            a = addr & 0xF
            if a == rm.CTRL:
                new = wdata & rm.CTRL_MASK
                if (new ^ self.ctrl) & rm.CTRL_OUT_MODE:
                    self._flush_paths()
                if new & rm.CTRL_SOFT_RST:
                    keep = new & (rm.CTRL_EN | rm.CTRL_OUT_MODE)
                    self._soft_reset()
                    self.ctrl = keep
                else:
                    self.ctrl = new
            elif a == rm.ALARM:
                self.health.clear_alarm(wdata & rm.AL_MASK)

        # 5. bus read
        popped = None
        if re:
            value, popped = self._read(addr)
            self.bus_rdata = value & 0xFFFFFFFF
            if popped == "raw":
                self.raw_fifo.pop()
            elif popped == "cond":
                self.cond_fifo.pop()

        # 6. stream pop
        sel = self._sel_fifo()
        sel_name = "cond" if self.out_mode_conditioned else "raw"
        if out_ready and sel.valid and popped != sel_name:
            sel.pop()

        return obs

    # -- convenience for testbenches --------------------------------------

    def run_bits(self, bits, out_ready: int = 0) -> list[dict]:
        """Feed a bit sequence with ``raw_valid`` high; returns the trace."""
        return [self.cycle(raw_bit=b, raw_valid=1, out_ready=out_ready)
                for b in bits]

    def write(self, addr: int, value: int) -> None:
        self.cycle(addr=addr, we=1, wdata=value)

    def read(self, addr: int) -> int:
        """Two cycles: issue the read, then observe the registered result."""
        self.cycle(addr=addr, re=1)
        return self.observe()["bus_rdata"]
