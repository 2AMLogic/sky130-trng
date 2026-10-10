---
dr: DR-0010-target-table-reconciliation
title: reconciling README.md's "Target specification (DRAFT)" table with the repository's own sky130 evidence — a single ratification packet for the operator
status: Proposed
date: 2026-10-10
deciders: unratified — Proposed by the Builder on #239; ratification is an operator action
supersedes: "n/a — this record supersedes nothing. It packages deltas that DR-0003 (rate) and DR-0004 (digital rows) already propose, adds the area and power evidence that has landed since, and routes the rows that are not decidable yet to the issues that own them. It relaxes no spec value."
superseded_by: n/a
related: "#239 (this record), #18 (Chipalooza sign-off epic), #221 (min-entropy floor vs local mismatch), #174 (whole-block post-layout characterization), #201 (gated-off/idle leakage across PVT), #226 (closed; floorplan compaction), DR-0001, DR-0002, DR-0003, DR-0004, spec/porting-plan.md §5 question 3, docs/chipalooza/challenge-4-proposal.md §4 and sign-off scorecard"
---

# DR-0010: target-table reconciliation (rate, area, power, and every other README row)

## Status

- 2026-10-10: **Proposed.** Not accepted by anyone. This is a *ratification
  packet*: one table, one row per row of `README.md`'s "Target specification
  (DRAFT)", each with the current README value, the sky130 value the
  repository has measured or derived (cited to a committed file), and a
  proposed disposition. Ratification is an operator action; no agent
  declares this record Accepted.
- This record does **not** edit `README.md`. The README table changes only
  after the operator ratifies, in a follow-up edit this record names (see
  "Follow-up required").
- No spec value is relaxed here. "Amend" appears only where an existing
  Proposed record already carries the amendment (rate), and it is explicitly
  the operator's to accept or reject. Area and power are deliberately left
  undecided.

## Context

