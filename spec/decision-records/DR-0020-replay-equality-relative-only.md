---
dr: DR-0020-replay-equality-relative-only
title: replay_equal drops its absolute tolerance floor -- exact zero is the only special case, every non-zero float is gated at 1e-9 relative
status: Proposed
date: 2026-11-18
deciders: "operator (rjwalters), attended /fleet:decide round 20261116-r15, ruling q145, posted on #547 2026-11-17"
supersedes: "n/a -- changes the comparison rule of sim/bin/replay_equal.py only (the shared replay equality introduced by #519, promoted by #543). No ratified result, spec value or existing record changes."
superseded_by: n/a
related: "#547 (this record), #519, #543, #528, DR-0005, DR-0019"
---

# DR-0020: `replay_equal` is relative-only -- no absolute floor

## Status

- 2026-11-18: **Proposed**. Directed by the operator ruling quoted above
  (option (a) of #547's decision block; options (b) per-field tolerance table
  and (c) keep-the-floor-and-document are declined). The ruling directs the
  record; it does not ratify it -- the usual ratification (two reviews, then
  the operator) applies.

## Context

Every committed-record replay in `sim/` compares floats through the shared
`replay_equal` (`sim/bin/replay_equal.py`, issue #519, promoted to one module
by #543). Until this record it gated with
`|a-b| <= max(1e-9*|v|, 1e-12)`. The absolute floor dominates wherever
`|v| < 1e-12 / 1e-9 = 1e-3`, and below that magnitude the *effective*
relative gate degrades to `1e-12/|v|` -- the advertised 1e-9 bound silently
does not hold.

That regime is not a corner case in this repo: several committed metrics are
seconds-scale jitter figures of magnitude 1e-12 to 1e-15. Measured by
bisecting the largest relative change a replay still calls MATCH, through
`sensitivity.py`'s `calibration_leg()` against the tip record
`20261113-150554-fb302c35` (issue #547, at #543's head `a3317836`;
re-verified first-hand on 2026-11-18 at this record's base):

| artifact field | smallest entry \|v\| | largest UNDETECTED relative change |
|---|---|---|
| `numerical_floor` | 6.459e-13 | **155 %** |
| `sigma_1_corrected` | 1.274e-12 | **78.5 %** |
| `sigma_1_raw` | 1.428e-12 | **70 %** |
| `T_0` | 1.321e-09 | 0.0757 % |

Over the whole tip record, 950 of 11181 non-zero float leaves (and 324 of
1188 in the calibration artifact) had an effective relative gate >= 1e-2.
The exposure is repo-wide, not study-local: `ripple.py`'s rows carry a
`pull_fraction` at ~2.1e-15 (effective gate 480x) and a `shift_pct` at
~1.1e-14 (90x) on the superseding tip record
`20261113-150546-fb302c35`.

`--check` is how this repo proves a committed record still re-derives from
its own raw responses, and sigma jitter is the quantity the min-entropy
assumption rests on. A replay comparison that cannot see a 70 % change in
`sigma_1_raw` does not bound re-derivation drift in the figure that matters
most, even though it bounds `lock_proximity` to 1e-9.

**Provenance of the floor**: `abs_tol=1e-12` entered at `17177097` (the
original ripple replay tolerance, #467-era) with no recorded rationale --
its commit message names only the relative value ("Compare floats to rel
1e-9"). From its shape and single original call site it reads as a guard
against the degenerate `isclose(0.0, tiny)` case rather than a statement
about seconds-scale jitter; the value predates the sub-picosecond metrics it
came to govern. No recorded rationale intends this floor. In-repo precedent
for the alternative already existed: `conditioned-output.py` has replayed
with `abs_tol=0.0` since `f4f95396` (#243).

## Decision

`replay_equal`'s float branch drops the absolute term: the gate is
`|a-b| <= 1e-9*|v|` (`math.isclose(..., rel_tol=1e-9, abs_tol=0.0)`), with
exact equality (`a == b`) as the only special case. Specifically:

- **Every non-zero float is gated at the advertised 1e-9 relative,
  uniformly** -- no magnitude below which the bound degrades. This tightens
  the guard; nothing is relaxed.
- **The zero-versus-tiny rule, stated plainly**: if one side is exactly
  `0.0` and the other is any non-zero float -- however tiny, down to the
  smallest subnormal (`5e-324`) -- the pair reads **DIFFERS**. A relative
  tolerance has no meaning at zero, so the choice is not "which tolerance
  applies" but "what a zero means": replay compares a *re-derivation*
  against what was committed, and a re-derivation that produces a non-zero
  value where the record committed exactly `0.0` is a real change in the
  reduction (a clamp that fired vs one that did not, a branch taken vs not),
  not cross-version numerical noise. `0.0` and `-0.0` compare equal (the
  `a == b` short-circuit; they are the same value in IEEE-754), and
  int/float pairs of equal value stay equal.
- **What a replay verdict now means**: MATCH bounds every non-zero float
  leaf of the re-derivation to 1e-9 relative against the committed record.
  A tamper or re-derivation drift beyond that, at any magnitude, is
  reported. The integrity pins (sha256 over committed bytes) are untouched
  and stay exact; no tolerance bridges a hash (as DR-0019 kept, this record
  changes only the tolerance-compared half).
- **The `sum()` split motive is unaffected**: the CPython <= 3.11 vs >= 3.12
  builtin `sum()` difference is ~1-ulp, ~1e-16 relative -- far inside the
  1e-9 relative gate at every magnitude. The replay evidence below is the
  verification of that claim; it does not rest on it.

## Replay evidence (all committed records, before vs after)

Every committed record of the three `replay_equal` consumers was replayed
with `--check` immediately before and after the change (2026-11-18, this
record's base commit vs its implementation commit). The verdicts are
identical: no record newly differs, and no currently-MATCHing record
degrades.

| consumer | record | before | after |
|---|---|---|---|
| `ro-vth-drift-sensitivity` | `20261010-164921-7e279ab` (controls) | MATCH, rc=0 | MATCH, rc=0 |
| `ro-vth-drift-sensitivity` | `20261010-175052-7e279ab` (grid, superseded) | DIFFERS, rc=1 | DIFFERS, rc=1 (same legs; by design, superseded by DR-0005's record) |
| `ro-vth-drift-sensitivity` | `20261113-150554-fb302c35` (tip) | MATCH, rc=0 | MATCH, rc=0 |
| `ro-array-supply-perturbation` | `20261009-000459/000500-28d3690`, `20261012-111244/111245-8100a6b` (superseded) | DIFFERS, rc=1 | DIFFERS, rc=1 (same; pre-#467 convention, pinned by `test_a_superseded_record_no_longer_replays`) |
| `ro-array-supply-perturbation` | `20261113-150541/150542/150544/150546-fb302c35` (superseding) | MATCH, rc=0 | MATCH, rc=0 |
| `xor-combining-alternatives` | `20261011-074331-ba1ae9e` | MATCH, rc=0 | MATCH, rc=0 |

(`records/*.calibration.json` artifacts are not replayed through `--check`
-- they are pin targets, not records. The behavioural-replay record
`20261010-175419-7e279ab` is reduced by `behavioral_replay.py`, which is
not a `replay_equal` consumer.)

The measured exposure collapses as expected. Re-running issue #547's
boundary bisect through `calibration_leg()` against the tip record:

| field | before (floor) | after (relative-only) |
|---|---|---|
| `numerical_floor` (6.459e-13) | 155 % | 1e-7 % (~1e-9) |
| `sigma_1_raw` (1.428e-12) | 70 % | 1e-7 % (~1e-9) |
| `sigma_1_corrected` (1.274e-12) | 78.5 % | 1e-7 % (~1e-9) |
| `T_0` (1.321e-09) | 0.0757 % | 1e-7 % (~1e-9) |

No committed record needed re-minting, and none was edited: the records
that replay MATCH today keep replaying MATCH under the tighter gate, which
is itself the evidence that cross-interpreter `sum()` noise never
approached the removed floor on real committed data.

## Consequences

- `sim/bin/replay_equal.py`: `abs_tol=1e-12` -> `abs_tol=0.0`; module and
  function docstrings rewritten to state the relative-only rule and the
  zero-vs-tiny rule. `sim/ro-vth-drift-sensitivity/analysis/sensitivity.py`
  (`calibration_leg`, `check` docstrings) and the study README no longer
  describe a floor.
- Boundary tests now pin the gate where it used to be blind:
  `test_vth_drift.py` inverts the old floor-pinning test into
  `test_sigma_field_drift_is_detected_by_the_relative_gate` (1e-6-relative
  injection into the tip artifact's real sub-picosecond fields ->
  DIFFERS; 1e-12-relative -> MATCH) and adds zero-vs-tiny cases;
  `test_ripple_reduction.py` pins the same property on this study's
  smallest committed floats (`pull_fraction` ~2e-15, `shift_pct` ~1e-14).
- **Accepted loss**: a re-derivation that legitimately produces exact-zero
  vs tiny-dust asymmetries at the 1e-20 scale now reads DIFFERS and must be
  reported rather than absorbed. If that ever happens from a legitimate
  cause, it is a finding against this record -- not a reason to quietly
  reintroduce a floor.
- No record is minted or edited; `sim/records-append-only-allowlist.txt` is
  untouched. Committed evidence is unchanged byte-for-byte.
- The min-entropy re-derivation chain now has its σ-jitter replay bounded at
  the advertised 1e-9 relative, which is what the `--check` gate claims.
