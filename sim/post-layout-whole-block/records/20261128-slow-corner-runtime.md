# 20261128 -- the slowest-expected grid point runs INSIDE the nominal: ss / -40 C / 1.62 V measured at 403.9 s, the 2.0x grid allowance kept (issue #814)

**Claim**: the coupled deck of ss / -40 C / 1.62 V -- `--set grid`'s own deck
for that point, sha256 `92b9f10a...` -- ran the whole committed program, 75
cycles and 7,870 ns, on the batch fleet in **403.9 s = 0.0513 s per simulated
ns**: **0.94x** the nominal point's 431.63 s
(`records/20261128-coupled-rate.md`) and **well inside** the grid's 864 s unit
timeout (2.14x under it). The hypothesis #814 was filed on -- that a slow
corner needs more than the nominal point -- is **refuted for this point**. The
nominal point is therefore the worst measured point, and `GRID_MARGIN_X`
**stays at 2.0**: not raised, because nothing measured needs it, and not
lowered to the 1.25x the issue's formula yields from the two measured points,
because a unit timeout is a kill-bound, not a reservation, and ten of the
twelve points are still unmeasured (the section below; for review).

**Level of this result, worded exactly**: **mixed-level (analog transistor /
digital gate-level), connectivity-only extract (no R/C)**. One non-nominal
point, one run, no retry: **a runtime only**. No functional oracle ran at this
point and no characterisation credit: no per-supply current, power, IR or
timing figure is claimed from it. O5d, O7 and O8 stay forced UNMET,
`ac3_claimable` stays `false`, and #18 AC3 stays UNMET. Provisional,
simulation-derived, not foundry sign-off, **not silicon**.

**Supersedes**: the sentence "Declared, not measured: no coupled run exists at
any other corner" of the `GRID_MARGIN_X` comment in
`sim/post-layout-whole-block/make-requests.py` (as of `e06ee72a`), and the
"declared, not measured" wording of the "Grid timeouts sized from this run"
section of `records/20261128-coupled-rate.md` -- **for ss / -40 C / 1.62 V
only**. It does **not** supersede that record's measurements, and the
allowance stays declared for the ten unmeasured points. No earlier record is
edited.

## The rule this run is judged by

The issue's own revised text (Curator enhancement, 2026-11-28), fixed before
the submission: measure **ss / -40 C / 1.62 V** first; measure ss / 125 C /
1.98 V as well only if that run exceeds about **1.5x** the nominal (647.4 s);
set `GRID_MARGIN_X` to `ceil(worst_measured / 431.63 x 1.25, 2 decimals)`,
capped by what `grid_timeouts()` can hold; run it on the batch fleet with
`--wait-for-capacity 600`; and "a measured refutation is a complete outcome".
The deck was fixed by the generator before the run (sha256 above). The one
judgement made after the result was known -- not lowering the allowance -- is
marked for review below.

## What was run (one unit, `klt sim`, batch backend, no local run, no retry)

From a host that has the `batch-runner-submit` profile (the receipt names it):
generate into an empty directory, `--dry-run`, `--submit-only
--wait-for-capacity 600`, poll `--job-status`, then `--attach` with
`--report-out`.

```bash
block="$PWD/sim/post-layout-whole-block"
run="$block/runs/20261128-slow-corner-ss-m40C-1.62V"
python3 "$run/make-request.py" "$run/requests"
req="$run/requests/grid-ss-m40C-1.62V/request.json"
klt sim "$req" --backend batch --dry-run -o "$run/out"
klt sim "$req" --backend batch --submit-only --wait-for-capacity 600 -o "$run/out"
klt sim "$req" --backend batch --job-status klt-sim-4ec1825cfa41     # until terminal
klt sim "$req" --backend batch --attach klt-sim-4ec1825cfa41 -o "$run/out" --report-out "$run/report.json"
python3 "$run/compare-vs-nominal.py"
```

