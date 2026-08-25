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

A record's status is meaningful: **Proposed** means drafted and not accepted
by anyone. Ratification is an operator decision, so no record here declares
itself Accepted. See the repo README for scope.
