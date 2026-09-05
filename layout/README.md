# layout

Physical layout evidence for the sky130-trng entropy source, verified with
`klayout-tools` (`klt`) against the sky130 open PDK. See `layout/pdk.json`
for the PDK/tool pin.

**Status (issue #22, this increment): proof of methodology, not a
DRC/LVS-clean block.** `layout/primitives/` is real, checkable evidence
(every distinct transistor geometry `design/xschem/` instantiates, drawn and
independently DRC-clean/extracted) that klt's generator + composition
surface *can* build this design's layout — but no multi-device gate, no
`ro_ring5`, no `ro_array_core`, no `sampler_core`, and no post-layout PVT
re-verification exist yet. That is genuinely more work than one PR — see
"What's deferred" below and the tracking issue it names.

## Correcting the curation note

Issue #22's curator enhancement (2026-09-05) flagged an open question: `klt`'s
installed command surface, as that curation pass observed it (`layers`,
`stats`, `drc`, `lvs`, `extract`, `synthesize`, `techmap`, `render`, etc.),
looked "verification/synthesis-oriented," with "no obvious path to compose
full-custom analog polygon layout by hand." That reading no longer matches
the `klt` build installed in this environment (`klt version` → `0.4.0`):

- **`klt gen`** — runs a named parametrized layout generator (a headless
  KLayout PCell) against a JSON params object, producing a GDS/OASIS +
  structured report. The relevant family for this design is the analog
  primitive generators: `mos_array` (matched MOS transistor arrays —
  `layout/primitives/` below is built entirely from this one), `guard_ring`,
  `well_island`, `diff_pair`, `esd_device`, `res_array`, `cap_array`,
  `bond_pad`, `bjt_array`.
- **`klt gen-compose`** — places a set of already-generated `klt gen` blocks
  (and/or existing library cells) into one composed GDS per a
  blocks[]/placement/connectivity[]/routing request document, with real
  Manhattan metal routing (`pya.Path`-native, not a schematic annotation).
  Its own module docstring names "a CMOS inverter's nfet/pfet pair" as the
  motivating case for its per-block `orientation` field — i.e. this is not a
  generic verification tool pressed into a role it was not designed for; gate
  composition from matched-device primitives is exactly what it is for.
- **`klt draw`** — writes arbitrary polygons/labels verbatim from a JSON
  shape description, for the (rare, for this design) case a generator can't
  cover.

So the honest finding is **not** "no composition path exists" — a
tool-gap issue against `2AMLogic/klayout-tools` claiming that would be
inaccurate, and was not filed. The honest finding is: composing this
design's specific gates (with sky130's implicit-bulk `mos_array` output —
see "The well-strap gap" below) and then this design's specific hierarchy
(4 non-identical ring instances, an XOR combining tree, 6 TG-DFF samplers)
is real, multi-day layout engineering, most of which remains to do. That is
the actual scope gap the tracking issue below is for.

## Cell hierarchy → generator mapping

From `design/README.md`'s "Cell hierarchy":

```
trng_top                   (not in scope for #22 — stops at the raw tap)
  sampler_core              PLANNED — 6x sampler_dff + wiring
    ro_array_core           PLANNED — this issue's minimum scope
      ro_ring5   (x4)        PLANNED — non-identical (wstv 0.42/0.44/0.46/0.48)
        ro_nand2              PLANNED — 1x guard_ring (or well_island) + 5x mos_array
        ro_stage   (x4)       PROVEN AT DEVICE LEVEL — 1x guard_ring/well_island + 4x mos_array (layout/primitives/)
      ro_buf     (x4)        PROVEN AT DEVICE LEVEL — 1x guard_ring/well_island + 2x mos_array
      xor2       (x3)        PROVEN AT DEVICE LEVEL — 1x guard_ring/well_island + 12x mos_array
    sampler_dff  (x6)        NOT STARTED — transmission-gate master-slave DFF, no generator surveyed yet
```

"PROVEN AT DEVICE LEVEL" means: every transistor geometry the cell needs is
individually DRC-clean and extracts correctly (`layout/primitives/`) — the
cell itself (multiple devices, placed, routed, DRC/LVS-clean as a unit) does
not exist yet.

## Floorplan decisions made so far

- **Guard/tap-ring strategy**: per-gate, not per-block. Each leaf gate
  (`ro_stage`, `ro_nand2`, `ro_buf`, `xor2`) gets its own `guard_ring` (NMOS
  side, tied to the design's local `vss`) and/or `well_island` (PMOS side,
  named-net tie to that ring's `vddr`/the block's `vdd`) rather than one
  ring around a whole assembled `ro_ring5`/`ro_array_core` — matching how
  the schematic already treats each ring's supply as independent
  (`design/README.md`'s pin table: `vddr1`..`vddr4` are separate,
  specifically so per-ring liveness/independence is observable). A
  per-array-wide ring would blur that independence at the layout level.
