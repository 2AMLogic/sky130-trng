# sim

The sky130 ngspice simulation harness and the evidence it produces.

This is the **bootstrap** of that harness (issue #9): the PDK pin, the PVT
corner runner, and one mechanism-check record confirming the sky130 device
noise model this whole entropy source depends on is actually active in the
corner decks as installed. It is deliberately **not** the jitter-accumulation
characterization campaign (`design/README.md`'s "Provisional, not sized"
table -- per-stage noise/gain, ring jitter accumulation, array sizing) that
this bootstrap unblocks; that is separate, later scope tracked by the
follow-up to #9 referenced from issue #6.

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

**Verdict**: mechanism check **PASS**. The jitter-accumulation
characterization campaign this unblocks -- transient-noise runs over
`ro_stage`/`ro_ring5` producing per-ring `sigma_1`/`T_0`, feeding the array
sizing law at the entropy-binding corner (`design/README.md`'s "Provisional,
not sized" table; `spec/porting-plan.md` §2.2/§2.4) -- is separate, later
scope.

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
`corner-run.py` runs when `--corners` is omitted. This mechanism check only
exercises the process axis at nominal temperature/supply -- the full
temperature/supply grid is characterization-campaign scope, not bootstrap
scope.

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
