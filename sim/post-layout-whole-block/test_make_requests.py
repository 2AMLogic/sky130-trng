#!/usr/bin/env python3
"""Unit test for ``make-requests.py``'s driven-input PWL stimulus shape.

Run directly (no pytest suite in this repo):

    python3 sim/post-layout-whole-block/test_make_requests.py

Issue #488: a SPICE ``PWL`` source interpolates **linearly** between its
breakpoints, so a breakpoint list carrying only the change instants emits every
driven input as a straight ramp across the whole hold interval instead of a hold
followed by an edge. Measured on this deck before the fix: ``bus_re`` came out
as ``PWL(0.0n 1.800 640.0n 0.000 970.0n 0.000)`` -- 1.8 V at t = 0 falling
linearly to 0 V at 640 ns, so 0.928 V at 310 ns -- and across the full 75-cycle
grid program **344 of 3000 (driven input x capture point) samples sat more than
10 % off a rail**, the worst at 0.905 V (``bus_addr[0]``, cycle 19, t = 2300 ns),
essentially mid-rail. ``test_capture_points_sit_at_a_rail`` is the control for
that: it fails on the pre-#488 shape and passes once each change carries a hold
breakpoint one ``EDGE_NS`` before it.

The assertions here are on the emitted card text, not on an internal helper, so
they hold against whatever ``points()``/``pwl_card()`` do internally:

* every driven input, evaluated at every cycle's capture point, is within 1 mV
  of either 0 V or ``VIH`` (the control);
* a mid-program change emits the hold/edge pair explicitly (``bus_re``'s
  ``639.9n`` at the old value immediately followed by ``640.0n`` at the new one);
* breakpoint hygiene: ``t = 0`` first, ``t_stop`` last, strictly increasing
  formatted timestamps (no duplicate breakpoint from an under-wide edge), and an
  input that never changes still emits exactly the two endpoints;
* the grid requests' timeouts are derived from the measured coupled run
  (issues #431 / #596, ``records/20261128-coupled-rate.md``), fit the fleet's
  whole-job ceiling as one single-process unit per request (``units=1``; the
  archived three-unit shape stays sized by the same function), and refuse
  what it cannot hold; the archived flat grid under ``corners/grid-*`` keeps
  its filed settings.

Issue #507 adds three assertions of its own:

* every emitted measurement's ``AT=`` **and** ``TO=`` sits within its own
  request's ``.tran`` stop, checked on generator output across all four
  ``--set`` groups (drift 1: the two committed startup probes carry nine
  pre-clip ``.meas`` cards that ``FIND`` at 3970/4570/7770 ns against a 970 ns
  stop -- a card past its transient end cannot resolve and would read as a
  block failure rather than a malformed request);
* a known-stale ledger over the committed ``corners/*/request.json``: every
  committed request satisfies the same invariant except the two startup probes,
  whose violations are pinned to exactly those nine cards -- so a *new* corner
  directory carrying an over-``t_stop`` card, or a regeneration of the startup
  probes that does not drop the ledger entry, both turn this red;
* the startup probes' timeouts: the generator emits ``timeout_s`` 3600 for
  ``startup-probe`` and 3480 / ``poll_timeout_s`` 3700 for
  ``startup-probe-batch``, while the committed batch pair still carries
  14400 / 7000 (drift 2, a checked divergence, not an undocumented mismatch).

Issue #555 hardens the #507 bound scan itself: the ``AT=``/``TO=`` pattern is
unit-agnostic and the unit suffix is asserted to be ``n`` inside
``over_stop_violations()`` -- the same fail-loud posture ``tran_stop_ns()``
already applies to the ``.tran`` stop -- and every request whose measurements
carry an ``AT=``/``TO=`` bound must visit at least one itself, so a card
emitted in ``u``/``p``/bare/any other unit turns the tests red instead of
being silently skipped by an ns-only pattern. The negative control
``test_bound_scan_flags_non_ns_units`` pins that on synthetic requests, no
generator edit needed.

Issue #576 closes the granularity gap #555 left in that guard: it was a
*per-request* presence test ("must visit at least one"), so a single card
whose bound token ``_BOUND_RES`` cannot reach hid behind the same request's
other matched bounds. ``assert_every_bound_visited()`` now counts the
``AT=``/``TO=`` tokens each card's raw text actually carries -- an
independent pattern, whitespace-tolerant before the ``=`` so
``AT = 3970.0n`` counts too -- and demands the scan visit exactly that
many, so the one skipped card fails on its own. The negative control
``test_per_card_guard_flags_unvisited_bound`` pins the mixed matched +
unmatchable request as red; a card carrying a duplicated ``AT=`` token
also turns red, which is deliberate (the scan reads one match per key per
card, and the generator emits one per key).

Issue #815: ``--set grid`` is now one COUPLED request per matrix point (12
single-process units, ``grid-<proc>-<T>-<Vdd>``), each embedding a gate model
built for that point from the Liberty deck ``pvt_deck_map.py`` maps it to.
Building a gate model needs decks, so the grid tests here run against a
synthetic PDK: ``SyntheticPdk`` writes the 8 mapped decks from
``CELL_STRUCTURE`` (the 64 cells' pins and functions, copied from the real
``tt_025C_1v80`` deck, whose structure is identical in all 8 decks) with a
distinct delay scale per deck, and ``synthetic_pins()`` re-pins
``DECK_TABLE``'s sha256 values to those files for the duration of a
generation -- the stand-in for "a sky130A install whose decks hash to the
pins". Without a resolvable PDK or ``--libs-ref`` the grid set refuses and
writes nothing (``test_grid_fails_closed_without_libs_ref``). Against the
real install, ``TestAgainstRealPdk`` (skipped without it) checks every
point names its pinned deck on disk and that the nominal point's model is
the committed, measured gate model byte for byte.

Pure Python: no klt, no PDK, no ngspice.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import program as P  # noqa: E402
import pvt_deck_map as PVT  # noqa: E402
from gate_model_lib import _eng, parse_verilog  # noqa: E402

spec = importlib.util.spec_from_file_location("make_requests", HERE / "make-requests.py")
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)


def gate_model_generator():
    """``make-gate-model.py`` loaded by path (its name carries a hyphen). Only
    the tests that exercise the generator CLI's own deck assembly load it
    (#804: the request generator imports program.py directly and no longer
    executes this sibling)."""
    spec = importlib.util.spec_from_file_location("make_gate_model", HERE / "make-gate-model.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Issue #815: a synthetic PDK for the coupled grid, offline
# ---------------------------------------------------------------------------

#: pin / function structure of the 64 ``sky130_fd_sc_hd`` cells the routed
#: netlist instantiates, copied from ``sky130_fd_sc_hd__tt_025C_1v80.lib``:
#: ``(input pins, {output pin: Liberty function}, (ff args, ff attrs) | None)``.
#: Structure is PDK-level -- identical in all 8 mapped decks, checked against
#: each -- so a deck built from it is a faithful stand-in for everything the
#: generator reads except the delay tables (synthetic, scaled per deck) and
#: the input threshold (50 %). Input capacitance is a uniform 0.002 pF.
CELL_STRUCTURE: dict[str, tuple[tuple[str, ...], dict[str, str], tuple | None]] = {
    "a211oi_1": (("A1", "A2", "B1", "C1"), {"Y": "(!A1&!B1&!C1) | (!A2&!B1&!C1)"}, None),
    "a21o_1": (("A1", "A2", "B1"), {"X": "(A1&A2) | (B1)"}, None),
    "a21oi_1": (("A1", "A2", "B1"), {"Y": "(!A1&!B1) | (!A2&!B1)"}, None),
    "a221o_1": (("A1", "A2", "B1", "B2", "C1"), {"X": "(B1&B2) | (A1&A2) | (C1)"}, None),
    "a221oi_1":
        (("A1", "A2", "B1", "B2", "C1"),
         {"Y": "(!A1&!B1&!C1) | (!A1&!B2&!C1) | (!A2&!B1&!C1) | (!A2&!B2&!C1)"},
         None),
    "a222oi_1":
        (("A1", "A2", "B1", "B2", "C1", "C2"),
         {"Y": "(!A1&!B1&!C1) | (!A1&!B1&!C2) | (!A1&!B2&!C1) | (!A2&!B1&!C1) | "
               "(!A1&!B2&!C2) | (!A2&!B1&!C2) | (!A2&!B2&!C1) | (!A2&!B2&!C2)"},
         None),
    "a22o_1": (("A1", "A2", "B1", "B2"), {"X": "(B1&B2) | (A1&A2)"}, None),
    "a22oi_1":
        (("A1", "A2", "B1", "B2"),
         {"Y": "(!A1&!B1) | (!A1&!B2) | (!A2&!B1) | (!A2&!B2)"},
         None),
    "a311o_1": (("A1", "A2", "A3", "B1", "C1"), {"X": "(A1&A2&A3) | (B1) | (C1)"}, None),
    "a311oi_1":
        (("A1", "A2", "A3", "B1", "C1"),
         {"Y": "(!A1&!B1&!C1) | (!A2&!B1&!C1) | (!A3&!B1&!C1)"},
         None),
    "a31o_2": (("A1", "A2", "A3", "B1"), {"X": "(A1&A2&A3) | (B1)"}, None),
    "a31oi_1": (("A1", "A2", "A3", "B1"), {"Y": "(!A1&!B1) | (!A2&!B1) | (!A3&!B1)"}, None),
    "a32o_1": (("A1", "A2", "A3", "B1", "B2"), {"X": "(A1&A2&A3) | (B1&B2)"}, None),
    "a32oi_1":
        (("A1", "A2", "A3", "B1", "B2"),
         {"Y": "(!A1&!B1) | (!A1&!B2) | (!A2&!B1) | (!A3&!B1) | (!A2&!B2) | (!A3&!B2)"},
         None),
    "and2_1": (("A", "B"), {"X": "(A&B)"}, None),
    "and3_1": (("A", "B", "C"), {"X": "(A&B&C)"}, None),
    "and3b_1": (("A_N", "B", "C"), {"X": "(!A_N&B&C)"}, None),
    "and4_1": (("A", "B", "C", "D"), {"X": "(A&B&C&D)"}, None),
    "and4b_1": (("A_N", "B", "C", "D"), {"X": "(!A_N&B&C&D)"}, None),
    "buf_4": (("A",), {"X": "(A)"}, None),
    "bufinv_16": (("A",), {"Y": "(!A)"}, None),
    "clkbuf_1": (("A",), {"X": "(A)"}, None),
    "clkinv_1": (("A",), {"Y": "(!A)"}, None),
    "clkinv_2": (("A",), {"Y": "(!A)"}, None),
    "clkinv_4": (("A",), {"Y": "(!A)"}, None),
    "clkinvlp_2": (("A",), {"Y": "(!A)"}, None),
    "dfrtp_1":
        (("CLK", "D", "RESET_B"),
         {"Q": "IQ"},
         (("IQ", "IQ_N",), {"clear": "!RESET_B", "clocked_on": "CLK", "next_state": "D"})),
    "dfstp_1":
        (("CLK", "D", "SET_B"),
         {"Q": "IQ"},
         (("IQ", "IQ_N",), {"clocked_on": "CLK", "next_state": "D", "preset": "!SET_B"})),
    "diode_2": (("DIODE",), {}, None),
    "inv_1": (("A",), {"Y": "(!A)"}, None),
    "inv_4": (("A",), {"Y": "(!A)"}, None),
    "mux2_2": (("A0", "A1", "S"), {"X": "(A0&!S) | (A1&S)"}, None),
    "mux2i_1": (("A0", "A1", "S"), {"Y": "(!A0&!S) | (!A1&S)"}, None),
    "nand2_1": (("A", "B"), {"Y": "(!A) | (!B)"}, None),
    "nand2b_1": (("A_N", "B"), {"Y": "(A_N) | (!B)"}, None),
    "nand3_1": (("A", "B", "C"), {"Y": "(!A) | (!B) | (!C)"}, None),
    "nand3b_1": (("A_N", "B", "C"), {"Y": "(A_N) | (!B) | (!C)"}, None),
    "nand4_1": (("A", "B", "C", "D"), {"Y": "(!A) | (!B) | (!C) | (!D)"}, None),
    "nand4b_1": (("A_N", "B", "C", "D"), {"Y": "(A_N) | (!B) | (!C) | (!D)"}, None),
    "nor2_1": (("A", "B"), {"Y": "(!A&!B)"}, None),
    "nor2b_1": (("A", "B_N"), {"Y": "(!A&B_N)"}, None),
    "nor3_1": (("A", "B", "C"), {"Y": "(!A&!B&!C)"}, None),
    "nor3b_1": (("A", "B", "C_N"), {"Y": "(!A&!B&C_N)"}, None),
    "nor4_1": (("A", "B", "C", "D"), {"Y": "(!A&!B&!C&!D)"}, None),
    "nor4b_1": (("A", "B", "C", "D_N"), {"Y": "(!A&!B&!C&D_N)"}, None),
    "o211a_1": (("A1", "A2", "B1", "C1"), {"X": "(A1&B1&C1) | (A2&B1&C1)"}, None),
    "o211ai_1": (("A1", "A2", "B1", "C1"), {"Y": "(!A1&!A2) | (!B1) | (!C1)"}, None),
    "o21a_1": (("A1", "A2", "B1"), {"X": "(A1&B1) | (A2&B1)"}, None),
    "o21ai_0": (("A1", "A2", "B1"), {"Y": "(!A1&!A2) | (!B1)"}, None),
    "o21ba_2": (("A1", "A2", "B1_N"), {"X": "(A1&!B1_N) | (A2&!B1_N)"}, None),
    "o21bai_1": (("A1", "A2", "B1_N"), {"Y": "(!A1&!A2) | (B1_N)"}, None),
    "o221ai_1": (("A1", "A2", "B1", "B2", "C1"), {"Y": "(!B1&!B2) | (!A1&!A2) | (!C1)"}, None),
    "o22ai_1": (("A1", "A2", "B1", "B2"), {"Y": "(!B1&!B2) | (!A1&!A2)"}, None),
    "o31a_1": (("A1", "A2", "A3", "B1"), {"X": "(A1&B1) | (A2&B1) | (A3&B1)"}, None),
    "o31ai_1": (("A1", "A2", "A3", "B1"), {"Y": "(!A1&!A2&!A3) | (!B1)"}, None),
    "o41a_1":
        (("A1", "A2", "A3", "A4", "B1"),
         {"X": "(A1&B1) | (A2&B1) | (A3&B1) | (A4&B1)"},
         None),
    "o41ai_1": (("A1", "A2", "A3", "A4", "B1"), {"Y": "(!A1&!A2&!A3&!A4) | (!B1)"}, None),
    "or2_2": (("A", "B"), {"X": "(A) | (B)"}, None),
    "or3_1": (("A", "B", "C"), {"X": "(A) | (B) | (C)"}, None),
    "or3b_2": (("A", "B", "C_N"), {"X": "(A) | (B) | (!C_N)"}, None),
    "or4_1": (("A", "B", "C", "D"), {"X": "(A) | (B) | (C) | (D)"}, None),
    "or4b_2": (("A", "B", "C", "D_N"), {"X": "(A) | (B) | (C) | (!D_N)"}, None),
    "xnor2_1": (("A", "B"), {"Y": "(!A&!B) | (A&B)"}, None),
    "xor2_1": (("A", "B"), {"X": "(A&!B) | (!A&B)"}, None),
}

#: the synthetic decks' base delays (ns, rise/fall): every arc of a
#: combinational cell, and of a flop, before the per-deck scale
SYNTH_COMB_DELAY_NS = (0.100, 0.200)
SYNTH_DFF_DELAY_NS = (0.900, 1.000)


def synth_factor(corner: str) -> float:
    """The delay scale of synthetic deck ``corner``: ``1.0 + 0.05 * i`` over
    the 8 mapped decks in sorted order, so each deck is a different file
    (different sha256) carrying delays a test can tell apart."""
    decks = sorted({row["liberty_corner"] for row in PVT.DECK_TABLE.values()})
    return 1.0 + 0.05 * decks.index(corner)


def _synth_nldm(name: str, value_ns: float) -> str:
    """A 2x2 ``cell_rise``/``cell_fall`` table whose four values are all
    ``value_ns``: the generator's bilinear reduction returns exactly it."""
    v = f"{value_ns:.6f}"
    return (f'                {name} ("del_2_2") {{\n'
            f'                    index_1("0.1000000000, 0.5000000000");\n'
            f'                    index_2("0.0010000000, 0.0090000000");\n'
            f'                    values("{v}, {v}", \\\n'
            f'                         "{v}, {v}");\n'
            f'                }}\n')


