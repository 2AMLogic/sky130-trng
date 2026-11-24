# 20261030 -- whole-block fleet probe after the bin fix: ngspice gets past parse, times out in analysis (issue #386, items c/d)

**Claim**: after transform 4 (`records/20261029-narrow-nfet-model-bin.md`), the whole-block flat
netlist no longer aborts at ngspice parse on the fleet. The single probe unit did **not** complete:
it ran into its 3480 s bound inside the analysis, so no circuit behaviour was observed.

Provisional, simulation-side. No simulation result is claimed; #307 stays unmet.

## What was run (one unit, `klt sim`, batch backend, no local run)

- Request: `runs/20261030-probe-post-bin-fix/corners/startup-probe-batch/request.json`, regenerated
  with `make-requests.py --set controls` from the committed (fixed) `trng_whole.sim.spice.gz`:
  `tt`, 27 C, all five supplies 1.8 V, `tran 20p 970n`, `timeout_s` 3480. Same request as the
  20261018 probe, so the only difference is the netlist. `netlist.cir` (15 MB) is not committed;
  its sha256 is `69d598b3...f29aa` in `plan.json` and it is regenerable.
- `klt sim <req> --backend batch --submit-only`, then `--job-status` polling, then `--attach`
  to collect. One submit, no retries, no capacity refusal.
- Job `klt-sim-2c6cc3324669` (`environment.remote`, `report.json`), launched 2026-10-30T00:24:43Z,
  spot `c7i.8xlarge` us-east-1a, `runtime_s` 3480.66, exit 4.

## Result

| | 20261018 (pre-fix netlist) | 20261030 (this probe) |
|---|---|---|
| `ngspice.log` | `Error on line 803 ... could not find a valid modelname`, `Simulation interrupted due to error!` | banner, `Circuit:`, `Doing analysis at TEMP = 27.000000`, `Using SPARSE 1.3 as Direct Linear Solver`; **no model error** |
| klt diagnostic | measurements `produced no value` | `timeout - ngspice did not complete within 3480s, killed` |
| runtime | 2844 s (stopped at the error) | 3480.66 s (killed by the bound) |

ngspice prints the `Doing analysis` line only after the deck is parsed and flattened, and the
20261018 log shows it never got there. So parse is passed. What the probe does not show: how far
the transient got (the log has no progress output), whether the DC start-up converged, or any
measurement (all 127 `produced no value`, a consequence of the kill, not of the circuit).

## Consequences

- #386 cause and fix confirmed on the fleet: the W=0.36 nFET bin error is gone.
- A new, separate limit is now visible: one transistor-level unit of the 6-cycle, 970 ns program
  does not finish in 3480 s. The 20261018 OUTCOME already noted the full
  7.87 us program cannot fit one unit; sizing the budget is #307's scope, not this issue's.
- Runner PDK: the report says `open_pdks c6d73a35f524...` at `/opt/pdk`
  (`pdk_stamp_comparison: not_comparable`), while the 20261018 OUTCOME recorded `f6eeac7d...`,
  the build the bin scan used. Both parsed the same cards here; flagged as an unresolved
  discrepancy, not explained.
- `engine_build_comparison` reports an ngspice build mismatch (runner 46, client local).
