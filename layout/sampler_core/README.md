# layout/sampler_core

`sampler_core` is `design/sampler_core.spice`'s top-level subckt: one
`ro_array_core` instance (`xdut`) plus six `sampler_dff` instances (`xsb`,
`xsv`, `xsr1`-`xsr4`), wired together (`design/README.md`'s own line:
"`sampler_core`  the sampler, wired to the source"). This directory promotes
[`layout/sampler_core-placement-poc/`](../sampler_core-placement-poc/README.md)'s
own six-instance floorplan (unchanged: 55.66 µm pitch, the same `sb`/`sv`/
`sr1`-`sr4` instance order and naming, the same `y=0.0` origin for every
instance) into a real, `compose-cell.py --check`-reproducible cell recipe.

## Result (this increment: `clk`/`rst_n` fan-out, issue #27 step 2)

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

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `place`) | DRC-clean, unchanged from the previous increment | `place.compose.request.json`, `place.compose.response.json`, `place.gds` |
| `klt gen-compose` (stage `route_supplies`, `vdd`/`vss`, met1) | DRC-clean, unchanged from the previous increment (now non-final — files renamed `route_supplies.compose.*`/`route_supplies.gds`, the same file-naming convention `place`'s own non-final stage already uses) | `route_supplies.compose.request.json`, `route_supplies.compose.response.json`, `route_supplies.gds` |
| `klt gen-compose` (stage `route_ctrl`, `clk`/`rst_n`, met2 — `"metal3"` role) | `clk` clean on the **first** attempt (five straight legs at `y=-1.7`); `rst_n`'s first attempt (a straight leg at `y=2.2`, mirroring `clk`'s recipe) failed all five legs — see "The `rst_n` correction" below — fixed by climbing to an empty band at `y=5.0` for the cross-instance haul. **0 unrouted nets** on the corrected attempt | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations**, on the corrected attempt; cell bbox unchanged | `drc.json` |
| `klt extract --deck sky130` | **132 devices** unchanged, **64 nets** (down from the `vdd`/`vss` increment's 74: `clk`/`rst_n` each merge from six separate per-instance nets into **one**, saving 5 apiece) | `extract.json`, `sampler_core.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_core` | **mismatch, as expected** — 0/132 devices, 1/64 nets matched (the `vdd` merge from a later dependency lookup); 0/176 devices, 1/92 nets matched against the reference (still incomplete, see "A known reference-generation gap" below). Not a regression: no `ro_array_core` instance exists yet, and `d`/`q` are still unwired | `lvs.json`, `sampler_core.ref.spice` |

Cell extent (final GDS, unchanged from every earlier increment — the new
`clk`/`rst_n` wiring stays within each instance's own already-drawn rail
footprint plus the inter-instance gaps) `x0=-2.19 x1=328.77 y0=-3.585
y1=7.085` µm. Generated on `klt 0.3.0+gc6dbf66c53c6` against open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` — `layout/pdk.json`'s own pin.

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

## A known reference-generation gap (not a `klt` gap — `compose-cell.py`'s own)

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

This does not block this increment — no LVS match is claimed or possible
yet regardless (no `ro_array_core` instance is even placed in the layout
side, and `clk`/`rst_n`/`d`/`q` are all unwired) — but it is worth recording
now so whoever attempts the real whole-cell LVS pass (issue #27 step 5) does
not have to re-discover it: fixing this generically means extending
`repoint_variant_instances` (or an equivalent rewrite) to every
`dependencies[]` entry's own body, not just the top subckt's.

## What remains (issue #22 / #27)

In rough dependency order (renumbered from
[`layout/sampler_core-placement-poc/README.md`](../sampler_core-placement-poc/README.md)'s
own list now that step 1 is done):

1. ~~**`vdd`/`vss` shared bus**~~ — **routed** (this increment).
2. **`clk`/`rst_n` shared fan-out** across all six instances — a six-way
   version of `layout/sampler_dff/README.md`'s own "Result: `clk` fan-out"
   derivation (a five-pin fan-out inside one cell); flagged by the placement
   PoC as likely the hardest remaining step, unchanged by this increment.
3. **Placing a `ro_array_core` instance** in this same row (or an adjacent
   one) and wiring its `xo`/`ro1`-`ro4` outputs to `sb`'s/`sr1`-`sr4`'s own
   `d` pins, plus `sv`'s `d` tied to the shared `vdd` bus this increment
   just built.
4. **Promoting the six `d`/`q` pin pairs** (`sb`'s `raw_bit`, `sv`'s
   `raw_valid`, `sr1`-`sr4`'s `ring_bit1`-`ring_bit4`) plus `en1`-`en4`/
   `vddr1`-`vddr4` (from the placed `ro_array_core`) as `sampler_core`'s own
   top-level pins — and, incidentally, `vdd`/`vss` themselves (also real
   top-level pins of `design/sampler_core.spice`'s own `.subckt
   sampler_core`), which this increment's own `route_supplies` stage could
   promote via `pins[]` cheaply once a later stage needs to address them,
   but does not do yet (nothing downstream needs the label this increment).
5. **Whole-cell `klt lvs`** against `design/sampler_core.spice`'s real
   `.subckt sampler_core` — the authoritative check, not attempted for real
   yet (see "A known reference-generation gap" above for the one concrete
   fix this will need first).
6. **Post-layout PVT simulation** of the fully assembled, LVS-clean
   `sampler_core` — the whole-chain (raw-tap-to-sampled-bit) claim issue #22
   was originally filed for, still open after every increment so far.
7. DR-0003 §8's `wstv` inter-ring decorrelation gap is **unaffected** by any
   of the above — it is about the entropy source's own inter-ring supply
   coupling (already re-evaluated at array scope by DR-0005/DR-0006), not
   the sampler side of the raw tap.

No `2AMLogic/klayout-tools` friction was found by this increment — the
`pins[]`/`connectivity[]` exclusivity rule (`gen-compose` rejects promoting
a port via `pins[]` that a `connectivity[]` net already wires, with a clear
error message naming both) is documented, expected router behaviour, not a
gap; and the reference-generation limitation above is this repo's own
`compose-cell.py`, not `klt`.
