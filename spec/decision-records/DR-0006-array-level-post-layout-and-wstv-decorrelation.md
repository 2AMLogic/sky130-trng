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
  `layout/ro_array_core/` gives a DRC-clean, LVS-matching, and
  `--check`-reproducible whole-array GDS to extract, and states what does
  and does not move as a
  result. It does not ratify DR-0001 through DR-0005, does not move any
  `design/README.md` target row, and does not change the array size, stage
  count, `wstv` ladder or operating point DR-0003 chose.

**Which records this record's numbers come from.** Every figure below is
measured against `layout/pex-array/ro_array_core_pex.spice` as extracted
from `layout/ro_array_core/ro_array_core.gds` -- the canonical,
`vss`-strapped array GDS -- i.e. the twelve `sim/post-layout-ro-array-core/`
records dated `20260907-0009xx`/`20260907-0010xx`. An earlier draft of this
record measured the same three decks against an extraction of the
placement PoC's `ro_array_core_signal9_poc.gds`, which has no `vss` straps
drawn and is superseded by the recipe promotion. Those thirteen
`20260906-*` records are **kept**, per this repo's append-only `sim/`
convention, and each new record names the one it supersedes in its own
`supersedes` field. The difference is not cosmetic (+25.0 fF of
capacitance to substrate) and it moved a finding -- see finding 2.

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

`layout/ro_array_core/` now gives a `klt drc`
clean (0 violations), `klt lvs` **matching** (132/132 devices, 96/96 nets,
two committed negative controls confirming discrimination),
`--check`-reproducible whole-array GDS
-- four non-identical rings, four output buffers, and the three-`xor2`
combining tree, with the ring-to-buffer signal chain, buffer-to-XOR fan-in,
XOR tree routing, the array-wide `vdd` bus and the array-wide `vss` strap
(`ring1..4`'s met2 rails plus `xa1..3`'s own taps) all really drawn.
`layout/pex-array/`
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

### 1. Real array-level parasitics cost 2.158x - 2.501x in ring period

`sim/post-layout-ro-array-core/testbench/tb_post_layout_ro_array_core.spice`
runs the post-layout array and an identical-topology pre-layout array in one
deck, at one corner, so the ratio is the parasitic contribution alone. Over
the full grid (four (temp, Vdd) points x `tt`/`ss`/`ff`, all four rings each
corner):

| Quantity | Pre-layout | Post-layout (array) | Post-layout (ring only, DR-0005) |
|---|---|---|---|
| Ring period, ratio to pre-layout | 1.000x | **2.158x - 2.501x** (mean 2.323x, n=48) | 1.378x - 1.479x |
| `wstv` ladder span (slowest/fastest) | 1.1234x - 1.2514x | **1.0843x - 1.1746x** | 1.1122x - 1.2096x |
| XOR-tree edge retention (N=4) | 0.5469 - 0.7236 | 0.6996 - 0.8208 | n/a (ring-only decks have no combining tree) |
| Combining-node bias (fraction of Vdd) | 0.3551 - 0.5371 | 0.4325 - 0.5542 | n/a |
| Array supply current, ratio to pre-layout | 1.000x | **0.911x - 1.039x** | n/a |

The array-level slowdown is substantially larger than the ring-only figure,
as expected: it now includes the ring-to-buffer signal routing, the
buffer-to-XOR fan-in, the XOR tree's own `t1`/`t2` routing, the
array-wide `vdd` bus for four buffers plus three `xor2` instances, and the
array-wide `vss` strap, none of
which DR-0005's ring-only extraction could include. It is not a clean
multiplicative composition of DR-0005's own two figures (1.378x-1.479x
intra-cell, 1.5045x-1.6546x more for one ring's own real interconnect,
whose product is 2.08x-2.45x) -- the array figure's range (2.158x-2.501x)
sits close to but not inside that product range, which is expected: the
array adds buffer and XOR-tree loading the single-ring campaigns never
carried at all, on top of the same per-ring effects.

The `wstv` ladder still discriminates (narrower than pre-layout, as every
prior post-layout campaign in this repo finds, but not collapsed).
Combining-node bias stays close to 0.5x Vdd in both cases (no new systematic
bias from the real routing; post-layout is, if anything, marginally *closer*
to 0.5x than pre-layout). Edge retention is, on this measurement,
*higher* post-layout than pre-layout at every grid point (0.6996-0.8208
against 0.5469-0.7236) --
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

Twelve grid points per deck (36 corner runs total), ring 1's own period as
the probe in every deck (comparable line for line):

    loading  = t(solo)  - t(tied)   = -0.353% to -0.192%
    coupling = t(float) - t(solo)   = +0.044% to +0.293%

Against DR-0005's ring-scope figures (loading -0.151% to -0.057%, coupling
-0.033% to +0.018%), both magnitudes are larger at array scale, plausibly
because the shared node now collects switching current from four rings
**plus four buffers plus three `xor2` gates**, all riding the same physical
substrate return -- more total capacitive activity landing on one node than
DR-0005's own ring-only extraction ever modelled.

