# layout/sampler_dff

**`sampler_dff` assembly, started: nine-block placement and the `vdd`/`vss`
supply buses, both DRC-clean.** `design/sampler_core.spice`'s `.subckt
sampler_dff` is 22 devices, flat (`design/xschem/sampler_dff.sch` has no
sub-schematic symbols of its own) — but read as a signal-flow graph rather
than a device list, it is almost a linear pipeline with two small local
feedback loops, not a crossbar:

```
clk -> inv_clk -> clkb

d -> TG_D(clk/clkb) -> m -> NAND_M(m,rst_n) -> mb -> inv_mc -> mc
     -> TG_FBM(clkb/clk) -> (feeds back into m)

mb -> TG_S(clkb/clk) -> s -> inv_q -> q -> NAND_S2(q,rst_n) -> qb
     -> TG_FBS(clk/clkb) -> (feeds back into s)
```

(`TG_FBM`/`TG_FBS` run the *opposite* `clk`/`clkb` phase from their own
stage's input TG — the standard master-slave transparent-when-off-phase
structure. Confirmed directly against `design/sampler_core.spice`'s own gate
assignments: `Mtdp`/`Mtdn` (`clk`/`clkb`), `Mfmp`/`Mfmn` (`clkb`/`clk`),
`Mtsp`/`Mtsn` (`clkb`/`clk`), `Mfsp`/`Mfsn` (`clk`/`clkb`).)

That structure reduces the whole cell to nine instances of the three leaf
shapes issue #27 already composed: 3x [`ro_buf`](../ro_buf/README.md) (the
plain inverter — `inv_clk`, `inv_mc`, `inv_q`), 4x
[`sampler_tg`](../sampler_tg/README.md) (the transmission gate — `TG_D`,
`TG_FBM`, `TG_S`, `TG_FBS`), 2x
[`sampler_nand2`](../sampler_nand2/README.md) (the rst_n-gated NAND2 —
`NAND_M`, `NAND_S2`). This cell places all nine as already-composed sibling
GDS files (`blocks[].cell`, the same technique `layout/xor2/` used for its
own two `ro_buf` instances and `layout/ro_ring5/` used for `ro_nand2`/
`ro_stage`), left to right in signal-flow order.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
python3 layout/bin/compose-cell.py layout/sampler_dff/cell.json           # rebuild in place
python3 layout/bin/compose-cell.py layout/sampler_dff/cell.json --check   # verify, don't overwrite
```

## Result

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `place`, nine `blocks[].cell` instances, zero routing) | **DRC-clean, 0 violations** — proves the floorplan itself has no collisions | `place.compose.request.json`, `place.compose.response.json` |
| `klt gen-compose` (final stage, `metal2` role) | `vdd`/`vss` fully routed as two buses (one attic run at `y=7.0`, one basement run at `y=-3.5`, each an 8-leg chain across all nine instances), **0 unrouted nets, 0 warnings** | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **22 devices (11 nfet, 11 pfet)** — the exact count and type split `design/sampler_core.spice`'s own `.subckt sampler_dff` has, confirmed before any signal wiring exists; `vdd` and `vss` each fully merged into one net across all nine instances (`extract.json`'s own net-label lists carry all nine `<instance>_vdd`/`<instance>_vss` tap labels plus the internal `nwell_vdd`/`mpa_py`/`mpb_py` labels on the `vdd` net) | `extract.json`, `sampler_dff.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_dff` | **mismatch, as expected** — 0/22 devices, 0/14 nets matched. Every device pin sits on its own isolated per-instance net (`a\|tg_d_a`, `en\|nand_m_en`, ...) because `rst_n`, `clk`/`clkb`, and the six data-path nets are not wired yet; only `vdd`/`vss` are real merged nets. Not a regression — this cell was never expected to LVS-match until the remaining wiring lands | `lvs.json` |

