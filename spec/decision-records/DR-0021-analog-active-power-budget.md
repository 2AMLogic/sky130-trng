---
dr: DR-0021-analog-active-power-budget
title: "Analog active power at ff / 1.98 V -- the 500 uW row is unreachable at the ratified operating point; options for the operator"
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
from DR-0003's ratified Ts = 20 us. The two matched fleet runs
(`sim/post-layout-sampler-core/corners/ts20u-*/`, one per failing
temperature, both legs in one deck, netlists and reset stimulus identical
to the committed controls) return, at DR-0003's own rate with all four
rings continuously enabled:

| corner | leg | 100 ns total | 20 us total | delta |
|---|---|---:|---:|---:|
| ff / -40 C / 1.98 V | schematic | 519.2 uW | 519.1 uW | -0.1 uW |
| ff / -40 C / 1.98 V | extracted | 583.6 uW | 577.2 uW | -6.4 uW |
| ff / +125 C / 1.98 V | schematic | 567.2 uW | 567.4 uW | +0.2 uW |
| ff / +125 C / 1.98 V | extracted | 603.8 uW | 598.5 uW | -5.3 uW |

(The 125 C rows cite `analysis/active-power-budget.md`, which regenerates
them from the committed reports; the 100 ns column is the committed
control records `20260908-050034/053634-ef0db50`. Cross-run agreement is
anchored on the stimulus-identical 50-250 ns reset-held window: the 20 us
runs reproduce the controls' totals there to within cross-build
agreement, ~0.1-0.4 %.)

The candidate cause is therefore **refuted by measurement**: the sampler
bank's per-sample dynamic charge is a sub-uW term at either rate
(six samplers, ~10 fF-class nodes, 50 kHz); the overrun is the
**continuous** analog core current — rings plus buffers plus XOR tree —
which the sampling rate does not touch. The budget lines at the cold
corner (schematic leg, 20 us): ring rails 173.5 uW, shared VDD
(buffers + XOR + six samplers) 345.7 uW.

Why no supported design iteration recovers the deficit:

- **Sampling rate / duty-cycling the rings is not available.** DR-0003's
  entropy basis assumes continuously running rings accumulated over
  Ts = 20 us (`Q_array = 4 * Q_ring_loaded(20 us)` = 1.036x the
  requirement); gating rings between samples destroys the accumulation the
  min-entropy target is derived from, and this issue has now measured that
  the sampler side has nothing to give back anyway.
- **N is already entropy-minimal.** DR-0003 §3: N = 4 is the smallest
  array clearing the entropy floor at a round Ts; supply current scales
  linearly with N, but there is no N < 4 to go to at 20 us.
- **The corner is inside the ratified envelope.** DR-0010 row 9 fixes
  1.62-1.98 V and -40...+125 C as the envelope; ff / 1.98 V cannot be
  declared out of scope without amending a ratified row.
- **The array alone already sits at 94.8 % of the budget at the hot
  corner** (DR-0010 R3: 473.9 uW array-only, ff / 125 C / 1.98 V), before
  the six samplers this composed cell adds (~87 uW cold, schematic) and
  before layout parasitics (+6-13 % at these corners). A re-sizing
  campaign (ring stage W/L, buffer strength) that recovers ~80-105 uW
  while re-clearing DR-0002's jitter basis and DR-0003's combining and
  entropy bounds is a re-derivation of the operating point, not a
  "smallest supported iteration", and no issue currently owns it.

## Decision

**Proposed, for the operator to choose (options P-A / P-B / P-C).** This
record recommends **P-A**.

- **P-A (recommended): amend the analog-partition active bound** to a
  measured-worst-corner-derived figure — `< 650 uW` active, analog
  partition, whole-envelope basis `worst extracted total across the
  12-corner grid` + guardband for silicon-vs-simulation (the current worst
  is 603.8 uW at ff / 125 C / 1.98 V, extracted; the grid's formal owner
  is #597). Cost: the Power row moves for the analog partition only;
  whole-block power remains #174's unmeasured row and is NOT claimable
  from these numbers. The justification bar DR-0010 sets ("stronger than
  'the design does not meet it'") is met by the measured refutation
  above: no rate, duty-cycle or array-size lever exists inside the
  ratified operating point.
- **P-B: hold `< 500 uW`** and record a per-corner derogation at
  ff / 1.98 V. Cost: the two corners stay red on every future report with
  no owned path to green; the array-only figure (473.9 uW) shows even a
  sampler-free redesign of the periphery does not close the gap. Listed
  for completeness.
- **P-C: open a re-derivation campaign** (ring/buffer sizing against
  DR-0002/DR-0003 bases) targeting the ~80-105 uW recovery. Cost: a
  multi-issue campaign re-opening ratified-basis measurements; no
  guarantee of success (the hot array-only figure leaves <= 26 uW of
  headroom before the samplers). This record does not recommend it, but
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
