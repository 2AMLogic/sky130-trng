# ro-vth-drift-sensitivity

Issue #254. End-of-life drift **sensitivity** of the ring-oscillator array: a bounded
threshold-voltage shift (BTI/HCI-like) applied to every NMOS and PMOS of the committed
`design/ro_ring5.spice` and `design/ro_array_core.spice`, swept across PVT. Everything here
is simulation-derived and provisional until silicon, and it is a first-order electrical
model only.

**This is a sensitivity bound, not a lifetime prediction.** Nothing in this slug converts a
threshold offset into a time, voltage, duty cycle or temperature, ratifies a lifetime or a
guard band, or changes a spec. Any such decision is an operator decision record
(see `spec/README.md`).

| File | Role |
|---|---|
| `aging.py` | the deterministic aged-netlist generator and the signed gate-offset wrappers (`vth_wrap_nfet`, `vth_wrap_pfet`); rejects unsupported device shapes |
| `campaign.py` | the PVT x shift grid, the required-key manifest, and the mechanical derivation of each `klt sim` request from the **unmodified** source testbenches |
| `make-requests.py` | writes `OUTDIR/<name>/{netlist.cir,request.json,plan.json}` (controls or grid) |
| `coverage-manifest.json` | the 222 required `(deck, corner, T, Vdd, dVtn, d|Vtp|)` keys; `analysis/sensitivity.py --check-manifest` fails if it drifts from the generator |
| `testbench/tb_dc_gate_offset.spice` | control 1: wrapped + unwrapped reference devices in one DC deck |
| `analysis/sensitivity.py` | reduction: metrics, matched zero-shift pairing, coverage check, controls/grid records, calibration artifact, `--check` replay |
| `analysis/behavioral_replay.py` | matched-seed behavioral replay through the existing raw-bit min-entropy reduction |
| `records/<id>.{md,json}` | append-only records (controls, sensitivity, behavioral replay); `records/<id>.calibration.json` is the versioned calibration artifact |
| `corners/<id>/` | per request: raw `*.klt-sim.json.gz` (job id inside), `*.request.json`, `*.netlist.cir`, `*.plan.json` |
| `../tests/test_vth_drift.py` | unit tests: wrapper generation, rejection, manifest, metrics, fail-closed rows, calibration negative tests |

## Model

For each instance of the pinned `sky130_fd_pr__nfet_01v8` / `sky130_fd_pr__pfet_01v8` the
generator swaps only the model token for a wrapper subcircuit that puts a voltage-controlled
source in series with the gate:

- NMOS, `dVtn >= 0`: `V(g_device) = V(g_original) - dVtn`
- PMOS, `d|Vtp| >= 0`: `V(g_device) = V(g_original) + d|Vtp|`

Drain/source/body nets and all 14 instance parameters are untouched (the generator requires the
exact parameter set and four nets, else `UnsupportedDevice`). The PDK and the committed
schematic-generated netlists are not edited; the aged netlist is derived text, inlined into each
request. The two shifts are read from independent global DC knob nodes (`vth_dvn`, `vth_dvp`) and
swept with `klt sim` `corners.supply_v` `alter` (the same mechanism as
`ro-array-supply-perturbation/`). Every unit `.meas`-es the knob nodes and the reduction rejects a
row whose read-back differs from its request, so a dropped `alter` cannot masquerade as a
shifted run.

**Why 20 mV and 60 mV.** 20 mV is the finite-difference resolution: it keeps four points
(0/20/40/60) for a monotonicity check while the pilot shows it already moves the ring period by
~6 % at `tt` / 27 C / 1.8 V, well above the 0.1 % deterministic tolerance. 60 mV is the declared
outer stress point, three steps out. Neither value is derived from SKY130 stress data. No public
SKY130-specific reliability source was relied on; general NBTI/PBTI/HCI literature on tens-of-mV
shifts in 130 nm-class CMOS is only illustrative and not technology-specific. No source is used to
turn the sweep into a lifetime.

## Replay

```bash
python3 sim/ro-vth-drift-sensitivity/make-requests.py REQDIR --set controls     # DC probe, unwrapped controls, pilot (local, one at a time)
python3 sim/ro-vth-drift-sensitivity/make-requests.py REQDIR --set grid         # 21 requests -> batch fleet (KLT_SIM_BACKEND=batch)
klt sim REQDIR/<name>/request.json -o REQDIR/<name>/out --format json > REQDIR/<name>/resp.json
python3 sim/ro-vth-drift-sensitivity/analysis/sensitivity.py --emit-controls REQDIR
python3 sim/ro-vth-drift-sensitivity/analysis/sensitivity.py --emit-record REQDIR --controls <controls rid>
python3 sim/ro-vth-drift-sensitivity/analysis/behavioral_replay.py --emit-record
# checks (no simulator needed)
python3 sim/ro-vth-drift-sensitivity/analysis/sensitivity.py --check-manifest
python3 sim/ro-vth-drift-sensitivity/analysis/sensitivity.py --check sim/ro-vth-drift-sensitivity/records/<id>.json
python3 sim/ro-vth-drift-sensitivity/analysis/behavioral_replay.py --regenerate-check sim/ro-vth-drift-sensitivity/records/<behavioral id>.json
python3 sim/tests/test_vth_drift.py
```

