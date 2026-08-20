# Porting plan: gf180-trng → sky130-trng

Status: **planning document, not a decision record and not a ratified spec.**
It answers the question this repo's `CLAUDE.md` and `README.md` pose before
any design work starts — *what carries over from
[gf180-trng](https://github.com/2AMLogic/gf180-trng) as-is, and what must be
re-derived for sky130* — and names the simulation evidence each
re-derivation needs. It does not ratify anything: per `CLAUDE.md`, "spec
changes go through `spec/` with a decision record," and every open question
below is deliberately left open for a future `spec/decision-records/DR-000N-*`
plus operator ratification, the same two-step process gf180-trng itself used
(architecture proposals in issues/PRs → `spec/decision-records/` → operator
ratification on the tracking issue, e.g. `spec/ratification-2026-07-31-target-spec.md`).

## Source pinning — re-verify before relying on this document

gf180-trng is an actively-worked sibling repo. Every claim below is sourced
from its `spec/` tree at commit **`f2ab01a`** (`main`, fetched
2026-08-20T16:37Z) — one commit newer than the `82cdd04` the Curator's
implementation guidance on issue #1 was written against, on the same day.
That one-commit drift changed nothing this plan relies on, but it is a
concrete illustration of the point: **do not treat any count, filename, or
"Accepted"/"Proposed" status below as durable.** Before a later issue acts on
a claim here, re-fetch `spec/decision-records/` and `spec/README.md` from
gf180-trng's current `main` and confirm the cited record's status has not
moved. Two decision records already changed status *within* the window this
plan was researched in (DR-0012's corner claim was narrowed by DR-0015,
itself still `Proposed`) — see §2.4.

As of that commit, gf180-trng has 24 decision records
(`spec/decision-records/DR-0001` … `DR-0022`, with two accidental
`DR-0011`/`DR-0012` filename collisions recorded and resolved in-place —
see each colliding file's own Status section), one ratification note
(`spec/ratification-2026-07-31-target-spec.md`), and one architecture survey
(`spec/entropy-architecture-survey.md`). Its `sim/` tree carries 13
characterization summary documents, an evidence-record harness
(`sim/harness/`, `sim/run_corners.py`, `sim/pdk.json`, `sim/records/`), and a
`sim/selftest.sh` / `sim/tools/` verification-tooling layer. This is
materially more mature than "twenty-plus decision records" — treat every
number in this paragraph as a floor, not a ceiling, by the time anyone acts
on it.

**Status legend used throughout**: **Ratified** = accepted by operator
decision via gf180-trng issue #1 (DR-0001…DR-0004, DR-0007). **Accepted
(delegated)** = accepted as a Builder/methodology decision under an existing
ratified record's delegation, not itself an operator ratification (e.g.
DR-0005, DR-0006, DR-0008, DR-0009, DR-0012, DR-0013, DR-0014, DR-0021,
DR-0022). **Proposed** = drafted, not yet accepted by anyone (DR-0010,
DR-0011-raw-rate, DR-0015, DR-0016, DR-0017, DR-0018, DR-0019, DR-0020). A
"Proposed" record is evidence of live, unresolved tension in the *source*
design, not a stable thing to port — this plan says explicitly, per record,
whether to treat it as inherited methodology or as an open question sky130
must re-litigate on its own evidence.

---

## 1. Entropy-source architecture carryover

### 1.1 What transfers as topology / methodology (process-independent)

These are decisions about *structure and analysis method*, not about a
specific device's measured behavior. They carry over to sky130 unchanged in
form, pending sky130-specific numbers filling in the same formulas.

| Carries over | Source | Why it is process-independent |
|---|---|---|
| N-way array of independent, free-running ring oscillators, deliberately non-integer-ratio frequencies, each with its own supply routing, XOR-combined into a single node ahead of one sampler | [DR-0007](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0007-multi-ro-xor-combined-entropy-source.md) §1 (**Ratified**) | Topology and the injection-locking rationale (Sunar/Martin/Stinson 2007; Markettos & Moore CHES 2009, cited in `spec/entropy-architecture-survey.md`) are literature results about RO-jitter TRNGs generically, not about gf180mcu specifically |
| The min-entropy bound `H ≥ 1 − (4/(π² ln 2))·exp(−4π²Q)`, `Q = σ²_acc(T_s)/T₀²` (Baudet, Lubicz, Micolod, Tassiaux, CHES 2011), and the white-noise sizing law `Q = σ₁²·T_s/T₀³` per ring | DR-0007 §2 | Published analysis of jitter-accumulation statistics; no PDK-specific constant appears in the law itself |
| The array sizing law `Q_array(T_s) = Σᵢ σ²_acc,i(T_s)/T₀,i²`, sized to `Q_array ≥ M·Q_H₀` at the entropy-binding corner, `M = 1.5` declared design margin | DR-0007 §2 | A statement about how independent variances add and how much margin to carry on top of the *model*; the margin factor is explicitly **not** sized to a measured device parameter (DR-0007: "not sized to cover the characterization's 2–4× uncertainty on Q itself") |
| **No XOR "piling-up" credit, no flicker/low-frequency credit** — both named as conservative-reading requirements, not device facts | DR-0007 §2 | Both are statements about which approximation is valid at the `Q` regime this architecture operates in (piling-up-lemma invalidity at `Q ~ 10⁻⁵`; flicker's non-stationarity making √t-extrapolation a lower bound) — mathematical/statistical arguments, reusable verbatim |
| Raw tap fixed at the sampler/digitizer output — after digitization, before any post-processing; the XOR tree is part of the noise source, not a raw tap itself | [DR-0001](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0001-raw-and-conditioned-output-paths.md) (**Ratified**), refined for the array case by DR-0007 | An interface/observability convention independent of device physics |
| Two output paths (raw always available, conditioned mode-selected via `OUT_MODE`), two distinct read registers (`RAW_DATA`, `DATA`), mode-switch flushes both the conditioner and the FIFO | DR-0001; register-map form fixed by [DR-0013](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0013-interface-register-map-and-streaming-semantics.md) (**Accepted, delegated**) | Digital interface convention, no device dependency |
| Raw-rate row defined at the raw tap, "sustained" meaning a full-run average with no FIFO underflow, and reported *and bound at a different corner than min-entropy* (rate binds at the slowest/hottest/lowest-supply corner; entropy binds near the coldest/opposite-supply region) | [DR-0003](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0003-throughput-defined-at-the-raw-tap.md) (**Ratified**) | The *structure* of "two rows, two different binding corners, don't conflate them" is a property of RO physics (jitter accumulation and oscillation speed move oppositely with P/V/T) that holds for any RO-based source, sky130 included |
| RCT/APT health-test *formulas* parameterized by `H` — `C_RCT = 1 + ⌈−log₂(α)/H⌉`; `C_APT` = smallest `C` with `Pr(X ≥ C) ≤ α` for `X ~ Binomial(W, 2⁻ᴴ)`; `α = 2⁻⁴⁰`; `W = 1024` for a binary source — plus the derivation of `α` from the target sample rate's false-alarm interval | [DR-0002](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0002-health-test-parameters-and-failure-behavior.md) (**Ratified**, amended A2/A6) | SP 800-90B §4.4.1/§4.4.2 formulas plus a false-alarm-rate argument tied to *sample rate*, not to device physics — independently reproduced by exact binomial computation per DR-0002's own record |
| **The APT degeneracy floor**: at `α = 2⁻⁴⁰, W = 1024` no valid `C_APT` exists below `H ≈ 0.03`, and the parameterization is only meaningful above `H ≈ 0.05` | DR-0002 "APT degeneracy floor" (added at ratification, amendment A2) | A property of the binomial tail at the chosen `α`/`W`, independent of which process measured `H` |
| Latch-and-gate health-test failure behavior: flag (sticky, write-1-to-clear), gate the **conditioned** path only, never gate the raw path, flush the FIFO on gate, mandatory start-up health test (1024 raw samples) before ungating | DR-0002 "Failure behavior" | An architecture/policy decision, not a measured one |
| The three-tier SP 800-90B claim discipline: Tier 1 "designed-for-90B" (raw access + continuous health tests + a documented entropy-source model + a declared conditioning class, all checkable pre-silicon), Tier 2 a **labelled, bounded, simulation-derived design estimate** (not an assessment), Tier 3 (validation proper) deferred to measured silicon | [DR-0004](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0004-sp-800-90b-path-pre-silicon.md) (**Ratified**) | This is a claims-discipline decision about what pre-silicon simulation can honestly support for *any* jitter-TRNG on *any* PDK — matches this repo's own `CLAUDE.md` framing ("simulation-derived entropy claims are provisional until silicon") verbatim, and should be adopted for the same reason it was adopted there |
| Behavioral/transistor verification-level split placed exactly at the raw tap: everything up to and including the raw tap is transistor-level (device physics matters — jitter, injection locking, metastability); everything downstream is a bit-exact behavioral model (Python), and a behavioral record may never be cited for a P/V/T-dependent claim | [DR-0009](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0009-behavioral-vs-transistor-verification-split.md) (**Accepted, delegated**) | A cost/methodology argument (a transistor-level run of a 256-sample conditioner block extrapolates to ~1.9 days; a 10⁶-sample entropy dataset to ~20 years — DR-0009's own table) that applies to any device-noise simulator, ngspice on sky130 included |
| Evidence-record discipline: append-only `sim/records/`, one record per (testbench, PVT point) not one aggregate grid record, every stochastic run states every seed, a `level:` field (`transistor`/`behavioral`/`gate`/`gate-simulation`) on every record, `superseded_by` rather than edit-in-place | [DR-0005](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0005-sim-harness-record-granularity.md) (**Accepted, delegated**), `sim/README.md`; gate-level additions [DR-0021](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0021-gate-level-timing-and-power-records.md)/[DR-0022](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0022-post-route-gate-level-simulation-records.md) | Pure evidence-hygiene convention; this repo's own `CLAUDE.md` ("`sim/` results are append-only evidence") already commits to the same discipline independently |

### 1.2 What transfers as a design *question to re-evaluate*, not a settled answer

These are choices gf180-trng made that are **not** device-physics facts, but
whose *reasoning* depends on a mix of process-independent logic and
gf180mcu-specific facts (available clocking, cell library contents, or
measured power). sky130-trng should read the reasoning, then check its own
premises before adopting the same conclusion — this is not a re-derivation
in the numeric sense of §2, but it is not a free carryover either.

- **Sampler clocked from a fixed external clock, not a divider on either
  entropy ring** — [DR-0012-sampler-fixed-external-clock](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0012-sampler-fixed-external-clock.md)
  (**Accepted, delegated**). The two reasons given — (a) a self-divided
  clock collapses the corner-metric to `Q ∝ σ₁/T₀`, which is unresolvable at
  a small PVT/seed grid, and (b) a ring-derived sample clock reintroduces a
  deterministic beat between the sampler and the signal it samples, the
  exact failure mode the array's non-integer frequency skew exists to avoid
  — are both architecture arguments, not gf180mcu-specific facts, and
  transfer directly. The alternative DR-0012 rejected on *this repo's
  specific budget* ("a third, dedicated free-running ring for clock
  generation... on top of an entropy array whose N=2 sizing was already
  driven to its floor by the power row") is exactly the kind of conclusion
  that must be re-checked once sky130's own N and power budget are known
  (§2.2) rather than assumed to reject the same way.
- **`sampler_dff`'s asynchronous reset gated into the storage loops' own
  inverters (the master's forward inverter and the slave's feedback
  inverter as NAND2s) rather than pull devices on the storage nodes** —
  [DR-0014](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0014-sampler-reset-gated-into-the-storage-loops.md)
  (**Accepted, delegated**). This is a cell-level circuit decision driven by
  a *measured* contention current on gf180mcu's specific `sampler_dff`
  transmission-gate topology (967 µW → 66 nW at nominal, a ~14,600×
  reduction). The **methodology** — measure reset-window contention current
  explicitly, per the specific storage-loop topology chosen, before assuming
  a brute-force reset is "free" — transfers; the **specific gating
  arrangement and its polarity argument does not**, because it is a property
  of gf180mcu's `sampler_dff` transmission-gate/latch circuit as drawn, and
  sky130's sampler cell (whether custom or built from `sky130_fd_sc_hd`
  primitives, see §2.4) has its own topology to re-derive this against. DR-0014's own "Alternatives considered" is worth reading in full before any
  sky130 sampler design starts — it records a specific, easy-to-walk-into
  wrong answer (gating the *feedback* rather than *forward* inverter defeats
  reset entirely in one clock phase) that is exactly the kind of mistake a
  quick re-implementation could repeat.
- **Metastability-hybrid tap kept as a stretch/secondary item, layered on
  the RO core rather than a free-standing source** —
  `spec/entropy-architecture-survey.md` §Recommendation 2,
  [DR-0011-metastability-hybrid-tap-claims-and-scope](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0011-metastability-hybrid-tap-claims-and-scope.md)
  (**Accepted, delegated**) for the claims discipline once built (a
  regeneration-time bound and a measured PVT-drift figure, never an entropy
  or histogram claim — full resolution-time statistics are judged
  not credibly reproducible in a general-purpose transient solver, and that
  judgment is tool-general, not PDK-specific). The scoping rationale
  transfers directly; whether to build it at all is unchanged as a stretch
  item, matching this repo's own README target table.

### 1.3 What is explicitly *not* being ported: the survey's superseded literature estimate

`spec/entropy-architecture-survey.md` (pre-DR-0007) recommended "a small
number (single digits)" of rings, a literature-informed plausibility figure
written before gf180-trng had any measured jitter. DR-0007 §3 explicitly
supersedes that count once measurement replaced the estimate — "This
supersedes the architecture survey's 'a small number (single digits)' of
rings... *on the count only*." This repo's port should read the survey for
its qualitative candidate comparison (why RO-jitter over metastability or
noise-amplification — see §2.1) and DR-0007 for the sizing *method*, but
must not cite the survey's ring-count language as if it were still current
even inside gf180-trng.

### 1.4 A worked illustration of why "re-derive, don't copy" is not a one-time step

gf180-trng's own history inside the window this plan was researched is the
sharpest available evidence for the repo's stated thesis. DR-0012 (accepted
2026-08-01) inferred the entropy-binding corner as `ss`/−40 °C/3.63 V from
three measured PVT points. [DR-0015](https://github.com/2AMLogic/gf180-trng/blob/f2ab01a/spec/decision-records/DR-0015-entropy-binding-corner-moves-to-the-hot-slow-corner.md)
(**Proposed**, 2026-08-02, not yet ratified) measured the full 27-point grid
and found the actual minimum-`Q` corner is `ss`/**+125 °C**/3.63 V instead —
the *opposite* temperature extreme — by 8%, because `Q ∝ T/(P·T₀²)` and a
66% period lengthening from −40 °C to +125 °C outweighs the extra thermal
noise and lower ring power. **This corner assumption inverted within the
same repository, on the same measured device family, after more PVT
coverage arrived** — it is not a one-time gf180-mcu-vs-sky130 gap to close
and then forget. sky130-trng inherits the obligation to run this same
full-grid check on its own devices (§2.4) rather than assuming either
gf180-trng's original guess or its later correction transfers by analogy.

---

## 2. What must be re-derived for sky130

Every item below currently rests on a gf180mcu **measurement**, not gf180mcu
device-independent analysis, so it cannot transplant. Each entry names the
gf180-trng evidence it displaces and the sky130-specific simulation evidence
that would close it — mirroring gf180-trng's own `sim/characterization-*.md`
+ `sim/records/*.md` pattern, not asserting a number here.

### 2.1 Supply / operating-envelope decision — resolved here, with rationale

This is the fork-in-the-road question CLAUDE.md and the issue both flag as
affecting "everything downstream," so it is answered explicitly rather than
left implicit, even though this document does not ratify a spec row.

**gf180mcu's envelope** (DR-0001…DR-0004's ratified basis): core logic
devices are `nfet_03v3`/`pfet_03v3`, a matched 3.3 V N/P pair, with 6.0 V
`nfet_06v0`/`pfet_06v0` I/O devices also available (`spec/entropy-architecture-survey.md`
§"PDK facts used"). The ratified target-spec envelope is 3.3 V ± 10%
(`README.md`'s "Operating envelope" row) — a single, symmetric core-device
supply, no I/O-vs-core split needed for the entropy source itself.

**sky130's device menu is structurally different, verified directly against
the installed `sky130A` PDK (open_pdks commit `c6d73a35`) for this plan**:

- The standard **core logic devices are `sky130_fd_pr__nfet_01v8` /
  `__pfet_01v8`** (plus `_lvt`/`_hvt` threshold variants) — a matched **1.8 V**
  N/P pair, confirmed BSIM4 (`level = 54.0`) via direct inspection of
  `sky130_fd_pr__nfet_01v8__tt.pm3.spice`.
- There is **no matched 3.3 V core pair**. The closest 3.3 V-class device is
  `sky130_fd_pr__nfet_03v3_nvt` — an **NMOS-only** "native"/thick-oxide
  device (no `pfet_03v3_nvt` exists in the installed PDK; confirmed by
  directory listing of `libs.ref/sky130_fd_pr/spice/`) — so a complementary
  3.3 V ring stage cannot be built from a symmetric core-device pair the way
  gf180mcu's `nfet_03v3`/`pfet_03v3` allows.
  \*\*This is a materially different fact than the "1.8 V core, 3.3 V I/O
  flavors available" framing in this repo's own `README.md`/`CLAUDE.md`
  implies\*\* — the 3.3 V option in sky130 is not a clean core-device
  alternative to 1.8 V; it is a single-polarity native device with a
  different intended use case (typically bias/cascode or ESD-adjacent
  circuitry), or the I/O-cell library below.
- 5 V/10.5 V-tolerant devices (`nfet_g5v0d10v5`/`pfet_g5v0d10v5`) and the
  `sky130_fd_io` I/O-cell library exist and are the PDK's actual route to a
  3.3 V-class *I/O domain* — sky130 I/O rings are conventionally configured
  1.8 V core / 3.3 V I/O using this library's multi-domain-capable pads, not
  a dedicated 3.3 V core transistor.
- Flicker/thermal noise **is** modeled in every corner (verified:
  `noia`/`noib`/`noic` + `tnoia`/`tnoib`/`rnoia`/`rnoib` populated with
  non-zero values, `fnoimod = 1.0`/`tnoimod = 1.0`, in
  `sky130_fd_pr__nfet_01v8__tt.pm3.spice`), so the TRNOISE-style
  jitter-characterization *mechanism* gf180-trng's survey validated for
  gf180mcu (§A.2 of `spec/entropy-architecture-survey.md`) is equally
  representable on sky130 — **but the parameterization differs**:
  gf180mcu's BSIM4 corner decks expose the classic SPICE2 legacy `kf`/`af`
  flicker terms; sky130's expose BSIM4's unified 1/f noise model
  (`noia`/`noib`/`noic`) plus separate thermal-noise coefficients
  (`tnoia`/`tnoib`/`rnoia`/`rnoib`). Any characterization script or
  `.noise`/`TRNOISE` setup ported from gf180-trng's harness must not assume
  `kf`/`af` exist in the sky130 model cards.
- The digital standard-cell library `sky130_fd_sc_hd` ships one combined
  transistor-level SPICE netlist (`sky130_fd_sc_hd.spice`, 437 subcircuits
  verified by direct grep) including drive-strength-scaled inverters
  (`inv_1`…`inv_16`) and reset flip-flops (`dfrtp_1`/`_2`/`_4` — `D`, `CLK`,
  active-low `RESET_B`, no integrated set) — a role directly analogous to
  gf180mcu_fd_sc_mcu9t5v0's `inv_*`/`dffnq`/`dffnrnq`/`dffnrsnq` cells the
  gf180-trng survey cited, though the exact flip-flop variant set differs
  (no ship-checked equivalent of `dffnrsnq`'s combined set+reset was found
  in this pass — re-verify if a set-and-reset variant is actually needed).

**Decision for this plan: target the 1.8 V core-device pair
(`nfet_01v8`/`pfet_01v8`) as sky130-trng's primary operating point,
deviating from the gf180-trng-mirrored README draft row ("supply per sky130
device flavor (1.8 V core, 3.3 V I/O devices available) — confirm before
ratification").**

Rationale:

1. It is the only sky130 device class with a **matched, symmetric N/P core
   pair** — required for a conventional inverter-chain ring oscillator the
   same way gf180mcu's `nfet_03v3`/`pfet_03v3` pair was used, per the
   survey's §A.3 device-availability argument. `nfet_03v3_nvt` cannot build
   a complementary ring stage alone.
2. It is the device class every open sky130 digital flow (the standard-cell
   library, the harness this repo's sibling `sky130-bandgap` already
   exercises) targets natively — keeping the entropy source's core devices
   and the digital conditioner/health-test standard cells on the same
   supply rail avoids a level-shifting requirement between the analog core
   and the digital section that gf180-trng's single-3.3V-domain design never
   had to solve.
3. It does **not** foreclose a 3.3 V I/O-domain interface (the register
   file / streaming port can sit behind `sky130_fd_io` at 3.3 V per the
   README's existing "3.3 V I/O devices available" framing) — only the
   entropy source's own ring/sampler core moves to 1.8 V.

This is stated here as the plan's working assumption, not a ratified spec
row — per this repo's `README.md`, "confirm before ratification," and per
`CLAUDE.md`, "agents do not relax the ratified spec to make results pass" (there
is no ratified spec yet to relax, but the same discipline applies
prospectively). **The evidence a future decision record needs to actually
ratify this**: an sky130-specific version of the architecture survey's §A.2
mechanism check (confirm `.noise`/`TRNOISE` on `nfet_01v8`/`pfet_01v8`
produces a usable jitter-accumulation signal) plus a first-cut ring
characterization at 1.8 V ± 10% before committing further design effort —
this is the sky130 analogue of gf180-trng's own issue #4 (RO delay-cell
jitter characterization), and should be filed as such rather than assumed.

### 2.2 Ring-oscillator jitter characterization and array sizing (`N`)

**What must be re-derived**: gf180-trng's DR-0007 sizing arithmetic
(`N₀ = 560` first-cut, later revised via the starved-cell constant in
DR-0010/DR-0011 to `N = 2` at eleven stages) is computed entirely from
gf180mcu-measured `σ₁`/`T₀` figures in
`sim/records/2026-07-31-ro-inv-05stage-jitter-*.md` and
`sim/records/2026-07-31-inv-stage-noise-*.md`. **None of these numbers are
portable to sky130** — they are the output of a device measurement, not the
sizing law itself (which does carry over, §1.1).

**Evidence needed to close it**: a sky130-specific rerun of the same
characterization campaign gf180-trng's issue #4 ran, i.e. the
transient-noise (`tran-noise`) jitter-accumulation testbenches over
`sky130_fd_pr__nfet_01v8`/`pfet_01v8` ring stages, at minimum the reduced
grid DR-0006 (**Accepted, delegated**) settled on for gf180mcu — a flagship
config at the full `{tt, ff, ss} × {−40, 27, 125 °C} × {nominal ± 10%}`
27-point grid, every other stage-count/topology variant at the 3 headline
points (nominal, fast/cold/high-supply, slow/hot/low-supply) — adapted to
sky130's own corner-bundle names (§3.1). DR-0006's cost/coverage argument
(a single seeded run at one PVT point took ~130–150 s on the gf180-trng
development machine) should be re-measured on sky130's own ngspice/PDK
combination before assuming the same reduced-grid trade-off is still
affordable, rather than copying the grid size unchanged.

### 2.3 Health-test cutoff numbers (not the formulas)

**What carries over**: the RCT/APT formula structure, `α = 2⁻⁴⁰`, `W = 1024`
(§1.1) — these are choices about false-alarm tolerance at a target sample
rate and a statistical test's structure, not about device noise.

**What must be re-derived**: the specific cutoff numbers in DR-0002's table
(`C_RCT = 81`, `C_APT = 824` at `H₀ = 0.5`) are **conditional on whichever
`H` sky130's own entropy source is eventually sized to hit at its own
entropy-binding corner** (§2.4) — they are not a gf180mcu-specific number to
replace with a sky130-specific one; they are a *formula evaluation* that
must be re-run once sky130's own `H` target and, later, measured `H` are
known. If sky130's array sizing lands on a materially different `H` design
target than `H₀ = 0.5`, DR-0002's APT degeneracy floor (no valid cutoff below
`H ≈ 0.03`, marginal below `H ≈ 0.05`) is exactly the structural risk to
re-check first, using the same table-generation method DR-0002's
"Independent verification" section used (exact binomial computation against
SP 800-90B §4.4.1/§4.4.2), before committing to any numeric cutoff.

**Evidence needed**: none beyond re-running the (portable) formula evaluation
once sky130's own `H` target is fixed — this is arithmetic, not a new
simulation campaign, but it is *sequenced* behind §2.2 and §2.4 and must not
be done first.

### 2.4 The entropy-binding corner itself

**What must be re-derived, and cannot be assumed by analogy even to
gf180-trng's own current answer**: §1.4 already shows gf180-trng's own
best-current answer (`ss`/+125 °C/3.63 V, per the still-**Proposed**
DR-0015) inverted an earlier, also-reasoned answer (`ss`/−40 °C/3.63 V, per
the **Accepted** DR-0012) once a fuller PVT grid existed. The *mechanism*
DR-0015 exposes — under a fixed external sample clock, `Q ∝ σ₁²/T₀³`, and
whether the coldest or hottest corner of the slow-process/high-voltage edge
wins depends on how period lengthening (`1/T₀²`, favors hot) trades against
higher thermal noise and lower ring power (favors hot) versus faster edges
at the same process corner (favors cold) — is process-independent and worth
porting as an analysis *method*. But which sky130 corner actually wins that
trade is an open, sky130-specific empirical question, not something this
plan or any document can answer without sky130's own measured `σ₁(T₀)` at
every corner sky130-trng's characterization campaign covers.

**Evidence needed**: the sky130 analogue of gf180-trng's
`sim/tb/ro-array-core-pvt-q/` — per-ring period and supply current measured
at every point of whatever PVT grid sky130-trng adopts (§3.1), reduced to
`Q` via the array sizing law (§1.1), with the minimum identified explicitly
rather than assumed from the gf180mcu direction (cold) or the gf180mcu
correction (hot) — sky130's own ring topology and corner set could differ
from both.

### 2.5 Power / idle-current budget, and where the leakage actually lives

**What transfers**: the diagnostic *method* DR-0017 (**Proposed**) used —
separately measuring the analog entropy-source block's leakage
(`sampler_core` at the idle bias, 32.8 nA on gf180mcu — 3.3% of the ratified
`< 1 µA` idle row) against the digital section's *estimated* ungated
standard-cell leakage (4.43 µA — 442% of the same row, from `design/digital_power_estimate.py`,
not yet measured) is a diagnostic split worth reusing: **do not assume the
analog entropy core is where an idle-power miss comes from** without first
separating it from the digital section's leakage, since on gf180mcu it was
overwhelmingly the latter.

**What must be re-derived**: sky130's leakage character at its own
process/temperature corners is unrelated to gf180mcu's — `sky130_fd_sc_hd`'s
cell-level leakage figures, and sky130_fd_pr's off-state device leakage at
`ff`/+125 °C-equivalent corners, are both sky130-PDK facts with no gf180mcu
analog. DR-0014's contention-current lesson (§1.2 — a brute-force reset
circuit can dominate a power budget by orders of magnitude through a
mechanism invisible until specifically measured) is a methodology warning
worth carrying forward regardless of the final sky130 sampler topology.

**Evidence needed**: an sky130-specific idle/leakage characterization
campaign mirroring `sim/characterization-startup-and-power-budget.md` and
`sim/characterization-supply-current-and-leakage.md` — per-block idle
current at sky130's own worst-leakage corner (process-fast/cold-or-hot per
whatever sky130's own leakage-vs-temperature-and-corner behavior turns out
to be — do not assume gf180mcu's `ff`/+125 °C direction transfers without
checking), separately for the entropy-source analog block and the digital
conditioner/health-test/interface section.

### 2.6 What is explicitly *not* re-derived from a gf180mcu number, because none exists yet in gf180-trng either

Two gf180-trng rows are themselves still **Proposed**, not **Accepted** or
**Ratified**, as of the pinned commit: the raw-rate value (DR-0010/DR-0011,
moved from the ratified `> 1 Mbps` target down to a measured-jitter-energy
figure, currently proposed at 2 kbps) and the area row
(DR-0019/DR-0020, a 2.7× miss against the ratified `< 0.05 mm²` budget, tied
to FIFO depth). sky130-trng should **not** treat either as a settled number
to port *or* to avoid — both are live evidence that gf180-trng's own rate ×
entropy ×power×area operating point has not converged, and sky130's version
of the same tension (which may resolve differently, given a different
supply and a different standard-cell area/leakage profile) needs its own
sizing pass rather than inheriting an unresolved gf180mcu answer either way.

---

## 3. Verification plan

### 3.1 PVT corner set for sky130

sky130's installed PDK (`sky130A`, open_pdks commit `c6d73a35`, verified via
direct inspection for this plan) exposes named process-corner sections
`tt`/`ss`/`ff`/`sf`/`fs` for the core MOS/BJT devices — the same five-corner
naming gf180mcu's harness uses — plus resistor/capacitor-specific skew
corners (`ll`/`hh`, and `hl`/`lh`/mismatch sections) that gf180mcu's harness
does not need in the same form. This repo's sibling **`sky130-bandgap`**
already runs a working ngspice/sky130 PVT harness against exactly this PDK
pin (`sim/pdk.json`: `sky130A`, `open_pdks_commit: c6d73a35...`,
`process_corners: [tt, ss, ff, sf, fs, ll, hh]`) with a corner-runner
(`sim/bin/corner-run.py`) and an evidence-record convention explicitly
modeled on gf180-bandgap's — i.e., **the same "bootstrap the harness from a
sibling repo" move gf180-trng's own DR-0005 made** (from `gf180-bandgap#23`)
is directly available here, from `sky130-bandgap`, rather than needing to be
invented.

