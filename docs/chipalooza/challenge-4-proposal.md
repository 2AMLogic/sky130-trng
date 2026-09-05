# Chipalooza Challenge #4 proposal — sky130 TRNG entropy source

**Program:** Open Circuit Design Chipalooza Challenge #4 (Sky130 / ChipFoundry).
Per [2AMLogic/2am#542](https://github.com/2AMLogic/2am/issues/542) (the
tracking epic), Challenge #4's own rules page (`rules-4.html`) is
**unpublished as of this document's date** (launches 2026-11-09; today is
2026-09-05). This document assumes the common structure `rules-2.html` /
`rules-3.html` describe, applied to Sky130's own native rails, per the epic's
own tracking table and per this repository's issue #18. When `rules-4.html`
publishes, a follow-up issue reconciles the slot-budget assumptions below
against the real brief — nothing here should be read as final until then.

**Re-verified 2026-09-05 (issue #18, second increment).**
`https://opencircuitdesign.com/chipalooza/rules-4.html` still 404s — the
rules page itself remains unpublished, so criterion 4 stays N/A and none of
the slot-budget assumptions above have anything new to reconcile against.
While checking, though, the site's own Challenge #4 landing page
(`https://opencircuitdesign.com/chipalooza/challenge-4.html`, live,
`Last-Modified: 2026-08-23`) now states **"Expected launch: November 9,
2027 (estimate)"** — one year later than the `2026-11-09` date this
document, issue #18, and the epic's own tracking table have been assuming.
The site is self-inconsistent about this: `chipalooza/index.html`'s
schedule table still lists Challenge #4 as launching `Nov 9, 2026`. Both
pages agree the challenge "has not launched yet" and no rules exist yet, so
nothing here changes as a result — but the 2026-vs-2027 launch-date
discrepancy is itself a delta worth flagging upstream (in the epic, not in
this document) before anyone schedules follow-up work against the
assumption that Challenge #4 opens in November 2026.

**Repository:** [`2AMLogic/sky130-trng`](https://github.com/2AMLogic/sky130-trng) —
public, Apache-2.0.

## Status of this repository — read this before anything below

**Pre-layout, pre-digital-section.** The entropy source (an `N = 4`, five-stage,
free-running ring-oscillator array, XOR-combined) and its sampler are drawn
as SPICE schematics and characterized across PVT at the transistor level
(`sim/`). Nothing downstream of the raw tap exists: **no conditioner, no
health-test module, and no register/streaming interface** —
[`design/README.md`](../../design/README.md)'s own "Deliberately not here"
section names all three as out of scope for this repository today, not
merely unfinished. No synthesis has been run, `layout/` is empty, and no
DRC/LVS has ever been attempted. Every decision record cited below
(DR-0001, DR-0002, DR-0003) carries status **Proposed** — drafted, not yet
accepted by an operator.

This is a materially earlier maturity point than the sibling
[`gf180-trng`](https://github.com/2AMLogic/gf180-trng) repository's own
Challenge #3 proposal, which already had a full register interface, health
tests, and a conditioner (even though its own layout was not yet composed
into one whole-block GDS either). **This document is not a submission-ready
package the way that sibling document was written to be.** It is this
issue's own deliverable: an honest, `sim/`-cited snapshot of where this
design stands against the Challenge #4 brief's assumed structure, naming
every gap between here and a submittable design rather than glossing over
it — per this repository's `CLAUDE.md`: "no claim without a testbench" and
"agents do not relax the ratified spec to make results pass." Layout,
DRC/LVS-clean GDS, and post-layout PVT simulation — the brief's full
sign-off bar — do not exist in this repository and are **not** claimed here;
they are named as explicit follow-up work at the end of this document.

---

## 1. Type of IP block

A digital true-random-number-generator **entropy source** (not a DRBG): a
four-ring, XOR-combined, free-running ring-oscillator array feeding a
fixed-external-clock sampler. No conditioner, no health tests, and no
register interface exist yet — see §3.

---

## 2. I/O list

`design/trng_top.spice`'s generated netlist (from
[`design/xschem/trng_top.sch`](../../design/xschem/trng_top.sch)) has 16
ports today: `en1..en4`, `vddr1..vddr4`, `vdd`, `vss`, `clk`, `rst_n`,
`raw_bit`, `raw_valid`, `ring_bit1..ring_bit4`. That is not a register-bus
SoC interface the way gf180-trng's `trng_interface` is — there is no bus to
reduce here, because no interface has been designed yet. What follows maps
these existing pins onto the Challenge #4 slot budget directly, and is
explicit about what a Challenge #4 slot would need that this repository does
not yet have.

### 2.1 Budget summary

| Resource | Assumed Challenge #4 budget | Requested | Headroom |
|---|---|---|---|
| Digital control inputs | ≤ 24 | **6** | 18 spare |
| Digital test outputs | ≤ 12 | **6** | 6 spare |
| Shared (multiplexed) analog lines | ≤ 4 | **1** | 3 declined |
| Bandgap-referenced current sources | ≤ 2 | **0** | 2 declined |
| Bandgap-referenced bias voltage | offered | **declined** | not needed |
| Dedicated pads | ≤ 4 | **3** | 1 spare (reserved, §2.5) |

### 2.2 Digital control inputs (6 of 24)

| Pin | Width | Maps to | Purpose |
|---|---|---|---|
| `clk` | 1 | `trng_top.clk` | Sampler clock — **fixed external**, 50 kHz per [DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md) (status Proposed); deliberately not divided down from either ring. |
| `rst_n` | 1 | `trng_top.rst_n` | Asynchronous power-on reset, active low. |
| `en1` | 1 | `trng_top.en1` | Ring 1 enable; `en = 0` stops that ring in a static state. |
| `en2` | 1 | `trng_top.en2` | Ring 2 enable. |
| `en3` | 1 | `trng_top.en3` | Ring 3 enable. |
| `en4` | 1 | `trng_top.en4` | Ring 4 enable. |

`en1..en4` double as a bench fault-injection hook (drive one ring's enable
low, observe the effect on the combined output and on that ring's own
`ring_bitN` test output, §2.3) — there is no dedicated liveness-monitor
circuit to exercise yet, because none exists (§3), but the same enable pins
this array already has for normal operation serve that purpose without any
new RTL. 6 of 24 used, 18 spare — none of it earmarked, because the digital
control-input needs of the not-yet-designed conditioner/health-test/
interface section (§3, §5.3) are unknown until that section is designed.

### 2.3 Digital test outputs (6 of 12)

| Pin | Width | Maps to | Purpose |
|---|---|---|---|
| `raw_bit` | 1 | `trng_top.raw_bit` | The entropy-evidence pin (§5.2): one raw, undecimated sample per `clk` edge, straight off the sampler's raw tap — after digitization, before any post-processing (there is no post-processing). |
| `raw_valid` | 1 | `trng_top.raw_valid` | Strobes `raw_bit`: asserts one `clk` edge after `rst_n` releases and stays high (there is no start-up test gating it, §3). |
| `ring_bit1` | 1 | `trng_top.ring_bit1` | Ring 1's own digitized sample. `design/README.md` scopes these as "block-internal, not read off-die" for an SoC integration — bringing them out here is a **new use this proposal introduces, not an existing design decision**, useful for the fault-injection bench step in §5.2 and for a first ring-vs-ring silicon comparison. |
| `ring_bit2` | 1 | `trng_top.ring_bit2` | Ring 2. |
| `ring_bit3` | 1 | `trng_top.ring_bit3` | Ring 3. |
| `ring_bit4` | 1 | `trng_top.ring_bit4` | Ring 4. |

**No conditioned output, no health-test alarm, no status/ready bits exist**
to offer as test outputs, because none of that circuitry has been designed
(§3). 6 of 12 used, 6 spare — reserved, not declined, for whatever the
digital section eventually needs (a conditioned-stream tap and a health-test
alarm output are the two most likely claimants, by direct analogy with
gf180-trng's own pinout, once that section exists).

### 2.4 Shared analog lines (1 of 4 used)

| Pin | Purpose |
|---|---|
| `ro_mon` | **Not yet implemented — an open item, not a committed pin.** A buffered analog monitor of the combining node `xo` (or, muxed, of an individual pre-buffer ring node), for a direct bench measurement of the frequencies in Row A (§4) and of jitter, independent of the digital sampler. Needs a low-resistance, high-bandwidth pad — the frequencies of interest run into the low gigahertz (§4 Row A), not a standard ESD-clamped digital pad's characterized passband. No buffer/mux wrapper exists in `design/xschem/` today; this line is requested by analogy with gf180-trng's own `ro_mon` pin, not because the wrapper RTL exists. |

The remaining 3 of 4 shared-analog slots are declined.

### 2.5 Dedicated pads (3 of 4 used, 1 spare)

| Pad | Purpose |
|---|---|
| `vdd` | Block supply — ring buffers, XOR combiner, sampler flip-flops. |
| `vss` | Block ground. |
| `vddr` | **Tied combination of the array's four independent per-ring supplies** (`vddr1..vddr4`). See the note below — this is a real capability loss, not a cosmetic simplification. |

**Dropped:** `ro_array_core`'s four independent per-ring supply pins
(`vddr1..vddr4`) are tied together onto the single `vddr` pad above to fit
the 4-pad budget. Per
[DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md)
§5, per-ring supply routing is an explicit **independence requirement** for
this array — separate rings are not supposed to share supply impedance —
and it "doubles as the per-ring liveness observation point": DR-0003 §5
measures each ring's own running-vs-stopped supply current (4.98–20.55 µA
running; 0.6 nA–255 nA stopped, an ~80–8800× contrast depending on corner)
specifically so a dead ring is separately observable from a live one on its
own supply current. Tying the four rails together for the test-chip slot
removes that per-ring *current*-based observability entirely; the
`ring_bit1..4` test outputs in §2.3 (bit-level, not current-level) are a
partial mitigant, not a replacement — they show whether a ring is toggling,
not how much current it draws while doing so. This is the same shape of
trade gf180-trng's own Challenge #3 proposal made (tying its two per-ring
supplies together), but with twice the ring count here, so the same
trade-off costs more.

The fourth pad is left **spare and reserved**, not requested, because the
not-yet-designed digital section (§3) may need its own supply pin (a
digital/analog domain split, or a level-shifted 3.3 V I/O-domain interface
per DR-0001's own "Consequences" section) that cannot be sized before that
section is designed.

### 2.6 Bandgap-referenced bias voltage / current sources: declined

This design needs neither. The ring array's frequency-setting element is a
fixed-geometry series "starve" device (`Mph`/`Mnt` in
[`design/xschem/ro_stage.sch`](../../design/xschem/ro_stage.sch) and
[`ro_nand2.sch`](../../design/xschem/ro_nand2.sch), starve length `lstv` =
2 µm, starve width `wstv` = 0.42–0.48 µm across the four rings, both fixed
geometry values — see `design/README.md`'s "Provisional, not sized" table)
— not a voltage-controlled current mirror referenced to an external
bandgap. No net anywhere in `design/*.spice` or `design/xschem/*.sch` is a
bias or bandgap input. We ask that the shared bandgap/current-source budget
be allocated to another Challenge #4 entry.

---

## 3. Functional description

The block is an **entropy source only** — no DRBG, no seeding, no
reseeding semantics; an integrator supplies its own DRBG downstream.

**Entropy source.** Four independent, free-running ring oscillators
(`ro_ring5`, five series-starved stages each, `wstv` skewed 0.42–0.48 µm in
four 0.02 µm steps so the four rings run at deliberately non-integer-ratio
frequencies), each isolated from the rest of the circuit by its own
minimum-width, unstarved output buffer (`ro_buf`), then XOR-combined
(3× `xor2`, a balanced depth-2 binary tree) into a single node (`xo`). The
entropy mechanism is accumulated oscillator phase jitter from thermal/
flicker device noise, not a metastability tap — the metastability-hybrid
alternative is explicitly out of scope for this port
([`spec/porting-plan.md`](../../spec/porting-plan.md) §1.2).

**Sampler.** A flip-flop pair per tap (`sampler_dff`, a transmission-gate
master-slave D flip-flop with asynchronous active-low reset) digitizes the
combined `xo` node — plus, separately, each of the four per-ring nodes
(`ring_bit1..4`) — on a **fixed external clock** (`clk`, 50 kHz per
DR-0003), deliberately decoupled from the rings' own free-running
frequency.

**Health tests, conditioner, interface: none exist.** Unlike gf180-trng
(continuous RCT/APT, a start-up test, a per-ring liveness monitor, a
non-vetted CRC-32 conditioner, and a word-addressed register file with a
streaming port), this repository has designed none of that downstream
circuitry yet. `design/README.md`'s "Deliberately not here" section states
this explicitly: "The analog/digital verification boundary is drawn at the
raw tap: everything up to and including `raw_bit` is transistor-level,
everything downstream is a behavioural model plus RTL. None of it exists in
this repo yet, and drawing it as SPICE subcircuits would fabricate netlists
for circuits nobody has designed." `spec/porting-plan.md` §1.1 identifies
which of gf180-trng's health-test *formulas* (RCT/APT parameterized by `H`,
the SP 800-90B three-tier claim discipline, the raw/conditioned two-path
convention) carry over as process-independent methodology once this section
is eventually designed — but naming a formula as portable is not the same
as having built the circuit, and none of it is built.

---

## 4. Target specification

**Every row below is re-derived directly from this repository's `sim/`
results**, citing the decision record that reduces them where one exists.
No row is copied from gf180-trng or from the README's own draft table
without a sky130-specific citation.

| # | Parameter | Min | Typ | Max | Target (README draft) | Binding corner | `sim/` / DR citation | Verdict |
|---|---|---|---|---|---|---|---|---|
| A | Combining-node (`xo`) toggle frequency, assembled `N = 4` array | 530.2 MHz | 944.0 MHz | 1516.7 MHz | not itself a ratified row (feeds row B) | min: `ss`/−40 °C/1.62 V; typ: `tt`/27 °C/1.8 V; max: `ff`/−40 °C/1.98 V | `sim/ro-array-core-combining/records/20260825-{094545,094718,094856}-53f1f7a.md` | Measured, supplementary |
| B | Raw sample rate, sustained at the raw tap | — | 50 kbps (chosen operating point) | — | Draft: **> 1 Mbps** (stretch: > 4 Mbps) | architectural ceiling ~78 kbps at any array size, binding at `ff`/−40 °C/1.98 V (fastest loaded corner, not the entropy-binding one) | [DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md) §1–3 (status Proposed); `sim/xor-combining-bandwidth/`, `sim/ro-array-operating-point/` | **Unmet** — DR-0003 retires the README's draft `> 1 Mbps` row as *architecturally unreachable at this topology*, not merely expensive: the XOR combining gate's own bandwidth caps any array size at ~78 kbps, roughly two orders of magnitude below the draft target. The 50 kbps operating point drawn here sits below even that ceiling for margin. DR-0003 is Proposed, not ratified — the README's rate row has not moved yet. |
| C | Raw min-entropy per bit | — | — | — | Design target: `H0 = 0.5` bit/sample (a sizing input, per DR-0002/DR-0003, not a claim) | n/a — no bitstream has been simulated | none — **no `sim/` record digitizes an actual noise-driven raw bit anywhere in this repository** | **Unmet/TBD, more fundamentally than a "not yet measured" caveat**: every `sim/` record under `ro-ring-jitter-accumulation/`, `ro-array-sizing/`, `ro-array-core-combining/`, etc. measures oscillator period/swing/jitter statistics ($\sigma_1$, $T_0$) or deterministic (noise-off) currents — none of them runs `sampler_dff` against a noise-injected ring and records the resulting 0/1 sequence. Not even a preliminary point estimate exists yet, unlike the sibling gf180-trng repository's own (explicitly-caveated) MCV estimate. |
| D | Active power, array only (rings + buffers + XOR; excludes sampler and any digital section) | 81.0 µW | — | 431.6 µW | < 500 µW | min: `ss`/−40 °C/1.62 V; max: `ff`/−40 °C/1.98 V | [DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md) §7; `sim/ro-array-core-combining/` | **Unmet/TBD as a whole-block claim.** The array term alone (431.6 µW worst-measured) already consumes 86.3% of the 500 µW budget, with the 6× `sampler_dff` instances (unsimulated — DR-0003's own "Follow-up required" lists this gap) and the entire not-yet-designed digital section still to add. gf180-trng's own experience is a direct warning here: its synthesized digital section alone cost 712.4 µW, more than this entire budget row by itself. This row should not be read as "passing" — it is an array-only partial measurement against a whole-block target. |
| E | Idle current, per ring (stopped) | 0.6 nA | — | 255 nA | not yet set — `spec/porting-plan.md` §2.5's leakage survey has not run | min: cold; max: `ff`/125 °C | `sim/ro-ring5-swing-and-current/` | No target exists to grade against. Reported because it exists now and did not before; excludes sampler/digital-section idle current, all unmeasured. |
| F | Time-to-first-valid | — | — | — | not stated | n/a | none — no start-up test exists | **N/A — architecture not yet designed.** There is no start-up health test (§3), so there is nothing for this row to measure yet. |
| G | Digital section max clean sample-clock frequency (`Fmax`) | — | — | — | supplementary, informative only | n/a | none — no synthesis has been run against `sky130_fd_sc_hd` | **N/A — no digital section exists to synthesize.** |
| H | Health-test cutoffs (RCT / APT) | — | — | — | formula-derived once `H` is measured | n/a | none — the *formulas* are identified as portable methodology in `spec/porting-plan.md` §1.1, but no health-test circuit or parameter computation exists in this repo | **N/A — not yet designed.** |
| I | Area, array only (rings + buffers + XOR; device-count estimate, no layout) | 0.0026 mm² | — | 0.0088 mm² | < 0.05 mm² | n/a (not PVT-dependent) | [DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md) §7 | Array-only estimate sits at 5–18% of budget — but excludes the sampler, any digital section, and actual layout (`layout/` is empty). **Not a whole-block claim; not a layout measurement.** |
| J | Architectural raw-rate ceiling (XOR combining-gate bandwidth), any array size | — | — | ~78 kbps | informative only — the hard constraint row B's operating point is chosen against | `ff`/−40 °C/1.98 V | [DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md) §1–2; `sim/xor-combining-bandwidth/` | Measured. This is the figure that forces row B's verdict — no amount of array resizing raises it; only redesigning the combining gate (wider devices, a different tree) would (DR-0003's own "Follow-up required"). |

### Rail-routing note (mirrors gf180-trng's own VDDA gap, opposite direction)

**This design's entropy source and sampler are built entirely from sky130's
1.8 V core device pair** (`sky130_fd_pr__nfet_01v8`/`__pfet_01v8`), per
[DR-0001](../../spec/decision-records/DR-0001-sky130-operating-envelope.md)
(status Proposed). Sky130 ships no matched 3.3 V core N/P pair — DR-0001
verified this directly against the installed PDK and rejected the two
alternatives that exist (`nfet_03v3_nvt` is NMOS-only with no complementary
`pfet_03v3_nvt`; the 5 V/10.5 V-tolerant `g5v0d10v5` I/O-class pair is
matched but optimized for tolerance, not the noise/speed behavior a jitter
TRNG depends on, and biasing it at 3.3 V would need a re-characterization
from scratch that has no evidence in `sim/` today).

If the Challenge #4 brief follows the "1.8 V digital / 3.3 V analog" rail
split this repository's issue #18 assumes from `rules-2.html`/`rules-3.html`'s
structure, this design's own analog entropy source wants to sit on the
**1.8 V digital rail**, not the 3.3 V analog rail — the mirror image of
gf180-trng's own Challenge #3 gap (where its analog block wanted the 3.3 V
digital rail instead of the 5.0 V analog rail). The root cause is the same
in both cases: neither PDK ships a device pair matched to the brief's
assumed analog-rail voltage for this topology.

**Request:** route `vdd`/`vddr` (§2.5) from the harness's 1.8 V digital
rail rather than its 3.3 V analog rail. If the program instead requires
every seat's analog pads to sit at 3.3 V, the options are, before any
schematic-review gate Challenge #4 defines: (a) migrate to sky130's
`g5v0d10v5` thick-oxide pair and re-run the sizing/characterization suite
from scratch (DR-0001's rejected Alternative — expensive, no existing
evidence), or (b) add a compact series-regulation element ahead of `vdd`.
Neither has any evidence in `sim/` today, and this proposal does not
pretend otherwise.

---

## 5. Test-plan outline

### 5.1 Bench setup

The packaged part is measured on whatever daughterboard/test-board fixture
the Challenge #4 harness provides (unpublished as of this document, §
"Status of this repository"). Minimum bench instrumentation, by direct
analogy with the pins requested in §2: a programmable supply for
`vdd`/`vddr` (independently of the harness's own rails per the rail-routing
note above), a function generator or FPGA-sourced `clk` (external by
design, DR-0003), a logic analyzer or FPGA capture fabric wide enough for
the 6 digital test outputs plus the 6 digital control inputs (§2.2–2.3), and
— if `ro_mon` (§2.4) is actually built before submission — an oscilloscope
probe path rated for the frequencies in row A. A thermal chamber or hot/cold
plate is needed to reach any point beyond bench ambient, since every row in
§4 that has been simulated at all was simulated across −40…+125 °C.

### 5.2 Per-row bring-up and closure plan

1. **Power-on / reset smoke test.** Assert `rst_n`, release, confirm
   `raw_valid` asserts one `clk` edge later (§2.3) and stays high. This is
   the first go/no-go gate; there is no start-up-test window to wait out
   (row F is N/A, §4), which is itself a gap this bench step surfaces
   immediately rather than papering over.
2. **Ring frequency sweep (row A / row J).** Sweep `vdd`/`vddr` and
   temperature across whatever range the bench and the rail-routing
   decision (§4) allow, toggle `en1..en4` one at a time, and compare
   `ring_bit1..4`'s toggling and (if `ro_mon` exists by then) its measured
   frequency against the `sim/ro-array-core-combining/` table in row A.
   This is the first real silicon-vs-simulation comparison this repository
   will ever have.
3. **Raw bit rate / raw min-entropy (rows B, C).** Drive `clk` at 50 kHz
   (the DR-0003 operating point) and capture `raw_bit`/`raw_valid` over a
   long consecutive run. Run the SP 800-90B non-IID entropy-source
   estimator suite plus a restart test against it. **This is the step that
   closes row C** — it cannot be closed by any further pre-tapeout
   simulation, because no transistor-level jitter-accumulation campaign
   affordably reaches the sample counts a real entropy estimate needs (the
   same argument the sibling gf180-trng repository's own proposal makes for
   its analogous row). This is also the step where a 50 kbps *architecture*
   makes measured entropy evidence dramatically cheaper to collect on real
   silicon than gf180-trng's own Row C — real time, not ngspice transient
   time.
4. **Per-ring fault injection (row A cross-check).** Use `en1..en4`
   individually to stop one ring at a time and confirm the corresponding
   `ring_bitN` output stops toggling while `raw_bit` (fed by the combined,
   now-3-ring signal) keeps producing bits. There is no health-test alarm
   to confirm gating (row H is N/A) — this step can only demonstrate that
   the raw path degrades gracefully with a dead ring, not that anything
   detects and reports it, which is exactly the gap §3 names.
5. **Power (row D).** Measure `vdd`+`vddr` current in the active state and
   with all rings disabled (`en1..en4 = 0`) across whatever voltage/
   temperature range the bench supports, and compare against the
   `sim/ro-array-core-combining/` array-only figures in row D — understanding
   going in that the measured whole-block number will be higher than the
   array-only figure cited, by however much the sampler and any digital
   section eventually added end up costing.

### 5.3 Open items before this design is submission-ready

These are not closeable by further pre-tapeout simulation of what exists
today; each needs new design work, tracked as separate issues (see the PR
that lands this document):

- **Design the digital section** (health tests, conditioner, register/
  streaming interface) that `design/README.md` explicitly scopes out today.
  Without it, rows C, F, G, and H stay N/A regardless of how much more
  analog characterization runs, and the pin mapping in §2 has no register
  bus or health-test alarm to offer.
- **Simulate an actual noise-driven raw bitstream** (row C) — even a
  preliminary, heavily-caveated point estimate, the way gf180-trng's own
  proposal had one, does not exist here yet.
- **Sampler_dff and whole-block power/area** — DR-0003's own "Follow-up
  required" already names sampler characterization as missing; row D's
  "Unmet/TBD" verdict will not improve until it and the digital section are
  both measured.
- **Ratify DR-0001, DR-0002, and DR-0003.** Every quantitative row in §4
  ultimately traces to at least one of these three Proposed records; none
  is yet an operator-accepted decision.
- **Layout and DRC/LVS.** `layout/` is empty. Nothing here is post-layout,
  nothing is DRC/LVS-clean, and the brief's full sign-off bar (post-layout
  PVT simulation, DRC/LVS-clean GDS) is not attempted in this document.
- **Reconcile against `rules-4.html`** once it publishes — this document was
  written against the assumed `rules-2.html`/`rules-3.html` structure
  because the real Challenge #4 brief was not yet published as of this
  document's date, and remained unpublished at the 2026-09-05 re-check
  above. Note that the assumed launch date itself is now unsettled: the
  epic's tracking table and this document have both been assuming
  `2026-11-09`, but the site's own Challenge #4 page states an estimated
  `2027-11-09` while its schedule index still says `2026-11-09` — resolve
  this discrepancy against whichever the site settles on before treating
  either date as load-bearing for scheduling.

---

## Program compliance notes

- **License.** This repository is [Apache-2.0](../../LICENSE), one of the
  challenge's named acceptable licenses, with all modifiable sources —
  schematics, netlists, testbenches, evidence records — public in this same
  repository. No separate licensing action is needed for this submission.
- **Open-source EDA flow.** Schematics and simulation: xschem + ngspice
  (ngspice 46, as run in `sim/`) against the sky130 open PDK, resolved via
  the search chain `design/netlist.py`/`sim/bin/corner-run.py` document
  (`SKY130_PDK_PATH` → `PDK_ROOT`/`PDK` → local/committed `pdk.json` →
  `volare`/built-in search roots). Layout would use klayout-tools (`klt`)
  per this repository's `CLAUDE.md`, once layout work starts — no layout
  has been attempted yet, so no klayout-tools friction has been filed
  against this design.
- **Disclosure.** This repository is public (per
  [2AMLogic/2am#542](https://github.com/2AMLogic/2am/issues/542)'s Phase 4
  visibility note, this repo was already public before Phase 4A). Nothing
  in this document discloses anything beyond what is already committed to
  it; no wording about the organization that maintains this repository, its
  business, or its other work appears here or belongs here.
