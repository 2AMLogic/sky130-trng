v {xschem version=3.4.4 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {ro_array_core -- the sky130-trng entropy source.

Ported from gf180-trng's design/xschem/ro_array_core.sch, then REBUILT for
sky130 at a measured operating point (issue #13). N independent,
separately-supplied, free-running ring oscillators of a common cell design
with deliberately skewed frequencies, XOR-combined into one node (xo) that
a single sampler observes. The TOPOLOGY is what ports: an array of
independent rings, non-integer frequency ratios, per-ring supply routing,
one combining node ahead of one sampler.

  N = 4 rings, 5 stages each, at a 50 kbps raw-rate operating point.

Both numbers are sky130 measurements, not inherited values, and both are
fixed by spec/decision-records/DR-0003-sky130-trng-operating-point (status
Proposed), which supersedes the N = 2 x 11 placeholder this file used to
carry. DR-0002 refuted that placeholder; DR-0003 replaces it. Read DR-0003
before changing anything below, because N and the stage count are no longer
free parameters -- each is pinned between a lower bound and an upper bound
that were measured independently, and the two bounds are NOT evaluated at
the same corner.

THE TWO BOUNDS, and why the array cannot simply be made bigger:

  lower bound (entropy)   N >= 4 at T_s = 20 us. The per-ring sizing law
                          Q_ring = sigma_1^2 T_s / T_0^3 evaluated at the
                          measured entropy-binding corner ss / -40 C /
                          1.62 V, with H0 = 0.5 and the declared M = 1.5
                          margin, over sim/ro-ring-jitter-accumulation/'s
                          sigma_1 and this cell's OWN buffer-loaded period
                          from sim/ro-ring5-swing-and-current/ (5.469 ns,
                          13% slower than the unloaded ring DR-0002
                          measured -- the loading a real output buffer and
                          the combining tree's own fan-in add).

  upper bound (combining) N <= 6 at ff / -40 C / 1.98 V -- NOT the entropy-
                          binding corner. Every ring puts two edges per
                          period into the combining node, so a balanced
                          tree's root sees a mean edge spacing of
                          T_0 / (2 N). The root gate is a static CMOS xor2
                          of minimum-width devices and has a MEASURED
                          minimum pulse width (sim/xor-combining-bandwidth/);
                          edges closer together than that are swallowed, so
                          they never reach the sampler and the entropy they
                          carried is not in the raw bit however large N is.
                          This bound is a hardware fact of ring speed vs.
                          gate resolution, independent of T_s -- it binds
                          hardest at the FASTEST ring in the measured grid
                          (ff / -40 C / 1.98 V, the same corner DR-0002
                          found fastest), not at the slowest one where the
                          entropy law happens to bind. sim/ro-array-
                          operating-point/ checks this at all nine measured
                          (temp, Vdd, corner) points, not just one, because
                          reporting only the entropy-binding corner's own
                          combining figure understates the constraint
                          whenever the two corners differ, which they do.

N = 4 is the largest power of two clearing N <= 6 with margin, which makes
the combining tree a balanced binary tree (3 gates, 2 levels) and keeps
area and supply current the smallest of the choices that clear both
bounds.

WHY THE RAW-RATE ROW MOVED, AND WHY IT MOVED FURTHER THAN AN EARLIER PASS
OVER THIS SAME EVIDENCE FOUND. The two bounds move differently with the
sample period: Q scales linearly with T_s, so the entropy bound falls as
the sample clock slows, while the combining bound does not move at all.
Where they cross is a hard ceiling on the raw rate, and evaluating the
combining bound only at the entropy-binding corner (the ring's OWN
slowest, easiest-to-combine point) understates how tight that ceiling
actually is -- the crossover has to use whichever corner makes the ring
FASTEST, since that is where the combining gate has the hardest job:

  10 Mbps   entropy wants N >= 773   combining allows N <= 6   IMPOSSIBLE
   1 Mbps   entropy wants N >= 78    combining allows N <= 6   IMPOSSIBLE
 100 kbps   entropy wants N >= 8     combining allows N <= 6   IMPOSSIBLE
  78 kbps   entropy wants N >= 7     combining allows N <= 6   the ceiling
  50 kbps   entropy wants N >= 4     combining allows N <= 6   N = 4, drawn
  10 kbps   entropy wants N >= 1     combining allows N <= 6   over-margined

So the README's draft "> 1 Mbps sustained at the raw tap" row is not merely
expensive for this entropy source on sky130 -- it is unreachable at ANY
array size, because the combining gate runs out of bandwidth roughly two
orders of magnitude before the sizing law runs out of rings. DR-0003 moves
the row to 50 kbps and states the ~78 kbps architectural ceiling behind it
(sim/ro-array-operating-point/).

WHY FIVE STAGES, measured on sky130 at five stages rather than inherited:

  * Entropy per sample. DR-0002 section 4 measured 5 stages at 12-48x
    better Q_ring than 11 at the same PVT points -- by far the largest
    lever on N of anything measured here, well clear of any plausible
    difference the combining bound could make between stage counts.
  * Swing, measured at FIVE stages rather than borrowed from ro_ring11.
    DR-0002 section 2 flagged the five-stage ring's internal swing (0.81 to
    1.00 x Vdd) as the reason not to move the stage count. The slug
    sim/ro-ring5-swing-and-current/ re-measures it deterministically, under
    this cell's own output-buffer load, over 12 PVT points: the internal
    ring node swings 0.78-0.96 x Vdd (worst at ff / 125 C / 1.98 V), and
    the BUFFERED output -- which is what the XOR tree and the liveness taps
    actually see -- swings 0.999-1.033 x Vdd at every single point. ro_buf
    squares the slew-limited ring node back to the rails. The objection is
    measured and retired, not waved away.
  * Cost. Five stages is 2.2x fewer devices and, measured here, 2.2x less
    ring supply current than eleven for the same job.

WHAT THE REBUILD MEASURED THAT THE #10 CAMPAIGN COULD NOT:

  * Output-buffer loading. The ring node drives ro_buf as well as the
    NAND2's own input, and that extra inverter load slows the ring by
    ~13-20 percent relative to the unloaded ring #10 characterized (5.47 ns
    against 4.82 ns at the binding corner). Since Q goes as 1/T_0^3 that is
    a ~1.5x reduction in Q_ring, and the sizing above uses the LOADED
    period, i.e. the pessimistic one. It sits inside DR-0002's declared
    2-4x band but it is a systematic, not noise, and it is applied here
    rather than absorbed.
  * The combining gate's own bandwidth ceiling on N (above) -- the
    constraint that turns out to bind before the entropy law does, which
    neither DR-0001 nor DR-0002 measured or anticipated.
  * Supply current, which no sky130 measurement previously existed for.
    Per running ring 4.98 uA (ss/-40/1.62) to 20.55 uA (ff/-40/1.98); per
    STOPPED ring 0.6 nA cold, 255 nA at ff / 125 C. The running-to-stopped
    ratio is 80x at the worst leakage corner and ~8800x at nominal, which
    is the contrast the per-ring-supply liveness monitor described below
    has to resolve -- now a number rather than an assertion.

WHAT IS STILL A PLACEHOLDER: every device width, the starve length lstv,
the wstv skew ladder below, and cld. See design/README.md's "Provisional,
not sized" table, which marks each row measured / refuted / placeholder.

  en1..en4      per-ring enable. en = 0 stops that ring in a static state.
  vddr1..vddr4  per-ring supply. Separate routing is an independence
                requirement of the array concept, and is also the per-ring
                liveness observation point -- a stopped ring's supply
                current collapses by the measured factor above, while a
                stuck ring is INVISIBLE at xo because it contributes a
                constant to the XOR.
  vdd/vss       block supply for the combining tree and the four ring
                output buffers. Deliberately not any ring's vddr, so
                per-ring supply sensing sees rings only.
  xo            the combined node. THE RAW TAP IS NOT HERE: it sits at the
                sampler output, after digitization. The sampler and its
                clock live one level up in sampler_core.sch.
  ro1..ro4      per-ring outputs, OBSERVATION ONLY, for a per-ring liveness
                monitor. They exist because a stuck ring is invisible at
                xo, and a monitor that cannot see a ring cannot report it.
                Nothing here digitizes them: the sampler_dff taps live one
                level up, on the same clock the raw tap uses, so this cell
                stays a purely analog free-running source with no clock.
                Since they are taken from the buffer output they are the
                BUFFERED node, not the ring's own raw node.

Per-ring output buffer. Each ring's own last stage drives one ro_buf
instance -- a minimum-width, unstarved inverter -- and ro1..ro4 are
re-driven from that buffer's output, not from the ring directly, so every
consumer downstream sees the buffered node. FOUR SEPARATE buffer
instances, one per ring: a single buffer feeding several combiner inputs
would recreate exactly the shared node the buffering exists to remove. All
buffers run off vdd/vss, not off any ring's vddr, so each ring's supply pin
stays a pure per-ring current signature.

Polarity: ro1..ro4 are the COMPLEMENT of their ring's own internal node.
a XOR b == (NOT a) XOR (NOT b) and every path from a ring to xo passes
through the same number of tree levels, so xo is bit-identical to the
un-inverted combination; a transition-counting liveness monitor is
polarity-blind; sampler entropy does not depend on polarity. A reader of
ro1..ro4 should not assume it is the ring's own sense.

The combining tree is BALANCED on purpose: xa1 pairs rings 1-2, xa2 pairs
rings 3-4, xa3 combines the two pairs into xo. Depth 2, so every ring
reaches xo through the same number of gates and no ring is delayed
relative to another by tree position. Tree depth costs delay, not
bandwidth: the measured w_90 that sets the N ceiling is a property of ONE
gate driven at the root's own edge rate, and in a balanced tree only the
root sees that rate -- xa1/xa2 each see half of it. See
sim/ro-array-core-combining/ for the array-level edge-retention
measurement that checks this on the assembled block rather than assuming
it.

Frequency skew is by starve-device width (wstv), not by stage count, so the
nominal ratio is set by a continuous parameter rather than by a ratio of
small integers -- integer-ratio rings are the ones that mutually injection
lock. The ladder drawn here is 0.42 um to 0.48 um in 0.02 um steps: 0.42 um
is sky130's minimum device width, and the step is chosen so the extreme
frequency ratio stays well clear of the small rationals (2/1, 3/2, 4/3).
The realized ratios are MEASURED per ring on the assembled array in
sim/ro-array-core-combining/, not assumed. What is still NOT measured is
the skew that actually DECORRELATES two sky130 rings: the array as drawn
has no shared supply impedance and no substrate model, so a netlist-level
correlation measurement over it can only confirm the absence of a coupling
path the netlist does not contain. That measurement needs extracted
parasitics, and design/README.md's wstv row stays "placeholder" until it
exists.} -1200 -700 0 0 0.22 0.22 {}
C {ipin.sym} -1200 -300 0 0 {name=pe1 lab=en1}
C {ipin.sym} -1200 -250 0 0 {name=pe2 lab=en2}
C {ipin.sym} -1200 -200 0 0 {name=pe3 lab=en3}
C {ipin.sym} -1200 -150 0 0 {name=pe4 lab=en4}
C {iopin.sym} -1000 -300 0 0 {name=pv1 lab=vddr1}
C {iopin.sym} -1000 -250 0 0 {name=pv2 lab=vddr2}
C {iopin.sym} -1000 -200 0 0 {name=pv3 lab=vddr3}
C {iopin.sym} -1000 -150 0 0 {name=pv4 lab=vddr4}
C {iopin.sym} -800 -300 0 0 {name=pv lab=vdd}
C {iopin.sym} -800 -250 0 0 {name=ps lab=vss}
C {opin.sym} -800 -200 0 0 {name=po lab=xo}
C {opin.sym} -800 -150 0 0 {name=po1 lab=ro1}
C {opin.sym} -800 -100 0 0 {name=po2 lab=ro2}
C {opin.sym} -800 -50 0 0 {name=po3 lab=ro3}
C {opin.sym} -800 0 0 0 {name=po4 lab=ro4}
C {ro_ring5.sym} 0 0 0 0 {name=xr1 wstv=0.42 lstv=2 cld=0.5f}
C {ro_ring5.sym} 0 300 0 0 {name=xr2 wstv=0.44 lstv=2 cld=0.5f}
C {ro_ring5.sym} 0 600 0 0 {name=xr3 wstv=0.46 lstv=2 cld=0.5f}
C {ro_ring5.sym} 0 900 0 0 {name=xr4 wstv=0.48 lstv=2 cld=0.5f}
C {lab_pin.sym} -70 -10 0 1 {name=le1 lab=en1}
C {lab_pin.sym} -70 290 0 1 {name=le2 lab=en2}
C {lab_pin.sym} -70 590 0 1 {name=le3 lab=en3}
C {lab_pin.sym} -70 890 0 1 {name=le4 lab=en4}
C {lab_pin.sym} 0 -70 0 0 {name=lw1 lab=vddr1}
C {lab_pin.sym} 0 230 0 0 {name=lw2 lab=vddr2}
C {lab_pin.sym} 0 530 0 0 {name=lw3 lab=vddr3}
C {lab_pin.sym} 0 830 0 0 {name=lw4 lab=vddr4}
C {lab_pin.sym} 0 70 0 0 {name=lg1 lab=vss}
C {lab_pin.sym} 0 370 0 0 {name=lg2 lab=vss}
C {lab_pin.sym} 0 670 0 0 {name=lg3 lab=vss}
C {lab_pin.sym} 0 970 0 0 {name=lg4 lab=vss}
C {lab_pin.sym} 70 -10 0 0 {name=lo1 lab=rn1}
C {lab_pin.sym} 70 290 0 0 {name=lo2 lab=rn2}
C {lab_pin.sym} 70 590 0 0 {name=lo3 lab=rn3}
C {lab_pin.sym} 70 890 0 0 {name=lo4 lab=rn4}
C {ro_buf.sym} 250 -10 0 0 {name=xb1}
C {ro_buf.sym} 250 290 0 0 {name=xb2}
C {ro_buf.sym} 250 590 0 0 {name=xb3}
C {ro_buf.sym} 250 890 0 0 {name=xb4}
C {lab_pin.sym} 200 -20 0 0 {name=lb1a lab=rn1}
C {lab_pin.sym} 300 -20 0 0 {name=lb1y lab=ro1}
C {lab_pin.sym} 250 -60 0 0 {name=lb1v lab=vdd}
C {lab_pin.sym} 250 40 0 0 {name=lb1g lab=vss}
C {lab_pin.sym} 200 280 0 0 {name=lb2a lab=rn2}
C {lab_pin.sym} 300 280 0 0 {name=lb2y lab=ro2}
C {lab_pin.sym} 250 240 0 0 {name=lb2v lab=vdd}
C {lab_pin.sym} 250 340 0 0 {name=lb2g lab=vss}
C {lab_pin.sym} 200 580 0 0 {name=lb3a lab=rn3}
C {lab_pin.sym} 300 580 0 0 {name=lb3y lab=ro3}
C {lab_pin.sym} 250 540 0 0 {name=lb3v lab=vdd}
C {lab_pin.sym} 250 640 0 0 {name=lb3g lab=vss}
C {lab_pin.sym} 200 880 0 0 {name=lb4a lab=rn4}
C {lab_pin.sym} 300 880 0 0 {name=lb4y lab=ro4}
C {lab_pin.sym} 250 840 0 0 {name=lb4v lab=vdd}
C {lab_pin.sym} 250 940 0 0 {name=lb4g lab=vss}
C {xor2.sym} 500 150 0 0 {name=xa1}
C {lab_pin.sym} 460 130 0 1 {name=lxa1a lab=ro1}
C {lab_pin.sym} 460 170 0 1 {name=lxa1b lab=ro2}
C {lab_pin.sym} 540 150 0 0 {name=lxa1y lab=t1}
C {lab_pin.sym} 500 110 0 0 {name=lxa1v lab=vdd}
C {lab_pin.sym} 500 190 0 0 {name=lxa1g lab=vss}
C {xor2.sym} 500 750 0 0 {name=xa2}
C {lab_pin.sym} 460 730 0 1 {name=lxa2a lab=ro3}
C {lab_pin.sym} 460 770 0 1 {name=lxa2b lab=ro4}
C {lab_pin.sym} 540 750 0 0 {name=lxa2y lab=t2}
C {lab_pin.sym} 500 710 0 0 {name=lxa2v lab=vdd}
C {lab_pin.sym} 500 790 0 0 {name=lxa2g lab=vss}
C {xor2.sym} 700 450 0 0 {name=xa3}
C {lab_pin.sym} 660 430 0 1 {name=lxa3a lab=t1}
C {lab_pin.sym} 660 470 0 1 {name=lxa3b lab=t2}
C {lab_pin.sym} 740 450 0 0 {name=lxa3y lab=xo}
C {lab_pin.sym} 700 410 0 0 {name=lxa3v lab=vdd}
C {lab_pin.sym} 700 490 0 0 {name=lxa3g lab=vss}
