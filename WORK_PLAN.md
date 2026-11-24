# Work Plan

This roadmap is generated from the current GitHub label state.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#524**: docs(signoff): pin the t1-report regeneration command to klayout-tools 0.8.0
- **#612**: sim/area-limiter-study: measure the area row's structural options (FIFO storage leads at 47.5%, best combination 0.0607 mm2)
- **#620**: feat(sim): raw-rate row options evidence -- sample-before-combine and 3-inversion ring study
- **#628**: sim: measured sampler_core active-power budget at Ts=20us; DR-0021 corrected to measured values
- **#684**: docs(signoff): correct stale klt signoff --attest availability prose and grader-pin cross-ref
- **#709**: feat(signoff): regenerate item-9 attestation aggregate on main (DR-0021)
- **#711**: feat(digital): two-word FIFOs with RTL and mapped-netlist equivalence evidence

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
- **#596**: Whole-block PVT (DR-0017 option b): build the coupled analog + gate-model deck and measure one fleet run to size the 12-point matrix

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#230**: CI: guard that every test_*.py is wired into a CI workflow and path filter
- **#314**: Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3

## In Progress

Issues currently being built (`loom:building`).

- **#221**: Decision record request: local mismatch can cap tt raw-bit H below DR-0004's 0.5 floor; adjacent rings approach 1:1
- **#371**: Regenerate composite layout cells, trng_digital/trng_whole and pex libraries under klayout-tools 0.8.0
- **#381**: verify-whole: adapt the whole-block harness to klayout-tools 0.8.0 VNB handling
- **#599**: Area row (< 0.05 mm2): measure each structural option DR-0010 names, starting from the repaired 65 % floorplan, and find what limits the layout
- **#600**: Raw rate row (> 1 Mbps): evidence study of sample-before-combine and higher-jitter ring options against the rate, power and area rows
- **#604**: Design iteration: sampler_core analog active power exceeds the 500 uW target at ff/high-Vdd corners (pre-layout already; post-layout adds +6-13%)
- **#679**: Two more stale klt-pin/verb-availability prose claims survive #674 (pdk-nightly.yml comment, signoff/README.md attest note)
- **#692**: corner-run repo_state() reports dirty: false when git status cannot run, and mint_record has no working-tree disclosure
- **#697**: Committed signoff attestation artifacts serialize every concurrent sim/ PR into a merge-conflict treadmill
- **#701**: Adopt two-word raw and conditioned FIFOs in DR-0004 and prove the production RTL and mapped netlists
- **#749**: ro_array_core recipe no longer rebuilds: 0.8.0 leaf regens moved the taps its declared ports name (compose-cell --check red)
- **#755**: layout/sampler_core/README.md's latest-increment paragraph quotes 8399 polygons and the 0.3.0 klt pin; committed GDS measures 8408 on 0.6.0+g5edb557f91d0

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#756**: docs(layout): align sampler_core README latest-increment stats with committed evidence

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#388**: fix(verify): strip klt 0.8.0 VNB from abstracted stubs, regenerate whole-block evidence
- **#524**: docs(signoff): pin the t1-report regeneration command to klayout-tools 0.8.0
- **#612**: sim/area-limiter-study: measure the area row's structural options (FIFO storage leads at 47.5%, best combination 0.0607 mm2)
- **#620**: feat(sim): raw-rate row options evidence -- sample-before-combine and 3-inversion ring study
- **#628**: sim: measured sampler_core active-power budget at Ts=20us; DR-0021 corrected to measured values
- **#684**: docs(signoff): correct stale klt signoff --attest availability prose and grader-pin cross-ref
- **#709**: feat(signoff): regenerate item-9 attestation aggregate on main (DR-0021)
- **#711**: feat(digital): two-word FIFOs with RTL and mapped-netlist equivalence evidence

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
- **#596**: Whole-block PVT (DR-0017 option b): build the coupled analog + gate-model deck and measure one fleet run to size the 12-point matrix *(curated)*
- **#599**: Area row (< 0.05 mm2): measure each structural option DR-0010 names, starting from the repaired 65 % floorplan, and find what limits the layout *(curated)*
- **#600**: Raw rate row (> 1 Mbps): evidence study of sample-before-combine and higher-jitter ring options against the rate, power and area rows *(curated)*
- **#604**: Design iteration: sampler_core analog active power exceeds the 500 uW target at ff/high-Vdd corners (pre-layout already; post-layout adds +6-13%) *(curated)*
- **#679**: Two more stale klt-pin/verb-availability prose claims survive #674 (pdk-nightly.yml comment, signoff/README.md attest note) *(curated)*
- **#692**: corner-run repo_state() reports dirty: false when git status cannot run, and mint_record has no working-tree disclosure *(curated)*
- **#697**: Committed signoff attestation artifacts serialize every concurrent sim/ PR into a merge-conflict treadmill *(curated)*
- **#701**: Adopt two-word raw and conditioned FIFOs in DR-0004 and prove the production RTL and mapped netlists *(curated)*
- **#749**: ro_array_core recipe no longer rebuilds: 0.8.0 leaf regens moved the taps its declared ports name (compose-cell --check red) *(curated)*
- **#755**: layout/sampler_core/README.md's latest-increment paragraph quotes 8399 polygons and the 0.3.0 klt pin; committed GDS measures 8408 on 0.6.0+g5edb557f91d0 *(curated)*

## Proposed (Architect / Hermit)

- **#470**: Consolidate the eight hand-rolled SPICE continuation-line folders: three behaviours for the same input across layout and sim scripts *(hermit)*
- **#495**: Continue the #173 seam: move ~500 lines of PDK-free verdict logic out of verify-whole.py into verify_whole_lib.py *(hermit)*

## Epics

- **#3**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#170**: Whole-block integration: compose analog+digital GDS, block DRC/LVS and post-layout PVT (remaining #18 AC3)

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 7 |
| Very important | 0 |
| Important | 7 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 12 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 8 |
| Curated | 22 |
| Architect / Hermit proposals | 2 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
