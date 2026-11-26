---
dr: DR-0021-analog-active-power-budget
title: "Analog active power at ff / 1.98 V -- the 500 uW row is not met at the Ts = 20 us study point; options for the operator"
status: Proposed
date: 2026-11-21
deciders: unratified — Proposed by the Builder on #604; ratification is an operator/Champion action
supersedes: n/a (this record proposes a disposition for issue #604's design-iteration finding; it amends nothing by itself)
superseded_by: n/a
related: "#604 (this study), #597 (formal 12-corner PEX evidence), #174 (whole-block power), #201 (idle/leakage), DR-0003 (the N = 4 / Ts = 20 us operating point that fixes the continuous-current term), DR-0010 row 8 and R3 (the target row and the array-only near-bound already recorded), DR-0018 (the idle half of the Power row, Accepted), sim/post-layout-sampler-core/analysis/active-power-budget.md (this record's evidence base)"
---

# DR-0021: analog active power at ff / 1.98 V

## Status

- 2026-11-21: **Proposed.** Not accepted by anyone. This record measures
  nothing itself; it reduces issue #604's measurements into the options the
  operator must choose among. It edits no README row, no spec value and no
  historical verdict.

## Context

Issue #604 exists because `sampler_core`'s analog active power exceeds the
README Power row's `< 500 uW` active bound (analog-partition share) at the
two ff / 1.98 V corners of the four-point post-layout grid — on **both**
legs, pre-layout (schematic) and post-layout (extracted), so a
parasitic-induced regression is ruled out as the primary term.

At the 20 us sampling period in DR-0003 (Proposed), the fleet runs in
`sim/post-layout-sampler-core/corners/ts20u-*/` measured the following
totals with all four rings enabled. Section 2 of `analysis/active-power-budget.md`
gives the ring and shared-VDD currents for each total.

| corner | leg | 20 us total | excess over 500 uW |
|---|---|---:|---:|
| ff / -40 C / 1.98 V | schematic | 519.1 uW | 19.1 uW |
| ff / -40 C / 1.98 V | extracted | 577.2 uW | 77.2 uW |
| ff / +125 C / 1.98 V | schematic | 569.1 uW | 69.1 uW |
| ff / +125 C / 1.98 V | extracted | 599.6 uW | 99.6 uW |

The September 100 ns records used PEX SHA-256 `2bad455e…`, ngspice 46,
and a 5 ps transient step. The 20 us runs used the re-extraction
`2aad0267…`, ngspice 47, and a 50 ps step. Reset-held totals agree within
0.54% across these configurations. This check covers only the 50–250 ns
reset window. Section 1 retains the historical budgets. Section 3 reports
a clock-rate delta only when a 100 ns fleet report at the same temperature
matches the 20 us design, PEX, model library and simulator settings.

All four totals exceed 500 uW at the proposed cadence. The six DFFs share
VDD with the buffers and the XOR tree (`design/sampler_core.spice`), and
the reports give four ring-rail currents plus one shared-VDD current per
leg, so this experiment does **not** isolate the sampler bank's absolute
power; no sampler-specific figure is claimed. The budget lines at the cold
corner (schematic leg, 20 us): ring rails 173.5 uW, shared VDD
(buffers + XOR + six samplers) 345.7 uW.

Design constraints at the measured operating point:

- **Ring duty cycle.** DR-0003's
  entropy basis assumes continuously running rings accumulated over
  Ts = 20 us (`Q_array = 4 * Q_ring_loaded(20 us)` = 1.036x the
  requirement); gating rings between samples destroys the accumulation the
  min-entropy target is derived from.
- **Array size.** DR-0003 §2 gives N_min = 4 at 20 us and N_min = 1 at
  100 us. Power and
  throughput at a redesigned operating point would need verification.
- **The corner is inside the recorded envelope.** DR-0010 row 9 (DR-0010
  is `status: Proposed`) records 1.62-1.98 V and -40...+125 C as the
  envelope; ff / 1.98 V cannot be declared out of scope without amending
  that row.
- **The array-only figure already sits at 94.8 % of the budget at the hot
  corner** (DR-0010 R3: 473.9 uW array-only, ff / 125 C / 1.98 V), leaving
  26.1 uW before the remaining loads of the composed cell. (The
  array-only decks and these decks are different configurations; the
  difference between them is not a measurement of the sampler bank's
  power.) The four 20 us legs exceed 500 uW by 19.1-99.6 uW. A re-sizing
  campaign (ring stage W/L, buffer strength) that recovers that excess
  while re-clearing DR-0002's jitter basis and DR-0003's combining and
  entropy bounds is a re-derivation of the operating point, not a
  "smallest supported iteration", and no issue currently owns it. These
  numbers do not by themselves rule out a periphery-only redesign.

## Decision

**Proposed, for the operator to choose (options P-A / P-B / P-C).** This
record recommends **P-A**.

- **P-A (recommended): amend the analog-partition active bound** to a
  measured-worst-corner-derived figure — `< 650 uW` active, analog
  partition, whole-envelope basis `worst extracted total across the
  12-corner grid` + guardband for silicon-vs-simulation. The guardband
  basis is #597's formal grid, whose worst is 602.6 uW at
  ff / 125 C / 1.98 V, extracted (the earlier same-deck control measured
  603.8 uW; this issue's 20 us re-rate of the same corner gives 599.6 uW
  -- all three agree within 0.7 %, and the grid's formal owner is #597).
  The 47.4 uW allowance is a proposed engineering margin. The grid
  measures the corner maximum; it supplies neither a silicon uncertainty
  bound nor a market comparison. Acceptance requires an operator decision
  on that margin and on the analog allocation within #174's whole-block row.
- **P-B: hold `< 500 uW`** and record a per-corner derogation at
  ff / 1.98 V. Cost: the two corners stay red on every future report with
  no owned path to green; the array-only figure (473.9 uW hot) leaves only
  26.1 uW under 500 uW before the remaining loads. Listed for
  completeness.
- **P-C: open a re-derivation campaign** (ring/buffer sizing against
  DR-0002/DR-0003 bases) targeting recovery of the 19.1-99.6 uW excess. Cost: a
  multi-issue campaign re-opening the DR-0002/DR-0003 basis measurements; no
  guarantee of success (the hot array-only figure leaves 26.1 uW of
  headroom before the remaining loads). This record does not recommend it, but
  names it so the operator sees the full space.

If the operator ratifies P-A, record the analog allocation explicitly in
the spec and Chipalooza proposal. Updating the README whole-block figure
requires the whole-block evidence from #174 and a separate decision.

## Consequences if ratified as proposed

- Any amended analog figure applies to the sampler_core partition.
- The two ff / 1.98 V rows of #597's PEX grid and of the committed
  post-layout controls remain recorded failures against `< 500 uW`; the
  spec change is forward-looking only.
- #174's whole-block characterization gains a stated analog-partition
  allocation to compare with the digital and other loads.
- Silicon characterization (DR-0014) must re-measure the same budget
  lines; the simulation-derived figures stay provisional until then.

## Follow-up required (not done by this record)

1. Collect the two short 100 ns fleet controls and regenerate the clock-rate
   comparison for the operator’s choice among P-A / P-B / P-C.
2. On P-A: document the scope and basis of the analog allocation. Revisit
   whole-block power when #174 lands.
3. #597 keeps ownership of the formal 12-corner PEX table this study's
   ff / 1.98 V rows slot into.
