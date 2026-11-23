# Work Log

Chronological record of recently merged pull requests and closed issues.

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)

### 2026-11-23

- **PR #704**: docs: version-qualify the no-verb claim for signoff items 1/2/9/10
- **PR #695**: fix: report corner-run repo dirty state as tri-state when git status fails
- **PR #694**: docs: retire superseded 7/22 count and 0.7.0 grader claims in signoff README
- **PR #689**: docs(signoff): restate T1 summary against the committed 0.8.0 report
- **PR #673**: fix(sim): refuse repeated measurement names in the template-lifted reducers
- **PR #667**: feat(evidence): disclose working-tree state in behavioral records
- **PR #605**: feat(sim): couple the transistor sampler to the routed gate model
- **Issue #700** (closed): sim/: reconcile compare_gate_model.duplicate_measurement_names() with sim/bin/measurement_names.py once PR #644 lands
- **Issue #696** (closed): signoff/README.md: 'klayout-tools has no verb behind these four items' is stale for item 1 on the 0.8.0 grader
- **Issue #691** (closed): signoff/README.md: dated 7/22 update line and two per-item 0.7.0 render claims are stale after #687
- **Issue #687** (closed): signoff/README.md T1 summary still says the report was rendered on klt 0.7.0; the committed report records v0.8.0
- **Issue #670** (closed): sim/: ten reducers still dedupe corner measurements into a name-keyed dict with no duplicate-name guard (#548's silent displacement, outside the two whole-block sites)
- **Issue #666** (closed): evidence_record: mint_behavioral_record pins repo_sha from HEAD with no dirty-tree disclosure, so a record can cite a revision that cannot produce it
- **Issue #475** (closed): Remove the 63-entry pull_request paths filter from ci.yml: 26 entries are redundant and PR-blocking checks read files it does not cover
- **PR #656**: refactor: route idle_leakage bundles via write_corner_bundle
- **PR #657**: refactor: route sim/ harness klt reads through _klt_common shared readers
- **PR #626**: fix(sim): re-hash 7.analog PEX run pins via the shared freshness loop
- **PR #652**: fix: raise BuildError, not IndexError, on a short device card in check_device_card
- **PR #629**: fix: score open() **kwargs splats as unestablishable write modes
- **PR #649**: fix(sim): drop the unscoreable last-cycle rdata word from whole-block requests
- **PR #645**: refactor: share one extracted-netlist renamer between pex-netlist and pex-measure
- **PR #685**: signoff: pin each harness's layout/bin and design helper closure in its own T1 inventory
- **PR #663**: docs: qualify WORK_LOG retention note for unmerged PRs #111 and #159
- **PR #688**: test: catch hashlib.new("sha256") fork shape in the no-fork guard
- **PR #686**: fix(ci): correct swapped #216/#289 suite pairings in ci.yml header
- **PR #675**: docs: add item-9 merge-conflict resolution recipe to signoff README
- **PR #681**: refactor(sim): consolidate remaining inline sha256 hexdigest sites onto _hashing
- **PR #678**: test: pin the plan-only reductions.input_load override from #595
- **PR #662**: ci: run the eight sim/tests suites ci.yml never wired
- **PR #677**: docs(signoff): correct stale 0.7.0 CI grader pin prose to 0.8.0
- **PR #664**: fix(sim): replay the five remaining --check reducers through shared replay_equal
- **PR #651**: fix(signoff): pin item 9's layout/bin import closure in its inventory
- **PR #607**: feat(sim): map the 12-point PVT matrix to Liberty decks and adopt boundary-load option 2
- **PR #665**: chore: remove stale npm test/lint/check scripts from package.json
- **Issue #655** (closed): Consolidate the last hand-rolled corner-bundle writer in idle_leakage.py onto evidence_record.write_corner_bundle
- **Issue #653** (closed): Consolidate remaining non-FV sim harness klt/path forks onto _klt_common
- **Issue #647** (closed): check_device_card: a short device card raises IndexError, not BuildError, breaking pex-measure's single documented failure mode
- **Issue #646** (closed): make-requests.py emits 32 rdata_k74_b* measurements the shared oracle cannot compare
- **Issue #638** (closed): Consolidate duplicated extracted-netlist renamer between pex-measure.py and pex-netlist.py
- **Issue #624** (closed): Record-tail guard treats open(path, **kwargs) as read-only, not as an unestablishable mode
- **Issue #619** (closed): Extend the 7.analog PEX freshness check to the report's remaining pinned repository inputs
- **Issue #650** (closed): T1 attestation still leaves two unpinned repo-local imports of attested sources (design/_pdk_search.py; items 2.* own closures)
- **Issue #637** (closed): Correct the WORK_LOG retention note for unmerged PRs #111 and #159
- **Issue #683** (closed): test_hashing.py no-fork guard: hashlib.new("sha256", ...) bypasses the AST scan
- **Issue #680** (closed): ci.yml header comment mis-pairs two of the eight #654 suites with their introducing issues (#216/#289 swapped)
- **Issue #672** (closed): T1 item-9 attestation hash makes any two concurrent sim/-touching PRs conflict on three generated files
- **Issue #669** (closed): Consolidate remaining 20 inline/helper sha256 .hexdigest() sites onto _hashing and guard against regrowth in test_hashing.py
- **Issue #668** (closed): test: pin plan.json's reductions.input_load to the settled boundary-load statement (no assertion guards the #595 fix)
- **Issue #671** (closed): Five sim/ reducer-replay unit suites are not invoked by any workflow
- **Issue #654** (closed): Eight sim/tests suites are never run by CI (ci.yml enumerates suites one by one; test_whole_block_reduction.py is one of them)
- **Issue #674** (closed): signoff/README.md prose still says the CI grader pin is 0.7.0; ci.yml installs 0.8.0
- **Issue #659** (closed): Consolidate remaining five sim/ --check reducers onto sim/bin/replay_equal.py: four fail under Python 3.11 sum(), one forks replay_diff
- **Issue #648** (closed): T1 attestation inventories pin sim/ harness source but not its layout/bin import closure
- **Issue #595** (closed): Whole-block PVT (DR-0017 option b): choose and record the boundary-load model and the Liberty deck for each (T, Vdd) point
- **Issue #463** (closed): Remove the four stale npm verification scripts from package.json

