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

A record's status is meaningful: **Proposed** means drafted and not accepted
by anyone. Ratification is an operator decision, so no record here declares
itself Accepted. See the repo README for scope.
