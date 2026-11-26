## 5. Proposed disposition

Both legs of both failing corners stay above the 500 uW bound at DR-0003's
own 20 us sampling period (section 3): the sampling rate is **refuted as
the overrun term by measurement** — moving from the committed controls'
100 ns clock to DR-0003's Ts = 20 us clock shifts each leg's total by at
most +1.9 / -6.5 uW (-1.1 % to +0.3 %), far below the 19.1-99.6 uW excess
over 500 uW (schematic then extracted: 19.1 / 77.2 uW at -40 C, 69.1 /
99.6 uW at +125 C), and the stimulus-identical W_RST window reproduces
across runs to 0.02-0.54 % (section 2 anchor). The six samplers share VDD
with the buffers and XOR tree, so these reports (four ring-rail currents
plus one shared-VDD current per leg) establish only that slowing the clock
leaves every leg over 500 uW; they do not isolate the sampler bank's
absolute power.

No supported design iteration is identified that recovers the excess inside
the Ts = 20 us, N = 4 operating point used here (ring gating destroys
DR-0003's accumulation basis; N = 4 is entropy-minimal; ff/1.98 V is
inside DR-0010 row 9's recorded envelope; the array-only figure is 473.9
uW at the hot corner, leaving 26.1 uW before the remaining loads; these
numbers do not rule out a periphery-only redesign). DR-0003 and DR-0010
are both `status: Proposed`. The evidence therefore warrants
reconsidering the target: **DR-0021 (Proposed)** records the rationale and
the operator options P-A (amend the analog-partition active bound to the
measured worst corner plus silicon guardband — recommended), P-B (hold
500 uW with a per-corner derogation) and P-C (a sizing re-derivation
campaign). This analysis leaves the README Power row, #597's grid and
every committed record intact; ratification is an operator action.

Whole-block power remains #174's row and is not claimable from these
numbers; the formal 12-corner PEX table is #597's.
