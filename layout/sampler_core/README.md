# layout/sampler_core

`sampler_core` is `design/sampler_core.spice`'s top-level subckt: one
`ro_array_core` instance (`xdut`) plus six `sampler_dff` instances (`xsb`,
`xsv`, `xsr1`-`xsr4`), wired together (`design/README.md`'s own line:
"`sampler_core`  the sampler, wired to the source"). This directory promotes
[`layout/sampler_core-placement-poc/`](../sampler_core-placement-poc/README.md)'s
own six-instance floorplan (unchanged: 55.66 µm pitch, the same `sb`/`sv`/
`sr1`-`sr4` instance order and naming, the same `y=0.0` origin for every
instance) into a real, `compose-cell.py --check`-reproducible cell recipe,
and — as of this increment — places the `ro_array_core` instance above it and
starts wiring the two together.

## Result (this increment: the `ro_array_core` instance, and the first two data nets, issue #27 step 3)

Three new stages on top of the `place`/`route_supplies`/`route_ctrl` stages
below (all three unchanged):

- **`place_array`** puts one `ro_array_core` instance —
  [`layout/ro_array_core/ro_array_core.gds`](../ro_array_core/README.md), the
  DRC-clean, **LVS-matching** entropy source — into the same cell as the six
  `sampler_dff` instances, at origin `(0.0, 23.635)`. This is the first time
  `design/sampler_core.spice`'s whole device population (`xdut` plus
  `xsb`/`xsv`/`xsr1`-`xsr4`, **264** devices) exists in one stream.
- **`data_m1`** (met1) draws the four short legs the channel haul needs at
  its ends: `sr1`'s and `sr4`'s own `d` pins climbed out of li1 up to a met1
  landing point at `y=6.0`, and `ro1`'s and `ro4`'s own already-drawn met1
  extended south out of the array's own bbox into the channel.
