# local-mismatch-monte-carlo

Issue #215. Local random **device mismatch** (Monte Carlo) of the committed pre-layout
`design/ro_array_core.spice` and of the `sampler_dff` in `design/sampler_core.spice`. Every
earlier record in `sim/` uses global process corners only, which shift all devices together and
so cannot show ring-to-ring spread, ring-pair proximity, or the sampler's decision offset.
Everything here is **simulation-derived and provisional until silicon**. Each draw is a
deterministic transient (no injected noise): this is a static-variation measurement, not an
entropy measurement.

| File | Role |
|---|---|
| `testbench/tb_ro_array_mismatch.spice` | circuit-body template: the array, five ideal rails, enable release at 5 ns, nine behavioural comparators on `xo` (thresholds 0.30..0.70 x vnom) giving the duty at each threshold |
| `testbench/tb_sampler_dff_offset.spice` | circuit-body template: one `sampler_dff`, D driven by a slow triangle while a 10 ns clock samples it; the D value at which Q flips going up and going down is the decision threshold |
| `make-requests.py` | writes the `klt sim` requests (`OUTDIR/<corner>-<kind>-<n>/`): `arr` / `smp` carry a `monte_carlo` block (`vary: "mismatch"`, section `<corner>_mm`); `arr0` / `smp0` are one-unit mismatch-free controls on the plain section |
| `reduce.py` | reduction (standard library only): periods, spread, pair proximity, Q ratio, bias, sampler offset, raw-bit bias, min-entropy bound; `--emit-record REQDIR`, `--check RECORD` (replay from the committed raw responses) |
| `yield_reports.py` | `klt yield` reduction of the same raw responses into per-PVT-point sample sets + reports (issue #598); `--check` byte-replay. Run under `uvx --from "klayout-tools[yield]==0.8.0" python ...` (the host `klt` carries no `klt_yield_native`) |
| `records/<id>.{md,json}` | append-only record per PVT point (one row per Monte Carlo unit, with the per-sample seeds) |
| `corners/<id>/` | per chunk: `*.klt-sim.json.gz` (raw batch response, job id inside), `*.request.json` and `*.netlist.cir` (exactly what was submitted), `*.plan.json` |
| `yield/<id>/` | the `klt yield` evidence per PVT point (issue #598): `samples.json` (the derived sample set, `h_bias_bit` over all 1800 pairings, limits `min 0.5` bit from the spec row as written, no target yield -- none exists on the row) and `klt-yield.json` (the pinned-0.8.0 report); cited as T1 item 6 analog in `signoff/block-manifest.json` |
| `../tests/test_mismatch_reduction.py` | unit tests on synthetic inputs |

```bash
python3 sim/local-mismatch-monte-carlo/make-requests.py REQDIR
uvx --from "klayout-tools==0.8.0" klt sim REQDIR/<d>/request.json -o REQDIR/<d>/out --format json > REQDIR/<d>/resp.json   # KLT_SIM_BACKEND=batch
python3 sim/local-mismatch-monte-carlo/reduce.py --emit-record REQDIR
python3 sim/local-mismatch-monte-carlo/reduce.py --check sim/local-mismatch-monte-carlo/records/<id>.json
uvx --from "klayout-tools[yield]==0.8.0" python sim/local-mismatch-monte-carlo/yield_reports.py          # emit
uvx --from "klayout-tools[yield]==0.8.0" python sim/local-mismatch-monte-carlo/yield_reports.py --check  # byte replay
python3 sim/tests/test_mismatch_reduction.py
```

The grid is `klt sim` requests with a `monte_carlo` block, run on the batch fleet; no
`ngspice` loop was hand-launched. No PDK switch beyond what the pinned `klt sim` exposes was
needed: sky130's own `tt_mm` / `ss_mm` / `ff_mm` library sections (MC_MM_SWITCH=1) are selected
through the ordinary `corners.process` axis.

## What was run

Three PVT points: **tt / 27 C / 1.8 V**, **ss / -40 C / 1.62 V** (DR-0002 entropy-binding
corner), **ff / -40 C / 1.98 V** (the fast corner, which also binds DR-0003's combining ceiling).
Per point:

- **RO array**: 30 mismatch draws (3 requests x 10, seeds 215, 216, 217) of the whole 4-ring array;
  40 rising-edge times per ring, `xo` duty at nine thresholds.
- **Sampler**: 60 mismatch draws (2 requests x 30, seeds 215, 216) of one `sampler_dff`.
- **Reference**: one plain-section (mismatch-free) unit of each deck, against which sampler offsets and
  ring shifts are taken.

Seeds: request i of a kind uses `monte_carlo.seed = 215 + i - 1`, the **same at every corner**, so draws are
paired across corners (common random numbers). The per-sample seeds `klt` derived are in each record's rows.
Sample counts are a starting point (issue text): 30 array draws bound a tail only to roughly the 1-in-30 level,
which is why a labelled model extrapolation is also reported.

## Findings (per corner; full tables in the three records)

| | tt / 27 C / 1.8 V | ss / -40 C / 1.62 V | ff / -40 C / 1.98 V |
|---|---|---|---|
| record | `20261009-111127-e57ad27` | `20261009-111126-e57ad27` | `20261009-111125-e57ad27` |
| ring period sigma, pooled (%) | 3.04 | 3.26 | 2.74 |
| ladder span, slowest/fastest, nominal; MC min / max | 1.184; 1.076 / 1.276 | 1.124; 1.023 / 1.219 | 1.169; 1.076 / 1.250 |
| min distance to 2/1, 3/2, 4/3 (DR-0005 figure), worst draw (%) | 4.31 (1-4 vs 4/3) | 8.60 | 6.24 |
| draws with that distance < 5 % (of 30) | 2 | 0 | 0 |
| min distance incl. 1:1, worst draw (%) | 0.07 (rings 2-3) | 0.02 (rings 3-4) | 0.09 (rings 2-3) |
| draws with an adjacent pair < 1 % / < 2 % apart (of 30) | 9 / 15 | 11 / 16 | 9 / 14 |
| `Q_array` ratio min / mean (margin 1/1.036 = 0.9653); draws below | 0.890 / 0.986; 10 | 0.890 / 0.991; 8 | 0.898 / 0.987; 7 |
| `<v(xo)>/vnom` min..max (DR-0003 band 0.31-0.53); draws outside | 0.274..0.561; 2 | 0.357..0.571; 1 | 0.365..0.551; 1 |
| sampler offset sigma / max abs (mV; resolution ~5-7 mV) | 15.2 / 45.0 | 30.6 / 102.5 | 16.0 / 46.2 |
| raw-bit p(1), nominal; worst of 1800 array x sampler pairings | 0.401; **0.279** | 0.365; 0.359 | 0.541; 0.376 |
| worst-case bias `|p-0.5|`; worst `H_bias` (bit) | 0.221; **0.472** | 0.141; 0.643 | 0.124; 0.680 |
| pairings with `H_bias` < 0.5 | **60 / 1800** | 0 / 1800 | 0 / 1800 |

`p(1)` is the duty of `xo` above the sampler's own (mismatch-moved) threshold, interpolated from the nine
comparator duties, for every array x sampler pairing (independent devices, so every pairing is a legitimate draw).
`H_bias = -log2(max(p, 1-p))` is an **upper bound** on the bit's min-entropy: a biased bit cannot exceed it. The
repo's SP 800-90B MCV estimator (`sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py`) was run on a seeded
Bernoulli stream at the worst-case `p` (100000 bits, seed 215) and agrees (tt 0.463, ss 0.634, ff 0.673 bit).

### Does DR-0004's H floor and DR-0003's operating point survive mismatch?

- **H floor (DR-0004 sec. 2.3, H = 0.5): not shown to survive at tt.** At ss and ff the static bias alone leaves
  `H_bias` >= 0.64 and >= 0.68, so the bias bound does not by itself threaten the floor there. At tt, 60 of 1800 array x
  sampler pairings (3.3 %) have a bias that caps the bit's min-entropy *below* 0.5, so the floor cannot hold for those
  devices irrespective of jitter; the worst case is p = 0.279. The driver is **array** mismatch (array-only min p = 0.282);
  sampler mismatch alone moves p by only +-0.003 at tt. This is a statement about a bound, not a measured min-entropy,
  and `H_bias` is not the jitter-limited entropy of DR-0003; but it is a case the ratified spec does not currently cover.
- **Ring-pair lock proximity (DR-0005's figure): the rationals the spec evaluates are not the exposure.** Against 2/1, 3/2
  and 4/3 the closest approach over 30 draws is 4.3 % (tt), 8.6 % (ss), 6.2 % (ff). The exposure is the **adjacent pairs near
  1:1**: the nominal ladder steps are only ~5-6 % apart, the pooled period sigma is ~3 % per ring, so in about a third of
  draws (9-11 of 30) some adjacent pair is within 1 % of each other and the ring order itself changes (spans down to
  1.02-1.08). A Gaussian per-ring extrapolation (independent rings, 200000 seeded draws, **not simulated**) puts that
  probability at 0.25 (tt), 0.40 (ss), 0.26 (ff) for < 1 %. Whether near-1:1 neighbours injection-lock under the real supply
  coupling is exactly what #200 examined only for ripple; this record does not simulate lock, it shows the proximity.
- **DR-0003's `Q` margin and bias band**: 7-10 of 30 draws per corner have a `T0^-3`-weighted `Q_array` below the 1/1.036 margin
  (the term is not a pure mismatch-free quantity: the mean over draws sits at 0.986-0.991, i.e. mismatch is a zero-mean spread
  around the margin, not a bias against it) and 1-2 draws have a combining-node bias outside 0.31-0.53.
- No spec value was changed. Following the issue, the bias and proximity results above are raised as a decision-record
  request rather than acted on here.

## `klt yield` reduction (issue #598, T1 item 6)

`yield_reports.py` re-reduces the committed raw responses of this campaign into one
`klt yield` sample set + report per PVT point under `yield/<record-id>/`, importing
`reduce.py`'s own `duty_at`/`h_bias` (nothing is copied) and refusing to write if the raw
responses no longer replay to the committed record or the derived pairings disagree with
its `raw_bit` statistics. The one measurement, `h_bias_bit`, is **H_bias -- the
static-bias UPPER bound on the raw bit's min-entropy, not the measured row quantity**:
a sample below the floor fails the row, a sample above it does not prove it. Limits are
the spec row as written (min 0.5 bit, DR-0004 sec. 2.3); the row states no target yield
and none is invented, so `klt yield` can only *report* the estimates (status `reported`,
never `fail`) -- which is why T1 item 6 analog stays `unmet`/`partial_coverage` when
these reports are cited in `signoff/block-manifest.json`: the row is unratified (README
target table DRAFT, decision records Proposed) and a yield citation with no
`target_yield` contributes no row coverage (klayout-tools#5490). The two missing inputs
-- a target yield on the row, and ratification -- are named on #3. The reports' own
findings stand either way: **tt 60/1800 pairings below the floor** (empirical 0.9667,
exact CI [0.9573, 0.9745] at 95%; the design response is #221 / DR-0013 / PR #249, not
touched here), ss and ff 0/1800 (empirical 1.0, bounded below at 0.998); sample size
`sufficient` at every corner (n 1800 vs required 1238 at tt / 183 at ss, ff). The
campaign's deterministic negative control -- the mismatch-free `arr0`/`smp0` units,
mismatch absent, statistic clean -- is recorded in each record and in the sample set's
`derivation` block; it is not a seeded-defect variant, so it is deliberately not fed to
`klt yield`'s `negative_control` field (which requires a known-bad variant that must show
up as degraded yield); a defect-injection campaign is follow-up work.

## Limits and caveats

- **Pre-layout, ideal sources**, as the cited records; no wire parasitics, no supply impedance.
- **Static, not dynamic**: `p(1)` is a time-average duty measured on a 60 ns-to-stop window of the transient (tt/ff 300 ns, ss 460 ns), not
  over a 20 us sample interval; the sampler offset is a DC-slow-ramp decision threshold, not a jitter-aware metastability window.
- **Sampler threshold measurement**: resolution is slope x clock period (~5-7 mV); the up-trip and down-trip differ by a hysteresis of
  30 mV (tt), 254 mV nominal (ss), 40 mV (ff), spread to 400 mV at ss. The decision threshold used is their mean. The
  ss hysteresis is large and not understood here (the clocked cell holds state through the slow ramp); the offset sigma at ss
  (30.6 mV) is therefore the least certain figure.
- 30 array / 60 sampler draws per corner: tail statements below ~1/30 are the model extrapolation, labelled as such.
  The Gaussian-in-ln T model ignores any correlation between rings (mismatch is independent per device; shared-supply effects are not mismatch).
- `Q_array` uses only the `T0^-3` term of DR-0002's `Q`; `sigma_1` is not re-measured under mismatch.
- The tt mismatch-free reference units (`tt-arr0-1`, `tt-smp0-1`) ran locally under klt 0.7.0 (a single unit stays local; the record
  lists them as `local`); all Monte Carlo units and the ss/ff references ran on the batch fleet under klt 0.6.0 (see below), ngspice 46.

## Method history (stated so it is not mistaken for selection)

The first submission of the full set under klt 0.7.0 failed on every batch unit with `batch_job_failed` (fleet runner klt 0.5.0 vs
client 0.7.0). Those failed responses carry no results and were discarded; the set was re-submitted unchanged under `klayout-tools==0.6.0`.
Some requests were refused with `BATCH_MAX_CONCURRENT_INSTANCES` (fleet at capacity) and re-submitted later unchanged. No request was
modified after seeing results. An earlier, interrupted pass of this work had already completed three of the one-unit mismatch-free
references under 0.6.0 on the fleet (`ss-smp0-1`, `ff-arr0-1`, `ff-smp0-1`); those were kept because their recorded `netlist_sha256` equals
that of the regenerated request (same deck, same section). Every Monte Carlo unit comes from the single clean pass described above.

Completeness of the records above rested on the operator noticing that a refused request had to be re-submitted: `reduce.py` used to
drop a request with no usable response and then take `n_array_requested` / `n_sampler_requested` from the units that came *back*, so a
set missing a refused chunk would have reported itself as "20/20 array, 30/30 sampler" with no error. It no longer can (issue #469):
the loader returns refused requests, the requested counts come from the plans' `monte_carlo.n`, and `--emit-record` refuses to write a
record while any request of the set has no usable response. The three committed records are unaffected — they are the complete set, and
still replay as `MATCHES` — this closes the gap that let a *future* re-run record a partial set as a whole one.

## Tool friction

Already filed upstream, hit again here: `2AMLogic/klayout-tools#2948` (batch runner/client version mismatch, runner 0.5.0 vs
client 0.7.0, and the capacity wait not honoured), `#2851` (the mismatch surfaces only after instance launch as per-corner errors),
`#2869` (concurrent batch submissions refused with no capacity). No new tool gap was found; `monte_carlo.vary = "mismatch"` with the
`*_mm` library sections worked as documented.
