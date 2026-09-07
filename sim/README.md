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

Issue #20 then added the digital section (`digital/`, everything downstream
of the raw tap, `spec/decision-records/DR-0004-sky130-digital-section-architecture.md`,
status **Proposed**). Those runs are **behavioural**, not ngspice: they have
no PVT axis and never will, because the verification-level split
(`spec/porting-plan.md` §1.1) puts everything past `raw_bit` in a bit-exact
model rather than a transistor-level deck. They follow the same
append-only record rules through `sim/bin/evidence_record.py`'s
`mint_behavioral_record()` instead of `sim/bin/corner-run.py`:

| Slug | Claim under test | Landed by |
|---|---|---|
| `digital-health-test-parameters/` | the SP 800-90B RCT/APT cutoffs derived from the formulas at this repo's own `H` target and 50 kbps raw rate; the exact APT degeneracy floor; the false-alarm and latency consequences | #20 |
| `digital-conditioner-equivalence/` | is the committed CRC-32/LFSR conditioner bit-exact against independently-constructed references, and does each word depend on exactly its own 256 raw bits? | #20 |
| `digital-section-behavioral/` | do the assembled section's health tests, start-up gate, latch-and-gate policy, raw-path invariant and mode-switch flush behave as DR-0004 specifies, over declared synthetic sources? | #20 |
| `digital-rtl-equivalence/` | does `digital/rtl/trng_digital.v` match the normative behavioural model cycle for cycle? | #20 |

Issue #21 then closed the one gap every campaign above left open: none of
them ever digitizes an actual noise-driven raw bit. It drives the same
assembled `ro_array_core` + `sampler_dff` path from injected per-stage
`trnoise()` sources (all four rings, in place, following
`ro-ring-jitter-accumulation/`'s own injection topology) through a real
`.tran` run and reduces the resulting sequence to a Most-Common-Value
(SP 800-90B section 6.3.1 style) min-entropy point estimate:

| Slug | Claim under test | Landed by |
|---|---|---|
| `raw-bit-min-entropy/` | a real, noise-driven raw bit sequence from the assembled array + sampler, and its MCV-style min-entropy point estimate, per PVT corner | #21 |

`sim/tests/test_raw_bit_entropy.py` is the fast, always-runnable unit-test
suite behind that record's reduction step (standard library only, no
simulator, no PDK).

`sim/tests/test_digital_section.py` is the fast, always-runnable unit-test
suite behind those records (standard library only, no simulator, no PDK):
`python3 sim/tests/test_digital_section.py`.

Issue #22 then added the first **post-layout** campaign — every record above
this line is driven from `design/*.spice`, xschem's schematic export, which
contains no physical interconnect at all. The first two slugs below are
driven from `layout/pex/ro_ring5_pex.spice`: `klt extract --parasitics` over
the nine *leaf* composed, DRC-clean and LVS-clean cells under `layout/`
(`layout/pex/README.md` states exactly what that parasitic model does and
does not contain, and why its numbers are *intra-cell* parasitics only —
there was no inter-cell interconnect in `layout/` to extract yet when that
library was built). A later increment of the same issue landed
`layout/ro_ring5*/` — the composed, DRC-clean and LVS-clean whole rings, with
real inter-gate metal routing drawn — which the third slug below extracts
directly, via the sibling library `layout/pex-ring/ro_ring5_assembled_pex.spice`
(`layout/pex-ring/README.md`):

| Slug | Claim under test | Landed by |
|---|---|---|
| `post-layout-ro-ring5/` | the five-stage ring's period, swing and supply current with extracted **intra-cell-only** parasitics (ideal inter-gate wires), at all four `wstv` widths, with the pre-layout netlist as a same-deck control — plus the shared-substrate-node coupling bound and its loading control | #22 |
| `post-layout-parasitic-impact/` | reduction of the above: what the parasitics cost, whether the `wstv` frequency ladder survives them, and how large the inter-ring coupling actually is | #22 |
| `post-layout-ro-ring5-assembled/` | the same period/swing/supply-current measurement, from extracting each **whole assembled ring's own GDS** directly — real inter-gate wiring included, not just intra-cell parasitics — with the pre-layout netlist as a same-deck control | #22 |

See "The post-layout campaign (issue #22)" below for what those decks are,
why the third leaf-level deck exists, and the one deck defect it caught; see
"Assembled-ring post-layout" for the ring-level extraction.

