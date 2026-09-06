---
dr: DR-0006-array-level-post-layout-and-wstv-decorrelation
title: whole-array post-layout parasitics on the sky130 entropy source, and DR-0005's follow-up items re-run at array scale
status: Proposed
date: 2026-09-06
deciders: unratified — Proposed by the Builder on #22; ratification is an operator/Champion action
supersedes: n/a — this record does NOT supersede DR-0003 §8 or DR-0005. It re-runs DR-0005's own named follow-up items ("Findings 1 and 3 should be re-run against the assembled block when it exists") now that the assembled array exists, and finds that DR-0003 §8's own statement of the gap still stands for the mechanism that matters most.
superseded_by: n/a
related: "#22 (this record), DR-0003 §8 (the inter-ring decorrelation gap this record re-measures against), DR-0005 (the prior post-layout campaign this record extends from ring scope to array scope), layout/pex-array/README.md (what this record's parasitic model contains), sim/README.md's 'Array-level post-layout' section (the full twelve-plus-twelve-plus-twelve-record reduction), klayout-tools#1503 (the substrate-node scoping defect that bounds what this record can say)"
---

# DR-0006: whole-array post-layout parasitics, and DR-0005's follow-up items re-run at array scale

## Status

- 2026-09-06: **Proposed.** Not accepted by anyone. This record re-runs
  DR-0005's own two open follow-up items ("Findings 1 and 3 should be
  re-run against the assembled block when it exists") now that
  `layout/ro_array_core-placement-poc/` gives a DRC-clean, LVS-matching
  whole-array GDS to extract, and states what does and does not move as a
  result. It does not ratify DR-0001 through DR-0005, does not move any
  `design/README.md` target row, and does not change the array size, stage
  count, `wstv` ladder or operating point DR-0003 chose.

## Context

DR-0005 measured intra-cell parasitics on nine separately-composed leaf
cells (finding 1: 1.378x-1.479x ring period penalty) and bracketed
inter-ring substrate coupling on those same nine leaf cells, hand-tied to a
shared `vsubs` node as if placed at infinite separation (finding 3: coupling
bounded at <= 0.033% of ring period, not resolved above the transient
solver's own numerical floor). Its own "Follow-up required" section named
exactly what this record does:

> **Inter-cell interconnect**: `xor2` routing, `ro_ring5` assembly,
> `ro_array_core` assembly, `sampler_dff`/`sampler_core` — tracked in
> 2AMLogic/sky130-trng#27. Findings 1 and 3 should be re-run against the
> assembled block when it exists; both will move.

`layout/ro_array_core-placement-poc/`'s "Increment 8" now gives a `klt drc`
clean (0 violations), `klt lvs` **matching** (132/132 devices, 96/96 nets,
two committed negative controls confirming discrimination) whole-array GDS
-- four non-identical rings, four output buffers, and the three-`xor2`
combining tree, with the ring-to-buffer signal chain, buffer-to-XOR fan-in,
XOR tree routing and array-wide `vdd` bus all really drawn. `layout/pex-array/`
extracts that GDS flat with `klt extract --parasitics`, and
`sim/post-layout-ro-array-core/` runs three decks from it across the same
four-(temp, Vdd)-point, `tt`/`ss`/`ff` grid every prior post-layout campaign
in this repo uses: a same-deck post-vs-pre-layout comparison (the array-scale
sibling of DR-0005 finding 1), and a tied/float/solo three-way substrate
bracket (the array-scale sibling of finding 3) -- the first time that bracket
has been run on a **real, physically-placed** layout rather than leaf cells
hand-tied to a shared node at assumed infinite separation.

## Decision

**We record the following findings as the current, provisional array-level
post-layout position, and we do NOT close DR-0003 §8.**

### 1. Real array-level parasitics cost 2.158x - 2.490x in ring period

`sim/post-layout-ro-array-core/testbench/tb_post_layout_ro_array_core.spice`
runs the post-layout array and an identical-topology pre-layout array in one
deck, at one corner, so the ratio is the parasitic contribution alone. Over
the full grid (four (temp, Vdd) points x `tt`/`ss`/`ff`, all four rings each
corner):

| Quantity | Pre-layout | Post-layout (array) | Post-layout (ring only, DR-0005) |
|---|---|---|---|
| Ring period, ratio to pre-layout | 1.000x | **2.158x - 2.490x** | 1.378x - 1.479x |
| `wstv` ladder span (slowest/fastest) | 1.1234x - 1.2514x | **1.0890x - 1.1796x** | 1.1122x - 1.2096x |
| XOR-tree edge retention (N=4) | 0.5469 - 0.7236 | 0.6093 - 0.7977 | n/a (ring-only decks have no combining tree) |
| Combining-node bias (fraction of Vdd) | 0.3551 - 0.5370 | 0.3809 - 0.5212 | n/a |
| Array supply current, ratio to pre-layout | 1.000x | **0.911x - 1.033x** | n/a |

The array-level slowdown is substantially larger than the ring-only figure,
as expected: it now includes the ring-to-buffer signal routing, the
buffer-to-XOR fan-in, the XOR tree's own `t1`/`t2` routing, and the
array-wide `vdd` bus for four buffers plus three `xor2` instances, none of
which DR-0005's ring-only extraction could include. It is not a clean
multiplicative composition of DR-0005's own two figures (1.378x-1.479x
intra-cell, 1.5045x-1.6546x more for one ring's own real interconnect,
whose product is 2.08x-2.45x) -- the array figure's range (2.158x-2.490x)
sits close to but not inside that product range, which is expected: the
array adds buffer and XOR-tree loading the single-ring campaigns never
carried at all, on top of the same per-ring effects.

