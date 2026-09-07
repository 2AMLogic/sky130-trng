---
dr: DR-0008-sampler-dff-assembled-post-layout
title: whole-cell (assembled) post-layout parasitics on the sky130 sampler_dff, and DR-0007's own named follow-up re-run at assembly scale
status: Proposed
date: 2026-09-07
deciders: unratified — Proposed by the Builder on #22; ratification is an operator/Champion action
supersedes: n/a — this record does NOT supersede DR-0007. It re-runs DR-0007's own named follow-up item ("Once layout/sampler_dff/'s m/mb nets are routed and its klt lvs matches, extract that GDS flat ... and re-run both decks") now that both nets are routed, and finds that finding 1 (capture-delay slowdown) moves in the direction DR-0007 itself predicted, while finding 3 (setup time) is explicitly not re-derived here.
superseded_by: n/a
related: "#22 (this record), DR-0007 (the prior post-layout campaign this record extends from intra-cell scope to whole-cell/assembled scope), DR-0006 (the array-scale sibling relationship this record repeats for the sampler: DR-0005 to DR-0006 is the same intra-cell-to-assembled step this record takes from DR-0007), layout/pex-sampler-dff-assembled/README.md (what this record's parasitic model contains), sim/README.md's 'Sampler post-layout' section (the eight-plus-four-record reduction), layout/sampler_dff/README.md (the m/mb routing that unblocked this extraction), PR #95 and PR #99 (mb and m, the two nets whose routing this record's extraction depended on)"
---

# DR-0008: whole-cell (assembled) post-layout `sampler_dff`, and DR-0007's own follow-up re-run at assembly scale

## Status

- 2026-09-07: **Proposed.** Not accepted by anyone. This record re-runs
  DR-0007's own named follow-up item ("whole-cell extraction") now that
  `layout/sampler_dff/`'s assembly GDS is DRC-clean and `klt lvs`-matching
  (22/22 devices, 14/14 nets, 0 mismatches) for the first time, and states
  what does and does not move as a result. It does not ratify DR-0001
  through DR-0007, does not change the array size, stage count, `wstv`
  ladder, raw rate or operating point DR-0003 chose, and does not re-derive
  DR-0007's setup-time finding (finding 3) — see "Known limitations" below.

**Which record's numbers come from where.** DR-0007's own figures are
measured against `layout/pex/sampler_dff_pex.spice` — three separately
composed leaf cells (`layout/ro_buf/`, `layout/sampler_tg/`,
`layout/sampler_nand2/`), rewired by the testbench itself with **ideal**
inter-cell wires. This record's own figures are measured against
`layout/pex-sampler-dff-assembled/sampler_dff_assembled_pex.spice` — one
flat `klt extract --parasitics` over `layout/sampler_dff/sampler_dff.gds`,
the same composed, DRC-clean, `klt lvs`-matching assembly GDS, with every
intra-cell net (`rst_n`, `clk`, `clkb`, `mc`, `q`, `qb`, `s`, `m`, `mb`)
**really routed** rather than assumed ideal between the three leaf shapes.
Four records, twelve corner runs, all `PASS`:
`sim/post-layout-sampler-dff-assembled/records/20260907-1552{29,35,30,26}-709dc0b.json`.

## Context

DR-0007 measured intra-cell parasitics on three separately-composed leaf
cells wired by ideal testbench nets (finding 1: 1.314x-1.418x clk→q capture
delay penalty) and explicitly deferred the whole-cell extraction:

> **Whole-cell extraction.** Once `layout/sampler_dff/`'s `m`/`mb` nets are
> routed and its `klt lvs` matches, extract that GDS flat — the sampler's
> equivalent of `layout/pex-ring/` — and re-run both decks. Findings 1 and 3
> will move; DR-0006's array-scale result suggests roughly another 1.5x -
> 1.7x on top of intra-cell alone.

