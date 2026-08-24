---
dr: DR-0001-sky130-operating-envelope
title: Build the entropy source on sky130's 1.8 V core device pair
status: Proposed
date: 2026-08-24
deciders: unratified — Proposed by the Builder on #4; ratification is an operator/Champion action
supersedes: n/a
superseded_by: n/a
related: "#4 (design sources, where this record was filed), #3 (T1 bronze tracker); spec/porting-plan.md §2.1 (the argument this record fixes), §2.2 (the jitter characterization that must follow), §2.5 (leakage survey), §3.1 (corner set); README.md §Target specification — Operating envelope row; design/xschem/ (every device instantiated under this decision)"
---

# DR-0001: Build the entropy source on sky130's 1.8 V core device pair

## Status

- 2026-08-24: **Proposed.** Not accepted by anyone. This record exists so the
  schematics landing in `design/xschem/` trace to a stated decision instead
  of an implicit assumption baked into device instantiations. Ratification is
  an operator decision, and this record does not self-declare it.

## Context

`spec/porting-plan.md` §2.1 already argues this question in full and then
explicitly defers its conclusion to "a future decision record." `CLAUDE.md`
requires that spec changes go through `spec/` with a decision record. This is
that record; its content is a restatement of §2.1's already-completed
reasoning, not new research.

The forcing question is that **gf180-trng's supply envelope has no
like-for-like sky130 counterpart.** gf180-trng's ratified 3.3 V ± 10 %
envelope rests on `nfet_03v3`/`pfet_03v3`, a *matched* 3.3 V N/P core pair,
with 6.0 V I/O devices also available. Its entropy source therefore lives in
a single symmetric core-device domain, and never had to solve a core/I/O
supply split at all.

sky130's device menu is structurally different. Verified directly against the
installed `sky130A` PDK (open_pdks commit `c6d73a35`) — first for
`spec/porting-plan.md` §2.1, and re-verified for this record and for the
schematics that accompany it:

- The standard core logic devices are `sky130_fd_pr__nfet_01v8` /
  `__pfet_01v8` (plus `_lvt`/`_hvt` threshold variants) — a matched **1.8 V**
  N/P pair. Both xschem symbols
  (`libs.tech/xschem/sky130_fd_pr/nfet_01v8.sym`, `.../pfet_01v8.sym`) exist
  in the installed PDK, so the choice is buildable with the toolchain as
  installed, not only on paper.
- **There is no matched 3.3 V core pair.** The closest 3.3 V-class device is
  `sky130_fd_pr__nfet_03v3_nvt` — an NMOS-only "native" device, with no
  `pfet_03v3_nvt` in the installed PDK. A complementary 3.3 V ring stage
  cannot be built from a symmetric core-device pair the way gf180mcu's
  `nfet_03v3`/`pfet_03v3` allows.
- 5 V/10.5 V-tolerant devices (`nfet_g5v0d10v5`/`pfet_g5v0d10v5`) and the
  `sky130_fd_io` cell library exist and are sky130's actual route to a
  3.3 V-class **I/O domain** — sky130 rings are conventionally configured
  1.8 V core / 3.3 V I/O with that library, not with a dedicated 3.3 V core
  transistor.
- The digital standard-cell library `sky130_fd_sc_hd` — which the conditioner
  and health-test section will eventually target — is a 1.8 V library.

This repo's own `README.md` currently frames the envelope as "supply per
sky130 device flavor (1.8 V core, 3.3 V I/O devices available) — confirm
before ratification." That framing implies a live choice between two core
options. There is not one: the 3.3 V option is not a core-device alternative.

**No simulation evidence exists in this repository yet, and none is cited
here.** `sim/` is empty. This is a device-availability decision, decided by
what the PDK ships, not a measured one — but it *creates* a measurement
obligation, recorded under Consequences below.

## Decision

**We will target sky130's 1.8 V core-device pair,
`sky130_fd_pr__nfet_01v8` / `__pfet_01v8`, as sky130-trng's primary operating
point for the entropy source and its sampler.**

Concretely, and as landed alongside this record:

- Every device instance in `design/xschem/` is `nfet_01v8` or `pfet_01v8`.
  No gf180mcu device reference and no other sky130 device flavour appears in
  the ported hierarchy.
- The block's supply rails (`vdd`, and each ring's own `vddr1`/`vddr2`) are
  1.8 V-class rails. The nominal operating point and its tolerance band are
  **not** fixed by this record — they belong to a corner-set decision that
  `spec/porting-plan.md` §3.1 sets up and that no evidence yet supports.
- This decision does **not** foreclose a 3.3 V I/O-domain interface. The
  register file and streaming port may sit behind `sky130_fd_io` at 3.3 V;
  only the entropy source's ring/sampler core is bound to 1.8 V here.

Rationale, in the order the alternatives fail (see below):

1. It is the only sky130 device class with a matched, symmetric N/P core
   pair, which a conventional inverter-chain ring oscillator requires.
2. It keeps the entropy source's core devices and the digital
   conditioner/health-test standard cells on one supply rail, avoiding a
   level-shifting requirement between the analog core and the digital section
   that gf180-trng's single-domain design never had to solve.
3. It is the device class every open sky130 flow targets natively, including
   the harness the sibling `sky130-bandgap` repo already exercises.

## Alternatives considered

### A 3.3 V core domain, mirroring gf180-trng's ratified envelope

- **What**: keep the ported design's supply envelope at 3.3 V ± 10 % so the
  gf180-trng spec rows, bias points, and health-test derivations transfer
  with the least disturbance.
