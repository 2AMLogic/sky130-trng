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
| Historical 100 ns, -40 C | schematic `34a9af2714b7cfd7`, PEX `2bad455e86e882ad` | outputs unloaded | 100 ns | rst 50-250 ns, act 400-800 ns, step 5 ps |
| Fleet requests at -40 C | schematic `34a9af2714b7cfd7`, PEX `2aad0267cba9c927` | outputs unloaded | 100 ns / 20 us | rst 50-250 ns, act 420-820 ns / 20.32-40.32 us, step 50 ps |
| Historical 100 ns, +125 C | schematic `34a9af2714b7cfd7`, PEX `2bad455e86e882ad` | outputs unloaded | 100 ns | rst 50-250 ns, act 400-800 ns, step 5 ps |
| Fleet requests at +125 C | schematic `34a9af2714b7cfd7`, PEX `2aad0267cba9c927` | outputs unloaded | 100 ns / 20 us | rst 50-250 ns, act 420-820 ns / 20.32-40.32 us, step 50 ps |

Each deck contains both legs with their own buffers, XOR tree and samplers.
Section 1 reproduces the historical records. Section 3 uses only fleet pairs
with matching schematic, PEX and executed model hashes, simulator builds
and requested settings. Section 3 gives the runner evidence for ngspice initialization.
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

## 2. The Ts = 20 us measurements (this issue's batch experiment)

At Ts = 20 us the first rising edge is at 320 ns and the clock duty is 49.8%.
W_RST covers 50-250 ns before the first edge. W_ACT covers 20.32-40.32 us,
one complete period between rising edges. The two half-window means show
phase-dependent current within that period. The plans record the transient
step and the enable and reset pulse widths.

### -40 C (job `klt-sim-a84860581d91`, state done, runner klt 0.9.0, compat match, engine 2985 s)

| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |
|---|---:|---:|---:|---:|
| schematic | 173.5 | 345.7 | 519.1 | -19.1 |
| extracted | 148.0 | 429.2 | 577.2 | -77.2 |

Shared-VDD half-window spread: schematic +44.31 %, extracted +32.53 % of the leg's W_ACT mean.

### +125 C (job `klt-sim-4019827a62fe`, state done, runner klt 0.9.0, compat match, engine 2748 s)

| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |
|---|---:|---:|---:|---:|
| schematic | 174.1 | 395.0 | 569.1 | -69.1 |
| extracted | 147.5 | 452.1 | 599.6 | -99.6 |

Shared-VDD half-window spread: schematic +38.42 %, extracted +32.25 % of the leg's W_ACT mean.

### Historical reset-window comparison (W_RST, 50-250 ns)

These differences describe reset-held operation across extractions.

| T | schematic total (uW) | extracted total (uW) |
|---|---:|---:|
| -40 C | 492.1 -> 492.7 (+0.12 %) | 556.8 -> 556.3 (-0.08 %) |
| +125 C | 531.3 -> 534.2 (+0.54 %) | 562.6 -> 562.7 (+0.02 %) |

## 3. Sampling-rate comparison and verdicts

- At -40 C the 100 ns control is awaiting fleet report. Requested ngspice settings `set measureprec=12`, `set numdgt=12` (100 ns pending, 20 us requested only).
- At +125 C the 100 ns control is awaiting fleet report. Requested ngspice settings `set measureprec=12`, `set numdgt=12` (100 ns pending, 20 us requested only).

The verdict uses the unrounded 20 us total. A total of exactly 500 uW fails.
Where a runner omits both init lines and digest, any clock-rate delta assumes
the runner applied the requested settings.

| T | leg | Matched 100 ns total (uW) | 20 us total (uW) | delta | 20 us verdict vs 500 uW |
|---|---|---:|---:|---:|---|
| -40 C | schematic | pending | 519.1 | pending | FAIL |
| -40 C | extracted | pending | 577.2 | pending | FAIL |
| +125 C | schematic | pending | 569.1 | pending | FAIL |
| +125 C | extracted | pending | 599.6 | pending | FAIL |

## 4. Array-only context (DR-0003 section 7 / DR-0010 R3)

| T | array-only, 100 ns decks (uW) | schematic leg 20 us (uW) |
|---|---:|---:|
| -40 C | 431.6 | 519.1 |
| +125 C | 473.9 | 569.1 |

## 5. Proposed disposition

At Ts = 20 us the two ff / 1.98 V corners exceed 500 uW on both legs.
The excess is 19.1 / 77.2 uW at -40 C and 69.1 / 99.6 uW at +125 C
(schematic / extracted). The historical 100 ns records and the 20 us
reports used different parasitic extractions and simulator settings.
Their 0.02–0.54% reset-window agreement applies only with reset held.
Section 3 uses the short 100 ns controls for clock-rate deltas. Each
leg measures four ring rails and one shared VDD for the buffers, XOR
tree and six samplers. This split leaves sampler-bank power unresolved.

No supported design iteration is identified that recovers the excess inside
the Ts = 20 us, N = 4 operating point used here (ring gating destroys
DR-0003's accumulation basis; N = 4 is entropy-minimal; ff/1.98 V is
inside DR-0010 row 9's recorded envelope; the array-only figure is 473.9
uW at the hot corner, leaving 26.1 uW before the remaining loads; these
numbers do not rule out a periphery-only redesign). DR-0003 and DR-0010
are both `status: Proposed`. At longer sampling periods the sizing law
permits fewer rings (DR-0003 §2). The measured misses warrant
reconsidering the target: **DR-0021 (Proposed)** records the rationale and
the operator options P-A (amend the analog-partition active bound to the
measured worst corner plus a proposed 47.4 uW allowance), P-B (hold
500 uW with a per-corner derogation) and P-C (a sizing re-derivation
campaign). This analysis leaves the README Power row, #597's grid and
every committed record intact; ratification is an operator action.

Whole-block power remains #174's row and is not claimable from these
numbers; the formal 12-corner PEX table is #597's.
