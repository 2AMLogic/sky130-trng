# Work Log

Chronological record of recently merged pull requests and closed issues.

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)

### 2026-11-14

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
- **Issue #138** (closed): CI: preserve started main verification runs with event-aware concurrency

### 2026-10-17

- **PR #323**: feat(signoff): cite artifact-anchored generic evidence for T1 items 1, 2, 9, 10
- **Issue #320** (closed): T1 items 1, 2, 9, 10: cite artifact-anchored inventory envelopes for both partitions
- **PR #322**: feat: map remaining spec rows to evidence and cite item 8 via generic envelope
- **Issue #321** (closed): T1 item 8: map the four unmapped characterization rows to their committed records, then cite the report
- **PR #184**: refactor(layout): remove inert BLOCKED_BLOCKS path from gen_analog_layout.py
- **PR #181**: refactor: route design netlisting through klt netlist
- **PR #178**: test: use shared start_clock in four remaining cocotb testbenches
- **Issue #179** (closed): Simplify design/netlist.py: replace raw xschem call with klt netlist
- **Issue #177** (closed): Remove inert BLOCKED_BLOCKS path from gen_analog_layout.py: empty since #72
- **Issue #176** (closed): Finish #44: four cocotb testbenches still redefine the shared 12 MHz clock helper

### 2026-10-16

- **PR #173**: chore(sim): remove unused mk_dut.py and fix stale DUT references
- **PR #172**: Bump Repo Skills 0.24.1 -> 0.24.3
- **Issue #107** (closed): Remove sim/tools/mk_dut.py: unused, superseded by design/netlist.py

### 2026-10-15

- **PR #318**: feat(sim): lag-count monitor study — DR-0015 Proposed, additive model, coverage and area evidence
- **Issue #301** (closed): DR request: on-chip coverage of correlated/periodic raw streams (RCT/APT miss balanced periodic sources)
- **PR #286**: Guard active SDF signoff evidence against changed simulation inputs
- **Issue #285** (closed): Guard active SDF signoff evidence against changed simulation inputs
- **PR #218**: ci: run volume-model and ripple-reduction tests in PR-blocking job
- **Issue #217** (closed): CI: run test_raw_bit_volume_model and test_ripple_reduction in the PR-blocking lint job
- **Issue #162** (closed): README: embed the fleet burndown chart (one line)
- **PR #170**: docs(records): equivalence-sim attempts on flattened driver incomplete; raise signal-quality timeout
- **PR #168**: docs(records): driver layout-plan re-run on post-resize netlist fails on m=4
- **PR #164**: feat(digital): SDF-annotated gate-level regression for T1 item 7.digital (#93)
- **PR #162**: Regenerate digital physical/evidence chain from current RTL (#131)
- **PR #149**: feat(rtl): add trim[4:0] integration input to usb_utmi_phy (#115)
- **Issue #115** (closed): RTL: add trim[4:0] pass-through input port (pin contract, #109)

### 2026-10-14

- **Issue #90** (closed): README: embed the fleet burndown chart (one line)

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
- **PR #151**: docs(spec): fix evidence link in decision 0005
- **Issue #159** (closed): Auditor guard decision: keep detached force-push guard
- **Issue #156** (closed): Lint: run scripts/test_setup_env.sh from npm run lint so setup-env.sh regressions reach CI

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
- **PR #153**: fix(verification): current-source records superseding stale #112/#113 carry-forwards (#147)
- **PR #145**: RTL: add pu_en output derived from TermSelect (#112)
- **Issue #152** (closed): Build failure on main: pin-contract planned TXOE test is stale
- **Issue #132** (closed): Decide whether UTMI Reset should reach the vendored RX transforms synchronously
- **Issue #113** (closed): RTL: add txoe driver-enable output (pin contract, #109)
- **Issue #112** (closed): RTL: add pu_en output derived from TermSelect (pin contract, #109)

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
- **PR #141**: docs(layout): re-measure resized differential_receiver (DRC clean, LVS mismatch)
- **PR #137**: fix: require full 45-corner evidence before fixed-trim PASS
- **PR #125**: Add --tool-light mode to setup-env.sh (#117)
- **Issue #136** (closed): Require complete PVT evidence before fixed-trim analysis can report PASS
- **Issue #130** (closed): Verify UTMI Reset aborts transmission through stuffing and EOP states
- **Issue #123** (closed): Characterize RX boundary synchronization with paired-input skew and reset injection
- **Issue #103** (closed): Re-run differential_receiver layout/DRC/LVS after MP_B1/MN_B1 resize (PR #102)
- **Issue #95** (closed): signoff: bare evidence keys 3 and 4 grade the analog partition met with no analog layout

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
- **PR #122**: Add top-level RX stuffing-error propagation and recovery tests (#118)
- **PR #121**: Reconcile status docs with superseding verification evidence
- **PR #111**: Attempt SDF-annotated gate-level regression for T1 item 7.digital (blocked; negative result recorded) (#93)
- **Issue #120** (closed): Reconcile current PHY status documents with superseding verification evidence
- **Issue #118** (closed): Verify top-level RX stuffing-error propagation and packet recovery
- **Issue #108** (closed): Verify RX bit sampling against spec §7 ±0.25% clock tolerance (no test covers host/device rate offset)
- **Issue #97** (closed): Analog: make differential_receiver resolve 200 mV over the full 0.8-2.5 V common-mode range (spec §4)
- **Issue #92** (closed): T1 item 5 (digital): mint one multi-corner klt sta envelope on the routed layout and cite it

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

