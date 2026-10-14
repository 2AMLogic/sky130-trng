## Configuration

- request: `sim/digital-electrical-repair/requests/control.json` (floorplan {'method': 'utilization', 'utilization_pct': 40, 'site': 'unithd', 'core_margin_um': 5, 'aspect_ratio': 1.0}, io {'layer_h': 'met3', 'layer_v': 'met2'}, power {'preset': 'sky130hd', 'power_net': 'VPWR', 'ground_net': 'VGND'}, constraints {'clock_port': 'clk', 'clock_period_ns': 20000, 'input_delay_ns': 4000, 'output_delay_ns': 4000}, seed 20260905)
- input netlist: `sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-trng_digital_synth.v` sha256 `sha256:9d2b8aed1cd057bd7985ca77e7394921a005846934a4b9c01921c56dade83126` (= klt's P&R input content_hash `sha256:9d2b8aed1cd057bd7985ca77e7394921a005846934a4b9c01921c56dade83126`); its synthesis-side klt content_hash `sha256:219738aae7c5fd3bfede92ae20bebe38e843f7341690eed151d1545a93db90ef` is the one recorded in `sim/digital-synthesis/records/20260910-001436-a4c3194.json`)
- klt `0.6.0+g10f3da34c088`, OpenROAD `26Q3-1510-g6cb3f2b704`, KLayout `0.30.12`, iverilog `Icarus Verilog version 13.0 (stable) (v13_0)`, PDK sky130A (open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b); liberty deck content_hash `sha256:8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135`

## Results

- P&R: stage `route`, die 60049.5 um2, core 54877.6 um2, utilisation 42.6334%, wirelength 66327 um, std-cell instance area n/a, route DRC 0, antenna violations 0
- DRC (`klt drc --deck sky130`): **clean**, 0 violations
- LVS (`gate-level-verilog` reference, cell-abstracted layout): **match**, 0 errors, power_connectivity `match`
- Functional co-sim of the routed netlist: **PASS** (4239 cycles, 0 mismatches)

### Post-route timing (routed DEF + extracted SPEF, 20000 ns clock, IO delay 4000 ns)

| corner | setup slack ns | hold slack ns | setup viol | hold viol | clock skew ns | max-slew viol (lib) | max-cap viol (lib) |
|---|---|---|---|---|---|---|---|
| ff_100C_1v65 | 15993.8 | 0.37033 | 0 | 0 | 0.02265 | 0 | 0 |
| ff_100C_1v95 | 15995.2 | 0.29516 | 0 | 0 | 0.01777 | 0 | 0 |
| ff_n40C_1v56 | 15992.3 | 0.4209 | 0 | 0 | 0.03077 | 0 | 0 |
| ff_n40C_1v65 | 15993.4 | 0.37213 | 0 | 0 | 0.02621 | 0 | 0 |
| ff_n40C_1v76 | 15994.2 | 0.32688 | 0 | 0 | 0.02374 | 0 | 0 |
| ff_n40C_1v95 | 15995.3 | 0.27529 | 0 | 0 | 0.01967 | 0 | 0 |
| ss_100C_1v40 | 15977.1 | 1.30978 | 0 | 0 | 0.06916 | 0 | 0 |
| ss_100C_1v60 | 15984.4 | 0.91198 | 0 | 0 | 0.04786 | 193 | 7 |
| ss_n40C_1v28 | 15945.3 | 2.5744 | 0 | 0 | 0.21096 | 297 | 10 |
| ss_n40C_1v35 | 15961.5 | 1.894 | 0 | 0 | 0.14984 | 0 | 0 |
| ss_n40C_1v40 | 15968.7 | 1.57987 | 0 | 0 | 0.11934 | 0 | 0 |
| ss_n40C_1v44 | 15972.8 | 1.40242 | 0 | 0 | 0.10357 | 0 | 0 |
| ss_n40C_1v60 | 15982.7 | 0.92914 | 0 | 0 | 0.06372 | 536 | 18 |
| ss_n40C_1v76 | 15987.5 | 0.70409 | 0 | 0 | 0.04741 | 104 | 2 |
| tt_025C_1v80 | 15992.4 | 0.4507 | 0 | 0 | 0.02672 | 0 | 0 |
| tt_100C_1v80 | 15992.4 | 0.4623 | 0 | 0 | 0.02497 | 0 | 0 |

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
