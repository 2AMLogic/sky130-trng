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

Issue #604's batch experiment has now measured the one untested candidate
cause: the sampling rate. Every committed post-layout `sampler_core` deck
clocks the sampler at Ts = 100 ns, a disclosed compute-budget deviation
from DR-0003's Ts = 20 us (DR-0003 is `status: Proposed`; 20 us is the
sampling period this study uses). The two matched fleet runs
(`sim/post-layout-sampler-core/corners/ts20u-*/`, one per failing
temperature, both legs in one deck, netlists and reset stimulus identical
to the committed controls) return, at DR-0003's Ts = 20 us with all four
rings continuously enabled:

| corner | leg | 100 ns total | 20 us total | delta |
|---|---|---:|---:|---:|
| ff / -40 C / 1.98 V | schematic | 519.2 uW | 519.1 uW | -0.1 uW |
| ff / -40 C / 1.98 V | extracted | 583.6 uW | 577.2 uW | -6.5 uW |
| ff / +125 C / 1.98 V | schematic | 567.2 uW | 569.1 uW | +1.9 uW |
| ff / +125 C / 1.98 V | extracted | 603.8 uW | 599.6 uW | -4.1 uW |

(All four 20 us rows are regenerated from the committed reports by
`analysis/active-power-budget.md` section 3; the 100 ns column is the
committed control records `20260908-050034/053634-ef0db50`. Cross-run
agreement is anchored on the stimulus-identical 50-250 ns reset-held
window: the 20 us runs reproduce the controls' totals there to within
cross-build agreement, 0.02-0.54 %.)

The candidate cause is therefore **refuted by measurement**: slowing the
clock 200x leaves all four totals above 500 uW (each leg's total moves by
at most +1.9 / -6.5 uW), so the overrun is not set by the sampling rate;
it is dominated by current that does not scale with it. The six DFFs share
VDD with the buffers and the XOR tree (`design/sampler_core.spice`), and
the reports give four ring-rail currents plus one shared-VDD current per
leg, so this experiment does **not** isolate the sampler bank's absolute
power; no sampler-specific figure is claimed. The budget lines at the cold
corner (schematic leg, 20 us): ring rails 173.5 uW, shared VDD
(buffers + XOR + six samplers) 345.7 uW.

Why no supported design iteration recovers the deficit:

- **Sampling rate / duty-cycling the rings is not available.** DR-0003's
  entropy basis assumes continuously running rings accumulated over
  Ts = 20 us (`Q_array = 4 * Q_ring_loaded(20 us)` = 1.036x the
  requirement); gating rings between samples destroys the accumulation the
  min-entropy target is derived from, and this issue has measured that
  changing the clock rate alone does not bring any leg under 500 uW.
- **N is already entropy-minimal.** DR-0003 §3: N = 4 is the smallest
  array clearing the entropy floor at a round Ts; supply current scales
  linearly with N, but there is no N < 4 to go to at 20 us.
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
  Cost: the Power row moves for the analog partition only;
  whole-block power remains #174's unmeasured row and is NOT claimable
  from these numbers. The justification bar DR-0010 sets ("stronger than
  'the design does not meet it'") is met by the measured refutation
  above: no rate, duty-cycle or array-size lever exists inside the
  Ts = 20 us, N = 4 operating point used in this study (DR-0003,
  `status: Proposed`).
- **P-B: hold `< 500 uW`** and record a per-corner derogation at
  ff / 1.98 V. Cost: the two corners stay red on every future report with
  no owned path to green; the array-only figure (473.9 uW hot) leaves only
  26.1 uW under 500 uW before the remaining loads. Listed for
  completeness.
- **P-C: open a re-derivation campaign** (ring/buffer sizing against
  DR-0002/DR-0003 bases) targeting recovery of the 19.1-99.6 uW excess. Cost: a
  multi-issue campaign re-opening the DR-0002/DR-0003 basis measurements; no
  guarantee of success (the hot array-only figure leaves <= 26 uW of
  headroom before the remaining loads). This record does not recommend it, but
  names it so the operator sees the full space.

On ratification of P-A (or any successor): edit the README Power row's
active figure, update `docs/chipalooza/challenge-4-proposal.md` §4 row D,
and leave every historical verdict and committed record intact (they
correctly report failures against the bound that was in force).

## Consequences if ratified as proposed

- The README Power row's active half moves to the amended figure; the
  idle half (DR-0018, `<= 200 uW`) is untouched.
- The two ff / 1.98 V rows of #597's PEX grid and of the committed
  post-layout controls remain recorded failures against `< 500 uW`; the
  spec change is forward-looking only.
- #174's whole-block characterization gains a stated analog-partition
  budget line to subtract against, instead of inheriting an unreachable
  one.
- Silicon characterization (DR-0014) must re-measure the same budget
  lines; the simulation-derived figures stay provisional until then.

## Follow-up required (not done by this record)

1. Operator choice among P-A / P-B / P-C.
2. On P-A: the README/Chipalooza edits above, and a re-statement of the
   whole-block row once #174 lands.
3. #597 keeps ownership of the formal 12-corner PEX table this study's
   ff / 1.98 V rows slot into.
