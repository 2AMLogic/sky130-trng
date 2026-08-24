v {xschem version=3.4.4 file_version=1.2}
G {wstv=0.42 lstv=2 cld=0.5f}
K {}
V {}
S {}
E {}
T {ro_ring5 -- the five-stage variant of the array's ring: a starved NAND2
enable stage followed by four starved inverters, closed on itself. Same
leaf cells, same starve parameters and same per-ring supply pin as
ro_ring11; only the stage count differs.

Ported from gf180-trng's design/xschem/ro_ring5.sch.

STAGE COUNT IS PROVISIONAL. This cell is not "the five-stage answer" for
sky130 and ro_ring11 is not "the eleven-stage answer" either. Both stage
counts are carried over from gf180-trng, where the choice between them was
settled by MEASURED small-signal gain of that PDK's starved cell and by a
measured ring swing. Neither measurement has a sky130 counterpart yet.
spec/porting-plan.md section 2.2 is explicit that gf180-trng's sizing
arithmetic is computed entirely from gf180mcu-measured sigma_1 / T_0
figures and that none of those numbers are portable.

Why the repository carries two stage counts at all -- and this part IS
process-independent, so it ports:

  * Affordability. A transient-noise run resolves every stage of every ring
    at picosecond steps, so its cost scales with N x stages x t_stop. A
    five-stage ring is roughly 2.2x cheaper per unit of simulated time than
    an eleven-stage one, which can be the difference between a run that
    fits in a session and one that does not.
  * Comparability. A per-ring jitter characterization is naturally run on a
    small ring; matching the array's ring to that stage count makes the
    array's per-ring sigma_1 comparable to the characterization
    stage-for-stage, with the delay cell as the only variable.

Three stages is the minimum an inverting ring allows and would be cheaper
still, but a starved cell may not have the per-stage gain for it: a
three-stage ring needs about 2.0 of small-signal gain per stage against a
five-stage ring's roughly 1.24. Whether sky130's starved ro_stage clears
either bar is exactly the kind of thing this port must MEASURE rather than
inherit -- see spec/porting-plan.md sections 2.2 and 3.2.} -700 -900 0 0 0.25 0.25 {}
C {ipin.sym} -700 -400 0 0 {name=p1 lab=en}
C {opin.sym} -600 -400 0 0 {name=p2 lab=ro}
C {iopin.sym} -700 -350 0 0 {name=p3 lab=vddr}
C {iopin.sym} -600 -350 0 0 {name=p4 lab=vss}
C {ro_nand2.sym} 0 0 0 0 {name=xg wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 300 0 0 0 {name=x1 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 600 0 0 0 {name=x2 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 900 0 0 0 {name=x3 wstv=wstv lstv=lstv cld=cld}
C {ro_stage.sym} 1200 0 0 0 {name=x4 wstv=wstv lstv=lstv cld=cld}
N 50 -10 250 -10 {lab=n1}
N 350 -10 550 -10 {lab=n2}
N 650 -10 850 -10 {lab=n3}
N 950 -10 1150 -10 {lab=n4}
N 1250 -10 1350 -10 {lab=ro}
N 1350 -10 1350 -140 {lab=ro}
N -150 -140 1350 -140 {lab=ro}
N -150 -140 -150 -30 {lab=ro}
N -150 -30 -50 -30 {lab=ro}
C {lab_pin.sym} 150 -10 0 0 {name=ln1 lab=n1}
C {lab_pin.sym} 450 -10 0 0 {name=ln2 lab=n2}
C {lab_pin.sym} 750 -10 0 0 {name=ln3 lab=n3}
C {lab_pin.sym} 1050 -10 0 0 {name=ln4 lab=n4}
C {lab_pin.sym} 600 -140 0 0 {name=lro lab=ro}
C {lab_pin.sym} -50 10 0 1 {name=len lab=en}
C {lab_pin.sym} 0 -50 0 0 {name=lv0 lab=vddr}
C {lab_pin.sym} 300 -50 0 0 {name=lv1 lab=vddr}
C {lab_pin.sym} 600 -50 0 0 {name=lv2 lab=vddr}
C {lab_pin.sym} 900 -50 0 0 {name=lv3 lab=vddr}
C {lab_pin.sym} 1200 -50 0 0 {name=lv4 lab=vddr}
C {lab_pin.sym} 0 50 0 0 {name=ls0 lab=vss}
C {lab_pin.sym} 300 50 0 0 {name=ls1 lab=vss}
C {lab_pin.sym} 600 50 0 0 {name=ls2 lab=vss}
C {lab_pin.sym} 900 50 0 0 {name=ls3 lab=vss}
C {lab_pin.sym} 1200 50 0 0 {name=ls4 lab=vss}
