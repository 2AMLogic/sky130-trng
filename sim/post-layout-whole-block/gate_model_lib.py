#!/usr/bin/env python3
"""The stdlib-only Verilog / Liberty / NLDM frontend of ``make-gate-model.py``
(issue #776).

Everything the gate-level generator needs to READ its inputs, split out of
the hyphenated CLI script verbatim: the structural post-route Verilog parser
(``parse_verilog``), the targeted streaming Liberty ``.lib`` parser
(``extract_cell_blocks``), the recursive-descent Liberty Boolean-function
compiler (``compile_function`` / ``truth_table``) and the 2-D NLDM bilinear
interpolator (``NldmTable`` / ``CellModel``). The XSPICE emitter, the
directed testbench deck assembly, the ``klt``/``ngspice`` environment probes
and the CLI entry point stay in ``make-gate-model.py``, which imports and
re-exports these symbols so its ``load_module`` callers are unchanged, while
the unit tests and the analysis tools import the frontend directly from here
instead of executing the CLI module.

Pure text work, stdlib only (``re`` and ``pathlib.Path``): no ``klt``, no
PDK, no ``ngspice``, no ``subprocess``, and no dependency on ``program`` or
``pvt_deck_map`` -- the same pure-library seam
``layout/bin/verify_whole_lib.py`` cut for ``verify-whole.py`` (#173, #495).
"""
from __future__ import annotations

import re
from pathlib import Path

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
