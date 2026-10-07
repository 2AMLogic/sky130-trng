# post-layout-ro-ring5-assembled-181

Issue #184 re-measurement of `sim/post-layout-ro-ring5-assembled/` on the
regenerated (#181) geometry and the re-extracted `layout/pex-ring/` library.
Append-only: the pre-#181 slug is untouched; each record here names the
pre-#181 record it is compared against.

The original campaign used `sim/bin/corner-run.py` (a local per-corner ngspice
loop). Host policy forbids hand-launching a corner grid on the dispatch worker,
so this re-run goes through `klt sim` (batch backend, Spot fleet) instead:

```bash
python3 sim/post-layout-ro-ring5-assembled-181/make-requests.py REQDIR   # p1..p4/{netlist.cir,request.json}
klt sim REQDIR/pN/request.json -o REQDIR/pN/out --format json > REQDIR/pN/resp.json   # KLT_SIM_BACKEND=batch
python3 sim/post-layout-ro-ring5-assembled-181/derive.py REQDIR sim/post-layout-ro-ring5-assembled-181/records
```

`make-requests.py` derives the netlist body and `.meas` cards mechanically from
the committed template deck (same ring ladder, same pre-layout same-deck
control, 160 ns / 5p transient, same four PVT points x tt/ss/ff). The deck's
`let` figures are recomputed by `derive.py` with the same formulas because
`klt sim` `expr` cannot read top-level `.meas` results (klayout-tools#2826).
`@@VDD@@/2` is folded to a literal because ngspice rejects the expression
inside `.meas WHEN`.

| Record | PVT | batch job | compared against (pre-#181) |
|---|---|---|---|
| `20261007-232716-ae3832e` | -40.0 degC / 1.62 V | `klt-sim-2be9ae6950bf` | `20260906-085337-9109b23` |
| `20261007-232717-ae3832e` | 27.0 degC / 1.8 V | `klt-sim-6169cb3e9a0a` | `20260906-085753-9109b23` |
| `20261007-232718-ae3832e` | 125.0 degC / 1.98 V | `klt-sim-4f3a2c51a3e5` | `20260906-090102-9109b23` |
| `20261007-232719-ae3832e` | -40.0 degC / 1.98 V | `klt-sim-acce3e1a1e4e` | `20260906-090413-9109b23` |

## Result

All four records PASS (12 corner runs). Against the pre-#181 records at the
same PVT point and process corner, every ring period (`t_asm_*`), slowdown,
swing fraction and supply current moved by at most 0.36 % (largest at -40 degC /
1.98 V, ss, supply current). The same-deck pre-layout control (design unchanged) reproduced to 0.00 % at
every point, so the macOS-local vs Linux-fleet environment (ngspice-46 in both,
identical sky130 model library sha256) contributes nothing visible, and the
small post-layout movement is attributable to the changed library. The library's total series
R fell about 25 % (extractor effect; geometry contributed 0.0 ohm, see
`layout/pex-ring/README.md`) with C bit-identical, and the ring-level numbers
did not respond measurably. No spec threshold was changed.

Scope and caveats:

- This bounds the sensitivity of the **ring-level** period/swing/current only.
  It is not evidence for the array, sampler or leaf-cell decks (see
  `sim/README.md`), and not a whole-block post-layout result (#18).
- The submitting `klt` was the host install (`0.6.0+g46802dd9d592`), not the
  `layout/pdk.json` pin; the PEX library itself was extracted with the pinned
  build. The fleet's own klt build is not recorded in the response.
- Simulation-derived; provisional until silicon.
