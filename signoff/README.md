# signoff — this block's graded gap to T1

The verdict of record for this block's distance from **T1
sim-validated** (the klayout-tools design-evidence ladder's bronze rung).
`klt signoff --manifest` renders the full T1 item table mechanically —
per-item `met`/`unmet` with a `reason` — instead of a hand-maintained
checkbox list that goes stale the moment the evidence or the checklist
moves. The hand-maintained checkbox list this directory replaced lived on
issue #3; that issue now points here and carries no checklist of its own
(issue #155 is the change that landed this). The fleet-wide view — one
line per canary, block + tier + the single blocking item — is the roll-up
on 2AMLogic/2am#956, which consumes this block manifest.

## Files

| file | what it is |
|---|---|
| `block-manifest.json` | the block manifest: this block's `kind` and, per T1 item, the evidence entry backing it. `block` identifies this block's row in the fleet roll-up. Every choice (including every deliberate non-citation) is documented in that file's `_comment` block. |
| `design-evidence-tiers.md` | byte-identical vendored copy of `2AMLogic/klayout-tools`'s `docs/design-evidence-tiers.md` — the tier ladder + T1 checklist the report is graded against. Provenance and why it is vendored: below. |
| `t1-report.json` | the committed `klt signoff --manifest` output — the evidence record for this block's current state. CI re-runs the exact command and diffs, so this file cannot rot. |

**Update 2026-10-09 (issue #211): 5/22 met.** The digital partition's
delivered physical evidence (`layout/trng_digital/`, issue #166) is now
cited: **item 3 digital** (`drc.json`) and **item 4 digital** (`lvs.json`)
render `met` on the pinned `klayout-tools==0.7.0` grader. Item 11 analog,
item 3 analog and item 4 analog are unchanged. The paragraph below is the
0.7.0 re-render (issue #164) and is superseded for the totals by this one.

At `origin/main`, re-rendered on the tagged grader `klayout-tools==0.7.0`
(2026-10-08, issue #164), the report reads: **22 T1 rows rendered
(11 checklist items × 2 partitions), 3 met — item 3 (DRC clean), item 4
(LVS clean) and item 11 (power delivery, structural), analog partition
only — so this block is 3/22 of the way to T1.** Issue #164 is closed by
this change: klayout-tools 0.7.0 carries the LVS supply-pairing fix
(klayout-tools#2405/#2431), and `11.analog` now renders `met` with
`power_delivery` populated (`supply_nets` vddr1..vddr4, vdd, vss;
`ties_checked_by_well_assertion` naming all six ties). Against the 0.6.0
report only item 11 changed verdict; every other row is byte-identical,
and the vendored checklist is unchanged (`doc_drift: false`). `tier` is
`null` until every rendered item is `met`. The report records its `build`
identity (`v0.7.0`, `is_release: true`) and pins the governing checklist
by `source_doc_content_hash`; three placeholder rows for T2/T3/T4 render
`tier_not_supported` after the 22 T1 rows (25 rows total). Read the
*report*, not this summary — it is the mechanical ground truth.

*History:* on `klayout-tools==0.6.0` (2026-09-23, issues #160/#161) the
report read 2/22 with item 11 `unmet` (`lvs_supply_unproven`).

**Re-rendered after the issue #181 regeneration (2026-10-07)** on the `klayout-tools==0.6.0` grader (superseded by the 0.7.0 re-render above). The `sampler_core` macro was rebuilt on the
klayout-tools cut-size/grid fix, and DRC, LVS and ERC were all re-run
against the new GDS. The manifest pins moved together with that evidence:
`3.analog` and the ERC half of `11.analog` went from `sha256:a00f6550…` to
`sha256:e3ff54a9…`. `4.analog` and the LVS half of `11.analog` are newly
pinned to the extracted netlist `sha256:bb9c7902…`. Every row's verdict was
unchanged at that time: 2/22 met, item 11 `lvs_supply_unproven`.

## Regenerating the report (CI runs exactly this)

```bash
klt signoff --manifest signoff/block-manifest.json \
  --tiers-doc signoff/design-evidence-tiers.md --format json \
  > signoff/t1-report.json
```

Exit code `3` is the documented mid-ladder state (`tier: null` — at least
one T1 item unmet), not a command failure; the command's own contract
reserves `0` for a block at T1. Echo the command above verbatim — the
report embeds the `--tiers-doc` value and relative evidence paths, so any
other invocation (different cwd, absolute tiers-doc path) produces a
report that no longer matches the committed one byte for byte. The output
is deterministic: same manifest + same evidence + same tiers doc + same
`klt` build ⇒ byte-identical report, which is what makes the CI
diff a valid staleness gate rather than a flaky one. 0.6.0 and later carry a
`--check REPORT` verb (klayout-tools#2258) that re-renders and compares a
committed report in one step — on this tree it prints `status: match`
(exit 0); CI keeps the explicit render-and-`cmp` form above so the job's
failure mode stays a plain byte diff.

## Why the tiers doc is vendored

The grade target is an upstream document that moves independently of this
repo — the checklist gained an **eleventh item on 2026-09-17**
(`klt erc` supply evidence, klayout-tools#2025), which instantly
invalidated every prior hand-read in the fleet. On the 0.5.0 grader the
wheel bundled a **10-item** copy of that doc, so rendering with the
wheel's default silently graded against a checklist that no longer
existed; the 0.6.0 grader (pinned since 2026-09-23, issue #160) bundles
a copy currently byte-identical to this one, but the vendored copy stays
authoritative anyway: 0.6.0 records the governing checklist's
`source_doc_content_hash` in the report (#2191), and grading against the
wheel's default would follow whatever doc a *future* wheel bundles
instead of the copy this repo reviews and re-vendors deliberately. This
vendored copy is byte-identical to upstream:

- repo: `2AMLogic/klayout-tools`, file `docs/design-evidence-tiers.md`
- upstream tag: `v0.6.0` (commit `c622e8a`, 2026-09-22)
- blob git-hash: `ecf02fd148c34902952b6f221a8117500529ddf7`
- upstream commit that last touched it: `0882541638acaec9ceb43c4df77b47d5a1a179db` (2026-09-22)
- sha256: `63eeec72e3d849761cf32dcf091af5728b069b1515e32bb3138e9454303671e5`

When upstream revises the checklist, refresh this copy (and the report)
in the same change, recording the new provenance here — the same
provenance-pin contract `layout/pdk.json` uses for `open_pdks_commit`.

## The claim the analog `met` rows rest on (and its limits)

`klt signoff` grades mechanically; it does not check topical relevance or
disclosure. This section is the claim, stated per the checklist's own
claimant-enforced item rules.

**Item 3, `met` (analog) — `layout/sampler_core/drc.json`.**
`klt drc` against `layout/sampler_core/sampler_core.gds`:
`status: clean`, 0 violations, deck `sky130`
(deck `content_hash sha256:2bcbd625…`), on klt `0.6.0+g5edb557f91d0` /
KLayout 0.30.12 (issue #181, which regenerated the macro on the
klayout-tools cut-size/grid fix). The manifest pins this citation to
`provenance.input.content_hash` `sha256:e3ff54a9…`, which is the sha256 of
the committed `sampler_core.gds` today, so the row is fresh against current
sources. A DRC regenerated against a changed GDS stops matching the pin and
renders `stale_evidence` instead of quietly passing.
*History:* before #181 this row cited a klt 0.4.0 run (deck
`sha256:5afac7ab…`) on GDS `sha256:a00f6550…`. That GDS was clean on the
0.4.0 deck but gives 5664 `licon1.ongrid.1` + 198 `via.width.1` on the
current deck. The regenerated GDS is clean on the current deck with no
rule waived. The row's `met` verdict is the same, but it now holds on the
current deck rather than only on the pinned old one.

*Coverage, quoted from the envelope's `coverage` block (item 3's
disclosure is these fields, not prose from memory):*

- `deck_scope` — the deck transcribes the foundry DRM for
  `cap2m, capm, ct, difftap, li, licon, m1, m2, m3, m4, m5, nwell, poly,
  via, via2, via3, via4` only.
- `layers_in_stream_without_rules` — drawn in this stream with no deck
  rule for them: `67/5`, `68/5`, `69/5` (the current deck now has rules
  for `65/44`, `tap.drawing`).
- `rules_skipped` — 89 rules the deck carries but this run did not
  evaluate (47 checked), because their layers are not drawn in this stream.
  They include the `capm.*`/`capm2.*` families, every met3–met5 rule,
  `via2`/`via3`/`via4`, and the implant/marker-layer `angle`/`ongrid`
  rules. The full list is in the envelope's `coverage.rules_skipped`.

A clean verdict inside that scope is exactly what this row claims — no
more.

*Scope:* the graded GDS is `sampler_core` — this block's **analog
partition** (the ring-oscillator array entropy source plus the six-DFF
digitizer bank; `design/sampler_core.spice`'s `.subckt sampler_core`,
fully composed, pinned at `layout/sampler_core/`). No top-level layout of
the whole block (analog + digital section composed) exists yet, and the
digital partition has no layout at all, which is why the digital row of
this kind-independent item is deliberately left `unmet/no_evidence` — see
the partition statement below and the manifest's `_comment` for why the
key is `3.analog`, not `3`.

**Item 4, `met` (analog) — `layout/sampler_core/lvs.json`.**
`klt lvs` comparing the extracted netlist of that same GDS (`klt
extract`, 264 devices / 152 nets, `provenance.input.content_hash`
matching `sha256:e3ff54a9…`, the #181-regenerated GDS) against the compose-cell.py-generated
reference for `.subckt sampler_core`: `status: match` — 264/264 devices,
152/152 nets — engine `klayout` 0.30.12.

*Warnings, listed per item 4's rule:* one warnings-only mismatch,
category `topology.flattened` — `options.flatten_reference` collapsed
17 reference circuits into one flattened top-level circuit before
comparing (topology verified after hierarchy removal on the reference
side), `error_count: 0`.

*Power/ground connectivity:* the regenerated envelope (#181,
`0.6.0+g5edb557f91d0`) carries a `power_connectivity` block with
`status: unchecked`. Its reason: the `subckt-call` reference form carries
its own power/ground pins and nets, which take part in the ordinary compare,
so the check (built for the signal-only gate-level form) does not apply.
Item 4's own text reads that as "does not apply here", **never as
"verified"**. (The pre-#181 klt 0.4.0 envelope carried no
`power_connectivity` block at all.) Nothing in this row claims power connectivity was checked;
the structural power question this block still owes is item 11 (see
#154).

*Freshness (pinned since #181):* the regenerated `lvs.json`
(`0.6.0+g5edb557f91d0`) records `provenance.input.content_hash`
`sha256:bb9c7902…`, role `netlist`. That is the sha256 of the committed
extracted `layout/sampler_core/sampler_core.spice` it compared, and it
equals the envelope's `environment.layout_sha256`.
`environment.reference_sha256 18aa2d10…` still equals the committed
`sampler_core.ref.spice`, which the regeneration left unchanged. The
manifest now pins `4.analog` (and item 11's LVS half) to that netlist hash,
and the grader reports `input_verified: true`. The GDS-to-netlist link is
`extract.json`'s own `provenance.input.content_hash`, which is the GDS pin
item 3 carries. Before #181 the klt 0.4.0 envelope recorded no input hash,
so this citation was file-backed with no pin, and its freshness was
verified by hand (`environment.layout_sha256 6ed6f71b…`). That gap is now
closed. Mechanical artifact-side verification upstream
(klayout-tools#2212) would still strengthen it.

**Item 11, `met` (analog) — the compound citation
`[erc.json, lvs.json]` (issue #161).** The ERC half is fully graded and
clean: `layout/sampler_core/erc-supply-spec.json` now declares `ties[]`
for every distinct well/substrate tie the layout draws — one entry per
supply group, with the well regions asserted as boxes derived from the
drawn nwell polygons (70 merged regions whose taps reach `vdd`, five
each reaching `vddr1`–`vddr4` — the ring-local rails do tie their own
wells — and the substrate, in the native-substrate
`well_layer: null` + `well_boxes` form, to `vss`). All six taps are
sky130's dedicated `tap.drawing` (65/44) layer, so no tie is degenerate.
The regenerated `erc.json` (tagged `klt` 0.6.0,
`provenance.klt_version` reads `0.6.0`, not a `+g…` dev build; re-run
against the #181-regenerated GDS, with the same 73 gates and the same
clean verdict) records
`erc_status: clean`, zero `erc.missing_tie` / `erc.unconnected_net` /
`erc.supply_short`, all six ties in `erc_coverage.checked` and in
`checked_by_well_assertion`, nothing in `skipped`. The erc citation is
pinned to the envelope's `provenance.input.content_hash` — the committed
GDS's sha, the same pin value item 3 carries.

*How the LVS half is now graded (issue #164).* The grader's no-PDN
(analog/full-custom) branch requires every supply declared in the erc spec
to be paired in the cited `lvs.json`'s `net_correspondence`. On 0.6.0 that
required the entire layout-side string to equal the supply name, which
`klt lvs`'s alias-joined rows (`G_VDDR_M1|…|VDDR|VDDR1`) can never satisfy
(klayout-tools#2405, filed under the friction protocol). klayout-tools
0.7.0 (#2431) fixes the pairing, and the unchanged committed artifacts now
grade `met`: `power_delivery.supply_nets` is `vddr1`–`vddr4`, `vdd`, `vss`,
`pdn: false`, `power_connectivity_status: unchecked` (the LVS reference
form does not apply that check, as item 4 states), and
`ties_checked_by_well_assertion` names all six ties
(`nwell_vdd`, `nwell_vddr1`–`nwell_vddr4`, `substrate_vss`).

**Item 4's freshness caveat applies to this citation's lvs part
unchanged** — it is the same file, cited unpinned for the same
no-envelope-hash reason (a pin with no envelope hash to match renders
`unverifiable_provenance`, per klayout-tools#2182's part-level rule).

## Digital-partition citations (issue #211) and what stays omitted

Audit of the `layout/trng_digital/` envelopes against the 0.7.0 grader and
the vendored item rules (no new simulation; existing artifacts only):

| Row | Decision | Why |
|---|---|---|
| `3.digital` | **cited** `drc.json`, pin `sha256:c65e1581…` | `klt drc` `status: clean`, 0 violations, deck `sky130` (`sha256:ef7800eb…`). The pin is `provenance.input.content_hash`, the sha256 of the committed `trng_digital.gds`. |
| `4.digital` | **cited** `lvs.json`, pin `sha256:93fdea04…` | `status: match`, engine `klayout` 0.30.12, `power_connectivity.status: match`. The pin is the sha256 of the extracted `trng_digital.layout.abstract.spice` that was compared (`environment.layout_sha256`). |
| `5.digital` | **not cited** | `sta.json` (16 Liberty corners, all `constrained`, non-negative setup/hold, SPEF-annotated) would grade `met` on its own, but item 5's digital rule is multi-corner STA *plus* a bit-exact functional suite. Native `klt functional-verification` reports now exist (issue #222, `sim/digital-functional-verification/records/20261009-120511-d9f51a4`; functional/unit-delay on the RTL and the routed netlist, not SDF-timed), so both halves of the evidence are present. The row is **still not cited**: item 5's note requires a ratified specification and DR-0004 (the digital section) is `Proposed`; that condition is unmet and stays explicitly unmet. |
| `7.digital` | not cited | Needs an SDF-annotated `klt functional-verification` run. The committed co-simulation is functional/unit-delay, not timed; `klt sta` is item 5 evidence (`wrong_kind`). `trng_digital.sdf.gz`/`.spef.gz` are inputs, not the required envelope. |
| `11.digital` | not cited | Needs a `klt erc` supply envelope for `trng_digital`; none is committed. `pnr.json` (PDN) and the `power_connectivity: match` in `lvs.json` exist but cannot satisfy the item alone. |
| `pnr.json` | not a citation | No T1 row grades a `place-and-route` envelope by itself; it is the PDN provenance for 11.digital and the layout provenance for item 2. |
| `1, 2, 6, 8, 9, 10` | unchanged | No klt verb / no aggregated artifact, as before. |

**Disclosures that travel with the two new `met` rows (quoted from the
envelopes, not re-derived):**

- *Item 3 digital.* Curated deck, not the foundry DRC: it transcribes
  `cap2m, capm, ct, difftap, li, licon, m1, m2, m3, m4, m5, nwell, poly,
  via, via2, via3, via4` (plus `x`); 91 rules checked, 45 rules skipped
  (`coverage.rules_skipped`, e.g. the `capm.*`/`capm2.*` families, implant
  and marker `angle`/`ongrid` rules); drawn layers with no deck rule:
  `64/5, 64/16, 64/59, 67/5, 67/16, 68/5, 68/16, 69/5, 69/16, 70/5, 70/16,
  72/5, 72/16, 81/4, 81/23, 83/44, 122/16, 235/4, 236/0`. No fill/density,
  antenna, seal-ring or latch-up checks. The run was on a pinned dev build
  (`0.6.0+g10f3da34c088`); the deck is marked `released: false`.
- *Item 4 digital.* The reference is the signal-pin-only routed gate-level
  Verilog, compared at standard-cell (black-box) level: `devices` counts are
  0, 2365 layout nets vs 2354 reference nets, cell internals are not
  compared. Warnings-only mismatches (35, `error_count: 0`):
  `topology.power_only_pruned` (1; fill cells removed),
  `topology.reference_port_alias_joined` (33) and
  `topology.top_level_pins_anchored` (1). `body_verification` is
  `unchecked` (pre-extracted netlist form: substrate/well taps and device
  bodies were not verified). `power_connectivity: match` is per-instance
  pin-to-net correctness only, not rail/grid continuity or IR drop.
- *Both rows* describe the digital macro `trng_digital` alone. They are not
  a whole-block result; whole-block characterization stays on #174. Low-voltage
  Liberty-limit behavior is recorded in `pnr.json` (541 max-transition and 18
  max-capacitance library-limit violations in the corner sweep) and is not
  something either cited row asserts away.
- `input_verified` is `null` for both: the grader compares the manifest pin to
  the envelope's own recorded input hash; it does not re-hash the artifact.
  Freshness is therefore as strong as regenerating the envelope on change.

**Staleness check performed:** with the `3.digital` pin altered by one digit,
`klt signoff` renders `3.digital` as `unmet`/`stale_evidence` (and the
met count drops from 5 to 4); `5.digital`, `7.digital` and `11.digital`
remain `unmet`/`no_evidence`. `klt signoff --check` on the committed report
prints `status: match`.

## Block kind and the partition boundary (the mixed-signal claim)

`kind: mixed-signal`, confirmed against the block. The **analog partition**
is the entropy source plus its digitizer bank: everything inside
`design/sampler_core.spice`'s `.subckt sampler_core` and its
implementation — the ring-oscillator array (`ro_array_core` of
`ro_ring5`/`ro_buf`/`ro_nand2`/`ro_stage` and the XOR combining tree) and
the six-`sampler_dff` bank — with top-level pins `clk, rst_n, raw_bit,
raw_valid, ring_bit1..ring_bit4, vdd, vss`. The **digital partition** is
the conditioner/health-monitor section, `digital/rtl/trng_digital.v` and
its synthesized gate netlists under `digital/flow/` (top module
`trng_digital`). `ring_bit*`/`raw_bit`/`raw_valid` are the partition
boundary nets: analog samples them, digital consumes them. The
mixed-signal claim makes both ladder columns apply at once — items 1, 2,
5, 7 and 11 are graded one row per partition (the report shows every
item twice, `partition: analog|digital`), and the kind-independent items
(3, 4, 6, 8, 9, 10) are graded for the partition their cited evidence
actually covers, via the manifest's partition-qualified keys.

## Reading the unmet rows

Every other row is `unmet` with `reason: no_evidence` — no passing,
gradeable envelope exists for it on this tree. That is an honest
mechanical statement, not a claim that the underlying work is absent: the
post-layout campaigns under `sim/` are real measurements, but they are
minted evidence records driven from `klt extract --parasitics` netlists —
no `klt sim`/`klt pex`/`klt yield`/`klt sta`/SDF-annotated
`functional-verification` envelope grades any of them, and item 7 exists
precisely to refuse a pre-layout sim or clean DRC as post-layout
evidence. Per-item notes on what exists and why it is not citable are in
the manifest's `_comment` block; the machine reading of what that means
for the tracker is the report itself. As evidence lands for an item, its
citation is added to the manifest and the report regenerated — never by
citing an envelope that does not actually support the item to make a row
go green.

## CI

`.github/workflows/ci.yml`'s `signoff-check` job installs the pinned
`klayout-tools==0.7.0` (since 2026-10-08, issue #164; 0.6.0 from 2026-09-23, issue #160 — deliberately
**diverged** from the PDK nightly's 0.5.0: the grader is a pure JSON
transform with no PDK, so it follows the grader release, while the
nightly's pin gates the nineteen committed cells' compose-cell `--check`
reproductions and moves only with a full `--check` re-verification
against a new build), runs the regeneration command
above, and fails if its output differs from the committed
`t1-report.json` — so a manifest citing an artifact that has since
changed goes red instead of rotting. The PR path needs no PDK and no
KLayout: grading is a pure JSON transform over committed envelopes.
