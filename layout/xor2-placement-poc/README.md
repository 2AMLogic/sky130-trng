# layout/xor2-placement-poc

> **SUPERSEDED — `xor2` is composed, DRC-clean and LVS-clean, in
> [`layout/xor2/`](../xor2/README.md)** (12/12 devices, 10/10 nets, 0
> violations). Two of this PoC's conclusions did not survive that, and both
> are corrected here rather than edited away, since the reasoning below is
> what a future reader would otherwise repeat:
>
> 1. **"A genuine multi-net channel-routing problem ... plausibly needing
>    `klt`'s third routing plane" was wrong** — not about the geometry this
>    PoC measured, which is reproducible, but about the conclusion drawn
>    from it. `layout/xor2/` uses **two** routing planes (li1 and met1), no
>    channel router, and no joint net ordering, because it does not present
>    the router with this PoC's problem at all: it places **9 blocks and 12
>    net legs** where this PoC placed 17 blocks and offered 31 nets. Three
>    moves do that — reading the pull-up tree as two *series* chains
>    (`mos_array`'s `finger_topology: "series"`, four devices per two
>    blocks, `mid` as a contactable interior `U0_D0`), placing the two
>    inverters as already-composed `ro_buf` cells, and splitting the nets
>    across *layers* (supplies + `y` on li1, the four gate nets on met1)
>    instead of across lanes on one layer. See `layout/xor2/README.md`
>    § "Why the PoC's prediction did not hold".
> 2. **The floorplan below is not the one that composed.** Twelve
>    individually-well-strapped devices with 41 bare promoted pins is a
>    valid DRC-clean placement and its port table is still correct for
>    *itself*, but `layout/xor2/` shares none of its coordinates.
>
> What **does** survive, and is used by `layout/xor2/`: the `"metal3"`
> single-hop finding (finding 1 below — still true, and still the reason a
> third plane is expensive), and the "chain multiple `connectivity[]`
> entries under one shared net name whenever two wired segments share an
> endpoint pin" rule (finding 2 below), which `layout/xor2/`'s five-leg
> `vdd` and four-leg `vss` chains depend on. The "friction candidate, not
> yet filed" note below was also **not** filed, and this increment did not
> find new grounds to file it: with 12 net legs rather than 31, the
> conflict diagnostics were never ambiguous.

**Placement-only proof of concept for `xor2`** — `design/ro_array_core.spice`'s
combining-tree XOR gate, the last leaf cell issue #27 step 2 names as not yet
attempted (`ro_buf`/`ro_stage`/`ro_nand2` are all DRC-clean *and* LVS-clean;
see `layout/README.md`). This directory proves the **floorplan** half of that
work — all twelve real devices placed, individually well-strapped, DRC-clean
— and documents, with concrete evidence, why the **routing** half is a
materially harder problem than any gate composed so far, so the next attempt
does not have to re-derive the same ground.

Mirrors `layout/well-strap-poc/`'s own convention: a named, honestly-scoped
proof of concept that establishes one technique and stops, rather than a
claimed-complete cell. **This is not a DRC/LVS-clean gate** — see "What this
does NOT establish" below.

## Why `xor2` is harder than `ro_nand2`

`design/ro_array_core.spice`'s `.subckt xor2 a b y vdd vss` is twelve
devices — double `ro_nand2`'s six — built from two inverters (`a`->`an`,
`b`->`bn`, the same `ro_buf` shape) feeding a classic static-CMOS XOR/XNOR
network: a PMOS pull-up tree (`Mp1`/`Mp2` in parallel from `vdd` to `mid`,
`Mp3`/`Mp4` in parallel from `mid` to `y`, gated `a`/`b`/`an`/`bn`
respectively) and an NMOS pull-down tree (two series pairs, `Mn1`-`Mn2` and
`Mn3`-`Mn4`, both spanning `y` to `vss`, gated by the same four signals). All
six PMOS device widths (`0.84`/`1.68 µm`) and all six NMOS widths
(`0.42`/`0.84 µm`) already exist as proven `layout/primitives/` geometries —
no new device sizes are needed.

