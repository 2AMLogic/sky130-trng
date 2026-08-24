v {xschem version=3.4.4 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {ro_buf -- minimum-width, UNSTARVED 1.8 V inverter: the per-ring output
buffer.

Ported from gf180-trng's design/xschem/ro_buf.sch. ro_array_core.sch
instantiates one per ring, between that ring's own last stage and every
consumer (the XOR combiner, and one level up the sampler and the per-ring
liveness digitizers).

Why the buffer is in the topology at all. A consumer's own input-stage
capacitance injects charge BACKWARDS into whatever drives it. Driving the
consumer from a low-impedance, actively-driven buffer output instead of
from the ring's own high-impedance oscillating node keeps that path from
landing on the ring node itself. gf180-trng MEASURED how much this is
worth on gf180mcu; that measurement is not portable and is not repeated
here, so the buffer is ported as a structural feature of the source, with
its sky130 effect left to be measured by the ring-coupling work
spec/porting-plan.md section 3.2 inventories.

Unlike ro_stage this inverter has NO series starve devices: it is not part
of a ring's frequency-setting delay chain.

Supply: this cell runs off vdd/vss -- the BLOCK supply, the same one the
XOR combiner uses -- not off either ring's vddr. That keeps each ring's
vddr pin a pure per-ring current signature, which is what the per-ring
independence requirement and the per-ring liveness observation point both
depend on. The buffer adds no switching current to either ring's own
supply branch.

Polarity: y = NOT a. Every consumer sees the COMPLEMENT of the node driving
a. a XOR b == (NOT a) XOR (NOT b), so a combiner fed from two buffered
rings is bit-identical to one fed directly, and a transition-counting
liveness monitor is polarity-blind. Nothing downstream needs a matching
change, but a reader of a buffered node's level should not assume it is the
ring's own sense.

Sizing is PROVISIONAL and identical to xor2's input-stage inverter:
Mp W = 0.84 um, Mn W = 0.42 um, both L = 0.15 um, on
sky130_fd_pr__pfet_01v8 / __nfet_01v8. W = 0.42 um is sky130's minimum
device width and L = 0.15 um its minimum drawn length; the 2:1 P:N ratio is
carried over from gf180-trng rather than re-derived for sky130's own
mobility ratio. See ro_stage.sch for the full provisional-sizing note.} -700 -650 0 0 0.25 0.25 {}
C {ipin.sym} -560 -150 0 0 {name=p1 lab=a}
C {opin.sym} -480 -150 0 0 {name=p2 lab=y}
C {iopin.sym} -560 -100 0 0 {name=p3 lab=vdd}
C {iopin.sym} -480 -100 0 0 {name=p4 lab=vss}
C {sky130_fd_pr/pfet_01v8.sym} 0 -200 0 0 {name=Mp L=0.15 W=0.84 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 0 -100 0 0 {name=Mn L=0.15 W=0.42 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
N 20 -170 20 -130 {lab=y}
N 20 -150 200 -150 {lab=y}
N -20 -200 -20 -100 {lab=a}
C {lab_pin.sym} -20 -150 0 1 {name=la lab=a}
C {lab_pin.sym} 100 -150 0 0 {name=ly lab=y}
C {lab_pin.sym} 20 -230 0 0 {name=lv1 lab=vdd}
C {lab_pin.sym} 20 -200 0 0 {name=lvb lab=vdd}
C {lab_pin.sym} 20 -70 0 0 {name=ls1 lab=vss}
C {lab_pin.sym} 20 -100 0 0 {name=lsb lab=vss}
