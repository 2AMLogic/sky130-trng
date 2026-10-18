# Batch startup probe, 2026-10-18 -- EXECUTED on the fleet, deck REJECTED by ngspice at parse

Client: klt 0.7.1.dev1801+g37e8698a1c78. Runner: engine ngspice 46, PDK sky130A
open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7 (`/opt/pdk` on the runner). The runner
version check passed: no `batch_runner_version_mismatch`, no capacity refusal.

| attempt | request | result |
|---|---|---|
| 1 (`submit-attempt-1.log`, `attach-1.log`) | `startup-probe-batch`, `timeout_s` 3480, `--wait-for-capacity 600` | launched immediately as job `klt-sim-d9572919cd95` (launched 2026-10-18T00:25:43Z). The submitting client was killed by the 10 min background limit at 952 s; the job was re-attached (`--attach`, not a second submit) and finished `failed`, status `error`, `runtime=2844.399s`. |

Only one submit attempt was used this pass.

## What the probe established

- Wall-clock: the unit ran 2844 s of the 3480 s bound **before ngspice stopped**. ngspice
  produced no analysis banner and no measurement, so this is the time to parse/flatten the
  ~25 000-transistor, 129 716-line deck, not a simulation rate. It matches the local probe
  (RSS growing to 17 GB with the log never leaving its header). **No simulated-time/wall-time
  rate exists**; memory was not reported by the runner.
- Failure (`out1/<corner>/ngspice.log`): `Error on line 803 or its substitute:
  m.xw.x$2.msky130_fd_pr__nfet_01v8 ... could not find a valid modelname`, then
  `Simulation interrupted due to error!`. Line 803 expands the first device instance
  `X$2` (`sky130_fd_pr__nfet_01v8 L=0.15 W=0.36`, 1 760 such devices in the deck). Root cause is
  NOT established: the PDK is not installed on this host, so a model-bin lookup at W=0.36 could
  not be reproduced locally. A 504-character net name on a plain MOS card parses fine in a local
  ngspice, so the long merged `VGND|g_vss_m1|...` net names are not the cause by themselves.
- All 127 requested measurements are `error` (`produced no value`); klt's report carries only
  those per-measurement diagnostics and does not surface the ngspice parse error. Nothing
  about the circuit's behaviour (start-up, rings, bus reads) was observed.

## Consequences

- The probe gate is **not** passed, so the 12-point grid was not submitted and
  `GRID_TIMEOUT_S`/`poll_timeout_s` were not re-sized (no measured rate to size them from;
  parse alone consumes 2844 s of the 3480 s per-unit ceiling, so the full 7.87 us program
  cannot fit in one unit at transistor level regardless).
- The next step is a netlist/model-binning fix in the flat-netlist generator (outside this
  issue's Affected Files), then a fresh probe. The grid, record, per-supply currents and the
  #18 scorecard are unchanged; AC3 stays UNMET.
- Per host rules nothing was run locally beyond a tiny ngspice syntax check (no PDK).
