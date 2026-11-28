#!/usr/bin/env python3
"""The importable library half of the gate-level digital model generator
(issues #776, #815).

Everything the gate-level generator needs to READ its inputs, split out of
the hyphenated CLI script verbatim: the structural post-route Verilog parser
(``parse_verilog``), the targeted streaming Liberty ``.lib`` parser
(``extract_cell_blocks``), the recursive-descent Liberty Boolean-function
compiler (``compile_function`` / ``truth_table``) and the 2-D NLDM bilinear
interpolator (``NldmTable`` / ``CellModel``).

Since #815 it also hosts the XSPICE **emitter** (``build_gate_model`` and its
helpers): the 12-point coupled grid (``make-requests.py --set grid``) builds
one gate model per matrix point in process, and shares that code by import
-- never by executing the sibling CLI (#804). The directed testbench deck
assembly, the ``klt``/``ngspice`` environment probes and the CLI entry point
stay in ``make-gate-model.py``, which imports and re-exports these symbols so
its ``load_module`` callers are unchanged, while the unit tests and the
analysis tools import the frontend directly from here instead of executing
the CLI module.

Pure text work, stdlib only plus this repo's own stdlib-only modules (``re``,
``pathlib.Path``, ``layout/bin/_hashing`` and ``program.boundary_signals``,
the DR-0017 boundary the emitter asserts the netlist against): no ``klt``, no
PDK, no ``ngspice``, no ``subprocess``, no ``pvt_deck_map`` -- the same
library seam ``layout/bin/verify_whole_lib.py`` cut for ``verify-whole.py``
(#173, #495).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "layout" / "bin"))
sys.path.insert(0, str(HERE))
from _hashing import sha256_file  # noqa: E402
import program as P  # noqa: E402

CELL_PREFIX = "sky130_fd_sc_hd__"

#: XSPICE refuses any delay parameter below 1 ps ("Value 0 below limit 1e-12 for
#: parameter 'clk_delay'"), so that floor -- not 0 -- is the generator's "no
#: delay". It is three orders of magnitude below the smallest cell delay in this
#: deck (the fastest cell_rise here is ~60 ps), so it is not a modelling choice.
MIN_DELAY_S = 1e-12


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


def netname(token: str) -> str:
    """A routed-netlist net/instance token as a flat, bracket-free SPICE name.

    Agrees with ``make-netlist.py:_normalise_name`` (the live owner of the
    committed ``trng_whole.sim.spice.gz`` names) on every plain ``name[i]``
    token, and additionally handles the two forms it does not: Yosys
    **escaped identifiers** (``\raw_mem[3] [30]``, where the escape ends at
    the space and ``[30]`` is a bit-select on it) and the resulting
    multi-dimensional names (``raw_mem[3][30]`` -> ``raw_mem_3__30_``).
    576 connections in the committed netlist use the escaped form, so this
    is load-bearing, not defensive.
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


