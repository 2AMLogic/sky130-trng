#!/usr/bin/env python3
"""Build a simulatable post-layout (parasitic) netlist library from layout/.

Reads a descriptor (``layout/pex/pex.json``) naming the composed, DRC/LVS-clean
cells under ``layout/``, runs ``klt extract --parasitics`` on each one's
committed GDS, and rewrites the results into a single ngspice-runnable
subcircuit library (``layout/pex/ro_ring5_pex.spice``) that a ``sim/``
testbench can ``.include`` in exactly the same place it would ``.include``
``design/ro_array_core.spice``.

Usage
-----

    python3 layout/bin/pex-netlist.py layout/pex/pex.json
    python3 layout/bin/pex-netlist.py layout/pex/pex.json --check

``--check`` regenerates everything into a temporary directory and diffs it
against what is committed (the library byte for byte, each extraction report
on its verdict-bearing fields), without touching the committed files -- the
same contract ``layout/bin/compose-cell.py --check`` and
``design/netlist.py --check`` offer.

Let the tool do what the tool does
----------------------------------

``klt extract`` writes device cards two different ways, and which one you get
decides how much work is left over. **Run without ``--pdk``** it emits
deck-native ``M`` cards naming the extraction deck's own device classes
(``M$1 ... nfet L=2U W=0.42U``) -- tool-neutral, and not runnable against
sky130's ngspice library, which has no ``.model nfet`` at all (its devices
are ``.subckt sky130_fd_pr__nfet_01v8 d g s b``). **Run WITH ``--pdk
sky130A``** it emits exactly the card this repo needs:

    X$1 ... sky130_fd_pr__nfet_01v8 L=2 W=0.42 AS=0.1764 AD=0.1764 ...

-- the PDK's own device subcircuit, with *unitless* geometry, which is
precisely the ``.option scale=1u`` convention every ``sim/`` deck in this
repo already runs under. So this script passes ``--pdk`` and does **no**
device-card or unit rewriting of its own. An earlier revision hand-rolled
both, having only ever run the bare form; that was duplicated tool
capability, not a tool gap, and re-deriving it here would have been exactly
the kind of inaccurate friction report ``CLAUDE.md`` warns against filing.

What it does instead is **verify** that contract on every run rather than
assume it (:func:`check_device_card`): every device card must be an ``X``
card, its model must be one the descriptor declares in
``expect_device_models``, and its geometry values must carry no unit suffix.
A future ``klt`` that changed any of the three would silently mis-scale
every device in a deck that ran at ``scale=1u``; here it is a hard error.

What is left for this script
----------------------------

Three things, none of which ``--pdk`` addresses:

1. **Net names contain ``|``** (and its escaped spelling ``\\x7c``). A cell
   built by the two-pass ``"stages"`` composition carries both a pin label
   and a net label on one physical net, and the extractor joins them
   (``mnt_g|vddr``, ``mnab_y|mpa_y|mpb_y|y``). ``layout/README.md`` §
   "Scouting ``--parasitics``" establishes those names are *consistent* --
   they do not silently split a node -- but they are still awkward to
   reference from a testbench, and ``$``/``|``/``\\`` are characters no deck
   should have to quote. Each joined name is renamed to the design-level
   name for that net, declared per cell in the descriptor's ``net_aliases``
   so the choice is reviewable rather than inferred from spelling, and the
   rename is checked to be injective so it can never merge two nets.

2. **The substrate return node is not a pin.** Every net-to-substrate
   capacitor returns to a node named ``vsubs`` which the extractor ties to
   ground only through ``Rvsubs_dctie vsubs 0 1e+12``, and which is neither
   a ``.SUBCKT`` pin nor ``.GLOBAL``-declared -- so *instantiating* the
   extracted cell (which is the only way to build a ring out of it) buries
   ``vsubs`` as a per-instance local node the testbench cannot reach, and
   the whole ground-capacitance model hangs off a node isolated from ground
   by 1 TOhm. ``layout/README.md`` measured the consequence (~1% impedance
   error at 1 GHz, ~17% at 10 GHz) and filed it upstream as
   klayout-tools#1503. This script emits the ``.GLOBAL vsubs`` that issue's
   write-up named as one of the two acceptable workarounds, and every
   record minted from the resulting library says which one it used.

3. **A hierarchy, not one DUT.** ``klt pex`` already automates
   extract-and-re-simulate for the case of *one* layout standing in for
   *one* schematic DUT inside a testbench that ``.include``s it. This
   design's post-layout ring is five instances of two different cells, at
   four different widths, plus a buffer -- nine extracted cells composed
   into one library that a testbench instantiates hierarchically, driven by
   this repo's own ``sim/bin/corner-run.py`` (which owns its record
   convention, PDK pin and record-id scheme). That is why the campaign is
   built here rather than on ``klt pex``; see ``layout/pex/README.md``.

What the rewrite deliberately does NOT do
-----------------------------------------

No R or C value is touched, no parasitic element is dropped or merged, no
device parameter other than its unit spelling is changed, and no
connectivity is altered: the ``__tN`` per-terminal leg nodes the extractor's
star model introduces are preserved exactly as extracted (renamed only where
their prefix is a joined net name). The rewritten library is a spelling
change plus a wrapper, and ``--check`` re-derives it from the committed GDS
so a reviewer never has to take that on trust.

The wrapper
-----------

The extractor promotes every labelled pin to a ``.SUBCKT`` port, including
nets that are internal in the schematic (``ro_stage``'s ``ny``/``py``, which
are ports of the *layout* only because the two-pass composition had to
promote them). A testbench built against that port list would have to invent
and thread a unique node per instance for each of them. So each cell is
emitted twice: ``<name>__core`` with the extractor's own port list, and
``<name>`` -- a wrapper with the *design's* port list
(``design/ro_array_core.spice``'s own ``.subckt`` line, declared per cell as
``ports``) that instantiates it and leaves the promoted-internal ports as
local nodes. A ``sim/`` deck instantiating ``ro_stage_pex_wstv0p42`` then
reads exactly like the pre-layout deck instantiating ``ro_stage``, which is
what makes a pre-vs-post comparison a one-token diff.

What ``--check`` does NOT treat as drift (issue #93)
----------------------------------------------------

``klt extract`` names an unlabelled internal net after a counter its own
KLayout ``l2n.extract_netlist()`` call assigns (``\\$3``), and stamps every
net with a ``net_id`` from the same counter. Neither is a stable contract
across ``klt``/KLayout builds -- upstream says so explicitly
(klayout-tools#1063, and its documentation follow-up #1072, both closed:
"compare via ``klt lvs`` (topological), not by byte-diffing extracted
netlist text"). Measured here on 2026-09-07 against the nine
``layout/pex/pex.json`` cells: three of them relabel one anonymous net
``\\$3`` -> ``\\$4`` and permute every net's ``net_id``, with **every** R
value, C value, coupling value, count, terminal and connection identical.

So :func:`canonical_parasitics` rewrites those two identifiers to a
*structural* key -- an anonymous net is named after the sorted
``<device>.<terminal>`` list it actually attaches to -- on **both** sides
before the report comparison. A pure renumbering therefore stops being
reported as verdict drift, while any change to an R, a C, a count, a
terminal or a connection still is.

The library text is deliberately **still** compared byte for byte: the same
counter reaches the composed library in three different spellings (the node
token ``n3``, the extractor's own element names ``R_3_t0``/``C_3``, and its
per-element ``* device instance _3_t0`` provenance comments), only the first
of which sits at a parseable node position. Canonicalizing the other two
would mean pattern-matching ``klt``'s element-naming derivation -- binding
this repo *harder* to the very spelling upstream declines to make a
contract. A loud, once-per-``klt``-move failure is the better trade, so
instead ``--check`` **classifies** it: when the library text differs but
every canonicalized parasitic value agrees, it says so in as many words, and
prints the committed evidence's own ``provenance.klt_version`` next to the
running one and to ``layout/pdk.json``'s ``klt_version_pin``, so the result
explains itself instead of dumping a raw diff.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klt_common import BuildError, run_klt, write_json  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Verdict-bearing fields --check compares in each cell's extraction report.
CHECK_FIELDS = (
    "status",
    "device_count",
    "net_count",
    "pin_count",
    "device_counts",
    "parasitics",
)

#: Geometry parameters a device card may carry, all of which must be
#: unitless for this library's `.option scale=1u` contract to hold.
_GEOM_PARAMS = ("L", "W", "AS", "AD", "PS", "PD", "NRD", "NRS")

#: An extractor-anonymous net, optionally with its per-terminal leg suffix:
#: `\$3` (the hub) and `\$3__t0` (one leg). The digits are KLayout's own
#: net counter, which is not stable across klt/KLayout builds -- see this
#: module's docstring and klayout-tools#1063/#1072.
_ANON_NET = re.compile(r"^(\\?\$\d+)(__t\d+)?$")


# --------------------------------------------------------------------------
# Canonicalizing the extractor's own net numbering (issue #93)
# --------------------------------------------------------------------------


def anonymous_base(name: str) -> str | None:
    """Return *name*'s anonymous-net hub, or ``None`` if it is not one.

    ``\\$3`` -> ``\\$3``; ``\\$3__t0`` -> ``\\$3``; ``a``/``a__t0`` -> None.
    """
    match = _ANON_NET.match(name)
    return match.group(1) if match else None


def _structural_key(net: dict) -> str:
    """A name for one anonymous net that does not use the extractor's counter.

    Derived from the net's own device attachments -- the sorted
    ``<device>.<terminal>`` list -- so two extractions of the same GDS agree
    on it regardless of what order KLayout happened to number its nets in.
    """
    terminals = sorted(
        f"{t.get('device')}.{t.get('terminal')}" for t in net.get("terminals", [])
    )
    if not terminals:
        raise BuildError(
            f"anonymous net {net.get('net')!r} has no device terminals, so it "
            "has no structural identity to canonicalize against"
        )
    return "\\$anon(" + ",".join(terminals) + ")"


def canonical_parasitics(parasitics: dict) -> dict:
    """Rewrite extractor-internal net identifiers to structural ones.

    Returns a copy of a report's ``parasitics`` block in which

    - every anonymous net (``\\$N``, and the ``\\$N__tK`` leg nodes derived
      from it) is renamed to :func:`_structural_key`'s device-terminal key,
      wherever it appears (``net``, ``hub_net``, ``terminals[].leg_net``,
      ``coupled[].net``);
    - every ``net_id`` -- the raw counter value -- is dropped;
    - ``nets`` and each net's ``coupled`` list are sorted by (canonical) name,
      since their order follows the same counter.

    **Nothing else is touched.** Every R, C, coupling value, count, device,
    terminal and connection is passed through unchanged, so a real
    electrical or topological difference still compares unequal. This exists
    only so that the identifiers upstream explicitly declines to make a
    contract (klayout-tools#1063/#1072) stop being reported as verdict drift
    -- see this module's docstring, and issue #93 for the measurement that
    motivated it.
    """
    nets = parasitics.get("nets")
    if not isinstance(nets, list):
        return parasitics

    mapping: dict[str, str] = {}
    claimed: dict[str, str] = {}
    for net in nets:
        base = anonymous_base(str(net.get("net", "")))
        if base is None:
            continue
        key = _structural_key(net)
        previous = claimed.setdefault(key, base)
        if previous != base:
            raise BuildError(
                f"anonymous nets {previous!r} and {base!r} share the structural "
                f"key {key!r} -- canonicalizing them would merge two distinct "
                "nets, so this report cannot be compared this way"
            )
        mapping[base] = key

    def rename(name: str) -> str:
        base = anonymous_base(name)
        if base is None or base not in mapping:
            return name
        return mapping[base] + name[len(base) :]

    out = dict(parasitics)
    canonical_nets = []
    for net in nets:
        entry = {k: v for k, v in net.items() if k != "net_id"}
        entry["net"] = rename(str(net.get("net", "")))
        if "hub_net" in entry:
            entry["hub_net"] = rename(str(entry["hub_net"]))
        entry["terminals"] = [
            {
                **t,
                **({"leg_net": rename(str(t["leg_net"]))} if "leg_net" in t else {}),
            }
            for t in net.get("terminals", [])
        ]
        entry["coupled"] = sorted(
            ({**c, "net": rename(str(c.get("net", "")))} for c in net.get("coupled", [])),
            key=lambda c: c["net"],
        )
        canonical_nets.append(entry)
    out["nets"] = sorted(canonical_nets, key=lambda n: n["net"])
    return out


# --------------------------------------------------------------------------
# Netlist rewriting
# --------------------------------------------------------------------------


def join_continuations(text: str) -> list[str]:
    """Fold ngspice ``+`` continuation lines into their logical line."""
    out: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("+"):
            if not out:
                raise BuildError("netlist starts with a continuation line")
            out[-1] = out[-1].rstrip() + " " + raw[1:].strip()
        else:
            out.append(raw.rstrip())
    return out


def canonicalize(name: str, aliases: dict[str, str]) -> str:
    """Rename a joined net name (and its ``\\x7c``-escaped spelling)."""
    for joined, canonical in aliases.items():
        escaped = joined.replace("|", "\\x7c")
        if name == joined or name == canonical:
            return canonical
        if name.startswith(escaped):
            return canonical + name[len(escaped) :]
        if name.startswith(joined):
            return canonical + name[len(joined) :]
    if "|" in name or "\\x7c" in name:
        raise BuildError(
            f"net name {name!r} is a joined extractor name with no "
            "net_aliases entry -- add one to the cell's descriptor entry"
        )
    return name


def sanitize(name: str) -> str:
    """Strip characters no ngspice deck should have to quote.

    The extractor names an unlabelled internal net after its own device
    index (``\\$3``, escaped) and its device instances the same way
    (``M$3``). ``$`` is an ngspice in-line comment character and ``\\`` is
    an escape, so both are replaced -- ``$`` by ``n`` (giving ``n3`` /
    ``Mn3``), ``\\`` dropped. ``rewrite_cell`` asserts the mapping stays
    injective per cell, so a rename can never silently merge two nets.
    """
    return name.replace("\\", "").replace("$", "n")


def check_device_card(line: str, expected_models: list[str]) -> str:
    """Verify one extracted device card against this library's contract.

    Returns the card unchanged. Raises :class:`BuildError` if it is not an
    ``X`` (subcircuit-call) card, if its model is not one the descriptor
    declares, or if any geometry value carries a unit suffix.

    See this module's docstring: ``klt extract --pdk`` already emits exactly
    the form this repo's decks need, so the job here is to *hold* that
    contract, not to re-implement it. All three failure modes would
    otherwise be silent -- an ``M`` card would fail to bind at all (loud),
    but a wrong model name binds to the wrong device and a stray ``U``
    suffix mis-scales the device by 1e-6 under ``.option scale=1u``, and
    both of those simulate cleanly.
    """
    tokens = line.split()
    name, model = tokens[0], tokens[5]
    if not name.upper().startswith("X"):
        raise BuildError(
            f"device card {name} is not a subcircuit call -- pass --pdk to "
            f"klt extract so it writes the PDK's own device subcircuits "
            f"(line: {line})"
        )
    if model not in expected_models:
        raise BuildError(
            f"device card {name} names model {model!r}, which is not in the "
            f"descriptor's expect_device_models {expected_models}"
        )
    for token in tokens[6:]:
        key, _, value = token.partition("=")
        if key.upper() not in _GEOM_PARAMS:
            raise BuildError(f"unexpected device parameter {token!r} on {name}")
        if not re.fullmatch(r"[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", value):
            raise BuildError(
                f"device parameter {token!r} on {name} is not a bare unitless "
                "number -- this library's .option scale=1u contract requires "
                "unsuffixed geometry (klt extract --pdk emits it that way)"
            )
    return line


def rewrite_cell(
    netlist_text: str,
    *,
    core_name: str,
    aliases: dict[str, str],
    expected_models: list[str],
) -> tuple[list[str], list[str]]:
    """Rewrite one extracted cell into ``<core_name>`` + its port list.

    Returns ``(lines, ports)``. Comment lines from the extractor's own
    parasitic-model preamble are dropped (they are reproduced once, at the
    top of the library, instead of once per cell); its per-device provenance
    comments are kept.
    """
    renames: dict[str, str] = {}

    def rename(token: str) -> str:
        out = sanitize(canonicalize(token, aliases))
        previous = renames.setdefault(out, token)
        if previous != token:
            raise BuildError(
                f"{core_name}: names {previous!r} and {token!r} both rewrite "
                f"to {out!r} -- renaming would merge two distinct nets"
            )
        return out

    lines: list[str] = []
    ports: list[str] = []
    in_cell = False
    for line in join_continuations(netlist_text):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith(".SUBCKT"):
            in_cell = True
            ports = [rename(tok) for tok in stripped.split()[2:]]
            lines.append(f".subckt {core_name} {' '.join(ports)}")
            continue
        if upper.startswith(".ENDS"):
            in_cell = False
            lines.append(f".ends {core_name}")
            continue
        if not in_cell:
            continue  # extractor preamble comments, reproduced library-wide
        if stripped.startswith("*"):
            lines.append(stripped)
            continue
        tokens = stripped.split()
        head = tokens[0].upper()
        if head.startswith(("X", "M")):
            # A device card's trailing tokens are the model name and
            # `PARAM=value` geometry, not node names -- only the instance
            # name and its four terminals go through the renamer.
            renamed = [rename(tok) for tok in tokens[:5]] + tokens[5:]
            lines.append(check_device_card(" ".join(renamed), expected_models))
        elif head[0] in "RC":
            # `<name> <node> <node> <value>` -- the value is not a name.
            renamed = [rename(tok) for tok in tokens[:3]] + tokens[3:]
            lines.append(" ".join(renamed))
        else:
            raise BuildError(f"unhandled element card in extracted netlist: {stripped}")
    if not ports:
        raise BuildError(f"{core_name}: no .SUBCKT line in the extracted netlist")
    return lines, ports


def wrapper_lines(cell: dict, core_name: str, core_ports: list[str]) -> list[str]:
    """The design-port-order wrapper described in the module docstring."""
    ports = cell["ports"]
    unknown = [p for p in ports if p not in core_ports]
    if unknown:
        raise BuildError(
            f"{cell['name']}: declared ports {unknown} are not pins of the "
            f"extracted cell (extracted pins: {core_ports})"
        )
    internal = [p for p in core_ports if p not in ports]
    return [
        f"* {cell['name']} -- design-port-order wrapper over {core_name}.",
        f"* Promoted-internal layout pins kept local here: "
        f"{', '.join(internal) if internal else '(none)'}",
        f".subckt {cell['name']} {' '.join(ports)}",
        f"xpex {' '.join(core_ports)} {core_name}",
        f".ends {cell['name']}",
    ]


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------


def library_header(substrate: str, descriptor: str) -> list[str]:
    """The generated library's banner, naming the descriptor that built it.

    *descriptor* is the repo-relative descriptor path actually invoked (e.g.
    ``layout/pex/pex.json`` or ``layout/pex/pex-sampler.json``) -- see issue
    #94: a header that hardcodes one descriptor regardless of which one ran
    is a false-reassurance failure, since the quoted ``--check`` command
    would re-verify the *wrong* library.

    Split out of :func:`build_library` so a unit test can assert the header
    text for a given descriptor without running ``klt`` (:mod:`test_pex_netlist`).
    """
    return [
        "* Post-layout (parasitic) subcircuit library -- GENERATED by",
        f"* layout/bin/pex-netlist.py from {descriptor}. Do not edit by",
        f"* hand: `python3 layout/bin/pex-netlist.py {descriptor} --check`",
        "* re-extracts every cell from its committed GDS and fails if this file",
        "* and that extraction disagree.",
        "*",
        "* Each cell below is `klt extract --pdk <variant> --parasitics` output",
        "* over a composed, DRC-clean and LVS-clean cell under layout/. --pdk is",
        "* what makes its device cards subcircuit calls on the PDK's own devices",
        "* with unitless geometry (this repo's decks run at .option scale=1u), so",
        "* NO device card, geometry value, R value, C value or connection is",
        "* rewritten here. Two things are: extractor-joined net names are renamed",
        "* to their design-level names, and a design-port-order wrapper is added",
        "* per cell. See layout/bin/pex-netlist.py's module docstring for why,",
        "* and layout/pex/README.md for what the parasitic model does and does",
        "* not contain.",
        "*",
        f"* Substrate return node: `{substrate}`, declared .global below --",
        "* klayout-tools#1503 (the extractor scopes it per-instance, which",
        "* isolates every ground capacitance behind a 1 TOhm tie once the cell",
        "* is instantiated rather than simulated flat). A deck including this",
        "* library MUST tie the node itself; every sim/ record minted from it",
        "* states which tie it used.",
        "",
        f".global {substrate}",
        "",
    ]


def build_library(spec: dict, spec_dir: Path, out_dir: Path, descriptor: str) -> dict:
    """Extract every declared cell and write the library + reports.

    *descriptor* is the repo-relative descriptor path this run was actually
    invoked with (``layout/pex/pex.json`` or ``layout/pex/pex-sampler.json``)
    -- it names itself, correctly, in the generated library's own header
    (:func:`library_header`, issue #94).
    """
    deck = spec["pdk"]["deck"]
    variant = spec["pdk"]["variant"]
    env = {**os.environ, "PDK": variant}
    expected_models = spec["expect_device_models"]
    substrate = spec["substrate_net"]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    (out_dir / "reports").mkdir(exist_ok=True)

    header = library_header(substrate, descriptor)

    body: list[str] = []
    summary: list[dict] = []
    for cell in spec["cells"]:
        name = cell["name"]
        core_name = f"{name}__core"
        raw_rel = Path("raw") / f"{name}.pex.spice"
        gds_rel = Path(cell["gds"])
        report = run_klt(
            [
                "extract",
                str(gds_rel),
                "--deck",
                deck,
                # --pdk is what makes the written device cards subcircuit
                # calls on the PDK's own devices, with unitless geometry --
                # see this module's docstring. Without it klt writes
                # deck-native M cards that sky130's ngspice library cannot
                # bind at all.
                "--pdk",
                variant,
                "--parasitics",
                "-o",
                str(raw_rel),
            ],
            env=env,
            cwd=out_dir,
        )
        write_json(out_dir / "reports" / f"{name}.extract.json", report)
        lines, core_ports = rewrite_cell(
            (out_dir / raw_rel).read_text(),
            core_name=core_name,
            aliases=cell.get("net_aliases", {}),
            expected_models=expected_models,
        )
        body.extend(
            [
                "*" + "-" * 71,
                f"* {name} -- post-layout, from {cell['gds']}",
                f"* klt extract --parasitics: {report['device_count']} devices, "
                f"{report['net_count']} nets",
                "*" + "-" * 71,
                *lines,
                "",
                *wrapper_lines(cell, core_name, core_ports),
                "",
            ]
        )
        summary.append(
            {
                "cell": name,
                "devices": report["device_count"],
                "nets": report["net_count"],
                "parasitics": report.get("parasitics", {}),
            }
        )

    (out_dir / spec["library"]).write_text("\n".join([*header, *body]))
    return {"cells": summary, "library": spec["library"]}


def klt_version_pin() -> str:
    """``layout/pdk.json``'s ``klt_version_pin``, or ``"(unknown)"``."""
    try:
        return json.loads((REPO_ROOT / "layout" / "pdk.json").read_text())[
            "klt_version_pin"
        ]
    except (OSError, KeyError, ValueError):
        return "(unknown)"


def _tool_stamp(report: dict) -> str:
    """``klt X / KLayout Y`` from one extraction report's own provenance."""
    provenance = report.get("provenance") or {}
    return (
        f"klt {provenance.get('klt_version', '(unknown)')} / "
        f"KLayout {provenance.get('klayout_version', '(unknown)')}"
    )


def compare_report(committed: dict, rebuilt: dict, label: str) -> list[str]:
    """Diff one extraction report's verdict-bearing fields, compactly.

    ``parasitics`` is compared through :func:`canonical_parasitics` on both
    sides, so the extractor's own net numbering (which upstream declines to
    make a contract -- klayout-tools#1063/#1072) is not reported as drift
    while every R, C, count, terminal and connection still is. The parasitics
    diff is reported per *net* rather than by printing the whole block, which
    on this repo's nine cells is the difference between a readable failure
    and ~99 kB of JSON (issue #93).
    """
    drift: list[str] = []
    for field in CHECK_FIELDS:
        if field == "parasitics":
            continue
        if committed.get(field) != rebuilt.get(field):
            drift.append(
                f"{label}.{field}: committed={committed.get(field)!r} "
                f"rebuilt={rebuilt.get(field)!r}"
            )
    left = canonical_parasitics(committed.get("parasitics") or {})
    right = canonical_parasitics(rebuilt.get("parasitics") or {})
    for key in sorted(set(left) | set(right)):
        if key == "nets":
            continue
        if left.get(key) != right.get(key):
            drift.append(
                f"{label}.parasitics.{key}: committed={left.get(key)!r} "
                f"rebuilt={right.get(key)!r}"
            )
    by_name_left = {n["net"]: n for n in left.get("nets", [])}
    by_name_right = {n["net"]: n for n in right.get("nets", [])}
    for name in sorted(set(by_name_left) - set(by_name_right)):
        drift.append(f"{label}.parasitics: net {name!r} is committed but not rebuilt")
    for name in sorted(set(by_name_right) - set(by_name_left)):
        drift.append(f"{label}.parasitics: net {name!r} is rebuilt but not committed")
    for name in sorted(set(by_name_left) & set(by_name_right)):
        if by_name_left[name] != by_name_right[name]:
            drift.append(
                f"{label}.parasitics: net {name!r} differs "
                f"(committed={by_name_left[name]!r} rebuilt={by_name_right[name]!r})"
            )
    return drift


def check_library(spec: dict, spec_dir: Path, descriptor: str) -> int:
    """Re-extract into a temp dir and diff against the committed evidence.

    *descriptor* flows through to :func:`build_library` so the rebuilt
    library's header names the same descriptor the committed one does --
    otherwise the two would differ on header text alone even when nothing
    else drifted (issue #94).
    """
    with tempfile.TemporaryDirectory(prefix="klt-pex-netlist-") as tmp:
        tmp_dir = Path(tmp)
        # klt is invoked with a relative path to each GDS, so the temporary
        # output directory has to sit at the same depth as layout/pex/ for
        # those "../<cell>/<cell>.gds" paths to resolve.
        work = tmp_dir / "pex"
        build_library(spec, spec_dir, _mirror_dir(spec_dir, work), descriptor)
        library_drift: list[str] = []
        report_drift: list[str] = []
        committed_lib = spec_dir / spec["library"]
        rebuilt_lib = work / spec["library"]
        if not committed_lib.exists():
            library_drift.append(f"{spec['library']}: missing from {spec_dir}")
        elif committed_lib.read_text() != rebuilt_lib.read_text():
            library_drift.append(
                f"{spec['library']}: rebuilt library differs from committed"
            )
        stamps: list[tuple[str, str, str]] = []
        for cell in spec["cells"]:
            rel = Path("reports") / f"{cell['name']}.extract.json"
            if not (spec_dir / rel).exists():
                report_drift.append(f"{rel}: missing from {spec_dir}")
                continue
            committed = json.loads((spec_dir / rel).read_text())
            rebuilt = json.loads((work / rel).read_text())
            stamps.append(
                (cell["name"], _tool_stamp(committed), _tool_stamp(rebuilt))
            )
            report_drift.extend(compare_report(committed, rebuilt, str(rel)))
        drift = [*library_drift, *report_drift]
    if drift:
        print(f"DRIFT in {spec_dir}:", file=sys.stderr)
        mismatched: dict[tuple[str, str], list[str]] = {}
        for name, committed_stamp, rebuilt_stamp in stamps:
            if committed_stamp != rebuilt_stamp:
                mismatched.setdefault((committed_stamp, rebuilt_stamp), []).append(name)
        for (committed_stamp, rebuilt_stamp), cells in mismatched.items():
            print(
                f"  provenance: {len(cells)} cell(s) committed by "
                f"{committed_stamp}; this rebuild by {rebuilt_stamp}\n"
                f"    ({', '.join(cells)})",
                file=sys.stderr,
            )
        print(
            f"  layout/pdk.json klt_version_pin: {klt_version_pin()}", file=sys.stderr
        )
        if library_drift and not report_drift and committed_lib.exists():
            print(
                "  NOTE: the library text differs, but every verdict-bearing "
                "parasitic value\n"
                "        matches after canonicalizing the extractor's own net "
                "numbering. That\n"
                "        numbering is explicitly not a stable contract across "
                "klt/KLayout builds\n"
                "        (klayout-tools#1063, #1072), so this is a relabeling, "
                "not an electrical\n"
                "        or topological difference. Regenerate the library on "
                "the klt named above\n"
                "        (and re-stamp the affected sim/ records' PEX_LIB "
                "provenance) to clear it.",
                file=sys.stderr,
            )
        for entry in drift:
            print(f"  {entry}", file=sys.stderr)
        return 1
    print(f"{spec_dir}: rebuild matches committed evidence")
    return 0


def _mirror_dir(spec_dir: Path, work: Path) -> Path:
    """Make *work* resolve the descriptor's relative GDS paths.

    The descriptor names each GDS relative to ``layout/pex/`` (e.g.
    ``../ro_stage/ro_stage.gds``) so that no absolute path leaks into klt's
    committed provenance. ``--check`` therefore symlinks the real
    ``layout/`` next to the temporary output directory rather than copying
    a GDS tree.
    """
    work.mkdir(parents=True, exist_ok=True)
    for sibling in spec_dir.parent.iterdir():
        if sibling.is_dir() and sibling.name != spec_dir.name:
            link = work.parent / sibling.name
            if not link.exists():
                link.symlink_to(sibling, target_is_directory=True)
    return work


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="path to layout/pex/pex.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-extract into a temp dir and diff against the committed "
        "library/reports instead of overwriting them",
    )
    args = parser.parse_args(argv)

    spec_path = args.spec.resolve()
    spec = json.loads(spec_path.read_text())
    spec_dir = spec_path.parent
    # Repo-relative, so no absolute home path leaks into the generated
    # library's own header -- the same constraint _mirror_dir's docstring
    # states for the GDS paths inside the descriptor (issue #94).
    descriptor = f"layout/pex/{spec_path.name}"

    try:
        if args.check:
            return check_library(spec, spec_dir, descriptor)
        summary = build_library(spec, spec_dir, spec_dir, descriptor)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"library: layout/pex/{summary['library']}")
    for cell in summary["cells"]:
        par = cell["parasitics"] or {}
        print(
            f"  {cell['cell']}: {cell['devices']} devices, {cell['nets']} nets, "
            f"R={par.get('total_resistance_ohm', 'n/a')} ohm, "
            f"C={par.get('total_capacitance_ff', 'n/a')} fF"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
