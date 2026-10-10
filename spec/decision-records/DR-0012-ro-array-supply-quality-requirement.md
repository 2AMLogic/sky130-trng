---
dr: DR-0012-ro-array-supply-quality-requirement
title: RO-array supply-quality requirement (static droop, slow ripple, RF ripple) from the #200 supply-perturbation evidence -- measured brackets, proposed limits, three options, one recommendation
status: Proposed
date: 2026-10-10
deciders: unratified -- Proposed by the Builder on #208; ratification is an operator action
supersedes: "n/a -- this record supersedes nothing and changes no ratified or Proposed spec value. It does not edit DR-0003's operating point, N = 4, the N_max_combine ceiling, or any README target-table row."
superseded_by: n/a
related: "#208 (this record), #200 (evidence, closed), #184 (extraction, closed), #174 (whole-block post-layout characterization), #221 (local mismatch / entropy floor -- a different question), #217 (CI coverage for the ripple reducer; related, not a prerequisite), DR-0002, DR-0003, DR-0005, DR-0006, DR-0010, sim/ro-array-supply-perturbation/README.md, sim/ro-array-supply-perturbation/records/20261009-000500-28d3690.md, sim/ro-array-supply-perturbation/records/20261009-000459-28d3690.md"
---

# DR-0012: RO-array supply-quality requirement

## Status

- 2026-10-10: **Proposed.** Not accepted by anyone. Ratification is an
  operator action; no agent declares this record Accepted (same status
  handling as [DR-0010](DR-0010-target-table-reconciliation.md)).
- Documentation only. No spec target, circuit, simulation or evidence file is
  changed by this record. Any option below that relaxes or adds a target is
  **explicitly pending ratification**.
- All evidence cited is **simulation-derived, pre-layout, deterministic and
  provisional until silicon**. It is a T0-shift and injection-lock
  robustness result, **not** an entropy claim: `sigma_1` was not re-measured
  under ripple.

## Evidence base

Two committed records from the #200 campaign (slug
`ro-array-supply-perturbation`), both at repo commit `28d3690`, both on the
pre-layout `design/ro_array_core.spice` with ideal behavioural sources:

- ss / -40 degC / 1.62 V (the DR-0002 entropy-binding corner):
  [`20261009-000500-28d3690.md`](../../sim/ro-array-supply-perturbation/records/20261009-000500-28d3690.md)
- ff / -40 degC / 1.98 V (the DR-0003 combining-binding corner):
  [`20261009-000459-28d3690.md`](../../sim/ro-array-supply-perturbation/records/20261009-000459-28d3690.md)
- Campaign definition and caveats:
  [`sim/ro-array-supply-perturbation/README.md`](../../sim/ro-array-supply-perturbation/README.md)

Closed prerequisites, verified 2026-10-10 by GitHub REST read: #200 and #184
are both closed. #184 is therefore not an outstanding prerequisite; however,
closing the extraction issue does not by itself supply post-layout
supply-impedance evidence, which remains separate work (see Follow-ups).

### Measurement conventions (what the numbers mean)

| Item | As recorded |
|---|---|
| Where ripple is applied | Common-mode, the same sinusoid on `vdd` and on `vddr1..vddr4` (five behavioural rails). Per-ring uncorrelated (independent) ripple was **not** run (campaign README, Limits). |
| Amplitude units | **pk** (peak, one-sided), per the record column "amp (mV pk)": 10, 50, 100, 200 mV. Not pk-pk. A 10 mV pk tone is 20 mV pk-pk. |
| Waveform | Sinusoid only. Arbitrary waveforms (steps, bursts, switching-correlated ripple) were not run. |
| Frequencies | Each ring's own frequency, each ring +0.5 %, 0.9 x f1, 1.1 x f4, ladder mean /2 and /3, 2 x ladder mean, 10 MHz; plus a quasi-static family. ss ladder 184.3 / 191.7 / 199.2 / 207.0 MHz; ff 626 / 661 / 696 / 733 MHz (README, "What was run"). |
| Phase | Transient tone rows use the testbench's own start phase; no phase sweep. The quasi-static family covers phase by evaluating the supply at the sine's extremes and Gauss-Chebyshev nodes (`dv = +-A, +-0.866 A`) for A = 10 and 50 mV only. Arbitrary tone phase against the sampling instant is **not** established by this campaign. |
| PVT | Exactly two points, both -40 degC: ss/1.62 V and ff/1.98 V. tt was not run; no temperature or voltage axis beyond these. |
| Noise | None injected (deterministic). Robustness measurement only. |
| Criteria | DR-0003's own margins: no ring/pair injection LOCK; `Q_array` ratio >= 1/1.036 (the `T0^-3` term only); `bias_xo` inside DR-0003's 0.31-0.53 band. |

