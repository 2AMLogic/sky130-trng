#!/usr/bin/env python3
"""Sum a synthesized netlist's leakage from a Liberty file's own
``cell_leakage_power`` entries.

``klt synthesize``'s response contract (``docs/cli/synthesize.md`` in
``2AMLogic/klayout-tools``, verified against the pinned ``klt 0.4.0`` build)
reports ``instance_count``/``area_um2``/``instance_counts_by_type`` and an
ABC pre-layout ``timing.critical_path_ps`` estimate, but **no leakage
field at all** -- there is no ``leakage_power``/``leakage_nw`` key anywhere
in its JSON envelope. That is a real gap against what
`sim/README.md`/this campaign's own record needs (a leakage figure at
``tt_025C_1v80``), not an oversight in this module: filed generically (not
this design's specifics) as
`2AMLogic/klayout-tools#1626 <https://github.com/2AMLogic/klayout-tools/issues/1626>`_.

The number this module produces instead is not a fabrication: standard-cell
leakage is exactly the sum, over every mapped instance, of that cell type's
own ``cell_leakage_power`` at the resolved corner -- the same Liberty file
``klt synthesize`` itself already read via ``dfflibmap``/``abc -liberty`` to
produce the netlist in the first place (verified against the generated
``.ys`` script: both name the identical resolved liberty path). This module
just does the sum ``klt synthesize`` does not do on the caller's behalf.

Liberty's ``cell_leakage_power`` is a flat, state-independent figure per
cell (SKY130's ``sky130_fd_sc_hd`` liberty carries exactly one
``cell_leakage_power`` entry per ``cell (...)`` block, no per-state
``leakage_power ()`` breakdown -- verified by direct grep), in whatever
``leakage_power_unit`` the library declares (``sky130_fd_sc_hd``'s is
``"1nW"``, also verified directly). This module reads that unit rather than
assuming it.
"""

from __future__ import annotations

import re
from pathlib import Path


def parse_cell_leakage_nw(liberty_path: Path) -> tuple[dict[str, float], float]:
    """Return ``({cell_name: leakage_nw}, leakage_power_unit_to_nw)``.

    ``leakage_power_unit_to_nw`` converts the raw Liberty figures (which are
    in whatever unit the library declares) to nanowatts; sky130_fd_sc_hd's
    own ``"1nW"`` unit makes this ``1.0``, but it is computed from the file
    rather than assumed.
    """
    text = liberty_path.read_text()

    unit_m = re.search(r'leakage_power_unit\s*:\s*"([^"]+)"\s*;', text)
    if not unit_m:
        raise ValueError(f"no leakage_power_unit found in {liberty_path}")
    unit = unit_m.group(1).strip()
    scale = {"1nW": 1.0, "1uW": 1e3, "1mW": 1e6, "1pW": 1e-3, "1W": 1e9}.get(unit)
    if scale is None:
        raise ValueError(f"unrecognised leakage_power_unit {unit!r} in {liberty_path}")

    leakage: dict[str, float] = {}
    for cell_m in re.finditer(r'cell\s*\(\s*"([^"]+)"\s*\)\s*\{', text):
        name = cell_m.group(1)
        start = cell_m.end()
        depth = 1
        i = start
        n = len(text)
        while depth > 0 and i < n:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        block = text[start:i]
        leak_m = re.search(r'cell_leakage_power\s*:\s*([0-9.eE+-]+)\s*;', block)
        if leak_m:
            # First cell block for a given name wins (a cell name is unique
            # per Liberty file; re.finditer already walks them in file order).
            leakage.setdefault(name, float(leak_m.group(1)) * scale)
    return leakage, scale


def total_leakage_nw(instance_counts_by_type: dict[str, int],
                     leakage_by_cell_nw: dict[str, float]) -> tuple[float, list[str]]:
    """Sum leakage over a synthesis run's ``instance_counts_by_type``.

    Returns ``(total_nw, missing_cell_names)`` -- ``missing_cell_names`` is
    every mapped cell type with no Liberty leakage entry (should be empty
    for a self-consistent synth-output/liberty pair; a non-empty result
    means the wrong Liberty file was passed in, and the total is not
    trustworthy).
    """
    total = 0.0
    missing: list[str] = []
    for cell, count in instance_counts_by_type.items():
        nw = leakage_by_cell_nw.get(cell)
        if nw is None:
            missing.append(cell)
            continue
        total += nw * count
    return total, missing
