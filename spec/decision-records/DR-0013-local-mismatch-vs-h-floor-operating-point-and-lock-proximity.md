---
dr: DR-0013-local-mismatch-vs-h-floor-operating-point-and-lock-proximity
title: local device mismatch versus DR-0004's H = 0.5 floor, DR-0003's operating point and DR-0005's lock-proximity criterion -- three questions, options, one recommendation
status: Proposed
date: 2026-10-10
deciders: unratified -- Proposed by the Builder on #221; ratification is an operator action
supersedes: "n/a -- this record supersedes nothing and changes no ratified or Proposed spec value (DR-0003, DR-0004, DR-0005 and the README target table are untouched)."
superseded_by: n/a
related: "#221 (this record), #215 and PR #220 (the local-mismatch campaign), #208 / DR-0012 (supply-quality requirement; shares the Q-margin, see 'Interaction with #208'), #174 (whole-block post-layout characterization), #216 (wake-up transient; touches the same start-up/H assumptions only indirectly), DR-0002, DR-0003, DR-0004, DR-0005, DR-0006, DR-0010 (rows 3 and 6 defer to this record; packet pattern), DR-0011 (pin budget), sim/local-mismatch-monte-carlo/"
---

# DR-0013: local mismatch versus the `H` floor, the operating point and the lock-proximity criterion

## Status

- 2026-10-10: **Proposed.** Not accepted by anyone. Ratification is an
  operator action; no agent declares this record Accepted.
- Doc and spec only. No `design/`, `digital/`, `layout/` or `sim/` file is
  changed, no existing record is edited, and **no numeric value in DR-0003,
  DR-0004, DR-0005 or the README target table is relaxed or altered.** DR-0003,
  DR-0004 and DR-0005 are themselves Proposed, not ratified; "the spec" below
  means those records as written.
- **Numbering.** The issue named DR-0012 as the next free number. At drafting
  time PR #248 (issue #208) already carries `DR-0012-ro-array-supply-quality-requirement`,
  so this record takes DR-0013 to avoid two files claiming one number.
- **No new simulation was run for this record.** Every figure is re-derived by
  replay and arithmetic over the committed `sim/local-mismatch-monte-carlo/`
  records (below). Everything is simulation-derived and provisional until
  silicon.

## Context

`sim/local-mismatch-monte-carlo/` (issue #215, PR #220) is the first record in
`sim/` that includes *local* device mismatch; all earlier records use global
process corners, which shift every device together and cannot show ring-to-ring
spread. It reports two things the Proposed spec does not address:

1. a static bias that can cap a raw bit's min-entropy below DR-0004 section 2.3's
   `H` = 0.5 floor at tt; and
2. adjacent rings that come within 1 % of each other (near 1:1) in about a
   third of the mismatch draws, which DR-0005's lock-proximity figure (2/1,
   3/2, 4/3) does not cover.

DR-0010 rows 3 and 6 explicitly defer the min-entropy and cutoff dispositions
to this record. The request is to decide whether the floor, the operating point
and the lock-proximity criterion need amending, or whether a trim or selection
mechanism is required. This record separates those into three questions.

## Evidence (re-derived, not copied)

Replay, run 2026-10-10 in the issue worktree (standard-library Python, no
simulator; all three exit 0):

```
$ python3 -I sim/local-mismatch-monte-carlo/reduce.py --check sim/local-mismatch-monte-carlo/records/20261009-111127-e57ad27.json
replay MATCHES sim/local-mismatch-monte-carlo/records/20261009-111127-e57ad27.json
$ ... records/20261009-111126-e57ad27.json
replay MATCHES sim/local-mismatch-monte-carlo/records/20261009-111126-e57ad27.json
$ ... records/20261009-111125-e57ad27.json
replay MATCHES sim/local-mismatch-monte-carlo/records/20261009-111125-e57ad27.json
```

Records: tt/27 C/1.8 V = `20261009-111127-e57ad27`; ss/-40 C/1.62 V (DR-0002
entropy-binding corner) = `20261009-111126-e57ad27`; ff/-40 C/1.98 V (DR-0003
combining-binding corner) = `20261009-111125-e57ad27`. Each has 30 array draws
and 60 sampler draws, 0 failed rows. The headline figures below were read from
each record's `summary` object (the replayed `reduce.py` arithmetic), not from
the README prose; the last four rows are additional cuts computed here from the
committed per-draw rows by importing `reduce.py`'s own `duty_at`/`h_bias`/
`q_ratio`.

