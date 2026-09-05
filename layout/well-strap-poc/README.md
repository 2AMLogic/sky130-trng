# layout/well-strap-poc

Solves the single most concrete blocking unknown `layout/README.md` (issue
#22's first increment) and its follow-up tracking issue
[#27](https://github.com/2AMLogic/sky130-trng/issues/27) named: **how to
physically strap a `klt gen mos_array`-drawn PMOS's own (implicit, unstrapped)
nwell to a real supply net**, so `klt extract` resolves the device's bulk
terminal to a named net instead of an anonymous, isolated one.

## The problem, restated precisely

`klt gen mos_array --params '{"flavor":"pfet",...}'` draws a PMOS unit
device's own nwell but no tap contact into it (`layout/primitives/README.md`).
Every reference netlist under `design/*.spice` ties PMOS bulk explicitly to a
supply (`XMp y a vdd vdd sky130_fd_pr__pfet_01v8 ...` — the last `vdd` before
the model name is the bulk terminal), so an LVS-matching gate needs that
nwell strapped to a real net.

The obvious fix — place a separate well-tap block (`klt gen guard_ring
--params '{"add_well":true,...}'`) *beside* the `mos_array` block — fails: the
two blocks' own local-interconnect (`li1`) geometry collides (a `li1.space.1`
DRC violation) at any offset close enough for their **nwells** to touch/merge
into one electrical node, because `guard_ring`'s own well margin (the gap
between its tap ring's outer `li1`/diffusion edge and its own nwell's outer
edge) is a fixed ~0.15 µm — not wide enough to also clear `li1.space.1`
against a neighbouring block's own `li1`.

## The fix: nest, don't abut

