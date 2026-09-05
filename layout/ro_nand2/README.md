# layout/ro_nand2

**The second cell whose starve devices' gates cross-couple to the *opposite*
rail, and the first with more than four devices** —
`design/ro_array_core.spice`'s `.subckt ro_nand2`, the enable-gated first
stage of each `ro_ring5` (the other four stages are plain `ro_stage`
inverters). Six devices, eight nets: `Mph`/`Mnt` are the same always-on
starve pair `ro_stage` has (`Mph.g = vss`, `Mnt.g = vddr`); `Mpa`/`Mpb` are a
**parallel** PMOS pull-up pair (`D=y`, `S=py` on both, gates `a`/`en`); `Mna`/
`Mnb` are a **series** NMOS pull-down pair (`y`-`Mna(a)`-`nm`-`Mnb(en)`-`ny`).
`layout/README.md`'s own note flagged this cell as reusing `ro_stage`'s
two-pass `"stages"` technique directly for the cross-coupled starve gates —
true, but two *new* floorplan problems (the parallel pull-up pair and the
series pull-down pair) needed their own solutions first, described below.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
python3 layout/bin/compose-cell.py layout/ro_nand2/cell.json            # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_nand2/cell.json --check    # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `core`, base metal/li1) | 5/5 nets routed, 6 endpoints promoted as bare pins | `core.compose.response.json` |
| `klt gen-compose` (final stage, metal2 + via-drop, 6 same-block self-nets) | 6/6 nets routed | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 6 devices (3 nfet, 3 pfet), 8 nets | `extract.json`, `ro_nand2.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt ro_nand2` (`wstv=0.42`, `lstv=2` — matching `xg` at `xr1`) | **match** — 6/6 devices, 8/8 nets, 0 mismatches | `lvs.json`, `ro_nand2.ref.spice` |