def extract_cell_blocks(
    lib_path: Path, wanted: set[str]
) -> tuple[dict[str, LibGroup], dict[str, str], dict[str, LibGroup]]:
    """Return ({cell_name: parsed group}, library attributes, lut templates).

    Streams the deck (13 MB for ``tt_025C_1v80``) and parses only the wanted
    ``cell`` blocks, so the whole library is never materialised as an AST.

    The library-level ``lu_table_template`` groups are collected **by name**.
    They cannot be read from the flat ``header`` dict: ``header`` folds every
    library-level attribute line in with ``setdefault``, so a template's
    ``variable_1`` lands there from whichever template appears first in the
    deck -- for the pinned deck that is ``power_inputs_1``'s
    ``input_transition_time``, 13 lines before ``del_1_7_7``. NldmTable reads
    each table's own template by the name in the table group's arg.
    """
    header: dict[str, str] = {}
    blocks: dict[str, LibGroup] = {}
    templates: dict[str, LibGroup] = {}
    collecting: list[str] | None = None
    collect_kind = ""                 # "cell" | "lu_table_template"
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
                    collect_kind = "cell"
                continue
            if g and g.group(1) == "lu_table_template":
                cand = g.group(2).strip().strip('"')
                collecting = [ln]
                depth = 1
                name = cand
                collect_kind = "lu_table_template"
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
            parsed = parse_liberty_group(collecting)
            if collect_kind == "cell":
                blocks[name] = parsed
            else:
                templates[name] = parsed
            collecting = None
    if collecting is not None:
        raise GateModelError(f"{lib_path}: unterminated {collect_kind} block for {name!r}")
    return blocks, header, templates


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

    Grammar (precedence low to high; Liberty binds ``^`` TIGHTER than
    ``&``/``*`/juxtaposition, so ``A ^ B & C`` is ``(A ^ B) & C``)::

        or    := and (('|' | '+') and)*
        and   := xor (('&' | '*')? xor)*       # juxtaposition is AND
        xor   := not ('^' not)*
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
        node = self.p_and()
        while self.peek() in (("op", "|"), ("op", "+")):
            self.i += 1
            node = ("or", node, self.p_and())
        return node

    def p_and(self):
        node = self.p_xor()
        while True:
            k, v = self.peek()
            if (k, v) in (("op", "&"), ("op", "*")):
                self.i += 1
                node = ("and", node, self.p_xor())
            elif k == "id" or k == "num" or (k, v) in (("op", "("), ("op", "!"), ("op", "~")):
                node = ("and", node, self.p_xor())  # juxtaposition
            else:
                return node

    def p_xor(self):
        node = self.p_not()
        while self.peek() == ("op", "^"):
            self.i += 1
            node = ("xor", node, self.p_not())
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

    #: the only axis spellings ``at(slew, load)`` is validated for: the row
    #: index must be the input transition (slew), the column the output load.
    #: These are the axes of the pinned deck's ``del_1_7_7`` and its siblings;
    #: a template that swaps them would be read transposed, silently.
    SLEW_AXIS = "input_net_transition"
    LOAD_AXIS = "total_output_net_capacitance"

    def __init__(self, group: LibGroup, where: str,
                 templates: dict[str, LibGroup]):
        self.where = where
        tname = group.args[0] if group.args else ""
        tmpl = templates.get(tname)
        if tmpl is None:
            raise GateModelError(
                f"{where}: table references lu_table_template {tname!r}, "
                f"which the deck does not define")
        v1, v2 = tmpl.attrs.get("variable_1"), tmpl.attrs.get("variable_2")
        if v1 != self.SLEW_AXIS or v2 != self.LOAD_AXIS:
            raise GateModelError(
                f"{where}: lu_table_template {tname!r} indexes "
                f"({v1!r}, {v2!r}), not ({self.SLEW_AXIS!r}, "
                f"{self.LOAD_AXIS!r}); at(slew, load) would read it "
                f"transposed -- refusing")
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

    def __init__(self, name: str, group: LibGroup,
                 templates: dict[str, LibGroup]):
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
                        NldmTable(rise, f"{name}/{pname}/cell_rise",
                                  templates) if rise else None,
                        NldmTable(fall, f"{name}/{pname}/cell_fall",
                                  templates) if fall else None,
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


def load_liberty_cells(liberty_path: Path, wanted: set[str],
                       expected_threshold_pct: float = P.EXPECTED_THRESHOLD_PCT,
                       ) -> tuple[dict[str, CellModel], float]:
    """The wanted cells of one Liberty deck, reduced, and the deck's input
    threshold (``(cells, threshold_pct)``).

    One deck serves several matrix points (``pvt_deck_map`` maps 12 points
    onto 8 decks), so the caller caches this per deck. Fails closed -- the
    same three refusals ``make-gate-model.py`` always raised -- on a cell the
    deck does not define, a deck without ``input_threshold_pct_rise/_fall``,
    asymmetric thresholds (one ``adc_bridge`` band cannot represent them) or
    a threshold other than ``expected_threshold_pct`` (the bridge band is
    derived for that one).
    """
    blocks, header, templates = extract_cell_blocks(liberty_path, wanted)
    absent = sorted(wanted - set(blocks))
    if absent:
        raise GateModelError(
            f"{liberty_path.name} has no cell block for {absent} -- refusing to write")
    thr_rise = header.get("input_threshold_pct_rise")
    thr_fall = header.get("input_threshold_pct_fall")
    if thr_rise is None or thr_fall is None:
        raise GateModelError(f"{liberty_path.name}: no input_threshold_pct_rise/_fall")
    if float(thr_rise) != float(thr_fall):
        raise GateModelError(
            f"{liberty_path.name}: asymmetric input thresholds {thr_rise}/{thr_fall}; "
            f"a single adc_bridge band cannot represent them")
    threshold_pct = float(thr_rise)
    if threshold_pct != expected_threshold_pct:
        raise GateModelError(
            f"{liberty_path.name}: input_threshold_pct is {threshold_pct}, not "
            f"{expected_threshold_pct}; the bridge band assumption needs re-deriving")
    return {name: CellModel(name, g, templates) for name, g in blocks.items()}, threshold_pct


# --------------------------------------------------------------------------
# Gate model construction (the XSPICE emitter; issue #486, here since #815)
# --------------------------------------------------------------------------

#: half-width of the adc_bridge band, as a fraction of the supply. The band is
#: centred on the Liberty deck's own 50 % delay-measurement threshold; this
#: fraction is the generator's declared choice (a narrow band, so the bridged
#: event time coincides with the deck's delay reference point).
BRIDGE_BAND_FRAC = 0.05
#: input slew operating point (ns) -- reduction 3 in make-gate-model.py's
#: module docstring
DEFAULT_SLEW_NS = 0.1
#: output-port load (pF) -- the deck's "outputs are unloaded" assumption
DEFAULT_PORT_LOAD_PF = 0.0
#: bridge transition times (s) for dac_bridge; 100 ps, the deck's own PULSE edge
DAC_EDGE_S = 100e-12
#: the routed structural netlist every gate model is emitted from
ROUTED_V = P.ROUTED_V


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
