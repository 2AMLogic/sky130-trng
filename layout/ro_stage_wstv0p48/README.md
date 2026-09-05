# layout/ro_stage_wstv0p48

The `wstv = 0.48 µm` starve-width instance of `ro_stage` —
`design/ro_array_core.spice`'s ring `xr4`, the last of the four-ring ladder
(`xr1` is `layout/ro_stage/`, built at the nominal `wstv = 0.42 µm`). Same
four devices, same six nets, same floorplan and routing as
`layout/ro_stage/` — see that cell's own README for the full methodology
writeup, which this file does not repeat. The only thing that changes per
`wstv` is documented here and in `layout/README.md`'s "Starve-width
variants" section.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_stage_wstv0p48/cell.json          # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_stage_wstv0p48/cell.json --check  # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `core`, base metal/li1) | 6/6 nets routed | `core.compose.response.json` |
| `klt gen-compose` (final stage, metal2 + via-drop) | 2/2 nets routed | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 4 devices, 6 nets | `extract.json`, `ro_stage_wstv0p48.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt ro_stage` (`wstv=0.48`, `lstv=2` — matching `xr4`) | **match** — 4/4 devices, 6/6 nets, 0 mismatches | `lvs.json`, `ro_stage_wstv0p48.ref.spice` |

## What's different from `layout/ro_stage/` (`wstv=0.42`)

Exactly two `cell.json` fields, both on `Mph`/`Mnt` (the starve pair):

1. `params.w_um: 0.48` instead of `0.42` on both `mph` and `mnt` blocks.
2. `placement.origins_um`, re-derived per `layout/README.md`'s "Starve-width
   variants" closed form:
   - `mph.y = 3.74 + w/2 = 3.98`
   - `mnt.y = 0.21 - w/2 = -0.03`

Every other block, origin, waypoint, and routing-layer choice is
byte-for-byte identical to `layout/ro_stage/cell.json`.

## What this does NOT establish

Same caveats as `layout/ro_stage/README.md`'s own list — none of those are
affected by which `wstv` value this specific cell is built at. This
completes the four-ring `ro_stage` ladder (`xr1`-`xr4`, `wstv` 0.42-0.48 µm) —
see `layout/README.md` for the running tally against issue #27's remaining
scope (`ro_nand2`'s own ladder, `xor2`, and hierarchical assembly).
