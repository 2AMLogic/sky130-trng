# ro-ring-timestep-convergence

Evidence that the ro_ring5 transient-noise jitter estimator is (or is not) sensitive to the transient
max timestep. Simulation-derived and provisional until silicon. Single process corner on purpose
(tt / 27 C / 1.8 V, seed 1): a numerical-convergence claim, not a PVT claim.

There is no deck of its own. The family is six points over the unmodified
`sim/ro-ring-jitter-accumulation/testbench/tb_ro_ring5_jitter.spice`:

| # | `@@TMAX@@` | `@@NA@@` (trnoise rms) | role |
|---|---|---|---|
| 0-3 | 5p, 10p, 20p, 40p | 2.0e-3 (default) | timestep ladder |
| 4-5 | 5p, 20p | 0 | solver-manufactured jitter floor |

| File | Role |
|---|---|
| `harness/run-convergence.py` | owns the point list; prints or runs the exact `sim/bin/corner-run.py` command per point |
| `records/<id>.{md,json}`, `corners/<id>/` | append-only evidence; never edit |

```bash
python3 sim/ro-ring-timestep-convergence/harness/run-convergence.py            # list the six points
python3 sim/ro-ring-timestep-convergence/harness/run-convergence.py --point 0  # print one command
python3 sim/ro-ring-timestep-convergence/harness/run-convergence.py --point 0 --run   # one local ngspice
```

There is intentionally no run-all; submit the grid as `klt sim` requests (batch fleet), not a local loop.
`--run` writes a new record under `records/`/`corners/`, as any `corner-run.py` call does.

PDK pin: `sim/pdk.json` `open_pdks_commit` (`c6d73a35f524070e85faff4a6a9eef49553ebc2b`).

## Caveat on the committed records

The committed records were produced with ngspice-46 (`tools.ngspice`) from a dirty tree on
`feature/issue-10` (commit `54f5715` is not in this repository). Re-running point 0 and point 4 with
ngspice-42 gives the same swing (within 1e-5) but a different cycle count and sigma_1 (see #348); the
sigma_N figures are ngspice-version-sensitive and should be compared only against runs from the same
ngspice build.

Re-run on ngspice-46 (2026-10-23, `706501c`, tt / 27 C / 1.8 V, seed 1; relative delta vs committed):

| point | `tbar` | `sigma_1` | `swing_frac` | `tk` |
|---|---|---|---|---|
| 4 (tmax=5p, `noise_amp=0`) | 0 | 0 | 0 | 0 (bit-identical) |
| 0 (tmax=5p, default noise) | 1.2e-6 | 7.7e-2 | 1.5e-4 | 6.4e-5 |

The deterministic control reproduces exactly. In the noisy point, `tbar`, `swing_frac` and `tk`
reproduce within 1e-3, but `sigma_1` does not (3.098e-12 vs committed 3.355e-12) even on the same
ngspice major version, so the committed `sigma_1` is not bit-reproducible from this tree. The
cause is not established. Treat the committed `sigma_1` values as indicative of the noise
mechanism, not as a reproducible number.
