# sim

The sky130 ngspice simulation harness and the evidence it produces.

Issue #9 bootstrapped it: the PDK pin, the PVT corner runner, and one
mechanism-check record confirming the sky130 device noise model this whole
entropy source depends on is actually active in the corner decks as
installed. Issue #10 then ran the jitter-accumulation characterization
campaign that bootstrap unblocked (`design/README.md`'s "Provisional, not
sized" table -- per-stage gain, ring jitter accumulation, ring swing, and
the array sizing law that turns them into an array size `N`). The slugs
below are that campaign's evidence.

| Slug | Claim under test | Landed by |
|---|---|---|
| `ro-stage-noise-mechanism-check/` | is the sky130 flicker/thermal noise mechanism actually active in the corner decks as installed? (go/no-go) | #9 |
| `ro-stage-small-signal-gain/` | open-loop small-signal gain of `ro_stage` at its own trip point | #10 |
| `ro-ring-timestep-convergence/` | does the ring jitter estimator depend on the transient max timestep, and what does it read with *zero* injected noise? | #10 |
| `ro-ring-jitter-accumulation/` | per-ring `T_0`, `sigma_1..sigma_8` and ring swing over the PVT grid, for `ro_ring5` and `ro_ring11` | #10 |
| `ro-array-sizing/` | reduction of the above to `Q`, the entropy-binding corner, and the sized `N` | #10 |

Issue #13 then rebuilt `ro_array_core.sch` at a measured operating point
(`spec/decision-records/DR-0003-sky130-trng-operating-point.md`), adding:

| Slug | Claim under test | Landed by |
|---|---|---|
| `xor-combining-bandwidth/` | the static-CMOS `xor2` combining gate's own minimum resolvable pulse width `w_90`, the figure that sets a hardware ceiling on array size `N` | #13 |
| `ro-ring5-swing-and-current/` | five-stage ring swing and per-ring supply current, deterministically (no injected noise), under the array's own output-buffer load | #13 |
| `ro-array-core-combining/` | the assembled, committed `ro_array_core.spice` end to end: realized per-ring frequency ladder, combining-node edge retention and DC bias, total array supply current | #13 |
| `ro-array-operating-point/` | reduction crossing the combining-bandwidth ceiling against the entropy sizing law (re-evaluated at the buffer-loaded ring period), producing the chosen `N` and raw-rate operating point | #13 |

Two rules from the root `CLAUDE.md` govern everything under this directory:

- **Verification is the product.** No claim without a testbench, and PVT
  corners on every recorded result.
- **`sim/` results are append-only evidence.** A record is never edited or
  deleted after it is written; a correction mints a new record and names the
  one it supersedes via its `Supersedes` field.

## Quick start

```bash
# 1. install the pinned PDK (see sim/pdk.json for the pin)
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. sanity-check PDK resolution
python3 sim/bin/corner-run.py --print-env

# 3. re-run the mechanism-check testbench (tt/ss/ff, ~a few seconds)
python3 sim/bin/corner-run.py \
  sim/ro-stage-noise-mechanism-check/testbench/tb_ro_stage_noise.spice \
  --slug ro-stage-noise-mechanism-check \
  --claim "<one-line claim this run substantiates>" \
  --corners tt,ss,ff
```

Prerequisites, all machine-level (not vendored here): `ngspice`, `volare` (or
another sky130 install method), `python3` (3.9+, standard library only). No
`xschem` step is needed at simulation time -- see "How this harness differs
from sky130-bandgap's" below.

## How the harness is wired

| Piece | File | Role |
|---|---|---|
| PDK pin | `sim/pdk.json` | open_pdks commit, variant, ngspice library path, the process-corner names the PDK actually ships |
| corner runner | `sim/bin/corner-run.py` | resolves the PDK, renders a deck template per corner, runs ngspice, parses results, mints a record |
| testbench | `sim/<slug>/testbench/*.spice` | deck **templates** (see placeholders below) -- not runnable decks as committed |
| records | `sim/<slug>/records/<record-id>.{md,json}` | one append-only evidence record per run: `.md` (human), `.json` (machine) |
| raw logs | `sim/<slug>/corners/<record-id>/<corner>.log` | the exact deck each corner ran, embedded, plus its raw ngspice stdout/stderr -- committed evidence, exempted from the root `.gitignore`'s `*.log` rule by `!sim/*/corners/**/*.log` |

