"""Library half of ``layout/bin/verify-whole.py`` (issue #173): mixed-level
whole-block reference generation, layout-netlist pin canonicalisation and the
independent per-port endpoint audit.

Pure text / ``klayout_tools.verilog_netlist`` work: nothing here runs ``klt``
or reads a GDS, so ``layout/test_verify_whole.py`` can exercise it without the
PDK on the PR-blocking CI path (the klt library import is the one soft
dependency; the tests skip the groups that need it when it is absent).

Mixed-level comparison boundary (what the generated reference declares)
----------------------------------------------------------------------

* Analog ``sampler_core`` -- **transistor level**. The committed, LVS-matched
  ``layout/sampler_core/sampler_core.ref.spice`` hierarchy is flattened into
  the top circuit with every device kept (264 MOSFETs). The layout side is a
  flat extraction, so the reference must be flat there too.
* Digital ``trng_digital`` -- **standard-cell level**. Every placed cell
  (``klt extract --abstract-cells``) is an opaque pin-only black box on the
  layout side; the reference calls the same pin-only stub. Signal pins come
  from the routed as-built Verilog, ``VPWR``/``VPB`` are tied to ``vdd`` and
  ``VGND`` to ``vss`` (the macro's documented supply aliases), and cells the
  Verilog never instantiates (fill / tap) come from the routed DEF
  ``COMPONENTS`` section and may only be power-only cells.
* The digital hierarchy is flattened into the whole-block top circuit (the
  extraction is flat); the ``trng_digital`` module boundary is not a circuit
  in the comparison.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

POWER_PINS = {"VPWR": "vdd", "VPB": "vdd", "VGND": "vss"}
#: Pins a layout-side abstracted stub never carries (the deck's global
#: substrate net; see the extract report warnings) and the reference
#: therefore does not carry either.
DROPPED_STUB_PINS = {"VNB"}
POWER_ONLY = {"VPWR", "VGND", "VPB", "VNB"}


class VerifyError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# SPICE helpers
# --------------------------------------------------------------------------


#: whitespace-split that keeps single-quoted xschem expressions whole
_TOKEN = re.compile(r"(?:[^\s']|'[^']*')+")


def join_continuations(text: str) -> list[str]:
    out: list[str] = []
    for line in text.split("\n"):
        if line.startswith("+") and out:
            out[-1] += " " + line[1:].strip()
        else:
            out.append(line)
    return out


def parse_subckts(text: str) -> dict[str, dict]:
    """``{name: {"ports": [...], "cards": [token lists]}}`` (case-preserving)."""
    subckts: dict[str, dict] = {}
    current = None
    for line in join_continuations(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        low = stripped.lower()
        if low.startswith(".subckt"):
            tok = stripped.split()
            current = {"ports": tok[2:], "cards": []}
            subckts[tok[1]] = current
        elif low.startswith(".ends"):
            current = None
        elif current is not None and not stripped.startswith("."):
            current["cards"].append(_TOKEN.findall(stripped))
    return subckts


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\[\]]", "_", name)


def flatten_analog(subckts: dict[str, dict], top: str, net_map: dict[str, str], prefix: str):
    """Flatten *top* (ports bound through *net_map*) into primitive-device cards.

    Returns ``(cards, device_count)``; a card is ``[name, n1.., model, k=v..]``
    with every internal net and instance name prefixed by its instance path.
    """
    cards: list[list[str]] = []

    def recurse(sub: str, binding: dict[str, str], path: str):
        for card in subckts[sub]["cards"]:
            name = card[0]
            if not name[0] in "Xx":
                raise VerifyError(f"analog reference card {name!r} in {sub!r} is not an X card")
            params = [t for t in card if "=" in t]
            body = [t for t in card[1:] if "=" not in t]
            model = body[-1]
            nets = body[:-1]
            bound = [binding.get(n, f"{prefix}{path}{n}") for n in nets]
            if model in subckts:
                child_ports = subckts[model]["ports"]
                if len(child_ports) != len(bound):
                    raise VerifyError(f"{sub}.{name}: {len(bound)} nets for {model} with {len(child_ports)} ports")
                recurse(model, dict(zip(child_ports, bound)), f"{path}{name[1:]}_")
            else:
                cards.append([f"X{prefix}{path}{name[1:]}", *bound, model, *params])

    top_ports = subckts[top]["ports"]
    recurse(top, {p: net_map[p] for p in top_ports}, "")
    return cards, len(cards)


# --------------------------------------------------------------------------
# reference generation
# --------------------------------------------------------------------------


def parse_def_components(def_text: str) -> list[tuple[str, str]]:
    m = re.search(r"^COMPONENTS\s+\d+\s*;(.*?)^END COMPONENTS", def_text, re.S | re.M)
    if not m:
        raise VerifyError("no COMPONENTS section in the routed DEF")
    return re.findall(r"^\s*-\s+(\S+)\s+(\S+)", m.group(1), re.M)


def stub_pins(order: list[str]) -> list[str]:
    return [p for p in order if p not in DROPPED_STUB_PINS]


def build_reference(
    *,
    analog_ref_text: str,
    analog_top: str,
    whole_ports: list[str],
    verilog_text: str,
    def_text: str,
    lib_pin_orders: dict[str, list[str]],
    digital_module: str,
    digital_to_whole: dict[str, str],
    header: list[str],
    verilog_parser,
) -> tuple[str, dict]:
    """Return ``(reference spice text, build facts)``."""
    asub = parse_subckts(analog_ref_text)
    if analog_top not in asub:
        raise VerifyError(f"analog top subckt {analog_top!r} not in the analog reference")
    ports = set(whole_ports)
    # analog macro ports are named like the whole-block nets; raw_bit/raw_valid
    # are the two inter-macro nets (not whole-block ports).
    analog_ports = asub[analog_top]["ports"]
    net_map = {p: p for p in analog_ports}
    unknown = [p for p in analog_ports if p not in ports and p not in ("raw_bit", "raw_valid")]
    if unknown:
        raise VerifyError(f"analog ports not in the whole-block port list: {unknown}")
    analog_cards, n_analog = flatten_analog(asub, analog_top, net_map, "a_")

    modules = verilog_parser(verilog_text)
    mods = [m for m in modules if m["name"] == digital_module]
    if len(mods) != 1:
        raise VerifyError(f"expected one module {digital_module!r} in the routed Verilog")
    mod = mods[0]
    # digital module port -> whole-block net name
    port_net = {}
    for p in mod["ports"]:
        if p not in digital_to_whole:
            raise VerifyError(f"digital module port {p!r} has no whole-block mapping")
        port_net[p] = digital_to_whole[p]
    canon_to_port: dict[str, str] = {}
    for p, canon in mod["port_aliases"].items():
        if canon in canon_to_port and canon_to_port[canon] != p:
            raise VerifyError(f"two ports alias the same net {canon!r}")
        canon_to_port[canon] = p
    internal: dict[str, str] = {}
    used: dict[str, str] = {}

    def net_of(n: str) -> str:
        if n in canon_to_port:
            return port_net[canon_to_port[n]]
        if n in port_net:
            return port_net[n]
        if n not in internal:
            nm = "d_" + sanitize(n)
            if nm in used and used[nm] != n:
                raise VerifyError(f"internal net name collision on {nm!r}")
            used[nm] = n
            internal[n] = nm
        return internal[n]

    insts = mod["instances"]
    verilog_names = {i["name"] for i in insts}
    def_comps = parse_def_components(def_text)
    used_cells = {i["cell"] for i in insts} | {c for _, c in def_comps}
    missing = sorted(c for c in used_cells if c not in lib_pin_orders)
    if missing:
        raise VerifyError(f"cells with no PDK pin order: {missing}")
    stubs = {c: stub_pins(lib_pin_orders[c]) for c in sorted(used_cells)}

    lines = list(header)
    lines.append("")
    lines.append(f".subckt trng_whole {' '.join(whole_ports)}")
    lines.append("* ---- analog sampler_core: transistor level (flattened, every device kept)")
    for c in analog_cards:
        lines.append(" ".join(c))
    lines.append("* ---- digital trng_digital: standard-cell level (pin-only black boxes)")
    n_signal_pins = 0
    n_dig = 0
    for inst in insts:
        cell = inst["cell"]
        conn = inst["connections"]
        nets = []
        for pin in stubs[cell]:
            if pin in POWER_PINS:
                nets.append(POWER_PINS[pin])
            elif pin in conn:
                v = conn[pin]
                if not isinstance(v, str):
                    raise VerifyError(f"{inst['name']}.{pin}: vector connection")
                nets.append(net_of(v))
                n_signal_pins += 1
            else:
                nets.append(f"NC_{sanitize(inst['name'])}_{pin}")
        bad = sorted(set(conn) - set(stubs[cell]))
        if bad:
            raise VerifyError(f"{inst['name']}: connections to non-pins {bad}")
        lines.append(f"X{sanitize(inst['name'])} {' '.join(nets)} {cell}")
        n_dig += 1
    power_only_cells = Counter()
    for name, cell in def_comps:
        if name in verilog_names:
            continue
        sig = [p for p in stubs[cell] if p not in POWER_ONLY]
        if sig:
            raise VerifyError(f"DEF component {name} ({cell}) is not in the Verilog and has signal pins {sig}")
        lines.append(f"X{sanitize(name)} {' '.join(POWER_PINS[p] for p in stubs[cell])} {cell}")
        power_only_cells[cell] += 1
        n_dig += 1
    def_names = {n for n, _ in def_comps}
    if not verilog_names <= def_names:
        raise VerifyError(f"Verilog instances absent from the DEF: {sorted(verilog_names - def_names)[:5]}")
    lines.append(".ends trng_whole")
    lines.append("")
    lines.append("* ---- pin-only standard-cell stubs (PDK pin order; VNB omitted, see header)")
    for cell, pins in stubs.items():
        lines.append(f".subckt {cell} {' '.join(pins)}")
        lines.append(f".ends {cell}")
    facts = {
        "analog_devices": n_analog,
        "digital_cell_instances": n_dig,
        "verilog_instances": len(insts),
        "power_only_instances": sum(power_only_cells.values()),
        "power_only_cells": dict(sorted(power_only_cells.items())),
        "signal_pin_connections": n_signal_pins,
        "internal_digital_nets": len(internal),
        "stub_cell_types": len(stubs),
        "whole_ports": len(whole_ports),
    }
    return "\n".join(lines) + "\n", facts


# --------------------------------------------------------------------------
# layout netlist pin canonicalisation
# --------------------------------------------------------------------------


def top_pins(text: str, top: str) -> list[str]:
    """Pin names of ``.SUBCKT <top>`` in a klt-extracted netlist."""
    lines = text.split("\n")
    for i, l in enumerate(lines):
        if re.match(rf"^\.SUBCKT\s+{re.escape(top)}\s*$", l, re.I) or re.match(
            rf"^\.SUBCKT\s+{re.escape(top)}\s", l, re.I
        ):
            pins = l.split()[2:]
            j = i + 1
            while j < len(lines) and lines[j].startswith("+"):
                pins += lines[j][1:].split()
                j += 1
            return pins
    raise VerifyError(f".SUBCKT {top} not found in the extracted netlist")


def canonicalise_pins(text: str, top: str, ports: list[str]) -> tuple[str, dict]:
    """Rename each top pin net whose ``|``-joined label components contain
    exactly one whole-block port name to that port name.

    A net with zero or several port names keeps its composite name and is
    recorded (``unnamed`` / ``joined``) -- never silently repaired, so a short
    between two ports shows up both here and as an LVS failure.
    """
    portset = set(ports)
    pins = top_pins(text, top)
    rename: dict[str, str] = {}
    joined: dict[str, list[str]] = {}
    unnamed: list[str] = []
    for pin in pins:
        comps = [c for c in pin.split("|")]
        # strip a "$N" duplicate-name suffix from the last component only
        hits = []
        for c in comps:
            base = re.sub(r"\$\d+$", "", c)
            if base in portset:
                hits.append(base)
        hits = sorted(set(hits))
        if len(hits) == 1:
            rename[pin] = hits[0]
        elif len(hits) > 1:
            joined[pin] = hits
        else:
            unnamed.append(pin)
    targets = Counter(rename.values())
    dup = sorted(t for t, n in targets.items() if n > 1)
    out_lines = []
    for line in text.split("\n"):
        if line.startswith("* pin "):
            # klt's per-pin comment: comma-separated pin names
            out_lines.append("* pin " + ",".join(rename.get(t, t) for t in line[6:].split(",")))
            continue
        if line.startswith("*"):
            out_lines.append(line)
            continue
        # net names contain no spaces, so token-wise replacement is exact
        out_lines.append(" ".join(rename.get(t, t) for t in line.split(" ")))
    renamed_text = "\n".join(out_lines)
    pin_after = top_pins(renamed_text, top)
    missing = sorted(portset - set(pin_after))
    return renamed_text, {
        "pins_before": len(pins),
        "pins_after": len(pin_after),
        "renamed": len(rename),
        "ports_missing": missing,
        "ports_duplicated": dup,
        "joined_pins": {k[:80]: v for k, v in joined.items()},
        "unnamed_pins": [p[:80] for p in unnamed],
    }


# --------------------------------------------------------------------------
# endpoint audit (independent of the LVS comparer)
# --------------------------------------------------------------------------


def endpoints(text: str, top: str, stub_cells: set[str]) -> dict[str, Counter]:
    """``{net: Counter({(kind, terminal): n})}`` for the top circuit of *text*.

    ``kind`` is ``nfet``/``pfet`` (terminals ``ds``/``g``/``b``) or the
    standard-cell type (terminal = its pin name). Pin names of a stub come
    from the stub's own ``.SUBCKT`` line in the same file.
    """
    subs = parse_subckts(text) if "\n.subckt" in text.lower() or text.lower().startswith(".subckt") else {}
    # parse_subckts is case-insensitive on directives, case-preserving on names
    if top not in subs:
        up = {k.upper(): k for k in subs}
        if top.upper() not in up:
            raise VerifyError(f"top {top!r} not found")
        top = up[top.upper()]
    stubs = {k: v["ports"] for k, v in subs.items() if k != top}
    nets: dict[str, Counter] = defaultdict(Counter)
    for card in subs[top]["cards"]:
        name = card[0]
        if name[0] in "Mm":
            d, g, s, b = card[1:5]
            model = card[5]
            kind = "pfet" if "pfet" in model.lower() or "pmos" in model.lower() else "nfet"
            nets[d]["%s.ds" % kind] += 1
            nets[s]["%s.ds" % kind] += 1
            nets[g]["%s.g" % kind] += 1
            nets[b]["%s.b" % kind] += 1
            continue
        body = [t for t in card[1:] if "=" not in t]
        model = body[-1]
        conns = body[:-1]
        if model in stubs:
            if len(stubs[model]) != len(conns):
                raise VerifyError(f"{name}: {len(conns)} nets for stub {model} ({len(stubs[model])} pins)")
            for pin, net in zip(stubs[model], conns):
                nets[net][f"{model}.{pin}"] += 1
        elif "nfet" in model or "pfet" in model:
            kind = "pfet" if "pfet" in model else "nfet"
            d, g, s, b = conns
            nets[d][f"{kind}.ds"] += 1
            nets[s][f"{kind}.ds"] += 1
            nets[g][f"{kind}.g"] += 1
            nets[b][f"{kind}.b"] += 1
        else:
            raise VerifyError(f"{name}: unrecognised model {model!r}")
    return nets


def stub_pin_sets(text: str) -> dict[str, list[str]]:
    return {k: v["ports"] for k, v in parse_subckts(text).items() if not v["cards"]}
