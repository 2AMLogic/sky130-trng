#!/usr/bin/env python3
"""Register map for the sky130-trng digital section.

The bus is a 4-bit **word** address (16 words); software byte offsets are
``4 * word``. The map is deliberately small and fully readable: every
health-test parameter is exposed read-only so that the provisional cutoffs
(which depend on an ``H`` this process has not measured yet -- issue #21) can
be audited from software rather than inferred from a document.

See ``spec/decision-records/DR-0004-sky130-digital-section-architecture.md``
§4 for the semantics each field commits to.
"""

from __future__ import annotations

# -- word addresses ---------------------------------------------------------

CTRL = 0x0
STATUS = 0x1
RAW_DATA = 0x2
DATA = 0x3
ALARM = 0x4
HT_RCT_CUTOFF = 0x5
HT_APT_CUTOFF = 0x6
HT_APT_WINDOW = 0x7
HT_STARTUP = 0x8
HT_COND_BLOCK = 0x9
ID = 0xA

#: ASCII "TRNG" -- a fixed, non-zero read that distinguishes "bus works,
#: block idle" from "bus returns zeros because nothing is there".
ID_VALUE = 0x54524E47

# -- CTRL fields ------------------------------------------------------------

CTRL_EN = 1 << 0          # consume samples from the raw tap
CTRL_OUT_MODE = 1 << 1    # 0 = raw, 1 = conditioned (streaming port only)
CTRL_SOFT_RST = 1 << 2    # self-clearing datapath + health-test reset
CTRL_MASK = CTRL_EN | CTRL_OUT_MODE | CTRL_SOFT_RST

# -- STATUS fields ----------------------------------------------------------

ST_STARTUP_DONE = 1 << 0
ST_GATED = 1 << 1          # conditioned path is gated (raw never is)
ST_RAW_TAP_VALID = 1 << 2  # raw_valid from the analog block
ST_RAW_FIFO_VALID = 1 << 3
ST_COND_FIFO_VALID = 1 << 4
ST_ALARM = 1 << 5
ST_RAW_LEVEL_SHIFT = 8     # bits 11:8
ST_COND_LEVEL_SHIFT = 12   # bits 15:12
ST_RAW_OVF = 1 << 16       # sticky: a raw word was dropped (FIFO full)
ST_COND_OVF = 1 << 17      # sticky: a conditioned word was dropped

# -- ALARM fields (write-1-to-clear) ---------------------------------------

AL_RCT = 1 << 0
AL_APT = 1 << 1
AL_STARTUP = 1 << 2
AL_MASK = AL_RCT | AL_APT | AL_STARTUP
