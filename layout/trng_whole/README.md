# layout/trng_whole

**Whole-block composition (issue #172, part of #170; contributes to #18 AC3):
the verified `sampler_core` analog macro and the verified `trng_digital`
digital macro placed in one top cell `trng_whole`, every boundary, clock/reset
and supply connection routed, with a combined LVS reference and an interface
table.** Provisional until silicon.

**Verdict: `composed; physical sign-off pending (#173 DRC/LVS, #174
characterization)`.** All 18 whole-block nets (22 legs) are routed with
`unrouted_nets: []` and `landed_on_block: true` on every leg, an independent
re-extraction of the composed stream confirms each net's terminals share one
metal-level cluster, distinct nets stay distinct and the four `vddr` rails stay
four rails. **Area: 378.16 x 333.5 um = 0.126116 mm2 against the unchanged
`< 0.05 mm2` target -- Unmet (2.52x)**, and `trng_digital` alone (0.060 mm2) is
already over the target, so no placement of these two unchanged macros can meet
it. **Not claimed here:** whole-block DRC, whole-block LVS, PVT/coupling/IR
characterization, closure of #170 / #18 AC3 or of DR-0003 section 8 / DR-0009
(distribution geometry now exists; every measurement obligation is still open).

## Result

| Step | Verdict | Evidence |
|---|---|---|
| input audit: 113 digital DEF pins vs GDS labels vs RTL bits; 18 analog `trng_top` pins vs nets; aliases, duplicates, directions | pass (0 errors) | `report.json` `audits.interface`, `audits.digital_geometry` |
| analog port audit: 18 declared analog ports vs a flat extraction of `sampler_core.gds` | pass; 18 distinct extracted nets | `audits.analog_ports` |
| `klt draw` boundary pad cell (16 met5 pads) | 16 shapes | `pins.draw.request.json`, `pins.draw.response.json`, `trng_whole_pins.gds` |
| `klt gen-compose` (explicit placement, `top_metal` routing, 107 label-only pins) | **18/18 nets `routed`, 22/22 legs routed, `landed_on_block` true, `unrouted_nets: []`, 107 `pins[]` promoted**, no warnings | `compose.request.json`, `compose.response.json`, `trng_whole.gds` |
| composed-stream connectivity audit (li1..met5, labels) | 18 nets -> 18 distinct clusters; 107 digital external pins isolated; `vddr1`-`vddr4` distinct, none merged with `vdd`/`vss`; `vdd` = `VPWR`, `vss` = `VGND` | `audits.composed_connectivity` |
| combined reference structure audit | pass (123-port `trng_whole`, 11 subckts, digital black box) | `trng_whole.ref.spice`, `audits.reference_structure` |
| area | **Unmet**, 0.126116 mm2 vs 0.05 mm2 | `report.json` `area` |
| `compose-whole.py --check` (isolated rebuild) | matches; the rebuilt `trng_whole.gds` is **byte-identical** to the committed one | see "Reproducing" |
| `layout/test_compose_whole.py` | PASS (composition-contract checks, below) | `layout/test_compose_whole.py` |
| informational `klt drc` on the composed stream | **clean, 0 violations** since the issue #181 regeneration of `sampler_core` (klt `0.6.0+g5edb557f91d0`, deck `sha256:2bcbd625…`). Before #181: 5664 `licon1.ongrid.1`, all inside `sampler_core` (`ana__` origin), 0 from the routing, pads or digital macro. **Not sign-off** | `drc-informational.json` |

## What was composed, and how it sits

Frame: micrometres, `trng_whole` frame. `klt gen-compose` orientation
`mirror_x` is (x, y) -> (-x, y) about the block's local origin, then translate.
Both macros are mirrored; see `floorplan.json`'s `_comment` for the full
reasoning (it is the orientation in which the four inter-macro nets are a
non-crossing nested-L matching on a single layer).

| Macro | Cell / source | Orientation | Origin (x, y) | Placed bbox x0..x1, y0..y1 |
|---|---|---|---|---|
| `dig` | `trng_digital` (`layout/trng_digital/trng_digital.gds`) | `mirror_x` | (200.0, 0.0) | -45.05..200.0, 0.0..245.05 |
| `ana` | `sampler_core` (`layout/sampler_core/sampler_core.gds`) | `mirror_x` | (328.77, 268.64) | 0.0..330.96, 265.055..323.36 |
| `pads` | `trng_whole_pins` (`klt draw`) | none | (0, 0) | 4.07..324.395, 330.5..333.5 |

Digital macro to the south (its sampler-facing edge east), analog macro to the
north (its sampler bank y ~ -1.7..5.0 local facing south toward the digital
macro, its ring array and the `en`/`vddr` pads nearer the north pin side).

**Routing layer.** Every inter-block / boundary / supply route is `met5`
(`routing.layer_role: "top_metal"`, 1.6 um wide, the `met5.width.1` floor) with
the tool's own via ladder (met2/met3/met4 landing pads, via2/via3/via4) at each
port. That is a workaround, not a preference: `klt gen-compose`'s sky130
routing roles stop at `metal3` (met2) apart from `top_metal`; met2 over the
analog macro is full of its own lanes and met3/met4 are not roles at all. See
"Friction" below.

### Port geometry (the interface, summarised)

The full per-pin table is `interface.md` / `interface.json` (generated). Key
facts a consumer must not guess:

- **`sampler_core.gds` has no top-level pin shapes or labels.** Its
  `compose.response.json` reports `ports: []`, and the only label on its top
  cell is the internal `vdd_link`. Each analog boundary connection here is a
  *declared port on existing conductor*, chosen and audited by
  `compose-whole.py` against an extraction of the analog GDS: `en1`-`en4` on the
  ring NAND enable li1 pads (y = 25.61 local), `vddr1`-`vddr4` on each ring's own
  met2 rail (y = 29.635), `vdd` (y = 31.135) and `vss` (y = 34.435) on their met2
  lanes, the six sampler `q` taps on their 0.42 um met2 pads (y = 2.71;
  `raw_bit` = `xsb`, `raw_valid` = `xsv`, `ring_bit1..4` = `xsr1..4`, per
  `design/trng_top.spice` and `layout/sampler_core/cell.json`'s instance
  order), `clk` on the y = -1.7 lane, `rst_n` on the y = 5.0 haul.
- **The routed Verilog is signal-only.** Digital physical pins come from
  `trng_digital.def`: 82 met3 pins on the **west** edge (x = 0.4), 29 met2 pins
  on the **south** edge (y = 0.242, `bus_wdata[3..31]`), and `VPWR`/`VGND` as met5
  stripe pins (8 / 9 rectangles). Pin labels are the GDS labels
  (`bus_rdata[N]` sits on DEF net `bus_rdata_r[N]`, `startup_done` on
  `startup_done_r`; the abstract netlist uses the net names).
- **Bit order:** `bus_addr[3:0]`, `bus_wdata/bus_rdata/out_data[31:0]`; bit 0 = LSB; names
  are the pin labels.
- **Directions** (`*.ipin/opin/iopin` for the analog pins, DEF/RTL for the digital
  pins, cross-checked): `en1-4`, `clk`, `rst_n` inputs; `ring_bit1-4`, `raw_bit`,
  `raw_valid` analog outputs; `vddr1-4`, `vdd`, `vss` inout (supplies).
- **Whole-block external pins.** 16 met5 boundary pads (`clk`, `rst_n`, `en1-4`,
  `vddr1-4`, `ring_bit1-4`, `vdd`, `vss`) at y = 332.0, 3 um square, each directly above its
  lane; the label sits on the routed net. The 107 other digital signal pins are
  label-only promotions on the digital macro's own pin shapes (east edge x = 199.6
  and south edge y = 0.2425 after mirroring). Their access from the
  corridor east of the digital macro is not planned here (the shared-net lanes
  occupy part of it on met5; the pads themselves are met3/met2, so pad-ring routing
  can still reach them on lower layers).
