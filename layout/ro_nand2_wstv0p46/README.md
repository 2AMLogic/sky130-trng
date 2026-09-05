# layout/ro_nand2_wstv0p46

The `wstv = 0.46 µm` starve-width instance of `ro_nand2` —
`design/ro_array_core.spice`'s ring `xr3` (`xr1` is `layout/ro_nand2/`, built
at the ladder's nominal `wstv = 0.42 µm`). Same six devices, same eight
nets, same floorplan and routing as `layout/ro_nand2/` — see that cell's own
README for the full methodology writeup, which this file does not repeat.
The only thing that changes per `wstv` is documented here and in
`layout/README.md`'s "Starve-width variants" section.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_nand2_wstv0p46/cell.json          # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_nand2_wstv0p46/cell.json --check  # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `core`, base metal/li1) | 5/5 nets routed, 6 endpoints promoted as bare pins | `core.compose.response.json` |
| `klt gen-compose` (final stage, metal2 + via-drop, 6 same-block self-nets) | 6/6 nets routed | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 6 devices (3 nfet, 3 pfet), 8 nets | `extract.json`, `ro_nand2_wstv0p46.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt ro_nand2` (`wstv=0.46`, `lstv=2` — matching `xg` at `xr3`) | **match** — 6/6 devices, 8/8 nets, 0 mismatches | `lvs.json`, `ro_nand2_wstv0p46.ref.spice` |

## What's different from `layout/ro_nand2/` (`wstv=0.42`)

Exactly two `cell.json` fields, both on `Mph`/`Mnt` (the starve pair):

1. `params.w_um: 0.46` instead of `0.42` on both `mph` and `mnt` blocks.
2. `placement.origins_um`, re-derived per `layout/README.md`'s "Starve-width
   variants" closed form:
   - `mph.y = 3.74 + w/2 = 3.97`
   - `mnt.y = 0.21 - w/2 = -0.02`

Every other block, origin, waypoint, and routing-layer choice is
byte-for-byte identical to `layout/ro_nand2/cell.json`.

## What this does NOT establish

Same caveats as `layout/ro_nand2/README.md`'s own list — none of those are
affected by which `wstv` value this specific cell is built at. See
`layout/README.md` for the running tally across all four `wstv` values.
