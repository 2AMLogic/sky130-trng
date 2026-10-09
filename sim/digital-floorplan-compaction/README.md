# digital-floorplan-compaction (issue #226)

Area feasibility study. Can digital floorplan compaction alone move the
composed block toward the unchanged `Area < 0.05 mm2` target? The committed
block is 0.126116 mm2. The `trng_digital` macro alone is 0.06005 mm2.

**Status: target unchanged, unmet.** The record under `records/` holds the
single recommendation. No geometry from this study is promoted:
`layout/trng_digital/` and `layout/trng_whole/` stay on the 40 % baseline.

## What is varied and what is fixed

Varied: `floorplan.utilization_pct` only, at 40 (baseline), 55 and 65
(`requests/util{40,55,65}.json`).

Fixed: everything else in the committed request
`digital/flow/place-and-route/pnr-trng-digital-50khz.json`. That means the
synthesized netlist (same file and sha256), seed 20260905, IO layers, the
`sky130hd` power preset, the 20000 ns clock and 4000 ns IO delays, aspect
ratio 1.0, the 5 um core margin, route as the target stage, and SPEF and SDF
generation. The study requests rebase only the netlist path. Every hash is in
`input-hashes.json`, which you can check with `sha256sum`.

Each request runs through the unchanged `sim/digital-pnr/` chain: P&R, then
klt-deck DRC, cell-level LVS, 16-corner post-route STA, routed-netlist
cosim and the four negative controls. The harness gained `--request` and
`--out-dir`. With neither option it behaves as before. `--emit-record` is
refused with a non-default request, so a study run cannot overwrite
`layout/trng_digital/`. `--out-dir` keeps every klt response, the
negative-control outcomes, the verdict, the per-stage OpenROAD
logs/metrics/scripts (`pnr-engine/`) and gzipped routed artifacts, including
for a run that fails.

## Result (record `records/20261009-214736-760b4d3.md`)

| | util40 (= baseline) | util55 | util65 |
|---|---|---|---|
| die | 245.05 um square, 0.060050 mm2 | 210.46 um square, 0.044291 mm2 | 194.39 um square, 0.037787 mm2 |
| achieved utilisation | 42.63 % | 58.36 % | 68.75 % |
| route DRC, antenna, klt DRC, LVS (signal and power), 16-corner setup/hold, cosim, 4/4 controls | all pass | all pass | all pass |
| library max-slew + max-cap violations, 16-corner total (unrepaired) | 1167 | 1165, but worse at 3 low-voltage ss corners | 1271, worse at 4 ss corners |
| combined area, estimate B (re-stacked, not composed) | 0.126116 mm2 (2.52x) | 0.102693 mm2 (2.05x) | 0.093609 mm2 (1.87x) |

- util40 reproduces the committed `layout/trng_digital/` byte for byte
  (GDS, DEF and routed Verilog), with no tool drift.
- **No candidate is selected.** Both compacted points raise unrepaired
  library-limit violations at some low-voltage ss corners.
- **Compaction alone cannot close the target.** With the committed topology,
  even a square digital macro at 100 % utilisation and no core margin would
  give 0.0795 mm2 (1.59x).
- The analog macro alone uses 38.6 % of the target, and the standard cells
  alone use 46 %.

## Runs

- `runs/20261009-202126-760b4d3/`: the study. It uses the exact
  `tool-pins.json` klt build `0.6.0+g10f3da34c088`. The harness's
  `pnr-engine/` log retention was added while util40 was already running.
  For util40 those files were copied from the klt scratch directory by a
  watcher once its P&R finished and before util55 wiped the directory. They
  are the same files the harness copies for util55 and util65.
  `input-hashes.json` carries the final harness hash. The util40 process ran
  an earlier revision that differs only by that retention block.
- `runs/20261009-193521-760b4d3/`: a tool-drift control on PyPI
  `klayout-tools==0.6.0`. See its `NOTE.md`. Its util40 output is
  byte-identical to the baseline geometry, but LVS `power_connectivity`
  reports `mismatch`. It is not study evidence.

## Reproduce

No SPICE is involved, and nothing touches host-wide tools. The pinned klt
goes into a venv inside the checkout (`.venv/` is gitignored):

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python \
  "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@10f3da34c0880daf965ed9635c7146e30ce4fc78"
.venv/bin/klt --version          # klt 0.6.0+g10f3da34c088
# run from the repo root (the containerised openroad wrapper mounts only $PWD);
# runs are sequential by construction (shared <requests>/.klt scratch), ~30 min each
sim/digital-floorplan-compaction/bin/run-study.sh "$PWD/.venv/bin/klt" <run-id> 40 55 65
python3 sim/digital-floorplan-compaction/analysis/compaction.py --run <run-id> \
  --control-run 20261009-193521-760b4d3 --emit-record
```

`compaction.py` does arithmetic only. It reads the run directories, the
committed baseline (`layout/trng_digital/{pnr,drc,lvs,sta}.json` and the
DEF/GDS hashes) and the committed composition geometry
(`layout/trng_whole/report.json`).

## Area figures

The record reports three numbers per candidate. They are labelled:

- **lower bound**: digital bbox plus analog bbox. Routing, gaps and pads are
  ignored, so no real layout can reach it.
- **estimate A**: the lower bound plus the committed composition's
  non-macro area of 0.046769 mm2, held constant.
- **estimate B**: the committed composition topology re-stacked around the
  resized digital macro. The digital pin edge stays at the lane corridor,
  and the VPWR escape, the digital-to-analog gap, the analog row and the
  pad row are kept. It reproduces 0.126116 mm2 exactly at the baseline
  size.

Neither estimate is a composed or verified layout.
