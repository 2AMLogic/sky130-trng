# Roadmap

sky130-trng ports the gf180-trng ring-oscillator entropy source to SkyWater sky130 to find out what breaks in
the PDK, the deck and the tools.

Status as of 2026-11-13, `main` @ `9185beff`. Issue and PR numbers are this repo's unless prefixed.
[`WORK_PLAN.md`](../WORK_PLAN.md) is a generated snapshot of label state; this file gives the order and why.

## Where it stands

Position on the README's maturity ladder: composed layout with section-level evidence, whole-block curated-deck
DRC and mixed-level LVS within stated coverage
([`layout/trng_whole/verify/`](../layout/trng_whole/verify/README.md)); whole-block post-layout characterization
is not done.

The graded verdict is [`signoff/t1-report.json`](../signoff/t1-report.json) (`klt signoff` 0.8.0, re-rendered
and byte-diffed in CI): **15 of 22 T1 rows met.** Tracker: #3.

| T1 item | Analog | Digital | Why a row is unmet |
|---|---|---|---|
| 1 Design sources | met | met | |
| 2 Layout | met | met | |
| 3 DRC clean | met | met | |
| 4 LVS clean | met | met | |
| 5 Full corner verification vs a ratified spec | unmet | unmet | no `klt sim` envelope cited (analog); STA and functional reports exist but the spec is not ratified (digital) |
| 6 Monte Carlo for statistical claims | unmet | unmet | no `klt yield` report |
| 7 Post-layout verification | unmet | met | no `klt pex` report; post-layout campaigns use `klt extract --parasitics` netlists, which item 7 does not accept |
| 8 Characterization report | unmet | unmet | report overall `fail`: 6 met, 3 unmet, 1 not measured of 10 targets |
| 9 Testbenches shipped | met | met | |
| 10 Repo hygiene | met | met | |
| 11 Power delivery (structural) | met | met | |

