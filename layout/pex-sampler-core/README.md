# layout/pex-sampler-core

The post-layout (parasitic-annotated) netlist library for the **whole
composed `sampler_core` cell** -- one hierarchy level up from
`layout/pex-array/` (the entropy source alone) and
`layout/pex-sampler-dff-assembled/` (one digitizer alone): the array's four
raw taps (`ro1`-`ro4`, `xo`) driving all six `sampler_dff` instances
(`sb`/`sv`/`sr1`-`sr4`), in one flat extraction.

`sampler_core_pex.spice` is a **generated** file: `layout/bin/pex-netlist.py`
-- the same, unmodified script every other `layout/pex*/` descriptor uses --
runs `klt extract --pdk sky130A --parasitics` directly over
[`layout/sampler_core/sampler_core.gds`](../sampler_core/README.md), the
canonical, `--check`-reproducible cell recipe's own output: **`klt drc`
clean (0 violations)** and **`klt lvs` matching** `design/sampler_core.spice`'s
own `.subckt sampler_core` (264/264 devices, 152/152 nets, 0 errors -- the
first whole-cell DRC/LVS-clean `sampler_core` assembly in this repo, PR
#113). Because that GDS carries the whole cell's real inter-block wiring --
the raw-tap-to-`d`-pin routing, the shared `clk`/`rst_n` fan-out across all
six instances, and both inter-block `vdd`/`vss` supply straps -- the
resulting parasitic model includes all of that, which neither
`layout/pex-array/` (the source alone) nor
`layout/pex-sampler-dff-assembled/` (one digitizer alone, ideal wires to the
source) could.

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-sampler-core/pex.json --check   # verify
python3 layout/bin/pex-netlist.py layout/pex-sampler-core/pex.json           # regenerate
```

`--check` re-extracts the cell from its committed GDS into a temporary
directory and fails on any byte-for-byte or verdict-field drift -- the same
contract every other `layout/pex*/pex.json` offers.

## What is in here

| Path | What it is |
|---|---|
| `pex.json` | the descriptor: the `sampler_core` GDS, the design port order (`en1 en2 en3 en4 vddr1 vddr2 vddr3 vddr4 vdd vss clk rst_n raw_bit raw_valid ring_bit1 ring_bit2 ring_bit3 ring_bit4`, from `design/sampler_core.spice`'s own `.subckt sampler_core`), and the 42 extractor-joined-net renames |
| `sampler_core_pex.spice` | **generated** -- the library a `sim/` testbench includes |
| `raw/sampler_core_pex.pex.spice` | `klt extract`'s own output, unmodified |
| `reports/sampler_core_pex.extract.json` | that run's full JSON response |

| Cell | Devices | Nets | Total series R | Total C |
|---|---|---|---|---|
| `sampler_core_pex` | 264 | 152 | 169817.28 Ω | 869.19 fF |

Device/net counts match [`layout/sampler_core/extract.json`](../sampler_core/README.md)
exactly, as expected: `--parasitics` adds R/C elements, it does not
re-recognize devices or merge/split nets. This run's own
`reports/sampler_core_pex.extract.json` records `provenance.klt_version:
"0.3.0"` (the ambient build this session installed) against the identical
input GDS content hash `layout/sampler_core/extract.json` itself recorded
under a `"0.4.0"`-tagged build -- the same documented per-session churn
`layout/pdk.json`'s own comment block names, not a version this repo pins as
a hard gate. `--check` reproduces this library byte for byte on the ambient
build with no drift, and the totals (264 devices, 152 nets, matching R/C)
agree with the whole-cell hand-off measurement recorded on issue #22 before
this directory existed, so the two `klt` builds agree numerically on this
GDS even though their own version strings differ (contrast
`layout/pex-array/README.md`'s own "not reproducible" finding for the
array-level library, which is a distinct GDS and a distinct, disclosed
regression).

## Net aliasing: built from `klt lvs`'s own verified net map, not from spelling

Every other `layout/pex*/pex.json` derives its `net_aliases` by reading the
extracted netlist's own joined labels and inferring the design-level name
from their spelling (a `ro_stage`'s `py`, an array's `rn1`, etc.). This
descriptor instead reads
[`layout/sampler_core/lvs.json`](../sampler_core/README.md)'s own
`net_correspondence` array -- the **`klt`-verified** layout&harr;reference net
map from the whole-cell match that landed this GDS (264/264 devices, 152/152
nets, 0 errors) -- and translates each `layout` entry directly into a
`net_aliases` key, so every canonical name below is `klt lvs`'s own answer,
not a human's reading of the label text.

That distinction matters for one specific family: **`raw_bit`, `raw_valid`
and `ring_bit1`-`ring_bit4` were never promoted to a GDS label at all.**
Confirmed directly (`grep` over the extracted `.SUBCKT`'s own pin list finds
no `raw_bit`/`raw_valid`/`ring_bit` string anywhere): each of the six
`sampler_dff` instances' own `q` pin carries the *identical* joined label
(`a|inv_q_y|inv_q_y_via|inv_q_y_via2|nand_s2_a|nand_s2_a_stub|nand_s2_a_via|nand_s2_a_via2|q|y`),
disambiguated only by `klt`'s own `$1`-`$5` counter suffixes -- so spelling
alone cannot say which suffix is `sb`'s own `q` (-> `raw_bit`) versus `sv`'s
(-> `raw_valid`) versus `sr1`-`sr4`'s (-> `ring_bit1`-`ring_bit4`).
`lvs.json`'s `net_correspondence` answers exactly that (`RAW_BIT <- ...|q|y`,
`RAW_VALID <- ...|q|y$1`, `RING_BIT1 <- ...|q|y$2`, ..., `RING_BIT4 <-
...|q|y$5`), so this descriptor gives that family **six explicit
`net_aliases` entries** instead of the usual one-base-alias-plus-auto-`$N`
pattern every other repeated-instance net here uses (`m`, `mb`, `mc`, `s`,
`qb`, `clkb` -- each local to its own `sampler_dff` instance, never
individually referenced, so one base alias per name is correct for them).

**Ordering is load-bearing for the six-entry family.** `canonicalize()`
matches by `name.startswith(alias_key)` (see `layout/bin/pex-netlist.py`'s
own docstring), and the bare, unsuffixed key (`...|q|y`, for `raw_bit`) is a
literal string-prefix of every suffixed one (`...|q|y$1`, ..., `...|q|y$5`).
`pex.json` lists the `$5`..`$1` entries **before** the bare one for exactly
this reason -- reversing the order would make the `raw_bit` entry's `startswith`
check fire first for every instance's own leg nodes too, silently misrouting
`raw_valid`/`ring_bit1`-`ring_bit4`'s own parasitics onto `raw_bit`.

### Verifying the six-way split independently of `canonicalize()`'s own logic

Trusting the ordering argument alone was not enough given how easy a
prefix-collision bug is to get wrong silently, so this was checked a second,
independent way: a plain union-find over every `R`/`C` element's own two
node tokens in the **generated** `sampler_core_pex__core` subcircuit (R only
-- `C` elements model substrate/coupling capacitance, which does not define
net identity, and unioning through the shared `vsubs` node collapses the
whole circuit into one component, as a first pass of this check did before
excluding it). Restricted to `R` elements (the star-topology series
resistance, which by construction only ever connects two points of the
*same* physical net) and excluding the single `Rvsubs_dctie` tie, the graph
resolves into **exactly 152 components** -- matching `net_count` exactly --
and `raw_bit`/`raw_valid`/`ring_bit1`-`ring_bit4` each land in their own,
mutually distinct component, as do each of `m`/`mb`/`mc`/`s`/`qb`/`clkb`'s
six per-instance copies. One superficially alarming intermediate finding
along the way, recorded here rather than silently dropped: `klt`'s own
"dup" leg-numbering convention (element names like
`..._dup1_t0`) sometimes spells an `$N`-suffixed net's own leg using the
**base** (unsuffixed) hub's text -- e.g. a leg literally named
`raw_bit__t02` turns out, via its own bridging resistor, to belong to
`raw_valid`'s star, not `raw_bit`'s. Read as plain text this looks like a
cross-net short; followed through the union-find it resolves correctly
every time, for every repeated-instance net checked. This is a labelling
quirk in how `klt` names internal star legs, not an extraction defect --
`klt lvs`'s own independent topology check already confirmed 152/152 nets
match the schematic exactly, and the union-find re-derives the identical
partition from the parasitic pass's own R-element graph. Not filed as
`klayout-tools` friction: the *report* and the *netlist* both remain
internally consistent and simulatable, this is just a non-obvious spelling
convention worth documenting for the next person who greps this file.

The full 42-entry table, transcribed from `lvs.json`'s `net_correspondence`:

| Design-level name(s) | Extractor-joined label |
|---|---|
| `en1`-`en4` | `en\|enN\|g_en` |
| `vddr1`-`vddr4` | `g_vddr_m1\|mnt_g\|s1_vddr_m1\|s2_vddr_m1\|s3_vddr_m1\|s4_vddr_m1\|vddr\|vddrN` |
| `vdd` | the 29-label merge including every `*_vdd` tap plus both inter-block strap segments |
| `vss` | the 28-label merge including every `*_vss` tap plus both inter-block strap segments |
| `clk` | the 13-label merge spanning all six instances' own `ctrl` taps |
| `rst_n` | `en\|nand_m_en\|nand_m_en_via\|nand_s2_en\|nand_s2_en_via\|rst_n` |
| `xo`, `ro1`-`ro4` | each net's own array-side label merged with its destination `d`-pin's `tg_d_a` label (one net now, not two) |
| `t1`, `t2`, `rn1`-`rn4` | unchanged from `layout/pex-array/pex.json` |
| `sig_n1`-`sig_n4`, `xor_an`, `xor_bn`, `py_g` | unchanged from `layout/pex-array/pex.json` (per-ring/per-`xor2` internal nets, one base alias each, `$N` auto-suffixed) |
| `m`, `mb`, `mc`, `s`, `qb`, `clkb` | unchanged from `layout/pex-sampler-dff-assembled/pex.json` (per-instance internal nets, one base alias each, `$N` auto-suffixed) |
| `raw_bit`, `raw_valid`, `ring_bit1`-`ring_bit4` | the six explicit, order-sensitive entries described above |

See `pex.json`'s own `_comment` block for the derivation notes inline with
the alias table itself.

## What the parasitic model contains

Same model as every other `layout/pex*/README.md` describes (lumped star
series resistance per net, quasi-static vertical-overlap-only net-to-net
capacitance, no inductance, no distributed RC unless `--critical-net` names
it -- not used here) -- `pex-netlist.py` is shared, unmodified. The
substrate-return-node caveat (`vsubs`, klayout-tools#1503) applies
identically: this library declares `.global vsubs`, and any testbench
`.include`-ing it must tie that node itself.

## What this directory does not attempt

This is the parasitic-extraction half of issue #22's remaining scope only.
**Not yet done, and not claimed here**: a post-layout PVT simulation
campaign against this library (the whole-chain, raw-tap-to-sampled-bit
post-layout evidence `layout/README.md`'s own history has flagged as open
since the `ro_array_core`-level extraction landed), and DR-0003 §8's `wstv`
inter-ring decorrelation re-evaluation once that campaign exists. Both
remain tracked against issue #22.

## Reproducing

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-sampler-core/pex.json --check
```
