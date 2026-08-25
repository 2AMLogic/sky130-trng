v {xschem version=3.4.4 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {trng_top -- the top-level integration.

Ported from gf180-trng's design/xschem/trng_top.sch.

This schematic is the ANALOG half of the top-level assembly, and it stops
exactly at the raw tap -- the same boundary the behavioural/transistor
verification split draws for the whole repository. It instantiates
sampler_core.sym (the entropy source, plus the sampler_dff instances that
digitize xo into raw_bit/raw_valid and ro1..ro4 into ring_bit1..ring_bit4)
UNMODIFIED: no device here differs from design/xschem/sampler_core.sch, so
this cell adds a name and a place in the hierarchy, not a new circuit.

The digital blocks -- conditioner, health tests and register interface --
are deliberately NOT instantiated here, and in this repository they do not
exist yet at all. Drawing them as SPICE subcircuits in this file would
either fabricate a netlist for circuits nobody has designed, or paper over
empty .subckt stubs that ngspice cannot simulate. Both are worse than
naming the boundary and stopping at it. When those blocks land they cross
the boundary as behavioural models and RTL, not as devices in this file.

Pin-for-pin, this schematic's four raw-tap pins are what the digital half
will consume:

  clk        the block's fixed external sample clock, 50 kHz per DR-0003
  rst_n      async, active-low reset
  raw_bit    the raw tap -- one digitized sample per clk edge
  raw_valid  high one clk edge after rst_n releases, and stays high

and the per-ring liveness taps cross the same boundary, one bit per ring:

  ring_bit1..ring_bit4   each ring's own digitized sample

That is four bits rather than two because issue #13 rebuilt the array
from N = 2 to N = 4 (spec/decision-records/DR-0003-sky130-trng-operating-
point, status Proposed). The tap count tracks the ring count by
construction: a liveness monitor that cannot see a ring cannot report it,
and a stuck ring is invisible at the combined node xo because it
contributes a constant to the XOR.

en1..en4 / vddr1..vddr4 / vdd / vss are forwarded straight through to
sampler_core.sym, unchanged from what design/xschem/sampler_core.sch
already does; ring enable and start-up sequencing are not this cell's job
either, for the same reason.

WHAT IS AND IS NOT SIMULATED. This top-level assembly has not been
simulated as a whole. Its entropy source has: ro_array_core as drawn here
is exercised end to end by sim/ro-array-core-combining/ (per-ring
frequencies, combining-node edge retention, total array supply current),
its ring by sim/ro-ring5-swing-and-current/ and
sim/ro-ring-jitter-accumulation/, and its combining gate by
sim/xor-combining-bandwidth/. The sampler_dff instances this file pulls in
have NOT been simulated at all -- no setup/hold, no metastability, no
clock-path characterization exists -- so nothing downstream of xo in this
hierarchy carries evidence yet. Device widths, the starve length and the
wstv skew ladder likewise remain placeholders; see design/README.md's
"Provisional, not sized" table, which marks every row measured, refuted or
placeholder, and spec/porting-plan.md sections 2 and 3 for the remaining
inventory.} -1400 -800 0 0 0.2 0.2 {}
C {ipin.sym} -1000 -300 0 0 {name=pe1 lab=en1}
C {ipin.sym} -1000 -250 0 0 {name=pe2 lab=en2}
C {ipin.sym} -1000 -200 0 0 {name=pe3 lab=en3}
C {ipin.sym} -1000 -150 0 0 {name=pe4 lab=en4}
C {iopin.sym} -800 -300 0 0 {name=pv1 lab=vddr1}
C {iopin.sym} -800 -250 0 0 {name=pv2 lab=vddr2}
C {iopin.sym} -800 -200 0 0 {name=pv3 lab=vddr3}
C {iopin.sym} -800 -150 0 0 {name=pv4 lab=vddr4}
C {iopin.sym} -600 -300 0 0 {name=pv lab=vdd}
C {iopin.sym} -600 -250 0 0 {name=ps lab=vss}
C {ipin.sym} -600 -200 0 0 {name=pc lab=clk}
C {ipin.sym} -600 -150 0 0 {name=pr lab=rst_n}
C {opin.sym} -600 -100 0 0 {name=pb lab=raw_bit}
C {opin.sym} -600 -50 0 0 {name=pvv lab=raw_valid}
C {opin.sym} -600 0 0 0 {name=pr1 lab=ring_bit1}
C {opin.sym} -600 50 0 0 {name=pr2 lab=ring_bit2}
C {opin.sym} -600 100 0 0 {name=pr3 lab=ring_bit3}
C {opin.sym} -600 150 0 0 {name=pr4 lab=ring_bit4}
C {sampler_core.sym} 0 0 0 0 {name=xsc}
C {lab_pin.sym} -150 -75 0 1 {name=l1 lab=en1}
C {lab_pin.sym} -150 -25 0 1 {name=l2 lab=en2}
C {lab_pin.sym} -150 25 0 1 {name=l3 lab=en3}
C {lab_pin.sym} -150 75 0 1 {name=l4 lab=en4}
C {lab_pin.sym} -75 155 0 0 {name=l9 lab=vddr1}
C {lab_pin.sym} -25 155 0 0 {name=l10 lab=vddr2}
C {lab_pin.sym} 25 155 0 0 {name=l11 lab=vddr3}
C {lab_pin.sym} 75 155 0 0 {name=l12 lab=vddr4}
C {lab_pin.sym} -50 -155 0 0 {name=l17 lab=vdd}
C {lab_pin.sym} 50 -155 0 0 {name=l18 lab=vss}
C {lab_pin.sym} -150 -175 0 1 {name=l19 lab=clk}
C {lab_pin.sym} -150 170 0 1 {name=l20 lab=rst_n}
C {lab_pin.sym} 150 -175 0 0 {name=l21 lab=raw_bit}
C {lab_pin.sym} 150 170 0 0 {name=l22 lab=raw_valid}
C {lab_pin.sym} 150 -75 0 0 {name=l23 lab=ring_bit1}
C {lab_pin.sym} 150 -25 0 0 {name=l24 lab=ring_bit2}
C {lab_pin.sym} 150 25 0 0 {name=l25 lab=ring_bit3}
C {lab_pin.sym} 150 75 0 0 {name=l26 lab=ring_bit4}