### The five regimes, kept distinct

1. **Static droop.** A DC offset below nominal. Judged at the trough Q.
2. **Slow ripple** (slower than the sample interval). The sample interval is
   20 us at 50 kbps; the sample sees an instantaneous supply, so it is judged
   at the trough Q, like static droop. Record label: "Ripple slower than the
   sample interval, or static droop (trough Q)".
3. **Sample-spanning ripple** (a sample interval spans at least one ripple
   cycle; ripple "far below the ring frequency, f_rip >~ 50 kHz"). The
   committed quasi-static family reduces this with the **cycle-averaged** Q
   (`Q_avg`), not the trough. The record's own definition: "Q_avg = cycle
   average of the per-node Q ratio (applies when a sample interval spans >= 1
   ripple cycle); Q_worst = trough node (a slower ripple, or a static
   droop)".
4. **RF ripple** (10 MHz up through the ring ladder and 2 x ladder).
   Injection LOCK, period modulation and Q judged on edge-time windows; Q is
   cycle-averaged.
5. **Combining-node bias.** `bias_xo` = `<v(xo)>/vnom` against DR-0003's
   0.31-0.53 band. This is a separate criterion that can fail while LOCK and Q
   pass.

**Correction carried into this record.** The issue's trigger text assigned
"50 kbps-synchronous ripple" to the trough. That is not the committed
reduction's rule: the recorded model uses cycle-averaged Q where a sample
interval spans at least one ripple cycle and trough Q only for slower ripple
or static droop. Any use of the trough for ripple that is merely
sample-synchronous is an **additional conservative phase/window assumption
of this record**, labelled as such wherever it is used below; it is not a
campaign result.

## Measured brackets (from the records; nothing here is a design limit)

### Static droop and slow ripple (trough Q)

| | ss / 1.62 V | ff / 1.98 V |
|---|---|---|
| Static droop at which Q falls to 1/1.036 (interpolated) | **3.93 mV** below nominal | **7.43 mV** below nominal |
| 10 mV pk, trough Q (quasi-static family) | Q_worst 0.9121, FAIL | Q_worst 0.9534, FAIL |
| 50 mV pk, trough Q | Q_worst 0.6215, FAIL | Q_worst 0.7820, FAIL |
| Tolerance headline (trough Q) | no tolerance found at 10 mV | no tolerance found at 10 mV |
| Per-ring period modulation at 10 mV, quasi-static | about -3.02 to -3.07 % | about -1.56 to -1.60 % |

Basis: the interpolated figures are as printed in the two records, under the
stated T0-only Q model with `sigma_1` unchanged. Their meaning is that
DR-0003's `Q_array` margin (sized at `N = 4`, 1.036 x `M*Q_H0`) corresponds to
a few millivolts of supply at the binding corners.

### Sample-spanning ripple (cycle-averaged Q)

| | ss / 1.62 V | ff / 1.98 V |
|---|---|---|
| 10 mV pk, Q_avg | 1.0017, PASS | 1.0004, PASS |
| 50 mV pk, Q_avg | 1.0429, PASS | 1.0098, PASS |
| Headline | >= 50 mV pk tested-safe (largest amplitude tested; upper bound not found) | same |

Cycle-averaged Q stays above 1 in the recorded family (the campaign README
attributes this to the convexity of `T^-3`). This is a statement about the T0
term of Q only.

### RF ripple (tone rows)

