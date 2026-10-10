# measurements

Silicon characterization data. **Empty until silicon exists.** Nothing in this
directory is a simulation result, a projection or a placeholder value: a file
here is a record of something measured on a fabricated die, or it does not
belong here. No measured result exists yet.

What to measure, under which conditions and against which criteria is in
[`spec/silicon-characterization-plan.md`](../spec/silicon-characterization-plan.md)
(Proposed, [DR-0014](../spec/decision-records/DR-0014-silicon-characterization-plan.md)).
This file is the layout contract for the data. Until a measured record
exists, the corresponding repository claim stays "simulation-derived,
provisional until silicon".

## Layout

```
measurements/
  README.md                          this contract
  index.md                           derived listing, regenerated from records (never evidence)
  <slug>/
    README.md                        setup, instruments, how to reproduce the reduction
    records/<rid>.md                 human-readable append-only record
    records/<rid>.json               machine-readable summary (schema below)
    runs/<rid>/                      raw captures and instrument exports (see "Raw data")
```

### Slug convention

- **Same name as the simulation slug it answers.** A measurement of the claim
  tested by `sim/raw-bit-min-entropy/` lives in `measurements/raw-bit-min-entropy/`.
  A reader moving between the trees keeps the same slug, and the plan's
  section 2.1 table already maps every `sim/` slug to its claim row.
- A measurement with no simulation counterpart (pure bring-up, board
  characterization, package ripple attenuation) uses the prefix `bringup-` or
  `board-` followed by a kebab-case topic.
- Slugs are lower-case kebab-case, one directory per slug, never renamed.

### Record id

`<YYYYMMDD>-<HHMMSS>-<shortsha>`: the scheme `sim/bin/evidence_record.py`
`new_record_id()` produces, with the short SHA of the repository commit that
holds the reduction code used. One record per (die, condition set, claim row),
not one aggregate record per campaign, matching the per-(testbench, PVT point)
granularity of `sim/`.

## Record schema

Markdown and JSON pair. The markdown reuses the `sim/` header fields and footer
(`evidence_record.record_footer()`: Author, Timestamp (UTC), Repo commit,
Supersedes); the JSON is a flat summary. Fields marked (sim) are the same as in
`sim/` records; fields marked (new) exist only here.

| Field | Meaning |
|---|---|
| `record_id`, `author`, `timestamp_utc`, `repo_sha` (sim) | as `sim/` records |
| `slug` (sim) | the directory name |
| `claim` (sim) | one-line statement of what the record substantiates |
| `claim_row` (new) | plan row id, e.g. `C1` |
| `level` (sim field, new value) | always `silicon` here. Never `behavioral`, `gate` or `transistor` |
| `die` (new) | die id, wafer/lot, run/shuttle, package, board id. Results are per die; no pooling into process corners |
| `conditions` (new) | actual measured chamber temperature and per-rail voltages (`vdd`, `vddr1..4`), `clk` frequency, enable states; setpoints and readbacks both |
| `instruments` (new) | model, serial and last calibration date for every instrument that produced a number |
| `estimators` (new) | tool, version and commit of the reduction (`raw-bit-battery.py`, `digital/model/`, ...) |
| `sample_count`, `restarts` (new) | volume actually captured |
| `artifacts` (sim) | repo-relative paths under `runs/<rid>/`, each with a `sha256` |
| `results` (new) | the measured quantities with confidence intervals; free-form per slug but documented in the slug README |
| `relation` (new) | `confirms`, `refutes` or `inconclusive`, judged against the plan row's criterion, never against a criterion changed afterwards |
| `supersedes` (sim) | list of fully qualified record references, see below |
| `disclaimer` (new) | replaces the "Provisional, simulation-derived" block with: *Measured on the stated die under the stated conditions. A per-die estimate; not an SP 800-90B validation or AIS-31 evaluation.* |

A record states every seed that exists on the measurement side (e.g. the order
of a randomized PVT sweep), and states plainly when none applies.

### Raw data

- Raw captures are the evidence, reductions are derived from them. Commit them
  under `runs/<rid>/` as text (`.txt`; packed hex for bit streams, like
  `sim/raw-bit-volume-campaign/runs/`), because the repository's `.gitignore`
  does not exempt other extensions. 2^20 bits is 128 KiB packed.
- A capture too large to commit is stored outside the repository and the record
  carries its `sha256`, size, location and the instruction to fetch it. The
  reduction must be re-runnable from the data without the record's own numbers
  (`--check RECORD`, as for `sim/` reductions).
- No simulated, modelled or synthetic stream may be placed here, including as a
  "reference" or "expected" trace. Those belong under `sim/`.

## Append-only rule

Identical to `sim/`: a record is never edited, deleted or renamed after it is
committed. A correction (a mislabelled die, a bad calibration, a reduction bug)
mints a new record whose `supersedes` names the one it corrects. Reviewed
exceptions, if ever needed, go in an allowlist beside the sim one, as a visible
diff, not a bypass.

Enforcement note: `sim/bin/check_records_append_only.py` and its CI job
(`sim-records-append-only`) protect both `sim/` and `measurements/`: every
existing file under `measurements/<slug>/records/` and every existing file under
`measurements/<slug>/runs/<rid>/` (or `corners/<rid>/`) where `<rid>` names a
record of the PR's base tree is rejected if modified, deleted, renamed or
type-changed. Association is keyed by root, slug and record id, so same-named
`sim/` and `measurements/` entries never protect one another. New records and
captures pass; this README and the derived `index.md` stay editable. Reviewed
exceptions use `sim/records-append-only-allowlist.txt` with fully qualified
paths (`sim/...` or `measurements/...`).

## How a measured record supersedes a provisional simulated record

A simulated record is a true statement about what was simulated. It is not
retracted when silicon disagrees with it, and it cannot be edited (CI forbids
it). A measured record therefore **points backward** and never rewrites the sim
tree:

1. The measured record's `supersedes` lists the simulated record(s) it answers,
   fully qualified (`sim/raw-bit-min-entropy/records/20261010-102516-3966094`),
   with `relation` saying whether it confirms, refutes or is inconclusive.
2. The simulated record is left byte-for-byte unchanged. Its own `Supersedes:
   (none)` footer stays.
3. Forward discoverability comes from the plan's section 2 table (which lists
   the sim records per claim row) and from `index.md`, a listing regenerated from
   the measured records' JSON. `index.md` is derived, may be regenerated freely,
   and is never cited as evidence.
4. A claim's status changes from "provisional until silicon" only when a measured
   record exists for its plan row and the status text is updated in the same
   change that cites the record. A `confirms` on one die and one condition
   changes the claim only for that die and condition, as the record states. A
   claim over a population or the whole envelope needs the records the plan row
   lists.
5. A later measured record may supersede an earlier measured one by the same
   mechanism.

Entropy claims in particular stay provisional beyond a single die's measurement:
a per-die estimate is not an SP 800-90B validation (plan, section 1).

## Cross-references

- Reuse, not copy: `sim/bin/evidence_record.py` (`new_record_id`, `record_footer`,
  `mint_record`). Its `mint_behavioral_record()` is not reusable unchanged (it
  writes under `sim/` and appends a simulation disclaimer); a silicon minting
  helper is a follow-up.
- Reductions: `sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`,
  `digital/model/`.
