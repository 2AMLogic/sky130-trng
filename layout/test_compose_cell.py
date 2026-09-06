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
import re
import sys
import tempfile
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "bin" / "compose-cell.py"
_spec = importlib.util.spec_from_file_location("compose_cell", _MODULE_PATH)
assert _spec and _spec.loader
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "design"))
from _test_check import Checker  # noqa: E402

_checker = Checker()
_check = _checker.check

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

#: Minimal .subckt ro_nand2 -- ro_ring5's other same-parameter dependency,
#: needed so RO_RING5's own "nested" rewrite has something real to rename.
RO_NAND2 = [
    ".subckt ro_nand2 a b y vddr vss wstv=0.42 lstv=2 cld=0.5f",
    "XMph py vss vddr vddr sky130_fd_pr__pfet_01v8 L=lstv W=wstv nf=1 m=1",
    "XMnt ny vddr vss vss sky130_fd_pr__nfet_01v8 L=lstv W=wstv nf=1 m=1",
    ".ends",
]

#: Shaped exactly like .subckt ro_array_core -- two ring instances, each
#: overriding ro_ring5's own wstv/lstv/cld with a *literal* value (not the
#: name=name pass-through form ro_ring5's own body uses to forward them).
RO_ARRAY_CORE = [
    ".subckt ro_array_core en1 en2 vddr1 vddr2 vss",
    "xr1 en1 ro1 vddr1 vss ro_ring5 wstv=0.42 lstv=2 cld=0.5f",
    "xr2 en2 ro2 vddr2 vss ro_ring5 wstv=0.44 lstv=2 cld=0.5f",
    ".ends",
]

PARAMS = {"wstv": 0.42, "lstv": 2}

#: One lvs.dependency_variants[] entry matching RO_ARRAY_CORE's two rings.
RING_VARIANT = {
    "subckt": "ro_ring5",
    "nested": ["ro_nand2", "ro_stage"],
    "drop_kwargs": ["cld"],
    "instances": [
        {
            "rename": "_r1",
            "top_instance_pattern": r"^xr1\b",
            "params": {"wstv": 0.42, "lstv": 2},
        },
        {
            "rename": "_r2",
            "top_instance_pattern": r"^xr2\b",
            "params": {"wstv": 0.44, "lstv": 2},
        },
    ],
}


def _write_netlist(lines: list[str]) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".spice", delete=False) as handle:
        handle.write("\n".join(lines) + "\n")
        return Path(handle.name)


def check_param_substitution_and_units() -> None:
    """Transformation 1 + 4, on a real starve-device card."""
    out = cc.build_reference(RO_STAGE, params=PARAMS, drop_prefixes=("Cld",))
    mph = next(line for line in out if line.startswith("XMph"))
    _check("starve device's L=lstv becomes a suffixed literal", "L=2u" in mph, mph)
    _check("starve device's W=wstv becomes a suffixed literal", "W=0.42u" in mph, mph)
    mp = next(line for line in out if line.startswith("XMp "))
    _check(
        "an already-literal L/W gains the u suffix and nothing else",
        "L=0.15u" in mp and "W=0.84u" in mp,
        mp,
    )
    _check(
        "a bare param inside a quoted expression is left unevaluated",
        "ad='int((1 + 1)/2) * wstv / 1 * 0.29'" in mph,
        mph,
    )
    _check(
        "the u suffix is applied to L/W only, never to nf/m",
        all("nf=1u" not in line and "m=1u" not in line for line in out),
    )
    _check(
        "the .subckt line keeps every port and drops every default",
        out[0] == ".subckt ro_stage a y vddr vss",
        out[0],
    )


def check_drop_prefixes() -> None:
    """Transformation 3: the Cld load capacitor is a sim model, not a device."""
    out = cc.build_reference(RO_STAGE, params=PARAMS, drop_prefixes=("Cld",))
    _check(
        "drop_prefixes removes the Cld load capacitor",
        not any(line.startswith("Cld") for line in out),
    )
    _check(
        "drop_prefixes removes nothing else -- all four devices survive",
        len([line for line in out if line.startswith("X")]) == 4,
    )
    kept = cc.build_reference(RO_STAGE, params=PARAMS, drop_prefixes=())
    _check(
        "with no drop_prefixes the capacitor is kept (the drop is opt-in)",
        any(line.startswith("Cld") for line in kept),
    )


