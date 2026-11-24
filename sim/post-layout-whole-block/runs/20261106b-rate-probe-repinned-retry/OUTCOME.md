# 100 ns rate probe on the re-pinned netlist, retry 2026-11-06 -- TIMEOUT at 3480 s (issue #449)

One unit submitted (`klt sim --backend batch --submit-only --wait-for-capacity 600`), job
`klt-sim-c594a1d79240`, launched 2026-11-06T19:49:45Z. Accepted first time, no capacity refusal.
Instance `c7i.8xlarge` (spot, us-east-1f). Polled with `--job-status` until terminal:
`state: failed`, "job command exited 4", `elapsed_seconds` 3489 (2026-11-06T20:48:06Z).
`--attach` collected the corner: `diagnostic: timeout - ngspice did not complete within 3480s, killed`
(`runtime=3480.66s`), 0 of 9 measurements. Not interrupted; no spot reclaim. Not run locally, not retried.
`ngspice.log.gz` holds the load banner and the initial (DC) transient solution only; no transient
progress lines. `netlist.cir` (4 MB) is not committed; its sha256 is in
`corners/rate-probe-batch/plan.json` (`flat_whole_netlist_sha256` 965f1e6c...).
Client `klt 0.9.2.dev111+g978f7464fae1`; client-side PDK `open_pdks f6eeac7dad08...` (via `~/.ciel`;
a second install under `~/.volare` was skipped, same as earlier probes).
See `records/20261106b-rate-probe-repinned-timeout.md`.
