# docs/decisions — process and tooling decision records

This directory holds decision records for **process, tooling, and repo-
infrastructure** questions — anything that is not a circuit-spec decision.

It exists as a sibling to, and is explicitly **not** the same track as,
[`spec/decision-records/`](../../spec/decision-records/). `CLAUDE.md` ties
`spec/decision-records/` specifically to circuit-spec changes ("Spec changes
go through `spec/` with a decision record"), and the two ratification review
keys this repo uses for that track (`ratification/ee-key/`,
`ratification/market-key/`) are scoped, by their own `SKILL.md` files, to
spec rows: device-physics claims, `sim/`-backed evidence tiers, and
competitor-datasheet comp tables. None of that machinery has jurisdiction
over — or a rubric that fits — a question like "how should we fix a broken
installed shell script." Filing process decisions here instead of under
`spec/decision-records/` keeps that track's naming and review pipeline
unambiguous, and keeps a process record from being silently pulled into (or
silently ignored by) a review process built for a different kind of claim.

## Conventions

Records here reuse the frontmatter shape established in
`spec/decision-records/` (`status`, `date`, `deciders`, `supersedes`,
`superseded_by`, `related`) where it transfers cleanly, but use a distinct
`PDR-NNNN` (Process Decision Record) numbering track so the two series never
collide and a reader can immediately tell, from the filename alone, which
review path (if any) a given record is subject to.

As with `spec/decision-records/`, a record's `status: Proposed` here means
drafted and not accepted by anyone — ratification/acceptance of a process
decision is a human (or Champion, per the repo's normal PR-review lifecycle)
action, not something a record self-declares.

## Records

- [`PDR-0001-generate-agents-md-path-fix.md`](PDR-0001-generate-agents-md-path-fix.md)
  — **Proposed**. Recommends the local-fix option (of three considered) for
  issue #75's broken `.loom/scripts/generate-agents-md.sh` relative path,
  and records why the two-key ratification mechanism used for circuit-spec
  rows does not apply to this kind of record.
