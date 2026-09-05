#!/usr/bin/env python3
"""Continuous and start-up health tests, bit-exact behavioural model.

SP 800-90B §4.4.1 (Repetition Count Test) and §4.4.2 (Adaptive Proportion
Test), plus the §4.3 start-up test, exactly as
``spec/decision-records/DR-0004-sky130-digital-section-architecture.md`` §2
specifies them. Cutoffs come from :mod:`digital.model.params`; nothing in
this module hard-codes a number.

Both tests operate on the **raw** tap (``raw_bit`` at ``sampler_core``'s
output, ``design/README.md`` § "Pins that leave the block") and never on the
conditioned stream -- conditioning a stream before testing it hides exactly
the failure the tests exist to catch.
"""

from __future__ import annotations

from .params import C_APT, C_RCT, STARTUP_SAMPLES, W_APT


class RepetitionCountTest:
    """SP 800-90B §4.4.1: fail on ``cutoff`` consecutive identical samples."""

    def __init__(self, cutoff: int = C_RCT) -> None:
        self.cutoff = cutoff
        self.reset()

    def reset(self) -> None:
        self.ref: int | None = None
        self.count = 0
        self.failed = False

    def update(self, bit: int) -> bool:
        """Feed one raw sample. Returns True on the sample that fails."""
        bit &= 1
        if self.ref is None or bit != self.ref:
            self.ref = bit
            self.count = 1
        else:
            self.count += 1
        fail = self.count >= self.cutoff
        self.failed = self.failed or fail
        return fail


class AdaptiveProportionTest:
    """SP 800-90B §4.4.2: fail when a window's reference value recurs too often.

    The first sample of each window is the reference and counts as one match;
    the window is ``w`` samples long, and the verdict is taken on the last
    sample of the window.
    """

    def __init__(self, window: int = W_APT, cutoff: int = C_APT) -> None:
        self.window = window
        self.cutoff = cutoff
        self.reset()

    def reset(self) -> None:
        self.ref: int | None = None
        self.matches = 0
        self.index = 0
        self.failed = False

    def update(self, bit: int) -> bool:
        """Feed one raw sample. Returns True on the sample that fails."""
        bit &= 1
        if self.index == 0:
            self.ref = bit
            self.matches = 1
        else:
            if bit == self.ref:
                self.matches += 1
        self.index += 1
        fail = False
        if self.index == self.window:
            fail = self.matches >= self.cutoff
            self.index = 0
            self.ref = None
            self.matches = 0
        self.failed = self.failed or fail
        return fail


class HealthMonitor:
    """RCT + APT + the start-up test, and the latch-and-gate policy.

    Failure behaviour, per DR-0004 §4.2 (the policy carried over from
    gf180-trng's DR-0002 and tightened here on one point -- an explicit
    software acknowledgement is required before the conditioned path can
    resume):

    * the alarm bits are **sticky**, cleared only by a write-1-to-clear;
    * the **conditioned** path is gated on failure; the **raw** path never is;
    * a gate flushes the conditioner and the conditioned FIFO;
    * ungating requires *both* a cleared alarm and a fresh, passing
      ``STARTUP_SAMPLES``-sample start-up test.
    """

    def __init__(self, c_rct: int = C_RCT, c_apt: int = C_APT,
                 window: int = W_APT, startup: int = STARTUP_SAMPLES) -> None:
        self.rct = RepetitionCountTest(c_rct)
        self.apt = AdaptiveProportionTest(window, c_apt)
        self.startup_samples = startup
        self.reset()

    def reset(self) -> None:
        """Power-on / reset state: alarms clear, start-up test running."""
        self.rct.reset()
        self.apt.reset()
        self.alarm_rct = False
        self.alarm_apt = False
        self.alarm_startup = False
        self.startup_count = 0
        self.startup_done = False

    # -- alarm plumbing ---------------------------------------------------

    @property
    def alarm(self) -> bool:
        return self.alarm_rct or self.alarm_apt or self.alarm_startup

    @property
    def gated(self) -> bool:
        """True while the conditioned path must produce nothing."""
        return self.alarm or not self.startup_done

    def clear_alarm(self, mask: int) -> None:
        """Write-1-to-clear over the ALARM register's three bits."""
        if mask & 0b001:
            self.alarm_rct = False
        if mask & 0b010:
            self.alarm_apt = False
        if mask & 0b100:
            self.alarm_startup = False

    # -- the per-sample step ---------------------------------------------

    def update(self, bit: int) -> bool:
        """Feed one raw sample. Returns True if this sample raised an alarm."""
        rct_fail = self.rct.update(bit)
        apt_fail = self.apt.update(bit)
        raised = False

        if rct_fail:
            self.alarm_rct = True
            raised = True
        if apt_fail:
            self.alarm_apt = True
            raised = True

        if not self.startup_done:
            if rct_fail or apt_fail:
                # A failure during the start-up window is its own alarm bit:
                # it means the block never reached a state where conditioned
                # output was permissible, which software must be able to tell
                # apart from a mid-run trip.
                self.alarm_startup = True
                self.startup_count = 0
                self.rct.reset()
                self.apt.reset()
                raised = True
            else:
                self.startup_count += 1
                if self.startup_count >= self.startup_samples:
                    self.startup_done = True
        elif raised:
            # Mid-run trip: re-arm the start-up test. Ungating additionally
            # requires the sticky alarm to be acknowledged (DR-0004 §4.2).
            self.startup_done = False
            self.startup_count = 0
            self.rct.reset()
            self.apt.reset()

        return raised
