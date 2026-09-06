# design

Schematic sources for the sky130-trng entropy source, and the SPICE netlists
derived from them.

These are design sources, not evidence. Most of the geometry here is still
a **provisional placeholder** ported from
[gf180-trng](https://github.com/2AMLogic/gf180-trng)'s topology and
re-expressed on sky130's 1.8 V core devices — but it is no longer *all* of
it. Issue #10's characterization campaign
([`spec/decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md`](../spec/decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md),
status **Proposed**) measured this design's own delay cell and rings across
the sky130 PVT grid, and issue #13's array rebuild
([`spec/decision-records/DR-0003-sky130-trng-operating-point.md`](../spec/decision-records/DR-0003-sky130-trng-operating-point.md),
status **Proposed**) then measured the array's own combining-gate bandwidth
and redrew `ro_array_core.sch` at the resulting operating point. See
[Provisional, not sized](#provisional-not-sized) below for which rows moved
and which did not.

**The headline result the rest of this file has to be read against**: the
array is now drawn at `N = 4` five-stage rings, not the `N = 2` x 11-stage
placeholder it used to carry. `N` is pinned between two independently
measured bounds that do **not** bind at the same corner — an entropy lower
bound (`N >= 4` at `T_s` = 20 µs, DR-0002's sizing law re-evaluated against
the buffer-loaded ring period) and a combining-gate upper bound (`N <= 6`,
measured at the array's own fastest corner, `ff`/−40 °C/1.98 V) — and the
second bound is a **hardware ceiling on the raw rate that no array size can
get past**: DR-0003 measures it at ~78 kbps, roughly two orders of
magnitude below this file's draft `> 1 Mbps` row. That row is retired as
architecturally unreachable, not merely expensive; the operating point drawn
here is `T_s` = 20 µs / 50 kHz sample clock / 50 kbps raw rate.

## What is here

```
design/
  xschem/              schematic + symbol sources (xschem's own text format)
  netlist.py           deterministic SPICE export driver, with a staleness + ERC guard
  _pdk_search.py       shared PDK-search walk, used by netlist.py and sim/bin/corner-run.py (issue #25)
  test_netlist_erc.py  regression fixture for netlist.py's ERC wiring (issue #16)
  test_pdk_search.py   unit test for _pdk_search.py's fallback order (issue #25)
  pdk.json             which sky130 install to resolve, and the open_pdks pin
  *.spice              GENERATED netlists -- committed output of netlist.py
```

### Cell hierarchy

```
trng_top                   top-level assembly; stops at the raw tap
  sampler_core             the sampler, wired to the source
    ro_array_core          the entropy source
      ro_ring5   (x4)      one starved ring oscillator, own enable + own supply
        ro_nand2           starved NAND2 -- the ring's enable/stop stage
        ro_stage   (x4)    starved inverter delay cell
      ro_buf     (x4)      per-ring output buffer (unstarved inverter)
      xor2       (x3)      static CMOS combiner, balanced depth-2 tree -> xo
    sampler_dff  (x6)      TG master-slave D flip-flop, async active-low reset
                           raw_bit, raw_valid, ring_bit1..ring_bit4
```

`ro_ring5` is instantiated by the hierarchy as of issue #13's rebuild
(DR-0003); it was previously a standalone characterization vehicle only.
`ro_ring11` (the 11-stage ring the array used to instantiate) remains in
`design/xschem/` as a standalone cell — DR-0002's jitter-characterization
testbenches under `sim/` still reference it directly — but is no longer
part of the `ro_array_core` hierarchy.

Every device instance is `sky130_fd_pr__nfet_01v8` or `__pfet_01v8` — the
1.8 V core pair, per
[`spec/decision-records/DR-0001-sky130-operating-envelope.md`](../spec/decision-records/DR-0001-sky130-operating-envelope.md)
(status **Proposed**) and `spec/porting-plan.md` §2.1. sky130 has no matched
3.3 V core N/P pair, so gf180-trng's `nfet_03v3`/`pfet_03v3` devices have no
like-for-like counterpart here.

### Port fidelity

`design/xschem/` **started** as a connectivity-identical port of
gf180-trng's own `design/xschem/` — same cells, same nets, same subcircuit
port order, cell for cell, with only the device flavour, the device
geometry, and every prose text block changed (gf180-trng's schematics cite
gf180mcu measurements in their headers, and those citations are not
transferable claims, so each block was rewritten to say what is actually
known here). Issue #13's array rebuild (DR-0003) then moved
`ro_array_core.sch`, `sampler_core.sch` and `trng_top.sch` off that
one-for-one instance count: gf180-trng's own array is `N = 2`, this
repository's is `N = 4`, sized independently from measured sky130 evidence
rather than inherited. The TOPOLOGY still ports — independent rings on
separate supplies, non-integer frequency skew, one XOR-combined node ahead
of one sampler — the instance count no longer does.

### Pins that leave the block

| Pin | Direction | Meaning |
|---|---|---|
| `en1`..`en4` | in | per-ring enable; `en = 0` stops that ring in a static state |
| `vddr1`..`vddr4` | supply | per-ring supply. Separate routing is an independence requirement, and doubles as the per-ring liveness observation point |
| `vdd`, `vss` | supply | block supply for the combiner, the ring buffers and the samplers |
| `clk` | in | the **fixed external** sample clock, 50 kHz per DR-0003 — deliberately not divided down from either ring |
| `rst_n` | in | asynchronous, active-low reset |
| `raw_bit` | out | the raw tap: one digitized sample per `clk` edge |
| `raw_valid` | out | high one `clk` edge after `rst_n` releases, and stays high |
| `ring_bit1`..`ring_bit4` | out | per-ring digitized samples for a liveness monitor; block-internal, not read off-die |

The raw tap sits at the **sampler output**, after digitization — not at the
array's internal combining node `xo`, which never becomes a pin.

## Regenerating the netlists

```bash
python3 design/netlist.py            # (re-)export every top cell
python3 design/netlist.py --check    # fail if a committed netlist is stale, or fails ERC
python3 design/netlist.py --lint     # brace guard only; no xschem, no PDK
python3 design/netlist.py --pdk      # show the resolved PDK + open_pdks pin
python3 design/test_netlist_erc.py   # regression fixture for the --check ERC wiring itself
python3 design/test_pdk_search.py    # unit test for the shared PDK-search fallback order
```

`--check` verifies two independent things, both required for exit `0`:

- **Staleness** — what makes a committed netlist evidence rather than a
  snapshot someone forgot to refresh: it re-exports into a temp directory
  and exits non-zero if the result differs from what is committed.
- **Connectivity** — xschem's own ERC (electrical rule check, `xschem
  netlist -erc`) finds no undriven node, open net, or shorted pin anywhere
  in each top cell's instantiated hierarchy. A schematic-level wiring
  defect (e.g. a `lab_pin` placed at the wrong coordinate relative to the
  net it is meant to tag) can produce a netlist that is internally
  self-consistent — a "before" and "after" regeneration of the same broken
  schematic agree on the same wrong result — so the staleness diff alone
  cannot catch it; ERC does (issue #16). A connectivity failure prints with
  an `ERC` prefix and a distinct exit code from a staleness failure's
  `STALE` prefix, so CI output tells the two apart. ERC only runs under
  `--check`; the plain write path (`python3 design/netlist.py`) does not
  run it, so an intentionally mid-edit schematic can still be exported
  while iterating. `design/test_netlist_erc.py` is the regression fixture:
  it confirms a deliberately-broken schematic (a `lab_pin` moved off its
  net) is actually caught, and that the current `TOP_CELLS` still pass
  cleanly.

Run `--check` after any schematic edit; commit the regenerated `.spice`
files in the same change.

`--lint` is the guard that can run without a PDK. Every schematic carries a
`T {...}` free-text header; a literal `{` or `}` inside that block — even a
balanced pair — makes xschem's own parser miscount and silently drop parts of
the exported netlist, with no error from xschem. The lint scans the
schematics' raw text for that, so it catches the problem at authorship rather
than at the next export.

The netlists are a **library of subcircuits** meant to be `.include`d by a
testbench deck, not decks of their own: `netlist.py` strips the trailing
`.end` and restores the top cell's own `.subckt`/`.ends` wrapper, which
xschem comments out.

`netlist.py` resolves the PDK through `SKY130_PDK_PATH` → `PDK_ROOT`+`PDK` →
`design/pdk.local.json` → `design/pdk.json` → built-in search roots, so no
path is hardcoded. That walk-a-list-of-roots search is shared with
`sim/bin/corner-run.py` via `design/_pdk_search.py` (issue #25); each caller
supplies only its own validator predicate (`libs.tech/xschem` here,
`libs.tech/combined` for the ngspice harness) and its own config source.
`netlist.py` also rewrites absolute paths out of the netlist header and
re-wraps SPICE continuation lines at a width it owns, so the output is
byte-identical across machines and across xschem releases that differ only in
line wrapping.

## Provisional, not sized

Issue #10's campaign and issue #13's array rebuild have moved some of this
table off "no sky130 measurement exists". Each row now says which.
**Status** is one of: *measured* (this repo has a cited sky130 record for
it), *refuted* (measured, and the value drawn here does not survive the
measurement), or *placeholder* (still carried over from gf180-trng, or
otherwise unmeasured on sky130).

| Parameter | Value here | Status | What backs it, or what is still missing |
|---|---|---|---|
| Device length `L` | 0.15 µm | placeholder | sky130 minimum drawn length. Not a sized result; nothing in either campaign varied it |
| NMOS width | 0.42 µm | placeholder | sky130 minimum device width. Same |
| PMOS width | 0.84 µm | placeholder | 2:1 P:N ratio **carried over from gf180-trng**. Issue #10 measured the cell's trip point at 0.805–0.844 V against a 0.81–0.99 V mid-supply across the grid, i.e. the ratio is not grossly mismatched — but that is a by-product, not a P:N sizing sweep, and no sweep was run |
| Series-stack widths | 2× the device they replace | placeholder | rule of thumb from the source cell, not a sky130 stage-delay match measurement |
| Starve length `lstv` | 2 µm | placeholder | gf180-trng reached 2 µm by measuring an array power rollup against its own ratified power row. **No sky130 lstv sweep exists** — both campaigns measured jitter, swing and current at this fixed value, so this row is untouched |
| Starve width `wstv` | 0.42–0.48 µm, four 0.02 µm steps | **measured (realized ratio), placeholder (decorrelation)** | The REALIZED frequency ratio across the ladder is measured on the assembled array (`sim/ro-array-core-combining/`, `skew_span` 1.12–1.19×, well clear of small rationals). What decorrelates two *sky130* rings — the coupling a real layout would have — is **still not measured**: the array as drawn has no shared supply impedance or substrate model, so a netlist-level check can only confirm the absence of a path the netlist does not contain. Extracted parasitics now exist for the leaf cells, and DR-0005 bounds ONE coupling path (the shared substrate return node) at ≤ 0.033% of the ring period — an upper bound, unresolved above the solver's own numerical floor. The ladder itself survives the parasitics (span 1.11–1.21×). §8's first-named mechanism, shared supply impedance, still has no layout to be measured on, so this row stays **placeholder** for decorrelation (DR-0003 §8, DR-0005 §3–4) |
| Per-stage gain | −14.3 nominal, −11.8 worst | **measured** | `sim/ro-stage-small-signal-gain/`, three headline points. ~12× the Barkhausen minimum at any stage count in play; retires DR-0001's gain risk |
| Ring swing (`ro_ring5`, buffered output) | 0.999–1.033 × Vdd p-p | **measured** | `sim/ro-ring5-swing-and-current/`, 12 PVT points, under this cell's own output-buffer load. The internal ring node itself swings less (0.78–0.96 × Vdd), but the BUFFERED node — what the XOR tree and liveness taps see — reaches the rails at every point measured |
| Ring stage count | 5 | **measured, chosen** | 12–48× better `Q_ring` than 11 stages at the same points (DR-0002 §4); own-count swing re-measured and confirmed above (this table's previous row cited it as an open objection — it is now retired). `ro_ring11` remains in `design/xschem/` as a standalone characterization cell, no longer part of this hierarchy |
| Array size `N` | 4 | **measured, chosen** | Pinned between an entropy lower bound (`N >= 4` at `T_s` = 20 µs) and a combining-gate upper bound (`N <= 6`, measured at the array's own fastest corner) that do **not** bind at the same PVT point — DR-0003 §1–3. `N = 4` is the largest power of two clearing the combining bound with margin |
| Raw-rate operating point | `T_s` = 20 µs, 50 kHz clock, 50 kbps | **measured, moved** | DR-0003 §2: the combining-gate bandwidth ceiling puts a **hard architectural ceiling of ~78 kbps on the raw rate at any array size** — nearly two orders of magnitude below this file's draft `> 1 Mbps` row, which is retired as unreachable rather than merely expensive |
| Entropy-binding corner | `ss` / −40 °C / 1.62 V | **measured** | Full 27-point grid, `sim/ro-array-sizing/`. Cold — the direction gf180-trng's DR-0012 guessed and its DR-0015 later reversed. Measured here, inherited from neither |
| XOR combining tree contribution | `w_90` = 122–241 ps (gate bandwidth); 0.56–0.68 edge retention at `N = 4` | **measured** | `sim/xor-combining-bandwidth/` (single-gate pulse-width sweep, the figure that sizes `N`) and `sim/ro-array-core-combining/` (assembled-array edge retention and combining-node DC bias, 0.31–0.53 × Vdd, no gross systematic offset). DR-0003 §5–6 |
| Array active power | 81.0–431.6 µW measured across the PVT grid run | **measured** | `sim/ro-array-core-combining/`. Worst-measured 431.6 µW clears the top-level README's `< 500 µW active` row with 13.7% margin |
| Array area | ~0.0026–0.0088 mm² (ROM estimate); every `ro_array_core` leaf cell now drawn, summing to 4 × 377 + 4 × 22.2 + 3 × 421.5 µm² = 0.00286 mm² | **estimated (array), measured (leaf cells only)** | Device-count-based estimate (DR-0003 §7): comfortably inside the `< 0.05 mm²` budget (~5–18%). Not yet an array measurement, but every cell it instantiates is now drawn: `ro_ring5` 41.125 × 9.17 µm (`layout/ro_ring5/README.md`), `ro_buf` 4.175 × 5.31 µm, `xor2` 23.97 × 17.585 µm (`klt stats` on each committed GDS). The 0.00286 mm² sum is leaf-cell bounding boxes only — it is a **floor**, not a floorplan: no inter-ring channel, no supply distribution, no sampler and no top-level PDN are drawn, and it assumes the eleven cell instances (4 rings + 4 buffers + 3 XORs) pack with zero waste between their bounding boxes |
| Idle current (per ring) | 0.6 nA (cold) – 255 nA (`ff`/125 °C) | **measured (per-ring), no target yet** | `sim/ro-ring5-swing-and-current/`. The top-level README's own idle-current target is still unset pending `spec/porting-plan.md` §2.5's leakage survey, so this is a reported number, not a pass/fail against a row that does not exist yet |
| Load cap `cld` | 0.5 fF | placeholder | an estimate of local interconnect load, not an extracted parasitic, and sky130's metal stack differs from gf180mcu's |

### Why the schematic reads `N = 4`, and why the raw-rate row moved to 50 kbps

`N` is not a parameter in `ro_array_core.sch`; it is a topology, and issue
#13 redrew it. `N = 4` is not the entropy law's own preferred value in
isolation — DR-0002 sized `N = 53` against the draft `> 1 Mbps` row — it is
the largest power-of-two array size that clears a **second, independent
constraint** DR-0002's campaign did not measure: the XOR combining gate's
own bandwidth. That second bound does not move with the sample rate, so it
sets a hard ceiling (~78 kbps) on the raw rate itself, not just on `N`.
`spec/decision-records/DR-0003-sky130-trng-operating-point.md`
(status **Proposed**) is the full derivation: the two bounds, where they
cross, why 50 kbps (not the ~78 kbps ceiling itself) was chosen for margin,
and the stage-count, area, current and combining-tree evidence that came
with drawing the array at last.

`spec/porting-plan.md` §2.6 predicted the shape of what both campaigns
found: gf180-trng's own rate × entropy × power × area operating point has
not converged, and sky130's version of the same tension needed its own
sizing pass. It did, and it resolved further downward than either campaign
alone implied — DR-0002's entropy law by itself still permits high rates at
large `N`; the combining gate does not. Whether 50 kbps should ratify as
this repository's ratified rate row, or whether the combining gate itself
should be redesigned to raise the ceiling, is the operator/spec decision
DR-0003 surfaces and does not resolve on its own authority.

## Deliberately not here

- **The metastability-hybrid tap** (`meta_arb`, `meta_inv`, `meta_nand2`,
  `ro_array_core_meta`, `ro_array_sanity`, `ro_meta_tap` in gf180-trng).
  `spec/porting-plan.md` §1.2 scopes it as a stretch/secondary item, not part
  of the core array, so it is out of scope for this port.
- **The digital section** — conditioner, health tests, register interface.
  The analog/digital verification boundary is drawn at the raw tap:
  everything up to and including `raw_bit` is transistor-level, everything
  downstream is a behavioural model plus RTL, and drawing it as SPICE
  subcircuits would fabricate netlists for circuits nobody has designed.
  That section now exists — as of
  [`spec/decision-records/DR-0004-sky130-digital-section-architecture.md`](../spec/decision-records/DR-0004-sky130-digital-section-architecture.md)
  (status **Proposed**) it lives in [`digital/`](../digital/README.md), not
  here, and none of it is or will be a `design/*.spice` netlist. `raw_bit`
  and `raw_valid` are the interface between the two directories.
- **Layout and DRC/LVS.** `layout/` holds **fifteen composed, DRC-clean
  and LVS-clean cells** — every leaf cell `ro_array_core` instantiates
  (rings, buffers, the combining-tree XOR; see
  [`layout/xor2/`](../layout/xor2/README.md)) **plus `ro_array_core`
  itself**, which is now a `--check`-reproducible six-stage `cell.json`
  recipe in
  [`layout/ro_array_core/`](../layout/ro_array_core/README.md) (132/132
  devices, 96/96 nets, 0 DRC violations, with `ring1..4`'s and `xa1..3`'s
  own `vss` taps drawn). That supersedes — without correcting — the PoC
  directory the increments below narrate.
  A prior increment first reached that verdict:
  [`layout/ro_array_core-placement-poc/`](../layout/ro_array_core-placement-poc/README.md)'s
  "Increment 8" section routes the last open net, the `vdd` supply, as
  seven `"metal2"`-role (met1) promotion stubs plus a six-leg `"metal3"`
  (met2) bus, merging the seven previously-separate per-instance `vdd`
  nets into one 38-device net. The composed block is **`klt drc` clean
  (0 violations)**, extracts to **132 devices / 96 nets**, and **`klt lvs`
  reports `match`: 132/132 devices, 96/96 nets** against
  `design/ro_array_core.spice`'s own `.subckt ro_array_core` — the whole
  entropy source (four differently-sized rings, four buffers, the
  three-XOR combining tree), not a leaf cell. Two committed negative
  controls (`lvs-negative-controls.py`) show that verdict is
  discriminating rather than vacuous: resizing ring 4's starve devices to
  ring 1's `wstv`, and crossing `xa1`/`xa2`'s inputs, each turn the same
  comparison into `mismatch`. The generated reference originally needed
  one thing `layout/bin/compose-cell.py`'s *plain* `lvs.dependencies`
  mechanism could not express — four differently parameterised copies of
  the *same* `ro_ring5` subckt — built at the time by a small one-off
  script (`array-reference.py`) that hand-rolled the rename/parametrize
  loop. **A follow-up increment folds that back into `compose-cell.py`**
  as a generic, unit-tested `lvs.dependency_variants` mechanism (see
  `layout/README.md`), and `array-reference.py` now calls it instead,
  verified to reproduce the identical reference body and LVS/negative-control
  verdicts. **The promotion that follow-up left open is done**:
  `layout/ro_array_core/cell.json` is the `--check`-reproducible recipe, and
  its `lvs` block is `lvs.dependency_variants`'s first real use. Array-level
  parasitic extraction and post-layout PVT remain follow-up work (#27).
  A prior increment wired the XOR combining tree's inputs:
  that directory's
  "Increment 7" section routes `t2` (`xa2.y` → `xa3.b`) via a `"metal3"`
  (met2) bridge fed by two short `"metal2"`-role (met1) promotion stubs
  added at the array-composition level, over the fence of already-routed
  met1 backbones the prior increment found blocking it — `klt drc` clean
  (0 violations) at every step, `klt extract` 132 devices (unchanged), 103
  nets (unchanged after the stubs) then 102 nets (after the bridge merges
  `xa2`'s `y` net with `xa3`'s `b` net, confirmed by net diff, nothing
  else). The prior increment (Increment 6) predicted the met1 promotion
  would need a change inside `xor2`'s own leaf cell, since met3's via-drop
  is single-hop and cannot reach a bare li1 pin — **this increment shows
  that's unnecessary**: an already-composed block can gain extra
  hand-declared ports at any layer, at any point an earlier increment's own
  routing already proved clear, one level up from the leaf cell rather than
  inside it. `t1` (`xa1.y` → `xa3.a`, 66.97 µm on met1, Increment 6) and
  `t2` together complete the tree's inputs; `xo` (`xa3.y`) remains exposed
  as a bare top-level pin. Increment 6 also recorded a finding that matters
  beyond this block: **`klt drc` clean is
  not connectivity evidence**: a first `t1` probe reported `unrouted_nets:
  []` and 0 violations while electrically shorting `xa1`'s internal `bn`
  node to its own output, because `klt gen-compose` models a placed block as
  an opaque bbox and cannot see its interior metal (filed generically
  against `2AMLogic/klayout-tools` as `klayout-tools#1527` per `CLAUDE.md`'s
  friction protocol; probe artifacts not committed). `xor2`'s `y` has exactly four legal met1
  escape windows, measured by a committed scan script rather than
  approximated. Before that, an increment
  routed `buf1`-`buf4`'s `vss` taps together as one
  bundle net on met1 (`klt drc` clean, 0 violations), but `klt extract`
  reports the same 132 devices and 104 nets as before — the merged `vss`
  net's own device count (122) is unchanged, because `klt extract`'s sky130
  deck already ties every un-isolated NMOS body to one global substrate
  identity via `connect_global`, so `vss` connectivity across the array's
  instances did not need this routing to reach a `klt lvs` match (the same
  mechanism `spec/decision-records/DR-0005-*.md` finding 3 documented on one
  ring's own parasitics, now confirmed at the array level). The bus is still
  real, DRC-clean, load-bearing metal a fabricated die needs — the substrate
  alone has no modelled resistance — just not what was blocking LVS. `vdd`
  was the opposite and stayed open for three increments: seven separate
  nets (one per `buf`/`xor2` instance), with a first buffer-only bus
  attempt failing outright (every candidate leg crosses a neighbouring
  ring's own bounding box) and Increment 6's fence measurement showing no
  met1 corridor could work at all — **closed by Increment 8 above**, using
  exactly the met1-stub-then-met2-bus recipe Increment 7 proved out for
  `t2`. Before that, an
  increment routed `ro_array_core`'s buffer→XOR `b` leg: `ro2` (`buf2.y`) into `xa1.b` and
  `ro4` (`buf4.y`) into `xa2.b` on met1, resolving that increment's own open
  finding (`klt drc` clean; `klt extract` 132 devices, 104 nets, down from
  106). Before that, the buffer→XOR `a` leg: `ro1` (`buf1.y`) into `xa1.a`
  and `ro3` (`buf3.y`) into `xa2.a` on met1 — the first routing this
  hierarchy level drew between the ring/buffer row and the XOR
  combining-tree row, with an escape-margin fix for the source pin's own
  tiny edge margin. Before that, `ro_array_core`'s forward ring→buffer
  signal chain was routed: the same eleven-sibling, 216.2 x 31.755 µm
  floorplan exposes `en1..en4`/the four `vddrN` domains/`ro1..ro4` as
  top-level pins (no routing needed — each is already a single node inside
  its own block) plus really routes `rn1..rn4` (`ro_ring5.ro` → `ro_buf.a`)
  on met1. Still open after Increment 8, none of it LVS-blocking:
  `ring1..4`'s and `xa1..3`'s own `vss` taps are still not drawn (a
  fabricated die wants the explicit strap; `klt extract`'s substrate model
  already merges the net, per the finding above), the PoC directory is not
  yet a `--check`-reproducible `layout/ro_array_core/` cell recipe, and no
  array-level parasitic extraction or post-layout PVT run exists yet — so
  the `wstv` inter-ring decorrelation question DR-0003 §8 leaves open is
  still open. `sampler_core`/
  `sampler_dff` remain untouched. The thirteen before it are nine leaf gates plus all
  four `ro_ring5` rings ([`layout/ro_ring5/`](../layout/ro_ring5/README.md)
  and `ro_ring5_wstv0p{44,46,48}/`), each `klt drc` clean (0 violations) and
  `klt lvs` **matching** `.subckt ro_ring5` at that ring's own `wstv`
  (22/22 devices, 19/19 nets, 0 errors). Those are the first *multi-gate*
  cells in the repository to reach that bar: five leaf gates placed via
  `klt gen-compose`'s `blocks[].cell` shape, the four forward inter-stage
  nets plus the `ro` feedback routed on met1, and `vddr`/`vss` bussed on
  met2 — four `gen-compose` stages across three physical routing planes.
  See [`layout/ro_ring5/README.md`](../layout/ro_ring5/README.md), which also
  records the two claims it corrects in the previous increment's
  `ro_ring5-connectivity-poc` (its `n1`-`n4` were a single shorted node, and
  its "unexplained device-internal DRC violations" were its own routes).
  The nine leaf cells are
  [`layout/ro_buf/`](../layout/ro_buf/README.md), this
  file's own `ro_buf` inverter,
  [`layout/ro_stage/`](../layout/ro_stage/README.md) and its three sibling
  `wstv` variants (`ro_stage_wstv0p{44,46,48}/`), the array's per-stage
  starved delay cell at all four ring widths, and
  [`layout/ro_nand2/`](../layout/ro_nand2/README.md) and its three sibling
  `wstv` variants (`ro_nand2_wstv0p{44,46,48}/`), each `ro_ring5`'s
  enable-gated first stage at all four ring widths — all built from `klt gen`
  primitives, placed and routed by `klt gen-compose`, `klt drc` clean (0
  violations against `klt`'s curated sky130 deck) and `klt lvs` **matching**
  their own `.subckt` in `design/ro_array_core.spice` (`ro_buf`: 2/2 devices,
  4/4 nets; `ro_stage`: 4/4 devices, 6/6 nets; `ro_nand2`: 6/6 devices, 8/8
  nets — each at all four `wstv`/`lstv=2` values, matching ring instances
  `xr1`-`xr4`), at this design's real `l_um=0.15` sizing. `ro_stage`'s and
  `ro_nand2`'s starve devices cross-couple their gates to the *opposite*
  rail, which needed a new two-pass composition technique (a second `klt
  gen-compose` call routing the crossing nets on a second metal level) to
  avoid a short — `ro_nand2`'s own parallel PMOS pull-up pair and series
  NMOS pull-down pair additionally needed that same technique generalized to
  a six-same-block-self-net final pass, and the three non-nominal `wstv`
  widths additionally needed the starve devices' own placement origin
  re-derived per width (a naive clone-and-reparametrize breaks DRC/LVS — see
  `layout/README.md`'s "Starve-width variants" section for the closed form)
  — see `layout/ro_stage/README.md` and `layout/ro_nand2/README.md` for the
  full derivations. All nine cells are reproducible from a committed
  descriptor, e.g.
  `python3 layout/bin/compose-cell.py layout/ro_nand2/cell.json` (add
  `--check` to verify without overwriting). Earlier increments established
  the per-device geometries (`layout/primitives/`) and the PMOS well-strap
  finding (`layout/well-strap-poc/`); the `klayout-tools` regression they
  recorded as a blocker
  ([#1491](https://github.com/2AMLogic/klayout-tools/issues/1491)) is fixed.
  Those nine cells are now also **extracted with parasitics and simulated**:
  [`layout/pex/`](../layout/pex/README.md) is a generated, `--check`-guarded
  post-layout netlist library (`klt extract --parasitics` over each
  committed GDS, rewritten for ngspice by `layout/bin/pex-netlist.py`), and
  `sim/post-layout-ro-ring5/` runs the five-stage ring from it across the
  PVT grid with the pre-layout netlist as a same-deck control — intra-cell
  parasitics cost **1.378×–1.479× in ring period**, raise ring-node swing
  1–4%, and lower per-ring supply current 2–6%
  (`spec/decision-records/DR-0005-*.md`).
  The four `ro_ring5` cells themselves are now **also** parasitic-extracted
  and simulated, this time as whole composed rings rather than leaf-cell
  compositions: [`layout/pex-ring/`](../layout/pex-ring/README.md) extracts
  each ring's own GDS directly (real inter-gate `n1`-`n4`/`ro` routing and
  `vddr`/`vss` rail busing included), and
  `sim/post-layout-ro-ring5-assembled/` re-runs the same period/swing/current
  measurement from it. Real inter-gate wiring costs the ring **1.5045×–1.6546×**
  more slowdown on top of intra-cell parasitics alone (period vs. pre-layout
  overall: **2.0819×–2.3666×**), and the `wstv` frequency ladder still
  survives. `xor2` has no post-layout record of its own: it is composed and
  verified but not extracted or simulated, since a PVT campaign is its own
  deliverable. Still open: no `ro_array_core` and no sampler as *assembled* layout, so
  there is still no *inter-ring* interconnect (supply distribution, XOR
  tree routing, buffer fan-in) to extract, and no whole-block post-layout
  PVT re-verification — every number above is one ring's own real
  interconnect with ideal wires to its neighbours. See `layout/README.md`
  for the full status and the follow-up issue (#27) it tracks. (`sim/` is no
  longer empty either — see `sim/README.md`.)
