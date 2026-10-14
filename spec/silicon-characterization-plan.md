# Silicon characterization plan

**Status: PLAN (Proposed, see [DR-0014](decision-records/DR-0014-silicon-characterization-plan.md)).
Not ratified. No silicon exists and no measurement is claimed anywhere in this
document or in `measurements/`.**

Every entropy claim in this repository is *simulation-derived and provisional
until silicon* (`README.md`, `CLAUDE.md`, `spec/porting-plan.md` section 3.3,
Tier 3). This plan states, before tape-out, what silicon has to show to turn
each recorded simulated claim into a measured one, under what conditions, with
what pass/fail criterion, and whether the block as currently specified lets a
bench observe it. It changes no ratified spec value, no interface, no RTL and
no simulation record.

Where a criterion below is "tied to" a number, that number is the existing
Proposed/ratified value cited next to it. This plan does not set new targets.
A measured value that misses a criterion is a finding to report, never a reason
to edit the criterion.

## 1. Conventions that apply to every row

- **What "confirm" means.** A measured record *confirms* a simulated claim if
  the measured quantity meets the row's criterion at every listed condition. It
  *refutes* it if the criterion fails at any listed condition. It is
  *inconclusive* if the estimator confidence cannot separate the two. Nothing
  here pre-judges which.
- **A die is not a corner.** Simulation sweeps `tt`/`ss`/`ff` process corners.
  A silicon die sits at one (unknown) process position; temperature and supply
  are the only bench-selectable PVT axes. Rows therefore sweep T and V per die
  and report results *per die*, never as a pooled "corner". The number of dies
  (and lots) is an operator decision (open item O1); the plan assumes more than
  one die per row that makes a population statement.
- **PVT points.** Temperature -40 / 27 / 125 degC (README operating envelope);
  rail 1.62 / 1.80 / 1.98 V (+/-10 %, DR-0001). The six points the volume
  campaign uses (27 C/1.8 V, -40 C/1.62 V, -40 C/1.98 V, 125 C/1.62/1.8/1.98 V)
  are the default sweep.
- **Sample volume.** At least 2^20 = 1 048 576 consecutive raw bits per stream
  (the size of record `20261010-095913-3966094`; SP 800-90B non-IID estimators
  are conventionally run at >= 1e6 samples). At the DR-0003 operating point
  (50 kbps, T_s = 20 us) that is 20.97 s of capture per stream.
