# layout/ro_array_core-placement-poc

**Placement-only proof of concept for `ro_array_core`** —
`design/ro_array_core.spice`'s top-level entropy-source assembly: four
`ro_ring5` rings (`wstv` 0.42/0.44/0.46/0.48, matching the four already-composed
ring variants), four `ro_buf` output buffers, and a three-`xor2` combining
tree (`xa1=xor(ro1,ro2)`, `xa2=xor(ro3,ro4)`, `xa3=xor(t1,t2)=xo`). All eleven
of these instances are now DRC-clean *and* LVS-clean as standalone cells (see
`layout/README.md`) — this is the first attempt at placing them together as
one block.

Started (Increment 1) as a placement-only proof of concept mirroring
`layout/xor2-placement-poc/`'s own convention one level up the hierarchy: a
named, honestly-scoped PoC that establishes the **floorplan** half of the
problem and stops. Seven routing increments later, **Increment 8 below closes
it**: `ro_array_core_signal9_poc.gds` is `klt drc` clean and `klt lvs`
**matches** `design/ro_array_core.spice`'s own `.subckt ro_array_core`
(132/132 devices, 96/96 nets). The directory name is now historical — the
per-increment `signal*` file sets are kept as the append-only record of how
it got there, and the "What this does NOT establish" section below is
preserved as Increment 1's own milestone text with each item's resolution
marked inline.

## Increment 8: the `vdd` supply bus routed — `ro_array_core` is DRC-clean and LVS-clean (this update)

Closes the last open net. Increment 7 left `vdd` — the buffer/XOR-tree
supply, distinct from the four per-ring `vddrN` starve domains — as **seven
separate nets** (one per `ro_buf`/`xor2` instance, `device_count` 2/2/2/2/
10/10/10), because `vdd` ties to each instance's own `nwell` and `nwell` has
no chip-wide global identity the way the p-substrate does (Increment 5's
finding): two separately-placed cells' nwells are one electrical node only if
a real strap physically joins them. Increment 7's own closing prediction —
that `vdd` "is the same shape" as `t2` and needs "its own set of met1 stubs
per buffer/XOR tap plus a met3 bus" — **holds exactly**, and that is what
this increment draws.

```
$ python3 vdd-tap-scan.py                                      # -> vdd-tap-scan.json
all_taps_clear: true  (7/7 taps on vdd li1, via landing clear, stub met1-clear)
$ klt gen-compose signal8.compose.request.json --format json   # -> signal8.compose.response.json, ro_array_core_signal8_poc.gds
unrouted_nets: []   (4 x 1.76um buffer stubs, 3 x 1.5um XOR stubs)
$ klt drc ro_array_core_signal8_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal8_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 102 (unchanged), pin_count: 92 (unchanged)

$ klt gen-compose signal9.compose.request.json --format json   # -> signal9.compose.response.json, ro_array_core_signal9_poc.gds
unrouted_nets: []   (6 legs, 58.2 / 58.3 / 58.3 / 63.315 / 31.0 / 63.74 um)
$ klt drc ro_array_core_signal9_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal9_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 96 (down from 102), pin_count: 86

$ python3 array-reference.py                                   # -> ro_array_core.ref.spice
$ klt lvs lvs.request.json --format json                       # -> lvs.json
status: match, devices 132/132, nets 96/96
$ python3 lvs-negative-controls.py                             # -> lvs-negative-controls.json
all_controls_detected: true   (both deliberately-wrong references -> mismatch)
```

### `signal8` — seven met1 promotion stubs, measured before they were drawn

