# layout

Physical layout evidence for the sky130-trng entropy source, verified with
`klayout-tools` (`klt`) against the sky130 open PDK. See `layout/pdk.json`
for the PDK/tool pin.

**Status (issue #22/#27, this increment): the well-strap composition
methodology is now solved and verified, but not a DRC/LVS-clean block.**
`layout/primitives/` is real, checkable evidence (every distinct transistor
geometry `design/xschem/` instantiates, drawn and independently
DRC-clean/extracted) that klt's generator + composition surface *can* build
this design's layout; `layout/well-strap-poc/` closes the concrete blocking
unknown that work left open (how to physically strap a `mos_array` PMOS's own
nwell to a named supply net). But no multi-device gate, no `ro_ring5`, no
`ro_array_core`, no `sampler_core`, and no post-layout PVT re-verification
exist yet — and a newly-discovered tool regression
([2AMLogic/klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491))
blocks composing this design's real (`l_um=0.15`) gates until resolved. See
"What's deferred" below and the tracking issue (#27) it names.

## Correcting the curation note

Issue #22's curator enhancement (2026-09-05) flagged an open question: `klt`'s
installed command surface, as that curation pass observed it (`layers`,
`stats`, `drc`, `lvs`, `extract`, `synthesize`, `techmap`, `render`, etc.),
looked "verification/synthesis-oriented," with "no obvious path to compose
full-custom analog polygon layout by hand." That reading no longer matches
`klt`'s actual command surface — though, per the "New blocker" note below,
**exactly which build is installed has proven unstable within a single
session** (`klt --version` was observed to report a transient
`0.3.0+g<hash>.dirty` build early in one session and settle to the
officially `uv tool list`-pinned `0.2.0` release later in the same session,
with no action taken by this repo's own tooling to explain the change) — the
version string in a given moment is not reliable evidence of what a fresh
clone of this repo will actually get; `uv tool list`'s own report is the
authoritative pin:

- **`klt gen`** — runs a named parametrized layout generator (a headless
  KLayout PCell) against a JSON params object, producing a GDS/OASIS +
  structured report. The relevant family for this design is the analog
  primitive generators: `mos_array` (matched MOS transistor arrays —
  `layout/primitives/` below is built entirely from this one), `guard_ring`,
  `diff_pair`, `esd_device`, `res_array`, `cap_array`, `bond_pad`,
  `bjt_array`. (A `well_island` generator was observed in the transient build
  mentioned above and used successfully in early exploration, but is **not
  present** in the officially pinned `v0.2.0` release — `layout/
  well-strap-poc/` uses `guard_ring` instead, which the pinned release does
  have, and which turns out to be sufficient.)
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
        ro_nand2              PLANNED — 1x guard_ring (nested well-strap, see well-strap-poc/) + 5x mos_array
        ro_stage   (x4)       PROVEN AT DEVICE LEVEL — 1x guard_ring (nested) + 4x mos_array (layout/primitives/)
      ro_buf     (x4)        PROVEN AT DEVICE LEVEL — 1x guard_ring (nested) + 2x mos_array
      xor2       (x3)        PROVEN AT DEVICE LEVEL — 1x guard_ring (nested) + 12x mos_array
    sampler_dff  (x6)        NOT STARTED — transmission-gate master-slave DFF, no generator surveyed yet
```

"PROVEN AT DEVICE LEVEL" means: every transistor geometry the cell needs is
individually DRC-clean and extracts correctly (`layout/primitives/`) — the
cell itself (multiple devices, placed, routed, DRC/LVS-clean as a unit) does
not exist yet.

## Floorplan decisions made so far

- **Guard/tap-ring strategy**: per-gate, not per-block. Each leaf gate
  (`ro_stage`, `ro_nand2`, `ro_buf`, `xor2`) gets its own PMOS well strap
  (a `guard_ring --params '{"add_well":true}'`, nested around each PMOS
  `mos_array` block per `layout/well-strap-poc/`, named-net tie to that
  ring's `vddr`/the block's `vdd`) rather than one ring around a whole
  assembled `ro_ring5`/`ro_array_core` — matching how
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

## The well-strap gap: SOLVED — see `layout/well-strap-poc/`

`layout/primitives/README.md`'s "What this does NOT establish" section named
the finding: `mos_array --params '{"flavor":"pfet",...}'` draws the PMOS's
own nwell but no tap into it, so `klt extract` reports an isolated,
unstrapped bulk net per PMOS device, while every reference netlist under
`design/*.spice` ties PMOS bulk explicitly to a supply (`vdd`/`vddr`).

[`layout/well-strap-poc/`](well-strap-poc/README.md) solves this: **nest** a
`mos_array` PMOS block inside a `guard_ring --params '{"add_well":true}'`
block's own hollow inner cavity (rather than placing them side by side, which
DRC-violates on `li1.space.1` — the ring's own well margin is a fixed
~0.15 µm, too tight to also clear inter-block `li1` spacing). `guard_ring`'s
own nwell is drawn as one solid rectangle spanning its *entire* outer bbox
(including the cavity), so a device nested inside that cavity shares the same
physical nwell as the ring's tap — merging into one electrical node — while
the ring's own tap diffusion/`li1` stays at whatever DRC-safe clearance the
caller sizes the cavity to give it. Reproduced and verified: `klt drc`
**clean, 0 violations**; `klt extract` resolves the PMOS's bulk terminal to
the named net (`"vdd"`) labelled onto the ring's own tap port via
`gen-compose`'s `pins[]`, not an anonymous one. NMOS still needs no
per-device strap (`vsubs` is sky130's one global substrate net, and `klt
lvs`'s own `device.body_unverified` diagnostic treats an unstrapped NMOS body
as a non-blocking warning, never a match/mismatch verdict change — see the
PoC's README for the citation), but the composed design still needs at least
one `vsubs`-to-`vss` tap somewhere.

**New blocker found while building this fix**: the `klt` version actually
pinned in this environment (`klayout-tools v0.2.0`) does not draw a
DRC-clean `mos_array` unit device for this design's *actual* gate lengths
(`l_um=0.15`, all of this design's non-starve devices) with
`gate_contact: true` — a regression/missing-fix relative to whatever build
produced the already-committed `layout/primitives/` evidence. Filed as
[2AMLogic/klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491);
see `layout/well-strap-poc/README.md`'s "Regression discovered" section for
the full diagnosis. This blocks composing this design's real gates (not the
well-strap methodology itself, which the PoC demonstrates at `l_um=0.28` to
route around it) until resolved.

## What's deferred (tracking issue)

Everything below issue #22's original scope needed and this PR does not
deliver, tracked in follow-up issue
[2AMLogic/sky130-trng#27](https://github.com/2AMLogic/sky130-trng/issues/27):

0. ~~Solve the well-strap nesting math~~ **DONE** — see
   `layout/well-strap-poc/`. Newly blocking this step's continuation:
   [2AMLogic/klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491)
   (this design's real `l_um=0.15` gates DRC-violate against the pinned `klt`
   release independent of the well-strap fix itself) needs resolving before
   step 1 below can use this design's actual device sizes rather than the
   PoC's `l_um=0.28` workaround.
1. Compose one fully DRC-clean **and** LVS-clean gate (`ro_buf` is the
   simplest: 2 devices) end to end as the methodology's real proof point,
   using this design's actual device sizes (blocked on the item above) —
   wiring the S/D/G routing between the two nested-well-strapped devices is
   still open even once unblocked (this PR's PoC only proves the body/well
   connection, not a fully-wired inverter).
2. Repeat for `ro_stage`, `ro_nand2` (including the 4-way `wstv` variants),
   and `xor2`.
3. Hierarchical assembly: `ro_ring5` (5 gates + inter-gate routing),
   `ro_array_core` (4 non-identical rings + combining XOR tree),
   `sampler_dff`/`sampler_core` (no generator surveyed yet for a
   transmission-gate DFF — may need `klt draw` or a new `klt gen` generator;
   if the latter is a genuine gap, *that* is the point to file a
   `2AMLogic/klayout-tools` issue, described generically).
4. Full-block `klt drc` + `klt lvs` (assembled netlist vs. `design/*.spice`)
   sign-off — also revisit the reference-netlist LVS request shape then: this
   PR's own attempt at running `klt lvs` against a hand-written reference
   subckt hit an additional (unresolved, not filed — plausibly this repo's
   own request-construction error rather than a tool gap) device-class-name
   mismatch (`"pfet"` vs. `"PFET"`) when using `reference.form:
   "subckt-call"` with `reference.deck` to convert this design's own
   `XMp ... sky130_fd_pr__pfet_01v8 ...`-style device cards; needs either a
   `reference.device_map` entry or a closer read of
   `klayout_tools.netlist_normalize`'s conversion table before step 1's
   "LVS-clean" claim can be made.
5. Post-layout PVT re-verification: re-run `sim/`'s existing corner-sweep
   harness (`sim/bin/corner-run.py`) against the `klt extract --parasitics`
   output, recording results under `sim/` per the existing append-only
   convention.
6. Re-evaluate DR-0003 §8's `wstv` inter-ring decorrelation gap using the
   extracted parasitics from step 5 — the measurement DR-0003 explicitly
   flagged as needing a real layout and unmeasurable at the netlist level.

## Reproducing the evidence in `layout/primitives/`

**Caveat added by this PR**: re-running the exact command below (`l_um=0.15`)
against the `klt` version actually pinned in this environment
(`klayout-tools v0.2.0`) reproduces the *layout* but does **not** currently
reproduce the *clean DRC verdict* — see
[2AMLogic/klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491)
and `layout/well-strap-poc/regression-evidence/`. The already-committed
`.gds`/`drc.json` files under `layout/primitives/` are unaffected (they are
static bytes; `klt drc` re-checks *those* files clean today) — only a
from-scratch regeneration is affected.

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
