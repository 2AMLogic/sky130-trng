# layout/xor2

**The combining-tree XOR gate, composed DRC-clean and LVS-clean** —
`design/ro_array_core.spice`'s `.subckt xor2`, the last leaf cell issue #27
step 2 named as not yet attempted, and the one blocking `ro_array_core`
assembly. Twelve devices, ten nets: two inverters (`a`->`an`, `b`->`bn`)
feeding a static-CMOS XOR network — a PMOS pull-up tree (`Mp1`/`Mp2` in
parallel from `vdd` to `mid`, `Mp3`/`Mp4` in parallel from `mid` to `y`) and
an NMOS pull-down tree (two series pairs `Mn1`-`Mn2` and `Mn3`-`Mn4`, both
spanning `y` to `vss`).

This supersedes [`layout/xor2-placement-poc/`](../xor2-placement-poc/README.md),
which proved the device count DRC-clean but left routing open and predicted
it would need "full channel-router-style joint net ordering" and plausibly
`klt`'s third routing plane. **It needed neither.** See "Why the PoC's
prediction did not hold" below — the three structural moves that turned a
17-block / 31-net single-plane routing problem into a 9-block / 12-net
two-stage one are the reusable finding here, not the coordinates.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
python3 layout/bin/compose-cell.py layout/xor2/cell.json            # rebuild in place
python3 layout/bin/compose-cell.py layout/xor2/cell.json --check    # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `core`, base metal/li1) | **13/13 net legs routed** (`vdd` x5, `mid`, `y` x3, `vss` x4), 12 endpoints promoted as bare pins | `core.compose.response.json` |
| `klt gen-compose` (final stage, metal2/met1 + via-drop) | **8/8 net legs routed** (`a`, `an`, `b`, `bn`, two legs each), 0 warnings | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **12 devices (6 nfet, 6 pfet), 10 nets** | `extract.json`, `xor2.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt xor2` | **match** — 12/12 devices, 10/10 nets, 0 mismatches, 0 errors | `lvs.json`, `xor2.ref.spice` |

