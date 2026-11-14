# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#464**: feat: netlist through bounded `klt netlist` instead of a raw xschem call

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#488**: bug: whole-block deck PWL stimulus ramps between cycles instead of holding, so bus inputs never switch cleanly

## Important

`loom:important`; taken before unlabelled work.

- **#174**: Whole-block characterization: post-layout PVT, dynamic power and IR evidence
- **#307**: Whole-block 12-point PVT matrix: run on the klt batch fleet once the runner image matches the client (follow-up of #174)
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **#372**: Move the layout klt pin (pdk-nightly.yml, pdk.json, REPRODUCE.md) to klayout-tools 0.8.0
- **#383**: pdk-nightly is red
- **#431**: DR-0017 follow-up: analog-chain-only feasibility probe, then gate-level co-simulation generator and reducer for the whole-block PVT matrix
- **#500**: Consolidate the eleven raw `klt` call sites outside `_klt_common`: two spellings of `klt_version` feed string-equality pin gates, and one `pdk find` scrapes klt's text output

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **#488**: bug: whole-block deck PWL stimulus ramps between cycles instead of holding, so bus inputs never switch cleanly
- **#497**: Consolidate the seven hand-rolled corner-bundle readers in six sim studies: the writer half already lives in evidence_record.py
- **#501**: Remove _NoExitCodes Path subclass: replace the .parent-lying shim with an exit_lookup parameter on compaction.summarize_run

## In Progress

Issues currently being built (`loom:building`).

- **#221**: Decision record request: local mismatch can cap tt raw-bit H below DR-0004's 0.5 floor; adjacent rings approach 1:1
- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter
- **#371**: Regenerate composite layout cells, trng_digital/trng_whole and pex libraries under klayout-tools 0.8.0
- **#381**: verify-whole: adapt the whole-block harness to klayout-tools 0.8.0 VNB handling
- **#460**: Replace raw xschem call and duplicated post-processing in design/netlist.py with klt netlist
- **#484**: Correct stale decision-record status text in README, spec/README and the Chipalooza proposal
- **#487**: Consolidate the nine hand-rolled in-memory sha256 helpers onto _hashing: two same-named functions in layout/bin return different formats
- **#500**: Consolidate the eleven raw `klt` call sites outside `_klt_common`: two spellings of `klt_version` feed string-equality pin gates, and one `pdk find` scrapes klt's text output

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#483**: docs: roadmap as of 2026-11-13
- **#499**: fix(spec): check the decision-record index against front matter, not the first history word
- **#503**: refactor(klt): read the klt version and pdk find through one shared contract

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#388**: fix(verify): strip klt 0.8.0 VNB from abstracted stubs, regenerate whole-block evidence
- **#464**: feat: netlist through bounded `klt netlist` instead of a raw xschem call

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
- **#460**: Replace raw xschem call and duplicated post-processing in design/netlist.py with klt netlist *(curated)*
- **#484**: Correct stale decision-record status text in README, spec/README and the Chipalooza proposal *(curated)*
- **#485**: Declare an evidence mapping for the Power row in the characterization report *(curated)*
- **#488**: bug: whole-block deck PWL stimulus ramps between cycles instead of holding, so bus inputs never switch cleanly *(curated)*

## Proposed (Architect / Hermit)

- **#463**: Remove stale package.json test/lint/check scripts: npm run check:all passes on 5 of the 26 test files CI runs *(hermit)*
- **#470**: Consolidate the eight hand-rolled SPICE continuation-line folders: three behaviours for the same input across layout and sim scripts *(hermit)*
- **#475**: Remove the 63-entry pull_request paths filter from ci.yml: 26 entries are redundant and PR-blocking checks read files it does not cover *(hermit)*
- **#490**: Consolidate the three copies of merged(): the cross-directory carve-out rationale is measurably false *(hermit)*
- **#491**: Remove the two byte-identical 15 MB netlist.cir copies under sim/post-layout-whole-block/runs/: #174 already ratified them as regenerated, and .gitignore's pattern misses the runs/ path *(hermit)*
- **#494**: Stop committing 11 MB of all-null antenna skeleton in layout/trng_digital/erc.json: 98.6% of the repo's largest file records that a check did not run *(hermit)*
- **#495**: Continue the #173 seam: move ~500 lines of PDK-free verdict logic out of verify-whole.py into verify_whole_lib.py *(hermit)*
- **#504**: Finish the #392 deferral: seven reducers hand-roll the record-minting tail because record_footer cannot say Supersedes *(hermit)*

## Epics

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#170**: Whole-block integration: compose analog+digital GDS, block DRC/LVS and post-layout PVT (remaining #18 AC3)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 1 |
| Important | 7 |
| Ready (`loom:issue`) | 4 |
| In Progress (`loom:building`) | 8 |
| PRs awaiting review | 3 |
| Approved PRs awaiting merge | 2 |
| Curated | 15 |
| Architect / Hermit proposals | 8 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
