# 20261029 -- whole-block netlist: bin-coverage scan and regeneration check (issue #386, items a/b)

**Claim**: every device card in the committed flat netlist `trng_whole.sim.spice.gz` has a model
bin in the pinned PDK, and the committed netlist is exactly the pre-fix netlist plus transform 4.
Provisional, simulation-side; connectivity-only. Follows (does not edit)
`20261029-narrow-nfet-model-bin.md`. Items (c) fleet probe and (d) #307 re-check are NOT done here.

## (a) Full bin-coverage scan, with a control that can fail

`check-bin-coverage.py` reads the `.model ... lmin/lmax/wmin/wmax` bins from the PDK files that
`sky130.lib.spice tt` loads (open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`: `nfet_01v8`,
`pfet_01v8` from `continuous/models_fet/`, `special_nfet_01v8` from the `__tt.pm3` file) and checks
**every** card (25 355, not just the 23 distinct combinations) against `lmin <= L < lmax`,
`wmin <= W < wmax`, compared in integer nm (the first draft compared floats and falsely flagged
W=0.42, whose edge `0.42*1e-6 != 4.2e-7`; the one-device repro in the earlier record shows 0.42 parses).

Command: `python3 -I check-bin-coverage.py <netlist> --pdk <...>/sky130A`

| netlist | cards | uncovered | exit |
|---|---|---|---|
| control: `git show 5d304686:sim/post-layout-whole-block/trng_whole.sim.spice.gz` (pre-fix) | 25 355 | **1 760** (all `nfet_01v8 L=0.15 W=0.36`) | 1 |
| committed `trng_whole.sim.spice.gz` | 25 355 | **0** | 0 |

Pass = both, as required. Full output:

```
== control: pre-fix netlist (5d304686) ==
netlist: /tmp/prefix386.gz
cards scanned: 25355 (23 distinct model/L/W)
    1760  sky130_fd_pr__nfet_01v8 L=0.15 W=0.36  UNCOVERED
    4613  sky130_fd_pr__nfet_01v8 L=0.15 W=0.42  ok
       4  sky130_fd_pr__nfet_01v8 L=0.15 W=0.52  ok
      32  sky130_fd_pr__nfet_01v8 L=0.15 W=0.54  ok
       6  sky130_fd_pr__nfet_01v8 L=0.15 W=0.55  ok
     462  sky130_fd_pr__nfet_01v8 L=0.15 W=0.64  ok
    5729  sky130_fd_pr__nfet_01v8 L=0.15 W=0.65  ok
      44  sky130_fd_pr__nfet_01v8 L=0.15 W=0.84  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.42  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.44  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.46  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.48  ok
    4833  sky130_fd_pr__pfet_01v8 L=0.15 W=0.42  ok
    1452  sky130_fd_pr__pfet_01v8 L=0.15 W=0.64  ok
       4  sky130_fd_pr__pfet_01v8 L=0.15 W=0.79  ok
     608  sky130_fd_pr__pfet_01v8 L=0.15 W=0.84  ok
    5750  sky130_fd_pr__pfet_01v8 L=0.15 W=1  ok
      12  sky130_fd_pr__pfet_01v8 L=0.15 W=1.68  ok
       6  sky130_fd_pr__pfet_01v8 L=0.25 W=1  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.42  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.44  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.46  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.48  ok
uncovered cards: 1760
exit=1

== committed netlist ==
netlist: trng_whole.sim.spice.gz
cards scanned: 25355 (23 distinct model/L/W)
    4613  sky130_fd_pr__nfet_01v8 L=0.15 W=0.42  ok
       4  sky130_fd_pr__nfet_01v8 L=0.15 W=0.52  ok
      32  sky130_fd_pr__nfet_01v8 L=0.15 W=0.54  ok
       6  sky130_fd_pr__nfet_01v8 L=0.15 W=0.55  ok
     462  sky130_fd_pr__nfet_01v8 L=0.15 W=0.64  ok
    5729  sky130_fd_pr__nfet_01v8 L=0.15 W=0.65  ok
      44  sky130_fd_pr__nfet_01v8 L=0.15 W=0.84  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.42  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.44  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.46  ok
       5  sky130_fd_pr__nfet_01v8 L=2 W=0.48  ok
    4833  sky130_fd_pr__pfet_01v8 L=0.15 W=0.42  ok
    1452  sky130_fd_pr__pfet_01v8 L=0.15 W=0.64  ok
       4  sky130_fd_pr__pfet_01v8 L=0.15 W=0.79  ok
     608  sky130_fd_pr__pfet_01v8 L=0.15 W=0.84  ok
    5750  sky130_fd_pr__pfet_01v8 L=0.15 W=1  ok
      12  sky130_fd_pr__pfet_01v8 L=0.15 W=1.68  ok
       6  sky130_fd_pr__pfet_01v8 L=0.25 W=1  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.42  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.44  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.46  ok
       5  sky130_fd_pr__pfet_01v8 L=2 W=0.48  ok
    1760  sky130_fd_pr__special_nfet_01v8 L=0.15 W=0.36  ok
uncovered cards: 0
exit=0
```

Limit: this proves bin coverage (the failure mode seen on the fleet), not that the whole deck
parses or simulates; other parse errors would not be caught by it.

## (b) Regeneration check, bounded

- `timeout 3600 python3 sim/post-layout-whole-block/make-netlist.py --check` (klt
  `0.8.1.dev702+g29c427336b28`, one process, host shared): **timed out, exit 124, no `check OK`.**
  A timeout is not a failure of this issue (per its scope), but it is also not a pass of `--check`.
- Substitute (seconds): transform 4 (`NARROW_NFET_RE` / `_special_nfet` from `make-netlist.py`)
  applied to the pre-fix netlist text gives output **byte-identical** to the committed gz
  (sha256 `bd694f2fd52f285bf55e74725c489fd855c73321352a0db26c09d5b7216fa684` both). So the
  committed netlist differs from the pre-fix one by transform 4 only. It does not re-prove that a
  fresh extract of the GDS reproduces the pre-fix text.
- Extract time with no progress output is a tool gap: 2AMLogic/klayout-tools#4594.

## Not done

- (c) single-point fleet probe via `klt sim`, (d) re-check of #307's hold.
