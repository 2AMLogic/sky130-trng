---
dr: DR-0005-post-layout-parasitics-and-wstv-decorrelation
title: what extracted parasitics cost the sky130 ring, and how far that closes DR-0003 §8's inter-ring decorrelation gap
status: Proposed
date: 2026-09-06
deciders: unratified — Proposed by the Builder on #22; ratification is an operator/Champion action
supersedes: n/a — this record does NOT supersede DR-0003 §8. It reports the first measurement §8 said it was waiting for, and finds that §8's own statement of the gap still stands for the part that matters most.
superseded_by: n/a
related: "#22 (this record), DR-0003 §8 (the inter-ring decorrelation gap this record measures against, and its measured wstv ladder), DR-0002 (the jitter/sizing campaign whose T_0 this record's periods should be read against), layout/pex/README.md (what the parasitic model contains), sim/post-layout-ro-ring5/ and sim/post-layout-parasitic-impact/ (the twelve records and the reduction), klayout-tools#1503 (the substrate-node scoping defect that bounds what this record can say)"
---

# DR-0005: post-layout parasitics on the sky130 ring, and the state of DR-0003 §8's `wstv` decorrelation gap

## Status

- 2026-09-06: **Proposed.** Not accepted by anyone. This record states what
  `klt extract --parasitics` over this repo's composed layout cells does to
  the ring's measured behaviour, and re-evaluates DR-0003 §8's explicitly
  unmeasured inter-ring decorrelation question now that a layout-derived
  netlist exists. It does not ratify DR-0001, DR-0002 or DR-0003, does not
  move any `design/README.md` target row, and does not change the array
  size, stage count, `wstv` ladder or operating point DR-0003 chose.

## Context

DR-0003 §8 recorded a gap and named its precondition precisely:

> **What is still NOT measured, and is explicitly re-flagged rather than
> quietly carried forward: the skew fraction that actually DECORRELATES two
> sky130 rings.** The array as drawn has no shared supply impedance and no
> substrate model, so a netlist-level correlation measurement over it can
> only confirm the absence of a coupling path the netlist does not contain
> — it cannot measure the coupling a real layout would have. That
> measurement needs extracted parasitics and stays out of scope until
> layout exists.

Layout now partly exists. `layout/` holds nine composed cells — `ro_buf`,
plus `ro_stage` and `ro_nand2` at each of the four ring `wstv` widths —
every one `klt drc` clean (0 violations) and `klt lvs` matching its own
`.subckt` in `design/ro_array_core.spice`, and all nine re-verified against
their committed evidence in the same session that produced this record.
`layout/bin/pex-netlist.py` turns them into a simulatable post-layout
library, and `sim/post-layout-ro-ring5/` runs the five-stage ring from it
across the PVT grid.

**What that does and does not license is the whole substance of this
record**, so it is stated before any number: these are *intra-cell*
parasitics. `layout/` contains no inter-cell interconnect — `ro_ring5`'s
stage-to-stage wires, the ring-to-buffer wires, and every supply
distribution wire between cells are still unbuilt (`xor2` routing and the
hierarchical assembly are open; see `layout/README.md` § "What's deferred").
A ring built from this library has real parasitics *inside* each gate and
ideal wires *between* them.

## Decision

**We record the following four findings as the current, provisional
post-layout position, and we do NOT close DR-0003 §8.**

### 1. Intra-cell parasitics cost 1.38x - 1.48x in ring period

`sim/post-layout-ro-ring5/testbench/tb_post_layout_ro_ring5.spice` runs the
post-layout ring and the pre-layout ring in **one deck**, at one corner,
with one measurement code path, so the ratio between them is the parasitic
contribution and nothing else. Over the whole grid (four (temp, Vdd) points
x `tt`/`ss`/`ff` x four `wstv` widths):

| Quantity | Pre-layout | Post-layout |
|---|---|---|
| Ring period, ratio to pre-layout | 1.000x | **1.378x - 1.479x** |
| Ring-node swing | 0.782 - 0.955 x Vdd | 0.815 - 0.964 x Vdd |
| Buffered output swing | 0.999 - 1.033 x Vdd | 0.999 - 1.021 x Vdd |
| Per-ring supply current, ratio | 1.000x | 0.938x - 0.979x |

The slowdown is dominated by resistance, not capacitance: each cell carries
1.7-2.0 kOhm of extracted series resistance against 4.7-6.3 fF of
capacitance, because every intra-gate net in these cells is routed on
sky130's `li1` local interconnect (`layout/README.md` § "Floorplan decisions
made so far"). Swing *rises* slightly post-layout, which is the expected
consequence of a slower ring having longer to reach its rails, and supply
current falls with the same slowdown.