`guard_ring`'s `add_well: true` output draws its nwell as **one solid
rectangle spanning its entire outer bounding box**, including the hollow
cavity in the middle of its own tap ring/diffusion loop (verified directly:
`klt layers pmos_well_tap.gds --flattened` reports layer `64/20` — sky130's
`nwell.drawing` — as a single shape whose bbox is the guard ring's *whole*
outer extent, not just the ring's own footprint). That means a `mos_array`
PMOS block **placed inside** that hollow cavity sits inside the *same*
physical nwell as the ring's own well tie, merging into one electrical node —
with the ring's own tap diffusion/`li1` kept at whatever `li1.space.1`-safe
clearance the caller sizes `inner_width_um`/`inner_height_um` to give it,
completely independent of the (fixed, non-adjustable) well margin that broke
the side-by-side placement.

Concretely, for a `w_um=0.84, l_um=0.28` PMOS (`pfet_demo.gen.json`'s own
reported `bbox_um`, 1.29 × 1.96 µm):

1. Generate the well tap (`guard_ring`, `add_well: true`) with
   `inner_width_um`/`inner_height_um` set to the PMOS's own bbox size plus
   `2 × 0.5 µm` clearance on every side (0.5 µm comfortably clears
   `li1.space.1`; not derived from the deck's exact rule value, just a safe
   round number — see `pmos_well_tap.gen.json`: `inner_width_um: 2.29`,
   `inner_height_um: 2.96`, `ring_width_um: 0.42`, `contacts_per_side: 4`).
2. Compose (`klt gen-compose`, `placement.strategy: "explicit"`) with the
   `guard_ring` block at the origin and the `mos_array` block's own origin
   offset by exactly that clearance margin — i.e. centred in the ring's
   hollow inner cavity — see `compose.request.json`.
3. Label one of the ring's own `TAP_*` ports `"vdd"` via `gen-compose`'s
   `pins[]` (writes a real `kdb.Text` label onto the ring's own metal, which
   is what `klt extract` reads to name the merged net) — no `connectivity[]`/
   routing needed for the *body* connection itself, since the wells are
   already one continuous physical region.

## Result (reproduced, both steps below)

```
$ klt drc pmos_with_well_strap.gds --deck sky130 --format json
status: clean, violation_count: 0                    # drc.json

$ klt extract pmos_with_well_strap.gds --deck sky130 --format json
devices[0]: {"class": "pfet", "nets": {"s": "$1", "g": "$3", "d": "$2", "b": "vdd"}, ...}
                                                       # extract.json — bulk
                                                       # is now the *named*
                                                       # "vdd" net, not an
                                                       # anonymous one
```

`s`/`g`/`d` are still each their own isolated single-terminal net in this PoC
— this directory proves only the **body/well strap**, not a working,
fully-wired inverter (that composition — the actual `ro_buf` gate, plus
`ro_stage`/`ro_nand2`/`xor2`, per issue #27's step 2 — is still open, and now
additionally blocked by the regression below).

## NMOS's substrate strap: no equivalent fix needed

`layout/primitives/README.md` already established that `klt extract` ties
every NMOS bulk to `vsubs` (sky130's single global p-substrate net)
automatically, with no drawn tap required — `klt lvs`'s own
`device.body_unverified` diagnostic (a non-blocking `severity: "warning"`
entry; confirmed by reading `klayout_tools/lvs.py`'s `_body_net_warnings` and
`run_lvs`, where warning-severity entries are appended *after* `status` is
already fixed from the comparator's own boolean verdict — they never change
it) is the tool's own documented, deliberate treatment of this case for a
deck (sky130's) that declares *some* tap mechanism, matching real sky130
design practice where the substrate genuinely is one shared conductor
chip-wide. The open item this repo still owns is a single `vsubs`-to-`vss`
strap *somewhere* in the composed design (not per-device) — unchanged from
`layout/README.md`'s existing note, not addressed by this PoC.

## Regression discovered while building this: `mos_array` sub-0.28 µm gate length + `gate_contact` (file against `2AMLogic/klayout-tools`)

While reproducing this repo's own already-committed `layout/primitives/`
evidence to build the PoC above, `klt gen mos_array` with this repo's
*actual* device geometries (`l_um=0.15`, `w_um=0.84`, `flavor=pfet`,
`gate_contact=true` — `pfet_w0p84_l0p15`, the exact params
`layout/primitives/README.md`'s reproduction recipe names) came back **DRC-
violating** (`li1.space.1`, 1 violation) against the `klt` version actually
pinned in this environment (`uv tool list` → `klayout-tools v0.2.0`) —
`regression-evidence/pfet_w0p84_l0p15_regen.{gen,drc}.json`.

Diffing the freshly-generated `gen.json` against the one already committed at
`layout/primitives/pfet_w0p84_l0p15/gen.json` (same params, same generator)
shows the geometry itself changed (`bbox_um.x1` 1.24 → 1.14, `U0_D.x_um` 0.88
→ 0.78, `U0_G.x_um` 0.545 → 0.495) and, tellingly, the generator's own
`drc_hints.notes` text changed with it: the committed evidence's version
reads *"the S/D local-metal pads are automatically padded clear of the gate
(issue #1187), so no S/D metal minimum-spacing violation results from this
alone"*; the regenerated version's reads plainly *"gate length below 0.28um
may violate the target PDK's poly minimum-width or S/D metal minimum-spacing
rule"* — i.e. **the pinned `klt` v0.2.0 does not include whatever fix
`issue #1187` shipped**, which the committed evidence's own generator build
did have. This PoC's own PMOS demo above deliberately uses `l_um=0.28` (the
generator's own documented threshold) specifically to route around this,
since sub-0.28 µm gate length is exactly this design's actual sizing
(DR-0002/DR-0003) for every device this repo's schematics instantiate.

**Practical consequence**: composing this design's *real* gates (`ro_buf`,
`ro_stage`, `ro_nand2`, `xor2` — all `l_um=0.15` or `l_um=2.0` starve
devices per `layout/primitives/README.md`'s table) is blocked pending either
a `klayout-tools` release that restores issue #1187's fix, or a locally-drawn
S/D pad workaround this repo would have to build itself (undesirable — it
would silently diverge from the generator's own intended geometry). Four of
the six primitives already committed under `layout/primitives/` (every
`l_um=0.15` one — `pfet_w0p84_l0p15`, `nfet_w0p42_l0p15`, `nfet_w0p84_l0p15`,
`pfet_w1p68_l0p15`) are **not reproducible DRC-clean** if regenerated fresh
against the currently-pinned tool version, even though the already-committed
`.gds` bytes for those four still DRC-clean today (`klt drc` re-checks
*geometry*, not the generator that made it — the committed files are static
and unaffected). Filed as
[2AMLogic/klayout-tools#1491](https://github.com/2AMLogic/klayout-tools/issues/1491)
— see that issue for the generic, design-agnostic report.

## What's still open (tracking issue #27)

This PoC closes step 1 of #27's plan (the well-strap nesting math) but does
not attempt steps 2+ (composing an actual gate, ring, array, or sampler; full
DRC/LVS sign-off; post-layout PVT; the `wstv` re-evaluation) — those remain
blocked on the regression above for this design's real (`l_um=0.15`) device
sizes, independent of the composition methodology itself.

## Reproducing

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

PDK=sky130A klt gen mos_array --params '{"w_um":0.84,"l_um":0.28,"rows":1,"cols":1,"dummy":0,"flavor":"pfet","gate_contact":true}' \
  --pdk sky130A --cell-name pfet_demo -o pfet_demo.gds --format json > pfet_demo.gen.json

PDK=sky130A klt gen guard_ring --params '{"inner_width_um":2.29,"inner_height_um":2.96,"ring_width_um":0.42,"contacts_per_side":4,"add_well":true}' \
  --pdk sky130A --cell-name pmos_well_tap -o pmos_well_tap.gds --format json > pmos_well_tap.gen.json

PDK=sky130A klt gen-compose compose.request.json --format json > compose.response.json
mv gen_compose_0.gds pmos_with_well_strap.gds

PDK=sky130A klt drc pmos_with_well_strap.gds --deck sky130 --format json      # clean, 0 violations
PDK=sky130A klt extract pmos_with_well_strap.gds --deck sky130 --format json # devices[0].nets.b == "vdd"
```