The dry run validated one unit, bound 3,480 s of the 3,600 s ceiling. The
submit was accepted at the first launch, with no capacity refusal. The client
timestamps are in `gen-timing.log`, `submit-timing.log` and
`attach-timing.log`; the job was polled to its terminal state inside the
session that submitted it, and no process of that session outlived the poll.

| | Nominal (`runs/20261128-coupled-full/`) | This run (`runs/20261128-slow-corner-ss-m40C-1.62V/`) |
|---|---|---|
| point | tt / 27 C / 1.8 V | **ss / -40 C / 1.62 V** (all five rails at 1.62 V) |
| `.tran` | `20p 7870n` | `20p 7870n` |
| deck sha256 | `5322a7ae...35da3c` | **`92b9f10a5be5af7a07c486651a1c0947beda910d5bda89bcafd00aca1155660c`** |
| gate model's Liberty deck | `sky130_fd_sc_hd__tt_025C_1v80` | `sky130_fd_sc_hd__ss_n40C_1v60` |
| request `timeout_s` / `poll_timeout_s` | 3360 / 3480 | 3360 / 3480 |
| job | `klt-sim-7d6f0e6f474f` | **`klt-sim-4ec1825cfa41`** |
| launched (UTC) | 2026-11-28T07:08:30Z | 2026-11-28T11:52:42Z |
| terminal | `done`, 07:16:09Z | `done`, 11:59:44Z |
| job `elapsed_seconds` | 447 | 412 |
| instance | `c7i.4xlarge`, spot, us-east-1a | `c7i.4xlarge`, spot, us-east-1a |
| corner `runtime_s` | 431.63 | **403.9** |
| simulated time reached | 7,870 ns of 7,870 ns | 7,870 ns of 7,870 ns (`clk_at_stop` resolved) |
| s per simulated ns | 0.054845 | **0.051321** |
| data rows (`ngspice.log`) | 394,752 | 394,794 |
| measurements | 900 of 900 | 917 of 917 (the coupled matrix set, #815) |
| peak RSS | 544 MiB | 579 MiB |
| engine | exit code 0 | exit code 0, not killed by a signal |

No Spot interruption and no diagnostic on the job.

## The request is the grid's request for that point

The measurement is only evidence about a grid unit if the deck that ran is
the deck the grid will run, so this was checked before the submission, against
`make-requests.py --set grid` regenerated into a throwaway directory:

- **Deck: byte-identical** to `grid-ss-m40C-1.62V/netlist.cir` as `--set grid`
  emits it (the sha256 above, on disk, in the plan and in the report).
- **`request.json` differs in exactly two fields**: `options.timeout_s`, 864
  -> 3360, and `batch.poll_timeout_s`, 1284 -> 3480.
- **`plan.json` differs in the `timeouts` block only.**

`test_make_requests.py` pins both facts
(`test_slow_corner_measurement_is_the_grids_request_for_that_point`).

**Why the measurement timeouts differ from the grid's.** A measurement has to
record a runtime even when the corner turns out to be slow. Submitted with
the grid's 864 s, a slow corner would have been killed at the timeout, which
yields "longer than 864 s" and no figure to size an allowance from. The pair
used is the one #596 measured the nominal point with: 3,360 s worker + 120 s
batch overhead = the 3,480 s one-unit cap, the largest a one-unit job holds.

## Why the slow corner is not slower to simulate

- **The step count is the corner's to keep, not to change.** 394,794 data rows
  against the nominal's 394,752 (+42, +0.01 %): at both points the timestep
  sat at `tmax` = 20 ps for the whole 7,870 ns. A point's number of steps is
  set by the deck's `tmax`, so it is the same at every point where `tmax`
  binds, as it did at both measured ones.
- **What differs is the cost per step: 1.023 ms here against 1.093 ms at the
  nominal, 6.4 % lower.** The corner that is slowest for the circuit is the
  cheaper one to simulate. The cause is not measured here -- the log carries
  no iteration counts -- so "a slower circuit asks less of the solver per
  step" is a reading of the two figures, not a finding.
- **What that suggests for the ten unmeasured points, as a hypothesis only:**
  the runtime is steps x cost per step; the step count is fixed where `tmax`
  binds; and the per-step cost moved by -6 % between two points as far apart
  as tt / 27 C / 1.8 V and ss / -40 C / 1.62 V. A point would need twice the
  nominal's per-step cost to reach 864 s. If any point costs more per step it
  is likelier to be a fast one (ff, 1.98 V), whose edges are steeper relative
  to 20 ps, than a slow one. Not measured. The 2.0x allowance is what covers
  it, and a killed unit in #307 would show it.

## The allowance: kept at 2.0x -- for review to confirm or reject

- The worst measured point is the nominal, 431.63 s. The issue's formula,
  `ceil(worst_measured / 431.63 x 1.25, 2 decimals)`, gives **1.25**, i.e. a
  540 s unit timeout.
- Applied literally, that would **lower** the grid's unit timeout from 864 s
  to 540 s -- the opposite of what #814 was filed for. A unit timeout is a
  kill-bound, not a reservation: a unit that finishes early is not made to
  wait, so a wider timeout costs nothing, while a narrower one turns any
  unmeasured point above 1.25x nominal into a killed unit and a lost fleet
  job. Ten of the twelve points are unmeasured.
- Not raised either: nothing measured needs more than the nominal, and the
  issue's own text calls a slow corner well inside 864 s a complete outcome
  ("no change needed").
- So `GRID_MARGIN_X` stays 2.0: `timeout_s` 864 s, job bound 984 s, poll
  1,284 s, unchanged. **What changed is its basis.** Every grid `plan.json`
  now carries the slow-corner measurement beside the nominal one
  (`timeouts.slow_corner_point`, `slow_corner_runtime_s`,
  `slow_corner_record`), `SLOW_CORNER_RUNTIME_S` is pinned to this record's
  figure, and a test refuses an allowance below what the two measured points
  ask for.
- The title's "2.69x" was the **three-unit** job shape's ceiling (1,160 s).
  Since #815 a request is one unit, whose timeout can hold 3,480 s = **8.06x**.
  `grid_timeouts()` still refuses past it (8.06x -> 3,479 s accepted; 8.1x ->
  refused) and still refuses the three-unit shape above what the ceiling
  holds. The ceiling and `BATCH_OVERHEAD_S` are not touched.

## Verdict

- **Speed at this point: measured.** 403.9 s for the full program at
  ss / -40 C / 1.62 V, 0.94x the nominal and 2.14x under the grid's 864 s unit
  timeout. The slowest-expected corner does not need more than the nominal.
- **Second corner (ss / 125 C / 1.98 V): not run.** The issue makes it
  conditional on the first exceeding about 1.5x nominal (647.4 s); this one
  measured 0.94x.
- **Allowance: kept at 2.0x**, on the basis stated above.
- **Not established by this record:** the other ten points (ff at all four
  (T, V); ss and tt at -40 C / 1.98 V and at 125 C / 1.98 V; ss at 27 C /
  1.8 V); the behaviour under concurrent units on one instance; the digital
  responses against the normative model at this point; any current, power, IR
  or timing figure; entropy at any rate. The raw bits are the sampler's and
  are not entropy evidence: `Ts` = 100 ns, not the ratified 20 us (O8).

## Digital responses: an observation, not an oracle

No functional oracle ran at this point. `analysis/compare-gate-model.py` is
the nominal run's comparator and refuses a non-nominal corner
(`compare-refused.log`: "batch report corner differs from the nominal coupled
request"); the matrix's per-point oracle is #307's
(`analysis/reduce-whole-block.py`). What can be stated is a consistency
observation, produced by the run directory's `compare-vs-nominal.py`
(`compare-vs-nominal.json`): of the run's **748** digital responses, **724**
equal the nominal run's cycle for cycle once a logic high is scaled by the
rail (1.62 V here, 1.8 V there, within 5 % of the rail).

- All **300** scalars equal: `alarm`, `gated`, `startup_done` and `out_valid`,
  75 each. `alarm` = 0, `gated` high and `startup_done` = 0 at all 75 cycles;
  `out_valid` is high in cycles 36 and 37 only, as at the nominal.
- `t_clk_first` = 320.05 ns, as at the nominal; `t_out_valid_first` = 3.924 us.
- The **24** that differ are exactly the bits of three words: `rdata` cycle 37
  (the `RAW_DATA` read) and `odata` cycles 36 and 37 (the two `out_data`
  words). Those are the three words the nominal record identifies as holding
  the sampler's bits, which are this run's own and differ from corner to
  corner by nature.

This is agreement with the nominal run, not with the normative model.

## Provenance

- Client `klt 0.9.3.dev5934+g88de22f5fefb` (the nominal run's client was
  `0.9.3.dev5891+gdb90790c546c`), runner `klt 0.9.0` as on the nominal run,
  `runner_compatibility` match; `image_profile` `sim`, AMI
  `ami-09c14f55df4958cbd`; 8 physical cores, Intel Xeon Platinum 8488C.
- Engine ngspice 47, binary sha256
  `e12148baf532d879d2e2053cecc5b498680bd4156a0dc3f69ce4f83e741e1314` -- the
  nominal record's binary -- engine build comparison match.
- PDK `sky130A`, open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`: runner
  `/opt/pdk`, stamp comparison match; client via `~/.ciel`, a second install
  under `~/.volare` skipped (the same two-install warning as on the nominal
  run). `models_lib` sha256
  `48de7c677e2c6e7d09b2559279de9f818be71010a4aa933d728eb4db3b133c84` on both
  sides, comparison match. Models staged: no.
- Deck inputs (`plan.json`): flat extract
  `965f1e6c29d771d5b8e18a3ea66ccabf93f0a5eb14c3f0c23810f39ae1052c36`, analog
  partition `ab2362ec6a80f39d1eecb6f298c07ff81b6a4fb0080115620de0fa33f9413f67`
  and routed Verilog
  `9f3956848e6e75223f75bd154df905fecbb4e988593e78d1a92e347969fbf37f`, the
  nominal record's three; gate model
  `b7d0d8338956092bb758dc94402b76d9f39a5a4032bafc23fd8e309323cd7f6b` reduced
  from Liberty `sky130_fd_sc_hd__ss_n40C_1v60.lib`
  `23cba893b985a950a7951e3f29ae66ae6a639aaef75c1478e2306fb68d4a7ee5`; the
  point's deck row (`pvt_deck_map.py`: dT 0 K, dV -0.02 V, delay direction
  pessimistic, power direction optimistic, estimated delay error 3.1 %;
  `records/20261121-pvt-deck-and-boundary-load.md`); boundary load option 2.
- Committed per run: `make-request.py` (the request's generator),
  `request.json`, `plan.json`, `report.json`, the submit, status and attach
  logs with timestamps, `jobid`, `batch-receipt.json`, the corner deck and
  `ngspice.log`, `compare-refused.log`, and the consistency observation's
  script and output. The per-request `netlist.cir` is regenerated by
  `make-request.py` and pinned by the sha256 above.
- Observed on the way, not blocking: `klt`'s advisory `timeout_preflight_warning`
  ("3360 s looks implausible for ~3.94e5 timepoints at a 50 timepoints/s
  floor") on this run as on the nominal; the run's own rate was about 980
  steps per second. It did not block the submission. A report collected by
  `--attach` again carries no `environment.remote.job_ceiling` field (as on
  the nominal run), so the ceiling assessment cited here comes from the dry
  run and the submit log.
