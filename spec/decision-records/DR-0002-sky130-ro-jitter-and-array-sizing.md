---
dr: DR-0002-sky130-ro-jitter-and-array-sizing
title: sky130 RO jitter characterization results, the entropy-binding corner, and the sized array size N
status: Proposed
date: 2026-08-25
deciders: unratified — Proposed by the Builder on #10; ratification is an operator/Champion action
supersedes: n/a
superseded_by: n/a
related: "#10 (the campaign this record reports), #13 (the array rebuild this record hands off), #9/PR #12 (the harness it runs on), #6 (parent), DR-0001 (the operating-envelope record whose 'Follow-up required' names this campaign and whose 'Revisit if' condition it tests); spec/porting-plan.md §1.1 (the laws that port), §1.4/§2.4 (why the entropy-binding corner must be measured, not inherited), §2.2 (the characterization this closes), §3.1 (the corner grid); design/README.md § 'Provisional, not sized'; sim/ro-array-sizing/records/20260825-071619-54f5715.md (the reduction), sim/ro-ring-jitter-accumulation/, sim/ro-stage-small-signal-gain/, sim/ro-ring-timestep-convergence/"
---

# DR-0002: sky130 RO jitter characterization results, the entropy-binding corner, and the sized array size `N`

## Status

- 2026-08-25: **Proposed.** Not accepted by anyone. This record states what
  the campaign measured and what follows arithmetically from it. It does
  **not** ratify DR-0001, and it does **not** by itself authorise the array
  rebuild its sizing implies — see "Consequences → Follow-up required".

## Context

`DR-0001` (Proposed) chose sky130's 1.8 V core pair for the entropy source
and, under "Follow-up required", named exactly one piece of work as the
thing that turns `design/xschem/`'s geometry from placeholder into result:

> **The sky130 analogue of gf180-trng's RO delay-cell jitter
> characterization** … transient-noise jitter-accumulation runs over
> `design/xschem/ro_stage.sch` at 1.8 V, producing per-ring `sigma_1` and
> `T_0`. Until it exists, every geometry in `design/xschem/` … is a
> provisional placeholder.

DR-0001 also attached a **"Revisit if"** condition to its own decision:

> the jitter characterization finds the 1.8 V starved cell cannot sustain a
> rail-to-rail oscillation at the slow/hot/low-supply corner at any workable
> stage count.

