# 20261128 -- DR-0017 option (b): the coupled whole block is measured on the batch fleet and FITS the 3480 s ceiling (issues #431, #596)

**Claim**: the DR-0017 coupled deck (the extracted transistor sampler driving the
routed gate model) ran the whole committed program, 75 cycles and 7,870 ns, at
tt / 27 C / 1.8 V on the batch fleet in **431.63 s = 0.0548 s per simulated ns**,
against the **0.38119 s/ns budget fixed before any submission**: **6.9x margin,
feasible**. All **311** compared digital responses equal the normative model's
replay of the sampler input the deck captured. The grid's two timeouts are now
sized from this run.

**Level of this result, worded exactly**: **mixed-level (analog transistor /
digital gate-level), connectivity-only extract (no R/C)**. One nominal point,
one run, no characterisation credit: no per-supply current, power, IR or
timing figure is claimed from it. O5d, O7 and O8 stay forced UNMET,
`ac3_claimable` stays `false`, and #18 AC3 stays UNMET. Provisional,
simulation-derived, not foundry sign-off, **not silicon**.

**Supersedes**: the "feasibility is undetermined" state of
`records/20261121-coupled-rate.md`; the analog-only and gate-model-only
extrapolations to the whole block (`records/20261105-analog-chain-probe.md`,
`records/20261114-gate-model-realisation.md`); and the confounded 20261030 /
20261103 whole-block verdicts, for the whole block under option (b). It does
**not** supersede `records/20261106b-rate-probe-repinned-timeout.md` (section
below). No earlier record is edited.

## Criterion fixed before fleet submission

Unchanged from `records/20261121-coupled-rate.md`, committed at `b6d3867f`:
the unit ceiling is 3,480 s, 480 s are reserved, so the coupled circuit must
run at or below **3,000 s / 7,870 ns = 0.38119 s/ns**. The 100 ns probe is run
first; a completed probe within that budget qualifies the full program. A
feasible result also requires the full 7,870 ns and digital responses that
agree with normative replay. A refusal before simulation yields no rate.

The probe deck this run submitted has sha256
`b21d2a5ceea3dfa4466b9b3172c9ea415e0f056076180141909fc0a128c4747c`, the deck
that record names, and its `request.json` is byte-identical to the one
committed there. Nothing in the criterion, the deck or the stimulus changed
between the declaration and the run.

## What was run (two units, `klt sim`, batch backend, no local run, no retry)

Both from a host that has the `batch-runner-submit` profile, the lack of which
stopped the 2026-11-21 attempt at its first upload. Each unit: generate into an
empty directory, `--dry-run`, `--submit-only --wait-for-capacity 600`, poll
`--job-status`, then `--attach` with `--report-out`.

```bash
block="$PWD/sim/post-layout-whole-block"
run="$block/runs/20261128-coupled-full"      # .../20261128-coupled-probe for the probe
python3 "$block/make-requests.py" "$run/requests" --set coupled-full   # --set coupled-probe
req="$run/requests/coupled-full/request.json"
klt sim "$req" --backend batch --dry-run -o "$run/out"
klt sim "$req" --backend batch --submit-only --wait-for-capacity 600 -o "$run/out"
klt sim "$req" --backend batch --job-status <job_id>                   # until terminal
klt sim "$req" --backend batch --attach <job_id> -o "$run/out" --report-out "$run/report.json"
python3 "$block/analysis/compare-gate-model.py" "$run/report.json" \
    "$run/requests/coupled-full/plan.json" --emit-record-json "$run/compare.json"
```

Both dry runs validated one unit, bound 3,480 s of the 3,600 s ceiling. Both
submits were accepted at the first launch, with no capacity refusal. Each
client invocation's timestamps are in `submit-timing.log` and
`attach-timing.log`; no process of this session outlived its poll.

