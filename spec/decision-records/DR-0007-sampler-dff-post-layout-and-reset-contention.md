---
dr: DR-0007-sampler-dff-post-layout-and-reset-contention
title: post-layout characterization of the sky130 sampler_dff, and DR-0014's reset-contention methodology re-derived for this topology
status: Proposed
date: 2026-09-07
deciders: unratified — Proposed by the Builder on #22; ratification is an operator/Champion action
supersedes: n/a — this record supersedes nothing. It discharges two items other records left explicitly open: DR-0003's "Follow-up required" entry "**Sampler_dff characterization** ... (unsimulated)", and the DR-0014 (gf180-trng) reset-window contention **methodology** that spec/porting-plan.md marks as transferring to sky130 while its numbers and polarity argument do not.
superseded_by: n/a
related: "#22 (this record), DR-0003 § 'Follow-up required' (the named open item this record measures), DR-0005 and DR-0006 (the two prior post-layout campaigns, both on the entropy-source side of the raw tap; DR-0005's 1.378x-1.479x intra-cell ring finding is the cross-check for finding 1), gf180-trng DR-0014 via spec/porting-plan.md (the reset-contention methodology transferred here), gf180-trng DR-0011 via spec/porting-plan.md (why finding 3 is a deterministic timing bracket and not a metastability claim), sim/README.md's 'Sampler post-layout' section (the full eight-record reduction), layout/pex/README.md's 'The sampler library' section (what this record's parasitic model contains), PR #87 (the sampler_nand2 pin-swap fix; with it merged, the unrouted m/mb pair is the whole of why the assembled sampler_dff GDS is not the extraction source)"
---

# DR-0007: post-layout `sampler_dff`, and DR-0014's reset-contention methodology re-derived

## Status

- 2026-09-07: **Proposed.** Not accepted by anyone. This record reports the
  first simulation of `sampler_dff` in this repository, pre- or
  post-layout. It does not ratify DR-0001 through DR-0006, does not change
  the array size, stage count, `wstv` ladder, raw rate or operating point
  DR-0003 chose, and does not move any `design/README.md` row other than
  adding the sampler row this campaign creates.

## Context

Three things were true before this record:

1. **The digitizer had never been simulated.** `design/README.md`'s
   target-specification table has rings, combining tree, array power and
   array area rows and no sampler row at all. DR-0003's own "Follow-up
   required" list says so in as many words — "**Sampler_dff
   characterization** for the now six-instance-per-block liveness/raw-tap
   digitizer fan-out (unsimulated, per `design/xschem/trng_top.sch`'s own
   text block)". `sim/raw-bit-min-entropy/` drives a bitstream *through*
   this cell, but measures the bitstream.
2. **Every post-layout record was on the far side of the raw tap.** DR-0005
   (leaf-cell intra-cell parasitics) and DR-0006 (whole-array extraction)
   are both entropy-source records. Issue #22's second acceptance criterion
   — post-layout PVT simulation over extracted parasitics — was
   substantially met for `ro_array_core` and not at all for
   `sampler_core`/`sampler_dff`.
3. **`spec/porting-plan.md` had an explicit, undischarged re-derivation.**
   gf180-trng's DR-0014 (Accepted, delegated) chose to gate `sampler_dff`'s
   asynchronous reset into the storage loops' own inverters — the master's
   *forward* inverter and the slave's *feedback* inverter as NAND2s —
   rather than hang pull devices on the storage nodes, on the strength of a
   measured reset-window contention current (967 µW → 66 nW at nominal, a
   ~14,600x reduction). The porting plan is explicit about what crosses:

   > The **methodology** — measure reset-window contention current
   > explicitly, per the specific storage-loop topology chosen, before
   > assuming a brute-force reset is "free" — transfers; the **specific
   > gating arrangement and its polarity argument does not**, because it is
   > a property of gf180mcu's `sampler_dff` transmission-gate/latch circuit
   > as drawn, and sky130's sampler cell ... has its own topology to
   > re-derive this against.

   Nobody had run that measurement here.