The hard part is **not** a new composition technique (`layout/README.md`
already called this: "a bigger single-pass floorplan, not a new composition
technique") — it is that four signals (`a`, `b`, `an`, `bn`) each fan out to
*two* physically separate gate destinations (one on the NMOS pull-down row,
one on the PMOS pull-up row), and those eight destinations interleave in `x`
across the same shared cluster `mid`/`y` also needs to route through
monotonically. This is a real multi-net **channel-routing** problem — the
kind real standard-cell libraries solve with 2-3 metal levels of *internal*
routing for exactly this class of gate — not a floorplan mistake a smarter
single placement dodges.

## What's proven here: the floorplan, DRC-clean

`compose.request.json` places all seventeen blocks (twelve `mos_array`
devices, one `guard_ring` per PMOS device to strap its own well, one shared
`guard_ring` for the NMOS substrate tap) with **zero merged multi-device
wells** — a deliberate departure from `ro_stage`/`ro_nand2`'s row-abutment
technique, chosen *because* every prior 3+-device merged row
(`layout/ro_nand2/README.md`'s `py`/`y` nets) needed the two-pass
promote-and-resolve-on-metal2 technique to route a single net whose pins sat
on that merged blob, and `xor2`'s much bigger fan-out would multiply that
same problem across many more nets. Giving every PMOS device (`mpia`,
`mpib`, `mp1`, `mp2`, `mp3`, `mp4`) its own individual tap
(`well-strap-poc`/`ro_buf`'s 0.10 µm bbox-overlap merge, one device + one
tap each, never three-in-a-row) keeps every net's *placement* interaction
pairwise instead of many-to-one-blob — proven by result: **`klt drc --deck
sky130` reports 0 violations** on this seventeen-block placement (`drc.json`),
and **`klt extract` reports exactly 12 devices, 6 nfet + 6 pfet**
(`extract.json`) — precisely `.subckt xor2`'s own device count and class
breakdown, at the design's real sizes. The NMOS substrate tap
(`psub_tap`) is the same single-shared-tap pattern `ro_stage`/`ro_nand2` use
(NMOS bulk is sky130's one global `vsubs` plane; no per-device NMOS strap is
needed, matching `well-strap-poc`'s own finding that an unstrapped NMOS body
is a non-blocking `klt lvs` warning, not a match/mismatch verdict change).

Reproduce:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
cd layout/xor2-placement-poc
klt gen-compose compose.request.json --format json   # -> compose.response.json (bbox, 41 bare pins)
klt drc xor2core.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract xor2core.gds --deck sky130 --format json  # -> 12 devices (6 nfet, 6 pfet), 41 nets
```

`compose.request.json` references every block's own `gen/<id>.gen.json` (the
`klt gen mos_array`/`klt gen guard_ring` response for that block, committed
alongside its `.gds`) — the same evidence-trail convention every other
`layout/` cell uses, so this placement is independently regenerable from
scratch, not just re-checkable from the committed GDS.

`connectivity` is empty and every device pin is a bare promoted `pins[]`
entry (41 of them, `<id>_<port>` named) rather than wired — this composes
placement only, deliberately, so a reader can inspect exactly which
`(block, port)` pair is `xor2`'s own `Mp1.G`/`Mn12.S0`/etc. via
`compose.response.json`'s `ports[]` list (absolute, post-orientation
coordinates — see next section) without also debugging routing at the same
time.

## What's NOT proven here: routing, and the specific failure evidence

No `connectivity[]` was successfully composed — `lvs.json` does not exist in
this directory, and `xor2core.gds` carries **no `met1`/`metal2` geometry at
all**, only the twelve devices' and seven taps' own `li1` pads (confirmed by
`drc.json`'s own `coverage.rules_skipped` list including `met1.space.1` —
DRC skips a rule with nothing on that layer to check). Two concrete,
reproducible obstacles, recorded so the next attempt does not rediscover
them by trial and error:

### 1. `klt` 0.4.0 has three routing planes, not two — `layout/README.md`'s own account is incomplete

`layout/README.md`'s "Two-pass composition" section documents `"metal"`
(li1) and `"metal2"` (met1, via `via1`) as the composition-side routing
roles `ro_stage`/`ro_nand2` use. The currently-installed `klt`
(`klt version` -> `0.4.0`, `git_commit 34548dc1353cc6ff71e89ed2a91db7f6902b4b27`)
also resolves **`"metal3"`** (met2, via `via2`) — confirmed by reading
`klayout_tools.gen._PDK_ROLE_LAYERS["sky130"]` directly in the installed
package (`~/.local/share/uv/tools/klayout-tools/lib/python3.12/site-packages/klayout_tools/gen.py`),
not from documentation, since the CLI's own `--help` text and
`docs/cli/gen-compose.md` in this checkout do not enumerate the full role
table. **The catch, load-bearing for any future attempt**: `"metal3"`'s
via-drop is single-hop only (`gen_compose.py`'s own docstring: "`metal3`
only reaches a pin already on `metal2`... a pin still on the base `metal`
role (li1, two hops away) is not reachable from a `metal3` backbone"). A
third routing stage is therefore only useful for nets whose *both* endpoints
were already wired on `metal2` by an earlier stage — it cannot bridge two
bare `li1` pins directly the way `metal2` can. Not filed as a
`klayout-tools` tool gap: this is a real, intentional, documented
capability with a real constraint, not a defect.

### 2. Four fan-out signals crossing a shared `mid`/`y` cluster is a genuine multi-net channel-routing problem

Concrete reproduction: composing `a`/`b`/`an`/`bn`'s full reach (each to its
own NMOS-row gate *and* PMOS-row gate, per the port table in
`compose.response.json`) alongside `mid`/`y`/`vdd`/`vss` on a single
`"metal2"` stage, using axis-aligned waypoint lanes (including deliberately
generous >=2 µm separated "basement" lanes below `y=0` and "attic" lanes
above `y=15.7`, mirroring `ro_nand2`'s own empirically-tuned-waypoint
technique), converged partially (20/31, then plateaued around 18-20/31
nets routed across several iterations) but never reached all 31. The
`klt gen-compose` response's own per-leg `reason` field was concrete and
actionable every time (`"crosses already-routed net '<name>'"` or `"comes
within 0.14um of already-routed net '<name>' -- closer than ... met1.space.1"`)
— this is a real strength of the tool's diagnostics, not a gap — but fixing
one reported conflict routinely surfaced a *different* one on the next net
in commit order, the classic symptom of a routing-congestion problem that
needs full channel-router-style joint net ordering rather than one-leg-at-a-
time patching. One genuine, reproducible bug this session's own mistake
surfaced and fixed along the way: naming a local join (e.g. `mpia.G`-`mnia.G`)
and its onward external reach (`mnia.G`-`mn12.G0`) as two *different* net
names, even though both touch the same physical pin, causes a same-point
via-drop conflict between the two nets — chaining multiple `connectivity[]`
entries under **one shared net name** (as `ro_nand2`'s own `py`/`y` legs
already do) is required, not optional, whenever two wired segments share an
endpoint pin.

### A `klayout-tools` friction candidate, not yet filed

`klt gen-compose`'s own conflict diagnostics name the offending
already-routed net but not *where* the conflict occurs (no coordinate,
bbox, or offending-segment reference) — for a request with many nets this
makes it hard to distinguish "these two nets are nowhere near each other by
my own coordinate math, so something else is going on" (this session's own
repeated experience) from a genuine geometry mistake. Whether this rises to
a fileable generic tool gap (a conflict diagnostic that includes the
colliding segment's own endpoints/bbox) is left to whoever next works this
problem with more of the underlying geometry directly inspectable (e.g. via
`klt render`) to corroborate before filing — this session did not have
enough independent confirmation to distinguish "the diagnostic under-
reports" from "this session's own mental model of the waypoint geometry was
wrong" (the `a_join`/`mnia_g` bug above shows real cases of the latter).

## The port table (reusable — do not re-derive)

`compose.response.json`'s `ports[]` list is the authoritative, empirically-
confirmed (not hand-computed) absolute position of all 41 promoted pins
post-placement, e.g. `mp1_g` (`Mp1`'s gate) at `x=16.545, y=13.29`, `mid`'s
four participants `mp1_d`/`mp2_d`/`mp3_s`/`mp4_s` all at `y=11.84`, `y`'s
four participants `mp3_d`/`mp4_d`/`mn34_s0`(`Mn3.D`)/`mn12_s0`(`Mn1.D`).
Whoever attempts routing next should read ports directly from this response
rather than re-deriving them from `klt gen`'s per-block local-frame reports
and the orientation transforms (`none`: `final = origin + local`;
`mirror_y`: `final = (origin.x + local.x, origin.y - local.y)`;
`rotate_180`: `final = (origin.x - local.x, origin.y - local.y)` — also
confirmed empirically this session, not documented anywhere in `klt`'s own
CLI docs, and worth folding into `layout/README.md` proper if a future
increment leans on them again).

## Suggested next steps (not attempted here)

1. **Reorder the physical cluster, or accept `mid`/`y` don't need
   monotonic adjacency the way this session assumed.** `mid`
   (`Mp1.D`-`Mp2.D`-`Mp3.S`-`Mp4.S`) and `y`
   (`Mp3.D`-`Mp4.D`-`Mn1.D`-`Mn3.D`) both only need *some* spanning-tree
   connectivity, not a left-to-right chain — a star topology from one
   central point per net may leave more routing freedom than the chain this
   session used.
2. **Lift `b`/`bn`'s destinations to `metal2` early, then bridge the
   genuinely-crossing pair via `metal3`** (see finding 1 above) — `a`/`an`
   (from `inv_a`) and `b`/`bn` (from `inv_b`) are the two origin groups whose
   fan-out intervals mathematically cross (verified: `a=[0.5,16.5]`,
   `b=[8.5,22.5]` interleave, neither nests in the other) — a real quantity,
   not a placement artifact, so one of the two groups needs the third layer.
3. Budget substantially more empirical `gen-compose` iterations than
   `ro_nand2` needed (six same-block self-nets in one final call) — `xor2`'s
   ~14 external-reach legs plus `mid`/`y`/`vdd`/`vss` is over double that
   count, interacting pairwise.

Tracked in issue #27 (step 2's `xor2` item) — **now closed by
[`layout/xor2/`](../xor2/README.md)**, which took none of the three
suggested next steps above: it did not reorder this cluster (it replaced the
cluster), did not need a `metal3` bridge, and needed *fewer* `gen-compose`
iterations than `ro_nand2`, not "substantially more" (two stages, one
DRC-driven port move).
