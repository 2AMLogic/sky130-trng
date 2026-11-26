# sampler_core analog active-power budget (issue #604)

Bound: **README target row: < 500 uW active (analog-partition share)**. Every number below is transistor-level transient
simulation (ngspice) of the committed `design/sampler_core.spice`
pre-layout netlist and the flat-extracted parasitic netlist
`layout/pex-sampler-core/sampler_core_pex.spice` (sha256 in each cited
record/plan) -- provisional, simulation-derived, not silicon. The
failing corners are exactly the two ff / 1.98 V temperatures of the
four-point post-layout PVT grid; the other ten corners of issue #597's
grid pass extracted and are not re-derived here.

## 0. Provenance

| comparison leg | netlist | loading | clk period | windows |
|---|---|---|---|---|
| 100 ns control (both legs, same deck) | `design/sampler_core.spice` + `layout/pex-sampler-core/sampler_core_pex.spice` (sha256 in each cited record) | each leg's own buffers/XOR/samplers; outputs unloaded | 100 ns, first edge 320 ns | rst 50-250 ns, act 400-800 ns |
| 20 us runs (both legs, same deck) | `design/sampler_core.spice` (sha256 `34a9af2714b7cfd7...`) + `layout/pex-sampler-core/sampler_core_pex.spice` (sha256 `2aad0267cba9c927...`) | identical to the control deck (netlists inlined verbatim) | 20 us, first edge 320 ns, 49.8 % duty | rst 50-250 ns, act 20.32-40.32 us (one complete settled period; deviations recorded in each corners/ts20u-*/plan.json) |

Supply 1.98 V on all rails; process ff; temperatures -40 / +125 C.

## 1. The 100 ns control budget (committed records, reproduced)

Active window 400-800 ns (four complete 100 ns clk periods), reset-held
window 50-250 ns; per-rail currents x 1.98 V. Sums reproduce the
issue's table; the rail split (ring rails vs shared VDD = buffers +
XOR tree + six samplers) is the budget line assignment.

### -40 C (record `20260908-050034-ef0db50`, ff/1.98 V, ngspice build: ** ngspice-46 : Circuit level simulation program)

| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |
|---|---:|---:|---:|---:|
| schematic | 173.7 | 345.5 | 519.2 | -19.2 |
| extracted | 147.9 | 435.8 | 583.6 | -83.6 |

### +125 C (record `20260908-053634-ef0db50`, ff/1.98 V, ngspice build: ** ngspice-46 : Circuit level simulation program)

| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |
|---|---:|---:|---:|---:|
| schematic | 174.5 | 392.7 | 567.2 | -67.2 |
| extracted | 147.4 | 456.3 | 603.8 | -103.8 |

Rail-sum consistency (rings + block vs the record's own total):

- -40 C schematic: +0.000 uW (source rounding)
- -40 C extracted: +0.000 uW (source rounding)
- +125 C schematic: -0.000 uW (source rounding)
- +125 C extracted: +0.000 uW (source rounding)

## 2. The Ts = 20 us matched runs (this issue's batch experiment)

Stimulus and windows: DR-0003's sampling period Ts = 20 us
(49.8 % duty, first edge 320 ns -- the control deck's own timing at the
real rate); W_RST = 50-250 ns bit-identical to the controls'; W_ACT =
20.32-40.32 us = exactly one complete settled clk period (edges at both
endpoints); halves at 30.32 us reported as a stationarity indicator.
Recorded deviations (tstep 50p vs the control's 5p; en/rst pulse widths
extended past tstop) and their measured error bars live in each
request's `plan.json`.

### -40 C (job `klt-sim-a84860581d91`, state done, runner klt 0.9.0, compat match, engine 2985 s)

| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |
|---|---:|---:|---:|---:|
| schematic | 173.5 | 345.7 | 519.1 | -19.1 |
| extracted | 148.0 | 429.2 | 577.2 | -77.2 |

Stationarity (shared-VDD half-window spread): schematic +44.31 %, extracted +32.53 % of the leg's W_ACT mean.

### +125 C (job `klt-sim-4019827a62fe`, state done, runner klt 0.9.0, compat match, engine 2748 s)

| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |
|---|---:|---:|---:|---:|
| schematic | 174.1 | 395.0 | 569.1 | -69.1 |
| extracted | 147.5 | 452.1 | 599.6 | -99.6 |

Stationarity (shared-VDD half-window spread): schematic +38.42 %, extracted +32.25 % of the leg's W_ACT mean.

### Cross-run anchor (W_RST, stimulus-identical)

| T | schematic total (uW) | extracted total (uW) |
|---|---:|---:|
| -40 C | 492.1 -> 492.7 (+0.12 %) | 556.8 -> 556.3 (-0.08 %) |
| +125 C | 531.3 -> 534.2 (+0.54 %) | 562.6 -> 562.7 (+0.02 %) |

## 3. Sampling-rate comparison and verdicts

| T | leg | 100 ns total (uW) | 20 us total (uW) | delta | 20 us verdict vs 500 uW |
|---|---|---:|---:|---:|---|
| -40 C | schematic | 519.2 | 519.1 | -0.1 | FAIL |
| -40 C | extracted | 583.6 | 577.2 | -6.5 | FAIL |
| +125 C | schematic | 567.2 | 569.1 | +1.9 | FAIL |
| +125 C | extracted | 603.8 | 599.6 | -4.1 | FAIL |

## 4. Array-only context (DR-0003 section 7 / DR-0010 R3)

| T | array-only, 100 ns decks (uW) | schematic leg 20 us (uW) |
|---|---:|---:|
| -40 C | 431.6 | 519.1 |
| +125 C | 473.9 | 569.1 |

## 5. Proposed disposition

Both legs of both failing corners stay above the 500 uW bound at DR-0003's
own 20 us sampling period (section 3): the sampling rate is **refuted as
the overrun term by measurement** — moving from the committed controls'
100 ns clock to DR-0003's Ts = 20 us clock shifts each leg's total by at
most +1.9 / -6.5 uW (-1.1 % to +0.3 %), far below the 19.1-99.6 uW excess
over 500 uW (schematic then extracted: 19.1 / 77.2 uW at -40 C, 69.1 /
99.6 uW at +125 C), and the stimulus-identical W_RST window reproduces
across runs to 0.02-0.54 % (section 2 anchor). The six samplers share VDD
with the buffers and XOR tree, so these reports (four ring-rail currents
plus one shared-VDD current per leg) establish only that slowing the clock
leaves every leg over 500 uW; they do not isolate the sampler bank's
absolute power.

No supported design iteration is identified that recovers the excess inside
the Ts = 20 us, N = 4 operating point used here (ring gating destroys
DR-0003's accumulation basis; N = 4 is entropy-minimal; ff/1.98 V is
inside DR-0010 row 9's recorded envelope; the array-only figure is 473.9
uW at the hot corner, leaving 26.1 uW before the remaining loads; these
numbers do not rule out a periphery-only redesign). DR-0003 and DR-0010
are both `status: Proposed`. The evidence therefore warrants
reconsidering the target: **DR-0021 (Proposed)** records the rationale and
the operator options P-A (amend the analog-partition active bound to the
measured worst corner plus silicon guardband — recommended), P-B (hold
500 uW with a per-corner derogation) and P-C (a sizing re-derivation
campaign). This analysis leaves the README Power row, #597's grid and
every committed record intact; ratification is an operator action.

Whole-block power remains #174's row and is not claimable from these
numbers; the formal 12-corner PEX table is #597's.
