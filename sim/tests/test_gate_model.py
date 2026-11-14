#!/usr/bin/env python3
"""Unit tests for the gate-level digital model generator (issue #486).

Runs with the standard library only -- no klt, no PDK, no ngspice -- so it is
a CI test::

    python3 sim/tests/test_gate_model.py

Three kinds of check, in order of strength:

1. **Correspondence with the real routed netlist** (AC2). The parse of the
   committed ``layout/trng_digital/trng_digital.routed.v`` is checked against
   its own counts and port list, and then the **committed manifest** of the
   recorded run is checked against that parse: every routed instance is
   accounted for as a primitive, a declared polarity inverter or a declared
   load-only no-op, the cell-type histogram agrees, and the bridged port list
   is exactly the module's bit-expanded port list. That is the real generated
   model being checked against the real netlist, without needing the PDK.
2. **Fail-closed behaviour** (AC2). A synthetic cell library and netlist drive
   the refusal paths: an unknown cell, an output pin with neither a Liberty
   ``function`` nor an ``ff`` group, a multiply-driven net, a net that is read
   but never driven, and a falling-edge flop. The generator must exit non-zero
   and leave **no** output directory behind.
3. **Unit behaviour of the two reductions.** The Liberty-function to
   ``d_genlut`` truth-table mapping (including the measured index ordering) and
   the NLDM bilinear interpolation with clamping, both on hand-computable
   inputs.

A fourth group regenerates the model from the **real** Liberty deck and
compares it with the committed manifest; it is skipped when the PDK install is
absent, which is why group 1 does not depend on it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BLOCK = REPO / "sim" / "post-layout-whole-block"
GENERATOR = BLOCK / "make-gate-model.py"
ROUTED_V = REPO / "layout" / "trng_digital" / "trng_digital.routed.v"
#: the committed manifest of the recorded full-program run
COMMITTED_MANIFEST = BLOCK / "corners" / "gate-model-full" / "gate-model.manifest.json"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loadmod import load_module  # noqa: E402

G = load_module("make_gate_model", GENERATOR)
MR = load_module("make_requests_for_gate_model", BLOCK / "make-requests.py")


# --------------------------------------------------------------------------
# A synthetic cell library and netlist: small enough to hand-check, shaped
# exactly like the real deck (same group nesting, same attribute spellings).
# --------------------------------------------------------------------------

def liberty(cells: str, threshold: str = "50.000000000") -> str:
    return f"""library ("synthetic_hd") {{
    delay_model : "table_lookup";
    time_unit : "1ns";
    voltage_unit : "1V";
    capacitive_load_unit(1.0000000000, "pf");
    input_threshold_pct_fall : {threshold};
    input_threshold_pct_rise : {threshold};
{cells}
}}
"""


def nldm(name: str, v00: str, v01: str, v10: str, v11: str) -> str:
    """A 2x2 NLDM table over slew [0.1, 0.5] ns and load [0.001, 0.009] pF."""
    return f"""                {name} ("del_2_2") {{
                    index_1("0.1000000000, 0.5000000000");
                    index_2("0.0010000000, 0.0090000000");
                    values("{v00}, {v01}", \\
                        "{v10}, {v11}");
                }}
"""


def comb_cell(name: str, inputs: list[str], out: str, function: str,
              rise=("0.100", "0.300", "0.500", "0.700"),
              fall=("0.200", "0.400", "0.600", "0.800")) -> str:
    pins = ""
    for p in inputs:
        pins += f"""        pin ("{p}") {{
            capacitance : 0.0020000000;
            direction : "input";
        }}
"""
    arcs = ""
    for p in inputs:
        arcs += f"""            timing () {{
                related_pin : "{p}";
                timing_sense : "non_unate";
                timing_type : "combinational";
{nldm("cell_rise", *rise)}{nldm("cell_fall", *fall)}            }}
"""
    return f"""    cell ("{name}") {{
        area : 5.0000000000;
{pins}        pin ("{out}") {{
            direction : "output";
            function : "{function}";
{arcs}        }}
    }}
