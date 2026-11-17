# 20261115a -- the committed startup-probe requests are known stale in four ways; future-only is reaffirmed and the gap is now pinned by tests (issue #507)

**Claim**: `corners/startup-probe/` and `corners/startup-probe-batch/` were
committed from an older `make-requests.py` than the one on `main`, and all six
`make-requests.py` `corners/*/plan.json` predate the DR-0017 fields. This
record continues `records/20261114b-pwl-hold-point-stimulus-fix.md` (its
"filed as issue #507" handoff): it records the exact gap so it is auditable
without re-running the generator, **reaffirms future-only**, and adds the
generator-side invariant plus a known-stale ledger so the gap cannot widen
silently again. **No measurement is retracted and none is added** -- no
transistor-level whole-block run has ever produced a measurement (all four
`corners/grid-*/report.json` and `corners/startup-probe-batch/report.json` are
`status=error` with zero units and zero measurements;
`corners/startup-probe/report.json` is a 0-byte file). Provisional,
simulation-side, bookkeeping-only. This record supersedes nothing and amends
no DR.

**Level of this result, worded exactly**: a **decision record plus three
unit-test assertions**. Nothing was simulated for this record -- no `klt sim`,
no `ngspice`, no PDK, no fleet submit. It is not a whole-block result and it
does not move #174, #307 or #308.

## The four drifts, measured

Verified 2026-11-15 against `origin/main` `a77db823` by regenerating all four
`--set` groups into a scratch directory under `/tmp` (read-only against the
committed tree) and diffing:

1. **Nine committed measurements probe past the probe's own `t_stop`.** Both
   committed `request.json` files carry `alarm_k36`, `gated_k36`,
   `startup_done_k36` and the same triples at `k42` and `k74`, which `FIND` at
   3970 / 4570 / 7770 ns against the 6-cycle probe's own `.tran` stop of
   **970 ns** (`"args": "20p 970n"`). A `.meas ... AT=` past the transient's
   end cannot resolve; submitted as committed it would read as 9 block
   failures rather than 9 malformed requests. `measurement_count` is 136
   committed vs **127** regenerated. The current generator clips the
   measurement list to `t_stop` (`measurement_cards`'s `add()` returns early
   when `t > t_stop`); the nine are pre-clip residue from the fixed
   `{2, 3, 36, 42, 74, n-1}` scalar-observable `k` set, whose values do not
   shrink when the program is truncated to 6 cycles. No shared measurement's
   SPICE text changes -- a pure clip, not a rewrite.