## What was measured

`sim/post-layout-sampler-dff/`, two decks, the four (temp, Vdd) points every
post-layout campaign in this repo uses, `tt`/`ss`/`ff` bundled into each —
**eight records, twenty-four corner runs, all PASS**:

| Deck | Question |
|---|---|
| `tb_post_layout_sampler_dff.spice` | after the clock edge: clk→q delay both directions, captured output levels, reset-window / idle / active supply current |
| `tb_post_layout_sampler_setup.spice` | before it: a twelve-rung d-to-clk offset ladder (3200…45 ps) on twelve post-layout and twelve pre-layout instances at once, bracketing setup time per side per corner |

Both decks run the post-layout cell and the pre-layout cell **in the same
transient, on the same stimulus sources**, for the reason
`sim/post-layout-ro-ring5/` established: the quantity of interest is a
ratio, and a ratio taken across two runs inherits every difference between
them.

**Extraction scope, which bounds every number below.** The post-layout side
is `layout/pex/sampler_dff_pex.spice` — `klt extract --parasitics` over the
three composed leaf cells `layout/sampler_dff/` places (`layout/ro_buf/`,
`layout/sampler_tg/`, `layout/sampler_nand2/`; each `klt drc` clean at 0
violations and `klt lvs` matching its own reference) — rebuilt into
`sampler_dff` per `design/sampler_core.spice` device for device, with
**ideal inter-cell wires**. This is DR-0005's scope on a different cell
family, not DR-0006's. `layout/sampler_dff/`'s own assembly GDS is
DRC-clean but its `m`/`mb` data-path nets are unrouted and its `klt lvs`
therefore does not match (15/22 devices, 7/14 nets as of PR #87's
`sampler_nand2` pin-swap fix, which closed the other half of the gap), so
extracting it flat today would extract an incomplete circuit. Stimulus is ideal PWL with 100 ps edges, identical on
both sides, so the post-layout cell's larger input capacitance never slows
its own input edges. **Every post-layout figure here is a floor on the real
cost.**

## Findings

### 1. Intra-cell parasitics cost 1.314x - 1.418x in clk→q delay

Mean 1.362x over 24 paired rise/fall points; post-layout capture delay is
103.6 - 299.0 ps across the grid, worst at `ss` / −40 °C / 1.62 V.

That range sits **inside DR-0005's own intra-cell finding of 1.378x -
1.479x** for the ring, measured with the same extraction scope on a
different cell family. Two independent measurements of "what intra-cell
parasitics cost in this PDK at this scope" now agree on the size of the
penalty. It also sets the expectation for what a future whole-GDS sampler
extraction should find: DR-0006 measured 2.158x - 2.501x once real
inter-cell routing was included at array scale, i.e. roughly another 1.5x -
1.7x on top of intra-cell alone.

Against DR-0003's ratified 20 µs sample period, 299 ps is **≤ 15 ppm of
`T_s`**. Capture delay does not constrain the raw rate at any corner.

### 2. The reset window carries no contention current on this topology

Measured with `rst_n` asserted **while `d` drives the opposite value through
the transparent master** — the condition under which the pull-device reset
DR-0014 rejected would be fighting the `d` driver.

Reset-window supply current is **19.3 pA** (`ss` / −40 °C / 1.62 V) to
**293 nA** (`ff` / 125 °C / 1.98 V): **0.90 nW at nominal** (`tt` / 27 °C /
1.8 V) and **580 nW at the hottest, fastest grid point**. Three independent
readings say that is leakage and nothing else:

- It **tracks temperature and corner the way leakage does** — three and a
  half orders of magnitude across a grid over which the same cell's
  *switching* figures move by less than 2x.