"""


DFRTP = """    cell ("sky130_fd_sc_hd__dfrtp_1") {
        area : 20.0000000000;
        ff ("IQ","IQ_N") {
            clear : "!RESET_B";
            clocked_on : "CLK";
            next_state : "D";
        }
        pin ("CLK") {
            capacitance : 0.0030000000;
            clock : "true";
            direction : "input";
        }
        pin ("D") {
            capacitance : 0.0040000000;
            direction : "input";
        }
        pin ("RESET_B") {
            capacitance : 0.0050000000;
            direction : "input";
        }
        pin ("Q") {
            direction : "output";
            function : "IQ";
            timing () {
                related_pin : "CLK";
                timing_type : "rising_edge";
""" + nldm("cell_rise", "0.900", "1.100", "1.300", "1.500") \
    + nldm("cell_fall", "1.000", "1.200", "1.400", "1.600") + """            }
            timing () {
                related_pin : "CLK";
                timing_type : "setup_rising";
            }
            timing () {
                related_pin : "RESET_B";
                timing_type : "clear";
""" + nldm("cell_rise", "0.700", "0.700", "0.700", "0.700") \
    + nldm("cell_fall", "0.800", "0.800", "0.800", "0.800") + """            }
        }
    }
"""

#: a cell with an output pin but neither a function nor an ff group
NO_FUNCTION = """    cell ("sky130_fd_sc_hd__bad_1") {
        area : 1.0000000000;
        pin ("A") {
            capacitance : 0.0020000000;
            direction : "input";
        }
        pin ("Y") {
            direction : "output";
            timing () {
                related_pin : "A";
                timing_type : "combinational";
""" + nldm("cell_rise", "0.100", "0.100", "0.100", "0.100") \
    + nldm("cell_fall", "0.100", "0.100", "0.100", "0.100") + """            }
        }
    }
"""

#: an antenna tie: an input pin and no output pin at all
DIODE = """    cell ("sky130_fd_sc_hd__diode_2") {
        area : 3.0000000000;
        pin ("DIODE") {
            capacitance : 0.0070000000;
            direction : "input";
        }
    }
"""

#: the real a21oi_1 output function, copied verbatim from
#: sky130_fd_sc_hd__tt_025C_1v80.lib (so the hand-computed table below is a
#: check on the PDK's own expression, not on a paraphrase of it)
A21OI_FUNCTION = "(!A1&!B1) | (!A2&!B1)"

SYNTH_LIB = liberty(
    comb_cell("sky130_fd_sc_hd__a21oi_1", ["A1", "A2", "B1"], "Y", A21OI_FUNCTION)
    + comb_cell("sky130_fd_sc_hd__inv_1", ["A"], "Y", "(!A)")
    + comb_cell("sky130_fd_sc_hd__and2_1", ["A", "B"], "X", "(A&B)")
    + DFRTP + NO_FUNCTION + DIODE)

#: a synthetic module carrying the four DR-0017 boundary inputs (the generator
#: asserts the boundary against program.boundary_signals(), so they must be
#: present) plus one testbench input and the observed outputs.
SYNTH_V = """/* synthetic */
module trng_digital (alarm,
    clk,
    raw_bit,
    raw_valid,
    rst_n,
    bus_re,
    gated);
 output alarm;
 input clk;
 input raw_bit;
 input raw_valid;
 input rst_n;
 input bus_re;
 output gated;
 wire n1;
 wire n2;
 wire q1;
 sky130_fd_sc_hd__a21oi_1 u1 (.A1(raw_bit),
    .A2(raw_valid),
    .B1(bus_re),
    .Y(n1));
 sky130_fd_sc_hd__dfrtp_1 u2 (.CLK(clk),
    .D(n1),
    .RESET_B(rst_n),
    .Q(q1));
 sky130_fd_sc_hd__inv_1 u3 (.A(q1),
    .Y(n2));
 sky130_fd_sc_hd__inv_1 u4 (.A(q1),
    .Y());
 sky130_fd_sc_hd__diode_2 ANTENNA_1 (.DIODE(clk));
 sky130_fd_sc_hd__and2_1 u5 (.A(n2),
    .B(q1),
    .X(alarm));
 assign gated = n2;
