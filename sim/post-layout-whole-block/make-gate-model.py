#!/usr/bin/env python3
"""Generate the ngspice gate-level model of the digital half (issue #486).

DR-0017 (Accepted, #404) chose option (b) -- analog chain at transistor level,
digital section at gate level behind a defined boundary -- and left *how* the
gate-level half is realised in ngspice to this follow-up, "to choose and to
evidence". **This script is the choice: a timed-delay XSPICE netlist.**

Every ``sky130_fd_sc_hd`` instance of ``layout/trng_digital/trng_digital.routed.v``
becomes one XSPICE event-driven primitive (``d_genlut`` for a combinational
cell, ``d_dff`` for a flop) carrying scalar rise/fall delays reduced from one
Liberty deck, with ``adc_bridge`` / ``dac_bridge`` cards at the boundary. The
emitted body is a *circuit body only* -- no ``.control``, no ``.end``, no
``.lib``/``.temp``/``.tran`` -- which is exactly the netlist convention
``klt sim`` requires (``make-requests.py`` docstring), so no code-model
loading or ``.control`` injection has to be smuggled past the runner.

Why this realisation and not event-driven co-simulation (``d_cosim``): a
``d_*``-plus-bridge netlist needs no per-netlist, per-corner shared object and
no second delay source, and ngspice's own ``digital.cm`` already ships every
primitive it uses (verified on both installs on the dispatch host, and
ngspice-46 is the build the fleet runner used for
``records/20261105-analog-chain-probe.md``). ``d_cosim`` stays the documented
fallback if a ``d_genlut`` width or fan-in limit ever bites; this netlist's
widest cell is 6 inputs (``a222oi_1``), well inside what was measured to work.

Declared reductions (each one a *disclosed deviation*, recorded with its
source -- none of them is silently taken):

1. **NLDM table -> scalar delay.** Liberty ``cell_rise``/``cell_fall`` are 2-D
   tables over (``input_net_transition``, ``total_output_net_capacitance``);
   ``d_genlut``/``d_dff`` take scalars. Each output pin's pair is a **bilinear
   interpolation** of its tables at the operating point
   (``--slew-ns``, C_load), **clamped** to the table's own index range (never
   extrapolated), and then the **maximum over every delay arc** reaching that
   pin -- the conservative STA convention, so a functional match is not an
   artefact of an optimistic delay. Index ``[0][0]`` is *not* taken.
2. **C_load is derived, not declared.** For each driven net it is the sum of
   the Liberty input-pin ``capacitance`` of every receiver on that net
   (``diode_2``'s antenna tie included -- see 5), plus ``--port-load-pf``
   (default 0.0) when the net also reaches a module output port, which is the
   whole-block deck's standing "outputs are unloaded" assumption
   (``README.md`` -> Assumptions -> Loading).
3. **Input slew operating point.** ``--slew-ns`` defaults to 0.1 ns, the
   rise/fall time every testbench source in this deck family already uses
   (``make-requests.py``'s ``PULSE(... 100p 100p ...)`` cards). It is a fixed
   single-pass operating point, not an STA slew propagation.
4. **Bridge levels move with the corner supply.** ``adc_bridge``'s band is
   ``(0.5 -+ BRIDGE_BAND_FRAC) * --supply-v``, centred on the chosen Liberty
   deck's own ``input_threshold_pct_rise``/``_fall`` (read from the deck and
   asserted to be 50, not assumed), so the bridged event time coincides with
   the point at which that deck measures its delays. ``dac_bridge`` drives
   ``vss``..``--supply-v``. DR-0017 fixes that thresholds move with ``vdd``
   rather than sitting in a fixed 1.8 V domain, which this honours.
5. **``diode_2`` is a declared no-op, not a silent drop.** The antenna tie has
   no Liberty ``function`` and no output pin: it contributes its input-pin
   ``capacitance`` to its net's C_load (see 2) and no primitive. It is counted
   in the manifest as ``declared_no_op_instances`` so the instance
   correspondence to the routed netlist stays exact.
6. **Active-low clear/preset get an explicit inverter.** XSPICE ``d_dff``'s
   ``set``/``reset`` were measured active-**high** on this install, while
   ``dfrtp``/``dfstp`` carry ``clear : "!RESET_B"`` / ``preset : "!SET_B"``.
   One zero-delay ``d_inverter`` per *distinct* driving net is emitted and
   shared, counted separately as ``polarity_inverters``.
7. **One scalar rise/fall pair per flop output.** ``d_dff``'s per-input
   ``clk_delay``/``set_delay``/``reset_delay`` are at XSPICE's own 1 ps floor
   (it refuses 0), so the asynchronous
   clear/preset arc is not modelled separately from the CLK->Q arc; the single
   pair is the max over both (see 1). ``ic=0``: the real cells power up
   undefined and the deck's reset (``rst_n`` low until 300 ns) establishes the
   state every comparison relies on.
8. **``input_load`` is the Liberty input-pin capacitance, and is NOT
   DR-0017's boundary-load choice.** The cards need *some* ``input_load`` to
   elaborate at all; using the real per-pin capacitance is strictly better
   than inventing a default. Choosing between DR-0017 option 1 (keep the first
   receiving cells at transistor level) and option 2 (model the load as
   Liberty input-pin capacitance at the matching corner) is the rest of #431
   and is **not** settled here.
9. **``vdd``/``vss`` are deck nets, but at gate level the supply enters only
   through 4 and through *which Liberty deck* is chosen.** ``Vvdd``/``Vvss``
   cards are emitted so the two supply nets exist by name (the boundary AC1
   names), but a ``corners.supply_v`` axis alone does **not** re-corner the
   digital half -- the Liberty deck has to move with the point. Recorded,
   because the rest of #431 needs it.

**Fail-closed.** Nothing is written unless every instance maps: an unknown
cell, an output pin with neither a ``function`` nor an ``ff`` group, an
unparseable function, a netlist pin absent from the deck, a missing delay arc,
a multiply-driven or undriven net, or a flop whose clock/next-state is not a
bare pin all raise and exit non-zero with no output file.

Usage::

    make-gate-model.py OUTDIR [--liberty PATH] [--supply-v 1.8] [--cycles 6]

writes, under OUTDIR:

    gate-model.cir             the gate-level model body (bridges + primitives)
    gate-model.manifest.json   counts, port list, boundary classification,
                               per-reduction parameters, input hashes
    netlist.cir                gate-model.cir + the directed program's stimulus
                               and .save list -- the runnable klt sim body
    request.json               the klt sim request (one corner, local backend)
    plan.json                  input hashes / provenance, make-requests.py style

Nothing here simulates anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import program as P  # noqa: E402

ROUTED_V = REPO / "layout" / "trng_digital" / "trng_digital.routed.v"
CELL_PREFIX = "sky130_fd_sc_hd__"

#: half-width of the adc_bridge band, as a fraction of the supply. The band is
#: centred on the Liberty deck's own 50 % delay-measurement threshold; this
#: fraction is the generator's declared choice (a narrow band, so the bridged
#: event time coincides with the deck's delay reference point).
BRIDGE_BAND_FRAC = 0.05
#: Liberty threshold the band must be centred on; asserted against the deck.
EXPECTED_THRESHOLD_PCT = 50.0
#: input slew operating point (ns) -- see reduction 3 in the module docstring
DEFAULT_SLEW_NS = 0.1
#: output-port load (pF) -- the deck's "outputs are unloaded" assumption
DEFAULT_PORT_LOAD_PF = 0.0
#: bridge transition times (s) for dac_bridge; 100 ps, the deck's own PULSE edge
DAC_EDGE_S = 100e-12
#: XSPICE refuses any delay parameter below 1 ps ("Value 0 below limit 1e-12 for
#: parameter 'clk_delay'"), so that floor -- not 0 -- is the generator's "no
#: delay". It is three orders of magnitude below the smallest cell delay in this
#: deck (the fastest cell_rise here is ~60 ps), so it is not a modelling choice.
MIN_DELAY_S = 1e-12
#: PWL edge width (ns) for a stimulus change: the same 100 ps every PULSE card
#: in this deck family uses, and the slew operating point the Liberty tables are
#: reduced at. Without an explicit edge a PWL source ramps linearly across the
#: whole interval between change points (see stimulus_cards.points).
PWL_EDGE_NS = 0.1
#: digital input high level (V). make-requests.py:75 fixes VIH = 1.8 V at every
#: corner and discloses it as a repo convention, not a published PDK figure.
VIH = 1.8
#: ngspice .tran max timestep -- the SAME value make-requests.py uses (TMAX), so
#: the measured rate is comparable with the analog-chain probe's.
TMAX = "20p"
#: PDK corner library klt sim resolves for the analog models (unused by the
#: event-driven primitives, but the request contract requires a models block)
LIB = "libs.tech/combined/sky130.lib.spice"
PDK = "sky130A"
#: klt sim's request schema allows only 'schematic' / 'extracted' here. A
#: gate-level netlist generated from a routed structural netlist plus a Liberty
#: deck is neither; 'extracted' is forced as the nearer label and the deviation
#: is recorded. Tool gap filed upstream as klayout-tools#5638.
NETLIST_SOURCE = "extracted"

#: raw_bit stimulus for the standalone digital run. In a coupled run raw_bit
#: comes across the boundary from the analog sampler; standalone it has to be
#: driven, so this committed, arbitrary-but-fixed pattern is used and the SAME
#: bits are fed to the normative model for the comparison. It is stimulus, not
#: entropy evidence.
RAW_BIT_PATTERN = "1001011100011110010101100011101011010010111001000110111101000011"


# --------------------------------------------------------------------------
# Verilog (structural, post-route) parsing
# --------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_MODULE_RE = re.compile(r"\bmodule\s+(\w+)\s*\((.*?)\)\s*;", re.S)
_PORTDIR_RE = re.compile(r"^\s*(input|output|inout)\s+(?:\[(\d+)\s*:\s*(\d+)\]\s+)?(\w+)\s*;",
                         re.M)
_INST_RE = re.compile(r"\b(" + CELL_PREFIX + r"[A-Za-z0-9_]+)\s+(\S+)\s*\((.*?)\)\s*;", re.S)
_CONN_RE = re.compile(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)")
_ASSIGN_RE = re.compile(r"\bassign\s+([^=;]+?)\s*=\s*([^;]+?)\s*;")


def scrub(name: str) -> str:
    """``name[i]`` -> ``name_i_`` and ``$`` -> ``z``: make-requests.py's convention.

    Kept byte-identical to ``make-requests.py:_scrub`` so a net that is a port
    of the whole-block extract carries the same spelling in both decks and the
    same ``.meas`` cards address it. Use :func:`netname` for netlist-body
    tokens; this one exists so the agreement can be asserted in the tests.
    """
    return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]", r"\1_\2_", name.replace("$", "z"))


def netname(token: str) -> str:
    """A routed-netlist net/instance token as a flat, bracket-free SPICE name.

    Agrees with :func:`scrub` (and so with ``make-requests.py:_scrub``) on
    every plain ``name[i]`` token, and additionally handles the two forms
    ``_scrub`` does not: Yosys **escaped identifiers** (``\raw_mem[3] [30]``,
    where the escape ends at the space and ``[30]`` is a bit-select on it) and
    the resulting multi-dimensional names (``raw_mem[3][30]`` ->
    ``raw_mem_3__30_``). 576 connections in the committed netlist use the
    escaped form, so this is load-bearing, not defensive.
    """
    t = token.strip()
    if t.startswith("\\"):
        t = t[1:]
    t = re.sub(r"\s+", "", t)
    return t.replace("$", "z").replace("[", "_").replace("]", "_")


class Design:
    """The parsed routed netlist: ports, instances, assign aliases."""

    def __init__(self, module: str, ports: list[tuple[str, str, int | None, int | None]],
                 instances: list[tuple[str, str, dict[str, str]]],
                 aliases: dict[str, str]):
        self.module = module
        #: [(name, direction, msb, lsb)] in module-header order
        self.ports = ports
        #: [(cell_type, instance_name, {pin: raw_net})]
        self.instances = instances
        #: {lhs_net: rhs_net} from ``assign`` statements
        self.aliases = aliases

    # -- port expansion ----------------------------------------------------
    def port_bits(self, direction: str | None = None) -> list[str]:
        """Scrubbed, bit-expanded port names, in declaration order."""
        out: list[str] = []
        for name, d, msb, lsb in self.ports:
            if direction is not None and d != direction:
                continue
            if msb is None:
                out.append(name)
            else:
                step = 1 if lsb <= msb else -1
                for i in range(msb, lsb - step, -step):
                    out.append(netname(f"{name}[{i}]"))
        return out

    def canon(self, net: str) -> str:
        """Follow ``assign`` aliases to the net that is actually driven."""
        seen = set()
        cur = net
        while cur in self.aliases:
            if cur in seen:
                raise GateModelError(f"assign alias cycle at net {net!r}")
            seen.add(cur)
            cur = self.aliases[cur]
        return cur

    def cell_histogram(self) -> dict[str, int]:
        h: dict[str, int] = {}
        for cell, _, _ in self.instances:
            h[cell] = h.get(cell, 0) + 1
        return h


class GateModelError(RuntimeError):
    """Any condition on which the generator must fail closed."""


def parse_verilog(path: Path) -> Design:
    text = _COMMENT_RE.sub(" ", path.read_text())
    m = _MODULE_RE.search(text)
    if not m:
        raise GateModelError(f"{path}: no module header found")
    module = m.group(1)
    header_order = [t.strip() for t in m.group(2).replace("\n", " ").split(",") if t.strip()]
    decls: dict[str, tuple[str, int | None, int | None]] = {}
    for d, msb, lsb, name in _PORTDIR_RE.findall(text):
        decls[name] = (d, int(msb) if msb else None, int(lsb) if lsb else None)
    missing = [p for p in header_order if p not in decls]
    if missing:
        raise GateModelError(f"{path}: ports with no direction declaration: {missing}")
    ports = [(p, *decls[p]) for p in header_order]

    instances: list[tuple[str, str, dict[str, str]]] = []
    for cell, inst, conns in _INST_RE.findall(text):
        pins: dict[str, str] = {}
        for pin, net in _CONN_RE.findall(conns):
            flat = netname(net)
            if not flat:
                # `.Y()` -- an explicitly unconnected pin. The router writes
                # CTS dummy loads either way (omitting .Y entirely in the
                # committed netlist), and both forms must mean the same thing:
                # the pin is not connected, so it gets no net at all.
                continue
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", flat):
                raise GateModelError(
                    f"{path}: instance {inst} ({cell}) pin .{pin} connects to "
                    f"{net.strip()!r}, which is not a usable SPICE net name")
            pins[pin] = flat
        if not pins:
            raise GateModelError(f"{path}: instance {inst} of {cell} has no connections")
        instances.append((cell, netname(inst), pins))
    if not instances:
        raise GateModelError(f"{path}: no {CELL_PREFIX}* instances found")

    # collision guard (make-netlist.py has the analogous one for its own
    # token transforms): netname() must stay injective over the netlist's
    # distinct raw tokens, or two different nets would merge silently.
    raw_tokens: dict[str, str] = {}
    for cell, inst, conns in _INST_RE.findall(text):
        for _, net in _CONN_RE.findall(conns):
            flat = netname(net)
            if not flat:
                continue
            prev = raw_tokens.setdefault(flat, net.strip())
            if prev != net.strip():
                raise GateModelError(
                    f"{path}: net name collision -- {prev!r} and {net.strip()!r} "
                    f"both flatten to {flat!r}")

    aliases: dict[str, str] = {}
    for lhs, rhs in _ASSIGN_RE.findall(text):
        l, r = netname(lhs), netname(rhs)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", r):
            raise GateModelError(f"{path}: unsupported assign right-hand side {rhs!r}")
        if l in aliases:
            raise GateModelError(f"{path}: net {l!r} assigned twice")
        aliases[l] = r
    return Design(module, ports, instances, aliases)


# --------------------------------------------------------------------------
# Liberty parsing (targeted: only the cells the netlist actually uses)
# --------------------------------------------------------------------------

_GROUP_RE = re.compile(r"^(\w+)\s*\((.*)\)\s*\{$")
_ATTR_RE = re.compile(r"^(\w+)\s*:\s*(.*?)\s*;$")
_CALL_RE = re.compile(r"^(\w+)\s*\((.*)\)\s*;$")
#: delay arcs this generator reduces; constraint arcs (setup/hold/recovery/
#: removal/min_pulse_width) carry no cell_rise/cell_fall and are ignored.
DELAY_ARC_TYPES = {"combinational", "combinational_rise", "combinational_fall",
                   "rising_edge", "falling_edge", "clear", "preset",
                   "three_state_enable", "three_state_disable"}


def _logical_lines(text: str):
    """Liberty logical lines: backslash continuations joined, blanks dropped."""
    buf = ""
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("//"):
            continue
        if s.endswith("\\"):
            buf += s[:-1]
            continue
        yield buf + s
        buf = ""
    if buf:
        yield buf


class LibGroup:
    """A Liberty group: its ``(args)``, scalar attributes and child groups."""

    __slots__ = ("kind", "args", "attrs", "calls", "groups")

    def __init__(self, kind: str, args: str):
        self.kind = kind
        self.args = [a.strip().strip('"') for a in args.split(",")] if args.strip() else []
        self.attrs: dict[str, str] = {}
        self.calls: dict[str, str] = {}
        self.groups: list[LibGroup] = []

    def first(self, kind: str, arg0: str | None = None) -> "LibGroup | None":
        for g in self.groups:
            if g.kind == kind and (arg0 is None or (g.args and g.args[0] == arg0)):
                return g
        return None

    def all(self, kind: str) -> list["LibGroup"]:
        return [g for g in self.groups if g.kind == kind]


def parse_liberty_group(lines: list[str]) -> LibGroup:
    """Parse one balanced ``kind (args) { ... }`` from ``lines[0]``."""
    g = _GROUP_RE.match(lines[0])
    if not g:
        raise GateModelError(f"not a Liberty group opener: {lines[0]!r}")
    root = LibGroup(g.group(1), g.group(2))
    stack = [root]
    for ln in lines[1:]:
        if ln == "}" or ln.startswith("}"):
            stack.pop()
            if not stack:
                break
            continue
        m = _GROUP_RE.match(ln)
        if m:
            child = LibGroup(m.group(1), m.group(2))
            stack[-1].groups.append(child)
            stack.append(child)
            continue
        m = _ATTR_RE.match(ln)
        if m:
            stack[-1].attrs[m.group(1)] = m.group(2).strip().strip('"')
            continue
        m = _CALL_RE.match(ln)
        if m:
            stack[-1].calls[m.group(1)] = m.group(2)
            continue
        # anything else (e.g. a bare `define(...)` variant) is not needed here
    return root


def extract_cell_blocks(lib_path: Path, wanted: set[str]) -> tuple[dict[str, LibGroup], dict[str, str]]:
    """Return ({cell_name: parsed group}, library-level attributes).

    Streams the deck (13 MB for ``tt_025C_1v80``) and parses only the wanted
    ``cell`` blocks, so the whole library is never materialised as an AST.
    """
    header: dict[str, str] = {}
    blocks: dict[str, LibGroup] = {}
    collecting: list[str] | None = None
    depth = 0
    name = ""
    in_library = False
    for ln in _logical_lines(lib_path.read_text()):
        if collecting is None:
            g = _GROUP_RE.match(ln)
            if g and g.group(1) == "cell":
                # the library-level attribute block ends at the first cell
                in_library = False
                cand = g.group(2).strip().strip('"')
                if cand in wanted:
                    collecting = [ln]
                    depth = 1
                    name = cand
                continue
            if g and g.group(1) == "library":
                in_library = True
                continue
            if in_library:
                a = _ATTR_RE.match(ln)
                if a:
                    header.setdefault(a.group(1), a.group(2).strip().strip('"'))
                c = _CALL_RE.match(ln)
                if c:
                    header.setdefault(c.group(1), c.group(2))
            continue
        collecting.append(ln)
        if _GROUP_RE.match(ln):
            depth += 1          # a group-opener line opens exactly one group
        depth -= ln.count("}")
        if depth <= 0:
            blocks[name] = parse_liberty_group(collecting)
            collecting = None
    if collecting is not None:
        raise GateModelError(f"{lib_path}: unterminated cell block for {name!r}")
    return blocks, header


# --------------------------------------------------------------------------
# Liberty boolean function -> truth table
# --------------------------------------------------------------------------

_TOK_RE = re.compile(r"\s*(?:(?P<id>[A-Za-z_][A-Za-z0-9_]*)|(?P<num>[01])|(?P<op>[!~&*|+^()']))")


def _tokenize(expr: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    i = 0
    while i < len(expr):
        if expr[i].isspace():
            i += 1
            continue
        m = _TOK_RE.match(expr, i)
        if not m or m.end() == i:
            raise GateModelError(f"unparseable Liberty function at {expr[i:]!r} in {expr!r}")
        kind = "id" if m.group("id") else ("num" if m.group("num") else "op")
        toks.append((kind, m.group(kind)))
        i = m.end()
    return toks


class _FuncParser:
    """Recursive-descent parser for a Liberty ``function`` expression.

    Grammar (precedence low to high)::

        or    := xor (('|' | '+') xor)*
        xor   := and ('^' and)*
        and   := not (('&' | '*')? not)*       # juxtaposition is AND
        not   := ('!' | '~') not | atom ("'")*
        atom  := ident | '0' | '1' | '(' or ')'
    """

    def __init__(self, toks: list[tuple[str, str]], pins: set[str], expr: str):
        self.toks = toks
        self.i = 0
        self.pins = pins
        self.expr = expr

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def parse(self):
        node = self.p_or()
        if self.i != len(self.toks):
            raise GateModelError(f"trailing tokens in Liberty function {self.expr!r}")
        return node

    def p_or(self):
        node = self.p_xor()
        while self.peek() in (("op", "|"), ("op", "+")):
            self.i += 1
            node = ("or", node, self.p_xor())
        return node

    def p_xor(self):
        node = self.p_and()
        while self.peek() == ("op", "^"):
            self.i += 1
            node = ("xor", node, self.p_and())
        return node

    def p_and(self):
        node = self.p_not()
        while True:
            k, v = self.peek()
            if (k, v) in (("op", "&"), ("op", "*")):
                self.i += 1
                node = ("and", node, self.p_not())
            elif k == "id" or k == "num" or (k, v) in (("op", "("), ("op", "!"), ("op", "~")):
                node = ("and", node, self.p_not())  # juxtaposition
            else:
                return node

    def p_not(self):
        k, v = self.peek()
        if (k, v) in (("op", "!"), ("op", "~")):
            self.i += 1
            return ("not", self.p_not())
        node = self.p_atom()
        while self.peek() == ("op", "'"):
            self.i += 1
            node = ("not", node)
        return node

    def p_atom(self):
        k, v = self.peek()
        if k == "id":
            if v not in self.pins:
                raise GateModelError(
                    f"Liberty function {self.expr!r} references {v!r}, not an input pin")
            self.i += 1
            return ("pin", v)
        if k == "num":
            self.i += 1
            return ("const", int(v))
        if (k, v) == ("op", "("):
            self.i += 1
            node = self.p_or()
            if self.peek() != ("op", ")"):
                raise GateModelError(f"unbalanced parentheses in {self.expr!r}")
            self.i += 1
            return node
        raise GateModelError(f"unexpected token {v!r} in Liberty function {self.expr!r}")


def compile_function(expr: str, pins: set[str]):
    """Return ``f(bits: dict[pin, int]) -> int`` for a Liberty function."""
    ast = _FuncParser(_tokenize(expr), pins, expr).parse()

    def ev(node, bits):
        op = node[0]
        if op == "pin":
            return bits[node[1]]
        if op == "const":
            return node[1]
        if op == "not":
            return 1 - ev(node[1], bits)
        a = ev(node[1], bits)
        b = ev(node[2], bits)
        if op == "and":
            return a & b
        if op == "or":
            return a | b
        return a ^ b

    return lambda bits: ev(ast, bits)


def truth_table(expr: str, in_pins: list[str]) -> str:
    """``d_genlut`` ``table_values`` for ``expr`` over ``in_pins``.

    MEASURED ordering (ngspice-47 on the dispatch host, 4 one-hot
    ``table_values`` against all four input combinations): the table index is
    ``sum(bit_k << k)`` where ``bit_k`` is the **k-th node of the A-device's
    input vector**, i.e. the FIRST connected input is the least significant
    bit. ``in_pins`` is emitted in this same order.
    """
    f = compile_function(expr, set(in_pins))
    n = len(in_pins)
    out = []
    for idx in range(1 << n):
        bits = {p: (idx >> k) & 1 for k, p in enumerate(in_pins)}
        out.append("1" if f(bits) else "0")
    return "".join(out)


# --------------------------------------------------------------------------
# NLDM table -> scalar delay
# --------------------------------------------------------------------------

def _numbers(s: str) -> list[float]:
    return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)]


class NldmTable:
    """A Liberty 2-D ``cell_rise``/``cell_fall`` table with bilinear lookup."""

    def __init__(self, group: LibGroup, where: str):
        self.where = where
        i1 = group.calls.get("index_1")
        i2 = group.calls.get("index_2")
        vals = group.calls.get("values")
        if i1 is None or vals is None:
            raise GateModelError(f"{where}: table without index_1/values")
        self.index_1 = _numbers(i1)
        self.index_2 = _numbers(i2) if i2 is not None else [0.0]
        flat = _numbers(vals)
        n1, n2 = len(self.index_1), len(self.index_2)
        if len(flat) != n1 * n2:
            raise GateModelError(
                f"{where}: {len(flat)} values for a {n1}x{n2} table")
        self.values = [flat[r * n2:(r + 1) * n2] for r in range(n1)]

    @staticmethod
    def _bracket(axis: list[float], x: float) -> tuple[int, int, float]:
        """(lo, hi, frac) for ``x`` on ``axis``, CLAMPED (never extrapolated)."""
        if len(axis) == 1 or x <= axis[0]:
            return 0, 0, 0.0
        if x >= axis[-1]:
            n = len(axis) - 1
            return n, n, 0.0
        hi = next(i for i in range(1, len(axis)) if axis[i] >= x)
        lo = hi - 1
        span = axis[hi] - axis[lo]
        return lo, hi, 0.0 if span == 0 else (x - axis[lo]) / span

    def at(self, slew: float, load: float) -> float:
        r0, r1, fr = self._bracket(self.index_1, slew)
        c0, c1, fc = self._bracket(self.index_2, load)
        v00, v01 = self.values[r0][c0], self.values[r0][c1]
        v10, v11 = self.values[r1][c0], self.values[r1][c1]
        top = v00 + (v01 - v00) * fc
        bot = v10 + (v11 - v10) * fc
        return top + (bot - top) * fr


class CellModel:
    """One Liberty cell reduced to what the generator needs."""

    def __init__(self, name: str, group: LibGroup):
        self.name = name
        self.inputs: list[str] = []
        self.outputs: list[str] = []
        self.capacitance: dict[str, float] = {}
        self.function: dict[str, str] = {}
        #: {out_pin: [(related_pin, timing_type, NldmTable|None rise, fall)]}
        self.arcs: dict[str, list[tuple[str, str, NldmTable | None, NldmTable | None]]] = {}
        for pin in group.all("pin"):
            pname = pin.args[0] if pin.args else ""
            direction = pin.attrs.get("direction")
            if direction == "input":
                self.inputs.append(pname)
                cap = pin.attrs.get("capacitance")
                self.capacitance[pname] = float(cap) if cap is not None else 0.0
            elif direction == "output":
                self.outputs.append(pname)
                if "function" in pin.attrs:
                    self.function[pname] = pin.attrs["function"]
                arcs = []
                for t in pin.all("timing"):
                    ttype = t.attrs.get("timing_type", "combinational")
                    if ttype not in DELAY_ARC_TYPES:
                        continue
                    rise = t.first("cell_rise")
                    fall = t.first("cell_fall")
                    arcs.append((
                        t.attrs.get("related_pin", "?"), ttype,
                        NldmTable(rise, f"{name}/{pname}/cell_rise") if rise else None,
                        NldmTable(fall, f"{name}/{pname}/cell_fall") if fall else None,
                    ))
                self.arcs[pname] = arcs
        self.inputs.sort()
        self.outputs.sort()
        #: the ``ff`` group, when this is a sequential cell
        self.ff = group.first("ff")

    def is_sequential(self) -> bool:
        return self.ff is not None

    def delays(self, slew: float, load: float, out_pin: str) -> tuple[float, float]:
        """(rise_s, fall_s): max over every delay arc reaching ``out_pin``."""
        arcs = self.arcs.get(out_pin) or []
        rises = [a[2].at(slew, load) for a in arcs if a[2] is not None]
        falls = [a[3].at(slew, load) for a in arcs if a[3] is not None]
        if not rises or not falls:
            raise GateModelError(
                f"{self.name}/{out_pin}: no cell_rise/cell_fall delay arc "
                f"(arcs: {[(a[0], a[1]) for a in arcs]})")
        # Liberty time_unit is 1 ns; XSPICE floors any delay at MIN_DELAY_S
        return (max(max(rises) * 1e-9, MIN_DELAY_S),
                max(max(falls) * 1e-9, MIN_DELAY_S))


# --------------------------------------------------------------------------
# Gate model construction
# --------------------------------------------------------------------------

def _eng(x: float) -> str:
    return f"{x:.6g}"


#: ngspice's card reader is line-oriented; the vector-valued bridge cards would
#: otherwise be single lines of several thousand characters. Wrap them with the
#: standard SPICE ``+`` continuation instead of relying on an unbounded reader.
WRAP_COLS = 110


def wrap_card(card: str) -> list[str]:
    """Split a long SPICE card into ``+``-continued lines at token boundaries."""
    toks = card.split(" ")
    lines: list[str] = []
    cur = toks[0]
    for tok in toks[1:]:
        if len(cur) + 1 + len(tok) > WRAP_COLS and len(cur.strip()) > 1:
            lines.append(cur)
            cur = "+ " + tok
        else:
            cur += " " + tok
    lines.append(cur)
    return lines


class GateModel:
    def __init__(self, body: list[str], manifest: dict):
        self.body = body
        self.manifest = manifest

    def text(self) -> str:
        return "\n".join(self.body) + "\n"


def _ff_pin(expr: str, pins: set[str], where: str) -> tuple[str, bool]:
    """Parse an ``ff`` group expression that must be ``PIN`` or ``!PIN``."""
    e = expr.strip()
    inverted = False
    if e.startswith("!") or e.startswith("~"):
        inverted = True
        e = e[1:].strip()
    if e.endswith("'"):
        inverted = not inverted
        e = e[:-1].strip()
    if e not in pins:
        raise GateModelError(f"{where}: {expr!r} is not a bare input pin")
    return e, inverted


def build_gate_model(design: Design, lib: dict[str, CellModel], *, supply_v: float,
                     slew_ns: float, port_load_pf: float, liberty_path: Path,
                     liberty_sha256: str, threshold_pct: float) -> GateModel:
    """Emit the gate-level body. Raises on anything that must fail closed."""
    # -- 1. resolve nets, find drivers, check the structure -----------------
    in_ports = set(design.port_bits("input")) | set(design.port_bits("inout"))
    out_ports = design.port_bits("output")
    drivers: dict[str, str] = {}      # net -> "port" | instance name
    receivers: dict[str, list[tuple[str, str]]] = {}  # net -> [(cell, pin)]
    for net in in_ports:
        drivers[design.canon(net)] = "port"

    for cell, inst, pins in design.instances:
        cm = lib.get(cell)
        if cm is None:
            raise GateModelError(
                f"instance {inst}: cell {cell} is not in {liberty_path.name} "
                f"(no primitive mapping; refusing to write a partial model)")
        unknown = sorted(set(pins) - set(cm.inputs) - set(cm.outputs))
        if unknown:
            raise GateModelError(
                f"instance {inst} ({cell}): connected pins {unknown} are not "
                f"input/output pins of the Liberty cell")
        for pin, net in pins.items():
            cnet = design.canon(net)
            if pin in cm.outputs:
                if cnet in drivers:
                    raise GateModelError(
                        f"net {cnet!r} driven by both {drivers[cnet]} and {inst}")
                drivers[cnet] = inst
            else:
                receivers.setdefault(cnet, []).append((cell, pin))

    undriven = sorted({n for n in receivers if n not in drivers} |
                      {design.canon(p) for p in out_ports if design.canon(p) not in drivers})
    if undriven:
        raise GateModelError(f"nets read or exported but never driven: {undriven[:10]}")

    # -- 2. per-net capacitive load (reduction 2) ---------------------------
    load_pf: dict[str, float] = {}
    for net, rs in receivers.items():
        load_pf[net] = sum(lib[c].capacitance.get(p, 0.0) for c, p in rs)
    for p in out_ports:
        cnet = design.canon(p)
        load_pf[cnet] = load_pf.get(cnet, 0.0) + port_load_pf

    # -- 3. emit ------------------------------------------------------------
    dn = lambda net: f"dn_{net}"  # noqa: E731  digital node namespace
    in_low = supply_v * (threshold_pct / 100.0 - BRIDGE_BAND_FRAC)
    in_high = supply_v * (threshold_pct / 100.0 + BRIDGE_BAND_FRAC)

    bs = P.boundary_signals()
    analog_boundary = sorted(n for n, v in bs.items()
                             if v["dir"] in ("analog->digital", "tb->both"))
    boundary_in = [p for p in design.port_bits("input") if p in analog_boundary]
    tb_in = [p for p in design.port_bits("input") if p not in analog_boundary]
    if sorted(boundary_in) != analog_boundary:
        raise GateModelError(
            f"analog/digital boundary mismatch: netlist inputs {sorted(boundary_in)} "
            f"!= program.boundary_signals() {analog_boundary}")

    body: list[str] = [
        f"* gate-level model of {design.module} -- DR-0017 option (b), digital half",
        f"* generated by make-gate-model.py from {ROUTED_V.relative_to(REPO)}",
        f"* Liberty deck: {liberty_path}",
        f"*   sha256 {liberty_sha256}",
        f"* realisation: timed-delay XSPICE netlist (d_genlut / d_dff + adc/dac bridges)",
        f"* operating point: slew {slew_ns} ns, port load {port_load_pf} pF, supply {supply_v} V",
        f"* bridge band: {in_low:.4f} .. {in_high:.4f} V "
        f"({threshold_pct:.0f} % +- {BRIDGE_BAND_FRAC * 100:.0f} % of supply)",
        "",
        "* ---- supplies: boundary nets by name. At gate level the supply enters",
        "* ---- only through the bridge levels and the Liberty deck (see record).",
        f"Vvdd vdd 0 dc {supply_v}",
        "Vvss vss 0 dc 0",
        "",
        "* ---- DR-0017 analog/digital boundary (adc_bridge) ----",
        *wrap_card(f"Aadc_boundary [{' '.join(boundary_in)}] "
                   f"[{' '.join(dn(n) for n in boundary_in)}] adc_b"),
        "* ---- testbench-driven digital inputs (adc_bridge) ----",
        *wrap_card(f"Aadc_tb [{' '.join(tb_in)}] [{' '.join(dn(n) for n in tb_in)}] adc_b"),
        f".model adc_b adc_bridge(in_low={_eng(in_low)} in_high={_eng(in_high)})",
        "",
    ]

    cards: list[str] = []
    models: list[str] = []
    n_genlut = n_dff = 0
    noops: list[dict] = []
    widest = 0
    inverter_for: dict[str, str] = {}
    inv_cards: list[str] = []

    def polarity_inverter(net: str) -> str:
        """Shared zero-delay d_inverter giving the active-high form of ``net``."""
        if net not in inverter_for:
            idx = len(inverter_for)
            out = f"dn_pol{idx}_{net}"
            inverter_for[net] = out
            inv_cards.append(f"Apol{idx} {dn(net)} {out} pol_inv")
        return inverter_for[net]

    for cell, inst, pins in design.instances:
        cm = lib[cell]
        if not cm.outputs:
            if cm.is_sequential() or cm.function:
                raise GateModelError(f"{cell}: no output pin but carries logic")
            # reduction 5: a declared load-only instance (the antenna tie)
            noops.append({"instance": inst, "cell": cell,
                          "pins": {p: n for p, n in sorted(pins.items())},
                          "reason": "no output pin in the Liberty cell (antenna tie): "
                                    "contributes input capacitance only"})
            continue
        if len(cm.outputs) != 1:
            raise GateModelError(
                f"{cell}: {len(cm.outputs)} output pins; only single-output cells map")
        out_pin = cm.outputs[0]
        if out_pin not in pins:
            # reduction 5: a declared load-only instance (a CTS dummy load whose
            # output the router left open). Nothing can read it, so omitting the
            # primitive is exact for an event-driven model; its own input
            # capacitance is still counted in its driver's C_load above.
            noops.append({"instance": inst, "cell": cell,
                          "pins": {p: n for p, n in sorted(pins.items())},
                          "reason": f"output pin {out_pin} unconnected in the routed "
                                    f"netlist (load-only instance): no reader, so no "
                                    f"primitive; input capacitance still loads its driver"})
            continue
        out_net = design.canon(pins[out_pin])
        load = load_pf.get(out_net, 0.0)
        rise, fall = cm.delays(slew_ns, load, out_pin)

        if cm.is_sequential():
            ffg = cm.ff
            pinset = set(cm.inputs)
            where = f"{cell}/ff"
            clk_pin, clk_inv = _ff_pin(ffg.attrs.get("clocked_on", ""), pinset, where)
            if clk_inv:
                raise GateModelError(
                    f"{where}: clocked_on is negated (falling-edge flop); d_dff is "
                    f"rising-edge only -- no mapping, refusing to write")
            d_pin, d_inv = _ff_pin(ffg.attrs.get("next_state", ""), pinset, where)
            if d_inv:
                raise GateModelError(f"{where}: next_state is negated; no d_dff mapping")
            iq, iqn = (ffg.args + ["", ""])[:2]
            fn = cm.function.get(out_pin, "")
            if fn == iq:
                q_slot, nq_slot = "q", "null"
            elif fn == iqn:
                q_slot, nq_slot = "null", "q"
            else:
                raise GateModelError(
                    f"{cell}/{out_pin}: function {fn!r} is neither {iq!r} nor {iqn!r}")

            def async_node(attr: str) -> str:
                expr = ffg.attrs.get(attr)
                if not expr:
                    return "null"
                pin, inverted = _ff_pin(expr, pinset, f"{where}/{attr}")
                if pin not in pins:
                    raise GateModelError(f"instance {inst} ({cell}): {attr} pin {pin} unconnected")
                net = design.canon(pins[pin])
                # measured: XSPICE d_dff set/reset are active HIGH (reduction 6)
                return polarity_inverter(net) if inverted else dn(net)

            set_node = async_node("preset")
            reset_node = async_node("clear")
            for required in (clk_pin, d_pin):
                if required not in pins:
                    raise GateModelError(f"instance {inst} ({cell}): pin {required} unconnected")
            q_node = dn(out_net)
            nodes = [dn(design.canon(pins[d_pin])), dn(design.canon(pins[clk_pin])),
                     set_node, reset_node,
                     q_node if q_slot == "q" else "null",
                     q_node if nq_slot == "q" else "null"]
            cards.append(f"A{inst} {' '.join(nodes)} m{inst}")
            models.append(
                f".model m{inst} d_dff(rise_delay={_eng(rise)} fall_delay={_eng(fall)} "
                f"clk_delay={_eng(MIN_DELAY_S)} set_delay={_eng(MIN_DELAY_S)} "
                f"reset_delay={_eng(MIN_DELAY_S)} ic=0)")
            n_dff += 1
            continue

        if out_pin not in cm.function:
            raise GateModelError(
                f"{cell}/{out_pin}: no Liberty function and no ff group -- "
                f"no primitive mapping, refusing to write a partial model")
        in_pins = [p for p in cm.inputs if p in pins]
        missing = sorted(set(cm.inputs) - set(in_pins))
        if missing:
            raise GateModelError(f"instance {inst} ({cell}): input pins {missing} unconnected")
        table = truth_table(cm.function[out_pin], in_pins)
        widest = max(widest, len(in_pins))
        in_nodes = [dn(design.canon(pins[p])) for p in in_pins]
        caps = [cm.capacitance[p] * 1e-12 for p in in_pins]  # pF -> F
        cards.append(f"A{inst} [{' '.join(in_nodes)}] [{dn(out_net)}] m{inst}")
        models.append(
            f'.model m{inst} d_genlut(table_values="{table}" rise_delay=[{_eng(rise)}] '
            f"fall_delay=[{_eng(fall)}] input_load=[{' '.join(_eng(c) for c in caps)}])")
        n_genlut += 1

    if inv_cards:
        body += ["* ---- declared polarity inverters for active-low clear/preset ----",
                 *inv_cards,
                 f".model pol_inv d_inverter(rise_delay={_eng(MIN_DELAY_S)} "
                 f"fall_delay={_eng(MIN_DELAY_S)} input_load=0)",
                 ""]
    body += ["* ---- cells ----"]
    for card, model in zip(cards, models):
        body += wrap_card(card) + wrap_card(model)

    obs_out = [p for p in out_ports]
    body += [
        "",
        "* ---- observed digital outputs (dac_bridge) ----",
        *wrap_card(f"Adac_obs [{' '.join(dn(design.canon(p)) for p in obs_out)}] "
                   f"[{' '.join(obs_out)}] dac_b"),
        f".model dac_b dac_bridge(out_low=0 out_high={_eng(supply_v)} "
        f"out_undef={_eng(supply_v / 2)} t_rise={_eng(DAC_EDGE_S)} t_fall={_eng(DAC_EDGE_S)})",
    ]

    total = n_genlut + n_dff + len(noops)
    if total != len(design.instances):
        raise GateModelError(
            f"instance accounting: {n_genlut} genlut + {n_dff} dff + {len(noops)} "
            f"declared no-ops = {total} != {len(design.instances)} routed instances")

    manifest = {
        "realisation": "timed-delay XSPICE netlist (d_genlut / d_dff + adc/dac bridges)",
        "dr_0017_option": "b",
        "module": design.module,
        "source_netlist": str(ROUTED_V.relative_to(REPO)),
        "source_netlist_sha256": sha256_file(ROUTED_V),
        "liberty_deck": str(liberty_path),
        "liberty_sha256": liberty_sha256,
        "routed_instances": len(design.instances),
        "primitives": {"d_genlut": n_genlut, "d_dff": n_dff},
        "polarity_inverters": len(inv_cards),
        "declared_no_op_instances": noops,
        "cell_histogram": design.cell_histogram(),
        "widest_genlut_inputs": widest,
        "ports": {
            "all": design.port_bits(),
            "inputs": design.port_bits("input"),
            "outputs": out_ports,
        },
        "boundary": {
            "analog_digital": boundary_in,
            "testbench_driven": tb_in,
            "observed": obs_out,
            "supplies": ["vdd", "vss"],
            "source": "program.boundary_signals()",
        },
        "reductions": {
            "slew_ns": slew_ns,
            "port_load_pf": port_load_pf,
            "supply_v": supply_v,
            "liberty_threshold_pct": threshold_pct,
            "adc_bridge_in_low_v": in_low,
            "adc_bridge_in_high_v": in_high,
            "dac_bridge_out_high_v": supply_v,
            "nldm_reduction": "bilinear interpolation at (slew, C_load), clamped to the "
                              "table index range, max over every delay arc to the pin",
            "c_load": "sum of Liberty input-pin capacitance of the receivers on the net, "
                      "plus port_load_pf on a net that reaches a module output port",
            "input_load": "Liberty input-pin capacitance per d_genlut input -- NOT the "
                          "DR-0017 boundary-load choice (option 1 vs 2 is open, #431)",
            "dff": f"clk_delay/set_delay/reset_delay = {MIN_DELAY_S} s (XSPICE's own "
                   f"floor; it refuses 0), ic = 0; one scalar rise/fall pair per flop "
                   f"covers the CLK->Q and async clear/preset arcs",
            "min_delay_s": MIN_DELAY_S,
            "supply_axis": "corners.supply_v alone does NOT re-corner the digital half; "
                           "the Liberty deck must move with the (T, Vdd) point",
        },
        "genlut_index_order": "index = sum(bit_k << k), k = position in the A-device "
                              "input vector (first input is the LSB); measured on "
                              "ngspice-47 with four one-hot table_values",
        "provenance": P.PROVENANCE,
    }
    return GateModel(body, manifest)


# --------------------------------------------------------------------------
# Stimulus, request and plan
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def raw_bits(n: int) -> list[int]:
    if n > len(RAW_BIT_PATTERN):
        raise GateModelError(f"RAW_BIT_PATTERN has {len(RAW_BIT_PATTERN)} bits, need {n}")
    return [int(c) for c in RAW_BIT_PATTERN[:n]]


def stimulus_cards(cycles: list[dict], vih: float) -> list[str]:
    """PWL cards for every driven input, plus clk/rst_n/raw_bit.

    The clock, reset and per-cycle bus PWL shapes are the whole-block deck's
    (``make-requests.py`` ``deck_body``/``input_cards``), so the digital half is
    driven exactly as it is inside the coupled run. ``raw_bit`` is testbench
    driven here (standalone), from the committed RAW_BIT_PATTERN.
    """
    inputs = P.cycle_inputs(cycles)
    n = len(cycles)
    t_stop = P.t_stop_ns(cycles)

    def pwl(sig: str, pts: list[tuple[float, float]]) -> str:
        body = " ".join(f"{t:.1f}n {v * vih:.3f}" for t, v in pts)
        return f"V{sig} {sig} 0 PWL({body})"

    def emit(sig: str, pts: list[tuple[float, float]]) -> list[str]:
        return wrap_card(pwl(sig, pts))

    def points(get) -> list[tuple[float, float]]:
        """PWL breakpoints that HOLD between changes, with a 100 ps edge.

        A PWL source interpolates **linearly** between its breakpoints, so a
        points list that carries only the change instants makes every input
        ramp over the whole interval instead of switching at it. Measured on
        this deck: ``bus_re`` emitted as ``PWL(0n 1.8 640n 0)`` sits at
        0.928 V at 310 ns, inside the adc_bridge dead band, and the whole
        digital state goes UNKNOWN. So each change gets a hold point one
        ``PWL_EDGE_NS`` before it. The edge width is the same 100 ps every
        PULSE card in this deck family uses, and the same operating point
        ``--slew-ns`` reduces the Liberty tables at.
        """
        pts = [(0.0, float(get(0)))]
        for k in range(1, n):
            if get(k) != get(k - 1):
                t_change = P.t_edge_ns(k) + P.SKEW_NS
                pts.append((t_change - PWL_EDGE_NS, float(get(k - 1))))
                pts.append((t_change, float(get(k))))
        pts.append((t_stop, float(get(n - 1))))
        return pts

    cards: list[str] = [
        f"Vrst_n rst_n 0 PULSE(0 {vih} {P.RST_N_RELEASE_NS:.0f}n 100p 100p 10u 20u)",
        f"Vclk clk 0 PULSE(0 {vih} {P.T0_NS:.0f}n 100p 100p 49.8n {P.TS_NS:.0f}n)",
    ]
    # raw_bit: the sampler's output in a coupled run; driven here. It changes
    # one skew after the edge of each sample cycle and holds.
    bits = raw_bits(sum(1 for i in inputs if i["raw_valid"]))
    seq: list[int] = []
    bi = 0
    for inp in inputs:
        if inp["raw_valid"]:
            seq.append(bits[bi])
            bi += 1
        else:
            seq.append(seq[-1] if seq else 0)
    cards += emit("raw_bit", points(lambda k: seq[k]))
    for bit in range(4):
        cards += emit(f"bus_addr_{bit}_",
                      points(lambda k, b=bit: (inputs[k]["addr"] >> b) & 1))
    for bit in range(32):
        cards += emit(f"bus_wdata_{bit}_",
                      points(lambda k, b=bit: (inputs[k]["wdata"] >> b) & 1))
    # module port name -> program.cycle_inputs() key
    for sig, key in (("bus_we", "we"), ("bus_re", "re"),
                     ("raw_valid", "raw_valid"), ("out_ready", "out_ready")):
        cards += emit(sig, points(lambda k, kk=key: inputs[k][kk]))
    return cards


def measurement_cards(cycles: list[dict]) -> tuple[list[dict], list[str]]:
    """``.meas`` entries for every digital response the model also predicts."""
    inputs = P.cycle_inputs(cycles)
    n = len(cycles)
    t_stop = P.t_stop_ns(cycles)
    meas: list[dict] = []
    save = {"clk", "rst_n", "raw_bit", "raw_valid", "alarm", "gated",
            "startup_done", "out_valid", "vdd", "vss"}

    def add(name: str, card: str, net: str | None = None, t: float | None = None):
        if t is not None and t > t_stop:
            return
        meas.append({"name": name, "spice": card})
        if net:
            save.add(net)

    for k, inp in enumerate(inputs):
        # A read's data is latched at the edge that ENDS cycle k and observed
        # during cycle k+1, so a read in the LAST cycle has no cycle to be
        # observed in and no model row to compare with: not measured.
        if inp["re"] and k + 1 < n:
            t = P.t_edge_ns(k + 1) + P.RDATA_NS
            for bit in range(32):
                add(f"rdata_k{k}_b{bit}",
                    f".meas tran rdata_k{k}_b{bit} FIND v(bus_rdata_{bit}_) AT={t:.1f}n",
                    f"bus_rdata_{bit}_", t)
    # streaming word captures on the cycles make-requests.py also captures
    # (the first completions and the tail); the comparison asserts them only
    # where the normative model reports out_valid = 1 for that cycle.
    for k in sorted({36, 37, 74} | set(range(max(0, n - 3), n))):
        if k >= n:
            continue
        t = P.t_edge_ns(k) + P.RDATA_NS
        for bit in range(32):
            add(f"odata_k{k}_b{bit}",
                f".meas tran odata_k{k}_b{bit} FIND v(out_data_{bit}_) AT={t:.1f}n",
                f"out_data_{bit}_", t)
    # scalar observables, measured DURING cycle k -- the same capture convention
    # make-requests.py uses, so the oracle mapping is identical: a `<sig>_k<k>`
    # sample is compared with the model row for cycle k, and a `rdata_k<k>`
    # sample (latched at the edge that ENDS cycle k) with the row for k+1.
    for k in range(n):
        t = P.t_edge_ns(k) + P.RDATA_NS
        for sig in ("alarm", "gated", "startup_done", "out_valid"):
            add(f"{sig}_k{k}", f".meas tran {sig}_k{k} FIND v({sig}) AT={t:.1f}n", sig, t)
    add("t_clk_first", ".meas tran t_clk_first WHEN v(clk)=0.9 RISE=1", "clk")
    names = [e["name"] for e in meas]
    if len(names) != len(set(names)):
        raise GateModelError("duplicate measurement names")
    return meas, sorted(save)


def build_deck(model: GateModel, cycles: list[dict], vih: float) -> tuple[str, list[dict], list[str]]:
    meas, save = measurement_cards(cycles)
    body = list(model.body)
    body += ["", "* ---- directed program stimulus (program.py) ----",
             *stimulus_cards(cycles, vih),
             "", "* ---- saved trace set ----"]
    for i in range(0, len(save), 8):
        body.append(".save " + " ".join(save[i:i + 8]))
    return "\n".join(body) + "\n", meas, save


def ngspice_version() -> str:
    try:
        out = subprocess.run(["ngspice", "--version"], capture_output=True,
                             text=True, timeout=30).stdout
        m = re.search(r"ngspice-\d+\S*", out)
        return m.group(0) if m else "unknown"
    except Exception:  # pragma: no cover - environment probe only
        return "unavailable"


def resolve_liberty(explicit: str | None, corner: str) -> Path:
    """Resolve the Liberty deck through the repo's documented order.

    ``--liberty`` wins; otherwise ``klt pdk find --pdk sky130A`` locates the
    install (``sim/README.md`` "PDK resolution order") and the deck is taken
    from its ``libs.ref/sky130_fd_sc_hd/lib/``. The absolute path and its
    sha256 are recorded; a ``~/.ciel`` literal is never hardcoded.
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise GateModelError(f"--liberty {p} does not exist")
        return p
    try:
        out = subprocess.run(["klt", "pdk", "find", "--pdk", PDK],
                             capture_output=True, text=True, timeout=300, check=True).stdout
    except Exception as exc:
        raise GateModelError(f"klt pdk find --pdk {PDK} failed: {exc}") from exc
    m = re.search(r"^\s*libs_ref:\s*(\S+)\s*$", out, re.M)
    if not m:
        raise GateModelError(f"klt pdk find printed no libs_ref:\n{out}")
    p = Path(m.group(1)) / "sky130_fd_sc_hd" / "lib" / f"sky130_fd_sc_hd__{corner}.lib"
    if not p.is_file():
        raise GateModelError(f"resolved Liberty deck {p} does not exist")
    return p.resolve()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir", type=Path, help="output directory (must be empty or absent)")
    ap.add_argument("--verilog", type=Path, default=ROUTED_V,
                    help="routed structural netlist (default: the committed one)")
    ap.add_argument("--liberty", default=None,
                    help="Liberty deck path; default resolves via klt pdk find")
    ap.add_argument("--corner", default="tt_025C_1v80",
                    help="Liberty corner name when --liberty is not given")
    ap.add_argument("--supply-v", type=float, default=1.8)
    ap.add_argument("--temp-c", type=float, default=27.0)
    ap.add_argument("--slew-ns", type=float, default=DEFAULT_SLEW_NS)
    ap.add_argument("--port-load-pf", type=float, default=DEFAULT_PORT_LOAD_PF)
    ap.add_argument("--vih", type=float, default=VIH)
    ap.add_argument("--cycles", type=int, default=6,
                    help="program cycles to drive (the short AC3 program); "
                         "0 means the full program")
    ap.add_argument("--timeout-s", type=int, default=3480,
                    help="klt sim per-corner wall-clock ceiling (DR-0017's unit ceiling)")
    ap.add_argument("--backend", default="local", choices=("local", "batch"))
    args = ap.parse_args(argv)

    outdir: Path = args.outdir
    if outdir.exists() and any(outdir.iterdir()):
        ap.error(f"{outdir} exists and is not empty; refusing to overwrite")

    design = parse_verilog(args.verilog)
    liberty = resolve_liberty(args.liberty, args.corner)
    lib_sha = sha256_file(liberty)
    wanted = set(design.cell_histogram())
    blocks, header = extract_cell_blocks(liberty, wanted)
    absent = sorted(wanted - set(blocks))
    if absent:
        raise GateModelError(
            f"{liberty.name} has no cell block for {absent} -- refusing to write")
    thr_rise = header.get("input_threshold_pct_rise")
    thr_fall = header.get("input_threshold_pct_fall")
    if thr_rise is None or thr_fall is None:
        raise GateModelError(f"{liberty.name}: no input_threshold_pct_rise/_fall")
    if float(thr_rise) != float(thr_fall):
        raise GateModelError(
            f"{liberty.name}: asymmetric input thresholds {thr_rise}/{thr_fall}; "
            f"a single adc_bridge band cannot represent them")
    threshold_pct = float(thr_rise)
    if threshold_pct != EXPECTED_THRESHOLD_PCT:
        raise GateModelError(
            f"{liberty.name}: input_threshold_pct is {threshold_pct}, not "
            f"{EXPECTED_THRESHOLD_PCT}; the bridge band assumption needs re-deriving")
    lib = {name: CellModel(name, g) for name, g in blocks.items()}

    model = build_gate_model(design, lib, supply_v=args.supply_v, slew_ns=args.slew_ns,
                             port_load_pf=args.port_load_pf, liberty_path=liberty,
                             liberty_sha256=lib_sha, threshold_pct=threshold_pct)

    limit = None if args.cycles == 0 else args.cycles
    cycles, phases = P.build_program(limit=limit)
    t_stop = P.t_stop_ns(cycles)
    deck, meas, save = build_deck(model, cycles, args.vih)

    request = {
        "netlist": "netlist.cir",
        "engine": "ngspice",
        "backend": args.backend,
        # klt sim accepts only 'schematic' or 'extracted' for netlist_source;
        # a gate-level netlist built from a routed structural netlist plus a
        # Liberty deck is neither. 'extracted' is the closer of the two (this
        # IS derived from the layout, via trng_digital.routed.v), and the
        # forced label is disclosed in plan.json and the record. Filed as a
        # tool gap: klayout-tools#5638.
        "netlist_source": NETLIST_SOURCE,
        "models": {"pdk": PDK, "lib": LIB},
        "corners": {"process": ["tt"], "temperature_c": [args.temp_c]},
        "analysis": {"kind": "tran", "args": f"{TMAX} {t_stop:.0f}n"},
        "measurements": meas,
        "options": {"timeout_s": args.timeout_s, "keep_artifacts": True,
                    "save_mode": "netlist"},
    }
    plan = {
        "name": "gate-model-probe",
        "issue": 486,
        "realisation": model.manifest["realisation"],
        "netlist_sha256": sha256_text(deck),
        "gate_model_sha256": sha256_text(model.text()),
        "routed_netlist_sha256": model.manifest["source_netlist_sha256"],
        "liberty_deck": str(liberty),
        "liberty_sha256": lib_sha,
        "program": {"t0_ns": P.T0_NS, "ts_ns": P.TS_NS, "cycles": len(cycles),
                    "t_stop_ns": t_stop,
                    "phases": [{"name": n, "from": a, "to": b} for n, a, b in phases]},
        "raw_bit_pattern": RAW_BIT_PATTERN[:sum(
            1 for i in P.cycle_inputs(cycles) if i["raw_valid"])],
        "analysis": request["analysis"],
        "corners": request["corners"],
        "measurement_count": len(meas),
        "vih_fixed": args.vih,
        "netlist_source_forced": {
            "value": NETLIST_SOURCE,
            "why": "klt sim accepts only 'schematic'/'extracted'; this netlist is "
                   "gate-level, generated from trng_digital.routed.v plus one Liberty "
                   "deck. Disclosed deviation, not a claim about the netlist's level.",
        },
        "tools": {"ngspice": ngspice_version()},
        "provenance": P.PROVENANCE,
        "reductions": model.manifest["reductions"],
    }

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "gate-model.cir").write_text(model.text())
    (outdir / "gate-model.manifest.json").write_text(
        json.dumps(model.manifest, indent=2, sort_keys=True) + "\n")
    (outdir / "netlist.cir").write_text(deck)
    (outdir / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    (outdir / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    m = model.manifest
    print(f"wrote {outdir}")
    print(f"  {m['routed_instances']} routed instances -> "
          f"{m['primitives']['d_genlut']} d_genlut + {m['primitives']['d_dff']} d_dff "
          f"+ {len(m['declared_no_op_instances'])} declared no-op"
          f" (+{m['polarity_inverters']} polarity inverters)")
    print(f"  Liberty {liberty.name} sha256 {lib_sha[:16]}...")
    print(f"  boundary (analog/digital): {' '.join(m['boundary']['analog_digital'])}")
    print(f"  program {len(cycles)} cycles, t_stop {t_stop:.0f} ns, {len(meas)} measurements")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GateModelError as exc:
        print(f"make-gate-model.py: {exc}", file=sys.stderr)
        sys.exit(2)
