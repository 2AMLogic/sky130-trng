---
dr: DR-0004-sky130-digital-section-architecture
title: sky130 digital section -- health tests, conditioner, and the two-path register/streaming interface
status: Proposed
date: 2026-09-05
deciders: unratified — Proposed by the Builder on #20; ratification is an operator/Champion action
supersedes: n/a (this is the first record covering anything downstream of the raw tap)
superseded_by: n/a
related: "#20 (this record), #21 (the raw-bitstream min-entropy simulation every cutoff here is conditional on), #22 (layout, which needs this section's RTL to exist), DR-0003 (the 50 kbps operating point and the model-derived H this record evaluates against), spec/porting-plan.md §1.1/§2.3/§3.2 (the carryover table this record follows), digital/ (the model, RTL and testbench), sim/digital-health-test-parameters/, sim/digital-conditioner-equivalence/, sim/digital-section-behavioral/, sim/digital-rtl-equivalence/ (the four evidence sets), docs/chipalooza/challenge-4-proposal.md rows F/G/H"
---

# DR-0004: sky130 digital section -- health tests, conditioner, and the two-path register/streaming interface

## Status

- 2026-09-05: **Proposed.** Not accepted by anyone. This record proposes the
  architecture of everything downstream of the raw tap, fixes the
  health-test parameters *conditionally* on an assumed `H`, and hands
  `digital/` its numbers. It does not ratify DR-0001, DR-0002 or DR-0003,
  it does not move any README target row, and it does not authorise
  silicon.
