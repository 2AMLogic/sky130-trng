# Batch startup probe, 2026-10-17/18 -- NOT EXECUTED (capacity refusal)

Client: klt 0.7.1.dev1792+gb1856063523f. Runner image/version: not reached.

| attempt | request | result |
|---|---|---|
| 1 (`submit-attempt-1-timeout14400.log`) | `options.timeout_s` 14400 | klt warned the bound exceeds the fleet 3600 s whole-job ceiling (timeout_s must be <= 3480); launch refused: 8 instances already running, `BATCH_MAX_CONCURRENT_INSTANCES=8`. |
| 2 (`submit.log`) | `timeout_s` 3480, `--wait-for-capacity 600` | 6 launch attempts over ~10 min, same capacity refusal. |

No unit executed, so there is no wall-clock rate, no memory figure, and no
runner-version evidence. `batch_runner_version_mismatch` was neither seen nor
cleared. Per host rules the grid was not run locally and not retried in a loop.
The 12-point matrix, #18 AC3 and the scorecard are unchanged (UNMET).