def _synth_arcs(related: str, delays: tuple[float, float]) -> str:
    return (f'            timing () {{\n'
            f'                related_pin : "{related}";\n'
            f'                timing_sense : "non_unate";\n'
            f'                timing_type : "combinational";\n'
            + _synth_nldm("cell_rise", delays[0]) + _synth_nldm("cell_fall", delays[1])
            + "            }\n")


def _synth_cell(short: str, scale: float) -> str:
    ins, outs, ff = CELL_STRUCTURE[short]
    pins = ""
    for p in ins:
        clock = '            clock : "true";\n' if ff and p == "CLK" else ""
        pins += (f'        pin ("{p}") {{\n            capacitance : 0.0020000000;\n'
                 f'            direction : "input";\n{clock}        }}\n')
    comb = tuple(d * scale for d in SYNTH_COMB_DELAY_NS)
    dff = tuple(d * scale for d in SYNTH_DFF_DELAY_NS)
    out = ""
    for pin, function in outs.items():
        arcs = ""
        if ff:
            arcs += _synth_arcs("CLK", dff).replace(
                'timing_type : "combinational";', 'timing_type : "rising_edge";')
            for attr, ttype in (("clear", "clear"), ("preset", "preset")):
                if ff[1].get(attr):
                    arcs += _synth_arcs(ff[1][attr].lstrip("!"), dff).replace(
                        'timing_type : "combinational";', f'timing_type : "{ttype}";')
        else:
            for p in ins:
                arcs += _synth_arcs(p, comb)
        out += f'        pin ("{pin}") {{\n            direction : "output";\n' \
               f'            function : "{function}";\n{arcs}        }}\n'
    group = ""
    if ff:
        args = ", ".join(f'"{a}"' for a in ff[0])
        group = (f'        ff ({args}) {{\n'
                 + "".join(f'            {k} : "{v}";\n' for k, v in ff[1].items()) + "        }\n")
    return f'    cell ("sky130_fd_sc_hd__{short}") {{\n        area : 5.0000000000;\n{pins}{group}{out}    }}\n'


def synthetic_deck_text(corner: str) -> str:
    """One synthetic ``sky130_fd_sc_hd`` deck: every cell the routed netlist
    uses, delays scaled by ``synth_factor(corner)``, a 50 % input threshold."""
    scale = synth_factor(corner)
    cells = "".join(_synth_cell(s, scale) for s in sorted(CELL_STRUCTURE))
    return (
        'library ("synthetic_sky130_fd_sc_hd") {\n'
        '    delay_model : "table_lookup";\n'
        '    time_unit : "1ns";\n'
        '    voltage_unit : "1V";\n'
        '    capacitive_load_unit(1.0000000000, "pf");\n'
        '    input_threshold_pct_fall : 50.000000000;\n'
        '    input_threshold_pct_rise : 50.000000000;\n'
        '    lu_table_template ("del_2_2") {\n'
        '        variable_1 : "input_net_transition";\n'
        '        variable_2 : "total_output_net_capacitance";\n'
        '    }\n'
        f'{cells}}}\n')


class SyntheticPdk:
    """A fake sky130A ``libs.ref`` holding the 8 synthetic decks (built once).

    ``root`` is what ``--libs-ref`` takes; ``sha[deck file]`` is the sha256 a
    plan must carry once ``DECK_TABLE`` is re-pinned to these files."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="test-synth-pdk-")
        self.root = Path(self._tmp.name)
        self.lib = self.root / PVT.LIB_SUBDIR
        self.lib.mkdir(parents=True)
        self.corner_of: dict[str, str] = {}
        self.sha: dict[str, str] = {}
        for row in PVT.DECK_TABLE.values():
            deck, corner = row["liberty_deck"], row["liberty_corner"]
            if deck in self.sha:
                continue
            text = synthetic_deck_text(corner)
            (self.lib / deck).write_text(text)
            self.corner_of[deck] = corner
            self.sha[deck] = hashlib.sha256(text.encode()).hexdigest()
        assert len(self.sha) == 8, sorted(self.sha)


SYNTH = SyntheticPdk()


@contextlib.contextmanager
def synthetic_pins():
    """Re-pin ``DECK_TABLE``'s sha256 values to the synthetic decks for the
    duration -- the test's stand-in for "a sky130A install whose decks hash
    to the pins" -- and restore the committed pins on exit."""
    pins = {k: row["liberty_sha256"] for k, row in PVT.DECK_TABLE.items()}
    for row in PVT.DECK_TABLE.values():
        row["liberty_sha256"] = SYNTH.sha[row["liberty_deck"]]
    try:
        yield
    finally:
        for k, sha in pins.items():
            PVT.DECK_TABLE[k]["liberty_sha256"] = sha


def run_grid(out: Path, *extra: str, libs_ref: bool = True, pins: bool = True) -> tuple[object, str]:
    """``mr.main(["--set", "grid", out, ...])`` quietly; ``(rc | SystemExit, stderr)``.

    ``libs_ref=False`` leaves the deck location to ``klt pdk find``;
    ``pins=False`` keeps the committed sha256 pins (so a synthetic deck fails
    the on-disk check)."""
    argv = ["--set", "grid", str(out)]
    if libs_ref:
        argv += ["--libs-ref", str(SYNTH.root)]
    err = io.StringIO()
    with contextlib.ExitStack() as stack:
        if pins:
            stack.enter_context(synthetic_pins())
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(err))
        try:
            rc: object = mr.main([*argv, *extra])
        except SystemExit as exc:
            rc = exc
    return rc, err.getvalue()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