| | ss / 1.62 V | ff / 1.98 V |
|---|---|---|
| LOCK + Q only | >= 10 mV pk, < 50 mV pk (bracketed) | >= 10 mV pk, < 50 mV pk (bracketed) |
| LOCK + Q + BIAS | >= 10 mV pk, < 50 mV pk (bracketed) | **no tolerance found at 10 mV** |
| First LOCK | 50 mV pk: all four rings flagged LOCKED at a tone 0.5 % off the ring's own frequency (pull 0.61 to 0.89); 100 mV pk also 1:2 (ring 2 at 2 x ladder mean); 200 mV pk neighbouring rings locked and a new ring-1/ring-2 pair lock | 50 mV pk: ring 1 at +0.5 % (pull 1.31); 100 mV pk ring 4 (+0.5 %); 200 mV pk rings 3 and 4 and 1:2 |
| First bias excursion outside 0.31-0.53 | 100 mV pk (`1.005*f2`, 0.5479) | 10 mV pk (e.g. `f1` 0.5530, `f3` 0.5594) |

Notes that bound these results:

- At ff the clean baseline `bias_xo` in the 60 ns-to-stop window is 0.5246,
  at the upper edge of the band, so the ff bias verdict is dominated by band
  proximity (campaign README, Criteria). It is a failure of the criterion at
  the smallest tested RF amplitude, not evidence that 10 mV pk ripple causes a
  large bias shift (the recorded bias shifts vs clean on the failing 10 mV rows are +0.010 to +0.035).
  It is still bounded as a failure here, not described as a pass.
- Tones placed exactly on a ring frequency are **UNRESOLVED** (lock vs
  coincidence) at the 40-edge window's ~0.25 % detuning resolution. "No lock
  at 10 mV" is therefore shown only for tones >= 0.5 % off a ring frequency.
  Eleven ss rows and nine ff rows are UNRESOLVED.
- Amplitudes tested were 10, 50, 100 and 200 mV pk only. The brackets are
  brackets; no threshold between 10 and 50 mV was located.
- `sigma_1` unchanged; the ring edge-time floor is 0.05-0.4 % pk period
  modulation (ss) and 0.14-0.40 % (ff), a timestep artifact.