- It is **at or below the same cell's own idle current** at every one of the
  12 grid points (ratio 0.501 - 1.014). A reset fighting a driver cannot be
  *below* the quiescent current of the same cell in the same run. The
  recurring ~0.50 ratio is the mechanism showing through: with `rst_n` low
  the NAND2s' series NMOS stacks are cut off, so a leakage path present at
  idle is absent during reset.
- It is **the same number pre-layout and post-layout**, agreeing to between
  5 significant figures (+5.0e−06) and 3 (+1.8e−03) across the whole grid.
  Parasitic R and C can only change *dynamic* current; a window whose
  current is invariant to them is carrying no switching current to change.

**What this licenses.** The methodology DR-0014 asked to be transferred has
been run, on this repo's own drawn topology, over the full PVT grid, and it
finds the reset window costs nothing above leakage. The gating arrangement
`design/sampler_core.spice` draws (NAND2 on the master's forward inverter,
`XMimpa`/`XMimpb`/`XMimna`/`XMimnb`; NAND2 on the slave's feedback inverter,
`XMis2pa`/`XMis2pb`/`XMis2na`/`XMis2nb`) is confirmed contention-free for
sky130 by measurement rather than by inheritance.

**What this does not license.** The brute-force pull-device alternative was
**not** simulated, so no reduction *ratio* against it is claimed and
gf180-trng's 967 µW → 66 nW pair is neither transplanted nor compared
against. This record says "the chosen topology's reset window is
leakage-limited on sky130", not "gating beats pull devices by X on sky130".
Establishing the latter needs a second, deliberately-wrong netlist as a
control, and is left as follow-up. Nor does it re-open DR-0014's polarity
argument (gating the feedback rather than the forward inverter defeats reset
in one clock phase): the drawn topology already follows the accepted
arrangement, and this record measures it rather than re-deriving why.

### 3. Setup time is 60 - 150 ps post-layout, and the digitizer is not the bottleneck

Post-layout setup brackets run from (60, 73] ps (`ff`, at both 1.98 V
points) to (125, 150] ps (`ss` / −40 °C / 1.62 V); pre-layout, (45, 60] ps
to (88, 105] ps. Parasitics cost exactly one ladder rung (~1.2x) at 10 of
the 12 grid points and two (~1.44x) at the other two — the same direction
and roughly the same size as finding 1.

**The worst case coincides with the entropy-binding corner** DR-0002 and
DR-0003 identified (`ss` / −40 °C / 1.62 V), which is convenient rather than
surprising: both are gated by the same slow devices.

**Compared against the combining gate**, whose minimum resolvable pulse
width `w_90` is 122 - 241 ps (`sim/xor-combining-bandwidth/`, the figure
DR-0003 §1 uses to bound `N`), the comparison that bears on `N_max_combine`
is *per corner*, against that corner's own `w_90` — not against the bottom
of the range. `sim/xor-combining-bandwidth/` covers −40 °C/1.62 V,
27 °C/1.80 V and −40 °C/1.98 V, so nine of this campaign's twelve grid
points have a `w_90` to be compared against; the three 125 °C/1.98 V points
do not, and are outside this comparison:

| PVT / corner | setup, post-layout | `w_90` (DR-0003 §1) |
|---|---|---|
| −40 °C / 1.62 V `tt` | (105, 125] ps | 190.9 ps |
| −40 °C / 1.62 V `ss` | (125, 150] ps | 241.3 ps |
| −40 °C / 1.62 V `ff` | (88, 105] ps | 166.0 ps |
| 27 °C / 1.80 V `tt` | (73, 88] ps | 163.4 ps |
| 27 °C / 1.80 V `ss` | (88, 105] ps | 186.3 ps |
| 27 °C / 1.80 V `ff` | (73, 88] ps | 133.2 ps |
| −40 °C / 1.98 V `tt` | (73, 88] ps | 134.0 ps |
| −40 °C / 1.98 V `ss` | (88, 105] ps | 163.9 ps |
| −40 °C / 1.98 V `ff` (`N_max_combine` binds) | (60, 73] ps | 122.0 ps |
| 125 °C / 1.98 V (×3) | (73, 88] / (73, 88] / (60, 73] ps | not measured |