**A ~1.4x period penalty is large enough to matter to DR-0002's sizing law**
(`Q_ring` goes as `sigma_1^2 / T_0^3`), and this record deliberately does
**not** propagate it into a re-sized `N`. Two reasons: the penalty is
measured on a partial layout (below), and `sigma_1` has not been re-measured
post-layout at all. Re-deriving `N` from a period that will move again when
inter-cell routing lands would be a false precision.

### 2. The `wstv` frequency ladder survives the parasitics

DR-0003 §8's stated criterion for the ladder is that the realized ring
periods stay clear of the small rationals (2/1, 3/2, 4/3) that mutually
injection-lock. Re-measured post-layout, with every ring buffered as
`ro_array_core.sch` wires them:

- **Post-layout ladder span (slowest/fastest ring): 1.1122x - 1.2096x**,
  against 1.1225x - 1.2464x for the same rings pre-layout in the same deck.
  The ladder narrows by 1-3%; it does not collapse.
- The closest approach of **any** ring pair to **any** locking rational,
  anywhere on the grid, is **9.3%** (at 125 degC / 1.98 V / `ss`, where
  `wstv` 0.42/0.48 reaches 1.2096 against 4/3).

So the parasitics do not threaten the ladder DR-0003 chose. Note this span
is measured on four separately-supplied rings, which is the same
independence condition DR-0003's own `skew_span` (1.12-1.19x on the
assembled array) was measured under.

### 3. Inter-ring coupling through the shared substrate: bounded at <= 0.033% of the ring period, and NOT resolved

This is the part DR-0003 §8 was actually about, and it is the part that has
to be read carefully.