`spec/porting-plan.md` §2.2 is the matching statement from the plan side:
gf180-trng's `N = 2` at eleven stages is computed entirely from
gf180mcu-measured `sigma_1`/`T_0`; **the law ports, the measured inputs do
not**. §1.4/§2.4 add the sharper warning: gf180-trng's own entropy-binding
corner answer *inverted inside that repository* (DR-0012's `ss`/−40 °C
became DR-0015's `ss`/+125 °C) once a fuller grid arrived, so neither its
original direction nor its correction may be assumed here.

Issue #10 is that campaign. Issue #9 / PR #12 landed the harness it runs on
and the go/no-go mechanism check (flicker/thermal noise confirmed active in
the sky130 corner decks as installed) that it depends on.

## Decision

**We adopt the following as this repository's first measured entropy-source
numbers, and we record `N = 2` as refuted rather than merely unconfirmed.**

Every number below is traceable to an append-only record under `sim/`; the
reduction that produces the derived rows is
`sim/ro-array-sizing/analysis/array-sizing.py`, re-runnable against the
committed records with no simulator.

### 1. Per-stage small-signal gain — measured, and DR-0001's gain risk retired

`ro_stage`'s open-loop gain at its own trip point
(`sim/ro-stage-small-signal-gain/`):

| Point | `vtrip` (V) | `dV(y)/dV(a)` |
|---|---|---|
| `tt` / 27 °C / 1.80 V (nominal) | 0.818 | **−14.27** |
| `ss` / 125 °C / 1.62 V (slow/hot/low-supply) | 0.805 | **−15.57** |
| `ff` / −40 °C / 1.98 V (fast/cold/high-supply) | 0.844 | **−11.83** |

The smallest |gain| anywhere in the set is **11.8**. The Barkhausen
requirement for an `n`-stage inverting ring is |A| > 1/cos(π/n) — under 2
for `n = 3` and falling toward 1 as `n` grows. At 11.8 the starved cell
clears that by roughly an order of magnitude at every headline point,
including DR-0001's named risk corner. **The gain half of DR-0001's
"Revisit if" is not triggered**, and it is not close.

### 2. Ring swing — confirmed at every corner, with one caveat that matters

`sim/ro-ring-jitter-accumulation/` measures steady-state peak-to-peak swing
at the ring node at every point it runs:

| Configuration | grid | worst swing | at |
|---|---|---|---|
| `ro_ring11` (**the ring `ro_array_core.sch` actually instantiates**) | 3 headline points | **1.061 × Vdd** | `ff` / −40 °C / 1.98 V |
| `ro_ring5` (the cheap characterization vehicle) | full 27-point grid | **0.809 × Vdd** | `ff` / 125 °C / 1.98 V |

`ro_ring11` exceeds the supply rail-to-rail (the >1.0 figures are node
overshoot/undershoot past the rails, not a measurement error) at all three
headline points. **Ring swing is CONFIRMED for the design as drawn, at
every corner measured, including the slow/hot/low-supply corner DR-0001
names.** The supply half of DR-0001's "Revisit if" is not triggered either.

The caveat is about the *alternative*, not the design: the 5-stage ring is
slew-limited and only reaches 0.81–1.00 × Vdd, worst at the fast/hot/
high-supply end. Anything that later proposes cutting the stage count
(§4 below gives a strong entropy reason to want to) must re-check swing at
its own chosen count rather than inheriting this record's `ro_ring11`
result.

### 3. The entropy-binding corner is `ss` / **−40 °C** / 1.62 V

Reducing the 27-point `ro_ring5` grid via the per-ring sizing law
`Q_ring = sigma_1² · T_s / T_0³` at `T_s` = 1 µs:

| | `Q_ring` | at |
|---|---|---|
| minimum (**entropy-binding**) | **1.122e−4** | `ss` / −40 °C / 1.62 V |
| maximum | 2.748e−3 | `ff` / 125 °C / 1.98 V |
| range | **24.5×** | |

**Direction: cold.** This is the same temperature direction gf180-trng's
DR-0012 originally inferred, and the *opposite* of DR-0015's later
correction to hot — which is precisely why `spec/porting-plan.md` §1.4/§2.4
forbids inheriting either. It is read off a full 27-point grid here, not
extrapolated from three points.

Mechanism, stated so it can be argued with: `Q ∝ sigma_1²/T_0³`, and across
this grid `T_0` moves 3.6× (1.32 ns at `ff`/−40 °C/1.98 V to 4.82 ns at
`ss`/−40 °C/1.62 V) while `sigma_1` moves 4.0×. The `T_0³` term dominates,
so the corner that oscillates *slowest* — slow process, low supply — wins on
`T_0`, and cold then wins the temperature axis because the fixed injected
noise level produces less timing jitter against cold's faster edges.

**A caveat that strengthens rather than weakens the direction**: the
injected noise level is fixed across corners (see §6), whereas real device
thermal noise rises with temperature. Correcting for that would lower
`sigma_1` at cold and raise it at hot, i.e. lower `Q` at cold further. The
cold direction is therefore robust to the one systematic this campaign knows
it carries.

### 4. Stage count: 11 stages is measured to be expensive, not merely unproven

Same three headline points, same injected level, same seed, same estimator:

| point | `ro_ring5` `Q_ring` | `ro_ring11` `Q_ring` | ratio |
|---|---|---|---|
| `ss` / 125 °C / 1.62 V | 2.240e−4 | 1.927e−5 | 11.6× |
| `tt` / 27 °C / 1.80 V | 5.719e−4 | 2.041e−5 | 28.0× |
| `ff` / −40 °C / 1.98 V | 1.180e−3 | 2.435e−5 | 48.5× |

Direction: **fewer stages is better for entropy per sample**, and by a lot.
That direction is what the sizing law predicts (`Q ∝ 1/n²` at fixed `T_s`);
the *magnitude* is not — using the measured `T_0` ratio the law predicts
~8.5× at nominal against a measured ~28×, because the measured `sigma_1`
*fell* from 5 to 11 stages instead of rising as `sqrt(n)`. **This campaign
does not explain that 3.3× excess** and records it as an open question
(Consequences → Follow-up required). Its sign is conservative for the
conclusion drawn here.

Per `spec/porting-plan.md` §2.2's instruction not to carry a geometry claim
on "left as-is": the stage count of 11 is **not** confirmed by this
campaign. It is measured to be a materially worse entropy-per-sample choice
than 5 stages, and the only reason this record does not move it is that
§2's swing result and the sampler-loading/frequency-skew consequences of a
2.7× faster ring have not been evaluated.

### 5. `N = 2` is refuted; the sized value is `N = 53` at the README's draft rows

Evaluated at the binding corner, `T_s` = 1 µs (README's draft
"> 1 Mbps sustained at the raw tap" row), `H0` = 0.5 (README's
raw-min-entropy row), `M` = 1.5 (DR-0007's declared margin, ported per
§1.1), with `Q_H0` = 3.964e−3 and the requirement `Q_array ≥ M·Q_H0` =
5.946e−3:

| `N` (`ro_ring5`) | `Q_array` | guaranteed `H` | meets `H0`? | meets `M·Q_H0`? |
|---|---|---|---|---|
| 2 ← **committed placeholder** | 2.245e−4 | 0.4205 | no | no (26× short) |
| 36 | 4.040e−3 | 0.5015 | yes | no |
| **53** ← **sized, with margin** | 5.948e−3 | 0.5377 | yes | **yes** |

For `ro_ring11` as actually drawn, the same arithmetic gives **`N ≥ 309`**
(a lower bound: only 3 of its points were measured, and its own grid minimum
was not searched).

Two things are simultaneously true and both belong in the record:

- **`Q_array` at `N = 2` is 26× short of what the sizing law asks for.** In
  the terms the law is written in, `N = 2` is refuted, not unconfirmed.
- **The min-entropy shortfall is 0.08 bit, not 0.5 bit.** The Baudet bound
  saturates at `1 − 4/(π² ln 2)` = 0.4153 as `Q → 0`, so `N = 2` still
  guarantees `H` ≥ 0.4205. Quoting only the 26× would overstate the
  physical gap; quoting only the 0.08 bit would understate how far the
  declared sizing discipline is from being satisfied.

### 6. What this record does *not* claim

- **No entropy claim.** Per `CLAUDE.md` and DR-0004's tier discipline
  (ported per §1.1), everything here is a **simulation-derived design
  estimate**, provisional until silicon.
- **The injected noise level is not per-corner device noise.** Every ring
  run injects a fixed `trnoise()` level anchored once to #9's measured
  near-oscillation-band output-noise density (4.0e−8 V/√Hz at `tt`). Per
  gf180-trng's precedent for the same method, treat every `sigma` as good
  to ~1.5–2×, hence every `Q` and every `N` to ~2–4×. `N = 53` is therefore
  "tens", not "fifty-three".
- **Single seed per PVT point** (gf180-trng used ≥4). Seed-to-seed spread is
  not characterized. The seed is held constant across the grid on purpose
  (common random numbers), so corner-*to*-corner comparisons are cleaner
  than corner-*absolute* values.
- **`fs`/`sf` remain dropped**, per DR-0006's duty-cycle-vs-period-jitter
  reasoning and `spec/porting-plan.md` §3.1. This campaign found no reason
  to reinstate them: it measures period jitter at a single node with a
  uniform per-stage injection, which is exactly the case that argument
  covers. That stays contingent on the sampler design, which does not exist
  yet.

## Alternatives considered

### Edit `design/xschem/ro_array_core.sch` to instantiate `N = 53` rings now

- **What**: do literally what issue #10's acceptance criterion says —
  replace the placeholder with the sized value in the schematic.
- **Why plausible**: it is the most direct reading of the criterion, and it
  would leave no gap between the record and the design sources.
- **Why rejected**: `N` is not a parameter in that schematic, it is a
  topology. Going from 2 to 53 rings means 53 enables, 53 separately-routed
  supplies, a 53-input XOR tree, and a sampler input load 26× larger — a
  block redesign whose own trades (area against the `< 0.05 mm²` row, XOR
  tree depth against the combining node's own jitter, per-ring supply
  routing) this campaign measured nothing about. Drawing it on the strength
  of a number carrying 2–4× uncertainty, derived against a **draft**
  raw-rate row, is exactly the "relax the spec to make the result land"
  move `CLAUDE.md` forbids. The criterion is met by *superseding* the
  placeholder — recording it as refuted, with the sized value and its
  derivation — and by filing the rebuild as its own increment, **#13**.

### Report `N` only at gf180-trng's own proposed 2 kbps raw rate

- **What**: size against 2 kbps (`T_s` = 500 µs), where `N = 1` suffices,
  and declare the array sized.
- **Why plausible**: gf180-trng's own raw-rate row moved from a ratified
  "> 1 Mbps" to a proposed 2 kbps for exactly this reason
  (`spec/porting-plan.md` §2.6), so 2 kbps is the more honest
  jitter-energy-derived figure.
- **Why rejected**: this repository's README still declares > 1 Mbps, and
  §2.6 is explicit that sky130-trng should treat gf180-trng's unresolved
  rate/entropy tension as *live evidence*, not as a number to port in either
  direction. Sizing against a rate row this repo has not adopted would
  quietly relax a spec row through the back door. The `N`-vs-`T_s` table is
  reported in full in the reduction record so the trade is visible; picking
  the point on it is a spec decision, not a Builder one.

### Wait for a per-corner device-noise re-measurement before recording anything

- **What**: re-run a `.noise` analysis at every one of the 27 points and
  re-anchor the injected level per corner, then measure jitter.
- **Why plausible**: it removes the single largest systematic in §6 and
  would make `N` good to better than 2–4×.
- **Why rejected**: it is a 27-point second campaign layered on a 30-run
  first one, and it changes none of the four qualitative results (gain
  margin, swing confirmed, binding corner cold, `N = 2` refuted). It is
  filed as follow-up rather than allowed to block a record that is already
  decision-grade for those four.

## Consequences

- **Positive**:
  - DR-0001's two "Revisit if" conditions are both **tested and not
    triggered**: the 1.8 V starved cell has ~12× the gain it needs and
    swings past both rails at every corner measured. The 1.8 V core choice
    survives its own named risk.
  - The entropy-binding corner is a measured sky130 fact
    (`ss`/−40 °C/1.62 V) rather than an inherited assumption, closing
    `spec/porting-plan.md` §2.4's obligation for this block.
  - `design/README.md`'s "Provisional, not sized" table can move four rows
    from "no sky130 measurement exists" to a cited measurement.
  - The reduction is a committed, re-runnable script over committed
    records, so the sizing arithmetic is auditable without re-simulating.

- **Negative / accepted cost**:
  - The block as drawn does not meet its own draft target rows: at 1 Mbps
    and `H0` = 0.5, `ro_array_core.sch` would need `N ≥ 309` rings, which no
    plausible area budget survives. **The rate row and the entropy row
    cannot both hold at this topology.** That is the same unresolved
    rate × entropy × power × area tension `spec/porting-plan.md` §2.6
    flags in gf180-trng, now reproduced independently on sky130 — evidence,
    not a defect introduced here, but it is a real gap between the README's
    target table and the design.
  - `N` carries ~2–4× uncertainty from the fixed injection level. Any
    ratification should read `N = 53` as "tens of rings", and any silicon
    claim must wait for measurement.
  - The `ro_ring5`-vs-`ro_ring11` `Q` ratio exceeds the sizing law's own
    prediction by ~3.3× for reasons this campaign does not explain.

- **Follow-up required**:
  - **The array rebuild and the operating-point decision** — filed as
    **#13**. Choose a point on the `N`-vs-`T_s` trade
    (`sim/ro-array-sizing/records/`'s table), then redraw
    `ro_array_core.sch` at the chosen `N` and stage count, with the
    XOR-tree, per-ring-supply-routing, sampler-loading and area
    consequences evaluated. This record deliberately does not do it.
  - **Per-corner device-noise re-anchoring** — a `.noise` sweep at each grid
    point feeding a per-corner `trnoise()` level, retiring the ~2–4×
    systematic on `Q`.
  - **Multi-seed runs** at (at minimum) the binding corner and nominal, to
    put an error bar on `sigma_1` that is measured rather than assumed.
  - **Explain the stage-count `sigma_1` scaling anomaly** (§4).
  - **Re-check `fs`/`sf`** once a sampler exists, per DR-0006's own
    follow-up and §3.1.
  - **README target-table rows** (raw rate, min-entropy, area) should be
    revisited against §5 — but that is a spec change and an operator action,
    not something this record performs.

- **Revisit if**: a per-corner noise re-anchoring moves `Q` by more than the
  ~2–4× band this record declares; or multi-seed runs show `sigma_1` spread
  wide enough to move the binding corner off `ss`/−40 °C/1.62 V; or the
  raw-rate row is re-ratified at a materially different `T_s`, which
  rescales every `N` in §5 linearly.