- **`raw_bit` and `raw_valid`** are macro-to-macro nets only; **no ring enable is connected
  to a digital status output** (none is implied; `en1-4` are boundary inputs).

### Supply distribution (DR-0003 section 8 / DR-0009)

- `vddr1`..`vddr4`: four dedicated met5 routes of 33.73 um each, from each ring's
  met2 rail port to its own boundary pad, never joined to each other or to `vdd`
  (audited on the composed stream, `vddr_rails_distinct: true`). **External
  source:** four independent supplies at the `vddr1..4` boundary pads; no regulator is
  drawn and none is implied (a regulator redesign is out of scope without a documented
  requirement).
- `vdd` / `vss`: one net each across digital (`VPWR` / `VGND`), analog (`vdd` / `vss`) and a
  boundary pad. `VGND` taps the topmost met5 stripe (y = 236.64 local) and runs straight
  north to the analog `vss` lane; `VPWR` cannot leave north (the `VGND` stripe sits above it
  on the same layer), so it escapes west through its stripe tip, around the outside of the
  digital bbox (x = -46.4) and along a gap lane (y = 257.0) to the analog `vdd` lane. That
  1.35 um excursion is why the bbox starts at x = -47.2.
- `VPB`/`VNB` standard-cell well/substrate connections are tied to `VPWR`/`VGND` by
  tap cells inside the digital macro; the analog macro's own well ties are as verified in
  `layout/sampler_core/erc.json`. This increment adds no tie.
