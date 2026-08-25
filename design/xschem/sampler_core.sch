v {xschem version=3.4.4 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sampler_core -- the sampler, wired to the source.

Ported from gf180-trng's design/xschem/sampler_core.sch.

Instantiates ro_array_core (the XOR-combined ring array) and samples its xo
node with two sampler_dff instances sharing one external clock and one
async reset, plus FOUR MORE instances of the SAME cell digitizing the four
per-ring observation outputs for the liveness monitor:

  xsb        D = xo    -> raw_bit       the raw tap, after digitization
  xsv        D = vdd   -> raw_valid     registered "out of reset" indicator
  xsr1..4    D = ro1..4 -> ring_bit1..4 each ring's own digitized sample

The ring-tap count follows the array. Issue #13 rebuilt ro_array_core from
2 rings to 4 (DR-0003, Proposed), and a liveness monitor that can only see
2 of 4 rings cannot report the other 2 -- which is the entire reason those
observation outputs exist. So this cell grows one sampler_dff per ring
rather than keeping the two it had. No new cell type is introduced: it is
the same sampler_dff the raw tap uses, six times.

Why the ring taps are HERE and not in ro_array_core: a digitizer needs a
clock, and ro_array_core is a free-running analog source with none -- the
sample clock enters the design at this level and this is already the cell
that owns it. So ro_array_core exposes ro1..ro4 as observation-only outputs
and this cell does the sampling, reusing the same sampler_dff the raw tap
uses rather than designing a second cell for the monitor.

The electrical cost of those taps -- gate capacitance on ro1..ro4 -- is
something to MEASURE on sky130 rather than assume, and part of it now is
measured: sim/ro-ring5-swing-and-current/ shows that adding ONE inverter
load (ro_buf) to a ring node slows the ring by 13-20 percent, and
DR-0003's sizing uses that loaded period rather than the unloaded one. The
sampler_dff tap sits on the BUFFERED node ro_i, not on the ring node, so
the buffer isolates the ring from it -- but the buffer's own delay and the
tap's load on the buffer output are still unmeasured, and the ring-liveness
tap-power testbench in spec/porting-plan.md section 3.2 is what owes that
number.

xo never leaves this schematic as a pin: the raw tap sits at the SAMPLER's
output, after digitization, not at the array's internal combining node.

xsv's D is tied permanently to vdd (logic 1), so raw_valid is low only
during and immediately after reset and goes high, and stays high, one clk
edge after rst_n releases -- a one-cycle reset synchronizer built from the
same cell as the data path rather than a second bespoke circuit.

clk / rst_n are the block's FIXED EXTERNAL sample clock and its async
active-low reset -- see sampler_dff.sch for why the clock is external
rather than divided down from either ring. This schematic contains no
divider and no clock-generation circuitry; that is the point of the
decision, not an omission. DR-0003 fixes that clock's frequency at 50 kHz
(T_s = 20 us) for the 50 kbps raw-rate row, and notes that because the
clock is external the rate row is the ONE sizing input that can be revised
after tape-out without touching a transistor: N is topology, T_s is a
clock choice.

en1..en4 / vddr1..vddr4 are forwarded straight through to ro_array_core --
ring enable and start-up sequencing are not this cell's job. vdd/vss feed
the array's combining tree, its ring buffers and all six samplers; the
rings keep their own separate vddr1..vddr4, untouched by this wrapper.

Everything downstream of raw_bit/raw_valid (the conditioner, the health
tests and the register interface) is digital and appears nowhere in this
file: the analog/digital verification boundary is drawn exactly at this
cell's outputs.} -1400 -1000 0 0 0.2 0.2 {}
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
C {ro_array_core.sym} 0 0 0 0 {name=xdut}
C {lab_pin.sym} -100 -75 0 1 {name=l1 lab=en1}
C {lab_pin.sym} -100 -25 0 1 {name=l2 lab=en2}
C {lab_pin.sym} -100 25 0 1 {name=l3 lab=en3}
C {lab_pin.sym} -100 75 0 1 {name=l4 lab=en4}
C {lab_pin.sym} -75 -100 0 0 {name=l9 lab=vddr1}
C {lab_pin.sym} -25 -100 0 0 {name=l10 lab=vddr2}
C {lab_pin.sym} 25 -100 0 0 {name=l11 lab=vddr3}
C {lab_pin.sym} 75 -100 0 0 {name=l12 lab=vddr4}
C {lab_pin.sym} -50 100 0 0 {name=l17 lab=vdd}
C {lab_pin.sym} 50 100 0 0 {name=l18 lab=vss}
C {lab_pin.sym} 100 0 0 0 {name=l19 lab=xo}
C {lab_pin.sym} 100 -75 0 0 {name=l20 lab=ro1}
C {lab_pin.sym} 100 -25 0 0 {name=l21 lab=ro2}
C {lab_pin.sym} 100 25 0 0 {name=l22 lab=ro3}
C {lab_pin.sym} 100 75 0 0 {name=l23 lab=ro4}
C {sampler_dff.sym} 500 -600 0 0 {name=xsb}
C {lab_pin.sym} 450 -630 0 0 {name=l28 lab=xo}
C {lab_pin.sym} 450 -600 0 0 {name=l29 lab=clk}
C {lab_pin.sym} 450 -570 0 0 {name=l30 lab=rst_n}
C {lab_pin.sym} 550 -600 0 0 {name=l31 lab=raw_bit}
C {lab_pin.sym} 500 -650 0 0 {name=l32 lab=vdd}
C {lab_pin.sym} 500 -550 0 0 {name=l33 lab=vss}
C {sampler_dff.sym} 500 -300 0 0 {name=xsv}
C {lab_pin.sym} 450 -330 0 0 {name=l34 lab=vdd}
C {lab_pin.sym} 450 -300 0 0 {name=l35 lab=clk}
C {lab_pin.sym} 450 -270 0 0 {name=l36 lab=rst_n}
C {lab_pin.sym} 550 -300 0 0 {name=l37 lab=raw_valid}
C {lab_pin.sym} 500 -350 0 0 {name=l38 lab=vdd}
C {lab_pin.sym} 500 -250 0 0 {name=l39 lab=vss}
C {sampler_dff.sym} 900 -700 0 0 {name=xsr1}
C {lab_pin.sym} 850 -730 0 0 {name=l40 lab=ro1}
C {lab_pin.sym} 850 -700 0 0 {name=l41 lab=clk}
C {lab_pin.sym} 850 -670 0 0 {name=l42 lab=rst_n}
C {lab_pin.sym} 950 -700 0 0 {name=l43 lab=ring_bit1}
C {lab_pin.sym} 900 -750 0 0 {name=l44 lab=vdd}
C {lab_pin.sym} 900 -650 0 0 {name=l45 lab=vss}
C {sampler_dff.sym} 900 -500 0 0 {name=xsr2}
C {lab_pin.sym} 850 -530 0 0 {name=l46 lab=ro2}
C {lab_pin.sym} 850 -500 0 0 {name=l47 lab=clk}
C {lab_pin.sym} 850 -470 0 0 {name=l48 lab=rst_n}
C {lab_pin.sym} 950 -500 0 0 {name=l49 lab=ring_bit2}
C {lab_pin.sym} 900 -550 0 0 {name=l50 lab=vdd}
C {lab_pin.sym} 900 -450 0 0 {name=l51 lab=vss}
C {sampler_dff.sym} 900 -300 0 0 {name=xsr3}
C {lab_pin.sym} 850 -330 0 0 {name=l52 lab=ro3}
C {lab_pin.sym} 850 -300 0 0 {name=l53 lab=clk}
C {lab_pin.sym} 850 -270 0 0 {name=l54 lab=rst_n}
C {lab_pin.sym} 950 -300 0 0 {name=l55 lab=ring_bit3}
C {lab_pin.sym} 900 -350 0 0 {name=l56 lab=vdd}
C {lab_pin.sym} 900 -250 0 0 {name=l57 lab=vss}
C {sampler_dff.sym} 900 -100 0 0 {name=xsr4}
C {lab_pin.sym} 850 -130 0 0 {name=l58 lab=ro4}
C {lab_pin.sym} 850 -100 0 0 {name=l59 lab=clk}
C {lab_pin.sym} 850 -70 0 0 {name=l60 lab=rst_n}
C {lab_pin.sym} 950 -100 0 0 {name=l61 lab=ring_bit4}
C {lab_pin.sym} 900 -150 0 0 {name=l62 lab=vdd}
C {lab_pin.sym} 900 -50 0 0 {name=l63 lab=vss}