| | Probe (`runs/20261128-coupled-probe/`) | Full program (`runs/20261128-coupled-full/`) |
|---|---|---|
| `.tran` | `20p 100n` | `20p 7870n` |
| deck sha256 | `b21d2a5c...c4747c` | `5322a7aec108372ff1b2178a5d52109500f345aa3b380fdd79782bca1635da3c` |
| job | `klt-sim-1d857d429e5a` | `klt-sim-7d6f0e6f474f` |
| launched (UTC) | 2026-11-28T07:05:42Z | 2026-11-28T07:08:30Z |
| terminal | `done`, 07:06:43Z | `done`, 07:16:09Z |
| job `elapsed_seconds` | 51 | 447 |
| instance | `c7i.4xlarge`, spot, us-east-1a | `c7i.4xlarge`, spot, us-east-1a |
| corner `runtime_s` | **14.291** | **431.63** |
| simulated time reached | 100 ns of 100 ns | 7,870 ns of 7,870 ns (`clk_at_stop` resolved) |
| s per simulated ns | 0.14291 (2.7x under budget) | **0.054845 (6.9x under budget)** |
| measurements | 9 of 9 | 900 of 900 |
| data rows (`ngspice.log`) | 5,014 | 394,752 |
| peak RSS | 313 MiB | 544 MiB |
| digital comparison | none (ends before the first clock at 320 ns) | 311 of 311 equal to the normative replay |

No Spot interruption and no diagnostic on either job.

## Cost: start-up versus per-nanosecond

Two points of the same deck give a fixed and a marginal cost:
(431.63 - 14.291) / (7,870 - 100) ns = **0.0537 s/ns marginal** and
**8.9 s fixed** (DC operating point and start-up). The probe's 0.143 s/ns is
that fixed cost over a short window, which is why it is not the figure to
size with.

| Estimate made before this run | Figure | For 7,870 ns |
|---|---|---|
| analog chain alone, 500 ns measured (`20261105-analog-chain-probe.md`) | 0.057 s/ns | about 450 s |
| gate model alone, 7,870 ns measured (`20261114-gate-model-realisation.md`) | 0.00975 s/ns | 76.7 s |
| the two added linearly (an assumption `compare-gate-model.py` still declares) | | 525 s |
| **this run: the two coupled, measured** | **0.0548 s/ns** | **431.63 s** |

The coupled block costs less than the sum of its halves: the sampler is not
clocked for most of the analog-only probe's window, and in the coupled deck
the gate model replaces the 25,091 transistor-level digital devices the flat
netlist carried. Linear additivity was conservative here by 1.22x; it stays an
assumption, not a measurement. The data-row count (394,752 for 7,870 ns) shows
the timestep sat at `tmax` = 20 ps throughout: time, not accuracy, set the step
at this corner.

The probe's supply currents, averaged 20-100 ns, are snapshots with no
characterisation credit: `vdd` -109 uA, `vddr1`-`vddr4` -12.2 to -13.9 uA each
(source sign convention), within 5 % of the analog-only probe's averages over
20-500 ns. The four `ring_bit` outputs read about 0 V at 100 ns: the rings
have not left their start-up state that early.

## Digital comparison, and the strobe finding

`analysis/compare-gate-model.py` replays the normative model
(`digital/model/digital_top.py`) with the `raw_bit` and `raw_valid` the deck
captured at every cycle and compares every measured digital response with it.
Result on the full run (`compare.json`):

- **311 of 311 responses equal**: 75 each of `alarm`, `gated`, `startup_done`
  and `out_valid`, 9 register words (`rdata`) and 5 streaming words (`odata`).
  Three `odata` words (cycles 72-74) are not compared because the model reports
  `out_valid` = 0 there.
- `alarm` = 0, `gated` = 1 and `startup_done` = 0 at all 75 cycles, and
  `out_valid` = 1 in cycles 36 and 37 only, as the model predicts.
- `t_clk_first` = 320.05 ns: the clock started where the deck says (320 ns,
  50 % of a 100 ps edge).

**Finding: the sampler's `raw_valid` is a level, not the program's strobe.**
The comparator as committed at run time also checked the captured `raw_valid`
against the per-cycle strobe of `program.cycle_inputs()`. It returned
`valid_mismatches` = cycles 0-3, 36-41 and 74, **11 of 75**, and the verdict
**fail** (`compare-at-run-time.json`). Those are exactly the cycles in which
the standalone decks' testbench holds `raw_valid` low: the three audit reads,
the enable write, the six register-phase reads and the final read.