Extracted parasitics do give four independently-supplied rings exactly one
shared node: the substrate return node every net-to-substrate capacitance
lands on. The extractor models no substrate resistance and no
tap-to-substrate contact resistance at all, and scopes the node per instance
in a way that cannot be used as-is (klayout-tools#1503), so the honest
treatment is to bracket it with two decks:

- **tied** (`vsubs` hard to 0): an ideal zero-impedance substrate. No
  coupling is possible by construction. This is what the composed cells'
  own per-gate psub guard rings are drawn to approach.
- **float** (`vsubs` on the extractor's own 1 TOhm dc tie): an ideal
  infinite-impedance shared substrate. Every ring's switching current is
  forced through the shared node and into every other ring.

A third deck is what makes the difference between them interpretable. A
floating node is not only a coupling path, it is also *not a ground*, so it
changes every net's effective load. `tb_post_layout_substrate_float_solo.spice`
runs the float deck with rings 2/3/4 **present but stopped** — same
extracted capacitance on the shared node, no switching — so ring 1's period
there carries the loading mechanism alone:

    loading  = t(solo)  - t(tied)     = -0.151% to -0.057%
    coupling = t(float) - t(solo)     = -0.033% to +0.018%

**The coupling-attributable period shift is at most 0.033% of the ring
period, and it is an upper bound rather than a resolved measurement.** Only
1 of 12 grid points exceeds the transient solver's own numerical period
scatter at the same 5 ps timestep (0.024% of `T_0`, measured with no
injected noise at all in `sim/ro-ring-timestep-convergence/`), and the
shift's sign is not consistent across the grid — a real frequency pull would
move every ring the same way. What *is* resolved is that the shared node
genuinely carries all four rings' activity: it swings 3.8% of Vdd peak to
peak with four rings running, against 1.1% with one.

### 4. DR-0003 §8 stays open, and this record does not supersede it

§8's question is "the skew fraction that actually decorrelates two sky130
rings". Finding 3 does not answer it. It measures one coupling path —
capacitive substrate return — on a layout that is missing the two paths most
likely to dominate:

- **Shared supply impedance.** §8 names this first. There is still no
  supply-distribution layout, so `vddr1`..`vddr4` remain four ideal,
  perfectly-isolated sources. The coupling a real, shared, resistive supply
  grid produces is not in this netlist, and is not bounded by anything above.
- **Substrate resistance.** The extractor emits no substrate or tap
  resistance, so the tied/float pair brackets the *terminals* of a range
  whose interior is unmodelled. The physical answer lies between them; this
  record cannot say where.
- **Proximity.** These are nine leaf cells simulated as if placed at
  infinite separation. Ring-to-ring physical distance, well-to-well
  spacing, and any shared guard structure are floorplan facts that do not
  exist yet.

Per this repo's decision-record convention, a correction supersedes rather
than edits in place. **There is no correction to make**: §8's statement of
the gap remains accurate. What this record adds is that the gap is now
*partially* bounded, and that the part that has been measured is small
enough not to be the interesting term.

## Alternatives considered

### Close DR-0003 §8 on finding 3

Rejected. The measurement covers one of three named coupling mechanisms, at
one of two bounding values of an unmodelled impedance, on a layout with no
inter-cell interconnect. Reading "coupling <= 0.033%" as "the rings are
decorrelated" would be exactly the substitution of an available measurement
for the required one that §8 was written to prevent.

### Re-size `N` against the 1.4x post-layout period

Rejected, deliberately, though the sizing law is sensitive to `T_0`. The
period will move again when inter-cell routing lands, and `sigma_1` has not
been re-measured post-layout, so both inputs to `Q_ring` would be
inconsistent. The right sequence is: finish the assembly, re-measure
`sigma_1` post-layout, then re-run `sim/ro-array-sizing/`'s reduction once
against a self-consistent set.

### Model a plausible substrate resistance instead of bracketing

Rejected. Any value would be invented — the extractor supplies none, and
this repo has no sky130 substrate-resistivity measurement of its own. A
bracket with an honest "the answer is somewhere in here" is worth more than
a single number with a fabricated basis. If klayout-tools#1503's fix (or a
successor) ever emits a real substrate network, this becomes a measurement
rather than a bound.

### Simulate the extracted cells flat instead of instantiated

Rejected for this campaign, though it is the other workaround
klayout-tools#1503's write-up names. A ring is five instances by
construction; flattening would mean hand-merging five cells' netlists per
ring and would make the substrate node per-ring rather than shared, which
is the opposite of what finding 3 needs. `.global vsubs` keeps the node
shared and lets the deck state its own tie explicitly, which is what makes
the tied/float bracket possible at all.

## Consequences

- **`layout/pex/ro_ring5_pex.spice` becomes a citable netlist**, on the same
  `--check`-guarded footing as `design/*.spice`: regenerable from committed
  GDS, byte-diffable, with a unit-tested rewrite
  (`layout/test_pex_netlist.py`) and a per-record sha256 in every record's
  `netlists` block.

- **`design/README.md`'s `wstv` row must keep saying decorrelation is
  unmeasured.** Finding 2 is about the *ladder*, finding 3 about one
  *coupling path*; neither is the decorrelating skew fraction.

- **Any future post-layout period claim must state which substrate tie it
  used.** The tied and float decks differ by ~0.1% on period here, which is
  small, but the same choice was measured at ~17% impedance error at 10 GHz
  in `layout/README.md` § "Scouting `--parasitics`". The `sim/` records
  state it; new decks must too.

- **Known limitations, stated as limitations:**
  - Intra-cell parasitics only. No inter-cell interconnect exists to extract.
  - The extractor's resistance model is a *lumped star* per net, not a
    distributed RC ladder, so each terminal sees the whole net's resistance.
    That over-states resistance, making finding 1's 1.4x an upper bound on
    the intra-cell penalty — while the absence of inter-cell wiring makes it
    a lower bound on the eventual whole-block penalty. The two do not
    cancel and neither should be assumed to dominate.
  - Lateral (same-layer) capacitive coupling is modelled only for nets named
    `--critical-net`, and this library names none, so the reported
    net-to-net coupling is crossover coupling alone.
  - Deterministic transients, no injected device noise, one seed's worth of
    nothing — this campaign says nothing about `sigma_1`, jitter or entropy
    post-layout. `sim/raw-bit-min-entropy/`'s measurement remains
    pre-layout.
  - "DRC-clean" throughout means clean against `klt`'s **curated** sky130
    deck (see each `drc.json`'s own `coverage` block), not a sign-off deck.

- **Follow-up required:**
  - **Ratification** of this record, and of DR-0001/DR-0002/DR-0003 — an
    operator/Champion action, not performed here.
  - **Inter-cell interconnect**: `xor2` routing, `ro_ring5` assembly,
    `ro_array_core` assembly, `sampler_dff`/`sampler_core` — tracked in
    2AMLogic/sky130-trng#27. Findings 1 and 3 should be re-run against the
    assembled block when it exists; both will move.
  - **A supply-distribution layout**, without which §8's first-named
    coupling mechanism cannot be measured at all.
  - **Post-layout `sigma_1`**, before any re-sizing of `N` against the
    post-layout period.
  - **klayout-tools#1503**, whose fix would replace this record's
    tied/float bracket with a modelled substrate network.
