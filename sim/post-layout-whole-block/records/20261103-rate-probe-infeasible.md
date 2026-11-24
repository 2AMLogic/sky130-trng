# 20261103 -- whole-block rate probe (100 ns): still times out at the unit ceiling; no rate derivable (issue #403)

**Claim**: the shortest feasible probe tried here -- the same flat post-layout netlist cut to
`.tran 20p 100n` (DC start-up plus ring oscillation only, before the clock at 320 ns) -- did **not**
finish inside the 3480 s unit ceiling. No simulated-time vs wall-time rate can be derived from it.
Outcome: **measured infeasible at this probe length and this netlist**. Provisional,
simulation-side; #307 stays unmet.

## What was run (one unit, `klt sim`, batch backend, no local run, no retry)

- Request: `runs/20261103-rate-probe/corners/rate-probe-batch/request.json`, generated with
  `make-requests.py <dir> --set rate-probe`: `tt`, 27 C, all five supplies 1.8 V,
  `tran 20p 100n`, `timeout_s` 3480, 9 measurements (supply-current averages 20-100 ns and the
  four `ring_bit*` levels at 100 ns), all bounded by the 100 ns stop
  (`test_rate_probe_measurements_within_stop_time`). `netlist.cir` (15 MB) is not committed; its
  sha256 is in `plan.json` and it is regenerable. Same netlist as the 20261030 probe.
- `klt sim ... --backend batch --submit-only`, `--job-status` polling, `--attach`. Client
  `klt 0.8.1.dev1269+g5f8a6175c492`; PDK stamp (client side) `open_pdks f6eeac7dad08...`
  (two installs found; `~/.ciel` won).
- Job `klt-sim-c290c482f586`, launched 2026-11-03T06:43:12Z, spot `m7i.4xlarge` us-east-1a
  (the 20261030 probe ran on `c7i.8xlarge`), job `elapsed_seconds` 3488, corner `runtime_s`
  3480.667, exit 4. Memory: not reported.

## Result

| | 20261030 probe | 20261103 probe (this) |
|---|---|---|
| `.tran` stop | 970 ns | **100 ns** |
| outcome | `timeout` at 3480 s | `timeout` at 3480 s |
| measurements | 0 of 127 | 0 of 9 |
| `ngspice.log` | ends at `Using SPARSE 1.3 ...` | ends at `Using SPARSE 1.3 ...` |

`ngspice.log` has no progress lines, so **simulated time reached is unknown**: the run was
killed with nothing recorded. The log is identical in shape to the 970 ns probe's.

## Derived rate and extrapolation

None is derivable. The only hard bound is a *lower* bound on cost: > 3480 s of wall time for
<= 100 ns of simulated time, i.e. **> 34.8 s per simulated ns** (the simulated time reached may
be well below 100 ns, so the true cost per ns is unknown and could be much higher). Extrapolating
that bound to the 7.87 us full program gives **> 274 000 s (> 76 h) -- a lower bound, not an
estimate, and flagged as an extrapolation**; it also assumes linear scaling, whereas start-up
(DC operating point / initial timestep) cost may dominate the first 100 ns. The current
`GRID_TIMEOUT_S` (21600 s) is far below that bound.

## Consequences for #307

- A faithful transistor-level whole-block transient (about 25 000 extracted devices) does not
  complete at 100 ns inside an hour on the fleet's current instance classes. A reduced-work
  strategy (the sibling decision issue) is required before the 12-point grid can be attempted;
  further blind probe lengths would not help unless the log shows progress.
- Not distinguished by this evidence: slow DC start-up versus slow time-stepping (timestep
  collapse in the rings). That needs progress output that `klt sim` does not currently expose
  for a killed run (tool friction, reported upstream generically).
- Runner/client discrepancies from the 20261030 record persist (`engine_build_comparison`
  runner 46 vs local; `pdk_stamp_comparison` `not_comparable`); not investigated here.
