# layout/ro_stage

**The first composed cell whose starve devices' gates cross-couple to the
*opposite* rail** — `design/ro_array_core.spice`'s `.subckt ro_stage`, the
starved CMOS inverter each `ro_ring5` instantiates four times as its
per-stage delay cell. Four devices, six nets: `Mph`/`Mnt` are the always-on
starve pair (`Mph.g = vss`, `Mnt.g = vddr` — each gate tied to the rail its
own *source* is not on), `Mp`/`Mn` are the switching pair (`g = a`, the
stage's real input). `layout/ro_buf/` proved the composition methodology on
a plain inverter; this cell is issue #27 step 2's "start here" gate — the
next hardest thing after `ro_buf`, and the first to need more than one
`klt gen-compose` pass.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
python3 layout/bin/compose-cell.py layout/ro_stage/cell.json            # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_stage/cell.json --check    # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `core`, base metal/li1) | 6/6 nets routed | `core.compose.response.json` |
| `klt gen-compose` (final stage, metal2 + via-drop) | 2/2 nets routed | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 4 devices, 6 nets | `extract.json`, `ro_stage.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt ro_stage` (`wstv=0.42`, `lstv=2` — matching `xr1`) | **match** — 4/4 devices, 6/6 nets, 0 mismatches | `lvs.json`, `ro_stage.ref.spice` |

The extracted netlist, in full (`mnt_g|vddr` and `mph_g|vss` are one
electrical node each — see "Two-pass composition" below for why the
extractor reports the joint label):

```
.SUBCKT ro_stage a mnt_g|vddr mph_g|vss ny py y
M$1 ny mnt_g|vddr mph_g|vss mph_g|vss nfet L=2U W=0.42U AS=0.1764P AD=0.1764P PS=1.68U PD=1.68U
M$2 y a ny mph_g|vss nfet L=0.15U W=0.42U AS=0.1974P AD=0.1974P PS=1.78U PD=1.78U
M$3 py mph_g|vss mnt_g|vddr mnt_g|vddr pfet L=2U W=0.42U AS=0.1764P AD=0.1764P PS=1.68U PD=1.68U
M$4 y a py mnt_g|vddr pfet L=0.15U W=0.84U AS=0.3948P AD=0.3948P PS=2.62U PD=2.62U
.ENDS ro_stage
```

`$1` is `Mnt` (D=`ny`, G=`vddr`, S=`vss`, B=`vss`), `$2` is `Mn` (D=`y`,
G=`a`, S=`ny`, B=`vss`), `$3` is `Mph` (D=`py`, G=`vss`, S=`vddr`,
B=`vddr`), `$4` is `Mp` (D=`y`, G=`a`, S=`py`, B=`vddr`) — the exact
topology of `design/ro_array_core.spice`'s `.subckt ro_stage`, confirmed by
`klt lvs`'s own graph-isomorphism match rather than by name (the layout
side's pin count is 6 against the reference's 4, since `mnt_g|vddr` and
`mph_g|vss` each carry two li1 labels merged onto one physical node — `klt
lvs` matches nets by connectivity, not by name, so this does not affect the
verdict).

## Why this gate needed a second `klt gen-compose` pass

`Mph.g = vss` and `Mnt.g = vddr` are each tied to the rail the *other*
starve device sits on, not their own — the always-on bias that keeps both
starve transistors permanently in a weak-conduction state regardless of the
stage's input. Physically that means: the PMOS row's own gate net needs to
reach all the way down to the NMOS row's rail, and the NMOS row's own gate
net needs to reach all the way up to the PMOS row's rail. Both of these
runs cross the *other* rail's own local wiring on the way — there is no
placement that makes them planar on one routing layer, because the two
nets' source-to-destination spans overlap almost completely in both `x`
and `y` (`layout/README.md`'s "Composing a gate" section flagged this as
the concrete blocker items 2/3 of issue #27's decomposition would have to
solve).

The fix is `compose-cell.py`'s new `"stages"` cell.json shape (see its own
module docstring): stage `core` composes the four devices plus their two
tap islands on the base `"metal"` role (li1) exactly like `ro_buf`, but
deliberately leaves `Mph.g` and `Mnt.g` **unconnected** — promoted via
`pins[]` as bare, unwired ports (`mph_g`, `mnt_g`) rather than wired to
anything. A second stage then takes `core`'s own composed output as a
*single* block (`"from_stage": "core"`) and routes exactly those two
crossing nets on `"metal2"` (sky130 met1) with `klt gen-compose`'s
automatic via-drop back down to each pin's own li1 pad. Because the two
nets are now on a different physical layer than every other wire in the
cell, they cannot short against them by construction — the composed GDS
carries three conductor levels (li1 for six of the eight net-legs, met1
plus mcon vias for the two that cross, and the ring/well layers underneath
both), and `klt drc`'s `met1.space.1`/`met1.width.1` rules (present in
`drc.json`'s own `deck_scope`) verify the met1 pair against each other and
themselves, same as any other layer.

