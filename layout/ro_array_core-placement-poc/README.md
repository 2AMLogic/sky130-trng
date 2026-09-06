# layout/ro_array_core-placement-poc

**Placement-only proof of concept for `ro_array_core`** —
`design/ro_array_core.spice`'s top-level entropy-source assembly: four
`ro_ring5` rings (`wstv` 0.42/0.44/0.46/0.48, matching the four already-composed
ring variants), four `ro_buf` output buffers, and a three-`xor2` combining
tree (`xa1=xor(ro1,ro2)`, `xa2=xor(ro3,ro4)`, `xa3=xor(t1,t2)=xo`). All eleven
of these instances are now DRC-clean *and* LVS-clean as standalone cells (see
`layout/README.md`) — this is the first attempt at placing them together as
one block.

Mirrors `layout/xor2-placement-poc/`'s own convention, one level up the
hierarchy: a named, honestly-scoped proof of concept that establishes the
**floorplan** half of the problem and stops, rather than a claimed-complete
block. **This is not a DRC/LVS-clean `ro_array_core`** — see "What this does
NOT establish" below.

## Increment 2: forward ring→buffer signal chain routed (this update)

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
  routed) by Increment 2 above.** Still fully open: `vdd`/`vss` (the
  buffer/XOR-tree supply, and the vss bus shared by rings, buffers *and*
  XORs — eleven taps total), the buffer-to-XOR nets `ro1..ro4`'s *second*
  leg (buffer `y` already exposed as a top-level pin, but not yet also
  wired into the XOR tree's `a`/`b` inputs), `t1`, `t2`, `xo`, and therefore
  any LVS attempt.
- **The floorplan is a first-pass grid, not a routing-aware plan.** 5 µm
  gaps were chosen for guaranteed DRC clearance (nwell/tap spacing rules in
  sky130 are sub-micron), not for routability. A next increment may need to
  widen specific gaps once real routing legs are attempted, the same way
  `xor2-placement-poc`'s own floorplan did not survive its cell's real
  composition (`layout/xor2/README.md`'s "Why the PoC's prediction did not
  hold").
- **`xor2`'s `y`/`vdd`/`vss` tap coordinates below are approximate, not
  tool-declared.** Unlike `ro_ring5`'s and `ro_buf`'s ports (read from an
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
2. Route `ro1..ro4` (buf `y`, already a top-level pin) into `xor2` `a`/`b`
   next — cross-row, long hops (buf1's `y` at abs `x≈50` to `xa1`'s `a` at
   abs `x≈3.4`, e.g., since `xa1` floorplans *above the ring pair*, not above
   its own feeding buffer) — using the now-confirmed `inva_a`/`invb_a`-style
   coordinates above. Expect this to need its own channel height distinct
   from `rn1..rn4`'s (`y=5.6` in `signal.compose.request.json`), since both
   sets of nets would otherwise contend for the same corridor across the
   same x-span.
3. Confirm `xor2`'s `y`/`vdd`/`vss` taps by attempting a real routed
   connection and checking `klt drc`/`klt extract` agree, before trusting
   the `approx` rows above for the combining tree (`t1`, `t2`, `xo`) and the
   `vdd`/`vss` distribution across all eight `buf`/`xor2` instances. This is
   the largest remaining unknown: `vss` alone is a genuinely global net
   (rings, buffers *and* XORs all share it — eleven taps across the full
   216 µm span and both rows), unlike anything routed so far in this
   directory.
4. Given `ro_ring5`'s and `xor2`'s own composition each needed a staged
   (`"stages"`) approach to keep crossing nets off one layer, expect
   `ro_array_core`'s own final assembly to need the same — this floorplan
   only proves blocks fit with clearance, not that every net above routes in
   one `gen-compose` pass. Confirmed for real by Increment 2's own finding
   above, one level down (the block-interior edge-margin rule), a different
   failure mode than the crossing-nets rule but with the same practical
   consequence: some nets need their own dedicated pass or channel.
5. Once routed, run `klt lvs` against `design/ro_array_core.spice`'s own
   `.subckt ro_array_core`. Note a real open question this increment did
   *not* resolve: the reference netlist defines a **single**
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
   `dependencies: ["ro_nand2", "ro_stage"]` never exercised. Whoever attempts
   the real `ro_array_core` LVS should check whether `compose-cell.py` needs
   extending for this (e.g. a per-dependency `params` override) before
   assuming the existing mechanism covers it as-is.

Tracked under issue #22 (`ro_array_core`/`sampler_core` assembly, still
open).