2. **`startup-probe-batch` timeouts do not match the generator.** Committed
   `options.timeout_s` 14400 vs the generator's **3480**; committed
   `batch.poll_timeout_s` 7000 vs the generator's **3700**.
   (`startup-probe`'s own `timeout_s` 3600 matches.) These two keys plus the
   nine measurements are the entire `request.json` delta; every other key is
   byte-identical.
3. **All six committed `plan.json` predate the DR-0017 fields.**
   `flat_whole_netlist_sha256`, `analog_partition_sha256`,
   `digital_gate_netlist_sha256`, `partition_check` and `provenance` (added by
   #431) are absent from all six (`grid-m40C-1.62V`, `grid-27C-1.80V`,
   `grid-m40C-1.98V`, `grid-125C-1.98V`, `startup-probe`,
   `startup-probe-batch`).
4. **The `netlist_sha256` drift `records/20261114b` deliberately left
   future-only.** The stimulus fix (PR #508) postdates the commit of these
   artifacts, so a regeneration today also moves `plan.json:netlist_sha256`
   on all six dirs. This is not a new finding -- `records/20261114b`'s
   post-fix table pre-computed it -- but it is a fourth thing any
   regeneration sweeps in, so the enumeration here names it.

The regenerated values, recorded so the gap is auditable without re-running
the generator (`trng_whole_gds_sha256` `af2f8dfe...` unchanged; the four grid
`request.json` are byte-identical under regeneration, `cmp` clean):

| corner dir | committed | regenerated |
|---|---|---|
| `startup-probe`, `startup-probe-batch` `measurement_count` | 136 | **127** |
| `startup-probe-batch` `options.timeout_s` | 14400 | **3480** |
| `startup-probe-batch` `batch.poll_timeout_s` | 7000 | **3700** |
| `startup-probe`/`-batch` `plan.json:netlist_sha256` | `e896f8651f03259b...` | `2f8da608858e343d...` |
| all six `plan.json` DR-0017 fields | absent | present |

## The decision: do not regenerate; pin instead

`records/20261114b` chose future-only for the committed artifacts one day
before this issue was filed and explicitly delegated drifts 1-3 here "rather
than fixed inside this stimulus change". A ratified decision is superseded by
a new record, not by a diff (CLAUDE.md), and nothing measured since changes
the arithmetic: a regeneration clears this instance, prevents nothing, and
necessarily sweeps in drift 4, un-deciding `20261114b` for a gap that costs
no measurement. Rejected for the same reason: a `make-requests.py --check`
byte-compare plus CI step -- `make-netlist.py --check` is a byte compare, so
the analogous guard goes red on the first run against all four drifts; it is
a regeneration wearing a guard's clothes.

What this record adds instead (control, registered in CI:
`sim/post-layout-whole-block/test_make_requests.py`, stdlib-only, already run
at `.github/workflows/ci.yml`):

- **the invariant** (drift 1's defect class, fixed where it can recur): every
  emitted measurement's `AT=` **and** `TO=` must sit within its own request's
  `.tran` stop, parsed from `analysis.args`, asserted on generator output
  across all four `--set` groups including the short 100 ns / 500 ns probes.
  `TO=` is asserted because 18 of the 136 cards carry no `AT=` at all (`WHEN`
  and the `AVG`/`INTEG` windows); the test also asserts it visits a non-zero
  number of `AT=`/`TO=` bounds so a drifted pattern cannot pass vacuously.
- **the known-stale ledger** (the recurrence guard): every committed
  `corners/*/request.json` satisfies the same invariant **except** the two
  startup probes, whose violations are pinned to exactly the nine cards
  above. A new corner directory carrying an over-`t_stop` card turns this
  red, and regenerating the startup probes later also turns it red until the
  ledger entry is dropped in the same change -- the ledger cannot go stale
  silently.
- **the timeout pin** (drift 2 as a checked fact): the generator's 3600 /
  3480 / 3700 and the committed divergence 14400 / 7000 are both asserted.

Negative controls, mirroring how `records/20261114b` documents its own:
raising the `add()` clip (compare against `t_stop * 10`) makes the invariant
test fail naming exactly the nine `k36`/`k42`/`k74` cards; adding a tenth
fake name to the pinned set makes the ledger test fail. Both were run and
reverted.

The corresponding README correction (`README.md`) drops the present-tense
claim that `plan.json` records the DR-0017 hashes: true of the generator
since #431, false of the six committed plans.

## Consequences

- No file under `corners/` or `records/` is modified, deleted or renamed by
  this change; the append-only check
  (`python3 sim/bin/check_records_append_only.py`) stays green. This record
  is an added file.
- Nothing reads the committed `netlist_sha256` values as a live contract
  (`analysis/reduce-whole-block.py` only copies them into report provenance;
  `make-requests.py` has no `--check`), and `make-requests.py` refuses a
  non-empty request directory, so the next whole-block run necessarily
  generates a fresh corner directory with a fresh, fully-populated
  `plan.json`.
- The `{2, 3, 36, 42, 74, n-1}` scalar-observable set stays a hard-coded
  literal: changing it would churn the four grid `request.json`, which are
  byte-identical and correct. The clip already contains it.
- Dropping the ledger entry requires either regenerating both startup-probe
  dirs or a new decision record continuing this one.
