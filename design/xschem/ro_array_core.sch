v {xschem version=3.4.4 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {ro_array_core -- the sky130-trng entropy source.

Ported from gf180-trng's design/xschem/ro_array_core.sch. N independent,
separately-supplied, free-running ring oscillators of a common cell design
with deliberately skewed frequencies, XOR-combined into one node (xo) that
a single sampler observes. The TOPOLOGY is what ports: an array of
independent rings, non-integer frequency ratios, per-ring supply routing,
one combining node ahead of one sampler.

N = 2 AND 11 STAGES ARE PROVISIONAL PLACEHOLDERS, NOT A SIZED RESULT FOR
sky130. gf180-trng arrived at N = 2 at eleven stages from gf180mcu
MEASUREMENTS -- a measured jitter figure feeding an array sizing law, and a
measured array power rollup against a ratified power row that the combining
tree, not the rings, turned out to bind. spec/porting-plan.md section 2.2
is explicit that none of those numbers port: they are the output of a
device measurement, not of the sizing law (which does port). This file
instantiates two eleven-stage rings because that is a known-good shape to
start a port from, and for no other reason.

What the sizing law needs before N stops being a placeholder, per
spec/porting-plan.md sections 2.2 and 3.1: sky130 transient-noise
jitter-accumulation runs over this design's own ro_stage, across the corner
grid, producing per-ring sigma_1 and T_0. Those feed the array law
Q_array = sum over rings of sigma_acc squared over T_0 squared, sized to
the min-entropy target with the declared design margin at the
entropy-binding corner -- and the entropy-binding corner is itself
something this port owes a full-grid measurement for (section 2.4), rather
than inheriting gf180-trng's, which inverted once inside that repository
when more grid coverage arrived. Until that work exists, treat N = 2 as
"the smallest array the concept allows, drawn so the hierarchy is
complete", not as a sky130 answer.

  en1, en2    per-ring enable. en = 0 stops that ring in a static state.
  vddr1/2     per-ring supply. Separate routing is an independence
              requirement of the array concept, and is also the per-ring
              liveness observation point -- a stopped ring's supply current
              collapses, while a stuck ring is INVISIBLE at xo because it
              contributes a constant to the XOR.
  vdd/vss     block supply for the combining gate and the two ring output
              buffers. Deliberately not either ring's vddr, so per-ring
              supply sensing sees rings only.
  xo          the combined node. THE RAW TAP IS NOT HERE: it sits at the
              sampler output, after digitization. The sampler and its clock
              live one level up in sampler_core.sch.
  ro1, ro2    per-ring outputs, OBSERVATION ONLY, for a per-ring liveness
              monitor. They exist because a stuck ring is invisible at xo,
              and a monitor that cannot see a ring cannot report it.
              Nothing here digitizes them: the sampler_dff taps live one
              level up, on the same clock the raw tap uses, so this cell
              stays a purely analog free-running source with no clock.
              These are per-ring signals INSIDE the block, not exposed
              pins. Since they are taken from the buffer output they are
              the BUFFERED node, not the ring's own raw node.

Per-ring output buffer. Each ring's own last stage drives one ro_buf
instance -- a minimum-width, unstarved inverter -- and ro1/ro2 are
re-driven from that buffer's output, not from the ring directly, so every
consumer downstream sees the buffered node. Two SEPARATE buffer instances,
one per ring: a single buffer feeding both combiner inputs would recreate
exactly the shared node the buffering exists to remove. Both buffers run
off vdd/vss, not off either ring's vddr, so each ring's supply pin stays a
pure per-ring current signature. gf180-trng measured what this buys on
gf180mcu; that number is not reproduced here, and the sky130 coupling
measurement is owed by the testbench work in spec/porting-plan.md
section 3.2.

Polarity: ro1/ro2 are the COMPLEMENT of their ring's own internal node.
a XOR b == (NOT a) XOR (NOT b), so xa1's output is bit-identical; a
transition-counting liveness monitor is polarity-blind; sampler entropy
does not depend on polarity. A reader of ro1/ro2 should not assume it is
the ring's own sense.

Frequency skew is by starve-device width (wstv), not by stage count, so the
nominal ratio is set by a continuous parameter rather than by a ratio of
small integers -- integer-ratio rings are the ones that mutually injection
lock. The two widths drawn here (0.42 um and 0.46 um, roughly a 9.5 % skew)
are PROVISIONAL: 0.42 um is sky130's minimum device width and the skew
fraction is carried over from gf180-trng's own pair. The realized frequency
ratio is a measurement this port owes, not an assumption -- and the skew
that actually decorrelates two sky130 rings is part of that measurement.} -1200 -700 0 0 0.25 0.25 {}
C {ipin.sym} -1200 -300 0 0 {name=pe1 lab=en1}
C {ipin.sym} -1200 -250 0 0 {name=pe2 lab=en2}
C {iopin.sym} -1000 -300 0 0 {name=pv1 lab=vddr1}
C {iopin.sym} -1000 -250 0 0 {name=pv2 lab=vddr2}
C {iopin.sym} -800 -300 0 0 {name=pv lab=vdd}
C {iopin.sym} -800 -250 0 0 {name=ps lab=vss}
C {opin.sym} -800 -200 0 0 {name=po lab=xo}
C {opin.sym} -800 -150 0 0 {name=po1 lab=ro1}
C {opin.sym} -800 -100 0 0 {name=po2 lab=ro2}
C {ro_ring11.sym} 0 0 0 0 {name=xr1 wstv=0.42 lstv=2 cld=0.5f}
C {ro_ring11.sym} 0 300 0 0 {name=xr2 wstv=0.46 lstv=2 cld=0.5f}
C {ro_buf.sym} 250 -10 0 0 {name=xb1}
C {ro_buf.sym} 250 290 0 0 {name=xb2}
C {xor2.sym} 400 150 0 0 {name=xa1}
C {lab_pin.sym} -70 -10 0 1 {name=le1 lab=en1}
C {lab_pin.sym} -70 290 0 1 {name=le2 lab=en2}
C {lab_pin.sym} 0 -70 0 0 {name=lw1 lab=vddr1}
C {lab_pin.sym} 0 230 0 0 {name=lw2 lab=vddr2}
C {lab_pin.sym} 0 70 0 0 {name=lg1 lab=vss}
C {lab_pin.sym} 0 370 0 0 {name=lg2 lab=vss}
C {lab_pin.sym} 70 -10 0 0 {name=lo1 lab=rn1}
C {lab_pin.sym} 70 290 0 0 {name=lo2 lab=rn2}
C {lab_pin.sym} 200 -20 0 0 {name=lb1a lab=rn1}
C {lab_pin.sym} 300 -20 0 0 {name=lb1y lab=ro1}
C {lab_pin.sym} 250 -60 0 0 {name=lb1v lab=vdd}
C {lab_pin.sym} 250 40 0 0 {name=lb1g lab=vss}
C {lab_pin.sym} 200 280 0 0 {name=lb2a lab=rn2}
C {lab_pin.sym} 300 280 0 0 {name=lb2y lab=ro2}
C {lab_pin.sym} 250 240 0 0 {name=lb2v lab=vdd}
C {lab_pin.sym} 250 340 0 0 {name=lb2g lab=vss}
C {lab_pin.sym} 360 130 0 1 {name=lxa1a lab=ro1}
C {lab_pin.sym} 360 170 0 1 {name=lxa1b lab=ro2}
C {lab_pin.sym} 440 150 0 0 {name=lxa1y lab=xo}
C {lab_pin.sym} 400 110 0 0 {name=lxa1v lab=vdd}
C {lab_pin.sym} 400 190 0 0 {name=lxa1g lab=vss}
