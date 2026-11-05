---
dr: DR-0017-whole-block-reduced-work-pvt
title: Whole-block post-layout PVT -- reduce the work (gate-level digital behind a boundary), not the claim
status: Accepted
date: 2026-11-03
deciders: "operator (rjwalters), ratified 2026-11-05 in attended fleet:decide round 20261105-r6, ruling r6-q26, after the EE key (approve) and the market key (request-changes, addressed by the amendment of 2026-11-05) on #404"
supersedes: "n/a -- chooses how the whole-block campaign of #174 is to be reduced. It relaxes no ratified result, spec value, target-table row, verdict or #18 acceptance criterion, and edits no existing record."
superseded_by: n/a
related: "#404 (this record), #307 (parent, unblocked by this), #403 (rate probe, input; landed in PR #407), #174, #170, #18 AC3, PR #393, DR-0003, DR-0008, DR-0010, sim/post-layout-whole-block/"
---

# DR-0017: whole-block PVT -- reduce the work, not the claim

## Status

- 2026-11-03: **Proposed.** Ratification is an operator action. This record
  is a decision and a specification only: it runs no simulation and changes no
  generator or reducer. **#18 AC3 stays UNMET.**
- 2026-11-04: **Amended, still Proposed** (operator send-back, `fleet:decide`
  round 20261031-r5, r5-q69; EE-key review at `ead914a`). Corrects the
  analog/digital boundary against `layout/trng_whole/interface.md`, replaces
  the sampler-load claim with a defined boundary-load model, fixes the
  supply-current attribution, names the analog netlist source and how it is
  checked, and brings in #403's outcome (the 100 ns probe also timed out), which
  makes (b)'s feasibility an explicit first gate. No ratified value, row or
  verdict is changed; **#18 AC3 stays UNMET.**
- 2026-11-05: **Accepted** (operator ruling r6-q26, attended `fleet:decide`
  round 20261105-r6). Both keys reviewed `e96bebf0` and posted on #404: the
  EE key approved, and the market key requested one change. Accepted with that
  change as a condition, made in the same amendment: §Claim level of a (b)
  result. The EE key's non-blocking notes are taken into §Feasibility gate,
  §Library, timing and corner mapping, and the `make-requests.py` partition
  check. Acceptance chooses the direction and the interface. It measures
  nothing; **#18 AC3 stays UNMET** and every O-row is as in §Coverage table.

## Context

The whole-block program (`sim/post-layout-whole-block/program.py`: 75 cycles,
`Ts = 100 ns`, `T0 = 320 ns`, stop about 7.87 us; 25 355 transistors) has
never completed on the batch fleet. The one probe that got past parse
(970 ns, PR #393, `records/20261030-fleet-probe-post-bin-fix.md`) hit the
3480 s ceiling in analysis having reached an unreported simulated time.

**Rate: still unknown; #403 reported a lower bound only** (amendment of
2026-11-04). #403 (PR #407,
`sim/post-layout-whole-block/records/20261103-rate-probe-infeasible.md`) cut the
same flat netlist to `.tran 20p 100n` -- DC start-up plus ring oscillation only,
before the clock starts at 320 ns, with the digital section held in reset and so
essentially static -- and that **100 ns probe also hit the 3480 s ceiling**
with no progress lines in `ngspice.log`. No simulated-time rate is derivable;
the only bound is a *lower* bound of > 34.8 s per simulated ns, i.e. > 76 h for
the 7.87 us program (an extrapolation that assumes linear scaling). The cost
driver is **not distinguished**: slow DC start-up versus slow time-stepping
(timestep collapse in the rings). Both the rings and the sampler stay at
transistor level under (b), so neither is removed by (b). The original reading
-- 970 ns did not finish and the full program is about 8.1x longer
(7.87 us / 0.97 us) -- stands but is now weaker evidence than the 100 ns result.

## Options