### 2026-11-22

- Note: removed 48 WORK_LOG records (42 here, 6 in the 2026-09 archive) that the 2026-10-18 Guide document-maintenance backfill (`e8b0dd38`) copied from `2AMLogic/gf180-usb2-phy`'s merged history. Each cited a number that also exists in this repo but resolved to unrelated work (wrong kind and title); the genuine records for the other 46 numbers are retained. The exceptions, #111 and #159, are PRs that closed without merging, and the log covers merged PRs and closed issues only, so they have no record of their own. Audit evidence and rationale: #633.
- **PR #643**: fix: preserve target mode when generate-agents-md.sh regenerates AGENTS.md
- **PR #635**: docs(work-log): remove 48 records backfilled from gf180-usb2-phy
- **Issue #640** (closed): generate-agents-md.sh's mktemp+mv render path tightens .loom/AGENTS.md from 644 to 600 on every regeneration
- **Issue #633** (closed): WORK_LOG.md carries three records from another repository's history (#149, #88, #87: USB UTMI PHY titles that do not match the forge)
- **PR #639**: fix: substitute {{INSTALL_DATE}} in generate-agents-md.sh for flattened installs
- **Issue #533** (closed): generate-agents-md.sh: no-arg run in a flattened install regresses {{INSTALL_DATE}} into the already-substituted .loom/AGENTS.md
- **PR #634**: docs: name klayout-tools 0.8.0 pin in attest.py docstring
- **Issue #631** (closed): signoff/attest.py:7 still names the 0.7.0 grader present-tense; CI has graded on 0.8.0 since issue #363
- **PR #529**: fix: generate-agents-md.sh doubled .loom/ path; accept PDR-0001's deferred follow-up
- **Issue #523** (closed): Finish PDR-0001's deferred follow-up: generate-agents-md.sh still fails with a doubled .loom/ path
- **PR #625**: test: guard the shared GDS geometry helpers against forks and compose-whole loaders
- **Issue #617** (closed): Guard the shared GDS geometry helpers against local copies and compose-whole loaders

### 2026-11-21

- **PR #623**: fix: classify open() mode in the record-tail guard so read-only opens pass
- **Issue #618** (closed): test_evidence_record_artifacts guard flags read-only open() of a record as a hand-rolled tail
- **PR #622**: chore: gitignore daemon-written .loom/account-ranking.codex runtime state
- **Issue #608** (closed): chore: gitignore the daemon's .loom/account-ranking.* runtime state (breaks check-main-clean for every builder)
- **PR #616**: refactor: extract the four GDS geometry helpers to _gds_geometry.py
- **Issue #613** (closed): Remove both dynamic compose-whole loaders by sharing the four GDS geometry helpers
- **PR #606**: sim(pex): cite a klt pex sampler_core delta report as 7.analog
- **Issue #597** (closed): T1 item 7 (analog): produce a klt pex schematic-vs-extracted delta report for sampler_core and cite it as 7.analog
- **PR #603**: docs: regenerate WORK_PLAN.md plan body from live labels via render_plan_body()
- **Issue #602** (closed): WORK_PLAN.md Important/Ready sections drift: hand-applied Guide deltas under-report ready work
- **Issue #615** (closed): Duplicate of #608, which tracks the missing ignore rule for Loom’s per-runtime account ranking file.

### 2026-11-20

- **Issue #580** (closed): design/netlist.py: no outer bound on the `klt netlist` subprocess, and a pre-release klt passes the floor
- **PR #591**: fix: bound klt netlisting and enforce the tagged version floor
- **Issue #460** (closed): Replace raw xschem call and duplicated post-processing in design/netlist.py with klt netlist
- **PR #464**: feat: netlist through bounded `klt netlist` instead of a raw xschem call

### 2026-11-18

- **Issue #587** (closed): Collapse the layered status preamble of challenge-4-proposal.md: ~110 lines of patched-in-place 'updated since' prose duplicate ROADMAP, layout/README and the scorecard
- **PR #588**: docs: collapse challenge-4-proposal status preamble to a summary of the recorded artifacts
- **Issue #547** (closed): sim/: replay_equal's abs_tol=1e-12 floor leaves sub-picosecond metrics (sigma_1, numerical_floor) effectively ungated — up to 155% relative change reads MATCH
- **PR #585**: fix(sim): drop the replay comparator's abs_tol floor -- gate every non-zero float at 1e-9 relative (DR-0020)