The sampler cannot produce that schedule. `design/sampler_core.spice`
registers `raw_valid` as a flip-flop with its data tied to `vdd`
(`xsv vdd clk rst_n raw_valid vdd vss sampler_dff`), and `design/README.md`
("Pins that leave the block") documents it: "high one `clk` edge after `rst_n`
releases, and stays high". The sampler has no input that could hold it off in
a bus cycle. The live capture shows 1.8 V at all 75 cycles. The per-cycle
`raw_valid` of the program is a testbench source for the standalone digital
decks (#486); it was never a description of the sampler, and the offline test
that pinned the check built its own `raw_valid` from that column, so it could
only agree with itself.

What it means for the block: once `CTRL.EN` is set, the digital section takes
a sample in every cycle, 71 in this program (cycles 4-74), not the 64 the
standalone schedule delivers. Six of the 311 responses differ from the
standalone run's, and the model explains each: the `STATUS` words (cycles 2,
36 and 41: standalone `0x2` / `0x106` / `0x2`, coupled `0x6` / `0x10e` /
`0x6`) show the sampler's `raw_valid` in `RAW_TAP_VALID` and the raw FIFO
state after the samples taken in the bus phase; the `RAW_DATA` word (cycle 37)
and the two `out_data` words (cycles 36 and 37) hold the sampler's bits rather
than the committed synthetic pattern. The gate-level digital section tracks
the normative model under the sampler's real input; no block defect is
indicated by the mismatch.

**Change made after the run, and it is for review to confirm or reject.** The
comparator's strobe reference is now the sampler's documented behaviour,
derived from the deck's reset and clock timing (`sampler_valid`), instead of
the testbench column. On the same, unmodified report it returns
`valid_mismatches` = [], `standalone_strobe_low` = the same 11 cycles, verdict
**pass**; the 311 response checks are byte-identical between the two versions.
This is a correction of an oracle that measured the wrong thing, not a
relaxation: a low or undecodable `raw_valid` at any capture still fails the
run, at any cycle. The functional gate is therefore recorded twice, and
neither is withdrawn:

| Oracle | Strobes | Responses | Verdict |
|---|---|---|---|
| as committed at run time (`compare-at-run-time.json`) | 11 of 75 differ from the testbench schedule | 311 of 311 | fail |
| as corrected in this change (`compare.json`) | 75 of 75 as the sampler is specified | 311 of 311 | pass |

Until the correction is accepted, #307 should read the functional gate as
*passed under the corrected oracle, failed under the oracle as committed*.

## Verdict against the 3480 s ceiling

- **Speed: feasible.** 431.63 s for the full program at the nominal point,
  6.9x under the 3,000 s allowance and 8.1x under the 3,480 s ceiling. The
  analog chain plus a gate-level digital block fits the ceiling. This is a
  measurement, not an extrapolation.
- **Function:** the digital responses agree with normative replay, 311 of 311.
  The strobe clause passes against the sampler's documented `raw_valid` and
  fails against the standalone testbench schedule, as the table above records.
- **Not established by this record:** any other corner (ss, ff, -40 C, 125 C,
  1.62 V, 1.98 V); the behaviour under concurrent units on one instance; any
  current, power, IR or timing figure; entropy at any rate. The raw bits are
  the sampler's and are not entropy evidence: `Ts` = 100 ns, not the ratified
  20 us (O8).

## Grid timeouts sized from this run

`make-requests.py --set grid` now derives its two timeouts instead of carrying
the 21,600 s / 6,600 s pair, which had no rate behind it and could not be
submitted under the ceiling:

- `timeout_s` = **864 s** per unit: the measured 431.63 s times a declared
  allowance of 2.0 for the grid's unmeasured points. The allowance is
  declared, not measured. A unit timeout above 3,480 s refuses generation.
- `poll_timeout_s` = **3,012 s**: one request is one job of three units
  (tt, ss, ff), whose serial bound 3 x 864 + 120 = 2,712 s sits under the
  3,600 s fleet ceiling, plus 300 s for boot, staging and collection (36.7 s
  observed around the probe's simulation, 15.4 s around the full run's). A
  bound the ceiling cannot hold refuses generation before anything is written.