Proposed grid, following DR-0006's reduced-grid *methodology* (not its
specific point count, which was gf180mcu-cost-derived — §2.2):
`{−40, 27, 125} °C × {process nominal ± 10% supply} × {tt, ff, ss}` as the
flagship full grid, with `fs`/`sf` dropped for the same reason DR-0006 gave
(a uniform per-stage injected-noise source in a ring testbench makes N/P
drive-strength asymmetry primarily a duty-cycle effect, not a period-jitter
one) unless sky130's sampler design turns out to be duty-cycle-sensitive
(DR-0006's own "Follow-up required" flagged exactly this for gf180-trng once
an edge-triggered sampler was added — re-check it here too once sky130's
sampler is designed, per §2.4's DR-0015 precedent of `fs`/`sf` still being
an open gap even in the source repo).

### 3.2 Testbench inventory to port from gf180-trng's harness

Splitting gf180-trng's `sim/tb/` + `sim/harness/` inventory the same way
DR-0009 splits verification levels:

**Process-independent tooling (port with adaptation, not a re-run)**:
- The harness architecture pattern itself: PDK-path resolution order, named
  corner bundles, `.temp`/`.lib`/`.include`/`.control`/`.endc`/`.end`
  testbench-fragment contract (DR-0005) — `sky130-bandgap`'s harness is
  already this repo's closer analog than gf180-bandgap's, so bootstrap from
  it directly rather than from gf180-trng's harness a second remove.
