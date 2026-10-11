# layout/trng_whole/verify

**Whole-block physical verification of the composed TRNG (issue #173, part of
#170; contributes to #18 AC3).** Provisional until silicon.

> **Whole-block project verification on klt's curated sky130 decks. NOT foundry
> sign-off.** No foundry DRC/LVS/antenna/density runset, no parasitic
> extraction, no electrical or entropy characterisation. Completion of this
> increment does **not** close #170, #18 AC3, DR-0003 section 8 or DR-0009.

**Verdict.** On the composed stream `layout/trng_whole/trng_whole.gds`
(`sha256:af2f8dfe…`, unchanged since #172/#181):

| Check | Result | Evidence |
|---|---|---|
| `klt drc --deck sky130` (curated deck `sha256:2bcbd625…`, 91 rules on 20 layers, `licon1.ongrid.1` enforced) | **clean, 0 violations** | `drc.request.json`, `drc.json` |
| `klt extract` with standard cells abstracted | extracted: 264 MOSFETs (132 nfet / 132 pfet), 8605 abstracted cell instances (69 cell types), 123 declared pins, 159 warnings all classified | `extract.request.json`, `extract.json.gz` |
| Mixed-level `klt lvs` (`options.anchor_top_level_pins`) | **match, 0 error mismatches** (one warning-severity disclosure, explained); 264/264 devices, 2511/2511 nets, 123/123 pins | `lvs.request.json`, `lvs.json` |
| Independent per-port endpoint audit | 123/123 ports: the standard-cell pins and transistor terminals on each port's layout net equal those on its reference net | `coverage.json`, `coverage.md` |
| Fault controls (swapped signal x3, disconnected interface, distinct-supply short) | **5/5 reach LVS and fail for the intended reason**; the untouched baseline re-run afterwards matches with identical stable fields | `controls/controls.json`, `controls/controls.md` |

## The `sampler_core` DRC finding (5664 `licon1.ongrid.1`)

Issue #172 reported 5664 `licon1.ongrid.1` violations inside the analog macro
(klayout-tools#2648: generated gate-contact cuts off the 0.005 um grid). The
operator-approved route for #173 was "regenerate and reverify the analog input
with new provenance". That regeneration was **already done by issue #181** (all
nineteen `layout/*/cell.json` cells rebuilt on klt `0.6.0+g5edb557f91d0`, the
build containing the #2648 fix; `sampler_core.gds` is now `sha256:e3ff54a9…`,
was `a00f6550…`) and #172's composition was refreshed on it. This increment
therefore needed **no further regeneration**: it re-verifies the composed
stream on that build, with the rule still enabled, and finds 0 violations.
No rule was waived, relaxed or removed (`drc.json` `coverage.rules_checked`
contains `licon1.ongrid.1`, and `test_verify_whole.py` asserts it).

## Mixed-level comparison boundary

- **Analog `sampler_core`: transistor level.** The committed, LVS-matched
  `layout/sampler_core/sampler_core.ref.spice` hierarchy is flattened into the
  top circuit (every MOSFET kept). The layout side is a flat extraction.
- **Digital `trng_digital`: standard-cell level.** All 8605 placed cells are
  opaque pin-only black boxes on both sides (`klt extract --abstract-cells`
  with the PDK LEF on the layout side, pin-only `.subckt` stubs on the
  reference side). Signal pins come from `layout/trng_digital/trng_digital.routed.v`;
  `VPWR`/`VPB` are tied to `vdd` and `VGND` to `vss`; the 6284 fill/tap
  instances (never in the Verilog) come from the routed DEF `COMPONENTS` and
  must be power-only cells. They are **compared, not pruned**.
- **Hierarchy is flattened**; `VNB` is dropped from every stub (klt extract
  resolves it only through the deck's global substrate net).
- **Digital black boxes must not hide boundary defects.** Three layers keep
  them honest: every cell's signal *and* power pin is an explicit stub pin
  compared by the LVS engine; `options.anchor_top_level_pins` pairs each of the
  123 top pins by name (otherwise two topologically interchangeable bus bits
  compare clean); and `coverage.json` carries a comparer-independent audit that
  each port net has the identical multiset of cell pins / transistor terminals
  on both sides (`vdd` 16654 endpoints, `vss` 8823, ...).

The reference is generated, not hand-edited: `lvs.ref.spice` (sha256 in
`verify.json`) is built by `layout/bin/verify-whole.py` from the #172 inputs;
`verify-whole.py check` rebuilds it and fails on drift.

## Coverage matrix and limitations

`coverage.md` / `coverage.json` list every one of the 123 top-level ports
(including `vdd`, `vss`, `vddr1`-`vddr4`, `clk`, `rst_n`, `en1`-`en4`,
`ring_bit1`-`ring_bit4` and 107 digital pins) against four checks: exactly one
extracted pin carries the name, it is not joined with another port, the LVS
comparer paired it by name, and the endpoint multisets agree. All 123 pass.

Named limitations, each carried into #174 and #170 (full text in
`coverage.md`): **L1** digital cell internals not compared; **L2** digital
substrate/`VNB` not checked (`VPB` is, and is confirmed tied to `VPWR`); **L3**
device bodies / tap convention unchecked (`body_verification: unchecked`, the
pre-extracted-netlist request form has no deck); **L4** device parameters at
klt defaults only; **L5** fill/tap/diode handling; **L6** `power_connectivity`
is `unchecked` for this reference form (power is part of the ordinary compare
instead); **L7** hierarchy flattened; **L8** pin names canonicalised (never
repaired when zero or several ports share a net); **L9** curated deck: partial
rule coverage. 45 deck rules not run, 19 stream layers without rules, each
classified in `drc_coverage_audit.md` (see "DRC coverage audit" below). Clean
on the curated deck is still not foundry DRC clean: no foundry sign-off runset,
and no antenna, density, seal-ring, latch-up or foundry-only rules.
**L10** analog DRC history;
**L11** connectivity only, no parasitics; **L12** area target still Unmet;
**L13** 29 unloaded input pins (`bus_wdata[31:3]`) have vacuous endpoint
audits; **L14** stub pin order; **L15** the extraction warnings, classified.

## DRC coverage audit (L9, issue #281)

`drc_coverage_audit.md` / `drc_coverage_audit.json` turn L9's counts into
statements a reader can check. **This is evidence, not sign-off.** It checks
klt's own curated-deck coverage report against the stream. It is not a foundry
runset, and it adds no antenna, density, seal-ring or latch-up check. The
density and antenna *estimates* that accompany it are in
`physical_estimates.*` (see "Physical estimates" below, issue #283).

- **Table 1: the 45 rules klt did not run** (`drc.json` `coverage.inapplicable`,
  reason `no_applicable_geometry`; `rules_skipped` is the legacy name of the
  same list). Each row gives the rule's check kind and deck layers from
  `klt deck rules`. Each layer is resolved to its stream layer/datatype through
  the deck's own layer table, and the row gives that layer's flattened shape
  count in `trng_whole.gds` (`klt layers --flattened --include-text`). Result:
  **45 of 45 `vacuous-confirmed`**, 0 residual, 0 unresolved. Every rule reads
  a layer with no geometry in the stream: `capm`/`capm2`, `dnwell`, the
  HV/implant/marker layers, `pad`, and so on. For the six two-layer rules
  (`capm.enclosing.via3.1`, `met3.enclosing.capm.1`, ...), `via3`/`via4`/`met3`/`met4`
  do carry shapes, but the MiM-cap plate each rule also needs is empty.
- **Table 2: the 19 stream layer/datatypes no curated rule reads.** **11 are
  `present-unruled`** (drawn geometry that nothing checks, a real residual
  gap): for example `64/16`, `122/16`, `81/4`, `236/0`, `235/4`. **8 are
  `text-or-marker-only`** (pin-label layers carrying only text objects): for
  example `64/5`, `67/5`, `83/44`. No layer is labelled absent. The deck's layer
  table names none of the 19, and the audit does not guess their purpose.

The "adds no antenna, density … check" limitation stays exactly as it is:
`physical_estimates.*` (below) are informational estimates, not checks.

Verdict rules are stated per check kind in the table. A rule is
`vacuous-confirmed` only for a known kind (`angle`/`ongrid`/`width`/`space` need
their one layer empty; `enclosing`/`separation` need one of their two layers
empty). An unknown rule, unmappable layer or unsupported kind is `unresolved`,
never vacuous.

**Pinning.** The mapping is taken only from the deck that produced `drc.json`.
`klt deck rules` must report `content_hash` equal to `drc.json`
`provenance.deck.content_hash` (`sha256:2bcbd625…`). The layer table comes from
`klayout_tools.decks.get_layer_names('sky130')`, imported from a `klayout_tools`
whose deck module hashes to that same value. If either hash differs, the audit
refuses and names both hashes. klt exposes no layer/datatype for rule layers on
its CLI, hence the Python import; filed as klayout-tools#3092.

**Drift.** `verify-whole.py check` (and the seconds-long
`check --audit-only`) recomputes the audit and fails if the stream, the
resolved layer map or the deck hash changes either table. Controls 1-5 run on
synthetic GDS fixtures with the real pinned deck: absent layer, present layer,
unknown rule, unmappable layer, unsupported kind, one-of-two layers, and drift
on a stream edit / remapped layer / changed deck hash. They are in
`controls/drc_coverage_audit_controls.md`, and `test_verify_whole.py` runs the
same controls on stubbed counts with no klt.

## Physical estimates (L9, issue #283)

`physical_estimates.md` / `physical_estimates.json` turn the rest of L9's "no
antenna, density … rules" statement into **informational numbers a reader can
check**. **These are estimates, not foundry sign-off** -- the pinned deck has
no density or antenna rule at all, so no window, threshold or verdict here is
foundry-derived, and neither artifact contains a pass/fail. What they carry:

- **Density** of the unioned drawing geometry of poly, li1 and met1..met5 over
  a 100 um x 100 um tiled grid. The window size and stride are an **arbitrary
  choice** (the deck documents no density window); the denominator is each
  window's own clipped area inside the top-cell bounding box, zero-area windows
  are skipped and counted, and invalid grids are refused. Per-window densities
  are committed so any single window can be spot-checked by hand.
- **Naive cumulative antenna ratios** per electrical net and level: summed
  li1..level conductor area / summed MOS gate W*L. Gate areas come from the
  committed extraction's 264 analog devices; conductor components come from a
  flat metal-only connectivity extraction and are attributed to a gate net
  only when their whole label set belongs to that net and no other. Everything
  that does not meet that bar is excluded and counted: zero-gate nets (never
  rated, never infinite), gate nets with no attributable conductor geometry
  (listed), ambiguous label sets, unlabeled geometry. All gates inside the
  8605 abstracted digital instances are excluded -- reported against the count
  of placed device-bearing instances, never an invented area fraction. Process
  sequencing, diode relief, side-wall area and foundry thresholds are not
  modelled.
- **Coverage accounting** quantifies how much drawn metal per level the
  label-based attribution covers (roughly 10-50% by level), so the ratios are
  read as lower bounds on real per-net exposure for the nets they do cover.

Why computed in-repo rather than with `klt stats`/`klt economy`: `stats
--per-layer` sums polygon areas without a boolean merge (overlaps
double-counted — `klt stats` will *not* reproduce these unioned numbers by
design), and neither command offers windowed per-layer density. Filed as
klayout-tools#3107 (see `docs/friction-ledger.md`).

**Drift.** `verify-whole.py check` includes the estimates: it recomputes both
artifacts from the committed GDS + extraction and fails on any difference
(`check --estimates-only` scopes to this gate alone, in seconds, with no klt
run). Regenerate with `verify-whole.py estimates`. The calculator controls
(union without double counting, hierarchy, boundary clipping, empty layer,
invalid grids, cumulative ratios, zero-gate and ambiguous-label accounting,
drift) run on synthetic GDS fixtures with real klayout: they are in
`controls/physical_estimates_controls.md`, and `test_verify_whole.py` runs the
pure arithmetic halves of the same controls on PR CI with nothing installed.

## Fault controls

Each control is a disposable copy of the composed GDS (or, for one, of the
reference) run through the *same* extract -> pin canonicalisation -> LVS
pipeline. Before verification an independent `klayout.db` probe proves the
defect is present (labels at the terminals, cluster ids, or reference-card
diff). After every control the golden GDS and reference hashes are re-checked,
and the untouched baseline is re-run at the end.

| Control | Defect | LVS error categories | Evidence |
|---|---|---|---|
| `swap-analog-ring-bits` | `ring_bit1` <-> `ring_bit2` identities swapped (all labels, all cells) | `device.unmatched` x10, `net.unmatched` x4 | the unmatched devices are the `sampler_dff` instances `sr1`/`sr2` attached to those nets |
| `swap-digital-bus-bits` | `bus_wdata[0]` <-> `bus_wdata[1]` swapped | `hints.rejected` x2, `topology` x5 | pin-anchor rejection naming `BUS_WDATA[0]`; endpoint audit flags both ports |
| `swap-interface-reference` | `raw_bit` <-> `raw_valid` exchanged on the digital cells' pins of a reference copy | `topology` x6 | unmatched standard-cell instances (`CLKBUF_1`, `AND2_1`, `NAND2_1`, ...) and `RAW_BIT`/`RAW_VALID` name conflicts |
| `disconnect-raw-bit` | 8 um gap cut in the met5 route from the sampler output to the digital input | `device.unmatched` x4, `net.unmatched` x1 | the `sb` sampler devices and the layout net labelled `RAW_BIT` have no counterpart |
| `short-ring-supply-to-logic-supply` | met5 bridge joins the `vddr4` and `vdd` boundary pads | `net.merged` x9, `net.split` x8, `device.unmatched` x19, `hints.rejected` x1 | pin canonicaliser reports one pin carrying both names (never repaired); `VDDR4` merged; endpoint audit flags `vdd` and `vddr4` |

Honest findings from building the controls:

- Swapping the names of two *unloaded* pins (`bus_wdata[3]`/`[4]`, no cell
  load in the as-built netlist) compares **match**: it is electrically a
  no-op, not a defect any LVS can see. The digital swap control therefore uses
  two loaded bits. This is limitation L13.
- The analog `ring_bit` swap is *not* flagged by the endpoint audit (the four
  rings are structurally identical; they differ in transistor widths), only by
  the LVS device comparison. Neither check alone is claimed to be sufficient.
- A pure label swap between structurally interchangeable nets is invisible to
  topology alone; that is what `options.anchor_top_level_pins` is for (the
  `swap-digital-bus-bits` control is reported as `hints.rejected`).

## Reproducing

Pins: klt `0.6.0+g5edb557f91d0` (the `layout/pdk.json` pin; venv recipe in
`layout/README.md`, "Regeneration on the cut-size/grid fix (issue #181)"),
KLayout 0.30.12, python `klayout` 0.30.12, open_pdks `c6d73a35f524…` (PDK root
via `$PDK_ROOT` / `klt pdk find`), PDK LEF `sha256:3a3ea4e9…`, PDK spice
`sha256:6dec6626…`. The interpreter must be the venv's `python` (it carries
`klayout_tools` and `klayout`). `klt sim` is not involved; nothing here is a
SPICE grid.

```bash
python layout/bin/verify-whole.py run        # DRC + extract + LVS + coverage   (~8 min)
python layout/bin/verify-whole.py controls   # the five fault controls + baseline re-run (~45 min)
python layout/bin/verify-whole.py check      # coverage-audit drift + isolated baseline re-run, diff against committed (~8 min)
python layout/bin/verify-whole.py check --audit-only   # DRC coverage audit drift only (seconds)
python layout/bin/verify-whole.py audit      # regenerate drc_coverage_audit.{json,md} from the committed drc.json
python layout/bin/verify-whole.py audit-controls   # coverage-audit controls 1-5 -> controls/drc_coverage_audit_controls.*
python3 layout/test_verify_whole.py          # evidence contract tests, no klt needed
```

The coverage audit needs the pinned klt specifically, not just "a klt": a
newer build ships a different curated deck (klt 0.7.0's is `sha256:f8f2c3f4…`),
and the audit refuses it by design rather than mapping `drc.json`'s rules
through another deck. Pass the pinned venv's binary with `--klt` if the `klt`
on `PATH` is a different build.

The committed reports can also be re-verified with the tool itself, from this
directory (they record relative paths, so these resolve against the committed
files; each re-hashes its inputs against the report and exits non-zero on drift):

```bash
klt drc --check drc.json                      # re-hashes ../trng_whole.gds and the deck
klt lvs --check lvs.json                      # re-hashes trng_whole.layout.spice and lvs.ref.spice; add --rerun for the full compare
zcat extract.json.gz > extract.json && klt extract --check extract.json; rm extract.json
```

`extract.json.gz` is the tool's report byte for byte, gzip-compressed for size.
The raw extracted netlist is not committed (8 MB; anonymous `$N` net numbering is
not a stable cross-host contract per `klt extract --help`; it did reproduce
byte-for-byte on this host); the canonical, pin-renamed netlist the LVS report
pins is.

## Files

| File | What |
|---|---|
| `verify.json` | provenance: input hashes, tool pins, reference facts, per-stage verdicts, warning review |
| `drc.request.json`, `drc.json` | `klt drc` request / full report |
| `extract.request.json`, `extract.json.gz` | `klt extract` request (PDK path as `${PDK_ROOT}`) / full report |
| `trng_whole.layout.spice` | extracted netlist with the 123 top pins renamed to their port names (the LVS layout side) |
| `lvs.ref.spice` | the generated mixed-level reference |
| `lvs.request.json`, `lvs.json` | `klt lvs` request / full report |
| `coverage.json`, `coverage.md` | per-port coverage matrix + named limitations |
| `drc_coverage_audit.json`, `drc_coverage_audit.md` | L9 audit: every rule klt did not run and every unruled stream layer, with shape counts and verdicts (issue #281) |
| `physical_estimates.json`, `physical_estimates.md` | informational density + naive antenna-ratio estimates, definitions and coverage limits in-file, "estimate, not foundry sign-off" (issue #283) |
| `controls/controls.json`, `controls/controls.md` | fault-control evidence |
| `controls/drc_coverage_audit_controls.json`, `.md` | coverage-audit controls 1-5 on synthetic fixtures |
| `controls/physical_estimates_controls.json`, `.md` | estimate calculator controls (union, hierarchy, clipping, grids, ratios, zero-gate/ambiguous accounting, drift) on synthetic fixtures |

## Handoff to #174 and #170

- **Extracted whole-block connectivity contract:** `trng_whole.layout.spice`
  (top `trng_whole`, 123 pins named exactly as in `layout/trng_whole/interface.md`
  and `trng_whole.ref.spice`), reproducible by `klt extract` with
  `extract.request.json`. Its devices are the 264 analog MOSFETs; the digital
  macro is 8605 black-box cell instances.
- **Not available from this verification (do not infer):** parasitics
  (`klt extract --parasitics` was not run), coupling between the
  `vdd`/`vddr1`-`vddr4` routes, IR drop, period scatter, PVT and every
  DR-0003 section 8 / DR-0009 measurement obligation; digital cell internals
  and substrate (L1, L2); device bodies (L3); area (L12, Unmet).
- **For a post-layout campaign:** tie each record to `trng_whole.gds`
  `sha256:af2f8dfe…`, to `verify.json`, and to the pin set above. Multi-corner
  or Monte Carlo grids go through `klt sim` (batch backend), never hand-launched.
- **Tool friction filed (generic):** klayout-tools#2853 (mixed-level LVS needs
  a pre-extracted netlist, dropping `body_verification`/`power_connectivity`)
  and klayout-tools#2854 (a declared pin set cannot yield canonical pin names),
  klayout-tools#3092 (deck rule layers cannot be mapped to stream
  layer/datatype from CLI JSON).
