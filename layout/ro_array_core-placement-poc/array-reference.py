#!/usr/bin/env python3
"""Build the ``klt lvs`` reference netlist for the composed ``ro_array_core``.

``layout/bin/compose-cell.py``'s ``lvs.dependencies`` mechanism extracts a
flat list of dependency subckt *names* from ``design/ro_array_core.spice`` and
rewrites all of them with **one** shared ``lvs.params`` dict.  That is exactly
right for every leaf/ring cell committed so far, and exactly wrong for
``ro_array_core``: the design netlist defines a **single**
``.subckt ro_ring5 en ro vddr vss wstv=0.42 lstv=2 cld=0.5f`` and calls it four
times with four different ``wstv=`` overrides (0.42/0.44/0.46/0.48), while
``layout/`` holds four physically distinct ring cells for those four sizings.
One shared ``params`` dict cannot express that, which is the open question
this directory's README has carried since Increment 2 ("Suggested next steps",
item 6).

This script is the narrowest thing that answers it: it reuses
``compose-cell.py``'s own ``extract_subckt``/``build_reference`` rewrite
verbatim -- same substitution rules, same ``Cld`` drop, same unit-suffix fix
(klayout-tools#1492) -- and calls it **four times over the ring hierarchy**,
once per ``wstv``, renaming ``ro_nand2``/``ro_stage``/``ro_ring5`` to
``*_r1``..``*_r4`` in each pass so the four differently-sized copies coexist in
one reference file.  ``ro_array_core``'s own ``xr1``..``xr4`` instance lines
are then repointed at the four renamed subckts (and their now-meaningless
``wstv=``/``lstv=``/``cld=`` pass-through kwargs dropped, the same rule
``compose-cell.py``'s transformation 2 applies).  ``ro_buf``/``xor2`` take no
parameters and pass through the unmodified single-pass rewrite.

The rename is deliberately *not* a new sizing convention: ``_r1``..``_r4``
exist only inside the generated reference so that ``flatten_reference: true``
sees four distinct definitions to inline.  Nothing in ``design/`` or the
composed layout is renamed.

Because a reference-netlist rewrite can silently produce a
plausible-but-wrong netlist that still yields a confident verdict (the exact
reason this repo's CI unit-tests ``compose-cell.py``'s rewrite), this script's
output is not trusted on its own: ``lvs-negative-controls.py`` re-runs the
same comparison against two deliberately-wrong references and requires both to
come back ``mismatch``.

Usage (from this directory)::

    python3 array-reference.py          # -> ro_array_core.ref.spice
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SOURCE = REPO_ROOT / "design" / "ro_array_core.spice"
OUT = HERE / "ro_array_core.ref.spice"

#: ``design/ro_array_core.spice``'s own four ``xrN ... ro_ring5 wstv=<w>``
#: overrides, in instance order.  ``lstv`` is the same for all four; ``cld``
#: is dropped along with the ``Cld`` load capacitor it parameterises.
RING_WSTV = {1: 0.42, 2: 0.44, 3: 0.46, 4: 0.48}

#: The ring hierarchy, innermost first -- every one of these carries the
#: ``wstv``/``lstv`` parameters and therefore needs one rewritten copy per ring.
RING_SUBCKTS = ("ro_nand2", "ro_stage", "ro_ring5")

#: Subckts with no parameters at all: one copy, rewritten once.
FLAT_SUBCKTS = ("ro_buf", "xor2")

DROP_PREFIXES = ("Cld",)
DROP_KWARGS = ("cld",)


def load_compose_cell() -> types.ModuleType:
    """Import ``layout/bin/compose-cell.py`` (a hyphenated, non-importable name)."""
    path = REPO_ROOT / "layout" / "bin" / "compose-cell.py"
    spec = importlib.util.spec_from_file_location("compose_cell", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build() -> list[str]:
    cc = load_compose_cell()
    lines: list[str] = []

    for index, wstv in RING_WSTV.items():
        suffix = f"_r{index}"
        params = {"wstv": wstv, "lstv": 2}
        for subckt in RING_SUBCKTS:
            rewritten = cc.build_reference(
                cc.extract_subckt(SOURCE, subckt),
                params=params,
                drop_prefixes=DROP_PREFIXES,
                drop_kwargs=DROP_KWARGS,
            )
            for line in rewritten:
                for name in RING_SUBCKTS:
                    line = re.sub(rf"\b{name}\b", name + suffix, line)
                lines.append(line)
            lines.append("")

    for subckt in FLAT_SUBCKTS:
        lines.extend(
            cc.build_reference(
                cc.extract_subckt(SOURCE, subckt),
                params=None,
                drop_prefixes=DROP_PREFIXES,
                drop_kwargs=DROP_KWARGS,
            )
        )
        lines.append("")

    top = cc.build_reference(
        cc.extract_subckt(SOURCE, "ro_array_core"),
        params=None,
        drop_prefixes=DROP_PREFIXES,
        drop_kwargs=DROP_KWARGS,
    )
    for line in top:
        match = re.match(r"^(xr(\d)\s+.*?)\bro_ring5\b(.*)$", line)
        if match:
            line = f"{match.group(1)}ro_ring5_r{match.group(2)}{match.group(3)}"
            line = re.sub(r"\s+(wstv|lstv|cld)=\S+", "", line)
        lines.append(line)
    return lines


def main() -> int:
    header = [
        "* Reference netlist for ro_array_core LVS -- GENERATED by",
        "* layout/ro_array_core-placement-poc/array-reference.py",
        "* Source: design/ro_array_core.spice .subckt ro_array_core plus",
        "* ro_ring5/ro_nand2/ro_stage (one renamed copy per ring wstv),",
        "* ro_buf and xor2. Only unit spellings, the four substituted wstv",
        "* values and the per-ring subckt renames differ from the source.",
    ]
    OUT.write_text("\n".join([*header, *build(), ""]))
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