The extracted netlist (`layout/ro_nand2/ro_nand2.spice`) confirms the exact
topology of the reference `.subckt ro_nand2` by `klt lvs`'s own
graph-isomorphism match, not by name — several nets carry a `|`-joined label
because more than one drawn li1 port lands on the same physical node (e.g.
`mnab_y|mpa_y|mpb_y|y` is the `y` output, reached from three different
promoted pads; `mpa_py|mpb_py|mph_py|py` is `py` reached from three more).
Device `$1`/`$4` are `Mnt`/`Mph` (the starve pair, unchanged from `ro_stage`);
`$2`/`$3` are `Mnb`/`Mna` (the extractor's own anonymous net `\$3` is the
internal `nm` node, formed automatically by the `finger_topology: "series"`
generator call's own shared diffusion — see below); `$5`/`$6` are `Mpb`/`Mpa`
(S/D swapped relative to the reference cards, immaterial to a
graph-isomorphism match on a symmetric device).

## Two new floorplan problems, on top of `ro_stage`'s cross-coupled starve gates

### 1. The series NMOS pair (`Mna`/`Mnb`) is one `mos_array` call, not two

`XMna y a nm ...` / `XMnb nm en ny ...` chain source-to-drain through the
internal node `nm`, with no other net touching it. Rather than drawing two
separate `mos_array` blocks and *routing* `nm` between them (extra metal, and
an extra pad to place), this cell draws **one** `mos_array` call with
`fingers: 2, finger_topology: "series"` (`docs/cli/gen.md`'s family-1
section): the generator folds two fingers into one strip of diffusion with a
gate stripe between each pair of segments, reporting `U0_S0`/`U0_D0`/`U0_S1`
(the `fingers + 1` S/D segments, west to east) and `U0_G0`/`U0_G1` (one gate
per finger) — `U0_D0` is the *shared, internal* middle segment, already one
physical node with no separate contact needed on either side. Mapping:
`U0_S0 = ny` (west end, faces the starve device), `U0_G0 = en` (finger 0 =
`Mnb`), `U0_D0` = `nm` (internal, **left out of every `connectivity`/`pins`
entry entirely** — `klt extract` recovers it as its own anonymous net purely
from the drawn geometry, with nothing external routed to it, matching the
reference netlist's own `nm` having no other connection), `U0_G1 = a` (finger
1 = `Mna`), `U0_S1 = y` (east end). `device_count` for this one block is `2`
(`fingers`), matching `klt extract`'s own `nfet: 3` (this block's 2 plus
`Mnt`'s 1) with no separate accounting needed anywhere in `cell.json`.

### 2. The parallel PMOS pair (`Mpa`/`Mpb`) needs `rotate_180`, not `mirror_y`

`XMpa`/`XMpb` are **not** chained — both have `D=y, S=py`, driven by
different gates (`a`/`en`). Physically abutting two more `pfet_w0p84_l0p15`
blocks onto `Mph`'s own row (same technique `ro_stage` used for its single
`Mp`) puts three matched-width blocks in a row, each block's own `S`/`D`
alternating west-to-east (`S`-`D` | `S`-`D` | `S`-`D`) — so a straight wire
tying the two `S`-side pins together (`py`) or the two `D`-side pins together
(`y`) necessarily runs directly over the *other* pin's own pad in between
(`Mpa`'s own `D` pad sits squarely between `Mpa.S` and `Mpb.S`). `klt
gen-compose` correctly rejects this (`"crosses ... through its own pin's
block"`) rather than silently drawing a short.

The fix: give `Mpb` `orientation: "rotate_180"` (both axes mirrored) instead
of `mirror_y`. Mirroring `mirror_y` alone (as `ro_stage`'s single `Mp` uses)
only flips *which side the gate faces* (needed so both switching devices'
gates point into the row's middle, toward the NMOS row below) — it leaves
`S`/`D`'s *east-west* order unchanged, so it does not fix the alternating-pad
problem. `rotate_180` additionally flips `Mpb`'s east-west order, moving its
`D` from the block's east edge to its west edge — so `Mpb.D` now faces
`Mpa.D` directly across a small gap (`direction_deg` reported as `180` for
both, confirmed by `klt gen`'s own orientation table:
`mirror_y` maps `0/180` unchanged, `rotate_180` swaps them). Overlapping
`Mpb`'s bbox against `Mpa`'s by the usual `0.10 um` (merging the whole
`Mph`-`Mpa`-`Mpb` row into one physical nwell, needing only `Mph`'s own tap)
lands `Mpa.D` and `Mpb.D` at the identical `y` with a `0.62 um` direct gap —
routed on the base `"metal"` role with no waypoints, exactly like `Mph.D`-
`Mpa.S`'s own `py` short in `ro_stage`. `Mpb.S` ends up on the row's far east
edge, facing away (`direction_deg: 0`) — its own connection to `py` is the
harder half of the problem below.

## Why every `py`/`y` endpoint is promoted, and nothing is wired inside `core`

`py` (`Mph.D` + `Mpa.S` + `Mpb.S`) and `y` (`Mpa.D` + `Mpb.D` + `Mna.D`) are
each **three-pin** nets once the series/parallel floorplan above is in place.
`Mph.D`-`Mpa.S` and `Mpa.D`-`Mpb.D` are both simple, close, opposite-facing
pairs that route fine inside stage `core` on the base metal role (exactly the
`ro_stage`-style short) — but the *third* pin of each net (`Mpb.S` for `py`,
`Mna`'s `y`-side end for `y`) sits on the far side of the row, and any
straight or single-jog path to it re-crosses one of the row's own other pads
(the same problem, one level up, that the `rotate_180` fix solved for `Mpb.D`
alone). Splitting `py`/`y` into two `connectivity[]` entries under the same
net name each — one direct, one needing an outside path — does not help
*inside* stage `core`, because `klt gen-compose`'s per-pin "own block" edge
margin check still measures against each pin's own **sub-block**'s bbox
(`Mpa`'s reported footprint is only `1.39 um` wide, and the pad sits well
inside it), and no waypoint threads between `Mph`/`Mpa`/`Mpb`'s three
overlapping, well-merged bboxes without re-entering at least one of them.

The fix (this cell's actual reuse of `ro_stage`'s two-pass technique, extended
from 2 same-block self-nets to 6): **promote every `py`/`y` endpoint as a bare
stage-`core` pin, and wire neither net inside `core` at all** —
`mph_py`/`mpa_py`/`mpb_py` and `mpa_y`/`mpb_y`/`mnab_y`, alongside `ro_stage`'s
usual `mph_g`/`mnt_g`. Once stage `core`'s own `gen-compose` response becomes
a single opaque block for the final stage (`{"from_stage": "core"}`), the
final stage's router only knows `core`'s **one** overall bbox plus its ten
promoted ports' positions — the per-sub-block edge-margin restriction is gone
entirely, because there are no more sub-blocks to measure against. What
remains is the same-block **pad-crossing** check (avoid another of `core`'s
*known* ports along the way), which is a much easier constraint to route
around with an explicit `waypoints_um` lane per leg:

| Net | Leg | `waypoints_um` | Why |
|---|---|---|---|
| `py` | `mph_py`\<->`mpa_py` | none (direct) | close, opposite-facing, same `y` |
| `py` | `mpa_py`\<->`mpb_py` | `[[3.25, 4.5], [5.21, 4.5]]` | up and over the whole PMOS row's own `y`-net pads, well above `core`'s bbox top (`4.31`) |
| `y` | `mpa_y`\<->`mpb_y` | none (direct) | close, opposite-facing, same `y` (the `rotate_180` short) |
| `y` | `mpb_y`\<->`mnab_y` | `[[4.54, 1.0], [4.79, 1.0]]` | straight down first (avoiding `mpb_y`'s own `x=5.21` neighbour `mpb_py`, which the `py` loop above already occupies at that `y`), then a short jog into `mnab_y` |
| `vss` | `mph_g`\<->`vss` | `[[0.5, 2.92], [0.5, 0.92]]` | unchanged from `ro_stage` (identical `mph`/tap placement) |
| `vddr` | `mnt_g`\<->`vddr` | `[[2.0, 1.03], [2.0, 4.4], [-1.83, 4.4]]` | `x` moved from `ro_stage`'s `2.4` to `2.0` — `2.4` sat only `0.23 um` from `py`'s own direct `mph_py`-`mpa_py` leg (`x` up to `2.63`), inside the router's route-vs-route safety margin, and was rejected as `"crosses already-routed net 'py'"` until widened |

All six legs were arrived at **empirically** against the real `klt
gen-compose` router, not derived closed-form: every lane above is the first
one tried that did not collide with one of the *other five* legs' own drawn
paths (`nets[].legs[].reason` names exactly which already-routed net a
rejected attempt crossed, e.g. `vddr`'s original `x=2.4` lane against `py`).
This is the same **`layout/README.md`-documented limitation** `ro_stage`
already flagged (`klt gen-compose` performs no net-to-net short check
*between separate calls*, only within one) — six same-block self-nets and
their five o(n²) interactions in a single `gen-compose` call, unlike
`ro_stage`'s two, made trial and error the practical path rather than closed-
form geometry, and it is recorded above precisely so a future increment does
not have to re-derive it.

## Floorplan

```
   [nwell_tap]==[Mph(0.42/2,mirror_y)]==[Mpa(0.84/0.15,mirror_y)]==[Mpb(0.84/0.15,rotate_180)]
        vddr        py(D) vss(G) vddr(S)     py(S) en(G) y(D)          y(D) a(G) py(S)
                                       ^0.10um merge          ^0.10um merge
   [psub_tap]==[Mnt(0.42/2,none)]  ...  [Mnab: Mnb(0.84/0.15) + Mna(0.84/0.15), series, one mos_array call]
        vss        vss(S) vddr(G) ny(D)      ny(S0) en(G0) [nm, internal] a(G1) y(S1)
```

- **`Mph`-`Mpa`-`Mpa`-`Mpb` merge into one continuous nwell**, each pair
  overlapping the next's bbox by `0.10 um` (the same abutment technique every
  prior cell uses), so only `Mph`'s own tap is needed for the whole row's
  `vddr` strap.
- **`mnt`-`mnab` keep `ro_stage`'s `0.40 um` clearance gap** (no merge —
  `nfet` draws no well at all, so there is nothing to merge or clear a
  spacing floor against; the gap is purely for the `ny` net's own routing
  channel). `mnab`'s origin `y` (`-0.21`, not `0`) is chosen so its `U0_S0`
  pad lands at the *same* `y` as `mnt`'s own `D` pad (`0.21`) despite the two
  blocks having different device widths (`w=0.42` vs `w=0.84`, hence
  different pad-center heights) — a direct, jog-free `ny` short, the same
  same-`y`-alignment discipline `ro_stage`'s README documents for `Mph.D`/
  `Mp.S`.
- **`a`/`en` are assigned to minimize each gate net's vertical run**: `Mpa`
  (the row's *middle* PMOS device, `x`-center closest to `mnab`'s *west*
  gate) carries `en`, matching `mnab`'s `U0_G0` (also the west/`Mnb` gate);
  `Mpb` (the row's *east* PMOS device) carries `a`, matching `mnab`'s `U0_G1`
  (the east/`Mna` gate). This is a free labelling choice — `Mpa`/`Mpb` are
  electrically interchangeable parallel devices, so which physical instance
  the schematic would call "`Mpa`" vs "`Mpb`" is immaterial to the `klt lvs`
  graph-isomorphism match — chosen purely to keep both gate nets short.

## What this does NOT establish

- **The DRC verdict is against `klt`'s curated sky130 deck, not sky130
  sign-off** — same caveat as every prior cell's own README. `drc.json`'s
  `coverage.deck_scope` is identical to `ro_stage`'s (`li`/`m1`/`m2`/`nwell`/
  `poly`/vias, plus `capm`/`cap2m`/`m3`-`m5` present in the deck but not
  exercised by this geometry); implant layers (`nsdm`/`psdm`) are still not
  drawn by any generator in use.
- **Built at one `wstv` value only (`0.42 µm`, matching `xr1`)** — same open
  item `ro_stage` already carries. The other three rings' starve-device
  variants (`0.44`/`0.46`/`0.48 µm`) are unstarted.
- **No parasitics, no post-layout simulation.** `klt extract` was run without
  `--parasitics`; nothing under `sim/` has been re-run against this cell, and
  DR-0003 §8's `wstv` inter-ring decorrelation gap remains unevaluated for the
  same reason `ro_stage/README.md` gives — the condition is "extracted
  parasitics of the *assembled array*", not of one leaf cell.
- **Two gates done, not a ring or an array.** `xor2`, `ro_ring5`,
  `ro_array_core`, `sampler_dff`, `sampler_core` remain unbuilt — tracked in
  issue #27.
- **The LVS reference is a unit-normalised, parameter-substituted copy** —
  same convention as `ro_buf`/`ro_stage`'s (`compose-cell.py`'s docstring),
  with `wstv=0.42`/`lstv=2` substituted for the schematic's own symbolic
  starve-device sizing and the `Cld` lumped load capacitor dropped (a
  simulation load model, not a device the layout omits).
