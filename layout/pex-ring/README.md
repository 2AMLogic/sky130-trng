# layout/pex-ring

The post-layout (parasitic-annotated) netlist library for the **assembled**
`ro_ring5` cells -- the ring-level sibling of `layout/pex/` (which extracts
the nine *leaf* gates and relies on the testbench to wire them with ideal
inter-cell nets).

`ro_ring5_assembled_pex.spice` is a **generated** file:
`layout/bin/pex-netlist.py` -- the same, unmodified script `layout/pex/`
uses -- runs `klt extract --pdk sky130A --parasitics` directly over each
composed ring's own committed GDS (`layout/ro_ring5*/ro_ring5*.gds`), the
whole five-gate hierarchy flattened in one extraction rather than five
separate leaf-cell extractions. Because that GDS is the same DRC-clean and
LVS-clean stream issue #22/#27 landed in PR #51 (`layout/ro_ring5/`,
`_wstv0p44`, `_wstv0p46`, `_wstv0p48`), the resulting parasitic model
includes the ring's own **real inter-gate metal routing** -- the `n1`-`n4`
signal chain, the `ro` feedback, and the `vddr`/`vss` rail busing -- which
`layout/pex/ro_ring5_pex.spice` cannot, by construction: that library only
ever sees one gate's own geometry at a time.

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-ring/pex.json --check   # verify
python3 layout/bin/pex-netlist.py layout/pex-ring/pex.json           # regenerate
```

`--check` re-extracts every ring from its committed GDS into a temporary
directory and fails on any byte-for-byte or verdict-field drift -- the same
contract `layout/pex/pex.json` and `layout/bin/compose-cell.py --check`
offer. `layout/test_pex_netlist.py` (shared, unmodified) is the other half
of the guard for the rewrite logic itself.

## Why a separate library, not a rewrite of `layout/pex/ro_ring5_pex.spice`

The two measure different things on purpose, and
`sim/post-layout-ro-ring5/`'s existing records were minted against
`layout/pex/ro_ring5_pex.spice` specifically -- swapping the netlist under
them would silently change what twelve already-committed records mean.
`layout/pex-ring/` is new, additive evidence (`sim/post-layout-ro-ring5-assembled/`
below), not a replacement.

## What is in here

| Path | What it is |
|---|---|
| `pex.json` | the descriptor: which ring GDS files, the design port order (`en ro vddr vss`, from `design/ro_array_core.spice`'s own `.subckt ro_ring5`), and the extractor-joined-net renames |
| `ro_ring5_assembled_pex.spice` | **generated** -- the library `sim/post-layout-ro-ring5-assembled/`'s testbench includes |
| `raw/<cell>.pex.spice` | `klt extract`'s own output, unmodified |
| `reports/<cell>.extract.json` | that run's full JSON response |

| Cell | Devices | Nets | Total series R | Total C to substrate | Net-to-net coupling C |
|---|---|---|---|---|---|
| `ro_ring5_assembled_pex_wstv0p42` | 22 | 19 | 10310.58 Ω | 42.246 fF | -- |
| `ro_ring5_assembled_pex_wstv0p44` | 22 | 19 | 10319.42 Ω | 42.276 fF | -- |
| `ro_ring5_assembled_pex_wstv0p46` | 22 | 19 | 10328.37 Ω | 42.306 fF | -- |
| `ro_ring5_assembled_pex_wstv0p48` | 22 | 19 | 10337.43 Ω | 42.336 fF | -- |
| `ro_buf_pex` | 2 | 4 | 1261.24 Ω | 2.494 fF | -- |

(`ro_buf_pex` is duplicated verbatim from `layout/pex/pex.json`'s own entry,
same GDS, so this library is self-contained for a testbench that includes
only `@@PEX_LIB@@` plus `design/ro_array_core.spice` -- avoiding a
same-subcircuit-name collision from including both pex libraries in one
deck.) Device/net counts match `layout/ro_ring5*/extract.json` exactly, as
expected: `--parasitics` adds R/C elements, it does not re-recognize
devices. 22 = `ro_nand2`'s 6 + 4x`ro_stage`'s 4, matching `layout/ro_ring5/README.md`.

Produced by `klt 0.4.0` (each report's own `provenance.klt_version` is the
authoritative per-file record).

## Net aliasing: a ring-level wrinkle leaf extraction never hits

`layout/pex/pex.json`'s own `net_aliases` renames each cell's *own* joined
labels to their design-level names (e.g. `ro_nand2`'s `py`). Flattening a
whole ring surfaces a case leaf extraction cannot: **the same internal net
name recurs across sibling instances.** Both `ro_nand2` and every
`ro_stage` in a ring carry a schematic-internal net literally named `py`
(the starve-PMOS-to-switch-PMOS node, `design/ro_array_core.spice`'s
`.subckt ro_stage`/`ro_nand2`) and another named `ny`. Extracting one gate
at a time (as `layout/pex/` does), each cell only ever has ONE such
net, so no collision is possible. Extracting a whole ring flattens **five**
instances (one `ro_nand2` + four `ro_stage`) into one net list, and KLayout
already disambiguates the four `ro_stage` copies at the SPICE-text level
(`py`, `py$1`, `py$2`, `py$3`) -- but `ro_nand2`'s *own* `py` is additionally
**joined** with its own pin labels (`mpa_py|mpb_py|mph_py|py`, the same
two-pass-composition artifact `layout/pex/pex.json` already renames to
`py`). Naively reusing that same target name collides with the *other*
four, already-distinct `py`/`py$1..3` nets -- `layout/bin/pex-netlist.py`'s
own injective-rename check catches this (`rewrite_cell` raises `BuildError`
rather than silently merging two physically distinct nodes), so this was a
loud failure, not a silent one. The fix: give the `ro_nand2`-owned name a
target that cannot collide with anything else in the same net list
(`py_g`, not `py`) -- see `pex.json`'s `net_aliases`.

The `n1`-`n4` family hits a related but distinct trap: canonicalizing to
bare `n1`..`n4` collided with the extractor's own anonymous-net naming
convention (`$4` -> sanitized to `n4`, since `sanitize()` replaces `$` with
`n` -- see `layout/bin/pex-netlist.py`'s docstring). `pex.json` uses
`sig_n1`..`sig_n4` instead, which cannot collide with any `$<digits>`
sanitization output. Both of `n1`-`n4` and `py`/`ny` are internal-to-the-ring
nets kept local by the design-port-order wrapper (`ports: ["en","ro","vddr","vss"]`
matches `design/ro_array_core.spice`'s own `.subckt ro_ring5` line exactly;
everything else stays a local node inside `ro_ring5_assembled_pex_wstv0p4x`).

## What the parasitic model contains, and what it newly includes

Same model as `layout/pex/README.md` describes (lumped star series
resistance per net, quasi-static vertical-overlap-only net-to-net
capacitance, no inductance) -- `pex-netlist.py` is shared, unmodified. The
difference is scope: because the extraction runs over the **whole composed
ring GDS**, the per-net R/C now includes the `n1`-`n4`/`ro` signal-routing
segments and the `vddr`/`vss` rail-busing metal `layout/ro_ring5/README.md`
documents (met1 signal routing, met2 rail busing) -- not just each gate's
own internal geometry. That is the entire point of this directory: turning
`layout/pex/`'s "real intra-cell parasitics, ideal inter-cell wires" into
"real intra-cell AND real inter-cell parasitics, for everything up to one
ring" (the array's inter-*ring* wiring -- buffer fan-in, the XOR combining
tree, per-ring supply distribution -- is still not drawn; see
`layout/README.md`'s "What's deferred").

The substrate-return-node caveat (`vsubs`, klayout-tools#1503) applies
identically here -- this library also declares `.global vsubs`, and
`sim/post-layout-ro-ring5-assembled/`'s testbench ties it hard to 0, the
same physically-motivated choice `sim/post-layout-ro-ring5/`'s primary deck
uses.

## Simulating a much bigger flat extraction: a memory trap, and its fix

The first full-corner run of `sim/post-layout-ro-ring5-assembled/`'s
testbench hit `Error: memory required (Id Bytes) is more than memory
available (Id Bytes)! Setting the output memory is not possible.` at the
`ff` corner (fastest devices, shortest internal timesteps) -- not a
convergence failure (no singular-matrix or timestep-too-small message), an
out-of-memory abort partway through the transient. Root cause: ngspice's
default history buffer keeps a full-resolution voltage trace for **every**
node in the deck, and a flat ring extraction has far more of them than the
leaf-cell composition does -- every per-terminal parasitic-star leg node
the extractor's own model introduces (`layout/bin/pex-netlist.py`'s
docstring calls these `__tN` nodes) now exists for the *whole* ring's
worth of routing, not just one gate's. At the `ff` corner's shorter
timesteps, that history exhausted available memory outright rather than
merely running slowly. Fix: a `.save` line in the testbench naming only the
handful of node voltages and branch currents the `.meas` statements
actually read (`v(r1o)`, `v(q1ob)`, `i(Vddrr1)`, etc.) -- none of the
internal leg nodes are read by any measurement, so this changes nothing
about the result, only the memory footprint. Confirmed by re-running the
`ff` corner alone after the fix: **PASS**, all four widths' periods
measured. Not filed against `klayout-tools`: this is ngspice's own default
trace-retention behaviour, unrelated to what `klt extract` wrote.

## Reproducing

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
python3 layout/bin/pex-netlist.py layout/pex-ring/pex.json --check
```
