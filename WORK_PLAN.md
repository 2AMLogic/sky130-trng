# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

- **#218**: ci: run volume-model and ripple-reduction tests in PR-blocking job

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter

## In Progress

Issues currently being built (`loom:building`).

- **#226**: Measure digital floorplan compaction feasibility against the unchanged area target

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#218**: ci: run volume-model and ripple-reduction tests in PR-blocking job

## Proposed

Issues carrying `loom:curated`.

- **#162**: README: embed the fleet burndown chart (one line) *(curated)*
- **#174**: Whole-block characterization: post-layout PVT, dynamic power and IR evidence *(curated)*
- **#226**: Measure digital floorplan compaction feasibility against the unchanged area target *(curated)*
- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter *(curated)*

## Proposed (Architect / Hermit)

- **#201**: Gated-off analog block idle/leakage across the full PVT envelope incl. +125 C, with combined digital standby estimate *(architect)*
- **#232**: CI: enforce the sim/ append-only record rule (fail PRs that modify, rename or delete committed records) *(architect)*

## Epics

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#170**: Whole-block integration: compose analog+digital GDS, block DRC/LVS and post-layout PVT (remaining #18 AC3)

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 4 |
| Architect / Hermit proposals | 2 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
