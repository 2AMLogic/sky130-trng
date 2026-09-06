# layout

Physical layout evidence for the sky130-trng entropy source, verified with
`klayout-tools` (`klt`) against the sky130 open PDK. See `layout/pdk.json`
for the PDK/tool pin.

**Status (issue #22, this increment): `ro_array_core`'s buffer→XOR `b` leg
is now really routed for both first-stage XORs, completing the forward
ring→buffer→XOR signal path for `xa1`/`xa2` —
[`layout/ro_array_core-placement-poc/`](ro_array_core-placement-poc/README.md)'s
"Increment 4" section.** `ro2` (`buf2.y`) is now really routed into `xa1`'s
`b` input, and `ro4` (`buf4.y`) into `xa2`'s `b` input, on `"metal2"`,
resolving the previous increment's own open finding. Still **`klt drc`
clean (0 violations)**, and `klt extract` now reports `132` devices
(unchanged) and `104` nets (down from `106`, exactly the two new merges,
each confirmed by a net-by-net diff to join only its intended `b`-labelled
net). Two findings: `gen-compose` rejects a backbone that crosses through a
*third*, unrelated block's own bounding box even well above the row being
routed through (discovered when a first attempt tried routing above
`xa1`/`xa2`'s own row height to dodge congestion, and was rejected for
crossing `xa2`'s/`xa3`'s own bbox); and the corridor between row 1 and row 2
had room for exactly one more pair of dedicated channels once reasoned about
via the two existing backbones' own vertical-segment extents (`y=8.5`/
`10.0`, distinct from `a`'s `y=8.0`/`9.0`) — see the PoC's own README
"Increment 4" section for both findings in full. **Still not a
DRC/LVS-clean `ro_array_core`**: `vdd`/`vss` (a genuinely global net —
rings, buffers *and* XORs all share `vss`, eleven taps total), the XOR
combining tree (`t1`, `t2`, `xo`), and therefore any LVS attempt, are all
still open. The PoC's README also carries an open question on
`compose-cell.py`'s `lvs.dependencies` mechanism, unchanged by this
increment: the reference netlist defines one `ro_ring5` subckt called four
times with four different `wstv=` overrides, not four separate subckts, and
the current dependency mechanism has not been exercised against that shape.

**A previous increment: `ro_array_core`'s buffer→XOR `a` leg was routed for
both first-stage XORs** —
[`layout/ro_array_core-placement-poc/`](ro_array_core-placement-poc/README.md)'s
"Increment 3" section. `ro1` (`buf1.y`) was routed into `xa1`'s `a` input,
and `ro3` (`buf3.y`) into `xa2`'s `a` input, on `"metal2"` — the first
routing this directory drew between row 1 (rings/buffers) and row 2 (the XOR
combining tree), needing an escape-margin fix for the source pin's own tiny
edge margin. `b` was deliberately left unwired that increment (resolved
above).

**A previous increment: `ro_array_core`'s forward
ring→buffer signal chain was routed** —
[`layout/ro_array_core-placement-poc/`](ro_array_core-placement-poc/README.md)'s
"Increment 2" section. On top of the same eleven-block floorplan the
previous increment placed, `en1..en4` and the four `vddrN` domains were
exposed as top-level pins directly off each ring's own already-formed
internal node (no routing needed — each is already one electrical node
inside its own ring), `ro1..ro4` were exposed the same way off each buffer's
`y` output, and the four `rn1..rn4` legs (`ro_ring5.ro` → `ro_buf.a`) were
newly, really routed on `"metal2"` — the first inter-cell wiring this
hierarchy level drew. One floorplan finding: `gen-compose` rejects a route
whose final leg drops straight into a block's interior toward a pin that
sits well inside that block's own bbox, with a precise measured diagnostic —
see the PoC's own README for the fix (approach horizontally at the pin's own
`y` instead).

**A previous increment: `xor2` is composed, DRC-clean and
LVS-clean, so every leaf cell `ro_array_core` instantiates now exists as a
verified physical cell.** [`layout/xor2/`](xor2/README.md) is
`design/ro_array_core.spice`'s own `.subckt xor2` — twelve devices, ten nets
— **`klt drc` clean (0 violations)** and **`klt lvs` match (12/12 devices,
10/10 nets, 0 errors)**, in two `gen-compose` stages across two routing
planes. It supersedes `layout/xor2-placement-poc/`, whose prediction that
this cell would need "full channel-router-style joint net ordering" and
plausibly a third routing plane was **wrong**: three structural moves —
reading the pull-up tree as two `finger_topology: "series"` chains sharing a
*contactable interior* `U0_D0` (`mid`), placing the two inverters as
already-composed `ro_buf` `blocks[].cell` blocks, and splitting the nets
across *layers* (`vdd`/`mid`/`y`/`vss` on li1, `a`/`an`/`b`/`bn` on met1)
rather than across lanes on one layer — reduce the problem from 17 blocks
and 31 nets to 9 blocks and 12 net legs. All fourteen composed cells
(`ro_buf`, `ro_stage` x4, `ro_nand2` x4, `ro_ring5` x4, `xor2`) `--check`
clean against `layout/pdk.json`'s `klt_version_pin` in the same session.
**Still open:** `ro_array_core` itself (the four rings + `ro_buf` fan-out +
the three-`xor2` combining tree) and `sampler_core`, so this is still not a
DRC/LVS-clean *block*; the array-level (inter-ring) parasitics — supply
distribution, the XOR tree's own routing, buffer fan-in — remain undrawn,
and DR-0003 §8's decorrelation gap is unchanged by this increment (still
bounded but not closed, for the reasons
`spec/decision-records/DR-0005-*.md` already states). `xor2` has no `sim/`
record and no `layout/pex/` entry: a post-layout campaign is its own
deliverable with its own PVT-corner discipline.

**A previous increment: the four composed `ro_ring5` rings
have their own ring-level post-layout PVT evidence** —
[`layout/pex-ring/`](pex-ring/README.md) extracts each ring's *whole*
composed GDS directly (real inter-gate `n1`-`n4`/`ro` routing and `vddr`/`vss`
rail busing included, not the ideal inter-cell wires the earlier leaf-cell
`layout/pex/` composition assumes), and
[`sim/post-layout-ro-ring5-assembled/`](../sim/post-layout-ro-ring5-assembled/)
runs the same period/swing/current measurement from it across the full PVT
grid. Headline: real inter-gate wiring costs the ring roughly another
50-65% multiplicatively beyond intra-cell parasitics alone, and the `wstv`
ladder still survives (see `sim/README.md`'s "Assembled-ring post-layout"
section for the full reduction). `ro_array_core` (the four rings + `ro_buf`
fan-out + the `xor2` combining tree) and `sampler_core` are still open, so
this is still not a DRC/LVS-clean *block*, and the array-level (inter-ring)
parasitics — supply distribution, the XOR tree's own routing, buffer fan-in
— remain undrawn; DR-0003 §8's decorrelation gap is bounded but not closed
for the reasons `spec/decision-records/DR-0005-*.md` already states.

