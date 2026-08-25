# design

Schematic sources for the sky130-trng entropy source, and the SPICE netlists
derived from them.

These are design sources, not evidence. Most of the geometry here is still
a **provisional placeholder** ported from
[gf180-trng](https://github.com/2AMLogic/gf180-trng)'s topology and
re-expressed on sky130's 1.8 V core devices — but it is no longer *all* of
it. Issue #10's characterization campaign (`sim/`, and
[`spec/decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md`](../spec/decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md),
status **Proposed**) measured this design's own delay cell and rings across
the sky130 PVT grid. See [Provisional, not sized](#provisional-not-sized)
below for which rows moved and which did not.

**The headline result the rest of this file has to be read against**: the
array size `N = 2` drawn here is **refuted**, not merely unconfirmed. At the
measured entropy-binding corner (`ss`/−40 °C/1.62 V) and this repo's own
draft target rows (> 1 Mbps raw, `H₀` = 0.5), the ported sizing law asks for
`N` = 53 five-stage rings, or `N` ≥ 309 of the eleven-stage rings this
hierarchy actually instantiates. DR-0002 states the number, its ~2–4×
uncertainty band, and why the schematic was not simply redrawn at that `N`.

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
      ro_ring11  (x2)      one starved ring oscillator, own enable + own supply
        ro_nand2           starved NAND2 -- the ring's enable/stop stage
        ro_stage   (x10)   starved inverter delay cell
      ro_buf     (x2)      per-ring output buffer (unstarved inverter)
      xor2                 static CMOS combiner -> the xo node
    sampler_dff  (x4)      TG master-slave D flip-flop, async active-low reset
                           raw_bit, raw_valid, ring_bit1, ring_bit2

ro_ring5                   5-stage ring; not instantiated by the hierarchy.
                           The cheap transient-noise vehicle for the jitter
                           characterization that has to happen before any
                           stage count here is a result rather than a guess.
```

Every device instance is `sky130_fd_pr__nfet_01v8` or `__pfet_01v8` — the
1.8 V core pair, per
[`spec/decision-records/DR-0001-sky130-operating-envelope.md`](../spec/decision-records/DR-0001-sky130-operating-envelope.md)
(status **Proposed**) and `spec/porting-plan.md` §2.1. sky130 has no matched
3.3 V core N/P pair, so gf180-trng's `nfet_03v3`/`pfet_03v3` devices have no
like-for-like counterpart here.

### Port fidelity

The hierarchy is a **connectivity-identical** port of gf180-trng's
`design/xschem/`: same cells, same instance names, same nets, same subcircuit
port order, cell for cell. What changed is the device flavour, the device
geometry, and every prose text block — gf180-trng's schematics cite gf180mcu
measurements in their headers, and those citations are not transferable
claims, so each block was rewritten to say what is actually known here.

### Pins that leave the block

| Pin | Direction | Meaning |
|---|---|---|
| `en1`, `en2` | in | per-ring enable; `en = 0` stops that ring in a static state |
| `vddr1`, `vddr2` | supply | per-ring supply. Separate routing is an independence requirement, and doubles as the per-ring liveness observation point |
| `vdd`, `vss` | supply | block supply for the combiner, the ring buffers and the samplers |
| `clk` | in | the **fixed external** sample clock — deliberately not divided down from either ring |
| `rst_n` | in | asynchronous, active-low reset |
| `raw_bit` | out | the raw tap: one digitized sample per `clk` edge |
| `raw_valid` | out | high one `clk` edge after `rst_n` releases, and stays high |
| `ring_bit1`, `ring_bit2` | out | per-ring digitized samples for a liveness monitor; block-internal, not read off-die |

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

Issue #10's campaign moved some of this table off "no sky130 measurement
exists". Each row now says which. **Status** is one of: *measured* (this
repo has a cited sky130 record for it), *refuted* (measured, and the value
drawn here does not survive the measurement), or *placeholder* (still
carried over from gf180-trng with no sky130 measurement behind it).

| Parameter | Value here | Status | What backs it, or what is still missing |
|---|---|---|---|
| Device length `L` | 0.15 µm | placeholder | sky130 minimum drawn length. Not a sized result; nothing in the campaign varied it |
| NMOS width | 0.42 µm | placeholder | sky130 minimum device width. Same |
| PMOS width | 0.84 µm | placeholder | 2:1 P:N ratio **carried over from gf180-trng**. The campaign measured the cell's trip point at 0.805–0.844 V against a 0.81–0.99 V mid-supply across the grid, i.e. the ratio is not grossly mismatched — but that is a by-product, not a P:N sizing sweep, and no sweep was run |
| Series-stack widths | 2× the device they replace | placeholder | rule of thumb from the source cell, not a sky130 stage-delay match measurement |
| Starve length `lstv` | 2 µm | placeholder | gf180-trng reached 2 µm by measuring an array power rollup against its own ratified power row. **No sky130 power measurement exists** — the campaign measured jitter and swing, not supply current, so this row is untouched |
| Starve width `wstv` | 0.42 µm / 0.46 µm | placeholder | 0.42 µm is minimum width; the ~9.5 % skew fraction is gf180-trng's. The campaign ran a single `wstv` and measured no inter-ring correlation, so the skew that decorrelates two *sky130* rings is still unmeasured |
| Per-stage gain | −14.3 nominal, −11.8 worst | **measured** | `sim/ro-stage-small-signal-gain/`, three headline points. ~12× the Barkhausen minimum at any stage count in play; retires DR-0001's gain risk |
| Ring swing (`ro_ring11`) | 1.06 × Vdd p-p | **measured** | `sim/ro-ring-jitter-accumulation/`, 3 headline points. Rail-to-rail with overshoot at every point, including DR-0001's slow/hot/low-supply risk corner |
| Ring stage count | 11 | **refuted as a good choice**, not as a working one | 11 stages oscillates fine, but measures 12–48× *worse* in `Q` than 5 stages at the same points (DR-0002 §4). Not moved here because the 5-stage ring's own swing (0.81–1.00 × Vdd) and the sampler/skew consequences of a 2.7× faster ring are unevaluated |
| Array size `N` | 2 | **refuted** | At the measured entropy-binding corner, `N = 2` gives `Q_array` 26× below what the sizing law asks for at this repo's draft rate/entropy rows. Sized value: `N` = 53 (5-stage) / ≥ 309 (11-stage, as drawn). DR-0002 §5, and see below for why the schematic still reads 2 |
| Entropy-binding corner | `ss` / −40 °C / 1.62 V | **measured** | Full 27-point grid, `sim/ro-array-sizing/`. Cold — the direction gf180-trng's DR-0012 guessed and its DR-0015 later reversed. Measured here, inherited from neither |
| Load cap `cld` | 0.5 fF | placeholder | an estimate of local interconnect load, not an extracted parasitic, and sky130's metal stack differs from gf180mcu's |

### Why the schematic still reads `N = 2`

`N` is not a parameter in `ro_array_core.sch`; it is a topology. Going from
2 rings to 53 means 53 enables, 53 separately-routed supplies, a 53-input
XOR tree and a 26× larger sampler input load — a block redesign whose own
trades (area against the `< 0.05 mm²` row, XOR-tree depth, per-ring supply
routing) this campaign measured nothing about, driven by a number that
carries ~2–4× uncertainty and is derived against a **draft** raw-rate row.
DR-0002's "Alternatives considered" argues this at length. The placeholder
is superseded *as a claim* — the schematic's own text block now says so —
and the rebuild is filed as its own increment.

`spec/porting-plan.md` §2.6 predicted the shape of what the campaign found:
gf180-trng's own rate × entropy × power × area operating point has not
converged, and sky130's version of the same tension needs its own sizing
pass. It does. At 1 Mbps the entropy row wants tens to hundreds of rings; at
gf180-trng's own proposed 2 kbps it wants one. Choosing the point on that
curve is a spec decision, not a Builder one.

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
