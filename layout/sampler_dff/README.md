# layout/sampler_dff

**`sampler_dff` assembly, continued: the five-pin `clk` fan-out is now
routed, DRC-clean, and lands on exactly the right six transistor gates
(issue #22).** `clk` is the first *fan-out* net in this cell — `vdd`/`vss`
are rails and `rst_n` was a two-pin point-to-point — and the first to be
drawn as a `gen-compose` **bundle net** with hand-steered
`connectivity[].legs[]`. Two stages: `clk_met1` vias all five pins straight
up from `li1` to `met1` (zero lateral distance, the same single-hop
via-drop `rst_n_met1` already uses), and the final stage runs the entire
long haul on `met2`/`"metal3"` as one basement lane at `y = -1.70` with a
vertical drop at each pin's own x. **0 DRC violations, 0 unrouted nets, and
the cell bbox is unchanged** (`-2.19 .. 50.47 x -3.585 .. 7.085` µm — the
lane fits under the device rows and inside the existing `vss` bus's own
vertical extent). Still open: `clkb` and the six `m`/`mb`/`mc`/`s`/`q`/`qb`
data-path nets — see "What remains" below.

**Why `clk` and `clkb` cannot be two mirrored lanes.** The obvious plan for
a differential clock pair — one bus above the device rows, one below, each
dropping straight onto its own gate — does not work here, and the reason is
circuit-level, not tool-level. `design/sampler_core.spice`'s own gate
assignments put `clk` on `tg_d`'s **PMOS** gate (`XMtdp`) and `tg_fbs`'s
**PMOS** gate (`XMfsp`), but on `tg_fbm`'s and `tg_s`'s **NMOS** gates
(`XMfmn`, `XMtsn`) — because a master-slave DFF's feedback gate runs the
opposite phase from its own stage's input gate. In `sampler_tg`'s layout
the PMOS gate (`ctrl`) sits at local `y = 2.50` and the NMOS gate (`ctrlb`)
at `y = 1.03`, so **the height `clk` has to reach alternates along the
row** — 2.50, 1.03, 1.03, 2.50 — and so does `clkb`'s, in antiphase. Any
single lane serving `clk` therefore has to pass *through* the height of a
`clkb` pin at two of the four transmission gates (and vice versa), at the
same x. Two mirrored lanes short in exactly two places, whichever way round
they are assigned. What this increment does instead: give `clk` the whole
`met2` plane below the rows (verticals at each pin's own x, since nothing
else is drawn down there), and leave `clkb` a **`met1` corridor at
`y ≈ 0.40`** — clear of `clk`'s own `met1` pads (lowest edge `y = 0.82`,
0.335 µm away against sky130's 0.14 µm `met1.space.1`) and of the `vss`
bus's own `met1` (top edge `y = -0.29`) — with a short `met2` hop over each
of the two `sampler_nand2` internal `met1` blobs, at `x` 12..14 and 43..45
where `clk` has no vertical at all. `clkb`'s verticals then cross `clk`'s
only on a *different layer*, which is not a short. The final stage's own
`_comment` in `cell.json` records this reservation so the next increment
does not have to re-derive it.

**Why `inv_clk`'s `clk` port is declared at `y = 1.03`, not the `y = 1.70`
the `place` stage uses — and what the alternative actually costs.** The
`place` stage declares `ro_buf`'s own `a` port at `(0.545, 1.70)`, a value
inherited from `layout/xor2/cell.json`, but that point is the middle of the
input strap's *narrow* section. `klayout.db` against `ro_buf.gds` shows the
strap is a dogbone: two 0.42 µm square gate pads at `y 0.82..1.24` and
`y 2.29..2.71`, joined by a 0.17 µm-wide bar (`x 0.46..0.63`) spanning
exactly the `y = 1.70` band. `gen-compose`'s via-drop landing pad is a
**fixed 0.42 µm square** (`_VIA_LANDING_SIZE_UM`, sized independently of
`routing.width_um` — the same convention the `rst_n_stub` derivation ran
into), so where the port lands decides whether that pad is an exact overlay
on existing metal or new geometry.

**Both were built and measured, not reasoned about.** With the port at
`y = 1.03` — the centre of the dogbone's own *lower* pad, which is the
identical 0.42 µm geometry as the two `ctrlb` pins this same net lands on —
`inv_clk`'s li1 strap in the composed `sampler_dff.gds` is
**polygon-for-polygon identical to `ro_buf.gds`'s own**: the landing pad is
an exact overlay and adds no li1 at all. With the port at `y = 1.70` (all
three of its declarations moved together and the cell rebuilt), the result
is **also `klt drc`-clean, 0 violations** — the concave step the pad leaves
against the lower pad's top edge measures 0.25 µm, comfortably above
sky130's 0.17 µm `li1.space.1`, so the "it would notch" intuition is simply
wrong and is recorded here so nobody re-derives it. What that variant does
cost is a 0.42 µm-wide li1 pad dropped across a 0.17 µm-wide bar directly
over the inverter's own gates — extra li1-over-poly area on a clock net,
for no benefit. `y = 1.03` is chosen for that reason, not for a DRC one.
No `2AMLogic/klayout-tools` friction was filed either way: nothing about
this is a tool gap.

## Result: `clk` fan-out (this increment)

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `clk_met1`, `metal2`/`met1` role) | All five `clk` pins vias li1→met1, zero lateral distance — **5/5 routed, 0 unrouted nets, 0 warnings** | `clk_met1.compose.request.json`, `clk_met1.compose.response.json`, `clk_met1.gds` |
| `klt gen-compose` (final stage, `metal3`/`met2` role, 5-pin bundle net with 4 hand-steered `legs[]`) | `clk` routed as one net, **74.735 µm total** over four legs (11.695 / 26.220 / 10.600 / 26.220 µm) — **`status: "routed"`, 0 unrouted nets, 0 warnings** | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` (whole `sampler_dff.gds`) | **clean, 0 violations** — first attempt, no iteration needed | `drc.json` |
| `klt extract --deck sky130` | **22 devices (11 nfet, 11 pfet)**, unchanged; `net_count` **31 → 27**, exactly the four merges a five-pin net makes. The merged net's own device list is the real check: `M$1` (`inv_clk` nfet), `M$12` (`inv_clk` pfet), `M$13` (`tg_d` **pfet**), `M$4` (`tg_fbm` **nfet**), `M$5` (`tg_s` **nfet**), `M$18` (`tg_fbs` **pfet**) — matching `XMnc`/`XMpc`/`XMtdp`/`XMfmn`/`XMtsn`/`XMfsp`, with `ctrlb\|tg_d_ctrlb`, `ctrl\|tg_fbm_ctrl`, `ctrl\|tg_s_ctrl`, `ctrlb\|tg_fbs_ctrlb` still four separate, correctly-unwired nets | `extract.json`, `sampler_dff.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_dff` | **mismatch, as expected** — 0/22 devices, 0/27 layout nets vs. 14 reference nets; `clkb` and the six data-path nets are still unwired and no top-level cell pins are promoted, so a full match is not attempted this increment | `lvs.json` |

Geometry, measured on the composed `sampler_dff.gds`: the whole `clk`
network is **one merged `met2` polygon** (`0.335 .. 49.24 x -1.785 ..
2.71` µm), physically separate from `rst_n`'s own `met2` bus
(`13.79 .. 45.11 x 2.50 .. 2.92` µm). The only two `clk` verticals whose x
falls inside `rst_n`'s span (`x = 24.6` and `29.74`) stop at their own
`ctrlb` pins — `met2` pad top edge `y = 1.24`, **1.26 µm** short of
`rst_n`'s lower edge — which is the whole reason the lane goes *below*
rather than above.

**A previous increment (issue #22): `rst_n` fan-out to both `sampler_nand2`
instances is routed, DRC-clean and electrically merged.**
`klt extract` confirms `nand_m_a`/`nand_s2_a`/`rst_n` are one net spanning
both instances (`sampler_dff.spice`'s own `.SUBCKT` pin line lists
`a|nand_m_a|nand_m_a_stub|nand_m_a_via|nand_s2_a|nand_s2_a_stub|nand_s2_a_via|rst_n`
as a single merged label group) — the first data/control net in this cell to
be wired end to end, after the previous increment's `vdd`/`vss` supply
buses. Still open: `clk`/`clkb` fan-out and the six `m`/`mb`/`mc`/`s`/`q`/`qb`
data-path nets — see "What remains" below.

**Why `rst_n` needed three routing stages, not one.** Both `sampler_nand2`
instances' `a` pin (the rst_n input) sits *inside* that leaf cell's own
internal `met1` via stack for its `y` output (confirmed with `klayout.db`
against `sampler_nand2.gds`: a single via/pad blob at local
`x=4.455..5.045, y=0.125..3.74`) — a `metal2`-role via-drop landing directly
on the pin (the first attempt) always shorts to that blob, on either
approach side, exactly as `gen-compose`'s own diagnostic says
(`"self-net's drawn metal overlaps block core's own drawn pad metal on the
route layer"`). The fix, in three additional stages on top of
`route_supplies`: `rst_n_stub` walks each pin east on `li1`/`"metal"`
role (no via, same layer as the pin) to an `_ext` point clear of the blob —
0.57 µm for `nand_m_a` (`x=13.43` → `14.0`) and 0.61 µm for `nand_s2_a`
(`x=44.29` → `44.9`), the two `route_length_um` values
`rst_n_stub.compose.response.json` reports (see "Why the two stubs are not
the same length" below);
`rst_n_met1` vias each `_ext` point straight up to `met1` (zero lateral
distance, a plain single-hop via-drop, the same mechanic every `vdd`/`vss`
leg in `route_supplies` already uses); the final stage vias again, `met1` to
`met3`/`"metal3"` role (also a single hop, the same one
`layout/ro_array_core/`'s own `t2bridge` stage uses), and runs the long haul
entirely on `met3` — a plane no leaf cell in this assembly draws on at all,
so it is clear of every leaf's own internal congestion *and* of the
`vdd`/`vss` buses' own `met1` bus (which spans the *entire* cell width at
`y=7.0`/`y=-3.5`, ruling out a "climb over the obstruction" detour: tried
and rejected first, since any such detour still has to cross the `vdd`/`vss`
buses' own drawn geometry somewhere within the assembly's own width).
`layout/sampler_dff/cell.json`'s own `_comment` blocks on the `rst_n_stub`
and `rst_n_met1` stages record the exact derivation, including a
`li1.space.1` DRC violation hit and fixed along the way (moving each real
`a` pin's own declared x from the `place` stage's `4.98` local to `4.90`, so
the new stub wire touches *both* the pin's own li1 pad *and* a separate,
only-transitively-connected li1 strap it was 20 nm short of overlapping
directly) and a second one (the via/pad's fixed 0.42 µm enclosure — sized
independently of `routing.width_um`, a `gen-compose` convention documented
in its own docstring — needing more x clearance from both the internal
`met1` blob and a nearby unrelated li1 pad than the first attempt gave it).
No `2AMLogic/klayout-tools` friction filed for this: `cross_block_layer_role`
(issue #1168) does not apply here (it bridges a same-block self-net leg
*mid-route* over an unrelated block's own pad, not a *destination pin*
sitting inside congestion), and the multi-hop `from_stage` chaining pattern
`layout/ro_array_core/cell.json` already established handled this case fine
once derived by hand.

**Why the two stubs are not the same length.** The two escapes are identical
in *method* — same direction (east, `direction_deg 0`), same layer, same
re-derived local pin coordinate (`4.90, 2.71`), both instances placed at
orientation `"none"` — but they are 0.57 µm and 0.61 µm long, not one shared
figure. Each `_ext` tip is snapped to a round *global* x (`14.0` for
`nand_m_a_ext`, `44.9` for `nand_s2_a_ext` — also the final `met3` bus's own
two endpoints, hence its `route_length_um` of exactly 30.9), while the pins
themselves land wherever each instance's placement origin puts them
(`8.53 + 4.90 = 13.43` and `39.39 + 4.90 = 44.29`). The origins are 30.86 µm
apart and the tips 30.9 µm apart, so the stubs differ by 0.04 µm. Neither
stub is length-critical: what actually has to clear the internal `met1` blob
(whose east edge lands at global `x=13.575` / `44.435`) is not the wire but
the 0.42 µm-wide landing pad the `rst_n_met1` via drops at the tip.
Measured on the composed `sampler_dff.gds`, that pad spans `x=13.79..14.21`
against a blob edge at `13.575` (0.215 µm of met1-to-met1 space) and
`x=44.69..45.11` against `44.435` (0.255 µm) — both clear, and `klt drc`
reports 0 violations. An earlier, shorter stub put that pad too close and
drew the second `li1.space.1` violation noted above; `14.0`/`44.9` are just
the first round global coordinates comfortably past that bound.

**A previous increment (issue #22): nine-block placement and the `vdd`/`vss`
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

## Result: `rst_n` fan-out (previous increment)

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `rst_n_stub`, `metal`/`li1` role) | Both `sampler_nand2` `a` pins get an li1-only stub east of that leaf's internal `met1` blob — **0.57 µm** (`nand_m_a_stub`, `x=13.43`→`14.0`) and **0.61 µm** (`nand_s2_a_stub`, `x=44.29`→`44.9`) per the response JSON's own `route_length_um`; same escape method, different lengths because the tips are snapped to round global x (see "Why the two stubs are not the same length"). **DRC-clean on its own** (`klt drc` against `rst_n_stub.gds` directly: 0 violations) | `rst_n_stub.compose.request.json`, `rst_n_stub.compose.response.json`, `rst_n_stub.gds` |
| `klt gen-compose` (stage `rst_n_met1`, `metal2`/`met1` role) | Each stub tip vias straight up to `met1`, zero lateral distance — **0 unrouted nets** | `rst_n_met1.compose.request.json`, `rst_n_met1.compose.response.json`, `rst_n_met1.gds` |
| `klt gen-compose` (stage `rst_n_bus`, `metal3`/`met2` role) | `rst_n` bussed the full `nand_m` → `nand_s2` span (`x=14.0..44.9`) entirely on `met3`, clear of every leaf's own `met1` usage and of the `vdd`/`vss` buses — **0 unrouted nets** | `rst_n_bus.compose.request.json`, `rst_n_bus.compose.response.json`, `rst_n_bus.gds` |
| `klt drc --deck sky130` (whole `sampler_dff.gds`) | **clean, 0 violations** — the two `li1.space.1` violations hit mid-derivation (both an `a`-pin-to-strap near-miss and a stub-pad-to-neighbour-pad near-miss, see the narrative above) are both resolved in the committed `cell.json` | `drc.json` |
| `klt extract --deck sky130` | **22 devices (11 nfet, 11 pfet)**, unchanged — `net_count` rises from `vdd`/`vss`-only (14 nets counting per-instance labels) to **31 nets**; `sampler_dff.spice`'s own pin line for this net lists `a\|nand_m_a\|nand_m_a_stub\|nand_m_a_via\|nand_s2_a\|nand_s2_a_stub\|nand_s2_a_via\|rst_n` as one merged label group, confirming real electrical connectivity from drawn geometry (not just JSON net-name bookkeeping) | `extract.json`, `sampler_dff.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_dff` | **mismatch, as expected** — 0/22 devices, 0/14 nets matched; `clk`/`clkb` and the six data-path nets are still unwired and no top-level cell pins are promoted yet, so a full match is not attempted this increment | `lvs.json` |

Cell extent is unchanged (`-2.19 .. 50.47 x -3.585 .. 7.085` µm — the ±0.085
µm growth on the y extremes is the `vdd`/`vss` bus width itself, already
present before this increment). Originally generated on
`klt 0.3.0+gc6dbf66c53c6`; re-generated unchanged (same verdicts, same
geometry) on `klt 0.4.0` by the `clk` increment above, which is what moves
`provenance.klt_version` to `0.4.0`, flips the deck's own
`released: false` → `true`, and adds a `dbu_um` field to every stage
response. Two mechanical consequences of that increment worth knowing when
reading a `git diff`: the previously-unnamed final stage is now named
`rst_n_bus` (so its evidence moved from `compose.*` to `rst_n_bus.*`,
freeing `compose.*` for the new final stage), and `net_count` in the
`rst_n` row below reads 31 against the state *before* `clk` was routed —
the current `extract.json` reports 27. KLayout 0.30.12 against open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` — matches `layout/pdk.json`'s
pin exactly, unchanged.

## Result: nine-block placement and `vdd`/`vss` (previous increment)

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `place`, nine `blocks[].cell` instances, zero routing) | **DRC-clean, 0 violations** — proves the floorplan itself has no collisions | `place.compose.request.json`, `place.compose.response.json` |
| `klt gen-compose` (stage `route_supplies`, `metal2` role — the final stage as of this increment's own predecessor, since renamed and given a `pins[]` promotion of `nand_m_a`/`nand_s2_a` so the `rst_n` stages below could reference them) | `vdd`/`vss` fully routed as two buses (one attic run at `y=7.0`, one basement run at `y=-3.5`, each an 8-leg chain across all nine instances), **0 unrouted nets, 0 warnings** | `route_supplies.compose.request.json`, `route_supplies.compose.response.json` |
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

- **`clkb` fan-out** — the other half of the clock pair: `inv_clk`'s own
  output plus `tg_d.ctrlb` (`5.31, 1.03`), `tg_fbm.ctrl` (`24.6, 2.5`),
  `tg_s.ctrl` (`29.74, 2.5`) and `tg_fbs.ctrlb` (`49.03, 1.03`). **`clk`'s
  own scheme cannot simply be mirrored** — see "Why `clk` and `clkb` cannot
  be two mirrored lanes" at the top of this file. The corridor the `clk`
  increment deliberately reserved for it, and did not consume, is: a `met1`
  long haul at `y ≈ 0.40` (clear of `clk`'s own `met1` pads, whose lowest
  edge is `y = 0.82`, and of the `vss` bus's own `met1` at `y = -0.29`),
  with a short `met2` hop over each of the two `sampler_nand2` internal
  `met1` blobs at `x` 12..14 and 43..45 — the only two places a `met1`
  lane across this cell is blocked, and two places where `clk` has no
  vertical to collide with. `clkb`'s own short `met1` risers to its four
  gate pins would sit at each pin's own x, crossing `clk`'s `met2`
  verticals on a *different layer* (not a short). None of this is drawn
  yet; the numbers above are derived from the committed geometry but not
  DRC-proven.
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
