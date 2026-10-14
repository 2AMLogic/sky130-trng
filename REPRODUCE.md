# REPRODUCE -- cold-start index

One page that maps every result family in this repo to the command that
re-creates it, the tools it needs, and the PDK revision it is pinned to. It
is an **index**: the per-directory READMEs own the detail and the caveats, and
this file points into them rather than duplicating them. Read the README of a
family before trusting a re-run.

Everything here is **simulation- or layout-derived evidence**. Simulated
entropy claims are provisional until measured on silicon. Nothing in this file
is a sign-off claim; this index does not grade any `signoff/block-manifest.json`
row.

`tools/check_reproduce.py` (run in the PR-blocking `lint` CI job) fails if a
repo path named in this file does not exist, if a `sim/` directory holding
minted records is not named here, or if the PDK pins in `design/pdk.json`,
`sim/pdk.json` and `layout/pdk.json` disagree.

## Pins

| What | Pin | Source of truth |
|---|---|---|
| PDK | sky130A, open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b` | `design/pdk.json`, `sim/pdk.json`, `layout/pdk.json` |
| PDK install | `volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b` | same files, `install_command` |
| xschem | >= 3.4.7 (hard gate) | `design/pdk.json` `xschem_version_min` |
| klt (klayout-tools) | `0.6.0+g5edb557f91d0` | `layout/pdk.json` `klt_version_pin`, `ci_klt_install` |
| KLayout / python klayout | 0.30.12 | `layout/trng_whole/README.md` ("Reproducing") |
| ngspice | machine-level install; each record stamps the version it ran on | `sim/README.md` ("Quick start") |
| Python | 3.9+, standard library only for every script here | `sim/README.md` |

Do not upgrade the shared tool install to reproduce; use a throwaway venv, e.g.
`uvx --from "klayout-tools==X.Y.Z" klt ...`, or the venv recipe in `layout/README.md`
("Regeneration on the cut-size/grid fix (issue #181)"). Check `klt --version`
against the pin before debugging a layout failure.

Cold start, once per machine:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 design/netlist.py --pdk          # xschem + PDK resolved against the pins
python3 sim/bin/corner-run.py --print-env
```

## 1. Design netlists (`design/`)

Detail: `design/README.md` ("Regenerating the netlists").

```bash
python3 design/netlist.py --check       # committed netlists not stale + xschem ERC
python3 design/netlist.py --lint        # no xschem, no PDK
python3 design/test_netlist_erc.py
python3 design/test_pdk_search.py
python3 design/test_netlist_xschem_version.py
```

Needs xschem >= 3.4.7 and the pinned PDK (except `--lint` and the unit tests).

## 2. Layout DRC / LVS / extraction (`layout/`)

Detail: `layout/README.md` (the "Reproducing ..." sections), `layout/trng_whole/README.md`,
`layout/trng_whole/verify/README.md`. Needs klt at the pin above and the pinned PDK;
no SPICE.

```bash
# every composed cell: isolated rebuild, diff the verdict-bearing fields
python3 layout/bin/compose-cell.py layout/ro_buf/cell.json --check      # likewise layout/<cell>/cell.json
# whole block
python3 layout/bin/compose-whole.py layout/trng_whole/floorplan.json --check
python3 layout/bin/verify-whole.py check        # DRC + extract + LVS re-run, ~8 min
python3 layout/bin/verify-whole.py controls     # fault controls, ~45 min
# primitives: klt gen / klt drc / klt extract, see layout/primitives/README.md
# unit tests, nothing installed
python3 layout/test_compose_cell.py
python3 layout/test_compose_whole.py
python3 layout/test_verify_whole.py
```

Post-layout netlist libraries consumed by `sim/` (re-extracted from committed GDS):

```bash
python3 layout/bin/pex-netlist.py layout/pex/pex.json --check
python3 layout/bin/pex-netlist.py layout/pex-array/pex.json --check
python3 layout/test_pex_netlist.py
```

## 3. Simulation harness (`sim/`)

