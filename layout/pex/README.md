# layout/pex

The post-layout (parasitic-annotated) netlist library, and the evidence that
produced it.

`ro_ring5_pex.spice` is a **generated** file: `layout/bin/pex-netlist.py`
runs `klt extract --pdk sky130A --parasitics` over each composed cell's
committed GDS and composes the results into one ngspice-runnable subcircuit
library. It is what
`sim/post-layout-ro-ring5/` simulates, and it is the first artifact in this
repo that lets a `sim/` record say anything about *physical* interconnect
rather than about xschem's schematic export.

**There are now two libraries here, from two descriptors, built by the same
script.** `pex.json` -> `ro_ring5_pex.spice` is the entropy-source side
(nine cells, everything a ring or the array instantiates).
`pex-sampler.json` -> `sampler_dff_pex.spice` is the **sampler** side (three
cells, everything `design/sampler_core.spice`'s flat 22-device
`.subckt sampler_dff` reduces to), simulated by
`sim/post-layout-sampler-dff/`. Everything below applies to both unless it
names one; see "The sampler library" for what is specific to the second.

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex/pex.json --check   # verify
python3 layout/bin/pex-netlist.py layout/pex/pex.json           # regenerate
```

`--check` re-extracts every cell from its committed GDS into a temporary
directory and fails if the rebuilt library differs from the committed one by
so much as a byte (plus a verdict-field diff of each extraction report) --
the same contract `layout/bin/compose-cell.py --check` and
`design/netlist.py --check` offer. `layout/test_pex_netlist.py` is the other
half of the guard: `--check` proves the committed library is what the script
produces *today*, the unit test proves the script's own transformations are
correct.

## What is in here

| Path | What it is |
|---|---|
| `pex.json` | the descriptor: which cells, their design port order, and the extractor-joined-net renames |
| `ro_ring5_pex.spice` | **generated** -- the library a `sim/` deck includes |
| `raw/<cell>.pex.spice` | `klt extract`'s own output, unmodified, for diffing against the composed library |
| `reports/<cell>.extract.json` | that run's full JSON response: per-net R/C breakdown, the parasitic model's own self-description, and `provenance.klt_version` |

Nine cells, every one of them already `klt drc` clean (0 violations) and
`klt lvs` matching its `design/*.spice` reference -- the composed cells
issues #22/#27 landed across PRs #35/#37/#41/#42. **All nine were
re-verified with `compose-cell.py --check` on `klt 0.4.0` in the same
session that produced this directory**, so the GDS these parasitics come out
of is the same GDS that carries the DRC/LVS verdicts:

| Cell | Devices | Nets | Total series R | Total C to substrate | Net-to-net coupling C |
|---|---|---|---|---|---|
| `ro_nand2_pex_wstv0p42` | 6 | 8 | 2020.96 Ω | 6.2514 fF | 0.01598 fF |
| `ro_nand2_pex_wstv0p44` | 6 | 8 | 2022.91 Ω | 6.2575 fF | 0.01598 fF |
| `ro_nand2_pex_wstv0p46` | 6 | 8 | 2024.88 Ω | 6.2635 fF | 0.01598 fF |
| `ro_nand2_pex_wstv0p48` | 6 | 8 | 2026.86 Ω | 6.2696 fF | 0.01598 fF |
| `ro_stage_pex_wstv0p42` | 4 | 6 | 1712.59 Ω | 4.7199 fF | 0.00312 fF |
| `ro_stage_pex_wstv0p44` | 4 | 6 | 1714.31 Ω | 4.7258 fF | 0.00327 fF |
| `ro_stage_pex_wstv0p46` | 4 | 6 | 1716.06 Ω | 4.7318 fF | 0.00342 fF |
| `ro_stage_pex_wstv0p48` | 4 | 6 | 1717.84 Ω | 4.7378 fF | 0.00356 fF |
| `ro_buf_pex` | 2 | 4 | 1261.24 Ω | 2.4937 fF | 0.0 fF |

Produced by `klt 0.4.0` / KLayout 0.30.12 (each report's own
`provenance.klt_version` is the authoritative per-file record --
`layout/pdk.json`'s `klt_version_pin` still reads `0.3.0+gc6dbf66c53c6`,
which is what produced the *composed-cell* evidence under
`layout/<cell>/`, and is deliberately left alone rather than retro-fitted
to a build that did not produce it).

The device count and net count of every cell match its own
`layout/<cell>/extract.json` exactly -- `--parasitics` adds R/C elements, it
does not re-recognize devices.

## The sampler library

`pex-sampler.json` -> `sampler_dff_pex.spice` extracts the three leaf shapes
`layout/sampler_dff/` physically places, which are exactly what
`design/sampler_core.spice`'s flat 22-device `.subckt sampler_dff` reduces
to (3 x inverter + 4 x transmission gate + 2 x NAND2 = 22 devices):

| Cell | From | Devices | Nets | Total series R | Total C to substrate | Net-to-net coupling C |
|---|---|---|---|---|---|---|
| `sampler_inv_pex` | `layout/ro_buf/` | 2 | 4 | 1261.24 Ω | 2.4937 fF | 0.0 fF |
| `sampler_tg_pex` | `layout/sampler_tg/` | 2 | 6 | 1262.17 Ω | 2.7292 fF | 0.0 fF |
| `sampler_nand2_pex` | `layout/sampler_nand2/` | 4 | 6 | 1599.23 Ω | 4.1288 fF | 0.01598 fF |

Produced by `klt 0.3.0+gc6dbf66c53c6` (each report's own
`provenance.klt_version` reads `0.3.0`) — which is `layout/pdk.json`'s
`klt_version_pin`, i.e. the build that produced the composed-cell evidence
under `layout/<cell>/`, unlike the nine cells above (`klt 0.4.0`). Two
consequences worth recording:

- **The extractor reproduced across that version gap exactly.**
  `sampler_inv_pex` is the *same GDS* as `ro_buf_pex` above, extracted by a
  different `klt` build, and its totals agree to every digit the table
  carries (1261.24 Ω / 2.4937 fF). The install churn
  `layout/pdk.json`'s comment block documents does not move these numbers.
- **Which is why the inverter is here under a second name.** The script
  writes `raw/<name>.pex.spice` and `reports/<name>.extract.json` into this
  one shared directory, so reusing `ro_buf_pex` would have made this
  descriptor's run overwrite artifacts `pex.json --check` compares against.
  Two names, two artifact sets, two libraries each independently
  `--check`-able:

```bash
python3 layout/bin/pex-netlist.py layout/pex/pex-sampler.json --check
```

**A deck includes one library or the other, never both** — they each define
the inverter's parasitics, under different subcircuit names, from the
identical GDS.

Both sampler leaves' `ports` come from each cell's own committed
micro-reference (`layout/sampler_tg/sampler_tg.source.spice`,
`layout/sampler_nand2/sampler_nand2.source.spice`) rather than from a
`design/*.spice` subckt line, because `design/xschem/sampler_dff.sch` is
flat and has no sub-schematic symbol for either shape — the same reason
those two cells' own `klt lvs` runs reference a micro-reference. The
micro-references are byte-for-byte reproductions of the design's own device
lines for one representative instance, so the port order still is the
design's.

`sim/post-layout-sampler-dff/`'s two decks rebuild `sampler_dff` from these
three cells with **ideal inter-cell wires**, and both deck headers say so.
`layout/sampler_dff/`'s own assembly GDS is *not* extracted here: its
`m`/`mb` data-path nets are still unrouted and its `klt lvs` therefore does
not match yet (15/22 devices, 7/14 nets as of PR #87's `sampler_nand2`
pin-swap fix — the deck headers, written before that fix landed, still cite
[#84](https://github.com/2AMLogic/sky130-trng/issues/84) as a second
reason), so a flat extraction of it would be an extraction of an
incomplete circuit. When `m`/`mb` close, the sampler's equivalent of
`layout/pex-ring/` becomes possible and these numbers become the intra-cell
control for it.

## What the parasitic model contains

`klt extract --parasitics` writes its own model description into the head of
every netlist it emits (see any file under `raw/`); the summary that matters
for reading a `sim/post-layout-ro-ring5/` record:

- **Resistance**: a *single lumped* series resistance per net, distributed
  as a **star** across that net's device terminals -- not a per-segment
  distributed RC ladder (that needs `--distributed-rc` plus naming the net
  as `--critical-net`, neither of which this library uses). Every terminal
  therefore sees the net's *whole* resistance to the hub node rather than
  the fraction of it a real distributed line would present. **This is the
  conservative direction**: the star over-states the resistance seen by a
  terminal, so a post-layout slowdown measured against it is an upper bound
  on the slowdown a distributed model would give, not a best estimate. That
  matters, because sky130's `li1` local interconnect -- the layer every
  intra-gate net in these cells is routed on (`layout/README.md` §
  "Floorplan decisions") -- is genuinely resistive, and the resistance is
  what dominates these numbers: 1.7-2.0 kΩ per cell against 4.7-6.3 fF.
- **Capacitance**: net-to-ground (substrate) for each net's own
  area/perimeter, plus net-to-net capacitance for **vertical overlap**
  (crossover) only. Lateral, same-layer sidewall coupling is modelled *only*
  for a pair naming a declared `--critical-net`, and this library declares
  none -- so the `0.003-0.016 fF` coupling column above is crossover
  coupling alone and is a floor, not a total.
- **Inductance**: none (`total_inductance_nh` is 0.0 on every cell).
- **Frequency**: quasi-static. One frequency-independent R and C per net; no
  skin effect, no transmission-line behaviour.

## What is NOT in here, and why it matters more than what is

**There is no inter-cell interconnect at all.** These are twelve *leaf
gates* (nine in `ro_ring5_pex.spice`, three in `sampler_dff_pex.spice`).
`ro_ring5`'s stage-to-stage wires, `ro_array_core`'s ring-to-buffer and
buffer-to-XOR wires, and every supply/ground distribution wire between cells
do not exist as layout yet (`layout/README.md` § "What's deferred", steps 2
and 3: `xor2`'s routing and the whole hierarchical assembly are open). So a
ring built from this library has **real intra-cell parasitics and ideal
inter-cell wires**.

That makes every post-layout number this library produces a **lower bound on
the parasitic penalty** at the ring level, in exactly the opposite direction
from the star-R model's own conservatism above. The two do not cancel and
should not be assumed to: a `sim/post-layout-ro-ring5/` record is evidence
about *intra-cell* parasitics specifically, and says so.

## What the tool does, and what is left over

`klt extract` writes device cards two different ways, and which one you get
decides how much work is left. **Without `--pdk`** it writes deck-native `M`
cards naming the extraction deck's own device classes
(`M$1 ... nfet L=2U W=0.42U`) — tool-neutral, and not runnable against
sky130's ngspice library, which has no `.model nfet` at all (its devices are
`.subckt sky130_fd_pr__nfet_01v8 d g s b`). **With `--pdk sky130A`** it
writes exactly the card this repo needs:

```
X$1 ... sky130_fd_pr__nfet_01v8 L=2 W=0.42 AS=0.1764 AD=0.1764 PS=1.68 PD=1.68
```

— the PDK's own device subcircuit, with *unitless* geometry, which is
precisely the `.option scale=1u` convention every `sim/` deck here already
runs under.

**This is worth recording as a correction, not just a setting.** An earlier
revision of `pex-netlist.py` hand-rolled both the device-card swap and a
unit-suffix strip, having only ever run the bare form — duplicated tool
capability, not a tool gap. Under this repo's friction protocol that
distinction matters: filing "extracted netlists are not simulatable" against
`2AMLogic/klayout-tools` would have been an inaccurate report of a flag not
being passed. No such issue was filed. (`layout/bin/compose-cell.py` sets
`PDK` in the environment but does not pass `--pdk`, which is why the bare
form is what this repo had seen until now; it does not need the PDK-bound
form for DRC/LVS.)

What the script does instead is **assert** that contract on every run rather
than assume it: every device card must be an `X` card, its model must be one
`pex.json` declares in `expect_device_models`, and every geometry value must
carry no unit suffix. A future `klt` that changed any of the three would
silently mis-scale or mis-bind every device in a deck running at
`scale=1u` — here it is a hard error. `layout/test_pex_netlist.py` covers
all three rejections.

Three things `--pdk` does not address, which the script does handle:

1. **Extractor-joined net names** (`mnt_g|vddr`,
   `mnab_y|mpa_y|mpb_y|y` — a two-pass-composed cell carries both a pin
   label and a net label on one physical net) are renamed to the
   design-level name, declared per cell in `pex.json`'s `net_aliases` so the
   choice is reviewable. The rename is checked to be injective per cell, so
   it can never merge two nets. The extractor's own `$`-indexed unnamed nets
   and instance names lose the `$` (an ngspice in-line comment character)
   and any `\` escape the same way.
2. **The substrate return node** — see the next section.
3. **A design-port-order wrapper** per cell, restoring the *design's* port
   order and burying the layout-only ports the two-pass composition had to
   promote (`ro_stage`'s `ny`/`py`). `x1 a y vddr vss ro_stage_pex_wstv0p42`
   and `x1 a y vddr vss ro_stage` are then the same line but for the
   subcircuit name, which is what makes a pre-vs-post comparison a one-token
   diff — see
   `sim/post-layout-ro-ring5/testbench/tb_post_layout_ro_ring5.spice`, which
   runs both in one deck for exactly that reason.

No R value, C value, device parameter or connection is changed by any of
that, and `raw/` holds the extractor's own output next to the rewrite so the
diff is inspectable.

## Why not `klt pex`

`klt pex` exists and does automate extract-and-re-simulate: it takes one
layout plus one or more `klt sim` testbench requests, and re-points the
testbench's DUT `.include` at the freshly-extracted netlist. That is the
right tool for *one* layout standing in for *one* schematic DUT.

It does not fit this campaign, for two reasons that are about this design's
shape rather than about the tool:

- **The DUT is a hierarchy, not a cell.** A post-layout `ro_ring5` is five
  instances of two different cells; the four-ring ladder is four of those at
  four different widths, plus buffers — nine separately-extracted cells
  composed into one library and instantiated hierarchically. `klt pex`'s
  one-layout/one-include contract has no place to put that.
- **The record convention is this repo's.** `sim/bin/corner-run.py` owns the
  PDK pin, the `<YYYYMMDD>-<HHMMSS>-<shortsha>` record-id scheme, the
  refuse-to-overwrite discipline and the `sim/<slug>/records/` layout that
  every prior campaign here is written against. Driving the post-layout runs
  through `klt sim` instead would have produced evidence in a second,
  incompatible shape.

So the split is: `klt` extracts (`klt extract --pdk --parasitics`, once per
cell), this repo composes and simulates. If `klt pex` ever grows a
multi-cell library mode, the composition half of `pex-netlist.py` is what
would become redundant.

## The substrate node (klayout-tools#1503)

Every net-to-substrate capacitor in every cell returns to a node named
`vsubs`, which the extractor ties to ground only through
`Rvsubs_dctie vsubs 0 1e+12` and declares neither as a `.SUBCKT` pin nor as
`.GLOBAL`. Simulated *flat* that is harmless. **Instantiated** -- the only
way to build a ring out of these cells -- it becomes a per-instance local
node no testbench can reach, so the entire ground-capacitance model hangs
off a node isolated from ground by 1 TΩ, silently, with no error and full
convergence. `layout/README.md` § "Scouting `--parasitics`" measured the
consequence (~1% impedance error at 1 GHz, ~17% at 10 GHz) and filed it
generically as
[klayout-tools#1503](https://github.com/2AMLogic/klayout-tools/issues/1503).

This library takes the `.GLOBAL vsubs` workaround that issue's write-up
named: the generated file declares `.global vsubs` once, at the top, so
`vsubs` is one node across the whole deck and a testbench can tie it. **A
deck including this library must tie it explicitly**, and every `sim/`
record minted from the library states which tie it used, because the choice
is measurable:

- `sim/post-layout-ro-ring5/testbench/tb_post_layout_ro_ring5.spice` ties it
  hard to 0 (the physically-motivated choice -- each composed cell carries
  its own psub guard ring tied to `vss`).
- `sim/post-layout-ro-ring5/testbench/tb_post_layout_substrate_float.spice`
  deliberately does **not** tie it, making the shared substrate an
  inter-ring coupling path, as the pessimistic bound of the same question.

Note that the *device body* terminals are not affected either way: the
extractor binds each transistor's bulk to its own well/tap net (`vddr` for
the PMOS, `vss` for the NMOS), not to `vsubs`, so the substrate node's
potential does not bias any device. It is a capacitive return node only.
