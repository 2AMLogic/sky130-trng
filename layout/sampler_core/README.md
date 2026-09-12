# layout/sampler_core

`sampler_core` is `design/sampler_core.spice`'s top-level subckt: one
`ro_array_core` instance (`xdut`) plus six `sampler_dff` instances (`xsb`,
`xsv`, `xsr1`-`xsr4`), wired together (`design/README.md`'s own line:
"`sampler_core`  the sampler, wired to the source"). This directory promotes
[`layout/sampler_core-placement-poc/`](../sampler_core-placement-poc/README.md)'s
own six-instance floorplan (unchanged: 55.66 µm pitch, the same `sb`/`sv`/
`sr1`-`sr4` instance order and naming, the same `y=0.0` origin for every
instance) into a real, `compose-cell.py --check`-reproducible cell recipe,
places the `ro_array_core` instance above it, and finishes wiring the two
together: all five data nets are routed and every sampler `d` pin is driven.
**As of this increment, both inter-block supply straps (`vdd` and `vss`) are
real metal, and `klt lvs` against `design/sampler_core.spice`'s own
`.subckt sampler_core` is a full match — DRC-clean, 264/264 devices,
152/152 nets, 0 errors.** This is the first whole-cell DRC/LVS-clean
`sampler_core` assembly in this repo.

## Result (this increment: the `vdd` inter-block supply strap and a whole-cell `klt lvs` match, issue #22 / #27 step 5, second half)

Three new stages on top of the twelve below (all unchanged): `vdd_strap1`
through final `vdd_strap3` route real metal from `ro_array_core`'s own `vdd`
to the six-`sampler_dff` bank's own `vdd` rail — the second and last of this
cell's two supply straps. Until this increment the two extracted as **two
separate nets**, both happening to contain the literal label `vdd` (the
array's own internal `vdd` bus, and the sampler bank's own `vdd` rail) — not
merged the way `vss` already was via the shared p-substrate, since sky130's
substrate model is NMOS-body-only and has no equivalent PMOS-well merge.

Unlike `vss`, a pure single-layer (met1) run from the array's own tap to the
rail does not work here: the array's own internal routing between the two
is far denser on this side, and a met1 net belonging to some other signal
(not previously named in this cell's own documentation) spans the *whole*
composed `x=211.64..214.97` corridor at `y=25.25..25.42`, with no gap to
route through at any `x` in that span — re-measured directly by exact
polygon intersection, not assumed, and not read off a `Region.merge()`
bounding box (a real pitfall this increment's own `vdd-strap-scan.py`
documents: a first-pass reading of this exact obstruction's *bbox* was
`172.86..214.97` at `y=25.125..29.32`, far bigger than its actual footprint,
because `merge()` unions many separate, unrelated same-layer shapes into one
polygon whose bbox is not its area). `vdd_strap1` (met1) descends from the
tap to a point safely above that obstruction; `vdd_strap2` (met2, a layer
the obstruction cannot short against) bridges past it in a 1.1 µm hop;
`vdd_strap3` (met1, final) returns to met1 for the last drop directly onto
the sampler bank's own `vdd` rail — an interior point on already-drawn
metal, the same technique `vss_strap4` used for `vss`. The chosen column,
composed `x=213.7`, is also clear of the array's own east vss riser (met2,
`x=214.29..214.71` — the same riser `vss_tap` lands directly on) with
`0.38` µm of margin, past the `0.14` µm sky130 spacing rule.

