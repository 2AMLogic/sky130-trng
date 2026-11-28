# 20261128 -- Cross-check of the ngspice timed-delay gate model against Icarus + SDF at `tt_025C_1v80` (issue #812, residual of #486)

**Claim**: Driving the routed gate-level netlist
(`layout/trng_digital/trng_digital.routed.v`) through two independent
simulators and two independent timing mechanisms at the same `tt_025C_1v80`
corner and the same 100 ns clock period (`program.TS_NS`) on the full
committed 75-cycle directed program (`program.build_program(75)`, including
the committed 64-bit `raw_bit` / `raw_valid` sequence) yields **311 of 311**
gate-model vs Icarus + SDF responses matching word for word, **0
disagreements**, and **first `out_valid` assertion at cycle 36** across all
three of:

1. the timed-delay XSPICE gate model under `ngspice-47`
   (`runs/20261114-gate-model-full/report.json`, #486);
2. the SDF-annotated routed Verilog netlist under Icarus Verilog 13.0
   (`analysis/cross-check-icarus-sdf.py`, reusing `fv-sdf-cosim.py`'s SDF
   preparation);
3. the independent normative behavioural model (`program.model_replay()`).

**Level of this result, worded exactly**: **gate-level digital section only**
at one corner (`tt_025C_1v80`), driven by testbench sources at its boundary --
**not** the mixed-level whole block and **not** a PVT sweep. Nothing here
claims any #18 AC3 row (`ac3_claimable` stays `false`), and no DR-0017
obligation changes. Provisional, simulation-derived, not foundry sign-off,
**not silicon**.

## Why the two existing runs could not be compared directly

Prior to this harness, the two post-route digital runs used different programs
and different clocks:

| Run | Stimulus | Clock period |
|---|---|---|
| Gate model (`make-gate-model.py`, #486) | `sim/post-layout-whole-block/program.py::build_program()` (75 cycles, `T0 = 320 ns`, `TS = 100 ns`) | 100 ns |
| Icarus + SDF (`sim/digital-sdf-timed-verification/`, #227) | `sim/digital-rtl-equivalence/harness/rtl-cosim.py::build_program(20260905)` | 20000 ns baseline (`TRNG_FV_CLK_NS` override) |

To make a cycle-by-cycle cross-check meaningful without disturbing #227's
testbench (`digital/tb/cocotb/test_trng_digital_fv.py`) or records,
`analysis/cross-check-icarus-sdf.py` and its companion cocotb testbench
`analysis/tb_whole_block_program.py` replay `program.build_program(N)`
(`N = 75`) and `make-gate-model.py::RAW_BIT_PATTERN` into the SDF-annotated
routed netlist at 100 ns, reusing `fv-sdf-cosim.py`'s exact SDF preparation
(`read_sdf_gz`, `drop_zero_port_source_interconnects`, `sdf_census`, and
`run_fv`) rather than forking a second SDF path.

## Inputs, corners, and tool versions

| Item | Value |
|---|---|
| Program / cycles | `sim/post-layout-whole-block/program.py::build_program(75)`, `N = 75`, `TS = 100 ns` |
| `raw_bit_pattern` (64 bits) | `1001011100011110010101100011101011010010111001000110111101000011` |
| Shared 40 input cards SHA-256 (`program.input_cards`, pinned by `test_standalone_waveform_bytes`) | `6fe44c0b0bab82a0b81f6eb83a052c3042d4b16d2145e7f81d2da07bf2a9333d` |
| Gate-model stimulus cards SHA-256 (`make-gate-model.py::stimulus_cards`, pinned by `test_standalone_waveform_bytes`) | `d16a420004f83722abf1e03af3e11e7509e8bf1a3a47add9c86eed2a36a0b0c9` |
| Per-cycle stimulus trace SHA-256 (program vs Icarus `stimulus.txt`) | `f5fdbeafb96ad62221bcb1adb4adb0075bec17224c4f76a190288ab4080b0a6b` (exact match: `true`) |
| Routed netlist (`layout/trng_digital/trng_digital.routed.v`) | `9f3956848e6e75223f75bd154df905fecbb4e988593e78d1a92e347969fbf37f` (identical in both runs) |
| Gate-model simulator | `ngspice-47` (binary sha256 `39ca1adb826660324c3626f72bd946ec40704f0f3fc8e243c623f76e24b3eee2`), from committed `runs/20261114-gate-model-full/report.json` + `corners/gate-model-full/plan.json` |
| Gate-model Liberty corner | `tt_025C_1v80` (`sky130_fd_sc_hd__tt_025C_1v80.lib`, sha256 `8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135`) |
| Gate-model deck / body SHA-256 | deck `5b8bd84fb9d2823a96011c81c2a8b862d22c0cabc43c696dc0d49b2feee9fd44`, body `abbe277084a8d97a4af35a054e151ebb1faa2d48d4a93bb6f39e9efcce447e51` |
| Icarus + SDF simulator | `Icarus Verilog version 13.0 (stable) (v13_0)` (engine `13.0`), `cocotb 2.0.1`, `klt 0.8.0` (worktree-local `.venv`) |
| SDF corner / selector | `tt_025C_1v80`, selector `typ` (`layout/trng_digital/trng_digital.sdf.gz` sha256 `46850cda3d0948738e17a6e70fdb4f71e6c9829e9f925547a934f15d9fc5dd78`; decompressed `cae0b59b15787cd9fecce34fd6746f77af1816215fc3a17725f763b2a578db15`; post-scrub `432f6abdb6d024bbd2c6a75e3c54f9eade03a9ad937274b0e6331919bdc4bd1b`) |
| PDK timing cell models (`specify`, non-`FUNCTIONAL`) | `open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (`sky130A`): `primitives.v` sha256 `7d4b1441d06b0f2b9662befa675a0484d77149e04eb42a5f1fa2d4cfded7b2ce`, `sky130_fd_sc_hd.v` sha256 `4a183a476baef9abb68d82808d24d8f2907ed7b6cdebff8d03002f45b12e7833` |
| Icarus observations SHA-256 (`observations.txt`) | `5f17f4bde555699da3886ac500b0585c4f32334080e3f9e32d85dd033a733309` |
| Cocotb testbench SHA-256 (`analysis/tb_whole_block_program.py`) | `2589bd3fb362956c401d30780029996c19558876ede41ea9162203e127d9027b` |

## SDF annotation reach and limitations

* **Pre-annotation scrub (reused verbatim from `fv-sdf-cosim.py`)**: 39
  zero-delay `INTERCONNECT <bus_addr|bus_wdata>[i] <inst>.<pin> (0.000:0.000:0.000)`
  entries removed because Icarus 13.0 cannot resolve bit-selected top-level
  input ports as intermodpath sources. Every dropped entry carries zero delay.
* **Tool-reported SDF status (`environment.sdf`)**: `annotated: true`,
  `corner: "typ"`, `entries: "all"`, **`partial: true`**.
  - Dropped by klt/Icarus: **455 `TIMINGCHECK` sections** and **33 zero-delay
    assign-alias output-port `INTERCONNECT` entries**.
  - Independent SDF census: 2320 of 2321 netlist cell instances present in the
    SDF (only `ANTENNA_1`, the antenna diode tie, is absent), 0 cell-type
    mismatches, 6030 `IOPATH` entries, 6163 `INTERCONNECT` entries (all zero).
* **Output-latency probe (proving SDF delays were active, not zero-delay)**:
  - `bus_rdata` `clk->out`: 45 transitions, **873 ps .. 931 ps**;
  - `out_data` `clk->out`: 25 transitions, **1114 ps .. 1816 ps**.
  (As documented in `fv-sdf-cosim.py`, cocotb value-change callbacks with SDF
  module paths active cover registered outputs only; combinational outputs
  `out_valid`, `alarm`, `gated` are checked by the cycle-by-cycle comparison
  below, and `startup_done` stays 0 throughout this 75-cycle program.)
* **Setup/hold behaviour NOT checked**: Icarus 13.0 does not implement SDF
  `TIMINGCHECK` (`sdf.partial: true`), so setup, hold, recovery, and removal
  checks are **not** simulated. This cross-check establishes agreement on
  **output values and cycle timing only** (not setup/hold sign-off; the
  16-corner STA in `layout/trng_digital/sta.json` remains the timing check).

## Word-for-word comparison (`N = 75` cycles)

### First `out_valid` assertion cycle

| Source | First cycle with `out_valid = 1` | Status |
|---|---|---|
| ngspice gate model (`20261114-gate-model-full`) | **36** | |
| Icarus 13.0 + SDF (`tt_025C_1v80`, 100 ns) | **36** | |
| Normative model (`program.model_replay()`) | **36** | **MATCH** |

### 32-bit word responses (all gate-model word captures)

| Observed cycle | Signal | Gate measurement | Read cycle | Gate model (ngspice) | Icarus + SDF | Normative model | Result |
|---:|---|---|---:|---|---|---|---|
| 1 | `bus_rdata` | `rdata_k0_b*` | 0 (`ID`) | `0x54524e47` | `0x54524e47` | `0x54524e47` | OK |
| 2 | `bus_rdata` | `rdata_k1_b*` | 1 (`HT_STARTUP`) | `0x00000400` | `0x00000400` | `0x00000400` | OK |
| 3 | `bus_rdata` | `rdata_k2_b*` | 2 (`STATUS`) | `0x00000002` | `0x00000002` | `0x00000002` | OK |
| 36 | `out_data` | `odata_k36_b*` | -- | `0x5c6a78e9` | `0x5c6a78e9` | `0x5c6a78e9` | OK |
| 37 | `bus_rdata` | `rdata_k36_b*` | 36 (`STATUS`) | `0x0000010a` | `0x0000010a` | `0x0000010a` | OK |
| 37 | `out_data` | `odata_k37_b*` | -- | `0x5c6a78e9` | `0x5c6a78e9` | `0x5c6a78e9` | OK |
| 38 | `bus_rdata` | `rdata_k37_b*` | 37 (`RAW_DATA`) | `0x5c6a78e9` | `0x5c6a78e9` | `0x5c6a78e9` | OK |
| 39 | `bus_rdata` | `rdata_k38_b*` | 38 (`ID`) | `0x54524e47` | `0x54524e47` | `0x54524e47` | OK |
| 40 | `bus_rdata` | `rdata_k39_b*` | 39 (`DATA`, gated) | `0x00000000` | `0x00000000` | `0x00000000` | OK |
| 41 | `bus_rdata` | `rdata_k40_b*` | 40 (`ALARM`) | `0x00000000` | `0x00000000` | `0x00000000` | OK |
| 42 | `bus_rdata` | `rdata_k41_b*` | 41 (`STATUS`) | `0x00000002` | `0x00000002` | `0x00000002` | OK |
| 72 | `out_data` | `odata_k72_b*` | -- | -- | -- | -- | not compared (`out_valid = 0` in all three) |
| 73 | `out_data` | `odata_k73_b*` | -- | -- | -- | -- | not compared (`out_valid = 0` in all three) |
| 74 | `out_data` | `odata_k74_b*` | -- | -- | -- | -- | not compared (`out_valid = 0` in all three) |

### Summary counts and scalar observables

| Check set | Matched / Total | Notes |
|---|---:|---|
| 32-bit words (gate vs Icarus vs model) | **11 / 11** | 9 `bus_rdata` reads + 2 active `out_data` words (3 `out_valid = 0` captures not compared) |
| Scalar observables (`out_valid`, `alarm`, `gated`, `startup_done`, cycles 0..74) | **300 / 300** | `out_valid = 1` on cycles 36..37 only; `gated = 1`, `alarm = 0`, `startup_done = 0` throughout |
| **Total gate model vs Icarus + SDF** | **311 / 311** | 0 undecodable voltages in gate model; 0 unresolvable X/Z literals in Icarus |
| Full-trace Icarus + SDF vs `program.model_replay()` (all 75 `bus_rdata` cycles + 2 active `out_data` cycles) | **77 / 77** | Every cycle's `bus_rdata` matches the normative model even outside the gate model's read `.meas` windows |
| **Disagreements** | **0** | Verdict: **PASS** |

## Disagreements and cycle-0 timing note

There are **zero disagreements** on any compared word, scalar, or `first_out_valid`
cycle.

One structural difference in reset-exit stimulus framing is noted for
completeness: in `make-gate-model.py`, `PWL` sources hold cycle 0's input
vector (`read(ID)`) from `t = 0` through `t_edge(1) + SKEW_NS`, so `read(ID)`
is sampled at both `t_edge(0)` and `t_edge(1)` (idempotent; `rdata_k0` is
measured at `t_edge(1) + 50 ns` = cycle 1). In `tb_whole_block_program.py`,
matching `program.model_replay()` and `test_trng_digital_fv.py`, reset releases
at the falling edge before cycle 0, cycle 0 observes the post-reset state
(`bus_rdata = 0x00000000`), and cycle 0's `read(ID)` latches on cycle 0's
closing rising edge so cycle 1 observes `0x54524e47`. Both simulators produce
identical responses on every measured cycle.

## Reproduce

Requires `iverilog` 13.0 on `PATH` and the pinned `sky130A` PDK (`klt pdk find`);
touches nothing host-wide (uses a worktree-local venv):

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python "klayout-tools==0.8.0" "cocotb==2.0.1"
python3 sim/post-layout-whole-block/analysis/cross-check-icarus-sdf.py \
    --klt "$PWD/.venv/bin/klt" --cycles 75
python3 sim/post-layout-whole-block/test_cross_check_icarus_sdf.py
```

(Pass `--run-gate-model` to run a fresh local single-corner `klt sim --backend
local` ngspice gate-model simulation instead of reading the committed
`runs/20261114-gate-model-full/report.json`.)
