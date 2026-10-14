## Configuration

- request: `sim/digital-floorplan-compaction/requests/util55.json` (floorplan {'method': 'utilization', 'utilization_pct': 55, 'site': 'unithd', 'core_margin_um': 5, 'aspect_ratio': 1.0}, io {'layer_h': 'met3', 'layer_v': 'met2'}, power {'preset': 'sky130hd', 'power_net': 'VPWR', 'ground_net': 'VGND'}, constraints {'clock_port': 'clk', 'clock_period_ns': 20000, 'input_delay_ns': 4000, 'output_delay_ns': 4000}, seed 20260905)
- input netlist: `sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-trng_digital_synth.v` sha256 `sha256:9d2b8aed1cd057bd7985ca77e7394921a005846934a4b9c01921c56dade83126` (= klt's P&R input content_hash `sha256:9d2b8aed1cd057bd7985ca77e7394921a005846934a4b9c01921c56dade83126`); its synthesis-side klt content_hash `sha256:219738aae7c5fd3bfede92ae20bebe38e843f7341690eed151d1545a93db90ef` is the one recorded in `sim/digital-synthesis/records/20260910-001436-a4c3194.json`)
- klt `0.6.0+g10f3da34c088`, OpenROAD `26Q3-1510-g6cb3f2b704`, KLayout `0.30.12`, iverilog `Icarus Verilog version 13.0 (stable) (v13_0)`, PDK sky130A (open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b); liberty deck content_hash `sha256:8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135`

## Results

- P&R: stage `route`, die 44291.3 um2, core 39731.9 um2, utilisation 58.3625%, wirelength 64298 um, std-cell instance area n/a, route DRC 0, antenna violations 0
- DRC (`klt drc --deck sky130`): **clean**, 0 violations
- LVS (`gate-level-verilog` reference, cell-abstracted layout): **match**, 0 errors, power_connectivity `match`
- Functional co-sim of the routed netlist: **PASS** (4239 cycles, 0 mismatches)

### Post-route timing (routed DEF + extracted SPEF, 20000 ns clock, IO delay 4000 ns)

| corner | setup slack ns | hold slack ns | setup viol | hold viol | clock skew ns | max-slew viol (lib) | max-cap viol (lib) |
|---|---|---|---|---|---|---|---|
| ff_100C_1v65 | 15994.3 | 0.37001 | 0 | 0 | 0.01789 | 0 | 0 |
| ff_100C_1v95 | 15995.6 | 0.29492 | 0 | 0 | 0.01397 | 0 | 0 |
| ff_n40C_1v56 | 15993 | 0.42058 | 0 | 0 | 0.02471 | 0 | 0 |
| ff_n40C_1v65 | 15993.9 | 0.37182 | 0 | 0 | 0.02118 | 0 | 0 |
| ff_n40C_1v76 | 15994.7 | 0.32658 | 0 | 0 | 0.01905 | 0 | 0 |
| ff_n40C_1v95 | 15995.7 | 0.27503 | 0 | 0 | 0.01571 | 0 | 0 |
| ss_100C_1v40 | 15978.7 | 1.30871 | 0 | 0 | 0.05558 | 0 | 0 |
| ss_100C_1v60 | 15985.5 | 0.91126 | 0 | 0 | 0.03965 | 131 | 4 |
| ss_n40C_1v28 | 15949.8 | 2.57554 | 0 | 0 | 0.16814 | 315 | 9 |
| ss_n40C_1v35 | 15964.7 | 1.89406 | 0 | 0 | 0.11905 | 0 | 0 |
| ss_n40C_1v40 | 15971.3 | 1.57976 | 0 | 0 | 0.09686 | 0 | 0 |
| ss_n40C_1v44 | 15975 | 1.40246 | 0 | 0 | 0.0841 | 0 | 0 |
| ss_n40C_1v60 | 15984.2 | 0.92846 | 0 | 0 | 0.05221 | 581 | 16 |
| ss_n40C_1v76 | 15988.5 | 0.70357 | 0 | 0 | 0.03812 | 107 | 2 |
| tt_025C_1v80 | 15993 | 0.45029 | 0 | 0 | 0.02181 | 0 | 0 |
| tt_100C_1v80 | 15993 | 0.46191 | 0 | 0 | 0.02029 | 0 | 0 |

(slew/cap columns are the in-flow `klt place-and-route` sweep's, estimated from global-route parasitics; setup/hold are from `klt sta` with the extracted SPEF.)

### Negative controls

- `lvs-pin-swap`: swapped A_N/B nets on one nand2b (raw_count[3] <-> _1411_) -> detected = **True**
- `lvs-instance-deleted`: deleted nor2_1 instance _1440_ -> detected = **True**
- `sta-clock-period-1ns`: same routed DEF+SPEF at tt_025C_1v80, clock_period_ns 1.0 with IO delays 0.2 ns (a 1 GHz target the routed design must miss; a 5000 ns clock with the 4000 ns IO delays unchanged was tried first and still passed, so it is not a valid control) -> detected = **True**
- `cosim-xor-to-and`: 19 xor2_1 instances replaced by and2_1 in the routed netlist -> detected = **True**

## What this record does and does not establish

- Established: the committed request places and routes `trng_digital` with sky130_fd_sc_hd; geometry, as-built netlist, SPEF and SDF are produced and hashed.
- DRC is the **klt `sky130` curated deck** (`klt drc --deck sky130`) over the standard-cell-merged GDS -- not the foundry signoff deck; its `coverage` block lists unsupported/skipped rules (see `layout/trng_digital/drc.json`). Metal fill / density rules are not covered by this flow (no fill step), so density-rule cleanliness is NOT claimed.
- LVS is **cell-level**: layout is extracted with standard cells as opaque black boxes (`--abstract-cells`), reference is the as-built Verilog, which carries **signal pins only** -- intra-cell transistors are not compared (cell internals are the PDK's), and a power-net defect is invisible to the Verilog-derived compare except for klt's own `power_connectivity` check. Filler/tap cells inserted by the flow are pruned from the compare (`topology.power_only_pruned`), not matched. The top-level `VPWR`/`VGND` supply ports exist only as layout pins/labels.
- Timing is `klt sta` (OpenSTA) on the routed DEF with SPEF extracted from the routed GDS, at every shipped `sky130_fd_sc_hd` Liberty corner (16, incl. the 1.28-1.95 V ss/ff voltages). The routed interconnect corner is `nom` only; the SPEF is a first-order lumped RC (no coupling-aware signoff extraction). Clock is ideal-propagated through the CTS tree. Constraints: one clock (`clk`, 20000 ns), input/output delays 4000 ns, no false-path / multicycle exceptions; `rst_n` is analysed as an ordinary constrained input. klt reports `timing_status: constrained` but no explicit unconstrained-endpoint list -- completeness of constraint coverage is therefore not independently enumerated.
- SPEF annotation: 2309/2309 design nets annotated; the SPEF also contains non-design (`$N`) fragments OpenSTA ignores (reader warnings recorded in `sta.json`).
- In-flow max-slew / max-capacitance checks (global-route estimate) report library-limit violations at the low-voltage ss corners (ss_100C_1v60, ss_n40C_1v28, ss_n40C_1v60, ss_n40C_1v76) -- see the table; these are DESIGN-RULE violations NOT repaired by this flow and are disclosed, not waived. They do not affect setup/hold at a 20000 ns clock.
- Functional co-simulation of the routed netlist uses `FUNCTIONAL`/`UNIT_DELAY #1` cell models: it verifies logic equivalence to the normative model over the directed program, NOT timing (no SDF annotation; the generated SDF is committed but not simulated).
- Not covered here (remains on #18): analog/digital top-level composition, the 1.8 V supply distribution across the full block, IR drop (`klt power`), dynamic-power numbers, antenna/ESD at pad level, whole-block brief reconciliation. Simulation-derived; provisional until silicon.