Three single-leg met1-only paths were tried and rejected before this
increment's own met1/met2/met1 route: two (an eastward jog along the
array's own vdd bus, and a direct crossing of `ro4_esc`'s own risers) are
recovered from a prior interrupted session's own uncommitted work — their
own descriptions, including the real short LVS caught, are preserved as
written rather than re-run; a third (a pure-met1 run straight down composed
`x=215.0`, the prior session's own chosen endpoint) was re-tested fresh
this session against the current toolchain and found to collide too — its
own exact `gen-compose` overlap-check output (`0.0231 um^2` at
`214.915..214.97, 25.125..25.545`) is reproduced by `vdd-strap-scan.py`'s
own "obstruction" claims. All three are documented in full in `cell.json`'s
own `vdd_strap1` stage comment.

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stages `place` … `vss_strap4`) | unchanged from the previous increments | `<stage>.compose.*.json`, `<stage>.gds` |
| `klt gen-compose` (stage `vdd_strap1`, met1 — `"metal2"` role) | **1/1 routed** | `vdd_strap1.compose.*.json`, `vdd_strap1.gds` |
| `klt gen-compose` (stage `vdd_strap2`, met2 — `"metal3"` role, auto-via both ends) | **1/1 routed** | `vdd_strap2.compose.*.json`, `vdd_strap2.gds` |
| `klt gen-compose` (final stage `vdd_strap3`, met1 — `"metal2"` role, auto-via at entry) | **1/1 routed** | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **264 devices** (unchanged), **152 nets** (down from 153 — `vdd`'s two nets are now genuinely one) | `extract.json`, `sampler_core.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_core` | **match — 264/264 devices, 152/152 nets, 0 errors** (the one reported `mismatch` is the standard `topology.flattened` informational warning every `flatten_reference` run in this repo carries, not a real mismatch) | `lvs.json`, `sampler_core.ref.spice` |
| `vdd-strap-scan.py` | **17/17 claims hold** | `vdd-strap-scan.json` |

Cell extent unchanged at `x0=-2.19 x1=328.77 y0=-3.585 y1=54.72` µm; 8408
polygons (from 8399), density essentially unchanged (`klt stats`).

Against this issue's own acceptance bar: `sampler_core` is now
DRC-clean **and** LVS-clean, closing #27 step 5 in full and step 7's
layout-side requirement — top-level pin promotion (previously listed as
also needed for step 7) turned out **not** to be required for a full `klt
lvs` match with `flatten_layout`/`flatten_reference` both `true`, since the
matcher compares flattened net/device topology rather than declared
top-level pins; that line item in "What remains" below is corrected rather
than carried forward. **Still open**: the assembled `sampler_core`
post-layout PVT run (issue #22's own whole-chain claim) and DR-0003 §8's
`wstv` inter-ring decorrelation re-evaluation — both deliberately not
attempted in this increment, tracked in #27.

## Result (a previous increment: the `vss` inter-block supply strap, issue #22 / #27 step 5)

Four new stages on top of the eight below (all unchanged): `vss_strap1`
through final `vss_strap4` route real metal from `ro_array_core`'s own `vss`
to the six-`sampler_dff` bank's own `vss` rail — the first of this cell's
two supply straps (`vdd` remains open; see "What remains" below). Until this
increment the two extracted as **one** net only through sky130's shared
p-substrate model (see "The electrical result, and one merge nobody drew"
below) — real for extraction purposes, but not something a fabricated die
can rely on as a low-impedance rail.

The strap taps the array's own **east** vdd/vss riser (met2, `x=214.5` — an
exact point on `layout/ro_array_core/cell.json`'s own `vssbus` stage,
verified by construction rather than by inspection) and descends through the
`sr2`→`sr3` inter-instance gap (`x=218.0`, one of the five 3.0 µm gaps
between adjacent `sampler_dff` bboxes that carry nothing but the four shared
buses, the same kind of gap `route_ctrl`'s own `clk`/`rst_n` chains already
cross): `vss_strap1` (met2) walks east then south from the riser tap to
`y=19.9`; `vss_strap2` (met1) crosses `ro3`'s and `ro4`'s own channel hauls
for free (different layer) down to `y=7.65`; `vss_strap3` (met2) bridges
over the shared `vdd` rail's own height; `vss_strap4` (met1, final) crosses
`rst_n`'s and `clk`'s own lanes for free and lands directly on the sampler
bank's own `vss` rail — the same "interior point on already-drawn metal, no
via needed" technique `sv_d_vdd_tie` used for `vdd`.

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stages `place` … `route_data2`) | unchanged from the previous increments | `<stage>.compose.*.json`, `<stage>.gds` |
| `klt gen-compose` (stage `vss_strap1`, met2 — `"metal3"` role) | **1/1 routed**, second attempt (see "The `sb`→`sv` attempt" below) | `vss_strap1.compose.*.json`, `vss_strap1.gds` |
| `klt gen-compose` (stage `vss_strap2`, met1 — `"metal2"` role) | **1/1 routed** | `vss_strap2.compose.*.json`, `vss_strap2.gds` |
| `klt gen-compose` (stage `vss_strap3`, met2 — `"metal3"` role) | **1/1 routed** | `vss_strap3.compose.*.json`, `vss_strap3.gds` |
| `klt gen-compose` (final stage `vss_strap4`, met1 — `"metal2"` role) | **1/1 routed** | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **264 devices** (unchanged), **153 nets** (unchanged — `vss` was already one net via the substrate; a real metal strap does not change the *topology*, only how it is realized) | `extract.json`, `sampler_core.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_core` | **mismatch, unchanged** — 138/264 devices, 100/152 nets. `vss` was already merged for LVS purposes too; the remaining mismatch is `vdd` (still two nets) plus top-level pin promotion, neither touched by this increment | `lvs.json`, `sampler_core.ref.spice` |
| `vss-strap-scan.py` | **12/12 claims hold** | `vss-strap-scan.json` |