- **Why plausible**: it is the null hypothesis of a port, and this repo's
  stated thesis is "the PDK is the variable, not the design." Minimising
  supply-domain change maximises what else can be compared like-for-like.
- **Why rejected**: sky130 does not ship the device pair it needs.
  `nfet_03v3_nvt` is NMOS-only; there is no `pfet_03v3_nvt`. A complementary
  starved inverter delay cell — the leaf cell the whole entropy source is
  built from — cannot be drawn. This is not a difficulty to engineer around,
  it is a missing primitive.

### A 5 V/10.5 V-tolerant pair (`nfet_g5v0d10v5` / `pfet_g5v0d10v5`) run at 3.3 V

- **What**: use the thick-oxide I/O-class pair, which *is* matched, biased at
  a 3.3 V-class supply, to recover a gf180-like envelope.
- **Why plausible**: it is the only other matched N/P pair in the PDK, so it
  is the only way a 3.3 V complementary ring is buildable at all.
- **Why rejected**: it puts the entropy core on I/O devices, which is a worse
  trade than it looks for a jitter TRNG. The digital section would still be
  1.8 V `sky130_fd_sc_hd`, so the level-shifting problem returns; the devices
  are optimised for tolerance rather than for the noise and speed behaviour
  the ring depends on; and the choice would have to be justified against a
  measured jitter advantage that nobody has measured. Adopting a
  non-standard core device class on the strength of an unmeasured hope is
  exactly the shortcut `CLAUDE.md` tells this repo not to take.

### Defer the decision until the sky130 jitter characterization exists

- **What**: draw nothing, run the §2.2 characterization first, and let
  measured jitter pick the device class.
- **Why plausible**: it is the most evidence-first ordering, and this repo's
  bias is strongly toward measuring before claiming.
- **Why rejected**: the characterization has to be run *on a delay cell*, and
  a delay cell has to be drawn on *some* device. The ordering is circular.
  What breaks the circle is that this decision is about device
  **availability**, not device performance: two of the three candidates are
  eliminated by what the PDK ships, before any measurement. Recording the
  choice as `Proposed`, with the measurement obligation attached, is
  strictly better than leaving it implicit in the schematics while the same
  work happens anyway.

## Consequences

- **Positive**:
  - The schematics in `design/xschem/` trace to a stated, arguable decision
    rather than to an undocumented assumption inside device instantiations.
  - One supply rail across the analog core and the digital section: no level
    shifter between the sampler's raw tap and the conditioner.
  - The design sits on the device class the open sky130 toolchain, standard
    cell library, and sibling repos all target, so nothing downstream is
    exotic.
  - Flicker and thermal noise are modelled in every sky130 corner for these
    devices (`noia`/`noib`/`noic`, `tnoia`/`tnoib`/`rnoia`/`rnoib` populated,
    `fnoimod`/`tnoimod` enabled), so the transient-noise jitter-measurement
    mechanism the architecture depends on is representable.

- **Negative / accepted cost**:
  - The block deviates from the README's draft Operating-envelope row and
    from gf180-trng's ratified 3.3 V envelope. Every gf180-trng row derived
    at 3.3 V — power, raw rate, and the health-test cutoffs that follow from
    a min-entropy assumption — is now doubly non-portable: different process
    *and* different supply.
  - A 1.8 V rail gives an inverter-chain ring less headroom above threshold
    than 3.3 V did. Whether the *starved* cell still swings rail-to-rail at
    the slow/hot/low-supply corner is an open question this decision creates
    and does not answer.
  - sky130's BSIM4 corner decks expose the unified `noia`/`noib`/`noic`
    flicker model rather than the legacy `kf`/`af` terms gf180mcu's decks
    carry. Any characterization script ported from gf180-trng's harness must
    not assume `kf`/`af` exist.

- **Follow-up required**:
  - **The sky130 analogue of gf180-trng's RO delay-cell jitter
    characterization** (`spec/porting-plan.md` §2.2): transient-noise
    jitter-accumulation runs over `design/xschem/ro_stage.sch` at 1.8 V,
    producing per-ring `sigma_1` and `T_0`. Until it exists, every geometry
    in `design/xschem/` — device widths, starve length, ring stage count,
    array size `N`, and the inter-ring frequency skew — is a provisional
    placeholder, and each schematic says so in its own text block.
  - **A mechanism check before that campaign**: confirm `.noise`/`TRNOISE` on
    `nfet_01v8`/`pfet_01v8` produces a usable jitter-accumulation signal
    under the corner decks as installed.
  - **A corner-set decision** fixing the nominal supply and its tolerance
    band, plus the process/temperature grid (`spec/porting-plan.md` §3.1).
    This record deliberately does not fix a supply *number*.
  - **A leakage survey** (§2.5): the idle-current row and the per-ring
    liveness margin both depend on 1.8 V-device leakage, which is one of the
    things the porting plan flags as needing its own measurement.
  - **README Operating-envelope row** should be updated to name the 1.8 V
    core pair and drop the implication that a 3.3 V core is a live
    alternative — but only once this record is ratified, since editing the
    target table is a spec change.

- **Revisit if**: the jitter characterization finds the 1.8 V starved cell
  cannot sustain a rail-to-rail oscillation at the slow/hot/low-supply
  corner at any workable stage count (which would make the
  `g5v0d10v5` alternative live again, at the cost of a level shifter), or if
  a future sky130 PDK release ships a matched 3.3 V core pair.
