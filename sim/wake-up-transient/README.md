# wake-up-transient

Issue #216. Analog wake-up transient of the committed pre-layout
`design/ro_array_core.spice` against DR-0004's 1024-sample start-up window (20.48 ms at
DR-0003's 50 kbps). Everything here is **simulation-derived and provisional until silicon**.

**Status: all acceptance items run** (2026-11-05, klt 0.9.1 client, klt 0.9.0 batch runner, one job per unit via
`batch.max_units_per_job = 1`): the 54-unit deterministic envelope (records `20261105-101845..101853-49aec1a`, all
54 units `pass`) and the transistor noisy leg (3 PVT points x 32 seeds + a 4-seed noise-off control at ss / -40 C /
1.62 V; records `20261105-101907/101909/101912-49aec1a`, all 100 units `pass`) ran on the Spot batch fleet through
`klt sim` corners / `monte_carlo`; the job ids are in each record's `Batch jobs` line. The margin statement is
re-emitted as `20261105-102351-49aec1a`. Earlier records are kept unedited as append-only history.

| File | Role |
|---|---|
| `testbench/tb_wakeup_array.spice`, `tb_wakeup_array_ramp.spice` | deterministic cold-start decks (enable-gated wake / 1 us supply ramp without gating) |
| `testbench/tb_wakeup_raw_bits.spice` | noisy deck: four rings held stopped until the enable, trnoise per stage, committed XOR tree + sampler, first 24 raw bits |
| `make-requests.py` | writes the `klt sim` requests; `--probe` writes one single-unit request per leg |
| `wakeup.py` | reduction (`--emit-det`, `--emit-noisy`, `--emit-margin`) and replay (`--check RECORD`) |
| `restart_matrix.py` | issue #267: restart-matrix reduction (`reduce MATRIX`), behavioural known-answer record (`--emit-record`), replay (`--check RECORD`) |
| `records/<id>.{md,json}` | append-only records: `det` (settling), `noisy` (first-window raw bits), `margin` (behavioural), `restart-matrix` (behavioural known-answer, #267) |
| `runs/<id>/restart-matrix-values.json.gz` | full per-row / per-column / per-restart values and every seed of a `restart-matrix` record |
| `corners/<id>/` | exactly what was submitted and the raw `klt sim` responses |
| `../tests/test_wakeup_reduction.py` | unit tests on synthetic edge trains |
| `../tests/test_restart_matrix.py` | restart-matrix known-answer fixtures, boundary/fail-closed tests, one-point record replay |

## What was and was not run

Run (local single-unit debug probes, `--backend local`, ngspice 46):

- `20261009-093152-e57ad27` det, ss / -40 C / 1.62 V, enable-gated and supply-ramp: all four rings oscillate; within 1 % of
  final period from the first edge: **2.61 ns** after the enable, **3.99 ns** after the end of a 1 us ramp.
- `20261009-093215-e57ad27` noisy, ss / -40 C / 1.62 V, **one** noise seed only (24 samples). No bias or min-entropy
  comparison is possible from one seed; it only shows the deck works (rings quiet before enable, oscillating after).
- `20261009-093500-e57ad27` margin (behavioural, phase-diffusion model of `sim/raw-bit-volume-campaign/`
  started from the stopped state, 1024 wake-ups per corner per arm, deterministic vs stationary start, DR-0004
  start-up test run on every wake-up) at all 18 calibrated points (tt/ss/ff x the base and hot PVT points).

NOT run: the 54-unit deterministic envelope (tt/ss/ff x -40/27/125 C x 1.62/1.8/1.98 V, both modes) and the
transistor noisy leg (32 seeds x 3 PVT points + a noise-off control) - the "first-window vs steady-state bias
from transistor seeds" acceptance item is therefore **not met** here. Cause: every `klt sim` submit to the batch
fleet failed - first with `8 instance(s) already running + 1 requested exceeds BATCH_MAX_CONCURRENT_INSTANCES=8`
(`batch.capacity_wait_s` was not honoured), and, once an instance was obtained, with
`batch_runner_version_mismatch` (runner klt 0.5.0, client 0.7.0; klt 0.5.0 has no `batch` backend, so no client matches).
Per the worker rules the grid was not run locally. Re-run when the fleet works:

```bash
python3 sim/wake-up-transient/make-requests.py REQDIR
# per REQDIR/<name>/:  KLT_SIM_BACKEND=batch klt sim request.json -o out --format json > resp.json
python3 sim/wake-up-transient/wakeup.py --emit-det REQDIR && python3 sim/wake-up-transient/wakeup.py --emit-noisy REQDIR
python3 sim/wake-up-transient/wakeup.py --emit-margin     # new record; earlier ones are never edited
python3 sim/wake-up-transient/wakeup.py --check sim/wake-up-transient/records/<id>.json
```

**Update 2026-11-05 (batch probe, issue #216).** `make-requests.py` now sets `batch.max_units_per_job = 1` and
`batch.max_concurrent_jobs = 4` (the `remote.hosts` field is implemented for local backends only), so every job's bound
is klt's 120 s per-job overhead plus one unit's `timeout_s` (det 3000 s -> 3120 s, noisy 3400 s -> 3520 s), under the fleet's 3600 s ceiling; the generator
refuses any request above it. One-unit probe (`det-en-ss-probe`, ss / -40 C / 1.62 V, `KLT_SIM_BACKEND=batch`) on the
klt 0.9.0 runner (AMI `ami-04591566329422a44`): job `klt-sim-e7e4fa4569fe` started, finished in 24 s, `runner_compatibility: match`,
unit `pass`, and `environment.remote` is populated in the report. The 54-unit deterministic envelope and the transistor
noisy leg are **still unrun**; the probe is not a margin result and no record was emitted from it.

## Margin statement vs DR-0004's 1024-sample start-up window

(Full text and per-corner table: `records/20261105-102351-49aec1a.md`; supersedes the 2026-10-09 record
`20261009-093500-e57ad27`, which rested on one probed corner.)

- **Analog settling** is nanoseconds at **every** one of the 9 (T, Vdd) x 3 process corners, both modes (54/54
  units settled, all rings oscillating): worst enable-gated settling (every ring within 1 % of its final period)
  **8.49 ns** at ss / 125 C / 1.62 V (`20261105-101851-49aec1a`), worst ramp-wake **4.37 ns**
  after the ramp ends. That is about 4 x 10^-4 of one 20 us sample interval, so the rings oscillate at steady
  frequency before the first 50 kbps sample, with a window margin of ~2.4 x 10^6. The earlier expectation that
  cold/SS is slowest is not what the data shows: ss settles last, but at hot / low supply, not at cold.
- **Statistical stationarity** is the binding effect: after the enable every ring restarts from the same stopped
  state, so the raw bit is not stationary across wake-ups until jitter has spread the phases. Worst case over the
  18 calibrated corners, samples to reach a worst-case bias bound B: B <= 0.2071 (H >= 0.5 bit) in 12; 2^-10 in 47;
  2^-20 in 92; **2^-40 in 181 (ss / -40 C / 1.62 V)**. The 1024-sample window therefore covers mixing to 2^-40 with
  a margin of **5.7x** (21.8x to 2^-10). The DR-0004 start-up test passed on all simulated wake-ups in both arms
  and cannot detect this non-stationarity (it counts those samples as healthy). Mixing time scales as 1/sigma_1^2, so
  a 2x error in the injected-noise-derived jitter changes the 5.7x to 1.4x - still adequate, but thin.
- **Transistor cross-check** (32 injected-trnoise seeds from the same stopped state, Ts = 100 ns compressed, noise-off
  control bit-identical across seeds at ss / -40 C / 1.62 V): rings quiet before the enable and oscillating rail to
  rail at the end for all 96 seeds; the raw-bit disagreement across seeds is far from 0 from the first window, i.e. the
  rings decorrelate within a few samples, as the model predicts. The behavioural model's 99 % band contains 15/15 rows at ss / -40 C / 1.62 V, 15/15 at tt / 27 C /
  1.8 V and **14/15 at ff / -40 C / 1.98 V**: there the raw-bit disagreement in samples 0..7 is 0.362 vs a band of
  0.008..0.346, i.e. the transistor bits decorrelate faster than the model at the very start, which is the
  conservative direction for the 2^-40 mixing time. One row outside a 99 % band in 45 is not on its own evidence of a
  model defect, but it is recorded here, not dropped. The compressed-Ts transistor leg checks the mixing *trend*, not
  the 2^-40 tail, which only the model reaches.
- **Conclusion**: adequate under the model, transistor evidence consistent; **no decision-record change is
  indicated**, so none was filed. The raw path is never gated, so raw-path consumers should discard roughly the first
  50 to 200 samples after a wake-up. Provisional until silicon.
- **Replay note**: `wakeup.py --check` on the 2026-10-09 margin record now reports `DIFFERS`. Its calibration takes
  periods from the det record at each PVT point, and that record used a combining-record fallback because no det
  record existed at most points; the new det records now exist. The old record is left unedited; the new one replays
  `MATCHES`.

## Restart-matrix reduction (issue #267)

`restart_matrix.py` is the analysis path for the silicon restart dataset of
`spec/silicon-characterization-plan.md` C5, exercised before silicon on behavioural matrices.
**Simulation-derived and provisional until silicon.**

```bash
python3 sim/wake-up-transient/restart_matrix.py reduce CAPTURE.txt[.gz] [--json OUT]   # exit 0 PASS, 1 FAIL, 2 refused
python3 sim/wake-up-transient/restart_matrix.py --emit-record                           # new record; ~3 min single process
python3 sim/wake-up-transient/restart_matrix.py --check sim/wake-up-transient/records/<id>.json [--entry ss:-40C:1.62V:deterministic]
```

- **Input**: R x N binary matrix, one restart per line of `0`/`1`, sample 0 = first sample after the restart.
  R >= 1000 and N >= 2048 (a 1024-sample first window plus an equal 1024-sample baseline; the 2048 length is an
  analysis choice above the plan's 1000+ minimum, not a new silicon requirement). Ragged, non-binary, empty or
  undersized input is refused with the offending row/column named.
- **Reduction**: H_MCV of every row and every column with `raw-bit-entropy.py:mcv_estimate`'s 99 % upper-confidence
  convention; pooled first-window vs baseline one-fraction, two-sided two-proportion z test at alpha = 0.01 ("not
  distinguishable" = p >= 0.01; pooling assumes independent samples, so it is a model diagnostic, not silicon
  confidence evidence); `digital.model.health.HealthMonitor` from reset on each row's first 1024 samples (pass,
  first trip index, alarm class).
- **Matrix sanity verdict**: PASS only if every row and column has H_MCV >= 0.5 and every start-up test passes.
  This verdict uses the DR-0004 0.5-bit floor; C5's silicon criterion (restart-matrix min-entropy >= the C1 value
  within CI) is a separate comparison for which the reducer supplies the row/column H_MCV minima but which it does
  not grade, and a silicon capture needs >= 2048 samples per restart for this reducer.
- **Known answers** (`sim/tests/test_restart_matrix.py`, model-independent): a seeded IID matrix passes; the same
  matrix with one deterministic column fails the column rule naming exactly that index.
- **Behavioural record** `20261010-231748-f259cb7`: 1000 x 2048 at all 18 calibrated points (tt/ss/ff x
  `behavioral_raw_bit.PVT_SETS["all"]`), deterministic-start and stationary-start arms separately, one derived seed
  per restart, calibration provenance per entry. Stationary arm: PASS at 18/18 points. Deterministic arm: PASS at
  7/18; the other 11 fail the column rule at sample indices 0..8 (rings restarted from a common phase have not yet
  diffused), which the DR-0004 start-up test passes on every restart (18000/18000 in each arm) and is not designed
  to see. No point shows a first-window vs baseline difference at alpha = 0.01.
- **Model boundary**: the phase-diffusion model starts the rings from phase zero after their measured start delays
  (deterministic arm) or uniform random phases (stationary arm) and advances them with independent white period
  jitter calibrated from committed records. It does not model physical supply-ramp dynamics, enable settling,
  sampler aperture/metastability, inter-ring coupling, 1/f noise or silicon process behaviour. The record validates
  the matrix plumbing and diagnostic rules only: it is not transistor-level wake-up verification, not evidence of
  physical C5 compliance and not an SP 800-90B validation. Analog wake-up/settling stays with #216.