- **This is the layout obligation only.** It does **not** close DR-0003 section 8's
  first-named mechanism (shared supply impedance) or DR-0009's row: coupling, period scatter,
  IR and every other measurement obligation stay open for #174 and the parent tracker.

## Area

Basis: axis-aligned bounding box of all drawn (non-text) geometry of the composed top
cell, routing and pads included, no halo/keep-out/seal ring, against the README
`Area < 0.05 mm2` row, unchanged.

| | Value |
|---|---|
| combined bbox | x -47.2..330.96, y 0.0..333.5 um |
| size | 378.16 x 333.5 um |
| area | 126116.36 um2 = **0.126116 mm2** |
| target | 0.05 mm2 (unchanged) |
| result | **Unmet** (2.52x) |
| macro bboxes | `trng_digital` 0.06005 mm2, `sampler_core` 0.019297 mm2, sum 0.079347 mm2 |

Over budget is reported, not hidden: the macros are unchanged, the target is unchanged.
`trng_digital` alone exceeds the target by 20%.

## Reproducing

```bash
# klt 0.6.0+g5edb557f91d0 (layout/pdk.json klt_version_pin; venv recipe in layout/README.md,
# "Regeneration on the cut-size/grid fix (issue #181)") / KLayout 0.30.12 / python klayout
# 0.30.12, open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b. SPICE is not involved.
python3 layout/bin/compose-whole.py layout/trng_whole/floorplan.json            # rebuild + publish
python3 layout/bin/compose-whole.py layout/trng_whole/floorplan.json --check    # isolated rebuild, diff, exit 1 on drift
python3 layout/bin/compose-whole.py layout/trng_whole/floorplan.json --informational-drc   # + drc-informational.json
python3 layout/test_compose_whole.py                                            # contract tests, no klt needed
```

The build always runs in a scratch directory and **publishes into this directory only after
every audit passed**: a failed or partial composition can never overwrite the committed
evidence. `--check` rebuilds the same way and diffs the stable report fields (input hashes,
per-net routing verdicts, macro transforms, area, audits), the canonical geometry hash, every
generated text artifact byte for byte, and the GDS hash. A binary-only GDS difference with an
identical canonical geometry hash would be reported as a header-timestamp difference; here
there is none -- two independent rebuilds produced a byte-identical `trng_whole.gds`.

### Input and output hashes

