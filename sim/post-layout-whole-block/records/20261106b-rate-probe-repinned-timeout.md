# 20261106b -- whole-block 100 ns rate probe on the re-pinned netlist: TIMEOUT at 3480 s (issue #449)

**Claim**: on the re-pinned netlist (`flat_whole_netlist_sha256` `965f1e6c...`) the 100 ns probe did
**not** finish within the 3480 s unit ceiling. The 20261030 and 20261103 infeasible verdicts are
**confirmed on the fixed netlist**. Provisional, simulation-side. #307 stays unmet. This record does
not amend DR-0017 or `GRID_TIMEOUT_S`.

## What was run (one unit, `klt sim`, batch backend, no local run)

- Request: `runs/20261106b-rate-probe-repinned-retry/corners/rate-probe-batch/request.json`, generated
  unchanged with `make-requests.py <dir> --set rate-probe` (`tt`, 27 C, all five supplies 1.8 V,
  `tran 20p 100n`, `timeout_s` 3480). `plan.json` names `965f1e6c29d771d5b8e18a3ea66ccabf93f0a5eb14c3f0c23810f39ae1052c36`.
- Submit: `--submit-only --wait-for-capacity 600`; accepted first time.
  Client `klt 0.9.2.dev111+g978f7464fae1`; client-side PDK `open_pdks f6eeac7dad08...` (`~/.ciel`).
- Job `klt-sim-c594a1d79240`, launched 2026-11-06T19:49:45Z, spot `c7i.8xlarge` us-east-1f.
  Terminal status `failed` ("job command exited 4"), `elapsed_seconds` 3489; corner `runtime=3480.66s`,
  diagnostic `timeout - ngspice did not complete within 3480s, killed`.

## Result

| | 20261103 probe | 20261106 probe | 20261106b probe (this) |
|---|---|---|---|
| netlist | pre-repin | re-pinned, `965f1e6c...` | re-pinned, `965f1e6c...` |
| outcome | `timeout` 3480 s | `interrupted` 3279 s | **`timeout` 3480 s** |
| measurements | 0 of 9 | none | 0 of 9 |
| `ngspice.log` | no progress lines | not available | load + initial solution only |

- **Did the 100 ns probe finish? No.** It hit the unit timeout.
- ngspice **did** load the regenerated netlist and solve the initial operating point (supplies at 1.8 V,
  `vvdd#branch` about -0.70 uA); this removes the earlier "never confirmed to load" doubt. It then
  produced no transient progress output before the kill.
- **No rate and no 7.87 us extrapolation can be given.** Simulated time reached is unknown (the log has
  no progress lines), so even a bound would need an assumption. What can be said: the unit did not complete its 100 ns within 3480 s of wall-clock on a `c7i.8xlarge`.

## Consequences

- The infeasible verdict for the full-block analog run now stands on the fixed netlist, which feeds
  the negative-result path already stated in the README for DR-0017 option (b). #431 (gate-level
  co-simulation) remains the open route; nothing here relaxes the spec.
- Prior records (20261030, 20261103, 20261105, 20261106) are untouched.