#: how close to a rail a capture-point sample must sit (V). The pre-#488 ramp
#: missed by hundreds of mV, so this is loose enough to be about shape and tight
#: enough that a residual ramp of any practical width still fails.
RAIL_TOL_V = 1e-3

_PWL_RE = re.compile(r"^V(\S+) (\S+) 0 PWL\((.*)\)$")


def parse_card(card: str) -> tuple[str, str, list[tuple[float, float]]]:
    """``(signal, net, breakpoints)`` from one emitted PWL card."""
    m = _PWL_RE.match(card)
    assert m, f"not a PWL card: {card!r}"
    body = m.group(3).split()
    assert len(body) % 2 == 0 and body, f"odd breakpoint body: {card!r}"
    pts = []
    for i in range(0, len(body), 2):
        t_tok = body[i]
        assert t_tok.endswith("n"), f"time {t_tok!r} is not in ns: {card!r}"
        pts.append((float(t_tok[:-1]), float(body[i + 1])))
    return m.group(1), m.group(2), pts


def pwl_at(pts: list[tuple[float, float]], t: float) -> float:
    """What ngspice's PWL source produces at ``t``: linear between breakpoints."""
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    raise AssertionError(f"t={t} not covered by {pts}")


def off_rail_samples(limit: int | None) -> list[tuple[str, int, float, float]]:
    """``(signal, cycle, t_ns, volts)`` for every capture point off a rail."""
    cycles, _ = P.build_program(limit)
    n_cycles = len(cycles)
    bad = []
    for card in mr.input_cards(cycles, n_cycles):
        sig, _net, pts = parse_card(card)
        for k in range(n_cycles):
            t = P.t_edge_ns(k) + P.CAPTURE_NS
            v = pwl_at(pts, t)
            if min(abs(v - 0.0), abs(v - mr.VIH)) > RAIL_TOL_V:
                bad.append((sig, k, t, v))
    return bad


def test_capture_points_sit_at_a_rail() -> None:
    """THE CONTROL (issue #488): no driven input is mid-flight at a capture point.

    Fails on the pre-#488 change-instants-only shape with 14 off-rail samples on
    the limit=6 startup deck and 344 of 3000 on the full grid program.
    """
    for limit, label, n_expected in ((6, "limit=6 startup probe", 240),
                                     (None, "full grid program", 3000)):
        cycles, _ = P.build_program(limit)
        cards = mr.input_cards(cycles, len(cycles))
        n_samples = len(cards) * len(cycles)
        assert n_samples == n_expected, (label, n_samples, n_expected)
        bad = off_rail_samples(limit)
        assert not bad, (
            f"{label}: {len(bad)} of {n_samples} (input x capture point) samples "
            f"are off-rail by more than {RAIL_TOL_V * 1e3:.0f} mV -- the PWL "
            f"ramps between cycles instead of holding. Worst: "
            f"{min(bad, key=lambda r: abs(r[3] - mr.VIH / 2.0))}"
        )


def test_change_emits_hold_then_edge() -> None:
    """A mid-program change is a hold breakpoint plus a ~100 ps edge, not a ramp.

    ``bus_re`` is 1 in the limit=6 startup deck's first cycle and 0 from the
    fourth on, so its single change lands at t_edge(3)+SKEW = 640 ns.
    """
    cycles, _ = P.build_program(6)
    cards = {parse_card(c)[0]: parse_card(c)[2] for c in mr.input_cards(cycles, len(cycles))}
    pts = cards["bus_re"]
    t_change = P.t_edge_ns(3) + P.SKEW_NS
    assert t_change == 640.0, t_change
    idx = [i for i, (t, _v) in enumerate(pts) if t == t_change]
    assert len(idx) == 1, (f"expected exactly one breakpoint at {t_change}n", pts)
    i = idx[0]
    assert i > 0, ("change breakpoint must be preceded by a hold point", pts)
    t_hold, v_hold = pts[i - 1]
    t_edge, v_edge = pts[i]
    assert (t_hold, v_hold) == (t_change - mr.EDGE_NS, mr.VIH), (
        f"hold point before the {t_change}n change should be "
        f"({t_change - mr.EDGE_NS}n, {mr.VIH}) -- got ({t_hold}n, {v_hold})", pts)
    assert v_edge == 0.0, (f"bus_re should switch to 0 V at {t_change}n", pts)
    # the edge itself is the declared edge width, not a cycle-long ramp
    assert abs((t_edge - t_hold) - mr.EDGE_NS) < 1e-9, (t_hold, t_edge)
    # and the formatted card really carries both timestamps distinctly
    card = next(c for c in mr.input_cards(cycles, len(cycles)) if c.startswith("Vbus_re "))
    assert "639.9n 1.800 640.0n 0.000" in card, card


def test_breakpoint_hygiene() -> None:
    """Endpoints, strict monotonicity in the FORMATTED times, and a constant input."""
    for limit in (6, None):
        cycles, _ = P.build_program(limit)
        n_cycles = len(cycles)
        t_stop = P.t_stop_ns(cycles)
        for card in mr.input_cards(cycles, n_cycles):
            sig, _net, pts = parse_card(card)
            assert pts[0][0] == 0.0, (sig, "first breakpoint must be t=0", pts[:2])
            assert pts[-1][0] == t_stop, (sig, "last breakpoint must be t_stop", pts[-2:])
            # duplicate formatted timestamps are what an under-wide EDGE_NS
            # produces; pwl_card writes times as f"{t:.1f}n", so compare those
            shown = [f"{t:.1f}" for t, _v in pts]
            assert len(set(shown)) == len(shown), (
                sig, "two breakpoints share a formatted timestamp", shown)
            assert shown == sorted(shown, key=float), (sig, "times not increasing", shown)
            assert all(v in (0.0, mr.VIH) for _t, v in pts), (
                sig, "every breakpoint value is a rail", pts)

    # an input that never changes still emits exactly its two endpoints. In the
    # limit=6 startup deck out_ready is 0 in every cycle.
    cycles, _ = P.build_program(6)
    inputs = P.cycle_inputs(cycles)
    assert len({i["out_ready"] for i in inputs}) == 1, [i["out_ready"] for i in inputs]
    card = next(c for c in mr.input_cards(cycles, len(cycles)) if c.startswith("Vout_ready "))
    _sig, _net, pts = parse_card(card)
    assert len(pts) == 2, ("a constant input needs no hold point", pts)
    assert pts == [(0.0, 0.0), (P.t_stop_ns(cycles), 0.0)], pts


def test_grid_timeouts_from_the_measured_coupled_rate() -> None:
    """Issues #431 / #596 / #815 / #814: the grid's timeouts come from the
    measured coupled runs, for the job shape the grid now has.

    ``records/20261128-coupled-rate.md`` measured the coupled whole block at
    431.63 s for the 7,870 ns program (tt / 27 C / 1.8 V);
    ``records/20261128-slow-corner-runtime.md`` measured the slowest-expected
    point, ss / -40 C / 1.62 V, at 403.9 s -- inside the nominal, so the
    nominal stays the worst measured point and the 2.0x allowance is kept
    rather than lowered to the 1.25x the two measured points ask for (a unit
    timeout is a kill-bound, not a reservation, and ten points are
    unmeasured). Since #815 one request is one single-process unit (one
    netlist, one gate model), so the job bound is 864 + 120 = 984 s and the
    caller waits 300 s longer. The archived flat grid under ``corners/grid-*``
    keeps the settings it was filed with (21600 / 6600 s, no rate behind them)
    and is not regenerated.
    """
    assert mr.COUPLED_FULL_RUNTIME_S == 431.63 and mr.GRID_MARGIN_X == 2.0
    # the slow-corner figure is the committed report's, at the committed
    # request's point and deck (#814); the request carried the one-unit
    # measurement timeouts, not the grid's, so a slow corner would have been
    # measured rather than killed
    run = HERE / "runs/20261128-slow-corner-ss-m40C-1.62V"
    report = json.loads((run / "report.json").read_text())
    plan = json.loads((run / "requests/grid-ss-m40C-1.62V/plan.json").read_text())
    corner, = report["corners"]
    assert report["status"] == "pass" and corner["status"] == "pass"
    assert mr.SLOW_CORNER_POINT == "ss / -40 C / 1.62 V"
    assert corner["runtime_s"] == mr.SLOW_CORNER_RUNTIME_S == 403.9
    assert (corner["process"], corner["temperature_c"], corner["supply_v"]["Vvdd"]) == ("ss", -40.0, 1.62)
    assert report["environment"]["remote"]["job_id"] == "klt-sim-4ec1825cfa41"
    assert report["environment"]["netlist_sha256"] == plan["netlist_sha256"]
    assert (plan["timeouts"]["timeout_s"], plan["timeouts"]["poll_timeout_s"]) == (3360, 3480)
    # the slowest-expected point runs inside the nominal: the nominal is the
    # worst measured point, and the allowance is never below what the measured
    # points ask for (the worst x 1.25, #814's formula)
    worst = max(mr.COUPLED_FULL_RUNTIME_S, mr.SLOW_CORNER_RUNTIME_S)
    assert worst == mr.COUPLED_FULL_RUNTIME_S
    assert mr.GRID_MARGIN_X >= math.ceil(worst / mr.COUPLED_FULL_RUNTIME_S * 1.25 * 100) / 100 == 1.25
    assert mr.GRID_TIMEOUT_S == math.ceil(mr.GRID_MARGIN_X * mr.COUPLED_FULL_RUNTIME_S) == 864
    assert mr.GRID_TIMEOUT_S <= mr.UNIT_TIMEOUT_CAP_S == 3480
    assert mr.GRID_UNITS == 1
    assert mr.grid_timeouts() == (mr.GRID_TIMEOUT_S, mr.GRID_POLL_TIMEOUT_S) == (864, 1284)
    grids = [(name, request) for name, request in generated_requests() if name.startswith("grid-")]
    assert len(grids) == 12
    for name, request in grids:
        assert request["options"]["timeout_s"] == mr.GRID_TIMEOUT_S
        assert len(request["corners"]["process"]) == 1, (name, "one process per request")
        # klt's one-job bound, the fleet ceiling, then the caller's wait
        bound = mr.GRID_UNITS * request["options"]["timeout_s"] + mr.BATCH_OVERHEAD_S
        assert bound == 984 <= mr.FLEET_JOB_CEILING_S == 3600
        assert request["batch"]["poll_timeout_s"] == bound + mr.JOB_SLACK_S == 1284
    for plan in grid_plans():
        assert plan["timeouts"] == mr.grid_timeout_basis()
        assert plan["timeouts"]["sized_from"] == "records/20261128-coupled-rate.md"
        # every grid plan carries the slow-corner measurement the allowance
        # was checked against (#814)
        assert plan["timeouts"]["slow_corner_point"] == mr.SLOW_CORNER_POINT
        assert plan["timeouts"]["slow_corner_runtime_s"] == mr.SLOW_CORNER_RUNTIME_S
        assert plan["timeouts"]["slow_corner_record"] == mr.SLOW_CORNER_RECORD
        assert mr.SLOW_CORNER_RECORD == "records/20261128-slow-corner-runtime.md"
        assert (plan["timeouts"]["timeout_s"], plan["timeouts"]["job_bound_s"],
                plan["timeouts"]["poll_timeout_s"], plan["timeouts"]["units"]) == (864, 984, 1284, 1)
    grids = sorted((HERE / "corners").glob("grid-*/request.json"))
    assert len(grids) == 4, [str(p) for p in grids]
    for req in grids:
        d = json.loads(req.read_text())
        assert d["options"]["timeout_s"] == 21600, (str(req), d["options"])
        assert d["batch"]["poll_timeout_s"] == 6600, (str(req), d["batch"])


