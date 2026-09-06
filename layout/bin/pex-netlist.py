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


def build_library(spec: dict, spec_dir: Path, out_dir: Path) -> dict:
    """Extract every declared cell and write the library + reports."""
    deck = spec["pdk"]["deck"]
    variant = spec["pdk"]["variant"]
    env = {**os.environ, "PDK": variant}
    expected_models = spec["expect_device_models"]
    substrate = spec["substrate_net"]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    (out_dir / "reports").mkdir(exist_ok=True)

    header = [
        "* Post-layout (parasitic) subcircuit library -- GENERATED by",
        "* layout/bin/pex-netlist.py from layout/pex/pex.json. Do not edit by",
        "* hand: `python3 layout/bin/pex-netlist.py layout/pex/pex.json --check`",
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


def check_library(spec: dict, spec_dir: Path) -> int:
    """Re-extract into a temp dir and diff against the committed evidence."""
    with tempfile.TemporaryDirectory(prefix="klt-pex-netlist-") as tmp:
        tmp_dir = Path(tmp)
        # klt is invoked with a relative path to each GDS, so the temporary
        # output directory has to sit at the same depth as layout/pex/ for
        # those "../<cell>/<cell>.gds" paths to resolve.
        work = tmp_dir / "pex"
        build_library(spec, spec_dir, _mirror_dir(spec_dir, work))
        drift: list[str] = []
        committed_lib = spec_dir / spec["library"]
        rebuilt_lib = work / spec["library"]
        if not committed_lib.exists():
            drift.append(f"{spec['library']}: missing from {spec_dir}")
        elif committed_lib.read_text() != rebuilt_lib.read_text():
            drift.append(f"{spec['library']}: rebuilt library differs from committed")
        for cell in spec["cells"]:
            rel = Path("reports") / f"{cell['name']}.extract.json"
            if not (spec_dir / rel).exists():
                drift.append(f"{rel}: missing from {spec_dir}")
                continue
            committed = json.loads((spec_dir / rel).read_text())
            rebuilt = json.loads((work / rel).read_text())
            for field in CHECK_FIELDS:
                if committed.get(field) != rebuilt.get(field):
                    drift.append(
                        f"{rel}.{field}: committed={committed.get(field)!r} "
                        f"rebuilt={rebuilt.get(field)!r}"
                    )
    if drift:
        print(f"DRIFT in {spec_dir}:", file=sys.stderr)
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

    try:
        if args.check:
            return check_library(spec, spec_dir)
        summary = build_library(spec, spec_dir, spec_dir)
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