| Quantity | tt | ss | ff | Agrees with issue text? |
|---|---|---|---|---|
| nominal (mismatch-free) `p(1)`, `H_bias` | 0.4006, 0.738 | 0.3646, 0.654 | 0.5407, 0.887 | n/a |
| worst `p` of 1800 pairings | **0.2789** | 0.3594 | 0.3758 | yes (0.279) |
| worst `H_bias` (bit) | **0.4718** | 0.6425 | 0.6800 | yes |
| pairings with `H_bias` < 0.5 | **60 / 1800** | 0 / 1800 | 0 / 1800 | yes |
| array-only min `p` / sampler-only `p` range | 0.2816 / 0.398-0.404 | 0.3606 / 0.363-0.371 | 0.3788 / 0.538-0.544 | yes (driver is the array) |
| SP 800-90B MCV on seeded Bernoulli stream at worst `p` | 0.463 | 0.634 | 0.673 | yes |
| draws with min pair closeness incl. 1:1 < 1 % / < 2 % (of 30) | **9 / 15** | **11 / 16** | **9 / 14** | yes |
| worst pair closeness incl. 1:1 (%) | 0.074 (rings 2-3) | 0.017 (rings 3-4) | 0.090 (rings 2-3) | n/a (README quotes 0.07 / 0.02 / 0.09) |
| DR-0005 figure (2/1, 3/2, 4/3 only), worst draw (%) | 4.31 | 8.60 | 6.24 | yes (4.3 / 8.6 / 6.2) |
| draws with `Q_array` ratio below 1/1.036 = 0.9653 (of 30) | 10 | 8 | 7 | yes (7-10) |
| `Q_array` ratio min / mean | 0.890 / 0.986 | 0.890 / 0.991 | 0.898 / 0.987 | n/a |
| draws with `<v(xo)>/vnom` outside 0.31-0.53 | 2 | 1 | 1 | yes (1-2) |
| ring period sigma, pooled (%) | 3.04 | 3.26 | 2.74 | n/a |
| Gaussian-model P(min closeness incl. 1:1 < 1 %), not simulated | 0.250 | (README: 0.40) | (README: 0.26) | n/a |

### Figures that need a qualification relative to the issue text

No headline number differs. Four readings do, and they matter for the
decision:

1. **The "60 of 1800 pairings" is one array draw, not sixty events.**
   Pairings are array draw x sampler draw. Recomputing the bias for each pairing
   from the per-draw rows, all 60 sub-floor pairings share a single array draw
   (`tt-arr-3`, sample 0, ring-period ratios to nominal
   0.997 / 1.060 / 0.960 / 1.016) crossed with every one of the 60 sampler
   draws (its `p` ranges 0.2789-0.2847 across them). No other tt array draw
   falls below the floor; the next-lowest tt array draw sits at `p` = 0.462.
   Because sampler mismatch moves `p` by only +-0.003, the sampler draws add
   almost no independent information. The honest denominator is **1 of 30
   array draws (3.3 %)**; that 3.3 % happens to equal 60/1800 by arithmetic.
   An isolated outlier in 30 draws is consistent with a heavy tail and with a
   single pathological draw, and 30 draws cannot tell the two apart.
2. **The same mismatch draw is the worst at all three corners.** Seeds are
   shared across corners (common random numbers), and sample 0 of request 3 is
   the minimum-`p` array draw at ss (0.359) and ff (0.376) as well. It stays
   above the floor there because the nominal `p` at ss/ff leaves headroom, so
   the dependence is on the draw, not on tt.
3. **The worst draw is also a near-1:1 draw, and its bias is flat in threshold.**
   At tt that draw's rings 3-4 are 0.21 % apart (ff: 0.12 %), and its `xo`
   duty is nearly independent of comparator threshold: 0.302 at 0.30 x
   `vnom`, 0.277 at 0.50, 0.252 at 0.70. Two consequences: (i) the sampler's
   threshold mismatch cannot rescue or damage it (hence array-only driver), and
   (ii) a threshold trim would move `p` by about 0.05 across the whole 0.30-0.70
   range, not by the ~0.2 needed. The measurement window is 300 ns with a 60 ns
   start, so ~240 ns; a 0.2 % ring-period difference beats on a period of
   about T/0.002, roughly 1.2 us at tt, i.e. the window covers about a fifth
   of one beat cycle. **A time-average duty over a fraction of a beat cycle is
   not a converged duty**, so the 0.279 may be partly a finite-window artifact
   of a near-1:1 pair. This is a hypothesis; it has not been tested (a
   single-unit longer-window re-run of that one seed would test it, see
   follow-ups). Not every outlier is near-1:1: the two lowest ss array draws
   (`p` = 0.361, 0.371) are not.
