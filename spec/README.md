# spec

- [`porting-plan.md`](porting-plan.md) — what carries over from
  [gf180-trng](https://github.com/2AMLogic/gf180-trng) as-is versus what
  must be re-derived for sky130, and the verification plan (PVT corners,
  testbench inventory, entropy/statistical evidence) that follows from it.
  A planning document, not a ratified spec or a decision record.

## Decision records

- [`decision-records/DR-0001-sky130-operating-envelope.md`](decision-records/DR-0001-sky130-operating-envelope.md)
  — **Proposed**. Build the entropy source on sky130's 1.8 V core device
  pair (`sky130_fd_pr__nfet_01v8`/`__pfet_01v8`), because sky130 ships no
  matched 3.3 V core N/P pair. Fixes the conclusion `porting-plan.md` §2.1
  argues and defers; every device in `design/xschem/` is instantiated under
  it.
- [`decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md`](decision-records/DR-0002-sky130-ro-jitter-and-array-sizing.md)
  — **Proposed**. Reports issue #10's sky130 RO delay-cell jitter
  characterization: the measured entropy-binding corner (`ss`/−40 °C/
  1.62 V), the per-stage gain and ring-swing results that retire DR-0001's
  named risks, and the array size the sizing law asks for at the README's
  then-draft rate row. Records the committed `N = 2` placeholder as
  refuted and hands the array rebuild off as issue #13.
- [`decision-records/DR-0003-sky130-trng-operating-point.md`](decision-records/DR-0003-sky130-trng-operating-point.md)
  — **Proposed**. Issue #13's array rebuild: measures the XOR combining
  gate's own bandwidth ceiling on array size (a second, independent
  constraint DR-0002 did not quantify), finds it binds before the entropy
  law does, and fixes the resulting operating point — `N = 4` five-stage
  rings at a 50 kbps raw rate, against an architectural ceiling of
  ~78 kbps at any array size. `design/xschem/ro_array_core.sch` is
  redrawn under it.

- [`decision-records/DR-0004-sky130-digital-section-architecture.md`](decision-records/DR-0004-sky130-digital-section-architecture.md)
  — **Proposed**. Issue #20's digital section, everything downstream of the
  raw tap: SP 800-90B RCT/APT health tests with a start-up test and a
  latch-and-gate failure policy, a non-vetted CRC-32 LFSR conditioner
  (`K` = 8), and a two-path register/streaming interface in which the raw
  path is never gated. Re-derives the health-test cutoffs from the formulas
  at this repository's own `H` target and 50 kbps raw rate (`C_RCT` = 81,
  `C_APT` = 824, **provisional** pending a measured `H`), computes the APT
  degeneracy floor exactly (`H` = 0.0390625), and fixes the
  behavioural-model-is-normative / RTL-implements-it split that `digital/`
  is built on.

