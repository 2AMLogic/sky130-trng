# raw-bit-volume-campaign

Issue #188. The only transistor-level raw-bit evidence
(`sim/raw-bit-min-entropy/`) is 24 samples per corner at Ts = 100 ns. This slug
supplies **>= 1e5 raw bits per tt/ss/ff corner** as `level: behavioral`
streams from a calibrated model, plus a small independent-seed transistor
cross-check run on the batch fleet.

Why behavioral: the #21 testbench costs ~46 s + ~0.12 s per simulated ns, so
1e5 bits is ~1.4e6 s per corner at Ts = 100 ns and ~2400 s per *bit* at
DR-0003's Ts = 20 us. Splitting into seeds does not cut simulated time.

| File | Role |
|---|---|
| `behavioral_raw_bit.py` | the model (4 free-running rings with white period jitter, XOR, ideal edge sampler), calibration from committed records, cross-checks, stream generation, record minting (`--emit-record`), reproducibility check (`--regenerate-check`) |
| `make-requests.py` | `klt sim` batch requests. Default: the #21 testbench, unmodified, one noise seed per request, tt/ss/ff at 27 C / 1.8 V. `--deck combining`: the combining deck, unmodified, one request per (T, Vdd) point (default the 125 C hot grid), tt/ss/ff bundled |
| `derive-combining.py` | turns the combining batch responses into append-only `ro-array-core-combining` records (deck `let` figures recomputed; raw response kept under `sim/ro-array-core-combining/corners/<id>/klt-sim.json`) |
| `transistor/seed*.klt-sim.json` | committed batch responses (job id in `environment.remote.job_id`) read by the cross-check |
| `records/`, `runs/<id>/` | append-only record (`.md`/`.json`) and the packed-hex bitstreams |

```bash
python3 sim/raw-bit-volume-campaign/make-requests.py REQDIR --seeds 101,102,103
klt sim REQDIR/s101/request.json -o REQDIR/s101/out --format json > REQDIR/s101/resp.json   # KLT_SIM_BACKEND=batch
cp REQDIR/s101/resp.json sim/raw-bit-volume-campaign/transistor/seed101.klt-sim.json
python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --emit-record
python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --regenerate-check sim/raw-bit-volume-campaign/records/<id>.json
```

Calibration PVT points are those that have both a `ro-array-core-combining`
and an `ro-ring-jitter-accumulation` (ring5) record. The #188 record uses
27 C/1.8 V, -40 C/1.62 V, -40 C/1.98 V; issue #197 adds the 125 C end of the
README operating envelope (125 C at 1.62/1.8/1.98 V, tt/ss/ff), see below.
Streams are provisional, simulation-derived, and not an SP 800-90B
or SP 800-22 result (the battery is a separate issue). Records are append-only:
a correction mints a new record naming the one it supersedes.

## 125 C extension (issue #197)

The ring5 jitter records at 125 C already existed
(`20260825-061916-54f5715` 1.62 V, `-061114-` 1.8 V, `-062221-` 1.98 V, all
tt/ss/ff). Only the combining half was missing, so only it was run; both decks
are unmodified and the jitter records are reused, not rerun.

```bash
python3 sim/raw-bit-volume-campaign/make-requests.py REQDIR --deck combining   # p1..p3: 125 C x 1.62/1.8/1.98 V
klt sim REQDIR/pN/request.json -o REQDIR/pN/out --format json > REQDIR/pN/resp.json   # KLT_SIM_BACKEND=batch
python3 sim/raw-bit-volume-campaign/derive-combining.py REQDIR                  # mints the combining records
python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --set hot --emit-record
python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --regenerate-check sim/raw-bit-volume-campaign/records/<hot id>.json
```

**Status: blocked on sim evidence.** The three combining batch submissions were
refused by the fleet (runner klt 0.5.0 vs client 0.6.0,
`batch_runner_version_mismatch`; plus transient `batch_no_capacity` / the
8-instance cap; tool gap filed as 2AMLogic/klayout-tools#2851). No local
fallback was run, and no combining records or hot volume record exist yet.
`PVT_POINTS` therefore still equals the #188 set; the hot points join it
automatically once the three combining records are committed, and the
hot-dependent tests skip (visibly) until then.

`--set hot` mints a record with ONLY the 18 hot streams (3 process x 3 supplies
x 2 Ts, 131072 bits each) and runs the jitter cross-check over all six PVT
points. Failing cross-check rows are listed under "Findings" in the record, not
filtered. There is no transistor-level raw-bit run at 125 C, so the p_hat /
Hamming cross-checks still exist only at 27 C/1.8 V. The #188 record is not
modified or superseded.

## Battery and 90B analysis of these streams (issue #195)

`sim/raw-bit-min-entropy/analysis/raw-bit-battery.py` has an explicit
volume-record input. It reads the source JSON's `streams` manifest, resolves
each file under `runs/<record_id>/`, decodes packed hex MSB first, and aborts
on any missing, malformed, truncated, wrong-length or wrong-hash stream (the
hash is of the hex text without its trailing newline). Per stream it runs the
single-sequence battery, a segmented pass-proportion battery (16 x 8192-bit
non-overlapping segments), and the 90B estimators (min H and binding
estimator), grouped by Ts. Failures are reported, never filtered.

```bash
python3 sim/raw-bit-min-entropy/analysis/raw-bit-battery.py \
    --volume-record sim/raw-bit-volume-campaign/records/<id>.json            # print only
python3 sim/raw-bit-min-entropy/analysis/raw-bit-battery.py \
    --volume-record sim/raw-bit-volume-campaign/records/<id>.json --emit-record
python3 sim/raw-bit-min-entropy/analysis/raw-bit-battery.py \
    --check sim/raw-bit-min-entropy/records/<derived-id>.json                # replay, writes nothing
```

The derived append-only record lands in `sim/raw-bit-min-entropy/records/`
(`level: behavioral (derived)`); `--check` exits nonzero if results, input
hashes or rendered tables change. Runtime is about one minute (pure Python).