Both nets are now routed (`mb`: PR #95; `m`: PR #99, issue #22) and
`layout/sampler_dff/`'s own `klt lvs` is a full match — see
`layout/sampler_dff/README.md`. `layout/pex-sampler-dff-assembled/`
extracts that GDS flat with `klt extract --parasitics`
(`layout/pex-sampler-dff-assembled/README.md` states the model), and
`sim/post-layout-sampler-dff-assembled/` re-runs
DR-0007's own capture-timing/reset-contention deck
(`tb_post_layout_sampler_dff.spice`'s topology, unchanged) against it,
across the same four-(temp, Vdd)-point, `tt`/`ss`/`ff` grid every post-layout
campaign in this repo uses — the sampler's exact sibling of the
DR-0005-to-DR-0006 step already taken on the ring/array side.

**This record re-runs only the capture-timing/reset-contention deck**, not
DR-0007's sibling setup-time-bracket deck
(`tb_post_layout_sampler_setup.spice`) — matching
`sim/post-layout-ro-ring5-assembled/`'s own precedent of adding one deck per
"assembled" increment rather than replaying every existing deck at the new
extraction scope. DR-0007's own finding 3 (setup time) is therefore **not**
re-derived here; see "Known limitations".

## Decision

**We record the following findings as the current, provisional whole-cell
post-layout position for `sampler_dff`.**

### 1. Real intra-cell interconnect costs 1.70x - 2.01x in clk→q delay — moving in the direction DR-0007 predicted, but by less than the naive multiplicative estimate

| Quantity | Pre-layout | Post-layout, leaf-cell (DR-0007) | Post-layout, assembled (this record) |
|---|---|---|---|
| clk→q delay, rise, ratio to pre-layout | 1.000x | 1.314x - 1.418x | **1.704x - 1.834x** |
| clk→q delay, fall, ratio to pre-layout | 1.000x | (paired with rise above) | **1.817x - 2.013x** |
| clk→q delay, absolute (post-layout) | n/a | 103.6 - 299.0 ps | **131.4 - 426.0 ps** |

Pairing this record's twelve corner runs against DR-0007's own twelve
matching (temp, Vdd, corner) points directly — the "on top of intra-cell"
ratio DR-0006 computed for the ring/array pair — the assembled deck's own
slowdown is **1.268x - 1.294x** (rise) / **1.383x - 1.425x** (fall) *of*
the leaf-only deck's own slowdown at that same point. That is smaller than
DR-0007's own "roughly another 1.5x - 1.7x" estimate (borrowed from
DR-0006's array-scale ring/buffer/XOR-tree result), which is not a
contradiction: `sampler_dff`'s own intra-cell routing spans a five-inverter/
four-transmission-gate/two-NAND2 master-slave loop on one `li1`/`met1`/
`met2` footprint (`layout/sampler_dff/README.md`'s own per-net derivations),
a materially different interconnect shape from `ro_array_core`'s
ring-to-buffer-to-XOR-tree fan-out — there was no reason to expect the two
cell families' "assembled-on-top-of-intra-cell" multipliers to agree, and
DR-0007 itself only offered the array figure as an order-of-magnitude
placeholder ("suggests"), not a prediction to be reproduced exactly.

Against DR-0003's ratified 20 µs sample period, the worst absolute capture
delay (426.0 ps, fall, `ss`/−40 °C/1.62 V) is **≤ 21.3 ppm of `T_s`** —
`~5.3 ppm` in DR-0007 becomes `~21.3 ppm` here, still four orders of
magnitude below mattering. Capture delay does not constrain the raw rate at
any corner, same conclusion as DR-0007, now with a wider margin measured
rather than assumed.

### 2. The reset window still carries no contention current — unchanged at assembly scale

Same protocol as DR-0007 finding 2: `rst_n` asserted while `d` drives the
opposite value through the transparent master, the condition under which a
brute-force pull-device reset would fight the `d` driver.

`i_rst_pex` and `i_rst_pre` (the assembled post-layout and pre-layout
reset-window currents) agree to **4-5 significant figures at every one of
the twelve grid points** (ratio 1.0000 - 1.0018), the same "identical
pre- and post-layout" signature DR-0007's own finding 2 reported at leaf
scope. `i_rst_pex / i_idle_pex` (reset current against the same cell's own
idle current) ranges **0.5012 - 1.0141** — inside DR-0007's own **0.501 -
1.014** range for the same ratio, to three significant figures, on a
*different* extraction (whole-cell flat vs. leaf composition). Two
independent measurements of "does drawing the real intra-cell routing add
any contention current to this reset topology" now agree at both extraction
scopes: it does not. Maximum reset-window current at the hottest, fastest
grid point is 293 nA (`ff`/125 °C/1.98 V); minimum is 19.3 pA
(`ss`/−40 °C/1.62 V) — both effectively unchanged from DR-0007's own
figures for the identical reason DR-0007 gives: a window whose current does
not move when real R/C is added to the loop is carrying no switching
current for that R/C to slow.

**What this adds to DR-0007's own licensing statement**: the reset-window
finding is now confirmed at the whole-cell extraction scope, not just the
leaf-cell composition scope, closing the one gap DR-0007's own "what this
does not license" section left about *this* topology's own drawn assembly
(the brute-force pull-device control DR-0007 named remains unsimulated
here too — see "Known limitations").

### 3. The post-layout assembled cell is functionally correct

Captured levels are **≥ 0.9988 × Vdd** high and **≤ 0.00195 × Vdd** low at
every grid point (DR-0007's own leaf-scope figures: ≥ 0.9983×Vdd /
≤ 0.0023×Vdd — the same order, on the real routed assembly this time);
asserted reset holds `q` **≤ 0.386 mV** while `d` drives the opposite value
(DR-0007: ≤ 0.38 mV, effectively identical). Worth stating as a finding
rather than assuming, same as DR-0007's own finding 4: the post-layout
netlist here is `layout/sampler_dff/sampler_dff.gds` extracted flat, so a
wrong route or an LVS-invisible short would show up as a captured-level
failure first, and none appears.

Active-window average current (55 ns spanning both capture edges) is
**1.585 - 2.637 µA** post-layout, **1.739x - 2.300x** the pre-layout figure
— larger than DR-0007's own leaf-scope **1.306x - 1.548x**, as expected: the
assembled extraction's real intra-cell routing adds capacitance the ideal
leaf-cell wires could not carry, and this is the one place that extra
capacitance shows up as real current rather than as delay alone.

## Known limitations

- **Finding 3 (setup time) is not re-derived here.** DR-0007's own
  setup-time-bracket deck (`tb_post_layout_sampler_setup.spice`, a
  24-instance ladder) was deliberately not re-run against the assembled
  extraction this increment — see "Context" above for why (matching the
  ring/array precedent's own one-deck-per-increment scope). DR-0007's
  setup-time figures (60 - 150 ps, leaf-cell scope) therefore still stand as
  the most recent measurement; a whole-cell re-run is named as follow-up
  below, and finding 1's own ratio (assembled costs another ~1.27x - 1.43x
  on top of intra-cell) is the best available estimate of how much the
  setup bracket should move until that follow-up lands.
- **The brute-force pull-device reset control** named in DR-0007 is still
  not simulated, at either extraction scope.
- **`sampler_core` scope** (six `sampler_dff` instances on shared
  `vdd`/`clk`/`rst_n`, driven from the array's own combining node) is
  unchanged from DR-0007: this record is still one isolated `sampler_dff`
  instance under ideal PWL stimulus, not the six-instance fan-out
  `design/sampler_core.spice` actually wires. `sampler_core` still has no
  layout at all.
- Deterministic transients, no injected device noise — this record says
  nothing about jitter or entropy post-layout at either extraction scope.
- "DRC-clean" and "`klt lvs`-matching" throughout mean clean/matching
  against `klt`'s **curated** sky130 deck, not a sign-off deck (same
  caveat every prior `layout/` record in this repo carries).

## Alternatives considered

### Re-run the setup-time-bracket deck in this same increment

Rejected for this record, though named as a real gap above. The 24-instance
ladder deck is a materially larger lift (twelve post-layout and twelve
pre-layout instances sharing one clock, one d source per rung) than
swapping the capture-timing deck's own library/subcircuit-name tokens, and
`sim/post-layout-ro-ring5-assembled/`'s own precedent (one new deck per
"assembled" increment, not a replay of every sibling deck at the new
extraction scope) argues for landing this record's own evidence first
rather than delaying it for a second deck. Tracked as follow-up.

### Treat finding 1's on-top-of-intra-cell ratio as a correction to DR-0007's own "~1.5x-1.7x" estimate

Rejected as a mischaracterization: DR-0007 named that figure as borrowed
from a *different cell family's* array-scale result ("DR-0006's array-scale
result suggests"), explicitly as an order-of-magnitude placeholder, not as
a `sampler_dff`-specific prediction. This record's own measured
1.268x-1.425x is additional evidence about `sampler_dff`'s own interconnect
shape specifically, not a correction to a claim DR-0007 never made about
this cell.

## Consequences

- **`layout/pex-sampler-dff-assembled/sampler_dff_assembled_pex.spice`
  becomes a citable netlist**, on the same `--check`-guarded footing as
  `layout/pex/`, `layout/pex-ring/` and `layout/pex-array/`'s own
  libraries: regenerable from committed GDS, byte-diffable, with a
  per-record sha256 in every `sim/` record's `netlists` block.
- **`design/README.md`'s sampler row gains an assembled-scope figure**
  alongside DR-0007's leaf-scope one.
- DR-0003's "Sampler_dff characterization" follow-up item is now discharged
  at the **whole-cell** post-layout scope for the capture-timing/
  reset-contention deck specifically; the setup-time deck and the
  six-instance `sampler_core` scope remain open (see "Known limitations").
- Nothing in DR-0003's operating point moves. `N`, the stage count, the
  `wstv` ladder, `T_s` = 20 µs and the 50 kbps raw rate are all untouched.

- **Follow-up required:**
  - **Ratification** of this record, and of DR-0001 through DR-0007 — an
    operator/Champion action, not performed here.
  - **Re-run the setup-time-bracket deck** against
    `sampler_dff_assembled_pex` — DR-0007's own finding 3, at whole-cell
    scope, is the one figure this record does not re-derive.
  - **`sampler_core` scope**: six `sampler_dff` instances on one shared
    `vdd`/`clk`/`rst_n`, driven from the array's own combining node rather
    than an ideal PWL source — the only way clock-distribution skew and the
    real (not ideal) input edge rate enter a `sampler_dff`-family
    measurement, and the prerequisite for any whole-chain
    raw-tap-to-sampled-bit post-layout claim.
  - **The brute-force reset control**, if a ratio against the rejected
    alternative is ever wanted as sky130 evidence rather than as
    gf180-trng's, at either extraction scope.
  - **Re-run finding 1 (and the deferred finding 3) with a realistic input
    edge**, not ideal PWL — DR-0007's own named gap, unchanged by this
    record.
