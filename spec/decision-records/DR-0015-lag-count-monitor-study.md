---
dr: DR-0015-lag-count-monitor-study
title: Study of a bounded lag-k match-count online monitor for the periodic/correlated raw streams RCT and APT cannot see
status: Proposed
date: 2026-10-15
deciders: unratified -- Proposed by the Builder on #301; ratification is an operator action
supersedes: "n/a -- this record supersedes nothing and changes no ratified or Proposed spec value, interface, RTL, simulation record or README target-table row. DR-0004 (C_RCT = 81, C_APT = 824, W = 1024, alpha = 2^-40) is untouched."
superseded_by: n/a
related: "#301 (this record), #300 / record sim/digital-section-behavioral/records/20261011-143828-a7af876.md (experiment I, the blind spot), #200 / #288 (injection-lock context), DR-0004 (RCT/APT, section 2), DR-0014 (offline characterization plan), digital/model/lagcount.py, sim/digital-section-behavioral/records/20261015-215152-4d66b80.md (experiment J), sim/digital-synthesis/records/20261015-214950-df2fc8b.md (area study)"
---

# DR-0015: study of a bounded lag-k match-count online monitor

## Status

- 2026-10-15: **Proposed.** Not accepted by anyone. Ratification is an
  operator action; no agent declares this record Accepted.
- This is the **study** the operator authorised on #301 (option a: "a bounded
  DR/design study for an online lag-count/autocorrelation monitor that keeps
  RCT/APT intact"). It derives numbers and makes a recommendation. It adopts
  no RTL, edits no ratified text, and claims no health coverage: the monitor
  exists only as a behavioural model (`digital/model/lagcount.py`) and a
  standalone synthesis prototype
  (`sim/digital-synthesis/prototypes/lagcount_monitor.v`).
- Numbering: DR-0013 is the open proposal for #221 (PR #249) and DR-0014 is on
  `main`, so this record takes DR-0015. (`spec/porting-plan.md`'s
  DR-0015..DR-0022 are gf180-trng's records, not this repository's.)
- Every number below is from a **simulation of synthetic logic stimuli** or a
  behavioural model of the source, or from a pre-layout synthesis estimate.
  All entropy claims are **provisional until measured on silicon**
  (`spec/silicon-characterization-plan.md`, DR-0014).

## Context