4. **"Adjacent" is by frequency rank, not ring index, at ss.** The < 1 % draws
   are index-adjacent pairs 1-2 / 2-3 / 3-4 in 9/9 draws at tt and ff, but at
   ss 3 of the 11 are 1-3 (2 draws) or 2-4 (1 draw): ring order itself has
   changed there (the ss nominal ladder step is smaller, ~3.9 % closest
   adjacent, versus ~5.6 % tt, ~5.2 % ff). Counts of "within 1 %" are
   unaffected; the physical reading is "two of the four rings are
   near-degenerate", not "ring k and k+1".

Also noted, not a discrepancy: the ss sampler offset sigma (30.6 mV, hysteresis
not understood) is the README's own least-certain figure, and it enters only
through the sampler-threshold half of the bias, which the data show is the
minor half.

## What this record does NOT establish

- **A static bound is not a jitter entropy.** `H_bias` = -log2(max(p, 1-p)) is an
  *upper* bound on min-entropy from a noiseless, time-averaged duty. It says a
  die with that duty *cannot exceed* that `H`; it does not say what `H` the die
  delivers, which is further limited by jitter and everything else DR-0002
  models. A `H_bias` >= 0.5 die is not thereby shown to meet the floor; a
  `H_bias` < 0.5 die is shown to miss it only if the duty is real (finding 3
  above) and only for a per-sample independence-free bound.
- **Lock was not simulated.** The netlist has no shared supply impedance and no
  substrate model (DR-0003 section 8); injection locking cannot occur in these
  decks. The record measures proximity only. Whether near-1:1 neighbours lock
  under real coupling is a layout and silicon question, and DR-0005 / DR-0006
  already say the coupling magnitude is only bracketed. Nearly equal
  frequencies are not, absent coupling, a decorrelation failure by themselves;
  the concern is the combination of near-degeneracy with whatever coupling
  exists.
- **Tail frequency.** 30 array draws bound a tail only to roughly 1-in-30; the
  Gaussian extrapolation assumes independent rings and a Gaussian `ln T`. No
  claim about yield below ~3 % is made.
- **Pre-layout, ideal sources.** No wire parasitics (DR-0005 reports post-layout
  ladder spans 1-3 % *narrower*, which would worsen adjacent proximity), no
  supply impedance, no `sigma_1` re-measurement under mismatch; `Q_array` uses
  only the `T0^-3` term.
- **Everything is simulation-derived and provisional until silicon.**

## Question (a): is `H` = 0.5 still the right floor, and what does `H_bias` < 0.5 mean for `C_RCT` / `C_APT`?

### What the floor and the cutoffs do

DR-0004 sections 2.1-2.3: `C_RCT = 1 + ceil(40 / H)`, `C_APT` = smallest `C` with
`Pr(Binomial(1024, 2^-H) >= C) <= 2^-40`. They are evaluated at the floor
because cutoffs shrink as `H` grows. Cutoffs at other `H` (recomputed here from
the DR-0004 formulas; the `H` = 0.5 and 0.5415 rows reproduce DR-0004's 81 / 824
and 75 / 806, which is the cross-check):

| `H` | `C_RCT` | `C_APT` | Where it comes from |
|---|---|---|---|
| 0.1898 | 212 | 966 | ss transistor-level `H_hat`, 24 bits, `T_s` = 100 ns (DR-0010 row 3 source a) |
| 0.3053 | 133 | 913 | tt/ff same record |
| 0.4000 | 101 | 869 | illustrative |
| **0.4718** | **86** | **836** | this evidence: worst tt `H_bias` |
| **0.5000** | **81** | **824** | adopted (DR-0004 section 2.3) |
| 0.5415 | 75 | 806 | DR-0003 modeled `H` |
| 0.6425 | 64 | 762 | worst ss `H_bias` |
| 0.6800 | 60 | 747 | worst ff `H_bias` |

### What a sub-floor source does to the adopted cutoffs

The cutoffs at the floor are set so that a source at or above 0.5 false-alarms
no faster than 2^-40. A source below 0.5 breaks that in the **fail-safe**
direction: it alarms *more*, not less. At the worst tt bias (max symbol
probability 1 - 0.2789392 = 0.7210608, `H` = 0.4718), with cutoffs left at
81 / 824:

- APT: the exact binomial tail of `Binomial(1024, 0.7210608)` at 824 is
  4.04e-10 per window. Against the design rate alpha = 2^-40 = 9.1e-13 (the
  basis of DR-0004's 713.6-year interval) that is about **444x**, and the
  713.6-year interval becomes about **1.6 years**. (Against the true tail of
  a source exactly at the floor, `H` = 0.5, which is 6.4e-13 at `C` = 824, the
  ratio is about 630x; the 713.6 -> 1.6-year comparison uses the alpha basis.
  Evaluating at the rounded 0.721 instead gives 3.93e-10, 432x, 1.65 years.)
- RCT: the run-probability exponent goes from 2^-40 to about 2^(-0.4718 x 80) =
  2^-37.7, about 4.8x higher; DR-0004's 254.5-day interval becomes about
  **53 days** (an upper-bound reading using the min-entropy rate).

So the health tests turn a sub-floor die into a nuisance-alarm die (`alarm`,
and the gating that follows), not into an undetected weak-entropy die. The
adverse direction would be the reverse (cutoffs derived at a higher `H` than
the truth), which is why DR-0004 section 2.3 chose the floor over 0.5415 and
why this record recommends against raising the cutoffs on the strength of the
ss/ff margins. Separately, the conditioner in DR-0004 takes 256 raw bits per
32-bit conditioned word (DR-0011's rate derivation); at `H` = 0.4718 that is
about 121 bits of input entropy, 3.8x the 32 output bits. Whether this meets any
particular full-entropy criterion is **not** evaluated here.

### Options

**(a1) Leave the floor and the cutoffs unchanged; record the exposure as an
accepted, provisional risk (recommended).**
- For: nothing is relaxed. The cutoffs are fail-safe for `H` below the floor. The
  evidence is a bound, from one array draw in 30, possibly partly a
  finite-window artifact (finding 3), and says nothing about jitter. Amending
  on this evidence would change a ratified-by-intent number on a statement that
  cannot yet be tied to a measured `H`. Consistent with the project rule that
  agents do not relax the spec to make results pass.
- Against: a die at the tail will not meet the README's min-entropy row and will
  alarm roughly every 1.6 years (APT) / 53 days (RCT) at 50 kbps even when
  working; the exposure is real if finding 3 does not dissolve it. Nothing in
  the design detects or removes such a die before it is deployed.

**(a2) Amend: lower the floor (for example to 0.45) and re-derive the cutoffs.**
- This is a relaxation of the README `H0` target and of DR-0004 section 2.3, and
  an operator-only decision. Cutoffs at 0.45 would be 90 / 846 (computed
  by the same formulas; not tabulated above) and detection gets slower.
- Against: lowers the guarantee to fit one outlier; a static bound cannot justify
  lowering a jitter-entropy floor in either direction. Not recommended without
  jitter-aware evidence.

**(a3) Amend: raise the floor or cutoffs' safety margin (for example derive at
the ss/ff bound).** Rejected: higher assumed `H` shrinks the cutoffs, which is
the unsafe direction (section 2.3), and the ss/ff bounds are bounds, not
measurements.

**(a4) Keep the floor but add a screening step (see "Trim and selection"
below).** Compatible with (a1); costs test time rather than silicon.

### Recommendation (a)

**(a1)**, with the explicit escalation condition: if the jitter-aware worst-draw
simulation (follow-up 2) or a longer-window re-run of the worst draw (follow-up
1) confirms a delivered `H` below 0.5 for a non-negligible fraction of a larger
mismatch sample, the operator then chooses between (a2) and a screening or trim
mechanism with the numbers in hand. The threshold for "non-negligible" is an
operator choice (it is a yield-versus-risk trade) and is not fixed here.

## Question (b): does DR-0003's operating point need amending?

DR-0003's operating point is `N` = 4, `T_s` = 20 us, `Q_array` = 1.036 x
`M*Q_H0` (guaranteed `H` = 0.5415), with `xo` bias inside 0.31-0.53 x `Vdd`
across the global-corner grid. Mismatch results: `Q_array` below the 0.9653 ratio
in 10 / 8 / 7 of 30 draws (tt/ss/ff), mean ratio 0.986-0.991, min 0.89-0.90;
`xo` bias outside the band in 2 / 1 / 1 draws.

Reading: mismatch is mainly a **spread around the nominal design point**, wide
enough to cross the margin. The minimum `Q` ratios 0.890 / 0.890 / 0.898 are
7.8 / 7.8 / 6.9 % below the 0.9653 margin (10-11 % below 1.0). The mean is above
the margin but **below 1.0 at all three corners**: 0.9863 / 0.9906 / 0.9867, with
sample SD 0.048 / 0.053 / 0.043 and standard error about 0.009 at n = 30, so
about 1.0-1.7 SE low. The per-ring `mean_shift_pct` (period longer than
nominal) is also positive for every ring at every corner, from +0.0 to
+1.2 %. The three corners share seeds (common random numbers), so they are not
three independent confirmations. The data are therefore consistent with a
zero-mean spread at n = 30, but the sample mean sits about 0.9-1.4 % below
nominal at every corner, and a small systematic shift is **not excluded**.

The 1.036x margin therefore does not hold per die. At best it holds for the
population mean, and only if that mean shift is not real. That is a fact about
how the margin should be worded, not by itself evidence of `H` < 0.5: `Q` is a
sizing proxy carrying DR-0002 section 6's 2-4x uncertainty band and, here, only
the `T0^-3` term. Any joint Q-margin amendment (below) should budget for a
possible mean shift as well as the spread.

### Interaction with #208 (DR-0012) -- which record owns the Q-margin amendment

#208 (PR #248, DR-0012, Proposed) argues from the #200 ripple evidence that the
Q margin corresponds to about 3.93 mV (ss) / 7.43 mV (ff) of *static supply
droop*, and recommends conditioning the `vddr1..4` rails (its Option A) while
holding a wider-Q-margin change (its Option B: more `N` or more nominal supply,
which would consume the DR-0003 `N_max_combine` = 6 ceiling margin) back.
This record's evidence is the **mismatch-driven** consumption of the same
margin: 7-10 of 30 draws are already below it with no supply error at all.

How the two fit:

- **Same margin, independent budget lines.** Rail conditioning (DR-0012) does
  nothing for mismatch, which is a static die-level spread, and a wider margin
  helps both. The two error sources add; in the worst-case sense a draw already
  below the margin has no supply tolerance left.
- **Ownership.** To prevent two records proposing different Q-margin values:
  **any change to the Q-margin *value* or to `N` / nominal supply is owned by
  one amendment, to be written only if an operator ratifies a wider-margin
  option, and it must size the margin as supply budget (DR-0012's mV figure) plus
  mismatch spread and possible mean shift (this record's distribution).** Neither DR-0012 nor this
  record proposes such a change. DR-0012 owns the supply-side requirement and
  the rail-conditioning item; this record owns the mismatch-side distribution
  and the statement that the margin is a population figure. DR-0012's
  Option B and this record's (b2) below are the same lever and are decided once.
- Neither record owns the other's question: #208's text and its own related
  field already separate itself from #221.

### Options

**(b1) Do not amend the operating point; restate the margin as a population
figure and carry the mismatch spread as an input to the Q-margin sizing (recommended).**
- For: avoids moving `N` or the supply on pre-layout, ideal-source, T0-only
  evidence; consistent with DR-0012 holding Option B back; keeps the 1.5x
  `N_max_combine` ring-count headroom DR-0003 spent deliberately.
- Against: leaves the per-die margin below 1.0 in about 1/4 to 1/3 of draws
  (7-10 of 30), unaddressed in silicon terms.

**(b2) Widen the Q margin (raise `N` toward `N_max_combine` = 6, or raise
nominal supply or `T_s`).**
- `T_s` is a rate cost (DR-0003 section 2: the 50 kbps row already sits below
  the ~78 kbps architectural ceiling; a longer `T_s` lowers the raw rate and
  moves the README row again). `N` = 5 or 6 breaks the 3-gate balanced
  combining tree (DR-0003 section 3), costs array area and supply current
  (linear in rings) and eats the combining headroom. Raising nominal supply is
  outside the 1.62-1.98 V envelope's meaning (DR-0001).
- This is the lever shared with DR-0012 Option B (see ownership above). Not
  recommended before the follow-ups say how much margin the worst-draw jitter
  evidence actually needs.

**(b3) Widen the bias band or drop the band as a criterion.** A relaxation of
DR-0003's evidence-derived 0.31-0.53; the band was an observation on global
corners, not a tolerance derived from an entropy requirement. Not recommended:
removes a guard when the data show 1-2 of 30 draws already outside it.

**(b4) Add an array-level mechanism to re-centre a die** -- see "Trim and
selection". Mismatch is the failure mode, so trimming is the matching remedy.

### Recommendation (b)

**(b1).** Do not change the operating point. State in the ratified wording that
1.036x is a population-mean margin that mismatch alone spends in 7-10/30 draws,
and let the single Q-margin amendment (owned jointly as above) be sized from
supply budget plus this spread and a possible mean shift when and if an operator chooses a wider margin.

## Question (c): does DR-0005's lock-proximity criterion need extending to 1:1 adjacent pairs?

DR-0003 section 8 / DR-0005 section 2: keep realized ring periods clear of the
small rationals 2/1, 3/2, 4/3 that mutually injection-lock. That is satisfied
with margin under mismatch (worst draw 4.3 % tt, 8.6 % ss, 6.2 % ff; 2 of 30
tt draws below 5 %, none at ss/ff). The criterion never covered 1:1 because a
deliberately skewed ladder was assumed to keep neighbours apart, and the
**nominal** ladder steps are only ~5.6 % (tt), ~3.9 % (ss), ~5.2 % (ff) between
closest neighbours (the MC nominal `close_any_pct` rows; DR-0005 measured the
post-layout ladder 1-3 % narrower), against a pooled per-ring period sigma of
2.7-3.3 %. A pair difference then has sigma around 4 %, so near-degenerate
neighbours are expected rather than exceptional.

To see how far a purely geometric fix could go, a Gaussian model (independent
rings, `ln T` sigma = 3.04 %, geometric ladder, 200000 seeded draws using
`reduce.py`'s own `pair_closeness`, arithmetic only, not a `klt sim` run) of
P(min pair closeness < 1 %), under two metrics. "1:1 only" counts only
near-degenerate pairs. "All ratios" is the record's `extrapolation` "any"
metric, which counts 1:1, 2/1, 3/2 and 4/3 together:

| nominal step | span (slow/fast) | sigma 3.04 %, 1:1 only | sigma 3.04 %, all ratios | sigma 1.52 %, 1:1 only | sigma 1.52 %, all ratios |
|---|---|---|---|---|---|
| 5.6 % (as drawn) | 1.178 | 0.25 | 0.25 | 0.05 | 0.05 |
| 8 % | 1.260 | 0.11 | 0.19 | 0.002 | 0.02 |
| 10 % | 1.331 | 0.05 | 0.26 | 0.00 | 0.36 |
| 12 % | 1.405 | 0.02 | 0.27 | 0.00 | 0.04 |

(sigma 1.52 % corresponds to 4x device area, if sigma ~ 1/sqrt(area).)

The two metrics coincide only at the drawn 5.6 % step, where every other
rational is far away. That 5.6 % row reproduces the record's own tt
extrapolation (0.250), which is a check on this model. **The "1:1 only" columns
are not a fix.** The 12 % row's 0.02 is the exact-1:1 figure alone: at span
1.405 the fast/slow pair sits about 5 % from 4/3 and about 6 % from 3/2, so the
all-ratio figure is 0.27, no better than the ladder as drawn. A 10 % step lands
the span on 1.33, i.e. on 4/3 itself, the very rational DR-0005 keeps the ladder
away from. At sigma 3.04 % the all-ratio figure is 0.19-0.27 for every step in
the table, so the ladder cannot be widened out of the problem; widening only
trades 1:1 proximity for 2/1, 3/2 or 4/3 proximity. Only reducing sigma
(larger matching-critical devices, a design and area change whose
dominant-device attribution has not been done) or screening/trim moves it, and
even at sigma 1.52 % the ladder step must avoid the rationals (the 10 % row
gets worse, 0.36). The sigma 1.52 % columns are an assumption about area
scaling, not a measurement, and vary at the 0.001 level with seed and draw count.

### Options

**(c1) Keep DR-0005's criterion as written, and add 1:1 as a *reported*
statistic with no numeric limit until lock is simulated (recommended).**
Proposed wording for the operator to ratify or reject: "Report, per corner,
the fraction of mismatch draws in which any ring pair is within 1 % and 2 % of
1:1, alongside the 2/1, 3/2, 4/3 figure; the pass limit for 1:1 is set when
lock behaviour of near-1:1 neighbours is simulated or measured." No existing
number is relaxed; one reported quantity is added.

**(c2) Extend the criterion with a numeric limit now** (for example: fewer than
X % of draws within 1 % of 1:1). Rejected for now: the evidence has no lock
simulation to say what the lock range is, so any X would be arbitrary, and
the measured 25-40 % fraction would make the ratified array fail its own
criterion by construction.

**(c3) Redesign the ladder or the ring devices** (wider `wstv` ladder,
bigger devices). The table shows widening alone runs into 4/3; device area
scales cost. DR-0003 estimates the array at 0.0026-0.0088 mm2 before any such
change, and no attribution of ring-period sigma to devices exists, so no area
figure is offered. Hold back pending follow-up 4.

**(c4) Declare near-1:1 a layout/silicon item only**, since lock needs coupling
that the netlist lacks, and rely on DR-0006/#174 to bracket the coupling.
Compatible with (c1); it is the honest classification of what cannot be
simulated pre-layout.

### Recommendation (c)

**(c1) together with (c4).** The exposure is real in proximity terms, not
demonstrated in lock terms; the criterion gets a reported statistic now and a
limit later.

## Trim and selection mechanisms (cost, and what could be re-simulated cheaply)

This section prices the "trim or selection mechanism" asked for by the issue,
across (a)-(c). Costs are structural estimates from the committed design and
RTL; no area, power or timing number was simulated for this record.

| Mechanism | Silicon area | Pins | DR-0004 register map | Verification | Re-simulatable now? |
|---|---|---|---|---|---|
| **S. Die screening** (no hardware change): after power-up, read `RAW_DATA` bursts and the `HT_*` / `ALARM` registers, or `raw_bit` taps, and bin the die by observed bias | none | none (uses existing interface; the raw taps are already planned in the DR-0011 recommendation) | none (existing `RAW_DATA`, `STATUS`, `ALARM`, `HT_*`) | silicon test procedure, not a design change; the health-test model already exists (`sim/digital-health-test-parameters/`) | the screening *statistic* can be exercised cheaply on the behavioral stream (`sim/raw-bit-volume-campaign/`); real yield is silicon-only |
| **T1. Per-ring frequency trim** (switchable parallel starve/`wstv` devices per ring) to widen the closest neighbour gap or recentre `Q` | adds a device bank to each of 4 rings plus its switches; the 40 existing starve devices are already long-channel (DR-0003 section 7), so each bank is not small; unquantified here | 0 if driven from a register; 8-12 if strapped (2-3 bits x 4 rings) | new writable trim register (8-12 bits of the 32-bit write bus; today only `bus_wdata[2:0]` is consumed, so a new register address and flops are required); changes DR-0004's ID/map and the RTL, and the 12 spare control-input budget in DR-0011 Option C only if strapped | analog: `klt sim` Monte Carlo with trim code as an axis (cheap relative to silicon); digital: re-run functional, RTL-equivalence, conditioned-output, SDF, PnR, DRC/LVS evidence, and recompose `trng_whole` (DR-0011 follow-up 3 lists the same cost class) | analog effect of trim on ladder gaps and `Q`: yes, via `klt sim` `monte_carlo`; whether it fixes *bias* is not known (trim moves frequency, the bias driver is a duty effect in the worst draw) |
| **T2. Sampler threshold trim** | small DAC/offset bank on `sampler_dff` | 0 (register) or 3-4 (strap) | new register | `klt sim` threshold sweep | **already shown ineffective for the worst draw**: sampler-only moves `p` by +-0.003 and the worst draw's duty varies only 0.30 -> 0.25 across the whole threshold range |
| **T3. Ring-enable selection** (use the existing `en1..en4`): disable a near-degenerate ring | none | existing `en1..en4` inputs | existing `CTRL` bits already gate the array | n/a | drops `Q_array` to 3/4 of its value (about 0.75 x 1.036 < 1) so it trades one shortfall for a larger one at `T_s` = 20 us; only viable with a longer `T_s` |
| **T4. Post-silicon re-roll** (not applicable): none | | | | | no |

Assessment: S is the only mechanism with no spec, layout or register-map
change and is compatible with every recommendation above. T1 is the
genuine trim; it is a large cross-cutting change (analog layout, DR-0004
register map, digital re-verification, whole-block LVS) whose benefit on the bias
failure is unestablished, so it is not recommended before follow-ups 1-3.
T2 is eliminated by the existing evidence. T3 reduces margin and is a runtime
fallback at best.

### What can be re-simulated cheaply versus what is silicon-only

Cheap, as `klt sim` requests (corners / `monte_carlo`) on the batch fleet, with
no new tool and no hand-launched grid: a larger array-draw sample at the same
three PVT points (the existing deck and `make-requests.py` take a seed and a
count; this directly attacks the 30-draw tail limit and gives the count of
sub-floor *array* draws); a single-corner, single-unit local re-run of
`tt-arr-3` sample 0 with a longer stop time (hypothesis 3 in the evidence
section; host rules permit one local unit); a sweep of ring-device sizing to
attribute the ring-period sigma.

Moderate: jitter-aware raw-bit entropy for the worst draw (a noise-enabled
transient over many `T_s` intervals is expensive at the literal 20 us; a
behavioral stream parameterized by the worst draw's per-ring periods and bias
is cheap but behavioral, not transistor-level).

Silicon-only: whether near-1:1 rings lock under real supply and substrate
coupling (needs the extracted coupling, DR-0006 / #174, then silicon); the
true delivered `H` of any die; the true yield tail below ~3 %; and the ss
sampler hysteresis.

## Recommendation (overall)

1. **(a1)** Leave the `H` = 0.5 floor and `C_RCT` = 81 / `C_APT` = 824 as they
   are. Record the sub-floor bias bound as an accepted, provisional risk,
   with the fail-safe direction and the nuisance-alarm intervals stated above.
2. **(b1)** Do not amend DR-0003's operating point. Reword the 1.036x margin as a
   population-mean figure; any margin change is the single amendment shared
   with DR-0012, sized as supply budget plus this record's mismatch spread and possible
   mean shift.
3. **(c1) + (c4)** Add 1:1 adjacent-pair proximity to DR-0005's criterion as a
   *reported* statistic; defer its numeric limit to lock simulation / layout.
4. **Screening (S)** is the cheap mitigation to prefer if the exposure turns out to
   be real; no trim hardware is recommended until the follow-ups below are in.

This is a recommendation, not a ratification. If the operator prefers to act
before the follow-ups, the only options that do not rest on a static bound are
(a1)-(c1), which change nothing.

## Consequences if ratified as proposed

- No ratified or Proposed number changes: `H` = 0.5, 81 / 824, `N` = 4, 1.036x,
  0.31-0.53 band, 2/1, 3/2, 4/3 stay as written.
- DR-0010 rows 3 and 6 dispositions become: row 3 **keep, provisionally** with
  this record as the cited exposure; row 6 **keep** (cutoffs unchanged).
- The Q-margin value is not edited here; a single later amendment, jointly
  informed by DR-0012 and this record, is the route.
- DR-0005's criterion gains one reported statistic.
- The README and design/layout/RTL are unchanged.

## Follow-up required (not done by this record)

These are the simulation and analysis issues needed to turn the proposal into
a ratifiable one. None is filed or run by this record; each, if run, must be a
`klt sim` request (corners / `monte_carlo`), appended as a new record under
`sim/` with a unit test wired per #230.

1. **Window and beat check of the worst draw.** Single-corner, single-unit
   re-run of `tt-arr-3` sample 0 (seed per the record) with a stop time of several
   beat periods (>= 3 us at tt), and a comparison of the duty over the
   original window versus the converged duty. Tests hypothesis 3; if the duty
   returns toward 0.5 the sub-floor bound is largely a window artifact.
2. **Jitter-aware raw-bit entropy under the worst-case mismatch draw.**
   Transistor-level if affordable, otherwise a behavioral stream (like
   `sim/raw-bit-volume-campaign/`) parameterized by the worst draw's per-ring
   periods and bias at the literal 20 us; report an SP 800-90B MCV `H` next to the
   bound.
3. **Larger mismatch sample.** At least a few hundred array draws at the same three
   PVT points to bound the sub-floor-array fraction, the `Q`-below-margin fraction
   and the near-1:1 fraction well below 1-in-30, with the same seeds scheme so
   draws remain paired across corners; add the ss sampler-hysteresis
   investigation (the unexplained 254 mV nominal hysteresis).
4. **Attribution of ring-period sigma** to ring devices (starve, inverter,
   buffer), to price any sigma-reducing change (c3) and to decide whether trim
   T1 is plausible.
5. **Lock simulation of near-1:1 pairs** with an explicit coupling element
   (supply impedance per DR-0006 / DR-0012's rail model, substrate bracket
   from DR-0009), to give DR-0005's 1:1 statistic a pass limit. Coordinate with
   #174 and with DR-0012's post-layout supply-impedance follow-up.
6. **Post-layout re-run of the proximity statistic** (DR-0005 found the ladder
   1-3 % narrower), once whole-block extraction supports it.
7. **Screening procedure definition** (mechanism S): bits per die, statistic,
   accept/reject threshold, and the interaction with `STATUS` / `ALARM` /
   `HT_*` (a test-plan item for the silicon bring-up, not an RTL change).
8. **Joint Q-margin amendment** (if any), owned as stated in "Interaction with
   #208", only after DR-0012's rail-conditioning decision and follow-ups 2-3
   are available.
9. After ratification: update DR-0010 row dispositions as above; the README
   target table is not edited by this record.