Every tap this directory has ever used is tapped **by coordinate** on a leaf
cell's own interior conductor (none of the composed leaf cells expose declared
pins), and Increment 6's finding 1 established what that costs: `klt
gen-compose` models a placed block as an opaque bbox with no obstacle model of
its interior metal, so a stub that starts inside a block can run straight
through another net's metal and short to it **silently** — `unrouted_nets: []`
and `klt drc` clean, wrong only in `klt extract`'s net list. `vdd` needed seven
such stubs at once, so `vdd-tap-scan.py` (committed, with its
`vdd-tap-scan.json` output) measures all seven first, **against the composed
array** (`ro_array_core_signal7_poc.gds`) rather than against the standalone
leaf cells — strictly stronger than a per-cell scan, because the composite's
met1 also contains every inter-cell backbone Increments 2-7 committed
(`rn1`-`rn4`, `ro1`-`ro4`, the buffer `vss` bus, `t1`, and Increment 7's own
`y_m1`/`b_m1` stubs), which a per-cell scan cannot see at all. For each tap it
checks three things: the tap point is inside one merged li1 polygon whose area
matches the leaf cell's own `vdd` component (so the tap is on `vdd`, not a
neighbour); an `mcon`-sized square centred on it lies wholly inside that
polygon (so the via lands); and the drawn stub, grown by half its width plus
sky130's 0.14 µm `met1.space`, touches **no** met1 anywhere in the composite.
`vdd` carries no met1 of its own before this increment, so *any* met1 contact
would be a foreign net — i.e. exactly Increment 6's silent short. All seven
report clear, and all seven then composed first-try with no discarded probes.

- **The four `ro_buf` taps** are the cell's own authoritative `TAP_N` port,
  block-local `(-1.12, 4.24)` — the coordinate this README's table has carried
  since Increment 2, now exercised for real. Each gets a met1 port `1.76 µm`
  north at absolute `y = 6.0`, just clear of `ro_buf`'s own bbox top (`4.6`).
  `ro_buf` contains **zero** met1 shapes of its own, so the only met1 the scan
  has to clear is the array's own committed backbones; the nearest is
  `rnN`'s lane at `y = 5.6`, which stops `1.37 µm` west of each buffer's `vdd`
  column.
- **The three `xor2` taps resolve a coordinate this README has flagged
  `*approx*` since Increment 2.** The candidate table below lists `xa1`'s
  `vdd` at `(10.885, 23.585)` "approx" — that point is **not on li1 at all**
  (checked directly; it lands in a gap between two rails). `xor2`'s `vdd` is
  one 27-shape li1-only component of area `17.07285 µm²`, and the tap this
  increment uses, block-local `(-1.12, 13.8)`, is the widest pad on it with a
  clear north escape. Each gets a met1 port `1.5 µm` north at absolute
  `y = 27.885`, still inside the block (`bbox` top `28.67`) — the promotion
  tip does **not** need to leave the cell, because met2 crosses over the
  cell's own metal without touching it and only drops a via at the tip.

`klt extract` confirms the stubs merged nothing: `net_count` stays `102`,
`device_count` stays `132`, and the net-by-net diff against
`signal7.extract.json` shows exactly seven *extensions* — the four 2-device
buffer `vdd` nets become `vdd|vdd_b1`..`vdd|vdd_b4`, the three 10-device XOR
`vdd` nets become `vdd|vdd_x1`..`vdd|vdd_x3`, every device count unchanged.

### `signal9` — a six-leg met2 bus, and why it had to be a chain

The bus treats the whole `signal8` GDS as one placed block and routes on
`"metal3"` (met2), the same technique Increment 7 used for `t2`. Two things
shaped its geometry:

1. **The met2 plane is not empty.** `klt gen-compose`'s own routability checks
   look at the block's *drawn* geometry on the route layer (its "self-net
   drawn-metal check"), and this composite has nine met2 shapes already: each
   `ro_ring5` carries **two** full-width met2 rails of its own (`vddr` and
   `vss`, `y ∈ [-3.085, 2.21]` and `[4.19, 6.085]`, spanning most of each
   ring's width — see `layout/ro_ring5/README.md`'s fourth stage), plus
   Increment 7's `t2` bridge (`x ∈ [37.195, 78.87]`, `y ∈ [19.185, 31.085]`).
   So the row-1 bus lane sits at `y = 7.5`, `1.2 µm` above every ring's upper
   met2 rail, and the two XOR-to-XOR legs deliberately avoid the `t2` bridge:
   `xa1→xa2` hops **over** the top at `y = 28.9` (stopping `2.45 µm` short of
   `t2`'s riser at `x = 37.405`), while `xa2→xa3` drops **under** it to
   `y = 10.5`, because a straight top-lane hop from `xa2` to `xa3` would cross
   `t2`'s own `y = 31.0` span at `x = 63.705` — a met2-on-met2 short, i.e. two
   merged shapes on one layer, which no rule deck can see.
2. **`waypoints_um` is only accepted for a two-pin net**, so a single seven-pin
   `vdd` entry could not be hand-routed at all — it would fall to the
   spanning-tree router with no obstacle model of the ring rails above. The
   bus is therefore declared as **six separate two-pin `vdd` entries**, each
   with its own waypoints. `gen-compose` rejects a leg that crosses an
   already-accepted leg of the same request *unless the two share a pin*
   ("shared pin -- an intended merge, not a short"), so the six legs form a
   **chain** — `buf4-buf3-buf2-buf1-xa1-xa2-xa3` — rather than a star or a
   trunk with taps: consecutive legs share a pin and are exempt, and every
   non-consecutive pair was laid out on disjoint lanes so nothing else
   touches. A star from one trunk would have been rejected leg-by-leg.

Net-by-net diff against `signal8.extract.json`: exactly the intended merge and
nothing else. The seven `vdd` nets (`4 x 2 + 3 x 10 = 38` devices) become one
38-device net `vdd|vdd_b1|vdd_b2|vdd_b3|vdd_b4|vdd_x1|vdd_x2|vdd_x3`;
`net_count` drops `102 → 96` (exactly the six merges), `device_count` stays
`132`.

### The LVS match, and the reference it needed

`lvs.json` reports **`status: match`, 132/132 devices, 96/96 nets** against
`design/ro_array_core.spice`'s own `.subckt ro_array_core`. That answers this
README's own "Suggested next steps" item 6 — including the open question it
raised, which turned out to be real:

**`layout/bin/compose-cell.py`'s `lvs.dependencies` mechanism genuinely cannot
express this reference.** It rewrites a flat list of dependency subckt *names*
with **one** shared `lvs.params` dict, and `ro_array_core` needs the *same*
`ro_ring5` subckt four times with four different `wstv=` overrides
(0.42/0.44/0.46/0.48). `array-reference.py` (committed) is the narrowest
answer: it reuses `compose-cell.py`'s own `extract_subckt`/`build_reference`
rewrite verbatim — same substitutions, same `Cld` drop, same unit-suffix fix
(klayout-tools#1492) — but calls it four times over the ring hierarchy
(`ro_nand2`/`ro_stage`/`ro_ring5`), renaming each pass's copies to `*_r1`..
`*_r4` so the four sizings coexist in one file, then repoints
`ro_array_core`'s `xr1`-`xr4` at them. The renames exist only inside the
generated reference (so `flatten_reference: true` has four distinct
definitions to inline); nothing in `design/` or in the layout is renamed.
Folding this back into `compose-cell.py` as a per-dependency `params`
override — and with it promoting this directory into a `layout/ro_array_core/`
`cell.json` recipe with `--check` reproducibility and the unit-test coverage
this repo's CI requires of netlist-rewriting code — is deliberately left as
follow-up, not smuggled into this increment.

**The match is verified to be discriminating, not vacuous.**
`lvs-negative-controls.py` (committed, with its `lvs-negative-controls.json`
output, and non-zero exit if either control passes) re-runs the identical
comparison against two deliberately-wrong references, with the layout side
byte-identical in all three runs:

| Control | Perturbation (reference side only) | Result |
|---|---|---|
| `width` | ring 4's starve devices resized `0.48 µm` → `0.42 µm` (ring 1's `wstv`), topology untouched | `mismatch`, 122/132 devices |
| `topology` | `xa1`/`xa2`'s second XOR inputs crossed (`ro2` ↔ `ro3`), every device parameter untouched | `mismatch`, 112/132 devices |

The first matters specifically for this block: `ro_array_core`'s entire
premise is four rings deliberately sized apart (DR-0003), and the four
physically distinct ring GDS cells under `layout/` differ *only* in that
width — if `klt lvs` did not compare `W`, four identical rings would have
matched this reference just as happily and the four separate cells would be
unverified. They are not: the sizing is compared, and it matches.

### What is still open after this increment

- **`ring1..4`'s and `xa1..3`'s own `vss` taps are still not drawn.** Not
  LVS-blocking — `klt extract`'s sky130 deck merges every un-isolated NMOS
  body into one substrate node (Increment 5's finding), which is why the
  match above is real without them — but a fabricated die needs the explicit
  low-impedance strap the substrate's own (unmodelled, per DR-0005 finding 3)
  resistance does not provide.
- **This is a PoC directory, not a `layout/ro_array_core/` cell.** Its
  `signal*.compose.request.json` files are hand-maintained, with no
  `compose-cell.py --check` reproducibility, and `array-reference.py` lives
  here rather than in `layout/bin/` (deliberately: `layout/bin/**` is on this
  repo's PR-blocking CI path and that code is unit-tested there — promoting
  the script belongs with promoting the recipe).
- **No array-level parasitic extraction or post-layout PVT run exists yet.**
  `sim/post-layout-ro-ring5-assembled/` covers a single ring; the whole
  array's extracted parasitics — and therefore DR-0003 §8's explicitly
  unmeasured `wstv` inter-ring decorrelation question, which needs real
  inter-ring coupling to answer — are untouched by this increment.
- **`sampler_core`/`sampler_dff` remain untouched**, so the block-level
  layout the Chipalooza brief asks for is still only its entropy-source half.

### Reproduce this increment

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
# klt's shared install churns between (and within) sessions -- pin it, per
# layout/README.md's "Correcting the curation note":
#   python3 -m venv /tmp/klt-venv && /tmp/klt-venv/bin/pip install \
#     "git+https://github.com/2AMLogic/klayout-tools@c6dbf66c53c6e9a73c4f5ae5e41a98e8fe414252"
cd layout/ro_array_core-placement-poc
python3 vdd-tap-scan.py                                      # -> vdd-tap-scan.json (all_taps_clear: true)
klt gen-compose signal8.compose.request.json --format json   # -> signal8.compose.response.json, ro_array_core_signal8_poc.gds
klt drc ro_array_core_signal8_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal8_poc.gds --deck sky130 --format json  # -> 132 devices, 102 nets
klt gen-compose signal9.compose.request.json --format json   # -> signal9.compose.response.json, ro_array_core_signal9_poc.gds
klt drc ro_array_core_signal9_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal9_poc.gds --deck sky130 --format json  # -> 132 devices, 96 nets
python3 array-reference.py                                   # -> ro_array_core.ref.spice
klt lvs lvs.request.json --format json                       # -> lvs.json (match, 132/132, 96/96)
python3 lvs-negative-controls.py                             # -> lvs-negative-controls.json (both mismatch)
```

## Increment 2: forward ring→buffer signal chain routed

The candidate coordinate table below (from the placement-only increment) is
now **exercised for real**: `en1..en4` and the four `vddrN` domains are
exposed as top-level pins straight off each ring's own already-formed
internal node (no new routing needed — each ring's `en`/`vddr` is already a
single electrical node inside its own composed GDS), `ro1..ro4` are exposed
as top-level pins straight off each buffer's own `y` output the same way, and
the four `rn1..rn4` legs (`ro_ring5.ro` → `ro_buf.a`) are **newly, really
routed** on `"metal2"` (met1) — the first inter-cell wiring this directory
has drawn.

```
$ klt gen-compose signal.compose.request.json --format json   # -> signal.compose.response.json, ro_array_core_signal_poc.gds
unrouted_nets: []
$ klt drc ro_array_core_signal_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal_poc.gds --deck sky130 --format json
device_count: 132 (66 nfet + 66 pfet), net_count: 108, pin_count: 98
```

`132` devices is unchanged from the placement-only increment (still the
right cells, right multiplicities). `net_count` drops from `112` to `108` —
exactly the four `rn1`-`rn4` merges, confirmed directly against
`signal.extract.json`'s own net list: `en1`-`en4`, `vddr1`-`vddr4` and
`ro1`-`ro4` each land on their own distinct net (the four `vddrN` domains
stay electrically isolated from each other, matching DR-0003's per-ring
starve-supply isolation intent), and `rn1`-`rn4` each merge exactly the
intended pair (e.g. `rn1`'s net carries labels `a`, `g_a`, `rn1`, `ro`,
`s4_y`, `y` — the extra labels are `ro_ring5`'s and `ro_stage`'s own
internal aliases for the same physical node, persisting through the
hierarchy exactly as `layout/README.md`'s "Correcting the curation note"
and `ro_ring5-connectivity-poc`'s own precedent already document, not a
short to anything else). No LVS attempted — see "What this does NOT
establish" below for what still needs to land first.

**The one new floorplan finding**: `gen-compose` rejects a route whose final
leg drops straight down (or up) into a block's interior toward a pin that
sits well inside that block's own bounding box — its own diagnostic calls
this out by measured distance (`"backbone's 0.17um-wide drawn path crosses
3.155um through its own pin's block 'buf1' -- more than that pin's own
2.82um edge margin"`), rather than failing silently or drawing a violation.
`ro_buf`'s own `a` pin sits mid-block (not at an edge), so the fix mirrors
`layout/ro_ring5/README.md`'s point 6: approach on `"metal2"` from just
outside the block at the pin's own `y`, then run the *whole* final leg
horizontally at that `y` into the pin, rather than dropping vertically from
a channel above it. Not filed as a `klt` tool gap: the diagnostic is
correct, specific, and actionable exactly as given.

### Reproduce this increment

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/ro_array_core-placement-poc
klt gen-compose signal.compose.request.json --format json   # -> signal.compose.response.json, ro_array_core_signal_poc.gds
klt drc ro_array_core_signal_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal_poc.gds --deck sky130 --format json  # -> 132 devices, 108 nets
```

## Increment 3: buffer→XOR "a" leg routed for both first-stage XORs

Continues directly from Increment 2's own "Suggested next steps" item 2:
`ro1` (`buf1.y`, already a top-level pin) is now **really routed** into
`xa1`'s `a` input, and `ro3` (`buf3.y`) into `xa2`'s `a` input — the first
routing this directory has drawn between **row 1** (rings/buffers) and
**row 2** (the XOR combining tree), an 18.2 µm vertical span most of which
is empty floorplan gap.

```
$ klt gen-compose signal2.compose.request.json --format json   # -> signal2.compose.response.json, ro_array_core_signal2_poc.gds
unrouted_nets: []
$ klt drc ro_array_core_signal2_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal2_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 106 (down from 108), pin_count: 96
```

`xa1`/`xa2` first needed their own `a`/`b` ports declared on the `blocks[].cell`
references (neither was declared in Increment 2, since nothing routed to them
yet) — `layout/xor2/core.compose.response.json`'s own authoritative `inva_a`/
`invb_a` ports (`x_um: -3.44`/`14.735`, `y_um: 6.81`, li1, `width_um: 0.17`,
`direction_deg: 180`), the same confirmed-not-approximate coordinates
Increment 2's own table already flagged as the recommended tap. Net count
drops by exactly 2 (108→106): `signal2.extract.json`'s own `merged_net_labels`
confirms each drop is `ro1`/`ro3` joining **only** its intended `a`-labelled
net (`a|inva_a|mn12_g0|mp13_g0|ro1|y` and the `xa2` equivalent for `ro3`) —
diffed net-by-net against Increment 2's own committed `signal.extract.json`,
nothing else in the design changed labels (the numbered `$N` anonymous nets
are KLayout's own harmless renumbering, not a real change).

**Two floorplan/tool findings, both empirically confirmed rather than
theorized:**

1. **The escape from `buf1.y`/`buf3.y` needed its own fix, independent of
   the "approach the destination horizontally" rule Increment 2 found.**
   The first attempt (`waypoints_um` starting with a vertical move straight
   off `buf1.y`) failed with `gen-compose`'s own diagnostic naming the
   *source* block: `"backbone's 0.17um-wide drawn path crosses 3.485um
   through its own pin's block 'buf1' -- more than that pin's own 0.17um
   edge margin"`. `buf1.y`/`buf3.y` sit only `0.085 um` from `ro_buf`'s own
   east bbox edge (`direction_deg: 0`, i.e. the pin's stub opens eastward),
   so a waypoint that moves *north* while still inside that 0.085 µm-wide
   column reads as "crossing" the whole vertical extent of `buf1`'s bbox
   above the pin, not just the tiny horizontal sliver the margin allows.
   The fix: escape **east** past the block's own edge first (`(50.215,1.2)
   -> (50.5,1.2)`, `50.5 > buf1`'s own `x1=50.3`), *then* turn north into the
   clear inter-row channel. Once outside the block, the rest of the route
   (a shared-style corridor at `y=8.0`/`9.0`, distinct per net so their
   backbones cannot intersect, then a vertical approach fully outside `xa1`/
   `xa2`'s own bbox, only turning onto the target's exact `y=19.395` after
   crossing into it) composed on the first attempt with **zero** `notes[]`
   entries — i.e. once the source-side margin fix was applied, `xa1.a`'s own
   3.445 µm in-block crossing (exactly matching the distance
   `layout/xor2/core.compose.response.json` itself reports from `xor2`'s own
   west-most bbox edge to `inva_a`) needed no special-casing at all.
2. **`b` (`xa1`/`xa2`'s second XOR input, `ro2`/`ro4`) is deliberately NOT
   wired this increment — routing it naively would risk a real short with
   `a`, not just a `gen-compose`-detected conflict.** `xor2`'s own `a` and
   `b` ports sit at the **identical** `y=19.395` (both `inva_a`/`invb_a`
   direction `180`, i.e. both openable only from the block's west edge), so
   a straight-line approach to `b` from the west would have to physically
   run *through* `a`'s own already-accepted backbone (`x` 0..3.445) before
   reaching `b` at `x=21.62` — `gen-compose`'s #1057 same-request
   backbone-overlap check would catch this (a loud `unrouted_nets[]` entry,
   not a silent extraction-time short), so it was not attempted blind. A
   probe attempt using a *closer*, block-interior vertical approach (turning
   onto `y=19.395` only ~1.1 µm before `b`, well clear of `a`'s own segment)
   did compose (`unrouted_nets: []`) but left a **real, `klt drc`-caught**
   `met1.space.1` violation near `buf2`'s own escape jog (not near `xa1` at
   all) — so `b`'s routing is a genuinely separate, still-open problem, not
   a copy-paste of `a`'s recipe with different numbers. That probe's GDS was
   not committed (its output path collided with, and was regenerated back
   over, this increment's own `signal2` evidence — the correct `signal2.*`
   files above were re-verified clean immediately after). Whoever attempts
   `b` next should budget a fresh escape-margin derivation for `buf2.y`/
   `buf4.y` rather than reusing `buf1`/`buf3`'s numbers unchanged.

**Still not a DRC/LVS-clean `ro_array_core`** as of Increment 3: `ro2`/`ro4`
into `xa1.b`/`xa2.b` (open per finding 2 above — resolved by Increment 4
below), `vdd`/`vss` (rings, buffers *and* XORs all share `vss`; `vdd` is
separate and only feeds buffers/XORs), the `t1`/`t2`/`xo` combining-tree
wiring (`xa1`/`xa2`'s outputs into `xa3`, and `xa3`'s own output), and
therefore any `klt lvs` attempt. Not re-attempted: `compose-cell.py`-style
`--check` reproducibility for this multi-file, multi-stage POC (unlike the
single-cell `layout/<cell>/cell.json` recipe, this directory's
`signal*.compose.request.json` files are hand-maintained, same as
Increment 2 left them).

### Reproduce this increment

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/ro_array_core-placement-poc
klt gen-compose signal2.compose.request.json --format json   # -> signal2.compose.response.json, ro_array_core_signal2_poc.gds
klt drc ro_array_core_signal2_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal2_poc.gds --deck sky130 --format json  # -> 132 devices, 106 nets
```

## Increment 4: buffer→XOR "b" leg routed for both first-stage XORs (this update)

Resolves Increment 3's own finding 2: `ro2` (`buf2.y`) is now **really
routed** into `xa1`'s `b` input, and `ro4` (`buf4.y`) into `xa2`'s `b`
input — the second and final buffer→XOR leg for the two first-stage XORs,
using the same `b` ports Increment 3 already declared on the `blocks[].cell`
references but left unwired.

```
$ klt gen-compose signal3.compose.request.json --format json   # -> signal3.compose.response.json, ro_array_core_signal3_poc.gds
unrouted_nets: []
$ klt drc ro_array_core_signal3_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal3_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 104 (down from 106), pin_count: 94
```

`signal3.extract.json`'s own `merged_net_labels` confirms each of the two
new merges joins **only** its intended `b`-labelled net (`ro2` lands on
`a|b|invb_a|mn12_g1|mp24_g0|ro2|y`, `ro4` on the `xa2` equivalent) —
diffed against Increment 3's own committed `signal2.extract.json`, nothing
else changed labels. The extra `a` label on `xor2`'s own `b` net (and vice
versa on `a`'s net, back in Increment 3) is `xor2`'s own internal alias
reuse, the same harmless-label phenomenon `layout/README.md` and
`ro_ring5-connectivity-poc` already document — not a short between the
design's actual `a` and `b` nets.

**Two more findings, both empirically confirmed, neither requiring a
`2AMLogic/klayout-tools` tool-gap filing (the diagnostics below were both
specific and actionable):**

1. **A structural rule not previously exercised: `gen-compose` rejects a
   backbone that crosses through a *third*, unrelated block's own bounding
   box, even when that block sits well above the row being routed through.**
   The first attempt routed `ro2`/`ro4` in a channel *above* `xa1`/`xa2`'s
   own row (`y=20.5`/`21.5`, i.e. higher than the `y=19.395` pin row) so as
   to clear both of `xor2`'s already-used `y=8.0`/`9.0` source-side
   channels entirely. `gen-compose` rejected both nets with a precise
   diagnostic: `"backbone's 0.17um-wide drawn path crosses 24.14um through
   unrelated block 'xa2''s bbox (including its own edge, within half the
   route's width) -- the route is not point-to-point between only the two
   connected blocks"` (and the `xa3` equivalent for `ro4`) — `xa1`/`xa2`'s
   own bbox extends up to `y=26.655` (`xor2`'s composed height, per
   `layout/xor2/core.compose.response.json`'s `bbox_um`), so a route merely
   *above the pin row* is not automatically clear of the block's own full
   footprint. This is a different failure mode than Increment 2's
   block-interior edge-margin rule (that one was about the route's *own*
   source/destination block; this one is about an *uninvolved third* block
   the backbone happens to pass over) but the same practical lesson: know
   every placed block's full `bbox_um`, not just the row it visually reads
   as occupying.
2. **The corridor between row 1 and row 2 has room for exactly one more
   pair of dedicated channels, found by reasoning about the two existing
   backbones' own vertical-segment extents rather than by trial and error.**
   `ro1`'s vertical rise (`x=50.5`) only occupies `y` `1.2`-`8.0`; `ro3`'s
   *source-side* vertical (`x=161.1`) only occupies `y` `1.2`-`9.0`; `ro3`'s
   *destination-side* vertical (`x=28.47`) occupies `y` `9.0`-`19.395`. A
   horizontal run at `y=8.5` (strictly between `8.0` and `9.0`) crosses
   `x=50.5` above `ro1`'s vertical's top and `x=28.47` below `ro3`'s
   vertical's bottom — clear of both — which is exactly `ro2`'s recipe
   (`buf2.y` escape at `(105.8, 1.2)` -> `(105.8, 8.5)` -> `(20.5, 8.5)` ->
   `(20.5, 19.395)` -> pin `xa1.b` at `(21.62, 19.395)`). `ro4` doesn't need
   to clear `x=28.47` at all (its own destination, `xa2.b` at `x=50.59`, sits
   *east* of that column), so a plain `y=10.0` channel — above both `ro1`'s
   and `ro3`'s source-side verticals' tops (`8.0`/`9.0`) — suffices:
   `buf4.y` escape at `(216.4, 1.2)` -> `(216.4, 10.0)` -> `(49.5, 10.0)` ->
   `(49.5, 19.395)` -> pin `xa2.b` at `(50.59, 19.395)`. Both escapes use
   Increment 3's own generalized rule (escape east past the source block's
   *own* `x1` edge, translated to `buf2`/`buf4`'s actual placement — `buf2`
   `x1=105.6` -> escape `105.8`; `buf4` `x1=216.2` -> escape `216.4` — not
   copy-pasted from `buf1`/`buf3`'s absolute numbers), confirming the prior
   increment's own guidance that a literal copy would have been wrong.

**`ro_array_core`'s forward ring→buffer→XOR signal path is now fully routed
for both first-stage XORs (`xa1`, `xa2`) — all four of `ro1`-`ro4` reach
their intended `a`/`b` inputs.** Still not a DRC/LVS-clean `ro_array_core`:
`vdd`/`vss` (rings, buffers *and* XORs all share `vss`; `vdd` is separate
and only feeds buffers/XORs — eleven taps total, the largest remaining
unknown per the "Suggested next steps" list below), the `t1`/`t2`/`xo`
combining-tree wiring (`xa1`/`xa2`'s outputs into `xa3`, and `xa3`'s own
output), and therefore any `klt lvs` attempt. Not re-attempted (same as
every prior increment): `compose-cell.py`-style `--check` reproducibility
for this multi-file, multi-stage POC.

### Reproduce this increment

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/ro_array_core-placement-poc
# klt's shared install has been observed to churn mid-session below the
# blocks[].cell request shape this directory depends on -- pin it in a venv
# per layout/README.md's "Correcting the curation note":
#   python3 -m venv /tmp/klt-venv && /tmp/klt-venv/bin/pip install \
#     "git+https://github.com/2AMLogic/klayout-tools@c6dbf66c53c6e9a73c4f5ae5e41a98e8fe414252"
klt gen-compose signal3.compose.request.json --format json   # -> signal3.compose.response.json, ro_array_core_signal3_poc.gds
klt drc ro_array_core_signal3_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal3_poc.gds --deck sky130 --format json  # -> 132 devices, 104 nets
```

## Increment 7: `t2` routed via a met2 bridge, without touching `xor2`'s own leaf cell

Resolves the `t2` half of Increment 6's own finding 3 (`vdd` is still open,
see below). Increment 6 predicted that reaching `"metal3"` (met2) would need
a met1 promotion **inside `xor2`'s own leaf cell** first, since met3's
via-drop is single-hop-only and cannot reach a bare li1 pin. **That
prediction does not hold**: the promotion can be done entirely at *this*
directory's own array-composition level, with two short met1 stub routes
added on top of the already-committed `signal5` GDS — no change to
`layout/xor2/cell.json`, no re-verification of the standalone `xor2` cell
needed.

Three new gen-compose calls, each first-try clean (no discarded probes this
time):

```
$ klt gen-compose signal6.compose.request.json --format json   # -> signal6.compose.response.json, ro_array_core_signal6_poc.gds
unrouted_nets: []
$ klt drc ro_array_core_signal6_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal6_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 103 (unchanged), pin_count: 93

$ klt gen-compose signal7.compose.request.json --format json   # -> signal7.compose.response.json, ro_array_core_signal7_poc.gds
unrouted_nets: [], t2 route_length_um: 56.875
$ klt drc ro_array_core_signal7_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal7_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 102 (down from 103), pin_count: 92
```

**`signal6` — two met1 promotion stubs, all `"metal2"` role (same layer role
every prior increment in this directory already uses), on top of the full
11-block floorplan plus every net routed through Increment 6:**

- `xa2.y` (the `t2` net's true source, li1-only, local `(1.55, 13.0)`) gets a
  second, hand-declared port `y_m1` on met1 at local `(1.55, 14.4)` — `1.4 µm`
  further along the *same* north escape column `xor2-y-escape-scan.py`
  already measured clear (window `x ∈ [1.340, 2.690]`), just stopping short
  of the cell's own top edge instead of continuing all the way to the
  external corridor the way `t1`'s route does. A `"metal2"`-role route
  between the two (`xa2.y` → `xa2.y_m1`) draws the via and the short stub:
  `route_length_um: 1.4`.
- `xa3.b` (`t2`'s eventual destination, li1-only, local `(14.735, 6.81)`,
  the same `inva_a`/`invb_a`-family port Increments 3/4 already proved
  approachable from the west at `y = 19.395`) gets a second port `b_m1` on
  met1 at local `(13.835, 6.81)` — `0.9 µm` further *west*, inside the exact
  lane Increment 4's own `ro4` route already proved clear at this position
  on `xa2`'s copy of the same cell (`ro4`'s backbone runs `x ∈ [49.5,
  50.59]` at `y = 19.395` on `xa2`; by translation the equivalent span on
  `xa3` is `x ∈ [78.47, 79.56]`, and `13.835`'s absolute position `78.66`
  sits inside it). A `"metal2"`-role route (`xa3.b` → `xa3.b_m1`) draws this
  stub: `route_length_um: 0.9`.

Net-by-net diff against `signal5.extract.json` (unaffected `$N` renumbering
aside): the only real change is `xa3`'s own `b` net (`a|b|invb_a|mn12_g1|
mp24_g0`, 4 devices) gaining exactly the new label `b3` — same
`device_count`, same net, nothing merged. `t2`'s own net (`t2|y`, 4 devices,
still a bare-pin promotion) is unchanged too. `net_count` stays `103`, as
expected: these are two *extensions* of already-existing nets, not new
connections between different nets.

**`signal7` — the met2 (`"metal3"`) bridge, over the top of everything.**
Treats the whole `signal6`-composed GDS as **one** placed block (a
`blocks[].cell` reference to `ro_array_core_signal6_poc.gds`, the same
technique every leaf/ring cell in this repository already uses one level
down), with two hand-declared ports at the two new met1 stub tips' absolute
coordinates (`xa2` origin `(35.855, 12.585)` + local `y_m1` = `(37.405,
26.985)`; `xa3` origin `(64.825, 12.585)` + local `b_m1` = `(78.66,
19.395)`), and a single `"metal3"`-role route between them at
`y = 31.0` — `2.33 µm` above every row-2 block's own bbox top (`28.67`,
per Increment 6) and a full different physical layer from `t1`'s own met1
backbone, which happens to run underneath part of this same span at
`y = 29.5`. Met3's single-hop via-drop rule is satisfied on both ends,
because both ends are now genuinely met1 (courtesy of `signal6`), not bare
li1 — exactly the fix Increment 6 called for, just executed one level
higher than predicted.

Net-by-net diff against `signal6.extract.json`: exactly the intended merge,
`t2|y` (4 devices, `xa2`'s `y`) plus `a|b|b3|invb_a|mn12_g1|mp24_g0`
(4 devices, `xa3`'s `b`) into one 8-device
`a|b|b3|invb_a|mn12_g1|mp24_g0|t2|y` — nothing else moved. `net_count` drops
`103` → `102`, `device_count` stays `132`.

**`t2` is now really routed** (`xa2.y` → `xa3.b`), completing the whole XOR
combining tree's *inputs* (`t1` from Increment 6, `t2` here); `xa3.y` (`xo`)
remains exposed as a bare top-level pin, unchanged. **Still not a DRC/LVS-clean
`ro_array_core`**: `vdd` (the buffer/XOR-tree supply, still seven separate
nets) is the one remaining open net, `ring1..4`'s and `xa1..3`'s own `vss`
taps are still un-routed (not LVS-blocking, per Increment 5's substrate
finding), and therefore any `klt lvs` attempt is still open.

**Finding: the met1-promotion-inside-the-leaf-cell prediction was
unnecessarily conservative.** Increment 6 reasoned from `xor2`'s own leaf
cell inward (`xor2`'s `y` and `ro_buf`'s ports are li1-only *inside that
cell*, so a met3 hop looked like it needed a leaf-cell change to fix). But
`klt gen-compose`'s `blocks[].cell` mechanism lets any already-placed
block gain *additional* hand-declared ports at any layer, at any point
already proven clear by an earlier increment's own routed geometry — so
the promotion only needs to happen at whichever composition level is doing
the connecting, not inside the cell that happens to own the physical pin.
The same technique should generalize to `vdd`: promote each buffer's/XOR's
own `vdd` tap to met1 with a short local stub (mirroring this increment's
`y_m1`/`b_m1` recipe), then bus them together on `"metal3"`, entirely at
this directory's own level.

### Reproduce this increment

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/ro_array_core-placement-poc
klt gen-compose signal6.compose.request.json --format json   # -> signal6.compose.response.json, ro_array_core_signal6_poc.gds
klt drc ro_array_core_signal6_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal6_poc.gds --deck sky130 --format json  # -> 132 devices, 103 nets
klt gen-compose signal7.compose.request.json --format json   # -> signal7.compose.response.json, ro_array_core_signal7_poc.gds
klt drc ro_array_core_signal7_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal7_poc.gds --deck sky130 --format json  # -> 132 devices, 102 nets
```

## Increment 5: buffer `vss` bus routed, and a substrate-connectivity finding that changes what "the largest remaining unknown" actually needs

Starts on the `vdd`/`vss` item Increment 4 flagged as the largest remaining
unknown: `buf1`-`buf4`'s own `vss` taps (`ro_buf`'s own authoritative
`TAP_N` port, `local (-1.22, 0.92)`, li1, `width_um 0.42`, `direction_deg
90` — `layout/ro_buf/compose.response.json`'s own reported `ports[]`, not an
approximation) are now really routed together as one 4-pin bundle net
(`#1073`'s spanning-tree router, no `waypoints_um` needed — the three
row-adjacent legs `buf1`-`buf2`, `buf2`-`buf3`, `buf3`-`buf4` each composed
on the first attempt).

```
$ klt gen-compose signal4.compose.request.json --format json   # -> signal4.compose.response.json, ro_array_core_signal4_poc.gds
unrouted_nets: []
$ klt drc ro_array_core_signal4_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal4_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 104 (unchanged), pin_count: 94 (unchanged)
```

**The finding that matters more than the routing itself: `net_count` did not
move, because `vss` was already one electrically merged net before this
increment drew a single wire.** Diffing `signal3.extract.json` against
`signal4.extract.json` net-by-net: both report exactly one net named
`g_vss_m1|mph_g|s1_vss_m1|s2_vss_m1|s3_vss_m1|s4_vss_m1|vss` with
`device_count: 122`, byte-identical in both files — the four buffers' own
NMOS bodies were already members of that net in `signal3`, before any
`buf`-to-`buf` `vss` routing existed anywhere in this directory. This is
`klt extract`'s sky130 deck's own documented `connect_global` behaviour
(`docs/cli/extract.md`'s "NMOS body" section: an un-isolated p-substrate is
modelled as one node chip-wide, "matching real silicon" for a design that
draws no deep-nwell isolation — which this one does not) — not a bug, and
not new: it is the same mechanism `spec/decision-records/DR-0005-*.md`
finding 3 already documented on a *single ring's* own extracted parasitics
("the shared node genuinely carries all four rings' activity"). This
increment confirms the same thing holds at the *array* composition level,
across four independently-placed rings plus four independently-placed
buffers, with no inter-block metal drawn between them at all — i.e. `vss`
connectivity across `ro_array_core`'s instances does not wait on this
directory's own routing to reach a `klt lvs` match; it is already there via
the substrate model. **The `vss` bus this increment draws is still real,
DRC-clean, physically load-bearing metal** — an actual fabricated die needs
an explicit low-impedance strap, not just the substrate's own (unmodelled,
per DR-0005 finding 3) resistance as its only return path — but it is not
what closes the "still open" item DR-0003 §8/DR-0005 are actually asking
about.

**`vdd` is not the same shape, and stays a genuinely open problem.**
`signal4.extract.json` still reports **seven separate `vdd` nets** — one
per `ro_buf`/`xor2` instance (`device_count` 2/2/2/2/10/10/10), unchanged
from `signal3` — because `vdd` ties to each device's own `nwell`, and
`nwell` has no chip-wide global identity the way substrate does: two
separately-placed cells' nwells are only the same electrical node if a real
strap physically joins them. A first attempt at routing the same four-buffer
`vdd` bundle (declared the same way, `ro_buf`'s own authoritative `vdd`
`TAP_N` port, local `(-1.12, 4.24)`) failed outright — `unrouted_nets:
["vdd"]`, every row-adjacent candidate leg rejected with `"backbone's
0.17um-wide drawn path crosses 41.29um through unrelated block 'ring2''s
bbox ... a bounded detour ... was tried first, and each one still crossed a
placed block"` — because `vdd`'s tap sits close enough to the top of each
`ro_buf`'s own bbox (local `y=4.24` against a bbox top of `4.6`) that the
router's automatic over-the-row detour lane cannot clear the intervening
`ring2`/`ring3` blocks (whose own composed bbox top, `4.81` µm, sits close
enough above `vdd`'s height that the two remaining candidate lanes — over
and under — both still cross a placed block per `#1167`'s bounded, two-lane
search) the way `vss`'s lower tap (`y=0.92`, well clear of the row's bottom)
apparently could. That probe's output was not committed (a failed,
zero-routed-nets `gen-compose` response is not layout evidence); whoever
attempts `vdd` next should budget explicit `waypoints_um` per leg — most
likely a corridor above `rn1`-`rn4`'s own `y=5.6` escape channel and above
every row-1 block's own bbox top (`> 4.81` µm), clear of `ro1`-`ro4`'s own
escape verticals (which run from `y=1.2` up through `y=8.0`-`10.0` at each
buffer's own `x`, so a `vdd` corridor below `8.0` still has to dodge those
four columns specifically) rather than the row-2/XOR-tree corridor
Increment 3/4 already used for signal routing.

**Not filed as a `klayout-tools` tool gap.** Both outcomes this increment
produced — the free `vss` merge and the blocked `vdd` route — came with
specific, actionable diagnostics (a documented `connect_global` mechanism in
one case, a named crossed-block reason in the other); neither is a case of
the tool being silently wrong or missing a capability.

### Reproduce this increment

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/ro_array_core-placement-poc
klt gen-compose signal4.compose.request.json --format json   # -> signal4.compose.response.json, ro_array_core_signal4_poc.gds
klt drc ro_array_core_signal4_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal4_poc.gds --deck sky130 --format json  # -> 132 devices, 104 nets (vss net's device_count unchanged at 122)
```

## Increment 6: the combining tree's `t1` routed, `xo`/`t2` taps confirmed — and a silent short that changes how every increment here has to be verified

Starts the XOR combining tree (`t1`, `t2`, `xo`), the last signal group
Increment 4 left open. `t1` (`xa1.y` → `xa3.a`) is now really routed, and
`xo` (`xa3.y`, a genuine top-level port of
`design/ro_array_core.spice`'s own `.subckt ro_array_core`) plus `t2`
(`xa2.y`) are exposed as pins on taps this increment *measured* rather than
approximated:

```
$ klt gen-compose signal5.compose.request.json --format json   # -> signal5.compose.response.json, ro_array_core_signal5_poc.gds
unrouted_nets: [], t1 route_length_um: 66.97
$ klt drc ro_array_core_signal5_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_signal5_poc.gds --deck sky130 --format json
device_count: 132 (unchanged), net_count: 103 (down from 104), pin_count: 93
```

Net-by-net diff against `signal4.extract.json`, which is the *only* check
that actually proves what was connected (see finding 1): exactly one merge,
`a|inva_a|mn12_g0|mp13_g0` (4 devices, `xa3`'s `a` input) plus one of the
three 4-device `y` nets (`xa1`'s output) → one 8-device
`a|inva_a|mn12_g0|mp13_g0|t1|y`. Nothing else moved: the other two `y` nets
gained exactly their new pin labels (`t2|y`, `xo|y`, still 4 devices each),
so both pin taps land on the real XOR output net and merge nothing.

### Finding 1: `klt drc` clean is not connectivity evidence — a first `t1` probe shorted silently

The first `t1` attempt tapped `xa1.y` at block-local `(4.5, 8.0)` and
escaped **north** to a corridor above the XOR row. `klt gen-compose`
reported `unrouted_nets: []` and `klt drc` reported `status: clean,
violation_count: 0` — and the result was electrically wrong. `klt extract`
reported `net_count: 102`, not `103`: **three** 4-device nets had merged
into one 12-device net,
`a|bn|inva_a|invb_y|mn12_g0|mn34_g1|mp13_g0|mp24_g1|t1|y`. The escape stub
ran north on met1 at `xa1`-local `x = 4.5` straight across `xor2`'s own
internal `bn` met1 lane (measured extent: local `y ∈ [8.915, 9.085]`,
`x ∈ [1.480, 7.780]`), shorting `xa1`'s internal `b`-inverter output to its
own `y` output. Two merged shapes on one layer are a *short*, not a spacing
error, so no rule deck can see it.

The mechanism is structural, not a bug in this request: **`klt gen-compose`
models a placed block as an opaque bbox.** It rejects a leg that crosses an
*unrelated* block's bbox (Increment 4's finding 1) and — newly confirmed
here, finding 3 — a leg that crosses an *already-routed net* in the same
call, but it has no obstacle model of a placed block's own interior
conductors, so a leg that starts at an interior port escapes through that
block's own metal unchecked. Everything this directory taps by coordinate
(`ro`, `a`, `b`, `y`, `vdd`, `vss` — none of the composed leaf cells expose
declared pins) starts at an interior port, so this applies to every net
here. Filed generically against `2AMLogic/klayout-tools` per this repo's
`CLAUDE.md` friction protocol (`2AMLogic/klayout-tools#1527`). The
probe's own artifacts are **not committed** — a DRC-clean GDS with a wrong
netlist is a trap, not evidence, and the same precedent Increment 5
applied to a zero-routed response
applies here.

**Verification rule this establishes for every later increment**: a routed
net is only proven by a net-by-net `klt extract` diff against the previous
increment showing exactly the intended merges, by device count and by name.
`unrouted_nets: []` proves the router drew something; `klt drc` proves the
drawing is legal; neither proves it is the intended circuit.

### Finding 2: `xor2`'s `y` has exactly four escape windows, and they are measured

`xor2` exposes no `y` pin of its own, and its `y` net is **li1-only**
inside the cell (`klt components` over li1+met1+mcon reports `y` as the one
li-only component: 12 shapes, bbox `(-0.085, 2.580)`-`(7.770, 13.840)`), so
*every* met1 shape in `xor2` belongs to another net and any contact with
one is a short. `xor2-y-escape-scan.py` (committed here, with its
`xor2-y-escape-scan.json` output) walks every point of that li1 component
and, for each of the four cardinal directions, tests whether a met1 stub of
this request's own `0.17 µm` width plus sky130's `0.14 µm` met1 spacing
reaches the cell boundary touching nothing:

| Direction | Legal window (block-local µm) | Width |
|---|---|---|
| north | `x ∈ [1.340, 2.690]` | 1.350 |
| south | `x ∈ [6.310, 7.770]` | 1.460 |
| east | `y ∈ [2.580, 3.595]` | 1.015 |
| west | `y ∈ [12.160, 13.840]` | 1.680 |

One window per direction, and the first probe's `(4.5, 8.0)` tap is in none
of them for the direction it escaped: **the tap coordinate was never the
bug, the escape direction was** — `(4.5, 8.0)` is genuinely on `y`, as is
the `(3.84, 4.6)` approximation the coordinate table below has carried
since Increment 2. This increment taps `(1.55, 13.0)` instead — the centre
of `mp13`'s own `U0_S1` source pad (`x ∈ [1.340, 1.760]`,
`y ∈ [12.160, 13.840]`), the west half of the pad pair the cell's own
`"core"` stage links across the top gap — which sits in the north window
and clears `bn`'s met1 attic lane (local `y ∈ [15.915, 16.085]`,
`x ∈ [3.085, 16.915]`) by `1.535 µm` in `x`. Above that the route joins a
corridor at `y = 29.5` (absolute), `0.83 µm` above every row-2 block's own
bbox top (`28.67`), and drops at `x = 55.0` — the gap between `xa2`'s right
edge (`52.94`) and `xa3`'s left (`57.94`) — onto `y = 19.395`, `xa3.a`'s
own already-declared approach lane.

### Finding 3: `t2` is blocked by the *routing plane*, not by the floorplan

`t2` (`xa2.y` → `xa3.b`) does not route in this pass, and both probes were
rejected by the router itself rather than discovered afterwards:

- **East escape** (`xa2.y` at local `(7.6, 3.0)`, inside the east window
  above): `unrouted_nets: ["t2"]`, reason `crosses already-routed net
  'ro4'`. `ro4`'s own committed backbone rises at `x = 49.5` from `y = 10.0`
  to `19.395`, which is *inside* `xa2`'s own bbox `x` range
  (`28.97`-`52.94`), so every eastward exit from `xa2` above `y = 10` meets
  it.
- **North escape** (`xa2.y` at local `(1.55, 13.0)`, corridor lane
  `y = 30.5`): `unrouted_nets: ["t2"]`, reason `crosses already-routed net
  't1'`.

The second rejection is not a waypoint choice, it is arithmetic: `t1` has
to run from `xa1`'s own escape column (absolute `x = 8.435`) east to `xa3`
(`x ≥ 57.94`), so its corridor lane necessarily spans `xa2`'s north escape
column (absolute `x ∈ [37.195, 38.545]`, the north window mapped through
`xa2`'s origin) — and that column is `t2`'s only unblocked escape, because
the other two windows lead into **closed pockets** bounded by the
already-committed `ro1`-`ro4` backbones. `xa1`'s south window, for example,
opens into `x ∈ (-0.5, 20.5)`, `y ∈ (8.0, 11.085)`: floor `ro1`'s
`y = 8.0` lane (`x` `-0.5`→`50.5`), west wall `ro1`'s `x = -0.5` vertical
(`y` `8.0`→`19.395`), east wall `ro2`'s `x = 20.5` vertical
(`y` `8.5`→`19.395`), ceiling `xa1`'s own bbox bottom. Swapping which of
`t1`/`t2` takes the higher corridor lane only moves the crossing from one
net's rise to the other's drop.

**So the next increment needs a second drawing plane, not a better
waypoint** — the same conclusion `ro_stage`/`xor2` reached one level down,
for the same reason (two nets that must cross cannot share a layer). The
catch is `"metal3"`'s documented single-hop via rule (`layout/README.md`,
"Floorplan decisions made so far"): met2 cannot reach a bare li1 pin, and
neither `xor2`'s `y` nor **any** `ro_buf` port carries met1 (`klt
components` reports all four `ro_buf` nets — `a`, `y`, `vdd`, `vss` — as
li1-only), so a met2 stage has to be preceded by a met1 promotion. The
cheapest place for that promotion is inside the leaf cell's own final
(`"metal2"`) stage rather than at this level, where there is no legal
two-pin met1 leg to draw one with; whoever attempts it should measure the
cell's interior free space the way `xor2-y-escape-scan.py` measures its
escape windows, not assume it.

### The same fence blocks `vdd`, for a sharper reason than Increment 5 recorded

Increment 5 left `vdd` open with a bbox-detour failure. The measurement
above says something stronger: `ro1`-`ro4`'s own backbones fence the
row-1/row-2 corridor **both ways**. Below `y = 8.0` the four escape
verticals (`x = 50.5`/`105.8`/`161.1`/`216.4`, each rising from `y = 1.2`)
cut the corridor into five cells, one per buffer; above `y = 8.0` the four
horizontal lanes (`y = 8.0`/`8.5`/`9.0`/`10.0`, spanning
`x` `-0.5`→`50.5`, `20.5`→`105.8`, `28.47`→`161.1`, `49.5`→`216.4`) cut it
the other way, and each buffer's `vdd` tap (`x = 47.195`/`102.495`/
`157.795`/`212.995`) sits under exactly one of them. A four-tap `vdd` bus
therefore crosses at least one already-routed backbone on met1 wherever it
runs — the corridor-height search Increment 5 recommended cannot succeed on
this plane, and `vdd` joins `t2` as work for the met2 increment.

### Reproduce this increment

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/ro_array_core-placement-poc
python3 xor2-y-escape-scan.py                                # -> xor2-y-escape-scan.json (finding 2's table)
klt gen-compose signal5.compose.request.json --format json   # -> signal5.compose.response.json, ro_array_core_signal5_poc.gds
klt drc ro_array_core_signal5_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_signal5_poc.gds --deck sky130 --format json  # -> 132 devices, 103 nets, 93 pins
```

## What this establishes

All eleven already-composed sibling cells (`ro_ring5` + 3 `wstv` variants,
`ro_buf` x4, `xor2` x3) placed on one floorplan via `klt gen-compose`'s
`blocks[].cell` mechanism (each block a `{"gds_path", "cell_name"}` reference
into its own committed `layout/<cell>/<cell>.gds`, no `klt gen` calls of its
own), with **zero routing/connectivity** — a pure macro-placement test:

```
$ klt gen-compose compose.request.json --format json   # -> compose.response.json
$ klt drc ro_array_core_poc.gds --deck sky130 --format json
status: clean, violation_count: 0
$ klt extract ro_array_core_poc.gds --deck sky130 --format json
device_count: 132 (66 nfet + 66 pfet), net_count: 112, pin_count: 102
```

`132` matches `design/ro_array_core.spice`'s own instance sum exactly
(`4 x 22` `ro_ring5` + `4 x 2` `ro_buf` + `3 x 12` `xor2` = `88 + 8 + 36 =
132`) — strong confirmation the right cells, in the right multiplicities,
are the ones placed. `112` disjoint nets is expected: with no connectivity
requested, each placed cell's own internal nets stay separate, so this
number is not comparable to the eventual assembled net count.

Composed extent: **216.2 x 31.755 µm**, `bbox_um {x0:0, y0:-3.085, x1:216.2,
y1:28.67}` — two rows, floorplanned as (each row left-to-right, 5 µm gaps
between every pair of adjacent bounding boxes):

- Row 1 (`y` origin `0.0`): `ring1` (`ro_ring5`, `wstv=0.42`) - `buf1` -
  `ring2` (`ro_ring5_wstv0p44`) - `buf2` - `ring3` (`ro_ring5_wstv0p46`) -
  `buf3` - `ring4` (`ro_ring5_wstv0p48`) - `buf4`.
- Row 2 (`y` origin `12.585`, `5 µm` above row 1's tallest bbox, `ro_ring5`'s
  own `top=6.085`): `xa1` - `xa2` - `xa3`, positioned above ring-pairs
  (1,2)/(3,4)/combining-node respectively, anticipating the XOR tree's own
  fan-in (not yet wired).

Every origin is in `compose.request.json`; every block's own placed `bbox_um`
is in `compose.response.json`.

## What this does NOT establish

**Below describes the original placement-only request
(`compose.request.json`/`compose.response.json`/`ro_array_core_poc.gds`),
kept unchanged as that milestone's own evidence.** "Increment 2" above
resolves the `en1..en4`/`vddrN`/`ro1..ro4` pin-exposure and `rn1..rn4`
routing items in a *separate* set of files
(`signal.compose.request.json`/`ro_array_core_signal_poc.gds`); everything
else below is still open.

- **No routing.** `en1..en4`, `vddr1..vddr4`, `vdd`/`vss`, the ring-to-buffer
  nets (`rn1..rn4`), the buffer-to-XOR nets (`ro1..ro4`), the two
  intermediate XOR outputs (`t1`, `t2`), and the final output (`xo`) are all
  unconnected. `112` disjoint nets, not `design/ro_array_core.spice`'s
  expected single connected `ro_array_core` — no LVS attempt was made
  against it (would fail outright: 112 nets vs. the reference's connected
  graph, by design of a placement-only request). **Resolved for
  `en1..en4`/`vddrN`/`ro1..ro4` (pin exposure, no routing needed — each is
  already a single node inside its own block) and `rn1..rn4` (really
  routed) by Increment 2 above.** **Increment 3 further resolves `ro1`'s and
  `ro3`'s second leg** (into `xa1.a`/`xa2.a`, really routed — see "Increment
  3" above), **and Increment 4 resolves `ro2`'s and `ro4`'s second leg**
  (into `xa1.b`/`xa2.b`, really routed — see "Increment 4" above), so all
  four of `ro1..ro4` now reach their intended XOR inputs. **Increment 6
  resolves `t1`** (`xa1.y` → `xa3.a`, really routed) **and exposes `xo`
  (`xa3.y`, a real top-level port) and `t2` (`xa2.y`) as pins on measured
  taps.** **Increment 7 resolves `t2`** (`xa2.y` → `xa3.b`, really routed via
  a met2/`"metal3"` bridge over two met1 promotion stubs added at the
  array-composition level — see "Increment 7" above) — the XOR combining
  tree's inputs are now fully wired. **Increment 8 resolves `vdd`** (seven
  met1 promotion stubs plus a six-leg met2 chain bus, merging the seven
  per-instance nets into one 38-device net) **and, with it, the whole
  connectivity item: `klt lvs` matches 132/132 devices and 96/96 nets.**
  Still not drawn, and no longer blocking anything: `ring1..4`'s and
  `xa1..3`'s own `vss` taps (not LVS-blocking, per Increment 5's substrate
  finding).
- **The floorplan is a first-pass grid, not a routing-aware plan.** 5 µm
  gaps were chosen for guaranteed DRC clearance (nwell/tap spacing rules in
  sky130 are sub-micron), not for routability. A next increment may need to
  widen specific gaps once real routing legs are attempted, the same way
  `xor2-placement-poc`'s own floorplan did not survive its cell's real
  composition (`layout/xor2/README.md`'s "Why the PoC's prediction did not
  hold").
- **`xor2`'s `y`/`vdd`/`vss` tap coordinates below are approximate, not
  tool-declared.** **`y` is resolved as of Increment 6**: the table's own
  `y (-> t1) approx (10.725, 17.185)` (block-local `(3.84, 4.6)`) is
  confirmed *on-net* — it and the tap Increment 6 actually routed from,
  local `(1.55, 13.0)`, are points on the same single li1 component `klt
  components` reports as `xor2`'s `y`. Being on-net is not the same as
  being escapable, though: only four windows on that component have a legal
  met1 escape at all, and the approximation above is in none of them (see
  Increment 6, finding 2, and `xor2-y-escape-scan.json`). `vdd`/`vss`
  remain approximate and unconfirmed. Unlike `ro_ring5`'s and `ro_buf`'s ports (read from an
  authoritative intermediate-stage `compose.response.json`, see below),
  `xor2`'s own final-stage response reports `"ports": []` (all of its pins
  are inherited, unlabeled, from its `core` stage), and a `klt components`
  scan of `xor2.gds` produced two internally-contradictory readings for `a`/
  `b` (a text-label proximity artifact at `xor2`'s tight 0.545 µm gate
  pitch, not a real short — `xor2`'s own committed `klt lvs` already proves
  no such short exists). `a`/`b` below use the authoritative `core`-stage
  ports instead (reliable); `y`/`vdd`/`vss` use the `components` scan's
  *unambiguous, single-label* components only, and are flagged `approx`
  accordingly. Confirm on contact, don't route blind.

## Candidate net-tap coordinates for the next increment

Absolute coordinates (`block origin + block-local port`), `orientation:
"none"` throughout so `final = origin + local` for every block placed here.
Sources: `ro_ring5`'s `en` from its own committed `compose.response.json`
`ports[]`; `ro_ring5`'s `ro`/`vddr`/`vss` from `layout/ro_ring5/{place,fb}
.compose.response.json` (`s4_y`, `*_vddr_m1`, `*_vss_m1`, the intermediate
stages the final rail-merge stage folds together — ports on a promoted net
remain physically present and tappable even after a later stage merges
several of them into one net, see `layout/README.md`'s "Composing a gate");
`ro_buf`'s `a`/`y`/`vdd`/`vss` cross-checked against `layout/xor2/cell.json`'s
own `inv_a`/`inv_b` hand-declared values (byte-for-byte the same points,
since every `ro_buf` instance is geometrically identical); `xor2`'s `a`/`b`
from `layout/xor2/core.compose.response.json`'s `mp13_g0`/`mn12_g0`
(net `a`) and `mp24_g0`/`mn12_g1` (net `b`) — either tap on a net is valid,
both are listed for routing-side flexibility.

| Block | Net | Absolute (µm) | Layer | Width | Dir |
|---|---|---|---|---|---|
| ring1 (`wstv=0.42`) | en1 | (5.875, 1.975) | li1 | 0.42 | 90 |
| ring1 | ro (-> rn1) | (40.915, 2.075) | li1 | 0.42 | 90 |
| ring1 | vddr1 (g-end / s4-end) | (2.190, 4.400) / (36.015, 4.400) | met1 | 0.17 | 90 |
| ring1 | vss (g-end / s4-end) | (2.690, 2.000) / (36.515, 2.000) | met1 | 0.17 | 90 |
| ring2 (`wstv=0.44`) | en2 | (61.175, 1.975) | li1 | 0.42 | 90 |
| ring2 | ro (-> rn2) | (96.215, 2.075) | li1 | 0.42 | 90 |
| ring2 | vddr2 (g-end / s4-end) | (57.490, 4.400) / (91.315, 4.400) | met1 | 0.17 | 90 |
| ring2 | vss (g-end / s4-end) | (57.990, 2.000) / (91.815, 2.000) | met1 | 0.17 | 90 |
| ring3 (`wstv=0.46`) | en3 | (116.475, 1.975) | li1 | 0.42 | 90 |
| ring3 | ro (-> rn3) | (151.515, 2.075) | li1 | 0.42 | 90 |
| ring3 | vddr3 (g-end / s4-end) | (112.790, 4.400) / (146.615, 4.400) | met1 | 0.17 | 90 |
| ring3 | vss (g-end / s4-end) | (113.290, 2.000) / (147.115, 2.000) | met1 | 0.17 | 90 |
| ring4 (`wstv=0.48`) | en4 | (171.775, 1.975) | li1 | 0.42 | 90 |
| ring4 | ro (-> rn4) | (206.815, 2.075) | li1 | 0.42 | 90 |
| ring4 | vddr4 (g-end / s4-end) | (168.090, 4.400) / (201.915, 4.400) | met1 | 0.17 | 90 |
| ring4 | vss (g-end / s4-end) | (168.590, 2.000) / (202.415, 2.000) | met1 | 0.17 | 90 |
| buf1 | a (<- rn1) | (48.860, 1.700) | li1 | 0.17 | 180 |
| buf1 | y (-> ro1) | (50.215, 1.200) | li1 | 0.17 | 0 |
| buf1 | vdd / vss | (47.195, 4.240) / (47.095, 0.920) | li1 | 0.42 | 90 |
| buf2 | a (<- rn2) | (104.160, 1.700) | li1 | 0.17 | 180 |
| buf2 | y (-> ro2) | (105.515, 1.200) | li1 | 0.17 | 0 |
| buf2 | vdd / vss | (102.495, 4.240) / (102.395, 0.920) | li1 | 0.42 | 90 |
| buf3 | a (<- rn3) | (159.460, 1.700) | li1 | 0.17 | 180 |
| buf3 | y (-> ro3) | (160.815, 1.200) | li1 | 0.17 | 0 |
| buf3 | vdd / vss | (157.795, 4.240) / (157.695, 0.920) | li1 | 0.42 | 90 |
| buf4 | a (<- rn4) | (214.760, 1.700) | li1 | 0.17 | 180 |
| buf4 | y (-> ro4) | (216.115, 1.200) | li1 | 0.17 | 0 |
| buf4 | vdd / vss | (213.095, 4.240) / (212.995, 0.920) | li1 | 0.42 | 90 |
| xa1 | a (<- ro1) | (14.780, 16.615) or (3.445, 19.395) | li1 | 0.42 / 0.17 | 90 / 180 |
| xa1 | b (<- ro2) | (15.450, 16.615) or (21.620, 19.395) | li1 | 0.42 / 0.17 | 90 / 180 |
| xa1 | y (-> t1) *approx* | (10.725, 17.185) | li1 | - | - |
| xa1 | vdd / vss *approx* | (10.885, 23.585) / (10.885, 14.585) | - | - | - |
| xa2 | a (<- ro3) | (43.750, 16.615) or (32.415, 19.395) | li1 | 0.42 / 0.17 | 90 / 180 |
| xa2 | b (<- ro4) | (44.420, 16.615) or (50.590, 19.395) | li1 | 0.42 / 0.17 | 90 / 180 |
| xa2 | y (-> t2) *approx* | (39.695, 17.185) | li1 | - | - |
| xa2 | vdd / vss *approx* | (39.855, 23.585) / (39.855, 14.585) | - | - | - |
| xa3 | a (<- t1) | (72.720, 16.615) or (61.385, 19.395) | li1 | 0.42 / 0.17 | 90 / 180 |
| xa3 | b (<- t2) | (73.390, 16.615) or (79.560, 19.395) | li1 | 0.42 / 0.17 | 90 / 180 |
| xa3 | y (-> xo) *approx* | (68.665, 17.185) | li1 | - | - |
| xa3 | vdd / vss *approx* | (68.825, 23.585) / (68.825, 14.585) | - | - | - |

`vddr1..vddr4` are **separate** top-level supply domains (per
`design/ro_array_core.spice`'s own port list, `en1..en4 vddr1..vddr4 vdd
vss`) — they must stay electrically isolated from each other and from the
shared `vdd`, matching DR-0003's per-ring starve-supply isolation intent.
`vdd`/`vss` (the buffer/XOR-tree supply, distinct from any `vddrN`) still
need a distribution plan across all eight `buf`/`xor2` instances — not
attempted here.

**Increment 8 correction: this table's three `xa* | vdd *approx*` rows are
wrong, not merely imprecise.** `(10.885, 23.585)` and its `xa2`/`xa3`
translations are **not on li1 at all** — checked directly against the
composed array, they land in a gap between two `vdd` rails. `xor2`'s `vdd`
is one 27-shape li1-only component of area `17.07285 µm²`; Increment 8 taps
it at block-local `(-1.12, 13.8)` (absolute `(5.765, 26.385)` /
`(34.735, 26.385)` / `(63.705, 26.385)`), measured by `vdd-tap-scan.py`
rather than approximated. The `ro_buf` `vdd` rows, by contrast, were right
all along (they come from the cell's own authoritative `TAP_N` port) and are
the taps Increment 8 actually used. The `vss *approx*` rows remain
unconfirmed and unexercised.

**Increment 2 update: the `xa1`/`xa2`'s `a`/`b` second-coordinate option is
now confirmed, not just candidate.** The `(x, 19.395)`-family alternative for
each `a`/`b` row above (e.g. `xa1`'s `a` at `(3.445, 19.395)`, `b` at
`(21.620, 19.395)`) is `layout/xor2/cell.json`'s own `inv_a`/`inv_b`
block-declared `a` ports (local `(-3.44, 6.81)` / `(14.735, 6.81)`,
`direction_deg: 180`) — the *exact* declarations `xor2` itself used to reach
its own committed `klt lvs` match, not a `klt components` guess. They are
the recommended taps for the next increment's buffer→XOR routing (the
`(x, 16.615)`-family alternative, `mn12_g0`/`mp24_g0`-style, remains valid
but unexercised). The `y`/`vdd`/`vss` rows are still `approx` and still
unconfirmed — nothing in Increment 2 touched them.

## Reproduce

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
# klt's shared install has been observed to churn mid-session below the
# blocks[].cell request shape this directory depends on -- pin it in a venv
# per layout/README.md's "Correcting the curation note":
#   python3 -m venv /tmp/klt-venv && /tmp/klt-venv/bin/pip install \
#     "git+https://github.com/2AMLogic/klayout-tools@c6dbf66c53c6e9a73c4f5ae5e41a98e8fe414252"
cd layout/ro_array_core-placement-poc
klt gen-compose compose.request.json --format json   # -> compose.response.json, ro_array_core_poc.gds
klt drc ro_array_core_poc.gds --deck sky130 --format json      # -> clean, 0 violations
klt extract ro_array_core_poc.gds --deck sky130 --format json  # -> 132 devices (66 nfet, 66 pfet), 112 nets
```

## Suggested next steps (not attempted here)

1. ~~Route `en1..en4` and the four `vddrN` domains first~~ **DONE, Increment
   2 above** — these turned out to need no routing at all, only pin
   exposure, since each is already a single node inside its own ring.
   `ro1..ro4` (buf `y`) turned out to be the same shape and are also now
   exposed, ahead of schedule relative to this list. ~~Route `rn1..rn4`
   (ring `ro` -> buf `a`)~~ **DONE, Increment 2 above**, on `"metal2"`, with
   one floorplan finding (the block-interior edge-margin rule — see
   Increment 2's own section).
2. ~~Route `ro1..ro4` (buf `y`, already a top-level pin) into `xor2` `a`/`b`
   next~~ **DONE — `a` in Increment 3, `b` in Increment 4** (`ro1`->`xa1.a`,
   `ro3`->`xa2.a`, `ro2`->`xa1.b`, `ro4`->`xa2.b`, all on `"metal2"`, each
   net its own dedicated channel so backbones cannot intersect — confirmed
   needed, matching this bullet's own prediction). `b`'s own recipe needed
   distinct source-side channel heights (`y=8.5`/`10.0`, see Increment 4's
   finding 2) rather than reusing `a`'s `y=8.0`/`9.0` rows, since `a`/`b`
   share the identical destination `y=19.395` and a naive shared-row
   approach either collided with `a`'s own backbone or crossed a third
   block's bbox (Increment 3's finding 2 and Increment 4's finding 1,
   respectively).
3. ~~Confirm `xor2`'s `y`/`vdd`/`vss` taps by attempting a real routed
   connection~~ **Partially superseded by Increment 5's own finding**: `vss`
   turns out not to need this directory's routing at all to reach a `klt
   lvs` match — `klt extract`'s sky130 `connect_global` substrate model
   already merges every instance's `vss`-tied NMOS body (and any drawn psub
   tap) into one net, confirmed at the array-composition level in Increment
   5 (buffer `vss` bus routed, `net_count` unchanged before/after). Routing
   `ring1..4`'s own `vss` and `xa1..3`'s `vss` explicitly is still worth
   doing eventually (a real die needs the low-impedance strap the substrate
   alone does not model, per DR-0005 finding 3), but it is no longer the
   blocker for LVS. `vdd` is the opposite: confirmed genuinely open (seven
   separate nets, unchanged by Increment 5), and a first buffer-only `vdd`
   bus attempt failed outright (`unrouted_nets: ["vdd"]`, every candidate
   leg rejected for crossing `ring2`/`ring3`'s own bbox) — see Increment 5's
   own section for the specific corridor-height reasoning whoever attempts
   `vdd` next should start from — **superseded again by Increment 6**: that
   corridor-height search cannot succeed on met1 at all, because
   `ro1`-`ro4`'s own backbones fence the row-1/row-2 corridor in both axes
   (Increment 6's `vdd` section), so `vdd` is now a met2 problem, not a
   waypoint problem. `xor2`'s own `y` tap is **confirmed by Increment 6**
   (`t1` really routed from it, one measured escape window of four); its
   `vdd`/`vss` taps remain unconfirmed and unattempted.
4. ~~A second drawing plane for `t2` and `vdd`~~ **`t2` DONE, Increment 7
   above** — routed via a `"metal3"` (met2) bridge at `y = 31.0`, fed by two
   short `"metal2"`-role met1 promotion stubs (`xa2.y` → `y_m1`, `1.4 µm`;
   `xa3.b` → `b_m1`, `0.9 µm`) added at *this* directory's own
   array-composition level (`signal6`), with the met3 bridge itself a
   separate call (`signal7`) that treats the whole `signal6` GDS as one
   placed block. **Correction to this bullet's own prior text**: the
   promotion did *not* need to happen inside `xor2`'s leaf cell — Increment
   7's own "Finding" explains why. **`vdd` DONE, Increment 8 above** — this
   bullet's own prediction ("the same shape ... its own set of met1 stubs
   per buffer/XOR tap plus a met3 bus") held exactly, with two things it did
   not anticipate: the met2 plane is *not* empty (each `ro_ring5` carries
   two full-width met2 rails of its own), and `waypoints_um` is accepted
   only for two-pin nets, so the bus had to be declared as a six-leg chain
   of two-pin `vdd` entries rather than one seven-pin net.
5. Given `ro_ring5`'s and `xor2`'s own composition each needed a staged
   (`"stages"`) approach to keep crossing nets off one layer, expect
   `ro_array_core`'s own final assembly to need the same — this floorplan
   only proves blocks fit with clearance, not that every net above routes in
   one `gen-compose` pass. Confirmed for real by Increment 2's own finding
   above, one level down (the block-interior edge-margin rule), a different
   failure mode than the crossing-nets rule but with the same practical
   consequence: some nets need their own dedicated pass or channel.
6. ~~Once routed, run `klt lvs` against `design/ro_array_core.spice`'s own
   `.subckt ro_array_core`~~ **DONE, Increment 8 above — `match`, 132/132
   devices, 96/96 nets, with two committed negative controls showing the
   verdict discriminates.** This bullet's open question was **real**, and
   `array-reference.py` is the answer: the reference netlist defines a
   **single**
   `.subckt ro_ring5 en ro vddr vss wstv=0.42 lstv=2 cld=0.5f` and calls it
   four times with four different `wstv=` overrides (`0.42`/`0.44`/`0.46`/
   `0.48`) — it does *not* define four separate subckts. `layout/`'s four
   physically-distinct GDS cells (`ro_ring5`, `ro_ring5_wstv0p44`,
   `ro_ring5_wstv0p46`, `ro_ring5_wstv0p48`) are a layout-side naming
   convention for those four device sizings, not four reference subckts.
   `compose-cell.py`'s current `lvs.dependencies` (a flat list of subckt
   *names*, all extracted with one shared `lvs.params` dict) has no
   mechanism yet to extract the *same* subckt name four times with four
   *different* parameter substitutions for one composed reference — that is
   new ground `layout/ro_ring5/cell.json`'s own single-instance
   `dependencies: ["ro_nand2", "ro_stage"]` never exercised. Increment 8
   confirms `compose-cell.py` does *not* cover it as-is and works around it
   in this directory (`array-reference.py`, four renamed passes over the
   ring hierarchy) rather than changing `compose-cell.py` mid-increment;
   the per-dependency `params` override belongs with promoting this
   directory into a `layout/ro_array_core/` `cell.json` recipe, which is
   follow-up work.
7. **Next, in rough dependency order**: draw the remaining `vss` taps
   (`ring1..4`, `xa1..3`) so the composed block carries a real supply strap
   rather than relying on the substrate model; promote this directory into a
   `layout/ro_array_core/` cell recipe (per-dependency `params` in
   `compose-cell.py` + unit tests, `--check` reproducibility); extract the
   whole array's parasitics (`klt extract --parasitics`, the same path
   `layout/pex/` already uses for one ring) and run a post-layout PVT
   campaign against them under `sim/`; and use *that* data to answer
   DR-0003 §8's `wstv` inter-ring decorrelation question, which needs real
   inter-ring coupling and cannot be answered at the netlist level. Then
   `sampler_core`/`sampler_dff`, which have no layout at all yet.

Tracked under issue #22 (`ro_array_core`/`sampler_core` assembly);
`ro_array_core` is closed out by Increment 8, `sampler_core` and the
post-layout PVT/decorrelation work are not.