[`layout/ro_ring5/`](ro_ring5/README.md) and its three `wstv` siblings
([`_wstv0p44`](ro_ring5_wstv0p44/README.md),
[`_wstv0p46`](ro_ring5_wstv0p46/README.md),
[`_wstv0p48`](ro_ring5_wstv0p48/README.md)) are
`design/ro_array_core.spice`'s own `.subckt ro_ring5` — five leaf gates
placed via `blocks[].cell`, the four forward nets, the `ro` feedback and
both `vddr`/`vss` rails all routed — each **`klt drc` clean (0 violations)**
and **`klt lvs` match (22/22 devices, 19/19 nets, 0 errors)** against the
schematic's own subckt at that ring's `wstv`. Four `gen-compose` stages
across three physical routing planes (li1-pinned placement, `n1`-`n4` and
`ro` on met1, rails on met2); see `layout/ro_ring5/README.md` for why each
plane is needed and the measured evidence behind each coordinate.

This increment also **corrects two wrong claims** in the previous one's
`ro_ring5-connectivity-poc`: its `n1`-`n4` were not merely marginal, they
were a single shorted node (its own committed `extract.json`'s
`merged_net_labels`/`warnings` said so and were read for counts only), and
its "5 unexplained device-internal `li1.space.1` violations" were the same
routes, not a hierarchy-dependent DRC effect — the corrected placement with
no routing at all is DRC-clean. See that directory's own README, which now
opens with the correction.

**Earlier increments (leaf cells, still the foundation):** both starved
leaf-gate ladders are composed at all four ring widths — nine composed cells
(three distinct gate types: `ro_buf`, plus `ro_stage` and `ro_nand2` at each
of the four `wstv` values), every one DRC-clean and LVS-clean.
[`layout/ro_buf/`](ro_buf/README.md) is `design/ro_array_core.spice`'s own
`.subckt ro_buf` inverter, built from `klt gen` primitives, placed and routed
by `klt gen-compose`, **`klt drc` clean (0 violations)** and **`klt lvs`
matching the design netlist (2/2 devices, 4/4 nets, 0 mismatches)**. That
closed step 1 of the deferred list below and, with it, the last open question
about whether this methodology reaches a working cell at all.
[`layout/ro_stage/`](ro_stage/README.md) is the array's own per-stage starved
delay cell — four devices whose starve pair cross-couples to the *opposite*
rail, which needed a genuinely new capability (`compose-cell.py`'s two-pass
`"stages"` composition, routing the two crossing nets on a second metal level)
to compose at all — also **`klt drc` clean (0 violations)** and **`klt lvs`
match (4/4 devices, 6/6 nets)**. That closes the harder half of step 2 below.
[`layout/ro_nand2/`](ro_nand2/README.md) is each `ro_ring5`'s enable-gated
first stage — six devices (the same cross-coupled starve pair as `ro_stage`,
plus a parallel PMOS pull-up pair and a series NMOS pull-down pair, both new
floorplan shapes) — also **`klt drc` clean (0 violations)** and **`klt lvs`
match (6/6 devices, 8/8 nets)**, reusing `ro_stage`'s two-pass `"stages"`
technique but extended from 2 to 6 same-block self-nets resolved in one final
`gen-compose` call (see `layout/ro_nand2/README.md` for the parallel/series
floorplan problems this needed and the six empirically-derived routing lanes).

**A previous increment**: `ro_stage`/`ro_nand2` are each cloned three more times —
[`ro_stage_wstv0p44`](ro_stage_wstv0p44/README.md),
[`ro_stage_wstv0p46`](ro_stage_wstv0p46/README.md),
[`ro_stage_wstv0p48`](ro_stage_wstv0p48/README.md) and
[`ro_nand2_wstv0p44`](ro_nand2_wstv0p44/README.md),
[`ro_nand2_wstv0p46`](ro_nand2_wstv0p46/README.md),
[`ro_nand2_wstv0p48`](ro_nand2_wstv0p48/README.md) — one physical cell per
ring (`design/ro_array_core.spice`'s `xr1`-`xr4`, `wstv` 0.42/0.44/0.46/0.48
µm), matching the schematic's own non-identical-ring intent. All six new
cells are **`klt drc` clean (0 violations)** and **`klt lvs` match**, closing
issue #27 step 2's "repeat for... the 4-way `wstv` variants" in full. See
"Starve-width variants" below for what does (and does not) change per width,
and why the naive clone-and-reparametrize approach fails without it.

**A previous increment (issue #22, follow-up), now superseded**:
[`layout/xor2-placement-poc/`](xor2-placement-poc/README.md) placed all
twelve of `xor2`'s real devices individually (every PMOS with its own well
tap), **`klt drc` clean (0 violations)** and **`klt extract` confirming 12
devices, 6 nfet + 6 pfet** — but left routing open and concluded it was a
channel-routing problem needing a third routing plane. `layout/xor2/`
above shows it is not, and shares none of that PoC's coordinates; its
README now opens with the correction. Two findings from it *are* still
load-bearing and are used by `layout/xor2/`: `"metal3"`'s single-hop
via-drop rule (see "Floorplan decisions made so far" below), and the rule
that two wired segments sharing an endpoint pin must be chained under **one**
shared net name rather than two.