`--emit-record` refuses to mint a grid record unless a PASSing controls record exists, the generator
hashes match it, every one of the 222 keys is present exactly once, every row is usable, and every
shifted row has its matched zero-shift row.

## Campaign design

- `ring5` (`tb_ro_ring5_jitter.spice`): common-mode 0/20/40/60 mV over tt/ss/ff x -40/27/125 C x
  1.62/1.8/1.98 V. Seed 1, `.tran` max step 20p, 21 crossings / 20 periods, noise amplitude 2.0e-3 and
  the 20n..115n swing window are the source deck's own.
- `array` (`tb_ro_array_core.spice`): the same common-mode grid (tmax 5p, stop 200n, source measurements),
  plus asymmetric (60, 0) and (0, 60) mV at ss/-40 C/1.62 V, tt/27 C/1.8 V, ff/-40 C/1.98 V.
- One request = one (deck, T, Vdd) point x process list x zipped shift units; 21 requests.

**Deliberate deviation: ring `.tran` stop is 175n, not 115n.** 115n is sized for the slowest *time-zero*
corner (5 + 20 x 4.82 ns). A shifted ring is up to ~20 % slower (pilot), so 21 crossings would not fit.
The stop is raised uniformly for the zero-shift and shifted rows of this campaign (so each pair is
like-for-like). A side effect is that the noise realization differs from the historical 115n records
(noise sources are generated over the stop time), so `sigma_1` here is **not** comparable row-for-row to
the historical records: compare only within this campaign.

## Estimator limits (inherited, not tightened)

20 periods give ~16 % (1-sigma) on `sigma_1` and ~32 % on `Q_ring`; one seed per point; fixed injection
level good to ~1.5-2x; `sigma_1` is deflated by the tt/27 C/1.8 V numerical floor (not re-measured under
shift, not per corner). Because this noise is larger than the 3.6 % DR-0003 margin, the DR-0003/DR-0004
view reports both an *as-measured* variant and a *period-only* variant (`sigma_1` held at the matched
zero-shift row, only the ring periods move); only the latter resolves the period term.

## Records

| Record | What |
|---|---|
| `records/20261010-164921-7e279ab.*` | controls (PASS): DC gate offset within 1 uV for 0/20/40/60 mV and the asymmetric (60,0)/(0,60) mV pairs, wrapped current equal to the unwrapped device at the shifted gate, zero-shift equivalence (array within 0.1 %; ring period/swing within 0.1 %, `sigma_1` within the 2-sigma band of two noise realizations), tt/27 C/1.8 V pilot monotone (+6.1/+12.8/+20.1 % ring, +5.8/+12.1/+19.0 % array period) |
| `records/20261010-175052-7e279ab.*` (+ `.calibration.json`) | the 222-row sensitivity grid, matched zero-shift pairing, small-rational approach, DR-0003/DR-0004 view, batch job ids |
| `records/20261010-175419-7e279ab.*` | matched-seed behavioral replay (108 streams, model output) |

Headline (see the records for the tables): a 60 mV common-mode shift slows the ring by +9.9 % to +31 %
across the PVT grid; DR-0003's 1.036 `Q` margin is exhausted within 3-8 mV of common-mode shift at every grid
point (period term only); the model-derived `H` bound crosses DR-0004's `H = 0.5` evaluation floor within 60 mV
at 3 of 27 grid points; the closest small-rational approach stays above 6 %. The follow-up decision request is
issue #262; nothing in `spec/` is changed here.

## Execution notes (what did not go to plan)

- The fleet runner is klt 0.5.0 and refuses the host's 0.7.0 client (`batch_runner_version_mismatch`; already
  tracked in `2AMLogic/klayout-tools` #2948 / #2851). The grid was submitted with a throwaway
  `uvx --from "klayout-tools==0.6.0" klt sim` client; no host tool was changed. Controls ran with the host klt
  locally (single points).
- First grid attempt at the array deck's source stop (200n) lost one unit (`tt1b` measurement: the 50th edge of
  the slowest shifted ring falls after 200n). The array stop was raised to 300n for every array row and the
  controls re-minted; the aborted first-attempt responses were not recorded.
- Four ring units aborted on the fleet (`2AMLogic/klayout-tools#3067`). Two cleared on a same-stop re-run; two
  (ss / -40 C / 1.62 V at 20 and 40 mV) failed deterministically with ngspice `Timestep too small` at the final
  breakpoint and were re-run with the ring stop nudged to 180n, which changes their noise realization: they are
  flagged `stop_override` and only their period/swing (not `sigma_1`/`Q_ring` deltas) are comparable to the
  matched zero-shift row. No unit was dropped.
