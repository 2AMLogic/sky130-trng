# xor-combining-alternatives

Issue #282. Evidence for DR-0010's operator-owned raw-rate row: does one concrete device-sizing
alternative for the XOR combining gate move the ~78 kbps architectural ceiling derived in DR-0003?
Everything here is **simulation-derived and provisional until silicon**, and deterministic (no injected
noise). It does not choose or amend the rate target.

The committed `N = 4` combiner is already a balanced three-gate, depth-2 tree (`design/ro_array_core.spice`:
`xa1`(ro1, ro2), `xa2`(ro3, ro4), `xa3`(t1, t2)), so "balanced tree versus chain" is not an alternative.
Exactly two variants are compared; the topology and `N = 4` are held fixed:

| Variant | Definition |
|---|---|
| `base` (control) | the committed minimum-width `xor2`, byte for byte |
| `w2x` | every MOS width in the `xor2` subcircuit multiplied by exactly 2 (all three tree gates and the pulse-bench gates are instances of that one subcircuit). Lengths and `mult` untouched; `ad/as`, `pd/ps`, `nrd/nrs` follow the relations the committed netlist obeys (`0.29 W`, `2 (W + 0.29)`, `0.29 / W`), checked on the baseline before scaling. The scaled subcircuit exists only inside the generated decks; `design/` is never written. |

| File | Role |
|---|---|
| `testbench/tb_xor_alternatives.spice` | circuit-body template: four independent circuits (pulse-width bench, full `N = 4` array, root `sampler_dff` load, input-capacitance probes) with separate supplies |
| `make-requests.py` | builds the decks and the `klt sim` requests; asserts exactly 18 unique jobs |
| `reduce.py` | fail-closed reduction; `--emit-record REQDIR`, `--check RECORD` (replay from committed raw responses), `--known-answer` |
| `records/<id>.{md,json}` | append-only record |
| `corners/<id>/` | per request: `*.klt-sim.json.gz` (raw response, job id inside), `*.request.json`, `*.netlist.cir` (exactly what was submitted), `*.plan.json` |
| `../tests/test_xor_alternatives.py` | unit tests (no simulator) |

```bash
python3 sim/xor-combining-alternatives/make-requests.py REQDIR          # 6 requests = 18 jobs
uvx --from "klayout-tools==0.8.0" klt sim REQDIR/<d>/request.json -o REQDIR/<d>/out --format json > REQDIR/<d>/resp.json   # KLT_SIM_BACKEND=batch
python3 sim/xor-combining-alternatives/reduce.py --emit-record REQDIR
python3 sim/xor-combining-alternatives/reduce.py --check sim/xor-combining-alternatives/records/<id>.json
python3 sim/xor-combining-alternatives/reduce.py --known-answer
python3 sim/tests/test_xor_alternatives.py
```

## Method

Grid: DR-0003's nine points, -40 C / 1.62 V, 27 C / 1.80 V, -40 C / 1.98 V, each x `tt`/`ss`/`ff`. One
request per (variant, temperature, supply) carries the three process corners as three units, so the 18
jobs are six batch requests; nothing is hand-launched.

Per job, one deck, one transient (`5p 200n`):

- **Component, `w_90`**: the committed nine-width fanout-1 pulse chain (8 ps edges, `w` = 500..25 ps,
  8-12 ns window), interpolated with the committed rule (`operating-point.py: interpolate_w90`, imported
  not copied).
- **Upstream ring-driver load / complete tree**: the committed `ro_array_core` with the variant's XORs
  (enable release at 5 ns, 60-200 ns window): four ring periods (10-period spans), root swing, DC level,
  edge retention at `N = 2` and `N = 4`, ring / XOR+buffer supply currents, total current, `P = I Vdd`.
  The XOR and `ro_buf` share the block `vdd` in the committed netlist, so their current is one component.
- **Downstream sampler load**: the same `sampler_dff` (clk low = transparent) on `xo` in both variants, on
  its own supply so it is not in the array current (its D input is still charged by `xa3`, which is real).
- **Capacitances (fF)**: effective switched capacitance `-integral(i dt) / Vdd` of a 0 -> Vdd ramp: xor2
  pin a, xor2 pin b (other pin low, output driving one further `xor2`), and the `sampler_dff` D pin. The
  sampler figure is reported separately and never added to the first-stage input load.
- **Area proxy (um2)**: sum `W x L x mult` over the MOS of the three XOR instances (5.670 baseline, 11.340
  2x). Device area only, not placed or routed area.

`T_0_loaded` is the period of ring 1 (`wstv` = 0.42, the reference ring of
`sim/ro-ring5-swing-and-current/`) inside the variant's own array deck; the other three are recorded and an
informational `N_max_combine` with the fastest ring at each point is printed beside the binding value.

