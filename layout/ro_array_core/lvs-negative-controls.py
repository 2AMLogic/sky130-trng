#!/usr/bin/env python3
"""Prove ``ro_array_core``'s ``klt lvs`` match is sensitive, not vacuous.

Promoted, unchanged in substance, from
``layout/ro_array_core-placement-poc/lvs-negative-controls.py`` -- it now runs
against **this** directory's own committed artifacts (``ro_array_core.spice``
extracted from ``ro_array_core.gds``, and the ``ro_array_core.ref.spice``
``compose-cell.py``'s ``lvs.dependency_variants`` mechanism generates from
``cell.json``) rather than against the PoC directory's hand-maintained
``signal9`` file set.

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
2. **The reference is machine-generated.** ``cell.json``'s
   ``lvs.dependency_variants`` entry makes ``compose-cell.py`` rename subckts
   and substitute per-ring parameters; a rewrite bug that produced a
   plausible-but-wrong netlist would still yield a confident verdict, exactly
   the failure mode this repo's CI unit-tests that rewrite for.

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

Usage (from this directory, after ``compose-cell.py cell.json``)::

    python3 lvs-negative-controls.py    # -> lvs-negative-controls.json

Exits non-zero if either control matches (i.e. if the comparison is not
discriminating), so it is usable as a check, not only as a report.

The perturbations, the LVS request and the report loop live in
``_lvs_negative_controls.py`` (issue #168), shared with the PoC directory's
wrapper; a ``klt`` tool error exits non-zero with its message.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))
from _lvs_negative_controls import main  # noqa: E402

REFERENCE = HERE / "ro_array_core.ref.spice"
LAYOUT_NETLIST = HERE / "ro_array_core.spice"
BASELINE = HERE / "lvs.json"
OUT = HERE / "lvs-negative-controls.json"


if __name__ == "__main__":
    sys.exit(
        main(
            reference=REFERENCE,
            layout_netlist=LAYOUT_NETLIST,
            baseline_path=BASELINE,
            out=OUT,
            tool_errors="exit",
        )
    )
