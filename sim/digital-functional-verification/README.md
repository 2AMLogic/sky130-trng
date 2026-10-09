# digital-functional-verification

Native `klt functional-verification` (klayout-tools 0.7.0, cocotb 2.0.1,
Icarus 13.0) evidence for the digital section (`trng_digital`), issue #222.
Records are append-only (`records/`, raw artifacts in `runs/<id>/`).

* Testbench: `digital/tb/cocotb/test_trng_digital_fv.py` -- the directed
  program and independent model of `sim/digital-rtl-equivalence`, one cocotb
  test per directed phase plus an exact-trace-length test.
* Harness: `harness/fv-cosim.py` -- runs RTL and routed-netlist baselines,
  four negative controls (xor2->and2 routed netlist, truncated, dropped and
  missing observations) and `--mutations` single-point mutants; refuses to
  mint on any pin mismatch, unclean baseline or undetected control.
* SDF-timed counterpart: `sim/digital-sdf-timed-verification` (#227).
* Scope: functional / unit-delay only (`FUNCTIONAL` + `UNIT_DELAY #1`, no
  `options.sdf`). It is NOT SDF-timed T1 item 7 evidence. T1 item 5 is not
  claimed: the digital section (DR-0004) is still `Proposed`.

Cold start (touches nothing host-wide; needs `iverilog` on PATH):

```
uv venv .venv
uv pip install --python .venv/bin/python "klayout-tools==0.7.0" "cocotb==2.0.1"
python3 sim/digital-functional-verification/harness/fv-cosim.py --klt .venv/bin/klt            # dry run
python3 sim/digital-functional-verification/harness/fv-cosim.py --klt .venv/bin/klt --emit-record
```

Rerun one native request by hand: `TRNG_FV_SEED=20260905 .venv/bin/klt
functional-verification runs/<id>/<label>.request.json --format json` (the
preserved request paths are repo-relative / `$PDK_LIBS_REF`-relative and must be
made absolute for your checkout and PDK first).

Known tool friction: `options.defines` cannot express the macro-text value
`UNIT_DELAY=#1` (nor a null value), so the defines live in
`digital/tb/cocotb/sky130_fd_sc_hd_sim_defines.v`, listed first in `sources`
(tracked upstream at 2AMLogic/klayout-tools#2884).
