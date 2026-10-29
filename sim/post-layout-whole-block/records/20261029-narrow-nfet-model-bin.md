# 20261029 -- whole-block flat netlist: W=0.36 nFET has no model bin (issue #386)

**Claim**: the `ngspice` abort `could not find a valid modelname` on the whole-block
flat netlist (`runs/20261018-probe-attempt/OUTCOME.md`) is a model-selection error, not a
netlist-size or net-name problem, and a recorded transform removes it.

Provisional, simulation-side. Connectivity-only netlist; no whole-block simulation result is
claimed here, and #307 stays unmet until a real fleet run.

## Cause

- The `sky130_fd_pr__nfet_01v8` that `sky130.lib.spice tt` loads (`continuous/models_fet/
  sky130_fd_pr__nfet_01v8.spice`, pinned PDK open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`)
  has a smallest width bin of wmin = 4.2e-7 (bins 4.2e-7, 5.5e-7, 1e-6, 3e-6, 5e-6, 7e-6). Any
  nFET card with W < 0.42 has no bin.
- The 1 760 `L=0.15 W=0.36` cards come from the standard cells' narrow nFETs. In the PDK's own
  `sky130_fd_sc_hd` netlists those devices are `sky130_fd_pr__special_nfet_01v8 w=0.36 l=0.15`
  (flops `dfxtp`/`dfrtp`/`dfbbp`..., 4 per cell; latches `dlxtp`/`dlrtp`..., 2-3; clock gates
  `dlclkp`, 1-2). The PDK's `special_nfet_01v8` is its own subckt with bins 3.6e-7..4.2e-7
  (same ports and instance parameters). The extractor draws no distinction between the two
  (same layers), so it wrote the scalable model.
- This is an **extraction/model-selection artefact, not a layout feature**: the drawn width is
  the standard cells' real 0.36 um and is unchanged. The individual owning cell of the first
  failing instance (`X$2`, 115.33, 5.855 um) was not traced to a single cell name; the PDK
  netlist scan above identifies the cell families that contain such devices.
- The 504-character net names are not the cause (OUTCOME.md, confirmed).

## One-device repro (local ngspice 42, seconds, no netlist)

```
.lib <pdk>/sky130A/libs.tech/combined/sky130.lib.spice tt
X1 d g 0 0 sky130_fd_pr__nfet_01v8 L=0.15 W=0.36   -> could not find a valid modelname
X1 d g 0 0 sky130_fd_pr__nfet_01v8 L=0.15 W=0.42   -> parses
X1 d g 0 0 sky130_fd_pr__special_nfet_01v8 L=0.15 W=0.36 -> parses
```

W = 0.30, 0.35, 0.37, 0.38, 0.39, 0.40, 0.41 on `nfet_01v8` all fail the same way.

## Fix (layer: netlist builder, documented transform 4)

`make-netlist.py` now re-points every `sky130_fd_pr__nfet_01v8` card with W < 0.42 at
`sky130_fd_pr__special_nfet_01v8`. No width or other parameter is changed; nothing is rounded.
It is the model the PDK uses for that exact device in the cells being verified, so it is
the electrically faithful choice, not a workaround. 1 760 cards changed (every W=0.36 card; no
other card touched). Tool gap filed generically: 2AMLogic/klayout-tools#4575.

`trng_whole.sim.spice.gz` regenerated: transform applied to the committed netlist text
(sha256 of the uncompressed result `bd694f2fd52f285bf55e74725c489fd855c73321352a0db26c09d5b7216fa684`).
The ports file is unchanged. `make-netlist.py --check` now reads the committed `.gz` (it previously
looked for a plain `.spice` that is not committed).

## Receipts

- **Distinct-card parse check** (one local ngspice unit per netlist, `.lib tt` + one instance of
  each of the 23 distinct (model, L, W) cards found in the flat netlist + `.end`, no analysis):
  original netlist -> `could not find a valid modelname` on the W=0.36 card; transformed
  netlist -> no error (`no simulations run`, exit 1 is ngspice's no-analysis code). No other
  (type, L, W) combination lacks a bin.
- **Full-flat parse not completed locally**: whole-netlist `ngspice -b` with the 123-port
  instantiation ran 560 s (RSS 8 GB) with no error on the transformed netlist, but the original
  netlist also ran 500 s with no error, so that run does not discriminate; the failure was
  reported by the fleet after ~2844 s of flattening. It was stopped by its time cap
  and is not a pass.
- `make-netlist.py --check`: see the PR description for the result.

## Not done

- **Fresh single-point fleet probe not performed.** It needs the Spot batch fleet, ~47 min of
  fleet time and an operator-visible submit; criterion "gets past parse on the fleet" is
  unverified. #307's hold should be re-checked against that probe, not this record.
