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
this directory's README carried since Increment 2 ("Suggested next steps",
item 6).

**Updated (issue #22 follow-up to #27 step 1)**: the per-ring rename +
per-instance-parametrize rewrite this script needed is no longer a
one-off -- it is now ``compose-cell.py``'s own generic
``lvs.dependency_variants`` mechanism (see that module's docstring, "A
same-subckt, differently-parametrized reference"), covered by
``layout/test_compose_cell.py``'s unit tests. This script is now a thin
caller of that mechanism (``build_variant_reference``/
``repoint_variant_instances``) rather than a bespoke rename loop -- the
``RING_VARIANT`` descriptor below is exactly the ``lvs.dependency_variants[]``
entry a future ``layout/ro_array_core/cell.json`` promotion would carry
verbatim. Verified byte-for-byte identical output (module docstring's own
worked check, not re-run automatically here) against the original
hand-rolled rewrite this script carried through PR #68.

Nothing in ``design/`` or the composed layout is renamed by this rewrite --
``_r1``..``_r4`` exist only inside the generated reference file, so that
``flatten_reference: true`` sees four distinct definitions to inline.

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
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SOURCE = REPO_ROOT / "design" / "ro_array_core.spice"
OUT = HERE / "ro_array_core.ref.spice"

#: Subckts with no parameters at all: one copy, rewritten once.
FLAT_SUBCKTS = ("ro_buf", "xor2")

DROP_PREFIXES = ("Cld",)
DROP_KWARGS = ("cld",)

#: The one ``lvs.dependency_variants[]`` entry this design needs: a single
#: ``ro_ring5`` definition (plus its own ``ro_nand2``/``ro_stage``
#: dependencies), instantiated four times by ``design/ro_array_core.spice``'s
#: own ``xr1``-``xr4`` with four different ``wstv`` overrides. See
#: ``compose-cell.py``'s docstring for the full schema.
RING_VARIANT = {
    "subckt": "ro_ring5",
    "nested": ["ro_nand2", "ro_stage"],
    "drop_prefixes": list(DROP_PREFIXES),
    "drop_kwargs": list(DROP_KWARGS),
    "instances": [
        {
            "rename": f"_r{index}",
            "top_instance_pattern": rf"^xr{index}\b",
            "params": {"wstv": wstv, "lstv": 2},
        }
        for index, wstv in enumerate((0.42, 0.44, 0.46, 0.48), start=1)
    ],
}


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

    for instance in RING_VARIANT["instances"]:
        lines.extend(
            cc.build_variant_reference(
                SOURCE,
                RING_VARIANT,
                instance,
                default_drop_prefixes=DROP_PREFIXES,
                default_drop_kwargs=DROP_KWARGS,
            )
        )

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
    lines.extend(cc.repoint_variant_instances(top, [RING_VARIANT]))
    return lines


def main() -> int:
    header = [
        "* Reference netlist for ro_array_core LVS -- GENERATED by",
        "* layout/ro_array_core-placement-poc/array-reference.py, via",
        "* layout/bin/compose-cell.py's generic lvs.dependency_variants",
        "* mechanism (#22/#27).",
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
