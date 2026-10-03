#!/usr/bin/env python3
"""Shared ``klt lvs`` negative-control logic for ``ro_array_core``.

The two deliberate faults (:func:`perturb_width`, :func:`perturb_topology`),
their descriptions (:data:`CONTROLS`), the LVS request and the report loop
were byte-identical in ``layout/ro_array_core/lvs-negative-controls.py`` and
``layout/ro_array_core-placement-poc/lvs-negative-controls.py``. Extracted
per issue #168, following this directory's ``_geom_common.py`` (issue #131)
and ``layout/bin/_klt_common.py`` (issues #49/#52): the controls are defined
once, so changing one copy can no longer silently weaken the other
directory's evidence check.

Each directory keeps its own executable ``lvs-negative-controls.py`` that
passes its own reference, layout netlist, baseline and output paths to
:func:`main`. The PoC wrapper imports this module the same way its
``vdd-tap-scan.py`` imports ``_geom_common``.

``tool_errors`` selects what happens when ``klt`` itself fails
(:class:`BuildError`): the live wrapper passes ``"exit"`` (converted to
``SystemExit`` with the error text), the PoC wrapper passes ``"raise"``
(the exception propagates, as it always did there).
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bin"))
from _klt_common import BuildError, run_klt  # noqa: E402


def perturb_width(text: str) -> str:
    """Resize ring 4's starve devices to ring 1's ``wstv`` (0.48 -> 0.42)."""
    out: list[str] = []
    in_ring4 = False
    for line in text.splitlines():
        lowered = line.lower()
        if lowered.startswith((".subckt ro_nand2_r4", ".subckt ro_stage_r4")):
            in_ring4 = True
        elif lowered.startswith(".subckt "):
            in_ring4 = False
        if in_ring4:
            line = line.replace("W=0.48u", "W=0.42u")
        out.append(line)
    return "\n".join(out) + "\n"


def perturb_topology(text: str) -> str:
    """Cross ``xa1``/``xa2``'s second inputs (``ro2`` <-> ``ro3``)."""
    swapped = text.replace(
        "xa1 ro1 ro2 t1 vdd vss xor2", "xa1 ro1 ro3 t1 vdd vss xor2"
    ).replace("xa2 ro3 ro4 t2 vdd vss xor2", "xa2 ro2 ro4 t2 vdd vss xor2")
    if swapped == text:  # pragma: no cover - defensive
        raise SystemExit("topology control: no xa1/xa2 instance line to perturb")
    return swapped


CONTROLS = {
    "width": (
        perturb_width,
        "ring 4's starve devices resized 0.48um -> 0.42um (ring 1's wstv); "
        "topology untouched",
    ),
    "topology": (
        perturb_topology,
        "xa1/xa2's second XOR inputs crossed (ro2 <-> ro3); every device and "
        "device parameter untouched",
    ),
}


def run_lvs(workdir: pathlib.Path, layout_name: str, reference_name: str) -> dict:
    request = {
        "layout": {"netlist": layout_name},
        "reference": {
            "netlist": reference_name,
            "form": "subckt-call",
            "deck": "sky130",
            "top": "RO_ARRAY_CORE",
        },
        "options": {"flatten_reference": True, "flatten_layout": True},
    }
    request_path = workdir / "lvs.request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n")
    return run_klt(["lvs", request_path.name], env=os.environ, cwd=workdir)


def main(
    *,
    reference: pathlib.Path,
    layout_netlist: pathlib.Path,
    baseline_path: pathlib.Path,
    out: pathlib.Path,
    tool_errors: str,
) -> int:
    """Run every control, write *out*, print it; 0 iff all were detected."""
    if tool_errors not in ("exit", "raise"):
        raise ValueError(f"tool_errors must be 'exit' or 'raise': {tool_errors!r}")
    source = reference.read_text()
    baseline = json.loads(baseline_path.read_text())

    results: dict[str, dict] = {}
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        workdir = pathlib.Path(tmp)
        shutil.copy(layout_netlist, workdir / layout_netlist.name)
        for name, (perturb, description) in CONTROLS.items():
            reference_name = f"{name}.ref.spice"
            (workdir / reference_name).write_text(perturb(source))
            try:
                report = run_lvs(workdir, layout_netlist.name, reference_name)
            except BuildError as exc:
                if tool_errors == "exit":
                    raise SystemExit(str(exc)) from exc
                raise
            detected = report.get("status") == "mismatch"
            ok = ok and detected
            results[name] = {
                "description": description,
                "status": report.get("status"),
                "detected": detected,
                "counts": report.get("counts"),
                "mismatch_categories": sorted(
                    {
                        entry.get("category")
                        for entry in report.get("mismatches", [])
                        if entry.get("severity") != "warning"
                        or "flattened" not in (entry.get("description") or "")
                    }
                ),
            }

    report = {
        "layout_netlist": layout_netlist.name,
        "reference": reference.name,
        "baseline_status": baseline.get("status"),
        "baseline_counts": baseline.get("counts"),
        "all_controls_detected": ok,
        "controls": results,
    }
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if ok else 1
