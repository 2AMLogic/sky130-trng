# layout/ro_ring5_wstv0p44

The `wstv = 0.44 µm` starve-width instance of `ro_ring5` —
`design/ro_array_core.spice`'s ring `xr2` (`xr1` is
[`layout/ro_ring5/`](../ro_ring5/README.md), built at the ladder's nominal
`wstv = 0.42 µm`). Same five leaf gates, same four routing stages, same
placement pitch and the same lanes — see
[`layout/ro_ring5/README.md`](../ro_ring5/README.md) for the full derivation
of every number, which this file does not repeat.

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_ring5_wstv0p44/cell.json          # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_ring5_wstv0p44/cell.json --check  # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (4 stages: place / `n1`-`n4` / `ro` / rails) | all nets routed | `*.compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 22 devices (11 nfet + 11 pfet), 19 nets | `extract.json`, `ro_ring5_wstv0p44.spice` |
| `klt lvs` vs. `.subckt ro_ring5` at `wstv=0.44`, `lstv=2` (matching `xr2`) | **match** — 22/22 devices, 19/19 nets, 0 errors | `lvs.json`, `ro_ring5_wstv0p44.ref.spice` |

## What's different from `layout/ro_ring5/` (`wstv=0.42`)

Exactly three `cell.json` fields — nothing geometric changed:

1. the five `blocks[].cell.gds_path`/`cell_name` pairs point at
   `layout/ro_nand2_wstv0p44/` and `layout/ro_stage_wstv0p44/` instead of
   `layout/ro_nand2/` and `layout/ro_stage/`;
2. `lvs.params.wstv: 0.44`;
3. `cell` (and therefore the output GDS/netlist names).

Every origin, lane, waypoint and port coordinate is byte-for-byte identical
to `layout/ro_ring5/cell.json`. That is **verified, not assumed**: all four
`wstv` variants of `ro_stage` and of `ro_nand2` have identical cell bounding
boxes, identical merged-`nwell` bounding boxes and identical merged-`met1`
bounding boxes (read directly from the committed GDS), because
`layout/README.md`'s "Starve-width variants" recipe absorbs the width change
by re-deriving `Mph`/`Mnt`'s own placement origin inside the leaf rather
than by growing the cell. Composed extent is therefore identical to ring 1's:
`-2.19 … 38.81 µm` in x for the placed blocks, with the
rails carrying the final GDS to `y = -3.085 … 6.085 µm`.

The `match` verdict above is width-specific rather than vacuous — see
`layout/ro_ring5/README.md`'s "Negative control" section, which uses
**this** family's `wstv=0.48` netlist against ring 1's `wstv=0.42` reference
and gets a 63-mismatch `mismatch`.
