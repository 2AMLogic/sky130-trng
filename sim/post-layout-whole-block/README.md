# post-layout-whole-block -- whole-block characterization (issue #174)

Append-only slug for the composed `layout/trng_whole/trng_whole.gds`
(sha256 `af2f8dfe2800599e97d769bdedd14924c9fa3f24fc7e1c4f43ccd72ac5572ddd`,
top `trng_whole`, 123 ports). Part of #170; contributes to #18 AC3.
Provisional, simulation-derived, not foundry sign-off, **not silicon**.

**Status of this slug: the 12-point transistor-level matrix is UNMET and
#18 AC3 is NOT claimed.** The dated record under `records/` states, per point,
why. In one line: the klt batch fleet refuses every submission from this repo's
klt (`batch_runner_version_mismatch`, runner image klt 0.5.0 vs client 0.7.0,
klayout-tools#2948/#2851), the fleet's shared concurrency cap was also full
for most attempts (klayout-tools#2917), and the one local single-corner probe
that the host rules allow did not finish. Nothing in this slug was computed by
a hand-launched ngspice grid.

How the whole-block work is to be reduced (analog at transistor level, digital at gate level; digital-current, IR and `Ts` rows stay UNMET): `spec/decision-records/DR-0017-whole-block-reduced-work-pvt.md` (Accepted 2026-11-05, #404).

## What is in the slug

| Path | What |
|---|---|
| `make-netlist.py` | `klt extract --deck sky130 --pdk sky130A` over the committed GDS, then recorded text transforms (port canonicalisation of header AND device body, `$` scrubbing, bracket de-indexing; #435). **Connectivity netlist: devices and nets of the layout, no extracted parasitics (no R/C).** The port map follows `-o` (`OUT.spice` -> `OUT.ports.json`, #478), so only a default-output run writes the committed map. `--check` is a byte compare and reproduces only under the klt build that produced the committed netlist, `0.9.1.dev102+gef1ec19c95f6` (see the next row); on any other build it reports the port-order difference and names both builds. |
| `trng_whole.sim.spice.gz`, `trng_whole.sim.ports.json` | its output (plain-text sha256 `965f1e6c29d771d5b8e18a3ea66ccabf93f0a5eb14c3f0c23810f39ae1052c36`, 25 355 X-instances of `sky130_fd_pr__{nfet,pfet,special_nfet}_01v8` + 1 `sky130_fd_pr__diode_pw2nd_05v5` X-instance, 123 ports) and the port-order map. The plain 15 MB copy is gitignored; `make-requests.py` reads the gz. **Produced by klt `0.9.1.dev102+gef1ec19c95f6`**; the top-level `.SUBCKT` port order is a klt-build artefact (klayout-tools#5534), so `--check` reproduces these bytes only under that build: `uvx --from "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@ef1ec19c95f6" python3 sim/post-layout-whole-block/make-netlist.py --check` -> `check OK: byte-identical, 123 ports, 25356 devices`. Record: `records/20261113-ports-order-klt-build.md` (#478). |
| `test_make_netlist.py` | the klt-free unit tests, run on every pull request (`.github/workflows/ci.yml`): the `$`-scrub collision guard, the pw2nd diode card rewrite, the all-card-type model check, the #435 body rename, and (#478) that the port map follows `-o` and that the committed header order still equals the committed `ports.json` order. No klt, no PDK, no GDS, no ngspice. |
| `check-bin-coverage.py` | scans every device card of a flat netlist against the pinned PDK's model bins (control: pre-fix netlist reports 1760 uncovered, committed reports 0). Record: `records/20261029-bin-coverage-scan.md` (issue #386). |
| `records/20261030-fleet-probe-post-bin-fix.md` | one-unit fleet probe after the bin fix: ngspice gets past parse, then times out at 3480 s in analysis (issue #386, `runs/20261030-probe-post-bin-fix/`). |
| `program.py` | the one directed bus program (75 cycles, `Ts = 100 ns`, `T0 = 320 ns`): ID / HT_STARTUP / STATUS reads with `EN=0`, `CTRL.EN` write, 32 raw samples, `STATUS`/`RAW_DATA`/`ID`/`DATA`/`ALARM`/`STATUS` reads, 32 samples with `out_ready=1`, final `STATUS`; plus `model_replay()` which replays it through the normative model `digital/model/`. Since #804 it also owns what every deck and reducer takes from that program: the shared deck constants (`VIH`, `W1`, `RAILS`, `ROUTED_V`), the `.meas` card sets (`gate_measurement_cards`, `coupled_measurements`, `whole_block_measurement_cards`, over one collector that clips past `t_stop` and refuses a repeated name) and the rail-bounded response comparator (`decode` / `response_checks`), so `make-requests.py`, `make-gate-model.py` and the two analysis CLIs import them instead of executing a sibling CLI. Since #815 it also owns the coupled matrix set (`coupled_matrix_measurements`: the coupled set plus the ring-rail W1/W2 currents and the throughput tap, the shared cards byte-identical) and the coupled oracle's two shared pieces -- `sampler_valid` (the `raw_valid` the sampler itself shows) and `coupled_capture_decode` (every cycle's strobe and bit, decoded against the point's own rail) -- that both the nominal comparator and the 12-point reducer replay through. |
| `make-requests.py` | emits the `klt sim` requests: `--set controls` (startup probe, local + batch), `--set grid` (since #815: **twelve coupled requests, one per matrix point**, `grid-<proc>-<m40C|27C|125C>-<supply>V`, each one process at one (T, Vdd) on all five rails, `backend: batch`, `save_mode: netlist`, 917 measurements) and `--set coupled-probe` / `--set coupled-full` (the nominal coupled rate experiment). Each driven input's `PWL` card **holds its value and then switches over `EDGE_NS` = 0.1 ns** ending at `t_edge(k) + SKEW_NS`; a breakpoint list carrying only the change instants makes a `PWL` source ramp across the whole hold interval instead (#488, `records/20261114b-pwl-hold-point-stimulus-fix.md`). The committed `corners/*/plan.json` predate that fix and are **not** regenerated -- the next run writes a fresh corner directory, and no committed report has a measurement. Since #595 each grid request's `plan.json` also carries `gate_model_pvt`: the boundary-load option (2) plus the digital half's Liberty deck (path + sha256 + error directions, since #815 the point's own single row) from `pvt_deck_map.py`, with an unmapped point failing generation closed. (#646: a read in the LAST cycle no longer emits its 32 `rdata_k74_b*` cards.) Since 2026-11-28 the grid's timeouts are sized from the measured coupled run (`records/20261128-coupled-rate.md`): `timeout_s` 864 s per unit (2x the measured 431.63 s), and since #815 `poll_timeout_s` 1284 s (one single-process unit's 984 s bound plus 300 s), the basis in `plan.json.timeouts`; a set the fleet's 3,600 s ceiling cannot hold refuses generation. **Since #815 the grid set emits the coupled deck per point** (DR-0017 option (b)): the extracted analog partition driving a gate model built for that point by the generator's emitter (`gate_model_lib.build_gate_model`, imported -- never the sibling CLI executed) from the deck the point maps to (the 8 distinct decks parsed once), with the 75-cycle program, the fixed 1.8 V input-high convention and the sampler as the sole source of both raw signals, plus `program.coupled_matrix_measurements` (the ring-rail W1/W2 currents and the throughput tap for O5a/O6). Its plan records the three partition hashes, the emitted netlist, gate model and Liberty sha256s and the point's `gate_model_pvt` deviations. Building the models needs the decks: `--libs-ref <dir>` (a sky130A install's `libs.ref`) or a resolvable `klt pdk find`; with neither, `--set grid` refuses before writing anything. The four committed `corners/grid-*` requests are the archived **flat-deck** grid (`grid-<T>-<V>`, three processes each, 21,600 / 6,600 s); they keep their filed values, are never regenerated, and never collide by name with the coupled set. |
| `test_make_requests.py` | the klt-free unit tests of the request generator's driven-input stimulus, run on every pull request (`.github/workflows/ci.yml`): every emitted `PWL` card evaluated at every cycle's `t_edge + CAPTURE_NS` must sit within 1 mV of a rail (the #488 control -- it fails on the pre-fix change-instants-only shape, where 344 of 3000 samples were >10 % off a rail), the hold/edge pair is asserted on the card text, breakpoint hygiene is checked (`t=0` first, `t_stop` last, no two breakpoints sharing a `f"{t:.1f}n"` timestamp, a constant input still two points), and `GRID_TIMEOUT_S` plus the committed grid requests' timeouts are pinned; (#507) every emitted measurement's `AT=`/`TO=` must sit within its own request's `.tran` stop across all four `--set` groups, the committed startup probes' nine over-`t_stop` cards are pinned in a known-stale ledger over `corners/*/request.json`, and the startup-probe timeouts (generator 3600 / 3480 + poll 3700 vs the committed batch pair's 14400 / 7000) are pinned (`records/20261115a-known-stale-startup-probe-requests.md`); (#646) a read in the last cycle emits no `rdata_k74_b*` measurement (card count 610 -> 578), earlier reads keep all 32 bits each, and a truncation whose last cycle is not a read changes nothing; (#595) the matrix-to-deck table covers tt/ss/ff x `GRID` exactly, every row IS the nearest shipped deck under the |dV|-first rule with self-consistent direction/estimate fields, an unmapped point fails `deck_row` and grid generation closed (with nothing written), and every generated grid plan carries `gate_model_pvt`; (#815) the twelve coupled grid requests are generated offline against a synthetic PDK (`SyntheticPdk`: the 8 mapped decks built from the 64 cells' committed pin/function structure, a distinct delay scale per deck) and checked for identity, mapped Liberty deck and sha256, per-deck delays, bridges and logic supply at the point's supply, partition/netlist hashes, the coupled matrix measurement set, the sampler as sole raw source at the fixed VIH, the 1-unit timeouts, the 8-deck parse cache, and the refusals (no PDK / no `--libs-ref`, a `--libs-ref` that is not a `libs.ref`, decks that do not hash to the pins, an unmapped point). Against the real install, `TestAgainstRealPdk` (skipped without it) checks every point names its pinned deck on disk and that the nominal point's gate model is the committed, measured one byte for byte. No klt, no PDK, no ngspice. |
| `corners/<req>/` | request, plan (input hashes), report, stderr and `submit-attempts.log` for every submission, **including the failed ones** (they are the evidence). `netlist.cir` per request is gitignored (regenerated; sha256 in `plan.json` and the report). |
| `ir/run-ir.py`, `ir/*.json*` | `klt power` extraction + static IR (see below). |
| `analysis/reduce-whole-block.py` | the reduction: enumerates the 12 points itself, marks a point MET only on a clean corner + oracle match, everything else UNMET with a reason; mints the record. Since #815 each `grid-*` report is first matched against its own `plan.json` / `request.json` (the deck it ran is the deck the plan hashed; each corner is one of the plan's points on all five rails) -- a mismatch is UNMET on the point it reports *and* on the point its plan asked for, unscored, and a second report claiming a point is UNMET rather than picked between -- and a coupled plan (`raw_source == "analog_sampler"`) is scored through the sampler's oracle (`program.sampler_valid` + `coupled_capture_decode`, every level against the point's own rail) over the coupled matrix set; any other plan, or none, keeps the flat-deck contract, so the archived flat `corners/grid-*` stay readable. Tested by `sim/tests/test_whole_block_reduction.py` (complete matrix MET; an omitted point, oracle mismatch, absent measurement, errored corner and klt error envelope are each UNMET; the committed nominal coupled capture replays to 75 strobes and 311 responses, and a corrupted capture, omitted current, wrong-point report, other deck, rail mismatch, duplicate point and failed unit are each UNMET). |
| `make-gate-model.py` | the **gate-level model of the digital half** (DR-0017 option (b), issue #486): every `sky130_fd_sc_hd` instance of `layout/trng_digital/trng_digital.routed.v` becomes one XSPICE event-driven primitive (`d_genlut` / `d_dff`) carrying scalar rise/fall delays reduced from one Liberty deck, with `adc_bridge`/`dac_bridge` at the boundary; emits the model, a manifest, and a runnable `klt sim` request. **Fails closed** on an unknown cell, an output pin with no Liberty `function` and no `ff` group, a multiply-driven or undriven net, or a flop with no `d_dff` mapping -- and writes nothing. Record: `records/20261114-gate-model-realisation.md`. Since #595: `--point PROC:TEMP_C:VDD` takes the Liberty deck from `pvt_deck_map.py` (sha256-pinned, unmapped points refused) and derives the bridge supply, temperature and process corner from the point; every plan carries the boundary-load option (2). Since #815 the XSPICE emitter (`build_gate_model`) and the deck-to-cells loader live in `gate_model_lib.py`, re-exported here, so `make-requests.py --set grid` builds one model per matrix point by import instead of running this CLI twelve times. |
| `analysis/compare-gate-model.py` | the oracle comparison and rate reduction for a gate-model run: decodes each measured level (refusing anything that is not a resolved rail, so an UNKNOWN net can never round to 0), compares every digital response with `program.model_replay()`, and scores the measured s-per-simulated-ns against the pass criterion computed from the same constants. For a coupled deck (`plan.raw_source == "analog_sampler"`) the model is replayed with the captured sampler input and the strobes are checked against the sampler's documented `raw_valid`, not the standalone testbench's per-cycle strobe; since #815 that reference (`program.sampler_valid`) and the every-cycle strobe/bit decode (`program.coupled_capture_decode`) are `program.py`'s, shared with the 12-point reducer. |
| `pvt_deck_map.py` | the single source of truth for #595's two choices: the boundary-load option (2, Liberty input-pin capacitance of the receiving cells at the mapped deck) and the 12-row matrix-to-deck mapping -- each row a named deck, its pinned sha256, dT/dV, and the delay/power error directions under the declared nearest-deck rule (min \|dV\| first, tie-break \|dT\|). `deck_row`/`plan_entry` fail closed on unmapped points and on a PDK whose decks hash differently. Record: `records/20261121-pvt-deck-and-boundary-load.md`. |
| `analysis/deck-axis-sensitivity.py` | the #595 direction evidence, pure Liberty parsing over the cell types the routed netlist uses: per-axis delay and `cell_leakage_power` ratios between deck pairs that isolate temperature (fixed V) and supply (fixed T). Finding: both sensitivities have the same sign (faster warm AND faster at high V -- temperature inversion), so every mapped row's net delay direction is established. Run on request (needs the PDK), not a CI test. |
| `sim/tests/test_gate_model.py` | the klt-free unit tests of the generator, run on every pull request: the committed manifest is checked against a fresh parse of the routed netlist (every instance accounted for, histogram, port list, DR-0017 boundary), the Liberty-function to truth-table mapping and the NLDM bilinear interpolation are checked on hand-computed values, and six refusal paths are checked to exit non-zero leaving no output; (#595) `--point` parsing/refusal paths are klt-free, and against the PDK all 12 pinned deck hashes match disk and a `--point` run carries the mapping in its plan and request. No klt, no PDK, no ngspice (the PDK-gated class skips without it). |

## The four PVT points

Resolved from the decision records, not the planning document: DR-0010
row 9 ratifies the envelope as 1.62 / 1.8 / 1.98 V (1.8 V +/-10 %) and
-40 / 27 / 125 C, and DR-0003 section 5 / DR-0008 fix the four (T, Vdd)
points every post-layout campaign in this repo uses:
(-40 C, 1.62 V), (27 C, 1.80 V), (-40 C, 1.98 V), (125 C, 1.98 V), each x
`tt`/`ss`/`ff` = 12 points. All five supplies (`vdd`, `vddr1`-`vddr4`) move
together with the point. Digital input high level is fixed at 1.8 V at every
corner (VIH(1.62 V) = 1.05 V accepts it); the supply sources carry the corner.

## Assumptions (declared, per the issue)

* Clock `clk` period `Ts = 100 ns`, **not DR-0003's 20 us** -- the same
  compute-budget deviation every post-layout sampler deck here states. The
  digital section is synchronous, so the program's cycle behaviour is
  independent of `Ts`; the analog sampling aperture is not, so raw-bit
  statistics from these decks are not entropy evidence at the ratified `Ts`.
* Reset: `rst_n` low until 300 ns; `clk` starts at 320 ns. Rings enabled at 5 ns.
* Loading: only the testbench's PWL/PULSE sources drive inputs; outputs are
  unloaded (no pad/off-chip capacitance model exists in the repo).
* Raw-tap boundary: the real post-layout sampler's `raw_bit`/`raw_valid`
  (internal to `trng_whole`) are measured at `Tedge(k)+80 ns` and fed to the
  normative model as the oracle's raw-tap stimulus.
* Throughput tap: `t_out_valid_first`, the first rise of `out_valid` (word
  availability after 32 raw samples at `Ts`). The start-up gate keeps
  `gated=1` for the 1024-sample window, which the budget cannot reach, so the
  conditioned `DATA` path is exercised only as a blocked read.
* Digital library/corner mapping: the digital cells are the extracted
  sky130_fd_sc_hd transistors, simulated with the same `.lib sky130.lib.spice`
  `tt`/`ss`/`ff` process corner as the analog devices (not Liberty STA).
* Power windows: W1 = rings running, digital reset-held, `clk` not started;
  W2 = every program cycle. Sign: `i(Vsrc)` is negative when the source
  delivers; the reducer negates. "Dynamic" digital power is
  `(I_vdd[W2] - I_vdd[W1]) * Vdd` for this program's activity only; leakage and
  dynamic are not otherwise separable in a transient.

## Static IR (`klt power`), what exists

`ir/run-ir.py` runs `klt power` on the committed GDS (top `trng_whole`) with:
met1-met5 sheet resistances and via/via2/via3/via4 resistances read from
the sky130A magic tech file in the PDK install (met1-met5: 0.125 / 0.125 / 0.047 / 0.047 /
0.029 ohm/sq; vias 4.5 / 3.41 / 3.41 / 0.38 ohm), pads at the 16 boundary-pad
coordinates of `layout/trng_whole/interface.json`, and **only the four
ring-supply loads**, each 20.55 uA at its ring island's node centroid (DR-0003's
per-ring running-current *maximum*, ff / -40 C / 1.98 V; ring ground returns on
`vss`). Results (`ir/summary.json`): worst droop **8.05 mV on `vss`**
(`(308.7, 295.0)` um, met1; 82.2 uA total ring return through ~98 ohm of
`vss` grid) and 0.30-0.36 mV on `vddr1`-`vddr4`.

This is a **partial, assumption-loaded** result, not whole-block IR:

* `li1` and `mcon` are omitted from the stackup: with `li1` declared, `klt power`
  cannot decompose the whole-block `li1` polygons (4096-mesh-cell cap,
  klayout-tools#3124) and every island is unsolved. The result is a met1-met5
  grid only.
* The logic supply `vdd`/`vss` carries **no digital load**: the transistor-level
  run that would supply digital and sampler currents did not complete, so the
  digital IR is not evaluated. `vdd` has one pad-connected island solved
  (zero load, zero droop by construction) and 12 islands with no pad path
  (`unsolved_reason: no_pad`), listed in `summary.json`.
* EM: no per-role current limits were declared, so `em_verdict` is
  `not_checked`.

## Reproduce (representative, isolated output)

```bash
python3 sim/post-layout-whole-block/test_make_netlist.py # generator + committed-pair contract, no klt
python3 sim/tests/test_whole_block_reduction.py          # reducer contract, no simulator
python3 sim/tests/test_gate_model.py                     # gate-model generator, no klt/PDK/ngspice
python3 sim/post-layout-whole-block/make-gate-model.py /tmp/gm --cycles 0   # the gate-level deck
python3 sim/post-layout-whole-block/make-requests.py /tmp/wb --set controls   # needs the gz netlist only
python3 sim/post-layout-whole-block/make-requests.py /tmp/wb-grid --set grid  # 12 coupled requests; needs the PDK's decks
                                                                          # (klt pdk find, or --libs-ref <libs.ref dir>)
python3 sim/post-layout-whole-block/ir/run-ir.py /tmp/wb-ir                    # ~10 s; summary.json must equal committed
```

`klt sim` needs **absolute** `-o`/request paths (relative `-o` makes ngspice
never start; klayout-tools#2892/#2939).

## DR-0017 option (b): provenance, partition, and what is still open (issue #431 Step 2)

Level of any result produced under option (b), worded verbatim wherever it is
reported: **mixed-level (analog transistor / digital gate-level),
connectivity-only extract (no R/C)**. `program.PROVENANCE` carries it; every
`plan.json` records it and the reducer writes it at matrix and point level.
`i_vdd_*`, `i_vss_w2` and `digital_delta_i_a` are `mixed`;
`digital_dynamic_power_w_estimate` is `gate-level`. The reducer's `obligations`
section lists O1-O8; **O5d, O7, O8 are forced UNMET** and `ac3_claimable` is
`false` (#18 AC3 stays UNMET). A reduction with no recorded provenance marks
every point and every row UNMET.

Partition: `make-requests.py` splits the flat `trng_whole.sim.spice.gz` extract
at composed y = 250 um (analog macro above, digital macro below; empty band
240-260 um) and `partition_check()` asserts, before any `plan.json` is written:
25 356 instances = 264 analog transistors + 25 091 digital transistors + the
antenna diode; the flat `.SUBCKT` ports equal `trng_whole.sim.ports.json`
(123); the nets both halves touch are exactly `clk`, `rst_n`, `raw_bit`,
`raw_valid` (+ `vdd`/`vss`). `plan.json` records `flat_whole_netlist_sha256`,
`analog_partition_sha256` and `digital_gate_netlist_sha256` (the routed
gate-level `layout/trng_digital/trng_digital.routed.v`) -- true of every
`plan.json` the generator writes since #431, but **not** of the six committed
ones (`grid-m40C-1.62V`, `grid-27C-1.80V`, `grid-m40C-1.98V`,
`grid-125C-1.98V`, `startup-probe`, `startup-probe-batch`), which predate
those fields and are not regenerated (#507,
`records/20261115a-known-stale-startup-probe-requests.md`). The check is a
transistor-count and net-name correspondence, not an LVS of the gate-level
netlist against the transistor-level digital macro.

**Done: the ngspice realisation of the gate-level digital half (issue #486).**
DR-0017's open choice between event-driven co-simulation and a timed-delay
netlist is settled as a **timed-delay XSPICE netlist** (`make-gate-model.py`:
2321 routed instances -> 1808 `d_genlut` + 456 `d_dff` + 57 declared load-only
no-ops, plus 1 declared polarity inverter), and it is **feasible**: the whole
committed program (75 cycles, 7870 ns) runs at tt / 27 C / 1.8 V in 76.716 s =
**0.00975 s per simulated ns**, against a pass criterion of <= 0.3852 s/sim-ns
stated before the run (**39.5x margin**), with **311 of 311** compared digital
responses equal to the normative model's. Level of that result, worded
exactly: **gate-level digital section only**, driven by testbench sources at
its boundary -- *not* the mixed-level whole block. Record:
`records/20261114-gate-model-realisation.md`; runs
`runs/20261114-gate-model-probe/` and `runs/20261114-gate-model-full/`.
`d_cosim` co-simulation remains the documented fallback.

**Nominal coupled deck (#596).** The 264-transistor analog partition now drives
the archived routed gate model through the sampler's extracted `raw_bit` and
`raw_valid` nodes. The two partitions share one clock, reset and pair of logic
rails. Generate the 100 ns probe or full 7,870 ns request with
`make-requests.py <empty-dir> --set coupled-probe` or `--set coupled-full`.
Each produces one tt / 27 °C / 1.8 V batch unit. The full request records the
sampler at every cycle for replay by `analysis/compare-gate-model.py`.

**Measured: the coupled whole block fits the ceiling (DR-0017 option (b),
2026-11-28).** Both coupled units ran on the batch fleet from a host with the
fleet submit profile. The 100 ns probe (`klt-sim-1d857d429e5a`) took 14.291 s;
the full 7,870 ns program (`klt-sim-7d6f0e6f474f`) took **431.63 s = 0.0548 s
per simulated ns** against the 0.38119 s/ns budget fixed before any
submission (**6.9x margin**): **feasible**. 311 of 311 digital responses equal
the normative replay of the captured sampler input. Level of that result,
worded exactly: **mixed-level (analog transistor / digital gate-level),
connectivity-only extract (no R/C)** -- one nominal point, no characterisation
credit, O5d / O7 / O8 and #18 AC3 unchanged. Finding: the sampler's
`raw_valid` is high one clock after reset and stays high
(`design/sampler_core.spice` `xsv`, `design/README.md`), where the standalone
decks' testbench holds it low in every bus cycle. Once enabled, the digital
section therefore samples in those cycles too. The coupled comparator checks
the strobes against the sampler, not against that schedule; 6 of the 311
responses differ from the standalone run's, for that reason and because the
bits are the sampler's. Record: `records/20261128-coupled-rate.md`; runs
`runs/20261128-coupled-probe/` and `runs/20261128-coupled-full/`.

**Done: the boundary-load model and the per-point Liberty deck (issue #595).**
DR-0017's two remaining per-point choices are made, recorded
(`records/20261121-pvt-deck-and-boundary-load.md`) and executable: the
boundary load is **option 2** (the Liberty input-pin capacitance of the
receiving cells at the mapped deck; option 1 would have moved instances
across the `partition_check()` partition, and extracted net capacitance does
not exist -- the committed extract is connectivity-only), and every one of
the 12 matrix points maps to **one named deck, pinned by sha256**, in
`pvt_deck_map.py` -- nearest deck under a declared |dV|-first rule, with the
delay and power error direction stated per row. Canary finding on the way:
this library is *faster* warm (temperature inversion) *and* faster at high
supply, so both axes err the same way and every row's net direction is
established (`analysis/deck-axis-sensitivity.py`); the worst-served point is
ss / 125 C / 1.98 V (~+52 % delay, deck 165 K cold and 0.22 V low) and the
only strongly optimistic one is tt / -40 C / 1.62 V (~-20 %). `--set grid`
plans carry `gate_model_pvt` per request; `make-gate-model.py --point
PROC:TEMP:VDD` takes its deck from the table and fails closed on any
unmapped point.

**Open**

* The 12-point matrix (#307) is prepared but not run (#815). `--set grid` emits
  the coupled deck per point -- twelve single-process requests
  `grid-<proc>-<T>-<V>`, each the analog partition driving a gate model built
  for that point from its mapped Liberty deck -- with `timeout_s` 864 s and
  `poll_timeout_s` 1284 s (2x the measured nominal runtime; one request is one
  unit, job bound 984 s under the 3,600 s ceiling; `plan.json.timeouts`
  records the basis). It refuses what the ceiling cannot hold, and refuses
  outright without the PDK's decks (`--libs-ref`, or a resolvable `klt pdk
  find`). `analysis/reduce-whole-block.py` matches each report to its plan,
  deck and point and replays the sampler's strobes through the shared coupled
  oracle. Remaining before submission: the slow-corner runtime measurement and
  margin selection (#814), then the fleet submission, evidence publication and
  scorecard (#307). [Rate and functional
  gate](records/20261128-coupled-rate.md).
* Full-block 100 ns rate probe on the re-pinned **flat** netlist (`965f1e6c...`): one batch job was
  interrupted by spot reclamation at 3279 s, no verdict (the retry below settled it). See
  `records/20261106-rate-probe-repinned-netlist.md`.
* Retry of that probe (issue #449): timed out at 3480 s on the same re-pinned netlist, 0 of 9
  measurements; infeasible verdict confirmed. That verdict is the flat deck's and stands; DR-0017
  option (b) replaced the flat route, and its coupled deck is measured above. See
  `records/20261106b-rate-probe-repinned-timeout.md`.
* An independent cross-check of a gate-model response against
  `sim/digital-sdf-timed-verification/`'s Icarus + SDF run at the same
  `tt_025C_1v80` corner (a different simulator and a different timing
  mechanism): available, not wired up (#812).
