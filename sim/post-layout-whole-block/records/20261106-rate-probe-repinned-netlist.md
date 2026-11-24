# 20261106 -- whole-block 100 ns rate probe on the re-pinned netlist: interrupted by spot reclamation; no verdict (issue #441)

**Claim**: the one batch job on the fixed netlist did **not** produce a result. It neither finished nor
hit the unit timeout; the spot instance was reclaimed at 3279 s. The 20261030 and 20261103 infeasible
verdicts are therefore **still unconfirmed** and also **not refuted** on the fixed netlist. Provisional,
simulation-side. #307 stays unmet, and DR-0017's premise is neither confirmed nor undercut by this run.

## What was run (one unit, `klt sim`, batch backend, no local run, no retry)

- Request: `runs/20261106-rate-probe-repinned/corners/rate-probe-batch/request.json`, generated unchanged
  with `make-requests.py <dir> --set rate-probe` (`tt`, 27 C, all five supplies 1.8 V, `tran 20p 100n`,
  `timeout_s` 3480). `plan.json` names `flat_whole_netlist_sha256`
  `965f1e6c29d771d5b8e18a3ea66ccabf93f0a5eb14c3f0c23810f39ae1052c36` (the re-pinned netlist from
  `records/20261105-body-rename-repin.md`); the inlined `netlist.cir` (4 MB) is not committed.
- Submit: `--submit-only --wait-for-capacity 600`; accepted first time, no `batch_no_capacity`.
  Client `klt 0.9.2.dev103+g9f4cec35997a`; client-side PDK `open_pdks f6eeac7dad08...` (two installs found,
  `~/.ciel` won, same as the earlier probes).
- Job `klt-sim-3bdf8c54a5a9`, launched 2026-11-06T18:23:47Z, spot `c7i.8xlarge` us-east-1a.
  Final status: `interrupted`, `elapsed_seconds` 3279, "spot reclamation notice received; job did not
  complete -- re-run it". `--attach` reported `interrupted` and returned no corner directory.

## Result

| | 20261103 probe | 20261106 probe (this) |
|---|---|---|
| netlist | pre-repin (94 of 123 ports unconnected) | re-pinned, `965f1e6c...` |
| outcome | `timeout` at 3480 s | **`interrupted`** at 3279 s (spot reclaim) |
| measurements | 0 of 9 | none (no output collected) |
| `ngspice.log` | no progress lines | not available |

- **Did the 100 ns probe finish? No -- and it did not time out either.** No rate can be derived.
- Not established: whether ngspice loaded the regenerated netlist (the repin record said this was never
  run); no log came back. This must not be read as either a load failure or a rate verdict.
- No rate bound or 7.87 us extrapolation is given: simulated time reached is unknown, so even a lower
  bound would rest on an assumption about start-up that this run cannot support.

## Consequences

- #431 still has no evidence either way from the full block. A re-run is needed (new dated run dir;
  the spot interruption is a fleet event, not a property of the circuit). Re-running is left to a
  follow-up issue; this pass was one bounded attempt.
- Prior records (20261030, 20261103, 20261105) are untouched.