- **Restart dataset.** 1000 independent restarts x 1000+ raw samples each from
  the first sample after restart (the SP 800-90B restart-test shape; check
  against the standard's text when this plan is ratified). `spec/porting-plan.md`
  section 3.3 defers this dataset to silicon.
- **Estimator reuse.** Silicon streams go through the same reductions the
  simulated streams did (`sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`,
  `digital/model/` for the digital section) so a measured and a simulated record
  are comparable number-for-number.
- **Scope disclaimer.** A per-die measurement is a measurement of that die under
  those conditions. It is **not** an SP 800-90B validation or an AIS-31
  evaluation. Tier 3 validation proper is a separate, later activity and is not
  planned here.

## 2. Claim-to-measurement table

"Sim record(s)" are committed records, newest first where several exist; the
slug is the directory under `sim/`. Simulated values are quoted from the cited
records and `spec/decision-records/DR-0010-target-table-reconciliation.md`;
they are provisional and are not restated as results.

| ID | Simulated / provisional claim | Sim slug(s) and record(s) | Silicon measurement that confirms or refutes it | Instrument / conditions | Pass / fail criterion (existing threshold) | Observable today? |
|---|---|---|---|---|---|---|
| C1 | Raw-bit min-entropy per PVT point: behavioral 2^20-bit streams at T_s = 20 us give min-over-estimators H in [0.6674, 0.8791] over 18 points (model; independence of jitter increments assumed by construction). Transistor-level evidence is only 24 bits/corner at T_s = 100 ns and does not speak to the design point. | `raw-bit-volume-campaign` (`20261010-095913-3966094`, supersedes `20261008-061809-56e0fb7`, `20261008-135454-847b454`); `raw-bit-min-entropy` (`20261010-102516-3966094`, earlier `20261008-124312-5d44390`, `20261008-150026-cd45d91`, `20260906-003407-6b86c9c`, `20260905-231908-6b86c9c`, `20261008-053740-56e0fb7`); `ro-array-sizing`; `ro-array-operating-point` | >= 2^20 consecutive `raw_bit` samples per stream at each PVT point, per die; run the IID track and the six non-IID estimators plus the reduced SP 800-22-style battery; min over estimators is the reported H | Logic analyzer or MCU capture on `raw_bit` with `raw_valid` as qualifier; external `clk` generator at 50 kHz (T_s = 20 us); thermal chamber; SMU for `vdd`, `vddr1..4` | Reported H >= 0.5 at every in-envelope point (README row 3 design target; DR-0004 cutoff derivation assumes H = 0.5). A point below 0.5 refutes the design target at that condition and makes the 81/824 cutoffs non-conservative there (C7) | Yes, if `raw_bit`/`raw_valid` reach a pad (audit F1) |
| C2 | Static bias from local mismatch: worst-case `H_bias` tt 0.4718 (60 of 1800 array x sampler pairings below the 0.5 floor), ss 0.6425, ff 0.6800; this is a static-variation result, not an entropy measurement | `local-mismatch-monte-carlo` (`20261009-111125-e57ad27`, `-111126-`, `-111127-`) | Per-die bias p-hat of `raw_bit` and of each `ring_bit1..4` from the C1 streams; population of p-hat across dies | Same capture as C1; per-ring bias needs `en` gating to isolate rings (`en1..4`) | Per-die `H_bias` from p-hat compared with the 0.5 floor of DR-0004; population fraction below the floor reported against the simulated 60/1800 (tt) figure. Disposition of the floor itself belongs to #221 (open item O2), not to this plan | Yes |
| C3 | Ring frequency ladder and spread: realized per-ring frequencies ss 184.3/191.7/199.2/207.0 MHz, ff 626/661/696/733 MHz at -40 C; per-ring jitter sigma_1 and Q(T_s); intra-cell and assembled post-layout shifts of period, swing and current; array and ring supply current | `ro-array-core-combining` (`20260825-094545-53f1f7a`, `-094718-`, `-094856-`, `20261008-135355-847b454`, `-135356-`, `-135357-`); `ro-ring-jitter-accumulation`; `ro-ring5-swing-and-current`; `post-layout-ro-ring5`; `post-layout-ro-ring5-assembled`; `post-layout-ro-ring5-assembled-181`; `post-layout-ro-array-core`; `post-layout-parasitic-impact`; `ro-array-sizing` | **Direct period/jitter measurement is not possible with the pins in DR-0011 (audit F2).** Indirect only: (a) per-rail supply current of `vddr1..4` with a single ring enabled (average current tracks frequency); (b) `ring_bitN` bias and H versus an external-`clk` T_s sweep, whose shape follows Q proportional to T_s in the white-noise regime | SMU on each `vddr` rail with `en` selecting one ring; clock generator with a T_s sweep | No pass criterion on frequency values (cannot be measured). Gross-failure criteria only: per-ring current within the simulated envelope of the same-corner post-layout record; H(T_s) monotone non-decreasing in the sweep range. These can refute, never confirm, the frequency ladder | Partially (F2) |
| C4 | Supply-quality sensitivity: static droop at which Q falls to 1/1.036 is 3.93 mV (ss) / 7.43 mV (ff) below nominal; RF ripple at the ring frequency locks all four rings at 50 mV pk (pre-layout, ideal sources, `sigma_1` not re-measured) | `ro-array-supply-perturbation` (`20261009-000500-28d3690` ss, `20261009-000459-28d3690` ff); evidence summarized in DR-0012 | Per-die H and bias versus (a) static offset of `vddr1..4` in steps (1 mV resolution around nominal), (b) sinusoidal ripple injected on `vddr1..4` and `vdd` at tones including the ring frequencies and sub-harmonics | Low-noise adjustable source on each `vddr`, bias tee + RF generator, scope probe at the pad; ripple amplitude is set **at the pad**, and package/board attenuation to the die is not known (report it as a pad-level result) | Sensitivity dH/dV reported with CI. Refutes DR-0012's static bracket if H drops below 0.5 at an offset smaller than 3.93 mV (ss) / 7.43 mV (ff) pad-referred equivalent; lock is judged from `ring_bitN` and `raw_bit` spectrum/bias. DR-0012's proposed limits are not ratified, so no pass/fail against them | Yes (separate `vddr` pads); die-level ripple not observable |
| C5 | Wake-up: enable-gated and supply-ramp settling to within 1 % of final period from the first edge (2.61 ns / 3.99 ns, single-corner local probes); behavioral first-window margin against DR-0004's 1024-sample start-up window at 18 calibrated points. Transistor noisy leg and 54-unit envelope were **not run** (record is PARTIAL). | `wake-up-transient` (`20261009-093152-e57ad27`, `-093215-`, `-093500-`) | Restart dataset: >= 1000 restarts (`rst_n` pulse, `en1..4` toggle, and full supply power-cycle as three separate arms) x 1000+ raw samples from `raw_valid` assertion; first-window (1024-sample) bias versus steady-state bias; start-up test outcome per restart. Analysis path: `sim/wake-up-transient/restart_matrix.py reduce` (issue #267; behavioural known-answer record `20261010-231748-f259cb7`) | As C1 plus programmable supply sequencing; `startup_done` and `alarm` pins | Start-up test (DR-0004) passes on every restart at the C1-confirmed conditions; first-window bias not distinguishable from steady-state at estimator confidence; restart-matrix min-entropy >= the C1 value within CI. Time-to-steady in ns is not resolvable by a 50 kHz sampled output and is not a measured quantity | Yes, given audit F1 |
| C6 | Power and idle: array only 81.0 uW (ss, -40 C, 1.62 V) to 431.6 uW (ff, -40 C, 1.98 V), higher at 125 C; sampler reset-held/idle/active current post-layout; digital static leakage about 9.98 nW (Liberty-summed, `tt_025C_1v80`, leakage only). Whole-block power, dynamic power and idle leakage across PVT are **unmeasured in simulation** (#174, #201) | `ro-array-core-combining`; `post-layout-sampler-dff` (`20260907-122033-e82623e` latest); `post-layout-sampler-dff-assembled` (`20260907-155526-709dc0b`); `post-layout-sampler-core` (`20260908-072741-084e7fa`); `post-layout-ro-ring5`; `digital-synthesis` (`20260910-001436-a4c3194`) | Per-rail average current at each PVT point: active (all `en` = 1, clocked), idle (`en` = 0, clock stopped / `rst_n` low), and gated; sum compared with the < 500 uW row | SMU or shunt + DMM with nA range on `vddr1..4` and `vdd`; chamber to 125 C | Active whole-block power < 500 uW (README row 8, pending operator disposition in DR-0010) at every point; idle reported, no target exists yet. `vdd` feeds the sampler and the digital section together, so their leakage is not separable (audit F3) | Yes (sum), not per-section on `vdd` |
| C7 | Health tests: C_RCT = 81, C_APT = 824 at H = 0.5, alpha = 2^-40, W = 1024; APT degeneracy floor H = 0.0390625; deterministic failure-injection detection latency per test; replay over simulated streams | `digital-health-test-parameters` (`20261008-150251-cd45d91`, earlier `20260905-192504-2ecb0a3`); `digital-section-behavioral` (`20260905-192548-2ecb0a3`); `digital-rtl-equivalence`; `digital-functional-verification` | (a) **Bit-exact replay**: feed every captured silicon raw stream through `digital/model/` and require the on-chip `alarm`/STATUS history to match; (b) read back `HT_*` registers and match the built parameters; (c) false alarms: count alarms over all captured samples; (d) detection: force a degraded source (disable rings with `en1..4`; stuck/biased output) and measure alarm latency in samples | Capture of `alarm`, `startup_done`, `raw_bit`, `raw_valid` on a common timebase; register access via the DR-0011 serial port (if ratified) | (a),(b) must match exactly (deterministic logic). (c) zero alarms is reported as an *upper bound only*: confirming alpha = 2^-40 would need about 1.1e12 samples (about 255 days at 50 kbps), so it cannot be confirmed on a bench; report "k alarms in n samples" and the resulting bound. (d) latency within the cutoff (RCT stuck output alarms within C_RCT = 81 samples) | Yes |
| C8 | Conditioner: CRC-32 LFSR (poly 0x04C11DB7, seed 0xFFFFFFFF, 256 raw bits per word) is bit-exact against references; DATA stream battery and 90B estimators; **no full-entropy claim** | `digital-conditioner-equivalence` (`20260905-192506-2ecb0a3`); `digital-conditioned-output` (`20261010-034058-d598fa6`; note it is derived from the superseded 2^17 source record `20261008-135454-847b454`); `digital-rtl-equivalence` | Concurrent capture of the raw bits and of the DATA words they produced; recompute the CRC from the captured raw bits and compare word for word; battery and estimators on the DATA stream | As C1 plus DATA readout (register or stream port) | Every DATA word equals the model of its 256 captured raw bits (exact). Statistical results on DATA are reported with the standing statement that a non-vetted CRC redistributes entropy and creates none | Yes if raw bits and DATA are captured over the same interval |
| C9 | Raw rate: 50 kbps chosen operating point; architectural ceiling about 78 kbps from XOR combining bandwidth, binding at ff/-40 C/1.98 V | `xor-combining-bandwidth` (`20260825-084826-53f1f7a`); `ro-array-operating-point` (`20260825-093740-53f1f7a`); `ro-array-sizing` (`20260825-071619-54f5715`) | Sweep external `clk` (hence T_s) upward at the ff-like condition (-40 C, 1.98 V) and downward, recording H and bias versus T_s and the clock at which the sampled bits degrade | Clock generator, chamber, as C1 | Raw rate 50 kbps sustained with no FIFO underflow and H >= 0.5 (DR-0003); the measured degradation clock is reported against the 78 kbps ceiling (confirms or refutes the ceiling as a bandwidth limit, but a degradation cause is not isolatable from pins) | Yes |
| C10 | Digital section function and clock margin: functional correctness, placed-and-routed STA at 16 corners, SDF-annotated verification | `digital-functional-verification`; `digital-sdf-timed-verification` (`20261009-172301-8cbd26a`); `digital-pnr` (`20261003-212010-fa76b17`); `digital-synthesis`; `digital-floorplan-compaction`; `digital-electrical-repair`; `digital-repaired-compaction` | Register-level bring-up: `ID` = 0x54524E47, `HT_*` readback, write/read of control registers, FIFO flush on mode switch; clock sweep to first functional failure at each PVT point | Serial port per DR-0011 (if ratified) | `ID` and parameter readback exact; the digital section functions at 50 kHz at all six PVT points; failing clock reported against the STA estimate. Area and utilisation records (`digital-floorplan-compaction`, `digital-repaired-compaction`) are layout facts with no silicon measurement | Only through the DR-0011 port (or the literal bus if bonded) |

### 2.1 Slug coverage (every `sim/` slug accounted for)

Slug list verified against `ls sim/*/records` at the commit this plan was
written (34 slugs). A new slug under `sim/` must be added here (or marked
"no silicon counterpart") in the same change that lands it.

| Slug | Row | Slug | Row |
|---|---|---|---|
| `digital-conditioned-output` | C8 | `ro-array-core-combining` | C3, C6 |
| `digital-conditioner-equivalence` | C8 | `ro-array-operating-point` | C1, C9 |
| `digital-electrical-repair` | C10 | `ro-array-sizing` | C1, C3, C9 |
| `digital-floorplan-compaction` | C10 | `ro-array-supply-perturbation` | C4 |
| `digital-functional-verification` | C7, C10 | `ro-ring-jitter-accumulation` | C3 |
| `digital-health-test-parameters` | C7 | `ro-ring-timestep-convergence` | none (simulator-method check; no silicon counterpart) |
| `digital-pnr` | C10 | `ro-ring5-swing-and-current` | C3 |
| `digital-repaired-compaction` | C10 | `ro-stage-noise-mechanism-check` | none directly (go/no-go on the simulator noise model; tested implicitly by C1) |
| `digital-rtl-equivalence` | C7, C8 | `ro-stage-small-signal-gain` | none (internal node, not observable; implicit in C1/C3) |
| `digital-sdf-timed-verification` | C10 | `wake-up-transient` | C5 |
| `digital-section-behavioral` | C7 | `xor-combining-bandwidth` | C9 |
| `digital-synthesis` | C6, C10 | | |
| `local-mismatch-monte-carlo` | C2 | | |
| `post-layout-parasitic-impact` | C3 | | |
| `post-layout-ro-array-core` | C3 | | |
| `post-layout-ro-ring5` | C3, C6 | | |
| `post-layout-ro-ring5-assembled` | C3 | | |
| `post-layout-ro-ring5-assembled-181` | C3 | | |
| `post-layout-sampler-core` | C6 (current); capture fidelity implicit in C1 | | |
| `post-layout-sampler-dff` | C6 (current); capture delay/setup not observable, implicit in C1 | | |
| `post-layout-sampler-dff-assembled` | C6 (current); as above | | |
| `raw-bit-min-entropy` | C1 | | |
| `raw-bit-volume-campaign` | C1 | | |

No whole-block post-layout simulation record exists yet (#174); no row can
link to one. When that campaign lands its slug is added to this table.

## 3. Observability audit against DR-0011

**Scope.** Does the external interface in
[DR-0011](decision-records/DR-0011-external-interface-vs-assumed-challenge-4-pin-budget.md)
expose what the rows above need, in particular the raw tap and raw-path access
for SP 800-90B-style raw and restart datasets? Read against DR-0011 as written
(Proposed; the 24-in / 12-out budget is itself an assumption), the as-composed
`layout/trng_whole/interface.md`, and `digital/rtl/trng_digital.v`. The interface
is **not** changed here.

### 3.1 What each measurement needs

| Need | Rows | Provided by | DR-0011 Option C |
|---|---|---|---|
| Full-rate raw dataset (every sample, undecimated, before any post-processing) | C1, C2, C5, C7, C8, C9 | `raw_bit` + `raw_valid` | counted in the 11 outputs |
| Restart dataset: first sample after a restart | C5 | `rst_n` (input), supply sequencing (external), `raw_valid` asserts after `rst_n` release, `startup_done` | `rst_n` counted; raw taps counted |
| Per-ring bias and ring isolation | C2, C3 | `ring_bit1..4`, `en1..4` | counted (`ring_bit1..4` outputs, `en1..4` inputs) |
| Per-ring and per-section supply current; supply injection | C3, C4, C6 | separate `vddr1..4` and `vdd`/`vss` pads | supplies are not digital slots (6 pads) |
| Clock control (T_s sweep, rate ceiling, Fmax) | C3, C9, C10 | external `clk` | counted |
| Health-test outcome, start-up result, parameter readback | C7 | `alarm`, `startup_done`, `gated`; `HT_*` registers | `alarm`, `gated`, `startup_done` direct; registers through the serial port |
| DATA words for conditioner check | C8 | `DATA` register (serial) or stream port | register path via the serial port; stream port not bonded |
| ID / control-register bring-up | C10 | register bus | serial port |

### 3.2 Result

**Result: NO GAP in DR-0011's pin budget, conditional on one dependency; two
observability limits are findings for the operator.** Every need above maps onto
a pin or register that Option C already counts (8 digital inputs of an assumed
24, 11 outputs of an assumed 12). Specifically:

- **F1 (dependency, not a gap if Option C is ratified): the raw taps must be
  bonded.** In the as-composed `trng_whole`, `raw_bit` and `raw_valid` are
  *internal nets with no boundary pad* (`layout/trng_whole/interface.md`;
  DR-0011 "Whole-block external demand"). DR-0011 Option C counts them in its 11
  outputs and says pads for them are new composition work. If the operator
  ratifies an option that does not bond them, there **is** a gap: serial
  `RAW_DATA` polling needs at least 36 clk per word against a 32-clk raw-word
  period (DR-0011 "Rate observations"), so full-rate raw capture, and with it
  C1, C2, C5, C7 and C9, would be unmeasurable. The restart dataset in
  particular needs the first sample after restart, which a register read cannot
  deliver. The plan therefore asks that any ratified interface keep `raw_bit` and
  `raw_valid` as pads.
- **F2 (observability limit): ring period and jitter are not observable.**
  `ring_bit1..4` and `raw_bit` are sampled at `clk` (50 kHz); the rings run at
  roughly 184-733 MHz in simulation. No pin carries a divided or buffered ring
  waveform, so the frequency ladder, per-ring period spread and `sigma_1` cannot
  be measured directly (C3 is indirect and can only refute). A divided-ring test
  output would fit Option C's budget by pin count (11 of 12 outputs used), but
  adding it is an interface change and is not made here. **Operator decision
  item.**
- **F3 (observability limit): `vdd` is shared** by the sampler bank and the
  digital section (`vdd` is `external_to_both`), so their idle leakage cannot be
  separated (C6). Only the sum is measurable. Informational; no change proposed.

Notes (no action required): the raw path is never gated, so `raw_valid`/`raw_bit`
are valid during the start-up window (DR-0004); the restart dataset needs three
arms (`rst_n` pulse, `en` toggle, power cycle) that use only pins already
counted; the `clk` pad doubles as the serial shift clock under Option C, so a
T_s sweep also clocks the serial port and sweeps its timing.

## 4. Open items for the operator

- **O1**: number of dies/lots per row and which rows need a population statement.
- **O2**: disposition of the `H_bias` floor and trim/selection (#221) decides
  whether C2 has a pass/fail or is reported only.
- **O3**: ratify or reject the F2 divided-ring test tap as a separate interface
  decision issue.
- **O4**: DR-0011 is Proposed and its budget is an assumption; if the real
  Challenge #4 brief or the chosen option differs, re-run section 3.
- **O5**: package/board characterization needed to refer C4 pad-level ripple to
  the die, if a die-level statement is wanted.

## 5. Where measured results go

`measurements/` holds them under the layout contract in
[`measurements/README.md`](../measurements/README.md). A measured record names
the simulated record(s) it confirms, refutes or replaces; simulated records are
never edited. Until a measured record exists, the corresponding claim stays
"simulation-derived, provisional until silicon".
