# 20261114b -- whole-block deck stimulus: driven inputs now HOLD and switch over 100 ps instead of ramping between cycles; committed corner artifacts are future-only (issue #488)

**Claim**: `make-requests.py:input_cards` emitted every driven input's `PWL`
card from the **change instants only**, and a SPICE `PWL` source interpolates
linearly between its breakpoints, so each input ramped across its whole hold
interval instead of holding and then switching. Each change now carries a hold
breakpoint one `EDGE_NS` (0.1 ns) before it, matching
`make-gate-model.py:stimulus_cards` and the 100 ps edges every `PULSE` card in
this deck family already used. **No measurement is retracted and none is
added**: this record retracts nothing because no transistor-level whole-block
run has ever produced a measurement. Provisional, simulation-side, generator-only.
This record does not amend DR-0017, `GRID_TIMEOUT_S` (21600) or the grid
requests' `poll_timeout_s` (6600), and it does not claim anything for #18 AC3.

**Level of this result, worded exactly**: a **stimulus-generator defect fix plus
its unit test**. Nothing was simulated for this record -- no `klt sim`, no
`ngspice`, no PDK, no fleet submit. It is not a whole-block result and it does
not move #174, #307 or #308.

## The defect, measured before the fix

Reproduced by calling `input_cards()` directly in a read-only Python process at
`origin/main` `78f35df` (the `#486`/PR #489 merge):

- The `limit=6` startup deck emitted
  `Vbus_re bus_re 0 PWL(0.0n 1.800 640.0n 0.000 970.0n 0.000)` -- 1.8 V at
  t = 0 falling **linearly** to 0 V at 640 ns, so **0.928 V at t = 310 ns**.
- Across the full 75-cycle grid program, **344 of 3000 (driven input x capture
  point) samples sat more than 10 % off a rail**; worst `Vbus_addr_0_` at
  cycle 19 (t = 2300 ns), **0.905 V -- essentially mid-rail**. At the 1 mV
  tolerance the new test asserts, the off-rail count is **21 of 240** on the
  `limit=6` startup deck.
- Consequence, stated as what it is: input slew in the generated decks was
  100 ns to hundreds of ns against the deck's own documented 100 ps, and an
  input nominally changing at `t_edge(k) + SKEW_NS` actually crossed its
  threshold somewhere mid-ramp, so the intended `CAPTURE_NS` of settling was
  not what the deck provided. The `i_vdd_w2` / `q_vdd_w2` digital-activity
  windows integrate that slew.

`clk` and `rst_n` were never affected: both are `PULSE` cards with explicit
100 ps edges.

## The fix

`sim/post-layout-whole-block/make-requests.py`: module-level `EDGE_NS = 0.1`
beside `VIH`, and `input_cards.points()` now appends
`(t_change - EDGE_NS, previous_value)` before `(t_change, new_value)`.

- `EDGE_NS` must stay **>= 0.1 ns**: `pwl_card` formats breakpoint times as
  `f"{t:.1f}n"`, so a narrower edge rounds the hold point and the change onto
  the same timestamp -- a duplicate breakpoint, not an edge.
- `bus_re` in the `limit=6` deck now reads
  `PWL(0.0n 1.800 639.9n 1.800 640.0n 0.000 970.0n 0.000)`.
- Changes are `TS_NS` (100 ns) apart and the earliest is at
  `t_edge(1) + SKEW_NS` = 440 ns, so no hold point can precede the change
  before it. An input that never changes still emits exactly its two endpoints.
- `points()` emits logical 0/1; `pwl_card` applies `VIH`, unchanged.

Control, registered in CI: `sim/post-layout-whole-block/test_make_requests.py`
(stdlib-only). It evaluates every emitted card at every cycle's
`t_edge(k) + CAPTURE_NS` and requires every sample within 1 mV of 0 V or `VIH`;
it **fails on the pre-fix shape** with the counts above and passes after.

## The committed corner artifacts are FUTURE-ONLY, deliberately

Issue #488's acceptance criterion 3 allowed either regenerating the committed
`corners/*/plan.json` pairs or recording the change as affecting future runs
only. **Future-only was chosen**, and here is the evidence it was the right
call rather than the cheap one. A regeneration was actually run into a scratch
directory and diffed against the committed artifacts; it would have swept in
three unrelated, pre-existing drifts between the committed artifacts and the
current generator:

1. `startup-probe/request.json` and `startup-probe-batch/request.json` would
   **lose 9 committed measurements** -- `alarm_k36`, `gated_k36`,
   `startup_done_k36` and the same triples at `k42` and `k74`, which probe at
   3970 / 4570 / 7770 ns, far past the 6-cycle probe's own 970 ns `t_stop`
   (`measurement_count` 136 -> 127). The committed requests predate the
   measurement list being clipped to `t_stop`. Retracting them is not this fix.
2. `startup-probe-batch/request.json` would change `options.timeout_s`
   14400 -> 3480 and `batch.poll_timeout_s` 7000 -> 3700 -- timeout churn this
   issue explicitly must not introduce.
3. All six `plan.json` would gain five DR-0017 fields added by #431 after they
   were committed: `flat_whole_netlist_sha256`, `analog_partition_sha256`,
   `digital_gate_netlist_sha256`, `partition_check`, `provenance`.

What makes future-only safe, checked rather than assumed:

- **Nothing reads these `netlist_sha256` values as a live contract.**
  `analysis/reduce-whole-block.py:216` only copies the value into a report's
  provenance block, and `make-requests.py` has no `--check` staleness guard
  (unlike `make-netlist.py`), so no job regenerates and byte-compares them.
- **No committed result depends on the old stimulus.** All four
  `corners/grid-*/report.json` and `corners/startup-probe-batch/report.json`
  are `status=error` with zero units and zero measurements, and
  `corners/startup-probe/report.json` is a 0-byte file.
- **`make-requests.py` refuses to write into a non-empty request directory**
  (`"exists and is not empty; refusing to mix sets"`), so the next whole-block
  run necessarily generates a fresh corner directory with a fresh `plan.json`
  carrying the new `netlist_sha256`. The committed pairs are evidence of what
  was planned, not an input to a future run.
- **The four grid `request.json` are byte-identical under regeneration**,
  confirming that `request.json` carries no deck text: its `netlist` key is the
  literal filename `"netlist.cir"`, and that file is gitignored.

The regenerated `netlist_sha256` values are recorded here so the change is
auditable without re-running the generator (scratch regeneration at this
record's tree, `trng_whole_gds_sha256` `af2f8dfe...` unchanged):

| corner dir | committed `netlist_sha256` | post-fix `netlist_sha256` |
|---|---|---|
| `grid-m40C-1.62V` | `0689fa77bc94c223...` | `66c1c511fa72fa82...` |
| `grid-27C-1.80V` | `6f92eb5d5467a89c...` | `1df798757ddb41de...` |
| `grid-m40C-1.98V` | `9e9ed4e1026a5a41...` | `3853ca34be249a33...` |
| `grid-125C-1.98V` | `ffbe2160d1949db2...` | `b7f761830fc371ee...` |
| `startup-probe` | `e896f8651f03259b...` | `2f8da608858e343d...` |
| `startup-probe-batch` | `e896f8651f03259b...` | `2f8da608858e343d...` |

(The two startup probes share a deck by construction -- same program, same
header, same `t_stop`; only backend and timeouts differ, and neither is deck
text. The post-fix column also carries drift 1 and 3 above, so it is the hash
of a deck generated by the current generator, not of the old deck with only the
stimulus changed.)

The three drifts above are real, pre-existing and **out of scope here**; they
are filed as **issue #507** rather than fixed inside this stimulus change.
Drift 1 in particular (nine `.meas ... AT=` cards past the probe's own 970 ns
`.tran` stop) is its own defect, not a consequence of this one.

## Consequences

- No prior record is edited; no `runs/` or `corners/` artifact is modified,
  deleted or renamed. This record supersedes nothing.
- `20261114-gate-model-realisation.md`'s observation ("A PWL stimulus with only
  change-instants ramps instead of switching") now holds for **both**
  generators in this directory; they no longer disagree about the same
  stimulus.
- Any future transistor-level whole-block grid or probe run gets the corrected
  stimulus automatically. Nothing is re-run for this record.
