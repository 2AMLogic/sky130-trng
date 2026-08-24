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
digitize xo into raw_bit/raw_valid and ro1/ro2 into ring_bit1/ring_bit2)
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

  clk        the block's fixed external sample clock
  rst_n      async, active-low reset
  raw_bit    the raw tap -- one digitized sample per clk edge
  raw_valid  high one clk edge after rst_n releases, and stays high

and the two per-ring liveness taps cross the same boundary, one bit per
ring:

  ring_bit1  ring 1's digitized sample
  ring_bit2  ring 2's digitized sample

en1/en2/vddr1/vddr2/vdd/vss are forwarded straight through to
sampler_core.sym, unchanged from what design/xschem/sampler_core.sch
already does; ring enable and start-up sequencing are not this cell's job
either, for the same reason.

NOTHING IN THIS HIERARCHY HAS BEEN SIMULATED. These schematics are design
sources, not evidence. Every device size, the ring stage count, the array
size and the frequency skew are provisional placeholders carried over from
gf180-trng's topology and re-expressed on sky130's 1.8 V core devices --
see ro_stage.sch, ro_array_core.sch and
spec/decision-records/DR-0001-sky130-operating-envelope.md. The
characterization and corner work that would turn any of them into a result
is inventoried in spec/porting-plan.md sections 2 and 3 and is separate,
later scope.} -1400 -900 0 0 0.2 0.2 {}
C {ipin.sym} -1000 -300 0 0 {name=pe1 lab=en1}
C {ipin.sym} -1000 -250 0 0 {name=pe2 lab=en2}
C {iopin.sym} -1000 -200 0 0 {name=pv1 lab=vddr1}
C {iopin.sym} -1000 -150 0 0 {name=pv2 lab=vddr2}
C {iopin.sym} -1000 -100 0 0 {name=pv lab=vdd}
C {iopin.sym} -1000 -50 0 0 {name=ps lab=vss}
C {ipin.sym} -1000 0 0 0 {name=pc lab=clk}
C {ipin.sym} -1000 50 0 0 {name=pr lab=rst_n}
C {opin.sym} -1000 100 0 0 {name=pb lab=raw_bit}
C {opin.sym} -1000 150 0 0 {name=pvv lab=raw_valid}
C {opin.sym} -1000 200 0 0 {name=pr1 lab=ring_bit1}
C {opin.sym} -1000 250 0 0 {name=pr2 lab=ring_bit2}
C {sampler_core.sym} 0 0 0 0 {name=xsc}
C {lab_pin.sym} -70 -60 0 1 {name=l1 lab=en1}
C {lab_pin.sym} -70 -20 0 1 {name=l2 lab=en2}
C {lab_pin.sym} -30 100 0 0 {name=l3 lab=vddr1}
C {lab_pin.sym} 0 100 0 0 {name=l4 lab=vddr2}
C {lab_pin.sym} 30 100 0 0 {name=l5 lab=vdd}
C {lab_pin.sym} 0 -100 0 0 {name=l6 lab=vss}
C {lab_pin.sym} -70 20 0 1 {name=l7 lab=clk}
C {lab_pin.sym} -70 60 0 1 {name=l8 lab=rst_n}
C {lab_pin.sym} 70 -20 0 0 {name=l9 lab=raw_bit}
C {lab_pin.sym} 70 20 0 0 {name=l10 lab=raw_valid}
C {lab_pin.sym} 70 -60 0 0 {name=l11 lab=ring_bit1}
C {lab_pin.sym} 70 60 0 0 {name=l12 lab=ring_bit2}