**The two metal2 nets still had to be routed clear of each other.** Moving
both crossing nets to the same second layer does not automatically avoid a
new short *between them* — `klt gen-compose`'s route-vs-route spacing check
(the one `layout/README.md` cites as `#1057`/`#1386`) fires exactly the
same way on metal2 as on the base metal. The two nets' natural direct paths
initially failed this way (`vddr`'s path came within 0.14 µm of the
already-routed `vss` path, closer than `met1.space.1` allows), because both
nets' sources sit at the *same* `x` coordinate (`Mph`'s and `Mnt`'s gates
are both drawn at `x = 1.42` in the unplaced generator frame, before either
device is translated) — the fix is `waypoints_um` on each 2-pin net,
choosing clearly separated parallel lanes (`vss`'s vertical run at
`x = 0.5`, `vddr`'s at `x = 2.4`) rather than letting both default to the
same corridor.

## Floorplan

Two device rows, same overall shape as `ro_buf`'s but with the PMOS row's
own two devices **directly nwell-merged with each other** rather than each
carrying its own separate tap:

```
   [nwell_tap]==[ Mph (pfet starve 0.42/2, mirror_y) ]==[ Mp (pfet 0.84/0.15, mirror_y) ]
        vddr          py(D)  vss(G)  vddr(S)                py(S)  a(G)  y(D)
                                                     ^ 0.10 um nwell overlap, S/D y-ALIGNED (no jog)
   [psub_tap]==[ Mnt (nfet starve 0.42/2)           ]  ...  [ Mn (nfet 0.42/0.15)          ]
        vss           vss(S)  vddr(G)  ny(D)                 ny(S)  a(G)  y(D)
```

- **`Mph`/`Mp` merge nwells directly** (0.10 µm bbox overlap, the same
  abutment technique `ro_buf` established for a device-to-tap merge, here
  used device-to-device instead), so only `Mph` needs its own tap —
  `Mp`'s bulk resolves to the same merged, `vddr`-strapped nwell island
  with no separate tap or long-haul wire. `Mnt`/`Mn`'s shared p-substrate
  needs no merge at all (`layout/README.md`'s well-strap section: NMOS
  bulk is sky130's one global `vsubs` net, so a single `psub_tap` anywhere
  in the cell straps both devices — `Mn` carries no dedicated tap).
- **`Mph.D` (`py`) and `Mp.S` (`py`) are placed at the *same* `y`
  (`3.74`)**, deliberately — not an accident of the two devices' own
  geometry (they differ in height when mirrored). A first attempt left a
  0.21 µm `y` mismatch between them, and every routing of the resulting
  jog failed `klt gen-compose`'s edge-margin check: because `Mph`'s and
  `Mp`'s bboxes are *already* overlapped by design (the well merge above),
  there is no `x` position between the two ports that lies outside *both*
  blocks, so any vertical jog in that corridor is charged against one
  block's own edge-margin budget in addition to its natural horizontal
  exit — and the sum exceeds the allowed margin. Re-deriving `Mp`'s own `y`
  origin (`4.16`, not `ro_buf`'s `3.95`) so `Mp.S` lands exactly on `Mph.D`'s
  `y` turns `py` into a single straight horizontal wire with no jog at all,
  which sidesteps the budget question entirely.
- **`nwell.space.1` is a real constraint on *unmerged* wells, not just a
  merge nicety.** An earlier iteration of this floorplan gave `Mp` its own
  *separate* tap (`nwell_tap_mp`, abutting `Mp` on a different side so as
  not to block `py`'s routing) instead of merging directly with `Mph`. That
  version routed and extracted cleanly but failed `klt drc` with two
  `nwell.space.1` violations: `Mph`'s and `Mp`'s (and separately `Mp`'s and
  `nwell_tap_mp`'s) wells sat only ~0.25-0.4 µm apart — well inside sky130's
  isolation-spacing floor for two *electrically-connected-elsewhere-but-
  geometrically-distinct* well polygons, which the deck does not treat as
  exempt just because a wire ties them to the same net elsewhere. Two nwell
  regions must either merge (touch/overlap, distance 0) or clear the full
  isolation spacing — there is no cheaper middle ground. The direct-merge
  floorplan above avoids the question by never having two distinct `vddr`
  well polygons at all.

## What this does NOT establish

- **The DRC verdict is against `klt`'s curated sky130 deck, not sky130
  sign-off** — same caveat as `layout/ro_buf/`'s own README. This cell adds
  met1/met2/via1 coverage to what was exercised (`drc.json`'s own
  `deck_scope` includes `m1`/`via` now, beyond `ro_buf`'s li1-only set),
  but implant layers (`nsdm`/`psdm`) are still not drawn by any generator
  in use.
- **This cell is `xr1`'s instance only (`wstv = 0.42 µm`).** The other three
  rings' starve-device variants are now built too — see
  `layout/ro_stage_wstv0p44/`, `layout/ro_stage_wstv0p46/`,
  `layout/ro_stage_wstv0p48/`, and `layout/README.md`'s "Starve-width
  variants" section for the placement-origin re-derivation each one needed.
- **No parasitics, no post-layout simulation.** `klt extract` was run
  without `--parasitics`; nothing under `sim/` has been re-run against this
  cell, and DR-0003 §8's `wstv` inter-ring decorrelation gap is **not**
  re-evaluated by this increment — its own text already states the
  condition is "extracted parasitics of the assembled array", which a
  single leaf cell's plain extraction does not supply. See
  `layout/README.md`'s own "What's deferred" section, unchanged by this PR.
- **One gate, not a ring or an array.** `ro_nand2`, `xor2`, `ro_ring5`,
  `ro_array_core`, `sampler_dff`, `sampler_core` remain unbuilt — tracked in
  issue #27.
- **The LVS reference is a unit-normalised, parameter-substituted copy** —
  same convention as `ro_buf`'s (`compose-cell.py`'s docstring), with
  `wstv=0.42`/`lstv=2` substituted for the schematic's own symbolic
  starve-device sizing and the `Cld` lumped load capacitor dropped (a
  simulation load model, not a device the layout omits).
