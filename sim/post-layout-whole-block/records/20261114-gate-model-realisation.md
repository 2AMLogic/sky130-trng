# 20261114 -- DR-0017 option (b) step 2, slice 1: the gate-level digital half is realised as a timed-delay XSPICE netlist, and it is FEASIBLE (issue #486)

**Claim**: DR-0017's open choice between event-driven co-simulation and a
timed-delay netlist is settled as a **timed-delay XSPICE netlist**: every
`sky130_fd_sc_hd` instance of `layout/trng_digital/trng_digital.routed.v`
becomes one XSPICE event-driven primitive carrying scalar rise/fall delays
reduced from one Liberty deck, with `adc_bridge`/`dac_bridge` cards at the
boundary. The generated model runs the whole committed directed program
(75 cycles, 7870 ns) at tt / 27 C / 1.8 V in **76.716 s**, i.e. **0.00975 s per
simulated ns**, against a pass criterion of **<= 0.3852 s per simulated ns**
stated before the run: **39.5x margin, PASS**. All **311** compared digital
responses equal the normative behavioural model's.

**Level of this result, worded exactly**: **gate-level digital section only**,
driven by testbench sources at its boundary -- **not** the mixed-level whole
block. Nothing here is a whole-block result, nothing here is claimed for
#18 AC3 (still UNMET, `ac3_claimable` still `false`), and no obligation
changes: O5d, O7 and O8 stay forced UNMET. `GRID_TIMEOUT_S` (21600) and the
grid requests' `poll_timeout_s` (6600) are **not** re-set by this record.
Provisional, simulation-derived, not foundry sign-off, **not silicon**.

## The realisation, and why this one

Chosen: **timed-delay XSPICE netlist** (`make-gate-model.py`). Rejected, with
the reason:

| Option | Why not |
|---|---|
| `d_cosim` event-driven co-simulation (Verilator 5.050 is on PATH) | needs a cosim shared object built per netlist and per corner, and the delays would still come from Liberty outside ngspice, so it adds a build dependency without removing the Liberty mapping. **Kept as the documented fallback** if a `d_genlut` width or fan-in limit ever bites; the widest cell here is 6 inputs (`a222oi_1`), measured working. |
| Decoupled Icarus + SDF run | already exists at `sim/digital-sdf-timed-verification/`, and DR-0017 names it: it "cannot by itself supply the boundary load", so it cannot be the whole-block realisation. |
| A behavioural stand-in for the digital section | forbidden by DR-0017 ("no workaround, no behavioral stand-in"). |

Three properties made the chosen one work, each checked rather than assumed:

1. It needs **no `.control` block**. `klt sim` owns `.lib`/`.temp`/`.tran` and
   the `.control` block and takes a circuit body; a `d_*`-plus-bridge netlist
   is exactly a circuit body. Confirmed from the generated corner deck
   (`runs/20261114-gate-model-full/out1/tt_novdd_27C/corner.cir`): klt added
   `.lib`, `.include`, `.temp`, the 749 `.meas` cards, `.tran` and `.control`
   around an untouched body.
2. The primitives ship with ngspice. `digital.cm` in ngspice-47p1 **and**
   ngspice-46 -- the build the fleet runner used for
   `records/20261105-analog-chain-probe.md` -- both carry `d_genlut`, `d_dff`,
   `d_inverter`, `adc_bridge` and `dac_bridge`, and `spinit` autoloads every
   `.cm`. Not a local-only capability.
3. The cell universe is small and closed: **2321 instances, 64 distinct cell
   types**, 63 of them combinational with a Liberty `function` on the output
   pin, 2 sequential (`dfrtp_1` 424, `dfstp_1` 32), 1 antenna tie.

## What was generated

`sim/post-layout-whole-block/make-gate-model.py`, from
`layout/trng_digital/trng_digital.routed.v`
(sha256 `9f3956848e6e75223f75bd154df905fecbb4e988593e78d1a92e347969fbf37f`):

| | count |
|---|---|
| routed instances | 2321 |
| `d_genlut` (combinational) | 1808 |
| `d_dff` (sequential) | 456 |
| declared load-only no-ops | 57 |
| shared polarity inverters (declared addition) | 1 |

