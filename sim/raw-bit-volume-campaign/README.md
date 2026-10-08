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
| `make-requests.py` | `klt sim` batch requests: the #21 testbench, unmodified, one noise seed per request, tt/ss/ff at 27 C / 1.8 V |
| `transistor/seed*.klt-sim.json` | committed batch responses (job id in `environment.remote.job_id`) read by the cross-check |
| `records/`, `runs/<id>/` | append-only record (`.md`/`.json`) and the packed-hex bitstreams |

```bash
python3 sim/raw-bit-volume-campaign/make-requests.py REQDIR --seeds 101,102,103
klt sim REQDIR/s101/request.json -o REQDIR/s101/out --format json > REQDIR/s101/resp.json   # KLT_SIM_BACKEND=batch
cp REQDIR/s101/resp.json sim/raw-bit-volume-campaign/transistor/seed101.klt-sim.json
python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --emit-record
python3 sim/raw-bit-volume-campaign/behavioral_raw_bit.py --regenerate-check sim/raw-bit-volume-campaign/records/<id>.json
```

Calibration PVT points are the three that have both a `ro-array-core-combining`
and an `ro-ring-jitter-accumulation` (ring5) record: 27 C/1.8 V, -40 C/1.62 V,
-40 C/1.98 V. Streams are provisional, simulation-derived, and not an SP 800-90B
or SP 800-22 result (the battery is a separate issue). Records are append-only:
a correction mints a new record naming the one it supersedes.