- 2026-09-09: **Follow-up discharged (issue #117).** "Synthesis against
  `sky130_fd_sc_hd`" — named above as "the single largest gap this record
  leaves" — has landed: `digital/flow/{unconstrained,constrained-50khz}/`
  (`klt synthesize` requests), `klt equiv` (`"yosys-sequential"` engine)
  proving RTL↔gate equivalence for both, and a gate-level re-run of
  `sim/digital-rtl-equivalence/`'s directed stimulus program, bit-for-bit
  matching. First `level: gate` record in this repository:
  `sim/digital-synthesis/records/`. Still open from the list below: the
  `H`-conditional cutoff re-evaluation, the per-ring liveness monitor
  question, the host-clock CDC, and FIFO depth vs. a measured area figure
  — none of those are touched by this addendum, and this entry does not
  edit the decision text above it.

## Context

`design/README.md` has said, correctly, that the digital section is
"deliberately not here" — "None of it exists in this repo yet, and drawing
it as SPICE subcircuits would fabricate netlists for circuits nobody has
designed." That was the right call while the analog side was unsized. It is
no longer the right call now that DR-0003 has fixed an operating point
(`N` = 4 five-stage rings, `T_s` = 20 µs, a 50 kbps raw rate), because three
downstream facts are now *derivable* and are blocking work elsewhere:

- `docs/chipalooza/challenge-4-proposal.md` rows F (time-to-first-valid),
  G (digital `Fmax`) and H (health-test cutoffs) all read "N/A — not yet
  designed", and the Challenge #4 pin budget has no health-test alarm or
  register bus to offer.
- Issue #22 (layout, DRC/LVS) needs this section's RTL to exist before a
  whole-block layout is meaningful.
- `spec/porting-plan.md` §3.3's Tier 1 "designed-for-90B" claim requires
  raw access *plus continuous health tests* — half of which does not exist.

`spec/porting-plan.md` §1.1 already partitions gf180-trng's digital-section
design into what transfers as methodology and what has to be re-derived.
This record follows that partition rather than re-litigating it, and §7
below audits itself against it row by row.

**The load-bearing caveat, stated once here and repeated everywhere it
matters**: every health-test cutoff in this record is a *formula evaluation
at an assumed `H`*. No sky130 raw bitstream has been simulated (issue #21),
so this process has no measured `H` at all. That is not a reason to defer
the architecture — the formulas, the policy, the interface and the
conditioner are all independent of the value — but it is a reason no number
here may be quoted without its condition.

## Decision

**We adopt a digital section consisting of continuous SP 800-90B RCT and APT
health tests plus a start-up test, a non-vetted CRC-32 LFSR conditioner
(`K` = 8), and a two-path register/streaming interface in which the raw path
is always available and never gated. It is specified by a normative
bit-exact behavioural model (`digital/model/`), implemented in Verilog
(`digital/rtl/`), and verified behaviourally — never in SPICE.**

### 1. Where the block boundary sits, and why nothing here is a SPICE deck

The analog/digital verification boundary stays exactly where
`design/README.md` draws it: at `raw_bit`, the sampler output. Everything
upstream is transistor-level because device physics decides the answer;
everything from `raw_bit` downstream is a bit-exact behavioural model plus
RTL, per `spec/porting-plan.md` §1.1's carryover of gf180-trng's DR-0009,
whose cost argument is tool-general and applies to ngspice on sky130
unchanged (a transistor-level run of a 256-sample conditioner block
extrapolates to days; a 10⁶-sample entropy dataset to decades).

Consequence, stated so it cannot be misread later: **no record produced by
this section may ever be cited for a P/V/T-dependent claim.** There is no
corner axis in `sim/digital-*/` and there should not be one. The digital
section's own PVT behaviour (setup/hold, `Fmax`, leakage) is a *gate-level*
question that needs synthesis against `sky130_fd_sc_hd`, which this record
does not perform (§ "Consequences").

New top-level directory `digital/`, not `design/digital/`: `design/` is
xschem/SPICE sources by its own README's definition, and putting
non-netlist sources under it would blur exactly the boundary the previous
paragraph draws.

### 2. Health tests

#### 2.1 Formulas and structure: carried over unchanged

Per `spec/porting-plan.md` §1.1, these transfer as methodology and are
adopted verbatim:

- `C_RCT = 1 + ⌈−log₂(α)/H⌉` (SP 800-90B §4.4.1);
- `C_APT` = the smallest `C` with `Pr(X ≥ C) ≤ α` for `X ~ Binomial(W, 2⁻ᴴ)`
  (§4.4.2);
- `W` = 1024 for a binary source;
- a start-up test of 1024 consecutive samples before any conditioned output
  (§4.3).

`digital/model/params.py` implements the formulas rather than transcribing
their results, so re-evaluating at a new `H` is a one-line change.

#### 2.2 `α` = 2⁻⁴⁰: the number is inherited, the justification is not

`α` is a false-alarm *rate*; it only becomes a false-alarm *interval* once a
sample rate is fixed, and sky130-trng's rate (50 kbps, DR-0003) is 20×
below the 1 Mbps row gf180-trng's choice was argued against. Re-derived at
this repository's own rate
(`sim/digital-health-test-parameters/`):

| | sky130-trng, 50 kbps | gf180-trng, 1 Mbps row |
|---|---|---|
| RCT false-alarm interval (one decision per sample) | **254.5 days** | 12.7 days |
| APT false-alarm interval (one decision per 1024-sample window) | **713.6 years** | — |

At this rate `α` = 2⁻⁴⁰ is *more* conservative than the inherited argument
required. We keep it anyway: relaxing to 2⁻³⁰ would move `C_RCT` from 81 to
61, i.e. buy **0.4 ms** of detection latency at 50 kbps, which is not worth
either the extra false-alarm rate or the loss of direct comparability with
the sibling repository's parameters.

#### 2.3 The cutoffs are evaluated at `H` = 0.5, the design *floor* — not at DR-0003's model value

Two candidate values of `H` exist for sky130 today, and neither is a
measurement:

- `H₀` = **0.5** bit/sample — the README's target-specification row, the
  value DR-0002/DR-0003 *sized the array against*;
- `H` = **0.5415** — what DR-0003 §3's sizing law *models* the drawn `N` = 4
  array as delivering at `T_s` = 20 µs, at the entropy-binding corner.

**We evaluate the cutoffs at 0.5.** Cutoffs shrink as `H` grows, so
evaluating at 0.5415 (`C_RCT` = 75, `C_APT` = 806) would produce a health
test that false-alarms *faster than `α` promises* for any true `H` below
0.5415 — and DR-0002 §6 declares a ~2–4× uncertainty band on every
`Q`-derived figure, which makes exactly that outcome likely. Evaluating at
the spec floor keeps the false-alarm guarantee valid across the whole range
the design claims to operate in, at the cost of slightly later detection.

Resulting adopted parameters, **provisional pending issue #21**:

| Parameter | Value | Basis |
|---|---|---|
| `C_RCT` | **81** | `1 + ⌈40/0.5⌉` |
| `C_APT` | **824** | exact binomial tail at `p` = 2⁻⁰·⁵, `W` = 1024, `α` = 2⁻⁴⁰ |

These are the same two numbers gf180-trng's DR-0002 records. **That is a
result, not a port**: identical formulas, identical `α` and `W`, and both
repositories currently targeting `H` = 0.5 must produce identical cutoffs,
and it would be evidence of an error if they did not. The load-bearing
artifact is the *table* in `sim/digital-health-test-parameters/`, which
gives the cutoff at every `H` from the degeneracy floor to 1.0 — the moment
sky130's measured `H` differs, the cutoffs move and the agreement
disappears. Recomputing them here from first principles also independently
reproduces gf180-trng's published values, which is the cheapest available
check on this implementation of the formulas.

#### 2.4 The APT degeneracy floor, computed exactly rather than quoted

`Pr(X ≥ W) = p^W = 2^(−H·W)`, so a valid cutoff `C ≤ W` exists only while
`2^(−H·W) ≤ α`:

    H > α_log2 / W = 40 / 1024 = 0.0390625

gf180-trng's DR-0002 states this as "no valid cutoff below `H ≈ 0.03`,
marginal below `H ≈ 0.05`". The exact value at these parameters is
**0.0390625**, and the practical floor is higher: at `H` = 0.05 the cutoff
is 1022 of 1024, i.e. the test only fires when essentially every sample in
a window matches. The design target `H` = 0.5 sits 12.8× above the floor,
so this is a stated risk boundary and not an active constraint — but it is
precisely the boundary issue #21's measurement could move the design into,
and `sim/tests/test_digital_section.py` asserts the clearance rather than
assuming it. **If #21 measures `H` below ~0.1, the APT as parameterised
here stops being a meaningful test and this record must be reopened**, not
patched by nudging a cutoff.

#### 2.5 Failure behaviour: latch and gate, with the ungate condition tightened

Carried over from gf180-trng's DR-0002 unchanged:

- alarm flags are **sticky**, cleared only by write-1-to-clear;
- a failure gates the **conditioned** path; the **raw** path is never
  gated, under any condition (SP 800-90B requires raw access, and the raw
  samples that caused the failure are exactly what a diagnostician needs);
- a gate flushes the conditioner and the conditioned FIFO, so no pre-failure
  bit can reach a post-failure word;
- the start-up test re-arms on a trip.

**Tightened here** (a deliberate deviation, not an oversight): ungating
requires **both** a cleared alarm *and* a start-up test that has passed
since the trip. Neither alone is sufficient. gf180-trng's policy as written
leaves it open whether a self-healing source silently resumes conditioned
output; making the acknowledgement mandatory means a trip is always visible
to software, which matters more here than there because this block's
intended integration path (Chipalooza Challenge #4) exposes a small number
of pins and one of the few things software *can* observe is the alarm.
`sim/digital-section-behavioral/` experiment G demonstrates both halves of
the conjunction independently.

A trip inside the start-up window raises the START-UP alarm bit *as well as*
the failing test's own bit, so software can distinguish "never came up"
from "came up and later failed".

### 3. Conditioner

#### 3.1 Non-vetted CRC-32 LFSR, `K` = 8

Adopted as the README's target-specification row already commits to
(`spec/porting-plan.md` §1.1 carries gf180-trng's DR-0008 across as a
*starting assumption*): 256 raw bits in, one 32-bit word out, generator
`0x04C11DB7`, register seeded `0xFFFFFFFF`.

#### 3.2 Re-seeded at every block boundary

The register is re-seeded at the start of each 256-bit block rather than
free-running across blocks. This is a decision, so it is recorded: a
free-running register makes every output word depend on the entire history
since reset, which is harmless for entropy but makes the entropy accounting
per word ("256 raw bits × `H` into this word") false as stated, and makes a
flush semantically murky. Bounded, non-overlapping block dependency keeps
the accounting exact and makes the flush total.
`sim/digital-conditioner-equivalence/` checks the property directly:
flipping one raw bit changes exactly its own block's word and no other.

#### 3.3 The entropy claim stays at the raw tap

This is a **non-vetted** conditioner in SP 800-90B terms. A CRC is a linear
map over GF(2): it redistributes entropy, it cannot create any. The block
therefore states its entropy at the raw tap and never at the conditioner
output, and makes **no full-entropy claim** for `DATA`. At the design
target this is 256 × 0.5 = 128 bits of min-entropy compressed into a 32-bit
word — a 4× input-to-output ratio — which is a *design margin*, not an
assessment. Per `spec/porting-plan.md` §3.3, an actual 90B output-entropy
figure for a non-vetted conditioner is Tier-2 work sequenced behind a
measured `H`, and is not claimed here.

### 4. Interface

#### 4.1 Two paths, one register map

The two-output-path convention carries over unchanged (`RAW_DATA` and
`DATA` as distinct read registers, `OUT_MODE` selecting which path the
streaming port carries, raw always readable). The map is in
`digital/README.md`; the design-relevant choices are:

- **The health-test parameters are readable** (`HT_RCT_CUTOFF`,
  `HT_APT_CUTOFF`, `HT_APT_WINDOW`, `HT_STARTUP`, `HT_COND_BLOCK`).
  Because the cutoffs are provisional, software must be able to discover
  what the silicon was actually built with instead of trusting a document
  that may have moved. This is a direct consequence of §2.3's conditionality.
- **A non-zero `ID`** (`0x54524E47`) so "the bus works and the block is
  idle" is distinguishable from "the bus returns zeros".
- **FIFO overflow is reported, not hidden** (`STATUS.RAW_OVF` /
  `COND_OVF`). The source is free-running and cannot be back-pressured, so
  a slow consumer *will* drop words; the design's job is to say so.

#### 4.2 Mode switches flush everything

Writing a different `OUT_MODE` flushes the conditioner, its partial block,
and **both** FIFOs — carried over from DR-0001/DR-0013. Without it a mode
switch would hand the consumer words assembled under the previous mode's
gating state.

#### 4.3 Clock domain

The whole section, register bus included, is in the 50 kHz sample-clock
domain. At 50 kHz there is no plausible timing pressure inside the block,
and a single domain removes every CDC hazard from the part of the design
that has to be *correct* rather than fast. A real SoC integration wants a
CDC to a host bus clock; that synchroniser is explicitly out of scope here
(§ "Consequences").

#### 4.4 FIFO depth 4 per path

Deliberately small. gf180-trng's own area row (DR-0019/DR-0020, a 2.7× miss
against its ratified budget) is explicitly tied to FIFO depth, and
`spec/porting-plan.md` §2.6 warns against inheriting that unresolved
tension in either direction. Four words is 32 bit-times of consumer slack at
either path's word rate; deeper is a decision to be made against a measured
area figure, which does not exist yet.

### 5. The model is normative; the RTL is an implementation

`digital/model/` is the specification of the block's behaviour, stated as
executable Python with an explicit cycle contract.
`digital/rtl/trng_digital.v` implements it. If they disagree, the RTL is
wrong. `digital/tb/tb_trng_digital.v` deliberately carries **no** golden
vectors — it transcribes stimulus in and observations out, and the
comparison happens against the model, because a testbench holding its own
expected values can only confirm what its author already believed.

### 6. Evidence

Four append-only records, all `level: behavioral`, plus 31 standard-library
unit tests (`sim/tests/test_digital_section.py`):

| Slug | What it establishes |
|---|---|
| `sim/digital-health-test-parameters/` | the cutoff table over an `H` grid, the exact degeneracy floor, and the false-alarm/latency consequences at 50 kbps (§2) |
| `sim/digital-conditioner-equivalence/` | the conditioner is bit-exact against GF(2) long division *and* against `zlib.crc32`, with per-block dependency and flush checked (§3) |
| `sim/digital-section-behavioral/` | eight experiments over declared synthetic sources: start-up timing, an RCT trip at exactly `C_RCT`, an APT trip on a window boundary, a below-target-`H` source that correctly does *not* trip, a 10⁶-sample false-alarm floor, the raw-never-gated invariant, the ungate conjunction, and mode-switch flush (§2.5, §4) |
| `sim/digital-rtl-equivalence/` | the RTL matches the normative model on all six observable outputs for all 4239 cycles of a directed program (§5) |

Two numbers fall out that other documents were waiting on, both at
DR-0003's 50 kHz sample clock:

- **time to first raw word: 0.64 ms** (32 samples; the raw path is never
  gated, so nothing else is in the way);
- **time to first conditioned word: 25.60 ms** (1024-sample start-up test
  = 20.48 ms, then one 256-bit block = 5.12 ms).

### 7. Self-audit against `spec/porting-plan.md` §1.1

| Carryover item | Treatment here |
|---|---|
| RCT/APT formulas parameterised by `H`; `α` = 2⁻⁴⁰; `W` = 1024 | adopted unchanged as *formulas*; `α`'s justification re-derived at 50 kbps (§2.2) |
| APT degeneracy floor | re-derived exactly (0.0390625, vs the source's "≈0.03"), and asserted in the test suite (§2.4) |
| Latch-and-gate failure behaviour | adopted, with the ungate condition tightened to a conjunction (§2.5) |
| Two output paths, `RAW_DATA`/`DATA`, `OUT_MODE`, mode-switch flush | adopted unchanged (§4.1–4.2) |
| Behavioural/transistor verification split at the raw tap | adopted unchanged (§1) |
| Evidence-record discipline (append-only, `level:`, seeds stated) | adopted; extended to behavioural runs via `sim/bin/evidence_record.py`'s `mint_behavioral_record()` |
| SP 800-90B three-tier claim discipline | adopted: this record is Tier-1 work only, and says so (§3.3) |
| **Numeric cutoffs** (`C_RCT` = 81, `C_APT` = 824 at `H₀` = 0.5) | **re-derived, not copied** — evaluated here from the formulas at this repo's own stated `H`, with the full `H`-grid table as the durable artifact (§2.3) |
| Conditioner class (non-vetted CRC-32, `K` = 8) | adopted as a starting assumption, with the block-boundary re-seed decided here (§3.2) |

## Alternatives considered

### Evaluate the cutoffs at DR-0003's model-derived `H` = 0.5415

- **What**: use `C_RCT` = 75, `C_APT` = 806 — the values at the `H` this
  repository's own sizing law says the drawn array delivers.
- **Why plausible**: it is a sky130-specific number derived from sky130
  measurements, which is exactly what "re-derive, don't copy" asks for, and
  it detects failure marginally sooner.
- **Why rejected**: `H` = 0.5415 is a *model output* carrying DR-0002 §6's
  declared ~2–4× uncertainty on `Q`, not a measurement. Cutoffs evaluated
  at an `H` the source does not actually achieve false-alarm faster than
  `α` promises, and the whole point of `α` is that it is a guarantee. The
  spec floor is the value the design is *committed* to; the model value is
  a hope. Where they differ, a health test should be parameterised by the
  commitment.

### Relax `α` to 2⁻³⁰ because 50 kbps buys so much false-alarm headroom

- **What**: exploit the 254-day RCT false-alarm interval (§2.2) to tighten
  the cutoffs.
- **Why plausible**: SP 800-90B's recommended range is 2⁻²⁰ … 2⁻⁴⁰, so 2⁻³⁰
  is squarely inside it, and tighter cutoffs detect degradation sooner.
- **Why rejected**: the gain is 0.4 ms of detection latency at this sample
  rate — nothing, against a start-up test that already costs 20.48 ms — and
  the cost is a real reduction in the false-alarm guarantee plus a
  parameter that no longer lines up with the sibling repository's, making
  the two designs' health-test behaviour harder to compare. The
  conservative default is free here.

### Free-running conditioner (no per-block re-seed)

- **What**: let the CRC register run continuously and sample it every 256
  bits.
- **Why plausible**: it is marginally cheaper (no re-seed mux) and mixes
  more history into each word.
- **Why rejected**: it makes the per-word entropy accounting in §3.3 false
  as stated and makes "flush" ambiguous — after a gate, a free-running
  register still carries pre-failure state into the next word unless it is
  re-seeded anyway, at which point the saving is gone. Bounded dependency
  is also what makes the equivalence check in
  `sim/digital-conditioner-equivalence/` a sharp test rather than a vague one.

### Gate the raw path when the health tests fail

- **What**: stop `RAW_DATA` from returning words while an alarm is latched.
- **Why plausible**: intuitively, a block that knows its source is broken
  should not hand out data from it.
- **Why rejected**: it is exactly backwards for an SP 800-90B entropy
  source. Raw access is a Tier-1 requirement, and the samples produced
  around a failure are the most diagnostically valuable ones the block will
  ever produce. The conditioned path is gated *because* a consumer may
  reasonably treat it as ready-to-use; the raw path carries no such
  implication. This is asserted as an invariant in both the unit tests and
  the behavioural campaign, and it is one of the two mutations used to
  confirm the RTL co-simulation can actually detect a wrong implementation.

### Auto-ungate once the source recovers, without a software acknowledgement

- **What**: gf180-trng's policy read literally — a passed start-up test
  alone lifts the gate; the sticky flag is informational.
- **Why plausible**: fewer states, no risk of a block sitting gated forever
  because nobody serviced an interrupt, and the sticky flag still records
  that something happened.
- **Why rejected**: a source that oscillates in and out of a failing state
  would silently resume conditioned output between trips, and the only
  evidence would be a flag that software may read long afterwards with no
  way to tell how much conditioned data was produced under a suspect
  source. Requiring acknowledgement makes the outage explicit. The cost —
  a block that stays gated until serviced — is acceptable precisely because
  the raw path is never gated, so nothing that acknowledgement gates is
  unavailable in the meantime.

### Put the digital section under `design/` as SPICE subcircuits

- **What**: model the health tests and conditioner as transistor-level
  netlists alongside the analog block.
- **Why plausible**: one directory, one flow, one simulator; and the
  eventual chip contains transistors either way.
- **Why rejected**: this is the exact thing `design/README.md`'s "Deliberately
  not here" section warned against, and `spec/porting-plan.md` §1.1's
  carryover of DR-0009 quantifies why: the runtimes are days-to-decades for
  the sample counts these blocks need, and none of the questions being asked
  (does the cutoff fire on the right sample? is the CRC right?) are device
  questions. Gate-level timing/power *is* a real question, but it is a
  synthesis question, not a hand-drawn-netlist question.

### RTL only, no behavioural model

- **What**: write `trng_digital.v` and verify it with a self-checking
  Verilog testbench.
- **Why plausible**: one artifact instead of two, and the RTL is what gets
  synthesised.
- **Why rejected**: a self-checking testbench encodes its author's belief
  about the answer, and for a block whose whole purpose is to be trusted,
  "the testbench agrees with the RTL" is a weak claim. Two independently
  written implementations that agree cycle-for-cycle is a much stronger
  one — and the Python model is additionally the thing that can be driven
  by 10⁶-sample campaigns and by issue #21's eventual real bitstream
  without a simulator in the loop.

## Consequences

- **Positive**:
  - The three deliverables the README's target-specification table names
    (conditioning, health tests, interface) exist as designed, executable
    artifacts rather than as targets.
  - `docs/chipalooza/challenge-4-proposal.md` rows F and H move off "N/A —
    not yet designed" to cited numbers (25.60 ms time-to-first-valid;
    `C_RCT` = 81 / `C_APT` = 824, provisional).
  - `spec/porting-plan.md` §3.3's Tier-1 "designed-for-90B" checklist gains
    its continuous-health-test item; raw access and a declared conditioning
    class were already present in intent and are now implemented.
  - Issue #22's whole-block layout now has RTL to synthesise.
  - The APT degeneracy floor is an exact, tested number rather than an
    inherited approximation.

- **Negative / accepted cost**:
  - **Every cutoff here is provisional.** They are correct arithmetic on an
    assumed `H`, and sky130 has measured no `H` at all (issue #21). If the
    measurement lands materially below 0.5, the cutoffs change; if it lands
    below ~0.1, §2.4's degeneracy discussion says the APT parameterisation
    itself has to be reopened.
  - **No synthesis has been run.** There is no `Fmax`, no gate count, no
    area and no leakage figure for this section — so
    `docs/chipalooza/challenge-4-proposal.md` row G stays "N/A", and row D's
    warning stands that the array's measured 431.6 µW is an *array-only*
    number with the digital section still to add. gf180-trng's own
    synthesised digital section cost 712.4 µW, more than this repository's
    entire 500 µW active-power row; that is a live risk this record does
    not retire.
  - **The register bus shares the 50 kHz sample clock.** Any real
    integration needs a CDC that is not designed here.
  - **The RTL equivalence claim is directed, not exhaustive.** 4239 cycles
    across eleven named phases, not a formal proof or a constrained-random
    campaign.
  - **No statistical test battery has been run** on any bitstream through
    this section, because there is no bitstream from the real source to run
    it on (issue #21). The root `CLAUDE.md`'s SP 800-22-style battery
    remains owed, sequenced behind #21.

- **Follow-up required**:
  - **Ratification** of this record (and DR-0001…DR-0003) — an
    operator/Champion action, not performed here.
  - **Re-evaluate the cutoffs against #21's measured `H`**, and re-check the
    degeneracy clearance (§2.4). This is arithmetic plus a re-run of
    `sim/digital-health-test-parameters/`, not a redesign — provided the
    measured `H` is not near the floor.
  - **Synthesis against `sky130_fd_sc_hd`** for `Fmax`, area and leakage,
    with `level: gate` records per the convention
    `spec/porting-plan.md` §3.2 names. This is the single largest gap this
    record leaves and is the natural next increment.
  - **A per-ring liveness monitor** consuming `ring_bit1..4` (the taps
    `design/xschem/trng_top.sch` already provides) — `spec/porting-plan.md`
    §5 question 1 leaves open whether sky130-trng adopts it at all, so it is
    deliberately absent here rather than half-designed.
  - **A host-clock CDC** for the register bus (§4.3).
  - **FIFO depth against a measured area figure** (§4.4).

- **Revisit if**: issue #21 measures `H` below ~0.1 (the APT
  parameterisation stops being meaningful); synthesis shows the digital
  section's power or area dominates the block's budget rows (the FIFO depth
  and the 1024-sample start-up test are the two obvious levers); or a
  vetted conditioner becomes affordable, which would change §3.3's claim
  structure, not just its implementation.