Detail: `sim/README.md` ("Quick start", "Writing a new record", "PVT grid").
Records under `sim/<slug>/records/` are append-only
(`sim/records-append-only-allowlist.txt`, checked by
`sim/bin/check_records_append_only.py`); a reproduction mints a **new** record, it
never edits an old one. Multi-corner and Monte Carlo grids go through `klt sim`
and the batch fleet (`KLT_SIM_BACKEND=batch`), not hand-launched ngspice loops.

```bash
python3 sim/bin/corner-run.py sim/ro-stage-noise-mechanism-check/testbench/tb_ro_stage_noise.spice \
  --slug ro-stage-noise-mechanism-check --claim "<claim>" --corners tt,ss,ff
python3 sim/bin/check_records_append_only.py
```

Unit tests for the reducers (stdlib only, no simulator): `sim/tests/`, e.g.
`python3 sim/tests/test_raw_bit_entropy.py`.

### 3a. Pre-layout PVT campaigns

Testbench in `<dir>/testbench/`, committed corner runs in `<dir>/corners/`,
records in `<dir>/records/`. Re-run with `sim/bin/corner-run.py <testbench> --slug <dir name>`
as above, using the testbench named in the record's `claim`.

| Directory | Testbench / generator |
|---|---|
| `sim/ro-stage-noise-mechanism-check/` | `testbench/tb_ro_stage_noise.spice` |
| `sim/ro-stage-small-signal-gain/` | `testbench/tb_ro_stage_gain.spice` |
| `sim/ro-ring-timestep-convergence/` | corners only; decks of `sim/ro-ring-jitter-accumulation/` |
| `sim/ro-ring-jitter-accumulation/` | `testbench/tb_ro_ring5_jitter.spice`, `testbench/tb_ro_ring11_jitter.spice` |
| `sim/ro-ring5-swing-and-current/` | `testbench/tb_ro_ring5_swing_current.spice` |
| `sim/xor-combining-bandwidth/` | `testbench/tb_xor2_pulse_width.spice` |
| `sim/ro-array-core-combining/` | `testbench/tb_ro_array_core.spice` |
| `sim/ro-array-sizing/` | `analysis/array-sizing.py` (analytic) |
| `sim/ro-array-operating-point/` | `analysis/operating-point.py` (analytic) |
| `sim/ro-array-supply-perturbation/` | `make-requests.py`, `ripple.py`; see its `README.md` |
| `sim/xor-combining-alternatives/` | `make-requests.py`, `reduce.py`; see its `README.md` |
| `sim/wake-up-transient/` | `make-requests.py`, `wakeup.py`, `restart_matrix.py`; see its `README.md` |
| `sim/local-mismatch-monte-carlo/` | `make-requests.py`, `reduce.py`; see its `README.md` |
| `sim/ro-vth-drift-sensitivity/` | `make-requests.py`, `campaign.py`, `analysis/sensitivity.py`; see its `README.md` |

### 3b. Post-layout PVT campaigns

Same runner, against the extracted netlists from section 2 (`layout/pex/`,
`layout/pex-array/`). Narrative and the `PEX_LIB` provenance notes:
`sim/README.md` ("The post-layout campaign (issue #22)" and following sections).

| Directory | Testbench / script |
|---|---|
| `sim/post-layout-ro-ring5/` | `testbench/tb_post_layout_ro_ring5.spice` |
| `sim/post-layout-ro-ring5-assembled/` | `testbench/tb_post_layout_ro_ring5_assembled.spice` |
| `sim/post-layout-ro-ring5-assembled-181/` | `make-requests.py`, `derive.py`; see its `README.md` |
| `sim/post-layout-ro-array-core/` | `testbench/tb_post_layout_ro_array_core.spice` |
| `sim/post-layout-sampler-dff/` | `testbench/tb_post_layout_sampler_dff.spice`, `testbench/tb_post_layout_sampler_setup.spice` |
| `sim/post-layout-sampler-dff-assembled/` | `testbench/tb_post_layout_sampler_dff_assembled.spice` |
| `sim/post-layout-sampler-core/` | `testbench/tb_post_layout_sampler_core.spice`, `analysis/substrate-bracket.py` |
| `sim/post-layout-parasitic-impact/` | `analysis/parasitic-impact.py` (reduction over the records above) |