Cell extent unchanged at `x0=-2.19 x1=328.77 y0=-3.585 y1=54.72` µm; 8399
polygons (from 8386), density essentially unchanged (`klt stats`). Generated
on `klt 0.3.0+gc6dbf66c53c6` against open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` — `layout/pdk.json`'s own pin.

### The `sb`→`sv` attempt, and why it moved east

The first attempt tapped the array's own `vss` bus directly (composed
`(52.0, 20.635)`, inside the `sb`→`sv` gap) and tried to descend the whole
way to the `vss` rail on met1 in one stage. It hit two real obstacles in
sequence, both found by `klt gen-compose`'s own checks rather than assumed:

1. **An array-internal met1 bar** at `y 20.125..20.295`, spanning
   `x 47.01..213.08` — almost certainly a ring/tap strap the array's own
   construction left connected to the substrate but not (yet) strapped to
   its own met2 `vss` bus by metal, the same "still through the substrate"
   gap this increment is closing at the block level. `gen-compose` rejected
   the single-stage met1 descent outright: `self-net's drawn 0.17um metal
   overlaps 0.0289um^2 of block 'core''s own drawn pad metal on the route
   layer (drawn geometry (no port of its own sits on it))` — a real, tool-
   caught silent-short candidate, not a false positive.
2. **No room for a via between that bar and `ro3`'s own channel haul.** The
   fix's own first retry split the descent into a met2 "dip" (clearing the
   bar) plus a met1 leg (crossing `ro3`/`ro2`/`ro1` for free), transitioning
   layers at `y=19.9` — but the window between `ro3`'s own top edge
   (`y=19.485`) and the bar's own bottom edge (`y=20.125`) is only `0.64 µm`,
   and a via's own `0.42 µm` pad plus `0.14 µm` clearance on both sides needs
   `0.70 µm`. `klt drc` caught this one too (`met2.space.1`, not a routing
   rejection): the via's own met2-side pad came within `0.005 µm` of `ro3`'s
   own edge.

Neither obstacle exists at `x=218` (the `sr2`→`sr3` gap this increment
actually uses): the array-internal bar stops at `x=213.08`, well west of it,
and `ro1`/`ro2`'s own channel hauls stop at `x≤173.645`, also well west of
it. `ro3`'s own *second* leg (`y=13.6`) and `ro4`'s haul (`y=15.0`) do cross
this gap, but both are far enough below this stage's own `y=19.9`→`y=7.65`
met1 run that they are crossed for free on the way down, with room to spare.
`vss-strap-scan.py`'s own group A/B claims re-derive both findings —
`gap1_window_too_narrow_for_a_via` and `gap4_has_no_array_internal_bar` —
directly from the committed pre-increment stream.

### Friction

No new `2AMLogic/klayout-tools` issue was filed by this increment. Both
rejections above (`gen-compose`'s own overlap check, `klt drc`'s own
`met2.space.1`) worked exactly as documented and caught real problems before
they became silent shorts.

## Result (this increment: the last three data nets, and `sv`'s own `vdd` tie, issue #22 / #105)

Two new stages on top of the six below (all six unchanged; `route_data` is now
non-final, so its files are renamed `route_data.compose.*`/`route_data.gds`, the
same convention the five stages before it already use):

- **`data2_m1`** (met1) draws nine legs: the `d`-input climbs for `sb`, `sr2`
  and `sr3` (the same `li1`→met1 recipe `data_m1` used for `sr1`/`sr4`), `sv`'s
  own `d`→`vdd` tie, `ro2`'s and `ro3`'s **westward** escapes along their own
  already-drawn horizontals, and the two short met1 legs `xo` needs — the
  `li1`→met1 promotion of `xa3`'s own `y` pad, and a detached "dip" that ducks
  under `xa2`'s own `t2` riser.
- **`route_data2`** (met2) closes the three remaining hauls (`ro2`→`sr2.d`,
  `ro3`→`sr3.d`, `xo`→`sb.d`) plus the one 2.1 µm met2 hop that joins `ro3`'s
  split met1 escape across `ro2`'s own vertical.

**Every `d` pin in the cell is now driven** — the five data nets from the array
plus `sv`'s constant `1` — which is the precondition item 7 below has been
waiting on.

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stages `place`, `route_supplies`, `route_ctrl`, `place_array`, `data_m1`, `route_data`) | unchanged from the previous increments | `<stage>.compose.request.json`, `<stage>.compose.response.json`, `<stage>.gds` |
| `klt gen-compose` (stage `data2_m1`, met1 — `"metal2"` role) | **9/9 routed**, first attempt | `data2_m1.compose.*.json`, `data2_m1.gds` |
| `klt gen-compose` (final stage `route_data2`, met2 — `"metal3"` role) | **5/5 routed**, first attempt | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **264 devices** (unchanged), **153 nets** — `157 − 4`, exactly one merge per net joined and nothing else | `extract.json`, `sampler_core.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_core` | **mismatch, as expected and quantified** — 138/264 devices, 100/152 nets (from 136/264, 94/152). The supplies are still two `vdd` nets where the schematic has one, so a match is not reachable until item 5 below lands | `lvs.json`, `sampler_core.ref.spice` |
| `data-path-scan.py` | **19/19 claims hold** (13 before) | `data-path-scan.json` |

Cell extent unchanged at `x0=-2.19 x1=328.77 y0=-3.585 y1=54.72` µm; 8386
polygons (from 8326), 22.9% density (`klt stats`). Generated on `klt
0.3.0+gc6dbf66c53c6` against open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b`
— `layout/pdk.json`'s own pin, the same build the previous increment used.

