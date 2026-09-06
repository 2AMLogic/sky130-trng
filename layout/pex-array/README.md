# layout/pex-array

The post-layout (parasitic-annotated) netlist library for the **whole
entropy source** -- `layout/pex/`'s and `layout/pex-ring/`'s sibling one more
hierarchy level up: four non-identical `ro_ring5` rings, four `ro_buf`
output buffers, and the three-`xor2` combining tree, all in ONE flat
extraction rather than nine leaf cells or four separate rings.

`ro_array_core_pex.spice` is a **generated** file:
`layout/bin/pex-netlist.py` -- the same, unmodified script `layout/pex/` and
`layout/pex-ring/` both use -- runs `klt extract --pdk sky130A --parasitics`
directly over
[`layout/ro_array_core-placement-poc/ro_array_core_signal9_poc.gds`](../ro_array_core-placement-poc/README.md)'s
own committed GDS: the same stream that PoC directory's own "Increment 8"
reports **`klt drc` clean (0 violations)** and **`klt lvs` matching**
`design/ro_array_core.spice`'s own `.subckt ro_array_core` (132/132 devices,
96/96 nets, with two committed negative controls confirming the match is
discriminating). Because that GDS carries the whole array's real inter-ring
wiring -- the ring-to-buffer signal chain, the buffer-to-XOR fan-in, the XOR
tree's own `t1`/`t2` routing, and the array-wide `vdd` bus for the four
buffers plus three `xor2` instances -- the resulting parasitic model
includes all of that for the first time; neither `layout/pex/` (nine
separately-extracted leaf cells, ideal wires between them) nor
`layout/pex-ring/` (one ring's own real interconnect, but ideal wires
*between* rings and the still-undrawn buffer/XOR tree) could.

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-array/pex.json --check   # verify
python3 layout/bin/pex-netlist.py layout/pex-array/pex.json           # regenerate
```

`--check` re-extracts the array from its committed GDS into a temporary
directory and fails on any byte-for-byte or verdict-field drift -- the same
contract `layout/pex/pex.json` and `layout/pex-ring/pex.json` offer.

## Sourcing the PoC's own GDS, not a `--check`-reproducible cell.json recipe

Deliberate, not an oversight. `layout/README.md`'s own "Still open" note
names folding `layout/ro_array_core-placement-poc/`'s nine `gen-compose`
stages into one `--check`-reproducible `layout/ro_array_core/cell.json`
recipe as separate, still-undone layout engineering (tracked by
[#27](https://github.com/2AMLogic/sky130-trng/issues/27)). Extraction does
not need that recipe to exist -- it needs a GDS whose DRC/LVS verdicts are
trustworthy, and the PoC's committed `signal9` GDS already carries both (see
above). A future recipe promotion is expected to reproduce that exact GDS
byte-for-byte and can swap this descriptor's `gds` path with no other change
once it lands.

## Net aliasing: the same technique, four rings' worth

`layout/pex-ring/pex.json`'s own `net_aliases` renames each ring's *own*
extractor-joined labels (`mpa_py|mpb_py|mph_py|py` -> `py_g`, etc.) to
design-level names. Flattening the whole array surfaces the same collision
class `layout/pex-ring/README.md` documents, now recurring **four times**
(once per ring) rather than once: each ring's own internal `n1`-`n4`/`py_g`
nets carry an *identical* joined label across all four ring instances, so
`klt extract`'s own `$1`/`$2`/`$3` disambiguation suffixes appear on three
of the four. `layout/bin/pex-netlist.py`'s `canonicalize()` already handles
this automatically -- one `net_aliases` entry per *base* joined label is
enough; the `$N`-suffixed copies canonicalize to `<canonical>$N`, which
`sanitize()` then turns into `<canonical>nN` (unique, if ungainly, and never
read by any `sim/` testbench, since none of these nets carry a design-level
name at the array's own scope). Two joined labels that recur only because
they are genuinely internal-and-unlabelled at the *gate* level, not the
array level -- `an|inva_y|mn34_g0|mp13_g1|y` and
`bn|invb_y|mn34_g1|mp24_g1|y`, `xor2`'s own two inverter output nets,
recurring once per `xor2` instance (`xa1`/`xa2`/`xa3`) -- get the same
treatment (`xor_an`/`xor_bn`). `design/ro_array_core.spice`'s own internal
net names (`rn1`-`rn4`, the ring-to-buffer nets; `t1`/`t2`, the XOR tree's
own inter-stage nets) are aliased to those exact names, matching the
convention `layout/pex-ring/pex.json` already set for `ro`. Bare,
already-`$N`-disambiguated names with no `|` in them (`mid`, `py`, `ny` and
their siblings) need no alias at all -- see `pex.json`'s own `_comment`
block for the full enumeration and `layout/bin/pex-netlist.py`'s module
docstring for why.

## What is in here

| Path | What it is |
|---|---|
| `pex.json` | the descriptor: the array GDS, the design port order (`en1 en2 en3 en4 vddr1 vddr2 vddr3 vddr4 vdd vss xo ro1 ro2 ro3 ro4`, from `design/ro_array_core.spice`'s own `.subckt ro_array_core`), and the 28 extractor-joined-net renames |
| `ro_array_core_pex.spice` | **generated** -- the library `sim/post-layout-ro-array-core/`'s testbenches include |
| `raw/ro_array_core_pex.pex.spice` | `klt extract`'s own output, unmodified |
| `reports/ro_array_core_pex.extract.json` | that run's full JSON response |

| Cell | Devices | Nets | Total series R | Total C to substrate |
|---|---|---|---|---|
| `ro_array_core_pex` | 132 | 96 | 81891.77 Ω | 367.43 fF |

Device/net counts match
[`layout/ro_array_core-placement-poc/signal9.extract.json`](../ro_array_core-placement-poc/README.md)
exactly, as expected: `--parasitics` adds R/C elements, it does not
re-recognize devices or merge/split nets.

Produced by `klt 0.4.0` (the report's own `provenance.klt_version` is the
authoritative record).

## The substrate return node

Same caveat as every other post-layout library in this repo
(klayout-tools#1503): `vsubs` is `.global`-declared, tied to ground only via
each device's own `Rvsubs_dctie ... 1e+12` inside the extracted netlist. A
deck including this library must tie the node itself (or explicitly leave
it floating, if that is the point of the deck -- see
`sim/post-layout-ro-array-core/`'s substrate-float and -solo decks). Because
`vsubs` is `.global`, it is addressed as `v(vsubs)` from a testbench's top
level directly -- **not** `v(<instance>.vsubs)` -- a wrinkle this
increment's own first substrate-float run got wrong (see
`sim/README.md`'s "Array-level post-layout" section for the correction and
its consequence: the node's own peak-to-peak swing was not captured this
round, though the period-based bracket that actually answers DR-0003 §8 was
unaffected).

## Reproducing

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-array/pex.json --check
```