Reduction (see `reduce.py`): `N_max_combine(point) = floor(T_0_loaded / (2 w_90))` at all nine points,
binding = minimum; entropy replay `N_min_entropy = ceil(M Q_H0 / Q_ring)`, `Q_ring = sigma_1^2 T_s /
T_0_loaded^3`, with the **variant's** `T_0_loaded` at ss / -40 C / 1.62 V; highest raw rate for an integer
`N` (at `N = N_max_combine`) and, separately, at the committed `N = 4`.

Fail-closed: a missing/failed/non-finite measurement, a missing grid point, a `w_90` that never crosses
0.90, or a baseline control outside +-5 % (`w_90`, vs `sim/xor-combining-bandwidth/`) or +-2 % (loaded
period, vs `sim/ro-ring5-swing-and-current/`) aborts with no record.

## Findings (record `20261011-074331-ba1ae9e`)

All 18 jobs passed on the batch fleet (six requests, jobs `klt-sim-423f7409f9af`, `61d3bd592df9`,
`fbd3b56e91aa`, `0d67bb60175c`, `34ef67099385`, `664c0a0147af`), and the baseline control reproduced the
committed evidence at all nine points: `w_90` within +0.09 % / -0.01 % (gate +-5 %), ring-1 loaded period
within -0.76 % to -1.11 % (gate +-2 %; the in-array period is consistently ~1 % shorter than the isolated
ring5 `tbar`).

| | baseline | 2x width |
|---|---|---|
| `w_90` at the binding ff / -40 C / 1.98 V (single gate) | 122.10 ps | 116.01 ps (-5.0 %) |
| `w_90` at ss / -40 C / 1.62 V | 241.29 ps | 229.64 ps (-4.8 %) |
| first-stage input load, pin a / b (mean over grid) | 3.66 / 4.38 fF | 7.24 / 8.69 fF (+98 %) |
| loaded ring-1 period, ff / -40 C / 1.98 V | 1.5968 ns | 1.5884 ns (-0.5 %) |
| root sampler `D` load (unchanged cell, reported apart) | 5.34 fF | 5.34 fF |
| complete-tree edge retention `N = 4`, min over grid | 0.493 | 0.493 |
| total active power, mean over grid | 235.6 uW | 350.8 uW (+49 %) |
| XOR device-area proxy (not layout) | 5.670 um2 | 11.340 um2 (+100 %) |
| `N_max_combine` (binding point) | **6** at ff / -40 C / 1.98 V | **6** at ff / -40 C / 1.98 V |
| highest raw rate at any integer `N` (`N = 6`) | 79.46 kbps | 80.15 kbps (+0.9 %) |
| rate at the committed `N = 4` | 52.98 kbps | 53.43 kbps (+0.9 %) |

Reading: doubling the XOR widths sharpens the single gate by about 5 %, but `floor(T_0 / (2 w_90))`
stays at the same integer at the binding point, so the ceiling moves by under 1 % (`N_max_combine = 6`
is unchanged). The upstream ring-driver load doubles but the ring periods barely move; the cost is paid in
supply current (+49 % power) and device area. Complete-tree edge retention is unchanged at the worst point.
The 2x variant therefore does **not** change the evidence behind DR-0010's rate row: the ~78 kbps
architectural ceiling (79.5 kbps here, which uses the in-array ring-1 period; DR-0003's isolated-ring `tbar`
gives 77.67 kbps in `--known-answer`) is a property of the combining-gate bandwidth relative to the ring
speed and is not meaningfully relaxed by this sizing. Informational: using the fastest of the four rings at
each point, `N_max_combine` is 5 for both variants. This is evidence only; the rate target remains the
operator's decision (DR-0010 stays Proposed).

## Caveats

- **Time step.** The committed pulse-width bench runs at 0.5p/12n and the array bench at 5p/200n. The
  fleet's runner (klt 0.5.0) and the only client that talks to it (0.6.0) have no `analysis_steps`, so one
  `5p 200n` transient serves both. On the hardest pulse-width corner (ff / -40 C / 1.98 V, committed
  121.99 ps) the same deck gives 122.10 ps at 5p, 122.02 ps at 2p, 121.99 ps at 1p and 121.99 ps at 0.5p
  (+0.09 % at 5p, local single-corner probe, not part of the recorded evidence), far inside the +-5 %
  gate.
- A first submission used `analysis_steps` (separate 0.5p/12n and 5p/200n analyses). The fleet runner rejected
  it (`batch_runner_version_mismatch`: runner klt 0.5.0 vs client 0.7.0; the 0.6.0 client does not know
  `analysis_steps`), so nothing from that attempt is recorded; the single-transient decks above were
  submitted instead.
- Optimistic 8 ps input edges in the pulse bench (inherited): `w_90` is a best case for the gate.
- Capacitances are state-dependent switched figures at one bias sweep, not small-signal values.
- Pre-layout, no parasitics. Wider devices add layout parasitics this evidence does not include.
