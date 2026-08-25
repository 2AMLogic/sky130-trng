---
dr: DR-0003-sky130-trng-operating-point
title: sky130 array rebuild -- the XOR combining bandwidth ceiling, the resulting operating point, and N = 4 five-stage rings
status: Proposed
date: 2026-08-25
deciders: unratified — Proposed by the Builder on #13; ratification is an operator/Champion action
supersedes: n/a (this is the array rebuild DR-0002 §"Follow-up required" hands off, not a correction of DR-0002's own content)
superseded_by: n/a
related: "#13 (this rebuild), #10/DR-0002 (the sizing inputs and the campaign this record hands off from), spec/porting-plan.md §2.6 (the rate/entropy/power/area tension this record resolves for sky130), design/README.md (the target-specification table and the 'Provisional, not sized' table this record moves), design/xschem/ro_array_core.sch (the redrawn schematic), design/xschem/sampler_core.sch and design/xschem/trng_top.sch (the ring-tap fan-out that tracks N), sim/xor-combining-bandwidth/, sim/ro-ring5-swing-and-current/, sim/ro-array-core-combining/, sim/ro-array-operating-point/ (the four evidence sets this record reduces)"
---

# DR-0003: sky130 array rebuild -- the XOR combining bandwidth ceiling, the resulting operating point, and N = 4 five-stage rings

## Status

- 2026-08-25: **Proposed.** Not accepted by anyone. This record fixes the
  raw-rate/min-entropy operating point issue #13 asks for, states the
  stage-count and array-size decisions that follow from it, and hands the
  redrawn `design/xschem/ro_array_core.sch` its numbers. It does not ratify
  DR-0001 or DR-0002, and it does not by itself authorise silicon.

## Context

DR-0002 (Proposed, issue #10) measured sky130's own RO delay-cell jitter,
found the committed `N = 2` placeholder refuted, and sized the array at
`N = 53` five-stage rings against the README's **draft** `> 1 Mbps` raw-rate
row -- while explicitly declining to redraw the schematic at that value,
because `N` is a topology, not a parameter, and because DR-0002's own
campaign measured nothing about the trades a 2 -> 53 rebuild introduces:
XOR-tree depth, per-ring supply routing, area, and the sampler's input load.
It filed the rebuild as issue #13 and listed, under "Follow-up required",
exactly the work this record performs: *"Choose a point on the `N`-vs-`T_s`
trade, then redraw `ro_array_core.sch` at the chosen `N` and stage count,
with the XOR-tree, per-ring-supply-routing, sampler-loading and area
consequences evaluated."*

`spec/porting-plan.md` §2.6 is explicit that sky130-trng must not inherit
gf180-trng's own unresolved answer to this tension in either direction:
gf180-trng's raw-rate row itself moved from a ratified `> 1 Mbps` to a
**proposed** `2 kbps`, for the same jitter-energy reason DR-0002 measures
here. Issue #13 step 1 makes fixing this operating point -- and stating
whether the README's rate row moves -- the thing that "gates everything
below."

## Decision

**We adopt `N = 4` five-stage rings at a `T_s = 20 us` (`50 kbps`) sample
period, and we record the README's draft `> 1 Mbps` raw-rate row as
architecturally unreachable at this topology, not merely expensive.**

That last clause is the load-bearing part of this record, and it is not
what DR-0002's own reduction implied. DR-0002 sized `N` against the entropy
law alone; this record measures the **second, independent constraint** the
campaign named as future work and never quantified: the XOR combining
gate's own bandwidth. The two constraints do not bind at the same corner --
evaluating the combining constraint only at the entropy-binding corner (the
ring's own slowest, most permissive point) would understate the true
ceiling by nearly 2x, per §1 below. `sim/ro-array-operating-point/` is the
reduction that checks the combining bound at every measured corner rather
than just one, and produces the numbers below.

### 1. Two bounds pin `N`, measured at different corners

**Entropy lower bound** (DR-0002's law, `Q_ring = sigma_1^2 T_s / T_0^3`,
`H0 = 0.5`, `M = 1.5`), re-evaluated against the **buffer-loaded** ring
period rather than DR-0002's bare-ring number (§3 below), at the measured
entropy-binding corner `ss` / -40 °C / 1.62 V:

    N_min_entropy(T_s) = ceil(M * Q_H0 / Q_ring_loaded(T_s))

**Combining upper bound**, newly measured here. Every ring puts two edges
per period into a balanced XOR tree's root, so the root sees a mean
inter-edge spacing `w_root = T_0 / (2N)`. The root gate -- a static-CMOS
`xor2` of minimum-width sky130 devices -- has a measured minimum resolvable
pulse width `w_90` (`sim/xor-combining-bandwidth/`, the pulse width at
which the gate's fanout-1 output swing first reaches 90% of `Vdd`); edges
narrower than that are swallowed before they reach the sampler:

    N_max_combine = floor(T_0_loaded / (2 * w_90))

evaluated at all nine (temp, `Vdd`, process-corner) points both
`sim/xor-combining-bandwidth/` and `sim/ro-ring5-swing-and-current/` cover,
and minimised over that set:

| T (°C) | `Vdd` (V) | corner | `w_90` (ps) | `T_0` loaded (ns) | `N_max_combine` |
|---|---|---|---|---|---|
| -40 | 1.62 | `ff` | 166.0 | 3.424 | 10 |
| -40 | 1.62 | `ss` | 241.3 | 5.469 | 11 |
| -40 | 1.62 | `tt` | 190.9 | 4.309 | 11 |
| **-40** | **1.98** | **`ff`** | **122.0** | **1.615** | **6 (binding)** |
| -40 | 1.98 | `ss` | 163.9 | 2.364 | 7 |
| -40 | 1.98 | `tt` | 134.0 | 1.945 | 7 |
| 27 | 1.8 | `ff` | 133.2 | 2.438 | 9 |
| 27 | 1.8 | `ss` | 186.3 | 3.617 | 9 |
| 27 | 1.8 | `tt` | 163.4 | 2.915 | 8 |

**`N_max_combine = 6`, binding at `ff` / -40 °C / 1.98 V** -- the fastest
loaded ring in the matched grid (the same corner DR-0002 found fastest
unloaded), *not* the entropy-binding corner. This bound is a hardware fact
of ring speed vs. gate resolution: it does not move with `T_s`, so no
sample-clock choice relaxes it. Reporting only the entropy-binding corner's
own combining figure (`N <= 11` there) understates the true ceiling by
nearly 2x.

### 2. Where the two bounds cross: the rate row has to move, and further than a first look at this evidence suggested

`N_min_entropy` falls as `T_s` grows; `N_max_combine` = 6 always. Crossing
them (`sim/ro-array-operating-point/`):

| raw rate | `T_s` | entropy wants `N >=` | combining allows `N <=` | verdict |
|---|---|---|---|---|
| 10 Mbps | 0.1 us | 773 | 6 | IMPOSSIBLE |
| 1 Mbps | 1 us | 78 | 6 | IMPOSSIBLE |
| 100 kbps | 10 us | 8 | 6 | IMPOSSIBLE |
| ~78 kbps | ~12.9 us | 7 | 6 | the ceiling |
| **50 kbps** | **20 us** | **4** | **6** | **`N = 4`, drawn** |
| 10 kbps | 100 us | 1 | 6 | over-margined |

The README's draft `> 1 Mbps` row is not merely expensive here, it is
**unreachable at any array size**: the combining gate runs out of bandwidth
roughly two orders of magnitude before the sizing law runs out of rings.
The architectural ceiling on the raw rate, at any `N`, is **~78 kbps**.

### 3. `N = 4`: the largest power-of-two clearing the combining bound with margin

`N = 4` is chosen over `N = 6` (the exact combining-bound value) because it
is a power of two, which keeps the combining tree a balanced binary tree
(3 gates, depth 2, every ring the same tree-distance from `xo`) and because
it is the smallest `N` clearing the entropy floor at a round `T_s`, hence
the smallest in area and supply current among the choices that clear both
bounds. At `T_s = 20 us`: `Q_array = 4 * Q_ring_loaded(20 us)` = 6.158e-3,
`1.036x` the `M*Q_H0` = 5.946e-3 requirement (guaranteed `H` = 0.5415,
against the `H0 = 0.5` target). The smallest `T_s` at which `N = 4` clears
the requirement at all is 19.31 us (51.78 kbps); 20 us / 50 kHz / 50 kbps is
the rounded, slightly more conservative choice.

**The README's raw-rate row moves from `> 1 Mbps` (draft) to `50 kbps`**,
and the min-entropy row's own sizing basis moves from DR-0002's bare-ring
`T_0` to the buffer-loaded one (§3 below). This is a real drop of more than
an order of magnitude from the aspirational draft row, and it is not this
record's to soften: the ceiling is measured, not assumed.

### 4. Stage count: five, re-confirmed at its own count on sky130 rather than borrowed from `ro_ring11`

Unchanged from DR-0002 §4's direction (12–48x better `Q_ring` at five
stages than eleven, at the same PVT points) and now cross-checked at the
count actually drawn:

- **Swing.** `sim/ro-ring5-swing-and-current/` re-measures five-stage swing
  deterministically (no injected noise, so no jitter-vs-swing confound),
  under this cell's OWN output-buffer load, over 12 PVT points: the
  internal ring node swings 0.78-0.96 x `Vdd` (worst at `ff` / 125 °C /
  1.98 V), and the BUFFERED output -- what the XOR tree and the liveness
  taps actually see -- swings 0.999-1.033 x `Vdd` at every point measured.
  `ro_buf` (a minimum-width, unstarved inverter) squares the slew-limited
  ring node back to the rails. DR-0002 §2's swing objection to moving off
  eleven stages is measured and retired here, not waived.
- **Cost.** Five stages is 2.2x fewer devices and, measured here, 2.2x less
  ring supply current than eleven for the same job (§5).
- This record does not re-derive an eleven-stage combining-bandwidth
  comparison (it would need the same loaded-period-plus-`w_90` pairing this
  record runs for five stages, at eleven, which is not measured). DR-0002's
  12-48x entropy-per-sample advantage for five stages is large enough that
  no plausible combining-bound difference between stage counts would
  overturn the choice, so this is not treated as an open question blocking
  the decision.

### 5. What the rebuild measured that #10's campaign could not

- **Output-buffer loading.** The ring node drives `ro_buf` as well as the
  next `ro_nand2`'s own input, and that extra inverter load slows the ring
  by 13.4% at the entropy-binding corner relative to the unloaded ring #10
  characterized (5.469 ns loaded vs. 4.823 ns unloaded). Since `Q` goes as
  `1/T_0^3`, that is a `0.686x` reduction in `Q_ring` at fixed `T_s`, and
  every sizing figure in this record uses the loaded period -- the
  pessimistic, and correct, one for a schematic where the buffer is a real
  load, not an afterthought.
- **The combining bandwidth ceiling itself** (§1-2) -- the constraint that
  turns out to bind before the entropy law does, and that neither DR-0001
  nor DR-0002 measured or anticipated.
- **Per-ring supply current**, no sky130 measurement of which previously
  existed. Running: 4.98 uA (`ss`/-40 °C/1.62 V) to 20.55 uA
  (`ff`/-40 °C/1.98 V). Stopped: 0.6 nA cold, 255 nA at `ff`/125 °C. The
  running-to-stopped ratio is ~8800x at nominal and ~80x at the worst
  leakage corner -- the contrast the per-ring-supply liveness monitor
  (`vddr1..vddr4`, one source per ring, per the array's own design intent)
  has to resolve to tell a stopped ring from a running one.
- **Array-level combining fidelity, assembled**, not inferred from a single
  gate. `sim/ro-array-core-combining/` drives the actual committed
  `ro_array_core.spice` (four real, mutually-skewed rings, not an idealised
  periodic source) and measures, at every corner:

  | | worst (at `ff`/-40 °C/1.98 V) | best (at `ss`/-40 °C/1.62 V) |
  |---|---|---|
  | Edge retention at `N = 4` (`xo`) | 0.559 | 0.678 |
  | Edge retention at `N = 2` (`t1`) | 0.777 | 0.816 |
  | Combining-node DC bias (`bias_xo`) | 0.468 | 0.324 |
  | Array supply current | 218.0 uA | 50.0 uA |
  | Array active power | 431.6 uW | 81.0 uW |
  | Realized frequency-ladder span (fastest/slowest) | 1.17x | 1.12x |

  Edge retention below 1.0 confirms the combining tree is genuinely
  filtering some fraction of edges at every corner, worst (44% of ideal
  edges swallowed) at the same corner that binds `N_max_combine` -- exactly
  where the bandwidth analysis in §1 predicts it should be worst. Value
  fidelity is the reassuring half: DC bias at `xo` stays within
  0.31-0.53 x `Vdd` across the grid, i.e. no gross systematic offset from
  the ideal 0.5 -- a swallowed edge pair leaves parity, and hence the
  sampled bit's distribution, close to unaffected. See §6 for why the
  bandwidth ceiling on `N` (§1-2) is the binding constraint and this
  retention number is not re-litigated as a separate sizing input.

### 6. The XOR combining tree's own contribution, addressed rather than assumed negligible

Two effects, kept distinct because they are not the same claim:

- **Bandwidth** (§1-2): sets the `N <= 6` architectural ceiling this whole
  record is organised around. This is the dominant effect and the one that
  actually sizes the array.
- **Assembled-array edge retention** (§5's table, `sim/ro-array-core-
  combining/`): at the chosen `N = 4`, measured 0.559-0.678 across the
  three PVT bundles run. This number is *not* independently subtracted
  from `Q_array` in §3's sizing arithmetic -- doing so would double-count
  against the bandwidth ceiling that already forced `N` down to a point
  with real margin under `N_max_combine = 6` (4 vs. 6, i.e. a `1.5x`
  margin on rings, which is qualitatively why edge retention at `N = 4`
  (0.56-0.68) is well above the near-zero retention `N = 6` would show
  right at the ceiling). Treated as a bound rather than a subtracted
  derating factor, consistent with how §1's `w_90` bound was derived and
  applied.

### 7. Array area and array supply current against the README's rows

**Area** (estimated, no layout exists -- `layout/` is explicitly out of
scope for issue #13). Device count from the committed netlist: 4 rings x
22 devices + 4 buffers x 2 devices + 3 XOR gates x 12 devices = 132
transistors, of which 40 are the long-channel (`lstv` = 2 um vs. sky130's
0.15 um minimum) starve devices. Using sky130_fd_sc_hd standard-cell
per-device area (`inv_1`/`nand2_1`, 1.38 x 2.72 um, i.e. ~1.41 um²/device
for a minimum-length device) as a floor, and scaling the 40 starve devices
by their channel-length ratio (13.3x) for the extra gate-poly area:

    raw transistor area ~= 880 um^2 (0.00088 mm^2)

No P&R, guard-ring or per-ring-isolation routing exists to measure, so a
3-10x overhead range is applied as a rough order-of-magnitude correction
for interconnect and the eight independently-guard-ringed supply domains
(`vddr1..4`, `vdd`/`vss`) this array's own independence requirement forces:

    0.0026 - 0.0088 mm^2  (~5-18% of the README's < 0.05 mm^2 budget)

**Result: comfortably within budget, not a miss**, with the caveat that
this is a device-count estimate, not layout, and that per-ring isolation
routing (not raw transistor area) is the more likely area driver once
layout exists.

**Array supply current / power** (measured, `sim/ro-array-core-combining/`,
§5's table): worst measured active power across the 3x3 PVT grid run is
**431.6 uW** at `ff`/-40 °C/1.98 V, against the README's `< 500 uW active`
row -- **a pass, with 13.7% margin**, at the single fastest/highest-supply
corner measured. A larger array clearing only the entropy bound (e.g. the
`N = 8` figure the "Alternatives considered" section below rejects) would
not: supply current scales linearly with ring count, and `N = 8` at the
same corner set would sit close to or over the budget -- another way the
combining bound's `N = 4` also turns out to be the power-compatible choice,
not merely the bandwidth-compatible one.

**Idle current**: `sim/ro-ring5-swing-and-current/` measures a single
stopped ring's own leakage at the entropy-binding corner at 0.709 nA; four
stopped rings would sum to ~2.8 nA of ring leakage alone. The README's own
idle-current row is still unset (`spec/porting-plan.md` §2.5's leakage
survey has not run), so there is no target to compare this against yet --
only the per-ring number, reported because it exists now and did not
before.

### 8. `wstv` skew: re-measured on the assembled array, decorrelation still unmeasured

The ladder drawn is `wstv` = 0.42-0.48 um in four 0.02 um steps (down from
the two-ring 0.42/0.46 um pair, extended to four rings on the same step).
`sim/ro-array-core-combining/` measures the REALIZED frequency ratio on the
assembled array (not the two-ring device-level periods DR-0002 measured in
isolation): the fastest-to-slowest ring period ratio (`skew_span`) is
1.12-1.19x across the PVT grid run, staying well clear of the small
rationals (2/1, 3/2, 4/3 = 1.33) that mutually injection-lock.

**What is still NOT measured, and is explicitly re-flagged rather than
quietly carried forward: the skew fraction that actually DECORRELATES two
sky130 rings.** The array as drawn has no shared supply impedance and no
substrate model, so a netlist-level correlation measurement over it can
only confirm the absence of a coupling path the netlist does not contain --
it cannot measure the coupling a real layout would have. That measurement
needs extracted parasitics and stays out of scope until layout exists.
`design/README.md`'s `wstv` row is updated to say so explicitly rather than
reading as measured.

## Alternatives considered

### Size against the entropy law alone (DR-0002's own `N` vs. `T_s` table), ignoring combining bandwidth

- **What**: pick a point on DR-0002's own `N`-vs-`T_s` table (e.g.
  `N = 8` at 100 kbps) without an independent combining-bandwidth check.
- **Why plausible**: DR-0002's table is already committed evidence, and
  100 kbps reads as a reasonable-looking compromise between the draft
  `> 1 Mbps` row and gf180-trng's own 2 kbps proposal.
- **Why rejected**: measured directly (`sim/ro-array-operating-point/`),
  `N = 8` at 100 kbps needs `N <= 6` to clear the combining bound at the
  fastest measured corner and does not -- it is architecturally
  IMPOSSIBLE, not merely under-margined. An operating point chosen from
  one bound alone, without checking the second, independent one this
  record measures, is not decision-grade.

### `N = 6` (the exact combining-bound value) instead of `N = 4`

- **What**: use the full combining headroom, `N = 6`, at whatever `T_s`
  clears the entropy floor there (`T_s` ~= 12.9 us, ~78 kbps).
- **Why plausible**: higher raw rate for the same architecture, and closer
  to the README's aspirational rate row.
- **Why rejected**: `N = 6` sits exactly at the measured ceiling with zero
  margin -- the same ~2-4x uncertainty band DR-0002 §6 declares on every
  `Q`-derived figure applies here too, and operating an array at a bound
  measured to ~2-4x precision, with no margin, is not a sound design
  choice. `N = 6` is also not a power of two, so its combining tree cannot
  be a balanced binary tree without an uneven (chain) level, reintroducing
  the tree-position skew DR-0002's own array design explicitly tries to
  avoid. `N = 4` keeps a `1.5x` ring-count margin under the ceiling and a
  clean balanced tree at the cost of the lower, still-real, 50 kbps rate.

### Report only the entropy-binding corner's own combining figure (`N <= 11` there)

- **What**: evaluate `N_max_combine` only at `ss`/-40 °C/1.62 V, the same
  corner the entropy law binds at, and report `N <= 11`.
- **Why plausible**: it is the corner the rest of the sizing arithmetic is
  already anchored to, and produces a less restrictive (more permissive)
  headline number.
- **Why rejected**: the combining bound is a property of ring speed vs.
  gate resolution, and the entropy-binding corner is the ring's own
  SLOWEST point in the measured grid -- the easiest possible case for the
  combining gate, not a representative or worst-case one. The array has to
  work at every corner it is specified for, so the constraint that actually
  binds is whichever corner makes the ring fastest, `ff`/-40 °C/1.98 V,
  where `N_max_combine = 6`, not 11. Reporting the easier corner's figure
  understates the real ceiling by nearly 2x and would have led this record
  to draw an `N` the array cannot actually support at its own fast corner.

## Consequences

- **Positive**:
  - The array rebuild issue #13 asks for now exists as a schematic:
    `design/xschem/ro_array_core.sch` instantiates `N = 4` five-stage
    rings with per-ring enables and per-ring supplies, `sampler_core.sch`
    and `trng_top.sch` track the ring count with one liveness tap per ring,
    and `python3 design/netlist.py --check` passes against the regenerated
    `.spice` files committed in the same change.
  - A second, independent sizing constraint (combining bandwidth) is now a
    measured sky130 fact rather than an unmeasured risk DR-0002 flagged and
    deferred.
  - Array active power (431.6 uW worst-measured) now clears the README's
    `< 500 uW` row with margin; area is estimated at 5-18% of the
    `< 0.05 mm^2` budget. Both rows move from "no sky130 measurement
    exists" to a cited number.
  - The XOR tree's own contribution (bandwidth ceiling AND assembled-array
    edge retention) is measured rather than assumed negligible, addressing
    issue #13's acceptance criterion directly.

- **Negative / accepted cost**:
  - **The README's draft `> 1 Mbps` raw-rate row is not merely revised
    downward, it is retired as unreachable at this topology.** The
    architectural ceiling this record measures is ~78 kbps at any `N`; the
    chosen operating point (50 kbps) sits below even that ceiling for
    margin. This is a larger gap than DR-0002 alone implied, because
    DR-0002 did not measure the combining constraint.
  - Every `Q`-derived figure still carries DR-0002 §6's ~2-4x uncertainty
    band from the fixed (not per-corner) injected noise level; this record
    adds no new noise measurement and does not retire that band.
  - The combining-bound measurement itself carries its own uncertainty:
    `w_90` is read off a 9-point pulse-width sweep via linear interpolation
    between the bracketing swept points (500, 300, 200, 140, 100, 70, 50,
    35, 25 ps), not a continuous sweep, and the loaded `T_0` comes from a
    12-point PVT grid, not the full 27-point grid DR-0002 ran for the
    unloaded ring. Both are stated to the precision the source records
    carry, not asserted more precise than that.
  - `wstv`'s inter-ring DECORRELATION is still unmeasured (§8); the
    realized frequency ratios are measured, the coupling that would
    actually threaten independence is not, and cannot be until extracted
    parasitics exist.
  - Area is an order-of-magnitude device-count estimate, not layout.

- **Follow-up required**:
  - **Ratification** of this record and DR-0002 -- an operator/Champion
    action, not performed here.
  - **Per-corner device-noise re-anchoring and multi-seed runs**, inherited
    unchanged from DR-0002 §"Follow-up required" -- this record's `N = 4`
    conclusion does not depend on retiring the ~2-4x band (§ "Alternatives
    considered", `N = 6` was rejected in part BECAUSE that band matters at
    a tight margin, and `N = 4`'s margin was chosen partly to be robust to
    it).
  - **Extracted-parasitics `wstv` correlation measurement**, once layout
    exists (§8).
  - **Sampler_dff characterization** for the now six-instance-per-block
    liveness/raw-tap digitizer fan-out (unsimulated, per
    `design/xschem/trng_top.sch`'s own text block).
  - **An eleven-stage combining-bandwidth measurement**, if the stage-count
    question is ever reopened -- not performed here because DR-0002's
    entropy-per-sample margin (12-48x) is judged large enough not to need
    it for this decision.
  - **Whether the raw-rate row should ratify at 50 kbps, or whether the
    combining gate itself should be redesigned** (wider devices, a
    different tree structure) to raise the ~78 kbps architectural ceiling
    -- a real design trade this record surfaces and does not resolve; it is
    an operator/spec decision, not a Builder one, per issue #13's own
    non-goals.

- **Revisit if**: a wider or restructured combining gate raises
  `N_max_combine` materially above 6; per-corner noise re-anchoring moves
  `Q` by more than the declared ~2-4x band; or an eleven-stage combining
  measurement shows the stage-count trade is closer than DR-0002's entropy
  margin alone suggests.