### The one thing that changes the shape of the problem: escape *sideways*, not down

The previous increment measured that `ro2` and `ro3` have no free met1 column
from their own runs down past the array's south edge, and concluded each would
need "a layer change *inside* the array's own footprint". That is right, but the
useful move turned out not to be a rung over the fencing horizontals — it is to
stay on met1, walk **west along the net's own horizontal** to the array's west
margin, and descend there on met2.

`data-path-scan.py`'s new group E scans `route_data.gds` — the state before this
increment drew anything — for every 0.05 µm column that is free of met2 over the
array's whole height (`y` 19.4 .. 50.0 in the composed frame, i.e. from just
under its south edge to above the `xor2` row). There are exactly two bands:

| Band | `x` (composed frame) | Reachable? |
|---|---|---|
| west margin | `-2.1 .. 1.65` | **yes** — met1 at `ro2`'s own `y=32.135` and at `ro3`'s `y=32.635` is free from `x=-0.415` to `x=20.415`, so both nets can walk to it |
| east margin | `215.05 .. 220.0` | **no** — see below |

The east band is free and useless. Getting onto it needs a met1↔met2 via
dropped between the array's own east `vdd`/`vss` riser (met2, right edge
`x=214.71`) and `ro4`'s own met1 escape leg (left edge `x=215.315`) — a
**0.605 µm** gap, where the via's own concentric 0.42 µm pads need
`0.42 + 2 × 0.14 = 0.70 µm` to clear both at sky130's 0.14 µm met spacing. Both
edges are measured from the stream, and the arithmetic is a claim
(`no_via_fits_between_the_east_riser_and_ro4s_escape_leg`), not a remark.

