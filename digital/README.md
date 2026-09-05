# digital

The digital section: health tests, conditioner, and the register/streaming
interface. Everything **downstream of the raw tap**.

`design/` stops at `raw_bit` on purpose — the analog/digital verification
boundary is drawn there, so everything in this directory is a behavioural
model plus RTL, and none of it is ever a SPICE subcircuit
(`spec/porting-plan.md` §1.1, gf180-trng DR-0009's cost argument: a
transistor-level run of a 256-sample conditioner block extrapolates to days,
a 10⁶-sample entropy dataset to decades).

Full statement of what is built here and why:
[`spec/decision-records/DR-0004-sky130-digital-section-architecture.md`](../spec/decision-records/DR-0004-sky130-digital-section-architecture.md)
(status **Proposed**).

## What is here

```
digital/
  model/          bit-exact, cycle-accurate Python behavioural model -- NORMATIVE
    params.py       alpha/W/K and the SP 800-90B cutoff formulas (and their evaluation)
    health.py       RCT, APT, start-up test, latch-and-gate policy
    conditioner.py  CRC-32 LFSR (K = 8), plus two independent references
    regmap.py       register map constants
    digital_top.py  the assembled section and its cycle contract
  rtl/
    trng_digital.v  synthesisable Verilog-2001 implementation of the model
  tb/
    tb_trng_digital.v  file-driven co-simulation testbench (carries no golden vectors)
```

**The model is normative and the RTL is an implementation of it.** If they
disagree, the RTL is wrong. `sim/digital-rtl-equivalence/` is the record that
they agree, cycle for cycle, over a directed program.

## Block diagram

```
raw_bit ─┬─► RCT  ─┐
         │  APT  ──┴─► health monitor ─► ALARM (sticky, W1C) ─► gate ─┐
         │                              start-up test (1024) ─────────┤
         │                                                            ▼
         ├─► raw packer (32b) ─► raw FIFO ──────────────► RAW_DATA  (never gated)
         │                                    │
         └─► CRC-32 LFSR (256b) ─► cond FIFO ─┴─► DATA           (gated)
                                                    │
                              OUT_MODE ─► mux ─► out_data/out_valid/out_ready
```

## Register map

Word-addressed; software byte offset is `4 × word`.

| Word | Byte | Name | Access | Contents |
|---|---|---|---|---|
| 0x0 | 0x00 | `CTRL` | RW | `[0]` EN, `[1]` OUT_MODE (0 = raw, 1 = conditioned), `[2]` SOFT_RST (self-clearing) |
| 0x1 | 0x04 | `STATUS` | RO | `[0]` STARTUP_DONE, `[1]` GATED, `[2]` RAW_TAP_VALID, `[3]` RAW_FIFO_VALID, `[4]` COND_FIFO_VALID, `[5]` ALARM, `[11:8]` raw FIFO level, `[15:12]` conditioned FIFO level, `[16]` RAW_OVF, `[17]` COND_OVF |
| 0x2 | 0x08 | `RAW_DATA` | RO, pops | 32 raw bits, LSB-first. **Never gated** |
| 0x3 | 0x0C | `DATA` | RO, pops | one conditioned word; reads 0 and does not pop while gated |
| 0x4 | 0x10 | `ALARM` | RW1C | `[0]` RCT, `[1]` APT, `[2]` STARTUP |
| 0x5 | 0x14 | `HT_RCT_CUTOFF` | RO | `C_RCT` as built (81) |
| 0x6 | 0x18 | `HT_APT_CUTOFF` | RO | `C_APT` as built (824) |
| 0x7 | 0x1C | `HT_APT_WINDOW` | RO | `W` as built (1024) |
| 0x8 | 0x20 | `HT_STARTUP` | RO | start-up test length as built (1024) |
| 0x9 | 0x24 | `HT_COND_BLOCK` | RO | raw bits per conditioned word (256) |
| 0xA | 0x28 | `ID` | RO | `0x54524E47` ("TRNG") |

The four `HT_*` registers exist because the cutoffs are **provisional**: they
are a formula evaluation at an assumed `H`, and no sky130 raw bitstream has
been simulated yet (issue #21). Exposing them read-only means software can
check what the silicon was actually built with instead of trusting a
document.

## Parameters as built

| Parameter | Value | Status |
|---|---|---|
| `alpha` (false-alarm rate) | 2⁻⁴⁰ | re-derived at this repo's own 50 kbps raw rate — DR-0004 §2.2 |
| `W` (APT window) | 1024 | SP 800-90B §4.4.2, binary source |
| `H` (cutoffs evaluated at) | 0.5 bit/sample | README **design target**, not a measurement |
| `C_RCT` | 81 | formula evaluation at `H` = 0.5 — **provisional** |
| `C_APT` | 824 | formula evaluation at `H` = 0.5 — **provisional** |
| start-up test | 1024 samples (20.48 ms at 50 kHz) | SP 800-90B §4.3 |
| conditioner | CRC-32 LFSR, `K` = 8 (256 raw bits → one 32-bit word) | non-vetted; no full-entropy claim |
| FIFO depth | 4 words per path | area/latency trade, DR-0004 §4.4 |

**Every entropy-dependent number here is provisional and
simulation-derived.** Nothing in this directory has been measured on
silicon, and none of it is an SP 800-90B entropy assessment.

## Running it

```bash
# fast unit tests (stdlib only, no simulator, no PDK)
python3 sim/tests/test_digital_section.py

# the cutoff derivation, printed
python3 digital/model/params.py

# the evidence campaigns (add --emit-record to mint an append-only record)
python3 sim/digital-health-test-parameters/analysis/health-test-cutoffs.py
python3 sim/digital-conditioner-equivalence/harness/conditioner-equivalence.py
python3 sim/digital-section-behavioral/harness/digital-section-campaign.py
python3 sim/digital-rtl-equivalence/harness/rtl-cosim.py          # needs iverilog
```

## Deliberately not here

- **Synthesis, gate-level timing, area and power.** No `sky130_fd_sc_hd`
  mapping has been run, so this directory supports no `Fmax`, area or power
  claim. That is the next increment, and it is what
  `docs/chipalooza/challenge-4-proposal.md` row G still needs.
- **A host-clock domain crossing.** The register bus is in the 50 kHz sample
  clock domain. A real integration wants a CDC to a faster host bus; the
  synchroniser and FIFO handshake for that are not designed here.
- **A vetted conditioner.** The README's stretch row (a vetted conditioner
  if the area budget allows) is untouched — this is the non-vetted CRC-32
  the target-specification table names.
- **Any entropy estimate.** The health tests and the conditioner are logic;
  the min-entropy they are parameterised by comes from the analog source and
  has not been simulated for sky130 (issue #21).