A later increment of the same issue extracted the **whole array**
(`layout/pex-array/`, slug `post-layout-ro-array-core/`; see "Array-level
post-layout" below), and the increment after that crossed the raw tap for
the first time: every slug named so far is on the **entropy-source** side of
it, and none of them measures the digitizer at all. `post-layout-sampler-dff/`
does, from `layout/pex/sampler_dff_pex.spice` — the second descriptor
(`layout/pex/pex-sampler.json`) over the three DRC-clean, LVS-clean leaf
cells `layout/sampler_dff/` places:

| Slug | Claim under test | Landed by |
|---|---|---|
| `post-layout-sampler-dff/` | the raw-tap digitizer's own clk→q capture delay, output levels, setup-time bracket, and reset-window / idle / active supply current, with extracted **intra-cell** parasitics and the pre-layout `.subckt sampler_dff` as a same-deck control | #22 |

See "Sampler post-layout" below. That slug is also where DR-0003's own named
follow-up item ("**Sampler_dff characterization** ... unsimulated") and
`spec/porting-plan.md`'s DR-0014 reset-contention **methodology** transfer
are discharged for sky130 —
[`spec/decision-records/DR-0007-*.md`](../spec/decision-records/DR-0007-sampler-dff-post-layout-and-reset-contention.md).

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
| evidence-record minter | `sim/bin/evidence_record.py` | shared append-only record-minting scaffolding; `mint_record()` for pure-reduction `analysis/*.py` scripts, `mint_behavioral_record()` for runs that have no simulator and no PDK (`level: behavioral`); a library each caller calls, not a runner |
| testbench | `sim/<slug>/testbench/*.spice` | deck **templates** (see placeholders below) -- not runnable decks as committed |
| records | `sim/<slug>/records/<record-id>.{md,json}` | one append-only evidence record per run: `.md` (human), `.json` (machine) |
| raw logs | `sim/<slug>/corners/<record-id>/<corner>.log` | the exact deck each corner ran, embedded, plus its raw ngspice stdout/stderr -- committed evidence, exempted from the root `.gitignore`'s `*.log` rule by `!sim/*/corners/**/*.log` |
| behavioural harness | `sim/<slug>/harness/*.py` (or `analysis/*.py` for a pure reduction) | the runnable testbench for a `level: behavioral` slug -- drives `digital/model/` (and, for the RTL slug, `iverilog`), then mints its own record |
| behavioural artifacts | `sim/<slug>/runs/<record-id>/*.txt` | the raw stimulus and traces a behavioural run produced -- the analogue of `corners/`, `.txt` rather than `.log` because the `.gitignore` exemption above is scoped to `corners/` |

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
- `@@PEX_LIB@@` -- absolute path to the committed **post-layout** subcircuit
  library (`--pex-lib`, default `layout/pex/ro_ring5_pex.spice`), the
  `pex-netlist.py --check`-guarded `klt extract --parasitics` netlist of the
  composed cells under `layout/`. A post-layout deck includes this *in
  addition to* `@@RO_RING5@@` when it wants the pre-layout netlist alongside
  as a same-deck control (see "The post-layout campaign" below). Both
  substituted paths, with their sha256, are recorded in every record's
  `netlists` block, so a record always names the netlist revision behind its
  numbers.
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

## The post-layout campaign (issue #22)

`sim/post-layout-ro-ring5/` is this repo's first campaign driven from a
*layout*-derived netlist rather than from a schematic export. Its input is
`layout/pex/ro_ring5_pex.spice` -- `klt extract --parasitics` over the nine
composed, DRC-clean and LVS-clean cells under `layout/`, rewritten for
ngspice by `layout/bin/pex-netlist.py`. Read `layout/pex/README.md` before
citing any number from it: the parasitic model is a lumped star resistance
per net (conservative) with **no inter-cell interconnect at all** (there is
none in `layout/` yet to extract), so these are intra-cell parasitics
specifically, not a full post-layout ring.

Three decks, run at the same four (temp, Vdd) points
`ro-ring5-swing-and-current/` used, each bundling `tt`/`ss`/`ff` -- twelve
records, thirty-six corner runs:

| Testbench | What it holds fixed | What it answers |
|---|---|---|
| `tb_post_layout_ro_ring5.spice` | `vsubs` tied hard to 0; four post-layout rings AND four pre-layout rings in one deck | what the parasitics cost (period, swing, supply current), as a same-corner ratio rather than a cross-record comparison |
| `tb_post_layout_substrate_float.spice` | `vsubs` untied (the extractor's own 1 TOhm dc tie); four rings running | the pessimistic inter-ring coupling bound -- the shared substrate node is the only node four independently-supplied rings share |
| `tb_post_layout_substrate_float_solo.spice` | `vsubs` untied; rings 2/3/4 present but **stopped** | the control that separates the floating node's capacitive *loading* from actual *coupling* |

`sim/post-layout-parasitic-impact/analysis/parasitic-impact.py` reduces all
twelve records (no simulator; run it to reproduce every number below):

- **Parasitics cost 1.378x - 1.479x in ring period** across the grid and all
  four widths, and *raise* the ring-node swing 1-4% (a slower ring reaches
  its rails more completely). Per-ring supply current falls 2-6%.
- **The `wstv` frequency ladder survives.** Post-layout ladder span
  (slowest/fastest ring) is 1.1122x - 1.2096x, against 1.1225x - 1.2464x
  pre-layout. The closest any ring pair comes to a mutual-injection-lock
  rational (4/3, 3/2, 2/1 -- DR-0003 §8's own criterion) anywhere on the
  grid is 9.3%.
- **Inter-ring coupling through the shared substrate node is at most 0.033%
  of the ring period** at the pessimistic bound -- an upper bound, not a
  resolved measurement, since only 1 of 12 grid points exceeds the transient
  solver's own 0.024% numerical period scatter and the shift's sign is not
  consistent across the grid. What *is* resolved is that the node genuinely
  carries all four rings' activity (3.8% of Vdd peak to peak with four rings
  running, 1.1% with one).

`spec/decision-records/DR-0005-*.md` states what this does and does not
settle for DR-0003 §8.

### The control that caught a deck defect

The solo control exists because the float-vs-tied difference alone is
uninterpretable -- but writing it caught something else first. An earlier,
uncommitted pass over these decks buffered only *one* of the four rings
(`ro_array_core.sch` buffers all four). The buffered ring ran ~18% slower
than its unbuffered neighbours purely from the extra load, and that showed
up in `skew_span` as if it were ladder span. The decks now buffer every
ring, on both the post-layout and pre-layout side, and all twelve committed
records are from the corrected decks -- **no record from the defective deck
was ever committed**, so there is nothing under `records/` to supersede.
The defect is recorded here, and in `tb_post_layout_ro_ring5.spice`'s own
buffer block, rather than left as a silent fix.

### `PEX_LIB` provenance re-stamp (issue #93)

All twelve records in `sim/post-layout-ro-ring5/` name
`layout/pex/ro_ring5_pex.spice` in their `netlists.PEX_LIB` block with
sha256 `c975689411eb…`. **That file has since been re-extracted and now
hashes `53ec4e3c78f3…`.** The records are append-only evidence and were
*not* edited; this note is the re-stamp explanation the change owes them.

Why it changed, and why it is provenance-only:

- The old library was produced by `klt 0.4.0`, the pin
  (`layout/pdk.json`'s `klt_version_pin`) is `0.3.0+gc6dbf66c53c6`, and
  `layout/bin/pex-netlist.py layout/pex/pex.json --check` therefore failed
  on a checkout matching the pin. Issue #93 re-extracted the nine cells on
  the pinned build so the committed evidence and the pin agree.
- **The entire diff is one anonymous net's name in three of the nine cells**
  (`n3` -> `n4` and back, in the node token, the extractor's own `R_*`/`C_*`
  element names, and its per-element provenance comments). All 24 changed
  lines were verified to be explained by that relabel and nothing else, and
  every R value, C value, coupling value, count, device, terminal and
  connection in every extraction report is identical. `layout/pex/README.md`
  § "When `--check` is red because the tool moved" has the measurement.
- **Directly demonstrated, not merely argued**: the deck
  `tb_post_layout_ro_ring5.spice` was rendered twice at the records' own
  `tt` / 27 °C / 1.8 V point -- once against the old library, once against
  the new -- and ngspice's two output logs are **byte-identical**. Every
  measured value in them also matches record
  `20260906-033032-4fe8c49.json`'s `tt` corner to every recorded digit
  (`t_pex_wstv0p42 = 4.10667e-09`, `slowdown_wstv0p42 = 1.408806`,
  `swing_frac_pex_ring = 0.8756866`, `i_pex_wstv0p42 = 1.057331e-05`),
  reproduced on a *different* host and a different ngspice (46 here, 47
  when the records were minted).

So nothing in `sim/post-layout-ro-ring5/` is superseded: the numbers stand,
and re-running any of those twelve records today would reproduce them from
the new library. Only the recorded input hash is stale, deliberately, and
this is where that is written down.

### Assembled-ring post-layout: real inter-gate wiring (issue #22)

`sim/post-layout-ro-ring5-assembled/` answers the question the section above
explicitly leaves open: `layout/pex/`'s numbers have **no inter-cell
interconnect at all**, so they are a lower bound on the ring's real
parasitic penalty. Once `layout/ro_ring5*/` existed as composed, DRC-clean
and LVS-clean *whole rings* (issue #22/#27, PR #51) with the `n1`-`n4`
signal chain, `ro` feedback and `vddr`/`vss` rail busing actually drawn,
extracting that GDS directly — rather than five separately-extracted leaf
cells wired by the testbench's own ideal nets — includes that inter-gate
metal in the ring's own period/swing/current numbers for the first time.
`layout/pex-ring/ro_ring5_assembled_pex.spice` is that extraction
(`layout/pex-ring/README.md` states the model and the two net-naming
collisions this flattening surfaces that leaf extraction never hits), and
`tb_post_layout_ro_ring5_assembled.spice` is the single deck: post-layout
assembled ring vs. the identical pre-layout `ro_ring5` subcircuit, same
corner, same deck, at the same four (temp, Vdd) points as every other deck
in this section.

Four records, twelve corner runs:

- **Real inter-gate wiring costs far more than intra-cell parasitics alone.**
  Period slows **2.0819x - 2.3666x** against the pre-layout control across
  the full grid and all four `wstv` widths, against `layout/pex/`'s
  intra-cell-only **1.378x - 1.479x**. Pairing the two campaigns' twelve
  matching (temp, Vdd, corner) points and four widths each (48 pairs, exact
  PVT-grid match) rather than just comparing the two ranges: the assembled
  deck's own slowdown is **1.5045x - 1.6546x** *of* the leaf-only deck's
  slowdown at that same point, mean 1.573x — i.e. drawing the real
  inter-gate wiring costs the ring another ~50-65% multiplicatively on top
  of intra-cell parasitics alone, fairly consistently across the grid (the
  48-pair range is narrower than either campaign's own per-width/per-corner
  spread). This is not a contradiction between the two libraries; it is the
  inter-cell wiring `layout/pex/README.md` itself names as entirely absent
  from its own model, now measured for the first time. The two campaigns are
  still not a same-deck ratio in the same sense every other ratio in this
  file is (two separate extractions, two separate ngspice runs) — see
  `layout/pex-ring/README.md` for why a single three-way deck was not built
  this increment.
- **The `wstv` frequency ladder still survives.** Assembled post-layout
  ladder span (slowest/fastest ring) is **1.0937x - 1.1822x** against
  **1.1225x - 1.2464x** on the identical same-deck pre-layout control — the
  pre-layout figure matches `post-layout-parasitic-impact/`'s own
  independently-computed pre-layout span almost exactly, cross-validating
  both reductions. The ladder is, if anything, *more* compressed with real
  inter-gate wiring than either the intra-cell-only or pre-layout figures,
  i.e. real routing parasitics do not introduce a new risk of closing the
  ladder onto a mutual-injection-lock rational (DR-0003 §8's own criterion).
- **`wstv` inter-ring decorrelation (DR-0003 §8, re-evaluated by
  `spec/decision-records/DR-0005-*.md`) is not superseded by this
  measurement.** DR-0005's own open finding — no supply-distribution layout
  exists, so §8's first-named mechanism (shared supply impedance) remains
  entirely unmodelled — is unaffected: this deck's `vddr1`..`vddr4` are
  still four ideal isolated sources, one ring's own GDS at a time. What this
  measurement adds is that a *single* ring's own real interconnect is now in
  the model; the inter-ring question DR-0005 leaves open is orthogonal to
  it and still requires the array-level assembly `layout/README.md`'s
  "What's deferred" tracks.
- **The memory trap this deck hit, and its fix, are recorded in
  `layout/pex-ring/README.md`** — the `ff` corner exhausted ngspice's
  default per-node history memory on the first run (a flat ring extraction
  has far more nodes than the leaf-cell composition's own subcircuit
  library, most of them parasitic-star leg nodes no `.meas` reads) until a
  `.save` line scoped the saved trace set to only the nodes measurements
  actually use.

### `PEX_LIB` provenance re-stamp (issue #96)

All four records in `sim/post-layout-ro-ring5-assembled/` name
`layout/pex-ring/ro_ring5_assembled_pex.spice` in their `netlists.PEX_LIB`
block with sha256 `5f9074c2c382…`. **That file has since been re-extracted
and now hashes `b4fdb68a8c42…`.** The records are append-only evidence and
were *not* edited; this note is the re-stamp explanation the change owes
them, following the convention § "`PEX_LIB` provenance re-stamp (issue #93)"
above established for `ro_ring5_pex.spice`.

Why it changed, and why it is provenance-only:

- The old library was produced by `klt 0.4.0`, the pin
  (`layout/pdk.json`'s `klt_version_pin`) is `0.3.0+gc6dbf66c53c6`, and
  `layout/bin/pex-netlist.py layout/pex-ring/pex.json --check` therefore
  failed on a checkout matching the pin. Issue #96 re-extracted all five
  cells on the pinned build so the committed evidence and the pin agree;
  `--check` now exits 0 there.
- **The entire 278-line diff is the extractor's own node-label
  bookkeeping**: one anonymous net renamed (`n4` -> `n5`, in the
  `wstv0p42` cell only), the per-terminal leg-node suffix renumbered
  (`vddr__t9` <-> `vddr__t12` and similar, each carrying its own series-R
  value with it), and `net_id` permuted in the reports. Every R value, C
  value, coupling value, count, device, model, geometry parameter and
  connection is unchanged. `layout/pex-ring/README.md` § "Re-extracted on
  the pin, and what that did and did not move" has the three independent
  checks, including a label-free colour-refinement (Weisfeiler-Lehman)
  isomorphism test that is itself validated against a
  randomly-relabelled control.
- **Directly demonstrated, not merely argued**: the deck
  `tb_post_layout_ro_ring5_assembled.spice` was rendered twice at the
  records' own `tt` / 27 °C / 1.8 V point — once against the old library,
  once against the new — and ngspice's two output logs are
  **byte-identical**. Every measured value in them also matches record
  `20260906-085753-9109b23.json`'s `tt` corner to every recorded digit
  (`t_asm_wstv0p42 = 6.446773e-09`, `t_asm_wstv0p48 = 5.673425e-09`,
  `slowdown_wstv0p42 = 2.212519`, `swing_frac_asm_ring = 0.8905795`,
  `i_asm_wstv0p42 = 9.536944e-06`, `skew_span_asm = 1.136311`), reproduced
  on a *different* host and OS (Linux here, macOS when the records were
  minted) on the same ngspice-46.

So nothing in `sim/post-layout-ro-ring5-assembled/` is superseded: the
numbers stand, and re-running any of those four records today would
reproduce them from the new library. Only the recorded input hash is stale,
deliberately, and this is where that is written down.

### Array-level post-layout: the whole entropy source, real inter-ring wiring (issue #22)

`sim/post-layout-ro-array-core/` answers the question the section above
still leaves open: `layout/pex-ring/`'s numbers are one ring's own real
interconnect with **ideal wires to its neighbours** — the ring-to-buffer
signal chain, buffer-to-XOR fan-in, XOR combining tree and array-wide `vdd`
bus are all still undrawn there. Now that
`layout/ro_array_core/` gives a `klt drc`
clean (0 violations), `klt lvs` **matching** (132/132 devices, 96/96 nets),
`--check`-reproducible whole-array GDS — `vdd` bus and array-wide `vss`
strap included — `layout/pex-array/ro_array_core_pex.spice` extracts it flat
— see that directory's own README for the parasitic model and the net-alias
technique extended to four rings' worth of duplicate internal labels.

Three testbenches, the same four (temp, Vdd) points every post-layout
campaign in this file uses, each bundling `tt`/`ss`/`ff` — thirty-six corner
runs across the three decks:

| Testbench | What it holds fixed | What it answers |
|---|---|---|
| `tb_post_layout_ro_array_core.spice` | `vsubs` tied hard to 0; post-layout array AND an identical-topology pre-layout array in one deck | array-level parasitic cost (period, `wstv` ladder, XOR-tree combining fidelity, supply current), same-corner ratio |
| `tb_post_layout_ro_array_core_substrate_float.spice` | `vsubs` untied; all four rings running | the pessimistic inter-ring coupling bound, now on the array's own real physical placement rather than four leaf cells hand-tied to a shared node |
| `tb_post_layout_ro_array_core_substrate_float_solo.spice` | `vsubs` untied; rings 2-4 present but **stopped** | separates the floating node's capacitive *loading* from actual *coupling*, same decomposition as `layout/pex-ring/`'s own solo control |

`spec/decision-records/DR-0006-*.md` states what this does and does not
settle for DR-0003 §8 in full; headline numbers:

- **Real array-level parasitics cost 2.158x - 2.501x in ring period** (mean
  2.323x over 48 paired ring/PVT points) — far
  more than intra-cell-only parasitics alone (1.378x - 1.479x), because the
  array now carries real ring-to-buffer, buffer-to-XOR, array-wide-`vdd` and
  array-wide-`vss` routing that no smaller-scope extraction in this repo
  could include.
- **The `wstv` ladder still discriminates.** Post-layout array span
  (slowest/fastest ring) is 1.084x - 1.175x, against 1.1234x - 1.2514x
  pre-layout in the same deck.
- **XOR-tree combining fidelity, measured post-layout for the first time.**
  Edge retention (N=4) is 0.700 - 0.821 post-layout against 0.547 - 0.724
  pre-layout in the same deck (retention is *higher*
  with real routing at every grid point — reported as measured, not
  explained); combining-node bias stays close to 0.5x Vdd in both cases
  (0.433 - 0.554 post-layout, 0.355 - 0.537 pre-layout), i.e. no new
  systematic bias from the real routing.
- **Array supply current stays the same order of magnitude**: 0.911x -
  1.039x of the pre-layout figure across the grid — real parasitic loading
  slows switching enough in most corners to slightly *reduce* net current,
  not raise it.
- **The tied/float/solo substrate bracket, now on a real physically-placed
  layout**: loading -0.353% to -0.192% of ring period, coupling **+0.044% to
  +0.293%** — both wider in magnitude than DR-0005's own ring-scale bracket
  (-0.151% to -0.057% loading, -0.033% to +0.018% coupling), and, unlike
  DR-0005's, **the coupling figure's sign is consistent across all twelve
  grid points** (12 of 12 positive). That is the signature DR-0005 named as
  what a real frequency pull would look like, and it appeared only once the
  canonical, `vss`-strapped GDS was the extraction source — the earlier
  extraction of the placement PoC's un-strapped `signal9` GDS read a
  mixed-sign -0.081% to +0.230% over the identical decks. DR-0006 is
  deliberate about what that does and does not license: the magnitude is
  still bracketed, not measured, and the array-scale numerical period-scatter
  floor has not been re-derived.

### A testbench defect and an environment note, both documented rather than fixed silently

The first run of the substrate-float/-solo decks addressed the shared
substrate node as `v(xarr.vsubs)` (hierarchical). Because `vsubs` is
`.global`-declared (klayout-tools#1503's own workaround), it is the *same*
node everywhere in the deck and is addressed as `v(vsubs)` directly, with no
instance prefix — the hierarchical form silently resolved to "no such
vector", so the node's own peak-to-peak swing was not captured this round.
The period-based bracket above is unaffected (it reads the array's own
exposed ports, not the internal global node). Not filed against
`klayout-tools`: `.global` addressing is standard ngspice behaviour.

Separately, during the earlier (pre-`vss`-strap) pass the `solo` deck's
first attempt at its coldest/highest-current
corner point had two of three process corners killed outright
(`exited -15`, then `exited -9`) within a few minutes — well under the 1800 s
per-corner timeout — consistent with transient memory contention from other
concurrent jobs on the shared host, not a deck fault. An immediate,
unmodified retry passed all three corners. Per this repo's append-only
convention, the partial-failure record was not deleted; it stands alongside
the successful retry.

### Two extraction passes, both kept

This slug holds **twenty-five** records, not twelve, because the whole
campaign was run twice against two different extractions of the same array:

| Records | Extracted from | Status |
|---|---|---|
| `20260906-*` (13, of which one is the host-contention `FAIL` above) | `layout/ro_array_core-placement-poc/ro_array_core_signal9_poc.gds` — the placement PoC's stream, no `vss` straps drawn | **superseded** |
| `20260907-*` (12, all `PASS`) | `layout/ro_array_core/ro_array_core.gds` — the canonical `cell.json` recipe's output, `vss` straps drawn | **current**; every number in the section above |

The recipe promotion landed after the first pass was measured, and it draws
`ring1..4`'s and `xa1..3`'s own `vss` taps, which moved the extracted
network's capacitance to substrate by +25.0 fF (+6.8%). Nothing was
deleted: each `20260907-*` record names the one it supersedes in its own
`supersedes` field, so the two passes are diffable line for line. That
diff is what surfaced the coupling-sign result above, which is why the
superseded pass is worth keeping rather than merely tolerable to keep.

### No `PEX_LIB` re-stamp here — and why that is the finding (issue #96)

Issue #96 re-extracted `layout/pex-ring/` on `layout/pdk.json`'s
`klt_version_pin` and re-stamped this slug's assembled-ring sibling above.
**It deliberately did *not* do the same for
`layout/pex-array/ro_array_core_pex.spice`**, so all twenty-five records
here still name the file they were actually measured against
(`ac97e365…` for the superseded pass, `82dede47…` for the current one) and
no re-stamp is owed.

The reason is a finding, not a deferral. Re-extracting this array from the
identical GDS on the pinned `klt 0.3.0+gc6dbf66c53c6` — **and, byte for
byte, on today's ambient `klt 0.4.0` too** — does not reproduce the
committed evidence, and the difference is not the node-relabelling class
that made the ring re-extraction safe. Three of the four `sig_n*` inter-net
coupling capacitors land on a different one of the four rings; a label-free
colour-refinement test proves the two netlists are not isomorphic; and the
`tt` / 27 °C / 1.8 V run moves this slug's headline combining figures
(`p_edge_retention` 0.7664580 -> 0.7195908, `p_f_xo` 4.920442e+08 ->
4.619850e+08, both −6.1%) where a pure relabelling of the same library
moves nothing at all. Full measurement, controls and the reasoning about
which extraction is likely correct:
`layout/pex-array/README.md` § "The array evidence is not reproducible, and
the difference is not cosmetic".

Consequence for a reader of these records: every number in this slug is
reproducible **only** against the committed
`layout/pex-array/ro_array_core_pex.spice` (sha256 as recorded), not from
a fresh extraction of the same GDS on any `klt` installable today.
`python3 layout/bin/pex-netlist.py layout/pex-array/pex.json --check` is
expected to exit 1 until that is settled — which is an operator decision
(re-measure the slug on today's tool, or keep the historical extraction and
pin harder), not something a re-extraction should quietly pre-empt.

## Sampler post-layout: the first measurement of `sampler_dff` at all (issue #22)

Every slug above this line sits on the **entropy-source** side of the raw
tap. `sim/post-layout-sampler-dff/` is the first that crosses it. Two
standing gaps meet here:

- **DR-0003's own "Follow-up required" list** names "**Sampler_dff
  characterization** for the now six-instance-per-block liveness/raw-tap
  digitizer fan-out (unsimulated, per `design/xschem/trng_top.sch`'s own
  text block)". It had been unsimulated ever since — `sim/raw-bit-min-entropy/`
  digitizes *through* this cell but measures the bitstream, not the cell.
- **`spec/porting-plan.md`'s DR-0014 entry** is explicit that the
  gf180-trng reset-window contention measurement's *methodology* transfers
  to sky130 while its *numbers and polarity argument* do not: "measure
  reset-window contention current explicitly, per the specific storage-loop
  topology chosen, before assuming a brute-force reset is 'free'". Nobody
  had measured it here.

Two decks, the same four (temp, Vdd) points every post-layout campaign in
this file uses, each bundling `tt`/`ss`/`ff` — twenty-four corner runs:

| Testbench | What it answers |
|---|---|
| `tb_post_layout_sampler_dff.spice` | what the sampler does **after** the edge: clk→q capture delay both directions, captured output levels, and reset-window / idle / active supply current — post-layout and pre-layout DFF in one deck on one shared stimulus |
| `tb_post_layout_sampler_setup.spice` | what it needs **before** the edge: a twelve-rung d-to-clk offset ladder (3200, 800, 260, 215, 180, 150, 125, 105, 88, 73, 60, 45 ps) run simultaneously on twelve post-layout and twelve pre-layout instances, bracketing each side's setup time per corner |

**Scope, stated up front.** This is `layout/pex/sampler_dff_pex.spice` —
`klt extract --parasitics` over the three composed leaf cells
`layout/sampler_dff/` places (`layout/ro_buf/`, `layout/sampler_tg/`,
`layout/sampler_nand2/`, each `klt drc` clean and `klt lvs` matching its own
reference), wired per `design/sampler_core.spice` device for device with
**ideal inter-cell wires**. It is exactly the scope
`sim/post-layout-ro-ring5/` has for the ring, one level below
`sim/post-layout-ro-ring5-assembled/`'s whole-GDS extraction.
`layout/sampler_dff/`'s own assembly exists and is DRC-clean, but its
`m`/`mb` data-path nets are still unrouted and its `klt lvs` therefore does
not match yet (15/22 devices, 7/14 nets as of PR #87's `sampler_nand2`
pin-swap fix), so extracting *that* GDS flat would extract an incomplete
circuit. Both deck headers state the same scope, but were authored while
the pin swap ([#84](https://github.com/2AMLogic/sky130-trng/issues/84)) was
still open and cite it as a second reason; that half is now closed and the
unrouted `m`/`mb` pair is the whole of what remains. The deck text is left
exactly as it was run — the committed per-corner logs under `corners/`
echo the deck verbatim, so editing the header after the fact would make
this slug's own transcripts disagree with its own decks. Stimulus is ideal
PWL (100 ps edges), identical on both sides, so
the post-layout cell's larger input capacitance never slows its own input
edges. **Every post-layout figure below is therefore a floor on the real
cost, not the whole of it.**

### What the capture-timing deck found

| PVT | corner | clk→q rise, post | pre | ratio | clk→q fall, post | pre | ratio |
|---|---|---|---|---|---|---|---|
| −40 °C / 1.62 V | `tt` | 167.6 ps | 120.6 ps | 1.389x | 231.9 ps | 167.9 ps | 1.382x |
| −40 °C / 1.62 V | `ss` | 210.4 ps | 148.4 ps | 1.418x | 299.0 ps | 211.6 ps | 1.413x |
| −40 °C / 1.62 V | `ff` | 137.9 ps | 101.0 ps | 1.365x | 183.8 ps | 135.7 ps | 1.354x |
| 27 °C / 1.80 V | `tt` | 141.3 ps | 102.9 ps | 1.373x | 187.6 ps | 139.0 ps | 1.350x |
| 27 °C / 1.80 V | `ss` | 174.2 ps | 124.5 ps | 1.400x | 236.9 ps | 172.1 ps | 1.376x |
| 27 °C / 1.80 V | `ff` | 118.4 ps | 87.5 ps | 1.353x | 151.4 ps | 114.0 ps | 1.327x |
| 125 °C / 1.98 V | `tt` | 127.6 ps | 93.7 ps | 1.361x | 169.2 ps | 126.9 ps | 1.333x |
| 125 °C / 1.98 V | `ss` | 155.6 ps | 112.2 ps | 1.387x | 212.2 ps | 156.5 ps | 1.356x |
| 125 °C / 1.98 V | `ff` | 108.1 ps | 80.4 ps | 1.344x | 138.1 ps | 105.1 ps | 1.314x |
| −40 °C / 1.98 V | `tt` | 121.1 ps | 89.4 ps | 1.355x | 157.5 ps | 117.4 ps | 1.342x |
| −40 °C / 1.98 V | `ss` | 145.8 ps | 105.9 ps | 1.377x | 194.7 ps | 142.6 ps | 1.365x |
| −40 °C / 1.98 V | `ff` | 103.6 ps | 77.1 ps | 1.344x | 128.6 ps | 97.3 ps | 1.321x |

- **Intra-cell parasitics cost 1.314x - 1.418x in clk→q delay** (mean 1.362x
  over the 24 paired rise/fall points). That lands squarely inside DR-0005's
  own intra-cell ring-period finding of **1.378x - 1.479x** for the same
  extraction scope on a different cell family — the sampler is not
  anomalously parasitic-sensitive, and the two independent measurements
  agree on the size of the intra-cell penalty.
- **Post-layout capture delay is 103.6 - 299.0 ps** across the grid, against
  the 20 µs sample period DR-0003 ratified: **≤ 15 ppm of `T_s`**. Capture
  delay is nowhere near a constraint on the raw rate.
- **The post-layout cell is functionally correct.** Captured levels are
  ≥ 0.9983 × Vdd high and ≤ 0.0023 × Vdd low at every one of the 12 grid
  points, `q` does not move when `d` changes with the slave opaque, and
  asserted reset holds `q` ≤ 0.38 mV while `d` drives the opposite value.

### Reset-window current: DR-0014's methodology, re-derived on sky130

The reset window is measured with **`rst_n` asserted while `d` drives the
opposite value through the transparent master** — i.e. the condition under
which the pull-device reset DR-0014 rejected would be fighting the `d`
driver. Both DFFs see it on the same stimulus in the same run.

| PVT | corner | reset window, post | idle, post | reset/idle | reset, post vs. pre |
|---|---|---|---|---|---|
| −40 °C / 1.62 V | `tt` | 20.31 pA | 20.75 pA | 0.979 | +3.1e−05 |
| −40 °C / 1.62 V | `ss` | 19.30 pA | 19.03 pA | 1.014 | +2.2e−05 |
| −40 °C / 1.62 V | `ff` | 45.54 pA | 70.78 pA | 0.643 | +1.2e−05 |
| 27 °C / 1.80 V | `tt` | 502.2 pA | 979.6 pA | 0.513 | +5.0e−06 |
| 27 °C / 1.80 V | `ss` | 68.74 pA | 113.6 pA | 0.605 | +3.5e−05 |
| 27 °C / 1.80 V | `ff` | 4.294 nA | 8.562 nA | 0.502 | +1.3e−05 |
| 125 °C / 1.98 V | `tt` | 55.38 nA | 110.5 nA | 0.501 | +5.0e−04 |
| 125 °C / 1.98 V | `ss` | 13.00 nA | 25.80 nA | 0.504 | +1.8e−03 |
| 125 °C / 1.98 V | `ff` | 293.0 nA | 584.6 nA | 0.501 | +7.5e−04 |
| −40 °C / 1.98 V | `tt` | 37.03 pA | 42.54 pA | 0.870 | +1.3e−05 |
| −40 °C / 1.98 V | `ss` | 32.35 pA | 34.75 pA | 0.931 | +1.9e−05 |
| −40 °C / 1.98 V | `ff` | 117.7 pA | 201.6 pA | 0.584 | +8.5e−06 |

**There is no contention component.** Three independent readings of the same
conclusion:

1. **Magnitude.** 19.3 pA (`ss` / −40 °C / 1.62 V) to 293 nA (`ff` / 125 °C
   / 1.98 V), i.e. **0.90 nW at nominal (`tt` / 27 °C / 1.8 V) and 580 nW at
   the hottest/fastest grid point** — leakage-scale, and it tracks
   temperature/corner the way leakage does (three and a half orders of
   magnitude across a grid over which the *switching* figures move by less
   than 2x).
2. **It is at or below the same cell's own idle current** at every grid
   point (ratio 0.501 - 1.014). A reset fighting a driver cannot be *below*
   the quiescent current of the same cell in the same run. The recurring
   ~0.50 ratio is itself the mechanism: with `rst_n` low the NAND2s' series
   NMOS stacks are cut off, so a leakage path that is present at idle is not
   present during reset.
3. **It is the same number pre-layout and post-layout**, to between 5
   significant figures (+5.0e−06) and 3 (+1.8e−03), across the whole grid.
   Parasitic R and C can only change *dynamic* current; a reset window whose
   current is invariant to them is carrying no switching current to change.

What this does **not** claim: the brute-force pull-device alternative was
not simulated, so no reduction *ratio* against it is quoted here, and
gf180-trng's own 967 µW → 66 nW figure is not transplanted or compared
against. See
[`spec/decision-records/DR-0007-*.md`](../spec/decision-records/DR-0007-sampler-dff-post-layout-and-reset-contention.md)
for what the measurement does and does not license.

The active-window average (the same 55 ns containing both capture edges) is
1.063 - 1.980 µA post-layout, 1.306x - 1.548x the pre-layout figure — the
one place where the parasitics *do* cost real current, as extra capacitance
being charged and discharged.

### The setup-time bracket

Every rung of the ladder read back either a clean 1.000 or ~0 (largest
non-rail reading anywhere in the 24 rungs × 12 corner runs: 2.0e−04 × Vdd).
No rung landed on an intermediate level at any corner, so there is no
boundary-rung ambiguity to report — and, per DR-0011's standing judgment
that resolution-time statistics are not credibly reproducible in a
general-purpose transient solver, **nothing here is a metastability claim**:
the brackets below are deterministic captured/not-captured results at stated
offsets.

| PVT | corner | setup, post-layout | setup, pre-layout |
|---|---|---|---|
| −40 °C / 1.62 V | `tt` | (105, 125] ps | (88, 105] ps |
| −40 °C / 1.62 V | `ss` | (125, 150] ps | (88, 105] ps |
| −40 °C / 1.62 V | `ff` | (88, 105] ps | (73, 88] ps |
| 27 °C / 1.80 V | `tt` | (73, 88] ps | (60, 73] ps |
| 27 °C / 1.80 V | `ss` | (88, 105] ps | (73, 88] ps |
| 27 °C / 1.80 V | `ff` | (73, 88] ps | (60, 73] ps |
| 125 °C / 1.98 V | `tt` | (73, 88] ps | (45, 60] ps |
| 125 °C / 1.98 V | `ss` | (73, 88] ps | (60, 73] ps |
| 125 °C / 1.98 V | `ff` | (60, 73] ps | (45, 60] ps |
| −40 °C / 1.98 V | `tt` | (73, 88] ps | (60, 73] ps |
| −40 °C / 1.98 V | `ss` | (88, 105] ps | (73, 88] ps |
| −40 °C / 1.98 V | `ff` | (60, 73] ps | (45, 60] ps |

- **Worst-case post-layout setup time is ≤ 150 ps** over the whole grid
  (`ss` / −40 °C / 1.62 V — the same entropy-binding corner DR-0002/DR-0003
  identified, so the two worst cases coincide), and ≤ 88 ps at every
  1.8 V-or-above point.
- **Parasitics cost one ladder rung (~1.2x) at 10 of the 12 grid points and
  two (~1.44x) at the other two.** The direction and size agree with the
  clk→q result; the ladder is not fine enough to quote a ratio more
  precisely than that, which is why the rungs are the reported quantity
  rather than an interpolated number.
- **The digitizer is not the block's bandwidth bottleneck.** The combining
  gate's own minimum resolvable pulse width `w_90` is 122 - 241 ps
  (`sim/xor-combining-bandwidth/`, the figure DR-0003 §1 uses to bound `N`),
  and the comparison that bears on `N_max_combine` is per corner, against
  that corner's own `w_90` rather than against the bottom of the range.
  `xor-combining-bandwidth/` covers −40 °C/1.62 V, 27 °C/1.80 V and
  −40 °C/1.98 V, so nine of this campaign's twelve grid points have a `w_90`
  to compare against (the three 125 °C/1.98 V points have none, and are
  outside the comparison). At **all nine** of those points the post-layout
  setup bracket lies entirely below that corner's own `w_90` from
  DR-0003 §1's table — (105, 125] vs 190.9, (125, 150] vs 241.3, (88, 105]
  vs 166.0 ps at −40 °C/1.62 V `tt`/`ss`/`ff`; (73, 88] vs 163.4, (88, 105]
  vs 186.3, (73, 88] vs 133.2 ps at 27 °C/1.80 V; (73, 88] vs 134.0,
  (88, 105] vs 163.9, (60, 73] vs 122.0 ps at −40 °C/1.98 V — the last of
  those being `ff` / −40 °C / 1.98 V, the corner where `N_max_combine`
  binds. A pulse narrow enough to trouble the sampler has already been
  swallowed by the XOR tree.
- An earlier, purely geometric factor-of-two version of this ladder
  (3200…25 ps, 8 rungs) is *not* committed: it bracketed correctly but put
  both sides in the same rung at all three corners it was scouted at, i.e.
  it could not resolve the post-vs-pre difference that is the reason the two
  ladders share a deck. The committed twelve-rung spacing (~1.2x across
  45 - 260 ps, plus two wide anchors) was chosen from that scouting run and
  the deck header records why.

### Records

Eight records, all `PASS`: four (temp, Vdd) points × two decks, each
bundling `tt`/`ss`/`ff`. `20260907-1203..1206` are the capture-timing deck,
`20260907-1207..1220` the setup ladder. Nothing in this slug supersedes
anything — it is the first campaign of its kind here.

### `PEX_LIB` provenance re-stamp (issue #94)

All eight records above name `layout/pex/sampler_dff_pex.spice` in their
`netlists.PEX_LIB` block with sha256 `ec8578e2…`. **That file has since been
regenerated and now hashes `7efc1003…`.** The records are append-only
evidence and were *not* edited; this note is the re-stamp explanation the
change owes them, following the same convention § "`PEX_LIB` provenance
re-stamp (issue #93)" above established for `ro_ring5_pex.spice`.

Why it changed, and why it is provenance-only:

- `layout/bin/pex-netlist.py`'s generated library header hardcoded the
  literal string `layout/pex/pex.json` — the *entropy-source* descriptor —
  regardless of which descriptor actually built the library. Since issue
  #92 added a second descriptor (`pex-sampler.json` → this file), the
  header both misnamed the file it was generated from and quoted a
  `--check` command that verifies the *other* library. Issue #94 threads
  the invoking descriptor's own path through `build_library()` /
  `check_library()` so the header names itself correctly.
- **The entire diff is those two header lines.** `git diff` on the
  regenerated file shows exactly two changed lines — `from
  layout/pex/pex.json` → `from layout/pex/pex-sampler.json`, and the
  `--check` command line to match — nothing else in the library body
  differs: same `klt` build (`0.3.0+gc6dbf66c53c6`, the
  `layout/pdk.json` pin, used for both the old and new extraction here),
  same devices, same nets, same R/C values, same connectivity.
- `layout/pex/ro_ring5_pex.spice` (the `pex.json` library) is **not**
  affected by this change and keeps its issue-#93 re-stamp hash
  (`53ec4e3c78f3…`) unchanged: its own descriptor path already *is*
  `layout/pex/pex.json`, so threading the real descriptor through produces
  byte-identical header text for that file. `python3
  layout/bin/pex-netlist.py layout/pex/pex.json --check` continues to exit
  0 with no regeneration needed — the regression guard issue #94's
  acceptance criteria asked for.

So nothing in `sim/post-layout-sampler-dff/` is superseded: the numbers
stand, and re-running any of those eight records today would reproduce them
from the new library. Only the recorded input hash is stale, deliberately,
and this is where that is written down.

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