- `sim/README.md`'s record format and the append-only/no-seed-no-evidence
  rules (DR-0005, §1.1) — a metadata convention, no PDK dependency.
- The `level:` field discipline and behavioral-record rules (DR-0009) —
  applies verbatim once sky130-trng has a conditioner/health-test digital
  section to model behaviorally.
- The gate-level (`level: gate`/`gate-simulation`) record conventions
  (DR-0021/DR-0022) once/if a synthesis+STA flow exists for sky130-trng's
  digital section.

**Device-physics testbenches (re-run on sky130 devices, not ported as
evidence)**: every `tran-noise` jitter-accumulation deck
(`ro-inv-*stage-jitter`, `ro-cinv-*stage-jitter`, the flicker/lownoise
sensitivity checks, `trnoise-calibration`), the array-level `Q`/power
testbenches (`ro-array-core-power`, `ro-array-core-pvt-q`), the
sampler-specific setup/hold/metastability and reset-current testbenches
(`sampler-dff-setup-hold`, `sampler-dff-reset-current-{xsv,xsb}`,
`sampler-dff-reset-clocked`), and the liveness-tap phase-cost/bit-bias
family (`ring-liveness-tap-power`, `ring-liveness-tap-phase-*`,
`sampler-bit-bias-*`, `array-liveness-tap-phase-*`) if sky130-trng adopts
the equivalent per-ring liveness monitor (§1.2/DR-0016, itself still
**Proposed** in the source repo). These testbench *structures* (what to
measure, at what corners, with what seed count) are worth copying as a
checklist; their *netlists* must be rebuilt against sky130 device models
and their *recorded results* start from zero.

