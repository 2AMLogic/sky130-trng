# layout/ro_ring5

`design/ro_array_core.spice`'s `.subckt ro_ring5 en ro vddr vss` at the
ladder's nominal `wstv = 0.42 µm` — i.e. `ro_array_core`'s ring `xr1` —
composed from the five already-committed, individually DRC-clean and
LVS-clean leaf gates under [`layout/ro_nand2/`](../ro_nand2/README.md) (`xg`)
and [`layout/ro_stage/`](../ro_stage/README.md) (`x1`-`x4`).

**This is the first multi-gate cell in this repository that is both `klt drc`
clean and `klt lvs` matching**, and therefore the first evidence that the
leaf-cell methodology composes upward at all. Everything before it was a
single gate (`ro_buf`/`ro_stage`/`ro_nand2` and their `wstv` variants) or a
placement-only proof of concept.

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/compose-cell.py layout/ro_ring5/cell.json          # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_ring5/cell.json --check  # verify, don't overwrite
```

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` stage `place` (placement only, no nets) | 5 blocks placed, 21 ports promoted | `place.compose.response.json` |
| `klt gen-compose` stage `sig` (metal2 / met1) | 4/4 nets routed (`n1`-`n4`) | `sig.compose.response.json` |
| `klt gen-compose` stage `fb` (metal2 / met1) | 1/1 net routed (`ro`) | `fb.compose.response.json` |
| `klt gen-compose` final stage (metal3 / met2) | 8/8 legs routed (`vddr` ×4, `vss` ×4) | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | 22 devices (11 nfet + 11 pfet), 19 nets | `extract.json`, `ro_ring5.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s own `.subckt ro_ring5` | **match** — 22/22 devices, 19/19 nets, 0 errors | `lvs.json`, `ro_ring5.ref.spice` |

22 devices is exactly `ro_nand2`'s 6 + 4 × `ro_stage`'s 4, with nothing
dropped or duplicated by placement. Composed extent (final GDS bounding box,
rails included): `-2.19 … 38.935 µm` in x, `-3.085 … 6.085 µm` in y.

**Every intermediate stage is independently DRC-clean too** (`klt drc
place.gds` / `sig.gds` / `fb.gds`, all `clean, 0 violations`), which is what
makes the failure analysis below attributable: a violation that appears at
stage *n* was introduced by stage *n*, not inherited.

## Why four stages

The ring needs three physical routing planes, and two of the four stages
cannot share a `gen-compose` call with each other.

### 1. `place` — placement only

No `connectivity[]` at all; every port of every leaf gate is promoted through
`pins[]`. This exists as a separate stage for two reasons: it isolates the
placement-pitch question from every routing question (see the DRC note
above), and its promoted `ports[]` is what the later stages route against.

**Pitch**: `ro_nand2`'s own nwell ends at local `x = 5.57 µm`; `ro_stage`'s
starts at local `x = -2.19 µm`. `sky130.lydrc`'s `nwell.space.1` wants
`1.27 µm` of nwell-to-nwell clearance, so the `g`→`s1` origin delta must be
at least `5.57 + 2.19 + 1.27 = 9.03 µm`. This cell uses `9.30 µm`
(`1.54 µm` gap). `ro_stage`'s own nwell ends at local `x = 4.28 µm`, so the
`s1`→`s2`→`s3`→`s4` deltas keep the narrower `8.175 µm` stage pitch
(`1.705 µm` gap). Origins: `g` 0, `s1` 9.30, `s2` 17.475, `s3` 25.65,
`s4` 33.825 µm.

### 2. `sig` — `n1`-`n4` on metal2 (met1), one shared lane at `y = -1.5 µm`

The four forward inter-gate nets do not overlap in x
(`4.79→12.985`, `14.20→21.16`, `22.375→29.335`, `30.55→37.51 µm`), so one
lane holds all four with ≥ `1.2 µm` between neighbouring nets.

**li1 does not work for these nets, and this is a property of the leaf
cells, not a tuning failure.** Each leaf gate's `a` input port sits *inside*
its own device cluster: for `ro_stage` it is at local `(3.685, 1.87) µm`,
with the `Mp` PMOS's own S/D pads at local x `3.04–3.46` and `3.71–4.13 µm`
directly above it and the `Mn` NMOS's pads directly below. A `0.17 µm` li1
route descending onto that port occupies local x `3.60–3.77 µm`, which
**overlaps** the `3.71–4.13 µm` pad — a short, not a spacing violation.
Approaching from below, from the left (blocked by the `vss` guard ring) or
from the right (blocked by the `y` net's own li1 column at local
`3.92–4.985 µm`) all fail the same way. See "The correction this cell makes"
below: this is exactly what the earlier `ro_ring5-connectivity-poc` did, and
its `n1`-`n4` were all shorted together as a result.

### 3. `fb` — `ro` on metal2, in its own `gen-compose` call

`ro` is `x4`'s output fed back into `xg`'s input, and is also the ring's
external output pin. It has to cross the whole ring, so on met1 it would
cross every one of the `sig` stage's four vertical risers. `klt gen-compose`
performs no net-to-net short check *between* separate calls, so routing it
in its own stage is allowed — and is checked after the fact by DRC (spacing)
and by the extraction/LVS below (shorts).

Its path is hand-planned rather than left to the router:

- **The `g` end is the tight one.** `ro_nand2`'s own internal met1 (drawn by
  its two-pass `"stages"` composition) covers essentially all of net `a`'s
  li1: the `y`-net met1 arm occupies local x `4.455–4.625 µm` from
  y `0.915–3.740 µm`. The one exposed spot is the a-side PMOS gate pad
  (li1, local `4.665–5.085 × 2.500–2.920 µm`). `gen-compose` draws a
  `0.42 µm` via landing pad regardless of the declared port width, so the
  port's x decides whether that pad clears the `y` arm by met1's `0.14 µm`
  minimum. Measured, holding everything else fixed:

  | port `a` local x | `klt drc ro_ring5.gds` |
  |---|---|
  | 4.90 | 1 × `met1.space.1` (65 nm gap) |
  | 4.95 | 1 × `met1.space.1` (115 nm gap) |
  | **4.98** | **clean, 0 violations** |
  | 5.00 | clean, 0 violations |
  | 5.02 | clean, 0 violations |

  `4.98 µm` is used: it is the first clean value, and it keeps the `mcon`
  cut (`4.895–5.065 µm`) inside the li1 pad with margin on both sides, which
  `5.00` and above progressively give up.

- It then leaves `g`'s bbox eastward at `y = 2.75 µm`, rises at
  `x = 6.3 µm` (in the `g`/`s1` gap, clear of both gates' met1) and crosses
  the ring at `y = 5.4 µm` — above every leaf cell's own met1, the highest
  of which is `ro_nand2`'s at `y = 4.585 µm` — before dropping onto `s4`'s
  `y` port at `x = 38.725 µm`.

### 4. final stage — `vddr` and `vss` on metal3 (met2)

met2 is completely empty in both leaf cells (0 shapes), so it is a free
plane for the rails. To use it, `gen-compose`'s **single-hop via-drop rule**
has to be satisfied: `"metal3"` can only reach a pin already on `"metal2"`.
The previous attempt (`ro_ring5-connectivity-poc`) hit exactly this wall and
proposed an extra li1→met1 promotion stage to get around it.

**No promotion stage is needed.** Both rails are *already* on met1 inside
each leaf gate, because each leaf's own second stage routed them there:

- `vddr`'s met1 route has a horizontal top arm at local y `4.315–4.485 µm`
  spanning local x `-2.085 … 2.085 µm` (`ro_nand2`) / `2.485 µm`
  (`ro_stage`). The rail port is declared on layer `68/20` at local
  `(0.0, 4.40) µm` — inside that arm, on its own net.
- `vss`'s met1 route has a vertical arm at local x `0.415–0.585 µm`
  spanning y `0.835–2.835 µm`. The rail port is declared at local
  `(0.5, 2.0) µm`.

Declaring the block port directly on met1 turns the two-hop problem into a
one-hop one, and the rails route in a single stage. `vddr` buses above the
cells at `y = 6.0 µm` and `vss` below at `y = -3.0 µm`, so neither bus
crosses the other's per-gate risers (the `vddr` risers span y `4.4→6.0`, the
`vss` risers y `-3.0→2.0`).

## The correction this cell makes to `ro_ring5-connectivity-poc`

The previous increment's
[`layout/ro_ring5-connectivity-poc/`](../ro_ring5-connectivity-poc/README.md)
recorded its `n1`-`n4` signal chain as "proven" (all four nets reported
`"status": "routed"`, 22 devices and 19 nets extracted "matching
expectation") and its 8 DRC violations as one diagnosed placement-pitch bug
plus "**7 `li1.space.1` violations … 2 attributed, 5 unexplained**", with the
five device-internal ones tentatively blamed on "a hierarchy-dependent DRC
evaluation difference".

**All three of those readings were wrong, and the errors compound.**

1. **There is no hierarchy-dependent DRC effect.** The same placement with
   the pitch corrected and *no* routing at all (`place.gds` here) is
   `klt drc` **clean, 0 violations**. Every one of the seven
   `li1.space.1` violations came from the routes.
2. **All seven are route-versus-device li1 spacing**, not device-internal
   geometry. KLayout attributes a space violation to the deepest cell on one
   of the two facing edges, which is why five of them *looked* like they lay
   inside a `mos_array`. Reading the geometry directly: the violation at
   `(12220,3224)-(12360,4256)` nm sits between `s1`'s `Mp` pad ending at
   x = 12220 nm and the `n1` route's own descending riser starting at
   x = 12360 nm. The identical shape repeats once per `ro_stage` instance
   at the identical *local* coordinates, which is the signature of a route
   drawn at each gate's port, not of a per-instance geometry difference.
3. **The signal chain was not merely marginal — it was shorted.** The same
   risers overlap the *next* pad along (local `3.71–4.13 µm`) outright. The
   PoC's own committed `extract.json` says so, and it was read as a
   device/net count rather than as a net list: it reports a single net named

   ```
   a|g_a|mnab_y|mpa_y|mpb_y|n1|n2|n3|n4|s4_y|y     device_count: 21
   ```

   i.e. `n1`, `n2`, `n3`, `n4`, the ring output and every gate's output are
   one electrical node. All five gate outputs are tied together; the ring
   cannot oscillate. `klt extract` said so at the time, in the committed
   evidence: that file's `merged_net_labels` block lists all eleven labels,
   and its `warnings` array opens with `net '…' merges 11 distinct labels …
   this usually means two differently-named nets were shorted together in
   the layout`. The tooling was not silent; the report was read for its
   counts only.

**The transferable lesson**: a `"routed"` verdict from `gen-compose` plus a
plausible device/net *count* from `klt extract` is not evidence of
connectivity. `gen-compose` checks route-versus-route conflicts within one
call and route-versus-*block-pad* conflicts for blocks it is routing across,
but a route that terminates *inside* a destination block may pass through
that block's own geometry on the way in. The cheap guard is the one this
repo already has and the PoC bypassed: run the whole `compose-cell.py`
chain, so LVS gets a chance to fail. The expensive guard is reading
`extract.json`'s `nets[].name` list rather than its `net_count`.

## What is and is not signed off

- **Is**: `ro_ring5` at `wstv = 0.42 µm` — DRC-clean against `klt`'s sky130
  deck, LVS-matching against the design's own schematic-exported subckt, at
  this design's real device sizes, reproducible from a committed descriptor.
  The rails are bussed in metal, the feedback net is closed, and the
  `en` input is a top-level pin.
- **Is not**:
  - **A whole-block claim.** `ro_array_core` still needs the four rings
    tiled with a shared supply, `ro_buf` fan-out and the `xor2` combining
    tree. (`xor2` itself is no longer the blocker it was when this was
    written: it is composed, DRC-clean and LVS-clean in
    [`layout/xor2/`](../xor2/README.md). What is missing is the
    array-level assembly, not a leaf cell.)
  - **A full sky130 sign-off.** `klt`'s sky130 deck is a curated subset;
    read `drc.json`'s own `coverage` block. For this cell the checked layer
    set does cover the entire stack it uses (`li1`/`mcon`/`met1`/`via`/
    `met2`, i.e. `67/20`, `67/44`, `68/20`, `68/44`, `69/20`), so the
    `rules_skipped` list here is met3-and-above plus MiM-cap rules that this
    cell has no geometry on. That is a better position than the standing
    caveat implies, but it is still not a sign-off run.
  - **An antenna / density / fill claim.** Nothing here checks those.
  - **A hierarchical LVS.** `lvs.json` carries one `topology.flattened`
    warning: `options.flatten_reference` collapses the reference's three
    circuits (`RO_RING5`, `RO_NAND2`, `RO_STAGE`) into one before comparing,
    because `klt extract` hands LVS a flat 22-device layout netlist. The
    device-for-device and net-for-net correspondence is therefore verified
    after the hierarchy boundary is removed on the reference side. That is
    the correct comparison for a flat extraction, but it does *not* verify
    that the layout's cell hierarchy mirrors the schematic's.
  - **Post-layout simulated.** No `--parasitics` extraction or `sim/` record
    is minted here; `layout/pex/` still covers leaf cells only.

## Negative control: the LVS match is width-specific

Four ring cells that differ by `0.02 µm` on ten devices each, all reporting
`match`, invite the same objection the leaf cells' own README answers.
Feeding `ro_ring5_wstv0p48`'s extracted netlist against **this** cell's
`ro_ring5.ref.spice` (`wstv = 0.42`) — the only change — flips the verdict:

```
status: mismatch   mismatch_count: 63   error_count: 62
counts: nets 19/19 matched 7, devices 22/22 matched 12
  device.property  error  matched device parameter 'w_um' differs
  device.property  error  matched device parameter 'as'/'ad'/'ps'/'pd' differs
```

Exactly 12 of 22 devices still match — which is exactly the count of
`wstv`-independent devices in a ring (`ro_nand2`'s `Mpa`/`Mpb`/`Mna`/`Mnb`
plus each `ro_stage`'s `Mp`/`Mn`) — and none of the 10 starve devices
(`Mph`/`Mnt`, one pair per gate) does. So each ring's `match` is evidence
that *that* layout implements *that* ring's `wstv`, not merely that some
five-stage starved ring was drawn.

## Files

| File | What it is |
|---|---|
| `cell.json` | the committed descriptor — four stages, LVS spec |
| `place.compose.{request,response}.json`, `place.gds` | stage 1 (placement) |
| `sig.compose.{request,response}.json`, `sig.gds` | stage 2 (`n1`-`n4`, met1) |
| `fb.compose.{request,response}.json`, `fb.gds` | stage 3 (`ro`, met1) |
| `compose.{request,response}.json`, `ro_ring5.gds` | final stage (rails, met2) |
| `drc.json` | `klt drc` report (clean) |
| `extract.json`, `ro_ring5.spice` | `klt extract` report + layout netlist |
| `ro_ring5.ref.spice`, `lvs.request.json`, `lvs.json` | generated reference + LVS report |
