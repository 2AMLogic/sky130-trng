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
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Verdict-bearing fields --check compares, per artifact.
CHECK_FIELDS: dict[str, tuple[str, ...]] = {
    "drc.json": ("status", "violation_count"),
    "extract.json": ("status", "device_count", "net_count", "device_counts"),
    "lvs.json": ("status", "mismatch_count", "error_count", "counts"),
    "compose.response.json": ("cell_name", "bbox_um"),
}


class BuildError(RuntimeError):
    """A step of the chain failed."""


def run_klt(args: list[str], *, env: dict[str, str], cwd: Path) -> dict:
    """Run ``klt`` with ``--format json`` and return its parsed response.

    Always run from the cell's own output directory with *relative* paths, so
    that every committed response records repo-relative provenance and no
    absolute home path leaks into the evidence (the leak ``klt
    env-provenance --scan`` exists to catch).

    A non-zero exit is not automatically fatal: ``klt gen-compose`` exits 3
    for a partial success (some net unrouted) and ``klt lvs`` exits 3 for a
    clean-run mismatch, both of which this script wants to report from the
    response body rather than from a traceback. A response that is not JSON
    at all is fatal.
    """
    proc = subprocess.run(
        ["klt", *args, "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
    )
    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BuildError(
            f"klt {' '.join(args)} produced no JSON response "
            f"(exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        ) from exc
    if "error" in response:
        raise BuildError(
            f"klt {' '.join(args)} failed: {response['error'].get('message')}"
        )
    return response


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


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

    Three transformations, each deliberately minimal and each visible in the
    written-out result:

    1. ``params`` values are substituted for the subckt's own parameter names
       wherever they appear as an ``L=``/``W=`` value (this design's starve
       devices are sized ``L=lstv W=wstv``), and the parameter defaults are
       dropped from the ``.subckt`` line.
    2. Element cards whose name starts with one of ``drop_prefixes`` are
       removed -- for this design that is ``ro_stage``/``ro_nand2``'s ``Cld``
       lumped load capacitor, a *simulation* load model with no physical
       counterpart in the layout, not a device the layout omits.
    3. Unitless ``L=``/``W=`` values gain an explicit ``u`` suffix -- see this
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
                line = re.sub(
                    rf"\b([LW])={re.escape(name)}\b", rf"\1={value}", line
                )
        out.append(_GEOMETRY_RE.sub(r"\1=\2u", line))
    return out


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------


def compose_cell(spec: dict, spec_dir: Path, out_dir: Path) -> dict:
    """Run the full gen -> compose -> drc -> extract -> lvs chain."""
    cell = spec["cell"]
    variant = spec["pdk"]["variant"]
    deck = spec["pdk"]["deck"]
    env = {**os.environ, "PDK": variant}

    gen_dir = out_dir / "gen"
    gen_dir.mkdir(parents=True, exist_ok=True)

    # 1. Per-block generation.
    for block in spec["blocks"]:
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

    # 2. Composition (place + route).
    request = {
        "pdk": {"variant": variant},
        "blocks": [
            {
                "id": block["id"],
                "generator_report": f"gen/{block['id']}.gen.json",
                **(
                    {"orientation": block["orientation"]}
                    if block.get("orientation", "none") != "none"
                    else {}
                ),
            }
            for block in spec["blocks"]
        ],
        "placement": spec["placement"],
        "routing": spec["routing"],
        "connectivity": spec["connectivity"],
        "pins": spec.get("pins", []),
        "options": {"cell_name": cell, "output": f"{cell}.gds"},
    }
    write_json(out_dir / "compose.request.json", request)
    compose = run_klt(["gen-compose", "compose.request.json"], env=env, cwd=out_dir)
    write_json(out_dir / "compose.response.json", compose)
    unrouted = [net["net"] for net in compose.get("nets", []) if not net.get("routed")]
    if unrouted:
        raise BuildError(f"{cell}: nets left unrouted by gen-compose: {unrouted}")

    # 3. DRC.
    drc = run_klt(["drc", f"{cell}.gds", "--deck", deck], env=env, cwd=out_dir)
    write_json(out_dir / "drc.json", drc)

    # 4. Extraction.
    extract = run_klt(["extract", f"{cell}.gds", "--deck", deck], env=env, cwd=out_dir)
    write_json(out_dir / "extract.json", extract)

    # 5. LVS against the design's own schematic-exported subckt.
    lvs_spec = spec["lvs"]
    reference_lines = build_reference(
        extract_subckt(REPO_ROOT / lvs_spec["reference"], lvs_spec["subckt"]),
        params=lvs_spec.get("params"),
        drop_prefixes=tuple(lvs_spec.get("drop_prefixes", ())),
    )
    reference_path = out_dir / f"{cell}.ref.spice"
    reference_path.write_text(
        "\n".join(
            [
                f"* Reference netlist for {cell} LVS -- GENERATED by "
                "layout/bin/compose-cell.py",
                f"* Source: {lvs_spec['reference']} .subckt {lvs_spec['subckt']}",
                "* Only unit spellings (and any substituted subckt parameter)",
                "* differ from the source -- see compose-cell.py's docstring.",
                *reference_lines,
                "",
            ]
        )
    )
    lvs_request = {
        "layout": {"netlist": str(Path(extract["netlist_path"]).name)},
        "reference": {
            "netlist": reference_path.name,
            "form": "subckt-call",
            "deck": deck,
        },
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