`<slug>` is a kebab-case directory per distinct claim under test (e.g.
`ro-stage-noise-mechanism-check`) -- one directory per claim, not per run,
matching the sibling `sky130-bandgap` repo's own `sim/<slug>/` convention
(and this repo's pre-existing `.gitignore` rule above, which already
anticipates it).

**PDK resolution order** (matches `design/netlist.py`'s resolver exactly, so
a schematic export and a simulation run against the same checkout always
agree on which PDK install they used): `SKY130_PDK_PATH` env var (absolute
variant-directory path) -> `PDK_ROOT` + `PDK` env vars -> `sim/pdk.local.json`
(machine-local, git-ignored) -> `sim/pdk.json` (committed defaults) ->
`volare path` / built-in search roots (`~/.volare`, `~/.ciel`, ...). The
runner refuses to proceed against an installed PDK that does not match
`sim/pdk.json`'s pinned `open_pdks_commit` unless `--allow-pdk-mismatch` is
passed, in which case the record says so.

**Deck template placeholders**: a testbench file under `sim/<slug>/testbench/`
is a template, not a runnable deck. `corner-run.py` substitutes:

- `@@PDK_LIB@@` -- absolute path to the resolved sky130 ngspice corner
  library (`sim/pdk.json`'s `ngspice_lib`, under the located PDK install).
- `@@CORNER@@` -- the process-corner section name for this run (`tt` /
  `ss` / `ff` / ...).
- `@@RO_RING5@@` -- absolute path to the committed, `netlist.py
  --check`-guarded `design/ro_ring5.spice`, the `.include`-style subcircuit
  library that defines `ro_stage`/`ro_nand2`/`ro_ring5` (see
  `design/README.md` § "Regenerating the netlists"). Overridable via
  `--ro-ring5` for a testbench that wants a different netlist.
- `@@OUT_ONOISE@@` -- a per-(record, corner) scratch path a deck can
  `wrdata` an `onoise_spectrum` trace to. If a testbench writes one, the
  runner reads it back and records a spread check (max/min ratio over the
  swept frequencies) confirming the trace is neither degenerate nor flat.
- `@@TEMP@@` / `@@VDD@@` (`--temp` / `--vdd`, default 27 degC / 1.8 V) --
  the temperature and supply axes. `@@CORNER@@` covers the *process* axis
  only, so one runner invocation is one (temp, vdd) point with the process
  axis bundled across `--corners`. Both are written into every record's
  `pvt` block whether or not the deck references them, so no record can be
  silent about the temperature/supply it ran at.
- `@@SEED@@` (`--seed`) -- for a stochastic (`tran-noise`) deck that writes
  its own `.option seed=`. A deterministic `.noise`/`.tf` deck never
  references it, and `--seed`'s default is a descriptive string, not a
  number, precisely so it can never silently become one.
- `@@TMAX@@` (`--tmax`, default `5p`) -- the max internal transient
  timestep, i.e. a deck writes `.tran @@TMAX@@ <tstop> uic`. This is the
  dominant cost term for a long transient-noise run, so it is a
  substitution rather than a deck literal: that is what makes a deck's
  numerical convergence in the timestep something the harness can
  *measure and record* (see `ro-ring-timestep-convergence/`) instead of
  something a deck asserts.
- `@@NA@@` (`--noise-amp`, default `2.0e-3`) -- the rms amplitude argument
  of a `trnoise()` source. `--noise-amp 0` re-runs the identical deck,
  seed and timestep with the injected noise switched off, so the estimator's
  own **numerical floor** is measurable rather than assumed. A sigma is only
  worth citing to the extent it stands above that floor.

`@@TMAX@@` and `@@NA@@` are recorded in each record's `tran` block.

Any `NAME = VALUE` line an ngspice `print` command writes to stdout (e.g.
`v(a) = 7.681062e-01`, `onoise_total = 3.712448e-03`) is captured generically
as a named measurement and checked for being a finite, parseable number --
this is what backs the "not NaN" bar, for any deck, without the runner
needing to know what a particular deck measures.

### How this harness differs from sky130-bandgap's

This repo's sibling `sky130-bandgap` (referenced in
`spec/porting-plan.md` §3.1) already runs a working ngspice/sky130 PVT
harness against the same PDK pin, and this harness's PDK-resolution order,
`<YYYYMMDD>-<HHMMSS>-<shortsha>` record-id scheme, and append-only
refuse-to-overwrite discipline are adapted from it directly. What differs is
the netlist layout it drives: `sky130-bandgap`'s testbenches are xschem
schematic sheets that its runner netlists through xschem on every invocation,
because that repo has no equivalent of `design/netlist.py`. This repo already
has one -- `design/*.spice` are committed, deterministic, `--check`-guarded
`.include`-style subcircuit libraries (`design/README.md` § "Regenerating the
netlists") -- so `sim/bin/corner-run.py` has no xschem step at all: it takes
an already-authored ngspice deck template, `.include`s the relevant
`design/*.spice` file directly, and drives ngspice.

## The mechanism-check record

`design/xschem/ro_stage.sch` (the starved-inverter delay cell every ring
stage in `design/xschem/` is built from) instantiates
`sky130_fd_pr__nfet_01v8` / `__pfet_01v8`. DR-0001's Consequences section
notes that sky130's BSIM4 model cards for these devices expose the unified
`noia`/`noib`/`noic` flicker-noise parameterization (plus
`tnoia`/`tnoib`/`rnoia`/`rnoib`, `fnoimod`/`tnoimod` enabled) rather than the
legacy `kf`/`af` terms gf180mcu's decks use for the same purpose -- `kf`/`af`
are present in the sky130 model card too, just zeroed (`kf = 0.0`) and
therefore inert. Before any jitter-accumulation characterization work is
worth running on this basis, DR-0001 names a prerequisite "mechanism check":
confirm `.noise`/`TRNOISE` on these devices actually produces a usable noise
signal under the corner decks as installed, rather than a silent zero because
the flicker model this repo's whole entropy-source architecture assumes is
active turns out not to be wired up the way DR-0001 expects.

`sim/ro-stage-noise-mechanism-check/testbench/tb_ro_stage_noise.spice` is
that check. It self-biases a single `ro_stage` instance as an inverting
small-signal amplifier around its own trip voltage (a large feedback resistor from output
back to input holds the DC bias near threshold; a large series resistor
couples in the noise-analysis reference source without disturbing that bias
-- the standard construction for characterizing a CMOS inverter/ring
delay-cell's noise ahead of a full transient jitter run, needed here because
a free-running ring has no small-signal DC operating point of the kind
ngspice's `.noise` analysis requires). It runs an ngspice `.noise` analysis
sweeping 10 Hz - 1 GHz and records `onoise_total` plus the raw
`onoise_spectrum` trace.

The latest run,
`sim/ro-stage-noise-mechanism-check/records/20260825-022446-d58d709.md`, is
**PASS** at all three of `spec/porting-plan.md` §3.1's flagship corners (`tt`, `ss`, `ff`,
nominal 1.8 V / 27 °C): every corner produced a finite, non-zero
`onoise_total` (3.55e-3 - 3.71e-3 V, process-dependent) and an `onoise_spectrum`
trace whose max/min ratio across the sweep is 620x-680x -- far from flat,
consistent with the expected 1/f-dominated-at-low-frequency,
thermal-floor-at-high-frequency shape a flicker-noise mechanism produces
(the spectrum falls from ~2.6e-5 V/sqrt(Hz) at 10 Hz to ~4.0e-8 V/sqrt(Hz) at
1 GHz). That frequency-domain shape is the signature the time-domain
jitter-accumulation characterization campaign depends on: a device with only
white (thermal) noise and no active flicker contribution would show a flat
low-frequency PSD instead, which this record's non-flat spread check would
have failed. See that record's `.md`/`.json` files for the full per-corner
measurement table, PDK/tool/repo provenance, and the raw per-corner ngspice
logs under its `corners/` subdirectory (the exact deck each corner ran, plus
stdout/stderr, embedded for reproducibility).

**Verdict**: mechanism check **PASS**. The campaign it unblocked is below.

## The characterization campaign (issue #10)

Full statement, with alternatives and consequences:
[`spec/decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md`](../spec/decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md)
(status **Proposed**). The reduction that produces every derived number is
`sim/ro-array-sizing/analysis/array-sizing.py` -- it runs **no simulator**,
reads only the committed records, and reproduces the sizing arithmetic
end to end:

```bash
python3 sim/ro-array-sizing/analysis/array-sizing.py       # print the reduction
```

Four results, each with its own slug:

1. **Per-stage gain** (`ro-stage-small-signal-gain/`): `ro_stage`'s
   open-loop gain at its own trip point is −14.3 nominal, −11.8 at the
   weakest of the three headline points. That is ~12x the Barkhausen
   minimum for any stage count in play, so **DR-0001's gain risk is
   retired**.
2. **Ring swing** (`ro-ring-jitter-accumulation/`): `ro_ring11` -- the ring
   `ro_array_core.sch` actually instantiates -- swings **1.06 x Vdd**
   peak-to-peak at every headline point, including the slow/hot/low-supply
   corner DR-0001 names. **Swing confirmed; DR-0001's "Revisit if" is not
   triggered.** The 5-stage vehicle is slew-limited to 0.81-1.00 x Vdd,
   which is a caution against a naive move to fewer stages.
3. **Entropy-binding corner** (`ro-array-sizing/`): **`ss` / −40 °C /
   1.62 V**, `Q_ring` = 1.122e−4, over a 24.5x range across the full
   27-point grid. **Cold** -- the direction gf180-trng's DR-0012 inferred
   and its DR-0015 later reversed. Measured here on a full grid, inherited
   from neither.
4. **Sized `N`**: `N = 2` is **refuted**. At the binding corner it gives
   `Q_array` 26x below the `M*Q_H0` the ported sizing law requires at this
   repo's draft rate/entropy rows; the sized value is **53** five-stage
   rings, or **>= 309** of the eleven-stage rings as drawn.

### What the campaign does not establish

Read these before citing any number above:

- **The injected noise level is fixed, not per-corner.** Every ring run
  injects a `trnoise()` source anchored once to the mechanism check's own
  measured near-band output-noise density. Per gf180-trng's precedent for
  the same method, every `sigma` is good to ~1.5-2x, hence every `Q` and
  every `N` to ~2-4x. `N = 53` means "tens".
- **One seed per PVT point** (gf180-trng used >= 4). Held *constant* across
  the grid on purpose -- common random numbers make corner-to-corner
  comparison cleaner, at the cost of saying nothing about seed spread.
- **20 periods per point** (8 for `ro_ring11`), so `sigma_1` carries ~16%
  (~25%) statistical error. This does not blur the corner search: `Q` goes
  as `sigma_1^2/T_0^3`, and `T_0` -- which ranges 3.6x across the grid and
  is measured to ~0.2% -- dominates the ordering.
- **An unexplained stage-count anomaly.** The measured `ro_ring5`-vs-
  `ro_ring11` `Q` ratio exceeds what the sizing law predicts by ~3.3x,
  because `sigma_1` *fell* with stage count instead of rising as
  `sqrt(n)`. Recorded as an open question, not smoothed over.
- **No power, no leakage, no inter-ring correlation, no sampler.** The
  starve length, the `wstv` skew fraction and every device width are
  untouched by this campaign and remain placeholders.

### How the estimator was validated before it was believed

`ro-ring-timestep-convergence/` holds two controls, both on the same deck,
corner and seed as the grid:

- a **timestep sweep** (`@@TMAX@@` = 5p/10p/20p/40p): `T_0` moves 0.19%
  across an 8x change in step; `sigma_1` scatters 31% with no monotone
  trend, i.e. no timestep dependence is resolvable above the estimator's own
  statistical error. That is what licenses running the 27-point grid at the
  coarse step, rather than merely wanting to.
- a **numerical floor** (`@@NA@@` = 0 -- injected noise off entirely): the
  transient solver by itself manufactures 0.58 ps (5p) / 0.65 ps (20p) of
  period scatter. Every grid `sigma_1` is corrected against it in
  quadrature, which lowers `Q` and raises `N` -- the conservative direction.

## Writing a new record

1. Author a deck template under `sim/<slug>/testbench/`, using the `@@...@@`
   placeholders above for anything corner- or PDK-dependent. Leave out the
   `.lib` corner selection (the runner injects it) and end with a
   `.control` block that runs whatever analyses you need and `print`s each
   measurement as `name = value`.
2. Run it: `python3 sim/bin/corner-run.py sim/<slug>/testbench/<file>.spice --slug <slug> --claim "<claim>" --corners tt,ss,ff`.
3. Commit the testbench (if new) and the minted `sim/<slug>/records/<record-id>.{md,json}`
   plus `sim/<slug>/corners/<record-id>/` -- the raw log is what makes a
   record auditable without re-running anything.

A record id is never reused: the runner refuses to start if
`sim/<slug>/records/<record-id>.md` (or its `.json` twin, or the matching
`sim/<slug>/corners/<record-id>/`) already exists. Running twice within the
same second on the same commit is the only way to collide; wait a second and
re-run.

### PVT grid

`spec/porting-plan.md` §3.1 proposes `{-40, 27, 125} degC x {process nominal
+/-10% supply} x {tt, ff, ss}` as the flagship full grid for the
characterization campaign, with `sf`/`fs` dropped per the same reasoning
DR-0006 gave in the sibling `gf180-trng` repo. `sim/pdk.json`'s
`process_corners` lists every corner section the installed PDK's ngspice
library actually defines (`tt`/`ss`/`sf`/`fs`/`ff` plus the resistor/
capacitor-skew-only `ll`/`hh`); `default_corners` (`tt`/`ss`/`ff`) is what
`corner-run.py` runs when `--corners` is omitted. #9's mechanism check
exercised the process axis at nominal temperature/supply only; #10's
campaign ran the full grid, one runner invocation per (temp, vdd) point
with the process axis bundled into it -- 9 invocations, 27 corner runs, one
record per (temp, vdd) point for `ro_ring5`, plus 3 single-corner records
for `ro_ring11` at the headline points.

### Record-granularity convention

`spec/porting-plan.md` §3.1 cites gf180-trng's DR-0005 append-only
evidence-record convention (one record per testbench/PVT point, a `level:`
field on every record, every stochastic run states its seed,
`superseded_by` rather than edit-in-place) as the convention this repo's own
`sim/` should follow. This bootstrap's one mechanism-check record covers
three PVT points (`tt`/`ss`/`ff` at nominal temperature/supply) in a single
document because the check itself is a single go/no-go claim ("is the
flicker-noise mechanism active under the corner decks as installed", not a
per-corner claim that could differ in kind from corner to corner) -- the
record's own per-corner table makes each point's individual result
inspectable. The later characterization campaign's *quantitative* claims
(`sigma_1`, `T_0`, per corner) are exactly the kind DR-0005's finer
per-(testbench, PVT point) granularity is for, and should follow it more
literally: one record per corner once those runs produce corner-specific
numbers worth citing independently.

The #10 campaign settled on **one record per (temp, vdd) point, with the
process axis bundled into it** -- 9 records for the 27-point `ro_ring5`
grid, not 27 and not 1. The reasoning: a runner invocation is atomic over
`--corners`, the three process corners at one (temp, vdd) share a single
claim and a single set of run conditions, and each record's own per-corner
table keeps every point individually inspectable and individually citable
(`sim/ro-array-sizing/`'s reduction cites points, not records). Going finer
would have meant 27 near-duplicate documents; going coarser would have
merged PVT points whose numbers differ by 24x into one claim, which is
exactly what DR-0005 forbids.

`sim/ro-array-sizing/` is a different shape again: a **derived** record.
It introduces no simulation, cites the records it reduces by id, and is
regenerated by a committed script rather than by `corner-run.py`. Its
`level` says so (`transistor (derived)`), so no reader can mistake it for a
run.
