# design

Schematic sources for the sky130-trng entropy source, and the SPICE netlists
derived from them.

**Nothing here has been simulated.** These are design sources, not evidence.
Every device size, the ring stage count, the array size and the inter-ring
frequency skew are **provisional placeholders** ported from
[gf180-trng](https://github.com/2AMLogic/gf180-trng)'s topology and
re-expressed on sky130's 1.8 V core devices. See
[Provisional, not sized](#provisional-not-sized) below.

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

None of the geometry below is a result. All of it is carried over from
gf180-trng's topology, re-expressed at sky130's minimum geometry, and is
expected to move:

| Parameter | Value here | Why it is provisional |
|---|---|---|
| Device length `L` | 0.15 µm | sky130 minimum drawn length |
| NMOS width | 0.42 µm | sky130 minimum device width |
| PMOS width | 0.84 µm | 2:1 P:N ratio **carried over from gf180-trng**, not re-derived against sky130's own mobility ratio |
| Series-stack widths | 2× the device they replace | rule of thumb from the source cell, not a sky130 stage-delay match measurement |
| Starve length `lstv` | 2 µm | gf180-trng reached 2 µm by measuring an array power rollup against its own ratified power row. No such measurement exists here |
| Starve width `wstv` | 0.42 µm / 0.46 µm | 0.42 µm is minimum width; the ~9.5 % skew fraction is gf180-trng's, and the skew that actually decorrelates two *sky130* rings is unmeasured |
| Ring stage count | 11 | gf180-trng chose 11 from measured starved-cell gain and measured ring swing on gf180mcu. Neither measurement has a sky130 counterpart |
| Array size `N` | 2 | gf180-trng's `N = 2` comes from a gf180mcu jitter measurement feeding an array sizing law. The **law** ports; the measured inputs do not |
| Load cap `cld` | 0.5 fF | an estimate of local interconnect load, not an extracted parasitic, and sky130's metal stack differs from gf180mcu's |

`spec/porting-plan.md` §2.2 is explicit that gf180-trng's sizing arithmetic is
computed entirely from gf180mcu-measured `sigma_1`/`T_0` figures, and that
none of those numbers port. What would replace the table above: sky130
transient-noise jitter-accumulation runs over `ro_stage`/`ro_ring5` across the
corner grid in §3.1, feeding the array sizing law at the entropy-binding
corner — and §2.4 notes that the entropy-binding corner is itself something
this repo owes a full-grid measurement for, rather than inheriting.

That work is separate, later scope.

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
- **Layout, DRC/LVS, and any simulation.** `layout/` and `sim/` are still
  empty; those are follow-on increments.
