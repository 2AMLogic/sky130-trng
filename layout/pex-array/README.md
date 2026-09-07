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
[`layout/ro_array_core/ro_array_core.gds`](../ro_array_core/README.md), the
canonical array stream: the `--check`-reproducible six-stage `cell.json`
recipe's own output, which that directory reports **`klt drc` clean (0
violations)** and **`klt lvs` matching** `design/ro_array_core.spice`'s own
`.subckt ro_array_core` (132/132 devices, 96/96 nets, with two committed
negative controls confirming the match is
discriminating). Because that GDS carries the whole array's real inter-ring
wiring -- the ring-to-buffer signal chain, the buffer-to-XOR fan-in, the XOR
tree's own `t1`/`t2` routing, the array-wide `vdd` bus for the four
buffers plus three `xor2` instances, and the array-wide `vss` strap that
merges `ring1..4`'s met2 rails with `xa1..3`'s own taps -- the resulting
parasitic model includes all of that; neither `layout/pex/` (nine
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

### What `--check` should print, and when (issue #96)

**This descriptor is expected to exit 1 today, on every `klt` build
available, including the pinned one.** That is a recorded finding, not an
un-run chore:

| Command | Expected today | Why |
|---|---|---|
| `python3 layout/bin/pex-netlist.py layout/pex-array/pex.json --check` | **exit 1**, `DRIFT`, with the provenance line naming `klt 0.4.0` (committed) vs whatever is running | the committed evidence is **not reproducible** by any `klt` this repo can install, and the difference is **electrical, not a relabel** -- see "The array evidence is not reproducible, and the difference is not cosmetic" below |

Every other descriptor in the repo exits 0 on `layout/pdk.json`'s
`klt_version_pin` (`0.3.0+gc6dbf66c53c6`): `layout/pex/pex.json` and
`layout/pex/pex-sampler.json` since issues #93/#94,
`layout/pex-ring/pex.json` since issue #96. This directory was the other
half of issue #96's own scope, and it is the one that did **not** turn out
to be a provenance-only gap.

**Do not "fix" this by regenerating.** Issue #96's acceptance criteria say
in as many words that a moved extracted *value* is a finding to investigate
and record, not noise to regenerate past; regenerating here would silently
change what the thirteen current `sim/post-layout-ro-array-core/` records
were measured against, and would move this slug's headline XOR-combining
numbers by ~6% (measured below). Deciding *which* extraction is right needs
a human: it is tracked separately.

## Which GDS, and why the `vss` straps mattered

This descriptor extracts `layout/ro_array_core/ro_array_core.gds` -- the
canonical, `--check`-reproducible recipe's output -- **not**
`layout/ro_array_core-placement-poc/ro_array_core_signal9_poc.gds`. An
earlier revision of this directory did source the PoC stream, because at the
time the recipe promotion had not landed; it has (`layout/ro_array_core/`),
and the promoted recipe additionally draws `ring1..4`'s and `xa1..3`'s own
`vss` taps, which the PoC stream does not have.

That is not a relabelling, and the re-extraction says so numerically. The
canonical GDS extracts to the **same 132 devices and 96 nets** -- the straps
are not LVS-visible, since `vss` was already one net electrically at the
`.subckt` level -- but its parasitic network is measurably different:

| Extracted from | Devices | Nets | Total series R | Total C to substrate |
|---|---|---|---|---|
| `ro_array_core-placement-poc/…signal9_poc.gds` (superseded) | 132 | 96 | 81891.77 Ω | 367.43 fF |
| `ro_array_core/ro_array_core.gds` (canonical, this library) | 132 | 96 | 81935.47 Ω | 392.44 fF |

**+25.0 fF (+6.8%) of capacitance to substrate**, from the added met2/met1
strap metal. Every number `sim/post-layout-ro-array-core/` reports is
measured against the canonical row; the superseded row is recorded here only
so the difference is on the record rather than assumed negligible.

The one descriptor change the swap needed beyond the `gds` path: the
extractor's own joined label for the `vss` net grows from seven merged
labels to ten (`g_vss_m1|mph_g|s1_vss_m1|s2_vss_m1|s3_vss_m1|s4_vss_m1|vss`
gains `|vss_x1|vss_x2|vss_x3`, the three `xor2` taps), so that one
`net_aliases` key is updated to match. All 27 other aliases are unchanged --
the straps touch no signal net's labelling.

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
| `ro_array_core_pex` | 132 | 96 | 81935.47 Ω | 392.44 fF |

Device/net counts match
[`layout/ro_array_core/extract.json`](../ro_array_core/README.md) exactly,
as expected: `--parasitics` adds R/C elements, it does not re-recognize
devices or merge/split nets.

Produced by `klt 0.4.0` (the report's own `provenance.klt_version` is the
authoritative record) -- **not** `layout/pdk.json`'s `klt_version_pin`
(`0.3.0+gc6dbf66c53c6`), and not, it turns out, any `klt 0.4.0` build that
can be installed today either. See the next section.

## The array evidence is not reproducible, and the difference is not cosmetic (issue #96)

Issue #96 set out to close the same provenance gap here that issue #93
closed for `layout/pex/` and issue #96 itself closed for
`layout/pex-ring/`: committed evidence stamped `klt 0.4.0` while the pin
reads `0.3.0+gc6dbf66c53c6`, so `--check` fails on a checkout matching the
pin. For those two directories the whole diff turned out to be the
extractor's own node-numbering bookkeeping, and re-extracting on the pin was
a provenance-only change. **Here it is not.** Measured 2026-09-07:

### 1. It is not a version gap

| Extraction | `ro_array_core_pex.spice` sha256 |
|---|---|
| committed (historical `klt 0.4.0`) | `82dede47fd59…` |
| re-extracted on the pin, `klt 0.3.0+gc6dbf66c53c6` | `2ac0da8b200d…` |
| re-extracted on today's ambient `klt 0.4.0+g59c2a2873c17.dirty` | `2ac0da8b200d…` — **byte-identical to the pinned rebuild** |

Both of today's builds agree with each other and disagree with the
committed file, over the **identical** input: all three extraction reports
record the same `provenance.input.content_hash`
(`sha256:97c472adc85dafa7445f4dc2d96a60bb154f6699224d8e43e3e07a17e07a0cda`,
which is `sha256sum layout/ro_array_core/ro_array_core.gds` today) and the
same `provenance.deck.content_hash`. So this is not `0.3.0` vs `0.4.0`, and
bumping the pin would not help: the committed evidence came from a
*historical* `klt 0.4.0` build that is no longer the `0.4.0` you get.

### 2. It is not a relabel

Colour refinement (Weisfeiler-Lehman) on the label-free hub graph -- every
parasitic leg folded into its hub, keeping the series-R value, and **no node
names used at all** -- separates the two. Colour refinement can never
distinguish two isomorphic graphs, so a split is a proof of
non-isomorphism, not a heuristic. The same checker returns "equivalent" for
all five `layout/pex-ring/` cells, and for a control built by randomly
relabelling 538 internal nodes of this very library.

The concrete difference is **which physical ring two of the four
`sig_n*` inter-net coupling capacitors sit on.** Each of `sig_n1`..`sig_n4`
recurs four times (once per ring); exactly one member of each family
carries the coupling to `nyn19` (0.0115 fF) and to `vss` (0.0155 fF).
Naming each family member by the `vddr` rail of the ring its devices
actually belong to:

| Coupled member of | committed (`klt 0.4.0`) | both of today's builds |
|---|---|---|
| the `sig_n1` family | ring on `vddr4` | ring on `vddr4` |
| the `sig_n2` family | ring on `vddr4` | ring on **`vddr3`** |
| the `sig_n3` family | ring on `vddr4` | ring on **`vddr1`** |
| the `sig_n4` family | ring on `vddr4` | ring on `vddr4` |

The committed extraction puts all four couplings on one ring -- which is
what physical adjacency to a single aggressor should produce. Today's puts
two of them on rings that are nowhere near it. On that reading the
committed (historical `0.4.0`) answer is the *right* one and today's builds
regressed, but this directory does not claim to have proved which is
correct: it records that they differ, and how.

### 2a. The extraction *report* cannot see any of this -- and neither, therefore, can half of `--check`

Worth recording separately, because it is the reason this took a netlist-
level comparison to find at all. `klt extract`'s **SPICE netlist**
disambiguates repeated net names with its own `$1`/`$2`/`$3` suffixes
(`a|n2|s1_y|s2_a|y`, `…y$1`, `…y$2`, `…y$3` -- one per ring). Its **JSON
report does not**: `devices[].nets`, `nets[].name` and
`parasitics.nets[].net` all carry the *unsuffixed* name, so for this cell
**10 distinct names cover 65 of the 96 nets**:

- 4 entries each, one per ring, share the names
  `a|g_y|mnab_y|mpa_y|mpb_y|n1|s1_a|y`, `a|n2|s1_y|s2_a|y`,
  `a|n3|s2_y|s3_a|y`, `a|n4|s3_y|s4_a|y` and `mpa_py|mpb_py|mph_py|py`;
- 3 entries each, one per `xor2`, share `an|inva_y|mn34_g0|mp13_g1|y`,
  `bn|invb_y|mn34_g1|mp24_g1|y` and `mid`;
- and the two bare gate-internal names `ny` / `py` are shared by 20 and 16
  entries respectively.

The only per-entry discriminator left is `net_id`, which is the counter
klayout-tools#1063/#1072 declines to make stable and which
`pex-netlist.py`'s `canonical_parasitics()` therefore (correctly) drops.
Two consequences:

- **The report genuinely cannot distinguish these two extractions.**
  Device `$23`'s drain reads `a|n3|s2_y|s3_a|y` in both, even though its
  `leg_net` (`…__t22` vs `…__t24`) resolves, via the netlist's own `R`
  cards, to two *different* physical nets. Comparing reports says
  "identical"; comparing netlists says "not isomorphic". The netlist is
  what `sim/` simulates, so the netlist is the authority here.
- **`--check`'s report half silently drops nets on this cell.**
  `compare_report()` indexes each side's nets into a dict keyed on that
  non-unique `net` name, so the 96 entries collapse to 41 keys and 55 of
  them are overwritten before the comparison runs. It is not what made
  `--check` red here (the library's byte comparison and the reports'
  `terminals[]` ordering did that). `layout/pex/`'s and
  `layout/pex/pex-sampler.json`'s leaf cells are unaffected -- every one of
  them has 4-8 nets with **no** repeated name -- but each
  `layout/pex-ring/` ring cell collapses 19 entries to 12 (`ny` ×5, `py`
  ×4), so the blind spot is not unique to this directory, only worst here.
  It is why `layout/pex-ring/`'s own re-extraction was verified by
  *netlist*-level isomorphism and an ngspice A/B rather than by `--check`
  going green alone. Deliberately **not fixed in this pass** -- issue #96's
  scope note says a genuine electrical difference is to be flagged for a
  human rather than turned into a script change -- but it is the clearest
  thing to fix first if either directory is revisited.

### 3. The difference is measurable, and it is not round-off

`sim/post-layout-ro-array-core/tb_post_layout_ro_array_core.spice`,
rendered at that slug's `tt` / 27 °C / 1.8 V point:

| | committed library | pinned rebuild |
|---|---|---|
| `p_edge_retention` | 0.7664580 | **0.7195908** (−6.1%) |
| `p_f_xo` | 4.920442e+08 | **4.619850e+08** (−6.1%) |
| `p_bias_xo` | 0.5068875 | 0.4874618 |
| `p_swing_frac_xo` | 1.085270 | 1.081891 |
| `p_skew_span` | 1.127767 | 1.131831 |
| `p_tr1` … `p_tr4` | 6.646537e-09 … 5.893540e-09 | 6.654365e-09 … 5.879292e-09 |
| ngspice log lines differing | — | **116** |

The control that makes this conclusive: the *same* deck run against a
pure relabeling of the committed library (538 internal nodes renamed, ports
and every value untouched) produces a **byte-identical** log -- 0 differing
lines. So node labelling on its own moves nothing here; the 116 lines above
are the network, not the naming. (Four free-running rings feeding an XOR
are chaotically sensitive, so a 0.0115 fF capacitor changing which ring it
loads is enough to move the combined output's edge-retention by 6%; the
magnitude of the movement is not itself evidence of how large the network
change is.)

### What was done about it

Nothing to the evidence, deliberately. The library, its raw netlist and its
report are all left exactly as committed, so the thirteen current
`sim/post-layout-ro-array-core/` records still name the file they were
actually measured against, and no `PEX_LIB` re-stamp is owed here (contrast
`sim/README.md` § "`PEX_LIB` provenance re-stamp (issue #96)", which covers
`sim/post-layout-ro-ring5-assembled/` only). Choosing between "re-extract
and re-measure the slug on today's `klt`" and "keep the historical
extraction and pin harder" is an operator decision with a real cost either
way, tracked separately; the tool-side half is filed generically against
`klayout-tools` per this repo's friction protocol.

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
