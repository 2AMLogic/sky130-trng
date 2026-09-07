# layout/sampler_tg

**The first transmission gate composed under `layout/`, and the resolution
of `layout/README.md`'s "no generator surveyed yet" open question for the
sampler.**

`sampler_tg` is a plain sky130 transmission gate: one `sky130_fd_pr__pfet_01v8`
(0.84/0.15 µm) and one `sky130_fd_pr__nfet_01v8` (0.42/0.15 µm), drains tied
together (`a`), sources tied together (`b`), gated by two *independent*
control signals (`ctrl` on the PMOS gate, `ctrlb` on the NMOS gate — normally
a `clk`/`clkb` complementary pair) rather than the one shared gate net an
inverter's PMOS/NMOS pair uses. `design/xschem/sampler_dff.sch`'s four
transmission gates — `TG_D`, `TG_FBM`, `TG_S`, `TG_FBS` — are this exact
two-device shape, four times, at this exact sizing (`sampler_dff.sch`'s own
note: "Plain inverters are 0.84 um PMOS / 0.42 um NMOS", and the four TGs use
the same PMOS/NMOS pair sizing).

Composing this cell is the empirical answer to `layout/README.md`'s
`sampler_dff` line ("NOT STARTED — transmission-gate master-slave DFF, no
generator surveyed yet") and to issue #27's own scope item 5's parenthetical
("no `klt gen` generator was surveyed for this cell type; if genuinely
missing, file a *generic* tool-gap issue"): **no new `klt gen` generator, and
no `klayout-tools` tool gap, is needed.** `mos_array` (the same generator
`ro_buf`/`ro_stage`/`ro_nand2`/`xor2` already use) composes a transmission
gate exactly as it composes an inverter — the only difference is which pins
share a net.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
python3 layout/bin/compose-cell.py layout/sampler_tg/cell.json           # rebuild in place
python3 layout/bin/compose-cell.py layout/sampler_tg/cell.json --check   # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` | 2/2 nets routed (`a`, `b`) plus `ctrl`/`ctrlb`/`vdd`/`vss` promoted as bare pins | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 2 devices, 6 nets | `extract.json`, `sampler_tg.spice` |
| `klt lvs` vs. hand-authored `sampler_tg.source.spice`'s `.subckt sampler_tg` | **match** — 2/2 devices, 6/6 nets, 0 mismatches | `lvs.json`, `sampler_tg.ref.spice` |

Cell extent `-0.525..1.615 x -2.49..6.14` µm (bbox includes both body-tie
islands, parked north/south rather than west as `ro_buf`'s are — see
"Floorplan" below for why).

## Why this cell has no `design/*.spice` reference to point at

Every other leaf gate under `layout/` (`ro_buf`, `ro_stage`, `ro_nand2`,
`xor2`) LVS-checks against a real `.subckt` in `design/ro_array_core.spice`,
because `design/xschem/ro_array_core.sch` instantiates each of those as a
named sub-schematic symbol. `design/xschem/sampler_dff.sch` is flat — it
draws all 22 transistors directly, with no `sampler_tg`/`sampler_nand2`
sub-schematic symbol of its own (see that schematic's own header comment) —
so there is no independently netlisted `.subckt sampler_tg` anywhere in
`design/*.spice` for `compose-cell.py`'s `lvs.reference` to extract.

`layout/sampler_tg/sampler_tg.source.spice` is a **hand-authored** two-device
micro-reference, committed alongside this recipe, that exists solely to give
`compose-cell.py` a real `.subckt` to LVS against. It is not an xschem
export — it reproduces one representative TG instance's own device lines
(`XMtdp`/`XMtdn` from `design/sampler_core.spice`'s `sampler_dff` subckt)
byte-for-byte, down to the `ad`/`as`/`pd`/`ps`/`nrd`/`nrs` geometry terms, just
renamed to this cell's own port names (`a`/`b`/`ctrl`/`ctrlb`/`vdd`/`vss`).
The 2/2 device, 6/6 net match against it is real evidence that this GDS's
own two devices are wired the way the schematic's own TG devices are —
but the *authoritative* LVS check for the transmission-gate shape happens
once `sampler_dff` itself is assembled from four instances of this cell and
checked against `design/sampler_core.spice`'s real `.subckt sampler_dff`
(not yet attempted — see "What this does NOT establish").

## Floorplan

Same two-row stack every other leaf gate here uses (NMOS at the origin,
PMOS `mirror_y` directly above it, gates facing across the row gap) — but
with the two body-tie islands moved from `ro_buf`'s west side to **north of
the PMOS row and south of the NMOS row**, because an inverter and a
transmission gate route completely different pins to the west:

```
                    [ nwell_tap ]  overlaps mp's own nwell by 0.10um  y ~ 4.0 .. 6.14
                          |
   [ mp  (pfet 0.84/0.15, mirror_y) ]                                y ~ 2.14 .. 4.1
        S(W)  G(S)  D(E)
         |            |                          <- b (west lane, x=-0.3), a (east lane, x=1.9)
        S(W)  G(N)  D(E)
   [ mn  (nfet 0.42/0.15) ]                                          y ~ 0 .. 1.24
                          |
                    [ psub_tap ]  0.5um clear of mn's own bbox        y ~ -2.54 .. -0.4
```

- **`net a`** ties both DRAIN pins (both east-facing) — the identical D-D
  shape and the identical `x = 1.9` clearance lane `ro_buf`'s own `net y`
  already proves.
- **`net b`** ties both SOURCE pins (both west-facing) — new to this cell,
  since `ro_buf`'s two source pins go to two *different* nets (each device's
  own supply tap), never to each other. This is what forces the taps out of
  the west lane: `ro_buf` parks `nwell_tap`/`psub_tap` to the *west*
  specifically because that is where its `vdd`/`vss` nets need to land. A
  transmission gate's west lane is needed for `b` instead, so the taps move
  to **north of `mp`** and **south of `mn`**, each still reachable from their
  own device via the row's own natural vertical exit (no route needed at all
  — see "The taps carry no route" below).
- **First attempt, and why it failed.** The first version of this cell kept
  `ro_buf`'s exact tap placement (west, abutting `mp`/`mn` as `ro_buf` does)
  and tried a plain two-point vertical `net b` at `x = 0.1`. `klt gen-compose`
  rejected it: `backbone's 0.17um-wide drawn path crosses 0.825um through its
  own pin's block 'mp' -- more than that pin's own 0.445um edge margin`. The
  route was trying to reach `mp`'s west-facing source pin from the *north*
  (over the top of `nwell_tap`, since the west lane was already claimed by
  the tap's own overlap with `mp`) — i.e. from `mp`'s "far side" relative to
  the pin's own facing direction, which the router's edge-margin check
  correctly refuses. Moving the taps out of the west lane entirely, rather
  than trying to route `b` around them, is what fixed it: `net b`'s two
  waypoints (`x = -0.3`) now approach each source pin from its own natural
  west-facing direction, well under the 0.445 µm margin.

### The taps carry no route

`ro_buf`'s `vdd`/`vss` nets do double duty: the same wire both supplies the
transistor's own source terminal *and* lands on the tap's contact pad,
because in an inverter the source terminal genuinely *is* the supply rail.
In a transmission gate neither S/D pin is a supply — both are signal nodes
(`a`, `b`) — so the taps have nothing to route to inside this cell at all.
`nwell_tap`/`psub_tap` are placed purely for the **physical** nwell-merge /
substrate-tie their abutment with `mp`/`mn` already establishes (the same
mechanism `ro_buf`'s README documents under "Why abutted, not nested"), and
their `TAP_N`/`TAP_S` ports are promoted directly as this cell's `vdd`/`vss`
pins with **zero** `connectivity[]` entries — the electrical connection is
the merged well/substrate region itself, not a drawn wire. One residual
`klt gen-compose` warning (`block 'mp' is placed 0.00um from block
'nwell_tap', closer than nwell_tap's own declared drc_hints.min_spacing_um
of 0.40um`) is the same expected-and-harmless overlap warning `ro_buf`'s own
compose response carries, for the same deliberate 0.10 µm well-merge reason.

## What this does NOT establish

- **Not `sampler_dff`.** This is one of the three distinct leaf shapes
  `sampler_dff`'s 22 devices reduce to (3× plain inverter — already `ro_buf`,
  reusable as-is per `layout/xor2/`'s own precedent of placing `ro_buf` as an
  already-composed `blocks[].cell` — plus 4× this transmission gate, plus 2×
  a plain rst_n-gated NAND2 not yet composed). Assembling `sampler_dff` from
  these, and LVS-checking the *whole* 22-device cell against
  `design/sampler_core.spice`'s real `.subckt sampler_dff`, is the
  authoritative check and remains open — see issue #27.
- **No `sampler_nand2` yet.** `design/sampler_core.spice`'s `sampler_dff`
  subckt's `NANDM`/`NANDS2` gates (a plain 2-input NAND2, rst_n-gated, no
  starve devices — structurally `ro_nand2` minus its two starve transistors)
  are the other missing leaf shape.
- **No parasitics, no post-layout simulation.** `klt extract` was run without
  `--parasitics`.
- **The DRC verdict is against `klt`'s curated sky130 deck**, the same scope
  every other cell under `layout/` is checked against — see `ro_buf/README.md`'s
  own note on `drc.json`'s `coverage` block for exactly what that does and
  does not cover.
- **The LVS reference is hand-authored, not an xschem export** — see "Why
  this cell has no `design/*.spice` reference to point at" above. It is
  correct evidence for this cell's own two-device shape, not a substitute
  for `sampler_dff`'s own whole-cell LVS check.
