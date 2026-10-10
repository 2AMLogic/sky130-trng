# Work Log

Chronological record of recently merged pull requests and closed issues.

### 2026-10-10

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

### 2026-09-21

- **PR #158**: feat(layout): add T1 item-11 klt erc supply read for sampler_core
- **PR #157**: feat(signoff): add klt signoff block manifest with CI staleness gate
- **PR #156**: ci: declare the run-pdk-check label the PDK-gated workflows' PR opt-in documents
- **Issue #155** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read
- **Issue #154** (closed): T1 item 11 (power delivery, structural): no klt erc supply spec or report in this repo
- **Issue #153** (closed): run-pdk-check label does not exist, so both PDK-gated workflows' documented PR opt-in is dead

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

### 2026-09-14

- **PR #138**: fix: dedup mint_behavioral_record's rid derivation onto new_record_id
- **Issue #27** (closed): Compose ro_array_core/sampler_core gates from proven klt primitives, DRC/LVS-clean
- **Issue #137** (closed): Dedup mint_behavioral_record's rid derivation onto new_record_id (sim/bin/evidence_record.py)

### 2026-09-13

- **PR #136**: refactor: consolidate lvs-negative-controls.py poc copy onto _klt_common.run_klt
- **PR #134**: Consolidate duplicate run_klt() in synthesize-and-verify.py with layout/bin/_klt_common.py
- **Issue #135** (closed): Consolidate lvs-negative-controls.py poc copy onto _klt_common.run_klt
- **Issue #133** (closed): Consolidate duplicate run_klt() in synthesize-and-verify.py with layout/bin/_klt_common.py

### 2026-09-12

- **PR #132**: Extract shared merged()/dbox_region() geometry helpers for ro_array_core scan scripts
- **PR #130**: refactor: extract merge_spans() interval-merge helper in sampler_core
- **PR #128**: Fix KeyError in digital-section-campaign.py report for experiment D
- **PR #127**: fix(layout): refresh sampler_core scan assertions for the post-#113 vdd strap
- **PR #124**: Extract layout/sampler_core's byte-identical merged() geometry helper
- **PR #123**: refactor: reuse _klt_common.run_klt in lvs-negative-controls.py
- **PR #120**: Wire package.json test/lint/check scripts to the real Python test suite
- **Issue #131** (closed): Extract byte-identical merged()/dbox_region() geometry helpers duplicated in ro_array_core scan scripts
- **Issue #129** (closed): Deduplicate the interval-merge loop in sampler_core scan scripts
- **Issue #126** (closed): Fix broken failure-path KeyError in digital-section-campaign.py's report (experiment D)
- **Issue #125** (closed): layout/sampler_core scan scripts do not reproduce their own committed *-scan.json in this environment
- **Issue #122** (closed): Extract layout/sampler_core's byte-identical merged() geometry helper
- **Issue #121** (closed): Consolidate lvs-negative-controls.py's klt plumbing into _klt_common.run_klt
- **Issue #119** (closed): Wire or remove misleading package.json placeholder test/lint/check scripts

### 2026-09-10

- **PR #118**: Synthesize digital section against sky130_fd_sc_hd, mint first level:gate record
- **Issue #117** (closed): Synthesize the digital section (digital/rtl/trng_digital.v) against sky130_fd_sc_hd with klt synthesize + klt equiv, and mint the first `level: gate` records (DR-0004's named next increment; proposal row G)

### 2026-09-09

- **Issue #52** (closed): Remove duplication: run_klt/write_json/BuildError copied between compose-cell.py and pex-netlist.py

### 2026-09-08

- **PR #116**: feat(sim): whole-chain substrate bracket, and DR-0003 §8 narrowed to one named blocker
- **PR #115**: feat(sim): sampler_core's first whole-cell post-layout PVT campaign

### 2026-09-07

