# digital-electrical-repair (issue #236)

Isolated study of the unrepaired Liberty max-slew / max-capacitance violations
in the routed `trng_digital` macro (1167 pin rows summed over 16 corners of the
in-flow global-route *estimate*, from #226). Nothing here edits
`digital/flow/place-and-route/pnr-trng-digital-50khz.json`,
`layout/trng_digital/` or `layout/trng_whole/`, and no geometry is promoted.
The area target (`Area < 0.05 mm2`) is untouched.

The single record is under `records/`. Read it first.

## What runs

`requests/control.json` is the committed request with the netlist path rebased.
The other requests add only `constraints.max_transition_ns` and/or
`max_capacitance_pf` (ns, pF). Each request goes through the unchanged
`sim/digital-pnr/harness/pnr-and-verify.py` chain (P&R, klt DRC, cell-level
LVS, 16-corner setup/hold, routed-netlist cosim, 4 negative controls), then:

| script | role |
|---|---|
| `analysis/final_route_audit.py` | fresh OpenSTA session per Liberty corner over the archived routed DEF + post-route SPEF; `report_check_types -max_slew/-max_capacitance -violators`. klt has no such check (klayout-tools#3005). A corner whose session fails or whose sensitivity probe sees no pins is `unsupported`, never zero. |
| `analysis/summarise_run.py` | per-run summary: estimate (parsed per pin from the retained engine logs, cross-checked to the klt response counts) vs final route vs cost |
| `analysis/derive_limits.py` | derives the tt-deck slew budget from the Liberty limits and the routed slew ratios; prints the per-cell capacitance limit table |
| `analysis/diagnose.py` | groups violating pins by net, driver and fanout |
| `analysis/record.py` | renders the record from run artifacts |
| `analysis/electrical.py` | parsing and the reduction (`sim/tests/test_electrical_reduction.py` pins its contract in CI) |

## Reproduce

No SPICE. The pinned klt (0.6.0+g10f3da34c088) goes in a worktree venv
(`.venv/` is gitignored); run from the repo root, requests run sequentially
(shared `<requests>/.klt` scratch), about 25 min each:

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python \
  "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@10f3da34c0880daf965ed9635c7146e30ce4fc78"
PATH=$PWD/.venv/bin:$PATH sim/digital-electrical-repair/bin/run-study.sh \
  "$PWD/.venv/bin/klt" <run-id> control slew0531
python3 sim/digital-electrical-repair/analysis/summarise_run.py --run-dir sim/digital-electrical-repair/runs/<run-id>/control
python3 sim/digital-electrical-repair/analysis/derive_limits.py  --run-dir sim/digital-electrical-repair/runs/<run-id>/control --klt "$PWD/.venv/bin/klt"
python3 sim/digital-electrical-repair/analysis/diagnose.py       --run-dir sim/digital-electrical-repair/runs/<run-id>/control
```

Runs are append-only evidence; the record cites them. `runs/20261010-control`,
`runs/20261010-cand1` (`slew0531`, `slew0531-cap034`) and `runs/20261010-cand2`
(`slew0700`, a deliberately too-loose budget, kept as a failed attempt).

## Routine P&R now gates on this audit (issue #250)

`sim/digital-pnr/harness/pnr-and-verify.py` calls `final_route_audit.audit()`
on the current run's request and routed DEF + extracted SPEF (step 8) and
reports a separately named verdict, `electrical_final_route`, in
`verdict.json`, the report and the record summary. It is required for overall
success and for `--emit-record`: a violation, a missing/unsupported corner,
a failed session or an audit exception fails it (diagnostics, raw per-corner
logs, input hashes and `electrical-audit.json` are kept under `--out-dir`
first); the other checks' results are unchanged. The in-flow slew/cap columns
stay labelled global-route estimates and gate nothing.

**The unrepaired committed baseline fails this verdict on purpose** (1512 slew
and 50 capacitance violations over 16 corners, see the record). Re-running the
harness on the committed request will therefore refuse to mint until a
separately reviewed geometry repair (e.g. the `slew0531` candidate) is
adopted; the checks were not weakened to avoid that. Committed layouts and
earlier records are untouched. Coverage: nominal interconnect corner, default
(zero) port loading, Liberty limits, sibling OpenSTA session (klt has no native
check), not a foundry sign-off. `sim/tests/test_electrical_final_route_gate.py`
replays the recorded control and `slew0531` sessions through the real audit,
reducer and harness verdict logic.
