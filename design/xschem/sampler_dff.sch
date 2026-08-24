v {xschem version=3.4.4 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sampler_dff -- static CMOS transmission-gate master-slave D flip-flop
with an asynchronous, active-low reset.

Ported from gf180-trng's design/xschem/sampler_dff.sch onto sky130's 1.8 V
core pair (sky130_fd_pr__nfet_01v8 / __pfet_01v8).

This is the digitizer: it is the ONLY cell in this block that turns an
analog swing (the entropy source's XOR node, design/xschem/ro_array_core.sch)
into a logic-level bit, so its own setup/hold/metastability behaviour is
part of the entropy story, not just a timing hazard.

Positive-edge-triggered, built from two opposite-phase transmission-gate
latches (the standard static TGFF topology). Each latch needs TWO series
inversions in its hold loop, not one -- a single inverter with a feedback
transmission gate creates q = NOT q, which is not bistable and settles at a
metastable half-rail voltage in simulation. That is a topology fact, not a
PDK fact; it is recorded here so nobody "simplifies" the cell back to the
one-inverter form on either process.

  master: TG_D (transparent clk=0) writes D into node m
          NANDM: NAND of m and rst_n -> mb   gated; drives the slave's TG_S
          INVM2: mb -> mc                    second inversion, feedback only
          TG_FBM (transparent clk=1) feeds mc back into m -- hold
  slave:  TG_S (transparent clk=1) passes mb -> node s
          INVS: s -> q                       the cell's output
          NANDS2: NAND of q and rst_n -> qb  gated second inversion, feedback
          TG_FBS (transparent clk=0) feeds qb back into s -- hold

D is captured into the master while clk=0; the master closes and the slave
opens as clk rises, so Q updates on the RISING clk edge.

RESET STRUCTURE, AND WHAT PORTS ABOUT IT. Reset is asynchronous and is
gated INTO the loops' own inverters rather than overriding either storage
node with dedicated pull devices. Exactly one inverter per latch becomes a
2-input NAND2 taking rst_n directly (a PMOS pull-up gated by rst_n is
active low, so no extra rst inversion is needed):

  NANDM  = Mimpa/Mimpb/Mimna/Mimnb, the master's FORWARD inverter m -> mb
  NANDS2 = Mis2pa/Mis2pb/Mis2na/Mis2nb, the slave's FEEDBACK inverter q -> qb

Whenever rst_n=0 the series NMOS pull-down of each NAND2 is broken and its
parallel PMOS pull-up forces the output HIGH regardless of the data input,
so mb=1 and qb=1. Those are the only two signals that can drive the slave's
storage node s -- mb through TG_S while clk=1, qb through TG_FBS while
clk=0 -- so BOTH agree on s=1, hence q=0, in either clock phase and across
every clock edge. Node m is driven to 0 through the master's own feedback
path on every clk=1 phase. No reset device ever fights a transmission gate
for a shared node.

WHY THE MASTER'S FORWARD INVERTER AND NOT ITS FEEDBACK ONE. Gating INVM2
(mb -> mc) instead reaches node m through the same feedback path and holds
q=0 in both STATIC clock phases, so on paper it looks equivalent. It is
not: it leaves mb tracking D while reset is asserted, and mb is exactly
what TG_S hands the slave on each clk RISING edge. With D=1 that drives
s=0 and hence q=1 for the whole clk-high phase, every phase -- reset is not
glitching, it is DEFEATED for as long as clk is high. That is a logic
argument about this topology and it holds on any process, which is why the
port keeps the forward-gated arrangement.

gf180-trng quantified both the residual clock-coupling excursion of the
shipped arrangement and the full-rail failure of the rejected one on
gf180mcu. Those are device measurements on another PDK. They are NOT
reproduced here as sky130 numbers and this file makes no quantitative
reset-window claim: the sky130 measurement is owed by the sampler
testbenches spec/porting-plan.md section 3.2 inventories.

Reset here is meant to be independent of clock phase, and the power-on
clock/reset relationship is not specified, so the sampler must not depend
on clk being parked while rst_n is low.

Sizing is PROVISIONAL -- see ro_stage.sch for the full note. Plain
inverters are 0.84 um PMOS / 0.42 um NMOS at L = 0.15 um. The series NMOS
leg of each NAND2 is 0.84 um, 2x the minimum-width device it replaces, to
compensate for series-stack resistance rather than degrade the loop's
regenerative gain; the parallel PMOS legs keep the 0.84 um sizing. Device
count is 22.

SAMPLER CLOCK SOURCE. clk is a FIXED EXTERNAL clock, not divided down from
either entropy-source ring. Deriving the sample clock from a ring that also
feeds the XOR node this cell digitizes reintroduces a deterministic beat
between source and sampler -- the exact failure mode the array's
non-integer frequency skew exists to avoid -- and it collapses the corner
metric the array sizing depends on into an unresolvable one. Both are
architecture arguments rather than gf180mcu facts, so both port directly
(spec/porting-plan.md section 1.2). This schematic therefore has no
clock-generation circuitry of its own, by decision and not by omission.} -200 -900 0 0 0.2 0.2 {}
C {ipin.sym} -300 -500 0 0 {name=p1 lab=d}
C {ipin.sym} -300 -450 0 0 {name=p2 lab=clk}
C {ipin.sym} -300 -400 0 0 {name=p3 lab=rst_n}
C {opin.sym} -300 -350 0 0 {name=p4 lab=q}
C {iopin.sym} -300 -300 0 0 {name=p5 lab=vdd}
C {iopin.sym} -300 -250 0 0 {name=p6 lab=vss}
C {sky130_fd_pr/pfet_01v8.sym} 0 -300 0 0 {name=Mpc L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 0 -100 0 0 {name=Mnc L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 600 -300 0 0 {name=Mtdp L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 600 -100 0 0 {name=Mtdn L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 900 -300 0 0 {name=Mimpa L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 1050 -300 0 0 {name=Mimpb L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 900 -100 0 0 {name=Mimna L=0.15 W=0.84 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 1050 -100 0 0 {name=Mimnb L=0.15 W=0.84 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 1200 -300 0 0 {name=Mim2p L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 1200 -100 0 0 {name=Mim2n L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 1500 -300 0 0 {name=Mfmp L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 1500 -100 0 0 {name=Mfmn L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 1800 -300 0 0 {name=Mtsp L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 1800 -100 0 0 {name=Mtsn L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 2100 -300 0 0 {name=Misp L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 2100 -100 0 0 {name=Misn L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 2400 -300 0 0 {name=Mis2pa L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 2550 -300 0 0 {name=Mis2pb L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 2400 -100 0 0 {name=Mis2na L=0.15 W=0.84 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 2550 -100 0 0 {name=Mis2nb L=0.15 W=0.84 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 2700 -300 0 0 {name=Mfsp L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 2700 -100 0 0 {name=Mfsn L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {lab_pin.sym} 20 -270 0 0 {name=l1 lab=clkb}
C {lab_pin.sym} -20 -300 0 0 {name=l2 lab=clk}
C {lab_pin.sym} 20 -330 0 0 {name=l3 lab=vdd}
C {lab_pin.sym} 20 -300 0 0 {name=l4 lab=vdd}
C {lab_pin.sym} 20 -130 0 0 {name=l5 lab=clkb}
C {lab_pin.sym} -20 -100 0 0 {name=l6 lab=clk}
C {lab_pin.sym} 20 -70 0 0 {name=l7 lab=vss}
C {lab_pin.sym} 20 -100 0 0 {name=l8 lab=vss}
C {lab_pin.sym} 620 -270 0 0 {name=l17 lab=d}
C {lab_pin.sym} 580 -300 0 0 {name=l18 lab=clk}
C {lab_pin.sym} 620 -330 0 0 {name=l19 lab=m}
C {lab_pin.sym} 620 -300 0 0 {name=l20 lab=vdd}
C {lab_pin.sym} 620 -130 0 0 {name=l21 lab=d}
C {lab_pin.sym} 580 -100 0 0 {name=l22 lab=clkb}
C {lab_pin.sym} 620 -70 0 0 {name=l23 lab=m}
C {lab_pin.sym} 620 -100 0 0 {name=l24 lab=vss}
C {lab_pin.sym} 920 -270 0 0 {name=l25 lab=mb}
C {lab_pin.sym} 880 -300 0 0 {name=l26 lab=m}
C {lab_pin.sym} 920 -330 0 0 {name=l27 lab=vdd}
C {lab_pin.sym} 920 -300 0 0 {name=l28 lab=vdd}
C {lab_pin.sym} 1070 -270 0 0 {name=l25b lab=mb}
C {lab_pin.sym} 1030 -300 0 0 {name=l26b lab=rst_n}
C {lab_pin.sym} 1070 -330 0 0 {name=l27b lab=vdd}
C {lab_pin.sym} 1070 -300 0 0 {name=l28b lab=vdd}
C {lab_pin.sym} 920 -130 0 0 {name=l29 lab=mb}
C {lab_pin.sym} 880 -100 0 0 {name=l30 lab=m}
C {lab_pin.sym} 920 -70 0 0 {name=l31 lab=mmid}
C {lab_pin.sym} 920 -100 0 0 {name=l32 lab=vss}
C {lab_pin.sym} 1070 -130 0 0 {name=l29b lab=mmid}
C {lab_pin.sym} 1030 -100 0 0 {name=l30b lab=rst_n}
C {lab_pin.sym} 1070 -70 0 0 {name=l31b lab=vss}
C {lab_pin.sym} 1070 -100 0 0 {name=l32b lab=vss}
C {lab_pin.sym} 1220 -270 0 0 {name=l33 lab=mc}
C {lab_pin.sym} 1180 -300 0 0 {name=l34 lab=mb}
C {lab_pin.sym} 1220 -330 0 0 {name=l35 lab=vdd}
C {lab_pin.sym} 1220 -300 0 0 {name=l36 lab=vdd}
C {lab_pin.sym} 1220 -130 0 0 {name=l37 lab=mc}
C {lab_pin.sym} 1180 -100 0 0 {name=l38 lab=mb}
C {lab_pin.sym} 1220 -70 0 0 {name=l39 lab=vss}
C {lab_pin.sym} 1220 -100 0 0 {name=l40 lab=vss}
C {lab_pin.sym} 1520 -270 0 0 {name=l41 lab=mc}
C {lab_pin.sym} 1480 -300 0 0 {name=l42 lab=clkb}
C {lab_pin.sym} 1520 -330 0 0 {name=l43 lab=m}
C {lab_pin.sym} 1520 -300 0 0 {name=l44 lab=vdd}
C {lab_pin.sym} 1520 -130 0 0 {name=l45 lab=mc}
C {lab_pin.sym} 1480 -100 0 0 {name=l46 lab=clk}
C {lab_pin.sym} 1520 -70 0 0 {name=l47 lab=m}
C {lab_pin.sym} 1520 -100 0 0 {name=l48 lab=vss}
C {lab_pin.sym} 1820 -270 0 0 {name=l49 lab=mb}
C {lab_pin.sym} 1780 -300 0 0 {name=l50 lab=clkb}
C {lab_pin.sym} 1820 -330 0 0 {name=l51 lab=s}
C {lab_pin.sym} 1820 -300 0 0 {name=l52 lab=vdd}
C {lab_pin.sym} 1820 -130 0 0 {name=l53 lab=mb}
C {lab_pin.sym} 1780 -100 0 0 {name=l54 lab=clk}
C {lab_pin.sym} 1820 -70 0 0 {name=l55 lab=s}
C {lab_pin.sym} 1820 -100 0 0 {name=l56 lab=vss}
C {lab_pin.sym} 2120 -270 0 0 {name=l57 lab=q}
C {lab_pin.sym} 2080 -300 0 0 {name=l58 lab=s}
C {lab_pin.sym} 2120 -330 0 0 {name=l59 lab=vdd}
C {lab_pin.sym} 2120 -300 0 0 {name=l60 lab=vdd}
C {lab_pin.sym} 2120 -130 0 0 {name=l61 lab=q}
C {lab_pin.sym} 2080 -100 0 0 {name=l62 lab=s}
C {lab_pin.sym} 2120 -70 0 0 {name=l63 lab=vss}
C {lab_pin.sym} 2120 -100 0 0 {name=l64 lab=vss}
C {lab_pin.sym} 2420 -270 0 0 {name=l65 lab=qb}
C {lab_pin.sym} 2380 -300 0 0 {name=l66 lab=q}
C {lab_pin.sym} 2420 -330 0 0 {name=l67 lab=vdd}
C {lab_pin.sym} 2420 -300 0 0 {name=l68 lab=vdd}
C {lab_pin.sym} 2570 -270 0 0 {name=l65b lab=qb}
C {lab_pin.sym} 2530 -300 0 0 {name=l66b lab=rst_n}
C {lab_pin.sym} 2570 -330 0 0 {name=l67b lab=vdd}
C {lab_pin.sym} 2570 -300 0 0 {name=l68b lab=vdd}
C {lab_pin.sym} 2420 -130 0 0 {name=l69 lab=qb}
C {lab_pin.sym} 2380 -100 0 0 {name=l70 lab=q}
C {lab_pin.sym} 2420 -70 0 0 {name=l71 lab=s2mid}
C {lab_pin.sym} 2420 -100 0 0 {name=l72 lab=vss}
C {lab_pin.sym} 2570 -130 0 0 {name=l69b lab=s2mid}
C {lab_pin.sym} 2530 -100 0 0 {name=l70b lab=rst_n}
C {lab_pin.sym} 2570 -70 0 0 {name=l71b lab=vss}
C {lab_pin.sym} 2570 -100 0 0 {name=l72b lab=vss}
C {lab_pin.sym} 2720 -270 0 0 {name=l73 lab=qb}
C {lab_pin.sym} 2680 -300 0 0 {name=l74 lab=clk}
C {lab_pin.sym} 2720 -330 0 0 {name=l75 lab=s}
C {lab_pin.sym} 2720 -300 0 0 {name=l76 lab=vdd}
C {lab_pin.sym} 2720 -130 0 0 {name=l77 lab=qb}
C {lab_pin.sym} 2680 -100 0 0 {name=l78 lab=clkb}
C {lab_pin.sym} 2720 -70 0 0 {name=l79 lab=s}
C {lab_pin.sym} 2720 -100 0 0 {name=l80 lab=vss}
