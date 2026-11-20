# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
_Generated: 2026-11-20T02:22:32Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#524**: docs(signoff): pin the t1-report regeneration command to klayout-tools 0.8.0
- **#529**: fix: generate-agents-md.sh doubled .loom/ path; accept PDR-0001's deferred follow-up

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#174**: Whole-block characterization: post-layout PVT, dynamic power and IR evidence *(held)*
- **#307**: Whole-block 12-point PVT matrix: run on the klt batch fleet once the runner image matches the client (follow-up of #174) *(held)*
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **#372**: Move the layout klt pin (pdk-nightly.yml, pdk.json, REPRODUCE.md) to klayout-tools 0.8.0 *(held)*
- **#383**: pdk-nightly is red *(held)*
- **#431**: DR-0017 follow-up: analog-chain-only feasibility probe, then gate-level co-simulation generator and reducer for the whole-block PVT matrix *(held)*

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3

## In Progress

Issues currently being built (`loom:building`).

- **#221**: Decision record request: local mismatch can cap tt raw-bit H below DR-0004's 0.5 floor; adjacent rings approach 1:1
- **#371**: Regenerate composite layout cells, trng_digital/trng_whole and pex libraries under klayout-tools 0.8.0
- **#381**: verify-whole: adapt the whole-block harness to klayout-tools 0.8.0 VNB handling
- **#514**: signoff/README.md's t1-report regeneration command carries no klt version pin, so a host klt silently renders a wrong build block
- **#523**: Finish PDR-0001's deferred follow-up: generate-agents-md.sh still fails with a doubled .loom/ path
- **#580**: design/netlist.py: no outer bound on the `klt netlist` subprocess, and a pre-release klt passes the floor

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#591**: fix: bound klt netlisting and enforce the tagged version floor

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#388**: fix(verify): strip klt 0.8.0 VNB from abstracted stubs, regenerate whole-block evidence
- **#524**: docs(signoff): pin the t1-report regeneration command to klayout-tools 0.8.0 — closes #514
- **#529**: fix: generate-agents-md.sh doubled .loom/ path; accept PDR-0001's deferred follow-up — closes #523

## Proposed

Issues carrying `loom:curated`.

- **#5**: Champion: Merge-Risk Hold Digest *(curated)* *(held)*
- **#174**: Whole-block characterization: post-layout PVT, dynamic power and IR evidence *(curated)* *(held)*
- **#221**: Decision record request: local mismatch can cap tt raw-bit H below DR-0004's 0.5 floor; adjacent rings approach 1:1 *(curated)*
- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter *(curated)*
- **#262**: Operator decision request: end-of-life Vth-drift sensitivity vs DR-0003 Q margin and DR-0004 health cutoffs (from #254) *(curated)* *(held)*
- **#289**: Extend seeded transistor raw-bit model cross-checks beyond nominal PVT *(curated)* *(held)*
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3 *(curated)*
- **#347**: Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact) *(curated)* *(held)*
- **#371**: Regenerate composite layout cells, trng_digital/trng_whole and pex libraries under klayout-tools 0.8.0 *(curated)*
- **#381**: verify-whole: adapt the whole-block harness to klayout-tools 0.8.0 VNB handling *(curated)*
- **#431**: DR-0017 follow-up: analog-chain-only feasibility probe, then gate-level co-simulation generator and reducer for the whole-block PVT matrix *(curated)* *(held)*
- **#514**: signoff/README.md's t1-report regeneration command carries no klt version pin, so a host klt silently renders a wrong build block *(curated)*
- **#580**: design/netlist.py: no outer bound on the `klt netlist` subprocess, and a pre-release klt passes the floor *(curated)*

## Proposed (Architect / Hermit)

- **#463**: Remove stale package.json test/lint/check scripts: npm run check:all passes on 5 of the 26 test files CI runs *(hermit)* *(held)*
- **#470**: Consolidate the eight hand-rolled SPICE continuation-line folders: three behaviours for the same input across layout and sim scripts *(hermit)* *(held)*
- **#475**: Remove the 63-entry pull_request paths filter from ci.yml: 26 entries are redundant and PR-blocking checks read files it does not cover *(hermit)* *(held)*
- **#490**: Consolidate the three copies of merged(): the cross-directory carve-out rationale is measurably false *(hermit)* *(held)*
- **#491**: Remove the two byte-identical 15 MB netlist.cir copies under sim/post-layout-whole-block/runs/: #174 already ratified them as regenerated, and .gitignore's pattern misses the runs/ path *(hermit)* *(held)*
- **#494**: Stop committing 11 MB of all-null antenna skeleton in layout/trng_digital/erc.json: 98.6% of the repo's largest file records that a check did not run *(hermit)* *(held)*
- **#495**: Continue the #173 seam: move ~500 lines of PDK-free verdict logic out of verify-whole.py into verify_whole_lib.py *(hermit)* *(held)*

## Epics

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers) *(held)*
- **#170**: Whole-block integration: compose analog+digital GDS, block DRC/LVS and post-layout PVT (remaining #18 AC3) *(held)*

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Very important | 0 |
| Important | 6 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 2 |
| In Progress (`loom:building`) | 6 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 3 |
| Curated | 13 |
| Architect / Hermit proposals | 7 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
