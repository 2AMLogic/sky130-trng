# area-limiter-study

Area-row evidence study (issue #599): what limits the whole-block layout
against the unchanged `< 0.05 mm2` target, measured per structural option
DR-0010 names. One append-only record under `records/` (raw artifacts in
the fleet artifact store; manifest committed under
`manifests/artifacts/`).

* **Item 1 (measured, `level: gate`)**: functional area attribution of the
  committed unconstrained `trng_digital` netlist — every one of the 2320
  mapped instances owns exactly one row (FIFO storage anchors = the 128
  `raw_mem` + 128 `cond_mem` Q-driven bits), rows sum to the committed
  22,203.7952 µm2 against the pinned Liberty deck
  (`sha256:8e78e14…`). Includes a same-tool baseline control synthesis and
  the depth-2 FIFO variant (`harness/variant_fifo2.v`, exact diff vs
  `digital/rtl/trng_digital.v`) with its functional-suite result against
  the normative model.
* **Item 2 (estimated — placement dry run)**: folded `sampler_core`
  arrangements from the committed cell recipe's own geometry. F1 (samplers
  3+3, ring row byte-identical) is the recommended estimate.
* **Item 3 (measured inputs, exact arithmetic)**: the composition-overhead
  account — non-macro area of the committed whole block decomposed into
  five disjoint rectangles.
* **Item 4 (estimated)**: combined options on the `rep65-slew0531` baseline
  and the committed 40 % baseline, with confidence labels, the
  reachability verdict and the largest remaining limiter.

Nothing here modifies `digital/rtl/`, any committed `layout/` cell, any
decision-record option or the `< 0.05 mm2` row. The whole-block figures
that are not composed-and-verified are labelled estimates, as in #226/#251.

## Reproducing

Cold start (needs `klt`, a native `yosys`, `iverilog`, and an installed
sky130A PDK whose `sky130_fd_sc_hd__tt_025C_1v80` Liberty deck hashes to
`sha256:8e78e144…` — the deck the 20260910-001436-a4c3194 synthesis record
pins; both `~/.volare` and `~/.ciel` roots are searched):

```
python3 sim/area-limiter-study/harness/run-study.py                 # dry run
python3 sim/area-limiter-study/harness/run-study.py --emit-record   # + record
```

Per-piece reruns: `attribute_digital_area.py --liberty <deck> --out …`,
`fold_sampler_core.py`, `composition_overhead.py`, `combine_options.py`
(each is stdlib-only and prints its own JSON). The synthesis requests the
runner copies into its workdir are the committed templates in
`harness/requests/`.