`README.md` still carries the gf180-derived draft values. The repository's own
evidence has since moved well past them, but the only places that say so are
scattered: DR-0003 §3 says the rate row "moves from `> 1 Mbps` (draft) to
`50 kbps`" but is only Proposed; the area and power figures live in
`layout/trng_whole/report.json` and `docs/chipalooza/challenge-4-proposal.md`;
`spec/porting-plan.md` §5 question 3 ("What raw-rate target does sky130's own
array sizing actually support") is still literally open. The Challenge #4
scorecard consequently reports "no row is Met against its README target"
(`docs/chipalooza/challenge-4-proposal.md`, AC2) — a statement about a stale
target table as much as about the design.

`CLAUDE.md` forbids agents relaxing the spec to make results pass, so the only
legitimate path is a decision record routed to the operator. This is it.

All figures below were re-read from the committed files cited in the table at
the `origin/main` commit this record was written against (`0d8f3c7`), not
copied from the issue or from the Chipalooza document. Where a re-read changed
or sharpened a figure, that is called out in "Re-verification notes".

## The reconciliation table

Disposition vocabulary: **keep** = keep the README target, the design must
close the gap; **amend to X** = proposed new target with rationale; **defer to
#N** = not decidable on current evidence, owned by the named issue.
Everything sky130-derived is simulation-derived and provisional until silicon.

| # | README row | README target (stretch) | Measured / derived on sky130 (citation) | Proposed disposition |
|---|---|---|---|---|
| 1 | Entropy source | N-way free-running RO array, XOR-combined ahead of one sampler; N re-sized from a jitter budget at the entropy-binding corner (stretch: metastability hybrid secondary tap) | `N = 4` five-stage rings, balanced 3-gate XOR tree: `N_max_combine = 6`, entropy floor at 50 kbps is `N >= 4` (DR-0003 §1–3; `sim/xor-combining-bandwidth/`, `sim/ro-array-operating-point/`). Entropy-binding corner `ss`/−40 °C/1.62 V (DR-0002). The `N` the row asked to be "re-sized" has been re-sized. No metastability-hybrid evidence exists. | **keep** (text already satisfied by DR-0003's `N = 4`; ratifying DR-0002/DR-0003 closes it). Stretch: **defer** — no issue or evidence exists; leave as an unevidenced stretch. |
| 2 | Raw rate | `> 1 Mbps` sustained at the raw tap, binding at the slowest-RO corner (stretch `> 4 Mbps`) | Architectural ceiling **~78 kbps at any `N`**, set by the XOR combining gate's bandwidth, binding at `ff`/−40 °C/1.98 V (DR-0003 §1–2, table; `sim/xor-combining-bandwidth/`, `sim/ro-array-operating-point/`). Chosen operating point **50 kbps** (`T_s` = 20 µs, `N = 4`, guaranteed `H` = 0.5415 against `H0` = 0.5; smallest `T_s` at which `N = 4` clears the requirement is 19.31 µs = 51.78 kbps). | **amend to 50 kbps** (DR-0003 §3, carried here unchanged; ceiling ~78 kbps stated alongside). **Cost, stated explicitly:** the `> 4 Mbps` stretch becomes unreachable with this RO + XOR topology (as is the `> 1 Mbps` target itself, by roughly two orders of magnitude); only redesigning the combining gate (wider devices, a different tree) raises the ceiling, per DR-0003's own "Follow-up required". Ratifying this amendment accepts that cost. |
| 3 | Raw min-entropy per bit | `H0` = 0.5 bit/sample as a design *target* at the entropy-binding corner (a sizing input, not a claim) | Not settled by evidence; three non-comparable sources. (a) Transistor-level, 24 raw bits/corner, one seed, at `T_s` = 100 ns (not DR-0003's 20 µs): `H_hat` = 0.3053 (`tt`/`ff`), 0.1898 (`ss`) — `sim/raw-bit-min-entropy/records/20260906-003407-6b86c9c.md`. (b) Behavioral (not transistor-level), 131072-bit streams at the literal 20 µs: `H_MCV` ≈ 0.985–0.990 at the corners listed, independence assumed by construction — `sim/raw-bit-volume-campaign/records/20261008-061809-56e0fb7.md`, `…20261008-135454-847b454.md`. (c) Static bias from local mismatch, `H_bias` worst case: `tt` 0.4718 (60 of 1800 array×sampler pairings below DR-0004's 0.5 floor), `ss` 0.6425, `ff` 0.6800 — `sim/local-mismatch-monte-carlo/records/20261009-111125-e57ad27.md`, `…111126…`, `…111127…`. | **defer to #221**, which asks whether the floor, the operating point and the lock-proximity criterion need amending or a trim/selection mechanism is required. This record neither restates nor pre-empts that analysis. Until #221 is decided the README value stays as is (**keep, provisionally**). |
| 4 | Quality | designed-for-SP 800-90B (raw access + RCT/APT + entropy-source model); validation deferred to silicon (stretch: AIS-31 PTG.2 structure) | Raw access never gated, RCT/APT, start-up test (DR-0004 §2, §2.5, §4.1). Only Tier 1/Tier 2 work exists; the repository makes no Tier 3 claim (DR-0004 §3.3). No AIS-31 work exists. | **keep** (the "designed-for, validation deferred" wording already matches the evidence). Stretch: **defer** — no evidence or owning issue. |
| 5 | Conditioning | non-vetted CRC-32 LFSR compression, `K` = 8 (256 raw bits : one 32-bit word) (stretch: vetted conditioner if area budget allows) | Implemented as specified: generator `0x04C11DB7`, register seeded `0xFFFFFFFF`, re-seeded per 256-bit block (DR-0004 §3.1; `sim/digital-conditioner-equivalence/`). Synthesized digital section 22099.95 µm² at the 50 kHz constraint, of which this block is a part (`sim/digital-synthesis/`). The stretch is gated on "area budget allows", and the area row (#7 below) is unmet. | **keep.** Stretch: **defer to the area decision** (row 7); it cannot be evaluated until the operator chooses the area option. |
| 6 | Health tests | continuous RCT + APT on raw stream; cutoffs re-derived from sky130 corners, not copied | `C_RCT` = 81, `C_APT` = 824 at `H` = 0.5, α = 2⁻⁴⁰, `W` = 1024; exact APT degeneracy floor `H` = 0.0390625; table over an `H` grid so a measured `H` moves the cutoff by lookup (DR-0004 §2; `sim/digital-health-test-parameters/`). Values coincide with gf180-trng's because the formulas and parameters coincide; recomputed, not copied. **Conditional on row 3.** | **keep** (derived and implemented). Cutoff values **defer to #221** insofar as a changed `H` floor changes them. |
| 7 | Area | `< 0.05 mm²` | **Whole block, drawn: 0.126116 mm² (378.16 × 333.5 µm), 2.522× target** — `layout/trng_whole/report.json` `area`. Macros: `trng_digital` 0.06005 mm² (die 60049.5 µm², core 54877.6 µm², 42.6334 % utilisation — `layout/trng_digital/pnr.json`), `sampler_core` 0.019297 mm². Digital macro alone exceeds the target. Compaction study (#226, `sim/digital-floorplan-compaction/records/20261009-214736-760b4d3.md`): digital P&R at 40/55/65 % requested utilisation gives die 0.060050 / 0.044291 / 0.037787 mm²; best re-stacked estimate (not composed) 0.093609 mm² (1.87× target) at 65 %, removing 42.7 % of the gap; floors — analog bbox alone 38.6 % of target, routed std-cell area 0.023052 mm² (46.1 %), cells + analog at 100 % utilisation with zero overhead 0.042349 mm². The 55/65 % points raise unrepaired library max-slew/cap violations and are not promoted. Earlier array-only *device-count estimate* 0.0026–0.0088 mm² (DR-0003 §7) is not a layout measurement and excludes sampler and digital. | **Operator decides; no recommendation made here.** See "Operator options: area" below. |
| 8 | Power | `< 500 µW` active; idle target set after a sky130 leakage survey | Array only (rings + buffers + XOR): worst 431.6 µW at `ff`/−40 °C/1.98 V, best 81.0 µW at `ss`/−40 °C/1.62 V over DR-0003's grid (DR-0003 §5/§7; `sim/ro-array-core-combining/`). See re-verification note R3: the 125 °C records give a higher array-only figure. Digital static leakage ≈ 9.98 nW unconstrained / ≈ 9.90 nW at 50 kHz, `tt_025C_1v80`, leakage only (`sim/digital-synthesis/`). **Unmeasured:** sampler power, digital dynamic power, whole-block power, idle/gated-off leakage across PVT. | **Pending #174 (whole-block post-layout characterization, dynamic power) and #201 (idle/leakage across PVT incl. +125 °C).** No conclusion drawn. See "Operator options: power" below. |
| 9 | Operating envelope | −40 … +125 °C; supply per device flavor (1.8 V core, 3.3 V I/O available) — confirm before ratification | Entropy source and sampler are built from the 1.8 V core pair, because sky130 ships no matched 3.3 V core N/P pair (DR-0001); PVT grids use 1.62 / 1.8 / 1.98 V (±10 %) and −40 / 27 / 125 °C (`sim/ro-array-core-combining/records/` incl. `20261008-1353{55,56,57}-847b454`; `sim/raw-bit-volume-campaign/records/20261008-135454-847b454.md`). | **keep** the temperature range. The supply wording "confirm before ratification" is discharged only by ratifying **DR-0001** (1.8 V ±10 % core); that is a clarification of the row, not a relaxation. |
| 10 | Interface | streaming, mode-selectable raw / conditioned; raw access always available and never gated | Two-path register/streaming interface, raw path never gated, latch-and-gate failure policy on the conditioned path (DR-0004 §4, §2.5 failure policy; verified in `sim/digital-section-behavioral/`, `sim/digital-functional-verification/`, `sim/digital-rtl-equivalence/`). Time-to-first-valid derived: 0.64 ms first raw word, 25.60 ms first conditioned word (DR-0004 §6). | **keep.** |

## Re-verification notes

- **R1 — rate.** DR-0003 §2 table and §3 were re-read; the 78 kbps / 50 kbps /
  `N = 4` / 19.31 µs / `H` = 0.5415 figures match the issue.
- **R2 — area.** `layout/trng_whole/report.json` gives 0.126116 mm² and a
  ratio to target of 2.522; the macro split and the compaction numbers above
  match `sim/digital-floorplan-compaction/records/20261009-214736-760b4d3.md`
  as committed. The README row does not state whether the `< 0.05 mm²` is a
  whole-block or an array-only figure; the Chipalooza scorecard grades it
  whole-block.
- **R3 — power: the issue's 431.6 µW is not the worst array-only figure any
  more.** 431.6 µW (= 218.0 µA × 1.98 V) is the worst of DR-0003's grid. The
  later 125 °C records (`sim/ro-array-core-combining/records/20261008-135357-847b454.md`,
  issue #197) report `i_array_total` = 239.36 µA at `ff`/125 °C/1.98 V. Taking
  supply × current as DR-0003 does, that is **≈ 473.9 µW (derived here, not
  stated in the record), 94.8 % of 500 µW**, array only. The Chipalooza
  document's 431.6 µW figure and "86.3 % of the budget" therefore understate
  the array-only worst case across the full README envelope. This record does
  not edit those documents.
- **R4 — min-entropy.** The `0.1898 / 0.3053` figures are taken from the
  `20260906-003407-6b86c9c` record (24 bits per corner, `T_s` = 100 ns). The
  behavioral and mismatch figures were added from records committed after the
  Chipalooza table was written; all three are listed because they disagree in
  kind, not just in value, and the choice among them is #221's.

## Operator options: rate (proposed amendment)

Option R-A (proposed): ratify the amendment to **50 kbps** with the ~78 kbps
ceiling recorded, as DR-0003 §3 already proposes. Cost: the `> 4 Mbps` stretch
is unreachable with this RO + XOR topology.

Option R-B: keep `> 1 Mbps`. The evidence says this cannot be met by any array
size on this topology (`N` the entropy law wants is 78 at 1 Mbps against
`N_max_combine` = 6); it would need a redesigned combining gate, which no
issue currently owns. Listed for completeness.

## Operator options: area (not pre-decided)

Option A-1 — **hold `< 0.05 mm²` and name the work needed.** The compaction
study shows no utilisation setting suffices (best estimate 1.87× target; floor
0.042349 mm² with zero overhead), so holding the target requires structural
changes, which #226 lists as separate, unfiled proposals: a folded or
side-by-side analog arrangement (the 330.96 µm-wide single-row `sampler_core`
sets a 0.029273 mm² analog row), a smaller digital section (standard cells
alone are 46 % of the target; FIFO depth/storage style is the named candidate,
with functional risk and a decision-record requirement), reduced composition
overhead (inter-macro lanes, supply escape, pad row), and possibly a smaller
`N` or other architectural change. Cost: new design and re-verification work
across the sign-off chain, with no evidence yet that it closes the gap.

Option A-2 — **amend the target with justification.** The operator picks a new
figure (and states its basis: whole block vs macros) and the rationale. The
measured anchors for choosing it are 0.126116 mm² (committed, verified), 0.093609
mm² (best compaction estimate, not composed, degraded electrical layout), and
0.042349 mm² (absolute floor of this netlist and analog macro). Cost: the
row stops being a constraint the design is judged against, so the
justification must be stronger than "the design does not meet it".

## Operator options: power (pending evidence, not pre-decided)

Not decidable now. The array-only worst case (R3, ≈ 473.9 µW) already sits
within 6 % of the `< 500 µW` target before the sampler, digital dynamic power
and any layout parasitics are added; whether the whole block closes is exactly
what #174 will measure. Idle/gated-off figures and the "idle target set after a
leakage survey" half of the row belong to #201. When both land the operator can
choose between holding the target (and naming duty-cycle, `N` or bias work
needed) and amending it with justification, as for area. This record takes no
position.

## Consequences if ratified as proposed

- Rows 1, 4–6, 9, 10 stay as written (row 9's supply wording is clarified via
  DR-0001); the rate row is amended to 50 kbps; rows 3, 6 (cutoff values),
  7 and 8 remain open against #221, the area options, and #174/#201.
- The Challenge #4 scorecard can then grade the rate row against 50 kbps
  without a relaxation having been made by an agent.
- `spec/porting-plan.md` §5 question 3 can be marked answered.

## Follow-up required (not done by this record)

1. On operator ratification of the rate amendment: edit `README.md`'s
   "Raw rate" row to 50 kbps (ceiling ~78 kbps noted; stretch row reworded
   per the ratified cost), and update `docs/chipalooza/challenge-4-proposal.md`
   §4 row B verdict accordingly.
2. Operator choice on area (A-1 or A-2) and, once #174/#201 land, on power.
3. Disposition of row 3 and the row 6 cutoffs from #221.
4. Optionally correct the array-only power figure in
   `docs/chipalooza/challenge-4-proposal.md` row D to reflect R3.