| | Option | Leaves UNMET (of the #18 obligations in the table below) |
|---|---|---|
| (a) | Shorter transistor-level program (register/start-up phases only, about 4 cycles + 6 reads, roughly 1 us) | O3 (streaming port), O4 (start-up/alarm scalars at 36/42/74), O6 (throughput tap). Also not shown feasible: 970 ns already hit the ceiling. |
| **(b)** | **Chosen, subject to the feasibility gate below.** Analog chain (ring array + sampler) at transistor level; digital section as gate-level behind a defined boundary | O5d (transistor-level digital supply current), O7 (IR with digital load), O8 (`Ts` deviation, unchanged) |
| (c) | Several shorter transistor-level probes split across units | The digital state is not carried between units, so every later probe needs a state restore (`.ic` on thousands of nodes) that is itself unevidenced. Leaves O2-O6 UNMET as a whole-program claim. |

Rejected, one line each:

- **(a)** -- is not shown to fit the ceiling (970 ns did not; neither did
  100 ns), and even if it does it covers only the first of the program's phases.
  The same "not shown to fit" standard applies to (b); see the feasibility gate.
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
*simulated detail* of the digital section is). The connectivity-only netlist
carries no extracted R/C, so removing the digital transistors loses no IR or
supply-coupling fidelity that the current netlist models.

### Feasibility gate (first step of the follow-up)

(b) is a choice of direction, **not shown to fit the 3480 s ceiling.** Before
the gate-level co-simulation is built, the follow-up's first step is an
**analog-chain-only short probe** (rings + sampler at transistor level, the
digital section absent or stubbed at the boundary) **with progress output**
(klayout-tools#4867), so the cost driver (DC start-up versus ring timestep
collapse) is distinguished. A negative result there is **recorded as a negative
result for (b)** and this record is amended; it is not worked around, and no
behavioral stand-in replaces the digital section to make it fit.

The pass criterion is stated **before** the probe runs, in the follow-up issue
and its record: the measured simulated-time rate (s per simulated ns,
from the progress output) must put one corner's full 7.87 us program within the
3480 s unit ceiling, with the margin the record names. A probe that cannot
report a rate counts as a fail, not as inconclusive.

### Claim level of a (b) result

A matrix produced under (b) is **mixed-level**: analog at transistor level and
digital at gate level, on a connectivity-only extract (no R/C). Every surface
that reports it carries that level, worded as **"mixed-level (analog
transistor / digital gate-level), connectivity-only extract (no R/C)"**. These
surfaces are the record headline, the matrix verdict,
`sim/post-layout-whole-block/README.md` and the
`docs/chipalooza/challenge-4-proposal.md` block-level post-layout PVT row. None
of them says "transistor-level" or "post-layout PVT" unqualified for a (b)
result, and "no R/C" stays next to every "post-layout" mention. The reducer
writes the `PROVENANCE` level at matrix and per-point level, not only in
`power.provenance` (see §Interface specification). This is the same labelling
pattern the repo already uses for its mixed-level LVS.

### Analog/digital boundary

Source of truth: `layout/trng_whole/interface.md` (generated by
`layout/bin/compose-whole.py`) and `trng_whole.sim.ports.json`.

| Signal | Class (`interface.md`) | Direction | Notes |
|---|---|---|---|
| `raw_bit`, `raw_valid` | inter_macro | analog -> digital | sampler outputs; land on standard-cell input pins in the flat netlist. Load and threshold model: see "Boundary-load model" |
| `clk`, `rst_n` | shared_input (`external_to_both`) | testbench -> **both** the sampler (transistor level; its `tg_*_ctrl` / `inv_clk` nets are on the `clk` cluster) **and** the digital section | PWL as today; the load of each side is on the same source |
| `en1`-`en4` | analog_external (`external_to_analog`) | testbench -> analog (ring enables) | **Not** driven by the digital section: no ring enable is connected to a digital output. Driven by the testbench (`Ven1..4 PULSE` in `make-requests.py`) |
| `ring_bit1`-`ring_bit4` | analog_external (`analog_to_external`) | analog -> observed | measured as today |
| `bus_addr[3:0]`, `bus_we`, `bus_re`, `bus_wdata[31:0]`, `out_ready` | whole-block external pins | testbench -> digital | PWL as today (port names as in `interface.md`) |
| `bus_rdata[31:0]`, `out_data[31:0]`, `out_valid`, `alarm`, `gated`, `startup_done` | whole-block external pins | digital -> observed | measured as today |
| `vdd`, `vss` | logic_supply / logic_ground (`external_to_both`) | supplies | **shared by the analog macro (sampler) and the digital section** |
| `vddr1`-`vddr4` | ring_supply (`external_to_analog`) | supplies | reach only the rings; four distinct nets. All five supply groups move with the corner |