### Three nets, one margin: what orders the lanes

All three remaining nets descend the same 3.75 µm-wide west margin, so the
ordering is forced by two facts rather than chosen:

- **`ro1`'s own channel haul** (met2, `y=17.0`) runs east from `x=-0.71`. A
  column that has to reach *below* `y=17` must therefore sit west of about
  `x=-1.02`. Only `xo` needs that (its target, `sb`'s `d`, is at `x=6.665`,
  east of the haul's own west end and under it), so `xo` takes `x=-1.5` and
  `ro2`/`ro3` turn east *above* the haul, at `y=18.6` and `y=19.4`.
- **`ro3`'s target column is east of `ro2`'s** (`x=229.305` vs `173.645`), so
  `ro3` takes the **higher** channel lane *and* the **eastern** of the two
  margin columns (`x=1.3` vs `0.3`). With that pairing neither net's lane ever
  crosses the other's column — the first try had them the other way round and
  the pre-flight scan found `ro3`'s lane crossing `ro2`'s descent, a silent
  short that DRC would not have reported.

`y=19.4` is the ceiling, not a round number: the array's own bottom met2 spans
`y 20.0..20.6` across `x 2.605..214.71`, and a via pad hangs to `y≈19.6` at
`x≈58`.

`ro3` then needs one more dogleg. Its target column (`x=229.305`) would cross
`ro4`'s own channel haul (met2, `y=15.0`, `x 215.4..284.965`) on the way down,
so it drops to a second lane at `y=13.6` at `x=210.0` — west of that haul's own
west end — and runs east underneath it before descending.

### `ro3`'s split escape, and the 2.1 µm hop

`ro2` walks west in one met1 leg (`x=20.5 → 0.3` at `y=32.135`). `ro3` cannot:
`ro2`'s own vertical (met1, `x 20.415..20.585`) sits between `ro3`'s horizontal
and the margin, and a met1 leg through it would short the two data nets
together. So `ro3`'s escape is two detached met1 legs at the same `y=32.635` —
`ro3_esc_e` (`28.47 → 21.6`) and `ro3_esc_w` (`19.5 → 1.3`) — joined by
`ro3_hop`, a 2.1 µm met2 leg in the final stage that crosses over `ro2`'s
vertical on a different plane. `klt extract` confirms the three fragments come
out as one net (`ro3|ro3_esc_e|ro3_esc_w|ro3_hop|sr3_d_stub|…`), and that
`ro2`'s stays separate.

### `xo`: the two-hop via gap, and one dip

`xa3`'s own `y` output is an li1 pad at `(66.375, 49.22)`, and the haul that has
to reach `sb`'s `d` runs on met2 — two via hops away, which `klt gen-compose`
will not do in one route (`klayout-tools#1567`, filed by the previous
increment). The workaround that gap's own filing predicts is a hand-built met1
rung, and this cell already contains the template for it:
`layout/ro_array_core/cell.json`'s own `core` stage declares exactly such a
promotion for `xa2` (its `y_m1` port, 1.4 µm straight north of the same `y` pad
in the same `xor2` cell). `xo_stub` is that promotion at `xa3` instead of `xa2`.

From there met2 is fenced in three directions by `xa2`'s own `t2` net: its riser
(met2, `x 37.32..37.49`) climbs from `y=50.41` into the `t2` bridge, and that
bridge spans `x 37.32..78.575` — so met2 is blocked west of `xa3` at `x≈37.4`,
blocked north at `y=54.635`, and blocked east at `x≈78.5` by `xa3`'s own `b_m1`
riser. The way through is one met1 **dip**: at `y=52.5`, met2 carries exactly
one obstacle between `x=30` and `x=66.375` (the `t2` riser), while met1 at that
same height is clear from `x=30` to `x=38.77`. So `xo_hop` runs met2 west at
`y=52.5` to `x=38.2`, `xo_dip` crosses under the riser on met1 to `x=36.5`, and
the final haul climbs back to met2, runs west at `y=53.5` (clear all the way to
the margin), and descends `x=-1.5` to the channel.

### `sv`'s `d` is not a haul at all

`design/sampler_core.spice` wires `xsv`'s own `d` to `vdd`, not to the array —
the valid-flag sampler samples a constant `1`. So `sv_d_vdd_tie` climbs the same
`d` column the other five instances use and simply keeps going to `y=7.0`, an
interior point **on** the shared `vdd` rail's own met1 (drawn at
`y 6.915..7.085` by `route_supplies`), landing directly on the target net's
metal with no via — the same technique that stage's own `vdd`/`vss` ports use.
`klt extract` puts `sv`'s `d` on the sampler bank's `vdd` net, and
`data-path-scan.py` checks both that and that the tie's own label sits in
`sv`'s own column.

