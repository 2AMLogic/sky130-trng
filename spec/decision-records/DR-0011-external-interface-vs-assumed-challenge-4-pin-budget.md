---
dr: DR-0011-external-interface-vs-assumed-challenge-4-pin-budget
title: DR-0004's external digital interface versus the assumed Challenge #4 pin budget -- pin-demand table, interface options, one recommendation
status: Proposed
date: 2026-10-10
deciders: unratified -- Proposed by the Builder on #244; ratification is an operator action
supersedes: "n/a -- this record supersedes nothing and changes no ratified or Proposed spec value. It does not touch DR-0004's register map, RTL, or the routed layouts."
superseded_by: n/a
related: "#244 (this record), #18 (Chipalooza sign-off epic, AC1/AC4), DR-0004 (the interface whose pin demand is counted), DR-0010 (the packet pattern followed here), digital/rtl/trng_digital.v, layout/trng_digital/trng_digital.routed.v, layout/trng_whole/interface.md, layout/trng_whole/report.json, docs/chipalooza/challenge-4-proposal.md section 2 and section 5.3"
---

# DR-0011: external interface vs the assumed Challenge #4 pin budget

## Status

- 2026-10-10: **Proposed.** Not accepted by anyone. Ratification is an
  operator action; no agent declares this record Accepted.
- Doc and spec only. No RTL, layout, simulation or tool change is made by this
  record. DR-0004's register map is not altered; the recommendation is
  deliberately a *wrapper* around the existing RTL.
- **The budget is an assumption.** The "24 digital control inputs / 12 digital
  test outputs" figures are this repository's stated assumption
  (`docs/chipalooza/challenge-4-proposal.md` section 2.1), taken from the
  structure of earlier Chipalooza challenges. Challenge #4's `rules-4.html`
  was still unpublished (HTTP 404) at the last re-check recorded in that
  document (2026-10-07). Nothing below treats 24/12 as binding; every
  "fits / does not fit" statement is relative to that assumption and must be
  re-evaluated when the real brief publishes.

## Context

The brief's section 2 was written against the 16-port analog netlist
(`design/trng_top.spice`) and asks for 6 of 24 digital inputs and 6 of 12 digital
test outputs. It states that this "predates DR-0004 and is not updated". Since
then the digital section (DR-0004) was designed, synthesized, placed and routed
(`layout/trng_digital/`) and composed with the analog half
(`layout/trng_whole/`), and the composed block carries the whole DR-0004
interface as external pins. The re-map was listed as a section 5.3 open item
with no issue; #244 is that issue.

## Pin-demand table (re-counted, not copied)

Sources, all read at `origin/main` `a6063ef`:

- Module header, `digital/rtl/trng_digital.v` lines 40-62.
- Routed netlist, `layout/trng_digital/trng_digital.routed.v` lines 1-30 (port
  declarations; identical port set and widths to the RTL header).
- Whole-block audit, `layout/trng_whole/report.json` `audits.interface`
  (`digital_signal_bits` 111, `digital_physical_pins` 113 = 111 signals +
  `VPWR`/`VGND`, `digital_shared_pins` = `clk`, `raw_bit`, `raw_valid`,
  `rst_n`, `digital_external_pins` 107, `analog_pins` 18) and
  `layout/trng_whole/interface.md`.
- Functional use of `bus_wdata`: `grep bus_wdata digital/rtl/trng_digital.v`.

### Digital macro `trng_digital`, per port

