# layout

Physical layout evidence for the sky130-trng entropy source, verified with
`klayout-tools` (`klt`) against the sky130 open PDK. See `layout/pdk.json`
for the PDK/tool pin.

**Status (issue #22/#27, this increment): one real gate is now composed,
DRC-clean and LVS-clean — but not a DRC/LVS-clean block.**
[`layout/ro_buf/`](ro_buf/README.md) is `design/ro_array_core.spice`'s own
`.subckt ro_buf` inverter, built from `klt gen` primitives, placed and routed
by `klt gen-compose`, **`klt drc` clean (0 violations)** and **`klt lvs`
matching the design netlist (2/2 devices, 4/4 nets, 0 mismatches)**. That
closes step 1 of the deferred list below and, with it, the last open question
about whether this methodology reaches a working cell at all.

Everything under it is still open: no `ro_stage`/`ro_nand2`/`xor2`, no
`ro_ring5`, no `ro_array_core`, no `sampler_core`, and no post-layout PVT
re-verification. See "What's deferred" below and the tracking issue (#27).

The earlier increments remain the foundation: `layout/primitives/` is
per-device evidence (every distinct transistor geometry `design/xschem/`
instantiates, drawn and independently DRC-clean/extracted), and
`layout/well-strap-poc/` established that a `guard_ring`'s nwell merges with a
`mos_array` PMOS's own. `ro_buf` changes *how* that merge is arranged —
abutted rather than nested, see below — because a nested device turns out to
be unroutable.

The `klt` regression the previous increment filed
([2AMLogic/klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491),
sub-0.28 µm gate length + `gate_contact` DRC-violating) is **fixed** as of
`klt 0.3.0+gc6dbf66c53c6`: regenerating `pfet_w0p84_l0p15`'s exact params from
scratch is DRC-clean again, and `ro_buf` is built entirely at this design's
real `l_um=0.15`.

## Correcting the curation note

Issue #22's curator enhancement (2026-09-05) flagged an open question: `klt`'s
installed command surface, as that curation pass observed it (`layers`,
`stats`, `drc`, `lvs`, `extract`, `synthesize`, `techmap`, `render`, etc.),
looked "verification/synthesis-oriented," with "no obvious path to compose
full-custom analog polygon layout by hand." That reading does not match
`klt`'s actual command surface — though **which build is installed has proven
unstable across sessions**, which is itself worth recording: the previous
increment saw `uv tool list` report `klayout-tools v0.2.0` (and a transient
`0.3.0+g<hash>.dirty` earlier in the same session), while this one sees
`v0.3.0` / `klt 0.3.0+gc6dbf66c53c6`, with a regression fixed in between and
a `well_island` generator that had come and gone now present again. The
version string in a given moment is not reliable evidence of what a fresh
clone of this repo will get; `uv tool list` plus each artifact's own
`provenance.klt_version` are the record. The composition-side verbs:

- **`klt gen`** — runs a named parametrized layout generator (a headless
  KLayout PCell) against a JSON params object, producing a GDS/OASIS +
  structured report. The relevant family for this design is the analog
  primitive generators: `mos_array` (matched MOS transistor arrays —
  `layout/primitives/` below is built entirely from this one), `guard_ring`,
  `diff_pair`, `esd_device`, `res_array`, `cap_array`, `bond_pad`,
  `bjt_array`. (A `well_island` generator — absent from the `v0.2.0` release
  the previous increment saw — is present again in `v0.3.0`. Neither
  `layout/well-strap-poc/` nor `layout/ro_buf/` uses it: `guard_ring` is
  present in every observed build and is sufficient for both, so the cells
  stay buildable across this churn.)
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
        ro_nand2              PLANNED — 2x guard_ring (abutted body ties) + 5x mos_array
        ro_stage   (x4)       PROVEN AT DEVICE LEVEL — 2x guard_ring (abutted) + 4x mos_array (layout/primitives/)
      ro_buf     (x4)        BUILT — DRC-clean + LVS-clean (layout/ro_buf/)
      xor2       (x3)        PROVEN AT DEVICE LEVEL — 2x guard_ring (abutted) + 12x mos_array
    sampler_dff  (x6)        NOT STARTED — transmission-gate master-slave DFF, no generator surveyed yet
```

"PROVEN AT DEVICE LEVEL" means: every transistor geometry the cell needs is
individually DRC-clean and extracts correctly (`layout/primitives/`) — the
cell itself (multiple devices, placed, routed, DRC/LVS-clean as a unit) does
not exist yet.

## Floorplan decisions made so far

- **Guard/tap-ring strategy**: per-gate, not per-block. Each leaf gate
  (`ro_stage`, `ro_nand2`, `ro_buf`, `xor2`) gets its own pair of tap islands
  (a `guard_ring --params '{"add_well":true}'` tied to `vdd`/`vddr` for the
  PMOS row, and a `guard_ring --params '{"add_well":false}'` tied to `vss` for
  the NMOS row), **abutted** to the device blocks rather than nested around
  them — see `layout/ro_buf/README.md` § "Why abutted, not nested". One ring
  around a whole assembled `ro_ring5`/`ro_array_core` was rejected, matching
  how the schematic already treats each ring's supply as independent
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

## Composing a gate: the working recipe

`layout/bin/compose-cell.py` drives the whole chain for one cell from a
committed descriptor (`layout/<cell>/cell.json`):

```
klt gen (per device/tap block) -> klt gen-compose -> klt drc -> klt extract -> klt lvs
```

```bash
python3 layout/bin/compose-cell.py layout/ro_buf/cell.json           # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_buf/cell.json --check   # verify without overwriting
```

Every step's JSON response is written next to the descriptor, so
`layout/<cell>/` is the full re-checkable evidence trail, and `--check` is the
layout sibling of `design/netlist.py --check` (rebuild into a temp dir, diff
the verdict-bearing fields against what is committed). All `klt` invocations
run from the cell directory with relative paths, so no absolute home path
leaks into the committed provenance.

**`--check` is now an automated regression guard, not just a manual
command** (issue #36): `.github/workflows/pdk-nightly.yml`'s `layout-check`
job runs `compose-cell.py --check` over every committed `layout/*/cell.json`
(currently just `layout/ro_buf/cell.json` — re-globbed at run time, not
hardcoded, so it keeps up as `ro_stage`/`ro_nand2`/`xor2` land per issue #27),
on the same trigger surface as the `netlist-check` job it sits beside in that
file: `schedule`, `workflow_dispatch`, and opt-in on a PR via the
`run-pdk-check` label, so it never adds the PDK/`klt` download cost to every
PR by default. This is the automated version of what
[klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491)
proved could otherwise silently invalidate already-committed evidence between
sessions.

That job installs `klt` from PyPI, pinned to the latest *tagged* release
(`klayout-tools==0.4.0` as of 2026-09-05) rather than to `layout/pdk.json`'s
committed `klt_version_pin` (a dev snapshot with no PyPI artifact of its own)
— see `layout/pdk.json`'s `ci_klt_install` comment for the full rationale.
Verified 2026-09-05: `klt 0.4.0` from PyPI reproduces `layout/ro_buf/`'s
committed evidence exactly.

The three constraints that decide a cell's floorplan, all learned building
`ro_buf` (see [`layout/ro_buf/README.md`](ro_buf/README.md) for each one's
evidence):

1. **Body ties abut, they do not enclose.** Overlap the device block's and
   the tap ring's `bbox_um` by 0.10 µm: their nwells merge (one electrical
   node, so the PMOS bulk extracts to the ring's labelled net) while their
   `li1` stays 0.20 µm apart, clear of sky130's 0.17 µm spacing floor. A
   *nested* device — `layout/well-strap-poc/`'s original geometry — is
   body-tied but **unroutable**: `gen-compose` treats the enclosing ring as an
   unrelated block and rejects every route reaching the device inside it
   (upstream: [klayout-tools#1493](https://github.com/2AMLogic/klayout-tools/issues/1493)).
2. **Mirror the PMOS row in `y`** (`blocks[].orientation: "mirror_y"`) so its
   gate faces the NMOS row's up-facing gate. Two same-facing gate ports make
   the router lift the connecting jog above both blocks, straight through the
   PMOS.
3. **Give a same-facing S/D pair an explicit `waypoints_um` lane** clear of
   both blocks' bboxes. The default one-stub-width jog runs back through the
   devices.

Two more, discovered while planning `ro_stage` and not yet resolved (issue
#27's step 2 starts here):

- **A port may be named by `pins[]` *or* wired by `connectivity[]`, never
  both.** An internal net that is also a cell pin therefore takes its name
  from its `connectivity[]` entry — which works, and is how `ro_buf`'s `a`/`y`
  come out named.
- **`ro_stage`/`ro_nand2` are not single-layer planar.** Their starve devices
  are cross-coupled to the rails (`Mph.g = vss`, `Mnt.g = vddr`), so with one
  tap island per rail on one side the two gate routes must cross. `klt
  gen-compose` performs no net-to-net short check (only block-obstacle,
  ring-opening and same-block pad checks), so a crossing composes "routed"
  and is caught only downstream by `klt extract`/`klt lvs` — treat an LVS
  match, not a routed verdict, as the gate's acceptance test. The fix is
  either a second tap island per rail placed near the gate that needs it (the
  substrate/well is itself the conductor joining two taps of the same net), or
  per-net routing-layer selection, which `routing.layer_role` does not offer
  today.

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

**Two corrections to the above, from building `layout/ro_buf/`:**

- **The nesting geometry is superseded.** Nesting does merge the wells, as
  described — but `gen-compose` then refuses to route *any* of the enclosed
  device's terminals, because its obstacle check counts the enclosing ring as
  an unrelated placed block (reproduced directly against this PoC's own
  committed blocks; see `layout/ro_buf/README.md` § "Why abutted, not
  nested", and upstream
  [klayout-tools#1493](https://github.com/2AMLogic/klayout-tools/issues/1493)).
  Abutting the two blocks with a 0.10 µm bbox overlap achieves the same well
  merge *and* leaves every terminal routable. New cells should abut.
- **The `l_um=0.15` regression is fixed.** The blocker recorded here
  ([klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491),
  now closed) does not reproduce on `klt 0.3.0+gc6dbf66c53c6`: regenerating
  `pfet_w0p84_l0p15`'s exact params from scratch is DRC-clean, with the same
  `bbox_um.x1 = 1.24` the committed evidence reports, and the generator's
  `drc_hints.notes` again cites the issue #1187 S/D-pad padding fix. Every
  device in `layout/ro_buf/` is drawn at this design's real `l_um=0.15`.

## What's deferred (tracking issue)

Everything below issue #22's original scope needed and this PR does not
deliver, tracked in follow-up issue
[2AMLogic/sky130-trng#27](https://github.com/2AMLogic/sky130-trng/issues/27):

0. ~~Solve the well-strap geometry~~ **DONE** — see
   `layout/well-strap-poc/` for the well-merge finding and
   `layout/ro_buf/README.md` § "Why abutted, not nested" for the routable
   form of it. The `l_um=0.15` regression that blocked this
   ([klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491))
   is fixed and closed.
1. ~~Compose one fully DRC-clean **and** LVS-clean gate end to end as the
   methodology's real proof point~~ **DONE** — `layout/ro_buf/`: `klt drc`
   clean (0 violations), `klt lvs` **match** against
   `design/ro_array_core.spice`'s own `.subckt ro_buf` (2/2 devices, 4/4
   nets), at this design's real device sizes, reproducible from a committed
   descriptor via `layout/bin/compose-cell.py`.
2. Repeat for `ro_stage`, `ro_nand2` (including the 4-way `wstv` variants),
   and `xor2`. **Start here.** `ro_buf`'s recipe (abutted tap islands,
   `mirror_y` PMOS row, `waypoints_um` for same-facing S/D pairs) carries
   over, but `ro_stage`/`ro_nand2` add a series PMOS/NMOS stack and a
   rail-crossing pair of starve-device gate nets that is **not planar on one
   routing layer** — see "Composing a gate" above for the two candidate
   resolutions. `layout/bin/compose-cell.py`'s `lvs.params`/`lvs.drop_prefixes`
   fields already exist for these cells: `params` substitutes the `wstv`/
   `lstv` values into the reference subckt's `L=lstv W=wstv` device cards
   (one descriptor per ring variant), and `drop_prefixes: ["Cld"]` drops the
   lumped load capacitor, which is a simulation load model with no physical
   counterpart, not a device the layout omits.
3. Hierarchical assembly: `ro_ring5` (5 gates + inter-gate routing),
   `ro_array_core` (4 non-identical rings + combining XOR tree),
   `sampler_dff`/`sampler_core` (no generator surveyed yet for a
   transmission-gate DFF — may need `klt draw` or a new `klt gen` generator;
   if the latter is a genuine gap, *that* is the point to file a
   `2AMLogic/klayout-tools` issue, described generically).
4. Full-block `klt drc` + `klt lvs` (assembled netlist vs. `design/*.spice`)
   sign-off. The **reference-netlist request shape is now settled** (it was
   listed here as an open unknown, mis-diagnosed as a `"pfet"`/`"PFET"`
   device-class-name mismatch): `reference.form: "subckt-call"` with
   `reference.deck: "sky130"` is correct, and the real cause of the total
   mismatch was that its converter reads an **unsuffixed** `L=`/`W=` value as
   SI metres, while this design's netlists are unitless under
   `.option scale=1u` — so `L=0.15` became a 0.15 m gate and nothing matched.
   `layout/bin/compose-cell.py` appends the explicit `u` suffix; filed
   upstream as
   [klayout-tools#1492](https://github.com/2AMLogic/klayout-tools/issues/1492).
   Note also that `klt`'s sky130 deck is a **curated subset**, not sky130
   sign-off — read each `drc.json`'s own `coverage` block (`deck_scope`,
   `layers_checked`, `layers_in_stream_without_rules`) before calling any
   result "DRC-clean" without qualification.
5. Post-layout PVT re-verification: re-run `sim/`'s existing corner-sweep
   harness (`sim/bin/corner-run.py`) against the `klt extract --parasitics`
   output, recording results under `sim/` per the existing append-only
   convention.
6. Re-evaluate DR-0003 §8's `wstv` inter-ring decorrelation gap using the
   extracted parasitics from step 5 — the measurement DR-0003 explicitly
   flagged as needing a real layout and unmeasurable at the netlist level.

   **Status after this increment: still open, and deliberately not
   re-evaluated.** DR-0003 §8's condition is not "some layout exists" but
   "extracted parasitics of the *assembled array* exist" — the quantity it
   names is the coupling between *rings* through shared supply impedance and
   the substrate, which by construction cannot be measured on a single leaf
   cell. `layout/ro_buf/` is one gate, of which the array contains four
   instances out of ~100 devices total, and its `klt extract` was run
   **without** `--parasitics`. Nothing in this increment changes what §8
   records, so nothing supersedes it; per this repo's decision-record
   convention a correction supersedes rather than edits in place, and there is
   no correction to make yet. The re-evaluation becomes possible at step 5,
   not before.

## Reproducing the evidence in `layout/primitives/`

**The caveat a previous increment added here is withdrawn.** It recorded that
regenerating these `l_um=0.15` geometries against the then-pinned
`klayout-tools v0.2.0` reproduced the layout but not the clean DRC verdict
([klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491),
evidence preserved under `layout/well-strap-poc/regression-evidence/`). That
issue is closed, and on `klt 0.3.0+gc6dbf66c53c6` a from-scratch regeneration
is DRC-clean again with byte-identical reported geometry — re-verified for
`pfet_w0p84_l0p15` while building `layout/ro_buf/`.

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

## Reproducing `layout/ro_buf/`

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_buf/cell.json --check
```

`--check` rebuilds the whole chain into a temporary directory and diffs the
verdict-bearing fields (`drc.json`'s `status`/`violation_count`,
`extract.json`'s `status`/`device_count`/`net_count`/`device_counts`,
`lvs.json`'s `status`/`mismatch_count`/`error_count`/`counts`, and
`compose.response.json`'s `cell_name`/`bbox_um`) against what is committed,
without touching it. Drop `--check` to regenerate in place.
