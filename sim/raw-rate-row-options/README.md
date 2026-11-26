# raw-rate-row-options

Issue #600. Evidence study for the README's `> 1 Mbps` raw-rate row: the two
structural levers the XOR width-scaling experiment (#282,
`sim/xor-combining-alternatives/`) did not touch, each and combined, against the
unchanged rate, power, area and idle rows. Everything here is
**simulation-derived and provisional until silicon**. It chooses nothing:
no target, schematic, layout or DR status is amended, and no implementation
issue is filed from it.

| Lever | Definition |
|---|---|
| `S` (sample-before-combine) | one `sampler_dff` per ring (the `ring_bit` taps `sampler_core.spice` already instantiates), XOR taken digitally after sampling, so `N_max_combine` no longer applies. Not drawn anywhere: adopting it is a topology decision needing its own ratified record (README row 1 says "XOR-combined ahead of a single sampler"). |
| `J` (higher-Q ring) | Three inversions (`ro_nand2` + 2 `ro_stage`) compared with five at fixed device widths and lengths. The 27-point five-stage jitter fit varies only process, voltage and temperature. The direction of a width or length change remains unknown. |

Four configurations, one `klt sim` matrix, nothing hand-launched (13 requests,
39 units; the process axis rides inside each request):

| Config | Deck | Role |
|---|---|---|
| `ctrl5` | `tb_ring_jitter_klt.spice` | the committed 5-stage transient-noise jitter vehicle itself at ss/tt/ff, -40 C, 1.62 V -- baseline control vs committed record `20260825-060208-54f5715`. Two-tier gate: `tbar` +-(1/2)% (deterministic), `sigma_1` statistical (+-(35)% at the binding corner `ss`, +-(60)% coarse elsewhere, plus a same-build draw-envelope check) because ngspice-47 `trnoise` is not same-seed replayable. |
| `ring3` | `tb_ring_jitter_klt.spice` | the 3-inversion ring's jitter + swing on the noise vehicle, 4 (T,V) x {tt,ss,ff}. |
| `sc5` | `tb_ring_swing_current_klt.spice` | the committed deterministic swing/current deck (`sim/ro-ring5-swing-and-current/`'s own method) re-run on its own 4 x 3 grid -- deterministic baseline control: loaded `tbar`/swing +-(2)%, currents +-(5)% vs the four committed records. |
| `sc3` | `tb_ring_swing_current_klt.spice` | the same measurement on the 3-inversion ring: its own LOADED period (no ratio estimate), its own per-ring supply current for the power row, and the buffered-output swing that answers DR-0002 Sec 2's sub-five-stage question. |

| File | Role |
|---|---|
| `testbench/tb_ring_jitter_klt.spice` | transient-noise jitter vehicle template, method-derived byte-for-byte from `sim/ro-ring-jitter-accumulation/testbench/tb_ro_ring5_jitter.spice` (same trnoise calibration NA=2.0e-3/NT=2e-10, same `.option seed=1`, same tstop/TMAX); the `.control` estimator is re-expressed as `.meas` cards because the klt sim runner owns the deck's single `.control` block |
| `testbench/tb_ring_swing_current_klt.spice` | deterministic swing/current template, derived likewise from `sim/ro-ring5-swing-and-current/testbench/tb_ro_ring5_swing_current.spice` |
| `make-requests.py` | builds the decks and the 13 `klt sim` requests; asserts 39 jobs |
| `reduce.py` | fail-closed reduction; `--emit-record REQDIR`, `--check RECORD` (replay from committed raw responses), `--known-answer` |
| `records/<id>.{md,json}` | append-only record |
| `corners/<id>/` | per request: `*.klt-sim.json.gz` (raw response, job id inside), `*.request.json`, `*.netlist.cir`, `*.plan.json` |
| `../tests/test_raw_rate_options.py` | unit tests (no simulator) |

```bash
python3 sim/raw-rate-row-options/make-requests.py REQDIR                     # 13 requests = 39 jobs
uvx --from "klayout-tools==0.9.1" klt sim REQDIR/<d>/request.json -o REQDIR/<d>/out \
    --format json --wait-for-capacity 600 > REQDIR/<d>/resp.json            # KLT_SIM_BACKEND=batch
python3 sim/raw-rate-row-options/reduce.py --emit-record REQDIR
python3 sim/raw-rate-row-options/reduce.py --check sim/raw-rate-row-options/records/<id>.json
python3 sim/raw-rate-row-options/reduce.py --known-answer
python3 sim/tests/test_raw_rate_options.py
```

Client note: the fleet runner (klt 0.9.0) refuses 0.8.0 clients
(`batch_runner_version_mismatch`), so submissions use `klayout-tools==0.9.1`
(the version this repo's pdk-nightly workflow already pins) even though CI's
sim pin remains 0.8.0 -- see the friction ledger.

## Method

Reduction (`reduce.py`), inheriting every law unchanged from the committed
records: `Q_ring = sigma_1^2 T_s / T_0^3` (quadrature-corrected `sigma_1`,
floor 0.646 ps), `Q_array >= M*Q_H0` = 5.946e-3, `N_max_combine =
floor(T_0_loaded / (2 w_90))`, per-ring active current from the sc decks'
worst point, area from two anchors (DR-0003 Sec 7 device-count floor; the
`sampler_core` macro's um2/device), idle scaled from the standby survey, lock
proximity from the committed mismatch model's figures plus the wstv-span
spacing arithmetic. Two baseline controls run before any new number is
trusted; replay compares all saved reduction and control fields. The decks
use ideal DC rails. Applying the stage-count result to hardware requires
pin-level droop and ripple evidence at the new ring frequencies under
Proposed DR-0012. The study assumes no particular regulator or filter.

## Findings (record `20261121-115332-7b5b48ca`)

- `sc5` reproduces the committed deterministic grid to <0.5% at every point
  (tbar to 1e-3); `ctrl5`'s `tbar` to +-(0.02)% with `sigma_1` inside the
  statistical gates.
- Lever J: **4.0x** ring5's per-ring `Q` at the entropy-binding corner (law
  says 2.8x), `N_min_entropy(1 Mbps)` = 20; but ring-node swing is below
  DR-0002's 0.80 bar at **every** point (worst 0.165 at ff/125 C/1.98 V, where
  the buffered output no longer squares up either), and `N_max_combine`
  drops to 2 -- the J-only ceiling is 104 kbps.
- Lever S removes the combining cap. The entropy model requires N = 78
  (ring5) or 20 (ring3) at 1 Mbps. Rings and buffers alone draw 3.4–10.3×
  the active-power budget at those counts. The limiting quantity is
  the **per-ring active supply current at ff/125 C/1.98 V against the
  < 500 uW row**, with lock proximity structural above N ~ 8.
- **Negative result.** Giving all 500 µW to rings and buffers limits S+J to
  five rings and a conditional upper bound of 260 kbps (585 kbps for a 50%
  larger `sigma_1`). Five rings, buffers and DFFs occupy an estimated
  0.013888 mm². The committed digital macro alone occupies 0.06005 mm²
  against the 0.05 mm² whole-block target. Whole-block feasibility remains
  unestablished given the missing floorplan, unmeasured block overhead and
  observed ring3 swing.
