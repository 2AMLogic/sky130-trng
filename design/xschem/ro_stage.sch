v {xschem version=3.4.4 file_version=1.2}
G {wstv=0.42 lstv=2 cld=0.5f}
K {}
V {}
S {}
E {}
T {ro_stage -- series-starved minimum-width 1.8 V inverter delay cell.

Ported from gf180-trng's design/xschem/ro_stage.sch. The TOPOLOGY is the
port: a minimum-width inverter (Mp/Mn) with always-on series starve devices
(Mph/Mnt, gates tied to the opposite rail) that set the charge/discharge
current -- and therefore the stage delay -- WITHOUT adding switched
capacitance to the output node y. That separation is the reason the cell is
drawn this way: starving buys ring frequency without raising the energy
switched per ring cycle, and the entropy-per-ring-power law the array is
sized against is quadratic in that energy.

Devices are sky130_fd_pr__nfet_01v8 / __pfet_01v8, the 1.8 V core pair, per
spec/porting-plan.md section 2.1 and spec/decision-records/
DR-0001-sky130-operating-envelope.md. sky130 has no matched 3.3 V core N/P
pair, so the gf180mcu nfet_03v3/pfet_03v3 devices this cell was drawn on do
not have a like-for-like sky130 counterpart; the 1.8 V pair is the only
symmetric core-device choice.

EVERY NUMBER BELOW IS PROVISIONAL. None of it is a sized result.
sky130 minimum geometry is L = 0.15 um, W = 0.42 um (contrast gf180mcu's
3.3 V core: L = 0.28 um, W = 0.22 um), so:

  Mn   W = 0.42 um   sky130 minimum width
  Mp   W = 0.84 um   2x Mn, carrying over gf180-trng's own P:N ratio as a
                     starting point -- NOT a re-derived sky130 ratio. The
                     mobility ratio that sets a balanced trip point differs
                     between the two processes and has not been measured
                     here.
  L    0.15 um       sky130 minimum drawn length
  lstv 2 um          starve length, carried over unchanged from gf180-trng.
                     gf180-trng arrived at 2 um by MEASURING an array power
                     rollup against its own ratified power row; no such
                     measurement exists on sky130 yet, so this is a
                     placeholder, not a conclusion.
  wstv 0.42 um       starve width at sky130 minimum. Per-ring frequency skew
                     is set by varying this parameter -- see
                     ro_array_core.sch.
  cld  0.5f          explicit placeholder for local interconnect load. An
                     estimate, not an extracted parasitic, and carried over
                     at gf180-trng's value even though sky130's metal stack
                     is different. Layout owes either an extraction at or
                     below cld, or a superseding sizing pass.

What would replace these numbers: the sky130 jitter-characterization work
named in spec/porting-plan.md section 2.2 -- transient-noise runs over this
cell across the corner grid in section 3.1, which is where sigma_1 and T_0
come from, and therefore where the ring/array sizing comes from. That work
is a separate, later issue. Nothing in this file is evidence.} -560 -420 0 0 0.25 0.25 {}
C {ipin.sym} -560 -150 0 0 {name=p1 lab=a}
C {opin.sym} -480 -150 0 0 {name=p2 lab=y}
C {iopin.sym} -560 -100 0 0 {name=p3 lab=vddr}
C {iopin.sym} -480 -100 0 0 {name=p4 lab=vss}
C {sky130_fd_pr/pfet_01v8.sym} 0 -300 0 0 {name=Mph L=lstv W=wstv nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 0 -200 0 0 {name=Mp L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 0 -100 0 0 {name=Mn L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=Mnt L=lstv W=wstv nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {capa.sym} 200 -120 0 0 {name=Cld m=1 value='cld'}
N 20 -270 20 -230 {lab=py}
N 20 -170 20 -130 {lab=y}
N 20 -70 20 -30 {lab=ny}
N -20 -200 -20 -100 {lab=a}
N 20 -150 200 -150 {lab=y}
C {lab_pin.sym} 20 -250 0 0 {name=lpy lab=py}
C {lab_pin.sym} -20 -150 0 1 {name=la lab=a}
C {lab_pin.sym} 100 -150 0 0 {name=ly lab=y}
C {lab_pin.sym} 20 -50 0 0 {name=lny lab=ny}
C {lab_pin.sym} 20 -330 0 0 {name=lv1 lab=vddr}
C {lab_pin.sym} 20 -300 0 0 {name=lv2 lab=vddr}
C {lab_pin.sym} 20 -200 0 0 {name=lv3 lab=vddr}
C {lab_pin.sym} -20 0 0 1 {name=lv4 lab=vddr}
C {lab_pin.sym} -20 -300 0 1 {name=ls1 lab=vss}
C {lab_pin.sym} 20 -100 0 0 {name=ls2 lab=vss}
C {lab_pin.sym} 20 0 0 0 {name=ls3 lab=vss}
C {lab_pin.sym} 20 30 0 0 {name=ls4 lab=vss}
C {lab_pin.sym} 200 -90 0 0 {name=ls5 lab=vss}