### 2026-11-17

- **Issue #583** (closed): WORK_PLAN's Ready section omits loom:issue items that also carry loom:curated

- **Issue #525** (closed): Four more reducers still hand-roll the record write tail outside mint_record/_publish_bundle
- **PR #578**: refactor(sim): mint the four remaining reducers through mint_record
- **Issue #498** (closed): ro-vth-drift-sensitivity: controls record's aging_sha256 pin invalidated by the #487 digest refactor
- **PR #517**: fix(sim): make the ro-vth-drift controls-pin refusal discriminate bytes from behaviour
- **Issue #576** (closed): Make the .meas bound-scan visit guard per-card, not per-request
- **PR #577**: test: make the .meas bound-scan visit guard per-card, not per-request
- **Issue #555** (closed): test: make the .meas bound scanner in test_make_requests.py unit-agnostic so a non-ns card cannot be silently skipped
- **PR #574**: test: fail loud on non-ns .meas bound units in the request bound scan
- **Issue #573** (closed): test_gate_model: the duplicate-name guard test does not exercise the scalar path it claims to
- **PR #575**: test: cover the scalar displacement shape the gate-model dedup guard refuses
- **PR #483**: docs: roadmap as of 2026-11-13
- **Issue #548** (closed): compare-gate-model: a DUPLICATE measurement name still shrinks the check set past the new count guard
- **PR #571**: fix: refuse duplicate measurement names the count guard cannot see

### 2026-11-16

- **PR #537**: fix: make the gate-model evidence pipeline fail closed on incomplete or unvalidated input
- **Issue #496** (closed): Harden the gate-model reduction against silent-input defects (four latent paths from #486)
- **PR #551**: ci: unfilter the pull_request trigger and add a CI Result aggregate verdict job
- **Issue #542** (closed): CI: give every PR one always-reporting verdict check, so main can require it (path-filtered ci.yml has none)
- **PR #569**: docs: reword loadmod.py docstring for its sim/bin home
- **Issue #567** (closed): sim/bin/loadmod.py docstring still tells callers to put sim/tests on sys.path
- **PR #565**: refactor(sim): move shared loadmod helper to sim/bin, drop tests-dir path inserts
- **Issue #549** (closed): Move the shared loadmod helper to sim/bin/: 20 production sim scripts now import from the tests directory
- **PR #563**: fix: apply read_corner_bundle prefix filter to missing notes too
- **Issue #560** (closed): read_corner_bundle: prefix= filters chunks but not the missing-notes list, and the docstring does not say so
- **PR #566**: refactor: write_json reuses dumps() for its JSON spelling
- **Issue #553** (closed): write_json re-implements _klt_common.dumps's spelling instead of calling it
- **PR #564**: spec: DR-0019 provenance pins report, not gate, in sensitivity.py --check
- **Issue #528** (closed): ro-vth-drift: #492's aging.py move broke the superseding record's --check replay (generator-hashes leg, rc=1) — live on main, unwired
- **PR #511**: refactor: one shared corner-bundle reader beside the bundle writer
- **Issue #497** (closed): Consolidate the seven hand-rolled corner-bundle readers in six sim studies: the writer half already lives in evidence_record.py
- **Issue #559** (closed): test_vth_drift.py fails on main: the Nov superseding record's aging_sha256 pin is stale, and CI never runs that test
- **PR #556**: test: detect hand-rolled record tails via AST path rendering
- **PR #541**: test: guard .meas AT=/TO= against the request's own .tran stop; ledger the stale startup probes
- **Issue #531** (closed): The #515 hand-rolled-tail guard's detector is spelling-sensitive: 5 of 8 plausible <rid>.md write spellings slip through
- **Issue #507** (closed): bug: committed whole-block startup-probe requests carry 9 measurements past their own t_stop and timeouts the generator no longer emits
- **PR #546**: fix: grade strict spec targets strictly in characterization report (lt/gt)
- **PR #540**: refactor: consolidate rel/load_json/klt_env/klayout_db/dumps into _klt_common
- **PR #543**: fix(sim): one shared cross-version replay equality for committed-record checks
- **PR #534**: ci: wire layout/test_hashing.py into the PR-blocking lint job; refresh the item-10 attestation chain
- **Issue #538** (closed): characterization_report.compare() has no strict `lt`/`gt`: the Power active check grades a "< 500 uW" target with `le 500`
- **Issue #535** (closed): Consolidate duplicated rel/load_json/klt_env/_klayout/dumps helpers in layout/bin
- **Issue #519** (closed): sim/: committed-record replay is not reproducible across CPython versions (ro-vth-drift-sensitivity + xor-combining-alternatives; MATCHES on 3.12, DIFFERS on CI's 3.11)
- **Issue #552** (closed): CI: revisit concurrency.cancel-in-progress once `CI Result` is a required context
- **Issue #493** (closed): Wire layout/test_hashing.py into CI: the shared digest helper's only regression guard has never run on a PR
- **PR #516**: refactor(sim): replace inline importlib loader blocks with shared loadmod helper
- **PR #510**: refactor: replace _NoExitCodes .parent shim with an exit_lookup parameter on summarize_run
- **PR #544**: docs: drop the uncheckable decision-record count from README; document oldest-first Status history
- **Issue #509** (closed): Finish the #412 deferral: ~18 inline importlib loader blocks remain in sim scripts, and the shared loadmod helper still lives under sim/tests/
- **Issue #501** (closed): Remove _NoExitCodes Path subclass: replace the .parent-lying shim with an exit_lookup parameter on compaction.summarize_run
- **Issue #532** (closed): Two residual uncheckable facts around the decision-record index: README's record count, and the undocumented oldest-first `## Status` ordering

