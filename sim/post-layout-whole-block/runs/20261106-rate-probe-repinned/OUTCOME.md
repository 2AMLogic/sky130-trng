# 100 ns rate probe on the re-pinned netlist, 2026-11-06 -- INTERRUPTED (spot reclamation), no verdict

One unit submitted (`klt sim --backend batch --submit-only --wait-for-capacity 600`), job
`klt-sim-3bdf8c54a5a9`, launched 2026-11-06T18:23:47Z. Accepted without a capacity refusal.
Final state `interrupted`: "spot reclamation notice received; job did not complete -- re-run it",
`elapsed_seconds` 3279 (at 2026-11-06T19:18:36Z), instance `c7i.8xlarge` (spot, us-east-1a).
`--attach` returned `interrupted` and fetched no corner output (only `batch-receipt.json`), so there is
no `ngspice.log`, no measurements, and nothing showing whether the netlist loaded.
Not retried in this pass (issue #441 instruction). Not run locally. `netlist.cir` (4 MB) is not committed;
its sha256 is in `corners/rate-probe-batch/plan.json` (`flat_whole_netlist_sha256` 965f1e6c...).
Client `klt 0.9.2.dev103+g9f4cec35997a`. See `records/20261106-rate-probe-repinned-netlist.md`.
