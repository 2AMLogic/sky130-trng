# trng_digital supply ERC (T1 item 11, digital column; issue #223)

Native `klt erc` evidence that the routed digital macro's two supplies are each
one connected island and that its well/substrate ties are real. Structural
only; not a foundry LVS/ERC/latch-up signoff, and not IR-drop/EM (#174).

| File | What it is |
|---|---|
| `erc-gen-supply-spec.py` | Derives the spec from `trng_digital.gds` + `pnr.json` (and cross-checks `trng_digital.def`). |
| `erc-supply-spec.json` | The native `klt erc` request (spec). Generated; do not hand-edit. |
| `erc.json` | The native `klt erc` report with the three inert antenna arrays emptied (issue #494; see "Committed prune"). |
| `erc-negative-controls.py` / `.json` | Isolated mutation controls and their recorded verdicts. |

## Pins

- klt `0.7.0` (released; the build that produced `erc.json`. `.github/workflows/ci.yml` grades on 0.8.0 since issue #363), klayout 0.30.12.
  `erc.json` `provenance.klt_version` records it.
- Input GDS `sha256:c65e1581...` = `erc.json` `provenance.input.content_hash`
  = `drc.json`'s input hash (same artifact generation as 3.digital).
- Spec `sha256:` in `erc.json` `provenance.spec.content_hash`.
- PDK layer numbers: sky130A (`layout/pdk.json`, open_pdks c6d73a35...); no
  PDK is passed to `klt erc` (`--pdk` is antenna-only and incompatible with
  `--findings-only`).

## Cold-start reproduction

```bash
python3 -m venv /tmp/klt070 && /tmp/klt070/bin/pip install "klayout-tools==0.7.0" "klayout==0.30.12"   # throwaway env (klayout pinned: provenance records its version)
export PATH=/tmp/klt070/bin:$PATH
# 1. regenerate the spec (cross-checks pnr.json/DEF/GDS; fails loudly on drift)
uv run --no-project --with klayout==0.30.12 python -I layout/trng_digital/erc-gen-supply-spec.py
# 2. the native run (~7 s, exit 4 is the expected --findings-only status; gate on erc_status)
klt erc layout/trng_digital/trng_digital.gds layout/trng_digital/erc-supply-spec.json \
    --findings-only --format json > layout/trng_digital/erc.json
# 2b. prune the inert antenna scaffolding to reproduce the committed bytes (issue #494)
python3 -c "
import json
p = 'layout/trng_digital/erc.json'
d = json.loads(open(p).read())
d['gates'] = []
d['coverage']['skipped'] = []
d['coverage']['inapplicable'] = []
open(p, 'w').write(json.dumps(d, indent=2) + '\n')
"
# 3. negative controls (6 x ~7 s)
uv run --no-project --with klayout==0.30.12 python -I layout/trng_digital/erc-negative-controls.py
# 4. tier report
klt signoff --manifest signoff/block-manifest.json \
    --tiers-doc signoff/design-evidence-tiers.md --format json > signoff/t1-report.json
```

## What the report says

- `VPWR`, `VGND`: `matched_islands: 1` each; `erc_findings: []`; `erc_status: clean`.
- Stackup: poly (gate role), li1, met1-met5 with the six cut layers. It covers
  every `pnr.json` `power.straps[].layer` (met1, met4, met5) and every layer in
  the DEF special nets (met1-met5). `71/5` carries no text so met4 is declared
  without a label layer (labels come from met1 cells and met3/met5 top text).
- Ties, both in `erc_coverage.checked`, nothing in `skipped`:
  - `nwell_vpwr`: the drawn nwell (64/20, 43 merged wells) against the dedicated
    tap layer 65/44 (704 n-taps), wired via li1. Every well must hold a tap
    reaching VPWR.
  - `substrate_vgnd`: sky130 has no drawn p-well, so this is the native
    substrate form (`well_layer: null` + 704 `well_boxes`, one per p-tap
    polygon). It grades as `checked_by_well_assertion` (the regions are the
    caller's assertion, derived from the GDS p-taps, falsified per box).
- The generator asserts `pnr.json placed.tapcells` (704) == tapcell instances in
  the DEF == n-taps == p-taps in the GDS, and that `power.pdn` is true.
  `lvs.json` `power_connectivity.status` is `match` (VPWR/VGND/VPB).

## Negative controls (all detected)

Each mutates a copy of the GDS (or spec) in a temp dir; the committed artifacts
are untouched. See `erc-negative-controls.json` for findings and input hashes.

| Control | Mutation | Result |
|---|---|---|
| P0 | none | clean, 1 island per supply |
| N1 | delete the met4-met5 cuts (71/44) | `erc.unconnected_net` x2, 2 islands per supply |
| N2 | met5 box bridging two adjacent straps | `erc.supply_short` |
| N3 | remove n-tap from all 16 tapcells of one well | `erc.missing_tie` (that well) |
| N4 | remove the p-tap from one tapcell | `erc.missing_tie` (its substrate box) |
| N5 | spec: nwell tie declared on VGND | `erc.missing_tie` x43 |

### `klt_version` spelling in the committed summary (issue #500)

The committed `erc-negative-controls.json` records `"klt_version": "klt 0.7.0"`,
with the `klt ` banner prefix. That is the faithful record of what the run
read: the generator resolved the version with `klt --version`, whose output is
the banner `klt 0.7.0` and not the bare `0.7.0`. It was the only one of the
392 `klt_version` values in this repo's committed evidence spelled that way,
and `sim/` records are append-only, so the value **stays** — the producer is
what changed.

`erc-negative-controls.py` now reads the version through
`_klt_common.klt_version()`, i.e. from `klt version --format json`'s `version`
field, so a re-run writes the bare `"0.7.0"`. Expect that one field to differ
from the committed summary on the next regeneration; it is a spelling
correction, not a tool change, and nothing compares this file's `klt_version`
against another record's.

## Coverage limits (not claimed)

- Substrate tie is a caller-asserted region (well assertion), not a drawn layer.
- `--findings-only`: the antenna half did not run (`status: not_checked`;
  the native run records it as `coverage.skipped` reason `findings_only` —
  in the committed prune those reason codes survive in
  `coverage.nothing_checked_reasons`); every per-level antenna data field
  in `gates[]` is null with `verdict: "unchecked"` (the per-gate
  `gate_area_um2` values are populated, not null — discarded by the prune
  below), and no `active_layer` is declared, so no gate-area claim is
  made. DRC/antenna are separate items.
- Matching is by labels (VPWR/VGND on met1 cell pins and met3/met5 top text).
  The pnr.json `power_connectivity`/instance pin correctness comes from item 4's
  LVS, not from this run; hierarchy is flattened; VPB/VNB pin labels (64/5,
  64/59) are not modeled; fill/endcap rails, tap spacing/latch-up rules and
  per-cell internal rails are not checked.
- `pnr.json` records its GDS at an uncommitted build path with no GDS hash; the
  link is by identical tapcell count/DEF layers (checked by the generator) and
  the shared DRC/ERC input hash, not by a recorded P&R-to-GDS hash.
- `erc.json` is committed at 238 KB, pruned from the native 16 MB (issue
  #494): the envelope carries per-gate antenna scaffolding even with
  `--findings-only` (tool gap filed: klayout-tools#2965). See "Committed
  prune" below.

## Committed prune (issue #494)

The committed `erc.json` is the native report with three arrays emptied —
not a summary and not a reformat: every other key is byte-identical to the
stdout `klt erc` wrote (the native formatting round-trips
`json.dumps(..., indent=2)` exactly).

| Array | Native entries | Every entry |
|---|---|---|
| `gates` (per-gate records) | 5,624 | `antenna_verdict: "unchecked"` |
| `gates` (per-level records) | 5,624 gates × 7 levels = 39,368 | `verdict: "unchecked"`, all six data fields `null` |
| `coverage.skipped` | 33,744 | `{"reason": "findings_only"}` |
| `coverage.inapplicable` | 5,624 | `{"reason": "gate_reference_level"}` |

Each of the 5,624 gate records also carried per-gate fields beyond
`antenna_verdict` — `gate_id` (5,624 non-null), `net` (2,244 non-null) and
a real `gate_area_um2` float (5,624 populated, 423 distinct values) — which
the prune discarded along with the inert level records. Regenerable via
steps 2 + 2b above.

That was 16,452,974 B → 238,415 B (−98.6%), and the three facts the arrays
restated are still carried by the scalars the envelope keeps:
`findings_only: true`, `coverage.nothing_checked: true`,
`coverage.nothing_checked_reasons: ["findings_only", "gate_reference_level"]`,
`gate_count: 5624`. The arrays are emptied to `[]`, not dropped:
`klt signoff`'s erc shape check requires `gates` to be a list, and the
common coverage validator requires all four work lists (`checked`/`skipped`/
`inapplicable`/`unknown`) present. A reader of the committed `erc.json`
alone therefore sees `coverage.skipped: []`, `coverage.inapplicable: []`
and `gates: []`, with the truth carried only by `gate_count: 5624`,
`coverage.nothing_checked_reasons` and this section — no in-band prune
marker exists, by design (adding a key would break the byte-identity of
the surviving keys the prune preserves).

Why pruning and not gzip, per the operator ruling of 2026-11-23 (issue
#494): the ruling preferred committing the report gzipped — which keeps the
file's bytes unedited — but the grading build this repo's CI pins for
`klt signoff` (0.8.0, issue #363) reads citations as plain UTF-8 JSON and
grades a `.gz` citation `unmet`/`unreadable_evidence` (verified by running
the recipe's step 4 against a `.gz` citation). Transparent `.gz` citation
support landed in klt 0.9.2 (klayout-tools#5458, reports #5452/#6944), so
once the grading pin moves to ≥ 0.9.2 the unedited-stdout artifact can be
restored: re-run step 2 and commit `erc.json.gz` instead of pruning.

Grading neutrality, verified: with the prune, `klt signoff` (0.8.0)
re-renders `signoff/t1-report.json` byte-identically to the committed
report; item 11.digital stays `met` with `check_status: "not_checked"`,
`input_verified: true`, `exit_status: 0`, and the manifest's input-GDS pin
(`sha256:c65e1581...`, the GDS, not the report bytes) is unchanged.
`erc_coverage` — the supply-island and tie evidence — is untouched, and
`erc-negative-controls.py` never opens the committed `erc.json`: its
`erc_coverage` reads are from its own run outputs.