**A previous increment (issue #22, post-layout)**: the nine composed cells are now
**simulated**. [`layout/pex/`](pex/README.md) is a generated, `--check`-guarded
post-layout netlist library — `klt extract --parasitics` over each cell's
committed GDS, rewritten for ngspice by `layout/bin/pex-netlist.py` — and
`sim/post-layout-ro-ring5/` runs the five-stage ring from it over the PVT
grid (twelve records, thirty-six corner runs), with the pre-layout netlist
as a same-deck control. That closes step 5 below for the leaf-cell scope
that exists, and turns step 6 (DR-0003 §8's `wstv` decorrelation gap) from
"unmeasurable" into "bounded, and still open for the mechanism that
matters" — see `spec/decision-records/DR-0005-*.md`. All nine cells were
re-verified DRC-clean and LVS-clean (`compose-cell.py --check`, `klt 0.4.0`)
in the same session, so the GDS carrying these parasitics is the GDS
carrying those verdicts.

**Previous increment (issue #22, hierarchical assembly, first attempt —
superseded, see the correction above)**:
[`layout/ro_ring5-connectivity-poc/`](ro_ring5-connectivity-poc/README.md)
places all five of `ro_ring5`'s leaf gates (`ro_nand2` + 4x `ro_stage`) via
`klt gen-compose`'s `blocks[].cell` request shape — the first proof that an
*already-composed* cell (not a fresh `klt gen` primitive) can be placed and
inter-wired this way — the one finding of that attempt that survives. It
also *reported* the four forward inter-gate signal nets (`n1`-`n4`) as
routed, which **they were not**: they are one shorted node in its committed
`core.gds`, as its own `extract.json` says (see the correction at the top of
this file and that directory's own README). **Not DRC-clean and not
LVS-attempted**: the placement pitch borrowed
unchanged from the original (uncommitted, recovered-and-superseded) attempt
is `0.27 µm` short of `nwell.space.1`'s clearance at the `ro_nand2`/`ro_stage`
boundary (correctly diagnosed), plus seven
`li1.space.1` violations it recorded as "2 attributed + 5 unexplained
device-internal" and which are in fact all seven the same routes, and the
ring's `vddr`/`vss`/`ro` rail busing hit a genuine `klt` via-drop limitation
(`routing.cross_block_layer_role` cannot rescue a bare base-layer pin —
single-hop-only, same limitation `"metal3"`'s own note below already
describes from a different angle) that stopped this attempt before DRC/LVS
were reachable. `layout/bin/compose-cell.py` gained `blocks[].cell` support
and multi-subckt LVS references (`lvs.dependencies`) to get this far, both
regression-tested against all nine previously-committed cells. Its
recommended next recipe — a three-stage li1→metal2→metal3 rail promotion —
turned out to be **unnecessary**: both rails are already drawn on met1
inside every leaf gate, so declaring the block's rail port on met1 satisfies
the single-hop rule directly (see `layout/ro_ring5/README.md`).

Everything else is still open: `ro_array_core`, `sampler_core`, and
therefore any *whole-block* post-layout claim. See "What's deferred" below
and the tracking issue (#27).

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
`provenance.klt_version` are the record.

**The churn is not only between sessions — it happens mid-session, and it
can be a downgrade past the features this directory depends on.** While
building `layout/ro_ring5/`, the ambient `uv`-managed `klt` changed from
`0.3.0+gc6dbf66c53c6` to **`0.2.0`** *between two commands*, with the
replacement installed from a pinned upstream commit ~324 commits behind the
one it replaced. `0.2.0` has no `blocks[].cell` request shape at all, so
every cell here that places an already-composed sibling fails outright with
a misleading `blocks[].generator_report must be a JSON object or a path to
one`. If you hit that error, check `klt --version` before debugging the
request. The fix is to build the pinned version into a venv of your own
rather than fighting over the shared tool install:

```bash
python3 -m venv /tmp/klt-venv
/tmp/klt-venv/bin/pip install \
  "git+https://github.com/2AMLogic/klayout-tools@c6dbf66c53c6e9a73c4f5ae5e41a98e8fe414252"
/tmp/klt-venv/bin/klt --version          # klt 0.3.0+gc6dbf66c53c6
PATH=/tmp/klt-venv/bin:$PATH python3 layout/bin/compose-cell.py layout/ro_ring5/cell.json --check
```

That commit is `layout/pdk.json`'s own `klt_version_pin`, and all fourteen
composed cells `--check` clean against it. Not filed upstream as a tool
gap: klayout-tools is behaving correctly at every version; this is an
environment-management problem on the consuming side, and the pin plus the
per-artifact `provenance.klt_version` already record it.

The composition-side verbs:

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
    ro_array_core           IN PROGRESS — floorplanned (ro_array_core-placement-poc/), forward signal chain routed (en/vddr/ro exposed, rn1-4 wired) and buffer->XOR "a" leg routed (ro1/ro3 into xa1.a/xa2.a), DRC-clean; ro2/ro4 into xa1.b/xa2.b, vdd/vss distribution, XOR combining tree and LVS still open
      ro_ring5   (x4)        BUILT, all 4 wstv values — DRC-clean + LVS-clean (layout/ro_ring5/, ro_ring5_wstv0p{44,46,48}/) — 4 distinct physical cells, one per ring; signal chain, ro feedback and vddr/vss rails all routed
        ro_nand2   (x1/ring)  BUILT, all 4 wstv values — DRC-clean + LVS-clean (layout/ro_nand2/, ro_nand2_wstv0p{44,46,48}/) — 4 distinct physical cells, one per ring
        ro_stage   (x4/ring)  BUILT, all 4 wstv values — DRC-clean + LVS-clean (layout/ro_stage/, ro_stage_wstv0p{44,46,48}/) — 4 distinct physical cells (one per ring's wstv), each reused 4x within its own ring
      ro_buf     (x4)        BUILT — DRC-clean + LVS-clean (layout/ro_buf/)
      xor2       (x3)        BUILT — DRC-clean + LVS-clean (layout/xor2/) — 4x mos_array (two series chains per tree) + 3x guard_ring + 2x ro_buf cell; one physical cell reused 3x (xa1/xa2/xa3 are identical instances)
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
  second metal to cross the per-gate guard rings without shorting into
  them. **Resolved, correcting the "TBD" note this bullet previously
  carried**: `klt` 0.4.0 resolves `routing.layer_role: "metal2"` (met1, via
  `via1`) *and* `"metal3"` (met2, via `via2`) against
  `klayout_tools.gen._PDK_ROLE_LAYERS["sky130"]` — confirmed by reading the
  installed package directly (`layout/xor2-placement-poc/README.md` has the
  full citation), since neither role appears in this checkout's own
  `docs/cli/gen-compose.md`. The catch: `"metal3"`'s via-drop is
  single-hop-only, so it can only bridge two pins *already* wired onto
  `"metal2"` by an earlier stage — it cannot reach a bare `li1` pin
  directly the way `"metal2"` can. `ro_stage`/`ro_nand2` only ever needed
  `"metal2"`; `xor2-placement-poc`'s own routing attempt predicted that
  `xor2` would be the first case in this repo where a `"metal3"` stage is
  necessary — **falsified by `layout/xor2/`**, which routes the whole gate
  on li1 + `"metal2"` and leaves met2 empty (see that cell's README, and
  points 9-10 in "Composing a gate" above). `"metal3"` remains used by
  exactly one cell family, `ro_ring5`'s rail busing. **`layout/ro_ring5/` is the
  first cell that actually uses all three planes**, and it shows the
  single-hop rule is cheaper to satisfy than it looks: rather than adding a
  promotion stage, declare the block port on the layer the pin is *already*
  drawn on. Both rails are on met1 inside every leaf gate, so `"metal3"` is
  one hop away from them; only the li1-pinned signal nets need `"metal2"`.
- **`wstv` per-ring variation**: the four rings are NOT identical layout
  cells — `design/ro_array_core.spice`'s `xr1`-`xr4` instantiate `ro_ring5`
  at four different `wstv` values (0.42/0.44/0.46/0.48 µm). The layout is
  four distinct physical `ro_stage`/`ro_nand2` starve-device variants (same
  generator call, `w_um` substituted, plus the origin re-derivation below),
  not one physical cell reused four times — matching the schematic's own
  non-identical-instance intent (DR-0003 §8's decorrelation strategy depends
  on the rings actually differing). **Done, both cell types, all four
  widths** — see "Starve-width variants" below.

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
(fourteen as of 2026-09-06 — re-globbed at run time, not hardcoded, so it
keeps up automatically as more cells land per issue #27), on the same
trigger surface as the `netlist-check` job it sits beside in that file:
`schedule`, `workflow_dispatch`, and opt-in on a PR via the `run-pdk-check`
label, so it never adds the PDK/`klt` download cost to every PR by default.
This is the automated version of what
[klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491)
proved could otherwise silently invalidate already-committed evidence between
sessions.

That job installs `klt` from PyPI, pinned to the latest *tagged* release
(`klayout-tools==0.4.0` as of 2026-09-05) rather than to `layout/pdk.json`'s
committed `klt_version_pin` (a dev snapshot with no PyPI artifact of its own)
— see `layout/pdk.json`'s `ci_klt_install` comment for the full rationale,
including why the mid-session churn documented above in "Correcting the
curation note" does not apply to CI's one-shot, explicitly-versioned
install. Verified 2026-09-06: `klt 0.4.0` from PyPI reproduces all fourteen
currently-committed `layout/*/cell.json` cells' evidence exactly, not just
`layout/ro_buf/` — including `ro_ring5`'s `blocks[].cell` hierarchical
composition, the exact request shape `v0.2.0` lacks.

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
   The same 0.10 µm overlap technique also merges two *devices'* nwells
   directly with each other (`layout/ro_stage/`'s `Mph`/`Mp`), not just a
   device with a dedicated tap — one fewer tap island, provided the two
   devices' S/D ports at the merge boundary are placed at the **same `y`**
   (see `layout/ro_stage/README.md`'s floorplan section for why an
   unaligned jog through the overlap zone fails the edge-margin check, and
   why an *unmerged* pair of same-net wells fails `nwell.space.1` instead —
   there is no cheaper middle ground between merging and clearing the full
   isolation spacing).
2. **Mirror the PMOS row in `y`** (`blocks[].orientation: "mirror_y"`) so its
   gate faces the NMOS row's up-facing gate. Two same-facing gate ports make
   the router lift the connecting jog above both blocks, straight through the
   PMOS.
3. **Give a same-facing S/D pair an explicit `waypoints_um` lane** clear of
   both blocks' bboxes. The default one-stub-width jog runs back through the
   devices.
4. **A gate whose two nets would cross on one layer composes in two
   `gen-compose` passes, not one.** `layout/ro_stage/`'s starve devices'
   gates each tie to the *opposite* rail, a topology no single-layer
   placement makes planar. `compose-cell.py`'s `"stages"` cell.json field
   (see its own module docstring, and `layout/ro_stage/README.md`) composes
   the gate once on the base `"metal"` role leaving the two crossing nets
   unwired, then again — treating the first pass's own composed cell as one
   block — routing just those two nets on `"metal2"` with automatic
   via-drop. The two metal2 nets still have to avoid crossing *each other*
   (the same `waypoints_um`-into-separate-lanes technique as point 3 above,
   since both nets' sources happen to land at the same `x` before
   placement).
5. **A many-pin same-net bundle in a row of matched devices is a
   two-pass problem too, once more than one device shares a net.**
   `layout/ro_nand2/`'s parallel PMOS pair (both `Mpa`/`Mpb` have `D=y,
   S=py`) and series NMOS pair make `py`/`y` **three-pin** nets whose third
   pin re-crosses another device's own pad no matter which two pins wire
   first — the same class of problem as point 4, just from more than two
   devices sharing a net rather than one device's gate crossing a rail. The
   same fix generalizes: promote *every* pin of the affected net as a bare
   `pins[]` port in the base stage (wiring none of it there), then resolve
   all of it in a final stage against the whole first stage's own composed
   cell — see `layout/ro_nand2/README.md` for the six-same-block-self-net
   worked example (`py`/`y`'s bundle, plus `ro_stage`'s usual `vss`/`vddr`
   cross-coupled pair, all six resolved in one final `gen-compose` call, each
   given its own `waypoints_um` lane clear of the *other five* legs' known
   pad positions — chosen empirically against the real router, not derived
   closed-form, once the sub-block-level edge-margin restriction disappears
   along with the sub-blocks themselves).

Three more, discovered while composing `ro_ring5` from already-composed leaf
cells (`blocks[].cell`) rather than from fresh `klt gen` primitives:

6. **A composed leaf gate's signal pins are only reachable from met1
   upward.** Every gate this design builds puts its `a` input in the middle
   of its own device cluster, so an li1 route arriving from outside crosses
   that gate's own S/D pads on the way in — a *short*, not a spacing
   violation, and `gen-compose` does not catch it because the block is the
   route's own destination. Start inter-gate signal routing at `"metal2"`.
7. **A composed leaf gate's rails are already on met1 — declare the block
   port there.** `ro_stage`/`ro_nand2`'s own second stage draws `vddr` and
   `vss` on met1 internally. Declaring the `blocks[].cell.ports[]` entry for
   a rail on layer `68/20` (a point inside that internal route) rather than
   on li1 collapses `"metal3"`'s two-hop problem into a legal single hop,
   and no intermediate promotion stage is needed. met2 is completely empty
   in these leaf cells, so it is a free plane for rail busing.
8. **`gen-compose` draws a fixed-size via landing pad, not one sized by the
   declared port width.** A `0.17 µm`-wide port still gets a `0.42 µm` pad,
   so a port's position — not its width — is what decides whether its pad
   clears neighbouring metal. `ro_ring5`'s `ro` feedback needed the `g`-end
   port moved by `0.08 µm` for exactly this reason
   (`layout/ro_ring5/README.md` has the measured sweep). **The same pad
   also has to clear the port's own net**, once the port is hand-declared
   on a composed cell's *internal* route: `layout/xor2/`'s `inv_b` output
   port first landed `0.095 µm` above a perpendicular leg of `ro_buf`'s own
   `y` wire — one `li1.space.1` violation on the pad's own net, which the
   curated deck checks net-agnostically. Budget `0.21 µm + li1.space.1`
   from any perpendicular leg of the wire the port sits on, or overlap it
   outright. `gen-compose` does not warn about this — a `blocks[].cell`
   block is modelled by bbox + declared `ports[]` only, so the cell's own
   internal geometry never enters the clearance check that route-vs-route
   conflicts already get. Filed generically as
   [klayout-tools#1520](https://github.com/2AMLogic/klayout-tools/issues/1520).

Two more, discovered while composing `xor2` (see
[`layout/xor2/README.md`](xor2/README.md) for the worked example):

9. **A series transistor chain is one `mos_array` block, and its interior
   S/D segment is contactable.** `finger_topology: "series"` with
   `fingers: 2` draws two transistors sharing one diffusion strip and
   reports `U0_S0`/`U0_G0`/`U0_D0`/`U0_G1`/`U0_S1`. `ro_nand2` used this
   for its series NMOS pull-down pair and left `U0_D0` unconnected (its
   `nm` is internal by construction, which is the *cheap* case). `xor2`
   shows the other half: `U0_D0` is a real contacted pad, so two series
   chains can be wired to **share** their interior node — that is how
   `xor2`'s `mid` (`Mp1`/`Mp2` drains and `Mp3`/`Mp4` sources) becomes a
   single two-pin route rather than a four-pin bundle. Reading a
   parallel-then-parallel tree as chain-then-chain wherever the schematic
   allows it is worth doing *before* floor-planning: it halved `xor2`'s
   block count and removed four well taps with it.
10. **Split a gate's nets across layers before splitting them across
   lanes.** `compose-cell.py`'s `"stages"` shape has always been used to
   move *one crossing net* to a second metal (points 4 and 5 above). The
   more general use is to partition the whole net list: `xor2`'s stage
   `core` routes `vdd`/`mid`/`y`/`vss` on the base `"metal"` (li1) role and
   its final stage routes `a`/`an`/`b`/`bn` on `"metal2"`. The two groups
   cross each other freely and at no cost, leaving two much smaller
   single-layer problems — each of which turned out to be planar by
   construction, with no waypoint tuning beyond the lane choices. The
   corollary is a floorplan question worth asking early: *which* nets can
   be made to live entirely above and below the rows (supplies, and any
   output whose pads face outward), leaving the channel to the gate nets
   alone?

Two more, discovered while planning `ro_stage`:

- **A port may be named by `pins[]` *or* wired by `connectivity[]`, never
  both.** An internal net that is also a cell pin therefore takes its name
  from its `connectivity[]` entry — which works, and is how `ro_buf`'s `a`/`y`
  come out named.
- **`ro_stage`/`ro_nand2` are not single-layer planar — SOLVED, see
  `layout/ro_stage/README.md` (and `layout/ro_nand2/README.md` for the same
  fix extended to more than two same-block self-nets).** Their starve
  devices are cross-coupled to
  the *opposite* rail (`Mph.g = vss`, `Mnt.g = vddr`), so the two gate routes
  cross no matter where a single tap island per rail is placed — this is a
  real topological property of the two nets' spans, not a placement mistake
  a smarter floorplan can dodge. `klt gen-compose` performs no net-to-net
  short check *between separate calls*, but two nets crossing *within one
  call* on the same `routing.layer_role` is caught (`#1057`/`#1386`, "Known
  limitations" below) — so the naive one-pass floorplan correctly reports
  the crossing net as unroutable rather than silently shorting it (an
  earlier draft of this section suggested the opposite; that was wrong).
  The fix `layout/ro_stage/` uses: `layout/bin/compose-cell.py`'s new
  `"stages"` cell.json shape composes the gate in two `klt gen-compose`
  passes — the first leaves the two crossing gate nets deliberately
  unwired (promoted via `pins[]` as bare ports instead), the second takes
  that composed cell as a single further block and routes just those two
  nets on `"metal2"` (sky130 met1) with automatic via-drop, so they cannot
  short against anything on the base `"metal"` (li1) layer by construction.
  A per-net `routing.layer_role` override within one call still does not
  exist and was not needed once nesting was used instead — not filed as a
  tool gap.

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

## Starve-width variants: why a naive clone-and-reparametrize fails

`ro_stage`/`ro_nand2` each need four physical cells (one per ring, `wstv`
0.42/0.44/0.46/0.48 µm) — see "Floorplan decisions made so far" above. The
tempting shortcut is: copy the `wstv=0.42` `cell.json`, change `Mph`/`Mnt`'s
`params.w_um`, done. **That shortcut does not compose at all at the other
three widths** — `klt gen-compose` reports the affected nets unrouted, so
`compose-cell.py` aborts before DRC/LVS ever runs.

The reason: `Mph`/`Mp` (and `Mnt`/`Mn`) are connected by a *straight,
no-jog* route (`py`/`ny`) that only works because both devices' S/D pads
land at the exact same absolute `y` — `ro_stage/README.md`'s own floorplan
section calls this out as deliberate, not incidental (`Mph.D` and `Mp.S`
both at `y = 3.74`). `Mp`/`Mn`'s own geometry is fixed (`w_um` doesn't
depend on `wstv`), but `Mph`/`Mnt`'s local port position *does* move with
their own `w_um`: `klt gen mos_array`'s reported local `y_um` for a starve
device's S/D pads is exactly `w_um / 2` (verified empirically across all
four widths, both flavors — `0.42→0.21`, `0.44→0.22`, `0.46→0.23`,
`0.48→0.24`, i.e. linear, and identical between `pfet`/`nfet` despite their
different bbox heights from the nwell margin). Re-generating `Mph`/`Mnt` at
a new `w_um` with `Mph`/`Mnt`'s **existing, `wstv=0.42`-tuned**
`placement.origins_um` shifts that port by exactly the width delta (as
little as `0.01 µm`), which is enough to turn the straight `py`/`ny` route
into a route `klt gen-compose` reports **unrouted**.

This is a reproduced negative control, not an assumption. Taking
`layout/ro_stage/cell.json` verbatim, substituting only `Mph`/`Mnt`'s
`params.w_um` to `0.44` and leaving every `placement.origins_um` entry at
its `wstv=0.42` value, `compose-cell.py` aborts on the first stage with:

```
error: core: nets left unrouted by gen-compose: ['py', 'vddr']
```

The failure is loud, not silent — the router refuses rather than routing at
zero margin — so the practical hazard is a future increment concluding the
`wstv` variants are simply infeasible, not one shipping a bad cell.

**The fix** — re-derive, don't copy, `Mph`/`Mnt`'s own `placement.origins_um.y`
per width, from the same closed form every `ro_stage_wstv0p*`/
`ro_nand2_wstv0p*` cell.json's own `_comment` block documents:

```
mph.y(w) = 3.74 + w/2   # keeps Mph.D aligned with Mp.S's fixed y=3.74
mnt.y(w) = 0.21 - w/2   # keeps Mnt.D aligned with Mn.S's fixed y=0.21
```

(`3.74`/`0.21` are `Mp`/`Mn`'s own fixed S-port `y`, unaffected by `wstv`
since neither device's geometry depends on it.) Every other block, origin,
waypoint, and routing-layer choice in `ro_stage`/`ro_nand2`'s `cell.json` is
**unaffected by width** and stays byte-for-byte identical across all four
variants — confirmed by all four `wstv` values landing DRC-clean (0
violations) and LVS-matching for both cell types, with no other geometry
change (`layout/ro_stage_wstv0p44/README.md` et al. document the resulting
concrete origin values). This is the same "same-`y` alignment" discipline
`ro_stage/README.md`'s floorplan section already flags for the `wstv=0.42`
case — this section's contribution is confirming it generalizes to a closed
form across the whole `wstv` range, rather than needing to be independently
re-tuned per width by trial and error.

### The LVS match is width-sensitive (negative control)

Four cells that differ by `0.02 µm` on two devices, all reporting `klt lvs`
**match**, invite an obvious objection: is `klt lvs` comparing device widths
at all, or would any of these layouts match any of these references? It is
comparing them. Feeding `ro_stage_wstv0p48`'s extracted netlist against
`ro_stage`'s (`wstv=0.42`) reference netlist — the only change — flips the
verdict:

```
status: mismatch   mismatch_count: 12   error_count: 12
counts: nets 6/6 matched 2, devices 4/4 matched 2
  device.property  error  matched device parameter 'w_um' differs
                          NFET  layout 0.48  reference 0.42
  device.property  error  matched device parameter 'w_um' differs
                          PFET  layout 0.48  reference 0.42
```

So each variant's `match` verdict is evidence that *that* layout implements
*that* ring's `wstv`, not merely that some starved inverter was drawn. The
`Mph`/`Mnt` `w_um` value is decisive in the compare, and it is the one thing
that differs between the four references (`compose-cell.py`'s
`lvs.params.wstv` substitution — see each cell's own `*.ref.spice`, where
`XMph`/`XMnt` carry `W=0.42u`/`0.44u`/`0.46u`/`0.48u` respectively while
`XMp`/`XMn` stay fixed).

One caveat worth recording for whoever assembles the ring: in that
deliberately-mismatched run, the reference side's `as`/`ad`/`ps`/`pd` read
back as `0.0`, because `design/ro_array_core.spice` states them as
*expressions* in `wstv` (`ad='int((1 + 1)/2) * wstv / 1 * 0.29'`) and `klt
lvs`'s `subckt-call` converter does not evaluate them. Those four parameters
are therefore **not** effectively compared for the starve devices in any of
these runs (they do not appear as mismatches in the passing runs either).
`W`/`L`, device class, and connectivity are compared and are what these
verdicts rest on. Not filed upstream as a tool gap: the parameters that
decide this design's device identity are compared, and a converter declining
to evaluate arbitrary SPICE parameter expressions is a defensible boundary
rather than a defect — but a future increment that starts depending on
S/D-area matching should re-check this rather than assume coverage.

## Scouting `--parasitics`: what step 5 will and will not have to fight

Step 5 below (post-layout PVT re-verification) is not attempted here, and
**no `sim/` record is minted by this increment** — a PVT campaign is its own
deliverable with its own corner discipline, and a half-run one is worth less
than none. But three things about the extraction-to-ngspice handoff were
cheap to settle now and expensive to discover mid-campaign, so they are
settled and recorded here as layout/tool evidence rather than as a
simulation claim.

Probe used throughout: `ro_stage_wstv0p48`'s committed GDS, re-extracted with
`klt extract <gds> --deck sky130 --parasitics`, on `klt 0.4.0` / ngspice-47.
This produced no committed artifact — the probe is reproducible from the
committed GDS in one command, so there is nothing to keep in the tree.

1. **`--parasitics` works on these composed cells.** It is not blocked, not
   deck-limited, and not defeated by the two-pass `"stages"` composition.
   `ro_stage_wstv0p48` yields 16 series R, 6 net-to-substrate C, and 1
   net-to-net coupling C (`total_resistance_ohm` 1717.8,
   `total_capacitance_ff` 4.74, `total_coupling_capacitance_ff` 0.0036),
   with a per-net breakdown and a star of per-terminal leg resistances. So
   step 5's input exists today for every cell in this directory.

2. **The `|` in the extracted net names is harmless — a false alarm,
   pre-empted.** Cells built by the two-pass technique carry a pin label and
   a net label on the same physical net (`ro_stage`'s `mph_g` and `vss`), and
   the extractor joins those into one name, spelling it `mph_g|vss` in the
   `.SUBCKT` line and R/C cards but `mph_g\x7cvss__t0` in device cards. That
   looks exactly like a netlist that will silently split into two nodes —
   and ngspice does treat `a|b` and `a\x7cb` as distinct nodes, so the worry
   is well-founded in general. It does not happen here: the escaped spelling
   is only ever used on the `__tN` *leg* nets, which are distinct nodes by
   construction, and the hub node is spelled consistently. Verified by
   instantiating the extracted subcircuit in ngspice and running `.op` —
   pins bind correctly and the parasitic R star is live (the `y` net's two
   legs settle at slightly different voltages, as a star of real resistors
   should). A future increment does not need to re-litigate this.

3. **The substrate return node is a real trap, and is filed upstream.**
   Every net-to-substrate capacitor returns to a node named `vsubs` which is
   *neither* a `.SUBCKT` pin *nor* `.GLOBAL`-declared, tied to ground only
   via `Rvsubs_dctie vsubs 0 1e+12`. Simulated flat (extracted cell as the
   top cell) that is fine. **Instantiated** — which is how any PVT sweep or
   hierarchical assembly will use it — `vsubs` becomes a per-instance local
   node the testbench cannot reach: a top-level `Vs vsubs 0 0` does *not*
   tie it (ngspice lists `vsubs` and `x1.vsubs` as separate nodes), so the
   whole ground-capacitance model hangs off a node isolated from ground by
   1 TΩ. Nothing errors and the sim converges. Measured on this cell's own
   output net, as-extracted versus the same netlist with `.GLOBAL vsubs`
   prepended: ~1% impedance difference at 1 GHz, ~17% at 10 GHz — small
   enough to pass a spot check, large enough to corrupt a campaign.

   Filed generically per this repo's friction protocol as
   [klayout-tools#1503](https://github.com/2AMLogic/klayout-tools/issues/1503)
   (described as a parasitic-writer substrate-node scoping problem, with no
   reference to this design). **Until it is fixed, step 5's harness must
   either simulate the extracted cell flat, or prepend `.GLOBAL vsubs` to
   the extracted netlist** — and whichever it does must be recorded in the
   `sim/` record, because the two give measurably different answers.

   **Resolved as implemented**: step 5 took the `.GLOBAL vsubs` path
   (`layout/bin/pex-netlist.py` emits the declaration, every deck ties the
   node itself, and every record states which tie it used). Flattening was
   rejected — a ring is five instances by construction, and flattening would
   make the substrate node per-ring rather than shared, destroying the one
   coupling path step 6's re-evaluation depends on. The choice turned out to
   be worth 0.06-0.15% on the ring period between a hard tie and no tie,
   which is small but is measured rather than assumed; see
   `sim/post-layout-parasitic-impact/`.

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
   and `xor2`. **`ro_stage` and `ro_nand2` are both DONE, all four `wstv`
   values** (see `layout/ro_stage/README.md`, `layout/ro_nand2/README.md`,
   and the `_wstv0p44`/`_wstv0p46`/`_wstv0p48` sibling directories of each):
   `klt drc` clean (0 violations) for all eight cells; `klt lvs` **match**
   against `design/ro_array_core.spice`'s own `.subckt ro_stage` (4/4
   devices, 6/6 nets) and `.subckt ro_nand2` (6/6 devices, 8/8 nets)
   respectively at every width, both using the two-pass `"stages"`
   composition (point 4 in "Composing a gate" above) to route their
   cross-coupled starve-device gates without a short. `ro_nand2`
   additionally needed point 5's generalization (promote every pin of a
   many-device same-net bundle, resolve the whole bundle — six same-block
   self-nets in one final `gen-compose` call, not `ro_stage`'s two) to
   floor-plan its parallel PMOS pull-up pair and series NMOS pull-down pair,
   neither of which `ro_stage`'s single-switching-device shape has an
   analogue for. The three additional `wstv` widths per cell type
   (`0.44`/`0.46`/`0.48 µm`) needed one further finding beyond the
   `wstv=0.42` recipe — re-deriving `Mph`/`Mnt`'s own `y` origin per width
   rather than cloning the `0.42`-tuned one unchanged — see "Starve-width
   variants" above for the closed form and why the naive clone fails.
   `layout/bin/compose-cell.py`'s `lvs.params`/`lvs.drop_prefixes` fields
   (`params` substitutes `wstv`/`lstv` into the reference subckt's `L=lstv
   W=wstv` device cards; `drop_prefixes: ["Cld"]` drops the lumped load
   capacitor, a simulation load model with no physical counterpart) were
   already in place from `ro_stage`/`ro_nand2`'s own initial build and
   needed no changes for the variants.
   **`xor2` is now DONE too, closing this step in full** — see
   [`layout/xor2/README.md`](xor2/README.md): `klt drc` clean (0
   violations) and `klt lvs` **match** (12/12 devices, 10/10 nets, 0
   errors) against `design/ro_array_core.spice`'s own `.subckt xor2`, in
   two `gen-compose` stages. It did **not** need the channel router or the
   third routing plane this bullet previously predicted, and the reason is
   the reusable part: `xor2`'s twelve devices are eight tree devices that
   read as **four two-transistor series chains** (point 9 below) plus two
   inverters that *are* `ro_buf` (placed via `blocks[].cell`), so only nine
   blocks are placed at all; and its ten nets split cleanly across **two
   layers** (point 10 below) instead of competing for lanes on one. The
   placement-only PoC that predicted otherwise is superseded and now opens
   with that correction.
3. Hierarchical assembly: `ro_ring5` (5 gates + inter-gate routing),
   `ro_array_core` (4 non-identical rings + combining XOR tree),
   `sampler_dff`/`sampler_core` (no generator surveyed yet for a
   transmission-gate DFF — may need `klt draw` or a new `klt gen` generator;
   if the latter is a genuine gap, *that* is the point to file a
   `2AMLogic/klayout-tools` issue, described generically).
   **`ro_ring5` is DONE, all four `wstv` values** — see
   [`layout/ro_ring5/README.md`](ro_ring5/README.md) and its three `wstv`
   siblings: `klt drc` clean (0 violations) and `klt lvs` **match**
   (22/22 devices, 19/19 nets, 0 errors) against
   `design/ro_array_core.spice`'s own `.subckt ro_ring5` at each ring's own
   `wstv`, with the five leaf gates placed via `blocks[].cell`, `n1`-`n4`
   and the `ro` feedback routed on met1 and both rails bussed on met2.
   Four things that increment settled, each of which the first attempt
   (`ro_ring5-connectivity-poc`, now superseded) had wrong or open:
   - **The leaf gates' `a` ports are not reachable on li1 from outside.**
     Each sits inside its own device cluster, so any li1 approach crosses
     that gate's own S/D pads. Inter-gate signal routing starts at met1.
   - **The proposed three-stage li1→met1→met2 rail promotion is
     unnecessary.** Both rails are *already* drawn on met1 inside every leaf
     gate (by that gate's own two-pass `"stages"` composition), so declaring
     the block's rail port directly on layer `68/20` satisfies
     `"metal3"`'s single-hop via-drop rule with no promotion stage.
   - **The placement pitch is a closed form**, not a tuning exercise:
     `ro_nand2`'s nwell ends at local `x=5.57`, `ro_stage`'s starts at
     local `x=-2.19`, so `g`→`s1` needs `≥ 9.03 µm`; `9.30` is used.
   - **The five "unexplained device-internal `li1.space.1` violations" were
     the routes**, and the corrected placement with no routing at all is
     DRC-clean — there is no hierarchy-dependent DRC effect to work around.
   `layout/bin/compose-cell.py` gained `blocks[].cell` support and
   multi-subckt LVS references (`lvs.dependencies`) in the previous
   increment, and in this one: `blocks[].cell.gds_path` resolution relative
   to the cell.json (so `--check`'s temp-dir rebuild can find a sibling
   cell's committed stream at all), `lvs.reference_top` (a multi-subckt
   reference leaves `klt lvs` more than one candidate top circuit) and
   `lvs.drop_kwargs`. All three regression-tested against all nine
   previously-committed leaf cells, every one still `--check` clean.
4. Full-block `klt drc` + `klt lvs` (assembled netlist vs. `design/*.spice`)
   sign-off. **Reached for `ro_ring5` (all four rings), still open for
   `ro_array_core`/`sampler_core`.** Two further findings from the first
   multi-subckt LVS run, both now handled by `compose-cell.py`:
   a reference built from more than one `.subckt` leaves `klt lvs` with
   several candidate top circuits and it refuses to guess
   (`reference.top`, `lvs.reference_top` in cell.json), and comparing a
   *hierarchical* reference against `klt extract`'s *flat* layout netlist
   needs `options.flatten_reference` — which LVS reports back as a
   `topology.flattened` warning, so the resulting `match` verifies
   device/net correspondence but **not** that the layout's cell hierarchy
   mirrors the schematic's. The
   **reference-netlist request shape is settled** (it was
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
   convention. **DONE for the leaf-cell scope that exists** — see
   [`layout/pex/`](pex/README.md) for the generated library and
   `sim/post-layout-ro-ring5/` + `sim/post-layout-parasitic-impact/` for the
   twelve records and their reduction. Headline: intra-cell parasitics cost
   **1.378x - 1.479x in ring period** over the grid, raise ring-node swing
   1-4%, and lower per-ring supply current 2-6%; the `wstv` frequency ladder
   survives (post-layout span 1.1122x - 1.2096x). **Still open**: the same
   measurement over an *assembled* block, which needs steps 2 and 3 —
   `layout/` has no inter-cell interconnect to extract, so every number
   above is intra-cell parasitics with ideal wires between gates.
   `layout/pex/README.md` states that limitation in full, in both directions
   (the extractor's lumped-star resistance over-states the intra-cell
   penalty; the missing inter-cell wiring under-states the whole-block one).
   **DONE for the assembled-ring scope, this increment**: the four
   `ro_ring5` cells' own composed GDS (real inter-gate `n1`-`n4`/`ro` routing
   and `vddr`/`vss` rail busing included) is now extracted directly —
   [`layout/pex-ring/`](pex-ring/README.md) — and
   `sim/post-layout-ro-ring5-assembled/` runs the same period/swing/current
   measurement across the identical four-point PVT grid, twelve corner runs,
   as a new (not a superseding) sibling of `sim/post-layout-ro-ring5/` — see
   `sim/README.md`'s "Assembled-ring post-layout" section for the full
   reduction. Headline: real inter-gate wiring costs the ring **1.5045x -
   1.6546x** more slowdown *on top of* intra-cell parasitics alone (48
   paired PVT-grid points, mean 1.573x) — period vs. pre-layout control is
   **2.0819x - 2.3666x** overall, against the intra-cell-only figure's
   1.378x - 1.479x above — and the `wstv` ladder still survives (assembled
   post-layout span 1.0937x - 1.1822x, tighter than either the intra-cell-only
   or pre-layout figures). **Still open**: the *array*-level assembly
   (`ro_array_core`'s inter-ring wiring — buffer fan-in, the XOR combining
   tree, per-ring supply distribution — none of it drawn yet), which needs
   steps 2 and 3 above; every number in this bullet is still one ring's own
   real interconnect with ideal wires to its neighbours, not a whole-array
   measurement.
6. Re-evaluate DR-0003 §8's `wstv` inter-ring decorrelation gap using the
   extracted parasitics from step 5 — the measurement DR-0003 explicitly
   flagged as needing a real layout and unmeasurable at the netlist level.

   **Status after this increment: partially bounded, still open, and still
   not superseded.** A previous increment recorded this as "deliberately not
   re-evaluated" because the extraction had been run without
   `--parasitics` and only one leaf gate existed. Step 5 above changes that,
   and `spec/decision-records/DR-0005-*.md` is the re-evaluation:

   - **Measured.** Extracted parasitics give four independently-supplied
     rings exactly one node in common — the substrate return node every
     net-to-substrate capacitance lands on. Bracketing it between an ideal
     tie (`vsubs` to 0, zero coupling by construction) and no tie at all
     (the extractor's own 1 TOhm dc tie, infinite-impedance shared
     substrate), **the coupling-attributable period shift is at most 0.033%
     of the ring period** — and it is an upper bound rather than a resolved
     measurement, since only 1 of 12 grid points clears the transient
     solver's own 0.024% numerical period scatter and the shift's sign is
     not consistent across the grid. A third deck (rings 2/3/4 present but
     *stopped*) separates that from the floating node's own capacitive
     loading, which is a different mechanism and is what a two-deck
     comparison would have misattributed.
   - **Still open, and this is the part that matters.** §8's first-named
     mechanism is *shared supply impedance*, and there is still no
     supply-distribution layout — `vddr1`..`vddr4` remain four ideal
     isolated sources. The extractor also emits no substrate or tap
     resistance, so the bracket's interior is unmodelled
     ([klayout-tools#1503](https://github.com/2AMLogic/klayout-tools/issues/1503)),
     and nine leaf cells simulated as if infinitely separated say nothing
     about proximity. §8's own statement of the gap is therefore still
     accurate, so nothing supersedes it — per this repo's decision-record
     convention a correction supersedes rather than edits in place, and
     there is still no correction to make.
   - **What did get answered** is the ladder half: the `wstv` frequency
     ladder survives the parasitics (post-layout span 1.1122x - 1.2096x
     against 1.1225x - 1.2464x pre-layout, closest approach to a
     mutual-injection-lock rational 9.3% anywhere on the grid).
   - **This increment's assembled-ring extraction (step 5 above) does not
     change any of the above.** `sim/post-layout-ro-ring5-assembled/`
     extracts one ring's own GDS at a time, same as `layout/pex/` did —
     `vddr1`..`vddr4` are still four independent ideal sources across
     separate ngspice runs, never sharing a node the way the substrate-float
     decks' four *simultaneous* rings do. So it adds no new information
     about inter-ring coupling and neither confirms nor supersedes DR-0005;
     it re-confirms the ladder-survival half on a real-inter-gate-wiring
     model (assembled post-layout span 1.0937x - 1.1822x, if anything
     *tighter* than either the intra-cell-only or pre-layout figures above),
     which is consistent with, not a correction to, what DR-0005 already
     states.

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

## Reproducing `layout/ro_stage/`

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_stage/cell.json --check
```

Same `--check` contract as `ro_buf` above, extended (see `check_cell` in
`layout/bin/compose-cell.py`) to also diff every non-final stage's own
`<name>.compose.response.json` (here, `core.compose.response.json`) on the
same fields, since a two-stage cell's drift could otherwise hide in the
first pass without moving the final cell's own verdict.

## Reproducing `layout/ro_nand2/`

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_nand2/cell.json --check
```

Same two-stage `--check` contract as `ro_stage` above. `layout/ro_nand2/`'s
own final stage resolves six same-block self-nets (`py`'s two legs, `y`'s two
legs, plus `ro_stage`'s usual `vss`/`vddr` cross-coupled pair) in one
`gen-compose` call rather than `ro_stage`'s two — see
`layout/ro_nand2/README.md`'s own table for why each leg's `waypoints_um`
lane sits where it does, empirically derived against the real router's
route-vs-route collision check.

## Reproducing the `wstv` ring variants

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_stage_wstv0p44/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_stage_wstv0p46/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_stage_wstv0p48/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_nand2_wstv0p44/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_nand2_wstv0p46/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_nand2_wstv0p48/cell.json --check
```

Same `--check` contract as `ro_stage`/`ro_nand2` above (each of these six is
also a two-stage `"stages"` cell). See "Starve-width variants" above for the
one thing that differs per width (`Mph`/`Mnt`'s own `w_um` and re-derived
`placement.origins_um.y`), and each variant's own README for that cell's
concrete numbers.

## Reproducing `layout/ro_ring5/` and the four rings

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_ring5/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_ring5_wstv0p44/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_ring5_wstv0p46/cell.json --check
python3 layout/bin/compose-cell.py layout/ro_ring5_wstv0p48/cell.json --check
```

Same `--check` contract as the leaf cells, now over four stages rather than
two (`place`, `sig`, `fb`, final) — every non-final stage's own
`<name>.compose.response.json` is diffed as well as the final cell's.

Two per-stage checks worth running by hand when something moves, because
`compose-cell.py` only DRCs the *final* cell:

```bash
cd layout/ro_ring5
klt drc place.gds --deck sky130 --format json   # placement alone: clean, 0 violations
klt drc sig.gds   --deck sky130 --format json   # + n1-n4:         clean, 0 violations
klt drc fb.gds    --deck sky130 --format json   # + ro feedback:   clean, 0 violations
```

A violation that first appears at stage *n* was introduced by stage *n*.
This is the check that turned the previous attempt's "5 unexplained
device-internal violations" into "the routes did it".

## Reproducing `layout/xor2-placement-poc/` (superseded)

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
cd layout/xor2-placement-poc
klt gen-compose compose.request.json --format json
klt drc xor2core.gds --deck sky130 --format json
klt extract xor2core.gds --deck sky130 --format json
```

Not a `compose-cell.py` cell (no `cell.json`, no `--check`) — this was a
placement-only proof of concept, not a composed-and-verified gate; there is
no `connectivity[]`/`lvs.json` to check against. **The composed, DRC-clean,
LVS-clean `xor2` is `layout/xor2/`**, which shares none of this PoC's
coordinates and is built and checked the ordinary way (`python3
layout/bin/compose-cell.py layout/xor2/cell.json --check`). This PoC is
kept because its own README now records, with evidence, which of its
conclusions the composed cell contradicts — see its correction header.

## Reproducing `layout/pex/` (the post-layout netlist library)

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex/pex.json --check   # verify
python3 layout/test_pex_netlist.py                              # rewrite unit test (no PDK)
```

`--check` re-extracts all nine cells from their committed GDS into a
temporary directory and fails if the rebuilt library differs from the
committed one by a byte, or if any extraction report's verdict fields moved.
`layout/test_pex_netlist.py` is the other half of that guard: `--check`
proves the library matches what the script produces *today*, the unit test
proves the script's rewrite (net renames, unit-suffix stripping, device-card
swap) is correct — a wrong rewrite would simulate cleanly and report wrong
numbers. See [`layout/pex/README.md`](pex/README.md) for the parasitic
model's own contents and limits.