### What the extraction says

`157 → 153` nets, `264` devices unchanged — exactly the four merges this
increment drew (`ro2`, `ro3`, `xo`, and `sv`'s tie), each confirmed
net-by-net rather than by the count alone. Every one of the five data nets is
one extracted net carrying the array's own promoted output label, every leg
drawn for it, the sampler stub it ends on, and a sampler `d` pin; every
`<instance>_d_stub` label sits in that instance's own `d` column, so each
connection lands on the intended sampler rather than merely on *a* sampler;
and **no unconnected `d` net remains**. The array's `vdd` and the sampler
bank's `vdd` are still two separate nets (item 5 below), and `vss` is still
one net through the shared p-substrate rather than through metal — both
unchanged by this increment, both still asserted.

### Friction

No new `2AMLogic/klayout-tools` issue was filed by this increment. It hit
`#1567` (no multi-level via drop) exactly where the previous increment
predicted, and worked around it the way that filing itself describes rather
than re-filing it.

## A previous increment: the `ro_array_core` instance, and the first two data nets (issue #27 step 3)

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

> **Answered by the increment at the top of this file.** Every measurement in
> this section still reproduces (`data-path-scan.py` still asserts
> `ro2_and_ro3_have_none`), and the conclusion "each needs a layer change
> *inside* the array's own footprint" was right. What it did **not** anticipate
> is the shape of that change: the two nets never hop their fencing horizontals
> at all — they walk west on met1 along their own runs to the array's own west
> margin, which is one of only two `x` bands where met2 is free over the array's
> whole height, and descend there. The met1 escape-column scan in this section
> looks straight down from each run and so cannot see that option; group E of
> the same script is the scan that does.

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
and, at the time, `array_and_sampler_vdd_are_still_two_nets`; the vdd strap
below later merged them on purpose, so that claim is now inverted and named
`array_and_sampler_vdd_are_one_net_via_the_strap`). It is worth stating plainly
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
3. ~~**Placing a `ro_array_core` instance**~~ — **placed** (PR #107, stage
   `place_array`), and two of its five data nets (`ro1`→`sr1.d`,
   `ro4`→`sr4.d`) routed.
