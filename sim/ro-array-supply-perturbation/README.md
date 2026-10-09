# ro-array-supply-perturbation

Issue #200. Transistor-level supply-ripple and injection-lock robustness of the
committed pre-layout `design/ro_array_core.spice`. Everything here is
**simulation-derived and provisional until silicon**; it is deterministic (no injected
noise), so it is a robustness measurement, not an entropy measurement. A post-layout
re-run is the follow-up once #184 lands.

| File | Role |
|---|---|
| `testbench/tb_ro_array_supply_perturbation.spice` | circuit-body template: the array, five behavioural supply rails (`vdd`, `vddr1..4`) that read DC "knob" sources for offset / ripple amplitude / ripple frequency, and the negative-control current injector |
| `make-requests.py` | writes the `klt sim` batch requests (`OUTDIR/<corner>-<group>-<n>/`); one request carries a whole zipped ripple ladder |
| `ripple.py` | reduction: edge-time analysis, lock detector, DR-0003 criteria, tolerance statement; `--emit-record REQDIR`, `--check RECORD` (replay from the committed raw responses) |
| `records/<id>.{md,json}` | append-only record per PVT point (one row per unit: corner, ripple amplitude, ripple frequency, verdict) |
| `corners/<id>/` | per chunk: `*.klt-sim.json.gz` (raw batch response, job id inside), `*.request.json` and `*.netlist.cir` (exactly what was submitted), `*.plan.json` |
| `../tests/test_ripple_reduction.py` | unit tests on synthetic edge trains, including a train that is locked by construction |

```bash
python3 sim/ro-array-supply-perturbation/make-requests.py REQDIR --groups a10,a50,a100,a200,q
klt sim REQDIR/<corner>-<group>-<n>/request.json -o REQDIR/<d>/out --format json > REQDIR/<d>/resp.json   # KLT_SIM_BACKEND=batch
python3 sim/ro-array-supply-perturbation/ripple.py --emit-record REQDIR
python3 sim/ro-array-supply-perturbation/ripple.py --check sim/ro-array-supply-perturbation/records/<id>.json
python3 sim/tests/test_ripple_reduction.py
```

## What was run