### 3c. Raw-bit and entropy campaigns

Detail: `sim/README.md` ("The characterization campaign (issue #10)"),
`sim/raw-bit-volume-campaign/README.md`. Estimator and battery unit tests run with
nothing installed.

```bash
python3 sim/tests/test_raw_bit_entropy.py
python3 sim/tests/test_raw_bit_battery.py
python3 sim/tests/test_raw_bit_volume_model.py
python3 sim/tests/test_raw_bit_pvt_crosscheck.py
python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --regenerate-check sim/raw-bit-volume-campaign/records/<id>.json
python3 sim/raw-bit-volume-campaign/transistor_pvt_crosscheck.py --check sim/raw-bit-volume-campaign/records/<id>.json
```

| Directory | Entry points |
|---|---|
| `sim/raw-bit-min-entropy/` | `testbench/tb_raw_bit_stream.spice`, `analysis/raw-bit-entropy.py`, `analysis/raw-bit-battery.py` |
| `sim/raw-bit-volume-campaign/` | `make-requests.py` (`klt sim` requests, fleet), `derive-combining.py`, `behavioral_raw_bit.py`, `transistor_pvt_crosscheck.py` |

Request generation emits `klt sim` documents; submit them per the README rather
than looping ngspice locally.

## 4. Digital flow (`digital/`)

Detail: `digital/README.md` ("Running it", "Synthesis (issue #117)", "Place and
route (issue #166)"). The harnesses mint new append-only records with
`--emit-record`.

```bash
python3 sim/tests/test_digital_section.py          # stdlib only
python3 digital/model/params.py                    # cutoff derivation
python3 sim/digital-synthesis/harness/synthesize-and-verify.py --emit-record   # needs klt, iverilog
python3 sim/digital-pnr/harness/pnr-and-verify.py --emit-record                # ~30 min; tool pins in digital/flow/place-and-route/tool-pins.json
```

| Directory | Entry point |
|---|---|
| `sim/digital-health-test-parameters/` | `analysis/health-test-cutoffs.py`, `analysis/health-test-replay.py` |
| `sim/digital-conditioner-equivalence/` | `harness/conditioner-equivalence.py` |
| `sim/digital-section-behavioral/` | `harness/digital-section-campaign.py` |
| `sim/digital-conditioned-output/` | `analysis/conditioned-output.py` |
| `sim/digital-rtl-equivalence/` | `harness/rtl-cosim.py` (needs iverilog) |
| `sim/digital-synthesis/` | `harness/synthesize-and-verify.py` |
| `sim/digital-functional-verification/` | `harness/fv-cosim.py`; see its `README.md` |
| `sim/digital-sdf-timed-verification/` | `harness/fv-sdf-cosim.py`; see its `README.md` |
| `sim/digital-pnr/` | `harness/pnr-and-verify.py` |
| `sim/digital-electrical-repair/` | `bin/run-study.sh`; see its `README.md` |
| `sim/digital-floorplan-compaction/` | `bin/run-study.sh`; see its `README.md` |
| `sim/digital-repaired-compaction/` | `bin/run-study.sh`; see its `README.md` |

## 4a. Whole-block characterization (`sim/post-layout-whole-block/`)

Detail: `sim/post-layout-whole-block/README.md`. Requests are `klt sim` batch
corners requests (never a local ngspice grid); IR is `klt power`.

```bash
python3 sim/tests/test_whole_block_reduction.py                                  # stdlib only
python3 sim/post-layout-whole-block/make-requests.py /tmp/wb --set grid          # the 4 x (tt/ss/ff) requests
python3 sim/post-layout-whole-block/ir/run-ir.py /tmp/wb-ir                      # klt power static IR
python3 sim/post-layout-whole-block/analysis/reduce-whole-block.py               # coverage reduction (exit 1 until 12/12)
```

| Directory | Entry point |
|---|---|
| `sim/post-layout-whole-block/` | `make-requests.py`, `ir/run-ir.py`, `analysis/reduce-whole-block.py` |
