# layout/sampler_dff

**`sampler_dff` assembly, continued: the third of the six data-path nets,
`qb`, is routed — DRC-clean, and its own device-list check found a
pre-existing, LVS-blocking pin swap on both `sampler_nand2` instances
(issue #22; the swap is filed as
[#84](https://github.com/2AMLogic/sky130-trng/issues/84)).** `qb` is
`design/sampler_core.spice`'s `NAND_S2` output node
(`XMis2pa`/`XMis2pb`'s shared PMOS drain and `XMis2na`'s NMOS drain)
driving `TG_FBS`'s own `a` terminal (`XMfsp`/`XMfsn`'s first terminal —
`XMfsp qb clk s vdd`, so `a` = `qb`, per the device-line template below) —
`nand_s2.y` (`44.18, 0.21`) to `tg_fbs.a` (`50.2, 0.21`). Where
`q`'s own east pin sat `0.77 µm` *west* of `sampler_nand2`'s internal
`met1` blob and could ignore it, `qb`'s west pin **is** that blob:
`klt extract` names it `mnab_y|mpa_y|mpb_y|nand_s2_y|y`, i.e. this net's
own output via stack, and the `0.42 µm` landing pad a via-drop puts at
`nand_s2.y` (`x = 43.97..44.39, y = 0.0..0.42`) is entirely *contained* in
it. So unlike `rst_n` — whose `a` pin sits inside the very same blob but on
a **different** net and therefore needed a three-stage li1 stub escape —
`qb` needs no stub at all, and its west landing adds no geometry whatsoever
(even the `mcon`, `44.07..44.29 x 0.10..0.32`, is an exact overlay on the
leaf's own). One `metal2`-role (`met1`) stage, `9.6 µm`, **`klt drc` clean,
0 violations, cell bbox unchanged**, `klt extract`'s net count drops from
21 to **20**. The merged net's five-device list matches
`design/sampler_core.spice` in count, class and width exactly (3 PMOS
`W=0.84`, one NMOS `W=0.84`, one NMOS `W=0.42`) and in **four** of five gate
assignments — the fifth is the finding: the `W=0.84` NMOS on this node is
gated by `rst_n` where `XMis2na` says `q`, which is the fingerprint of
`rst_n` and the data input being wired to the swapped `sampler_nand2` pins.
See "Result: `qb` fan-out" and "The `sampler_nand2` input swap this
increment found" below.

**A previous increment (issue #22): the second of the six data-path nets,
`q`, is routed — DRC-clean on the first attempt, and the first data-path
net that needs only one `gen-compose` stage (issue #22).** `q` is
`design/sampler_core.spice`'s `inv_q`'s own output pair (`XMisp`/`XMisn`)
driving `NAND_S2`'s `en` input (`XMis2pa`'s parallel PMOS gate and
`XMis2na`'s input-side series NMOS gate) — `inv_q.y` (`37.9, 1.2`) to
`nand_s2.en` (`43.075, 1.975`). Unlike `mc`, no via-then-bus split is
needed: `klayout.db` against the composed `sampler_dff.gds` (post-`mc`)
shows `met1` is completely empty across `x = 37..44.5, y = 0.8..2.2` other
than `sampler_nand2`'s own internal `met1` blob at `nand_s2`
(`x = 43.845..44.435`, the same obstruction `rst_n`/`clk`/`clkb`'s own
long hauls all had to route around at other columns), and this net's own
east pin sits `0.77 µm` west of that blob's own west edge — a route that
never crosses `x = 43.845` has no reason to detour around it at all. One
`metal2`-role (`met1`) stage vias both pins straight up from `li1` (the
same single-hop via-drop every other fan-out in this cell uses) and runs
the whole L-shaped haul — east from `(37.9, 1.2)` to `(43.075, 1.2)`, then
north to `(43.075, 1.975)`, `5.95 µm` total — entirely on `met1`, the same
single-stage recipe `clkb_seg1` already established for a one-hop route.
**`klt drc` clean, 0 violations on the first attempt, cell bbox
unchanged**, `klt extract`'s net count drops from 22 to **21** (the one
merge a two-pin net makes), and the merged net's own four-device list —
`inv_q`'s own PMOS/NMOS output pair and `NAND_S2`'s two `en`-gated
devices — matches `design/sampler_core.spice`'s
`XMisp`/`XMisn`/`XMis2pa`/`XMis2na` exactly. See "Result: `q` fan-out"
below and "What remains" for the four nets still open.

> **Superseded in part by the `qb` increment above (issue
> [#84](https://github.com/2AMLogic/sky130-trng/issues/84)).** The
> device *count*, classes and widths in that last claim hold, and three of
> the four are `XMisp`/`XMisn`/`XMis2pa` exactly — but the fourth, the
> `q`-gated `W=0.84` NMOS, sits in `XMis2nb`'s position (`vss`-adjacent,
> `$10`: gate `q`, source `vss`, drain the stack mid-node) rather than
> `XMis2na`'s (`qb`-adjacent). That is the `sampler_nand2` input swap, not
> a property of the `q` route: `q` was wired to `nand_s2`'s `en` pin where
> `design/sampler_core.spice` puts it on `a`. Same for `rst_n`'s own
> increment further below, which wired `rst_n` to both `a` pins.

**A previous increment (issue #22): the first of the six data-path nets,
`mc`, is routed — DRC-clean on the first attempt.** `mc` is
`design/sampler_core.spice`'s `XMim2p`/`XMim2n` (`inv_mc`'s own inverter
output) driving `XMfmp`/`XMfmn`'s shared drain-side pass terminal — which
`sampler_tg.source.spice`'s own device-line template (`a` = first
terminal, `b` = third) resolves to `tg_fbm`'s **`a`** pin, not `b`
(`tg_fbm`'s `b` pin is the *other* data net, `m` — a future increment, not
this one; see "Deriving which `sampler_tg` pin carries which data net"
below). A plain `met1` route between `inv_mc.y` (`21.19, 1.2`) and
`tg_fbm.a` (`25.955, 1.2`) is blocked for its entire useful height band:
`clkb_seg2`'s own `clkb_mid` backbone (a previous increment) runs a `met1`
backbone at `y ≈ 2.33` spanning `x = 24.6..29.74` — squarely between the
two pins — and `clk_bus`'s own via-drop pad at `tg_fbm.ctrlb`
(`met1`, `x = 24.39..24.81`, `y = 0.82..1.24`) sits at the same x as the
pin gap. `met2` is empty across this whole span (the only `met2` here is
`clk`'s own basement lane at `y = -1.70` and `clkb`'s two bridges, neither
of which reaches `x = 21..26` at any positive `y`), so this net vias each
end up one further plane, to `met2`, and runs a short U-shaped lane at
`y = 1.8` — up from `(21.19, 1.2)`, across to `(25.955, 1.8)`, back down to
`tg_fbm.a`. Two stages (`mc_met1`/final), no cell-bbox growth. **0 DRC
violations on the first attempt, `klt extract` merges exactly the one pin
pair a two-pin net should, and the merged net's own four-device list
matches `design/sampler_core.spice`'s
`XMim2p`/`XMim2n`/`XMfmp`/`XMfmn` exactly** — see "Result: `mc` fan-out"
below. Still open: five data-path nets, `m`/`mb`/`s`/`q`/`qb` — see "What
remains" below.

## Deriving which `sampler_tg` pin carries which data net

`layout/sampler_tg/sampler_tg.source.spice` (the hand-authored LVS
micro-reference every `sampler_tg` instance checks against) reproduces one
representative device pair's own lines byte-for-byte:
`.subckt sampler_tg a b ctrl ctrlb vdd vss` / `XMp a ctrl b vdd ...` / `XMn
a ctrlb b vss ...`, built from `design/sampler_core.spice`'s own
`XMtdp`/`XMtdn` (`TG_D`). That fixes the mapping for every transmission
gate: `a` = the device line's own **first** terminal, `ctrl` = the PMOS
gate (second terminal of the `XMxxp` line), `b` = the **third** terminal,
`ctrlb` = the NMOS gate. Reading each TG's own two device lines against
that template (and cross-checking against `clk_bus`/`clkb_bus`'s own
already-*committed, DRC-clean and `klt extract`-verified* `ctrl`/`ctrlb`
net assignments,
which independently confirm the `ctrl`/`ctrlb` half of each row):

| TG | Device lines | `a` | `ctrl` | `b` | `ctrlb` |
|---|---|---|---|---|---|
| `TG_D` | `XMtdp d clk m vdd` / `XMtdn d clkb m vss` | `d` | `clk` | `m` | `clkb` |
| `TG_FBM` | `XMfmp mc clkb m vdd` / `XMfmn mc clk m vss` | `mc` | `clkb` | `m` | `clk` |
| `TG_S` | `XMtsp mb clkb s vdd` / `XMtsn mb clk s vss` | `mb` | `clkb` | `s` | `clk` |
| `TG_FBS` | `XMfsp qb clk s vdd` / `XMfsn qb clkb s vss` | `qb` | `clk` | `s` | `clkb` |

Every `ctrl`/`ctrlb` entry above matches `clk_bus`/`clkb_bus`'s own already
-verified routing exactly (e.g. `TG_FBM`'s `ctrl` carries `clkb`, and
`clkb_seg2`'s own connectivity names `tg_fbm_ctrl` on the `clkb_mid` net) —
independent confirmation that the `a`/`b` half of the same table, derived
from the identical device lines by the identical rule, is trustworthy too.
This table is the working reference for deriving the remaining five
data-path nets' own pin positions; it is not re-derived per net below.

**A previous increment (issue #22): `clkb`'s own five-pin fan-out is
routed, DRC-clean, landing on exactly the six transistor gates
`design/sampler_core.spice` puts it on.** `clkb` is `clk`'s
differential pair, but — as `clk`'s own increment already derived and
recorded below — it cannot reuse `clk`'s own `met2` lane: the two nets'
verticals share four of five x-columns (`tg_d`/`tg_fbm`/`tg_s`/`tg_fbs`'s
`ctrl`/`ctrlb` pins sit at identical x, opposite y, on each transmission
gate), so any single `met2` lane for `clkb` would cross `clk`'s own
verticals in the middle. `clkb` instead takes the `met1` corridor `clk`'s
own final stage reserved (`y ≈ 0.40`), with two short `met1`→`met2`→`met1`
bridges (`clkb_bridge1`/`clkb_bridge2`) hopping over `sampler_nand2`'s own
internal `met1` blobs exactly where `clk`'s own long haul also had to stay
clear of them, and two east-side jogs (in `clkb_seg2`) around `clk`'s own
via-drop pads at the `tg_fbm`/`tg_s` columns, the two places a straight
drop from `clkb`'s own pin down to the corridor would otherwise run
through `clk`'s own metal on the same layer. Five stages
(`clkb_seg1`/`clkb_bridge1`/`clkb_seg2`/`clkb_bridge2`, plus the new final
stage), all `met1`/`met2`, no cell-bbox growth. **0 DRC violations, `klt
extract` merges exactly the four pin pairs a five-pin net should, and the
merged net's own six-device list matches `design/sampler_core.spice`'s
`XMpc`/`XMnc`/`XMtdn`/`XMfmp`/`XMtsp`/`XMfsn` exactly** — see "Result:
`clkb` fan-out" below. Still open: the six `m`/`mb`/`mc`/`s`/`q`/`qb`
data-path nets — see "What remains" below.

**Environment note (klayout-tools `legs[]` support): verify the installed
`klt` actually implements the request field you are about to use, not just
its own `--version` string.** The host's installed `klt`
(`~/.local/bin/klt`, a `uv tool`) reported `0.4.0+g59c2a2873c17.dirty` —
plausible-looking, same major/minor as the `klayout-tools` git checkout —
but its own `gen_compose.py` predates `connectivity[].legs[]` (issue
#1529) entirely: no `_parse_legs` function at all.
`_parse_connectivity` does not reject an unrecognized `"legs"` key, so a
request built for `legs[]` composes *without error* against this build —
every named leg's own `waypoints_um` is silently dropped, and
`route_bundle()` falls back to its default nearest-first search with no
caller-supplied steering, which can still report `routed: true` while
having drawn a *different* path than the one requested (in this case, a
straight one-jog backbone that ran directly through `clk`'s own via-drop
pad — caught only because `klt extract`'s own device-list check, not
`gen-compose`'s own `unrouted_nets`/DRC signal, disagreed with the
intended connectivity). Confirmed by installing the `klayout-tools` git
checkout (`fdc5018`, includes `legs[]` via #1536) into a scratch venv and
re-running: `entry.get("legs")` is `None` on the stale build,
`route_bundle()`'s own `explicit_legs` argument is `None` in a trace, and
the same request routes exactly as authored once the venv's `klt` — the
one this increment's own evidence was built with — is used instead. The
underlying install-staleness itself is the same class PR #80 already hit
and worked around the same way (see its own "Environment note for
reviewers") — not a tool defect on its own — but the *silent* fallback (no
error, no warning, a request field simply ignored by an older build) is a
generic tool gap: filed as
[`2AMLogic/klayout-tools#1548`](https://github.com/2AMLogic/klayout-tools/issues/1548)
(an unrecognized `connectivity[]` key, e.g. `legs`, should be a hard parse
error, not a silent no-op, since a `routed: true` response can otherwise
diverge from the caller's own intended path with no signal at all).

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

## Result: `qb` fan-out (this increment)

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (final stage, `metal2`/met1 role, 2-pin, explicit `waypoints_um`) | `nand_s2_y`'s via-drop is an exact overlay on that pin's own already-drawn met1/mcon (zero added geometry); `tg_fbs_a` vias li1→met1 at `(50.2, 0.21)` — routed as one lane `(44.18,0.21)→(44.35,0.21)→(44.35,2.0)→(50.2,2.0)→(50.2,0.21)`, **routed, 9.6 µm, 0 unrouted nets, 0 warnings** | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` (whole `sampler_dff.gds`) | **clean, 0 violations** — no DRC iteration; the one iteration this net needed was a `gen-compose` *refusal* on the destination port, before any GDS was written (see "Why the destination port is not the port table's own value" below) | `drc.json` |
| `klt extract --deck sky130` | **22 devices (11 nfet, 11 pfet)**, unchanged; `net_count` **21 → 20**, exactly the one merge a two-pin net makes. The merged net (`a\|mnab_y\|mpa_y\|mpb_y\|nand_s2_y\|qb\|tg_fbs_a\|y`) carries **5** devices — the count `design/sampler_core.spice`'s own `qb` node has — and matches it device-for-device on class and width (`$21` pfet `W=0.84` gate `q` = `XMis2pa`; `$22` pfet `W=0.84` gate `rst_n` = `XMis2pb`; `$18` pfet `W=0.84` gate `clk` = `XMfsp`; `$7` nfet `W=0.42` gate `clkb` = `XMfsn`; `$11` nfet `W=0.84`). Four of the five gate assignments match exactly. `$11`'s does not — it is gated by `rst_n` where `XMis2na` says `q` — and that is a **pre-existing** input-pin swap, not a property of this route: see below | `extract.json`, `sampler_dff.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_dff` | **mismatch, as expected** — 12/22 devices, 4/14 nets matched (up from 6/22, 3/14 before this net); three data-path nets are still unwired, no top-level cell pins are promoted, and the swap below is still open | `lvs.json` |

Cell extent unchanged (`-2.19 .. 50.47 x -3.585 .. 7.085` µm), measured on
the composed GDS: this stage adds **1.5951 µm² of met1** as a single
polygon (`44.265 .. 50.41 x 0.0 .. 2.085`) which merges with
`sampler_nand2`'s own blob into one shape spanning
`43.1 .. 50.41 x 0.0 .. 3.95` (`2.7716 µm²`) — the "drawn geometry, not
JSON net-name bookkeeping" check `rst_n` established — plus `0.0912 µm²`
of li1 in two slivers at the destination pad and one new `mcon`
(`50.09 .. 50.31 x 0.10 .. 0.32`). Nothing is added on met2.

**Why the climb is jogged 0.17 µm east before it goes up.** Above
`y = 1.085` the `nand_s2` blob narrows to a 0.17 µm-wide bar at
`x = 43.845..44.015` running to `y = 3.53`. A climb centred on the pin's
own `x = 44.18` (wire `44.095..44.265`) would leave an **0.08 µm** gap
against that bar's east edge — under sky130's 0.14 µm `met1.space.1`, and
a net-unaware deck flags a *same-net* notch just as readily as a foreign
one. Jogging first to `x = 44.35` (wire `44.265..44.435`) makes the climb
an exact overlay on the blob's own `y = 0.42..0.915` section
(`x = 44.265..44.435`) and clears the narrow bar by 0.25 µm everywhere
above it; the `y = 0.21` jog itself (wire `y = 0.125..0.295`) stays inside
the blob's own `x = 43.97..44.435` bottom section.

**Why the long haul runs at `y = 2.0`.** It is the only free met1 lane
east of the blob. Below it, `clkb_bus`'s own east segment occupies
`44.69..49.24 x 0.19..1.24` (top edge 0.675 µm away); above it,
`clk_bus`'s own via-drop pad at `tg_fbs_ctrl` occupies
`48.82..49.24 x 2.29..2.71` (0.205 µm away). `rst_n`'s own met1 via pad at
`nand_s2_a` (`44.69..45.11 x 2.5..2.92`) clears by 0.415 µm and `q`'s own
met1 (east edge `43.285`) by 0.56 µm. Nothing else is drawn on met1 east of
`x = 44.435` below the `vdd` bus (`y ≥ 4.03`), which is why one straight
run does the whole span.

**Why the destination port is not the port table's own value.** The
`sampler_tg` port table below gives `a` as local `(1.9, 1.2)` — global
`(50.385, 1.2)` on `tg_fbs`. That is the correct conductor, but `tg_fbs` is
the **last** block in the row, and a 0.42 µm landing pad centred there spans
`x = 50.175..50.595`, pushing the cell's own east bbox edge from `50.47` out
to `50.595` — the one place in this cell where a landing pad grows the cell
instead of filling it. `klayout.db` shows `tg_fbs`'s own `a` li1 strap is a
single polygon that is **solid from `x = 49.155` to `50.47` across
`y = 0.125..0.295`**, while at `y = 1.2` it is only the 0.17 µm-wide
vertical at `x = 50.3..50.47` — so the same node is reachable at
`(x, 0.21)` for a whole range of x. The first choice there, a round
`(50.0, 0.21)`, was **refused by `gen-compose`**: the landing pad is drawn
on li1 as well as met1, and at `x = 49.79..50.21` its east edge lands
0.09 µm short of that vertical's west edge (`50.3`, present for
`y > 0.295`) — under sky130's 0.17 µm `li1.space.1`, and the response said
so exactly (*"draws a pad (49.79, 0) - (50.21, 0.42) on layer (67, 20) that
comes within 0.09um of block 'core''s own drawn geometry on that layer"*).
Shifting 0.2 µm east to `(50.2, 0.21)` makes the pad **overlap** that
vertical instead of nearly missing it (pad `49.99..50.41` vs the vertical's
`50.3..50.47`, same net, so they merge into one shape), keeps its west edge
0.415 µm clear of the strap's own `49.155..49.575` lower stub, and leaves
its east edge 0.06 µm *inside* the cell's own east bbox edge. Re-checked
independently on `klayout.db`: a 0.17 µm li1 `space_check` over the strap
plus the pad reports **0** violations at `x = 50.2` (and reproduces the 1
`gen-compose` reported at `50.0`). No `2AMLogic/klayout-tools` friction
filed for this: the refusal was correct, and its diagnostic named the rule,
the offending pad's own coordinates, and the fix.

One mechanical consequence worth knowing when reading a `git diff`: the
previously-unnamed final stage (the `q` net's own L-lane) is now named
`q_bus` — so its evidence moved from `compose.*` to `q_bus.*`, freeing
`compose.*` for `qb`'s own new final stage, the same renaming
`rst_n`→`clk`→`clkb`→`mc` already did at each of their own boundaries.

**Environment note for reviewers: same install staleness, same workaround,
nothing new filed.** The host's installed `klt` (`~/.local/bin/klt`,
reporting `0.4.0`) still has the pre-`legs[]` `gen_compose.py` the `clkb`
increment documented below (no `_parse_legs`), and this cell's `clkb_seg1`/
`clkb_seg2` stages are rebuilt on every run — so every stage's evidence here
was regenerated with a scratch venv built from the `klayout-tools` git
checkout (`klt 0.4.0+ge2edd1bb15a5`), exactly as the `clkb` and `q`
increments did. Two independent confirmations that this is the same tool
build as before and not a silent drift: `python3
layout/bin/compose-cell.py layout/sampler_dff/cell.json --check` reported
"rebuild matches committed evidence" against the *pre*-`qb` tree before any
edit, and the committed artifacts' own `provenance` blocks
(`klt_version 0.4.0`, `klayout_version 0.30.12`, deck content hash
`sha256:5afac7ab…`) are byte-identical to what was already on `main`. The
underlying staleness is already filed as
[`2AMLogic/klayout-tools#1548`](https://github.com/2AMLogic/klayout-tools/issues/1548);
this increment found no new tool gap.

## The `sampler_nand2` input swap this increment found

The device-list check above is the reason this cell's increments run it at
all, and here it earned its keep: **`layout/sampler_dff/cell.json` wires
`rst_n` to each `sampler_nand2` instance's `a` pin and the data input to its
`en` pin, and `design/sampler_core.spice` requires the opposite.** Filed as
[#84](https://github.com/2AMLogic/sky130-trng/issues/84); **not** fixed
here, because fixing it re-derives two already-merged increments (`rst_n`'s
three-stage stub escape and `q`'s own route) and this repo's layout
increments are one net wide.

The leaf cell is unambiguous about which pin is which.
`layout/sampler_nand2/extract.json` (that cell's own LVS is `match`, 4/4
devices) shows pin **`a`** gating the NMOS adjacent to the output `y`, and
pin `en` gating the NMOS adjacent to `vss` — matching
`sampler_nand2.source.spice`'s own `XMna y a nm vss` / `XMnb nm en vss vss`.
`design/sampler_core.spice` puts the **data** input on the output-adjacent
device in both NAND2s (`XMimna mb m mmid vss`, `XMis2na qb q s2mid vss`), so
`nand_*.a` must carry `m`/`q` and `nand_*.en` must carry `rst_n`. The
composed GDS has it the other way round on both instances: on `qb` the NMOS
is gated by `rst_n` (should be `q`), and on `nand_m_y` the NMOS is gated by
`a` = `rst_n` (should be `m`).

**Why the leaf's own clean LVS did not catch it, and why the top level will.**
A NAND2's two inputs are functionally interchangeable, so this is not a logic
bug — and at the leaf, `a` and `en` are *structurally* interchangeable too, so
`klt lvs` matches either way (verified: swapping the two gate assignments in
`sampler_nand2.ref.spice` and re-running `klt lvs` against the unchanged
extracted leaf netlist still reports `match`, 4/4 devices). The swap only
becomes visible once the two inputs are distinguishable by what else they
connect to. Verified on a minimal symmetry-broken pair — the same four NAND2
devices, plus an inverter driving the data input exactly as `inv_q` drives
`q`:

| layout side | `klt lvs` verdict |
|---|---|
| stack as designed (data input adjacent to the output) | **`match`**, 6/6 devices, 7/7 nets |
| stack swapped (`rst_n` adjacent to the output) | **`mismatch`**, 4/6 devices, 4/7 nets, `topology: nets were paired despite a name/identity conflict — layout Q vs reference RST_N` |

So the eventual whole-cell `klt lvs` sign-off cannot pass until #84 is fixed.
Nothing about `qb` itself is affected: `nand_s2.y` ↔ `tg_fbs.a` is the same
connection under either pin assignment, which is why this increment lands as
routed rather than being held.

## Result: `q` fan-out (previous increment)

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (final stage, `metal2`/met1 role, 2-pin, explicit `waypoints_um`) | `inv_q_y` and `nand_s2_en` each via li1→met1, zero lateral distance, then routed as one L-shaped lane (`(37.9,1.2)→(43.075,1.2)→(43.075,1.975)`) entirely on met1 — **routed, 5.95 µm, 0 unrouted nets, 0 warnings** | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` (whole `sampler_dff.gds`) | **clean, 0 violations** — first attempt, no iteration needed | `drc.json` |
| `klt extract --deck sky130` | **22 devices (11 nfet, 11 pfet)**, unchanged; `net_count` **22 → 21**, exactly the one merge a two-pin net makes. The merged net's own device list is the real check: `inv_q`'s own pfet/nfet output pair (both with drain on this net, gate on `inv_q.a`) and `NAND_S2`'s two `en`-gated devices (a pfet with drain on this net, and an nfet whose drain is the internal `s2mid` node) — matching `XMisp`/`XMisn` (`inv_q`) and `XMis2pa`/`XMis2na` (`NAND_S2`) exactly, and nothing else | `extract.json`, `sampler_dff.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_dff` | **mismatch, as expected** — 6/22 devices, 3/14 nets matched (up from 1/14 before this net); four data-path nets are still unwired and no top-level cell pins are promoted | `lvs.json` |

Cell extent unchanged (`-2.19 .. 50.47 x -3.585 .. 7.085` µm). The merged
net's own met1 footprint, measured on the composed `sampler_dff.gds`, is
one polygon spanning `x = 37.69 .. 43.285, y = 0.99 .. 2.185` (`1.29 µm²`)
— its east edge (`43.285`) sits `0.56 µm` clear of `sampler_nand2`'s own
internal `met1` blob at `nand_s2` (`x = 43.845..44.435`), confirming the
route never needed to detour around it. No `2AMLogic/klayout-tools`
friction filed: the single-stage, one-hop recipe `clkb_seg1` already
proved works exactly as documented.

## Result: `mc` fan-out (previous increment)

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (`mc_met1`, `metal2`/met1 role) | `inv_mc_y` and `tg_fbm_a` each via li1→met1, zero lateral distance — **2/2 routed, 0 unrouted nets, 0 warnings** | `mc_met1.compose.request.json`, `mc_met1.compose.response.json`, `mc_met1.gds` |
| `klt gen-compose` (`mc_bus`, `metal3`/met2 role, 2-pin, explicit `waypoints_um`) | `inv_mc_y_m1` → `tg_fbm_a_m1` via a U-shaped lane (`(21.19,1.2)→(21.19,1.8)→(25.955,1.8)→(25.955,1.2)`) — **routed, 0 unrouted nets, 0 warnings** | `mc_bus.compose.request.json`, `mc_bus.compose.response.json` |
| `klt drc --deck sky130` (whole `sampler_dff.gds`) | **clean, 0 violations** — first attempt, no iteration needed | `drc.json` (at the time) |
| `klt extract --deck sky130` | **22 devices (11 nfet, 11 pfet)**, unchanged; `net_count` **23 → 22**, exactly the one merge a two-pin net makes. The merged net's own device list is the real check: two pfets (`W=0.84`) and two nfets (`W=0.42`), all with `mc` on their drain terminal — matching `XMim2p`/`XMfmp` (pfets) and `XMim2n`/`XMfmn` (nfets) exactly, and nothing else | `extract.json` (at the time) |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_dff` | **mismatch, as expected** — 6/22 devices, 1/14 nets matched; five data-path nets were still unwired and no top-level cell pins were promoted | `lvs.json` (at the time) |

One mechanical consequence of this increment worth knowing when reading a
`git diff`: the previously-unnamed final stage (the `mc` net's own U-lane)
is now named `mc_bus` — so its evidence moved from `compose.*` to
`mc_bus.*`, freeing `compose.*` for `q`'s own new final stage, the same
renaming `rst_n`→`clk`→`clkb` already did at each of their own boundaries.

Cell extent unchanged (`-2.19 .. 50.47 x -3.585 .. 7.085` µm). Before
settling on the `met2` U-lane, three `met1`-only candidates were checked
directly against the composed GDS's own drawn geometry (via
`klayout.db`, not just reasoned about) and all three collide with
`clkb_seg2`'s own backbone or its `x = 25.2` vertical excursion
somewhere in their span: a straight run at `y = 1.2` (crosses `tg_fbm.b`'s
own li1 pad, a different net, on the same layer it would need to switch
off of anyway), a `y = 1.8` U-lane taken straight through `x = 25.2`
(clips `clkb_mid`'s vertical jog there directly), and a `y = 1.8` lane
jogging north around that jog at `x ≈ 24.95..25.4` (still clips
`clkb_mid`'s own via landing pad near `tg_fbm.ctrl`, or a plain `y = 2.8`
full-height lane, which clips `clkb_mid`'s backbone itself around
`x = 25.7..26.2`, next to `tg_fbm.a`'s own pin). `met2` needed no such
iteration: empty across the whole span, so the first `met2` candidate
tried was DRC-clean.

## Result: `clkb` fan-out (previous increment)

| Stage | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (`clkb_seg1`, `metal2`/met1 role, 3-pin bundle, 2 `legs[]`) | `inv_clk_y` → `tg_d_ctrlb` → `hop1w` (a bare waypoint pin, no device) — **routed, 11.96 µm over two legs (4.84 / 7.12 µm)**, 0 unrouted, 0 warnings | `clkb_seg1.compose.request.json`, `clkb_seg1.compose.response.json`, `clkb_seg1.gds` |
| `klt gen-compose` (`clkb_bridge1`, `metal3`/met2 role, 2-pin) | `hop1w` → `hop1e`, a met1→met2→met1 hop clearing `sampler_nand2`'s own `nand_m` blob (global x `12.24..13.575`) — **routed, 2.20 µm**, 0 unrouted | `clkb_bridge1.compose.request.json/response.json`, `clkb_bridge1.gds` |
| `klt gen-compose` (`clkb_seg2`, `metal2`/met1 role, 4-pin bundle, 3 `legs[]`) | `hop1e` → `tg_fbm_ctrl` → `tg_s_ctrl` → `hop2w` — **routed, 34.39 µm over three legs (13.90 / 5.48 / 15.01 µm)**, the first and third jogging east around `clk`'s own via-drop pads at those two columns, 0 unrouted | `clkb_seg2.compose.request.json/response.json`, `clkb_seg2.gds` |
| `klt gen-compose` (`clkb_bridge2`, `metal3`/met2 role, 2-pin) | `hop2w` → `hop2e`, the second met1→met2→met1 hop, clearing `nand_s2`'s own blob (global x `43.1..44.435`) — **routed, 2.25 µm**, 0 unrouted | `clkb_bridge2.compose.request.json/response.json`, `clkb_bridge2.gds` |
| `klt gen-compose` (final stage, `metal2`/met1 role, 2-pin) | `hop2e` → `tg_fbs_ctrlb` — **routed, 4.76 µm**, 0 unrouted, 0 warnings | `compose.request.json`, `compose.response.json` |
| `klt drc --deck sky130` (whole `sampler_dff.gds`) | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **22 devices (11 nfet, 11 pfet)**, unchanged; `net_count` **27 → 23**, exactly the four merges a five-pin net makes. The merged net's own six-device list is the real check: `M$1`/`M$12` (`inv_clk` nfet/pfet, drain = `clkb`), `M$2` (`tg_d` **nfet**), `M$7` (`tg_fbs` **nfet**), `M$15` (`tg_fbm` **pfet**), `M$16` (`tg_s` **pfet**) — matching `XMpc`/`XMnc`/`XMtdn`/`XMfsn`/`XMfmp`/`XMtsp` exactly, with `clk`'s own merged group (still `a\|clk\|ctrl\|ctrlb\|...`) staying a separate net | `extract.json`, `sampler_dff.spice` |
| `klt lvs` vs. `design/sampler_core.spice`'s own `.subckt sampler_dff` | **mismatch, as expected** — 0/22 devices, 0/23 layout nets vs. 14 reference nets; the six data-path nets are still unwired and no top-level cell pins are promoted | `lvs.json` |

Geometry, measured on the composed `sampler_dff.gds`: `clkb`'s own drawn
metal is five separate merged shapes — three on `met1` (`1.69 .. 12.01 x
0.19 .. 1.41`, `13.79 .. 42.86 x 0.19 .. 2.71`, `44.69 .. 49.24 x 0.19 ..
1.24`) and two small `met2` bridges (`11.59 .. 14.21 x 0.19 .. 0.61`,
`42.44 .. 45.11 x 0.19 .. 0.61`) — that `klt extract` still resolves to
**one** electrical node, the same "drawn geometry, not JSON net-name
bookkeeping" discipline `rst_n`'s own three-stage derivation already
established. `clk`'s own `met2` polygon (`0.335 .. 49.24 x -1.785 ..
2.71`) and `clkb`'s two `met2` bridges stay four *separate* merged shapes
after `klt gen-compose`'s own region-merge pass, even though the bridges'
x spans (`11.59 .. 14.21`, `42.44 .. 45.11`) sit well inside `clk`'s own
x range — a bbox overlap, not a shape one: `clk`'s polygon is one
contiguous sheet up to `y = 2.71`, but its own drawn extent stops well
short of `y = 0.61` everywhere in that x range (the corridor `clk`'s own
increment reserved and did not consume), so the two bridges never
actually touch it. `klt drc`'s clean result is consistent with this: two
same-layer shapes that *did* overlap would either merge into one polygon
(a real short `klt extract` would also report as a merged node) or trip
a spacing rule.

## Result: `clk` fan-out (previous increment)

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

- **Three data-path nets** (`mc`, `q` and `qb` are now routed, see their
  three "Result:" sections above): `m` (`TG_D.b` <-> `NAND_M.en` <->
  `TG_FBM.b` — per "Deriving which `sampler_tg` pin carries which data
  net" above, `TG_D`'s and `TG_FBM`'s *`b`* pins, not `a`), `mb`
  (`NAND_M.y` <-> `inv_mc.a` <-> `TG_S.a`), `s` (`TG_S.b` <-> `inv_q.a` <->
  `TG_FBS.b`). `q` also still needs the cell's own output pin promoted once
  top-level pin promotion happens (see below). `m` and `s` are three-pin
  fan-outs spanning most of the cell's own width (`TG_D.b` at `x = 4.465`
  to `TG_FBM.b` at `x = 23.755` for `m`; a comparable span for `s`) and,
  unlike `mc`/`q`/`qb`, cross `sampler_nand2`'s own internal `met1` blob at
  a *foreign*-net column (the same obstruction `rst_n`'s own stub escape
  and `clk`/`clkb`'s own bridges already solved) — expect these to need a
  stub-plus-bridge recipe closer to `rst_n`'s or `clkb`'s own than `mc`'s
  or `q`'s single-lane recipes. `mb` starts on `NAND_M.y` — the same pin
  `qb` started on at the other instance, i.e. *inside* that instance's own
  met1 blob but on the blob's **own** net — so `qb`'s recipe transfers
  directly: no stub escape, but a jogged climb that keeps 0.14 µm off the
  blob's own narrow upper bar. Note also that `m`/`mb`'s own `NAND_M` pin
  assignment must follow the corrected mapping below, not the committed
  one.
- **The `sampler_nand2` input swap**
  ([#84](https://github.com/2AMLogic/sky130-trng/issues/84)): `rst_n` is
  wired to both instances' `a` pins and the data inputs to their `en` pins;
  `design/sampler_core.spice` requires the opposite. Verified LVS-blocking —
  see "The `sampler_nand2` input swap this increment found" above. This
  gates the whole-cell `klt lvs` sign-off below and should land before, or
  together with, `m`/`mb`.
- **Promoting the whole-cell external pins** (`d`, `clk`, `rst_n`, `q`,
  `vdd`, `vss`) once the above wiring exists, and the resulting
  `klt lvs` sign-off against `design/sampler_core.spice`'s real `.subckt
  sampler_dff` — the authoritative check for this cell, not yet attempted.
- **`sampler_core`**'s own six-instance wiring, and the whole-chain
  (raw-tap-to-sampled-bit) post-layout PVT campaign, both still fully
  open behind the above.