- **Routing layer**: `routing.layer_role: "metal"` (li1, sky130's local
  interconnect) for every intra-gate net — the same layer every
  `mos_array`/`guard_ring` port already lands on with `gate_contact: true`,
  so no via-drop is needed inside one gate. Inter-gate/inter-ring routing
  (once `ro_ring5`/`ro_array_core` assembly starts) will likely need a
  second metal (`met1` role name TBD against `klt`'s `_PDK_ROLE_LAYERS`
  table) to cross the per-gate guard rings without shorting into them —
  not yet resolved, tracked in the follow-up issue.
- **`wstv` per-ring variation**: the four rings are NOT identical layout
  cells — `design/ro_array_core.spice`'s `xr1`-`xr4` instantiate `ro_ring5`
  at four different `wstv` values (0.42/0.44/0.46/0.48 µm). The layout plan
  is four distinct physical `ro_stage`/`ro_nand2` starve-device variants
  (same generator call, `w_um` substituted), not one physical cell reused
  four times — matching the schematic's own non-identical-instance intent
  (DR-0003 §8's decorrelation strategy depends on the rings actually
  differing).

## The well-strap gap (the concrete blocking unknown)

`layout/primitives/README.md`'s "What this does NOT establish" section has
the full finding; summary: `mos_array --params '{"flavor":"pfet",...}'`
draws the PMOS's own nwell but no tap into it, so `klt extract` reports an
isolated, unstrapped bulk net per PMOS device. Every reference netlist under
`design/*.spice` ties PMOS bulk explicitly to a supply (`vdd`/`vddr`), so an
LVS-matching gate needs a `guard_ring`/`well_island`-drawn well tap
physically placed to abut (not just neighbor) each PMOS device's own nwell,
with `gen-compose`'s `"explicit"` placement strategy (which performs no
overlap validation of its own, so nesting a device block inside a ring
block's inner cavity is mechanically possible) — the geometry math for that
nesting (ring `inner_width_um`/`inner_height_um` sizing against the enclosed
`mos_array` block's own reported `bbox_um`, concentric origin placement) was
not worked out to convergence in this session and is the single most
concrete item the tracking issue names. NMOS bulk needs no per-device strap
(`vsubs` is sky130's one global substrate net), but still needs at least one
`vsubs`-to-`vss` tap somewhere in the composed design.

## What's deferred (tracking issue)

Everything below issue #22's original scope needed and this PR does not
deliver, tracked in follow-up issue
[2AMLogic/sky130-trng#27](https://github.com/2AMLogic/sky130-trng/issues/27):

1. Solve the well-strap nesting math above; compose one fully DRC-clean
   **and** LVS-clean gate (`ro_buf` is the simplest: 2 devices) end to end
   as the methodology's real proof point.
2. Repeat for `ro_stage`, `ro_nand2` (including the 4-way `wstv` variants),
   and `xor2`.
3. Hierarchical assembly: `ro_ring5` (5 gates + inter-gate routing),
   `ro_array_core` (4 non-identical rings + combining XOR tree),
   `sampler_dff`/`sampler_core` (no generator surveyed yet for a
   transmission-gate DFF — may need `klt draw` or a new `klt gen` generator;
   if the latter is a genuine gap, *that* is the point to file a
   `2AMLogic/klayout-tools` issue, described generically).
4. Full-block `klt drc` + `klt lvs` (assembled netlist vs. `design/*.spice`)
   sign-off.
5. Post-layout PVT re-verification: re-run `sim/`'s existing corner-sweep
   harness (`sim/bin/corner-run.py`) against the `klt extract --parasitics`
   output, recording results under `sim/` per the existing append-only
   convention.
6. Re-evaluate DR-0003 §8's `wstv` inter-ring decorrelation gap using the
   extracted parasitics from step 5 — the measurement DR-0003 explicitly
   flagged as needing a real layout and unmeasurable at the netlist level.

## Reproducing the evidence in `layout/primitives/`

```bash
# PDK pin: see layout/pdk.json (same open_pdks_commit as design/pdk.json, sim/pdk.json)
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

klt gen mos_array --params '{"w_um":0.84,"l_um":0.15,"rows":1,"cols":1,"dummy":0,"flavor":"pfet","gate_contact":true}' \
  --pdk sky130A --cell-name pfet_w0p84_l0p15 -o /tmp/pfet_w0p84_l0p15.gds --format json

klt drc /tmp/pfet_w0p84_l0p15.gds --deck sky130 --format json
klt extract /tmp/pfet_w0p84_l0p15.gds --deck sky130 --format json
```

Repeat with `layout/primitives/README.md`'s table for the other five
geometries.