1808 + 456 + 57 = 2321 exactly; the generator refuses to write if that sum
does not close. The 57 are the one `diode_2` antenna tie (no output pin in the
Liberty cell) and 56 CTS dummy-load cells whose output the router left open --
nothing can read them, so omitting the primitive is exact for an event-driven
model, and their own input capacitance still loads their drivers. They are
**declared**, named and reasoned about in
`corners/gate-model-full/gate-model.manifest.json`, not dropped.

Boundary, asserted against `program.boundary_signals()` before anything is
written: the analog/digital boundary is exactly **`clk`, `raw_bit`,
`raw_valid`, `rst_n`** (one `adc_bridge` card), the 39 testbench-driven inputs
are a separate `adc_bridge` card, the 68 observed outputs one `dac_bridge`
card, and `vdd`/`vss` exist as deck nets. This is the same contract
`make-requests.py:partition_check()` already asserts for the transistor-level
partition.

Committed form of the realised model:
`runs/20261114-gate-model-full/gate-model.cir.gz`
(sha256 `1f4120d9fd3e23e79969d78be79f6b59d93b0e81b6798003ab8899a3975fe5df`;
plain-text sha256 `abbe277084a8d97a4af35a054e151ebb1faa2d48d4a93bb6f39e9efcce447e51`).
The per-request `netlist.cir` and `gate-model.cir` under `corners/` are
gitignored and regenerated deterministically (both sha256 in each `plan.json`;
a regeneration on this host reproduced all five files byte-identically).

## Inputs and tool versions

