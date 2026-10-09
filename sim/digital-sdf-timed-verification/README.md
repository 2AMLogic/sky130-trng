# digital-sdf-timed-verification

SDF-annotated, routed-netlist verification of the digital section
(`trng_digital`) through the native `klt functional-verification` interface
(klayout-tools 0.7.0, cocotb 2.0.1, Icarus 13.0), issue #227. Records are
append-only (`records/`, raw artifacts in `runs/<id>/`). The functional /
unit-delay baseline (`sim/digital-functional-verification`, #222) is untouched.

* DUT: `layout/trng_digital/trng_digital.routed.v` with the sky130_fd_sc_hd
  **timing** (`specify`) cell models -- no `FUNCTIONAL`, no `UNIT_DELAY` -- and
  `layout/trng_digital/trng_digital.sdf.gz` back-annotated via `options.sdf`.
* Oracle/stimulus: the same directed program and independent model as #222;
  testbench `digital/tb/cocotb/test_trng_digital_fv.py` (clock period via
  `TRNG_FV_CLK_NS`, default 10 ns = #222 behaviour; optional output-latency probe
  via `TRNG_FV_TIMING_OUT`).
* Harness: `harness/fv-sdf-cosim.py` runs the declared-timing baseline
  (20000 ns, the P&R clock), an 8 ns stress baseline and the controls
  (SDF removed, SDF mistargeted, exact +137 ps arc shift, +15000 ns arc shift,
  5 ns clock vs the same run unannotated); it refuses to mint unless every
  baseline is a clean annotated pass and every control is detected.
* Scope: ONE SDF corner (`tt_025C_1v80`), not a PVT sweep; Icarus 13.0 does not
  implement SDF `TIMINGCHECK` (setup/hold not simulated, `sdf.partial: true`);
  39 zero-delay bit-selected-input `INTERCONNECT` entries are removed before
  annotation (Icarus cannot resolve them as intermodpath sources; disclosed and
  hashed in each record). Timing results are simulation-derived and provisional;
  DR-0004 is still `Proposed`.

Cold start (touches nothing host-wide; needs `iverilog` on PATH):

```
uv venv .venv
uv pip install --python .venv/bin/python "klayout-tools==0.7.0" "cocotb==2.0.1"
python3 sim/digital-sdf-timed-verification/harness/fv-sdf-cosim.py --klt "$PWD/.venv/bin/klt"            # dry run
python3 sim/digital-sdf-timed-verification/harness/fv-sdf-cosim.py --klt "$PWD/.venv/bin/klt" --emit-record
```

(Pass an absolute `--klt`; the harness runs each request from its own directory.)