| Port | Dir | Width | Source/sink | Whole-block exposure today |
|---|---|---|---|---|
| `clk` | in | 1 | external, shared with analog | boundary pad |
| `rst_n` | in | 1 | external, shared with analog | boundary pad |
| `raw_bit` | in | 1 | analog `raw_bit` | internal net, no pad |
| `raw_valid` | in | 1 | analog `raw_valid` | internal net, no pad |
| `bus_addr` | in | 4 | external | external pin |
| `bus_we` | in | 1 | external | external pin |
| `bus_re` | in | 1 | external | external pin |
| `bus_wdata` | in | 32 | external | external pin x32 |
| `out_ready` | in | 1 | external | external pin |
| `bus_rdata` | out | 32 | external | external pin x32 |
| `out_data` | out | 32 | external | external pin x32 |
| `out_valid` | out | 1 | external | external pin |
| `alarm` | out | 1 | external | external pin |
| `gated` | out | 1 | external | external pin |
| `startup_done` | out | 1 | external | external pin |

Re-count: inputs 1+1+1+1+4+1+1+32+1 = **43**; outputs 32+32+1+1+1+1 = **68**;
total **111** signal bits, which equals `digital_signal_bits` in
`report.json`. The routed netlist declares the same ports and widths. (The
issue text said "roughly 40 inputs and about 68 outputs"; the exact figures
are 43 including the two analog-fed taps, so 41 external, and 68.)

### Whole-block external demand (digital plus analog pins)

| Group | Inputs | Outputs | Basis |
|---|---|---|---|
| Digital macro, external signals | 41 (`clk`, `rst_n`, `bus_addr[3:0]`, `bus_we`, `bus_re`, `bus_wdata[31:0]`, `out_ready`) | 68 | 43 - 2 analog-fed taps; 111 - 2 = 109 = 107 label-only pins + `clk` + `rst_n` |
| Analog macro, external signals | 4 (`en1..en4`) | 4 (`ring_bit1..ring_bit4`) | `layout/trng_whole/interface.md` |
| **Total digital-class pins, literal** | **45** | **72** | |
| Optional taps if still wanted as test outputs | - | +2 (`raw_bit`, `raw_valid`) | currently internal nets in `trng_whole`; pads would be new composition work |
| Supplies (not digital slots) | - | - | `vdd`, `vss`, `vddr1..vddr4`: 6 pads |

Cross-check: 107 digital external + `clk` + `rst_n` + 8 analog signals + 6
supplies = 123, matching the 123 pins the LVS run extracts
(`layout/trng_whole/verify/coverage.md`, L15).

### Against the assumed budget

| Resource | Assumed budget | Brief section 2 request today | Literal DR-0004 demand | Verdict (assumed budget) |
|---|---|---|---|---|
| Digital control inputs | 24 | 6 | 45 | Over by 21 |
| Digital test outputs | 12 | 6 | 72 (74 with raw taps) | Over by 60 (62) |

### What is functionally required (important)

Only `bus_wdata[2:0]` is consumed by the RTL (`CTRL[2:0]` write at line 288,
`ALARM` write-1-to-clear at lines 327-329). `bus_wdata[31:3]` are 29 input
ports with no cell load in the routed netlist; the whole-block LVS record
already notes this as limitation L13
(`layout/trng_whole/verify/coverage.md`). So the *functional* input demand is
`clk`, `rst_n`, `bus_addr` (4), `bus_we`, `bus_re`, `bus_wdata[2:0]` (3),
`out_ready` = 12, plus `en1..en4` = **16**, which fits 24 without any
wrapper, provided the 29 unloaded `bus_wdata` pins are simply not bonded.
The inputs are therefore not the blocker. **The outputs are**: `bus_rdata`
and `out_data` are fully populated 32-bit words (`HT_*` cutoffs, `ID`,
`RAW_DATA`, `DATA`), so no bit of either can be dropped by tying.

## Rate observations that constrain the options

Derived arithmetic from numbers already in the repository (DR-0003/DR-0004:
50 kHz sample clock, raw word every 32 samples, conditioned word every 256 raw
bits, FIFO depth 4); these are sample-count derivations, not simulation
results.

- Raw word period = 32 clk = 0.64 ms. Conditioned word period = 256 clk =
  5.12 ms.