- Every generated grid `plan.json` carries the basis in `timeouts`. The four
  committed `corners/grid-*` requests are historical evidence and keep their
  filed values.

**What this sizing does not make runnable.** `--set grid` still emits the flat
transistor-level whole-block deck, which is the deck that timed out twice; the
timeouts are those of the coupled deck the matrix runs under option (b). Before
the 12 points are submitted, the grid set has to emit the coupled deck per
point (a gate model from `make-gate-model.py --point`), and
`analysis/reduce-whole-block.py` has to replay the sampler's strobes: it reads
the raw taps only in the program's sample cycles today, so it would score the
extra samples as mismatches. Both are #307's work. This record sizes the
matrix; it does not re-queue it.

## What this record supersedes, and what it does not

- `records/20261121-coupled-rate.md`: its "feasibility is undetermined" and
  "no measured figure" are replaced by the measurements above. Its upload
  refusal (`klt-sim-9ffb4c91eb0f`) stands as evidence of the host gap it names.
- `records/20261105-analog-chain-probe.md` and
  `records/20261114-gate-model-realisation.md`: their own measurements stand
  (analog chain alone, gate model alone). Their whole-block figures, "about
  450 s" by linear extrapolation and the additivity assumption, are replaced
  by the coupled measurement.
- `records/20261030-fleet-probe-post-bin-fix.md` and
  `records/20261103-rate-probe-infeasible.md`: their "infeasible" verdicts were
  measured on a netlist whose ports were not connected (`20261105`), so they
  are superseded for the analog chain by that record and, for the whole block
  under option (b), by this one.
- **Not superseded:** `records/20261106b-rate-probe-repinned-timeout.md`. The
  flat transistor-level whole block did not finish 100 ns in 3,480 s on the
  connected netlist, and this record did not re-run it. That verdict stands
  for the flat deck. `records/20261106-rate-probe-repinned-netlist.md` (no
  verdict) is unchanged.

## Provenance

- Client `klt 0.9.3.dev5891+gdb90790c546c`, runner `klt 0.9.0`,
  `runner_compatibility` match; `image_profile` `sim`, AMI
  `ami-09c14f55df4958cbd`; 8 physical cores, Intel Xeon Platinum 8488C.
- Engine ngspice 47, binary sha256
  `e12148baf532d879d2e2053cecc5b498680bd4156a0dc3f69ce4f83e741e1314`, engine
  build comparison match. The analog-only probe of `20261105` ran on ngspice
  46.
- PDK `sky130A`, open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`: runner
  `/opt/pdk`, stamp comparison match; client via `~/.ciel`, a second install
  under `~/.volare` skipped. `models_lib` sha256
  `48de7c677e2c6e7d09b2559279de9f818be71010a4aa933d728eb4db3b133c84` on both
  sides, match. Models staged: no.
- Deck inputs (`plan.json` of each request): flat extract
  `965f1e6c29d771d5b8e18a3ea66ccabf93f0a5eb14c3f0c23810f39ae1052c36`, analog
  partition `ab2362ec6a80f39d1eecb6f298c07ff81b6a4fb0080115620de0fa33f9413f67`,
  routed Verilog
  `9f3956848e6e75223f75bd154df905fecbb4e988593e78d1a92e347969fbf37f`, gate
  model `abbe277084a8d97a4af35a054e151ebb1faa2d48d4a93bb6f39e9efcce447e51`,
  Liberty `sky130_fd_sc_hd__tt_025C_1v80`
  `8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135`, boundary
  load option 2 (`records/20261121-pvt-deck-and-boundary-load.md`).
- Committed per run: `request.json`, `plan.json`, `report.json`, the submit,
  status and attach logs with timestamps, `batch-receipt.json`, the corner
  deck and `ngspice.log`. The per-request `netlist.cir` is regenerated by the
  generator and pinned by the sha256 above; `test_make_requests.py` regenerates
  both decks and checks them against the committed reports.
- Observed on the way, not blocking: a report collected by `--attach` carries
  `environment.remote.job_ceiling: null`, so the ceiling assessment cited here
  comes from the dry run and the submit log. `ngspice.log` again has no
  progress lines (klayout-tools#4867); simulated time reached is taken from the
  completed transient and `clk_at_stop`, not from progress output.
