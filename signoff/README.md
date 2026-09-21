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

At `origin/main` at the time this landed, the report reads:
**22 T1 rows rendered (11 checklist items × 2 partitions), 2 met —
item 3 (DRC clean) and item 4 (LVS clean), analog partition only —
so this block is 2/22 of the way to T1**, with item 11 (power delivery,
structural) counted and `unmet` from the day it was added. `tier` is
`null` until every rendered item is `met`. Read the *report*, not this
summary — it is the mechanical ground truth.

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
diff a valid staleness gate rather than a flaky one.

## Why the tiers doc is vendored

The grade target is an upstream document that moves independently of this
repo — the checklist gained an **eleventh item on 2026-09-17**
(`klt erc` supply evidence, klayout-tools#2025), which instantly
invalidated every prior hand-read in the fleet. The `klt` PyPI release
this repo's CI pins (`klayout-tools==0.5.0`) bundles a **10-item** copy
of that doc, so rendering with the wheel's default would silently grade
against a checklist that no longer exists. This vendored copy is
byte-identical to upstream:

- repo: `2AMLogic/klayout-tools`, file `docs/design-evidence-tiers.md`
- blob git-hash: `143fdacaa5b099ea59d38807e5d7d14546c33db6`
- upstream commit that last touched it: `31a3e3c41c08bbd58719e0b99a3d6d19beb9be63` (2026-09-21)
- sha256: `c7a1e7e10627fae396007e0ff951734f37d95028b8f49f2e21e802e9f552f318`

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

`.github/workflows/ci.yml`'s `signoff-check` job installs the same pinned
`klayout-tools==0.5.0` as the PDK nightly, runs the regeneration command
above, and fails if its output differs from the committed
`t1-report.json` — so a manifest citing an artifact that has since
changed goes red instead of rotting. The PR path needs no PDK and no
KLayout: grading is a pure JSON transform over committed envelopes.
