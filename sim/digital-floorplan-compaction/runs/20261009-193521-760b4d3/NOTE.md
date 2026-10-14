# Run 20261009-193521-760b4d3 -- tool-drift control, NOT the study

Started by an earlier builder session for issue #226 with PyPI
`klayout-tools==0.6.0` in a throwaway venv. That build reports `klt 0.6.0`. It is
not the `tool-pins.json` build `0.6.0+g10f3da34c088`, so the harness ran with
`--allow-tool-drift` and recorded the drift.

- `util40/`: completed, exit 0. Its routed GDS, DEF and as-built Verilog are
  **byte-identical** to the committed `layout/trng_digital/` geometry. Its
  DRC, LVS signal compare, 16-corner STA, cosim and all four negative
  controls agree with the baseline. The one difference is **LVS
  `power_connectivity: mismatch`**: `power.inconsistent_pin_net` on `VPB`,
  reaching 43 distinct nets. The pinned build reports `match` on the same
  bytes. Identical geometry with a different verdict means the two builds'
  checkers differ; the layout does not. The finding has the shape of the
  well-body false positive in klayout-tools#2082. That issue closed on
  2026-09-19, before the 0.6.0 PyPI upload on 2026-09-22, so this record
  does not establish which change separates the release from the pinned
  git build (2026-10-03). A confirmatory re-grade of the committed
  `layout/trng_digital/` GDS was run on the host's klt `0.7.0+g86740f86d44f`
  (extract with the same `--abstract-cells` arguments, then LVS against
  `trng_digital.routed.v`; not committed). It gives `match`, 0 errors and
  power_connectivity `match`, so current releases do not carry the
  difference. The 0.6.0 PyPI build's P&R response also omits the per-corner
  `*_violation_count_vs_library` fields, so its `stdout.md` slew/cap
  columns read `None`. The plain per-corner counts in `pnr-output.json` are
  identical to the baseline's.
- `util55/`: stopped part-way through P&R at 2026-10-09T20:19Z, when the study was
  restarted on the exact pinned build (worktree venv,
  `klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@10f3da34c0880daf965ed9635c7146e30ce4fc78`).
  It has no results. It is an abandoned run, not a failure of the floorplan.
- `util65/`: never started.

The study's evidence is run `20261009-202126-760b4d3` on the pinned build.
This directory is kept as-is (append-only) because it shows why the exact
pin matters.