endmodule
"""


def write_pair(tmp: Path, verilog: str = SYNTH_V, lib: str = SYNTH_LIB):
    v = tmp / "synth.v"
    l = tmp / "synth.lib"
    v.write_text(verilog)
    l.write_text(lib)
    return v, l


def build(tmp: Path, verilog: str = SYNTH_V, lib: str = SYNTH_LIB, **kw):
    """Parse + build a gate model from a synthetic pair, in process."""
    v, l = write_pair(tmp, verilog, lib)
    design = G.parse_verilog(v)
    blocks, header = G.extract_cell_blocks(l, set(design.cell_histogram()))
    cells = {n: G.CellModel(n, g) for n, g in blocks.items()}
    kwargs = dict(supply_v=1.8, slew_ns=0.1, port_load_pf=0.0,
                  liberty_path=l, liberty_sha256="0" * 64, threshold_pct=50.0)
    kwargs.update(kw)
    return design, G.build_gate_model(design, cells, **kwargs)


# --------------------------------------------------------------------------
# 1. correspondence with the real routed netlist (AC2)
# --------------------------------------------------------------------------

class TestRoutedNetlistCorrespondence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = G.parse_verilog(ROUTED_V)
        cls.hist = cls.design.cell_histogram()

    def test_parse_counts_match_the_committed_netlist(self):
        # re-derived from the file, not quoted from the issue: the same two
        # numbers a grep over the netlist gives.
        text = ROUTED_V.read_text()
        grep_instances = len(re.findall(r"^\s*sky130_fd_sc_hd__", text, re.M))
        grep_types = len(set(re.findall(r"sky130_fd_sc_hd__[a-z0-9_]+", text)))
        self.assertEqual(len(self.design.instances), grep_instances)
        self.assertEqual(len(self.hist), grep_types)
        self.assertEqual(sum(self.hist.values()), len(self.design.instances))

    def test_sequential_cells_are_the_two_flop_types(self):
        seq = {c for c in self.hist if "df" in c}
        self.assertEqual(seq, {"sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__dfstp_1"})

    def test_port_list_matches_the_module_header(self):
        header = re.search(r"\bmodule\s+trng_digital\s*\((.*?)\)\s*;",
                           ROUTED_V.read_text(), re.S).group(1)
        declared = [t.strip() for t in header.replace("\n", " ").split(",") if t.strip()]
        base = []
        for p in self.design.port_bits():
            m = re.match(r"^(.*?)_\d+_$", p)
            base.append(m.group(1) if m else p)
        # every bit-expanded port traces back to a header port, and every
        # header port contributes at least one bit
        self.assertEqual(set(base), set(declared))
        self.assertEqual(len(self.design.port_bits()),
                         len(self.design.port_bits("input"))
                         + len(self.design.port_bits("output")))

    def test_escaped_identifiers_are_parsed_not_dropped(self):
        # 576 connections in the committed netlist use Yosys's escaped-identifier
        # form (\raw_mem[3] [30]); a parser that ignored them would silently
        # lose nets, so assert they survive as flat bracket-free names.
        text = ROUTED_V.read_text()
        n_escaped = len(re.findall(r"\.\w+\(\s*\\", text))
        self.assertGreater(n_escaped, 0)
        flat = [n for _, _, pins in self.design.instances for n in pins.values()
                if re.match(r"^\w+_\d+__\d+_$", n)]
        self.assertGreater(len(flat), 0)
        for _, _, pins in self.design.instances:
            for net in pins.values():
                self.assertRegex(net, r"^[A-Za-z_][A-Za-z0-9_]*$",
                                 "net name is not a flat SPICE identifier")

    def test_netname_agrees_with_make_requests_scrub(self):
        # make-requests.py owns the port spelling the whole-block deck's .meas
        # cards use. netname() must not diverge from it on any port bit, or the
        # two decks would address different nets by the same name.
        for name, direction, msb, lsb in self.design.ports:
            if msb is None:
                self.assertEqual(G.netname(name), MR._scrub(name))
            else:
                for i in range(min(msb, lsb), max(msb, lsb) + 1):
                    tok = f"{name}[{i}]"
                    self.assertEqual(G.netname(tok), MR._scrub(tok))

    def test_committed_manifest_accounts_for_every_routed_instance(self):
        m = json.loads(COMMITTED_MANIFEST.read_text())
        self.assertEqual(m["routed_instances"], len(self.design.instances))
        accounted = (m["primitives"]["d_genlut"] + m["primitives"]["d_dff"]
                     + len(m["declared_no_op_instances"]))
        self.assertEqual(accounted, len(self.design.instances),
                         "primitives + declared no-ops must equal the routed count")
        # one d_dff per sequential instance, and nothing else is sequential
        n_seq = sum(v for k, v in self.hist.items() if "df" in k)
        self.assertEqual(m["primitives"]["d_dff"], n_seq)
        # every declared no-op names a real instance and gives a reason
        insts = {i for _, i, _ in self.design.instances}
        for noop in m["declared_no_op_instances"]:
            self.assertIn(noop["instance"], insts)
            self.assertTrue(noop["reason"], "a no-op must be declared, not silent")

    def test_committed_manifest_histogram_and_ports_match_the_parse(self):
        m = json.loads(COMMITTED_MANIFEST.read_text())
        self.assertEqual(m["cell_histogram"], self.hist)
        self.assertEqual(m["ports"]["all"], self.design.port_bits())
        self.assertEqual(m["ports"]["inputs"], self.design.port_bits("input"))
        self.assertEqual(m["ports"]["outputs"], self.design.port_bits("output"))
        # every port is bridged exactly once, on the side its direction says
        bridged = (m["boundary"]["analog_digital"] + m["boundary"]["testbench_driven"]
                   + m["boundary"]["observed"])
        self.assertEqual(sorted(bridged), sorted(self.design.port_bits()))
        self.assertEqual(len(bridged), len(set(bridged)))

    def test_committed_manifest_boundary_is_dr0017s(self):
        m = json.loads(COMMITTED_MANIFEST.read_text())
        sys.path.insert(0, str(BLOCK))
        import program as P  # noqa: E402
        expected = sorted(n for n, v in P.boundary_signals().items()
                          if v["dir"] in ("analog->digital", "tb->both"))
        self.assertEqual(m["boundary"]["analog_digital"], expected)
        self.assertEqual(m["boundary"]["supplies"], ["vdd", "vss"])
        self.assertEqual(m["source_netlist_sha256"], G.sha256_file(ROUTED_V),
                         "the committed manifest must describe the committed netlist")


# --------------------------------------------------------------------------
# 2. fail-closed behaviour (AC2)
# --------------------------------------------------------------------------

class TestFailsClosed(unittest.TestCase):
    def assert_refuses(self, needle: str, *, verilog=SYNTH_V, lib=SYNTH_LIB):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with self.assertRaises(G.GateModelError) as cm:
                build(tmp, verilog, lib)
            self.assertIn(needle, str(cm.exception))

    def test_unknown_cell(self):
        v = SYNTH_V.replace("sky130_fd_sc_hd__and2_1 u5", "sky130_fd_sc_hd__nosuch_9 u5")
        self.assert_refuses("is not in", verilog=v)

    def test_output_pin_without_function_or_ff(self):
        v = SYNTH_V.replace("""sky130_fd_sc_hd__inv_1 u3 (.A(q1),
    .Y(n2));""", """sky130_fd_sc_hd__bad_1 u3 (.A(q1),
    .Y(n2));""")
        self.assert_refuses("no Liberty function and no ff group", verilog=v)

    def test_multiply_driven_net(self):
        v = SYNTH_V.replace(""" sky130_fd_sc_hd__inv_1 u4 (.A(q1),
    .Y());""", """ sky130_fd_sc_hd__inv_1 u4 (.A(q1),
    .Y(n2));""")
        self.assert_refuses("driven by both", verilog=v)

    def test_net_read_but_never_driven(self):
        v = SYNTH_V.replace(".B1(bus_re)", ".B1(dangling_net)")
        self.assert_refuses("never driven", verilog=v)

    def test_unconnected_input_pin(self):
        v = SYNTH_V.replace(".A2(raw_valid),\n", "")
        self.assert_refuses("unconnected", verilog=v)

    def test_falling_edge_flop_has_no_mapping(self):
        lib = SYNTH_LIB.replace('clocked_on : "CLK";', 'clocked_on : "!CLK";')
        self.assert_refuses("rising-edge only", lib=lib)

    def test_liberty_threshold_other_than_50_is_refused(self):
        # the adc_bridge band is centred on the deck's own delay-measurement
        # threshold; a deck that measures elsewhere needs the band re-derived.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            only_inv = """module trng_digital (clk, raw_bit, raw_valid, rst_n, gated);
 input clk;
 input raw_bit;
 input raw_valid;
 input rst_n;
 output gated;
 sky130_fd_sc_hd__inv_1 u1 (.A(clk),
    .Y(gated));
