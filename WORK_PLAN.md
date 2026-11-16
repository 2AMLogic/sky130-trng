# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#464**: feat: netlist through bounded `klt netlist` instead of a raw xschem call

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

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **#507**: bug: committed whole-block startup-probe requests carry 9 measurements past their own t_stop and timeouts the generator no longer emits
- **#535**: Consolidate duplicated rel/load_json/klt_env/_klayout/dumps helpers in layout/bin

## In Progress

Issues currently being built (`loom:building`).

- **#221**: Decision record request: local mismatch can cap tt raw-bit H below DR-0004's 0.5 floor; adjacent rings approach 1:1
- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter
- **#371**: Regenerate composite layout cells, trng_digital/trng_whole and pex libraries under klayout-tools 0.8.0
- **#381**: verify-whole: adapt the whole-block harness to klayout-tools 0.8.0 VNB handling
- **#460**: Replace raw xschem call and duplicated post-processing in design/netlist.py with klt netlist
- **#485**: Declare an evidence mapping for the Power row in the characterization report
- **#493**: Wire layout/test_hashing.py into CI: the shared digest helper's only regression guard has never run on a PR
- **#496**: Harden the gate-model reduction against silent-input defects (four latent paths from #486)
- **#497**: Consolidate the seven hand-rolled corner-bundle readers in six sim studies: the writer half already lives in evidence_record.py
- **#498**: ro-vth-drift-sensitivity: controls record's aging_sha256 pin invalidated by the #487 digest refactor
- **#501**: Remove _NoExitCodes Path subclass: replace the .parent-lying shim with an exit_lookup parameter on compaction.summarize_run
- **#509**: Finish the #412 deferral: ~18 inline importlib loader blocks remain in sim scripts, and the shared loadmod helper still lives under sim/tests/
- **#514**: signoff/README.md's t1-report regeneration command carries no klt version pin, so a host klt silently renders a wrong build block
- **#523**: Finish PDR-0001's deferred follow-up: generate-agents-md.sh still fails with a doubled .loom/ path

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#483**: docs: roadmap as of 2026-11-13
- **#511**: refactor: one shared corner-bundle reader beside the bundle writer
- **#534**: ci: wire layout/test_hashing.py into the PR-blocking lint job; refresh the item-10 attestation chain
- **#537**: fix: make the gate-model evidence pipeline fail closed on incomplete or unvalidated input

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#388**: fix(verify): strip klt 0.8.0 VNB from abstracted stubs, regenerate whole-block evidence
- **#464**: feat: netlist through bounded `klt netlist` instead of a raw xschem call
- **#524**: docs(signoff): pin the t1-report regeneration command to klayout-tools 0.8.0
- **#526**: feat(signoff): declare the Power evidence mapping in the characterization report
- **#529**: fix: generate-agents-md.sh doubled .loom/ path; accept PDR-0001's deferred follow-up

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
- **#485**: Declare an evidence mapping for the Power row in the characterization report *(curated)*
- **#493**: Wire layout/test_hashing.py into CI: the shared digest helper's only regression guard has never run on a PR *(curated)*
- **#496**: Harden the gate-model reduction against silent-input defects (four latent paths from #486) *(curated)*
- **#498**: ro-vth-drift-sensitivity: controls record's aging_sha256 pin invalidated by the #487 digest refactor *(curated)*
- **#507**: bug: committed whole-block startup-probe requests carry 9 measurements past their own t_stop and timeouts the generator no longer emits *(curated)*
- **#514**: signoff/README.md's t1-report regeneration command carries no klt version pin, so a host klt silently renders a wrong build block *(curated)*
- **#519**: sim/: committed-record replay is not reproducible across CPython versions (ro-vth-drift-sensitivity + xor-combining-alternatives; MATCHES on 3.12, DIFFERS on CI's 3.11) *(curated)*
- **#532**: Two residual uncheckable facts around the decision-record index: README's record count, and the undocumented oldest-first `## Status` ordering *(curated)*

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
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 6 |
| Ready (`loom:issue`) | 3 |
| In Progress (`loom:building`) | 14 |
| PRs awaiting review | 4 |
| Approved PRs awaiting merge | 5 |
| Curated | 20 |
| Architect / Hermit proposals | 7 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
