# trng_digital supply ERC (T1 item 11, digital column; issue #223)

Native `klt erc` evidence that the routed digital macro's two supplies are each
one connected island and that its well/substrate ties are real. Structural
only; not a foundry LVS/ERC/latch-up signoff, and not IR-drop/EM (#174).

| File | What it is |
|---|---|
| `erc-gen-supply-spec.py` | Derives the spec from `trng_digital.gds` + `pnr.json` (and cross-checks `trng_digital.def`). |
| `erc-supply-spec.json` | The native `klt erc` request (spec). Generated; do not hand-edit. |
| `erc.json` | The native `klt erc` report (unedited stdout). |
| `erc-negative-controls.py` / `.json` | Isolated mutation controls and their recorded verdicts. |

## Pins

- klt `0.7.0` (released, the pin `.github/workflows/ci.yml` uses), klayout 0.30.12.
  `erc.json` `provenance.klt_version` records it.
- Input GDS `sha256:c65e1581...` = `erc.json` `provenance.input.content_hash`
  = `drc.json`'s input hash (same artifact generation as 3.digital).
- Spec `sha256:` in `erc.json` `provenance.spec.content_hash`.
- PDK layer numbers: sky130A (`layout/pdk.json`, open_pdks c6d73a35...); no
  PDK is passed to `klt erc` (`--pdk` is antenna-only and incompatible with
  `--findings-only`).

## Cold-start reproduction

```bash
python3 -m venv /tmp/klt070 && /tmp/klt070/bin/pip install "klayout-tools==0.7.0"   # throwaway env
export PATH=/tmp/klt070/bin:$PATH
# 1. regenerate the spec (cross-checks pnr.json/DEF/GDS; fails loudly on drift)
uv run --no-project --with klayout==0.30.12 python -I layout/trng_digital/erc-gen-supply-spec.py
# 2. the native run (~7 s, exit 4 is the expected --findings-only status; gate on erc_status)
klt erc layout/trng_digital/trng_digital.gds layout/trng_digital/erc-supply-spec.json \
    --findings-only --format json > layout/trng_digital/erc.json
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

## Coverage limits (not claimed)

- Substrate tie is a caller-asserted region (well assertion), not a drawn layer.
- `--findings-only`: the antenna half did not run (`status: not_checked`,
  `coverage.skipped` reason `findings_only`); `gates[]` areas are null and no
  `active_layer` is declared, so no gate-area claim is made. DRC/antenna are
  separate items.
- Matching is by labels (VPWR/VGND on met1 cell pins and met3/met5 top text).
  The pnr.json `power_connectivity`/instance pin correctness comes from item 4's
  LVS, not from this run; hierarchy is flattened; VPB/VNB pin labels (64/5,
  64/59) are not modeled; fill/endcap rails, tap spacing/latch-up rules and
  per-cell internal rails are not checked.
- `pnr.json` records its GDS at an uncommitted build path with no GDS hash; the
  link is by identical tapcell count/DEF layers (checked by the generator) and
  the shared DRC/ERC input hash, not by a recorded P&R-to-GDS hash.
- `erc.json` is 16 MB because the native envelope carries per-gate scaffolding
  even with `--findings-only` (tool gap filed: klayout-tools#2965).