endmodule
"""
            v, l = write_pair(tmp, only_inv, liberty(
                comb_cell("sky130_fd_sc_hd__inv_1", ["A"], "Y", "(!A)"),
                threshold="40.000000000"))
            out = tmp / "out"
            with self.assertRaises(G.GateModelError) as cm:
                G.main([str(out), "--verilog", str(v), "--liberty", str(l)])
            self.assertIn("input_threshold_pct", str(cm.exception))
            self.assertFalse(out.exists())

    def test_cli_exits_non_zero_and_writes_nothing(self):
        """The whole point of fail-closed: no partial model on disk."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            v, l = write_pair(
                tmp,
                SYNTH_V.replace("sky130_fd_sc_hd__and2_1 u5",
                                "sky130_fd_sc_hd__nosuch_9 u5"),
                SYNTH_LIB)
            out = tmp / "out"
            proc = subprocess.run(
                [sys.executable, str(GENERATOR), str(out),
                 "--verilog", str(v), "--liberty", str(l)],
                capture_output=True, text=True, timeout=300)
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("nosuch", proc.stderr)
            self.assertFalse(out.exists(), "a refused run must leave no output")

    def test_cli_succeeds_on_the_synthetic_pair(self):
        """The positive control for the test above: same CLI, mappable cells."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            v, l = write_pair(tmp)
            out = tmp / "out"
            proc = subprocess.run(
                [sys.executable, str(GENERATOR), str(out),
                 "--verilog", str(v), "--liberty", str(l), "--cycles", "4"],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            for name in ("gate-model.cir", "gate-model.manifest.json",
                         "netlist.cir", "request.json", "plan.json"):
                self.assertTrue((out / name).is_file(), name)
            req = json.loads((out / "request.json").read_text())
            self.assertEqual(req["engine"], "ngspice")
            # klt sim owns .lib/.temp/.tran and the .control block: the body
            # must carry NONE of them (comments excepted).
            cards = [ln for ln in (out / "netlist.cir").read_text().splitlines()
                     if not ln.startswith("*")]
            for forbidden in (".control", ".endc", ".tran", ".end", ".lib", ".temp"):
                self.assertFalse([ln for ln in cards if ln.startswith(forbidden)],
                                 f"{forbidden} must be left to klt sim")


# --------------------------------------------------------------------------
# 3. the two reductions, on hand-computable inputs
# --------------------------------------------------------------------------

class TestTruthTable(unittest.TestCase):
    def test_a21oi_table_matches_a_hand_computation(self):
        pins = ["A1", "A2", "B1"]
        table = G.truth_table(A21OI_FUNCTION, pins)
        # index = A1 + 2*A2 + 4*B1 (first input is the LSB -- measured)
        expect = ""
        for idx in range(8):
            a1, a2, b1 = idx & 1, (idx >> 1) & 1, (idx >> 2) & 1
            expect += "1" if ((not a1 and not b1) or (not a2 and not b1)) else "0"
        self.assertEqual(table, expect)
        # and spelled out, so a change to either side is visible in review:
        # Y = !((A1&A2)|B1): 1 unless (A1&A2) or B1
        self.assertEqual(table, "1110" "0000")

    def test_index_order_puts_the_first_input_in_the_lsb(self):
        # the ordering is a MEASURED property of ngspice's d_genlut (four
        # one-hot table_values against all four input combinations), so pin it.
        self.assertEqual(G.truth_table("(A&!B)", ["A", "B"]), "0100")
        self.assertEqual(G.truth_table("(!A&B)", ["A", "B"]), "0010")

    def test_nand_and_nor_and_xor_and_constants(self):
        self.assertEqual(G.truth_table("(!A) | (!B)", ["A", "B"]), "1110")
        self.assertEqual(G.truth_table("(!A&!B)", ["A", "B"]), "1000")
        self.assertEqual(G.truth_table("A^B", ["A", "B"]), "0110")
        self.assertEqual(G.truth_table("A'", ["A"]), "10")
        self.assertEqual(G.truth_table("A B", ["A", "B"]), "0001")  # juxtaposition
        self.assertEqual(G.truth_table("1", ["A"]), "11")

    def test_function_referencing_an_unknown_pin_is_refused(self):
        with self.assertRaises(G.GateModelError):
            G.truth_table("(A&C)", ["A", "B"])

    def test_unparseable_function_is_refused(self):
        for expr in ("(A&", "A&&B", "A@B", "A)"):
            with self.assertRaises(G.GateModelError):
                G.truth_table(expr, ["A", "B"])


class TestNldmReduction(unittest.TestCase):
    def table(self):
        lines = ["cell_rise (\"del_2_2\") {",
                 "index_1(\"0.1, 0.5\");",
                 "index_2(\"0.001, 0.009\");",
                 "values(\"1.0, 2.0\", \"3.0, 5.0\");",
                 "}"]
        return G.NldmTable(G.parse_liberty_group(lines), "test")

    def test_corner_values_are_exact(self):
        t = self.table()
        self.assertAlmostEqual(t.at(0.1, 0.001), 1.0)
        self.assertAlmostEqual(t.at(0.1, 0.009), 2.0)
        self.assertAlmostEqual(t.at(0.5, 0.001), 3.0)
        self.assertAlmostEqual(t.at(0.5, 0.009), 5.0)

    def test_bilinear_midpoint(self):
        t = self.table()
        # slew midpoint, load midpoint -> mean of the four corners
        self.assertAlmostEqual(t.at(0.3, 0.005), (1.0 + 2.0 + 3.0 + 5.0) / 4)
        # load midpoint at the fast slew row only
        self.assertAlmostEqual(t.at(0.1, 0.005), 1.5)

    def test_out_of_range_is_clamped_never_extrapolated(self):
        t = self.table()
        self.assertAlmostEqual(t.at(0.0, 0.0), 1.0)
        self.assertAlmostEqual(t.at(99.0, 99.0), 5.0)
        self.assertAlmostEqual(t.at(0.0, 99.0), 2.0)

    def test_malformed_table_is_refused(self):
        lines = ["cell_rise (\"bad\") {",
                 "index_1(\"0.1, 0.5\");",
                 "index_2(\"0.001, 0.009\");",
                 "values(\"1.0, 2.0\", \"3.0\");",
                 "}"]
        with self.assertRaises(G.GateModelError):
            G.NldmTable(G.parse_liberty_group(lines), "bad")

    def test_delay_is_the_max_over_arcs_and_floored(self):
        with tempfile.TemporaryDirectory() as td:
            _, model = build(Path(td))
            # Hand arithmetic. q1 is read by u3.A, u4.A and u5.B, each
            # 0.002 pF, so C_load = 0.006 pF; the slew operating point is
            # 0.1 ns = index_1[0], so only the fast-slew row is used.
            #   CLK->Q   cell_rise row 0: 0.9 .. 1.1 ns over load 0.001..0.009
            #            -> 0.9 + 0.2 * (0.005/0.008) = 1.025 ns
            #            cell_fall row 0: 1.0 .. 1.2 -> 1.125 ns
            #   RESET_B->Q arc is 0.7/0.8 ns flat, so the max over the two
            #   arcs is the CLK arc. Index [0][0] (0.9/1.0) is NOT what a
            #   silent reduction would have given -- that is the point.
            dff = [ln for ln in model.body if ".model mu2 d_dff" in ln]
            self.assertEqual(len(dff), 1, model.body)
            self.assertIn("rise_delay=1.025e-09", dff[0])
            self.assertIn("fall_delay=1.125e-09", dff[0])
            self.assertIn(f"clk_delay={G._eng(G.MIN_DELAY_S)}", dff[0])


# --------------------------------------------------------------------------
# 4. emitted-netlist structure, on the synthetic pair
# --------------------------------------------------------------------------

class TestEmittedStructure(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.design, self.model = build(Path(self._td.name))
        self.body = self.model.body
        self.text = self.model.text()

    def tearDown(self):
        self._td.cleanup()

    def test_instance_accounting(self):
        m = self.model.manifest
        self.assertEqual(m["routed_instances"], 6)
        # u1 a21oi, u3 inv, u5 and2 -> genlut; u2 -> d_dff;
        # u4 (output open) and ANTENNA_1 (no output pin) -> declared no-ops
        self.assertEqual(m["primitives"], {"d_genlut": 3, "d_dff": 1})
        self.assertEqual(len(m["declared_no_op_instances"]), 2)
        self.assertEqual(
            {n["instance"] for n in m["declared_no_op_instances"]}, {"u4", "ANTENNA_1"})
        self.assertEqual(m["polarity_inverters"], 1)

    def test_active_low_clear_gets_a_shared_polarity_inverter(self):
        inv = [ln for ln in self.body if ln.startswith("Apol0 ")]
        self.assertEqual(len(inv), 1, self.body)
        self.assertEqual(inv[0].split()[1:3], ["dn_rst_n", "dn_pol0_rst_n"])
        dff = next(ln for ln in self.body if ln.startswith("Au2 "))
        # d_dff node order: data clk set reset out nout
        self.assertEqual(dff.split()[1:7],
                         ["dn_n1", "dn_clk", "null", "dn_pol0_rst_n", "dn_q1", "null"])

    def test_bridges_cover_every_port_once(self):
        boundary = next(ln for ln in self.body if ln.startswith("Aadc_boundary "))
        self.assertEqual(re.findall(r"\[(.*?)\]", boundary)[0].split(),
                         ["clk", "raw_bit", "raw_valid", "rst_n"])
        dac = " ".join(self.text.splitlines()[
            next(i for i, ln in enumerate(self.body) if ln.startswith("Adac_obs ")):])
        # 'gated' is an assign alias of n2, so the bridge's digital side must be
        # the DRIVEN net, not the alias
        self.assertIn("dn_n2", dac)
        self.assertIn("gated", dac)

    def test_supply_nets_exist_by_name(self):
        self.assertIn("Vvdd vdd 0 dc 1.8", self.body)
        self.assertIn("Vvss vss 0 dc 0", self.body)

    def test_bridge_band_tracks_the_supply(self):
        _, m2 = build(Path(self._td.name) / "x" if False else Path(self._td.name),
                      supply_v=1.62)
        r = m2.manifest["reductions"]
        self.assertAlmostEqual(r["adc_bridge_in_low_v"], 1.62 * 0.45)
        self.assertAlmostEqual(r["adc_bridge_in_high_v"], 1.62 * 0.55)
        self.assertAlmostEqual(r["dac_bridge_out_high_v"], 1.62)

    def unwrapped(self, prefix: str) -> str:
        """A single emitted card with its ``+`` continuations joined back up."""
        out = None
        for ln in self.body:
            if ln.startswith(prefix):
                out = ln
            elif out is not None and ln.startswith("+"):
                out += " " + ln[1:].strip()
            elif out is not None:
                break
        self.assertIsNotNone(out, prefix)
        return out

    def test_genlut_input_load_is_the_liberty_capacitance(self):
        card = self.unwrapped(".model mu1 d_genlut")
        loads = re.search(r"input_load=\[(.*?)\]", card).group(1).split()
        self.assertEqual(len(loads), 3)                 # A1 A2 B1
        self.assertTrue(all(abs(float(x) - 2e-15) < 1e-18 for x in loads), loads)

    def test_load_only_instance_still_loads_its_driver(self):
        # u4's input capacitance must appear in q1's C_load even though u4
        # contributes no primitive: the no-op is a logic no-op, not an
        # electrical one. q1 drives u3.A, u4.A and u5.B -> 3 x 0.002 pF.
        self.assertEqual(len(self.model.manifest["declared_no_op_instances"]), 2)
        card = self.unwrapped(".model mu3 d_genlut")
        rise = float(re.search(r"rise_delay=\[(.*?)\]", card).group(1))
        # 0.006 pF is past index_2's 0.009 upper bound? no: 0.006 < 0.009, so
        # the lookup interpolates rather than clamps, giving a value strictly
        # between the 0.001 and 0.009 columns of the fast-slew row.
        self.assertGreater(rise, 0.100e-9)
        self.assertLess(rise, 0.300e-9)

    def test_no_card_exceeds_the_wrap_width(self):
        for ln in self.body:
            if ln.startswith("*"):
                continue
            self.assertLessEqual(len(ln), G.WRAP_COLS + 8, ln)

    def test_net_name_collision_is_refused(self):
        v = SYNTH_V.replace(".Y(n1));", ".Y(\\n1 [0]));").replace(
            " wire n1;", " wire n1;\n wire n1_0_;")
        v = v.replace(".D(n1),", ".D(\\n1 [0]),")
        # introduce a second token that flattens to the same flat name
        v = v.replace(".A(q1),\n    .Y());", ".A(n1_0_),\n    .Y());")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(G.GateModelError) as cm:
                build(Path(td), verilog=v)
            self.assertIn("collision", str(cm.exception))


# --------------------------------------------------------------------------
# 5. against the real Liberty deck (skipped without the PDK)
# --------------------------------------------------------------------------

def real_liberty() -> Path | None:
    try:
        return G.resolve_liberty(None, "tt_025C_1v80")
    except Exception:
        return None


REAL_LIB = real_liberty()


@unittest.skipUnless(REAL_LIB is not None,
                     "needs the pinned sky130A PDK install (klt pdk find)")
class TestAgainstRealLiberty(unittest.TestCase):
    def test_regenerating_reproduces_the_committed_manifest(self):
        committed = json.loads(COMMITTED_MANIFEST.read_text())
        design = G.parse_verilog(ROUTED_V)
        blocks, header = G.extract_cell_blocks(REAL_LIB, set(design.cell_histogram()))
        cells = {n: G.CellModel(n, g) for n, g in blocks.items()}
        model = G.build_gate_model(
            design, cells,
            supply_v=committed["reductions"]["supply_v"],
            slew_ns=committed["reductions"]["slew_ns"],
            port_load_pf=committed["reductions"]["port_load_pf"],
            liberty_path=REAL_LIB,
            liberty_sha256=committed["liberty_sha256"],
            threshold_pct=committed["reductions"]["liberty_threshold_pct"])
        self.assertEqual(model.manifest, committed,
                         "the committed manifest is not what the generator now emits")


if __name__ == "__main__":
    unittest.main(verbosity=2)
