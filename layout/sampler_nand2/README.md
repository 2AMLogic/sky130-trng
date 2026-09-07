# layout/sampler_nand2

**The second and last missing leaf shape `sampler_dff` needs — a plain
2-input NAND2, `structurally ro_nand2 minus its two always-on starve
devices`.** `design/sampler_core.spice`'s `sampler_dff` subckt draws this
exact four-device shape twice (`NANDM`: `XMimpa`/`XMimpb`/`XMimna`/`XMimnb`,
gating `m`/`rst_n` into `mb`; `NANDS2`: the same shape gating `q`/`rst_n`
into `qb`) — a parallel PMOS pull-up pair (`Mpa`/`Mpb`, sources tied
**directly** to `vdd`, no starve device in between) and a series NMOS
pull-down pair (`Mna`/`Mnb`, far end tied **directly** to `vss`). This closes
issue #27 step 1's remaining leaf-primitive gap: with this cell and
`layout/sampler_tg/` (the transmission gate) and `layout/ro_buf/` (the plain
inverter, reusable as-is per `layout/xor2/`'s own `blocks[].cell`
precedent), all three of `sampler_dff`'s 22 devices reduce to already-composed
leaf shapes. Assembling the whole 22-device `sampler_dff` cell from them
remains open — see "What this does NOT establish" below.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
python3 layout/bin/compose-cell.py layout/sampler_nand2/cell.json           # rebuild in place
python3 layout/bin/compose-cell.py layout/sampler_nand2/cell.json --check   # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` (stage `core`, base metal/li1) | 3/3 nets routed (`en`, `a`, `vss`), 6 endpoints promoted as bare pins | `core.compose.response.json` |
| `klt gen-compose` (final stage, metal2 + via-drop, two 3-way same-block self-nets) | 4/4 legs routed (`vdd` x2, `y` x2) | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 4 devices (2 nfet, 2 pfet), 6 nets | `extract.json`, `sampler_nand2.spice` |
| `klt lvs` vs. hand-authored `sampler_nand2.source.spice`'s `.subckt sampler_nand2` | **match** — 4/4 devices, 6/6 nets, 0 mismatches | `lvs.json`, `sampler_nand2.ref.spice` |

The extracted netlist confirms the topology by `klt lvs`'s own
graph-isomorphism match, not by name: `y`'s own promoted-pad label carries
all three of its routed legs (`mnab_y|mpa_y|mpb_y|y`), and `vdd`'s carries all
three of its own (`mpa_py|mpb_py|nwell_vdd|vdd`) — the same joined-label
pattern `ro_nand2`'s own `py`/`y` nets show, for the identical reason (more
than one drawn li1/metal2 port lands on the same physical node).

## Why this composes in fewer steps than `ro_nand2`, but needs the same technique

`ro_nand2`'s own README documents why its `py`/`y` nets (each a three-pin net
once the parallel-PMOS/series-NMOS floorplan is in place) cannot be wired
inside a single `gen-compose` call: the *third* pin of each net sits on the
far side of the row, and any straight or single-jog path to it re-crosses
one of the row's own other pads. This cell has no starve devices, so it does
not need `ro_nand2`'s own `mph_g`/`mnt_g` cross-coupled-gate promotion pair
— but it still has the **same** two three-pin nets:

- **`vdd`** = `nwell_tap.TAP_E` + `Mpa.S` + `Mpb.S` (the direct-supply
  analogue of `ro_nand2`'s `vddr`-tap-connection plus `py` combined into one
  net, since there is no starve device's own drain sitting between the tap
  and the pull-up pair here).
- **`y`** = `Mpa.D` + `Mpb.D` + `Mnab.S1` — identical in shape to `ro_nand2`'s
  own `y` net, since the parallel-PMOS/series-NMOS floorplan is unchanged.

Both are resolved with `ro_nand2`'s own fix: promote every endpoint as a bare
stage-`core` pin (`nwell_vdd`, `mpa_py`, `mpb_py`, `mpa_y`, `mpb_y`,
`mnab_y`), wire neither net inside `core` at all, and resolve both three-pin
nets on `"metal2"` in the final stage, once `core`'s own sub-block edge-margin
restriction is gone and only the same-block pad-crossing check remains.