**Behavioral testbenches (port the model + equivalence-test pattern, not
the numbers)**: the conditioner (`conditioner-crc32` if sky130-trng adopts
the same non-vetted CRC-32/LFSR conditioner this repo's README target table
already mirrors from DR-0008), the RTL/behavioral-model equivalence-check
pattern (`sim/tests/test_conditioner.py`, DR-0009 rule 5), and the
declared-synthetic-source convention for driving digital-block testbenches
before a real captured raw bitstream exists.

### 3.3 Entropy / statistical evidence plan

Adopt DR-0004's three-tier structure and DR-0009's behavioral/transistor
split unchanged as *policy* (both already match this repo's own `CLAUDE.md`
framing, §1.1):

1. **Tier 1 (designed-for-90B, pre-silicon-checkable by inspection)**: raw
   access + continuous RCT/APT + a documented entropy-source model (naming
   sky130's own noise mechanism, entropy-relevant nodes, and deterministic-
   coupling risks — DR-0004 itself flags this as the one Tier-1 item
   gf180-trng never assigned a single accountable issue to; sky130-trng
   should not repeat that gap) + a declared conditioning class.
2. **Tier 2 (sim-stage min-entropy estimate)**: bounded 90B-style estimators
   (IID + non-IID suite) applied only to the extent an affordable simulated
   bit count supports, with confidence degradation stated explicitly; a
   target of ≥ 10⁶ consecutive raw samples where cost permits, else the
   largest affordable N with an explicit statement of what that N does and
   does not support; the restart dataset explicitly deferred to silicon
   (DR-0004's own reasoning — ~1000 independent power-on restarts is a
   silicon-measurement question, not a transient-noise-simulation one);
   **every number mandatorily labeled** "simulation-derived design estimate;
   not an SP 800-90B entropy assessment," reported at the sky130-specific
   worst-corner `H` from §2.4, never at nominal.
