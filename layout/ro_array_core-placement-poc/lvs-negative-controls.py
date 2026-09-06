#!/usr/bin/env python3
"""Prove ``ro_array_core``'s ``klt lvs`` match is sensitive, not vacuous.

``lvs.json``'s ``status: match`` is only worth as much as the comparison's own
discrimination.  Two things could make it vacuous, and both are live risks for
*this* comparison specifically:

1. **Device sizing might not be compared at all.** ``ro_array_core``'s whole
   point is four rings deliberately sized apart (``wstv`` 0.42/0.44/0.46/0.48,
   per ``spec/decision-records/DR-0003-*``); the four physically distinct ring
   cells under ``layout/`` differ *only* in that width.  If ``klt lvs`` ignored
   ``W``, four identical rings would match this reference just as happily --
   and the layout's whole reason for holding four separate ring GDS files
   would be unverified.
2. **The reference is machine-generated.** ``array-reference.py`` renames
   subckts and substitutes per-ring parameters; a rewrite bug that produced a
   plausible-but-wrong netlist would still yield a confident verdict, exactly
   the failure mode this repo's CI unit-tests ``compose-cell.py``'s rewrite for.

So this script re-runs the *same* comparison against two deliberately-wrong
references and requires both to come back ``mismatch``:

``width`` -- ring 4's starve devices resized from ``wstv=0.48`` to ``0.42``
    (ring 1's width), leaving topology untouched.  A pass here would mean
    device widths are not being compared.
``topology`` -- ``xa1``/``xa2``'s inputs crossed (``ro2``<->``ro3``), leaving
    every device and every device parameter untouched.  A pass here would mean
    the XOR combining tree's wiring is not being compared.

Both perturbations are applied to the *reference* side, so the layout under
test is byte-identical across all three runs.

Usage (from this directory, after ``array-reference.py`` and a ``klt extract``
of ``ro_array_core_signal9_poc.gds``)::

    python3 lvs-negative-controls.py    # -> lvs-negative-controls.json

Exits non-zero if either control matches (i.e. if the comparison is not
discriminating), so it is usable as a check, not only as a report.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REFERENCE = HERE / "ro_array_core.ref.spice"
LAYOUT_NETLIST = HERE / "ro_array_core_signal9_poc.spice"
BASELINE = HERE / "lvs.json"
OUT = HERE / "lvs-negative-controls.json"


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


def run_lvs(workdir: pathlib.Path, reference_name: str) -> dict:
    request = {
        "layout": {"netlist": LAYOUT_NETLIST.name},
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
    completed = subprocess.run(
        ["klt", "lvs", request_path.name, "--format", "json"],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    if not completed.stdout.strip():
        raise SystemExit(f"klt lvs produced no output: {completed.stderr[:400]}")
    return json.loads(completed.stdout)


def main() -> int:
    source = REFERENCE.read_text()
    baseline = json.loads(BASELINE.read_text())

    results: dict[str, dict] = {}
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        workdir = pathlib.Path(tmp)
        shutil.copy(LAYOUT_NETLIST, workdir / LAYOUT_NETLIST.name)
        for name, (perturb, description) in CONTROLS.items():
            reference_name = f"{name}.ref.spice"
            (workdir / reference_name).write_text(perturb(source))
            report = run_lvs(workdir, reference_name)
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
        "layout_netlist": LAYOUT_NETLIST.name,
        "reference": REFERENCE.name,
        "baseline_status": baseline.get("status"),
        "baseline_counts": baseline.get("counts"),
        "all_controls_detected": ok,
        "controls": results,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