### 2026-11-15

- **PR #526**: feat(signoff): declare the Power evidence mapping in the characterization report
- **PR #527**: fix: mint the controls record through mint_record and guard against new hand-rolled tails
- **PR #520**: refactor(idle-leakage): read request dirs through the shared request_dir walk
- **PR #503**: refactor(klt): read the klt version and pdk find through one shared contract
- **PR #499**: fix(spec): check the decision-record index against front matter, not the first history word
- **PR #492**: refactor: add sha256_text/sha256_bytes to _hashing and drop nine hand-rolled copies
- **Issue #536** (closed): test_vth_drift: superseding-record replay check fails at HEAD in a stdlib-only run
- **Issue #530** (closed): test_vth_drift.py fails on main (provenance generator-hash mismatch), and 8 sim/tests are absent from CI
- **Issue #485** (closed): Declare an evidence mapping for the Power row in the characterization report
- **Issue #521** (closed): A fifth private klt invoker remains: run-ir.py's klt_power never inspects the response for an `error` object
- **Issue #518** (closed): Remove five superseded signal routing-increment sets from layout/ro_array_core-placement-poc/: operator decision on the README's retention choice
- **Issue #515** (closed): sensitivity.py's controls record is still minted outside mint_record/_publish_bundle, with a footerless md
- **Issue #512** (closed): Finish the #469 consolidation: idle_leakage.py still hand-rolls a sixth request-directory walk
- **Issue #506** (closed): make-gate-model.py re-introduced hand-rolled sha256_text/sha256_file after #487 consolidated them
- **Issue #500** (closed): Consolidate the eleven raw `klt` call sites outside `_klt_common`
- **Issue #487** (closed): Consolidate the nine hand-rolled in-memory sha256 helpers onto _hashing
- **Issue #484** (closed): Correct stale decision-record status text in README, spec/README and the Chipalooza proposal
- **PR #513**: refactor(sim): mint the seven hand-rolled record tails through evidence_record
- **Issue #504** (closed): Finish the #392 deferral: seven reducers hand-roll the record-minting tail because record_footer cannot say Supersedes

### 2026-11-14

- **PR #508**: fix(whole-block): hold each driven input's PWL value, then switch over 100 ps
- **Issue #488** (closed): bug: whole-block deck PWL stimulus ramps between cycles instead of holding, so bus inputs never switch cleanly

- **PR #489**: feat: generate the digital half's gate-level ngspice model as a timed-delay XSPICE netlist
- **Issue #486** (closed): Choose and evidence the ngspice realisation of the gate-level digital half (first slice of #431 step 2)

### 2026-11-13

- **PR #479**: fix(post-layout-whole-block): write the port map next to -o, and name both klt builds when --check differs
- **Issue #478** (closed): make-netlist.py rewrites committed ports.json as a side effect, and its order + --check both diverge from the committed evidence
- **PR #477**: fix: fail spec-index check on unknown status word; drop 7 dead defs
- **Issue #471** (closed): Wire the unused STATUS_WORDS into check_spec_index (index status typos pass CI) and remove seven other never-referenced definitions
- **PR #473**: refactor(sim): one shared request-directory walk; stop the mismatch reducer dropping refused requests
- **Issue #469** (closed): Consolidate the five load_reqdir request-directory loaders: the mismatch reducer silently drops refused requests and still reports a full sample count
- **PR #474**: refactor(sim): one shared DR-0005 lock-proximity rule, and correct the two order-dependent reducers
- **Issue #467** (closed): Consolidate the five DR-0005 lock-proximity implementations in the sim reducers into one shared helper and correct the two order-dependent ones
- **PR #466**: refactor: one shared evidence path-hygiene rule for both digital harnesses
- **Issue #465** (closed): Consolidate the two drifted evidence path sanitizers in the digital synthesis and P&R harnesses into one shared helper
- **PR #458**: docs(spec): DR-0018 adopt <=200 uW worst-corner idle power envelope
- **Issue #446** (closed): Decision record: adopt (or not) an idle-power target for sampler_core from the #201 leakage survey

### 2026-11-07

- **PR #456**: refactor: use shared sha256_file in remaining sim/ scripts
- **Issue #455** (closed): Consolidate remaining sim/ file-digest helpers onto _hashing.sha256_file

### 2026-11-06