def test_grid_timeouts_refuse_what_the_ceiling_cannot_hold() -> None:
    """A unit allowance no one-unit job can hold refuses generation closed,
    and the archived three-unit shape -- still sized by the same function --
    refuses what no job can hold serially: nothing is written either way."""
    with tempfile.TemporaryDirectory(prefix="test-grid-timeout-") as tmp:
        real = mr.GRID_MARGIN_X
        mr.GRID_MARGIN_X = 20.0
        try:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    mr.main(["--set", "grid", str(Path(tmp) / "g20")])
            except ValueError as e:
                assert "one unit" in str(e), e
            else:
                raise AssertionError("margin 20.0 did not refuse")
            assert not (Path(tmp) / "g20").exists()
        finally:
            mr.GRID_MARGIN_X = real
        mr.GRID_MARGIN_X = 8.0
        try:
            # the allowance itself fits one unit (3454 s) ...
            assert mr.grid_timeouts(units=1) == (3454, 3454 + 120 + 300)
            # ... but no job holds three of them serially
            try:
                mr.grid_timeouts(units=3)
            except ValueError as e:
                assert "3 units" in str(e), e
            else:
                raise AssertionError("margin 8.0 x 3 units did not refuse")
        finally:
            mr.GRID_MARGIN_X = real
    assert mr.grid_timeouts() == (mr.GRID_TIMEOUT_S, mr.GRID_POLL_TIMEOUT_S) == (864, 1284)
    # the pre-#815 three-unit shape, for the record: 3 x 864 + 120 + 300
    assert mr.grid_timeouts(units=3) == (864, 3012)
    assert mr.grid_timeout_basis(units=3)["job_bound_s"] == 2712


# ---------------------------------------------------------------------------
# Issue #507: no measurement may probe past its own request's .tran stop
# ---------------------------------------------------------------------------

#: a `.meas` time bound in this deck family's card text: `AT=310.0n`, `TO=250n`.
#: Unit-agnostic since issue #555: the value and its unit suffix are captured
#: separately and the suffix asserted in `over_stop_violations()`, so a bound
#: in any other unit (or a bare number with no unit at all) is visited and
#: *flagged* -- never silently skipped the way the old ns-only pattern
#: (`([\d.]+)n`) skipped it while the cross-request totals stayed non-zero.
_BOUND_RES = {key: re.compile(rf"\b{key}=\s*([\d.]+)([a-zA-Z]*)\b")
              for key in ("AT", "TO")}

#: the committed startup-probe requests' known-stale over-`t_stop` cards
#: (issue #507's ledger). They predate the card collector's ``t_stop`` clip
#: (``program._MeasCollector.add``) and are deliberately NOT regenerated --
#: dropping this entry requires either a regeneration of both dirs or a new
#: decision record continuing
#: `records/20261115a-known-stale-startup-probe-requests.md`.
KNOWN_STALE_OVER_STOP = {
    "startup-probe": frozenset(f"{sig}_k{k}" for sig in
                               ("alarm", "gated", "startup_done") for k in (36, 42, 74)),
    "startup-probe-batch": frozenset(f"{sig}_k{k}" for sig in
                                     ("alarm", "gated", "startup_done") for k in (36, 42, 74)),
}

#: the sixteen requests the generator emits across the four `--set` groups:
#: since #815 the grid is twelve single-process coupled requests (#815)
_GENERATED_NAMES = ("analog-probe-batch",
                    "grid-ff-125C-1.98V", "grid-ff-27C-1.80V", "grid-ff-m40C-1.62V", "grid-ff-m40C-1.98V",
                    "grid-ss-125C-1.98V", "grid-ss-27C-1.80V", "grid-ss-m40C-1.62V", "grid-ss-m40C-1.98V",
                    "grid-tt-125C-1.98V", "grid-tt-27C-1.80V", "grid-tt-m40C-1.62V", "grid-tt-m40C-1.98V",
                    "rate-probe-batch", "startup-probe", "startup-probe-batch")

_generated: list[tuple[str, dict]] | None = None


def generated_requests() -> list[tuple[str, dict]]:
    """``(corner name, request dict)`` for every request the generator emits.

    Runs the real writer (``mr.main``) for all four ``--set`` groups into a
    throwaway ``tempfile`` directory -- never into ``corners/`` (the generator
    refuses a non-empty directory, and writing into the repo would dirty
    tracked paths). The grid set is generated against the synthetic PDK
    (``run_grid``). Memoized: one generation serves all the #507 tests.
    """
    global _generated
    if _generated is None:
        out: list[tuple[str, dict]] = []
        with tempfile.TemporaryDirectory(prefix="test-make-requests-") as tmp:
            for which in ("controls", "rate-probe", "analog-probe"):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = mr.main(["--set", which, str(Path(tmp) / which)])
                assert rc == 0, (which, rc)
            rc, err = run_grid(Path(tmp) / "grid")
            assert rc == 0, err
            for p in sorted(Path(tmp).glob("*/*/request.json"),
                            key=lambda p: p.parent.name):
                out.append((p.parent.name, json.loads(p.read_text())))
        _generated = out
    return _generated


def tran_stop_ns(request: dict) -> float:
    """The request's own ``.tran`` stop (ns), from ``analysis.args``.

    ``args`` is ``f"{TMAX} {analysis_args}"`` (``"20p 970n"``), so the stop is
    its last whitespace-separated token, with a unit suffix.
    """
    tok = request["analysis"]["args"].split()[-1]
    assert tok.endswith("n"), f".tran stop {tok!r} is not in ns"
    return float(tok[:-1])


def over_stop_violations(request: dict) -> tuple[list[str], int, int]:
    """``(over-stop names, #AT= visited, #TO= visited)`` for one request.

    ``AT=`` is the instant a ``FIND`` samples at; ``TO=`` is the end of an
    ``AVG``/``INTEG`` window (``w2`` ends at ``t_stop - TS_NS``). ``WHEN``
    cards carry neither and are skipped by construction. The unit suffix is
    asserted to be ``n`` (issue #555): the generator only emits ns, so any
    other unit is generator drift the scan must flag rather than skip --
    same posture as ``tran_stop_ns()`` on the stop side.
    """
    stop = tran_stop_ns(request)
    over: list[str] = []
    n_at = n_to = 0
    for m in request["measurements"]:
        for key, rx in _BOUND_RES.items():
            mm = rx.search(m["spice"])
            if mm is None:
                continue
            assert mm.group(2) == "n", (
                f"{m['name']}: bound {mm.group(0)!r} is not in ns -- the "
                "bound scan must flag units it cannot check, not skip them")
            if key == "AT":
                n_at += 1
            else:
                n_to += 1
            if float(mm.group(1)) > stop:
                over.append(m["name"])
    return over, n_at, n_to


#: every shape of bound token the card text could carry, counted straight
#: off the raw text: ``AT``/``TO`` then optional whitespace then ``=``.
#: Broader than ``_BOUND_RES`` on purpose (issue #576): the scanner's value
#: grammar may lag what a future card emits, but a token this counter sees
#: and the scanner does not visit must turn the suite red, never skip.
_BOUND_TOKEN_RES = {key: re.compile(rf"\b{key}\s*=") for key in ("AT", "TO")}


def assert_every_bound_visited(name: str, request: dict) -> tuple[list[str], int, int]:
    """Per-card visit guard (#576): the scan visits every bound a card carries.

    ``over_stop_violations()``'s counts are request-level totals, so the
    pre-#576 guard (``n_at + n_to > 0`` when any card carries a bound) could
    not see one unmatchable card hiding behind its neighbours. This counts
    the ``AT=``/``TO=`` tokens per card -- ``_BOUND_TOKEN_RES``, not
    ``_BOUND_RES`` -- and asserts each one was visited, subsuming that
    per-request check: a request with only matched cards passes exactly as
    before, while a single card whose token the pattern cannot reach fails
    on its own. A card with two ``AT=`` tokens also fails: the scan reads
    one match per key per card (``rx.search``), and the generator emits one
    per key. ``WHEN`` cards carry neither token and are exempt.

    Returns ``(over, n_at, n_to)`` unchanged from ``over_stop_violations()``
    so the caller keeps one scan per request.
    """
    over, n_at, n_to = over_stop_violations(request)
    skipped = []
    for m in request["measurements"]:
        present = sum(len(rx.findall(m["spice"]))
                      for rx in _BOUND_TOKEN_RES.values())
        if not present:
            continue
        visited = sum(1 for rx in _BOUND_RES.values() if rx.search(m["spice"]))
        if visited < present:
            skipped.append((m["name"], present, visited))
    assert not skipped, (
        name, f"{len(skipped)} measurement card(s) carry AT=/TO= bound "
        "tokens the bound scan did not visit -- its pattern cannot reach "
        "them, so those bounds are checked nowhere (name, tokens present, "
        "tokens visited):", skipped)
    return over, n_at, n_to


def test_generated_measurements_within_tran_stop() -> None:
    """Issue #507 drift 1, on generator output: no measurement's ``AT=`` or
    ``TO=`` exceeds its own request's ``.tran`` stop.

    All four ``--set`` groups, including the two short probes (100 ns and
    500 ns) whose stop is far tighter than the startup probe's 970 ns. The
    cross-request visit counts are asserted non-zero so a drifted
    ``_BOUND_RES`` cannot make the scan pass vacuously, and -- issue #576,
    subsuming #555's per-request check -- every card carrying an
    ``AT=``/``TO=`` token must have that token visited by the scan itself,
    so a single card whose bound the pattern cannot reach fails on its own
    instead of hiding behind the hundreds of visited ones. Requests whose
    measurements are all ``WHEN`` cards carry neither bound and are exempt.
    """
    reqs = generated_requests()
    assert tuple(n for n, _ in reqs) == _GENERATED_NAMES, [n for n, _ in reqs]
    n_at_total = n_to_total = 0
    for name, d in reqs:
        over, n_at, n_to = assert_every_bound_visited(name, d)
        n_at_total += n_at
        n_to_total += n_to
        assert not over, (
            name, f"{len(over)} emitted measurements probe past the request's own "
            f".tran stop {tran_stop_ns(d)}n", sorted(over))
    assert n_at_total > 0 and n_to_total > 0, (
        "the bound scan visited no AT=/TO= token -- it is vacuous",
        n_at_total, n_to_total)


