---
dr: DR-0016-evidence-bytes-in-artifact-store
title: New sim evidence bytes go to the fleet artifact store; git keeps a manifest and a summary
status: Proposed
date: 2026-10-23
deciders: unratified -- Proposed by the Builder on #347; ratification is an operator action
supersedes: "n/a -- changes the evidence-handling convention for NEW runs only. It relaxes no ratified result, spec value, target-table row or verdict, and edits no existing record."
superseded_by: n/a
related: "#347 (this record), 2AMLogic/2am#5553 (fleet decision), 2AMLogic/sg13g2-comparator#319 / #321 (reference implementation), sim/README.md (append-only rule), sim/bin/artifact_store.py, sim/bin/check_artifact_manifests.py"
---

# DR-0016: new sim evidence bytes go to the artifact store

## Status

- 2026-10-23: **Proposed.** Not accepted by anyone; ratification is an
  operator action. The fleet-level decision is 2AMLogic/2am#5553; this record
  only adapts this repository's writers to it.

## Context

About 231 MB of raw run output (ngspice logs, GDS, P&R reports) is committed
under `sim/` and `layout/`, and every campaign adds more. The fleet decision is
that evidence bytes are private and live in a common artifact store, while
manifests (name, size, sha256, `artifact:<key>` URI) are public and safe to
commit.

## Decision

1. For **new** runs the shared minting paths (`sim/bin/corner-run.py` and
   `evidence_record.mint_behavioral_record`) stage raw outputs in the
   git-ignored `.artifact-staging/`, store them with `klt artifact put`, and
   commit only `manifests/artifacts/<bench>-<run-id>.manifest.json` plus a
   Markdown summary `sim/<bench>/artifacts/<run-id>.md`. The record JSON names
   the manifest in `artifact_manifest`.
2. **Fail closed.** `$KLT_ARTIFACT_BROKER` unset, a `klt` without
   `artifact put`, or an unreachable broker exits nonzero and writes nothing
   under `manifests/` or `sim/`. There is no fallback that commits the bytes.
3. `sim/bin/check_artifact_manifests.py` runs in CI: manifest schema,
   `artifact:` URIs only, no bucket/account text, and no stored object's bytes
   (matched by sha256 and size) tracked in git.
4. Manifests and summaries join the append-only rule
   (`sim/bin/check_records_append_only.py`).
5. **Manifest-forward only.** Existing committed evidence stays; no history
   rewrite. Per-bench scripts that write `runs/`/`corners/` directly instead of
   going through the shared minting paths are unchanged and are follow-ups.

## Consequences

- Reproducing a run's raw bytes needs access to the store
  (`klt artifact get|verify <manifest>` from a fleet worker); the manifest pins
  the exact sha256, so an audit is by hash, not by trust.
- `klt` with `artifact` (klayout-tools >= 7e3561f) is needed to write new
  evidence. The `signoff-check` job keeps its `klayout-tools==0.7.0` pin; it
  does not use the artifact verbs.
- CI cannot reach the broker, so the live `klt artifact verify` is an
  out-of-band step on the first real campaign run after merge.
- This changes no simulation result and relaxes no ratified spec. All entropy
  claims remain simulation-derived and **provisional until measured on
  silicon**.