3. **Tier 3 (validation proper)**: explicitly deferred to measured silicon,
   matching this repo's own maturity ladder (`README.md`: "…→ shuttle seat →
   measured silicon. **Current position: pre-spec.**").

Statistical test batteries this Tier-2 work should run on simulated
bitstreams (per this repo's `CLAUDE.md`: "statistical test suites (e.g. NIST
SP 800-22-style batteries) run on simulated bitstreams") should follow
DR-0004/DR-0009's discipline: 90B's IID track and non-IID estimator suite
first (since the design's own health tests and Tier-2 claim are already
90B-shaped), with an SP 800-22 battery as a secondary/complementary check on
whatever simulated bitstream length is affordable — treating both, like
DR-0004 already insists, as **provisional pre-silicon indicators**, never as
a pass/fail certification claim.

---

## 4. Deviations from the README draft target table — stated and why

Per this repo's own `README.md` ("Where sky130's devices make a target
inappropriate rather than merely harder, change it and record why"):

| Row | README draft (mirrors gf180-trng) | This plan's finding | Why |
|---|---|---|---|
| Operating envelope | "supply per sky130 device flavor (1.8 V core, 3.3 V I/O devices available) — confirm before ratification" | **Confirmed, with a correction to the underlying premise**: sky130 has no matched 3.3 V core N/P device pair (only an NMOS-only `nfet_03v3_nvt` native device); the entropy source's core devices should target the 1.8 V `nfet_01v8`/`pfet_01v8` pair, with 3.3 V reachable only via the I/O-cell library, not a core-device alternative | §2.1. A future spec ratification should correct "3.3 V I/O devices available" to name the I/O library specifically, not imply a symmetric 3.3 V core option exists |
| Raw min-entropy per bit, Health tests | `H₀ = 0.5` as a sizing target; RCT/APT cutoffs "re-derived from sky130 noise/leakage corners, not copied from gf180" | Not changed here — the README row is already correctly hedged. This plan adds: the *cutoff formulas* carry over unchanged (§1.1); only the *cutoff numbers* and the entropy-binding corner they're evaluated at are open (§2.3, §2.4) | No deviation — confirming the existing hedge is correctly scoped |
| Power | "< 500 µW active; idle target set after a sky130 leakage survey" | Not changed here — already correctly hedged as pending a survey. This plan adds the diagnostic method (§2.5: separate analog-core leakage from digital-section leakage before attributing a miss) | No deviation |
| Entropy source | "N-way array... N re-sized from a jitter budget at the entropy-binding corner" | Not changed — this is exactly DR-0007's sizing law (§1.1), already correctly reflected in the README's own wording | No deviation |