def test_committed_request_ledger() -> None:
    """Issue #507 recurrence guard over the committed ``corners/*/request.json``.

    Every committed request satisfies the ``AT=``/``TO=`` <= ``.tran`` stop
    invariant except the two startup probes, whose violations are pinned to
    exactly the nine pre-clip cards. A *new* corner directory carrying an
    over-``t_stop`` card turns this red, and regenerating the startup probes
    later also turns it red until the ledger entry is dropped -- so the ledger
    cannot go stale silently.
    """
    for req in sorted((HERE / "corners").glob("*/request.json")):
        name = req.parent.name
        over, _n_at, _n_to = over_stop_violations(json.loads(req.read_text()))
        assert sorted(over) == sorted(KNOWN_STALE_OVER_STOP.get(name, ())), (
            name, "committed measurement bounds past the request's own .tran "
            "stop differ from the known-stale ledger; if the startup probes "
            "were regenerated, drop the ledger entry in the same change",
            sorted(over))
    for name in KNOWN_STALE_OVER_STOP:
        assert (HERE / "corners" / name / "request.json").exists(), (
            f"known-stale ledger names {name} but its committed request is gone")


def test_startup_probe_timeouts_pinned() -> None:
    """Issue #507 drift 2: what the generator emits vs what is committed.

    The generator emits ``timeout_s`` 3600 for ``startup-probe`` (local) and
    3480 / ``poll_timeout_s`` 3700 for ``startup-probe-batch``; the committed
    batch pair still carries 14400 / 7000. Both sides are pinned so the
    divergence is a checked, named fact rather than an undocumented mismatch.
    """
    gen = dict(generated_requests())
    assert gen["startup-probe"]["options"]["timeout_s"] == 3600, \
        gen["startup-probe"]["options"]
    assert "batch" not in gen["startup-probe"], gen["startup-probe"].get("batch")
    assert gen["startup-probe-batch"]["options"]["timeout_s"] == 3480, \
        gen["startup-probe-batch"]["options"]
    assert gen["startup-probe-batch"]["batch"]["poll_timeout_s"] == 3700, \
        gen["startup-probe-batch"]["batch"]
    # the committed pair records the divergence (not regenerated; issue #507)
    committed = json.loads((HERE / "corners" / "startup-probe" / "request.json").read_text())
    assert committed["options"]["timeout_s"] == 3600, committed["options"]
    committed_b = json.loads((HERE / "corners" / "startup-probe-batch" / "request.json").read_text())
    assert committed_b["options"]["timeout_s"] == 14400, committed_b["options"]
    assert committed_b["batch"]["poll_timeout_s"] == 7000, committed_b["batch"]


def test_final_cycle_read_emits_no_rdata_measurement() -> None:
    """Issue #646: the deck must not collect a measurement nothing can score.

    A read's data is latched at the edge that ENDS cycle k and observed
    during cycle k+1, so a read in the last cycle has no cycle to be
    observed in and no model row to compare with. ``make-gate-model.py``
    has always guarded its rdata set with ``k + 1 < n``; before #646 this
    generator emitted the word anyway -- 32 cards the shared oracle
    structurally skips while the reducer's ``required`` contract demands
    their presence, i.e. collected, required, never compared.

    The committed program's last cycle is the final STATUS read, so the
    guard bites on it: ``rdata_k74_b*`` is gone, every earlier read keeps
    its full 32-bit word, and the grid program's card count drops
    610 -> 578.
    """
    cycles, _ = P.build_program()
    n = len(cycles)
    inputs = P.cycle_inputs(cycles)
    assert inputs[n - 1]["re"], "the committed program's last cycle is a read"
    cards, _save = mr.measurement_cards(cycles)
    names = {c["name"] for c in cards}
    for bit in range(32):
        assert f"rdata_k{n - 1}_b{bit}" not in names
    for k, inp in enumerate(inputs[:-1]):
        if inp["re"]:
            got = sum(1 for b in range(32) if f"rdata_k{k}_b{b}" in names)
            assert got == 32, (k, got)


def test_last_cycle_without_read_changes_nothing() -> None:
    """Issue #646 edge cases: the guard must bite only on a last-cycle read.

    The committed program truncated to 43 cycles ends on a streaming
    sample and its last read sits in cycle 41 = n-2: no card changes
    against the pre-#646 generator (417 cards), and the n-2 read still
    emits its full 32-bit word -- it is observed in cycle n-1, which
    exists.
    """
    cycles, _ = P.build_program(43)
    n = len(cycles)
    assert cycles[n - 1]["op"] == "sample", cycles[n - 1]["op"]
    inputs = P.cycle_inputs(cycles)
    assert inputs[n - 2]["re"], "cycle n-2 is a read in this truncation"
    cards, _save = mr.measurement_cards(cycles)
    names = {c["name"] for c in cards}
    assert len(cards) == 417, len(cards)
    for k, inp in enumerate(inputs):
        if inp["re"]:
            expected = 32 if k + 1 < n else 0
            got = sum(1 for b in range(32) if f"rdata_k{k}_b{b}" in names)
            assert got == expected, (k, got)


def test_shared_collector_clips_and_refuses_repeated_names() -> None:
    """#804: the three card sets share one collector (program._MeasCollector).

    A card sampling past ``t_stop`` is dropped whole -- the #507 invariant,
    enforced at the source instead of once per generator -- and a repeated
    name is refused rather than displacing the entry it repeats (#548);
    make-gate-model.py surfaces that refusal as ``GateModelError``.
    """
    c = P._MeasCollector(970.0, {"clk"})
    c.add("a", ".meas tran a FIND v(x) AT=970.0n", "x", 970.0)   # at t_stop: kept
    c.add("b", ".meas tran b FIND v(y) AT=970.1n", "y", 970.1)   # past it: dropped
    c.word("odata", 3, "out_data_{}_", 870.0)
    assert c.meas[0] == {"name": "a", "spice": ".meas tran a FIND v(x) AT=970.0n"}
    assert [m["name"] for m in c.meas[1:]] == [f"odata_k3_b{b}" for b in range(32)]
    assert c.meas[1] == {"name": "odata_k3_b0",
                         "spice": ".meas tran odata_k3_b0 FIND v(out_data_0_) AT=870.0n"}
    assert c.save == {"clk", "x"} | {f"out_data_{b}_" for b in range(32)}
    assert c.result() == (c.meas, sorted(c.save))
    c.add("a", ".meas tran a FIND v(x) AT=970.0n")
    try:
        c.result()
    except ValueError as e:
        assert "duplicate measurement names" in str(e), e
    else:
        raise AssertionError("a repeated measurement name was not refused")


# ---------------------------------------------------------------------------
# Issue #555: the bound scan must fail loud on a unit it cannot check
# ---------------------------------------------------------------------------

def test_bound_scan_flags_non_ns_units() -> None:
    """Issue #555 negative control: a non-``n`` unit suffix turns the scan red.

    The pre-#555 ns-only ``_BOUND_RES`` silently skipped ``AT=1.5u``-style
    cards -- one skipped card among hundreds of visited ones kept the
    cross-request non-vacuity totals non-zero, so
    ``test_generated_measurements_within_tran_stop`` kept passing while no
    longer covering that card. These fixtures call ``over_stop_violations()``
    directly on synthetic requests, so the fail-loud posture is pinned
    permanently without editing the generator or any committed request.
    """
    def req_with(*cards: str) -> dict:
        return {"analysis": {"args": "20p 970n"},
                "measurements": [{"name": "m", "spice": c} for c in cards]}

    # ns bounds still scan -- including whitespace after `=`, which the old
    # pattern would also have missed
    over, n_at, n_to = over_stop_violations(
        req_with(".meas tran m FIND v(out) AT=310.0n"))
    assert (over, n_at, n_to) == ([], 1, 0), (over, n_at, n_to)
    over, n_at, n_to = over_stop_violations(
        req_with(".meas tran m AVG i(Vvdd) FROM=20n TO= 90.0n"))
    assert (over, n_at, n_to) == ([], 0, 1), (over, n_at, n_to)

    # the check itself still fires on an ns card past the stop
    over, n_at, n_to = over_stop_violations(
        req_with(".meas tran m FIND v(out) AT=3970.0n"))
    assert over == ["m"] and n_at == 1, (over, n_at, n_to)

    # any other unit -- ``u``/``p``, a multi-letter spelling, or a bare number
    # with no unit at all (what the generator's bare-substitution forms would
    # emit if someone dropped their pre-formatted `n`) -- is flagged, not
    # skipped
    for bad in ("AT=1.5u", "AT=310p", "AT=310ns", "AT=310",
                "TO=2u", "TO=90.0ns"):
        card = (f".meas tran m FIND v(out) {bad}" if bad.startswith("AT=")
                else f".meas tran m AVG i(Vvdd) FROM=20n {bad}")
        try:
            over_stop_violations(req_with(card))
        except AssertionError:
            continue
        raise AssertionError(
            f"bound {bad!r} was silently skipped instead of flagged -- the "
            "bound scan regressed to ns-only matching")

    # a WHEN card carries neither AT= nor TO=; the scan visits nothing but
    # must not raise on it (exempt from the per-request visit check)
    over, n_at, n_to = over_stop_violations(
        req_with(".meas tran m WHEN v(out_valid)=1.4 RISE=1"))
    assert (over, n_at, n_to) == ([], 0, 0), (over, n_at, n_to)


# ---------------------------------------------------------------------------
# Issue #576: the bound-scan visit guard is per-card, not per-request
# ---------------------------------------------------------------------------