- **PR #99**: feat(layout): route sampler_dff's m data-path net, DRC/LVS clean
- **PR #98**: fix(layout/pex): thread the invoking descriptor into the generated library header
- **PR #97**: fix(layout/pex): canonicalize klt's own net numbering in --check and re-extract on the pinned klt
- **PR #95**: feat(layout): route sampler_dff's mb data-path net on met1, DRC-clean
- **PR #92**: feat(layout,sim): first sampler_dff post-layout PVT campaign and DR-0014 reset-contention re-derivation
- **PR #90**: refactor: remove unused reg fb from trng_digital.v
- **PR #89**: feat(layout): promote sampler_dff's d input pin to a real top-level label
- **PR #87**: fix(layout): correct sampler_nand2 rst_n/data-input pin swap in sampler_dff
- **PR #86**: feat(layout): route sampler_dff's s data-path net on met2, DRC-clean
- **PR #85**: feat(layout): route sampler_dff's qb data-path net, DRC-clean
- **PR #83**: feat(layout): route sampler_dff's q data-path net, DRC-clean
- **PR #82**: feat(layout): route sampler_dff's mc data-path net, DRC-clean
- **PR #81**: feat(layout): route sampler_dff's clkb fan-out, DRC-clean
- **PR #80**: feat(layout): route sampler_dff's five-pin clk fan-out, DRC-clean
- **PR #79**: feat(layout): route sampler_dff's rst_n fan-out, DRC-clean and merged
- **PR #78**: feat(layout): place sampler_dff's nine leaf-cell instances, route vdd/vss
- **PR #77**: refactor(digital): remove unused TrngDigital.run_bits
- **PR #76**: feat(layout): compose sampler_nand2, the last leaf shape sampler_dff needs
- **PR #74**: feat(layout): compose sampler_tg, the transmission gate sampler_dff needs
- **PR #72**: feat(layout,sim): whole-array post-layout PVT campaign and array-scale substrate bracket
- **PR #114**: feat(layout): extract sampler_core's post-layout parasitics
- **PR #113**: feat(layout): route sampler_core's vdd strap to a full whole-cell LVS match
- **PR #112**: feat(layout): route sampler_core's vss inter-block supply strap, DRC-clean
- **PR #110**: docs(layout): confirm sampler_dff --check regression is klt legs[] tool drift, not recipe drift
- **PR #108**: feat(layout): route sampler_core's last three data nets and sv's vdd tie
- **PR #107**: feat(layout): place ro_array_core in sampler_core and route the first two data nets
- **PR #104**: feat(layout): route sampler_core's shared clk/rst_n fan-out across six sampler_dff instances
- **PR #103**: feat(layout): route sampler_core's shared vdd/vss bus across six sampler_dff instances
- **PR #102**: feat(layout): DRC-clean placement proof-of-concept for sampler_core's six-sampler_dff bank
- **PR #101**: feat(layout,sim): sampler_dff whole-cell (assembled) post-layout extraction and PVT campaign
- **PR #100**: fix(layout/pex-ring,pex-array): close #96's provenance gap for pex-ring, record pex-array's electrical divergence
- **Issue #96** (closed): layout/pex-ring, layout/pex-array: klt 0.4.0 evidence vs the 0.3.0 klt_version_pin (the other half of #93's provenance gap)
- **Issue #94** (closed): layout/bin/pex-netlist.py: generated library banner hardcodes pex.json, so sampler_dff_pex.spice names the wrong descriptor for its own --check
- **Issue #93** (closed): layout/pex: ro_ring5_pex.spice fails `pex.json --check` on the pinned klt build (0.3.0 vs 0.4.0 provenance gap)
- **Issue #91** (closed): Rebase feature/issue-84 (PR #87) onto current main: rst_n/q pin-swap fix conflicts with s-net routing (PR #86)
- **Issue #88** (closed): Remove unused reg fb in trng_digital.v
- **Issue #84** (closed): sampler_dff wires rst_n and the data input to the swapped sampler_nand2 pins -- an LVS-blocking NMOS series-stack inversion on both NAND2 instances
- **Issue #73** (closed): Remove unused TrngDigital.run_bits convenience method
- **Issue #109** (closed): layout/sampler_core: find a viable rung for xo/ro2/ro3 beyond each net's own run (follow-up to #105)
- **Issue #106** (closed): layout/sampler_dff/cell.json --check no longer reproduces: clkb_mid left unrouted by gen-compose
- **Issue #105** (closed): layout/sampler_core: route the remaining three data nets (xo, ro2, ro3) and tie sv's d to vdd