The `wstv` ladder still discriminates (narrower than pre-layout, as every
prior post-layout campaign in this repo finds, but not collapsed).
Combining-node bias stays close to 0.5x Vdd in both cases (no new systematic
bias from the real routing). Edge retention is, on this measurement,
somewhat *higher* post-layout than pre-layout at most grid points --
plausibly because the real parasitics slow every ring's edges enough to
shift the beat pattern between them, changing which near-coincident edge
pairs get swallowed by the combining tree -- but this record does not derive
a mechanism for that shift; it is reported as measured, not explained.
Per DR-0005's own precedent, this penalty is **not** propagated into a
re-sized `N`: `sigma_1` has not been re-measured post-layout at any scale,
and re-deriving `N` from a period that could move again once
`sampler_dff`/`sampler_core` land would be false precision.

### 2. The tied/float/solo substrate bracket, now on a real physically-placed layout

DR-0005 finding 3 bracketed inter-ring substrate coupling on nine leaf cells
sharing a `vsubs` node only because the testbench declared it shared -- its
own "Proximity" limitation named this directly: "these are nine leaf cells
simulated as if placed at infinite separation... floorplan facts that do not
exist yet." `layout/pex-array/`'s single flat extraction of the real
composed array closes that specific limitation: the four rings' real
physical placement, well spacing and shared psub geometry are exactly as
drawn, not hand-approximated.

Same three-deck bracket as DR-0005, now over the array:

- **TIED** (`sim/post-layout-ro-array-core/testbench/tb_post_layout_ro_array_core.spice`,
  finding 1's own deck): `vsubs` hard to 0. Already run above.
- **FLOAT** (`tb_post_layout_ro_array_core_substrate_float.spice`): `vsubs`
  on the extractor's own 1 TOhm dc tie, all four rings running.
- **SOLO** (`tb_post_layout_ro_array_core_substrate_float_solo.spice`):
  `vsubs` floating, rings 2-4 present but held disabled the whole run (a
  defined, non-switching state per `ro_nand2`'s own disable behaviour, not a
  floating one) -- separates the floating node's own capacitive *loading*
  from actual inter-ring *coupling*, the same decomposition DR-0005's own
  solo deck used.

Twelve records per deck (36 total), ring 1's own period as the probe in
every deck (comparable line for line):

    loading  = t(solo)  - t(tied)   = -0.379% to -0.247%
    coupling = t(float) - t(solo)   = -0.081% to +0.230%

Against DR-0005's ring-scope figures (loading -0.151% to -0.057%, coupling
-0.033% to +0.018%), both magnitudes are larger at array scale, plausibly
because the shared node now collects switching current from four rings
**plus four buffers plus three `xor2` gates**, all riding the same physical
substrate return -- more total capacitive activity landing on one node than
DR-0005's own ring-only extraction ever modelled. **The coupling figure's
sign is still not consistent across the twelve grid points** (7 of 12
positive, 5 of 12 negative), which is the same signature DR-0005 read as "a
real frequency pull would move every ring the same way" -- so this is still
not a resolved directional coupling, only a wider bound than DR-0005's own.
This record does not re-derive the transient solver's own numerical period
scatter at array scale (DR-0005 cited 0.024% of `T_0`, measured on the
ring-only deck in `sim/ro-ring-timestep-convergence/`); several of the
twelve `coupling` points here (up to 0.230%) clear that ring-scale floor by
a wider margin than DR-0005's own single point did, but confirming that
floor's value carries over unchanged to a deck with roughly 6x the node
count is not established by this record and is named as a follow-up below.