No other README target-table row is changed by this plan. Everything else
(raw-rate structural definition, quality-tier structure, conditioning
approach, interface shape) is carried over per §1.1 without modification.

---

## 5. Open questions this plan deliberately leaves open

These are named so a future decision record addresses them explicitly rather
than by accident:

1. Does sky130-trng adopt the per-ring liveness monitor (DR-0016) given it
   is still **Proposed**, not accepted, in gf180-trng itself?
2. Does sky130-trng adopt the per-ring output buffer (DR-0018, **Proposed**)
   that gf180-trng found removes 96.5% of a clk-locked phase-coupling cost
   discovered only after the liveness tap was added — or does sky130's
   sampler/tap design avoid that coupling mechanism differently?
3. What raw-rate target does sky130's own array sizing (§2.2) actually
   support, given gf180-trng's own rate target is unresolved (DR-0010/
   DR-0011, both **Proposed**, §2.6) and this repo's README currently
   mirrors the *ratified* `> 1 Mbps` figure rather than either proposal?
4. Vetted vs. non-vetted conditioner: DR-0004's default (non-vetted,
   area-driven) and DR-0008's specific choice (CRC-32/LFSR, K=8) both
   transfer as a *starting assumption* (§1.1), but sky130's own area budget
   and standard-cell area-per-gate figures have not been checked against it.

