# layout/ro_stage_wstv0p44

The `wstv = 0.44 µm` starve-width instance of `ro_stage` —
`design/ro_array_core.spice`'s ring `xr2` (`xr1` is `layout/ro_stage/`, built
at the ladder's nominal `wstv = 0.42 µm`). Same four devices, same six nets,
same floorplan and routing as `layout/ro_stage/` — see that cell's own
README for the full methodology writeup (why this gate needed a two-pass
`"stages"` composition, the `py`/`Mph`-`Mp` well-merge, etc.), which this
file does not repeat. The only thing that changes per `wstv` is documented
here and in `layout/README.md`'s "Starve-width variants" section.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_stage_wstv0p44/cell.json          # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_stage_wstv0p44/cell.json --check  # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `core`, base metal/li1) | 6/6 nets routed | `core.compose.response.json` |
| `klt gen-compose` (final stage, metal2 + via-drop) | 2/2 nets routed | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 4 devices, 6 nets | `extract.json`, `ro_stage_wstv0p44.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt ro_stage` (`wstv=0.44`, `lstv=2` — matching `xr2`) | **match** — 4/4 devices, 6/6 nets, 0 mismatches | `lvs.json`, `ro_stage_wstv0p44.ref.spice` |

## What's different from `layout/ro_stage/` (`wstv=0.42`)

Exactly two `cell.json` fields, both on `Mph`/`Mnt` (the starve pair) —
nothing else in the descriptor changed:

1. `params.w_um: 0.44` instead of `0.42` on both `mph` and `mnt` blocks.
2. `placement.origins_um` for `mph`/`mnt`, re-derived (not copied) — see
   `layout/README.md`'s "Starve-width variants" section for the closed-form
   derivation this uses:
   - `mph.y = 3.74 + w/2 = 3.96`
   - `mnt.y = 0.21 - w/2 = -0.01`

Every other block, origin, waypoint, and routing-layer choice is
byte-for-byte identical to `layout/ro_stage/cell.json`. This is not an
approximation: rebuilding with the *unadjusted* (`wstv=0.42`-tuned) origins
at `w=0.44` fails `klt gen-compose` with `py`/`vddr` reported unrouted (the
`Mph`/`Mp` well-merged pair's straight, no-jog route depends on `Mph.D`
landing at exactly the same absolute `y` as `Mp.S`, which only holds when
`Mph`'s own origin is re-derived for its new width) — see
`layout/README.md` for the failure evidence and the derivation.

## What this does NOT establish

Same caveats as `layout/ro_stage/README.md`'s own list (curated-deck DRC
scope, no parasitics/post-layout sim, DR-0003 §8 still unevaluated, LVS
reference is a unit-normalised parameter substitution) — none of those are
affected by which `wstv` value this specific cell is built at. This cell
does **not** by itself close issue #27's "four distinct physical cells" item
for `ro_stage`; see `layout/README.md` for the running tally across all four
`wstv` values.