- [`decision-records/DR-0005-post-layout-parasitics-and-wstv-decorrelation.md`](decision-records/DR-0005-post-layout-parasitics-and-wstv-decorrelation.md)
  — **Proposed**. Issue #22's first post-layout campaign: what `klt extract
  --parasitics` over the composed `layout/` cells costs the five-stage ring
  (1.38x−1.48x in period, with swing and supply current), that the `wstv`
  frequency ladder survives it (span 1.11x−1.21x, closest approach to a
  mutual-injection-lock rational 9.3%), and a first **bounded** answer to
  DR-0003 §8's inter-ring decorrelation question — coupling through the one
  node extracted parasitics give the rings in common is ≤ 0.033% of the ring
  period, at the pessimistic bound, and is not resolved above the solver's
  own numerical floor. Explicitly does **not** close §8: the parasitics are
  intra-cell only, and §8's first-named mechanism (shared supply impedance)
  has no layout to be measured on.

- [`decision-records/DR-0006-array-level-post-layout-and-wstv-decorrelation.md`](decision-records/DR-0006-array-level-post-layout-and-wstv-decorrelation.md)
  — **Proposed**. Issue #22's whole-array post-layout campaign, re-running
  DR-0005's own named follow-up items against the real, DRC-clean and
  LVS-matching assembled `ro_array_core` GDS: array-level parasitics cost
  2.158x−2.501x in ring period (against 1.38x−1.48x intra-cell-only), the
  `wstv` ladder still discriminates (span 1.084x−1.175x), and a tied/float/
  solo substrate bracket — now on a real physically-placed layout rather
  than leaf cells hand-tied to a shared node — finds a *wider* (not
  narrower) coupling bound than DR-0005's own ring-scale study
  (loading −0.353% to −0.192%, coupling +0.044% to +0.293%), and — new with
  the canonical `vss`-strapped GDS as extraction source — a coupling sign
  that is consistent across all twelve grid points. Explicitly does **not**
  close §8 or supersede
  DR-0005: the magnitude is still a bracket rather than a measurement, and
  §8's first-named mechanism (shared supply impedance) still has no
  layout to be measured on at any scale.

- [`decision-records/DR-0007-sampler-dff-post-layout-and-reset-contention.md`](decision-records/DR-0007-sampler-dff-post-layout-and-reset-contention.md)
  — **Proposed**. Issue #22's first sampler_dff post-layout campaign
  (intra-cell parasitics, leaf-cell composition with ideal inter-cell
  wires): clk→q capture delay costs 1.314x−1.418x, inside DR-0005's own
  1.378x−1.479x ring-scale intra-cell finding; the reset window carries no
  contention current on this topology (DR-0014's methodology, re-derived
  for sky130); setup time is 60−150 ps post-layout and the digitizer is not
  the combining-gate bandwidth bottleneck at any grid point where both are
  measured. Explicitly defers the whole-cell extraction (`m`/`mb` were
  still unrouted) — discharged by DR-0008 below.

- [`decision-records/DR-0008-sampler-dff-assembled-post-layout.md`](decision-records/DR-0008-sampler-dff-assembled-post-layout.md)
  — **Proposed**. Issue #22's whole-cell (assembled) sampler_dff post-layout
  campaign, re-running DR-0007's own named "whole-cell extraction" follow-up
  now that `m`/`mb` are routed and `layout/sampler_dff/`'s own `klt lvs` is a
  full match: clk→q capture delay costs 1.704x−2.013x against pre-layout
  (1.268x−1.425x on top of DR-0007's own intra-cell figure at the same
  grid points), the reset window still carries no contention current
  (unchanged from DR-0007 to within a few significant figures), and the
  post-layout assembly is functionally correct. Explicitly does **not**
  re-derive DR-0007's own setup-time finding, and does not supersede
  DR-0007.

- [`decision-records/DR-0009-sampler-core-substrate-bracket-and-wstv-decorrelation.md`](decision-records/DR-0009-sampler-core-substrate-bracket-and-wstv-decorrelation.md)
  — **Proposed**. Issue #22's `sampler_core`-scope substrate bracket, and
  an audit of which of DR-0003 §8's three named inter-ring coupling
  mechanisms are now measured and which are not. Narrows the gap rather than
  closing it, and does not supersede DR-0003 §8, DR-0005 or DR-0006. Whole-block
  composition (`layout/trng_whole/`) gives distribution geometry, but its
  measurement obligations remain open (#174).

- [`decision-records/DR-0010-target-table-reconciliation.md`](decision-records/DR-0010-target-table-reconciliation.md)
  — **Proposed**. Issue #239's ratification packet for `README.md`'s
  "Target specification (DRAFT)" table: every row, with the current README
  value, the measured/derived sky130 value cited to a committed file, and a
  proposed disposition. Carries DR-0003's 50 kbps / ~78 kbps rate amendment
  with its cost stated; presents area and power as operator options without
  pre-deciding them (power pending #174/#201); routes min-entropy to #221.
  Does not edit the README table.

- [`decision-records/DR-0012-ro-array-supply-quality-requirement.md`](decision-records/DR-0012-ro-array-supply-quality-requirement.md)
  — **Proposed**. Issue #208's supply-quality requirement for the RO array
  rail, from the #200 supply-perturbation evidence (pre-layout, ideal
  sources, `sigma_1` not re-measured). Separates static droop, slow ripple,
  sample-spanning ripple, RF lock and combining-node bias; separates measured
  brackets from proposed limits; weighs rail conditioning, operating-point
  change and an environmental assumption plus monitor, recommending rail
  conditioning conditionally. Changes no target and preserves DR-0003's
  combining ceiling; distinct from #221 (mismatch/entropy).
- [`decision-records/DR-0013-local-mismatch-vs-h-floor-operating-point-and-lock-proximity.md`](decision-records/DR-0013-local-mismatch-vs-h-floor-operating-point-and-lock-proximity.md)
  — **Proposed**. Issue #221's decision packet from the local-mismatch Monte
  Carlo (`sim/local-mismatch-monte-carlo/`, pre-layout, simulation-derived,
  provisional until silicon): separates the DR-0004 `H` = 0.5 floor and its
  cutoffs, the DR-0003 operating point, and the DR-0005 lock-proximity
  criterion. Re-derives the evidence (the 60/1800 sub-floor pairings at tt are
  one array draw; `H_bias` is a static bound, not jitter entropy; lock is not
  simulated), prices trim and screening options, and recommends leaving all
  numeric values unchanged with follow-up simulations listed. States how it
  shares the Q-margin with DR-0012 (#208). Changes no spec value.

- [`decision-records/DR-0014-silicon-characterization-plan.md`](decision-records/DR-0014-silicon-characterization-plan.md)
  — **Proposed**. Issue #256's silicon characterization plan
  ([`silicon-characterization-plan.md`](silicon-characterization-plan.md)):
  a claim-to-measurement table linking every simulated claim to its `sim/`
  records, an observability audit against DR-0011 (no gap in the pin budget,
  conditional on bonding `raw_bit`/`raw_valid`; ring period not observable),
  and the `measurements/` layout contract. Claims no measured result; no
  silicon exists. DR-0013 is held by the open #221 proposal.

### Open requests for an operator decision record (no record yet)

- **End-of-life Vth-drift envelope** — issue [#262](https://github.com/2AMLogic/sky130-trng/issues/262), from
  issue #254's bounded gate-offset sensitivity campaign
  ([`../sim/ro-vth-drift-sensitivity/`](../sim/ro-vth-drift-sensitivity/)). The campaign shows how far a
  0-60 mV common-mode threshold shift moves the ring periods, `Q_ring`, the frequency ladder and the
  model-derived `H` bound against DR-0003's `Q` margin and DR-0004's `H = 0.5` evaluation floor. It is a
  sensitivity bound, not a lifetime prediction, and **changes no ratified or proposed decision**; whether to
  adopt a lifetime, a guard band or a re-sizing is left to the operator via that request.

A record's status is meaningful: **Proposed** means drafted and not accepted
by anyone. Ratification is an operator decision, so no record here declares
itself Accepted. See the repo README for scope.
