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

At `origin/main`, re-rendered on the tagged grader `klayout-tools==0.6.0`
(2026-09-23, issue #160), the report reads: **22 T1 rows rendered
(11 checklist items × 2 partitions), 2 met — item 3 (DRC clean) and
item 4 (LVS clean), analog partition only — so this block is 2/22 of the
way to T1**, with item 11 (power delivery, structural) counted and
`unmet` (`lvs_supply_unproven`) — the `11.analog` citation is now IN
(issue #161): the ERC half grades fully clean (see the item-11 claim
section below), and the one surviving reason is the LVS half's supply
pairing, which is structurally unsatisfiable against this block's
committed `lvs.json` (klayout-tools#2405; local follow-up #164) — not a
missing artifact. `tier` is `null` until every rendered item is `met`. The 0.6.0 build changed the report's *shape*,
not its verdict: rows now carry a per-item `graded_by_build` flag, the
report records its `build` identity (`v0.6.0`, `grading_ruleset_id`) and
pins the governing checklist by `source_doc_content_hash`
(klayout-tools#2191/#2222), and — as on 0.5.0 — three placeholder rows
for T2/T3/T4 render `tier_not_supported` after the 22 T1 rows (25 rows
total in the file). Same manifest + evidence on 0.5.0 produced the same
22-row/2-met verdict, so nothing regressed in the bump. Read the
*report*, not this summary — it is the mechanical ground truth.

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
diff a valid staleness gate rather than a flaky one. 0.6.0 also carries a
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

## The claim the two `met` rows rest on (and its limits)

`klt signoff` grades mechanically; it does not check topical relevance or
disclosure. This section is the claim, stated per the checklist's own
claimant-enforced item rules.

**Item 3, `met` (analog) — `layout/sampler_core/drc.json`.**
`klt drc` against `layout/sampler_core/sampler_core.gds`:
`status: clean`, 0 violations, deck `sky130`
(deck `content_hash sha256:5afac7ab…`), on klt 0.4.0 / KLayout 0.30.12.
The manifest pins this citation to `provenance.input.content_hash`
`sha256:a00f6550…`, which is the sha256 of the committed
`sampler_core.gds` today, so the row is fresh against current sources —
and a DRC regenerated against a changed GDS stops matching the pin and
renders `stale_evidence` instead of quietly passing.

*Coverage, quoted from the envelope's `coverage` block (item 3's
disclosure is these fields, not prose from memory):*

- `deck_scope` — the deck transcribes the foundry DRM for
  `cap2m, capm, ct, difftap, li, licon, m1, m2, m3, m4, m5, nwell, poly,
  via, via2, via3, via4` only.
- `layers_in_stream_without_rules` — drawn in this stream with no deck
  rule for them: `65/44`, `67/5`, `68/5`, `69/5`.
- `rules_skipped` — 28 rules the deck carries but this run did not
  evaluate: the `capm.*`/`capm2.*` families, met2–met5
  `enclosing`/`space`/`width` rules (e.g. `met3.space.1`,
  `met4.width.1`), and `via2`/`via3`/`via4` `space`/`width`.

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
matching `sha256:a00f6550…`) against the compose-cell.py-generated
reference for `.subckt sampler_core`: `status: match` — 264/264 devices,
152/152 nets — engine `klayout` 0.30.12.

*Warnings, listed per item 4's rule:* one warnings-only mismatch,
category `topology.flattened` — `options.flatten_reference` collapsed
17 reference circuits into one flattened top-level circuit before
comparing (topology verified after hierarchy removal on the reference
side), `error_count: 0`.

*Power/ground connectivity:* this klt 0.4.0 envelope shape carries **no
`power_connectivity` block at all** — the pin-to-net question was never
asked, which item 4's own text reads as "does not apply here", **never as
"verified"**. Nothing in this row claims power connectivity was checked;
the structural power question this block still owes is item 11 (see
#154).

*Freshness, and why this citation is the one without a pin:* klt 0.4.0's
lvs envelope records no `provenance.input.content_hash` (its provenance
`input` is `null`; the in-envelope hashes are
`environment.layout_sha256 6ed6f71b…`, verified equal to the sha256 of
the committed `layout/sampler_core/sampler_core.spice`, and
`environment.reference_sha256 18aa2d10…`, verified equal to the committed
`layout/sampler_core/sampler_core.ref.spice` — both re-verified by hand
against the committed artifacts when this manifest landed). A manifest
`content_hash` pin with no envelope hash to match against renders the
citation `stale_evidence`, so the entry is file-backed with no pin — the
one citation whose freshness gate cannot be *mechanical* on this envelope
shape. Regenerating `lvs.json` under a newer `klt` that records
`provenance.input.content_hash` (or the upstream
"verify a citation's input against the artifact" grading,
klayout-tools#2212, landing) closes this gap and should be done together
with the next layout/evidence regeneration pass, then the pin added here.

**Item 11, `unmet` (analog) — the compound citation
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
`provenance.klt_version` reads `0.6.0`, not a `+g…` dev build) records
`erc_status: clean`, zero `erc.missing_tie` / `erc.unconnected_net` /
`erc.supply_short`, all six ties in `erc_coverage.checked` and in
`checked_by_well_assertion`, nothing in `skipped`. The erc citation is
pinned to the envelope's `provenance.input.content_hash` — the committed
GDS's sha, the same pin value item 3 carries.

*Why the row is still unmet — the LVS half, and it is not this repo's
artifacts.* The grader's no-PDN (analog/full-custom) branch requires
every supply declared in the erc spec to appear in the cited `lvs.json`'s
`net_correspondence` as a row whose **entire** layout-side string equals
that supply name. `klt lvs` writes a label-merged net's row as every
alias joined with `|`, so this block's six supply rows read
`G_VDDR_M1|…|VDDR|VDDR1` etc. and can never equal `vddr1` — verified:
zero single-name supply rows exist in the 152 committed rows, and no
spec-side name can satisfy both halves at once (the ERC half needs real
label names; the LVS half needs exact alias-string equality). The
supplies demonstrably *were* part of the compare — each row pairs its
alias set to a reference-side net with `pin: true` against the SPICE
reference — which is exactly why this is a grader gap, not a design one:
filed upstream as klayout-tools#2405 (friction protocol), with local
re-grade follow-up #164. When a tagged grader release carrying the fix
lands, the expected one-command re-render moves this row to `met` and
the headline to 3/22.

**Item 4's freshness caveat applies to this citation's lvs part
unchanged** — it is the same file, cited unpinned for the same
no-envelope-hash reason (a pin with no envelope hash to match renders
`unverifiable_provenance`, per klayout-tools#2182's part-level rule).

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
`klayout-tools==0.6.0` (since 2026-09-23, issue #160 — deliberately
**diverged** from the PDK nightly's 0.5.0: the grader is a pure JSON
transform with no PDK, so it follows the grader release, while the
nightly's pin gates the nineteen committed cells' compose-cell `--check`
reproductions and moves only with a full `--check` re-verification
against a new build), runs the regeneration command
above, and fails if its output differs from the committed
`t1-report.json` — so a manifest citing an artifact that has since
changed goes red instead of rotting. The PR path needs no PDK and no
KLayout: grading is a pure JSON transform over committed envelopes.