- **PR #453**: refactor: use shared sha256_file helper in sim/ scripts
- **Issue #452** (closed): Consolidate 12 duplicate sha256 file helpers in sim/ onto layout/bin/_hashing.py
- **PR #450**: sim: record whole-block 100 ns rate-probe timeout on re-pinned netlist
- **PR #448**: sim: record interrupted whole-block rate probe on re-pinned netlist
- **PR #444**: sim: add idle/leakage survey of the gated-off sampler_core across the PVT grid
- **Issue #449** (closed): Re-run the interrupted 100 ns whole-block rate probe on the re-pinned netlist
- **Issue #441** (closed): Re-run the 100 ns whole-block rate probe on the re-pinned netlist (965f1e6c) and record it
- **Issue #201** (closed): Gated-off analog block idle/leakage across the full PVT envelope incl. +125 C, with combined digital standby estimate
- **PR #443**: refactor(sim): share corner-bundle writer across sim reducers
- **PR #442**: refactor: share one sha256_file helper across layout/ and signoff/
- **Issue #392** (closed): Consolidate hand-rolled corner-bundle record minting in four sim reducers into evidence_record
- **Issue #326** (closed): Consolidate ~18 duplicated sha256 file-hash helpers into one shared helper

### 2026-11-05

- **PR #438**: sim: add DR-0017 provenance, partition check and obligations to whole-block tooling
- **PR #436**: fix(sim): rename whole-block netlist body nodes to canonical port names
- **Issue #435** (closed): make-netlist.py renames only the .SUBCKT port list; whole-block body keeps cluster names (94/123 ports unconnected)
- **PR #434**: sim: analog-chain-only feasibility probe (DR-0017 Step 1) and port-connectivity finding
- **PR #432**: docs(spec): accept DR-0017 with the claim-level condition (operator r6-q26)
- **PR #429**: docs(sim): mark superseded wake-up-transient not-run paragraphs historical
- **Issue #428** (closed): wake-up-transient README: 'What was and was not run' still says the grid is unrun
- **PR #427**: feat(sim): wake-up transient PVT envelope and noisy transistor leg from the batch fleet
- **Issue #216** (closed): Analog wake-up transient: time-to-steady-oscillation and first-window raw-bit bias vs the DR-0004 start-up window
- **PR #424**: feat(sim): shard wake-up batch requests under the fleet job ceiling
- **PR #423**: fix(sim): emit pw2nd diode as PDK subckt, scan all card models, re-pin netlist
- **PR #420**: fix(sim): make whole-block $-scrub guard linear and collision-only, re-pin netlist
- **Issue #422** (closed): Assess whether results citing old whole-block netlist hash bd694f2f need re-running after #420 re-pin
- **Issue #419** (closed): make-netlist.py --check: quadratic and false-positive $-scrub collision guard
- **PR #418**: docs: record whole-block klt extract rerun on Spot with stage timings
- **Issue #417** (closed): Bump klayout-tools pin 0.3.0 → 0.8.0
- **Issue #395** (closed): Measure the whole-block klt extract on current klt with --progress (on Spot) and report to klayout-tools#4594

### 2026-11-04

- **PR #405**: docs(spec): DR-0017 whole-block PVT reduction via gate-level digital behind a boundary
- **Issue #404** (closed): Decision record: reduced-work approach for the whole-block PVT matrix (prerequisite of #307)
- **PR #413**: refactor(sim): use shared load_module in five scripts instead of local _load
- **Issue #412** (closed): Consolidate duplicated importlib _load helpers in sim scripts onto shared load_module
- **Issue #415** (closed): Bump klayout-tools pin 0.3.0 → 0.5.0

### 2026-11-03

- **PR #410**: refactor(tests): use shared load_module in 13 sim tests
- **Issue #409** (closed): Use shared load_module in 16 remaining inline test loaders (follow-up to #342)
- **PR #407**: sim: add 100 ns rate-probe variant; record that it still times out
- **Issue #403** (closed): Whole-block fleet probe that finishes and reports simulated time reached (rate measurement; prerequisite of #307)

### 2026-10-31

- **PR #399**: feat: commit klt-minted 1.analog attestation and make netlist-check --check blocking
- **PR #361**: feat(signoff): wire klt signoff --attest 1 for analog netlist freshness

### 2026-10-30

- **PR #393**: docs(sim): record fleet probe of bin-fixed whole-block netlist (past parse, timeout in analysis)
- **Issue #386** (closed): Flat netlist fails ngspice model binning (sky130_fd_pr__nfet_01v8 L=0.15 W=0.36): blocks #307
- **PR #391**: feat(sim): all-cards bin-coverage scan for whole-block netlist with pre-fix control

### 2026-10-29

- **PR #389**: fix(sim): map sub-0.42um nFETs to special_nfet_01v8 in whole-block netlist

### 2026-10-27

- **PR #379**: fix: regenerate xor2 layout evidence under klayout-tools 0.8.0
- **PR #377**: docs(sim): move batch-client recipes and friction ledger to klayout-tools 0.8.0
- **PR #375**: fix(layout): regenerate leaf cells under klayout-tools 0.8.0
- **Issue #370** (closed): Re-floorplan ro_nand2*, sampler_nand2 and xor2 for klayout-tools 0.8.0
- **Issue #369** (closed): Regenerate leaf layout cells under klayout-tools 0.8.0 (primitives, ro_buf, ro_stage*, sampler_tg)
- **Issue #363** (closed): Bump klayout-tools pin 0.7.0, 5edb557f91d0 → 0.8.0
- **PR #376**: fix(layout): re-floorplan nand2 cells for klt 0.8.0 block growth
- **PR #373**: docs: record klayout-tools#4428 and the deck rule-diff recipe
- **Issue #368** (closed): File klayout-tools friction issues for 0.8.0 PDK-root preference and missing deck-rule diff (from #367)
- **Issue #364** (closed): Nightly compose-cell --check does not reproduce the nineteen cells under klt 0.8.0
- **PR #367**: docs(layout): classify klayout-tools 0.8.0 drift across layout cells
- **PR #365**: ci: move signoff grader pin to klayout-tools 0.8.0