- A serial register read of `RAW_DATA` clocked by the 50 kHz `clk` needs at
  least 4 address bits plus 32 data bits = 36 clk (before any framing
  overhead), which is more than the 32-clk raw word period. A host polling
  `RAW_DATA` serially at `clk` rate cannot keep pace with the raw path
  indefinitely (overflow is reported via `STATUS.RAW_OVF`, not hidden). The
  conditioned path (5.12 ms per word) has about 7x headroom.
- Full-rate raw capture does not need the register port at all: `raw_bit` /
  `raw_valid` as test outputs already carry every raw sample (brief section
  5.2).
- A serial bus on a faster clock than `clk` removes the constraint but needs a
  clock-domain crossing, which DR-0004 section 4.3 explicitly leaves out of
  scope.

## Interface options

All options keep DR-0004's register map and RTL behaviour unchanged unless
stated.

**A. Literal (bond everything).** Expose all 111 signals. Does not fit the
assumed 12-output budget by an order of magnitude (72 vs 12). Rejected unless
the real brief is far larger than assumed.

**B. Narrow parallel bus.** Wrapper exposing, e.g., a byte-wide read data port
plus byte-select address bits, and the streaming port narrowed likewise.
Minimum outputs: 8 (`rdata`) + 8 (stream) + 4 flags + 4 `ring_bit` = 24; still
twice the assumed 12. Needs a multi-cycle byte-assembly protocol and
byte-lane muxes in a wrapper. Fits only if `ring_bit` and the stream port are
dropped, at which point a serial port is simpler.

**C. Serial register port, streaming port not bonded (recommended).** A
small wrapper around the unchanged `trng_digital` presents a framed serial
register interface (SPI-like, using the existing `clk` as shift clock so no
CDC is introduced; `cs_n` framing; `mosi`/`miso`). The wrapper drives
`bus_addr`/`bus_we`/`bus_re`/`bus_wdata` internally. The parallel streaming
port (`out_data`, `out_ready`) is not bonded; the conditioned and raw words
are read through `DATA`/`RAW_DATA` (a register read of the same FIFO pops it,
RTL "popped" logic), and full-rate raw evidence uses `raw_bit`/`raw_valid`.
`alarm`, `gated`, `startup_done` stay direct pins, plus `out_valid` as a
"word ready" strobe.

Resulting external demand (assumed-budget comparison):

| Resource | Pins | Count | Assumed budget |
|---|---|---|---|
| Digital control inputs | `clk`, `rst_n`, `en1..en4`, `cs_n`, `mosi` | 8 | 24 (16 spare) |
| Digital test outputs | `miso`, `alarm`, `gated`, `startup_done`, `out_valid`, `raw_bit`, `raw_valid`, `ring_bit1..ring_bit4` | 11 | 12 (1 spare) |

If `out_valid` or the `ring_bit` taps are not wanted, spare outputs increase;
conversely the brief's own `ring_bit1..4` request (a new use introduced by the
brief, not a DR-0004 requirement) is the first thing to give if the real
budget is smaller than assumed. If a dedicated shift clock is wanted
(`sclk`), inputs rise to 9; that variant needs a CDC (see Option D).

**D. Serial port on an independent fast `sclk`.** As C, with its own clock and
a two-flop/handshake CDC to the 50 kHz domain. Lifts the 36-clk-per-word raw
limit. Adds a synchroniser DR-0004 section 4.3 declined, a new clock pad, and
a new verification item (CDC). Not needed for the conditioned path; not
needed for raw capture if the raw taps are bonded.

**E. Revise the request instead (request more slots).** Ask for more outputs
once the real brief publishes. Depends on information that does not exist yet
and cannot be assumed; useful only as a fallback if the real budget is larger
than 12.

## Recommendation

**Option C**, as the plan of record under the assumed budget, with Option E
as the fallback if the real brief offers more outputs and Option D held back
unless a measured need appears.