The reasons are spelled out in [`signoff/block-manifest.json`](../signoff/block-manifest.json) and
[`signoff/characterization-report.md`](../signoff/characterization-report.md). The three unmet targets are raw
rate (50 kbps operating point against > 1 Mbps, DR-0003), raw min-entropy (one tt local-mismatch record below
the 0.5 floor, #221) and area (0.126 mm² composed against < 0.05 mm²). Power is "not measured" because the
report declares no evidence mapping for it.

Decision records: DR-0017 (reduced-work whole-block PVT) and DR-0018 (idle power envelope) are Accepted; the
other fifteen are Proposed. DR-0013 exists only in open PR #249.

Whole-block PVT (#174, #307): 0 of 12 points have run to a verdict. The flat transistor-level netlist timed out
at the 3480 s unit ceiling twice on a 100 ns probe
([record](../sim/post-layout-whole-block/records/20261106b-rate-probe-repinned-timeout.md)). The analog chain
alone is feasible (500 ns in 28.7 s,
[record](../sim/post-layout-whole-block/records/20261105-analog-chain-probe.md)), and the DR-0017 generator,
partition check and reducer are merged (PR #438). What is missing is the gate-level digital half in ngspice and
a measured full-block rate.

Tool pins are split: `signoff-check` grades on klayout-tools 0.8.0, while `layout/pdk.json` still pins
`0.6.0+g5edb557f91d0`, and `pdk-nightly` is red on the layout drift guard (#383, parked on #372). Leaf cells are
regenerated under 0.8.0 (#369, #370 closed); composites are not (#371).

## Now (can start today)

1. **Correct the stale decision-record status text.** `README.md` says every record is Proposed,
   `spec/README.md` lists DR-0017 as Proposed, and row E of `docs/chipalooza/challenge-4-proposal.md` says the
   leakage survey has not run. `tools/check_spec_index.py` passes anyway because it reads the first status word
   in a record's `## Status` history. Done when the three places and the checker follow the record front matter
   and `signoff-check` passes. No issue yet.
2. **Give the characterization report a Power row mapping.** Done when `sim/bin/characterization_report.py`
   declares `EVIDENCE["Power"]`, the idle check reads the idle-leakage record against DR-0018's 200 µW envelope,
   the whole-block active check is declared against a record that does not exist yet (so the row
   stays `not measured`), and the regenerated report and envelope pass their CI byte-diff. No issue yet.
3. **Choose and evidence the ngspice realisation of the gate-level digital half** (first open item of #431 step
   2; DR-0017 leaves event-driven co-simulation versus a timed-delay netlist to the follow-up). Done when a
   generator builds it from `layout/trng_digital/trng_digital.routed.v` for one Liberty corner, a unit test
   checks instance and port correspondence, and a dated record under `sim/post-layout-whole-block/records/`
   states the measured wall-clock per simulated nanosecond, or the negative result. Tracked by #431, which still
   carries a blocked label from before DR-0017 was accepted.
4. **Get the open_pdks re-pin green** (#314, PR #316). Done when PR #316 passes CI with every pin location at
   `f6eeac7`, ciel provisioning, and a PDK search that reports a revision mismatch instead of using the first
   tree it finds. The PR is open and failing CI.
5. **Merge the klayout-tools 0.8.0 whole-block verify adaptation** (#381, PR #388, approved); first link of Next.

## Next (unblocked by a named item)

- **Regenerate composite cells, `trng_digital`, `trng_whole` and the pex libraries under 0.8.0** (#371, PR
  #382). Done when every cell is DRC and LVS clean with 0.8.0 provenance and `compose-cell.py --check` passes in
  a clean venv. After #381.
- **Move the layout klt pin** in `pdk-nightly.yml`, `layout/pdk.json` and `REPRODUCE.md` together (#372). Done
  when `pdk-nightly` is green, which closes #383 and the tracker #366. After #371.
- **Re-qualify reference records under open_pdks `f6eeac7`** (#315). After #314; old records stay append-only.
- **Finish DR-0017 option (b)** (#431): boundary-load model and Liberty deck per (T, Vdd) point stated with
  their source, a measured full-block run, and `GRID_TIMEOUT_S` / `poll_timeout_s` set from it. After Now item
  3. A rate over the 3480 s ceiling is recorded as a negative result and stops there.
- **Run the 12-point whole-block matrix** (#307): tt/ss/ff at the four ratified (T, Vdd) points, reduced with
  `reduce-whole-block.py --emit-record`. After #431. O5d, O7 and O8 stay UNMET under DR-0017, so this does not
  by itself meet #18 AC3.
- **Measured per-supply currents for static IR and digital dynamic power** (#308), replacing the assumed ring
  loads. After #307; the `klt power` coverage limit is klayout-tools#3124.
- **T1 item 7, analog: a `klt pex` report for `sampler_core`** cited in the manifest. After #372, so the report
  is produced by the pinned tool on regenerated cells. No issue yet.

## Later (each needs an answer first)

- **T1 item 5, both partitions.** Which spec does the grader read as ratified? DR-0010 is the packet for the
  README target table; DR-0004 gates the digital row. The digital STA and functional reports already exist.
- **T1 item 6.** Which spec rows are statistical, and can the local-mismatch Monte Carlo
  (`sim/local-mismatch-monte-carlo/`) be expressed as a `klt yield` report with a seed, sample count and
  negative control?
- **Raw min-entropy below the floor at tt** (#221, DR-0013 in PR #249): amend the floor, the operating point or
  the lock-proximity criterion, or add trim or selection?
- **Raw rate and area.** Both targets are unmet by the chosen architecture (about 78 kbps ceiling; 2.52x area).
  DR-0010 presents the dispositions; nothing is decided.
- **External interface.** DR-0011 recommends a wrapper against an assumed pin budget; no wrapper exists and the
  `ro_mon` monitor pin is not implemented. Is the budget assumption right?
- **End-of-life Vth drift** (#262): adopt a lifetime, a guard band or a re-sizing?

## Blocked and waiting

- **Ratification.** Fifteen decision records and the README target table are Proposed. T1 item 5 and the
  Chipalooza submission status both wait on it.
- **Whole-block chain:** #18 (AC3) <- #170 <- #174 <- #307 <- #431.
- **Held PRs:** #464 (netlist through `klt netlist`, #460) is approved and held; #249 (DR-0013) has changes
  requested; #382 is labelled blocked; draft #231 (CI wiring guard, #230) is titled as held for #218, which is
  closed.
- **Operator-labelled:** #360 (item 1 analog attestation; the row already renders met), #463 and #475 (CI and
  `package.json` cleanups), #5.
- **Labelled blocked:** #347 and #356 (evidence bytes in the artifact store, DR-0016 Proposed), #289 (seeded
  cross-checks beyond nominal PVT), #470 (SPICE continuation-line folders).
- **Upstream:** the klayout-tools issues this repo cites are indexed in [`friction-ledger.md`](friction-ledger.md).

No open issue is ready for a Builder as labelled today: Now items 1 to 3 need an issue or a label fix, 4 and 5 are PRs.

## Not planned

- A DRBG or seeding semantics: entropy source only.
- Relaxing a target to make a result pass; changes go through `spec/` with a decision record.
- A foundry sign-off claim. Verification here is the curated deck and a mixed-level LVS, and the README says so.
