---
dr: DR-0009-sampler-core-substrate-bracket-and-wstv-decorrelation
title: whole-chain (sampler_core) post-layout substrate bracket, and what remains of DR-0003 §8's inter-ring decorrelation gap after ring, array and sampler_core scopes are all measured
status: Proposed
date: 2026-09-08
deciders: unratified — Proposed by the Builder on #22; ratification is an operator/Champion action
supersedes: "n/a — this record does NOT supersede DR-0003 §8, DR-0005 or DR-0006. It runs DR-0006's own named follow-up (`sampler_core` is the one remaining hierarchy level with no substrate-coupling measurement of its own) and then states, for the first time in one place, exactly which of DR-0003 §8's three named mechanisms are now measured and which two are not — narrowing the gap rather than closing it."
superseded_by: n/a
related: "#22 (this record), DR-0003 §8 (the inter-ring decorrelation gap this record re-measures against and narrows), DR-0005 (ring-scope tied/float/solo bracket), DR-0006 (array-scope tied/float/solo bracket, and the follow-up this record discharges), DR-0007/DR-0008 (the sampler_dff-scope post-layout campaigns whose own follow-up named sampler_core scope), layout/pex-sampler-core/README.md (what this record's parasitic model contains), sim/README.md § 'Sampler post-layout, whole composed cell' (the campaign this record extends), sim/post-layout-sampler-core/analysis/substrate-bracket.py (the reduction that reproduces every number below), klayout-tools#1503 (the substrate-node modelling gap that bounds what this record can say)"
---

# DR-0009: the `sampler_core`-scope substrate bracket, and what is left of DR-0003 §8

## Status

- 2026-09-08: **Proposed.** Not accepted by anyone. This record runs the
  tied/float/solo substrate bracket at `sampler_core` scope — the one
  hierarchy level DR-0006's own "Follow-up required" section names as having
  no substrate-coupling measurement of its own — and then does the thing
  none of DR-0005, DR-0006, DR-0007 or DR-0008 did: audits DR-0003 §8's
  three named coupling mechanisms one by one against the evidence that now
  exists, and states which are measured, which are not, and what
  specifically would have to exist for the two that are not. It does not
  ratify DR-0001 through DR-0008, does not move any `design/README.md`
  target row from placeholder to measured, and does not change the array
  size, stage count, `wstv` ladder or operating point DR-0003 chose.

## Context

DR-0003 §8 flagged, and deliberately did not resolve, "the skew fraction
that actually DECORRELATES two sky130 rings", on the grounds that the
measurement "needs extracted parasitics and stays out of scope until layout
exists". Layout now exists at every level of this block's hierarchy, and
three records have chipped at §8 from three different scopes:

| Record | Extraction scope | `loading` (t(solo) − t(tied)) | `coupling` (t(float) − t(solo)) |
|---|---|---|---|
| DR-0005 | nine leaf cells, ideal inter-cell wires, hand-tied to a shared node | −0.151% to −0.057% | −0.033% to +0.018% (mixed sign) |
| DR-0006 | the whole `ro_array_core` GDS, flat | −0.353% to −0.192% | +0.044% to +0.293% (12 of 12 positive) |
| **this record** | the whole `sampler_core` GDS, flat — entropy source **and** all six digitizers | **-0.650% to -0.283%** | **+0.361% to +0.584%** (12 of 12 positive) |

DR-0006's own follow-up list is explicit about why a fourth row was owed:

> **`sampler_dff`/`sampler_core` as layout at all**, tracked in #27 — the
> only remaining hierarchy level with no physical implementation.

