---
dr: DR-0014-silicon-characterization-plan
title: Silicon characterization plan -- claim-to-measurement table, observability audit against DR-0011, and the measurements/ layout contract
status: Proposed
date: 2026-10-10
deciders: unratified -- Proposed by the Builder on #256; ratification is an operator action
supersedes: "n/a -- this record supersedes nothing and changes no ratified or Proposed spec value, interface, RTL, simulation record or README target-table row."
superseded_by: n/a
related: "#256 (this record), DR-0004 (three-tier claim discipline, start-up test), DR-0003 (operating point), DR-0010 (target table), DR-0011 (pin budget audited here), DR-0012 (supply-quality brackets), spec/porting-plan.md section 3.3, spec/silicon-characterization-plan.md, measurements/README.md, sim/bin/evidence_record.py, sim/bin/check_records_append_only.py"
---

# DR-0014: silicon characterization plan

## Status

- 2026-10-10: **Proposed.** Not accepted by anyone. Ratification is an
  operator action; no agent declares this record Accepted.
- Documentation and spec text only. No RTL, layout, simulation, tool or
  interface change is made. No measured result is claimed or implied; no
  silicon exists.
- Numbering: DR-0013 is already taken by the open proposal for #221 (PR #249,
  not yet merged), so this record takes the next free number, DR-0014.

## Context

Every entropy claim in this repository is "simulation-derived, provisional until
silicon" (`README.md`, `CLAUDE.md`; `spec/porting-plan.md` section 3.3 defers
Tier 3 validation and the restart dataset to silicon). `measurements/README.md`
was a three-line placeholder. Nothing defined what silicon must show to convert
each simulated claim into a measured one, or whether the block exposes what that
measurement needs. If bring-up needs a pin, tap or mode the block lacks, it is
cheapest to learn that before tape-out.

## Decision proposed

Adopt [`spec/silicon-characterization-plan.md`](../silicon-characterization-plan.md)
as the plan of record for what `measurements/` will hold, and replace
`measurements/README.md` with the layout contract:

1. **Claim-to-measurement table** (plan section 2): ten rows (C1-C10), each
   linking to existing `sim/` record slugs and ids, with the silicon
   measurement, instrument and conditions, and a pass/fail criterion tied to an
   existing threshold (H = 0.5 design target, RCT/APT cutoffs 81/824, 50 kbps,
   < 500 uW, DR-0012's brackets). Plan section 2.1 maps all 34 slugs currently
   under `sim/`; 3 have no silicon counterpart and are marked so with a reason.
2. **Observability audit against DR-0011** (plan section 3). Result stated
   explicitly below.
3. **Layout contract** (`measurements/README.md`): slug convention, record schema
   reusing `sim/bin/evidence_record.py` conventions, append-only rule, and how a
   measured record supersedes, rather than edits, a provisional simulated record.

### Observability audit result

**No gap in DR-0011's pin budget, conditional on F1; two observability limits
(F2, F3) reported for the operator.**

- **F1 -- raw taps must be bonded.** `raw_bit` and `raw_valid` are internal nets
  in the composed `trng_whole` today. DR-0011 Option C counts them in its
  11-of-12 outputs. If the ratified interface does not bond them there is a
  gap: serial `RAW_DATA` (36 clk per word against a 32-clk raw-word period)
  cannot carry full-rate raw capture, and a register read cannot deliver the
  first sample after a restart. Rows C1, C2, C5, C7, C9 depend on it.
- **F2 -- ring period and jitter are not observable.** Every output is sampled
  at the 50 kHz `clk`; the rings run at hundreds of MHz in simulation. The
  frequency ladder and `sigma_1` can be refuted only indirectly (supply current,
  H versus an external-`clk` T_s sweep), never confirmed. A divided-ring test
  tap would fit the pin count but is an interface change and is **not made
  here**; it is an operator decision item (separate issue if wanted).
- **F3 -- `vdd` is shared** by sampler bank and digital section; their idle
  leakage is not separable. Informational.

## Alternatives considered

- **Leave `measurements/` empty until tape-out.** Cheapest now, but the
  observability findings above are then discovered after the interface is
  frozen. Rejected as the recommendation; the plan is fully reversible.
- **Put the plan in `measurements/` rather than `spec/`.** `measurements/` is for
  measured evidence only; mixing a plan (which carries pass/fail criteria and a
  decision record) into it would blur "nothing under `measurements/` is
  unmeasured". Kept the plan in `spec/` and the data contract in `measurements/`.
- **Pool silicon results into process corners (tt/ss/ff).** Rejected: a die has
  one process position; pooled corners would manufacture a comparison the
  hardware cannot support. The plan reports per die.

## Consequences if ratified as proposed

- The plan's criteria become the bar a measured record is judged against. A
  measured miss is reported, never fixed by editing the criterion (the ratified
  spec is not relaxed to make results pass).
- Any ratified interface (DR-0011 or its successor) is expected to keep
  `raw_bit` and `raw_valid` as pads.
- The "Observable today?" column and section 3 are re-run if DR-0011's budget
  assumption changes or the real brief publishes.
- Rows whose `sim/` evidence is PARTIAL (`wake-up-transient`) or pre-layout only
  keep that caveat in the plan; the plan does not upgrade any simulated claim.

## Follow-up required (not done by this record)

1. Operator decisions O1-O5 in the plan section 4 (die count, #221 disposition for
   C2, the F2 tap, DR-0011's budget assumption, package characterization).
2. Extend `sim/bin/check_records_append_only.py` (whose `RECORD_RE` matches only
   `sim/<slug>/records/...`) and the CI job that calls it to cover
   `measurements/<slug>/records/...`, before the first record is added. Until
   then the rule is enforced by review.
3. A minting helper for silicon records. `mint_behavioral_record()` hard-codes
   `sim/<slug>/` paths and a "simulation-derived" disclaimer, so it cannot be
   reused unchanged; `new_record_id`, `record_footer` and `mint_record` (which
   take an output directory) can.
4. When the whole-block post-layout campaign (#174) lands, add its slug to plan
   section 2.1.
