# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
_Generated: 2026-11-20T20:57:15Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#524**: docs(signoff): pin the t1-report regeneration command to klayout-tools 0.8.0
- **#529**: fix: generate-agents-md.sh doubled .loom/ path; accept PDR-0001's deferred follow-up

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#174**: Whole-block characterization: post-layout PVT, dynamic power and IR evidence
- **#307**: Whole-block 12-point PVT matrix: run on the klt batch fleet once the runner image matches the client (follow-up of #174)
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **#372**: Move the layout klt pin (pdk-nightly.yml, pdk.json, REPRODUCE.md) to klayout-tools 0.8.0
- **#383**: pdk-nightly is red
- **#431**: DR-0017 follow-up: analog-chain-only feasibility probe, then gate-level co-simulation generator and reducer for the whole-block PVT matrix
- **#595**: Whole-block PVT (DR-0017 option b): choose and record the boundary-load model and the Liberty deck for each (T, Vdd) point

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **#595**: Whole-block PVT (DR-0017 option b): choose and record the boundary-load model and the Liberty deck for each (T, Vdd) point
- **#600**: Raw rate row (> 1 Mbps): evidence study of sample-before-combine and higher-jitter ring options against the rate, power and area rows

## In Progress

Issues currently being built (`loom:building`).

- **#221**: Decision record request: local mismatch can cap tt raw-bit H below DR-0004's 0.5 floor; adjacent rings approach 1:1
- **#371**: Regenerate composite layout cells, trng_digital/trng_whole and pex libraries under klayout-tools 0.8.0
- **#381**: verify-whole: adapt the whole-block harness to klayout-tools 0.8.0 VNB handling
- **#523**: Finish PDR-0001's deferred follow-up: generate-agents-md.sh still fails with a doubled .loom/ path
- **#598**: T1 item 6: reduce the committed local-mismatch Monte Carlo into klt yield reports and record the item-6 verdict (6.analog)
- **#602**: WORK_PLAN.md Important/Ready sections drift: hand-applied Guide deltas under-report ready work

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#388**: fix(verify): strip klt 0.8.0 VNB from abstracted stubs, regenerate whole-block evidence
- **#524**: docs(signoff): pin the t1-report regeneration command to klayout-tools 0.8.0
- **#529**: fix: generate-agents-md.sh doubled .loom/ path; accept PDR-0001's deferred follow-up
- **#601**: docs: Guide document maintenance update

## Proposed

Issues carrying `loom:curated`.

- **#5**: Champion: Merge-Risk Hold Digest *(curated)*
- **#174**: Whole-block characterization: post-layout PVT, dynamic power and IR evidence *(curated)*
- **#221**: Decision record request: local mismatch can cap tt raw-bit H below DR-0004's 0.5 floor; adjacent rings approach 1:1 *(curated)*
- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter *(curated)*
- **#262**: Operator decision request: end-of-life Vth-drift sensitivity vs DR-0003 Q margin and DR-0004 health cutoffs (from #254) *(curated)*
- **#289**: Extend seeded transistor raw-bit model cross-checks beyond nominal PVT *(curated)*
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3 *(curated)*
- **#347**: Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact) *(curated)*
- **#371**: Regenerate composite layout cells, trng_digital/trng_whole and pex libraries under klayout-tools 0.8.0 *(curated)*
- **#381**: verify-whole: adapt the whole-block harness to klayout-tools 0.8.0 VNB handling *(curated)*
- **#431**: DR-0017 follow-up: analog-chain-only feasibility probe, then gate-level co-simulation generator and reducer for the whole-block PVT matrix *(curated)*
- **#514**: signoff/README.md's t1-report regeneration command carries no klt version pin, so a host klt silently renders a wrong build block *(curated)*
- **#595**: Whole-block PVT (DR-0017 option b): choose and record the boundary-load model and the Liberty deck for each (T, Vdd) point *(curated)*
- **#596**: Whole-block PVT (DR-0017 option b): build the coupled analog + gate-model deck and measure one fleet run to size the 12-point matrix *(curated)*
- **#597**: T1 item 7 (analog): produce a klt pex schematic-vs-extracted delta report for sampler_core and cite it as 7.analog *(curated)*
- **#598**: T1 item 6: reduce the committed local-mismatch Monte Carlo into klt yield reports and record the item-6 verdict (6.analog) *(curated)*
- **#599**: Area row (< 0.05 mm2): measure each structural option DR-0010 names, starting from the repaired 65 % floorplan, and find what limits the layout *(curated)*
- **#600**: Raw rate row (> 1 Mbps): evidence study of sample-before-combine and higher-jitter ring options against the rate, power and area rows *(curated)*
- **#602**: WORK_PLAN.md Important/Ready sections drift: hand-applied Guide deltas under-report ready work *(curated)*

## Proposed (Architect / Hermit)

- **#463**: Remove stale package.json test/lint/check scripts: npm run check:all passes on 5 of the 26 test files CI runs *(hermit)*
- **#470**: Consolidate the eight hand-rolled SPICE continuation-line folders: three behaviours for the same input across layout and sim scripts *(hermit)*
- **#475**: Remove the 63-entry pull_request paths filter from ci.yml: 26 entries are redundant and PR-blocking checks read files it does not cover *(hermit)*
- **#490**: Consolidate the three copies of merged(): the cross-directory carve-out rationale is measurably false *(hermit)*
- **#491**: Remove the two byte-identical 15 MB netlist.cir copies under sim/post-layout-whole-block/runs/: #174 already ratified them as regenerated, and .gitignore's pattern misses the runs/ path *(hermit)*
- **#494**: Stop committing 11 MB of all-null antenna skeleton in layout/trng_digital/erc.json: 98.6% of the repo's largest file records that a check did not run *(hermit)*
- **#495**: Continue the #173 seam: move ~500 lines of PDK-free verdict logic out of verify-whole.py into verify_whole_lib.py *(hermit)*

## Epics

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#170**: Whole-block integration: compose analog+digital GDS, block DRC/LVS and post-layout PVT (remaining #18 AC3)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Very important | 0 |
| Important | 7 |
| Ready (`loom:issue`) | 4 |
| In Progress (`loom:building`) | 6 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 4 |
| Curated | 19 |
| Architect / Hermit proposals | 7 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