def test_per_card_guard_flags_unvisited_bound() -> None:
    """Issue #576 negative control: one unmatchable bound token turns red alone.

    The pre-#576 guard was per-request (``n_at + n_to > 0``): a card whose
    bound token the scan cannot reach hid behind the request's other
    matched bounds -- ``AT = 3970.0n`` (whitespace before the ``=``, which
    ``_BOUND_RES`` cannot match) probed 3000 ns past a 970 ns stop while
    its neighbour's ``AT=310n`` kept the visit count non-zero. Fixture-based,
    no generator edit: the same mixed request through
    ``assert_every_bound_visited()`` must raise instead. Edge cases:
    ``AT={expr}`` and ``AT=-5n`` (shapes the scanner's value grammar cannot
    reach) and a duplicated ``AT=`` token (the scan reads one match per key
    per card) all fail loudly too.
    """
    def req_with(*cards: str) -> dict:
        return {"analysis": {"args": "20p 970n"},
                "measurements": [{"name": f"m{i}", "spice": c}
                                 for i, c in enumerate(cards)]}

    # the mixed request from the issue: matched + unmatchable in one scan
    mixed = req_with(".meas tran m0 FIND v(out) AT=310n",
                     ".meas tran m1 FIND v(out) AT = 3970.0n")
    try:
        assert_every_bound_visited("mixed", mixed)
    except AssertionError as e:
        assert "did not visit" in str(e), e
        assert "('m1', 1, 0)" in str(e), ("the skipped card must be named", e)
    else:
        raise AssertionError(
            "the unmatchable card 'AT = 3970.0n' was silently skipped -- "
            "the visit guard regressed to per-request granularity")

    # a fully-matched request still passes, per-card, with nothing visited
    # being a violation only when a token is present (WHEN cards stay exempt)
    over, n_at, n_to = assert_every_bound_visited(
        "matched", req_with(".meas tran m0 FIND v(out) AT=310n",
                            ".meas tran m1 WHEN v(out_valid)=1.4 RISE=1"))
    assert (over, n_at, n_to) == ([], 1, 0), (over, n_at, n_to)

    # other shapes the scanner's value grammar cannot reach: a substitution
    # expression or a negative value -- flagged per card, not skipped
    for bad in (".meas tran m0 FIND v(out) AT={t_clip}",
                ".meas tran m0 FIND v(out) AT=-5n"):
        request = req_with(bad, ".meas tran m1 FIND v(out) AT=310n")
        try:
            assert_every_bound_visited("edge", request)
        except AssertionError as e:
            assert "('m0', 1, 0)" in str(e), (bad, e)
        else:
            raise AssertionError(f"card {bad!r} was silently skipped")

    # a duplicated AT= token in one card: the scan reads one match per key
    # per card, so the second token would go unchecked -- red by design
    try:
        assert_every_bound_visited(
            "dup", req_with(".meas tran m0 FIND v(out) AT=310n AT=320n"))
    except AssertionError as e:
        assert "('m0', 2, 1)" in str(e), e
    else:
        raise AssertionError("a duplicated AT= token went unflagged")


def test_standalone_waveform_bytes() -> None:
    # SHA-256 of all returned lines at 7330672f, including the final LF.
    gate = gate_model_generator()  # stimulus_cards is the generator CLI's own
    for count, request_hash, gate_hash in (
        (6, "d9d8ae12bab9f3d0898a2c95f6409ff65e329961bf97dbec3e0a6aa022f1f276",
         "656f1a1faf32cea1dd71d27c4dd9f4764e19304170eaa4d31b347307f8893a3f"),
        (75, "6fe44c0b0bab82a0b81f6eb83a052c3042d4b16d2145e7f81d2da07bf2a9333d",
         "d16a420004f83722abf1e03af3e11e7509e8bf1a3a47add9c86eed2a36a0b0c9"),
    ):
        cycles, _ = P.build_program(count)
        for cards, expected in ((mr.input_cards(cycles, count), request_hash),
                                (gate.stimulus_cards(cycles, 1.8), gate_hash)):
            assert hashlib.sha256(("\n".join(cards) + "\n").encode()).hexdigest() == expected


def check_sampler_path(deck: str) -> None:
    # Resolve the Xw call positionally through the actual .SUBCKT declaration.
    cards = deck.replace("\n+", " ").splitlines()
    header = next(c for c in cards if c.startswith(".SUBCKT trng_whole "))
    formals = header.split()[2:]
    actuals = next(c.split()[1:-1] for c in cards if c.startswith("Xw "))
    assert len(formals) == len(actuals)
    analog = cards[cards.index(header):
                   next(i for i, c in enumerate(cards) if c.startswith(".ENDS"))]
    bridge = next(c for c in cards if c.startswith("Aadc_boundary "))
    src, dst = (v.split() for v in re.findall(r"\[([^\]]+)\]", bridge))
    assert "adc_b" == bridge.split()[-1] and ".model adc_b adc_bridge(" in deck
    for name in ("raw_bit", "raw_valid"):
        pin = formals[actuals.index(name)]
        assert name in pin.split("|")
        assert any(c.startswith("Xz") and pin in (c.split()[1], c.split()[3])
                   for c in analog)  # sampler MOS drain or source
        digital = dst[src.index(name)]
        assert digital == "dn_" + name
        assert any(digital in c.replace("[", " ").replace("]", " ").split()[1:-2]
                   for c in cards if c.startswith("A_"))
        assert not any(c[0:1].upper() in ("V", "I", "B", "E", "G", "F", "H")
                       and name in c.split()[1:3] for c in cards)
    for name in ("clk", "rst_n", "vdd", "vss"):
        assert formals[actuals.index(name)] == name
        if name in ("clk", "rst_n"):
            assert dst[src.index(name)] == "dn_" + name
        assert sum(c.startswith("V") and c.split()[1] == name for c in cards) == 1


def test_coupled_request() -> None:
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    with tempfile.TemporaryDirectory() as tmp:
        for mode, stop in (("coupled-probe", 100), ("coupled-full", 7870)):
            out = Path(tmp) / mode
            assert mr.main([str(out), "--set", mode]) == 0
            base = out / mode
            deck = (base / "netlist.cir").read_text()
            plan = json.loads((base / "plan.json").read_text())
            request = json.loads((base / "request.json").read_text())
            assert request["backend"] == "batch" and request["corners"]["process"] == ["tt"]
            assert tran_stop_ns(request) == stop
            assert request["corners"]["temperature_c"] == [27.0]
            assert all(axis == [1.8] for axis in request["corners"]["supply_v"].values())
            assert request["options"]["timeout_s"] + 120 <= 3480
            assert request["batch"]["poll_timeout_s"] <= 3480
            assert plan["analysis_stop_ns"] == stop and plan["provenance"] == P.PROVENANCE
            # issue #682: the settled DR-0017 option 2 travels with the plan
            assert plan["boundary_load_option"] == mr.PVT.boundary_load_block()
            assert plan["boundary_load_option"]["option"] == 2
            assert "settled as option 2" in plan["reductions"]["input_load"]
            assert "is open" not in plan["reductions"]["input_load"]
            nominal = mr.PVT.plan_entry(["tt"], 27.0, 1.8)
            assert nominal["decks"]["tt"]["exact"] and nominal["decks"]["tt"]["liberty_sha256"] == plan["liberty_sha256"]
            assert not assert_every_bound_visited(mode, request)[0]
            assert sum(c.startswith("V") and " PWL(" in c for c in deck.splitlines()) == 39
            check_sampler_path(deck)
            for broken in (deck.replace(" raw_bit raw_valid trng_whole", " nc raw_valid trng_whole"),
                           deck + "Vfake raw_valid 0 DC 0\n"):
                try:
                    check_sampler_path(broken)
                except (AssertionError, ValueError):
                    continue
                raise AssertionError("disconnected sampler or synthetic driver passed")
            assert plan["netlist_sha256"] == digest(deck.encode())
            assert plan["flat_whole_netlist_sha256"] == digest(gzip.decompress(mr.NETLIST_GZ.read_bytes()))
            analog = mr.analog_netlist_text()
            assert plan["analog_partition_sha256"] == digest(analog.encode())
            # Exporting the sampler changes the formal pin list only.
            assert analog[analog.index("* device instance"):] in deck
            gate = gzip.decompress((HERE / "runs/20261114-gate-model-full/gate-model.cir.gz").read_bytes())
            assert plan["gate_model_sha256"] == digest(gate)
            assert gate.decode() in deck
            assert plan["digital_gate_netlist_sha256"] == digest(P.ROUTED_V.read_bytes())
            pc = plan["partition_check"]
            assert (pc["analog_transistors"], pc["digital_transistors"], pc["diode_instances"],
                    pc["total_instances"]) == (264, 25091, 1, 25356)
            manifest = json.loads((HERE / plan["gate_manifest"]).read_text())
            assert manifest["source_netlist_sha256"] == plan["digital_gate_netlist_sha256"]
            routed = {name for _, name, _ in parse_verilog(P.ROUTED_V).instances}
            primitives = {m[1] for m in re.finditer(r"^A(\S+) .* m\1$", deck, re.MULTILINE)}
            noops = {n["instance"] for n in manifest["declared_no_op_instances"]}
            assert len(routed) == manifest["routed_instances"] == 2321
            assert primitives.isdisjoint(noops) and primitives | noops == routed


def test_committed_coupled_artifacts_match_generator() -> None:
    """The committed coupled-probe request.json/plan.json must equal what the
    generator emits today (a freshly generated plan cannot detect a stale
    committed one)."""
    committed = HERE / "runs/20261121-coupled-probe/requests/coupled-probe"
    with tempfile.TemporaryDirectory(prefix="test-make-requests-coupled-") as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            assert mr.main([str(Path(tmp) / "c"), "--set", "coupled-probe"]) == 0
        fresh = Path(tmp) / "c" / "coupled-probe"
        assert json.loads((fresh / "request.json").read_text()) == json.loads((committed / "request.json").read_text())
        # plan.json is historical evidence (byte-stable): the current plan differs
        # by exactly two intentional metadata changes (issue #682).
        expected = json.loads((committed / "plan.json").read_text())
        expected["reductions"]["input_load"] = (
            "Liberty input-pin capacitance per d_genlut input; the DR-0017 "
            "boundary-load choice is settled as option 2 (#595, see boundary_load_option)")
        expected["boundary_load_option"] = mr.PVT.boundary_load_block()
        assert json.loads((fresh / "plan.json").read_text()) == expected
        # the runs measured on the fleet on 2026-11-28: request, plan and
        # deck are what the generator emits today, and the committed report
        # ran that deck
        for mode in ("coupled-probe", "coupled-full"):
            out = Path(tmp) / mode
            with contextlib.redirect_stdout(io.StringIO()):
                assert mr.main([str(out), "--set", mode]) == 0
            fresh, run = out / mode, HERE / f"runs/20261128-{mode}/requests" / mode
            for name in ("request.json", "plan.json"):
                assert json.loads((fresh / name).read_text()) == json.loads((run / name).read_text()), (mode, name)
            plan = json.loads((fresh / "plan.json").read_text())
            deck = hashlib.sha256((fresh / "netlist.cir").read_bytes()).hexdigest()
            report = json.loads((HERE / f"runs/20261128-{mode}/report.json").read_text())
            assert report["environment"]["netlist_sha256"] == plan["netlist_sha256"] == deck, mode
            assert report["environment"]["remote"]["state"] == "done"


# ---------------------------------------------------------------------------
# Issue #595: the matrix-to-deck mapping and the boundary-load option
# ---------------------------------------------------------------------------

