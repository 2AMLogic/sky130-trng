// Compile-time defines every sky130_fd_sc_hd gate-level simulation needs;
// must be listed FIRST in a request's `sources` (a `define persists across
// the files of one compile). Same two defines as
// sim/digital-synthesis/harness/gate_cosim.py. Functional / unit-delay only:
// NOT an SDF-timed model.
//   FUNCTIONAL  -- zero-delay behavioural cell models (Icarus does not
//                  implement $setuphold/$recrem delayed signals, so the
//                  timing-check branch would simulate every flop D as x).
//   UNIT_DELAY  -- 1 ns output delay on sequential UDPs so a zero-delay
//                  netlist has no D/Q race at the clock edge.
`define FUNCTIONAL
`define UNIT_DELAY #1