**A testbench defect, caught and documented rather than silently fixed**:
the first run of the float/solo decks referenced the shared substrate node
as `v(xarr.vsubs)` (hierarchical, one level down through the array
instance). Because `vsubs` is `.global`-declared in
`layout/pex-array/ro_array_core_pex.spice` (klayout-tools#1503's own
workaround), it is the *same* node everywhere in the deck and is addressed
as `v(vsubs)` directly, with no instance prefix -- the hierarchical
reference silently resolved to nothing (`no such vector`), so the node's own
peak-to-peak swing (the corroborating figure DR-0005's own write-up reports:
"3.8% of Vdd peak to peak with four rings running, 1.1% with one") was not
captured this round. The period-based bracket above is unaffected: `p_tr1`
through `p_tr4` and `p_skew_span` all resolved correctly in the same runs,
since they reference the array's own exposed ports (`v(pro1)` etc.), not the
internal global node. Not filed against `klayout-tools`: `.global` net
addressing is standard ngspice behaviour, not a tool defect, and this is
recorded here as a testbench-authoring note for whoever writes the follow-up
deck that re-measures the swing.

**Environment note, not a testbench defect**: the first attempt at the
`solo` deck's coldest/highest-current corner point failed two of three
process corners (`ss`, `ff`) with the ngspice process killed outright
(`exited -15`, then `exited -9`) inside a few minutes, well under this
record's own 1800 s per-corner timeout — consistent with transient memory
contention from other concurrent jobs on the same host (unrelated `ngspice`
processes from other simulation work were observed running concurrently), not
a fault in the deck. An immediate retry of the identical command, with
nothing else changed, passed all three corners; the earlier partial-failure
record was **not** deleted (this repo's `sim/` evidence is append-only) and
stands alongside the successful retry as the record of what happened.

### 3. DR-0003 §8 still stays open, and this record does not supersede it or DR-0005

§8's question is "the skew fraction that actually decorrelates two sky130
rings." Finding 2 above measures the same one coupling path DR-0005 finding
3 measured -- capacitive substrate return -- now on a real, physically-placed
layout rather than an approximated one, and finds a *wider* (not narrower)
bound than DR-0005's own ring-level study. It still does not measure the two
paths §8 names as more likely to dominate:

- **Shared supply impedance**, §8's first-named mechanism. Still entirely
  unmodelled: `layout/ro_array_core-placement-poc/`'s own "Still open" list
  names `vddr1`-`vddr4`'s own per-ring supply distribution as undrawn, and
  this record's own testbenches keep all four `vddr` sources ideal and
  independent, matching the design's own intentional per-ring supply
  independence (`design/README.md`'s pin table). There is no layout fact
  this record could measure this mechanism against.
- **Substrate resistance.** Same limitation as DR-0005: the extractor emits
  none, so the tied/float pair still brackets the *terminals* of a range
  whose interior is unmodelled.

Per this repo's decision-record convention, a correction supersedes rather
than edits in place. **There is no correction to make to DR-0003 §8 or to
DR-0005**: both records' own statements of the gap remain accurate. What
this record adds is that the gap has now been re-measured on a real,
physically-placed whole-array layout rather than an approximation of one,
and the measured bound moved (wider, not narrower) without changing which
mechanism the gap is actually about.

## Alternatives considered

### Close DR-0003 §8 on finding 2

Rejected, for the same reason DR-0005 rejected it: the measurement covers
one of three named coupling mechanisms, at one of two bounding values of an
unmodelled impedance, and the first-named mechanism (shared supply
impedance) still has no layout to be measured on at all.

### Re-derive the numerical period-scatter floor at array scale before reporting the coupling bracket

Rejected for this record, though named as a real gap above. Re-running
`sim/ro-ring-timestep-convergence/`'s own no-injected-noise methodology
against the array-level deck is straightforward with the infrastructure this
record already built, but doing it here would have delayed landing the
primary post-layout PVT evidence issue #22's acceptance bar asks for.
Tracked as follow-up.

### Attempt the array-level supply-distribution layout in this same increment

Rejected as out of scope for this record. A real `vddr1`-`vddr4` distribution
layout is itself substantial floorplan/routing work (and would change
whether the design's own intentional per-ring independence, `design/README.md`'s
pin table, is preserved or deliberately altered) -- a separate, independently
schedulable increment, not a corollary of running the extraction-and-simulate
chain against the array GDS that already exists.

## Consequences

- **`layout/pex-array/ro_array_core_pex.spice` becomes a citable netlist**,
  on the same `--check`-guarded footing as `layout/pex/` and
  `layout/pex-ring/`'s own libraries: regenerable from committed GDS,
  byte-diffable, with a per-record sha256 in every `sim/` record's
  `netlists` block.
- **`design/README.md`'s `wstv` decorrelation row must keep saying
  decorrelation is unmeasured.** This record's finding 2 is about one
  coupling path at array scale, not the decorrelating skew fraction §8 asks
  for.
- **Any future array-level post-layout period claim must state which
  substrate tie it used**, same discipline DR-0005 established at ring
  scope.
- **Known limitations, stated as limitations:**
  - Buffer and XOR-tree loading is now included for the first time, but
    `sampler_dff`/`sampler_core` still have no layout at all -- this is not
    a whole-chain (raw tap to sampled bit) post-layout measurement.
  - The substrate node's own peak-to-peak swing was not captured this round
    (see the testbench-defect note above) -- only the period-based bracket.
  - The transient solver's own numerical period-scatter floor is cited from
    DR-0005's ring-scale measurement, not re-derived at array scale.
  - Deterministic transients, no injected device noise -- this record says
    nothing about `sigma_1`, jitter or entropy post-layout at any scale.
  - "DRC-clean" and "LVS-matching" throughout mean clean/matching against
    `klt`'s **curated** sky130 deck, not a sign-off deck (same caveat every
    prior `layout/` record in this repo carries).

- **Follow-up required:**
  - **Ratification** of this record, and of DR-0001 through DR-0005 -- an
    operator/Champion action, not performed here.
  - **`layout/ro_array_core/` as a `--check`-reproducible `cell.json`
    recipe** (folding the PoC's nine `gen-compose` stages into one, per
    `layout/README.md`'s own "Still open" note), and `sampler_dff`/
    `sampler_core`, both tracked in #27.
  - **A supply-distribution layout for `vddr1`-`vddr4`**, without which
    §8's first-named coupling mechanism cannot be measured at all, at any
    scale.
  - **Post-layout `sigma_1`**, before any re-sizing of `N` against either
    this record's or DR-0005's post-layout period.
  - **Re-derive the numerical period-scatter floor at array scale** before
    treating any single grid point's `coupling` figure as individually
    significant, rather than reading the twelve-point range as a bound (see
    "Alternatives considered" above).
  - **A follow-up deck correcting the `v(vsubs)` addressing** to capture
    the substrate node's own peak-to-peak swing at array scale, corroborating
    (or not) DR-0005's own ring-scale swing figures.
  - **klayout-tools#1503**, whose fix would replace this record's own
    tied/float bracket with a modelled substrate network, at any scale.
