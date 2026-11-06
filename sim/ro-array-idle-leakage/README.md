# ro-array-idle-leakage

Issue #201. **Idle / leakage survey** of the committed pre-layout `design/sampler_core.spice` (the four-ring
`ro_array_core`, XOR tree and six `sampler_dff`) with its enables low (rings gated off through `ro_nand2`) and the
sampler idle: `.op` supply current at tt/ss/ff x -40/27/125 C x 1.62/1.8/1.98 V, combined with the library's digital
leakage at a mapped Liberty view. Everything here is **simulation-derived and provisional until silicon**.

This is a *survey*. It measures and reports a standby figure per corner and **recommends** an idle-target value; it
ratifies nothing. `README.md` says the idle target is unset pending this survey, so no claim is made that any README
target "holds" for idle, and the 500 uW *active* figure is context only. Adopting the recommendation, or any violation
of an existing budget, goes to a separate decision-record issue; no spec / README edit is made here.

Record: `records/20261106-185750-8deaf42.{md,json}` (27 assembled-deck units valid; replay with
`python3 sim/ro-array-idle-leakage/analysis/idle_leakage.py --check records/20261106-185750-8deaf42.json`).

| File | Role |
|---|---|
| `testbench/tb_idle.spice` | assembled `sampler_core`, en1..4 = 0, clk = 0, rst_n = Vk, per-rail current sensors, sampler latches clamped to their stable state |
| `testbench/tb_idle_leaf.spice` | the same leaf cells as independent instances at their idle input levels: the "leaf-cell sum" the assembled current is compared against (contention-path signature, DR-0007) |
| `make-requests.py` | writes the `klt sim` requests (`idle` and `leaf` legs, one request per process, 27 units each, `analysis.kind = op`, currents as `expr` measurements); `--probe` writes one single-unit request for a local debug run |
| `analysis/idle_leakage.py` | reduction: analog-to-Liberty view mapping, aggregation, flags, worst corners, record minting (`--emit-record REQDIR`) and replay (`--check`) |
| `records/<id>.{md,json}` | append-only record |
| `corners/<id>/` | exactly what was submitted and the raw `klt sim` responses |
| `../tests/test_idle_leakage.py` | unit tests: all 27 grid points map to a named view, 125 C points flagged extrapolated, tt -40 C fallback, aggregation, flags, invalid-unit rejection |

Reproduce: `python3 sim/ro-array-idle-leakage/make-requests.py REQDIR`, then submit the grid as `klt sim --batch-set
REQDIR/*/request.json` (fleet backend; never hand `ngspice` loops), save each request's report as `REQDIR/<name>/resp.json`,
then `python3 sim/ro-array-idle-leakage/analysis/idle_leakage.py --emit-record REQDIR`.

## Method notes that a reader needs

- **Digital term.** `cell_leakage_power` summed over the mapped `trng_digital` instance counts of
  `sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-synthesize-output.json` (2320 cells). The issue
  text cites record `20261015-214950-df2fc8b` for the counts; that record is the lag-count prototype study and has no
  `trng_digital` instance list, so the `trng_digital` synthesis record is used. Liberty leakage is a flat, state-averaged
  figure, not a worst-state one.
- **Corner mapping** (fixed, see the `idle_leakage.py` docstring): same process; nearest listed temperature; supply at or
  above Vdd for tt/ff, nearest for ss. The library has no 125 C view (hottest 100 C), no tt -40 C view and no tt
  1.62/1.98 V view, so every 125 C digital figure is a lower bound; a separate, labelled exponential-in-T column
  extrapolates it. The recommendation uses the extrapolated worst case.
- **Latch state.** At `clk = 0` each `sampler_dff` slave latch holds its last sampled value, so the `.op` is
  under-determined and has an unstable mid-rail solution (`s = qb` about 0.85-0.9 V) with uA of crowbar current. The
  first grid run landed on it in several units (e.g. ff / 27 C / 1.8 V: 78 uA on the vdd rail). A `.nodeset` hint and
  tighter solver options each only moved the problem to another corner, so the slave node `s` of every flip-flop is now
  held by an ideal source at the rail of the stable state it holds after sampling its own idle input (`q = d`). The
  current each clamp supplies is measured and reported (`i_cl_*`; share of the block current: median 2.7 %, max 4.5 %,
  flagged above 5 %).
- **Solver options.** `gmin = 1e-15`, `abstol = 1e-15`, `reltol = 1e-6`: the default `gmin` (1e-12 S across every junction) is
  not negligible against sub-nA standby currents (leaf deck, ss / -40 C / 1.98 V: 2.7e-10 A at the default vs 1.2e-10 A).
  Raising `itl1` / `gminsteps` as well made other corners fail, so they are not set.
- **Invalid units are rejected, not trusted.** `klt sim` reports a unit that hit ngspice's non-convergence fallbacks as
  `pass` (with a `nonconvergence` diagnostic) and can return negative supply currents; the analysis rejects any unit
  with that diagnostic or a negative rail current. One leaf-deck unit (ss / -40 C / 1.98 V) is rejected this way and its
  leaf cross-check is recorded as unavailable; its assembled-deck figure is valid and unaffected.
- **Run history.** Five earlier grids were submitted and discarded before any was committed (the un-clamped deck with
  metastable latch states; the `.nodeset` deck; a deck with `itl1`/`gminsteps`; and two clamp-deck variants with the
  validity gate being added), each for the reason above. Only the final grid is recorded.
- **Local cross-check** (test plan): a single-unit `klt sim --backend local` run of the final deck at tt / 27 C / 1.8 V
  gives 8.577555 nA, identical to the fleet unit.
- **Not established**: any silicon figure; post-layout leakage; a worst-state digital figure; the idle current of other
  states (rst_n low, clk toggling); fs/sf corners; Monte Carlo.
- **Tool gaps filed** (generic, `2AMLogic/klayout-tools`): #5077 (an `op` of a bistable circuit silently converges to the
  unstable mid-rail solution; no way to pin or detect node states), #5078 (`analysis.kind: "op"` requires an empty
  `args` key). Related existing: #1626 (no leakage field in `klt synthesize`), #2492 (`fail_on_diagnostic`).
