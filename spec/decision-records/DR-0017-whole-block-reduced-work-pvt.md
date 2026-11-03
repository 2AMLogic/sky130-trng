---
dr: DR-0017-whole-block-reduced-work-pvt
title: Whole-block post-layout PVT -- reduce the work (gate-level digital behind a boundary), not the claim
status: Proposed
date: 2026-11-03
deciders: unratified -- Proposed by the Builder on #404; ratification is an operator action
supersedes: "n/a -- chooses how the whole-block campaign of #174 is to be reduced. It relaxes no ratified result, spec value, target-table row, verdict or #18 acceptance criterion, and edits no existing record."
superseded_by: n/a
related: "#404 (this record), #307 (parent, unblocked by this), #403 (rate probe, input), #174, #170, #18 AC3, PR #393, DR-0003, DR-0008, DR-0010, sim/post-layout-whole-block/"
---

# DR-0017: whole-block PVT -- reduce the work, not the claim

## Status

- 2026-11-03: **Proposed.** Ratification is an operator action. This record
  is a decision and a specification only: it runs no simulation and changes no
  generator or reducer. **#18 AC3 stays UNMET.**

## Context

The whole-block program (`sim/post-layout-whole-block/program.py`: 75 cycles,
`Ts = 100 ns`, `T0 = 320 ns`, stop about 7.87 us; 25 355 transistors) has
never completed on the batch fleet. The one probe that got past parse
(970 ns, PR #393, `records/20261030-fleet-probe-post-bin-fix.md`) hit the
3480 s ceiling in analysis having reached an unreported simulated time.

**Rate: unknown.** #403 (the probe that finishes and reports simulated time
reached) had not landed when this record was written. The decision below is
therefore made on the stated fact only: 970 ns of the transistor-level whole
block did not finish in 3480 s, and the full program is about 8.1x longer
(7.87 us / 0.97 us). Even a perfectly linear scaling makes the full program
infeasible at the ceiling; a super-linear one is worse. If #403 reports a
rate, the numbers in "Consequences" are to be re-checked, and this record is
amended (new status line), not silently edited.

## Options

