---
dr: DR-0019-provenance-pin-exit-contract
title: sensitivity.py --check provenance pins are reported, not gated -- byte-identical netlist regeneration stays the discriminator
status: Proposed
date: 2026-11-16
deciders: "operator (rjwalters), attended /fleet:decide round 20261111-r14, ruling q100, posted on #528 2026-11-15"
supersedes: "n/a -- narrows the exit contract of sim/ro-vth-drift-sensitivity/analysis/sensitivity.py check() only. No ratified result, spec value or existing record changes."
superseded_by: n/a
related: "#528 (this record), #517, #498, #492, #487, DR-0005"
---

# DR-0019: provenance-pin exit contract for `sensitivity.py --check`

## Status

- 2026-11-16: **Proposed**. Directed by the operator ruling quoted above
  (option (b) of #528's decision block); this record carries the ruling into
  `spec/` for repo review and any ratification hold. The ruling directs the
  record; it does not ratify it.

## Context

`sim/ro-vth-drift-sensitivity/analysis/sensitivity.py --check` replays a
committed record from its raw responses and folds five booleans into its exit
code: rows/summary replay (`ok`), calibration artifact (`ok_cal`), byte-identical
netlist regeneration (`ok_gen`), file provenance (`prov_ok`) and the coverage
manifest (`manifest_ok`).

The provenance leg compares two of the record's four file pins -- the
`generator_sha256` pin on `campaign.py` and the `aging_sha256` pin on
`aging.py` -- against the current bytes of those files. The other two pins in
the same record (`manifest_sha256`, `analysis_sha256`) are **not** read by the
exit code at all: `analysis/sensitivity.py`, the record's own reducer, has
moved since the record was minted and `check()` says nothing about it.

That asymmetry was already visible before the event that forced this decision.
Since #487/#492 consolidated the digest helper into `layout/bin/_hashing.py`
(`aging.sha256_file` *is* the shared helper), any refactor that touches the
helper moves `aging.py`'s bytes, and every record pinning a pre-move digest
stopped replaying -- not because its evidence changed, but because a shared
helper two directories away did. The DR-0005 superseding record
`20261113-150554-fb302c35` was the first to break this way on `main`: rows,
summary, calibration and byte-identical netlist regeneration all still MATCH;
only the `aging_sha256` leg reported DIFFER, and the replay exited 1
(#528, #516, #517).

The record's pins still have value -- they say *which bytes produced this
record* -- but folding them into the replay verdict conflates "the evidence
does not reproduce" with "the code has moved on". A pinned-file digest is a
provenance *report*, not a replay *gate*.

The pin history makes the pattern clear: `aging.py`'s digest moved
`4af3c5e7...` (01309d60) -> `25607e21...` (c52cc9ba, #455) -> `f96b7db0...`
(0fd83357, #492), and the repo already tried and reversed within one day
(242b2ae1 -> c52cc9ba) the stance of freezing hash-pinned sim scripts to keep
records replaying. Freezing bytes to satisfy pins fights the refactors the
repo needs; the pins should not gate.

## Decision

`check()`'s exit code shall be decided by `ok and ok_cal and ok_gen and
manifest_ok` -- **`prov_ok` is removed from the fold.** Specifically:

- **What a provenance pin asserts, after this change**: a record's
  `provenance` block records *which bytes produced the record when it was
  minted*. It is historical metadata. It is **not** an assertion that the
  current tree still carries those bytes, and a mismatch is expected drift as
  the code evolves -- not a replay failure.
- **The report stays**: `check()` still computes both provenance legs and
  still prints `generator hashes: MATCH|DIFFER`. A stale pin remains visible
  in every replay; it just no longer decides the exit code.
- **Byte-identical netlist regeneration (`ok_gen`) stays the discriminator**:
  if the current generator no longer reproduces the committed netlists
  byte-for-byte, the replay still exits 1. This is the leg that detects a
  behaviour change, and it is what the study README's refusal guidance already
  tells readers to run.
- **Accepted loss**: a behaviour change that still produces byte-identical
  netlists is no longer caught by `check()`'s exit code. The behavioural guard
  on the shared digest helper is `layout/test_hashing.py` (wired into CI since
  #493/#534), which exercises `_hashing.py` directly; the replay's own
  rows/summary and calibration legs re-derive the record's numbers from raw
  responses, so a semantic change that alters any committed number still
  fails. The residual gap -- a change that alters behaviour but neither any
  replayed number nor any generated netlist byte -- is accepted by this
  record.
- **The controls path is untouched**: a `kind == "controls"` record never read
  provenance; it still does not.
- **No record is minted or edited.** `sim/` evidence is append-only, and this
  change deliberately adds no superseding record for a pure byte move: the
  chain's tip keeps pinning the bytes that produced it. Re-minting a 796 KB /
  110-file corner bundle whose rows and summary would be byte-identical was
  the declined alternative (option (a) of #528's decision block).

## Consequences

- `sim/ro-vth-drift-sensitivity/analysis/sensitivity.py`: `prov_ok` removed
  from the exit fold; legs and print retained. The DR-0005 superseding record
  replays rc=0 again while still printing `generator hashes: DIFFER`; the
  superseded record still exits 1 (on rows **and** calibration, independent of
  provenance); the controls record still exits 0.
- Existing records are **not** rewritten and no new record is minted; the
  pinned digests stay stale-by-design for files that have since moved.
- `signoff` attest item 9 (which pins `sensitivity.py` itself) is regenerated
  mechanically via `attest.py --write 9`; the re-render of
  `signoff/t1-report.json` uses the CI-pinned `klayout-tools==0.8.0` grader.
- Refactors that move pinned sim scripts no longer break record replay. A
  future refactor must not use this as cover for a behaviour change: `ok_gen`
  still gates, and `layout/test_hashing.py` still guards the digest helper.