**The new result here, and the one this record is least willing to
overstate: the coupling figure's sign is consistent across all twelve grid
points** (12 of 12 positive; `float` is slower than `solo` everywhere,
+0.044% at the mildest point and +0.293% at the hottest). That is the
signature DR-0005 named as what a *real* frequency pull would look like
("a real frequency pull would move every ring the same way") and did not
observe at ring scope -- nor did an earlier revision of this record, which
extracted the placement PoC's `signal9` GDS (no `vss` straps drawn) and
read a mixed-sign bracket of -0.081% to +0.230%. Re-extracting the
canonical, `vss`-strapped `layout/ro_array_core/ro_array_core.gds`
(+25.0 fF, +6.8%, of capacitance to substrate; see
`layout/pex-array/README.md`) is the only change between those two
readings, since these are deterministic transients with no injected noise.

**This record still does not call that a resolved coupling magnitude**, for
two reasons it states rather than argues around:

- The transient solver's own numerical period scatter has **not** been
  re-derived at array scale. DR-0005 cited 0.024% of `T_0`, measured on the
  ring-only deck in `sim/ro-ring-timestep-convergence/`. All twelve
  `coupling` points here exceed that ring-scale figure, and the sign
  consistency is itself hard to produce from symmetric numerical scatter --
  but whether 0.024% carries over unchanged to a deck with roughly 6x the
  node count is not established by this record, and is named as a follow-up
  below.
- The magnitude still depends on an unmodelled substrate resistance (see
  finding 3): `tied` and `float` bracket the *terminals* of that range, so
  a consistent sign tells us the direction of the effect at the
  infinite-impedance terminal, not its size at the real one.

What changed relative to the pre-`vss`-strap reading is therefore the
*sign consistency*, not the bound's width -- and the honest reading is that
the array's real substrate return now shows a directionally consistent
loading of ring 1 by its neighbours' switching, whose magnitude remains
bracketed rather than measured.

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

**Environment note, not a testbench defect**: during the earlier
(pre-`vss`-strap) pass, the first attempt at the
`solo` deck's coldest/highest-current corner point failed two of three
process corners (`ss`, `ff`) with the ngspice process killed outright
(`exited -15`, then `exited -9`) inside a few minutes, well under this
record's own 1800 s per-corner timeout — consistent with transient memory
contention from other concurrent jobs on the same host (unrelated `ngspice`
processes from other simulation work were observed running concurrently), not
a fault in the deck. An immediate retry of the identical command, with
nothing else changed, passed all three corners; the earlier partial-failure
record (`20260906-225010-6adba77`) was **not** deleted (this repo's `sim/`
evidence is append-only) and stands alongside the successful retry as the
record of what happened. The re-run against the canonical GDS passed all
twelve records / thirty-six corners on the first attempt.

### 3. DR-0003 §8 still stays open, and this record does not supersede it or DR-0005

§8's question is "the skew fraction that actually decorrelates two sky130
rings." Finding 2 above measures the same one coupling path DR-0005 finding
3 measured -- capacitive substrate return -- now on a real, physically-placed
layout rather than an approximated one, and finds a *wider* (not narrower)
bound than DR-0005's own ring-level study, this time with a consistent sign.
A consistent sign on **one** of three named mechanisms is not an answer to
§8's question, which asks for a decorrelating *skew fraction*, not for
whether one coupling path pulls in a reproducible direction. It still does
not measure the two paths §8 names as more likely to dominate:

- **Shared supply impedance**, §8's first-named mechanism. Still entirely
  unmodelled: `layout/README.md`'s own "Still open" list
  names `vddr1`-`vddr4`'s own per-ring supply distribution as undrawn (the
  one array-layout item the `layout/ro_array_core/` recipe does *not*
  contain), and
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
and the measured bound moved (wider, not narrower, and now consistent in
sign) without changing which mechanism the gap is actually about.

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
  - **`sampler_dff`/`sampler_core` as layout at all**, tracked in #27 —
    the only remaining hierarchy level with no physical implementation.
    (`layout/ro_array_core/` as a `--check`-reproducible `cell.json`
    recipe, with `ring1..4`/`xa1..3`'s own `vss` taps, is **done**; it is
    what this record extracts from.)
  - **A supply-distribution layout for `vddr1`-`vddr4`**, without which
    §8's first-named coupling mechanism cannot be measured at all, at any
    scale.
  - **Post-layout `sigma_1`**, before any re-sizing of `N` against either
    this record's or DR-0005's post-layout period.
  - **Re-derive the numerical period-scatter floor at array scale** before
    treating any single grid point's `coupling` figure as individually
    significant, rather than reading the twelve-point range as a bound (see
    "Alternatives considered" above). This is now the *load-bearing*
    follow-up for finding 2: the sign consistency (12 of 12) is the strongest
    claim this record makes, and confirming it against an array-scale
    scatter floor is what would turn it from a signature into a measurement.
  - **A follow-up deck correcting the `v(vsubs)` addressing** to capture
    the substrate node's own peak-to-peak swing at array scale, corroborating
    (or not) DR-0005's own ring-scale swing figures.
  - **klayout-tools#1503**, whose fix would replace this record's own
    tied/float bracket with a modelled substrate network, at any scale.
