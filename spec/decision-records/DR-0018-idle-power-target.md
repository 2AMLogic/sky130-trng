---
dr: DR-0018-idle-power-target
title: Idle power target -- worst-corner envelope <= 200 uW for sampler_core
status: Accepted
date: 2026-11-13
deciders: "operator (rjwalters), attended /fleet:decide round 20261111-r14, ruling q54, posted on #446 2026-11-13"
supersedes: "n/a -- fills the README Power row's unset idle target. It relaxes no ratified result, spec value or verdict; the < 500 uW active figure is unchanged."
superseded_by: n/a
related: "#446 (this record), #444 (leakage survey, merged), sim/ro-array-idle-leakage/records/20261106-185750-8deaf42.md, DR-0001"
---

# DR-0018: idle power target

## Status

- 2026-11-13: **Accepted** (operator ruling q54, attended `/fleet:decide`
  round 20261111-r14, option (a)). This record adopts a target. It measures
  nothing and is not a claim that silicon meets it.

## Context

The README Power row left the idle target "set after a sky130 leakage survey".
The survey has landed (PR #444, record
`sim/ro-array-idle-leakage/records/20261106-185750-8deaf42.md`): standby
(rings gated off, sampler idle) power of the pre-layout `sampler_core` across
tt/ss/ff x -40/27/125 C x 1.62/1.8/1.98 V, with `trng_digital` leakage taken
from Liberty `cell_leakage_power`.

| Quantity | Value |
|---|---|
| Combined standby, best corner (ss / -40 C / 1.62 V) | 0.001517 uW |
| Combined standby, worst corner (ff / 125 C / 1.98 V) | 38.04 uW |
| Same worst corner with the 125 C digital extrapolation | 114.9 uW |

The cell library has no view above 100 C, so the 125 C digital figure is a
lower bound; 114.9 uW is a separate, labelled exponential-in-temperature
extrapolation. The figures are simulation-derived and pre-layout.

## Decision

Idle (standby: rings gated off, sampler idle) power of `sampler_core` shall be
**<= 200 uW, as a worst-corner envelope** over the spec's -40 to +125 C and
supply range.

- **The 125 C digital term is counted as the labelled extrapolation** from the
  survey record above (the cell library has no view above 100 C), not as the
  Liberty lower bound.
- **The 1.5x margin behind 200 uW is a stated choice, not a derived one.** It
  is not computed from a variation model; it is headroom the operator chose
  over the 114.9 uW extrapolated worst case.
- The target is simulation-derived and pre-layout, and provisional until
  measured on silicon. It is not a claim that silicon meets it.

## Consequences

- README Power row: idle target becomes <= 200 uW worst-corner envelope,
  citing this record. No other row changes; < 500 uW active is unchanged.
- Post-layout re-verification should recheck standby against this envelope,
  including the 125 C digital term, once a measured or extrapolation-free
  view is available.
