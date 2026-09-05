# layout/ro_buf

**The first composed, DRC-clean *and* LVS-clean cell in this repository.**

`ro_buf` is `design/ro_array_core.spice`'s unstarved CMOS inverter — the
per-ring output buffer `xb1`-`xb4` instantiate between each ring's raw node
and the XOR combining tree. Two devices, four nets; the simplest real gate
this design contains, and therefore the right first proof that
`klayout-tools`' generator + composition surface can build this design's
cells rather than only its individual transistors.

Rebuild and re-verify with:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
python3 layout/bin/compose-cell.py layout/ro_buf/cell.json            # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_buf/cell.json --check    # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` | 4/4 nets routed (`a`, `y`, `vdd`, `vss`) | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 2 devices, 4 nets, every terminal on a named net | `extract.json`, `ro_buf.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt ro_buf` | **match** — 2/2 devices, 4/4 nets, 0 mismatches | `lvs.json`, `ro_buf.ref.spice` |

The extracted netlist, in full:

```
.SUBCKT ro_buf a vdd vss y
M$1 y a vss vss nfet L=0.15U W=0.42U AS=0.1974P AD=0.1974P PS=1.78U PD=1.78U
M$2 y a vdd vdd pfet L=0.15U W=0.84U AS=0.3948P AD=0.3948P PS=2.62U PD=2.62U
.ENDS ro_buf
```

Both bodies land on the right rail — `b: vss` on the NMOS, `b: vdd` on the
PMOS — which is the whole point of the tap islands below, and is what
`layout/well-strap-poc/` established was needed but could not yet wire.

## Floorplan

Two device rows with a body-tie island west of each:

```
   [ nwell_tap ]==[ mp  (pfet 0.84/0.15, mirror_y) ]        y ~ 2.1 .. 4.6
        vdd            S(W)  G(S)  D(E)
                        |     |     |                        <- a, y route down
   [ psub_tap ]==[ mn  (nfet 0.42/0.15)            ]        y ~ -0.7 .. 1.2
        vss            S(W)  G(N)  D(E)
```

- **`mp` is `mirror_y`-flipped** so its gate faces *down*, at the same `x` as
  `mn`'s up-facing gate. `net a` is then a single straight vertical wire
  between two ports that face each other. Without the flip both gates face
  north and the router lifts the jog above *both* blocks, ploughing the
  connecting wire straight through the PMOS block — rejected, correctly.
- **`net y`** connects two east-facing drain ports, so it carries an explicit
  `waypoints_um` lane at `x = 1.9`, clear of both blocks' bboxes. The
  default one-stub-width jog would run at `x = 1.05`, i.e. straight back
  through both devices.
- **The tap islands are abutted, not nested** — see "Why abutted" below.
- `pins[]` labels `nwell_tap.TAP_N` → `vdd` and `psub_tap.TAP_N` → `vss`;
  the `a`/`y` net names come from `connectivity[]` directly (a port may be
  named by `pins[]` *or* wired by `connectivity[]`, not both).

### Why abutted, not nested (supersedes `layout/well-strap-poc/`'s geometry)

`layout/well-strap-poc/` established that a PMOS `mos_array` block placed
*inside* a `guard_ring`'s hollow cavity shares the ring's nwell, so the
device's bulk extracts to the ring's named net. That is true, and this cell
relies on the same underlying fact — but nesting turns out to be unusable for
a real cell: `klt gen-compose`'s obstacle check treats the enclosing ring as
an unrelated placed block, so *every* route reaching the enclosed device is
rejected for crossing it. Reproduced directly against the PoC's own committed
blocks:

```
vdd unrouted -- backbone's 0.17um-wide drawn path crosses 1.48um through its
own pin's block 'well_tap' -- more than that pin's own 0.445um edge margin
```

A body-tied device with no routable terminal is not a cell. Filed upstream,
generically, as
[2AMLogic/klayout-tools#1493](https://github.com/2AMLogic/klayout-tools/issues/1493)
(`mos_array` has no `add_guard_ring` the way `diff_pair`/`esd_device` do, and
`gen-compose` has no way to declare that one block encloses another).

**Abutment works instead**, and needs no tool change. A `mos_array` block's
reported `bbox_um` already *includes* its own 0.15 µm well margin, and a
`guard_ring`'s routing metal is inset from its bbox by the same margin. So
overlapping the two blocks' bboxes by 0.10 µm:

- overlaps their **nwells** by 0.10 µm — one merged electrical region, so the
  PMOS bulk resolves to the ring's labelled net; while
- leaving their **li1** 0.20 µm apart — clear of sky130's 0.17 µm li1
  spacing floor.

Align the device port's and the tap port's cross-axis coordinate (here
`y = 3.53` for `vdd`, `y = 0.21` for `vss`) so the connecting route is a
straight line that stays inside each endpoint's own edge-margin allowance.
`klt drc` clean, `klt extract` resolves both bodies. The same construction
gives the NMOS row its `vsubs`-to-`vss` substrate tie, which
`layout/primitives/README.md` correctly flagged as still open.

## What this does NOT establish

- **The DRC verdict is against `klt`'s curated sky130 deck, not sky130
  sign-off.** `drc.json`'s own `coverage` block is explicit about this:
  `deck_scope` covers `nwell`/`difftap`/`poly`/`licon`/`li`/`met1`-`met5`/
  `via*`/`capm`, `layers_checked` was only `64/20, 65/20, 66/20, 66/44,
  67/20`, and `layers_in_stream_without_rules` lists `65/44` (the tap
  diffusion) — i.e. the tap rings' own geometry carries no rules in this
  deck. The generators also draw **no implant layers** (`nsdm`/`psdm`), which
  a full sky130 deck would require. "DRC-clean" here means exactly "zero
  violations of the rules this deck checks", nothing more.
- **No parasitics, no post-layout simulation.** `klt extract` was run without
  `--parasitics`; nothing under `sim/` has been re-run against this cell.
- **One gate, not a block.** `ro_stage`, `ro_nand2`, `xor2`, `ro_ring5`,
  `ro_array_core`, `sampler_dff`, `sampler_core` are all still unbuilt — see
  `../README.md` § "What's deferred" and issue #27.
- **The LVS reference is a unit-normalised copy**, not `design/*.spice`
  byte-for-byte — `ro_buf.ref.spice` is generated from the design netlist's
  own `.subckt ro_buf` with `u` suffixes appended to the `L=`/`W=` values,
  because `klt lvs`'s `subckt-call` converter reads an unsuffixed value as
  metres while this design's netlists are unitless-under-`.option scale=1u`.
  Only unit spellings differ; diff it against the source subckt to confirm.
  Filed upstream as
  [2AMLogic/klayout-tools#1492](https://github.com/2AMLogic/klayout-tools/issues/1492).