### 2026-10-24

- **PR #357**: docs: scope manifest URI grep claim to manifest files
- **Issue #350** (closed): Live-verify klt artifact verify on first real sim campaign (follow-up of #347 / PR #349)

### 2026-10-23

- **PR #353**: docs(sim): record ngspice-46 reproduction of ro-ring timestep-convergence points 0 and 4
- **PR #351**: feat(sim): add timestep-convergence harness so T1 item 9 attests
- **PR #349**: feat(sim): store new run evidence in the artifact store, commit only manifests
- **Issue #348** (closed): T1 item 9: commit the testbench for sim/ro-ring-timestep-convergence (or declare it unclaimed) and re-attest

### 2026-10-21

- **PR #339**: ci: remove report-loom-ui job and OIDC permission from pdk-nightly
- **Issue #338** (closed): Drop the report-loom-ui job from pdk-nightly (CI pushes nothing; no OIDC)

### 2026-10-20

- **PR #343**: refactor(sim): share one importlib path loader across sim scripts
- **Issue #342** (closed): Consolidate 11 copy-pasted importlib _load helpers into one shared loader

### 2026-10-19

- **PR #336**: refactor: remove unused tautological family_false_alarm_bound
- **Issue #335** (closed): Remove family_false_alarm_bound: unused tautology (always returns 2**-alpha)

### 2026-10-18

- **PR #329**: sim(whole-block): record fleet startup probe that failed at ngspice parse
- **PR #328**: fix(sim): correct whole-block stimulus levels, probe measurements and reducer omission handling

### 2026-10-17

- **PR #323**: feat(signoff): cite artifact-anchored generic evidence for T1 items 1, 2, 9, 10
- **Issue #320** (closed): T1 items 1, 2, 9, 10: cite artifact-anchored inventory envelopes for both partitions
- **PR #322**: feat: map remaining spec rows to evidence and cite item 8 via generic envelope
- **Issue #321** (closed): T1 item 8: map the four unmapped characterization rows to their committed records, then cite the report

### 2026-10-15

- **PR #318**: feat(sim): lag-count monitor study — DR-0015 Proposed, additive model, coverage and area evidence
- **Issue #301** (closed): DR request: on-chip coverage of correlated/periodic raw streams (RCT/APT miss balanced periodic sources)
- **PR #286**: Guard active SDF signoff evidence against changed simulation inputs
- **Issue #285** (closed): Guard active SDF signoff evidence against changed simulation inputs
- **PR #218**: ci: run volume-model and ripple-reduction tests in PR-blocking job
- **Issue #217** (closed): CI: run test_raw_bit_volume_model and test_ripple_reduction in the PR-blocking lint job
- **Issue #162** (closed): README: embed the fleet burndown chart (one line)

### 2026-10-12

- **PR #311**: feat(sim): lock-resolution campaign for the supply-ripple evidence (#288)
- **Issue #288** (closed): Resolve near-frequency supply injection-lock brackets with longer observation windows
- **PR #309**: Whole-block characterization attempt: partial static IR, 12-point matrix explicitly Unmet (Part of #174)
- **PR #306**: ci(pdk-nightly): record nightly failures on loom-ui

### 2026-10-11

- **PR #303**: Whole-block verify: informational density and naive antenna-ratio estimates (#283)
- **Issue #283** (closed): Whole-block verify: informational metal/poly density and naive antenna-ratio estimates (split from #281)
- **PR #302**: feat(sim): health-test detection coverage on correlated/periodic streams (#300)
- **Issue #300** (closed): Health-test detection coverage against correlated / injection-locked raw streams
- **PR #299**: docs(sim): #289 batch retry still blocked by runner/client version mismatch
- **PR #298**: Friction ledger: index of cited klayout-tools issues with CI coverage check
- **Issue #295** (closed): Friction ledger: in-repo index of filed klayout-tools issues with CI coverage check
- **PR #297**: feat(spec): index DR-0011 and add decision-record index checker (#296)
- **Issue #296** (closed): Decision-record index consistency check (DR-0011 missing from spec/README.md)
- **PR #294**: docs: top-level REPRODUCE.md cold-start index with CI consistency check
- **Issue #292** (closed): Top-level REPRODUCE.md cold-start index with CI consistency check (T1 items 9/10)
- **PR #293**: feat(signoff): aggregated characterization report + CI staleness gate (#291)
- **Issue #291** (closed): Aggregated characterization report generator with CI staleness gate (T1 item 8)
- **PR #290**: feat(sim): non-nominal PVT seeded transistor raw-bit cross-check (generator, reducer, controls)
- **PR #287**: feat(sim): XOR combining-gate alternatives evidence for the raw-rate decision (#282)
- **Issue #282** (closed): Evidence for the raw-rate decision: measure XOR combining-gate alternatives against the ~78 kbps bandwidth ceiling
- **PR #284**: feat(verify): audit klt-inapplicable DRC rules and unruled layers against the composed GDS
- **Issue #281** (closed): Whole-block DRC: audit the 45 klt-inapplicable deck rules and 19 unruled stream layers against the composed GDS
- **PR #280**: fix(sim): reject summary collisions with behavioral evidence provenance
- **Issue #276** (closed): Reject summary collisions with behavioral evidence provenance
- **PR #279**: fix(sim): publish complete evidence bundles with exclusive id reservation
- **Issue #277** (closed): Publish complete evidence bundles with exclusive record ID reservation
- **PR #275**: Reject colliding artifact basenames before minting behavioral evidence
- **Issue #273** (closed): Reject colliding artifact basenames before minting behavioral evidence
- **Issue #278** (closed): Auditor: guard telemetry dispositions and read-only S3 refinement

