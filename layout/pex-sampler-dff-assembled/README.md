# layout/pex-sampler-dff-assembled

The post-layout (parasitic-annotated) netlist library for the **assembled**
`sampler_dff` cell -- the sampler-side sibling of `layout/pex-ring/` (which
extracts the *assembled* `ro_ring5` cells, real inter-gate metal routing
included, rather than `layout/pex/`'s separately-extracted leaf gates wired
by ideal testbench nets).

`sampler_dff_assembled_pex.spice` is a **generated** file:
`layout/bin/pex-netlist.py` -- the same, unmodified script every other
`layout/pex*/` descriptor uses -- runs `klt extract --pdk sky130A
--parasitics` directly over `layout/sampler_dff/`'s own composed, DRC-clean,
`klt lvs`-matching GDS (`layout/sampler_dff/sampler_dff.gds`), the whole
22-device master-slave-DFF hierarchy flattened in one extraction rather than
three separately-extracted leaf cells. Because that GDS is the same
DRC-clean and `klt lvs`-**matching** (22/22 devices, 14/14 nets, 0
mismatches, issue #22, PR #99) stream `layout/sampler_dff/README.md`
narrates, the resulting parasitic model includes the cell's own **real
intra-cell routing** -- `rst_n`, `clk`, `clkb`, `mc`, `q`, `qb`, `s`, `m` and
`mb` all really wired -- which `layout/pex/sampler_dff_pex.spice` cannot, by
construction: that library only ever sees one leaf gate's own geometry at a
time and relies on the testbench itself to wire the three leaf instances
together with ideal nets.

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-sampler-dff-assembled/pex.json --check   # verify
python3 layout/bin/pex-netlist.py layout/pex-sampler-dff-assembled/pex.json           # regenerate
```

`--check` re-extracts the cell from its committed GDS into a temporary
directory and fails on any byte-for-byte or verdict-field drift -- the same
contract `layout/pex/pex.json`, `layout/pex-ring/pex.json` and
`layout/bin/compose-cell.py --check` offer. `layout/test_pex_netlist.py`
(shared, unmodified) is the other half of the guard for the rewrite logic
itself.

## Why this extraction was deferred until now

`layout/sampler_dff/`'s own assembly GDS existed well before this
directory -- placement, supply buses, and every fan-out net except the two
data-path nets touching `NAND_M` (`m`, `mb`) were routed across many prior
increments (see `layout/README.md`'s own history). `layout/pex/README.md`'s
"The sampler library" section named the reason explicitly: extracting an
incomplete circuit (`klt lvs` not matching, 15/22 devices, 7/14 nets as of
the last increment before `m` closed) would have been extracting the wrong
thing. `spec/decision-records/DR-0007-*.md`'s own "Follow-up required" list
names the same gate: "Once `layout/sampler_dff/`'s `m`/`mb` nets are routed
and its `klt lvs` matches, extract that GDS flat -- the sampler's equivalent
of `layout/pex-ring/` -- and re-run both decks." Both nets are now routed
(`mb`: PR #95; `m`: PR #99) and `layout/sampler_dff/`'s own `klt lvs` is a
full match, so that gate is clear.

## Why a separate library, not a rewrite of `layout/pex/sampler_dff_pex.spice`

The two measure different things on purpose, and
`sim/post-layout-sampler-dff/`'s existing eight records were minted against
`layout/pex/sampler_dff_pex.spice` specifically -- swapping the netlist
under them would silently change what those already-committed records mean.
`layout/pex-sampler-dff-assembled/` is new, additive evidence
(`sim/post-layout-sampler-dff-assembled/`, see `sim/README.md`), not a
replacement.

## What is in here

| Path | What it is |
|---|---|
| `pex.json` | the descriptor: the `sampler_dff` GDS, the design port order (`d clk rst_n q vdd vss`, from `design/sampler_core.spice`'s own `.subckt sampler_dff`), and the extractor-joined-net renames |
| `sampler_dff_assembled_pex.spice` | **generated** -- the library `sim/post-layout-sampler-dff-assembled/`'s testbench includes |
| `raw/<cell>.pex.spice` | `klt extract`'s own output, unmodified |
| `reports/<cell>.extract.json` | that run's full JSON response |

| Cell | Devices | Nets | Total series R | Total C to substrate | Net-to-net coupling C |
|---|---|---|---|---|---|
| `sampler_dff_assembled_pex` | 22 | 14 | 14317.234 Ω | 61.4344 fF | 0.429443 fF |
| `ro_buf_pex` | 2 | 4 | 1261.2402 Ω | 2.493682 fF | -- |

(`ro_buf_pex` is duplicated verbatim from `layout/pex/pex.json`'s own entry
and `layout/pex-ring/pex.json`'s own copy, same GDS, so this library is
self-contained for a testbench that `.include`s only `@@PEX_LIB@@` plus
`design/sampler_core.spice` -- avoiding a same-subckt-name collision from
`.include`-ing more than one pex library in one deck.) Device/net counts
match `layout/sampler_dff/extract.json` exactly, as expected:
`--parasitics` adds R/C elements, it does not re-recognize devices.

Produced by `klt 0.4.0` (each report's own `provenance.klt_version` is the
authoritative per-file record) -- the ambient build in this session, which
does not match `layout/pdk.json`'s own `klt_version_pin`
(`0.3.0+gc6dbf66c53c6`); see that file's own comment block and
`layout/pex/README.md`'s "When `--check` is red because the tool moved"
(issue #93) for why that provenance pin churns between sessions and is a
record of what actually produced committed evidence, not a hard gate.
`--check` on this exact ambient `klt` reproduces byte for byte.

## Net aliasing: the same 12 named nets `layout/sampler_dff/extract.json` already lists

Unlike `layout/pex-ring/pex.json`'s own net-aliasing wrinkle (the same
internal net name recurring across four sibling `ro_stage` instances),
`sampler_dff` has no repeated sub-cell instances at the net-naming level --
each of its 14 nets is extracted once. Twelve of them carry extractor-joined
labels (`klt`'s `l2n.extract_netlist()` joins every label found on one
physical net with `|`) that this descriptor's `net_aliases` renames to the
design-level name a reader would expect:

- **Design ports** (`d`, `clk`, `rst_n`, `q`, `vdd`, `vss`) rename to
  themselves, dropping the joined label soup around them (e.g. `en|nand_m_en|nand_m_en_via|nand_s2_en|nand_s2_en_via|rst_n`
  -> `rst_n`).
- **Internal data-path and control nets** (`m`, `mb`, `mc`, `s`, `qb`,
  `clkb`) are kept local by `pex-netlist.py`'s own design-port-order
  wrapper (see that module's docstring) -- promoted to layout pins only
  because the leaf-cell composition needed them addressable, the same
  reason `ro_ring5`'s `n1`-`n4`/`py` are local in `layout/pex-ring/pex.json`.
- The remaining **two nets carry no label at all** (`klt`'s own anonymous
  `\$6`/`\$7`, internal series-device nodes inside the two `sampler_nand2`
  instances) and need no alias: `pex-netlist.py`'s `sanitize()` renames them
  to `n6`/`n7` automatically, and they are never referenced by the
  testbench.

## What the parasitic model contains, and what it newly includes

Same model as `layout/pex/README.md` describes (lumped star series
resistance per net, quasi-static vertical-overlap-only net-to-net
capacitance, no inductance) -- `pex-netlist.py` is shared, unmodified. The
difference is scope: because the extraction runs over the **whole composed
`sampler_dff` GDS**, the per-net R/C now includes the `rst_n`/`clk`/`clkb`/
`mc`/`q`/`qb`/`s`/`m`/`mb` routing `layout/sampler_dff/README.md` documents
(a mix of `li1`, `met1` and `met2` stages, per net) -- not just each leaf
gate's own internal geometry. Total series resistance (14.3 kΩ) and total
capacitance to substrate (61.4 fF) are both roughly 3-4x the sum of the
three leaf cells' own totals in `layout/pex/README.md`'s "The sampler
library" table (1261 + 1262 + 1599 = 4122 Ω; 2.49 + 2.73 + 4.13 = 9.35 fF),
consistent with real inter-leaf-cell routing adding resistance and
capacitance no leaf-only sum could include.

The substrate-return-node caveat (`vsubs`, klayout-tools#1503) applies
identically here -- this library also declares `.global vsubs`, and
`sim/post-layout-sampler-dff-assembled/`'s testbench ties it hard to 0, the
same physically-motivated choice `sim/post-layout-sampler-dff/`'s own deck
uses.

## Reproducing

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-sampler-dff-assembled/pex.json --check
```
