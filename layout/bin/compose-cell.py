#!/usr/bin/env python3
"""Compose one layout cell from klt primitive generators and verify it.

Reads a cell descriptor (``layout/<cell>/cell.json``) and drives the whole
klayout-tools (``klt``) layout chain for that cell, end to end:

    klt gen (per device/tap block)
      -> klt gen-compose (place + route)
      -> klt drc          (rule sign-off)
      -> klt extract      (layout-derived netlist)
      -> klt lvs          (extracted vs. design/*.spice reference)

Every step's JSON response is written next to the descriptor, so the
committed contents of ``layout/<cell>/`` are the full, re-checkable evidence
trail for that cell rather than a bare GDS.

Usage
-----

    python3 layout/bin/compose-cell.py layout/ro_buf/cell.json
    python3 layout/bin/compose-cell.py layout/ro_buf/cell.json --check

``--check`` re-runs everything into a temporary directory and diffs the
verdict-bearing fields against what is committed, without touching the
committed files -- the layout sibling of ``design/netlist.py --check``.

Descriptor shape
----------------

See ``layout/README.md`` and ``layout/ro_buf/cell.json``. In brief::

    {
      "cell": "ro_buf",
      "pdk": {"variant": "sky130A", "deck": "sky130"},
      "blocks": [
        {"id": "mn", "generator": "mos_array", "cell_name": "nfet_...",
         "params": {...}, "orientation": "none"}
      ],
      "placement": {"strategy": "explicit", "order": [...],
                    "origins_um": {...}},
      "routing": {"layer_role": "metal", "width_um": 0.17},
      "connectivity": [...],
      "pins": [...],
      "lvs": {"reference": "design/ro_array_core.spice", "subckt": "ro_buf"}
    }

Two-pass composition (``"stages"``, #27 step 2)
------------------------------------------------

Some gates have two nets that would short if both were routed on the same
metal layer in one ``klt gen-compose`` call -- ``ro_stage``/``ro_nand2``'s
always-on starve devices cross-couple their gates to the *opposite* rail
(``Mph.g = vss``, ``Mnt.g = vddr``), so wiring both crossing nets on the
base ``"metal"`` role in a single pass is not routable without one net
running through the other's block or backbone (see ``layout/README.md``'s
"Composing a gate" section). A cell.json may replace its top-level
``blocks``/``placement``/``routing``/``connectivity``/``pins`` fields with a
``"stages"`` list instead, each entry shaped like those same fields plus a
``"name"`` (required on every stage but the last, which is always named
after the cell itself and always ends up as ``compose.request.json``/
``compose.response.json`` with no prefix -- so ``--check`` and the DRC/
extract/LVS steps below are completely unaware whether a cell used one
stage or several). A later stage's ``blocks[]`` entry may reference an
earlier stage's own composed cell instead of a fresh ``klt gen`` call via
``{"id": ..., "from_stage": "<earlier stage's name>"}``, which resolves to
that stage's own ``<name>.compose.response.json`` -- a valid
``generator_report`` in its own right, since ``klt gen-compose``'s response
already carries ``generator: "gen-compose"`` plus a composed-frame
``ports[]`` promoted from that stage's own ``pins[]`` (this is what the CLI
itself calls composition "nesting"). The usual second stage routes the two
gate-crossing nets on ``"metal2"`` (sky130 met1) with an automatic via-drop
back to each pin's own base-``"metal"``-role pad, over the first stage's
already-composed cell -- see ``layout/ro_stage/cell.json`` for a worked
example and ``layout/ro_stage/README.md`` for why each net landed on the
layer it did.

The reference-netlist unit rewrite
----------------------------------

``design/*.spice`` is xschem's own export and is simulated under
``.option scale=1u`` (see any ``sim/*/testbench/*.spice``), so its device
cards carry *unitless* geometry that means micrometres: ``L=0.15 W=0.84``
is a 0.15 um x 0.84 um device.

``klt lvs``'s ``reference.form: "subckt-call"`` converter reads an unsuffixed
value as SI **metres** and rescales it, turning ``L=0.15`` into
``L=150000U`` -- a 0.15 m gate. The compare then fails with a
``device.unmatched``/``net.unmatched`` avalanche and no diagnostic pointing
at the units. Reported upstream (generically) as
2AMLogic/klayout-tools#1492.

Until that is fixed this script appends an explicit ``u`` suffix to the
``L=``/``W=`` values of the extracted reference subckt (and to the values of
any parameter substituted into them), which the converter then reads
correctly. Only the unit spelling changes -- no topology, no net names, no
device count, and the rewritten reference is written to disk
(``<cell>.ref.spice``) so a reviewer can diff it against the source subckt.
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

#: Verdict-bearing fields --check compares, per artifact.
CHECK_FIELDS: dict[str, tuple[str, ...]] = {
    "drc.json": ("status", "violation_count"),
    "extract.json": ("status", "device_count", "net_count", "device_counts"),
    "lvs.json": ("status", "mismatch_count", "error_count", "counts"),
    "compose.response.json": ("cell_name", "bbox_um"),
}


# --------------------------------------------------------------------------
# Reference-netlist extraction
# --------------------------------------------------------------------------

_SUBCKT_RE = r"^\.subckt\s+{name}\b"
_GEOMETRY_RE = re.compile(r"\b([LW])=([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(?![0-9a-zA-Z.])")


def extract_subckt(netlist: Path, subckt: str) -> list[str]:
    """The ``.subckt <subckt> ... .ends`` block of ``netlist``, as lines."""
    start = re.compile(_SUBCKT_RE.format(name=re.escape(subckt)), re.IGNORECASE)
    lines = netlist.read_text().splitlines()
    for index, line in enumerate(lines):
        if start.match(line):
            for end in range(index, len(lines)):
                if lines[end].lower().startswith(".ends"):
                    return lines[index : end + 1]
            raise BuildError(f"{netlist}: .subckt {subckt} has no .ends")
    raise BuildError(f"{netlist}: no .subckt {subckt}")


def build_reference(
    lines: list[str],
    *,
    params: dict[str, float] | None,
    drop_prefixes: tuple[str, ...],
) -> list[str]:
    """Rewrite an xschem-exported subckt into a klt-lvs-ready reference.

    Four transformations, each deliberately minimal and each visible in the
    written-out result:

    1. ``params`` values are substituted for the subckt's own parameter names
       wherever they appear as an ``=<name>`` value token (this design's
       starve devices are sized ``L=lstv W=wstv``, so this covers ``L=``/
       ``W=`` in particular, but is not limited to them), and the parameter
       defaults are dropped from the ``.subckt`` line. A bare occurrence of
       the parameter name *inside* a quoted expression (e.g. the ``wstv`` in
       ``ad='int((1 + 1)/2) * wstv / 1 * 0.29'``, not immediately preceded by
       ``=``) is deliberately left unevaluated, unchanged from this script's
       original single-subckt behaviour -- see "The LVS match is
       width-sensitive" in ``layout/README.md`` for why that is fine (``klt
       lvs`` does not compare ``ad``/``as``/``pd``/``ps`` for these devices).
    2. A pass-through keyword argument on an instance-call line (``name=name``
       -- e.g. ``xg ro en n1 vddr vss ro_nand2 wstv=wstv lstv=lstv cld=cld``,
       ``ro_ring5``'s own forwarding of its parameters to each sub-gate
       instance) is dropped entirely rather than substituted, once a
       multi-subckt reference (``lvs.dependencies``, below) needs to
       instantiate one already-parameterized subckt from another: the callee
       subckt's own header no longer declares that parameter (transformation
       1 already stripped it, replacing every internal use with a literal),
       so passing it by keyword would name an undeclared parameter.
    3. Element cards whose name starts with one of ``drop_prefixes`` are
       removed -- for this design that is ``ro_stage``/``ro_nand2``'s ``Cld``
       lumped load capacitor, a *simulation* load model with no physical
       counterpart in the layout, not a device the layout omits.
    4. Unitless ``L=``/``W=`` values gain an explicit ``u`` suffix -- see this
       module's docstring for why (klayout-tools#1492).
    """
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(".subckt"):
            # Drop `name=value` parameter defaults from the port list.
            head = [tok for tok in stripped.split() if "=" not in tok]
            out.append(" ".join(head))
            continue
        if drop_prefixes and stripped.upper().startswith(
            tuple(p.upper() for p in drop_prefixes)
        ):
            continue
        if params:
            for name, value in params.items():
                line = re.sub(rf"\s+{re.escape(name)}={re.escape(str(name))}\b", "", line)
                line = re.sub(rf"=({re.escape(name)})\b", f"={value}", line)
        out.append(_GEOMETRY_RE.sub(r"\1=\2u", line))
    return out


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------


def compose_stage(
    stage: dict,
    *,
    is_final: bool,
    cell: str,
    variant: str,
    env: dict[str, str],
    out_dir: Path,
    stage_responses: dict[str, str],
) -> dict:
    """Run one stage's ``gen`` (per new block) + ``gen-compose`` (place/route).

    A stage's ``blocks[]`` entries are either freshly generated (the
    ``generator``/``params``/``cell_name`` shape ``compose_cell`` always
    supported) or a reference to an *earlier* stage's own composed output
    (``block["from_stage"]``, naming that earlier stage's ``name``) -- which
    ``klt gen-compose`` accepts unmodified as a further ``generator_report``,
    since its own response already carries ``generator: "gen-compose"`` plus
    a ``ports[]`` promoted from that stage's own ``pins[]`` (see this
    module's docstring and ``layout/README.md``'s "Two-pass composition"
    section for why a cell ever needs more than one stage: routing two nets
    that would otherwise cross on the same metal layer, resolved by moving
    one of them to a second routing-metal level in a second pass over the
    first pass's own composed output).

    The **final** stage (``is_final=True``) writes ``compose.request.json``/
    ``compose.response.json`` with no prefix, and its ``options.cell_name``
    is the cell's own name -- unprefixed, exactly as every single-stage cell
    already committed under ``layout/`` expects, so a cell.json with no
    ``"stages"`` key (wrapped by ``compose_cell`` into one implicit final
    stage) is byte-for-byte unaffected by this function's existence. A
    non-final stage's files are prefixed with its own ``name`` instead
    (``<name>.compose.request.json`` etc.), and its composed cell is named
    ``<name>``, so every stage's evidence lives in the cell's own directory
    without filename collisions.
    """
    gen_dir = out_dir / "gen"
    gen_dir.mkdir(parents=True, exist_ok=True)

    blocks_request = []
    for block in stage["blocks"]:
        if "from_stage" in block:
            ref_name = block["from_stage"]
            blocks_request.append(
                {
                    "id": block["id"],
                    "generator_report": stage_responses[ref_name],
                    **(
                        {"orientation": block["orientation"]}
                        if block.get("orientation", "none") != "none"
                        else {}
                    ),
                }
            )
            continue
        if "cell" in block:
            # An *existing* library cell -- a previously-composed,
            # already-committed layout/<other-cell>/<other-cell>.gds this
            # cell.json did not (re)generate -- placed via klt gen-compose's
            # own `blocks[].cell` request shape (`{gds_path, cell_name,
            # ports[], bbox_um}`, #1189 in klayout-tools). No `klt gen` call:
            # there is nothing to generate, only an existing stream to
            # place. See layout/ro_ring5-connectivity-poc/README.md for why
            # this needs hand-declared `ports[]` (a pre-existing cell never
            # reported a ports[] list to any `klt gen` response the way a
            # fresh primitive does).
            blocks_request.append(
                {
                    "id": block["id"],
                    "cell": block["cell"],
                    **(
                        {"orientation": block["orientation"]}
                        if block.get("orientation", "none") != "none"
                        else {}
                    ),
                }
            )
            continue
        response = run_klt(
            [
                "gen",
                block["generator"],
                "--params",
                json.dumps(block["params"]),
                "--pdk",
                variant,
                "--cell-name",
                block["cell_name"],
                "-o",
                f"gen/{block['id']}.gds",
            ],
            env=env,
            cwd=out_dir,
        )
        write_json(gen_dir / f"{block['id']}.gen.json", response)
        blocks_request.append(
            {
                "id": block["id"],
                "generator_report": f"gen/{block['id']}.gen.json",
                **(
                    {"orientation": block["orientation"]}
                    if block.get("orientation", "none") != "none"
                    else {}
                ),
            }
        )

    name = cell if is_final else stage["name"]
    prefix = "" if is_final else f"{stage['name']}."
    request = {
        "pdk": {"variant": variant},
        "blocks": blocks_request,
        "placement": stage["placement"],
        "routing": stage["routing"],
        "connectivity": stage["connectivity"],
        "pins": stage.get("pins", []),
        "options": {"cell_name": name, "output": f"{name}.gds"},
    }
    write_json(out_dir / f"{prefix}compose.request.json", request)
    compose = run_klt(
        ["gen-compose", f"{prefix}compose.request.json"], env=env, cwd=out_dir
    )
    write_json(out_dir / f"{prefix}compose.response.json", compose)
    unrouted = [net["net"] for net in compose.get("nets", []) if not net.get("routed")]
    if unrouted:
        raise BuildError(f"{name}: nets left unrouted by gen-compose: {unrouted}")
    return compose


def compose_cell(spec: dict, spec_dir: Path, out_dir: Path) -> dict:
    """Run the full gen -> compose -> drc -> extract -> lvs chain.

    ``spec["stages"]`` is optional (#27 step 2): a list of stage dicts, each
    shaped like this function's single-stage fields
    (``blocks``/``placement``/``routing``/``connectivity``/``pins``) plus a
    ``name`` (required on every stage but the last, which is always named
    after the cell itself). When absent, ``spec`` itself is wrapped as the
    one implicit final stage -- every cell.json committed before #27 step 2
    has no ``"stages"`` key and is therefore unaffected by this branch.
    """
    cell = spec["cell"]
    variant = spec["pdk"]["variant"]
    deck = spec["pdk"]["deck"]
    env = {**os.environ, "PDK": variant}

    stages = spec.get("stages") or [
        {
            "blocks": spec["blocks"],
            "placement": spec["placement"],
            "routing": spec["routing"],
            "connectivity": spec["connectivity"],
            "pins": spec.get("pins", []),
        }
    ]

    stage_responses: dict[str, str] = {}
    compose = None
    for index, stage in enumerate(stages):
        is_final = index == len(stages) - 1
        compose = compose_stage(
            stage,
            is_final=is_final,
            cell=cell,
            variant=variant,
            env=env,
            out_dir=out_dir,
            stage_responses=stage_responses,
        )
        if not is_final:
            stage_responses[stage["name"]] = f"{stage['name']}.compose.response.json"
    assert compose is not None  # stages is always non-empty

    # 3. DRC.
    drc = run_klt(["drc", f"{cell}.gds", "--deck", deck], env=env, cwd=out_dir)
    write_json(out_dir / "drc.json", drc)

    # 4. Extraction.
    extract = run_klt(["extract", f"{cell}.gds", "--deck", deck], env=env, cwd=out_dir)
    write_json(out_dir / "extract.json", extract)

    # 5. LVS against the design's own schematic-exported subckt.
    lvs_spec = spec["lvs"]
    reference_source = REPO_ROOT / lvs_spec["reference"]
    lvs_params = lvs_spec.get("params")
    lvs_drop_prefixes = tuple(lvs_spec.get("drop_prefixes", ()))
    dependency_subckts = lvs_spec.get("dependencies", ())
    reference_lines: list[str] = []
    for dependency in dependency_subckts:
        reference_lines.extend(
            build_reference(
                extract_subckt(reference_source, dependency),
                params=lvs_params,
                drop_prefixes=lvs_drop_prefixes,
            )
        )
        reference_lines.append("")
    reference_lines.extend(
        build_reference(
            extract_subckt(reference_source, lvs_spec["subckt"]),
            params=lvs_params,
            drop_prefixes=lvs_drop_prefixes,
        )
    )
    reference_path = out_dir / f"{cell}.ref.spice"
    dependency_note = (
        f" plus dependency subckt(s) {', '.join(dependency_subckts)}"
        if dependency_subckts
        else ""
    )
    reference_path.write_text(
        "\n".join(
            [
                f"* Reference netlist for {cell} LVS -- GENERATED by "
                "layout/bin/compose-cell.py",
                f"* Source: {lvs_spec['reference']} .subckt "
                f"{lvs_spec['subckt']}{dependency_note}",
                "* Only unit spellings (and any substituted subckt parameter)",
                "* differ from the source -- see compose-cell.py's docstring.",
                *reference_lines,
                "",
            ]
        )
    )
    lvs_options = {}
    if lvs_spec.get("flatten_reference"):
        lvs_options["flatten_reference"] = True
    if lvs_spec.get("flatten_layout"):
        lvs_options["flatten_layout"] = True
    lvs_request = {
        "layout": {"netlist": str(Path(extract["netlist_path"]).name)},
        "reference": {
            "netlist": reference_path.name,
            "form": "subckt-call",
            "deck": deck,
        },
        **({"options": lvs_options} if lvs_options else {}),
    }
    write_json(out_dir / "lvs.request.json", lvs_request)
    lvs = run_klt(["lvs", "lvs.request.json"], env=env, cwd=out_dir)
    write_json(out_dir / "lvs.json", lvs)

    return {
        "cell": cell,
        "drc": f"{drc['status']} ({drc['violation_count']} violations)",
        "extract": (
            f"{extract['status']}: {extract['device_count']} devices, "
            f"{extract['net_count']} nets"
        ),
        "lvs": (
            f"{lvs['status']}: {lvs['counts']['devices']['matched']}/"
            f"{lvs['counts']['devices']['reference']} devices, "
            f"{lvs['counts']['nets']['matched']}/"
            f"{lvs['counts']['nets']['reference']} nets matched"
        ),
        "clean": (
            drc["status"] == "clean"
            and drc["violation_count"] == 0
            and extract["status"] == "extracted"
            and lvs["status"] == "match"
        ),
    }


def check_cell(spec: dict, spec_dir: Path) -> int:
    """Rebuild into a temp dir and diff verdicts against what is committed."""
    with tempfile.TemporaryDirectory(prefix="klt-compose-cell-") as tmp:
        tmp_dir = Path(tmp)
        compose_cell(spec, spec_dir, tmp_dir)
        drift: list[str] = []
        for name, fields in CHECK_FIELDS.items():
            committed_path = spec_dir / name
            if not committed_path.exists():
                drift.append(f"{name}: missing from {spec_dir}")
                continue
            committed = json.loads(committed_path.read_text())
            rebuilt = json.loads((tmp_dir / name).read_text())
            for field in fields:
                if committed.get(field) != rebuilt.get(field):
                    drift.append(
                        f"{name}.{field}: committed={committed.get(field)!r} "
                        f"rebuilt={rebuilt.get(field)!r}"
                    )
        # A multi-stage cell.json (#27 step 2) also commits each non-final
        # stage's own "<name>.compose.response.json" (see compose_stage's
        # docstring) -- diff those too, on the same verdict-bearing fields
        # as the final compose.response.json above, so drift in an earlier
        # stage's own placement/routing is caught even when it happens not
        # to move the final cell's own bbox/DRC/LVS verdict.
        for committed_path in sorted(spec_dir.glob("*.compose.response.json")):
            if committed_path.name == "compose.response.json":
                continue  # the final stage, already diffed above
            rebuilt_path = tmp_dir / committed_path.name
            if not rebuilt_path.exists():
                drift.append(f"{committed_path.name}: missing from rebuild")
                continue
            committed = json.loads(committed_path.read_text())
            rebuilt = json.loads(rebuilt_path.read_text())
            for field in CHECK_FIELDS["compose.response.json"]:
                if committed.get(field) != rebuilt.get(field):
                    drift.append(
                        f"{committed_path.name}.{field}: "
                        f"committed={committed.get(field)!r} "
                        f"rebuilt={rebuilt.get(field)!r}"
                    )
    if drift:
        print(f"DRIFT in {spec_dir}:", file=sys.stderr)
        for entry in drift:
            print(f"  {entry}", file=sys.stderr)
        return 1
    print(f"{spec_dir}: rebuild matches committed evidence")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="path to a layout/<cell>/cell.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild into a temp dir and diff verdicts against the committed "
        "evidence instead of overwriting it",
    )
    args = parser.parse_args(argv)

    spec_path = args.spec.resolve()
    spec = json.loads(spec_path.read_text())
    spec_dir = spec_path.parent

    try:
        if args.check:
            return check_cell(spec, spec_dir)
        summary = compose_cell(spec, spec_dir, spec_dir)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"cell:    {summary['cell']}")
    print(f"drc:     {summary['drc']}")
    print(f"extract: {summary['extract']}")
    print(f"lvs:     {summary['lvs']}")
    return 0 if summary["clean"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