Rationale: it is the smallest change that makes the interface fit
(inputs 45 -> 8, outputs 72 -> 11), it wraps rather than rewrites the RTL
(DR-0004's register map, model and all four digital evidence sets stay
authoritative), it introduces no new clock domain, and it keeps the
health/status signals (`alarm`, `gated`, `startup_done`) as direct pins as the
issue's starting point suggested. Its main cost is the 36-vs-32 clk raw-word
limit for serial `RAW_DATA` polling, which is mitigated by the direct raw tap
pins and is irrelevant to the conditioned path.

This is a recommendation only. It is not ratified and no wrapper exists.

## What Option C means for existing layouts and tables

Stated, not done:

- **`trng_digital` macro.** Its 111-signal pin set is today's routed, placed,
  synthesized, STA'd and DRC/LVS'd design. A wrapper can be added two ways:
  (i) as a separate small cell composed with the unchanged macro (existing
  `trng_digital` evidence stays valid; the composition gains a block and
  routing, and an area increase on top of the already-unmet 0.126 mm² vs
  0.05 mm² whole-block figure from DR-0010 row 7); or (ii) by re-synthesizing
  and re-routing a new digital top containing both, which invalidates
  `layout/trng_digital/` DRC/LVS/STA results and the `digital-pnr`,
  `digital-synthesis` and `digital-floorplan-compaction` evidence for that
  top. No area figure for the wrapper has been estimated in this record.
- **`trng_whole` interface table** (`layout/trng_whole/interface.md`,
  generated by `layout/bin/compose-whole.py`). The 107 label-only external
  pins would drop to the wrapper's pins; the 29 unloaded `bus_wdata` pins
  (limitation L13) would disappear. `raw_bit`/`raw_valid` would need boundary
  pads if kept as test outputs (they are internal nets today). Whole-block
  LVS (#173) would need re-running over the new composition.
- **`trng_whole` pin-count audit** (`report.json` `audits.interface`) and its
  123-pin extraction expectation would change.
- **Interim, no-wrapper note.** Independent of any option, the 29
  `bus_wdata[31:3]` pins need not be bonded, because the RTL ignores them;
  this reduces the literal demand by 29 inputs without any change.

## Consequences if ratified as proposed

- Brief section 2 is rewritten as: inputs 8 of 24, outputs 11 of 12 under the
  assumed budget, still labelled assumed.
- The DR-0004 register map and RTL are unchanged. DR-0004's own interface
  section is not edited by this record.
- A pin-budget conformance statement for #18 AC1/AC4 becomes possible once
  the wrapper exists; until then it remains a plan, not a result.

## Follow-up required (not done by this record)

1. RTL wrapper `trng_digital_io` (or equivalent): framed serial register
   port on `clk`, address/data mapping to DR-0004's bus, defined behaviour
   for write data narrower than 32 bits (only bits [2:0] are consumed),
   reset and mid-frame `cs_n` abort. Protocol detail is a design decision for
   that issue, not fixed here.
2. Re-run the affected digital evidence on the wrapped top: functional
   verification (`sim/digital-functional-verification/`), RTL equivalence
   (`sim/digital-rtl-equivalence/`), conditioned-output record
   (`sim/digital-conditioned-output/`), and a new serial-port stimulus
   including the 36-vs-32 clk raw-poll overflow case.
3. Decide wrapper integration style (separate composed cell vs re-synthesized
   top) and then: synthesis and area estimate, P&R, DRC/LVS, STA for whatever
   changes; re-run `compose-whole.py`, whole-block DRC/LVS (#173); note effect
   on the whole-block area row (DR-0010 row 7).
4. Decide bonding of `raw_bit`/`raw_valid` (new boundary pads) and whether
   `ring_bit1..4` stay in the request.
5. Operator choice on the supply-pad question that this record does not
   touch (section 2.5 of the brief: `vddr` tying).
6. When `rules-4.html` publishes, re-evaluate every count above against the
   real budget; Options D/E become live if the real budget differs.
7. After ratification, rewrite brief section 2 tables and the section 5.3
   item to reflect the ratified interface (this record only adds pointers).