- The negative control (current into ring 2's internal node) fired on the
  decisive +2 % control in both corners, so the lock detector is not blind.

### What the records do not establish

- A universally bias-safe 10 mV limit. At ff, LOCK + Q alone gives the 10-50
  mV pk bracket, but with bias included the record says "no tolerance found
  at 10 mV". Any proposed limit below 10 mV is an **engineering hypothesis
  requiring validation**, not a measured all-criteria safe threshold.
- Behaviour for independent per-ring ripple (only common-mode was run).
- Arbitrary waveform or phase guarantees.
- Any entropy or `sigma_1` consequence.
- Anything on a real supply network: shared supply impedance is DR-0006's
  first-named, still-unmeasured coupling mechanism.

## The proposed supply-quality budget (proposed limits, not measured)

This section is a proposal that separates *DC error*, *slow droop* and *RF
ripple*. Every number is a design hypothesis derived from the brackets above
and labelled as such.

1. **DC error plus slow droop (regimes 1-2), per ring rail `vddr1..vddr4`.**
   The measured exhaustion points are 3.93 mV (ss) and 7.43 mV (ff) *below
   nominal*, with nothing left for any other term. The issue's illustrative
   "well inside about +-4 mV at 1.62 V" is therefore not itself a safe budget:
   at the ss corner a 4 mV droop already crosses the 3.93 mV exhaustion
   point. A budget must be a **fraction** of 3.93 mV, one-sided
   (droop below nominal is what costs margin), and must cover regulator
   set-point error, load regulation, IR drop through the supply network and
   temperature drift **together**. Proposed form: a single stacked allowance,
   with the number to be set by the operator once the rail-conditioning item
   below names a structure; this record deliberately proposes only that the
   stack be below 3.93 mV with a stated margin and not a specific value.
   For scale only: a stack limited to about half the ss exhaustion point
   would be ~2 mV; this is arithmetic on the record's figure, not a measured
   or validated number.
2. **Sample-spanning ripple (regime 3).** Measured as tolerated to 50 mV pk
   tested-safe by cycle-averaged Q. Proposed use: do **not** claim this as a
   supply-quality allowance, because (a) it holds only where the sample
   interval spans >= 1 ripple cycle, (b) the sample instant relative to the
   ripple phase is not controlled, and (c) the trough of such a ripple
   behaves like static droop for any ripple period near or above the sample
   interval. Proposed conservative assumption of this record (not a campaign
   result): treat the *peak low-side excursion* of slow and
   sample-comparable ripple as consuming the same DC-plus-slow-droop stack of
   item 1.
3. **RF ripple at and around ring-ladder frequencies (regime 4), pk, on
   `vddr1..4`.** Measured bracket: >= 10 mV pk and < 50 mV pk by LOCK + Q;
   with bias, ss keeps the same bracket and ff has no tolerance found at 10
   mV. Proposed limit is "at or below 10 mV pk" as a hypothesis only for LOCK
   and Q, with the ff bias criterion explicitly **not** passed at 10 mV. A
   smaller figure (the hypothesis space is anything below 10 mV pk) needs
   validation; a figure of 10 mV or more is not supported by a bias-inclusive
   ff record. The ring-ladder bands are about 180-210 MHz (ss) and 620-730
   MHz (ff), and 2 x those.
4. **Combined statement.** The three terms are not additive in a
   demonstrated way: static droop was measured on the Q term, RF ripple on
   lock/bias/Q, and no combined (DC + ripple together) run exists. Until one
   does, the budget is three separate caps plus an explicit
   "combination not validated" caveat.

### Why a concrete regulator or filter topology cannot be certified yet

The evidence is ideal-source: five behavioural rails with zero source
impedance and no substrate or shared-network coupling. It shows how the rings
respond to a given voltage at their supply pins, but not how much voltage
appears there. Supply impedance, decoupling resonance, supply-to-substrate
coupling, switching current from the digital section and per-ring
uncorrelated ripple are all absent. A regulator or RC filter corner chosen
from these results would be a guess about the very quantity (the voltage at
the pin) the campaign took as given. Ideal-source results can set a *target
at the ring pins*; they cannot certify a topology that must be shown to meet
it.

## Options

### A. Rail conditioning and isolation of `vddr1..4` (recommended)

A dedicated regulator and/or RC filter (with decoupling) on `vddr1..4`,
with the filter corner set well below the ring-ladder band and chosen
relative to the 50 kbps sample rate, plus physical isolation of the array
rail from the digital section (today the digital section shares no rail with
the array *only by netlist*, not by layout).

- Pros: attacks the cause; keeps `N = 4`, the DR-0003 operating point and
  every committed array evidence set unchanged; separable and verifiable as a
  block.
- Costs: area and power for the regulator/filter (both are already open
  targets in [DR-0010](DR-0010-target-table-reconciliation.md)); a regulator
  adds its own noise and its own supply-quality problem; a filter corner low
  enough to attenuate ~180-730 MHz ripple but high enough not to add
  settling or droop at the 50 kbps sample clock must be shown, not assumed;
  possible extra supply pads.
- Unresolved validation: regulator or filter structure, its output impedance
  at ring frequencies, and the voltage actually appearing at `vddr1..4` in
  the layout.

### B. Operating point or array change (wider Q margin)

Raise the Q margin by changing `N` and/or the nominal supply, so that the
margin spans more than a few millivolts.

- Pros: no new analog block.
- Costs: `N` is bounded above by DR-0003's `N_max_combine = 6`
  (binding at ff / -40 degC / 1.98 V); DR-0003 already sized `N = 4` with a
  1.5 x ring-count margin under that ceiling, so margin gained by raising `N`
  consumes ceiling margin that DR-0003 spent deliberately. **This record
  preserves the DR-0003 combining ceiling and does not propose exceeding
  it.** A higher nominal supply moves the ff combining corner and the leakage
  and reliability envelope (DR-0001) and re-opens DR-0003's operating-point
  derivation. Because T0 shifts ~3 %/10 mV at ss, even a wider margin buys
  only tens of millivolts, not a regulation substitute. Any change here
  relaxes or alters a ratified DR-0003 quantity and is **pending
  ratification**.
- Unresolved validation: re-derivation of DR-0003's operating point; not
  attempted here.

### C. Environmental assumption plus monitor

Document the supply-quality limit as an assumption on the integrating system
and add a monitor (for example a supply-droop or ring-frequency check feeding
the existing alarm path).

- Pros: cheapest on silicon, honest about what the block cannot control.
- Costs: transfers the problem to an unspecified integrator; a limit of a few
  millivolts is far tighter than a typical external rail; a monitor adds
  design and verification scope and is blind to RF ripple and to bias shifts
  unless purpose-built; relaxes the block's standalone claim, which is
  **pending ratification**. Whether DR-0004's health tests would detect a supply-induced T0 shift
  is not shown by any committed evidence.
- Unresolved validation: what the monitor would measure and its thresholds.

### Recommendation

**Option A, conditionally**, with Option C as a minimum documentation
companion (state the assumption that the pad-level rail is not the quality
the ring pins need), and Option B held back unless Option A cannot meet the
budget.

Rationale: the margin is a few millivolts at the binding corners and
ideal-source RF locking begins between 10 and 50 mV pk; no external rail or
monitor can credibly hold that, and Option B moves ratified numbers for
millivolts of benefit. Option A is the only choice that addresses the cause
without disturbing DR-0003.

Known cost: regulator/filter area, power and added complexity; Option A is
not certified by this record (see "Why a concrete topology cannot be
certified yet").

### Ratification question (for the operator)

Does the operator want the RO array rail's supply quality stated as a spec
requirement in the form "DC-plus-slow-droop stack below the ss exhaustion
point (3.93 mV) with a margin the operator chooses, plus RF ripple at or
below 10 mV pk with the ff bias criterion unresolved", assigned to a
rail-conditioning design item (Option A), and is Option C's assumption
wording acceptable as the interim stance? Absent ratification, no spec value
changes.

## Follow-ups (each assigned to a design component or work package)

None of these is done by this record. Each lists the evidence that would
retire it.

| # | Component / work package | Work | Evidence to retire |
|---|---|---|---|
| 1 | **Rail conditioning and isolation** (new design item: `vddr1..4` regulator/RC filter, decoupling, digital-section isolation) | Choose and size a structure; fix filter corner relative to the 50 kbps sample rate; define layout isolation of the array rail from the digital rails | A committed design with netlist, its output impedance vs frequency, and a simulation showing the voltage at `vddr1..4` meets the ratified budget at ss/1.62 V and ff/1.98 V, with PVT corners |
| 2 | **Post-layout supply-impedance validation** (array-level, coordinated with #174 whole-block characterization and DR-0006's open first-named mechanism) | Re-run the ripple and droop campaign on extracted layout with real supply impedance and shared-network coupling; include independent per-ring ripple; do not claim #174's results here | Committed post-layout records for both corners with measured pin-level supply error and the same LOCK/Q/BIAS criteria |
| 3 | **Noise / jitter validation** (entropy-source characterization) | Re-measure `sigma_1` and the min-entropy consequences under ripple at the proposed limits; test a combined DC + ripple case | Committed noise/jitter records with injected noise under ripple; this is the only route to an entropy statement |
| 4 | **Bias-band baseline at ff** (array / DR-0003 band definition) | Resolve the 0.5246 clean ff baseline at the upper edge of 0.31-0.53 against the criterion used; any band change goes through its own DR | A decision record or evidence showing whether the band or the ripple limit is what binds at ff |
| 5 | **Lock-resolution closure** (sim/ro-array-supply-perturbation) | Resolve the UNRESOLVED on-frequency tone rows (longer windows) and locate the 10-50 mV threshold | A record with finer amplitudes and a longer edge window |

Preserved and distinguished:

- **DR-0003 combining ceiling.** `N_max_combine = 6` is unchanged and not
  traded against here.
- **#221 versus this record.** #221 owns the question of whether *local
  device mismatch* caps raw-bit H below DR-0004's floor and adjacent rings
  approach 1:1. This record's question is *supply quality*: how much supply
  error and ripple the array tolerates. They can interact (a supply-induced
  frequency pull is another route to 1:1 closeness) but neither decides the
  other, and nothing here pre-empts #221.
- **#174 versus this record.** #174 owns whole-block post-layout
  characterization; follow-up 2 is coordinated with it and does not claim its
  results.
- **#217** adds CI coverage for the existing ripple reducer; it is related
  and neither a prerequisite for nor a duplicate of this record.

## Caveats carried

- Pre-layout, ideal sources, deterministic; provisional until silicon.
- Two PVT points only; tt not run.
- Common-mode ripple only; sinusoids only; pk amplitudes.
- `sigma_1` not re-measured; no entropy claim.
- Interpolated droop figures are under the T0-only Q model.
- Dimensions of any regulator or filter, and any numerical supply-quality
  requirement, are decisions reserved for the operator.