4. ~~**The remaining three data nets**~~ — `xo`→`sb.d`, `ro2`→`sr2.d`,
   `ro3`→`sr3.d`, plus `sv`'s own `d`→`vdd` tie: **routed** (this increment,
   stages `data2_m1`/`route_data2`). The layer change each needed inside the
   array's own footprint turned out to be a westward met1 walk to the array's
   own west margin plus a met2 descent, not a rung over the fencing
   horizontals — see this increment's own section above.
5. ~~**The inter-block supply straps.**~~ **Both routed.** `vss` (PR #112,
   stages `vss_strap1`-`vss_strap4`); `vdd` (this increment, stages
   `vdd_strap1`-`vdd_strap3` — see this increment's own section above). The
   array-side access point for `vdd` did sit much deeper inside the array's
   own footprint than `vss`'s own edge-adjacent riser, exactly as the
   previous increment predicted, and did need its own derivation (a met2
   bridge past a previously-undocumented met1 obstruction) rather than a
   trivial mirror.
6. ~~**Promoting the top-level pins**~~ — **turned out not to be required.**
   The six `d`/`q` pin pairs, `en1`-`en4`/`vddr1`-`vddr4`, and `vdd`/`vss`
   themselves are exercised as ordinary nets in `klt lvs`'s own flattened
   comparison (`flatten_layout`/`flatten_reference` both `true`); no
   `cell.json` `pins[]` declaration was needed for a full match (this
   increment). This item is corrected, not carried forward.
7. ~~**Whole-cell `klt lvs` match**~~ — **achieved (this increment): 264/264
   devices, 152/152 nets, 0 errors**, against `design/sampler_core.spice`'s
   real `.subckt sampler_core`, reference side unchanged (264 devices,
   complete — see "The reference-generation gap, closed" below).
8. **Post-layout PVT simulation** of the fully assembled, DRC/LVS-clean
   `sampler_core` — the whole-chain (raw-tap-to-sampled-bit) claim issue #22
   was originally filed for, still open. Now unblocked: the supplies are a
   single `vdd` net and a single `vss` net, matching the schematic, so an
   extraction of this cell's GDS is finally an extraction of the circuit the
   schematic actually describes. Deliberately not attempted in this
   increment.
9. DR-0003 §8's `wstv` inter-ring decorrelation gap remains **unaffected**
   by any of the above — it is about the entropy source's own inter-ring
   supply coupling (already re-evaluated at array scope by
   DR-0005/DR-0006), not the sampler side of the raw tap. A `sampler_core`
   post-layout run (item 8) does not change that scope; re-evaluating it
   would need parasitics of the *assembled array itself* across multiple
   ring instances, which this cell's own extraction does not add.

Two `2AMLogic/klayout-tools` items were filed by the `place_array` increment
(no multi-level via drop; a docstring that denies a capability the tool has) —
see "Friction filed" below; the current increment filed none. The `pins[]`/`connectivity[]` exclusivity rule the
previous increment considered and dismissed is still not a gap, and the
reference-generation limitation it recorded was this repo's own
`compose-cell.py`, now fixed here.

## Files

| File | What it is |
|---|---|
| `cell.json` | the recipe: eight stages plus the `lvs` block |
| `<stage>.compose.request.json` / `.response.json` / `.gds` | each non-final stage's own request, response and composed stream (`place`, `route_supplies`, `route_ctrl`, `place_array`, `data_m1`, `route_data`, `data2_m1`) |
| `compose.request.json` / `compose.response.json` | the final stage (`route_data2`)'s own |
| `sampler_core.gds` | the composed cell |
| `drc.json`, `extract.json`, `sampler_core.spice` | sign-off + extracted netlist |
| `lvs.request.json`, `sampler_core.ref.spice`, `lvs.json` | the LVS run and its generated reference |
| `data-path-scan.py` / `.json` | the 19 geometric and electrical claims behind this cell's own data-path routing (13 before this increment), re-derivable and self-checking (exits non-zero if any stops holding) |
