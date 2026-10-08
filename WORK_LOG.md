# Work Log

Chronological record of recently merged pull requests and closed issues.

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