### 2026-10-10

- **PR #272**: feat(sim): restart-matrix reduction + behavioural known-answer record for the C5 restart dataset
- **Issue #267** (closed): Restart-matrix (SP 800-90B restart-test shape) reduction with behavioral known-answer record, ahead of silicon
- **Issue #270** (closed): Auditor guard telemetry: cloud-cli:aws s3 (rm|rb|cp|mv|sync|mb)
- **PR #271**: feat(sim): protect measurements/ records and raw captures with append-only guard
- **Issue #269** (closed): Protect silicon measurement records and raw captures with the existing append-only CI guard
- **PR #268**: ci(pdk-nightly): reproduce whole-block composition and baseline DRC/LVS (#264)
- **Issue #264** (closed): PDK nightly: reproduce composed whole-block geometry and baseline DRC/LVS
- **PR #266**: feat(sim): protect record-associated runs/ and corners/ artifacts in append-only guard
- **Issue #265** (closed): Preserve raw run artifacts associated with append-only simulation records
- **Issue #259** (closed): Auditor guard telemetry: gh-api-rawfield-body-literal-at
- **PR #263**: feat(sim): bounded Vth-shift sensitivity of the RO array across PVT (#254)
- **Issue #254** (closed): End-of-life drift: bounded Vth-shift (BTI/HCI) derate of the RO array across PVT
- **Issue #258** (closed): Auditor guard telemetry: worktree-write-confinement-unresolved-var
- **Issue #244** (closed): Decision record: DR-0004 external interface vs the assumed Challenge #4 pin budget (brief §2 re-map)
- **Issue #208** (closed): Decision record needed: RO-array supply-quality requirement (droop/ripple) from #200 evidence
- **Issue #250** (closed): Gate digital P&R success on extracted final-route Liberty electrical limits
- **Issue #253** (closed): Raw-bit statistical evidence at SP 800-90B standard sample size (>= 2^20 bits per stream)
- **Issue #251** (closed): Measure repaired digital floorplan compaction with 16-corner electrical closure
- **Issue #256** (closed): Silicon characterization plan: claim-to-measurement table, observability audit, measurements/ layout
- **PR #247**: docs(spec): DR-0011 Proposed -- external interface vs assumed Challenge #4 pin budget
- **PR #248**: docs(spec): DR-0012 Proposed -- RO-array supply-quality requirement (#208)
- **PR #252**: Gate digital P&R on extracted final-route Liberty electrical limits
- **PR #255**: feat(sim): 2^20-bit raw-bit streams and min-H shift vs 2^17 (#253)
- **PR #257**: sim: repaired floorplan compaction with 16-corner electrical closure (#251)
- **PR #260**: docs(spec): silicon characterization plan, DR-0014 Proposed, measurements/ layout contract (#256)
- **PR #245**: feat(sim): conditioned-output (DATA) battery + estimator evidence (#243)
- **PR #241**: docs: sync sim/README slug index and Challenge #4 sign-off row 3 (#240)
- **PR #242**: docs(spec): DR-0010 target-table reconciliation packet (Proposed)
- **PR #238**: feat(digital): constraint-driven electrical-limit repair study with 16-corner final-route audit (#236)
- **Issue #243** (closed): Conditioned-output (DATA) statistical evidence: run the CRC-32 conditioner over the volume-campaign raw streams
- **Issue #240** (closed): docs: sync sim/README slug index and Challenge #4 sign-off row 3 with delivered evidence
- **Issue #239** (closed): Spec: DR-0010 target-table reconciliation packet (rate, area, power rows) for operator ratification
- **Issue #236** (closed): Digital physical closure: repair and audit low-voltage Liberty slew/capacitance violations
- **Issue #235** (closed): Auditor guard telemetry: worktree-write-confinement-unresolved-var

### 2026-10-09