def test_pvt_deck_table_covers_the_matrix() -> None:
    """The 12-point matrix is mapped exhaustively, each row to the nearest
    shipped deck under the declared rule (min |dV| first, tie-break |dT|),
    and every row's direction/estimate fields are self-consistent.

    klt-free: the shipped-deck list is committed in ``pvt_deck_map.py``;
    the PDK-gated disk check of the pinned sha256 values lives in
    ``sim/tests/test_gate_model.py``.
    """
    points = {(proc, t, v) for proc in PVT.MATRIX_PROCESSES for (t, v) in mr.GRID}
    assert set(PVT.matrix_points()) == points, "mapped points != tt/ss/ff x GRID"
    assert len(PVT.matrix_points()) == 12
    for key in PVT.matrix_points():
        row = PVT.DECK_TABLE[key]
        proc, temp, vdd = key
        # the named deck is a shipped deck of the same process corner
        assert row["liberty_deck"] in PVT.SHIPPED_DECKS, row["liberty_deck"]
        dproc, dtemp, dvdd = PVT.deck_corner(row["liberty_deck"])
        assert dproc == proc, (row["liberty_deck"], proc)
        # the nearest-deck rule: no shipped deck of this process is closer
        # in |dV|, or equal in |dV| and closer in |dT|
        best = min(
            (abs(PVT.deck_corner(d)[2] - vdd), abs(PVT.deck_corner(d)[1] - temp), d)
            for d in PVT.SHIPPED_DECKS if PVT.deck_corner(d)[0] == proc)
        assert (abs(dvdd - vdd), abs(dtemp - temp), row["liberty_deck"]) == best, (
            f"{key}: {row['liberty_deck']} is not the nearest shipped deck "
            f"under the |dV|-first rule ({best[2]} is)")
        # sha256 pins are full hex; directions use the declared vocabulary
        assert re.fullmatch(r"[0-9a-f]{64}", row["liberty_sha256"]), key
        assert row["delay_direction"] in ("pessimistic", "optimistic", "mixed", "none")
        assert row["power_direction"] in ("pessimistic", "optimistic", "mixed", "none")
        est, ddir = row["est_delay_error_pct"], row["delay_direction"]
        if ddir == "pessimistic":
            assert est > 0, (key, est)
        elif ddir == "optimistic":
            assert est < 0, (key, est)
        elif ddir == "none":
            assert abs(est) <= 0.1, (key, est)
        # the axes the row declares are the deck's own characterisation axes
        assert row["dT_K"] == round(dtemp - temp, 1), key
        assert row["dV_V"] == round(dvdd - vdd, 2), key
        if row["exact"]:
            assert abs(row["dT_K"]) <= 2.0 and row["dV_V"] == 0.0, key
    # the nominal point is served exactly; the 125 C point is not
    assert PVT.DECK_TABLE[("tt", 27.0, 1.8)]["exact"] is True
    assert PVT.DECK_TABLE[("tt", 125.0, 1.98)]["exact"] is False


def test_pvt_deck_map_fails_closed() -> None:
    """An unmapped point raises -- both the direct lookup and grid
    generation itself, which must leave nothing behind (the gate models and
    the deck rows of all 12 points are resolved before a single request is
    written)."""
    for bad in (("tt", 125.0, 1.62), ("tt", -40.0, 1.65), ("ls", 27.0, 1.8)):
        try:
            PVT.deck_row(*bad)
        except PVT.DeckMapError as e:
            assert "no Liberty deck mapping" in str(e), e
        else:
            raise AssertionError(f"deck_row{bad} did not fail closed")
    try:
        PVT.plan_entry(["tt"], -40.0, 1.98)
    except PVT.DeckMapError as e:
        raise AssertionError(f"a mapped point refused: {e}")
    # an unmapped grid point: patch GRID, generation must refuse with the
    # point named, before writing anything
    with tempfile.TemporaryDirectory(prefix="test-pvt-grid-") as tmp:
        real_grid = mr.GRID
        mr.GRID = list(real_grid) + [(125.0, 1.62)]
        try:
            rc, err = run_grid(Path(tmp) / "grid")
            assert isinstance(rc, SystemExit) and rc.code == 2, (rc, err)
            assert "tt/125.0C/1.62V" in err and "no Liberty deck mapping" in err, err
            assert not (Path(tmp) / "grid").exists(), "an unmapped point still wrote a request"
        finally:
            mr.GRID = real_grid


_grid_plans: list[dict] | None = None


def grid_plans() -> list[dict]:
    """``plan.json`` of the twelve grid requests, generated into a throwaway
    dir against the synthetic PDK (memoized; the #507 suite generates the same
    thing for ``request.json``, this serves the #595 / #815 plan fields)."""
    global _grid_plans
    if _grid_plans is None:
        with tempfile.TemporaryDirectory(prefix="test-grid-plans-") as tmp:
            rc, err = run_grid(Path(tmp) / "grid")
            assert rc == 0, err
            _grid_plans = [json.loads(p.read_text())
                           for p in sorted(Path(tmp).glob("grid/grid-*/plan.json"))]
    assert len(_grid_plans) == 12, [p["name"] for p in _grid_plans]
    return _grid_plans


def test_grid_plans_carry_gate_model_pvt() -> None:
    """Every grid request's plan records the boundary-load option and the
    point's own deck row, deck hash included (issue #595 AC, #815: one
    single-process row per request)."""
    seen = set()
    for plan in grid_plans():
        g = plan["gate_model_pvt"]
        blk = g["boundary_load"]
        assert blk["option"] == 2, (plan["name"], blk)
        assert "Liberty input-pin capacitance" in blk["source"]
        assert blk["record"].endswith("20261121-pvt-deck-and-boundary-load.md")
        proc = plan["corners"]["process"][0]
        assert list(g["decks"]) == [proc], (plan["name"], list(g["decks"]))
        row = g["decks"][proc]
        assert row["liberty_deck"].endswith(".lib"), (plan["name"], proc)
        assert re.fullmatch(r"[0-9a-f]{64}", row["liberty_sha256"])
        assert row["delay_direction"] in ("pessimistic", "optimistic", "mixed", "none")
        assert row["power_direction"] in ("pessimistic", "optimistic", "mixed", "none")
        # the row IS the committed table's row for that point
        t, v = plan["corners"]["temperature_c"][0], plan["corners"]["supply_v"]["Vvdd"][0]
        want = PVT.deck_row(proc, t, v)
        assert row["liberty_sha256"] == SYNTH.sha[want["liberty_deck"]], (plan["name"], proc)
        assert row["delay_direction"] == want["delay_direction"], (plan["name"], proc)
        assert (row["dT_K"], row["dV_V"], row["exact"]) == (want["dT_K"], want["dV_V"], want["exact"]), (plan["name"], proc)
        assert row["liberty_deck"] == str(SYNTH.lib / want["liberty_deck"]), (plan["name"], row["liberty_deck"])
        # the twelve plans cover the twelve (proc, T, Vdd) points of GRID x tt/ss/ff
        seen.add((proc, t, v))
    assert seen == {(p, t, v) for (t, v) in mr.GRID for p in PVT.MATRIX_PROCESSES} == set(PVT.matrix_points())


def gate_text_of(deck: str) -> str:
    """The gate model body embedded in a coupled deck: from its header to the
    ``dac_bridge`` model line inclusive (``GateModel.text()`` verbatim)."""
    i = deck.index("* gate-level model of trng_digital")
    j = deck.index("\n", deck.index(".model dac_b dac_bridge(")) + 1
    return deck[i:j]


def test_grid_emits_twelve_coupled_requests() -> None:
    """#815 AC1 / AC4: one runnable coupled deck per matrix point, offline.

    Per point: the single-process request at that (proc, T, supply) on all
    five rails; the gate model reduced from the deck ``pvt_deck_map.py``
    maps the point to (its own delays, its file name and sha256 in the deck
    and the plan); the bridges and the logic supply at the point's supply;
    the analog partition, the routed Verilog and the emitted netlist hashed;
    the coupled MATRIX measurement set; the fixed 1.8 V input-high convention
    and the sampler as the sole source of both raw signals.
    """
    cycles, _ = P.build_program()
    stop = P.t_stop_ns(cycles)
    expected_names = sorted(mr.grid_name(p, t, v) for (t, v) in mr.GRID for p in PVT.MATRIX_PROCESSES)
    with tempfile.TemporaryDirectory(prefix="test-grid-ids-") as tmp:
        # eight distinct decks serve the twelve points: parsed once each
        with mock.patch.object(mr, "load_liberty_cells", wraps=mr.load_liberty_cells) as spy:
            rc, err = run_grid(Path(tmp) / "grid")
        assert rc == 0, err
        assert spy.call_count == len(SYNTH.sha) == 8, spy.call_count
        dirs = sorted(p.name for p in (Path(tmp) / "grid").iterdir())
        assert dirs == expected_names and len(dirs) == 12
        decks_seen = set()
        for name in dirs:
            base = Path(tmp) / "grid" / name
            plan = json.loads((base / "plan.json").read_text())
            request = json.loads((base / "request.json").read_text())
            deck = (base / "netlist.cir").read_text()
            proc = request["corners"]["process"]
            temp = request["corners"]["temperature_c"][0]
            supply = request["corners"]["supply_v"]["Vvdd"][0]
            row = PVT.deck_row(proc[0], temp, supply)
            assert name == plan["name"] == mr.grid_name(proc[0], temp, supply)
            # -- identity: one process, one point, all five rails at its supply
            assert proc == [proc[0]] and request["corners"] == plan["corners"]
            assert request["corners"]["supply_v"] == {f"V{r}": [supply] for r in mr.RAILS}
            assert request["backend"] == "batch" and tran_stop_ns(request) == stop == 7870
            assert plan["program"] == {"t0_ns": P.T0_NS, "ts_ns": P.TS_NS, "cycles": 75, "t_stop_ns": stop}
            assert plan["vih_fixed"] == 1.8 and plan["raw_source"] == "analog_sampler"
            assert plan["provenance"] == P.PROVENANCE
            # -- the deck the point maps to: file, sha256 and delays
            deck_file = row["liberty_deck"]
            decks_seen.add(deck_file)
            assert Path(plan["liberty_deck"]).name == deck_file
            assert plan["liberty_deck"] == str(SYNTH.lib / deck_file), plan["liberty_deck"]
            assert plan["liberty_sha256"] == SYNTH.sha[deck_file]
            assert plan["gate_model_pvt"]["decks"][proc[0]]["liberty_deck"] == plan["liberty_deck"]
            assert plan["gate_model_pvt"]["boundary_load"] == PVT.boundary_load_block()
            gate = gate_text_of(deck)
            assert f"* Liberty deck: {plan['liberty_deck']}" in gate
            assert f"*   sha256 {plan['liberty_sha256']}" in gate
            assert sha256_text(gate) == plan["gate_model_sha256"]
            first_genlut = re.search(r"^\.model m\S+ d_genlut\(.*$", gate, re.M).group(0)
            scale = synth_factor(row["liberty_corner"])
            expected_rise = _eng(SYNTH_COMB_DELAY_NS[0] * 1e-9 * scale)
            assert f"rise_delay=[{expected_rise}]" in first_genlut, (name, first_genlut)
            # -- rails: bridges and the logic supply move with the point
            assert (f".model adc_b adc_bridge(in_low={_eng(0.45 * supply)} in_high={_eng(0.55 * supply)})"
                    in gate), name
            assert (f".model dac_b dac_bridge(out_low=0 out_high={_eng(supply)} out_undef={_eng(supply / 2)}"
                    in gate), name
            assert f"\nVvdd vdd 0 dc {supply}\n" in gate, name
            assert plan["reductions"]["supply_v"] == supply
            assert plan["reductions"]["dac_bridge_out_high_v"] == supply
            # -- what the plan hashes: the three partition hashes and the emitted deck
            assert plan["netlist_sha256"] == sha256_text(deck)
            flat = gzip.decompress(mr.NETLIST_GZ.read_bytes()).decode()
            assert plan["flat_whole_netlist_sha256"] == sha256_text(flat)
            assert plan["analog_partition_sha256"] == sha256_text(mr.analog_netlist_text())
            assert plan["digital_gate_netlist_sha256"] == sha256_text(P.ROUTED_V.read_text())
            assert plan["digital_gate_netlist_sha256"] == plan["routed_netlist_sha256"]
            pc = plan["partition_check"]
            assert (pc["analog_transistors"], pc["digital_transistors"], pc["total_instances"]) == (264, 25091, 25356)
            # -- the coupled matrix measurement set, and nothing else
            meas, save = P.coupled_matrix_measurements(cycles, supply)
            assert request["measurements"] == meas and plan["measurement_count"] == len(meas) == 917
            assert "\n".join(f".save {' '.join(save[i:i + 8])}" for i in range(0, len(save), 8)) in deck
            cross = next(m for m in meas if m["name"] == "t_out_valid_first")["spice"]
            level = float(cross.split("v(out_valid)=")[1].split()[0])
            assert supply / 2 < level < supply, (name, cross)   # inside the dac swing, never an X
            assert not assert_every_bound_visited(name, request)[0]
            # -- the sampler is the sole source of both raw signals, inputs at the fixed VIH
            check_sampler_path(deck)
            assert sum(c.startswith("V") and " PWL(" in c for c in deck.splitlines()) == 39
            assert "\n".join(P.input_cards(cycles, len(cycles), P.VIH, coupled=True)) in deck
            assert f"Vclk clk 0 PULSE(0 {P.VIH} {P.T0_NS:.0f}n" in deck
            assert f"Vrstn rst_n 0 PULSE(0 {P.VIH}" in deck
    assert decks_seen == set(SYNTH.sha)   # the 8 mapped decks, each used