None of these is resolved by this document — each is exactly the kind of
question a future `spec/decision-records/DR-000N-*` should answer once its
own simulation evidence exists, following the same pattern gf180-trng used
throughout: propose in an issue/PR, record the decision and its evidence,
ratify (or not) via the operator.

---

## References

- gf180-trng, pinned at commit `f2ab01a` (`main`, fetched 2026-08-20T16:37Z):
  - `spec/README.md`, `spec/entropy-architecture-survey.md`,
    `spec/ratification-2026-07-31-target-spec.md`
  - `spec/decision-records/DR-0001` … `DR-0022` (24 files, two renumbering
    collisions noted in-place per each file's own Status section)
  - `sim/README.md`, `sim/characterization-*.md` (13 documents)
- sky130A PDK, open_pdks commit `c6d73a35f524070e85faff4a6a9eef49553ebc2b`
  (installed via `volare`), inspected directly for this plan:
  `libs.ref/sky130_fd_pr/spice/sky130_fd_pr__nfet_01v8__tt.pm3.spice`,
  `libs.ref/sky130_fd_pr/spice/` (device-flavor directory listing),
  `libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice`.
- `2AMLogic/sky130-bandgap`, `sim/pdk.json` and `sim/README.md` — the
  sibling repo's already-working sky130 ngspice PVT harness, cited here as
  the sky130-side analog of gf180-bandgap's role in gf180-trng's DR-0005.
- Baudet, Lubicz, Micolod, Tassiaux, "An Improved Analysis of Jitter-Based
  Random Number Generators," CHES 2011 (cited via DR-0007).
- Sunar, Martin, Stinson, "A Provably Secure True Random Number Generator
  with Built-In Tolerance to Active Attacks," IEEE Trans. Computers, 2007;
  Markettos & Moore, "The Frequency Injection Attack on Ring-Oscillator
  RNGs," CHES 2009 (both cited via `spec/entropy-architecture-survey.md`).