| What | Value |
|---|---|
| Liberty deck | `/home/ubuntu/.ciel/ciel/sky130/versions/f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib` |
| Liberty sha256 | `8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135` |
| routed netlist sha256 | `9f3956848e6e75223f75bd154df905fecbb4e988593e78d1a92e347969fbf37f` |
| PDK | `open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, variant `sky130A`, resolved via `klt pdk find --pdk sky130A` (two installs present; `~/.ciel` won, `~/.volare` shadowed -- klt warned) |
| ngspice | `ngspice-47`, binary sha256 `39ca1adb826660324c3626f72bd946ec40704f0f3fc8e243c623f76e24b3eee2` |
| klt | `0.9.2.dev1022+g2a9c52b27ce7` |
| ngspice corner lib sha256 | `48de7c677e2c6e7d09b2559279de9f818be71010a4aa933d728eb4db3b133c84` (loaded by klt; **no device card uses it** -- the body is purely event-driven) |

The deck path is resolved through the repo's documented order and recorded as
an absolute path plus sha256; no `~/.ciel` literal is hardcoded in the
generator.

## The pass criterion, stated before the run

DR-0017's feasibility gate requires the criterion be fixed before the probe.
From the committed figures:

* unit ceiling **3480 s** over the full program's `t_stop` **7870 ns**
  (`program.build_program()` -> 75 cycles, `t_stop_ns` 7870.0)
  = **0.4422 s per simulated ns** for the whole block;
* the analog chain is measured at **0.057 s/sim-ns**
  (`records/20261105-analog-chain-probe.md`, job `klt-sim-52ede9c6e92b`,
  28.732 s for 500 ns);
* so the digital half's budget is **0.4422 - 0.057 = 0.3852 s/sim-ns**.

**This slice passes if the generated gate model's measured rate is at or under
0.3852 s/sim-ns.** A run that cannot report a rate is a fail, not
inconclusive. The criterion and the arithmetic are computed in
`analysis/compare-gate-model.py:digital_budget_s_per_ns()` from the same
constants, not retyped.

**Declared assumption**: the standalone gate-model rate is a **lower bound** on
the digital half's contribution to a coupled run, and **linear additivity of
the two halves is an extrapolation, not a measurement**. The coupled rate is
still unmeasured; see "What is still open".

## The runs (`klt sim`, local backend, one unit each, no retry)

Both are single-unit runs, so they were kept local (`--backend local` passed
explicitly). No `ngspice -b` grid was hand-launched; the two one-off
`ngspice -b` debug probes used while developing the cards ran in
`/home/ubuntu/scratch/`, outside the repository.

| | `20261114-gate-model-probe` | `20261114-gate-model-full` |
|---|---|---|
| program | 6 cycles (reset, release, 3 reads, `CTRL.EN` write, 2 samples) | the full committed program, 75 cycles |
| `t_stop` | 970 ns | 7870 ns |
| `.tran` max step | `20p` (the same `TMAX` `make-requests.py` uses) | `20p` |
| measurements | 217 | 749 |
| corner status | pass | pass |
| wall clock | **13.253 s** | **76.716 s** |
| **s per simulated ns** | **0.01366** | **0.00975** |
| margin vs 0.3852 | **28.2x** | **39.5x** |
| peak RSS | 213.5 MB | 426.1 MB |
| deck sha256 | `3f51c279107a3f0ae3425e086c7a40cd95b9c2e847f550897a0b4de76e466500` | `5b8bd84fb9d2823a96011c81c2a8b862d22c0cabc43c696dc0d49b2feee9fd44` |

The **full-program** figure is the one to cite: it is measured over exactly the
`t_stop` the 12-point grid requests use, so the digital half's rate needs **no
extrapolation in simulated time** at all. (The short probe is the run AC3 of
#486 asks for; the full run was cheap at this rate and is strictly better
evidence, so both are recorded.)

## Oracle comparison: 311 of 311 responses match the normative model

`analysis/compare-gate-model.py` replays the same program through
`digital/model/digital_top.py` via `program.model_replay()` -- the *same*
normative function the transistor-level reduction uses, not a second
implementation -- and compares every measured digital response. Per-check
output in `runs/20261114-gate-model-full/compare.json`.

A measured level is decoded to a logical bit only within 50 mV of `vss` or of
the supply. Anything between -- in particular `dac_bridge`'s `out_undef`
(supply/2), which is what an UNKNOWN digital net reads as -- is reported
`undecodable` and **fails** the comparison; it is never rounded to the nearer
rail. There were none in either recorded run.

Non-trivial matches, in both runs where applicable:

* `ID` read -> `0x54524e47` (the block's ID constant), model and sim;
* `HT_STARTUP` -> `0x00000400`, `STATUS` -> `0x00000002`;
* `RAW_DATA` pop after 32 samples -> **`0x5c6a78e9`**, which is the LSB-first
  packing of the committed raw-bit stimulus' first 32 bits. The gate netlist's
  packer, the normative model's packer and a hand computation of
  `sum(b_k << k)` all agree;
* the streaming port: `out_valid` rises and `out_data` -> `0x5c6a78e9` on
  cycles 36 and 37;
* the gated `DATA` read returns 0 and `gated` stays 1 for the whole program --
  the start-up window blocks the conditioned path, exactly the behaviour
  `README.md` -> Assumptions declares and the program is written to show;
* `alarm` 0 and `startup_done` 0 throughout.

`out_data` is compared **only** on cycles where the normative model reports
`out_valid = 1`; on the other three captured cycles the model's FIFO head is
not an output the hardware claims, so asserting it would be comparing
don't-cares. Those three are reported as `not compared`, with the reason, and
are excluded from the 311.

Independent cross-check available but **not run here**: the existing
`sim/digital-sdf-timed-verification/` Icarus + SDF run at the same
`tt_025C_1v80` corner exercises the same routed netlist against the same
independent model (#227). It is a different simulator and a different timing
mechanism, so it is the right third opinion; wiring the two reductions
together is not in this slice's scope and is listed as open below.

## Disclosed deviations (each one stated, none silently taken)

1. **NLDM table -> scalar delay.** Liberty `cell_rise`/`cell_fall` are 2-D
   tables over (`input_net_transition`, `total_output_net_capacitance`);
   `d_genlut`/`d_dff` take scalars. Each output pin's pair is a **bilinear
   interpolation** of its tables at the operating point (slew, C_load),
   **clamped** to the table's own index range (never extrapolated), then the
   **maximum over every delay arc** reaching that pin -- the conservative STA
   convention, so a functional match cannot be an artefact of an optimistic
   delay. **Index `[0][0]` is not taken.** Source: the deck above.
2. **C_load is derived, not declared**: for each driven net, the sum of the
   Liberty input-pin `capacitance` of every receiver on that net (the antenna
   tie's and the CTS dummy loads' included), plus `--port-load-pf` (default
   **0.0**) on a net that reaches a module output port -- the whole-block
   deck's standing "outputs are unloaded" assumption.
3. **Slew operating point**: 0.1 ns, the rise/fall time every testbench source
   in this deck family already uses (`make-requests.py`'s
   `PULSE(... 100p 100p ...)`). A fixed single-pass operating point, **not** an
   STA slew propagation.
4. **Bridge levels move with the corner supply**: `adc_bridge` band
   `(0.50 -+ 0.05) * Vdd` = 0.81 .. 0.99 V at 1.8 V, centred on the chosen
   deck's own `input_threshold_pct_rise`/`_fall`, which is **read from the deck
   and asserted to be 50** rather than assumed; the +-5 % half-width is the
   generator's declared choice (a narrow band, so the bridged event time
   coincides with the point at which that deck measures its delays).
   `dac_bridge` drives `vss` .. Vdd with `out_undef` = Vdd/2. This honours
   DR-0017's requirement that thresholds move with `vdd` rather than sitting
   in a fixed 1.8 V domain. The **drive** level is still the repo's disclosed
   `VIH = 1.8` convention (`make-requests.py:75`); at this corner VIH == Vdd,
   so the two coincide and the question of their divergence at 1.62 V / 1.98 V
   is left to the rest of #431.
5. **One scalar rise/fall pair per flop output**: `d_dff`'s per-input
   `clk_delay`/`set_delay`/`reset_delay` sit at XSPICE's own **1 ps floor**
   (it refuses 0 -- "Value 0 below limit 1e-12"), three orders of magnitude
   below the fastest cell delay here, so the asynchronous clear/preset arc is
   not modelled separately from the CLK->Q arc; the single pair is the max over
   both. `ic=0`: the real cells power up undefined and the deck's reset
   (`rst_n` low until 300 ns) establishes the state every comparison relies on
   -- and the `dfstp` cells' preset is exercised by that same reset, so the
   match is not an artefact of the initial condition.
6. **Active-low clear/preset get an explicit inverter.** XSPICE `d_dff`'s
   `set`/`reset` were **measured active-high** on this install, while
   `dfrtp`/`dfstp` carry `clear : "!RESET_B"` / `preset : "!SET_B"` in their
   Liberty `ff` groups. One zero-delay `d_inverter` per *distinct* driving net
   is emitted and shared; in this netlist every flop's asynchronous pin is
   `rst_n`, so there is exactly **1**. Counted separately in the manifest.
7. **`input_load` is the Liberty input-pin capacitance, and is NOT DR-0017's
   boundary-load choice.** The cards need some `input_load` to elaborate at
   all; using the real per-pin capacitance is strictly better than inventing a
   default. **Choosing between DR-0017 option 1 (keep the first receiving
   cells at transistor level) and option 2 (model the load as Liberty
   input-pin capacitance at the matching corner) is the rest of #431 and is
   not settled here.**
8. **`netlist_source` is forced.** `klt sim`'s request schema accepts only
   `schematic` or `extracted`; a gate-level netlist generated from a routed
   structural netlist plus a Liberty deck is neither. `extracted` is used as
   the nearer label (this *is* derived from the layout, via
   `trng_digital.routed.v`) and the forced value is recorded in each
   `plan.json` under `netlist_source_forced`. Filed upstream as
   klayout-tools#5638.

## Findings worth carrying forward

* **`corners.supply_v` alone does not re-corner the digital half.** At gate
  level the supply enters only through the bridge levels and through *which
  Liberty deck* is used. A grid request that moves `supply_v` without moving
  the Liberty deck would silently simulate the digital half at the wrong
  corner. The rest of #431 must pair each (T, Vdd) point with its deck.
* **sky130A cannot serve the 125 C / 1.98 V point exactly.** The install ships
  16 non-ccsnoise `sky130_fd_sc_hd` decks: `tt_025C_1v80`, `tt_100C_1v80`,
  6 `ss_*` and 6 `ff_*` plus `ss_100C_1v40`/`ss_100C_1v60` -- **none above
  100 C**, and no `tt` deck off 1.80 V. A deviation the rest of #431 inherits;
  not resolved here.
* **A PWL stimulus with only change-instants ramps instead of switching.** The
  first version of this deck emitted `Vbus_re bus_re 0 PWL(0n 1.8 640n 0)`,
  which a PWL source interpolates **linearly**: at 310 ns it sits at 0.928 V,
  inside the `adc_bridge` dead band, and the entire digital state goes UNKNOWN
  (every observable read back as `out_undef` = 0.9 V). The generator now emits
  a hold point one 100 ps edge before each change. **The identical shape is
  produced by `make-requests.py:input_cards`' `points()` for the
  transistor-level decks**, where CMOS inputs still resolve but every bus
  input ramps over hundreds of ns instead of switching at its skew point.
  That is a pre-existing defect in a deck this slice does not own, so it is
  filed as **#488** rather than changed here. It is not a retraction of any
  committed result: no transistor-level grid run has ever produced
  measurements, so nothing recorded depends on that stimulus shape.
* **Two measured XSPICE facts this netlist depends on**, both pinned by
  `sim/tests/test_gate_model.py` so a refactor cannot drift off them:
  `d_genlut`'s `table_values` index is `sum(bit_k << k)` with the **first**
  connected input as the least significant bit (measured with four one-hot
  tables against all four input combinations of a 2-input LUT), and `d_dff`'s
  connection order is `data clk set reset out nout` with `null` allowed in any
  unused slot, inputs scalar (not bracketed vectors).

## Verdict against DR-0017

The gate-level realisation of option (b)'s digital half **exists, is
reproducible, and is feasible**: 0.00975 s per simulated ns over the full
program, 39.5x inside the 0.3852 s/sim-ns budget, with all 311 compared digital
responses matching the normative model. This is **not** a negative result for
option (b); it removes the digital half as the suspected cost driver.

It is also not the end of step 2. The **coupled** run -- the analog partition
at transistor level and this gate model behind the boundary, in one deck, with
the boundary load modelled -- is unmeasured, and so is any fleet run. Until
that exists, no whole-block rate is claimed and `GRID_TIMEOUT_S` /
`poll_timeout_s` stay as they are.

## What is still open (nothing below is claimed by this record)

* The **coupled** whole-block deck: the analog partition and this gate model
  in one netlist, with DR-0017's boundary-load option 1 or 2 chosen and its
  source stated. Includes the `raw_bit`/`raw_valid` hand-off, which is driven
  by testbench PWL here.
* A **measured fleet run** with simulated time reached, and only then the
  question of re-setting `GRID_TIMEOUT_S` / `poll_timeout_s`.
* The per-(T, Vdd) Liberty deck selection, with the two findings above
  (supply axis, no deck above 100 C) as its inputs.
* Cross-checking a response against `sim/digital-sdf-timed-verification/`'s
  Icarus + SDF run at the same corner, as an independent third opinion.
* O5d / O7 / O8 remain forced UNMET and #18 AC3 remains UNMET.

## Friction filed

* **klayout-tools#5638** -- `klt sim` has no `netlist_source` value for a
  gate-level netlist generated from a structural netlist plus a timing
  library, so the request is forced to claim `extracted`. Filed 2026-11-14;
  row added to `docs/friction-ledger.md`.

## Reproduce

```bash
python3 sim/tests/test_gate_model.py                      # no klt, no PDK, no ngspice
python3 sim/post-layout-whole-block/make-gate-model.py /tmp/gm --cycles 0
klt sim /tmp/gm/request.json --backend local -o /tmp/gm-out --report-out /tmp/gm/report.json
python3 sim/post-layout-whole-block/analysis/compare-gate-model.py \
    /tmp/gm/report.json /tmp/gm/plan.json
```

`klt sim` needs **absolute** `-o`/request paths (klayout-tools#2892/#2939).
