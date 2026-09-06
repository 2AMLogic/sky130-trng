# `ro_ring5-connectivity-poc`

**Status: connectivity proven, DRC/LVS/rails not clean.** Not a
`compose-cell.py` cell (no `cell.json`, no `--check`) — same convention as
[`layout/xor2-placement-poc/`](../xor2-placement-poc/README.md): a
proof-of-concept directory for a hierarchical-assembly step that is not yet
fully composed, following issue [#27](https://github.com/2AMLogic/sky130-trng/issues/27)
step 3 ("hierarchical assembly: `ro_ring5` (5 gates + inter-gate routing)").

This is the first attempt at composing `ro_ring5` — `design/ro_array_core.spice`'s
`.subckt ro_ring5 en ro vddr vss` — from the five already-composed,
individually DRC-clean/LVS-clean leaf gates under `layout/ro_nand2/` and
`layout/ro_stage/` (`xg`/`x1`-`x4` in that subckt), placed via `klt
gen-compose`'s `blocks[].cell` request shape (an *existing* stream, not a
fresh `klt gen` call — see `compose-cell.py`'s own module docstring, "the
working recipe" in `layout/README.md`).

## What is proven

**The inter-stage signal chain (`n1`-`n4`) places and routes cleanly.**
[`compose.request.json`](compose.request.json) places `g` (`ro_nand2`,
`design/ro_array_core.spice`'s `xg`) and `s1`-`s4` (`ro_stage`, `x1`-`x4`) at
explicit origins and wires the four forward inter-gate nets
(`g.y`->`s1.a`, `s1.y`->`s2.a`, `s2.y`->`s3.a`, `s3.y`->`s4.a`) on the base
`"metal"` (li1) role, each on its own staggered waypoint height (`5.0`/
`5.3`/`5.6`/`5.9` µm) to keep them from crossing each other — the same
technique `layout/README.md`'s "Composing a gate" section documents for a
same-block bundle, extended here across five separately-placed blocks.
[`compose.response.json`](compose.response.json) confirms all four nets
`"status": "routed"`, and [`extract.json`](extract.json) confirms the
resulting `core.gds` extracts to **22 devices (11 nfet + 11 pfet — exactly
`ro_nand2`'s 6 + 4x`ro_stage`'s 4), 19 nets**, matching the expected device
count for five placed gates with no devices dropped or duplicated by
placement.

This is genuine, new evidence: it is the first proof that `klt
gen-compose`'s `blocks[].cell` request shape (placing an *already-composed*
cell rather than a fresh `klt gen` primitive) works for this design's own
leaf cells, and that a multi-block inter-gate signal chain composes without
the same-layer route-crossing failure a naive first attempt hit (see "What
was tried and did not work" below for that failure and its fix).

`layout/bin/compose-cell.py` gained two capabilities to make this possible,
both regression-tested against every previously-committed cell
(`ro_buf`, `ro_stage`, `ro_nand2`, and all three `wstv` variants of each —
nine cells total, all `--check` clean against this change):

1. **`blocks[].cell` support** (`compose_stage`, "An *existing* library
   cell" branch): a `cell.json` block entry with `"cell": {"gds_path",
   "cell_name", "ports": [...]}`  places a previously-composed,
   already-committed `layout/<other-cell>/<other-cell>.gds` instead of
   running `klt gen`. Since a pre-existing cell never reported a `ports[]`
   list to any `klt gen`/`klt gen-compose` response the way a fresh
   primitive does, its ports have to be hand-declared — see "A hand-declared
   `ports[]` is a real hazard" below for what that costs when the
   declaration doesn't match the underlying GDS.
2. **Multi-subckt LVS references** (`lvs.dependencies`, `build_reference`'s
   transformation 2): once a composed cell's reference netlist needs more
   than one `.subckt` from `design/*.spice` (`ro_ring5`'s own body
   instantiates `ro_nand2` and `ro_stage`), `compose-cell.py` can extract and
   rewrite each dependency subckt ahead of the top subckt, and drops a
   pass-through keyword argument (`wstv=wstv`) on an instance-call line
   rather than trying to substitute it, since the *callee* subckt's own
   header no longer declares that parameter once transformation 1 has
   already replaced every internal use with a literal. Not exercised end to
   end here (this PoC never reaches the LVS step — see below), but proven
   independently: [`lvs.request.json`](#) is not committed because no LVS
   attempt was made against an unrouted layout, and the reference-building
   logic itself is unit-testable via `build_reference` directly if a future
   increment wants a dedicated test before depending on it further.

## What is not proven: `core.gds` is not DRC-clean

Running `klt drc` directly against the five-gate placement (bypassing
`compose-cell.py`, since the full chain aborts before DRC — see below)
reports **8 violations** ([`drc.json`](drc.json)):

| rule | where | bbox (nm) | shortfall |
|---|---|---|---|
| `li1.space.1` | `core` (new `n1` route vs. `g`'s own li1) | (4540,1409)-(4705,1890) | 5 nm (165 vs. 170 required) |
| `li1.space.1` | `core` (new `n1` route vs. `g`'s own li1) | (4665,865)-(4705,1615) | 130 nm (40 vs. 170 required) |
| `li1.space.1` | `g`'s own `mpb` device | (4875,3205)-(5000,4275) | 45 nm (125 vs. 170 required) |
| `li1.space.1` | `s1`'s own `mp` device | (12220,3224)-(12360,4256) | 30 nm (140 vs. 170 required) |
| `li1.space.1` | `s2`'s own `mp` device | (20395,3224)-(20535,4256) | 30 nm (140 vs. 170 required) |
| `li1.space.1` | `s3`'s own `mp` device | (28570,3224)-(28710,4256) | 30 nm (140 vs. 170 required) |
| `li1.space.1` | `s4`'s own `mp` device | (36745,3224)-(36885,4256) | 30 nm (140 vs. 170 required) |
| `nwell.space.1` | between `g` and `s1`'s own wells | (5570,2350)-(6570,4810) | 270 nm (1000 vs. 1270 required) |

Two distinct root causes, not one:

1. **The `nwell.space.1` violation is a placement-pitch bug, fully
   diagnosed.** `compose.request.json`'s `placement.origins_um` puts `g` at
   `x=0` and `s1` at `x=8.76` — a bbox-edge-to-bbox-edge gap of exactly
   `6.57 - 5.57 = 1.00 µm` (`g`'s own bbox `x1=5.57`, `s1`'s own bbox
   `x0=-2.19` plus its `8.76` origin). `sky130.lydrc`'s `nwell.2a` requires
   `1.27 µm` nwell-to-nwell clearance (`klayout_tools/decks/sky130.py`'s
   `nwell.space.1`, `threshold_dbu=1270`), so `1.00 µm` is `0.27 µm` short —
   and the reported violation's own bbox width is exactly `1000 nm`,
   confirming this reading precisely. The other three inter-block gaps
   (`s1`-`s2`, `s2`-`s3`, `s3`-`s4`) all use a *looser* `8.175 µm` origin
   delta against `ro_stage`'s narrower `6.52 µm` bbox width, landing a
   `1.655 µm` gap that clears `1.27 µm` — which is exactly why only the
   `g`-`s1` boundary (the one place a wider `ro_nand2` meets a narrower
   `ro_stage`) violates. **The fix for a future attempt is mechanical**:
   widen every inter-block origin delta by at least `0.27 µm` (a safe
   margin, e.g. `+0.5 µm`, is recommended so the fix survives being
   ± reused for other gate-pair boundaries) and re-derive the `n1`-`n4`
   waypoints' x-coordinates from the new placements — the y-coordinates
   (the per-net staggered heights) are unaffected.
2. **The seven `li1.space.1` violations are not yet root-caused with the
   same confidence — 2 are attributed, 5 are unexplained.** The **two**
   attributed ones (rows 1-2 of the table, `source_path`
   `g__ro_nand2/core__core`, i.e. against `g`'s own top-level li1 rather
   than any device inside it) are plausibly the newly-drawn `n1` route
   (introduced by *this* composition, landing at `x=4.79 µm` per its own
   waypoint) sitting too close to a pre-existing `li1` pad inside `g` — the
   composed `n1` route did not exist when `ro_nand2` was independently
   verified DRC-clean, so this is a genuinely new interaction the leaf-cell
   verification could not have caught. The remaining **five** (rows 3-7)
   are the more surprising finding, and none of them is explained: all five
   land inside a leaf gate's *own device* geometry (`source_path` ending in
   a `mos_array`) — one in `g`'s own `mpb` (45 nm short) and four repeated
   once per `ro_stage` instance in each `s1`-`s4`'s own `mp` (30 nm short,
   identical shape and relative position, all at the same local
   coordinates). Both leaf cells are independently DRC-clean (0 violations
   in `layout/ro_nand2/drc.json` and `layout/ro_stage/drc.json`), so the
   same device geometry reporting a marginal `li1.space.1` violation only
   once nested one level deeper inside `core`'s own composition suggests
   either a hierarchy-dependent DRC evaluation difference (flattened vs.
   cell-based rule application — see `layout/README.md`'s standing caveat
   that `klt`'s sky130 deck is a *curated subset*, not full sign-off) or a
   real marginal geometry this PoC's placement newly exposes. **Left open
   for the next attempt to root-cause with `klt render`** (see "What was
   tried and did not work" below for the rendering technique that did work
   for the rail-routing investigation) — recorded here as a fact, not a
   diagnosis, since neither explanation is confirmed.

   2 attributed + 5 unexplained = the 7 `li1.space.1` rows above, which
   with the single `nwell.space.1` row is the 8 violations `drc.json`
   reports (`rule_counts`: `li1.space.1: 7`, `nwell.space.1: 1`).

Given both categories, **`core.gds` cannot be called DRC-clean**, so this
PoC does not run `klt extract`/`klt lvs` toward any sign-off claim — the
`extract.json` committed here is purely a device/net-count sanity check, not
an LVS input.

## What was tried and did not work: rail busing (`vddr`, `vss`, `ro`)

`design/ro_array_core.spice`'s `ro_ring5` subckt has four pins:
`en`, `ro`, `vddr`, `vss`. Beyond the four `n1`-`n4` signal nets, the ring
needs: `vddr`/`vss` bussed across all five gates (ten leg connections total,
two per gate), and `ro` — the feedback net closing `x4`'s output back into
`xg`'s own input, which is *also* the ring's external output pin.

**First attempt: route these on the base `"metal"` role, same as `n1`-`n4`.**
Fails immediately: `ro`'s own waypoints must approach `g.a` (local
`x=4.665`) via a vertical stub, which physically overlaps `n1`'s own
vertical stub (`g.y`, local `x=4.79`) — the two ports are only `0.125 µm`
apart, closer than the `0.17 µm` route width, so *any* two vertical stubs
serving them will overlap regardless of waypoint choice. This is a real
geometric constraint of `ro_nand2`'s own pin layout, not a tuning mistake.

**Second attempt: move `vddr`/`vss`/`ro` to the `"metal2"` role** (the same
via-drop technique `ro_stage`/`ro_nand2`'s own two-pass `"stages"`
composition already uses internally). This clears the `n1`-`n4` conflict
(different physical layer) but hits a new, more fundamental one:
`gen-compose` reports (verbatim)

```
self-net's drawn 0.17um metal overlaps 0.2834um^2 of block 'core''s own
drawn pad metal on the route layer (drawn geometry (no port of its own sits
on it)) -- bussing this net across the block would draw a silent short to
that pad (its drawn metal is larger than the contact size its port
reports); route to a layer_role with a metal2/via stack instead (or
configure routing.cross_block_layer_role, issue #1168), or wire this net
externally
```

Rendering `layout/ro_nand2/ro_nand2.gds`'s own metal2 layer (`klt render
ro_nand2.gds --layers '[[68,20],[67,20]]'`) shows why: `ro_nand2`'s own
internal `vddr`-to-`mnt_g` and `py`-bundle metal2 routing (drawn by its own
two-pass `"stages"` composition, per `layout/ro_nand2/cell.json`) already
occupies most of the cell's upper region (`y` roughly `3.74`-`4.5 µm`
across most of the cell's `x` extent), and `ro_stage`'s own internal
`vddr`-to-`mnt_g` routing comes within `0.11 µm` of the `vss` bus's own
target height at the block boundary — both closer than the `0.17 µm` route
width can clear. A `vddr`/`vss` bus wired point-to-point across five placed
gates' own external pins runs directly into every gate's own *internal*
metal2 wiring, because both now share the same physical layer.

**Third attempt: `routing.cross_block_layer_role` (issue #1168 in
klayout-tools)** — a documented `gen-compose` feature built for exactly
this class of conflict: a same-block self-net leg that would otherwise
short across another of that block's own pads on the primary
`routing.layer_role` automatically retries on a second, higher metal role,
leaving every other net on the primary role unchanged
(`klayout_tools/gen_compose.py`, "Cross-block bus routing" in its own
module docstring). Configuring `"cross_block_layer_role": "metal3"`
fails differently:

```
pin 'g_vddr' on block 'core' is drawn on layer (67, 20), which
routing.layer_role's (69, 20) cannot reach: routing.layer_role's metal
(deck metals[2]) is more than one via hop from this pin's own layer (deck
metals[0]) -- gen_compose's via-drop only supports a single-hop drop
```

This is the same single-hop via-drop limit `layout/README.md`'s "Floorplan
decisions made so far" section already names for a different reason
(`"metal3"` needing a pin already wired onto `"metal2"`) — confirmed here
to also block `cross_block_layer_role`'s own fallback when the *original*
pin is a bare base-`"metal"` (li1) port, which every leaf gate in this
design exposes. **Not filed as a new `klayout-tools` issue**: this is the
same documented single-hop-only via-drop behaviour, applied through a
different call path, not a new capability gap — the existing citations
(`layout/README.md`'s `"metal3"` note) already describe it accurately.

**What the next attempt should try, not yet attempted here**: an explicit
intermediate stage that promotes each rail pin from li1 to metal2 with a
short, local (not cell-crossing) via stub *before* the cross-gate bus stage
routes on metal3 — i.e. three stages total (base-metal `n1`-`n4`, a
per-gate li1-to-metal2 promotion stub, then a metal3 bus), so
`cross_block_layer_role`'s single-hop rule is satisfied at each step. This
was reasoned through but not implemented or verified in this PoC; treat it
as a hypothesis, not a proven recipe.

## A hand-declared `ports[]` is a real hazard

`compose.request.json`'s `blocks[].cell.ports[]` entries for `g`/`s1`-`s4`
are hand-typed from each leaf cell's own committed evidence (`layout/ro_nand2/`,
`layout/ro_stage/`'s `core.compose.response.json` — the intermediate stage,
since the *final* `compose.response.json` for both leaf cells reports an
**empty** `"ports": []`, i.e. neither leaf's own top-level response exposes
port geometry at all once its second stage runs). One of those hand-typed
values was simply wrong: `vddr`'s `direction_deg` was declared `90`
(matching every other port's stub direction) but its real value, read from
`layout/ro_stage/core.compose.response.json`, is `180` (the tap ring's own
contact faces `-x`, not `+y`). Whether this specific mismatch caused any of
the routing failures above (as opposed to the genuine geometric conflicts
already identified) was not conclusively separated out before time on this
PoC ran out — flagged here so the next attempt does not have to
independently discover that the *only* authoritative source for a
pre-existing cell's port geometry is its own intermediate per-stage
response, not its final one, and does not have to re-derive `vddr`'s real
`180°` direction from scratch.

## Reproducing this PoC

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/ro_ring5-connectivity-poc
klt gen-compose compose.request.json --format json   # re-places + re-routes n1-n4
klt drc core.gds --deck sky130 --format json          # reproduces the 8 violations above
klt extract core.gds --deck sky130 --format json      # reproduces the 22-device, 19-net count
```

## What's next

Tracked as part of issue [#27](https://github.com/2AMLogic/sky130-trng/issues/27)
step 3 (hierarchical assembly). A future increment should, in order: (1) fix
the placement pitch (mechanical, fully diagnosed above), (2) root-cause the
seven `li1.space.1` violations with `klt render` — the five unexplained
device-internal ones first — before assuming either candidate explanation, (3) attempt the three-stage
li1-to-metal2-to-metal3 rail-promotion recipe above for `vddr`/`vss`/`ro`,
and only then re-run `compose-cell.py`'s full chain (which will also
exercise the `lvs.dependencies` multi-subckt reference support added by
this increment, not yet exercised end to end).
