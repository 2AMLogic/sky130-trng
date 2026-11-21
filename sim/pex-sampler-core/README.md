# pex-sampler-core

The analog partition's T1 **item 7 (post-layout verification)** evidence
slug: native `klt pex` **schematic-vs-extracted delta reports** for the
whole composed `sampler_core` cell. Filed by issue #597 — item 7 is
kind-restricted (a `klt pex` report is the only envelope the grader
accepts for an analog partition), and before this slug no such report
existed: the `post-layout-*` campaigns are real measurements, but they
run from `klt extract --parasitics` netlists through `sim/bin` harnesses,
which item 7 by design does not accept.

## Why `--measure-command` (and not `klt sim` testbench requests)

Every delta row here reads DUT-internal nets (`ro1`–`ro4`, `xo`) whose
extracted-leg names are KLayout-joined multi-label spellings
(`ro1|ro1_esc|sr1_d_stub|…`) — characters no `.meas` card can quote, and
names that do not exist at all on the schematic leg. Testbench mode
re-runs one byte-identical deck on both netlists, so no single `.meas`
card can express these rows on both legs. `klt pex --measure-command`
keeps the comparison itself in `klt pex`: it runs the committed harness
once per side and computes every `delta[]` row; the harness never
compares the two sides. The measurement mode is disclosed in the
envelope's `measurement` block.

The harness (`harness/pex-measure.py`) renders the committed body
template (`testbench/tb_sampler_core_body.spice` — `sim/post-layout-sampler-core/`'s
own whole-cell deck reduced to one DUT instance) per PVT point and per
leg, applies the committed alias map (`net-aliases.json`, from `klt
lvs`'s own net correspondence) to the extracted netlist it is handed, and
submits one `klt sim` corner request per (temperature, supply) point with
the tt/ss/ff axis bundled in — the grid is expressed as `klt sim`
requests on the batch fleet, never a hand-launched ngspice loop.

## Spec rows

Eleven rows map to the README target-table rows the analog partition
owns: `ring{1..4}_period_ns`, `xo_edge_retention`, `raw_tap_freq_mhz`,
`xo_swing_frac`, `xo_bias_frac` (Entropy source / Raw rate support;
verdicts live in item 8), `active_power_uw` / `reset_power_uw` (Power),
and `sampler_reset_max_v` (Interface). The **only limit** carried is
`active_power_uw` < 500 µW; every other row is limit-free ("measured,
therefore comparable", the same default unlimited `klt sim` gives).

## Records

| Record | Verdict |
|---|---|
| `records/20261121-001303-7330672` (run artifacts under `runs/20261121-001303-7330672/`) | `fail` — 130/132 rows pass; `active_power_uw` fails at `ff/-40C/1.98V` and `ff/125C/1.98V` **on both legs** (pre-layout already 519/567 µW; parasitics add 6–13 %). Follow-up: issue #604. Disclosures (`extraction.model` limits, `body_bias: biased`, PDK/deck pins) in the record and its `.md`. |

The layout regeneration chain (#371/#372, klayout-tools 0.8.0) will
change `layout/sampler_core/sampler_core.gds`; the manifest citation pins
the GDS content hash, so the graded report goes stale the day the
regenerated GDS lands and this slug mints a new record then — that
re-run is part of that chain, not a defect of this one.

## PVT grid

`sim/post-layout-sampler-core/`'s own four-point grid crossed with the
process axis: 27 C/1.8 V, −40 C/1.62 V, −40 C/1.98 V, 125 C/1.98 V ×
tt/ss/ff — 12 corners per leg, both legs on the same batch fleet model
library.