- **`route_data`** (met2) closes the two hauls across the channel — the
  first raw-tap-to-sampler connections this repo has ever drawn.

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stages `place`, `route_supplies`, `route_ctrl`) | DRC-clean, unchanged from the previous increments (`route_ctrl` is now non-final — its files are renamed `route_ctrl.compose.*`/`route_ctrl.gds`, the same convention the two stages before it already use) | `<stage>.compose.request.json`, `<stage>.compose.response.json`, `<stage>.gds` |
| `klt gen-compose` (stage `place_array`, declare-only, no routing) | placed, **0 unrouted nets** (there are none to route) | `place_array.compose.request.json`, `place_array.compose.response.json`, `place_array.gds` |
| `klt gen-compose` (stage `data_m1`, met1 — `"metal2"` role) | **4/4 routed**, first attempt | `data_m1.compose.*.json`, `data_m1.gds` |
| `klt gen-compose` (final stage `route_data`, met2 — `"metal3"` role) | **2/2 routed**, first attempt | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **264 devices** (132 sampler + 132 array — the whole schematic population), **157 nets** | `extract.json`, `sampler_core.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_core` | **mismatch, as expected and quantified** — 136/**264** devices, 94/152 nets. The reference is now the *complete* 264-device netlist for the first time (it read 176 before — see "The reference-generation gap, closed" below), so this mismatch is a real measure of what is still unwired, not an artefact | `lvs.json`, `sampler_core.ref.spice` |
| `data-path-scan.py` | **13/13 claims hold** — every lane this increment picked, and the electrical result it produced, re-derived from the committed streams | `data-path-scan.json` |

Cell extent (final GDS) `x0=-2.19 x1=328.77 y0=-3.585 y1=54.72` µm —
`330.96 x 58.305` µm, 8326 polygons, 22.3% density (`klt stats`). The x
extent is unchanged from every earlier increment: the array (217.07 µm wide)
fits entirely inside the sampler row's own 330.96 µm span, so the cell grew
in `y` only. Generated on `klt 0.3.0+gc6dbf66c53c6` against open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` — `layout/pdk.json`'s own pin.

## Why the array goes above the row, not below

The floorplan offset `(0.0, 23.635)` is derived, not chosen for looks. `x=0`
puts the array's own x-origin on `sb`'s; `y=23.635` puts the array's own bbox
bottom (local `y=-3.635`) at exactly `y=20.0`, leaving a **12.915 µm** empty
channel above the sampler row's own top edge (`y=7.085`) — about 25 lanes'
worth at this repo's 0.17 µm/0.23 µm wire/space, so the channel is not the
constraint on any later increment.

*Above* is forced by the **sampler** side. Every data net has to end on a
`sampler_dff`'s own `d` pin, which is an li1 pad at cell-local
`(6.665, 1.2)`, and sky130's `klt` routing roles stop at `"metal3"` (met2) —
so the only question is which single column of metal can reach that pad.
`data-path-scan.py` measures both directions in all six instances, on
`route_ctrl.gds` (the state before the array existed), over a 0.62 µm-wide
window:

| Direction | What is in the way | Legs needed |
|---|---|---|
| **Up** | met2 at `y=3.2` (the in-cell `m` lane) and `y=5.0` (`route_ctrl`'s own `rst_n` haul, drawn continuously from `x=27.0` to `x=305.3`, i.e. over five of the six columns); met1 only at `y=6.915..7.085`, the shared `vdd` rail | **two**: one met1 leg from the pad up to `y=6.0` (met1 is clear from `y=0.485` to `y=6.915` in every column, so it crosses both met2 obstacles for free), then one met2 leg over the `vdd` rail |
| **Down** | met1 at `y=0.4` (the in-cell `clkb` lane) *and* `y=-3.5` (the shared `vss` rail); met2 at `y=-1.7` (the shared `clk` lane) | **four**: neither a met1 leg nor a met2 leg gets out of the column at all (`met1_below_pin_clear` and `met2_below_pin_clear` are both false in all six), so it takes a met2/met1/met2 weave plus the pad via |

That asymmetry — one obstacle crossable by a layer change vs. three
interleaved on the only two layers available — is the whole argument, and it
is checked rather than asserted: `no_single_layer_leg_leaves_any_d_column_downward`.

## Two of five data nets, and the measured reason it is not five

`ro_array_core`'s four buffered ring taps are four met1 horizontals stacked
in the array's own local `y`: `ro1` at `8.0` (spanning `x` `-0.5..50.5`),
`ro2` at `8.5` (`20.5..105.8`), `ro3` at `9.0` (`28.47..161.1`), `ro4` at
`10.0` (`49.5..216.4`). Every one of them is an *interior* backbone: the
cell promotes `ro1`-`ro4`/`xo` as text labels but has no boundary pin
geometry for them at all, so a block-level haul has to leave from a point on
the net's own drawn metal and find its own way out.

`data-path-scan.py` scans **every** 0.05 µm column over each net's own run
for a met1 path from just under the run down past the array's own south
edge, and finds:

| Net | Free south columns (array-local x) | Why |
|---|---|---|
| `ro1` | `-0.5 .. -0.25` | its own west leg is already at the array's west boundary; nothing else is under it |
| `ro2` | **none** | every column of its run is crossed by `ro3`'s run at `y=9.0`, `ro4`'s at `y=10.0`, or both |
| `ro3` | **none** | every column of its run is crossed by `ro4`'s run at `y=10.0` |
| `ro4` | `215.3 .. 215.55` | east of `ro3`'s own run end (`161.1`) and clear of `buf4`'s own riser at `x=216.4` |

So `ro1` (tap at `(-0.5, 8.0)`) and `ro4` (tap at `(215.4, 10.0)`) are
exactly the two nets that can leave the array southward on their own layer,
and they are the two this increment routes. `ro2`, `ro3` and `xo` need a
layer change *inside* the array's own footprint before they can escape —
`ro2`/`ro3` to hop `ro4`'s met1 horizontal (met2 is blocked there too, by
the array's own `vss` met2 bus at local `y=10.59..11.01`, `x` `68.5..214.7`),
`xo` because it is an li1 pad at local `(66.375, 25.585)` and met2 is two
via hops from li1, which `klt gen-compose` will not do in one route (see
"Friction filed" below). That is a separable increment, not a harder version
of this one, and it is filed as such.

## What the two hauls actually are

Each is one 2-pin `connectivity[]` entry between two met1 landing points
`data_m1` drew, so `klt gen-compose` drops a met1↔met2 via at **both** ends
and the haul itself is pure met2 across the empty channel:

```
ro1: (-0.5, 17.0) --east--> (117.985, 17.0) --south--> (117.985, 6.0)
ro4: (215.4, 15.0) --east--> (284.965, 15.0) --south--> (284.965, 6.0)
```

`117.985` and `284.965` are `sr1`'s and `sr4`'s own `d` columns
(`origin_x + 6.665` at `origin_x` = `111.32` / `278.3`). The two lanes are
2.0 µm apart, both inside the channel, both above the sampler row's topmost
metal (`y=7.085`) and below the array's own bottom edge (`y=20.0`) — and the
scan confirms the channel band `y` `7.2..19.8` contains **nothing else**: no
li1 at all, exactly two met1 shapes (the two escape legs) and exactly two
met2 shapes (the two hauls).

## The electrical result, and one merge nobody drew

`klt extract` on `place_array.gds` (the placement before any inter-block
metal) reports **159** nets, not the 160 the two blocks' own standalone
counts (`96` for `ro_array_core`, `64` for the six-sampler bank) would
predict:

```
klt extract place_array.gds --deck sky130 --pdk sky130A   # 264 devices, 159 nets
```

The missing one is the array's `vss` and the sampler bank's `vss` arriving
as **one** net although no metal joins them. They share the p-substrate,
which sky130's extraction deck models as a real conductor. This is not `klt`
merging two same-named nets: `vdd` is labelled `vdd` on both sides too, has
no shared body, and stays two separate nets — `data-path-scan.py` asserts
both halves of that (`array_and_sampler_vss_are_one_net_via_the_substrate`,
`array_and_sampler_vdd_are_still_two_nets`). It is worth stating plainly
because it is easy to misread as "the supplies are already connected": they
are not. A metal `vss` strap between the two blocks is still owed, and so is
every bit of `vdd`.

The final cell's **157** nets are then `159 - 2`: exactly the two intended
merges and nothing else. The scan pins them by name *and* by position — the
`sr1_d_stub`/`sr4_d_stub` labels `gen-compose` drew sit in `sr1`'s and
`sr4`'s own `d` column respectively, so each connection lands on the intended
instance rather than merely on *an* instance — and confirms four `d` pins
remain unconnected (`sb`'s, `sv`'s, `sr2`'s, `sr3`'s).

## The reference-generation gap, closed

The previous increment recorded a `compose-cell.py` limitation (not a `klt`
gap) that had to be fixed before any real whole-cell LVS pass: the
`repoint_variant_instances` step, which rewrites a subckt's instance-call
lines to point at the renamed `ro_ring5_r1`..`_r4` copies, ran **only** on
the top subckt's own lines, never on a plain `dependencies[]` entry's body.
`ro_array_core` is exactly such an entry in this descriptor, so the generated
`sampler_core.ref.spice` called a bare, undefined `ro_ring5` on its
`xr1`-`xr4` lines. `klt lvs` does not error on that — it drops the
unresolvable instances — so the only symptom was a reference device count
quietly short by those four rings' 88 devices: **176** where the schematic
has **264**.

That is now fixed. The reference assembly moved into its own function,
`build_lvs_reference`, which puts **every** emitted body through the same
repoint pass, and `layout/test_compose_cell.py` gained
`check_lvs_reference_repoints_dependency_bodies_too`, which asserts on a
`sampler_core`-shaped input that no call anywhere names the bare `ro_ring5`
and that every subckt a card calls is actually defined. `sampler_core.ref.spice`
now carries all 264 devices, and `klt lvs`'s reported reference count says so.
No other cell's committed evidence moved: `compose-cell.py --check` still
reproduces every one of them byte-for-byte on the verdict-bearing fields.

## Friction filed

One real `klt gen-compose` capability gap, and one documentation defect,
are filed generically against `2AMLogic/klayout-tools` per this repo's
`CLAUDE.md` friction protocol:

- **No multi-level via drop** (`klayout-tools#1567`). A route on the third
  metal role cannot land
  on a base-`"metal"`-role pad: `gen_compose`'s via-drop resolves exactly
  one hop, and rejects anything further apart. The caller has to hand-build
  a per-level ladder stage instead. That is why `xo` — an li1 pad at array-
  local `(66.375, 25.585)` — is not routed here while `ro1`/`ro4` (already
  on met1) are.
- **A stale docstring about orientation** (`klayout-tools#1568`).
  `gen_compose`'s module docstring
  states that `"explicit"` placement "supports no orientation (rotation)".
  It does: the request validator accepts `mirror_x`, `mirror_y` and
  `rotate_180`, and a mirrored `blocks[].cell` places correctly (verified
  directly on `layout/xor2/xor2.gds`). Believing the docstring cost this
  increment a floorplan detour.

For the record, since the corrected fact invites the question: mirroring the
array would **not** have rescued `ro2`/`ro3`. They are fenced in by `ro3`'s
and `ro4`'s own horizontals, which lie between them and the array's edge in
*both* directions — the scan above finds no free column over their runs
going north either, so no rigid-body transform of the array exposes one.

## A previous increment: `clk`/`rst_n` fan-out (issue #27 step 2)

On top of the `place`/`route_supplies` stages below (unchanged), a third
stage, `route_ctrl`, routes the shared `clk` fan-out and shared `rst_n`
fan-out across all six instances — the item flagged as likely the hardest
remaining step, by analogy with `layout/sampler_dff/README.md`'s own
single-cell `clk` fan-out derivation (a five-pin bundle net *inside* one
cell). At this scope `clk`/`rst_n` are each already a single, already-routed
net inside every `sampler_dff` instance (`layout/sampler_dff/cell.json`'s
own `clk_met1`/`clk_bus` and `rst_n_met1`/`rst_n_bus` stages), each carrying
its own correctly-spelled net-name text label as a side effect of that
routing (confirmed directly against `layout/sampler_dff/sampler_dff.gds`
with `klayout.db`: layer `69/20` — met2, `"metal3"` role — text labels
`clk` at local `(3.662, -1.7)` and `rst_n` at local `(27.645, 2.2)`), so this
stage's own job is the *same* chain-of-six technique `route_supplies` already
used for `vdd`/`vss`, not a fresh six-pin-bundle derivation.

That increment's own verdicts, as recorded at the time: `klt gen-compose`
routed `clk` clean on the **first** attempt (five straight legs at
`y=-1.7`), while `rst_n`'s first attempt (a straight leg at `y=2.2`,
mirroring `clk`'s recipe) failed all five legs — see "The `rst_n`
correction" below — and was fixed by climbing to an empty band at `y=5.0`
for the cross-instance haul; `klt drc --deck sky130` clean, 0 violations;
`klt extract --deck sky130` 132 devices, **64** nets (down from the
`vdd`/`vss` increment's 74: `clk`/`rst_n` each merge from six separate
per-instance nets into one, saving 5 apiece); `klt lvs` a mismatch, as
expected at that scope, with no `ro_array_core` instance placed yet. The
cell extent was then `x0=-2.19 x1=328.77 y0=-3.585 y1=7.085` µm; the
`route_ctrl` stage's own stream is still committed, now as
`route_ctrl.gds`/`route_ctrl.compose.*.json`, and
`data-path-scan.py`'s "from above vs. from below" measurement above reads
that stream rather than the final one precisely because it is the state
before the array existed.

## The `rst_n` correction: a same-height haul is not safe outside its own span

`clk`'s own in-cell lane (`y=-1.7`) already spans the *entire* local width
of every instance (`layout/sampler_dff/README.md`'s own `clk_bus`
derivation: "below every leaf's own drawn geometry ... The lane spans
`x 0.545..49.03`"), so a straight cross-instance leg at that same height
never crosses anything else — confirmed empirically: all five `clk` legs
routed clean on the first attempt, using a shared local anchor `x=25.0`
(inside `clk`'s own `0.46..49.115` span).

`rst_n` is not that simple. Its own in-cell bus (`rst_n_bus`, `y=2.2`) spans
only local `x 12.215..43.075` **by design** — clear of `clk`'s own verticals
*only inside that window* (`rst_n_bus`'s own `_comment`: `clk`'s two
`ctrlb` drops at `x=24.6`/`29.74` stop at `y=1.03`/`1.24`, well below
`rst_n`'s own `y=1.975` lower edge). Outside that window `clk` has two
*other* verticals (`tg_d.ctrl` at local `(5.31, 2.5)`, `tg_fbs.ctrl` at
local `(49.03, 2.5)`) that reach well above `rst_n`'s own height. The first
attempt reused `clk`'s own anchor `x=25.0` for `rst_n` too (for a uniform
anchor across both nets) and failed all five legs:

```
self-net's drawn 0.17um metal overlaps 0.1734um^2 of block 'core''s own
drawn pad metal on the route layer (ports 'sb_clk', 'sv_clk') -- bussing
this net across the block would draw a silent short to that pad ...
```

Not a collision at the port itself (`x=25.0` is mid-span and clear at
`y=2.2` in isolation) — the *straight haul* from that port all the way to
the block's own edge (needed to reach the next instance) crosses local
`x 43.9..49.1`, where `clk`'s own `tg_fbs.ctrl` riser lives, confirmed
directly with `klayout.db`: a `y=2.15..2.25` band slice across the whole
cell width finds real met2 at local `x` `4.38-4.55`, `5.225-5.395`,
`43.915-44.085`, `44.815-44.985`, `47.93-48.1` and `48.945-49.115` — none of
them `rst_n`'s own bus (`12.005-43.285`), every one a *different* net's own
narrow vertical (`clk`'s `tg_fbs.ctrl` riser among them), invisible to a
naive "is the anchor `x` inside `rst_n`'s own labelled span" check.

**Fix**: route `rst_n`'s cross-instance haul on a completely empty met2 lane
instead of reusing `y=2.2` outside `rst_n_bus`'s own span. A `klayout.db`
band scan (thin y-slices, full local `x -3..52`) found local `y=3.4..6.9`
entirely free of met2 in every one of the six identical instances — nothing
this repo has ever drawn there (`vdd`'s own rail starts at `y=6.915`;
everything else — `clk`, `rst_n`, `q`/`qb`/`s`/`mc`/`mb`, the leaf gates'
own `vdd`/`ctrl` pads — tops out at or below `y=2.795`). Also confirmed at
the chosen anchor column specifically (local `x=27.0`, inside `rst_n`'s own
`12.215..43.075` span and clear of both `ctrlb` drops at `24.6`/`29.74`):
met2 there is only `rst_n`'s own lane (`y 2.115..2.285`) and `clk`'s own
basement lane (`y -1.785..-1.615`) — nothing between `2.285` and `7.1`. Each
leg now climbs (same layer, still no via) from `(27.0, 2.2)` straight up to
`(27.0, 5.0)`, runs the whole inter-instance haul at `y=5.0`, and drops back
down to `(27.0, 2.2)` at the next instance — an explicit four-point
`waypoints_um` U-shape per leg, the same recipe `rst_n_bus`'s own in-cell
stage already used at a smaller scale (`[[x1,y1],[x1,y2],[x2,y2],[x2,y1]]`),
just one plane "higher" in `y` rather than crossing a plane in layer. `clk`
needed no such detour and keeps its own single straight-line legs at
`y=-1.7` unchanged.

## Where the `clk`/`rst_n` ports land

Global `x` per instance: `clk` = `origin_x + 25.0` (`sb=25.0`, `sv=80.66`,
`sr1=136.32`, `sr2=191.98`, `sr3=247.64`, `sr4=303.3`); `rst_n` =
`origin_x + 27.0` (`sb=27.0`, `sv=82.66`, `sr1=138.32`, `sr2=193.98`,
`sr3=249.64`, `sr4=305.3`) — the same offset arithmetic `route_supplies`
already used for `vdd`/`vss` at `x=0.0`. Ten two-pin `connectivity[]`
entries (five legs each), not a single six-pin bundle net with
`connectivity[].legs[]`, for the same portability reason `route_supplies`'s
own `_comment` already gives (`klayout-tools#1548`: an unrecognized
`legs[]` field is silently dropped rather than rejected on some installed
`klt` builds encountered in this repo's history).

## Where the `vdd`/`vss` ports land

Unlike every earlier `route_supplies`-shaped stage in this repo
(`layout/sampler_dff/cell.json`'s own `route_supplies`,
`layout/ro_array_core/cell.json`'s `vddstub`/`vssstub`), which via-drop a
**li1 gate pad** up to met1/met2 because that is where a *leaf* cell's own
promoted rail port sits, `layout/sampler_dff/sampler_dff.gds` is not a leaf
— it is already a fully-routed, multi-stage assembly whose own `vdd`/`vss`
rails are drawn directly on **met1** (layer `68/20`, the `"metal2"` role),
the product of its own `route_supplies` stage (PR #78). Measured directly
against the composed `sampler_dff.gds` with `klayout.db`
(`begin_shapes_rec` over layer `68/20`, filtering for shapes reaching the
attic/basement height band):

- `vdd` (attic): one continuous merged region at `y=6.915..7.085` (0.17 µm
  wide, centred on `y=7.0`) spanning local `x=-1.205..49.115`.
- `vss` (basement): the same shape at `y=-3.585..-3.415` (centred on
  `y=-3.5`) spanning local `x=-1.305..49.115`.

Both spans comfortably contain `x=0.0`, so every one of the six instances
declares its own `vdd`/`vss` port at the identical local `(0.0, 7.0)`/
`(0.0, -3.5)`, layer `68/20` (met1, `"metal2"` role), width `0.17` — an
**interior point on an already-drawn rail**, not an edge pin, the same
"land directly on the target net's own metal, no via needed" technique
`layout/sampler_dff/cell.json`'s own `m_met1`/`final` stages used for their
`tg_fbm_b_alt` anchor. Declaring the routing role (`"metal2"`) equal to the
port's own already-drawn layer means `gen-compose` draws the new wire
directly on met1 with no via-drop at all — confirmed by the unchanged cell
bbox (a via would need `_VIA_LANDING_SIZE_UM`-sized pad geometry that could,
in principle, push the bbox; it does not, because none is drawn).

## Two-pin chain, not one six-pin bundle

`route_supplies`'s `connectivity[]` is ten two-pin entries (five for `vdd`,
five for `vss`, chaining `sb`→`sv`→`sr1`→`sr2`→`sr3`→`sr4`), each with an
explicit `waypoints_um` bridging the ~5.34 µm gap between adjacent
instances' own rail spans at the shared bus height — not a single six-pin
bundle net with `connectivity[].legs[]`. This mirrors
`layout/sampler_dff/cell.json`'s own `route_supplies` stage precisely, for
the same reason recorded there: this repo has already found more than one
installed `klt` build that silently drops an unrecognized `legs[]` field
rather than rejecting it (`klayout-tools#1548`), so the portable, always-
supported per-leg `connectivity[]` shape is used regardless of which build
is running an increment.

## The reference-generation gap, as it was found (now closed — see above)

Wiring up this cell's `lvs` block (`dependencies: ["sampler_dff",
"ro_array_core", "ro_buf", "xor2"]` plus a `dependency_variants` entry for
`ro_ring5`'s four `wstv` sizings, copied from
`layout/ro_array_core/cell.json`'s own already-working block) surfaced a
real `compose-cell.py` limitation, not a `klt` tool gap: `compose_cell`'s
`repoint_variant_instances` call — the step that rewrites a top subckt's own
instance-call lines to point at the renamed `ro_ring5_r1`..`_r4` copies — is
applied **only** to `lvs.subckt`'s own extracted lines (`top_lines`), never
to a plain `dependencies[]` entry's own body. `ro_array_core` is exactly
such an entry *in this descriptor* (it is `sampler_core`'s dependency here,
not its own top subckt, unlike in `layout/ro_array_core/cell.json` where it
*is* the top subckt and gets repointed correctly) — so the generated
`sampler_core.ref.spice`'s own copy of `ro_array_core`'s body still calls
the bare, undefined `ro_ring5` on its `xr1`-`xr4` instance lines, even
though the file only defines the renamed `ro_ring5_r1`..`_r4`. Confirmed
directly: `grep -n "^\.subckt\|ro_ring5\b" sampler_core.ref.spice` shows
`ro_ring5` (bare) only on instance-call lines, never as a `.subckt` header.

`klt lvs` does **not** error on this — it silently drops the four
unresolvable ring instances rather than failing the run, which is why this
stays a mismatch-against-an-incomplete-reference rather than a crash. The
reported reference device count (176) is exactly consistent with that. Per
`design/sampler_core.spice`'s own device cards: `ro_ring5` is `1 x
ro_nand2` (6 devices) `+ 4 x ro_stage` (4 devices each `= 16`) `= 22`
devices; `ro_array_core` is `4 x ro_ring5` (`88`) `+ 4 x ro_buf` (2 each,
`8`) `+ 3 x xor2` (12 each, `36`) `= 132` devices (matching every other
place this repo already reports `ro_array_core`'s own device count); the
full, correctly-resolved `sampler_core` reference would be `6 x
sampler_dff` (22 each, `132`) `+ ro_array_core` (`132`) `= 264` devices.
This increment's own `sampler_core.ref.spice` is short by exactly the four
dropped `ro_ring5` instances' own `88` devices: `264 - 88 = 176`, matching
`lvs.json`'s reported reference count precisely.

That is exactly what this increment fixed, and the fix is the one named
here: `repoint_variant_instances` is now applied to every `dependencies[]`
entry's own body, not just the top subckt's — see "The reference-generation
gap, closed" above for the shape of the fix and the unit test that pins it.
The paragraphs above are kept because the arithmetic in them is the reason
the *current* reference count (264) is known to be the right one.

## What remains (issue #22 / #27)

In rough dependency order:

1. ~~**`vdd`/`vss` shared bus**~~ — **routed** (PR #103).
2. ~~**`clk`/`rst_n` shared fan-out** across all six instances~~ —
   **routed** (PR #104).
3. ~~**Placing a `ro_array_core` instance**~~ — **placed** (this increment,
   stage `place_array`), and two of its five data nets (`ro1`→`sr1.d`,
   `ro4`→`sr4.d`) routed.
4. **The remaining three data nets** — `xo`→`sb.d`, `ro2`→`sr2.d`,
   `ro3`→`sr3.d`. Each needs a layer change *inside* the array's own
   footprint before it can escape, which the two routed here did not: see
   "Two of five data nets, and the measured reason it is not five" above for
   the per-net measurement. `sv`'s own `d` is a fourth, different job — the
   schematic ties it to `vdd`, not to the array.
5. **The inter-block supply straps.** `vdd` is two separate nets today (the
   array's and the sampler bank's); `vss` extracts as one only through the
   shared p-substrate, which is not a supply connection. Both need real
   metal.
6. **Promoting the top-level pins** — the six `d`/`q` pin pairs (`sb`'s
   `raw_bit`, `sv`'s `raw_valid`, `sr1`-`sr4`'s `ring_bit1`-`ring_bit4`)
   plus `en1`-`en4`/`vddr1`-`vddr4` (from the placed `ro_array_core`) and
   `vdd`/`vss` themselves, all real top-level pins of
   `design/sampler_core.spice`'s own `.subckt sampler_core`.
7. **Whole-cell `klt lvs` match** against `design/sampler_core.spice`'s real
   `.subckt sampler_core`. The reference side of that is now ready (264
   devices, complete — see "The reference-generation gap, closed" above);
   the layout side needs items 4-6 first. Today: 136/264 devices,
   94/152 nets.
8. **Post-layout PVT simulation** of the fully assembled, LVS-clean
   `sampler_core` — the whole-chain (raw-tap-to-sampled-bit) claim issue #22
   was originally filed for, still open. Nothing under `sim/` is added by
   this increment, deliberately: extracting parasitics from a cell whose
   three remaining data nets are unrouted would produce numbers about a
   circuit that is not the schematic.
9. DR-0003 §8's `wstv` inter-ring decorrelation gap is **unaffected** by any
   of the above — it is about the entropy source's own inter-ring supply
   coupling (already re-evaluated at array scope by DR-0005/DR-0006), not
   the sampler side of the raw tap.

Two `2AMLogic/klayout-tools` items *were* filed by this increment (no
multi-level via drop; a docstring that denies a capability the tool has) —
see "Friction filed" above. The `pins[]`/`connectivity[]` exclusivity rule the
previous increment considered and dismissed is still not a gap, and the
reference-generation limitation it recorded was this repo's own
`compose-cell.py`, now fixed here.

## Files

| File | What it is |
|---|---|
| `cell.json` | the recipe: six stages plus the `lvs` block |
| `<stage>.compose.request.json` / `.response.json` / `.gds` | each non-final stage's own request, response and composed stream (`place`, `route_supplies`, `route_ctrl`, `place_array`, `data_m1`) |
| `compose.request.json` / `compose.response.json` | the final stage (`route_data`)'s own |
| `sampler_core.gds` | the composed cell |
| `drc.json`, `extract.json`, `sampler_core.spice` | sign-off + extracted netlist |
| `lvs.request.json`, `sampler_core.ref.spice`, `lvs.json` | the LVS run and its generated reference |
| `data-path-scan.py` / `.json` | the 13 geometric and electrical claims behind this increment, re-derivable and self-checking (exits non-zero if any stops holding) |
