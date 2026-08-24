v {xschem version=3.4.4 file_version=1.2}
G {wstv=0.42 lstv=2 cld=0.5f}
K {}
V {}
S {}
E {}
T {ro_ring11 -- one ring of the entropy-source array: a starved NAND2 enable
stage followed by ten starved inverters, closed on itself.

Ported from gf180-trng's design/xschem/ro_ring11.sch.

ELEVEN STAGES IS A PROVISIONAL PLACEHOLDER, NOT A SIZED RESULT. It is the
stage count gf180-trng converged on, and it converged there on gf180mcu
MEASUREMENTS: a measured small-signal gain of that PDK's starved cell at
its own trip point, and a measured ring swing showing three- and five-stage
rings of that cell failing to reach the rails. Both of those are device
measurements, so per spec/porting-plan.md section 2.2 neither transfers.
sky130's own numbers do not exist yet. Eleven stages is carried over
because it is a known-good topology shape to start the port from, not
because anything here says eleven is right for sky130.

The reasoning that DOES port, and that the sky130 characterization work
should re-run rather than re-argue:

  * The entropy delivered per unit of ring power goes as the inverse SQUARE
    of the energy switched per ring cycle, and that energy is roughly
    proportional to the stage count. So the FEWEST stages that still
    oscillate rail-to-rail is the efficient choice, and the binding
    constraint is per-stage small-signal gain, not stage count as such: a
    three-stage inverting ring needs about 2.0 of gain per stage, a
    five-stage one about 1.24.
  * A ring that hands the XOR tree an analog level rather than a logic
    swing is a sampler problem. Reaching the rails is a hard requirement,
    not a preference.
  * The starve devices set the ring current, and therefore the period,
    WITHOUT adding switched capacitance -- so lstv moves the array's power
    and its XOR-node transition density together at roughly constant energy
    per cycle. Longer starve is NOT automatically better: past some point
    slower ring edges cost the combining gates more short-circuit charge
    than the lower transition rate saves. gf180-trng found its array fit
    its power row by ring COUNT, not by starve length. Whether sky130's
    array does the same is a measurement this repo owes, not an inference.

lstv = 2 um and wstv = 0.42 um are carried over placeholders -- see
ro_stage.sch for the full provisional-sizing note.

vddr is this ring's OWN supply pin (the per-ring supply routing the array's
independence requirement calls for), and doubles as the per-ring liveness
observation point: a stopped ring's supply current collapses by orders of
magnitude. The size of that collapse on sky130 is a leakage question, and
sky130 leakage is one of the things spec/porting-plan.md section 2.5 flags
as needing its own survey.} -700 -900 0 0 0.25 0.25 {}
C {ipin.sym} -700 -400 0 0 {name=p1 lab=en}
C {opin.sym} -600 -400 0 0 {name=p2 lab=ro}
C {iopin.sym} -700 -350 0 0 {name=p3 lab=vddr}
C {iopin.sym} -600 -350 0 0 {name=p4 lab=vss}
C {ro_nand2.sym} 0 0 0 0 {name=xg wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 300 0 0 0 {name=x1 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 600 0 0 0 {name=x2 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 900 0 0 0 {name=x3 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 1200 0 0 0 {name=x4 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 1500 0 0 0 {name=x5 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 1800 0 0 0 {name=x6 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 2100 0 0 0 {name=x7 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 2400 0 0 0 {name=x8 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 2700 0 0 0 {name=x9 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 3000 0 0 0 {name=x10 wstv=wstv lstv=lstv cld=cld}
N 50 -10 250 -10 {lab=n1}
N 350 -10 550 -10 {lab=n2}
N 650 -10 850 -10 {lab=n3}
N 950 -10 1150 -10 {lab=n4}
N 1250 -10 1450 -10 {lab=n5}
N 1550 -10 1750 -10 {lab=n6}
N 1850 -10 2050 -10 {lab=n7}
N 2150 -10 2350 -10 {lab=n8}
N 2450 -10 2650 -10 {lab=n9}
N 2750 -10 2950 -10 {lab=n10}
N 3050 -10 3150 -10 {lab=ro}
N 3150 -10 3150 -140 {lab=ro}
N -150 -140 3150 -140 {lab=ro}
N -150 -140 -150 -30 {lab=ro}
N -150 -30 -50 -30 {lab=ro}
C {lab_pin.sym} 150 -10 0 0 {name=ln1 lab=n1}
C {lab_pin.sym} 450 -10 0 0 {name=ln2 lab=n2}
C {lab_pin.sym} 750 -10 0 0 {name=ln3 lab=n3}
C {lab_pin.sym} 1050 -10 0 0 {name=ln4 lab=n4}
C {lab_pin.sym} 1350 -10 0 0 {name=ln5 lab=n5}
C {lab_pin.sym} 1650 -10 0 0 {name=ln6 lab=n6}
C {lab_pin.sym} 1950 -10 0 0 {name=ln7 lab=n7}
C {lab_pin.sym} 2250 -10 0 0 {name=ln8 lab=n8}
C {lab_pin.sym} 2550 -10 0 0 {name=ln9 lab=n9}
C {lab_pin.sym} 2850 -10 0 0 {name=ln10 lab=n10}
C {lab_pin.sym} 1500 -140 0 0 {name=lro lab=ro}
C {lab_pin.sym} -50 10 0 1 {name=len lab=en}
C {lab_pin.sym} 0 -50 0 0 {name=lv0 lab=vddr}
C {lab_pin.sym} 300 -50 0 0 {name=lv1 lab=vddr}
C {lab_pin.sym} 600 -50 0 0 {name=lv2 lab=vddr}
C {lab_pin.sym} 900 -50 0 0 {name=lv3 lab=vddr}
C {lab_pin.sym} 1200 -50 0 0 {name=lv4 lab=vddr}
C {lab_pin.sym} 1500 -50 0 0 {name=lv5 lab=vddr}
C {lab_pin.sym} 1800 -50 0 0 {name=lv6 lab=vddr}
C {lab_pin.sym} 2100 -50 0 0 {name=lv7 lab=vddr}
C {lab_pin.sym} 2400 -50 0 0 {name=lv8 lab=vddr}
C {lab_pin.sym} 2700 -50 0 0 {name=lv9 lab=vddr}
C {lab_pin.sym} 3000 -50 0 0 {name=lv10 lab=vddr}
C {lab_pin.sym} 0 50 0 0 {name=ls0 lab=vss}
C {lab_pin.sym} 300 50 0 0 {name=ls1 lab=vss}
C {lab_pin.sym} 600 50 0 0 {name=ls2 lab=vss}
C {lab_pin.sym} 900 50 0 0 {name=ls3 lab=vss}
C {lab_pin.sym} 1200 50 0 0 {name=ls4 lab=vss}
C {lab_pin.sym} 1500 50 0 0 {name=ls5 lab=vss}
C {lab_pin.sym} 1800 50 0 0 {name=ls6 lab=vss}
C {lab_pin.sym} 2100 50 0 0 {name=ls7 lab=vss}
C {lab_pin.sym} 2400 50 0 0 {name=ls8 lab=vss}
C {lab_pin.sym} 2700 50 0 0 {name=ls9 lab=vss}
C {lab_pin.sym} 3000 50 0 0 {name=ls10 lab=vss}