def test_grid_fails_closed_without_libs_ref() -> None:
    """#815: the grid needs the PDK's decks. With no ``--libs-ref`` and no
    resolvable ``klt pdk find`` it refuses, naming the flag, and writes
    nothing -- never the nominal model, never the flat deck. A ``--libs-ref``
    that is not a ``libs.ref`` refuses too, and so does one whose decks do
    not hash to the pins (the PDK-version guard survives the flag)."""
    with tempfile.TemporaryDirectory(prefix="test-grid-nopdk-") as tmp:
        out = Path(tmp) / "grid"
        saved = mr._KLT_LIBS_REF
        with mock.patch.object(mr, "libs_ref", side_effect=OSError("klt: not found")):
            mr._KLT_LIBS_REF = mr._UNSET
            try:
                rc, err = run_grid(out, libs_ref=False)
            finally:
                mr._KLT_LIBS_REF = saved
        assert isinstance(rc, SystemExit) and rc.code == 2, (rc, err)
        assert "--libs-ref" in err and "never falls back" in err, err
        assert not out.exists()
        rc, err = run_grid(Path(tmp) / "g2", "--libs-ref", str(Path(tmp) / "not-a-pdk"))
        assert isinstance(rc, SystemExit) and "is not a sky130A libs.ref directory" in err, err
        assert not (Path(tmp) / "g2").exists()
        rc, err = run_grid(Path(tmp) / "g3", pins=False)
        assert isinstance(rc, SystemExit) and "on-disk sha256" in err and "!= pinned" in err, err
        assert not (Path(tmp) / "g3").exists()
        # the committed pins are intact once a run has finished under the synthetic ones
        assert all(PVT.DECK_TABLE[k]["liberty_sha256"] == r["liberty_sha256"]
                   for k, r in PVT.DECK_TABLE.items())


def real_libs_ref() -> Path | None:
    try:
        return mr.resolve_libs_ref(None)
    except Exception:
        return None


REAL_LIBS_REF = real_libs_ref()


@unittest.skipUnless(REAL_LIBS_REF is not None,
                     "needs the pinned sky130A PDK install (klt pdk find)")
class TestAgainstRealPdk(unittest.TestCase):
    """The twelve coupled requests against the real Liberty decks (#815 test
    plan, PDK-gated): every point names its pinned deck on disk, and the
    nominal point's gate model IS the committed, measured one."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="test-grid-real-")
        out = Path(cls.tmp.name) / "grid"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mr.main(["--set", "grid", str(out)])
        assert rc == 0, rc
        cls.points = {}
        for p in sorted(out.glob("grid-*/plan.json")):
            plan = json.loads(p.read_text())
            corners = plan["corners"]
            key = (corners["process"][0], corners["temperature_c"][0], corners["supply_v"]["Vvdd"][0])
            cls.points[key] = (plan, p.with_name("netlist.cir").read_text())
        assert len(cls.points) == 12

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_point_names_its_pinned_deck_on_disk(self):
        checked = PVT.verify_against_disk(REAL_LIBS_REF)
        self.assertEqual(len(checked), 12)
        decks = set()
        for (proc, temp, supply), (plan, _deck) in self.points.items():
            row = PVT.deck_row(proc, temp, supply)
            self.assertEqual(Path(plan["liberty_deck"]).resolve(),
                             (REAL_LIBS_REF / PVT.LIB_SUBDIR / row["liberty_deck"]).resolve())
            self.assertEqual(sha256_file_text(Path(plan["liberty_deck"])), row["liberty_sha256"])
            self.assertEqual(plan["liberty_sha256"], row["liberty_sha256"])
            decks.add(row["liberty_deck"])
        self.assertEqual(len(decks), 8)

    def test_nominal_point_reproduces_the_measured_model(self):
        # the per-point builder at tt / 27 C / 1.8 V is the generator's
        # emitter at the committed run's own operating point: byte for byte
        # the model the fleet measured (records/20261128-coupled-rate.md)
        plan, deck = self.points[("tt", 27.0, 1.8)]
        committed = gzip.decompress((HERE / "runs/20261114-gate-model-full/gate-model.cir.gz").read_bytes())
        manifest = json.loads((HERE / "corners/gate-model-full/gate-model.manifest.json").read_text())
        recorded_deck = Path(manifest["liberty_deck"])
        live = gate_text_of(deck)

        def strip(text: str, path: Path) -> str:
            return text.replace(str(path), "<deck>")   # the install path is host-specific

        self.assertEqual(strip(live, Path(plan["liberty_deck"])), strip(committed.decode(), recorded_deck))
        if Path(plan["liberty_deck"]) == recorded_deck:
            self.assertEqual(live, committed.decode())
            measured = json.loads((HERE / "runs/20261128-coupled-full/requests/coupled-full/plan.json").read_text())
            self.assertEqual(plan["gate_model_sha256"], measured["gate_model_sha256"])

    def test_non_nominal_points_re_corner_deck_and_rails(self):
        for (proc, temp, supply), deck_file in (
                (("ss", -40.0, 1.62), "sky130_fd_sc_hd__ss_n40C_1v60.lib"),
                (("ss", 125.0, 1.98), "sky130_fd_sc_hd__ss_n40C_1v76.lib"),
                (("ff", 125.0, 1.98), "sky130_fd_sc_hd__ff_100C_1v95.lib")):
            plan, deck = self.points[(proc, temp, supply)]
            self.assertEqual(Path(plan["liberty_deck"]).name, deck_file)
            self.assertIn(f".model dac_b dac_bridge(out_low=0 out_high={_eng(supply)}", deck)
            self.assertIn(f".model adc_b adc_bridge(in_low={_eng(0.45 * supply)} "
                          f"in_high={_eng(0.55 * supply)})", deck)

    def test_slow_corner_measurement_is_the_grids_request_for_that_point(self):
        # #814: the request the fleet measured at ss / -40 C / 1.62 V is
        # `--set grid`'s request for that point with only its two timeouts
        # exchanged for the one-unit measurement pair, so the runtime it
        # measured is the grid unit's (records/20261128-slow-corner-runtime.md)
        run = HERE / "runs/20261128-slow-corner-ss-m40C-1.62V/requests/grid-ss-m40C-1.62V"
        measured = json.loads((run / "request.json").read_text())
        measured_plan = json.loads((run / "plan.json").read_text())
        grid = json.loads((Path(self.tmp.name) / "grid/grid-ss-m40C-1.62V/request.json").read_text())
        self.assertEqual((measured["options"]["timeout_s"], measured["batch"]["poll_timeout_s"]),
                         (3360, 3480))
        self.assertEqual((grid["options"]["timeout_s"], grid["batch"]["poll_timeout_s"]),
                         (mr.GRID_TIMEOUT_S, mr.GRID_POLL_TIMEOUT_S))
        for request in (measured, grid):
            del request["options"]["timeout_s"]
            del request["batch"]["poll_timeout_s"]
        self.assertEqual(grid, measured)
        # the deck embeds the Liberty deck's install path: where that path is
        # the recorded one, the measured deck IS the grid's deck, by sha256
        plan, _deck = self.points[("ss", -40.0, 1.62)]
        if Path(plan["liberty_deck"]) == Path(measured_plan["liberty_deck"]):
            self.assertEqual(plan["netlist_sha256"], measured_plan["netlist_sha256"])

    def test_explicit_libs_ref_matches_the_resolved_install(self):
        out = Path(self.tmp.name) / "explicit"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mr.main(["--set", "grid", str(out), "--libs-ref", str(REAL_LIBS_REF)])
        self.assertEqual(rc, 0)
        by_name = {plan["name"]: plan for plan, _ in self.points.values()}
        for p in sorted(out.glob("grid-*/plan.json")):
            self.assertEqual(json.loads(p.read_text()), by_name[p.parent.name], p.parent.name)


def sha256_file_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    test_coupled_request()
    test_committed_coupled_artifacts_match_generator()
    test_standalone_waveform_bytes()
    test_capture_points_sit_at_a_rail()
    test_change_emits_hold_then_edge()
    test_breakpoint_hygiene()
    test_grid_timeouts_from_the_measured_coupled_rate()
    test_grid_timeouts_refuse_what_the_ceiling_cannot_hold()
    test_generated_measurements_within_tran_stop()
    test_committed_request_ledger()
    test_startup_probe_timeouts_pinned()
    test_final_cycle_read_emits_no_rdata_measurement()
    test_last_cycle_without_read_changes_nothing()
    test_shared_collector_clips_and_refuses_repeated_names()
    test_bound_scan_flags_non_ns_units()
    test_per_card_guard_flags_unvisited_bound()
    test_pvt_deck_table_covers_the_matrix()
    test_pvt_deck_map_fails_closed()
    test_grid_plans_carry_gate_model_pvt()
    test_grid_emits_twelve_coupled_requests()
    test_grid_fails_closed_without_libs_ref()
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(TestAgainstRealPdk))
    if not result.wasSuccessful():
        return 1
    print("test_make_requests OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