| Input | sha256 |
|---|---|
| `layout/sampler_core/sampler_core.gds` | `e3ff54a9bb15122298f0d5df817612ed1caacb3b045533f9ba86d009036c2004` (regenerated by #181; was `a00f6550…`) |
| `layout/trng_digital/trng_digital.gds` | `c65e15818ebb0bf3fb2f59cab63563e88c1acebe32f0e83040c43c9ad87fa750` |
| `layout/trng_digital/trng_digital.def` | `55b59c05ed2807a5b023efe4b45dfd9d9d4c68e136907c57c84e39179ef214fa` |
| `digital/rtl/trng_digital.v` | `219738aae7c5fd3bfede92ae20bebe38e843f7341690eed151d1545a93db90ef` |
| `design/trng_top.spice` | `3d1ecc97b757f961c5f9fa7b63555132723bc87be373e9e5c3cbd1f18bde6a3b` |
| `design/xschem/trng_top.sch` | `78aaa0bfeeed5299b564d823cdb7d3f21411f39805e48285dac9c01d294c568c` |

(All inputs, including the rest, are in `report.json` `inputs_sha256`; the design and RTL
files are **unmodified** -- `layout/test_compose_whole.py` re-hashes every recorded input.)

| Output | sha256 |
|---|---|
| `trng_whole.gds` | `af2f8dfe2800599e97d769bdedd14924c9fa3f24fc7e1c4f43ccd72ac5572ddd` (recomposed by #181; was `a8e9865a…`) |
| canonical geometry (240257 merged polygons, 57908 labels, 39 layers) | `628377a12cc05c69807e3cb7f8eb6040226ac6241b31e99c4210407a7ae0fe51` (was `73063d4e…`; same counts, only `sampler_core`'s cut sizes/positions differ) |
| `trng_whole_pins.gds` | `c957f712dbd108f079df2909a1b5e2b978e47f402c4b26d8df35a445794d4b41` |
| `trng_whole.ref.spice` | `983d3d2237ec19fd86612254de638a74b8f3fb32ab16af8dbfd6e3e30d56d38f` |
| `interface.json` / `interface.md` | `ffee0519b72088f917c67e94e565c4f3953b7969c534ef1aebc7e694b064309d` / `284570087bfa3377ab5e1e41f23ce61028a3b5529d41d5c716ebc8e2d4874b03` |

Tool pins. Composing (recomposed by issue #181): klt `0.6.0+g5edb557f91d0`, the exact
klayout-tools source commit `layout/pdk.json`'s `klt_version_pin`/`ci_klt_install` now name.
This is not a tagged release, and `compose-whole.py --check` is not on CI. The grader pin is
still 0.6.0. KLayout 0.30.12 via klt, python `klayout` 0.30.12 for the audits, open_pdks
`c6d73a35...`. The macros were produced by *different* klt builds. `trng_digital` used
`0.6.0+g10f3da34c088` + OpenROAD `26Q3-1510-g6cb3f2b704`, from
`digital/flow/place-and-route/tool-pins.json`. `sampler_core` used `0.6.0+g5edb557f91d0`
for compose/DRC/extract/LVS and tagged `0.6.0` for `erc.json`. `report.json` now reads those
per-artifact versions from each file's `provenance.klt_version` instead of a hardcoded
string. This increment only places and wires their
committed GDS and re-extracts metal connectivity, so it pins the composing klt and does not
assume the macro environments are identical.

## Composition-contract checks (and what they do not cover)

Real failing-input runs against the tool (each exits 1, nothing is written into this directory):

| Input | Result |
|---|---|
| digital DEF path missing | `error: missing input: .../does-not-exist.def` |
| `raw_bit`/`raw_valid` analog taps swapped | `analog port audit failed: raw_bit: design/trng_top.spice drives 'raw_valid' from xsv` |
| `en1`/`en2` analog ports swapped | `analog port audit failed: en1: net there carries ['en2'], not 'en1'` |
| a digital pin claimed by two nets | `interface audit failed: digital pin 'raw_bit' claimed by both 'raw_bit' and 'raw_valid'` |
| an analog pin dropped (`ring_bit3`) | `interface audit failed: analog trng_top pins not covered by any net: ['ring_bit3']` |
| a partial/unrouted tool result (`VPWR` escape lane moved inside the digital bbox) | tool exits 3 with a parseable body; `composition did not complete: unrouted_nets: ['vdd']; net vdd: status 'partial'` |

`layout/test_compose_whole.py` pins the same shapes (plus the verdict check against eleven synthetic bad
responses, port coverage, bus-bit mapping, duplicate/missing/conflicting aliases, the lane-pitch
and nested-L invariants, the reference-netlist audit, and the committed-evidence self-consistency)
and is on the PR path in `.github/workflows/ci.yml`. The connectivity audit is **metal-level**
(li1..met5 + labels): there is no device, well or substrate model in it, so it is not LVS and does
not stand in for #173's extracted connectivity proof, or for #174's coupling/IR evidence.

## Handoff to #173 and #174 (pending verification, exact paths)

- **GDS under test:** `layout/trng_whole/trng_whole.gds` (top cell `trng_whole`).
- **Combined reference:** `layout/trng_whole/trng_whole.ref.spice`: `design/trng_top.spice`
  verbatim + a black-box `.subckt trng_digital` (VPWR VGND + 111 RTL bits, **empty body**) + the
  top `.subckt trng_whole` (123 ports). **Standard-cell abstraction:** the digital macro's
  committed abstract netlist has 0 devices, so whole-block LVS must either bring a cell-level
  digital reference or compare the digital instance as a black box -- this file does not decide
  that. The analog hierarchy still carries xschem parameter expressions (`'cld'`,
  `'int(..)'`) that klayout's SPICE reader rejects; `layout/bin/compose-cell.py`'s unit/parameter
  rewrite (`build_reference`) is the established way through (see `layout/sampler_core/`), and
  was not applied here so the reference stays a verbatim copy.
- **Interface table:** `interface.md` / `interface.json`: every macro signal and supply pin,
  bus bit order, directions, aliases, ports and pad coordinates.
- **Provenance:** `report.json` (inputs/outputs/tool pins/transforms/audits),
  `compose.request.json` / `compose.response.json` (the deterministic request and the tool's own
  per-net verdicts), `floorplan.json` (every hand-chosen coordinate with its justification).
- **Items for #173:** (1) the analog macro exposes **no pin shapes** -- a flat extraction will see
  `vdd`, `vss` etc. only as label text on interior metal, not as pins, and the new routes carry the
  net labels; (2) *resolved by #181:* before the regeneration, the committed
  `layout/sampler_core/drc.json` was clean only on klt 0.4.0's deck, while the current deck
  reported 5664 `licon1.ongrid.1` on `sampler_core` (generator side: klayout-tools#2648). After
  regenerating on the fix, both `sampler_core/drc.json` and `drc-informational.json` read 0
  violations on the same current deck. That is still not #173's sign-off verdict; (3) the digital macro's
  PDK cells are black boxes to extraction; (4) the extracted whole-block netlist's pin names will be
  the labels listed in `interface.md`.
- **Items for #174:** supply-coupling between `vdd`/`vddr1-4` routes (route lengths: `vddr1..4`
  33.73 um each, `vdd` 303.03 um over two legs, `vss` 95.36 um, all met5 1.6 um), period scatter,
  IR drop, PVT characterization -- none attempted; this directory only supplies geometry.
- **Not closed by this increment:** #170, #18 AC3, the DR-0003 section 8 measurement gaps, and
  DR-0009's shared-supply-impedance row.

## Corrections to the issue's premises (found while building)

- The issue calls `layout/sampler_core/compose.response.json` "promoted port metadata". It is not:
  `ports` is `[]` and the cell has no top-level pins (see above). Ports were derived from the GDS.
- The issue lists `layout/bin/_klt_common.py` / `compose-cell.py` as "modify only where needed":
  neither was modified. `compose-cell.py --check` keeps its full-chain semantics for every
  `layout/*/cell.json`; this directory deliberately has no `cell.json`, so the nightly
  `layout/*/cell.json` glob does not pick it up.
- Digital pins sit on **two** edges (west met3 and south met2), not one.

## Friction

- **klayout-tools#2738** (open, filed by an earlier session): sky130 `gen-compose` routing roles stop
  at met2. Confirmed here, with one new data point: `routing.layer_role: "top_metal"` (met5) *is*
  accepted as a routing role and the tool's via ladder climbs met2 -> met5 correctly, which is what
  made this composition routable; met3/met4 remain unavailable as roles. Commented there rather than
  filing a duplicate.
- **klayout-tools#2648** (open): `klt gen` places sky130 gate-contact licon1 cuts off the 0.005 um grid.
  Confirmed here as the sole DRC finding on `sampler_core`; commented there.

## Files

| File | What |
|---|---|
| `floorplan.json` | hand-authored floorplan + port selection, justified inline |
| `compose.request.json`, `compose.response.json` | the one `klt gen-compose` request / the tool's response (absolute paths stripped) |
| `pins.draw.request.json`, `pins.draw.response.json`, `trng_whole_pins.gds` | the boundary pad cell (`klt draw`) |
| `trng_whole.gds` | the composed, routed whole block |
| `trng_whole.ref.spice` | the combined LVS reference (generated) |
| `interface.md`, `interface.json` | the interface table (generated) |
| `report.json` | provenance, hashes, routing verdicts, audits, area |
| `drc-informational.json` | `klt drc` on the composed stream, attributed by origin; **not sign-off** |
