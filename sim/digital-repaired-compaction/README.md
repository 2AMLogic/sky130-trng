# digital-repaired-compaction (issue #251)

Does digital floorplan compaction become acceptable once the slew repair from
`sim/digital-electrical-repair/` (#236) is applied? The original compaction
study (#226) rejected 55 % and 65 % utilisation because they worsened the
unrepaired Liberty max-slew / max-cap violations. This study re-runs 40, 55 and
65 % with `constraints.max_transition_ns: 0.531` and audits each result at final
route at all 16 corners.

**Status: target unchanged (`Area < 0.05 mm2`), unmet. No geometry promoted.**
`layout/trng_digital/` and `layout/trng_whole/` are untouched. Read the record
under `records/` first.

## What runs

- `requests/rep{40,55,65}-slew0531.json`: the #226 `util*` requests plus
  `constraints.max_transition_ns = 0.531` and nothing else. `rep40-slew0531.json`
  is byte-identical to `sim/digital-electrical-repair/requests/slew0531.json`.
- `requests/rep55-slew0524.json`: the budget `derive_limits.py` gives for the
  55 % floorplan (0.524 ns). Kept but **not run**, because 0.531 ns already
  passed everything at 55 %.
- `bin/run-study.sh`: sequential P&R + verification chain
  (`sim/digital-pnr/harness/pnr-and-verify.py`) then
  `sim/digital-electrical-repair/analysis/final_route_audit.py`.
- `analysis/repaired_compaction.py`: arithmetic and reduction, mints the record.
  It reuses the #226 area model and the #236 reduction.
- `runs/<id>/limit-derivations/`: `derive_limits.py` output per #226 unrepaired
  floorplan (40: 0.531, 55: 0.524, 65: 0.533 ns with 10 % margin).
- `runs/<id>/unrepaired-util{55,65}/`: audit inputs copied from the #226 runs
  plus the final-route audit of that unrepaired geometry (the #226 run
  directories are unchanged).

## Evidence notes

- In `runs/20261010-092825-main/exit-codes.txt` each `audit exit 2` line is a
  path bug in the first draft of `bin/run-study.sh` (it called the audit script
  from this directory). The audits were re-run by hand with the correct script
  and `--request`; those lines are labelled "manual rerun". The script is now
  fixed. The failed first audit attempts are kept (`audit-stderr.log` was
  overwritten by the rerun; the exit-code lines are the record).
- The `rep40` first rerun (`exit 1`) missed `--request`, so the audit looked for
  the request under the #236 study.

## Reproduce

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python \
  "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@10f3da34c0880daf965ed9635c7146e30ce4fc78"
PATH=$PWD/.venv/bin:$PATH sim/digital-repaired-compaction/bin/run-study.sh \
  "$PWD/.venv/bin/klt" <run-id> rep40-slew0531 rep55-slew0531 rep65-slew0531   # ~30 min each, sequential
for n in rep40-slew0531 rep55-slew0531 rep65-slew0531; do
  python3 sim/digital-electrical-repair/analysis/summarise_run.py --run-dir sim/digital-repaired-compaction/runs/<run-id>/$n
done
python3 sim/digital-repaired-compaction/analysis/repaired_compaction.py --run <run-id> --emit-record
```

No SPICE is involved. Inputs and tool hashes: `input-hashes.json`.