Cell extent (final GDS) `-2.19 .. 50.65 x -3.5 .. 8.0` µm (nine instances
spread ~53 µm wide plus the attic/basement bus rows). Generated on `klt
0.4.0` / KLayout 0.30.12 against open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` — `layout/pdk.json`'s own pin
(the `klt` build installed in this environment has since moved to `0.4.0`;
`layout/pdk.json`'s own comment already documents this as expected churn,
not a hard gate).

## Floorplan: nine blocks, left to right in signal-flow order

```
inv_clk  tg_d  nand_m  inv_mc  tg_fbm  tg_s  inv_q  nand_s2  tg_fbs
x=0.0   4.765  8.53   19.29   24.055  29.195 36.0  39.39    48.485
```

Each pair of adjacent blocks is placed with a 3.0 µm bbox-to-bbox gap in `x`
(generous — this increment optimizes for "does it fit and route", not for
area; a tighter re-pitch is a legitimate future increment once the wiring
is proven). All nine origins share `y=0.0`; the three leaf shapes have very
different heights (`ro_buf` ~5.3 µm, `sampler_nand2` ~5.5 µm,
`sampler_tg` ~8.6 µm, since its taps sit north/south of the device row
rather than to the west) and are left un-recentred for the same reason.

## Deriving nine sets of hand-declared ports

`blocks[].cell` needs every instance's own port geometry hand-declared
(`layout/xor2/README.md` established this for `ro_buf`; `layout/ro_ring5/
cell.json` for two-stage cells like `ro_nand2`). This cell needed all three
shapes at once, so here is where each of the fifteen distinct
`(shape, port)` values below actually came from — every one is either an
*already-proven, already-merged* value, or independently derived from that
leaf's own `klt gen`/`gen-compose` response JSON and cross-checked against a
known-working example of the same orientation transform before use (the
same discipline `layout/sampler_nand2/README.md` used deriving its own tap
positions from `ro_nand2`'s).

**Validating the orientation-transform arithmetic.** `mos_array`/
`guard_ring` blocks placed at `origin=(ox, oy)` report *local* port
coordinates (from their own `gen/*.gen.json`, pre-placement); three
placement `orientation`s appear across this repo's cells, and this
increment needed a hand-checked formula for each because a `blocks[].cell`
port has no `gen-compose`-side feedback if it is wrong (it is just a
coordinate the router trusts):

- `"none"`: `global = (ox + local_x, oy + local_y)`. Verified against
  `layout/ro_buf/`'s own committed `nwell_tap` (`origin=(-2.04, 2.61)`,
  local `TAP_N=(0.92, 1.63)`) reproducing its known promoted `vdd` port
  exactly: `(-1.12, 4.24)`.
- `"mirror_y"`: `global = (ox + local_x, oy - local_y)`. Verified against
  `layout/sampler_tg/`'s own `mp` block (`origin=(0, 3.95)`, local
  `U0_G=(0.545, 1.45)`) reproducing its known promoted `ctrl` port exactly:
  `(0.545, 2.5)`.
- `"rotate_180"`: `global = (ox - local_x, oy - local_y)`. Verified against
  `layout/sampler_nand2/`'s own `mpb` block (`origin=(5.42, 4.16)`) by
  reproducing its *bbox* (not a single pin — see caveat below) exactly
  against `core.compose.response.json`'s own reported `bbox_um`.

**Caveat on `rotate_180` pin-level precision.** Applying the verified bbox
formula to `mpb`'s own `U0_G` local coordinate predicts `(4.875, 2.71)` for
`sampler_nand2`'s `a` (gate) pin — close to, but not exactly,
`layout/ro_ring5/cell.json`'s own already-*committed and DRC/LVS-clean*
value for the identical physical pin (`(4.98, 2.75)`, declared there when
`layout/ro_ring5/` reused `ro_nand2.gds`, whose `mpa`/`mpb`/`mnab` blocks are
placed at the *identical* `origins_um` `sampler_nand2` uses). The ~0.1 µm
gap is most likely `gen-compose`'s own via/landing-pad centroid correction
(the same effect `layout/xor2/README.md` and
`2AMLogic/klayout-tools#1520` document — a promoted port's drawn location is
not always the raw device-pin coordinate). Given a real discrepancy between
"my own arithmetic" and "an already-proven, merged value for the identical
physical geometry", this cell trusts the proven value:

| Port | Value used | Source |
|---|---|---|
| `sampler_nand2.en` | `(3.685, 1.975)`, dir 90 | `layout/ro_ring5/cell.json`'s own `g` block (identical `mpa`/`mnab` placement) |
| `sampler_nand2.a` | `(4.98, 2.75)`, dir 0 | same |
| `sampler_nand2.y` | `(4.79, 0.21)`, dir 90 | same |
| `sampler_nand2.vdd` | `(1.92, 4.45)`, dir 90 | derived: `nwell_tap` `TAP_N`, `"none"` formula, `origin=(1.00, 2.82)` |
| `sampler_nand2.vss` | `(1.94, -0.5)`, dir 270 | derived: `psub_tap` `TAP_S`, `"none"` formula, `origin=(1.02, -0.71)` |
| `sampler_tg.a` | `(1.9, 1.2)`, dir 0 | this cell's own `connectivity[].net "a"` waypoint (`x=1.9`, the same D-D lane `layout/ro_buf/`'s own `y` net already proves), any `y` in the routed span `0.21..3.53` |
| `sampler_tg.b` | `(-0.3, 1.2)`, dir 180 | this cell's own `connectivity[].net "b"` waypoint (`x=-0.3`), same span |
| `sampler_tg.ctrl` | `(0.545, 2.5)`, dir 270 | this cell's own promoted `pins[]` entry (`mp.U0_G`) |
| `sampler_tg.ctrlb` | `(0.545, 1.03)`, dir 90 | this cell's own promoted `pins[]` entry (`mn.U0_G`) |
| `sampler_tg.vdd` | `(0.545, 5.78)`, dir 90 | this cell's own promoted `pins[]` entry (`nwell_tap.TAP_N`) |
| `sampler_tg.vss` | `(0.545, -2.28)`, dir 270 | this cell's own promoted `pins[]` entry (`psub_tap.TAP_S`) |
| `ro_buf.a` | `(0.545, 1.7)`, dir 180 | `layout/xor2/cell.json`'s own `inv_a`/`inv_b` blocks (already proven) |
| `ro_buf.y` | `(1.9, 1.2)`, dir 0 | same |
| `ro_buf.vdd` | `(-1.12, 4.24)`, dir 90 | same (`ro_buf`'s own promoted `vdd` pin) |
| `ro_buf.vss` | `(-1.22, -0.5)`, dir 270 | same (`layout/xor2/`'s own choice of `psub_tap.TAP_S`, not `ro_buf`'s own internally-promoted `TAP_N` — a *different*, non-conflicting face on the same physical net, exactly as `layout/sampler_nand2/README.md` used a non-conflicting tap face for its own external promotion) |

## Why the `place` stage exists on its own

`layout/ro_ring5/cell.json` names this pattern explicitly (`"place" --
placement only, no routing... The bare placement is DRC-clean on its own`)
for exactly the reason it is used again here: nine heterogeneous blocks
spread across ~53 µm is the single largest floorplan attempted in this
repo, and proving zero collisions *before* attempting any routing turns one
large risky `gen-compose` call into two much smaller, independently
diagnosable ones. It succeeded on the first attempt (0 DRC violations),
which is not something every prior cell in this repo could say (compare
`layout/sampler_tg/README.md`'s "first attempt, and why it failed").

## Why `vdd`/`vss` needed `"metal2"`, not `"metal3"`

The first attempt at the supply-bus stage used `routing.layer_role:
"metal3"`, following `layout/ro_ring5/cell.json`'s own final stage (which
routes `vddr`/`vss` on `metal3` specifically *because* its leaf cells never
draw anything on that plane). That attempt failed outright:
`gen-compose` refused every leg with `routing.layer_role's (69, 20) cannot
reach: routing.layer_role's metal (deck metals[2]) is more than one via hop
from this pin's own layer (deck metals[0]) -- gen_compose's via-drop only
supports a single-hop drop`. Every port declared here is on the generic
`(67, 20)` abstract pin layer (`deck metals[0]`, li1), and `metal3` is `deck
metals[2]` — two hops away. `"metal2"` (`deck metals[1]`, met1) is the
correct single-hop target for these ports, and it is available here (unlike
in `ro_array_core`'s own array-level bus, which needed `metal3` precisely
*because* its own leaf cells already draw `metal2` at the exact locations a
`metal2` bus would need to cross) because this cell's own `vdd`/`vss` buses
run at `y=7.0`/`y=-3.5`, well outside the vertical extent every leaf
instance's own internal `metal2` wiring occupies (the tallest leaf,
`sampler_tg`, only reaches `y=6.14`/`y=-2.49`).

## What remains (issue #27)

- **`rst_n` fan-out** to both `sampler_nand2` instances' own `a` pin
  (`NAND_M`'s `Mimpb`/`Mimnb`, `NAND_S2`'s `Mis2pb`/`Mis2nb`).
- **`clk`/`clkb` fan-out** to `inv_clk` (input/output) and all four
  transmission gates' `ctrl`/`ctrlb` pins (opposite assignment between
  `TG_D`/`TG_S` and `TG_FBM`/`TG_FBS`, see the signal-flow diagram above).
  **Not a simple repeat of the `vdd`/`vss` bus technique**: `ctrl`/`ctrlb`
  sit at local `y = 2.5`/`1.03`, inside each transmission gate's own device
  row gap rather than at a block extremity, so a bus at `y=7.0` or `y=-3.5`
  (already claimed by `vdd`/`vss`) would force a vertical stub straight
  through the already-drawn horizontal bus wire at that instance's own `x`
  — a same-layer short. This needs either its own distinct `y` band
  strictly between the device rows and the `vdd`/`vss` buses, or a route
  that goes around the assembly's own east/west ends rather than through
  the middle; not yet attempted.
- **The six data-path nets**: `m` (`TG_D.a`/`b` <-> `NAND_M.en` <->
  `TG_FBM.a`/`b`), `mb` (`NAND_M.y` <-> `inv_mc.a` <-> `TG_S.a`/`b`), `mc`
  (`inv_mc.y` <-> `TG_FBM.a`/`b`), `s` (`TG_S.a`/`b` <-> `inv_q.a` <->
  `TG_FBS.a`/`b`), `q` (`inv_q.y` <-> `NAND_S2.en`, and the cell's own
  output pin), `qb` (`NAND_S2.y` <-> `TG_FBS.a`/`b`).
- **Promoting the whole-cell external pins** (`d`, `clk`, `rst_n`, `q`,
  `vdd`, `vss`) once the above wiring exists, and the resulting
  `klt lvs` sign-off against `design/sampler_core.spice`'s real `.subckt
  sampler_dff` — the authoritative check for this cell, not yet attempted.
- **`sampler_core`**'s own six-instance wiring, and the whole-chain
  (raw-tap-to-sampled-bit) post-layout PVT campaign, both still fully
  open behind the above.