- **PR #237**: CI: enforce sim/ append-only record rule (#232)
- **PR #234**: sim: digital floorplan-compaction feasibility study (#226)
- **PR #229**: Add SDF-annotated routed digital verification with annotation controls (#227)
- **PR #225**: feat(layout): native supply ERC for routed trng_digital; cite item 11.digital
- **PR #224**: feat(sim): native klt functional-verification evidence for the digital suite
- **PR #220**: Local-mismatch Monte Carlo of RO array spread and sampler offset/bias
- **PR #219**: Wake-up transient campaign vs DR-0004 start-up window (partial, #216)
- **PR #214**: Cite delivered digital DRC/LVS evidence in T1 manifest (#211)
- **PR #213**: Refresh current sign-off status and simulated-stream documentation
- **PR #209**: Supply-ripple and injection-lock robustness campaign for the RO array (#200)
- **Issue #232** (closed): CI: enforce the sim/ append-only record rule (fail PRs that modify, rename or delete committed records)
- **Issue #226** (closed): Measure digital floorplan compaction feasibility against the unchanged area target
- **Issue #223** (closed): Verify routed digital supplies and well ties with native ERC evidence
- **Issue #227** (closed): Add SDF-annotated routed digital verification with annotation controls
- **Issue #210** (closed): Guard telemetry: retain containment for unresolved scratch-write variables
- **Issue #222** (closed): Record native digital functional-verification evidence alongside routed STA
- **Issue #207** (closed): Guard telemetry: retain shared-stash creation protection
- **Issue #215** (closed): Local-mismatch Monte Carlo of RO array frequency spread and sampler decision offset/bias
- **Issue #211** (closed): Refresh T1 manifest with eligible delivered digital physical evidence
- **Issue #212** (closed): Refresh current sign-off status and simulated-stream documentation
- **Issue #200** (closed): Supply-ripple and injection-lock robustness campaign for the RO array (transistor level)

### 2026-10-08

- **PR #206**: chore(signoff): klayout-tools 0.7.0 grader; 11.analog met (3/22)
- **Issue #164** (closed): Re-grade T1 item 11 (11.analog) once klayout-tools#2405 (alias-joined LVS supply pairing) lands
- **PR #204**: Whole-block DRC, mixed-level LVS and fault controls for trng_whole (#173)
- **PR #203**: Re-derive and empirically validate RCT/APT cutoffs against estimated H (#196)
- **PR #202**: Add 125 C combining evidence and hot volume record (#197)
- **PR #199**: Hot-corner (125 C) calibration plumbing for the raw-bit volume campaign (#197, partial: batch fleet refused jobs)
- **PR #198**: Run SP 800-22 battery and 90B estimators on the #188 volume streams
- **PR #194**: Raw-bit volume campaign: >=1e5 behavioral bits per PVT corner (#188)
- **PR #193**: ci: run sim/tests unit tests in the lint job
- **PR #192**: feat(sim): SP 800-22-style battery + non-MCV SP 800-90B estimators (#189)
- **Issue #170** (closed): Whole-block integration: compose analog+digital GDS, block DRC/LVS and post-layout PVT (remaining #18 AC3)
- **Issue #173** (closed): Whole-block physical verification: DRC/LVS and interface/supply negative controls
- **Issue #196** (closed): Re-derive and empirically validate RCT/APT health-test cutoffs against estimated H
- **Issue #197** (closed): Extend raw-bit volume campaign calibration to the 125 C corner of the operating envelope
- **Issue #195** (closed): Run the SP 800-22 battery and 90B estimators on the #188 volume streams
- **Issue #188** (closed): Raw-bit volume campaign: >=1e5 bits per PVT corner for statistical evidence (current record has 24)
- **Issue #190** (closed): CI: run sim/tests unit tests (test_raw_bit_entropy, test_digital_section) in the lint job
- **Issue #189** (closed): Add SP 800-22-style battery and non-MCV SP 800-90B estimators to the raw-bit analysis

### 2026-10-07

- **PR #187**: Re-extract layout/pex* on #181 geometry; re-measure assembled ring via klt sim (#184)
- **Issue #184** (closed): Re-extract post-layout netlist libraries (layout/pex*) on the regenerated #181 geometry
- **PR #185**: fix(layout): regenerate the analog cell chain on the klt cut-size/grid fix
- **Issue #181** (closed): Regenerate sampler_core analog cells to clear 5664 licon1.ongrid.1 violations on the current klt sky130 deck
- **PR #182**: docs: reconcile Challenge #4 scorecard against whole-block composition (Part of #18)
- **Issue #175** (closed): pdk-nightly is red

### 2026-10-05

- **PR #179**: fix(ci): pdk-nightly tracker discovery independent of loom:triage
- **PR #177**: fix(ci): authenticate volare PDK downloads in pdk-nightly
- **PR #176**: Whole-block composition: interface reference, routed GDS and supply distribution (#172)
- **Issue #178** (closed): pdk-nightly failure tracker matches existing trackers only by loom:triage label
- **Issue #172** (closed): Whole-block composition: interface reference, routed GDS and supply distribution

### 2026-10-04

- **PR #171**: docs: Challenge #4 proposal scorecard after #166 (Part of #18)

### 2026-10-03

- **PR #169**: refactor: share ro_array_core LVS negative-control logic
- **PR #167**: Place and route the DR-0004 digital section with physical sign-off evidence
- **Issue #168** (closed): Deduplicate the remaining LVS negative-control logic across live and PoC scripts
- **Issue #166** (closed): Place and route the DR-0004 digital section with reproducible physical sign-off evidence

### 2026-09-23

- **PR #165**: feat(signoff): declare sampler_core well/substrate ties in the erc supply spec and cite 11.analog
- **PR #163**: chore(signoff): bump signoff grader pin to klayout-tools 0.6.0, re-vendor tiers doc, regenerate t1-report
- **Issue #161** (closed): T1 item 11: declare sampler_core's well ties in the klt erc supply spec on klayout-tools 0.6.0 and cite 11.analog in the block manifest
- **Issue #160** (closed): Bump the signoff grader pin to klayout-tools 0.6.0, re-vendor the tiers doc, and regenerate signoff/t1-report.json

