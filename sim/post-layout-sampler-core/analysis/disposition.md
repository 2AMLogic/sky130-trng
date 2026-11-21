## 5. Proposed disposition

Both legs of both failing corners stay above the 500 uW bound at DR-0003's
own 20 us sampling period (section 3): the sampling rate is **refuted as
the overrun term by measurement** — moving from the committed controls'
100 ns clock to the ratified 20 us clock shifts each leg's total by at most
+1.9 / -6.5 uW (-1.1 % to +0.3 %), far below the 69-100 uW deficit, and
the stimulus-identical W_RST window reproduces across runs to 0.02-0.54 %
(section 2 anchor). The overrun is the continuous analog core current
(rings + buffers + XOR tree), not sampler dynamic charge.

No supported design iteration recovers the deficit inside the ratified
operating point (ring gating destroys DR-0003's accumulation basis; N = 4
is entropy-minimal; ff/1.98 V is inside DR-0010 row 9's envelope; the
array alone is already at 94.8 % of the budget at the hot corner before
the samplers or parasitics). The evidence therefore warrants
reconsidering the target: **DR-0021 (Proposed)** records the rationale and
the operator options P-A (amend the analog-partition active bound to the
measured worst corner plus silicon guardband — recommended), P-B (hold
500 uW with a per-corner derogation) and P-C (a sizing re-derivation
campaign). This analysis leaves the README Power row, #597's grid and
every committed record intact; ratification is an operator action.

Whole-block power remains #174's row and is not claimable from these
numbers; the formal 12-corner PEX table is #597's.
