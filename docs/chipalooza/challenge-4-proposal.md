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

**Pre-layout, pre-synthesis.** The entropy source (an `N = 4`, five-stage,
free-running ring-oscillator array, XOR-combined) and its sampler are drawn
as SPICE schematics and characterized across PVT at the transistor level
(`sim/`). Everything downstream of the raw tap — health tests, conditioner,
register/streaming interface — now exists as a normative behavioural model
plus RTL under `digital/`, per
[DR-0004](../../spec/decision-records/DR-0004-sky130-digital-section-architecture.md)
(status Proposed, issue #20), verified behaviourally under `sim/digital-*/`.
**No synthesis against `sky130_fd_sc_hd` has been run**, so that section
contributes no `Fmax`, area, power or leakage figure to §4, and no
DRC/LVS-clean array or sampler layout exists: `layout/` now holds
fourteen composed, individually DRC-clean and LVS-clean cells — nine leaf
gates (`ro_buf`, plus `ro_stage`/`ro_nand2` at all four ring `wstv` widths),
all four `ro_ring5` rings (`layout/ro_ring5/` + three `wstv` siblings,
22/22 devices and 19/19 nets LVS-matching each), and the combining tree's
`xor2` (`layout/xor2/`, 12/12 devices and 10/10 nets) — see
`layout/README.md`. That is every cell `ro_array_core` instantiates, but
still not a composed array, sampler, or whole-block GDS: nothing wires the
fourteen together yet.
Every decision record cited below (DR-0001,
DR-0002, DR-0003, DR-0004) carries status **Proposed** — drafted, not yet
accepted by an operator.

This is still an earlier maturity point than the sibling
[`gf180-trng`](https://github.com/2AMLogic/gf180-trng) repository's own
Challenge #3 proposal: the register interface, health tests and conditioner
now exist here too, but that sibling's were synthesized and power/area-
characterized, and neither repository has composed a whole-block GDS. **This document is not a submission-ready
package the way that sibling document was written to be.** It is this
issue's own deliverable: an honest, `sim/`-cited snapshot of where this
design stands against the Challenge #4 brief's assumed structure, naming
every gap between here and a submittable design rather than glossing over
it — per this repository's `CLAUDE.md`: "no claim without a testbench" and
"agents do not relax the ratified spec to make results pass." Layout,
DRC/LVS-clean GDS, and post-layout PVT simulation — the brief's full
sign-off bar — do not exist in this repository *for the whole block* and are
**not** claimed here; they are named as explicit follow-up work at the end
of this document. (Updated since this document's first revision: nine leaf
cells are DRC/LVS-clean and have been extracted with parasitics and
simulated over the PVT grid — see §5.3 — all four `ro_ring5` rings are
now composed DRC/LVS-clean on top of them and parasitic-extracted as whole
rings, and the combining tree's `xor2` is composed DRC/LVS-clean as well,
which completes every leaf cell `ro_array_core` instantiates. A floorplan
for the array now exists, its forward ring→buffer signal chain is really
routed, its buffer→XOR `a` and `b` legs are now routed for both
first-stage XORs, its four buffers share a really-routed `vss` bus, and the
XOR combining tree's inputs are now fully wired — `t1` (`xa1.y`→`xa3.a`)
and `t2` (`xa2.y`→`xa3.b`) are both really routed, `t2` via a `"metal3"`
(met2) bridge over two met1 promotion stubs added at the array-composition
level, resolving the fence of already-routed met1 backbones "Increment 6"
found blocking it (`layout/ro_array_core-placement-poc/`, DRC-clean at
every step); `xo` (`xa3.y`) remains exposed as a bare top-level pin.
Extraction shows the `vss` bus did not change the array's own `vss` net
topology at all, since sky130's substrate model already ties every
un-isolated NMOS body to one global node regardless of drawn routing
(`layout/README.md`'s "Increment 5"), so `vdd` distribution is the array's
one remaining unwired net, expected to need the same met1-stub-then-met2-bridge
recipe "Increment 7" proved out for `t2` — `xor2` has no post-layout record
of its own, and there is still no LVS-clean array, sampler, or top-level
layout, so the whole-block bar is still unmet.)

---

## 1. Type of IP block

A digital true-random-number-generator **entropy source** (not a DRBG): a
four-ring, XOR-combined, free-running ring-oscillator array feeding a
fixed-external-clock sampler, followed by SP 800-90B health tests, a
non-vetted CRC-32 conditioner, and a two-path register/streaming interface
(DR-0004, unsynthesized) — see §3.

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

**The pin mapping above predates DR-0004 and is not updated here.** A
health-test `alarm` output, a `gated`/`startup_done` status pair and a
conditioned-stream tap now exist in RTL and are the obvious claimants for
the spare slots; committing them to specific slots is work for the
reconciliation against the real `rules-4.html` (§5.3), not for this
increment. 6 of 12 used, 6 spare — reserved, not declined, for whatever the
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

**Health tests, conditioner, interface: designed as RTL and a behavioural
model, not yet synthesized.** As of
[DR-0004](../../spec/decision-records/DR-0004-sky130-digital-section-architecture.md)
(status Proposed, issue #20) this repository has continuous SP 800-90B
RCT/APT health tests with a 1024-sample start-up test and a latch-and-gate
failure policy, a non-vetted CRC-32 LFSR conditioner (`K` = 8: 256 raw bits
in, one 32-bit word out), and a word-addressed register file with a
mode-selectable streaming port — raw always readable and never gated,
conditioned path gated behind the start-up test and the alarm. The
normative description is a bit-exact, cycle-accurate Python model
(`digital/model/`); `digital/rtl/trng_digital.v` implements it and is
checked against it cycle-for-cycle (`sim/digital-rtl-equivalence/`).

Two things are still genuinely absent, and rows D/G below depend on them:
**no synthesis against `sky130_fd_sc_hd` has been run** (so no `Fmax`,
gate count, area or leakage figure exists for this section), and **no
per-ring liveness monitor** consumes the `ring_bit1..4` taps —
`spec/porting-plan.md` §5 leaves open whether this port adopts one at all,
so DR-0004 declines to half-design it. The health-test cutoffs are a
formula evaluation at the README's `H` = 0.5 *design target*, not at a
measured `H`; row C below is exactly the measurement they are conditional
on.

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
| C | Raw min-entropy per bit | 0.1898 bit/sample (`ss`) | 0.3053 bit/sample (`tt`/`ff`) | 0.3053 bit/sample (`tt`/`ff`) | Design target: `H0 = 0.5` bit/sample (a sizing input, per DR-0002/DR-0003, not a claim) | `ss`/27 °C/1.8 V (lowest `H_hat` of the three corners run) | `sim/raw-bit-min-entropy/` (noise-injected transient digitization + MCV-style SP 800-90B §6.3.1 reduction, issue #21) | **First raw-bitstream evidence in this repository, but still Unmet against `H0` and NOT at DR-0003's operating point.** 24 raw bits per corner, one seed each, at `Ts` = 100 ns (a disclosed compute-budget deviation from DR-0003's `Ts` = 20 µs — see the testbench's own header) all clear a non-degenerate go/no-go bar (mixed 0/1, `ro1_swing_frac` ≈ 1.06 confirming real oscillation) but fall short of `H0 = 0.5`. This is explicitly a **Tier 2 design estimate** (gf180-trng's own DR-0004 three-tier claim discipline, cited by `spec/porting-plan.md`), not a Tier 3 SP 800-90B validation, and it is provisional until measured on silicon per the root `CLAUDE.md`. Sample-count-limited (`n` = 23-24), single seed per corner (not independent trials — `se_naive` ≈ 0.10 is therefore an UNDER-estimate of the true uncertainty), and measured at 200× DR-0003's sample rate, so `H_hat` should not be rescaled to the literal 20 µs operating point without re-running at that `Ts`. See the record's own caveats for the full disclosure. |
| D | Active power, array only (rings + buffers + XOR; excludes sampler and any digital section) | 81.0 µW | — | 431.6 µW | < 500 µW | min: `ss`/−40 °C/1.62 V; max: `ff`/−40 °C/1.98 V | [DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md) §7; `sim/ro-array-core-combining/` | **Unmet/TBD as a whole-block claim.** The array term alone (431.6 µW worst-measured) already consumes 86.3% of the 500 µW budget, with the 6× `sampler_dff` instances (unsimulated — DR-0003's own "Follow-up required" lists this gap) and the entire not-yet-designed digital section still to add. gf180-trng's own experience is a direct warning here: its synthesized digital section alone cost 712.4 µW, more than this entire budget row by itself. This row should not be read as "passing" — it is an array-only partial measurement against a whole-block target. |
| E | Idle current, per ring (stopped) | 0.6 nA | — | 255 nA | not yet set — `spec/porting-plan.md` §2.5's leakage survey has not run | min: cold; max: `ff`/125 °C | `sim/ro-ring5-swing-and-current/` | No target exists to grade against. Reported because it exists now and did not before; excludes sampler/digital-section idle current, all unmeasured. |
| F | Time-to-first-valid | 0.64 ms (first **raw** word) | — | 25.60 ms (first **conditioned** word) | not stated | n/a (sample-count derived; the 50 kHz clock is fixed and external) | [DR-0004](../../spec/decision-records/DR-0004-sky130-digital-section-architecture.md) §6 (status Proposed); `sim/digital-health-test-parameters/`, `sim/digital-section-behavioral/` experiment A | **Derived, no target to grade against.** The raw path is never gated, so its first 32-bit word lands 32 samples after `raw_valid` (0.64 ms at 50 kHz). The conditioned path waits for the mandatory 1024-sample start-up health test (20.48 ms) plus one 256-bit conditioner block (5.12 ms). Both figures are sample counts at DR-0003's clock, verified in the behavioural campaign — not silicon, and not PVT-dependent (nothing here is a timing-closure claim). |
| G | Digital section max clean sample-clock frequency (`Fmax`) | — | — | — | supplementary, informative only | n/a | none — RTL now exists (`digital/rtl/trng_digital.v`, DR-0004) but **no synthesis has been run against `sky130_fd_sc_hd`** | **Still N/A — the design exists, the number does not.** DR-0004 § "Consequences" names synthesis as the largest gap it leaves: without a mapped netlist and STA there is no `Fmax`, gate count, area or leakage figure for this section, and none should be inferred from the RTL simulating correctly. The block is designed to run entirely in the 50 kHz sample-clock domain, so `Fmax` is expected to be enormously in excess of what is needed — but expected is not measured. |
| H | Health-test cutoffs (RCT / APT) | — | `C_RCT` = 81, `C_APT` = 824 at `H` = 0.5, `α` = 2⁻⁴⁰, `W` = 1024 | — | formula-derived once `H` is measured | n/a (a formula evaluation, not a corner-dependent measurement) | [DR-0004](../../spec/decision-records/DR-0004-sky130-digital-section-architecture.md) §2 (status Proposed); `sim/digital-health-test-parameters/` (cutoff table over an `H` grid, exact APT degeneracy floor, false-alarm intervals at 50 kbps) | **Derived and implemented, but PROVISIONAL — conditional on row C.** The cutoffs are the SP 800-90B formulas evaluated at the README's `H` = 0.5 *design target*, because sky130 has no measured `H` (row C). They are deliberately evaluated at the design floor rather than at DR-0003's model-derived `H` = 0.5415, so the false-alarm guarantee stays valid across the whole claimed range. The evidence record tabulates the cutoff at every `H` from the exact APT degeneracy floor (`H` = 0.0390625) upward, so closing row C moves this row by lookup. The values coincide with gf180-trng's own because the formulas, `α`, `W` and the `H` target all coincide — recomputed here, not copied. |
| I | Area, array only (rings + buffers + XOR; device-count estimate, not derived from the real layout's own measured bbox) | 0.0026 mm² | — | 0.0088 mm² | < 0.05 mm² | n/a (not PVT-dependent) | [DR-0003](../../spec/decision-records/DR-0003-sky130-trng-operating-point.md) §7 | Array-only estimate sits at 5–18% of budget — but excludes the sampler and any digital section. **Not a whole-block claim; not a layout measurement** — a composed, DRC-clean, LVS-matching `ro_array_core` layout now exists (`layout/ro_array_core/`, see §5.3) with a measured `bbox_um` in its own committed evidence, but this row has not been re-derived from it. |
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

- **Synthesize the digital section** against `sky130_fd_sc_hd`. The
  section itself is designed (DR-0004: model, RTL, four evidence records),
  which moves rows F and H off "N/A" — but row G, and the digital half of
  rows D and I, need a mapped netlist plus STA and power analysis that no
  record in this repository provides.
- **Re-map the §2 pin budget onto DR-0004's interface** — a health-test
  alarm, status bits and a conditioned-stream tap now exist to claim the
  spare test-output slots, and the §2 tables still describe the pre-DR-0004
  block.
- ~~**Simulate an actual noise-driven raw bitstream** (row C) — even a
  preliminary, heavily-caveated point estimate, the way gf180-trng's own
  proposal had one, does not exist here yet.~~ **Landed (issue #21,
  `sim/raw-bit-min-entropy/`).** A preliminary, heavily-caveated MCV-style
  point estimate now exists per corner (row C above) — but it does not
  close this item's underlying gap on its own: it is a Tier 2 design
  estimate at a 200×-compressed sample rate, not the Tier 3 SP 800-90B
  validation §5.2 step 3 above still requires from real silicon.
- **Sampler_dff and whole-block power/area** — DR-0003's own "Follow-up
  required" already names sampler characterization as missing; row D's
  "Unmet/TBD" verdict will not improve until it and the digital section are
  both measured. **Partly discharged since this document was written**:
  `sim/post-layout-sampler-dff/` is the first simulation of `sampler_dff`
  in this repository, pre- or post-layout — clk→q capture delay
  103.6–299.0 ps, setup 60–150 ps and a leakage-limited (19.3 pA–293 nA)
  reset window, all post-layout (leaf-cell composition, ideal inter-cell
  wires) over the full PVT grid, with the pre-layout netlist as a same-deck
  control
  ([`spec/decision-records/DR-0007-*.md`](../../spec/decision-records/DR-0007-sampler-dff-post-layout-and-reset-contention.md)).
  **Further discharged**: `sim/post-layout-sampler-dff-assembled/` re-runs
  the capture-timing/reset-contention deck against `sampler_dff`'s own
  whole composed GDS (real intra-cell routing included, `m`/`mb` now
  routed) — clk→q capture delay 131.4–426.0 ps (1.704x–2.013x pre-layout,
  still ≤ 21.3 ppm of the ratified 20 µs `T_s`) and the same
  leakage-limited reset-window finding, confirmed at a second, stricter
  extraction scope
  ([`spec/decision-records/DR-0008-*.md`](../../spec/decision-records/DR-0008-sampler-dff-assembled-post-layout.md)).
  **Further discharged**: `layout/sampler_core-placement-poc/` places all
  six `sampler_dff` instances `sampler_core` needs side by side (DRC-clean,
  0 violations; `klt extract` confirms 132 devices, 66 nfet + 66 pfet) — a
  placement-only proof-of-concept, not yet the shared `vdd`/`vss`/`clk`/
  `rst_n` bus, the `ro_array_core` wiring, or an LVS-checkable
  `sampler_core` cell.
  **Further discharged**: [`layout/sampler_core/`](../../layout/sampler_core/README.md)
  promotes that floorplan into a real cell recipe and routes the shared
  `vdd`/`vss` bus across all six instances (DRC-clean, 0 violations; `klt
  extract` confirms 132 devices unchanged, 74 nets — `vdd` merged from six
  per-instance nets into one).
  **Further discharged**: the same directory now also routes the shared
  `clk` fan-out and shared `rst_n` fan-out across all six instances
  (DRC-clean, 0 violations; `klt extract` confirms 132 devices unchanged,
  64 nets — `clk`/`rst_n` each merged from six per-instance nets into one).
  Still missing for row D: the `ro_array_core` wiring, `d`/`q`/`vdd`/`vss`
  pin promotion, whole-cell `klt lvs`, and therefore whole-block
  power/area.
- **Ratify DR-0001, DR-0002, and DR-0003.** Every quantitative row in §4
  ultimately traces to at least one of these three Proposed records; none
  is yet an operator-accepted decision.
- **Layout and DRC/LVS.** *The narrative in this bullet is a snapshot taken
  when this document was written and is deliberately not rewritten per
  increment; [`layout/README.md`](../../layout/README.md) and
  [`sim/README.md`](../../sim/README.md) are the current record.* Landed
  since: `ro_array_core` itself as a `--check`-reproducible cell recipe
  (`klt lvs` matching at 132/132 devices, 96/96 nets), the whole-array
  parasitic extraction and post-layout PVT campaign behind
  `spec/decision-records/DR-0006-*.md`, the two remaining sampler leaf cells
  (`layout/sampler_tg/`, `layout/sampler_nand2/`), `layout/sampler_dff/`'s
  own placement, supply buses and full routing (`klt lvs` now a full match,
  22/22 devices, 14/14 nets), the sampler post-layout campaign behind
  `spec/decision-records/DR-0007-*.md`, and — now that `sampler_dff`'s own
  assembly GDS is a valid extraction source — the whole-cell (assembled)
  sampler post-layout campaign behind
  `spec/decision-records/DR-0008-*.md`; a DRC-clean placement
  proof-of-concept for `sampler_core`'s own six-`sampler_dff` bank
  (`layout/sampler_core-placement-poc/`, 132 devices, no routing yet), then
  that bank promoted to a real `cell.json` recipe with its shared
  `vdd`/`vss` bus and its shared `clk`/`rst_n` fan-out routed across all six
  instances; and, most recently, the `ro_array_core` instance placed inside
  `sampler_core` with the first two raw-tap data nets (`ro1`→`sr1.d`,
  `ro4`→`sr4.d`) routed end to end — `layout/sampler_core/`, DRC-clean, 264
  devices (the whole `.subckt sampler_core` population), 157 nets, `klt lvs`
  a quantified mismatch at 136/264 devices against a now-complete reference.
  **Still open on this bullet**: the other three data nets (`xo`, `ro2`,
  `ro3`), the inter-block `vdd`/`vss` straps, top-level pin promotion, a
  whole-cell LVS *match*, and the assembled `sampler_core` post-layout PVT
  run — so the brief's full sign-off bar (post-layout PVT over a DRC/LVS-
  clean **block** GDS) is closer but not met. The snapshot follows.

  `layout/` held fourteen composed **DRC-clean
  and LVS-clean cells** at the time of writing — which was **every leaf cell
  `ro_array_core`
  instantiates**. The newest then was `layout/xor2/`, the combining tree's XOR
  gate (`xa1`-`xa3`): twelve devices, ten nets, `klt drc` clean (0
  violations) and `klt lvs` **match** against
  `design/ro_array_core.spice`'s own `.subckt xor2` (12/12 devices, 10/10
  nets, 0 errors), occupying 23.97 × 17.585 µm. It supersedes the
  placement-only `layout/xor2-placement-poc/` and corrects that PoC's
  conclusion that this gate needed a channel router and a third routing
  plane: it needs neither — reading its two device trees as four
  two-transistor series chains, placing its two inverters as
  already-composed `ro_buf` cells, and splitting its nets across two
  *layers* rather than across lanes on one reduces it from 17 blocks and 31
  nets to 9 blocks and 12 net legs. Four more of the fourteen are the whole `ro_ring5` ring, one
  physical cell per ring (`layout/ro_ring5/` at `wstv=0.42` plus
  `ro_ring5_wstv0p{44,46,48}/`), each composed from five leaf gates and each
  `klt drc` clean (0 violations) and `klt lvs` **matching**
  `design/ro_array_core.spice`'s own `.subckt ro_ring5` at that ring's
  `wstv` (22/22 devices, 19/19 nets, 0 errors), with the forward signal
  chain, the `ro` feedback and both `vddr`/`vss` rails routed across three
  physical metal planes — the first multi-gate cells in this repository to
  reach that bar. Each ring cell occupies 41.125 × 9.17 µm including its
  rail lanes. Underneath them are the nine leaf cells:
  `layout/ro_buf/` (the per-ring output inverter),
  `layout/ro_stage/` plus its three `wstv` siblings
  (`ro_stage_wstv0p{44,46,48}/`, the array's per-stage starved delay cell at
  all four ring widths), and `layout/ro_nand2/` plus its three `wstv`
  siblings (`ro_nand2_wstv0p{44,46,48}/`, each ring's enable-gated first
  stage at all four ring widths) — all `klt drc` clean and `klt
  lvs`-matching against `design/ro_array_core.spice`'s own `.subckt`s — on
  top of the earlier device-level evidence (`layout/primitives/`) and
  well-strap finding (`layout/well-strap-poc/`); see `layout/README.md`.
  `ro_stage`'s and `ro_nand2`'s starve devices cross-couple their gates to
  the opposite rail, which needed a new two-pass composition technique
  (routing the crossing nets on a second metal level in a second `klt
  gen-compose` call) to avoid a short; `ro_nand2`'s own parallel PMOS
  pull-up pair and series NMOS pull-down pair needed that same technique
  generalized further (six same-block self-nets resolved in one final pass,
  not two); the three non-nominal `wstv` widths needed the starve devices'
  own placement origin re-derived per width, since a naive
  clone-and-reparametrize breaks DRC/LVS (`layout/README.md`'s "Starve-width
  variants" section). The `klayout-tools` regression previously recorded
  here as a blocker
  ([2AMLogic/klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491))
  is fixed. Those nine cells are now also extracted with parasitics and
  simulated: `layout/pex/` is a generated, `--check`-guarded post-layout
  netlist library and `sim/post-layout-ro-ring5/` runs the five-stage ring
  from it over the PVT grid (twelve records, thirty-six corner runs) with
  the pre-layout netlist as a same-deck control — intra-cell parasitics cost
  1.378×–1.479× in ring period, and the `wstv` frequency ladder survives
  them (`spec/decision-records/DR-0005-*.md`). The four ring cells
  themselves are now also parasitic-extracted, as whole composed rings with
  real inter-gate wiring rather than leaf-cell compositions:
  `layout/pex-ring/` extracts each ring's own GDS directly, and
  `sim/post-layout-ro-ring5-assembled/` re-runs the same measurement from it
  — real inter-gate wiring costs the ring 1.5045×–1.6546× more slowdown on
  top of intra-cell parasitics alone (period vs. pre-layout overall
  2.0819×–2.3666×), and the ladder still survives. `xor2` itself has no
  post-layout record: it is composed and verified, not extracted or
  simulated. A floorplan attempt at the array itself now exists —
  `layout/ro_array_core-placement-poc/` places all eleven sibling instances
  `ro_array_core` needs (the four rings, four buffers, three combining-tree
  XORs) on one 216.2 × 31.755 µm grid, `klt drc` clean, `klt extract`
  reporting the expected 132 devices — its "Increment 2" routed the
  forward ring→buffer signal chain on top of that floorplan (`en1..en4`, the
  four `vddrN` domains and `ro1..ro4` exposed as top-level pins, `rn1..rn4`
  really routed on met1), its "Increment 3" routed the buffer→XOR
  `a` leg for both first-stage XORs (`ro1`→`xa1.a`, `ro3`→`xa2.a`), and its
  "Increment 4" now routes the `b` leg for both as well (`ro2`→`xa1.b`,
  `ro4`→`xa2.b`) — completing the forward ring→buffer→XOR signal path for
  `xa1`/`xa2` — still `klt drc` clean (132 devices, 104 nets, each of the
  two new merges confirmed by net diff to join only its intended net).
  `b`'s recipe needed distinct source-side channel heights rather than
  reusing `a`'s rows, since a naive shared-row approach either collided
  with `a`'s own backbone or crossed a third block's bbox (both ruled out
  empirically, see the PoC's own README). Its "Increment 5" then routed the
  four buffers' own `vss` taps into one bus (`klt drc` clean, 132 devices,
  104 nets unchanged) — and found that `klt extract`'s sky130 deck already
  merges every un-isolated NMOS body onto one global substrate node
  regardless of drawn routing, so `vss`'s device count on the merged net
  (122) was identical before and after this bus existed: `vss` was not
  actually blocking an eventual `klt lvs` match, only `vdd` was (at that
  point still seven separate nets; a first buffer-only `vdd` bus attempt failed
  outright, every candidate leg crossing a neighbouring ring's own bounding
  box). Its "Increment 6" starts the XOR combining tree: `t1`
  (`xa1.y`→`xa3.a`) really routed on met1 and `xo`/`t2` exposed as pins on
  measured taps (`klt drc` clean, 132 devices, 103 nets — exactly one merge,
  confirmed by net diff). That increment's findings are worth
  carrying: `klt drc` clean is **not** connectivity evidence (a first `t1`
  probe was DRC-clean and electrically shorted, because `klt gen-compose`
  models a placed block as an opaque bbox and cannot see its interior
  metal — filed generically as `2AMLogic/klayout-tools#1527`); `xor2`'s `y`
  output has exactly four legal met1 escape windows, now measured by a
  committed scan script rather than approximated; and `t2` plus `vdd` are
  blocked by the *same* fence of already-routed backbones, with the router
  rejecting both `t2` probes itself, so the next move is a second drawing
  plane — which that increment predicted would need a met1 promotion inside
  `xor2`'s own leaf cell first. Its "Increment 7" resolves `t2`
  (`xa2.y`→`xa3.b`) via a `"metal3"` (met2) bridge fed by two short met1
  promotion stubs, and **shows the leaf-cell prediction was wrong**: the
  promotion can happen entirely at the array-composition level, one level
  up from `xor2`'s own cell, since `klt gen-compose`'s `blocks[].cell`
  mechanism lets an already-placed block gain extra hand-declared ports at
  any layer, at any point an earlier increment's own routing already proved
  clear (`klt drc` clean at every step, 132 devices throughout, 103 → 102
  nets, each merge confirmed by net diff). Its **"Increment 8" closes the
  array**: `vdd` — the last open net, seven separate per-instance nets
  because `nwell` has no chip-wide global identity the way the p-substrate
  does — is routed as seven met1 promotion stubs (each tap measured against
  the composed array by a committed scan script before anything was drawn)
  plus a six-leg met2 chain bus, merging them into one 38-device net.
  **`ro_array_core` is now `klt drc` clean (0 violations) and `klt lvs`
  matching `design/ro_array_core.spice`'s own `.subckt ro_array_core`:
  132/132 devices, 96/96 nets** — the whole entropy source, not a leaf
  cell. Its LVS reference needed four differently parameterised copies of
  the *same* `ro_ring5` subckt, which `layout/bin/compose-cell.py`'s
  plain one-shared-`params` mechanism could not express, so it was
  generated at the time by a small one-off script hand-rolling the rename
  four times over renamed copies; **a follow-up increment folds that back
  into `compose-cell.py` as a generic, unit-tested `lvs.dependency_variants`
  mechanism**, verified to reproduce the identical reference and verdicts.
  **Two committed negative controls** (resizing ring 4's starve
  devices to ring 1's `wstv`; crossing `xa1`/`xa2`'s inputs) both turn the
  comparison into `mismatch`, so the verdict is discriminating rather than
  vacuous. **A later increment (issue #69) promotes that PoC directory into
  a real `--check`-reproducible cell recipe** — `layout/ro_array_core/`,
  six `gen-compose` stages in one `cell.json`, rebuilt and re-verified by
  the same one command every other cell under `layout/` is, and
  additionally drawing `ring1..4`'s and `xa1..3`'s own `vss` taps (not
  LVS-blocking, but a real die wants the strap). That GDS, not the PoC's,
  is the canonical array layout. **A later increment still (issue #22)
  closes the block-level
  post-layout PVT gap this section used to name as unattempted**:
  `layout/pex-array/` extracts that canonical array GDS flat with `klt extract
  --parasitics`, and `sim/post-layout-ro-array-core/` runs it across the
  same four-(temp, Vdd)-point, `tt`/`ss`/`ff` grid every other post-layout
  campaign here uses (36 corner runs) — array-level parasitics cost
  2.158×–2.501× in ring period against pre-layout, the `wstv` ladder still
  discriminates (span 1.084×–1.175×), combining-node bias stays close to
  0.5×Vdd (no new systematic bias from the real routing), and a tied/float/
  solo inter-ring substrate bracket — the first one run on a real,
  physically-placed layout rather than leaf cells hand-tied to a shared
  node — finds coupling wider than the prior ring-scale study and, for the
  first time in this repo, consistent in sign across all twelve grid points
  (+0.044% to +0.293% of ring period), though still a bracket on magnitude
  rather than a resolved measurement (`spec/decision-records/DR-0006-*.md`).
  **This does not close DR-0003 §8**: its first-named mechanism, shared
  `vddr1`-`vddr4` supply impedance, still has no layout to be measured on at
  any scale. Still outstanding for the brief's full sign-off bar:
  a `vddr1`-`vddr4` supply-distribution layout, and
  **the sampler as assembled layout** (`sampler_core`/`sampler_dff` have no
  *assembled* layout at all, so no whole-*chain*, raw-tap-to-sampled-bit
  post-layout claim exists yet). **Later increments composed all three of
  the sampler's own leaf shapes**: `layout/sampler_tg/` composes the plain
  sky130 transmission gate `sampler_dff`'s four `TG_D`/`TG_FBM`/`TG_S`/
  `TG_FBS` instances share — `klt drc` clean, `klt lvs` match (2/2 devices,
  6/6 nets) against a hand-authored micro-reference, since
  `design/xschem/sampler_dff.sch` is flat and has no `.subckt` of this shape
  for `compose-cell.py`'s LVS to reference directly — confirming `mos_array`
  is sufficient for this shape (no `klayout-tools` tool gap).
  `layout/sampler_nand2/` composes the other missing leaf shape — a plain
  rst_n-gated NAND2, structurally `ro_nand2` minus its two always-on starve
  devices — also `klt drc` clean, `klt lvs` match (4/4 devices, 6/6 nets)
  against a hand-authored micro-reference for the same reason, reusing
  `ro_nand2`'s own parallel-PMOS/series-NMOS floorplan and its three-pin-net
  promote-then-resolve technique. With the third leaf shape (a plain
  inverter, already `ro_buf`), all 22 of `sampler_dff`'s devices now reduce
  to already-composed leaf cells; the 22-device whole-cell assembly and LVS
  check against `design/sampler_core.spice`'s own `.subckt sampler_dff`
  remains open. **A later increment started that assembly**:
  `layout/sampler_dff/` places all nine leaf-cell instances DRC-clean (0
  violations) and routes a DRC-clean `vdd`/`vss` supply bus across all nine
  (`klt extract` confirms both rails merged into one net each, and confirms
  the composed geometry's 22-device, 11 nfet/11 pfet split already matches
  `design/sampler_core.spice`'s own subckt before any signal wiring exists).
  `rst_n`/`clk`/`clkb` fan-out, the six data-path nets, and the resulting
  whole-cell `klt lvs` sign-off remain open (#27). **A later increment
  routed `rst_n`**: both `sampler_nand2` instances' `a` pin sits inside that
  leaf's own internal `met1` via stack, so a direct `metal2`-role via-drop
  always shorted to it; the fix routes a short `li1`-only stub clear of the
  obstruction, vias to `met1`, then vias again to `met3`/`"metal3"` role for
  the long haul — a plane no leaf cell here draws on, clear of the
  `vdd`/`vss` buses too. `klt drc` clean (0 violations), and `klt extract`
  confirms `nand_m`'s and `nand_s2`'s `a` pins and `rst_n` are one physically
  merged net. **A later increment routed `clk`**: a five-pin fan-out drawn
  as a `gen-compose` bundle net with hand-steered `connectivity[].legs[]`,
  long-hauled on `met2` in one basement lane at `y = -1.70` with a vertical
  drop at each pin's own x — `klt drc` clean (0 violations), 0 unrouted
  nets, cell bbox unchanged, and `klt extract` confirms it reaches exactly
  the six clk-gated devices `design/sampler_core.spice` has (with the four
  `clkb`-gated devices still correctly isolated). Because the DFF's
  feedback gates run the opposite clock phase from their own stage's input
  gate, `clk` and `clkb` cannot be two mirrored buses; that increment
  reserved a separate `met1` corridor at `y ≈ 0.40` for `clkb` rather than
  consuming it. **A later increment routed `clkb`**: the differential
  half of `clk`'s own fan-out, across five stages taking the reserved
  `met1` corridor with two `met1`→`met2`→`met1` bridges hopping over
  `sampler_nand2`'s own internal `met1` blobs and two east-side jogs
  dodging `clk`'s own via-drop pads at the shared `tg_fbm`/`tg_s`
  columns — `klt drc` clean (0 violations), cell bbox unchanged, and
  `klt extract`'s net count drops from 27 to 23 (exactly the four merges
  a five-pin net makes), with the merged net's own six-device list
  matching `design/sampler_core.spice`'s
  `XMpc`/`XMnc`/`XMtdn`/`XMfsn`/`XMfmp`/`XMtsp` exactly. **A later increment
  routed the first data-path net, `mc`** (`inv_mc.y` → `tg_fbm.a`): blocked
  on `met1` for its entire useful height band (`clkb`'s own backbone
  crosses at `y ≈ 2.33`; `clk`'s via-drop pad sits at the same x as the
  pin gap), so this net vias one plane further to `met2` — empty across
  this span — and runs a short U-shaped lane at `y = 1.8`. `klt drc` clean
  (0 violations) on the first attempt, cell bbox unchanged, `klt extract`'s
  net count drops from 23 to 22 (the one merge a two-pin net makes), and
  the merged net's own four-device list matches
  `XMim2p`/`XMim2n`/`XMfmp`/`XMfmn` exactly. Five data-path nets
  (`m`/`mb`/`s`/`q`/`qb`) and the whole-cell `klt lvs` sign-off remain open
  (#27).
  Note also that
  "DRC-clean" here means clean against `klt`'s **curated** sky130 deck (a
  documented subset — see each `drc.json`'s own `coverage` block), not a
  full sky130 sign-off deck.
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
