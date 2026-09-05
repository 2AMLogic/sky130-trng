# layout/primitives

Proof-of-methodology evidence for issue #22: one `klt gen mos_array`-drawn
GDS per **distinct transistor geometry** this repository's schematics
actually instantiate, each independently verified with `klt drc` and
`klt extract` against the sky130 open PDK. This is the maximum honest
increment toward issue #22's full acceptance bar (a DRC/LVS-clean GDS for
`ro_array_core`/`sampler_core`, plus post-layout PVT) achievable in one PR —
see `../README.md` for the full floorplan/status writeup and what is
deliberately deferred.

## Claim under test

Does `klt`'s installed generator surface (`klt gen`, family 1's `mos_array`)
actually draw every transistor geometry `design/xschem/{ro_stage,ro_nand2,
ro_buf,xor2}.sch` instantiate, DRC-clean against the sky130 deck, with
`klt extract` recovering the intended device class and W/L?

**Yes, for all six geometries below.** This directly refutes issue #22's
curator note that `klt`'s command surface has "no obvious path to compose
full-custom analog polygon layout by hand" — see `../README.md` § "Correcting
the curation note" for the citation trail (this session found `klt gen`,
`klt gen-compose`, and `klt draw`, none of which the curation pass's snapshot
of the tool surface had discovered).

## The six geometries

Derived by reading every `X...` device card in `design/ro_array_core.spice`
(the committed, `netlist.py`-generated netlist library — see
`design/README.md` § "Regenerating the netlists"): every `(flavor, w_um,
l_um)` pair that netlist instantiates, deduplicated. `gate_contact: true` on
every call (finishes the gate stack to a routable local-metal pad —
needed for the follow-up composition work in the tracking issue, not for
this proof by itself).

| Directory | flavor | `w_um` | `l_um` | Used by (schematic / device) |
|---|---|---|---|---|
| `pfet_w0p84_l0p15/` | pfet | 0.84 | 0.15 | `ro_buf.Mp`, `ro_stage.Mp`, `ro_nand2.Mpa`/`Mpb`, `xor2.MpiA`/`MpiB` |
| `nfet_w0p42_l0p15/` | nfet | 0.42 | 0.15 | `ro_buf.Mn`, `ro_stage.Mn`, `xor2.MniA`/`MniB` |
| `nfet_w0p84_l0p15/` | nfet | 0.84 | 0.15 | `ro_nand2.Mna`/`Mnb`, `xor2.Mn1`-`Mn4` |
| `pfet_w1p68_l0p15/` | pfet | 1.68 | 0.15 | `xor2.Mp1`-`Mp4` |
| `pfet_starve_w0p42_l2/` | pfet | 0.42 (`wstv`) | 2.0 (`lstv`) | `ro_stage.Mph`, `ro_nand2.Mph` — the always-on starve header. `wstv` is drawn here at ring 1's nominal 0.42 µm; DR-0003's array instantiates four rings at `wstv` = 0.42/0.44/0.46/0.48 µm (`design/ro_array_core.spice`'s four `xr1`-`xr4` calls) — the same generator call with `w_um` substituted covers the other three, deferred to the tracking issue's composition phase rather than duplicated here |
| `nfet_starve_w0p42_l2/` | nfet | 0.42 (`wstv`) | 2.0 (`lstv`) | `ro_stage.Mnt`, `ro_nand2.Mnt` — the always-on starve footer. Same `wstv` note as above |

Each directory holds:

- `<name>.gds` — the drawn cell (`klt gen mos_array` output)
- `gen.json` — the full `klt gen` response (bbox, ports, `drc_hints`)
- `drc.json` — `klt drc --deck sky130` response
- `<name>.spice`, `extract.json` — `klt extract --deck sky130` output: the
  extracted SPICE (devices + connectivity, no parasitics) and its structured
  JSON summary

## Result

| Directory | `klt drc` | `klt extract`: device class | `klt extract`: `w_um`/`l_um` recovered | bulk (`b`) net |
|---|---|---|---|---|
| `pfet_w0p84_l0p15/` | **clean**, 0 violations | `pfet` | 0.84 / 0.15 (exact) | isolated (own nwell, unstrapped) |
| `nfet_w0p42_l0p15/` | **clean**, 0 violations | `nfet` | 0.42 / 0.15 (exact) | `vsubs` (sky130's single global p-substrate net) |
| `nfet_w0p84_l0p15/` | **clean**, 0 violations | `nfet` | 0.84 / 0.15 (exact) | `vsubs` |
| `pfet_w1p68_l0p15/` | **clean**, 0 violations | `pfet` | 1.68 / 0.15 (exact) | isolated (own nwell, unstrapped) |
| `pfet_starve_w0p42_l2/` | **clean**, 0 violations | `pfet` | 0.42 / 2.0 (exact) | isolated (own nwell, unstrapped) |
| `nfet_starve_w0p42_l2/` | **clean**, 0 violations | `nfet` | 0.42 / 2.0 (exact) | `vsubs` |

Every geometry: DRC-clean, and `klt extract` recovers the exact intended
device class and W/L — reproduce with `klt drc <dir>/<name>.gds --deck sky130`
/ `klt extract <dir>/<name>.gds --deck sky130`.

## What this does NOT establish (read before citing)

- **Single devices only — no gate composition.** None of these six GDS files
  is a working logic gate. `ro_buf`, `ro_stage`, `ro_nand2`, `xor2` each need
  2-12 of these devices placed and routed together (`klt gen-compose`) before
  `klt drc`/`klt lvs` can be run against a multi-device cell.
- **The PMOS well-strap gap.** Both `pfet_*` geometries extract with an
  **isolated, unstrapped** bulk net (`$4` — `klt extract`'s placeholder name
  for a floating net) — `mos_array`'s own docs confirm a `flavor: "pfet"`
  call draws the nwell but no well-tap contact into it. Every reference
  netlist under `design/*.spice` ties PMOS bulk explicitly to `vddr`/`vdd`
  (e.g. `ro_buf.spice`'s `XMp y a vdd vdd ...`), so composing an LVS-matching
  cell needs a `guard_ring`/`well_island`-drawn well tap physically abutting
  each PMOS device's own nwell, strapped to the right supply net — confirmed
  buildable (both generators exist and were smoke-tested against `sky130A`
  during this investigation) but not yet composed into a working cell. This
  is the single most concrete open item the tracking issue names.
- **NMOS substrate already resolves, but to `vsubs`, not `vss`.** sky130's
  substrate is one global p-well/p-sub region, so `klt extract` ties every
  NMOS bulk to a single net (`vsubs`) without any per-device tap — but that
  net is not automatically the same node as `vss` unless something in the
  composed layout straps `vsubs` to `vss` somewhere. The reference netlists
  assume that strap exists (as a real chip's own substrate tap ring would
  provide it) — composing a full cell/array still needs at least one
  `vsubs`-to-`vss` tap in the design, even though no *per-device* well
  strapping is needed for NMOS the way it is for PMOS.
- **No routing, no hierarchy, no array, no sampler, no PVT.** `ro_ring5`,
  `ro_array_core`, `sampler_dff`/`sampler_core`, and post-layout PVT
  simulation against extracted parasitics are all untouched by this
  directory — see `../README.md` and the tracking issue for the plan.