No other ring control exists between the digital section and the analog block
in the committed netlist; if the follow-up finds one it names the net from the
netlist rather than assuming it. The boundary is a *signal* boundary; how the
gate-level model is realised in ngspice (event-driven co-simulation versus a
timed-delay netlist) is for the follow-up to choose and to evidence. A
decoupled gate-level simulation (the route gf180-trng DR-0022 took for its
digital half, Icarus + SDF) is a known realisation of the digital half but
cannot by itself supply the boundary load below. If the toolchain cannot do
this, that is a tool gap to be filed generically, not a reason to fall back to a
behavioral stand-in.

### Boundary-load model

Under (b) the cells that receive `raw_bit`/`raw_valid` (and the digital share of
the `clk`/`rst_n` load) *are* the gate-level section, so the sampler output sees
whatever the bridge supplies, **not** the transistor-level load. The follow-up
must pick, state and disclose one of:

1. keep the first receiving cell(s) of `raw_bit`/`raw_valid` (and the digital
   `clk`/`rst_n` receivers) at transistor level, or
2. model the load as the Liberty input-pin capacitance of the receiving cells
   at the matching corner.

Bridge thresholds move with the corner's `vdd` (1.62 / 1.80 / 1.98 V), not a
fixed 1.8 V domain. The fixed 1.8 V *drive* level stays as the slug README
already discloses. The VIH(1.62 V) = 1.05 V in `make-requests.py` is a repo
convention (about 0.65 x VDD), not a published PDK figure; the follow-up picks a
VIL/VIH band (or about VDD/2 with hysteresis) and states its source.

### Library, timing and corner mapping

- Cells: `sky130_fd_sc_hd`, the cells in the synthesized netlist.
- Process corner: the same `.lib sky130.lib.spice` `tt`/`ss`/`ff` as the analog
  devices. Gate delays are taken from a Liberty deck selected **per (T, Vdd)
  point** -- to be selected by the follow-up from the decks present in the pinned
  PDK install (the public library also ships 100 C decks, which may be closer
  than an `n40C` deck for the 125 C / 1.98 V point), and recorded, not assumed.
  The Liberty decks are listed per process corner, not per (T, Vdd) point, so
  several of the four points are not served exactly.
- Any interpolation between the Liberty corners and the four (T, Vdd) points is
  disclosed in each result as a deviation. It is not timing sign-off.
- That Liberty deviation travels with every digital-function result (O2-O4,
  O6), not only the timing rows.

### Provenance of per-supply currents

- `vddr1`-`vddr4` currents: transistor-level, measured as today (W1/W2).
- `vdd` current is a **mixed-provenance sum**: `I(vdd)` = sampler
  (transistor level) + digital section (gate level). `vss` returns the rings,
  the sampler and the digital section, so `i_vss_w2` is likewise mixed. In an
  event-driven co-simulation `I(vdd)` is close to sampler-only; it is **not** a
  measure of the digital supply current. The existing
  `digital_delta_i_a = I_vdd[W2] - I_vdd[W1]` already folds in the sampler's
  clocked current (the clock starts after W1) and is **not** a digital-only
  quantity.
- Reporting: `i_vdd_w1/w2`, `i_vss_w2` and `digital_delta_i_a` carry
  `provenance: "mixed"`; `digital_dynamic_power_w_estimate` carries
  `provenance: "gate-level"`. None feeds a MET verdict. **Gate-level digital
  current is not transistor-level digital evidence** (consistent with gf180-trng
  DR-0021/0023, which label gate-level power "MEASURED-at-gate-level", never a
  measured supply current).