Experiment I (#300) drove the ratified RCT/APT with 75 seeded synthetic
streams of known analytic min-entropy. Of the 52 below `H_DESIGN` = 0.5, the
online tests alarmed on 8 and missed 44, including every balanced period-k
stream (k = 2..256) at any flip noise: marginal bias is 1/2 and runs are
bounded by k, so neither RCT nor APT can see it, as SP 800-90B documents.
Injection lock (#200 / #288) is the plausible physical route to such streams.

The question put to the operator was whether to add a serial-correlation- or
periodicity-sensitive online check. The operator authorised a bounded study of
a lag-k match-count monitor. This record is that study.

## What was studied

A bank of `L` lag counters. Lag `j` counts, over a window of `W_L`
comparisons, how often `x[i] == x[i-j]`. An ideal fair source matches at rate
1/2; a period dividing `j` matches at rate 1 (less flip noise `eps`:
`(1-eps)^2 + eps^2`); a sticky chain matches at its stay probability at lag 1.
The monitor alarms (sticky) when any lag's count reaches `C_L` at the end of a
window. Warm-up is `L` samples, so the first possible verdict is at
`L + W_L` samples. Normative definition: `digital/model/lagcount.py`
(`LagCountMonitor`, with a packed batch scanner asserted bit-for-bit equal to it
by `sim/tests/test_health_detection_coverage.py`).

It runs next to RCT/APT and replaces nothing.

## 1. The cutoff: the issue's binomial derivation under-covers, an exact one is used

The method of DR-0004 sections 2.1-2.3 is to take the smallest `C` whose exact
binomial upper tail is at most `alpha` for an i.i.d. source at the min-entropy
floor `H_DESIGN` = 0.5. Applied here (`p = 2^-0.5`, lag match probability
`p^2 + (1-p)^2 = 0.5858`, `alpha` per window `2^-40` split over `L` lags by a
union bound), with the routine cross-checked to reproduce `C_APT` = 824 at
`W` = 1024, it gives for example `C_L` = 717 for `L` = 32, `W_L` = 1024.

**That cutoff is not valid.** The binomial assumes the `W_L` match indicators
are independent. They are independent only for a fair coin. For a biased
source, `[x[i] == x[i-j]]` and `[x[i+j] == x[i]]` share `x[i]`; at `H` = 0.5 the
covariance is 0.0356 against a variance of 0.2427, a 29 % variance excess. The
APT does not have this problem (its indicators are `x[i] == x[0]`, independent
given the reference); a lag count does.

Measured two ways (record `20261015-215152-4d66b80`):

- **Loosened-alpha calibration** (`alpha` = 2^-4, `L` = 16, an i.i.d. source at
  the `H` floor, 10^6 samples): binomial cutoff fails 84 of 976 windows
  (0.086 against a bound of 0.0625); the exact cutoff fails 38 of 976 (0.039).
  Same result at `W_L` = 4096 (21/244 vs 7/244).
- **Analytically at the real operating point**: the exact tail at the
  binomial cutoff exceeds its `2^-40 / L` target by a factor of 930 to 1,400
  (`L` = 8..256, `W_L` = 1024 and 4096), i.e. a true per-window false-alarm
  probability near 2^-30, not 2^-40.

The cutoff used is therefore `C_L` = the smallest `C` with
`Pr(M >= C) <= 2^-40 / L` computed **exactly** for the lag-1 match count of an
i.i.d. source with `P(1) = 2^-0.5` (a two-state Markov-chain DP, verified
against brute-force enumeration and, for a fair coin, against the binomial).
Lag 1 is the heaviest tail over lags (asserted for lags 1, 2, 3, 4, 8, 16, 32 at
`W_L` = 256 in the tests), so
one cutoff covers all `L` lags. It is larger than the binomial's by 17 to 35
counts:

| `L` | `W_L` | `C_L` exact | `C_L` binomial (not used) |
|---|---|---|---|
| 8 | 1024 | 732 | 714 |
| 16 | 1024 | 733 | 716 |
| 16 | 2048 | 1389 | 1364 |
| 32 | 1024 | 735 | 717 |
| 32 | 4096 | 2670 | 2635 |
| 256 | 4096 | 2679 | 2644 |

(`python3 digital/model/lagcount.py` prints the full grid.) Re-derived for the
chosen `W_L`; not copied from gf180-trng.

## 2. False-alarm limit

- **Analytic**: per lag `<= 2^-40 / L`; per window `<= 2^-40` for any **i.i.d.**
  source whose min-entropy is at least `H_DESIGN` (union bound, conservative:
  the lag counts are positively correlated; evaluated at the `H` floor, and
  monotone in bias, which the fair-coin runs below corroborate but this record
  does not prove). At 50 kHz this is a mean time to a false window of
  `2^40 / (50,000 / W_L)` s: about 1,400 years at `W_L` = 2048 and 2,900 years
  at `W_L` = 4096.
- **Simulated** (10^6 samples, seeded): fair coin and an i.i.d. `H` = 0.5 source
  at `L` = 32 / 256, `W_L` = 4096 and `L` = 32, `W_L` = 1024: **0 failing
  windows in all six runs**. The worst lag count seen on the `H` = 0.5 source
  was 2574 against `C_L` = 2670 (`L` = 32, `W_L` = 4096). 2^-40 itself cannot be
  reached by simulation; the loosened-alpha calibration in section 1 is what
  validates the tail derivation.
- **Replay over the sky130 behavioural corner streams** (the 18 Ts = 20 us
  streams, 131,072 samples, `H_est` 0.649..0.819): **0 alarms** at
  (`L` = 16, `W_L` = 2048), (32, 4096) and (256, 4096). Worst lag count over
  every lag and window: 1199 vs 1389, 2363 vs 2670 and 2361 vs 2679, a minimum
  margin of 7.5 % to 9.3 % of `W_L`. This is a model with independent noise
  increments, not silicon; it says the monitor does not trip on the model's
  own source, not that it will not trip on the real one.
- **The bound does not cover correlated sources that are above target.** The
  null hypothesis is an i.i.d. source. A source with serial correlation and a
  true `h` just above 0.5 can trip the monitor: in experiment J, `markov sym
  stay=0.7` (`h` = 0.515, lag-1 match rate 0.7) and the lock mixtures at
  `f` = 0.5 (`h` = 0.500..0.537) alarm at `W_L` = 4096. That is an availability
  cost (a conditioned-path gate on a marginal source), not a safety hole, but
  it means the false-alarm figure above is not a claim about the real source.
  Only silicon can say how much lag-1..L correlation the real raw stream has.

## 3. Coverage

Experiment J reruns the 75 experiment-I streams (same seed and generators,
65,536 samples each; experiment I's output is unchanged by the refactor that
exposes them) through RCT/APT and the monitor over a grid of `L` and `W_L`.
Streams below `H_DESIGN`: 52. Caught by RCT/APT or the lag monitor:

| `L` | `W_L` = 1024 | `W_L` = 2048 | `W_L` = 4096 | still missed (at 2048/4096) |
|---|---|---|---|---|
| 8 | 38 | 38 | 39 | period 16, 64, 256 |
| 16 | 41 | 42 | 42 | period 64, 256 |
| 32 | 42 | 42 | 42 | period 64, 256 |
| 64 | 47 | 47 | 47 | period 256 |
| 128 | 47 | 47 | 47 | period 256 |
| 256 | 51 | 52 | 52 | none |

(Baseline RCT/APT alone: 8 of 52.) The lag monitor alone catches the rest of
each column: every period-`k` stream with `k <= L`, every sticky chain, every
lock mixture (`f` >= 0.5 at the tested noise), because a locked period-2
segment has a high match rate at every even lag.

- **Covered lag range**: lags `1..L`, so periods `k <= L` (and any stream with a
  lag-`j <= L` match rate above `C_L / W_L`). A period beyond `L` is missed *by
  construction*: its match rate at every monitored lag is about 1/2. The
  documented limitation is "no on-chip detection of periods above `L`, covered
  offline by DR-0014's plan". One period of `L` and of `L + 1` is tested at the
  edge (`sim/tests/test_health_detection_coverage.py`).
- **Covered H range** (period-`k`, `k <= L`, flip noise `eps`, per-window
  probability at the stream's own lag; binomial approximation, bounded by the
  simulated grid):

  | `L` | `W_L` | `eps`, `h` alarmed with P >= 0.5 per window | with P >= 0.99 | first verdict |
  |---|---|---|---|---|
  | 16 | 1024 | 0.172, 0.272 | 0.148, 0.232 | 20.8 ms |
  | 16 | 2048 | 0.202, 0.325 | 0.182, 0.291 | 41.3 ms |
  | 32 | 4096 | 0.225, 0.367 | 0.209, 0.339 | 82.6 ms |

  So the reliably covered range is `h` up to about 0.23 (`W_L` = 1024), 0.29
  (2048) or 0.34 (4096). Streams with `h` between that and 0.5 are below target
  and mostly **not** caught (e.g. period-`k`, `eps` = 0.25, `h` = 0.415, alarms
  with probability 2e-4 per window at `W_L` = 4096). This is not an
  implementation defect: a threshold set at the tail of the `H` = 0.5 source
  cannot, at a fixed window, separate a source barely below that floor from it,
  exactly as for the APT's own sensitivity. The simulated grid agrees at the
  tested points (`eps` = 0.2 alarmed at `W_L` >= 2048, `eps` = 0.3 not alarmed).
- **Latency**: `L + W_L` samples to the first verdict; 20.8 ms to 87 ms at
  50 kHz for the configurations above. Even `W_L` = 1024 needs 1,040 samples,
  just past the 1,024-sample start-up test, so the monitor would not gate
  start-up unless that test were lengthened; no such change is proposed.

## 4. Area

Standalone yosys synthesis (`klt synthesize`) of the parallel-counter prototype
against `sky130_fd_sc_hd`, `tt_025C_1v80`, unconstrained (record
`20261015-214950-df2fc8b`), next to the existing `trng_digital` at
22,203.8 um^2 (2,320 cells; record `20260910-001436-a4c3194`):

| `L` | `W_L` | cells | area um^2 | vs `trng_digital` |
|---|---|---|---|---|
| 8 | 1024 | 586 | 5,637.9 | +25 % |
| 16 | 1024 | 1,117 | 10,667.7 | +48 % |
| 16 | 2048 | 1,156 | 11,471.0 | +52 % |
| 32 | 1024 | 2,068 | 19,904.1 | +90 % |
| 32 | 4096 | 2,483 | 23,981.8 | +108 % |
| 64 | 4096 | 4,787 | 46,176.8 | +208 % |
| 128 | 4096 | 9,080 | 88,912.8 | +400 % |
| 256 | 4096 | 20,082 | 185,499.2 | +835 % |

For scale, `design/README.md` budgets the RO array alone at
`< 0.05 mm^2` (50,000 um^2). Area grows about linearly in
`L x (log2 W_L + 1)` counter bits.

**Basis and limits.** Pre-layout cell area of a prototype; no `klt equiv`
proof, no place-and-route, no utilisation overhead, no timing. The RTL's first
alarm sample is checked against the Python model on five streams with Icarus
(`PrototypeRtlMatchesModel`), which supports that the prototype implements the
model, not that the area is final. `digital/rtl/trng_digital.v` is untouched.

**Cost levers not modelled or synthesised** (so no number is claimed):

- A period-`k` stream matches at *every* lag that is a multiple of `k`, so
  monitoring only lags `L/2 + 1..L` (plus lag 1 for sticky chains) still covers
  every period `<= L`, at roughly half the counters; the history register stays
  `L` bits. This follows from the match structure but needs a model run and a
  synthesis before it is a claim.
- A time-multiplexed scheme (one counter, a stored window) needs a clock faster
  than the 50 kHz sample clock, which DR-0004 section 4.3 does not provide.

## Recommendation: do not adopt now

**Do not adopt the monitor, or any RTL for it, on the strength of this study.**
Reasons, each from the numbers above:

1. **The cost is large against what it buys, and the benefit cannot be
   quantified yet.** The smallest configuration worth discussing
   (`L` = 16, `W_L` = 2048, `C_L` = 1389) adds about 11,500 um^2 (+52 % of the
   digital section) and covers periods up to 16 down to `h` of about 0.3. No
   data says what period an injection-locked ring produces; #200 / #288 are
   transistor-level robustness studies and do not yet bracket it. A coverage
   range the operator cannot compare against the failure it is meant to catch is
   not a case for area.
2. **It does not close the gap it was opened for.** Periods above `L` stay
   missed, and sources with `h` between roughly 0.3 and 0.5 are mostly missed
   at any affordable window. What it closes is the specific case of balanced,
   short-period, strongly low-entropy streams (`h` below about 0.3), which RCT
   and APT miss entirely.
3. **Its false-alarm figure is conditional.** It holds for an i.i.d. source;
   a correlated source above target can trip it (section 2). The 18-stream
   replay is encouraging (7.5 % to 9.3 % margin) but is a model.

What this record does establish, for the operator to ratify or not:

- the design: lag counters, derived `C_L`, sticky alarm, window verdict;
- the cutoff must be derived with the dependence-aware tail, not DR-0004's
  binomial, or the false-alarm probability is about 2^-30, not 2^-40;
- if on-chip coverage of the class is wanted, the specification to adopt is
  `L` = 16, `W_L` = 2048, `C_L` = 1389 (about +52 % digital area, first verdict
  41 ms), or `L` = 8, `W_L` = 1024, `C_L` = 732 (about +25 %, periods up to 8,
  `h` up to about 0.23), after the follow-ups below;
- if it is not wanted, the honest statement is the one in option (b) of #301:
  periodic and lock-mixture streams below `H_DESIGN` are not detectable
  on-chip by RCT/APT, and are covered only by offline characterization
  (DR-0014), with the experiment-I and experiment-J tables as the documented
  limitation.

## Follow-ups (not done here, none blocks this record)

- Bracket the period and `h` an injection-locked ring produces (#200 / #288) so
  `L` can be chosen against a failure rather than against a cost.
- Model and synthesise the half-lag-set variant and any shared-adder variant;
  re-run the area study.
- Measure lag-1..`L` autocorrelation of the real raw stream as part of the
  DR-0014 plan before any availability claim.
- If adopted: register-map / alarm-bit plumbing, a start-up interaction rule,
  `klt equiv`, and place-and-route are all still to do and are out of scope here.
- Wire `sim/tests/test_health_detection_coverage.py` into CI (it is not listed
  in `.github/workflows/ci.yml`); PR #231 tracks the guard that would flag it.

## Alternatives considered

- **Take the DR-0004 binomial cutoff as the issue's text describes.** Rejected:
  measured to under-cover by about 1,000x in tail probability (section 1).
- **Full autocorrelation / FFT hardware.** Rejected before running: area, and no
  better on the measured class (a period-`k` stream is already a single high
  match rate at lag `k`).
- **A two-sided test (also flag unusually low match rates).** Not needed for the
  measured class; a period-`k` stream is always high at lag `k`.
- **Relax or change `C_RCT`, `C_APT`, `W`, `alpha`.** Out of scope and not done.

## Self-audit

- No DR-0004 value or text, RTL, synthesis flow or floorplan file is edited;
  the model, harness, prototype and tests are additive.
- Experiment I's harness output is byte-identical before and after the stream
  generator refactor (checked by diffing the two runs).
- Every simulation-derived claim is marked provisional until silicon; no
  statement here is about the fabricated source.
- Records are append-only; none is edited.