Cell extent `23.97 x 17.585 µm` (`klt stats`: `x` -6.885..17.085, `y`
-1.5..16.085), 267 polygons. Generated on `klt 0.3.0+gc6dbf66c53c6` /
KLayout 0.30.12 against open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b`
— `layout/pdk.json`'s own pin.

`klt lvs` reports 8 layout pins against the reference's 5 and matches all
8 (`lvs.json`'s `counts.pins`, confirmed by `extract.json`'s own
`pin_count: 8`): stage `core` promotes 12 bare pins (the eight gate pads
and the four inverter signal ports) so the final stage can wire them, but
four of those labels merge onto nets that already carry another promoted
pin's label by final LVS, leaving 8 distinct net-level pins. The extracted
netlist's net names show this directly —
`a|inva_a|mn12_g0|mp13_g0` is `a`, `an|inva_y|mn34_g0|mp13_g1|y` is `an`
(the trailing `y` is `inv_a`'s *own internal* output label, which does **not**
merge with `xor2`'s `y`: they are separate nets in `extract.json`, which is
the check that this hierarchical placement did not create a label short).
`\$3` and `\$6` are `s1` and `s2`.

## Why the PoC's prediction did not hold

`layout/xor2-placement-poc/README.md` measured a real problem: with all
twelve devices placed individually and every net routed on one `metal2`
stage, `gen-compose` converged to 18-20 of 31 nets and plateaued. Three
structural moves remove that problem rather than solving it.

### 1. The pull-up tree is two *series chains*, not two parallel pairs

`XMp1 mid a vdd vdd` / `XMp3 y an mid vdd` is the chain
`vdd -[Mp1, g=a]- mid -[Mp3, g=an]- y`; `XMp2`/`XMp4` is the same chain
gated `b`/`bn`. Each chain is therefore **one** `mos_array` call with
`fingers: 2, finger_topology: "series"` (`klt` issue #777/#781), whose
reported ports are `U0_S0`/`U0_G0`/`U0_D0`/`U0_G1`/`U0_S1`. The pull-down
tree is already written as two series pairs in the schematic and gets the
same treatment. Eight devices collapse into **four blocks**, and with them
disappear four well taps and the six-pin `mid`/`y` bundles that made the
PoC's floorplan a many-to-one-blob problem.

**The interior S/D segment of a `series` unit is contactable, and this is
the first cell here to use that.** `ro_nand2`'s own `cell.json` comment
describes `U0_D0` as "the internal shared node ... left unconnected —
internal", which is correct for `ro_nand2` (its `nm` needs no wire) but
understates the port: `mid` is `mp13.U0_D0` **and** `mp24.U0_D0`, wired to
each other by a single 2-pin li1 route in the attic, and `klt lvs` matches
it against the reference's `mid` node. The pull-down tree's two interior
nodes (`s1`, `s2`) are the `ro_nand2` case and stay unwired — the reference
has them as internal 2-terminal nodes, so leaving them alone is what makes
the match, not an omission.

### 2. The two inverters *are* `ro_buf`

`XMpiA`/`XMniA` and `XMpiB`/`XMniB` are byte-for-byte
`.subckt ro_buf`'s device pair (pfet `0.84/0.15` + nfet `0.42/0.15`,
out/in/`vdd`/`vss`), so each inverter is placed as an already-composed
`blocks[].cell` — `ro_ring5`'s technique applied to a *leaf* gate rather
than to a ring. Four more devices and two more taps leave the flat problem.

Its two signal ports are hand-declared on `ro_buf`'s own internal li1
wires, and **their exit directions are the load-bearing part**:

- `a` at ro_buf-local `(0.545, 1.70)`, `direction_deg: 180` — on the
  vertical li1 leg joining `mp.U0_G` (local `y = 2.50`) to `mn.U0_G`
  (`y = 1.03`). It exits **west** because local `y = 1.70` is in the free
  band between `mn`'s bbox top (`1.24`) and `mp`'s bbox bottom (`2.14`),
  where everything at `x < -0.15` is clear of both devices and of both taps
  (`nwell_tap` starts at `y = 2.46`, `psub_tap` ends at `y = 1.13`).
- `y` at local `(1.90, 1.20)`, `direction_deg: 0` — on the `x = 1.90` leg of
  `ro_buf`'s own `y` route, which lies entirely east of both device bboxes
  (`mn` `x1 = 1.09`, `mp` `x1 = 1.24`). It exits **east**.

A `ro_buf` placed with `orientation: "none"` therefore presents its input to
the west and its output to the east. That is why `inv_a` sits in the west
margin (feeding the `a`/`an` columns, which are the western ones) and
`inv_b` in the east margin (feeding `b`/`bn`): each inverter's *near*
signal leaves in the direction its destinations lie, and only the far one
has to detour.

**One measured DRC constraint this costs, worth carrying forward.**
`layout/README.md`'s point 8 already records that `gen-compose` draws a
fixed `0.42 µm` via landing pad regardless of the declared port width. The
same is true of a port hand-declared on a *composed cell's internal wire*,
and there the pad has the cell's own geometry to clear. `inv_b`'s `y` port
at local `y = 0.60` put that pad's bottom edge at `5.50 µm` global, `0.095 µm`
above `ro_buf`'s own `y`-route horizontal (top edge `5.405`) — a single
`li1.space.1` violation, on the pad's *own net*, which the curated deck
checks net-agnostically. Moving the port to local `y = 1.20` (pad bottom
`6.10`, clearance `0.695 µm`) is the whole fix. The rule of thumb: a port
declared on an internal wire needs `0.21 µm + li1.space.1` of clearance from
any perpendicular leg of that same wire, or else to overlap it outright.

`gen-compose` gave no warning about this — it reported the net routed, and
only `klt drc` on the composed stream found it, with coordinates that have
to be reverse-mapped onto the request by hand. A `blocks[].cell` block
appears to be modelled by its bbox plus its declared `ports[]` only, so
nothing *inside* the placed cell participates in the clearance check that
`gen-compose` already applies to route-vs-route conflicts. Filed
generically per this repo's friction protocol as
[klayout-tools#1520](https://github.com/2AMLogic/klayout-tools/issues/1520)
(described as a composer/placed-cell modelling boundary, with no reference
to this design).

### 3. Split the nets by *layer*, not by lane

The PoC routed everything on one `metal2` stage. This cell routes the four
supply/output nets on **li1** in stage `core` and the four gate nets on
**metal2 (met1)** in the final stage:

| Stage | Layer role | Nets | Where they live |
|---|---|---|---|
| `core` | `metal` (li1) | `vdd`, `mid`, `y`, `vss` | attic (`y = 15.0` for `vdd`, `14.4` for `mid`), one channel lane at `y = 4.6` and the top gap for `y`, basement (`y = 2.0`) for `vss` |
| final | `metal2` (met1) | `a`, `an`, `b`, `bn` | the channel, plus the met1 basement (`y = 1.0`) and met1 attic (`y = 16.0`) |

The two groups cross each other constantly and it costs nothing, because
they are on different layers. What is left is two much smaller
single-layer problems, each of which is planar by construction. No
`"metal3"` stage exists in this cell; met2 (`69/20`) carries no geometry at
all, which is why `drc.json`'s `coverage.rules_skipped` lists
`met2.space.1`/`met2.width.1` (and `met1.enclosing.via.1`, there being no
`via`/`68-44` geometry either).

## The column order, and why only two gate nets are long

`mp13` is `mirror_y` and `mp24` is `rotate_180`, so the PMOS row reads
`vdd, a, mid, an, y | y, bn, mid, b, vdd` west to east. That buys two
things at once: the two `y` pads face each other across the top gap (one
straight li1 route at `y = 13.0`, no waypoints), and the two `vdd` pads land
at the row's two outer ends, so `vdd` is one attic run whose only verticals
are outside `mid`'s span — the three attic nets nest rather than
interleave. The NMOS row has no equivalent freedom: an nfet's gates face up
only in `orientation: "none"`, and both `mirror_y` and `rotate_180` turn
them downward, so `mn34`/`mn12` must read `y, an, s2, bn, vss | y, a, s1, b,
vss`.

The resulting gate columns are:

| Net | top gate (`x`) | bottom gate (`x`) |
|---|---|---|
| `a` | 0.545 (`mp13.G0`) | 7.895 (`mn12.G0`) |
| `an` | 1.215 (`mp13.G1`) | 0.895 (`mn34.G0`) |
| `bn` | 7.695 (`mp24.G1`) | 1.565 (`mn34.G1`) |
| `b` | 8.365 (`mp24.G0`) | 8.565 (`mn12.G1`) |

`an` and `b` are adjacent local pairs (`0.895`/`1.215` and
`8.365`/`8.565`), each reachable from its own inverter with a two-leg route
that never leaves its end of the channel. Exactly two nets span the cell,
in opposite directions: `a` west-to-east and `bn` east-to-west. Those two
would cross anywhere in the channel, so they are given opposite *outsides*
— `a` drops through the west margin into the met1 basement (`y = 1.0`),
runs east under both rows, and climbs back into the channel through the
bottom gap at `x = 6.0`; `bn` leaves `inv_b` eastward, climbs the east
margin into the met1 attic (`y = 16.0`), runs west over both rows, and drops
back through the top gap at `x = 3.0`. They never share a region, so no
third routing plane and no joint net ordering are needed.

## Floorplan numbers

| Block | Generator / cell | Orientation | Origin (µm) | Role |
|---|---|---|---|---|
| `mp13` | `mos_array` pfet `1.68/0.15`, `fingers=2` series | `mirror_y` | `(0.0, 13.84)` | `Mp1`+`Mp3` |
| `mp24` | `mos_array` pfet `1.68/0.15`, `fingers=2` series | `rotate_180` | `(8.91, 13.84)` | `Mp2`+`Mp4` |
| `mn34` | `mos_array` nfet `0.84/0.15`, `fingers=2` series | `none` | `(0.35, 2.58)` | `Mn3`+`Mn4` |
| `mn12` | `mos_array` nfet `0.84/0.15`, `fingers=2` series | `none` | `(7.35, 2.58)` | `Mn1`+`Mn2` |
| `nwt1` | `guard_ring` `add_well=true` | `none` | `(-2.04, 12.08)` | `mp13`'s well strap |
| `nwt2` | `guard_ring` `add_well=true` | `none` | `(9.11, 12.08)` | `mp24`'s well strap |
| `pst` | `guard_ring` `add_well=false` | `none` | `(3.0, -1.5)` | `vsubs`->`vss` tap |
| `inv_a` | `cell` `../ro_buf/ro_buf.gds` | `none` | `(-3.985, 5.11)` | `MpiA`+`MniA` |
| `inv_b` | `cell` `../ro_buf/ro_buf.gds` | `none` | `(14.19, 5.11)` | `MpiB`+`MniB` |

Both well straps abut their device by the established `0.10 µm` bbox
overlap (`nwt1` east edge `-0.05` against `mp13` west edge `-0.15`; `nwt2`
west edge `8.96` against `mp24` east edge `9.06`), so each PMOS chain's
nwell merges with its own tap's — `gen-compose` warns about the `0.00 µm`
block spacing in all four directions, which is the intended merge and not a
DRC finding. The two merged nwells are `5.09 µm` apart
(`1.91` -> `7.00`), and `inv_a`/`inv_b`'s own nwells are `1.48 µm` below the
PMOS row's in `y`; every nwell rule in the deck ran (`nwell` is in
`coverage.deck_scope`, `64/20` in `layers_checked`) and reported nothing.

The row pitch is set by the two device rows' port geometry, not tuned:
`mp13` `mirror_y` at `y = 13.84` puts its S/D pads at `13.84 - 0.84 = 13.00`
and its gates at `13.84 - 2.29 = 11.55`; `mn34`/`mn12` at `y = 2.58` put
theirs at `2.58 + 0.42 = 3.00` and `2.58 + 1.45 = 4.03`. That leaves a
`6.95 µm` channel (`4.24` to `11.19`) — deep enough to hold both `ro_buf`
cells (`5.31 µm` tall, placed at `y ∈ [4.40, 9.71]`) *and* keep `a`'s
`y = 10.4` lane clear of both the cells below (`0.69 µm`) and the PMOS row
above (`0.79 µm`).

## What is and is not signed off

**Is:** the composed `xor2.gds` is DRC-clean under `klt`'s sky130 deck and
LVS-matches `design/ro_array_core.spice`'s own `.subckt xor2` device for
device (12/12) and net for net (10/10), at this design's real sizes, with
every step's request/response committed next to the stream and reproducible
from `cell.json` alone.

**Is not:**

- **Not sky130 sign-off DRC.** `klt`'s deck is a curated subset; read
  `drc.json`'s own `coverage` block (`deck_scope`, `layers_checked`,
  `layers_in_stream_without_rules`, `rules_skipped`) before quoting "DRC
  clean" without qualification. In particular `65/44` (`tap.drawing`, the
  well/substrate tie diffusion the three `guard_ring` blocks draw) and
  `67/5`/`68/5` (the li1 and met1 label layers) are in the stream with no
  rules of their own.
- **No post-layout simulation.** This cell has no `sim/` record and no entry
  in `layout/pex/`. `sim/xor-combining-bandwidth/` remains a *pre-layout*
  campaign; the post-layout equivalent is a separate deliverable with its
  own PVT-corner discipline, and half of one is worth less than none.
- **Not `ro_array_core`.** This unblocks the array assembly (all three
  `xor2` instances, four `ro_ring5` rings and four `ro_buf` buffers now
  exist as composed cells) but does not perform it. The array-level
  interconnect — inter-ring supply distribution, the combining tree's own
  routing, buffer fan-in — is still undrawn, so DR-0003 §8's decorrelation
  gap is unchanged by this increment.
- **`ad`/`as`/`pd`/`ps` are not decisive in this match.** As
  `layout/README.md`'s "The LVS match is width-sensitive" section records
  for the starve devices, `klt lvs`'s `subckt-call` converter compares
  `W`/`L`, device class and connectivity; `xor2`'s reference states its S/D
  areas as literals rather than expressions, but the verdict here rests on
  the same three things it does everywhere else in this directory.

## Files

| File | What it is |
|---|---|
| `cell.json` | the descriptor `layout/bin/compose-cell.py` drives; its `_comment` block carries the reasoning summary |
| `gen/*.gen.json`, `gen/*.gds` | per-block `klt gen` responses and streams (the seven generated blocks; `inv_a`/`inv_b` generate nothing — they place `../ro_buf/ro_buf.gds`) |
| `core.compose.request.json` / `core.compose.response.json` | stage `core` (li1): placement + `vdd`/`mid`/`y`/`vss`, and the 12 promoted bare pins with their absolute post-placement coordinates |
| `compose.request.json` / `compose.response.json` | the final stage (met1): `a`/`an`/`b`/`bn` |
| `core.gds` | stage `core`'s own composed stream (the final stage's single input block) |
| `xor2.gds` | the composed cell |
| `drc.json` | `klt drc --deck sky130` — clean, 0 violations, with its own coverage block |
| `extract.json`, `xor2.spice` | `klt extract --deck sky130` — 12 devices, 10 nets, and the layout-derived netlist |
| `lvs.request.json`, `lvs.json` | `klt lvs` — match, 12/12 devices, 10/10 nets |
| `xor2.ref.spice` | the generated reference netlist (`.subckt xor2` with `u` suffixes appended — see `compose-cell.py`'s docstring and klayout-tools#1492) |
