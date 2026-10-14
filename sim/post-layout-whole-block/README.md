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

## What is in the slug

| Path | What |
|---|---|
| `make-netlist.py` | `klt extract --deck sky130 --pdk sky130A` over the committed GDS, then three recorded text transforms (port canonicalisation, `$` scrubbing, bracket de-indexing). **Connectivity netlist: devices and nets of the layout, no extracted parasitics (no R/C).** The extract takes more than 10 minutes on this host; `--check` was not re-run this pass (it would re-run the whole extract). |
| `trng_whole.sim.spice.gz`, `trng_whole.sim.ports.json` | its output (plain-text sha256 `75d561b85975d56999a5148d743bf13844aca36970c505e28d588b7045620502`, 25 355 X-instances of `sky130_fd_pr__{nfet,pfet}_01v8`, 123 ports) and the port-order map. The plain 15 MB copy is gitignored; `make-requests.py` reads the gz. |
| `program.py` | the one directed bus program (75 cycles, `Ts = 100 ns`, `T0 = 320 ns`): ID / HT_STARTUP / STATUS reads with `EN=0`, `CTRL.EN` write, 32 raw samples, `STATUS`/`RAW_DATA`/`ID`/`DATA`/`ALARM`/`STATUS` reads, 32 samples with `out_ready=1`, final `STATUS`; plus `model_replay()` which replays it through the normative model `digital/model/`. |
| `make-requests.py` | emits the `klt sim` requests: `--set controls` (startup probe, local + batch) and `--set grid` (four requests, one per (T, Vdd) point, each bundling `tt`/`ss`/`ff` = the 12-point matrix, `backend: batch`, `save_mode: netlist`, 610 measurements each). |
| `corners/<req>/` | request, plan (input hashes), report, stderr and `submit-attempts.log` for every submission, **including the failed ones** (they are the evidence). `netlist.cir` per request is gitignored (regenerated; sha256 in `plan.json` and the report). |
| `ir/run-ir.py`, `ir/*.json*` | `klt power` extraction + static IR (see below). |
| `analysis/reduce-whole-block.py` | the reduction: enumerates the 12 points itself, marks a point MET only on a clean corner + oracle match, everything else UNMET with a reason; mints the record. Tested by `sim/tests/test_whole_block_reduction.py` (complete matrix MET; an omitted point, oracle mismatch, absent measurement, errored corner and klt error envelope are each UNMET). |

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
python3 sim/tests/test_whole_block_reduction.py          # reducer contract, no simulator
python3 sim/post-layout-whole-block/make-requests.py /tmp/wb --set controls   # needs the gz netlist only
python3 sim/post-layout-whole-block/ir/run-ir.py /tmp/wb-ir                    # ~10 s; summary.json must equal committed
```

`klt sim` needs **absolute** `-o`/request paths (relative `-o` makes ngspice
never start; klayout-tools#2892/#2939).