- The sampler's own supply current is not separable from the digital share on
  `vdd`/`vss`, so it gets no MET-if-measured row: it is **UNMET with O5d**.
  A separate short transistor-level window (candidate (a)-style, with its own
  feasibility against #403) is the only route to MET for these rows and is out
  of scope here.

### Coverage table

The reducer enumerates 12 *points* and per-point problems, not these groups;
the O-IDs are **introduced by this record**. **MET-if-measured** means the row can become MET
only if the corresponding follow-up run completes cleanly and matches the
oracle at all 12 points; nothing is MET by this record.

| ID | Original obligation | Under (b) |
|---|---|---|
| O1 | 12-point matrix present (3 process x 4 (T, Vdd)) | MET-if-measured |
| O2 | Register path vs normative model (`rdata_k*`) | MET-if-measured |
| O3 | Streaming port (`out_valid_k*`, `odata_k*`) | MET-if-measured |
| O4 | `alarm`/`gated`/`startup_done` scalars | MET-if-measured |
| O5a | Ring-supply currents `vddr1`-`vddr4` (transistor-level) | MET-if-measured |
| O5d | Digital supply current / dynamic power, and the sampler's own `vdd`/`vss` current (not separable) | **UNMET** |
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
| netlist | analog side = a **partition of the flat `trng_whole.sim.spice.gz` extract** (not a separate analog-macro extract) + the gate-level digital model. `plan.json` records three distinct hashes: `flat_whole_netlist_sha256`, `analog_partition_sha256`, `digital_gate_netlist_sha256`. A check that analog + digital reproduces the whole is required: instance count (all 25 356 instances of the flat extract: 25 355 transistors plus the antenna diode on `clk`, so no device is silently dropped) and port/net correspondence against `design/trng_top.spice` and the synthesized digital netlist (or LVS) |
| measurements | names unchanged (`raw_bit_k*`, `rdata_k*_b*`, `out_valid_k*`, `odata_k*_b*`, `alarm_k*`, `gated_k*`, `startup_done_k*`, `i_*_w1/w2`, `q_*_w2`, `t_out_valid_first`, `t_clk_first`) |

### `analysis/reduce-whole-block.py`

(Paths are relative to `sim/post-layout-whole-block/`; full path `sim/post-layout-whole-block/analysis/reduce-whole-block.py`.)

| Item | Change |
|---|---|
| `expected_points()` | unchanged (12 points) |
| point status | per-point status stays MET only on clean corner + oracle match |
| new `obligations` section | one row per ID in the table above, `status` and `reasons` |
| `power.provenance` | `"mixed"` for `i_vdd_*`, `i_vss_w2`, `digital_delta_i_a`; `"gate-level"` for `digital_dynamic_power_w_estimate`; `O5d` is forced UNMET whatever the numbers are |
| `ac3_claimable` | forced `False` while any of O5d/O7/O8 is UNMET |
| `level` | new, at matrix and per-point level: from `PROVENANCE`; `"mixed-level (analog transistor / digital gate-level), connectivity-only extract (no R/C)"` when `PROVENANCE.digital == "gate-level"` |
| tests (`sim/tests/test_whole_block_reduction.py`) | add: O5d UNMET even when the corner is clean and the oracle matches; `provenance` absent -> every row UNMET; a matrix with `PROVENANCE.digital == "gate-level"` never emits an unqualified transistor-level label |

## Consequences

- The campaign becomes feasible only if the analog chain plus a gate-level
  digital block fits the ceiling; this is **not shown**. #403 produced no rate
  (a 100 ns probe also timed out; > 34.8 s per simulated ns, > 76 h lower
  bound for the full program), and the cost driver is undistinguished and stays
  under (b). The analog-chain-only probe with progress output is the first gate;
  a negative result is recorded as a negative result for (b), not worked around.
- The digital-current obligation moves to a separately tracked item with its own
  feasibility question; it is not dropped.
- All results remain simulation-derived and **provisional until measured on
  silicon**; this is not foundry sign-off.