That level now has one. `layout/sampler_core/` is `klt drc` clean (0
violations) and a full `klt lvs` match (264/264 devices, 152/152 nets, 0
errors) against `design/sampler_core.spice`'s own `.subckt sampler_core`,
and `layout/pex-sampler-core/sampler_core_pex.spice` extracts it flat with
real parasitics. `sim/post-layout-sampler-core/` already drives that library
through a functional/timing/current campaign (twelve `PASS` corner runs,
PR #115) whose own write-up closes with "**`wstv` inter-ring decorrelation
remains unmeasured** … that measurement, if attempted, would need a deck
built specifically to probe it". This record is that deck, and its
reduction.

## Decision

**We record the following as the current, provisional whole-chain position,
and we NARROW rather than close DR-0003 §8.**

### 1. The tied/float/solo bracket at `sampler_core` scope

Three decks, all reading ring 1's own period with the identical estimator,
over the four (temp, Vdd) points × `tt`/`ss`/`ff` grid every post-layout
campaign in this repo uses:

- **TIED** — `sim/post-layout-sampler-core/testbench/tb_post_layout_sampler_core.spice`,
  `vsubs` hard to 0. Already run and recorded (PR #115); no coupling is
  possible by construction.
- **FLOAT** — `…_substrate_float.spice`, `vsubs` untied on the extractor's
  own 1 TΩ dc tie, all four rings running.
- **SOLO** — `…_substrate_float_solo.spice`, `vsubs` untied, rings 2-4
  present but held disabled the whole run (a defined, non-switching state
  per `ro_nand2`'s own disable behaviour).

All three carry the six-`sampler_dff` bank, its real `d`-pin fan-out load,
its real extracted capacitance onto the shared substrate, and an identical
`clk`/`rst_n` history — so the digitizer bank's own contribution is common
to all three and cancels out of both differences:

    loading  = t(solo)  - t(tied)   = -0.650% to -0.283%
    coupling = t(float) - t(solo)   = +0.361% to +0.584%   (12 of 12 positive)

**Both magnitudes are again larger than the next scope down, and the
progression across the three scopes is monotone in both columns** (see the
Context table). That is the expected direction and the expected reason: the
shared node now collects switching current from four rings, four output
buffers, three `xor2` gates *and* six `sampler_dff` instances, all on one
physically-drawn substrate return, where DR-0006's array extraction carried
the first three and DR-0005's leaf-cell extraction carried only the rings.

**The coupling figure's sign is consistent across all twelve grid points**
(12 of 12 positive; `float` is slower than `solo` everywhere). DR-0006
observed that signature for the first time at array scope and named it as
"what a *real* frequency pull would look like"; this record reproduces it
at an independent, larger scope, with a magnitude roughly 2-8x larger
(+0.361% to +0.584% against +0.044% to +0.293%), and every one of the twelve
points now clears DR-0005's ring-scale numerical period-scatter floor
(0.024% of `T_0`) by 15-24x, against 1 of 12 at ring scope.

**That is still not a resolved coupling magnitude**, and this record declines
to call it one, for the two reasons DR-0006 gave and which this record cannot
retire either:

- The transient solver's own numerical period-scatter floor has **not** been
  re-derived at this scale (or at array scale). 0.024% is a ring-only
  measurement, and this deck has far more nodes. The 15-24x margin makes it
  implausible that scatter explains the result, but implausible is not
  measured.
- The magnitude still depends on an unmodelled substrate resistance (finding
  3): `tied` and `float` bracket the *terminals* of a range whose interior
  is unmodelled, so a consistent sign tells us the direction of the effect
  at the infinite-impedance terminal, not its size at the real one.

**DR-0003 §8's own ladder criterion still holds at this scope, on the
pessimistic terminal.** Measured on the float deck itself (all four rings,
`vsubs` untied), the realized ladder span is 1.0964x - 1.1843x and the
closest approach any ring pair makes to any mutual-injection-lock rational
(2/1, 3/2, 4/3) anywhere on the grid is **11.2%** — comfortably clear, and
consistent with DR-0005's own ring-scope figure of 9.3%, now with the whole
chain in the netlist and the substrate deliberately left floating.

`python3 sim/post-layout-sampler-core/analysis/substrate-bracket.py`
reproduces every figure above from the committed records alone — it runs no
simulator and reads no PDK.

### 2. The digitizer bank is a first-order substrate aggressor, and it dissolves the coupling signature

Finding 1's estimator is the one all three decks share, and at this design's
post-layout ring periods its thirteen rising edges all land before `rst_n`
releases at 300 ns. So finding 1 measures the bracket with the six samplers
**placed, extracted and loading their `d` pins, but not switching** — a
strictly-larger-scope repeat of DR-0006's question, not a new one.

The float and solo decks therefore carry a **second** period estimator that
DR-0006 had no equivalent of: ten periods taken from the first rising edge
past 400 ns, inside the clocked window, with all six `sampler_dff` instances
actually latching. Its result is the substantive new finding here:

    coupling (reset-held window, samplers static)   = +0.361% to +0.584%,  12 of 12 positive
    coupling (clocked window, samplers latching)    = -0.486% to +0.589%,   8 of 12 positive

**Once the digitizer bank switches, the ring-to-ring coupling term is no
longer separable in sign.** The range is comparable in magnitude but the
consistent direction — the one property DR-0006 named as the signature of a
real frequency pull, and which finding 1 reproduces — is gone.

The shared node's own excursion says why, and it is the corroborating
measurement DR-0006's follow-up list explicitly asked a later deck to
capture (its own array-scope attempt addressed the node hierarchically and
silently read nothing). As a fraction of Vdd, peak to peak:

| Window | Four rings running (float) | One ring running (solo) |
|---|---|---|
| reset-held (100-300 ns): samplers static | 9.94% - 15.36% | 6.12% - 6.43% |
| clocked (400-600 ns): samplers latching | 11.66% - 19.12% | **6.55% - 16.87%** |

Read the bottom-right cell against the top-right one: **with only one ring
running, releasing the six samplers to clock takes the shared node from a
tight 6.12-6.43% band to 6.55-16.87%.** Compared per grid point rather than
by range — one ring plus a clocking sampler bank, against four free-running
rings with the bank static, at the same corner — **the sampler bank wins at
7 of 12 points**. It is not a perturbation on a ring-dominated node; at
whole-chain scope it is a comparable or dominant aggressor.

**Why that matters for §8, beyond this deck.** §8 is framed entirely as a
*ring-to-ring* question — "the skew fraction that actually decorrelates two
sky130 rings". This is the first measurement in this repository at a scope
where that framing is visibly incomplete: the largest identified aggressor
on the one node the rings actually share is not another ring. Whether that
matters for entropy is *not* something this record can say — it injects no
device noise and makes no jitter or min-entropy claim — but any future
attempt to answer §8 by measuring ring-to-ring correlation alone should know
that the sampler bank is on the same node at comparable amplitude.

**What this finding is not.** There is no `loading` counterpart in the
clocked window: the TIED records were minted before these decks existed
(PR #115) and carry no clocked-window estimator, so only the float-minus-solo
difference is available there (see "Alternatives considered"). The two
windows are also not interchangeable estimators of the same quantity — they
average different ring cycles under different circuit conditions — so the
comparison above is between two coupling figures, not a decomposition of one.
And both are read at the `float` terminal, which is not a physical substrate.

### 3. The audit DR-0003 §8 was actually waiting for

§8 names three mechanisms. After DR-0005 (ring), DR-0006 (array) and this
record (whole chain), their status is no longer uniform, and stating them
separately is the substantive contribution here:

| §8 mechanism | Status after this record | What would change it |
|---|---|---|
| **Proximity** — "ring-to-ring physical distance, well-to-well spacing, and any shared guard structure are floorplan facts that do not exist yet" (DR-0005) | **CLOSED.** Those floorplan facts exist and have been extracted at every scale: one ring (`layout/pex-ring/`), the whole array (`layout/pex-array/`), and now the whole array plus all six digitizers in one flat extraction (`layout/pex-sampler-core/`). Nothing in §8's proximity concern is hypothetical any more. | — (nothing; this is measured) |
| **Substrate capacitive return** | **BRACKETED, at three scales, not resolved — and, at whole-chain scope, no longer a two-party mechanism.** The bracket's width grows monotonically with how much switching silicon shares the node (finding 1), its interior is unmodelled because the extractor emits no substrate or tap resistance at all, and finding 2 shows the ring-to-ring sign consistency does not survive the digitizer bank's own switching on the same node. | klayout-tools#1503 — a modelled substrate network would replace the bracket with a measurement, at every scale at once |
| **Shared supply impedance** — §8's **first-named** mechanism | **ENTIRELY UNMEASURED, and not measurable from anything in this repository.** Every deck in every one of DR-0005/0006/0009 drives `vddr1`-`vddr4` from four ideal, perfectly-isolated sources, because that is what the design specifies (`design/README.md`'s pin table) and what the layout draws: `layout/README.md`'s own open list still names per-ring supply distribution as undrawn. There is no layout fact to measure against. | A supply-distribution layout for `vddr1`-`vddr4` — substantial, independently-schedulable floorplan/routing work, and a design decision (it would change whether the per-ring supply independence the design deliberately has is preserved) |

**So DR-0003 §8 does not close, and this record says so with a reason that
is now specific rather than generic**: two of its three mechanisms are
retired or bounded, and the residue is exactly one mechanism whose
measurement is blocked on one piece of layout that does not exist, plus one
tool capability that does not exist. Neither is a simulation this repository
could have run and did not.

Per this repo's decision-record convention, a correction supersedes rather
than edits in place. **There is no correction to make to DR-0003 §8, to
DR-0005 or to DR-0006** — every one of those records' statements of the gap
remains accurate as written. What this record adds is the decomposition
above: the gap is no longer "layout does not exist", which is how §8 phrased
it and how DR-0005 inherited it, but "one named mechanism, two named
prerequisites".

## Alternatives considered

### Close DR-0003 §8 on the strength of three scopes agreeing

Rejected. Three scopes agreeing about **one** of three mechanisms is not an
answer to a question about a decorrelating *skew fraction*. §8's
first-named mechanism has never been in any netlist this repo has
simulated, at any scale, and no amount of substrate evidence substitutes
for it.

### Re-derive the numerical period-scatter floor at this scale first

Named as a gap rather than done, exactly as DR-0006 named it and for the
same reason: re-running `sim/ro-ring-timestep-convergence/`'s
zero-injected-noise methodology against the whole-chain deck is
straightforward with the infrastructure this record already built, but each
corner of this deck costs roughly an hour of wall clock, and doing it here
would have delayed the bracket itself. This record therefore reads its
`coupling` column as a **range/bound**, and quotes DR-0005's ring-scale
0.024%-of-`T_0` floor only as the comparison it is, not as a resolution
threshold that has been validated at this scale. It remains the
load-bearing follow-up, inherited unchanged from DR-0006.

### Build a supply-distribution layout in this same increment

Rejected as out of scope for this record, for the same reason DR-0006
rejected it: it is substantial independent floorplan work *and* a design
decision about whether the per-ring supply independence
`design/README.md`'s pin table specifies is preserved or deliberately
altered. It is named here as the single load-bearing prerequisite for
closing §8, which is a stronger statement than DR-0006 made, but it is not
work this record does.

### Re-run the TIED deck with the clocked-window estimator too

Rejected on cost. The already-minted TIED records (PR #115) do not carry
the clocked-window period estimator this record's float/solo decks add, so
the clocked window yields a `coupling` figure but no `loading` figure. Adding
one would mean re-running twelve more whole-chain corner runs to recover a
quantity the reset-held window already reports. The asymmetry is reported in
finding 2 rather than hidden, and the primary bracket is unaffected — it
uses the estimator all three decks share.

## Consequences

- **`design/README.md`'s `wstv` row must still say decorrelation is
  unmeasured** — but its *reason* changes, and the row is updated to give
  the specific residue (shared supply impedance, with no layout) rather than
  the generic "no layout exists", which is no longer true.
- **`sim/post-layout-sampler-core/` now holds three decks, not one**, and
  any future whole-chain period claim from that slug must state which
  substrate tie it used — the same discipline DR-0005 established at ring
  scope and DR-0006 repeated at array scope.
- **The tied/float/solo bracket is now complete across this block's whole
  hierarchy** (leaf cells → ring → array → array + digitizers). A fourth
  *scope* does not exist to run it at; the remaining moves on this mechanism
  are a change of *stimulus* (finding 2's implied rings-off deck) or of
  *model* (klayout-tools#1503), not another scale.
- **DR-0006's own follow-up asking for a deck that captures the substrate
  node's peak-to-peak swing** — its array-scope decks addressed the
  `.global` node hierarchically and silently measured nothing — is
  **discharged** here, at a larger scope, with the corrected `v(vsubs)`
  addressing and in two separate windows (finding 2's table).
- **Known limitations, stated as limitations:**
  - Deterministic transients, no injected device noise. This record says
    nothing about `sigma_1`, jitter, or entropy post-layout at any scale,
    and therefore nothing about how any of the above would move a min-entropy
    estimate.
  - The transient solver's own numerical period-scatter floor is quoted from
    DR-0005's **ring-scale** measurement and has not been re-derived at this
    scale (or at array scale — DR-0006 named the same gap).
  - The `float` leg is not a physical configuration. With `vsubs` on a 1 TΩ
    tie the node settles to a non-zero potential and every device's body bias
    moves with it; that is the *point* of a bracket terminal, but it is not
    a state any real substrate is in.
  - `layout/pex-sampler-core/pex.json --check` is **red** on today's ambient
    `klt 0.4.0` against the `layout/pdk.json` pin of
    `0.3.0+gc6dbf66c53c6` — verified during this record's own work to be a
    provenance/labelling difference only (all 19 differing nets have
    identical resistance, capacitance, RC model, per-terminal leg resistance
    and terminal-letter multiset; only anonymous `$NNN` device ids are
    renumbered). Every number here is measured against the committed
    library, cited by sha256 in each record's `netlists` block.
  - "DRC-clean" and "LVS-matching" throughout mean clean/matching against
    `klt`'s **curated** sky130 deck, not a sign-off deck (the same caveat
    every prior `layout/` record in this repo carries).

- **Follow-up required:**
  - **Ratification** of this record, and of DR-0001 through DR-0008 — an
    operator/Champion action, not performed here.
  - **A supply-distribution layout for `vddr1`-`vddr4`.** This is now the
    single named blocker on DR-0003 §8, promoted from one item in a list to
    the load-bearing one by finding 3's audit.
  - **Re-derive the numerical period-scatter floor** at array and
    whole-chain scale, inherited unchanged from DR-0006, before treating any
    individual grid point's `coupling` figure as significant rather than
    reading the range as a bound.
  - **Isolate the digitizer bank's own substrate aggression** — the
    fourth deck finding 2 implies but does not run: all four rings held
    disabled, the six samplers clocking, `vsubs` floating. Finding 2 bounds
    that contribution indirectly (via the solo deck's own two windows); a
    dedicated deck would measure it, and is the natural next increment on
    this mechanism at this scope.
  - **klayout-tools#1503**, whose fix would replace the tied/float bracket
    with a modelled substrate network at every scale at once.
  - **Post-layout `sigma_1`**, before any re-sizing of `N` against any
    post-layout period from any of DR-0005, DR-0006 or this record.
