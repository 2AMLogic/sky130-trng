#!/usr/bin/env python3
"""Unit test for ``layout/bin/compose-cell.py``'s reference-netlist rewrite.

Standalone script, following ``design/test_pdk_search.py``'s and
``layout/test_pex_netlist.py``'s "run it directly" convention -- there is no
pytest suite in this repository:

    python3 layout/test_compose_cell.py

Pure Python: no ``klt``, no KLayout, no PDK install, no GDS. Everything here
runs in any environment, which is why it is on this repo's PR-blocking CI
path while the real composition is not.

Why this exists. ``build_reference`` rewrites the *reference side* of every
LVS run under ``layout/`` -- the netlist the layout is compared against. A
wrong rewrite does not crash: it produces a plausible SPICE file that
``klt lvs`` happily compares, and the resulting verdict (match OR mismatch)
is then evidence about the wrong thing. ``--check``'s rebuild cannot catch
that, because it re-runs the same rewrite. Two failure shapes in particular
are silent:

- a **too-greedy** substitution or kwarg drop that also removes a real
  connection, a real device parameter, or a real instance argument -- LVS
  then compares against a netlist that is not the schematic;
- a **too-timid** unit rewrite that leaves an unsuffixed ``L=``/``W=``,
  which ``klt lvs``'s ``subckt-call`` converter reads as SI metres
  (klayout-tools#1492) and turns into a metre-scale device.

Each check below pins one of the four documented transformations against a
minimal ro_ring5/ro_stage-shaped input, so a future edit to the regexes has
to break a test rather than a verdict.
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "bin" / "compose-cell.py"
_spec = importlib.util.spec_from_file_location("compose_cell", _MODULE_PATH)
assert _spec and _spec.loader
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

_FAILURES: list[str] = []

#: Shaped exactly like design/ro_array_core.spice's own .subckt ro_stage --
#: a starve pair sized by the subckt's own parameters, a fixed-size pair, and
#: the Cld simulation-only load capacitor.
RO_STAGE = [
    ".subckt ro_stage a y vddr vss wstv=0.42 lstv=2 cld=0.5f",
    "XMph py vss vddr vddr sky130_fd_pr__pfet_01v8 L=lstv W=wstv nf=1 "
    "ad='int((1 + 1)/2) * wstv / 1 * 0.29' m=1",
    "XMp y a py vddr sky130_fd_pr__pfet_01v8 L=0.15 W=0.84 nf=1 m=1",
    "XMn y a ny vss sky130_fd_pr__nfet_01v8 L=0.15 W=0.42 nf=1 m=1",
    "XMnt ny vddr vss vss sky130_fd_pr__nfet_01v8 L=lstv W=wstv nf=1 m=1",
    "Cld y vss cld m=1",
    ".ends",
]

#: Shaped exactly like .subckt ro_ring5 -- a body of nothing but instance
#: calls, each forwarding all three of the parent's parameters by keyword.
RO_RING5 = [
    ".subckt ro_ring5 en ro vddr vss wstv=0.42 lstv=2 cld=0.5f",
    "xg ro en n1 vddr vss ro_nand2 wstv=wstv lstv=lstv cld=cld",
    "x1 n1 n2 vddr vss ro_stage wstv=wstv lstv=lstv cld=cld",
    "x4 n4 ro vddr vss ro_stage wstv=wstv lstv=lstv cld=cld",
    ".ends",
]

PARAMS = {"wstv": 0.42, "lstv": 2}


def _check(condition: bool, name: str, detail: str = "") -> None:
    if condition:
        print(f"ok     {name}")
    else:
        _FAILURES.append(name)
        print(f"FAIL   {name}" + (f"\n       {detail}" if detail else ""))


def check_param_substitution_and_units() -> None:
    """Transformation 1 + 4, on a real starve-device card."""
    out = cc.build_reference(RO_STAGE, params=PARAMS, drop_prefixes=("Cld",))
    mph = next(line for line in out if line.startswith("XMph"))
    _check("L=2u" in mph, "starve device's L=lstv becomes a suffixed literal", mph)
    _check("W=0.42u" in mph, "starve device's W=wstv becomes a suffixed literal", mph)
    mp = next(line for line in out if line.startswith("XMp "))
    _check(
        "L=0.15u" in mp and "W=0.84u" in mp,
        "an already-literal L/W gains the u suffix and nothing else",
        mp,
    )
    _check(
        "ad='int((1 + 1)/2) * wstv / 1 * 0.29'" in mph,
        "a bare param inside a quoted expression is left unevaluated",
        mph,
    )
    _check(
        all("nf=1u" not in line and "m=1u" not in line for line in out),
        "the u suffix is applied to L/W only, never to nf/m",
    )
    _check(
        out[0] == ".subckt ro_stage a y vddr vss",
        "the .subckt line keeps every port and drops every default",
        out[0],
    )


def check_drop_prefixes() -> None:
    """Transformation 3: the Cld load capacitor is a sim model, not a device."""
    out = cc.build_reference(RO_STAGE, params=PARAMS, drop_prefixes=("Cld",))
    _check(
        not any(line.startswith("Cld") for line in out),
        "drop_prefixes removes the Cld load capacitor",
    )
    _check(
        len([line for line in out if line.startswith("X")]) == 4,
        "drop_prefixes removes nothing else -- all four devices survive",
    )
    kept = cc.build_reference(RO_STAGE, params=PARAMS, drop_prefixes=())
    _check(
        any(line.startswith("Cld") for line in kept),
        "with no drop_prefixes the capacitor is kept (the drop is opt-in)",
    )


def check_pass_through_kwargs() -> None:
    """Transformation 2, both halves: params-driven and drop_kwargs-driven."""
    out = cc.build_reference(
        RO_RING5, params=PARAMS, drop_prefixes=("Cld",), drop_kwargs=("cld",)
    )
    body = [line for line in out if line.startswith(("xg", "x1", "x4"))]
    _check(len(body) == 3, "every instance-call line survives", str(body))
    _check(
        all("=" not in line for line in body),
        "no keyword argument survives on an instance call (callee no longer "
        "declares any of these parameters)",
        str(body),
    )
    _check(
        body[0] == "xg ro en n1 vddr vss ro_nand2",
        "an instance call keeps its full node list and its subckt name",
        body[0],
    )
    _check(
        body[2] == "x4 n4 ro vddr vss ro_stage",
        "the feedback instance's own nodes are untouched",
        body[2],
    )
    still = cc.build_reference(RO_RING5, params=PARAMS, drop_prefixes=("Cld",))
    _check(
        any("cld=cld" in line for line in still),
        "without drop_kwargs, cld=cld survives -- the drop is opt-in, and "
        "this is the state that produced klt lvs's 'Not a known parameter "
        "for circuit' warnings",
    )


def check_drop_kwargs_is_not_greedy() -> None:
    """A drop_kwargs entry must only strip the exact ``name=name`` form."""
    lines = [
        ".subckt probe a y",
        "x1 a y child cld=0.5f",
        "x2 a y child other=cld",
        "x3 a y child cldx=cldx",
        ".ends",
    ]
    out = cc.build_reference(lines, params=None, drop_prefixes=(), drop_kwargs=("cld",))
    _check("cld=0.5f" in out[1], "a real value assignment is not dropped", out[1])
    _check("other=cld" in out[2], "a param used as someone else's value stays", out[2])
    _check(
        "cldx=cldx" in out[3],
        "a longer name that starts with it is not a match",
        out[3],
    )


def check_extract_subckt_is_exact() -> None:
    """The subckt slicer must not match a longer name with the same prefix."""
    text = "\n".join(
        [
            ".subckt ro_stage_wstv0p44 a y",
            "XMn y a 0 0 nfet L=0.15 W=0.42",
            ".ends",
            ".subckt ro_stage a y",
            "XMp y a 0 0 pfet L=0.15 W=0.84",
            ".ends",
        ]
    )
    with tempfile.NamedTemporaryFile("w", suffix=".spice", delete=False) as handle:
        handle.write(text)
        path = Path(handle.name)
    try:
        got = cc.extract_subckt(path, "ro_stage")
        _check(
            got[0] == ".subckt ro_stage a y" and "pfet" in got[1],
            "extract_subckt picks the exact subckt, not a longer-named sibling",
            str(got),
        )
    finally:
        path.unlink()


def main() -> int:
    check_param_substitution_and_units()
    check_drop_prefixes()
    check_pass_through_kwargs()
    check_drop_kwargs_is_not_greedy()
    check_extract_subckt_is_exact()

    if _FAILURES:
        print(f"FAIL   {len(_FAILURES)} check(s) failed")
        return 1
    print("PASS   layout/test_compose_cell.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