| | Option | Leaves UNMET (of the #18 obligations in the table below) |
|---|---|---|
| (a) | Shorter transistor-level program (register/start-up phases only, about 4 cycles + 6 reads, roughly 1 us) | O3 (streaming port), O4 (start-up/alarm scalars at 36/42/74), O6 (throughput tap). Also not shown feasible: 970 ns already hit the ceiling. |
| **(b)** | **Chosen.** Analog chain (ring array + sampler) at transistor level; digital section as gate-level behind a defined boundary | O5-digital (transistor-level digital supply current), O7 (IR with digital load) |
| (c) | Several shorter transistor-level probes split across units | The digital state is not carried between units, so every later probe needs a state restore (`.ic` on thousands of nodes) that is itself unevidenced. Leaves O2-O6 UNMET as a whole-program claim. |

Rejected, one line each:

- **(a)** -- is not shown to fit the ceiling (970 ns did not), and even if it
  does it covers only the first of the program's phases.
- **(c)** -- the state hand-off between units is an unevidenced assumption that
  would stand in for the continuity the whole-block claim is about.
- **Any option that relabels an UNMET obligation MET, or substitutes
  behavioral digital activity for transistor-level per-supply current
  evidence** -- never acceptable; (b) names the digital-current row UNMET
  rather than do this.

## Decision

Choose **(b)**: the analog chain stays at transistor level on the committed
GDS-extracted netlist; the digital section (`trng_digital`, the synthesized
netlist of #117 / `digital/flow`) is simulated at gate level behind a fixed
boundary; the full 75-cycle program and all four (T, Vdd) points x
`tt`/`ss`/`ff` are kept (the matrix and program are not reduced -- the
*simulated detail* of the digital section is).

### Analog/digital boundary

| Signal | Direction | Notes |
|---|---|---|
| `raw_bit`, `raw_valid` | analog -> digital | the sampler outputs; digital input thresholds modelled at the 1.8 V domain, VIH(1.62 V) = 1.05 V |
| `clk`, `rst_n`, `addr`, `we`, `re`, `wdata[31:0]`, `out_ready` | testbench -> digital | PWL as today |
| `bus_rdata[31:0]`, `out_data[31:0]`, `out_valid`, `alarm`, `gated`, `startup_done` | digital -> observed | measured as today |
| `en` / ring-enable and ring controls | digital -> analog | stay a transistor-level path in the analog block |
| `vdd`, `vss`; `vddr1`-`vddr4` | supplies | digital on `vdd`/`vss`; rings on `vddr1`-`vddr4`, all five move with the corner |

The boundary is a *signal* boundary only; the analog block sees the real
transistor-level loading of the sampler outputs, the digital block sees
voltage-threshold-correct stimuli. How the gate-level model is realised in
ngspice (event-driven co-simulation versus a timed-delay netlist) is for the
follow-up to choose and to evidence; if the toolchain cannot, that is a tool
gap to be filed generically, not a reason to fall back to a behavioral
stand-in.

### Library, timing and corner mapping

- Cells: `sky130_fd_sc_hd`, the cells in the synthesized netlist.
- Process corner: the same `.lib sky130.lib.spice` `tt`/`ss`/`ff` as the analog
  devices. Gate delays are taken from the matching Liberty corner
  (`tt_025C_1v80`, `ss_n40C_1v60`, `ff_n40C_1v95` as closest available; the
  nearest-corner mapping per (T, Vdd) point is part of the follow-up's
  specification and is recorded, not assumed).
- Any interpolation between the Liberty corners and the four (T, Vdd) points is
  disclosed in each result as a deviation. It is not timing sign-off.

### Provenance of per-supply currents

- `vddr1`-`vddr4` currents: transistor-level, measured as today (W1/W2).
- `vdd` current: **gate-level digital current is not transistor-level digital
  evidence.** The record reports it as **UNMET**
  (`i_vdd_w1/w2`, `digital_delta_i_a`, `digital_dynamic_power_w_estimate`
  carry `provenance: "gate-level"` and never feed a MET verdict). A
  separate short transistor-level window (candidate (a)-style, state its own
  feasibility against #403's rate) is the only route to MET for this row and is
  out of scope here.

### Coverage table

Obligations are the groups the reducer already enumerates plus the two
non-matrix evidence rows. **MET-if-measured** means the row can become MET
only if the corresponding follow-up run completes cleanly and matches the
oracle at all 12 points; nothing is MET by this record.

| ID | Original obligation | Under (b) |
|---|---|---|
| O1 | 12-point matrix present (3 process x 4 (T, Vdd)) | MET-if-measured |
| O2 | Register path vs normative model (`rdata_k*`) | MET-if-measured |
| O3 | Streaming port (`out_valid_k*`, `odata_k*`) | MET-if-measured |
| O4 | `alarm`/`gated`/`startup_done` scalars | MET-if-measured |
| O5a | Ring-supply currents `vddr1`-`vddr4` (transistor-level) | MET-if-measured |
| O5d | Digital supply current / dynamic power (`vdd`) | **UNMET** |
| O6 | Throughput tap `t_out_valid_first` | MET-if-measured |
| O7 | Static IR with a digital load | **UNMET** (no transistor-level digital load; #308) |
| O8 | Entropy statistics at the ratified `Ts` | **UNMET** (`Ts = 100 ns`, not 20 us; unchanged by this record) |

Consequently **#18 AC3 remains UNMET** under this decision: O5d, O7 and O8 are
UNMET by construction, and no other row is MET until measured.

## Interface specification (for the follow-up Builder issue)

### `program.py`

| Entry point | Status | Change |
|---|---|---|
| `build_program(limit=None)` | unchanged | same 75 cycles; `limit` stays |
| `cycle_inputs(cycles)` | unchanged | boundary stimulus is derived from it |
| `model_replay(captured_bits)` | unchanged | the oracle |
| `boundary_signals()` -> `dict[str, {dir, width, domain}]` | new | the table above, as data |
| `digital_stimulus(cycles)` -> per-cycle vectors for the gate-level block | new | `cycle_inputs` plus the clock/reset times, without analog sources |
| `PROVENANCE = {"analog": "transistor", "digital": "gate-level"}` | new | written into each request |

### `make-requests.py`

| Item | Change |
|---|---|
| `--set grid` | unchanged matrix (four requests, `tt`/`ss`/`ff` each) |
| netlist | analog extract + gate-level digital model; the gz netlist sha256 and the digital netlist sha256 both go in `plan.json` |
| measurements | names unchanged (`raw_bit_k*`, `rdata_k*_b*`, `out_valid_k*`, `odata_k*_b*`, `alarm_k*`, `gated_k*`, `startup_done_k*`, `i_*_w1/w2`, `q_*_w2`, `t_out_valid_first`, `t_clk_first`) |

### `analysis/reduce-whole-block.py`

| Item | Change |
|---|---|
| `expected_points()` | unchanged (12 points) |
| point status | per-point status stays MET only on clean corner + oracle match |
| new `obligations` section | one row per ID in the table above, `status` and `reasons` |
| `power.provenance` | `"gate-level"` for `vdd`; `O5d` is forced UNMET whatever the numbers are |
| `ac3_claimable` | forced `False` while any of O5d/O7/O8 is UNMET |
| tests (`sim/tests/test_whole_block_reduction.py`) | add: O5d UNMET even when the corner is clean and the oracle matches; `provenance` absent -> every row UNMET |

## Consequences

- The campaign becomes feasible only if the analog chain plus a gate-level
  digital block fits the ceiling; this is **not shown**. #403's rate is the
  input to confirm that, and a negative result is recorded as such, not worked
  around.
- The digital-current obligation moves to a separately tracked item with its own
  feasibility question; it is not dropped.
- All results remain simulation-derived and **provisional until measured on
  silicon**; this is not foundry sign-off.