### 2026-09-22

- **PR #88**: feat: vendor shared USB protocol RTL and adapt the UTMI wrapper
- **Issue #87** (closed): Re-run usb_utmi_phy place-and-route and post-layout PVT against the vendored rtl/common sources (post-#84)

### 2026-09-21

- **PR #158**: feat(layout): add T1 item-11 klt erc supply read for sampler_core
- **PR #157**: feat(signoff): add klt signoff block manifest with CI staleness gate
- **PR #156**: ci: declare the run-pdk-check label the PDK-gated workflows' PR opt-in documents
- **Issue #155** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read
- **Issue #154** (closed): T1 item 11 (power delivery, structural): no klt erc supply spec or report in this repo
- **Issue #153** (closed): run-pdk-check label does not exist, so both PDK-gated workflows' documented PR opt-in is dead
- **Issue #83** (closed): T1 item 11 (digital): declare well/substrate ties[] in layout/digital/erc-supply-spec.json and re-run klt erc — upstream klayout-tools#2169 fix is already in the pinned klt
- **Issue #79** (closed): T1 item 11 digital leg: committed LVS report predates power_connectivity - re-run digital LVS on a klt that computes it
- **Issue #78** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read
- **Issue #77** (closed): T1 item 11 (power delivery, structural): no klt erc supply spec or report in this repo

### 2026-09-18

- **PR #38**: ci(layout): add compose-cell.py --check regression guard to pdk-nightly
- **PR #152**: ci: pin xschem to a 3.4.7 floor and surface a red pdk-nightly (#151)
- **Issue #36** (closed): layout: compose-cell.py --check has no automated regression guard (nothing runs it)
- **Issue #151** (closed): pdk-nightly netlist-check has been red since 2026-09-15: xschem version drift emits expr() templates where committed netlists have evaluated values (4 cells STALE)

### 2026-09-16

- **PR #150**: refactor: remove dead constants in sampler_core data-path-scan
- **Issue #149** (closed): Remove dead constants in layout/sampler_core/data-path-scan.py

### 2026-09-15

- **PR #148**: docs: fix stale not-yet-composed claims in sampler_tg README
- **PR #146**: fix: eliminate pipefail+set-e crash in merge-pr.sh champion:hold-state check
- **PR #144**: fix: eliminate pipefail+SIGPIPE race in verify-proposal-refs.sh full_tree check
- **PR #143**: refactor: extract carrying() scan-script helper into _geom_common.py
- **PR #140**: fix: update stale sim/-is-empty comments in design/pdk.json and netlist.py
- **PR #139**: docs: add PDR-0001 recommending fix for broken generate-agents-md.sh path
- **Issue #75** (closed): Fix or remove broken generate-agents-md.sh (installed Loom surface, unused + broken path)
- **Issue #56** (closed): Champion merged PR #54 after its own verdict had just been invalidated by a stale-verdict reconciliation
- **Issue #34** (closed): Fix stale sim/-is-empty comments in design/pdk.json and design/netlist.py
- **Issue #22** (closed): sky130-trng layout + DRC/LVS-clean GDS, and post-layout PVT simulation
- **Issue #147** (closed): Fix stale "not yet composed"/"remains open" claims in layout/sampler_tg/README.md
- **Issue #145** (closed): merge-pr.sh: _check_champion_hold_state_staleness crashes via pipefail+grep -o SIGPIPE-class bug on ordinary PRs
- **Issue #142** (closed): verify-proposal-refs.sh: false MISSING FILE due to pipefail + grep -q SIGPIPE race
- **Issue #141** (closed): Remove duplicated carrying() helper: sampler_core scan scripts