At **all nine** overlapping points the setup bracket lies entirely below
that corner's own `w_90` — including (60, 73] ps against 122.0 ps at `ff` /
−40 °C / 1.98 V, the corner where `N_max_combine` binds. A pulse narrow
enough to trouble the sampler has already been swallowed by the XOR tree.
**DR-0003 §1's `N_max_combine` bound therefore stands unchanged**: the
digitizer does not add a tighter one.

**This is not a metastability result.** Per gf180-trng's DR-0011, carried
into `spec/porting-plan.md`, full resolution-time statistics are judged not
credibly reproducible in a general-purpose transient solver, and that
judgment is tool-general rather than PDK-specific. The brackets above are
deterministic captured/not-captured results at stated offsets. Every one of
the 24 rungs × 12 corner runs read back a clean rail (largest non-rail
reading anywhere: 2.0e−04 × Vdd), so no rung even landed close enough to the
boundary to invite the question.

### 4. The post-layout cell is functionally correct

Captured levels are ≥ 0.9983 × Vdd high and ≤ 0.0023 × Vdd low at every grid
point; `q` does not move when `d` changes with the slave opaque; asserted
reset holds `q` ≤ 0.38 mV while `d` drives the opposite value. This is worth
stating as a finding rather than assuming: the post-layout netlist is
`design/sampler_core.spice`'s topology rebuilt out of *separately extracted
physical cells*, and a wrong port assignment in that rebuild would show up
here first.

Active-window average current (55 ns containing both capture edges) is
1.063 - 1.980 µA post-layout, 1.306x - 1.548x the pre-layout figure — the
one place the parasitics cost real current, as extra capacitance charged and
discharged.

## Consequences

- `design/README.md` gains a **measured** sampler row for the first time
  (capture delay, setup, reset/idle current), citing this campaign.
- DR-0003's "Sampler_dff characterization" follow-up item is **discharged at
  the leaf-cell post-layout scope**, not at whole-block scope: the six
  `sampler_dff` instances `sampler_core` wires (raw tap, liveness, four ring
  taps) are still not simulated together, and `sampler_core` has no layout.
- `spec/porting-plan.md`'s DR-0014 methodology transfer is **discharged for
  the chosen topology** and left open for the brute-force control (see
  finding 2).
- Nothing in DR-0003's operating point moves. `N`, the stage count, the
  `wstv` ladder, `T_s` = 20 µs and the 50 kbps raw rate are all untouched;
  finding 3 confirms the combining gate remains the binding bandwidth
  constraint.

## Follow-up required

- **Whole-cell extraction.** Once `layout/sampler_dff/`'s `m`/`mb` nets are
  routed and its `klt lvs` matches, extract that GDS flat
  — the sampler's equivalent of `layout/pex-ring/` — and re-run both decks.
  Findings 1 and 3 will move; DR-0006's array-scale result suggests roughly
  another 1.5x - 1.7x on top of intra-cell alone.
- **`sampler_core` scope.** Six `sampler_dff` instances on one shared
  `vdd`/`clk`/`rst_n`, driven from the array's own combining node rather
  than an ideal PWL source. That is where clock-distribution skew and the
  real (not ideal) input edge rate first enter, and where a whole-chain
  raw-tap-to-sampled-bit post-layout claim becomes possible at all.
- **The brute-force reset control** for finding 2, if a ratio against the
  rejected alternative is ever wanted as sky130 evidence rather than as
  gf180mcu's.
- **Re-run finding 3 with a realistic input edge**, not ideal PWL. Setup
  time is defined against the input's own slew; an ideal 100 ps edge is
  optimistic, and the combining node's real post-layout edge (DR-0006
  measured 0.700 - 0.821 edge retention at N = 4) is slower.