Two PVT points, both -40 C, tt not run: **ss / 1.62 V** (the DR-0002 entropy-binding corner)
and **ff / 1.98 V** (the fast corner, which also binds DR-0003's combining ceiling). Ring
frequencies come from the committed `ro-array-core-combining` records at the same point
(ss 184.3 / 191.7 / 199.2 / 207.0 MHz; ff 626 / 661 / 696 / 733 MHz).

Common-mode sinusoidal ripple on `vdd` and `vddr1..4` at 10, 50, 100 and 200 mV pk, at: each ring's own frequency,
each ring +0.5 %, 0.9 x f1, 1.1 x f4, the ladder mean over 2 and over 3 (sub-harmonics),
2 x the mean, and 10 MHz. Ripple far below the ring frequency (including the 50 kbps sample
rate) is not simulated cycle by cycle (a 20 us period is ~4000 ring periods per cycle): the
ring follows the instantaneous supply, so the supply is stepped to the sine's extremes and
Gauss-Chebyshev nodes (`dv = +-A, +-0.866 A`) for A = 10 and 50 mV. The 10 MHz transient
row agrees with it on period modulation (ss 3.2 % pk at 10 mV vs 3.0 % quasi-static).

Per row: per-ring period modulation and mean-period shift, Q ratio, ring-vs-tone and
ring-vs-ring lock state, DR-0005 closeness, combining-node bias (`<v(xo)>/vnom`) and its
shift from the clean run. Rows carry corner, amplitude, frequency and a unit id; there is no seed (deterministic).

## Criteria (DR-0003's margins, not new ones)

- **LOCK**: no ring locked to the tone (slip < 0.1 ring cycle across the 39-period window while
  the clean ring would have slipped more) and no new ring-pair lock.
- **Q**: `Q_array` ratio >= 1/1.036. DR-0003 sec. 3 sizes `N = 4` at 1.036 x `M*Q_H0`; `Q ~ T0^-3`
  (DR-0002) so this is the T0 term only: `sigma_1` is not re-measured under ripple.
- **BIAS**: `bias_xo` inside DR-0003's 0.31-0.53 band. The ff clean baseline in this window is
  0.525, i.e. at the band's upper edge, so the ff verdict under this criterion is dominated by
  band proximity; the records therefore print every tolerance both with and without the bias band.

## Findings (see the two records for the tables)

| | ss / 1.62 V (binding) | ff / 1.98 V |
|---|---|---|
| RF ripple tolerance (10 MHz through 2x ring frequency), LOCK + Q + BIAS | **>= 10 mV pk, < 50 mV pk** | **no tolerance found at 10 mV** (bias leaves the band) |
| same, LOCK + Q only | >= 10 mV, < 50 mV | >= 10 mV, < 50 mV |
| first lock | 50 mV: all four rings dragged 61-89 % of the way to a tone 0.5 % off (flagged LOCKED); 100 mV also 1:2 (tone at 2 x f); 200 mV: neighbouring ring locked from 4 % away and a new ring-1/ring-2 pair lock | 50 mV: ring 1 at +0.5 % (pull 1.3); 100 mV ring 4; 200 mV rings 3, 4 and 1:2 |
| ripple below the ring frequency, cycle-averaged Q | passes to 50 mV (convexity of `T^-3`) | passes to 50 mV |
| ripple slower than the sample interval, or static droop (trough Q) | **no tolerance found at 10 mV** | **no tolerance found at 10 mV** |
| static droop at which Q reaches 1/1.036 | **~3.9 mV** | ~7.4 mV |

The headline implication, filed as a separate decision-record request (#208) and **not**
acted on here: the DR-0003 `Q` margin corresponds to about 4 mV of supply droop at the
binding corner. No spec value was relaxed.

## Negative control

A sinusoidal current (10 and 50 uA pk) forced into ring 2's internal node `xr2.n2` at ring 2's
frequency x {1.00, 1.02, 1.20}. The 1.02 and 1.20 rows are LOCKED in both corners (clean-ring slip 0.78 and 3.9
cycles, observed slip ~0), so the detector fires on a deliberate lock. The at-frequency row
is COINCIDENT, not LOCKED: the clean ring is already inside the detector's resolution of the tone.
(An earlier probe of a 0.3 V *supply-local* tone at a ring's own frequency did not lock the ring; a
supply tone is a weak injector, which is why the control is a current into a ring node.)

## Limits and caveats

- **Resolution**: 40 edges per ring give ~0.25 % detuning resolution. Tones placed on a ring's own
  frequency are reported UNRESOLVED (lock vs coincidence), not passed; the +0.5 % rows bound the lock range.
  A "pass" at 10 mV is therefore shown for tones >= 0.5 % off a ring frequency.
- **Edge-time floor**: the clean run reads 0.05-0.4 % pk period modulation (timestep interpolation).
- Pre-layout, ideal sources: no supply impedance or substrate (DR-0006's first-named coupling).
  Ripple is applied in common to all five rails; per-ring uncorrelated ripple was not run.
- Amplitudes tested: 10, 50, 100, 200 mV only; the tolerance is a bracket, not a threshold.
- The bias window is 60 ns to stop (ss 460 ns, ff 300 ns). Tone rows whose edge window holds < 2 ripple cycles
  (10 MHz at ff) are excluded from the Q criterion; the quasi-static family covers that regime.
- Method history, stated so it is not mistaken for selection: a first set of requests (shorter bias windows,
  ripple-local supply control) was explored and **not recorded**; the committed set is the second, with the
  current-injection control and longer windows. One request (ff 50 mV, first 8 units) never returned from the
  batch fleet after ~2 h and was re-submitted as two 4-unit requests (`ff-a50-1h0`, `ff-a50-1h1`).

## Tool friction (filed per the friction protocol)

- `2AMLogic/klayout-tools#2867`: `corners.supply_v` (`alter`) cannot sweep a time-varying source's parameters;
  `alter` of a `.param` is a silent no-op. Worked around with behavioural rails reading DC knob sources.
- `2AMLogic/klayout-tools#2868`: no way to get a threshold-crossing series from a transient (160 `.meas` cards per unit).
- `2AMLogic/klayout-tools#2869`: concurrent multi-request batch submissions mostly refused with `batch_no_capacity`.
- `sim/bin/corner-run.py` was not used: it substitutes a fixed set of placeholders and runs one corner at a time
  locally, and has no way to sweep ripple parameters. The campaign is `klt sim` batch requests, like #184/#188/#197.