def check_pass_through_kwargs() -> None:
    """Transformation 2, both halves: params-driven and drop_kwargs-driven."""
    out = cc.build_reference(
        RO_RING5, params=PARAMS, drop_prefixes=("Cld",), drop_kwargs=("cld",)
    )
    body = [line for line in out if line.startswith(("xg", "x1", "x4"))]
    _check("every instance-call line survives", len(body) == 3, str(body))
    _check(
        "no keyword argument survives on an instance call (callee no longer "
        "declares any of these parameters)",
        all("=" not in line for line in body),
        str(body),
    )
    _check(
        "an instance call keeps its full node list and its subckt name",
        body[0] == "xg ro en n1 vddr vss ro_nand2",
        body[0],
    )
    _check(
        "the feedback instance's own nodes are untouched",
        body[2] == "x4 n4 ro vddr vss ro_stage",
        body[2],
    )
    still = cc.build_reference(RO_RING5, params=PARAMS, drop_prefixes=("Cld",))
    _check(
        "without drop_kwargs, cld=cld survives -- the drop is opt-in, and "
        "this is the state that produced klt lvs's 'Not a known parameter "
        "for circuit' warnings",
        any("cld=cld" in line for line in still),
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
    _check("a real value assignment is not dropped", "cld=0.5f" in out[1], out[1])
    _check("a param used as someone else's value stays", "other=cld" in out[2], out[2])
    _check(
        "a longer name that starts with it is not a match",
        "cldx=cldx" in out[3],
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
            "extract_subckt picks the exact subckt, not a longer-named sibling",
            got[0] == ".subckt ro_stage a y" and "pfet" in got[1],
            str(got),
        )
    finally:
        path.unlink()


def check_variant_reference_renames_subckt_and_nested() -> None:
    """``build_variant_reference`` renames the subckt AND its nested deps."""
    path = _write_netlist(RO_NAND2 + RO_STAGE + RO_RING5)
    try:
        instance = RING_VARIANT["instances"][0]  # _r1, wstv=0.42
        out = cc.build_variant_reference(
            path,
            RING_VARIANT,
            instance,
            default_drop_prefixes=("Cld",),
            default_drop_kwargs=("cld",),
        )
        headers = [line for line in out if line.startswith(".subckt")]
        _check(
            "every one of nested + subckt gets its own renamed definition, "
            "innermost (nested) first",
            headers
            == [
                ".subckt ro_nand2_r1 a b y vddr vss",
                ".subckt ro_stage_r1 a y vddr vss",
                ".subckt ro_ring5_r1 en ro vddr vss",
            ],
            str(headers),
        )
        body = [line for line in out if line.startswith(("xg", "x1", "x4"))]
        _check(
            "ro_ring5's own instance-call lines call the renamed siblings, "
            "not the shared unrenamed originals",
            body
            == [
                "xg ro en n1 vddr vss ro_nand2_r1",
                "x1 n1 n2 vddr vss ro_stage_r1",
                "x4 n4 ro vddr vss ro_stage_r1",
            ],
            str(body),
        )
        mph = next(line for line in out if line.startswith("XMph"))
        _check(
            "the instance's own params substitute into the renamed copy",
            "L=2u" in mph and "W=0.42u" in mph,
            mph,
        )
    finally:
        path.unlink()


def check_variant_reference_two_instances_differ() -> None:
    """Two instances of the same variant produce two distinctly-sized copies."""
    path = _write_netlist(RO_NAND2 + RO_STAGE + RO_RING5)
    try:
        out_r1 = cc.build_variant_reference(
            path,
            RING_VARIANT,
            RING_VARIANT["instances"][0],
            default_drop_prefixes=("Cld",),
            default_drop_kwargs=("cld",),
        )
        out_r2 = cc.build_variant_reference(
            path,
            RING_VARIANT,
            RING_VARIANT["instances"][1],
            default_drop_prefixes=("Cld",),
            default_drop_kwargs=("cld",),
        )
        mph_r1 = next(line for line in out_r1 if line.startswith("XMph"))
        mph_r2 = next(line for line in out_r2 if line.startswith("XMph"))
        _check("_r1 keeps ring 1's own wstv (0.42)", "W=0.42u" in mph_r1, mph_r1)
        _check(
            "_r2 gets ring 2's own wstv (0.44), not ring 1's",
            "W=0.44u" in mph_r2 and "W=0.42u" not in mph_r2,
            mph_r2,
        )
        _check(
            "the two instances' subckt names never collide",
            "ro_ring5_r1" in "\n".join(out_r1) and "ro_ring5_r2" in "\n".join(out_r2),
        )
    finally:
        path.unlink()


def check_repoint_variant_instances_matches_only_its_own_instance() -> None:
    """The top subckt's instance lines are repointed one-for-one, not by name."""
    top = cc.build_reference(
        RO_ARRAY_CORE, params=None, drop_prefixes=(), drop_kwargs=()
    )
    out = cc.repoint_variant_instances(top, [RING_VARIANT])
    xr1 = next(line for line in out if line.startswith("xr1"))
    xr2 = next(line for line in out if line.startswith("xr2"))
    _check("xr1 is repointed at ro_ring5_r1", "ro_ring5_r1" in xr1, xr1)
    _check(
        "xr2 is repointed at ro_ring5_r2, not ro_ring5_r1", "ro_ring5_r2" in xr2, xr2
    )
    _check(
        "the now-meaningless wstv/lstv/cld literal overrides are dropped",
        all(kw not in xr1 and kw not in xr2 for kw in ("wstv=", "lstv=", "cld=")),
        f"{xr1!r} {xr2!r}",
    )
    _check(
        "the instance's own node list survives untouched",
        xr1.startswith("xr1 en1 ro1 vddr1 vss ro_ring5_r1")
        and xr2.startswith("xr2 en2 ro2 vddr2 vss ro_ring5_r2"),
        f"{xr1!r} {xr2!r}",
    )


def check_variant_reference_is_end_to_end_self_consistent() -> None:
    """The full array reference: two renamed rings plus a repointed top."""
    path = _write_netlist(RO_NAND2 + RO_STAGE + RO_RING5 + RO_ARRAY_CORE)
    try:
        lines: list[str] = []
        for instance in RING_VARIANT["instances"]:
            lines.extend(
                cc.build_variant_reference(
                    path,
                    RING_VARIANT,
                    instance,
                    default_drop_prefixes=("Cld",),
                    default_drop_kwargs=("cld",),
                )
            )
        top = cc.build_reference(
            cc.extract_subckt(path, "ro_array_core"),
            params=None,
            drop_prefixes=(),
            drop_kwargs=(),
        )
        lines.extend(cc.repoint_variant_instances(top, [RING_VARIANT]))
        text = "\n".join(lines)
        _check(
            "both renamed ring definitions are present",
            "ro_ring5_r1" in text and "ro_ring5_r2" in text,
        )
        _check(
            "the top subckt calls only the renamed rings, never the bare name",
            not re.search(r"\bro_ring5\b(?!_r)", text),
            text,
        )
    finally:
        path.unlink()


def main() -> int:
    check_param_substitution_and_units()
    check_drop_prefixes()
    check_pass_through_kwargs()
    check_drop_kwargs_is_not_greedy()
    check_extract_subckt_is_exact()
    check_variant_reference_renames_subckt_and_nested()
    check_variant_reference_two_instances_differ()
    check_repoint_variant_instances_matches_only_its_own_instance()
    check_variant_reference_is_end_to_end_self_consistent()

    return _checker.summary("layout/test_compose_cell.py")


if __name__ == "__main__":
    raise SystemExit(main())
