## 5. Proposed disposition

At Ts = 20 us the two ff / 1.98 V corners exceed 500 uW on both legs.
The excess is 19.1 / 77.2 uW at -40 C and 69.1 / 99.6 uW at +125 C
(schematic / extracted). The historical 100 ns records and the 20 us
reports used different parasitic extractions and simulator settings.
Their 0.02–0.54% reset-window agreement applies only with reset held.
Section 3 uses the short 100 ns controls for clock-rate deltas. Each
leg measures four ring rails and one shared VDD for the buffers, XOR
tree and six samplers. This split leaves sampler-bank power unresolved.

No supported design iteration is identified that recovers the excess inside
the Ts = 20 us, N = 4 operating point used here (ring gating destroys
DR-0003's accumulation basis; N = 4 is entropy-minimal; ff/1.98 V is
inside DR-0010 row 9's recorded envelope; the array-only figure is 473.9
uW at the hot corner, leaving 26.1 uW before the remaining loads; these
numbers do not rule out a periphery-only redesign). DR-0003 and DR-0010
are both `status: Proposed`. At longer sampling periods the sizing law
permits fewer rings (DR-0003 §2). The measured misses warrant
reconsidering the target: **DR-0021 (Proposed)** records the rationale and
the operator options P-A (amend the analog-partition active bound to the
measured worst corner plus a proposed 47.4 uW allowance), P-B (hold
500 uW with a per-corner derogation) and P-C (a sizing re-derivation
campaign). This analysis leaves the README Power row, #597's grid and
every committed record intact; ratification is an operator action.

Whole-block power remains #174's row and is not claimable from these
numbers; the formal 12-corner PEX table is #597's.
