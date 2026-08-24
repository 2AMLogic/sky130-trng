v {xschem version=3.4.4 file_version=1.2}
G {wstv=0.42 lstv=2 cld=0.5f}
K {}
V {}
S {}
E {}
T {ro_nand2 -- series-starved minimum-width NAND2, the enable/stop stage of
one ring of the entropy-source array.

Ported from gf180-trng's design/xschem/ro_nand2.sch onto sky130's 1.8 V
core pair (sky130_fd_pr__nfet_01v8 / __pfet_01v8).

  en = 1 : the stage is an inverter of a and the ring oscillates.
  en = 0 : y is held at vddr, the ring latches in a static state and draws
           only leakage. Per-ring stop is what an "idle" block state means
           (all rings stopped, block powered), and it is also the handle a
           per-ring liveness check needs.

Sizing is PROVISIONAL -- see ro_stage.sch for the full note. The series
NMOS pair is widened to 0.84 um (2x sky130's 0.42 um minimum) so the
stack's pull-down drive roughly matches the single 0.42 um NMOS of
ro_stage; the parallel PMOS stay at the same 0.84 um as ro_stage's PMOS.
Mph/Mnt are the same always-on starve devices as ro_stage, parameterised by
the same wstv/lstv, so every stage of a ring is starved by the same W/L and
the ring's stage delays stay matched.

The 2x series-stack compensation is a rule of thumb carried over from the
gf180-trng cell, not a sky130 measurement. What would replace it: a
stage-delay match check across the corner grid in spec/porting-plan.md
section 3.1, alongside the jitter characterization in section 2.2.} -700 -700 0 0 0.25 0.25 {}
C {ipin.sym} -700 -420 0 0 {name=p1 lab=a}
C {ipin.sym} -700 -380 0 0 {name=p2 lab=en}
C {opin.sym} -620 -420 0 0 {name=p3 lab=y}
C {iopin.sym} -700 -340 0 0 {name=p4 lab=vddr}
C {iopin.sym} -620 -340 0 0 {name=p5 lab=vss}
C {sky130_fd_pr/pfet_01v8.sym} 0 -500 0 0 {name=Mph L=lstv W=wstv nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 0 -400 0 0 {name=Mpa L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 200 -400 0 0 {name=Mpb L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 0 -300 0 0 {name=Mna L=0.15 W=0.84 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 0 -200 0 0 {name=Mnb L=0.15 W=0.84 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 0 -100 0 0 {name=Mnt L=lstv W=wstv nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {capa.sym} 400 -320 0 0 {name=Cld m=1 value='cld'}
N 20 -470 20 -430 {lab=py}
N 20 -450 220 -450 {lab=py}
N 220 -450 220 -430 {lab=py}
N 20 -370 20 -330 {lab=y}
N 20 -350 220 -350 {lab=y}
N 220 -370 220 -350 {lab=y}
N 220 -350 400 -350 {lab=y}
N 20 -270 20 -230 {lab=nm}
N 20 -170 20 -130 {lab=ny}
N -20 -400 -20 -300 {lab=a}
C {lab_pin.sym} 20 -450 0 0 {name=lpy lab=py}
C {lab_pin.sym} 100 -350 0 0 {name=ly lab=y}
C {lab_pin.sym} 20 -250 0 0 {name=lnm lab=nm}
C {lab_pin.sym} 20 -150 0 0 {name=lny lab=ny}
C {lab_pin.sym} -20 -350 0 1 {name=la lab=a}
C {lab_pin.sym} 180 -400 0 1 {name=len1 lab=en}
C {lab_pin.sym} -20 -200 0 1 {name=len2 lab=en}
C {lab_pin.sym} 20 -530 0 0 {name=lv1 lab=vddr}
C {lab_pin.sym} 20 -500 0 0 {name=lv2 lab=vddr}
C {lab_pin.sym} 20 -400 0 0 {name=lv3 lab=vddr}
C {lab_pin.sym} 220 -400 0 0 {name=lv4 lab=vddr}
C {lab_pin.sym} -20 -100 0 1 {name=lv5 lab=vddr}
C {lab_pin.sym} -20 -500 0 1 {name=ls1 lab=vss}
C {lab_pin.sym} 20 -300 0 0 {name=ls2 lab=vss}
C {lab_pin.sym} 20 -200 0 0 {name=ls3 lab=vss}
C {lab_pin.sym} 20 -100 0 0 {name=ls4 lab=vss}
C {lab_pin.sym} 20 -70 0 0 {name=ls5 lab=vss}
C {lab_pin.sym} 400 -290 0 0 {name=ls6 lab=vss}