`vss` (`Mnab.U0_S0` <-> `psub_tap.TAP_E`) is the one net this cell wires
**directly inside `core`**, unpromoted — it is only a two-pin net (no starve
device's own drain in between to make it three-way), the same reason
`ro_nand2`'s own `ny` net (`Mnt.D`<->`Mnab.S0`) routed directly in its base
stage.

## Floorplan: `mpa`/`mpb`/`mnab` keep `ro_nand2`'s own coordinates unchanged

`mpa` (`{"x": 3.04, "y": 4.16}`), `mpb` (`{"x": 5.42, "y": 4.16}`) and `mnab`
(`{"x": 3.24, "y": -0.21}`) are placed at the **identical** `origins_um`
`ro_nand2/cell.json` uses for its own same-shaped, same-sized blocks (both
cells' `Mpa`/`Mpb` are `pfet_w0p84_l0p15`; both cells' series NMOS pair is the
identical `mos_array` call, `w_um=0.84, fingers=2, finger_topology="series"`)
— so `ro_nand2`'s own already-proven `core.compose.response.json` port
coordinates and the final stage's `y`-net `waypoints_um`
(`[[4.54, 1.0], [4.79, 1.0]]`) carry over completely unchanged, and were
reused verbatim rather than re-derived.

What differs is `nwell_tap`/`psub_tap`: `ro_nand2` abuts them against `Mph`/
`Mnt` (the starve pair); this cell has no starve pair, so they abut `Mpa`/
`Mnab` directly instead. Both were placed by transforming `klt gen`'s own
reported **local** bbox/port coordinates (queried standalone, offset
`(0, 0)`, for `guard_ring(add_well=true/false)` and the same
`pfet_w0p84_l0p15`/series-`mos_array` calls above) through each block's own
orientation:

- **`none`**: `(x, y) -> (offset.x + x, offset.y + y)`, direction unchanged.
- **`mirror_y`** (`mpa`): `(x, y) -> (offset.x + x, offset.y - y)`; a
  direction of `90`/`270` flips, `0`/`180` unchanged.
- **`rotate_180`** (`mpb`): `(x, y) -> (offset.x - x, offset.y - y)`;
  direction `+= 180 mod 360`.

Both transforms were verified against `ro_nand2`'s own committed
`core.compose.response.json` port coordinates before being trusted for this
cell's new placements (every `mpa`/`mpb` port position and direction in that
file reproduces exactly from `klt gen`'s standalone-`none`-orientation report
plus the formulas above).

- **`nwell_tap`** (`{"x": 1.00, "y": 2.82}`): chosen so its `TAP_E` port
  (local `(1.63, 0.92)`, `none` orientation) lands at `y = 2.82 + 0.92 =
  3.74` — the **same** `y` as `mpa.U0_S` (`mpa_py`, per the `mirror_y`
  formula: `4.16 - 0.42 = 3.74`) — for a direct, jog-free wire once both are
  promoted to the final stage, and its bbox (`x1 = 1.00 + 1.99 = 2.99`)
  overlaps `mpa`'s own bbox (`x0 = 2.89`) by the usual `0.10 um` well-merge
  margin.
- **`psub_tap`** (`{"x": 1.02, "y": -0.71}`): chosen so its `TAP_E` port
  (local `(1.63, 0.92)`) lands at `y = -0.71 + 0.92 = 0.21` — the same `y` as
  `mnab.U0_S0` (`(3.24 + 0.21, -0.21 + 0.42) = (3.45, 0.21)`, `none`
  orientation, direct from `klt gen`'s own local report) — with a `0.38 um`
  clearance gap to `mnab`'s own bbox (`x0 = 3.24`, `psub_tap`'s own
  `x1 = 1.02 + 1.84 = 2.86`), comfortably inside `sky130`'s `li1` spacing
  floor. Both taps' physical body-tie role (nwell merge / substrate tie via
  bbox overlap or proximity) is identical to every other cell under
  `layout/` — see `layout/ro_buf/README.md`'s "Why abutted, not nested".

No trial-and-error was needed this time: composing on the first attempt
(`klt gen-compose`, `klt drc`, `klt extract`, `klt lvs` all passed cleanly in
one run) validated that the coordinate-transform approach above, derived
purely from `klt gen`'s own standalone reports plus `ro_nand2`'s committed
evidence as a cross-check, is sufficient — unlike most other leaf cells under
`layout/`, whose own READMEs document one or more rejected floorplan attempts
along the way.

## What this does NOT establish

- **Not `sampler_dff`.** This is the second of the three distinct leaf shapes
  `sampler_dff`'s 22 devices reduce to (3x plain inverter — already `ro_buf`;
  4x transmission gate — `layout/sampler_tg/`; 2x this NAND2). Assembling all
  22 devices into one `sampler_dff` cell, placed and routed, and LVS-checking
  it against `design/sampler_core.spice`'s real `.subckt sampler_dff` is the
  authoritative check and remains open — see issue #27.
- **No `sampler_core`.** The six-`sampler_dff`-instance wiring around the
  entropy source has no layout at all yet.
- **No parasitics, no post-layout simulation.** `klt extract` was run without
  `--parasitics`; nothing under `sim/` has been re-run against this cell.
- **The DRC verdict is against `klt`'s curated sky130 deck**, the same scope
  every other cell under `layout/` is checked against.
- **The LVS reference is hand-authored, not an xschem export** — same
  reason as `layout/sampler_tg/README.md` gives (`design/xschem/sampler_dff.sch`
  is flat, with no `sampler_nand2` sub-schematic symbol of its own, so there
  is no independently netlisted `.subckt sampler_nand2` anywhere in
  `design/*.spice`). The 4/4 device, 6/6 net match against it is real evidence
  that this GDS's own four devices are wired the way the schematic's own
  `NANDM`/`NANDS2` devices are — but the authoritative check happens once
  `sampler_dff` itself is assembled and checked against
  `design/sampler_core.spice`'s real `.subckt sampler_dff`.

No `2AMLogic/klayout-tools` friction was found composing this cell — `klt
gen`'s standalone per-block reports were sufficient to derive a working
floorplan without any tool-side gap.
