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
  xschem/          schematic + symbol sources (xschem's own text format)
  netlist.py       deterministic SPICE export driver, with a staleness guard
  pdk.json         which sky130 install to resolve, and the open_pdks pin
  *.spice          GENERATED netlists -- committed output of netlist.py
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
python3 design/netlist.py --check    # fail if a committed netlist is stale
python3 design/netlist.py --lint     # brace guard only; no xschem, no PDK
python3 design/netlist.py --pdk      # show the resolved PDK + open_pdks pin
```

`--check` is what makes a committed netlist evidence rather than a snapshot
someone forgot to refresh: it re-exports into a temp directory and exits
non-zero if the result differs from what is committed. Run it after any
schematic edit; commit the regenerated `.spice` files in the same change.

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
path is hardcoded. It also rewrites absolute paths out of the netlist header
and re-wraps SPICE continuation lines at a width it owns, so the output is
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
| Starve width `wstv` | 0.42–0.48 µm, four 0.02 µm steps | **measured (realized ratio), placeholder (decorrelation)** | The REALIZED frequency ratio across the ladder is measured on the assembled array (`sim/ro-array-core-combining/`, `skew_span` 1.12–1.19×, well clear of small rationals). What decorrelates two *sky130* rings — the coupling a real layout would have — is **still not measured**: the array as drawn has no shared supply impedance or substrate model, so a netlist-level check can only confirm the absence of a path the netlist does not contain. Needs extracted parasitics (DR-0003 §8) |
| Per-stage gain | −14.3 nominal, −11.8 worst | **measured** | `sim/ro-stage-small-signal-gain/`, three headline points. ~12× the Barkhausen minimum at any stage count in play; retires DR-0001's gain risk |
| Ring swing (`ro_ring5`, buffered output) | 0.999–1.033 × Vdd p-p | **measured** | `sim/ro-ring5-swing-and-current/`, 12 PVT points, under this cell's own output-buffer load. The internal ring node itself swings less (0.78–0.96 × Vdd), but the BUFFERED node — what the XOR tree and liveness taps see — reaches the rails at every point measured |
| Ring stage count | 5 | **measured, chosen** | 12–48× better `Q_ring` than 11 stages at the same points (DR-0002 §4); own-count swing re-measured and confirmed above (this table's previous row cited it as an open objection — it is now retired). `ro_ring11` remains in `design/xschem/` as a standalone characterization cell, no longer part of this hierarchy |
| Array size `N` | 4 | **measured, chosen** | Pinned between an entropy lower bound (`N >= 4` at `T_s` = 20 µs) and a combining-gate upper bound (`N <= 6`, measured at the array's own fastest corner) that do **not** bind at the same PVT point — DR-0003 §1–3. `N = 4` is the largest power of two clearing the combining bound with margin |
| Raw-rate operating point | `T_s` = 20 µs, 50 kHz clock, 50 kbps | **measured, moved** | DR-0003 §2: the combining-gate bandwidth ceiling puts a **hard architectural ceiling of ~78 kbps on the raw rate at any array size** — nearly two orders of magnitude below this file's draft `> 1 Mbps` row, which is retired as unreachable rather than merely expensive |
| Entropy-binding corner | `ss` / −40 °C / 1.62 V | **measured** | Full 27-point grid, `sim/ro-array-sizing/`. Cold — the direction gf180-trng's DR-0012 guessed and its DR-0015 later reversed. Measured here, inherited from neither |
| XOR combining tree contribution | `w_90` = 122–241 ps (gate bandwidth); 0.56–0.68 edge retention at `N = 4` | **measured** | `sim/xor-combining-bandwidth/` (single-gate pulse-width sweep, the figure that sizes `N`) and `sim/ro-array-core-combining/` (assembled-array edge retention and combining-node DC bias, 0.31–0.53 × Vdd, no gross systematic offset). DR-0003 §5–6 |
| Array active power | 81.0–431.6 µW measured across the PVT grid run | **measured** | `sim/ro-array-core-combining/`. Worst-measured 431.6 µW clears the top-level README's `< 500 µW active` row with 13.7% margin |
| Array area | ~0.0026–0.0088 mm² (ROM estimate, no layout) | **estimated** | Device-count-based estimate (DR-0003 §7): comfortably inside the `< 0.05 mm²` budget (~5–18%), but not a layout measurement — `layout/` remains empty |
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
  downstream is a behavioural model plus RTL. None of it exists in this repo
  yet, and drawing it as SPICE subcircuits would fabricate netlists for
  circuits nobody has designed.
- **Layout and DRC/LVS.** `layout/` is still empty; that is a follow-on
  increment. (`sim/` is no longer empty — see `sim/README.md`.)
