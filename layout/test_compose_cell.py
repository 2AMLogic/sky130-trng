#!/usr/bin/env python3
"""Unit tests for ``layout/bin/compose-cell.py``'s two silent-failure paths.

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

The second silent path, and the second group of checks:
``resolve_cell_block``, which decides what a ``blocks[].cell`` entry's
``gds_path`` is resolved *relative to*. A committed sibling cell's path is
relative to the cell.json (and so must be absolutized when ``--check``
rebuilds into a temp directory); an earlier **stage**'s own stream
(``cell.from_stage``) is relative to the output directory (and so must NOT
be). Swap those two and nothing fails loudly: a ``--check`` rebuild would
compose its later stages over the *committed* earlier stages and report
"rebuild matches committed evidence" no matter what drifted in stage 1 --
i.e. the reproducibility guarantee would silently become vacuous for exactly
the multi-stage cells that need it most.
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


def check_lvs_reference_repoints_dependency_bodies_too() -> None:
    """A *dependency*'s own variant instance calls are repointed as well.

    ``layout/sampler_core``'s ``lvs`` block names ``ro_array_core`` as a
    plain ``dependencies[]`` entry (there, ``sampler_core`` is the top
    subckt, not ``ro_array_core``) while the ``ro_ring5`` variants stay in
    ``dependency_variants``. Only the renamed ``ro_ring5_r1``/``_r2``
    definitions are ever emitted, so ``ro_array_core``'s own ``xr1``/``xr2``
    lines have to be repointed at them.

    The bug this pins is silent: ``klt lvs`` does not error on a call to an
    undefined subckt, it drops the instance. The generated reference simply
    comes out short -- ``sampler_core``'s read 176 devices where the
    schematic has 264 -- and the LVS verdict is then a comparison against
    the wrong netlist with nothing in the run saying so.
    """
    sampler_core = [
        ".subckt sampler_core en1 en2 vddr1 vddr2 vdd vss",
        "xdut en1 en2 vddr1 vddr2 vss ro_array_core",
        ".ends",
    ]
    path = _write_netlist(
        RO_NAND2 + RO_STAGE + RO_RING5 + RO_ARRAY_CORE + sampler_core
    )
    try:
        lines, variant_names = cc.build_lvs_reference(
            path,
            {
                "subckt": "sampler_core",
                "dependencies": ["ro_array_core"],
                "dependency_variants": [RING_VARIANT],
                "drop_prefixes": ["Cld"],
                "drop_kwargs": ["cld"],
            },
        )
        text = "\n".join(lines)
        _check(
            "the renamed ring definitions are emitted",
            ".subckt ro_ring5_r1" in text and ".subckt ro_ring5_r2" in text,
        )
        _check(
            "the dependency's own instance lines are repointed one-for-one",
            "xr1 en1 ro1 vddr1 vss ro_ring5_r1" in text
            and "xr2 en2 ro2 vddr2 vss ro_ring5_r2" in text,
            text,
        )
        _check(
            "no call anywhere names the bare, never-defined ro_ring5",
            not re.search(r"\bro_ring5\b(?!_r)", text),
            text,
        )
        _check(
            "every subckt a call names is actually defined in the reference",
            _undefined_calls(lines) == [],
            f"undefined: {_undefined_calls(lines)}",
        )
        _check(
            "the variant names are reported for the provenance header",
            variant_names == ["ro_ring5_r1", "ro_ring5_r2"],
            str(variant_names),
        )
    finally:
        path.unlink()


def _undefined_calls(lines: list[str]) -> list[str]:
    """Subckt names called by an ``x...`` card but never defined."""
    defined = {
        line.split()[1].lower()
        for line in lines
        if line.strip().lower().startswith(".subckt")
    }
    called = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped[0] not in "xX":
            continue
        # Drop `key='expr with spaces'` and `key=value` before tokenizing --
        # a quoted geometry expression would otherwise leave its own trailing
        # fragment looking like the card's subckt name.
        stripped = re.sub(r"\S+='[^']*'", "", stripped)
        tokens = [tok for tok in stripped.split() if "=" not in tok]
        if len(tokens) < 2:
            continue
        name = tokens[-1].lower()
        if name.startswith("sky130_fd_pr__"):
            continue  # a device model card, not a subckt call
        if name not in defined:
            called.append(tokens[-1])
    return sorted(set(called))


def check_cell_block_from_stage_is_output_relative() -> None:
    """``cell.from_stage`` resolves against the OUTPUT dir, not the cell.json.

    The reproducibility-critical case is a ``--check`` rebuild, where
    ``out_dir`` is a temp directory and ``spec_dir`` is the committed cell
    directory. A committed sibling cell's ``gds_path`` MUST be absolutized
    against ``spec_dir`` there (the temp dir has no ``../ro_buf/``); a stage's
    own stream MUST NOT be, because the run just wrote it into ``out_dir``.
    Absolutizing it too would silently compose every later stage over the
    *committed* earlier stage, so a ``--check`` would report "matches" no
    matter what drifted in stage 1.
    """
    spec_dir = Path("/repo/layout/ro_array_core")
    out_dir = Path("/tmp/klt-compose-cell-xyz")
    resolved = cc.resolve_cell_block(
        {"from_stage": "vddstub", "ports": [{"name": "vdd", "x_um": 1.0}]},
        block_id="core",
        spec_dir=spec_dir,
        out_dir=out_dir,
        stage_responses={"core": "core.compose.response.json",
                         "vddstub": "vddstub.compose.response.json"},
    )
    _check(
        "gds_path is the stage's own output-relative stream",
        resolved["gds_path"] == "vddstub.gds",
        resolved,
    )
    _check(
        "cell_name defaults to the stage's own composed-cell name",
        resolved["cell_name"] == "vddstub",
        resolved,
    )
    _check(
        "the from_stage key itself does not leak into the klt request",
        "from_stage" not in resolved,
        resolved,
    )
    _check(
        "hand-declared ports[] pass through untouched",
        resolved["ports"] == [{"name": "vdd", "x_um": 1.0}],
        resolved,
    )

    explicit = cc.resolve_cell_block(
        {"from_stage": "vddstub", "cell_name": "something_else", "ports": []},
        block_id="core",
        spec_dir=spec_dir,
        out_dir=out_dir,
        stage_responses={"vddstub": "vddstub.compose.response.json"},
    )
    _check(
        "an explicit cell_name overrides the stage-name default",
        explicit["cell_name"] == "something_else",
        explicit,
    )


def check_cell_block_from_stage_rejects_unknown_stage() -> None:
    """The negative case: a stage name that is not an EARLIER stage.

    Without this, a typo (or a stage referenced before it runs) would fall
    through to ``klt gen-compose`` with a ``gds_path`` naming a file that
    either does not exist yet or -- worse, when rebuilding in place -- is the
    *previous run's* leftover stream, composing this run's later stages over
    stale geometry.
    """
    for name, known in (("vddbus", {"core": "core.compose.response.json"}),
                        ("typo", {})):
        try:
            cc.resolve_cell_block(
                {"from_stage": name, "ports": []},
                block_id="core",
                spec_dir=Path("/repo/layout/ro_array_core"),
                out_dir=Path("/repo/layout/ro_array_core"),
                stage_responses=known,
            )
        except cc.BuildError as exc:
            _check(
                f"from_stage {name!r} raises BuildError naming the block and stage",
                "core" in str(exc) and name in str(exc),
                str(exc),
            )
        else:
            _check(f"from_stage {name!r} raises BuildError", False, "no exception")


def check_cell_block_sibling_path_rule_is_unchanged() -> None:
    """Regression guard: the committed-sibling path keeps its old behaviour.

    Every cell.json already committed under ``layout/`` (``ro_ring5``,
    ``xor2``, ``ro_array_core``'s own first stage) places committed sibling
    cells this way, so the ``from_stage`` branch must not have moved this one.
    """
    spec_dir = Path("/repo/layout/xor2")
    in_place = cc.resolve_cell_block(
        {"gds_path": "../ro_buf/ro_buf.gds", "cell_name": "ro_buf", "ports": []},
        block_id="inv_a",
        spec_dir=spec_dir,
        out_dir=spec_dir,
        stage_responses={},
    )
    _check(
        "rebuilding in place keeps the repo-relative spelling",
        in_place["gds_path"] == "../ro_buf/ro_buf.gds",
        in_place,
    )
    rebuilt = cc.resolve_cell_block(
        {"gds_path": "../ro_buf/ro_buf.gds", "cell_name": "ro_buf", "ports": []},
        block_id="inv_a",
        spec_dir=spec_dir,
        out_dir=Path("/tmp/klt-compose-cell-xyz"),
        stage_responses={},
    )
    _check(
        "--check absolutizes it against the cell.json's own directory",
        rebuilt["gds_path"] == str(Path("/repo/layout/ro_buf/ro_buf.gds")),
        rebuilt,
    )


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
    check_lvs_reference_repoints_dependency_bodies_too()
    check_cell_block_from_stage_is_output_relative()
    check_cell_block_from_stage_rejects_unknown_stage()
    check_cell_block_sibling_path_rule_is_unchanged()

    return _checker.summary("layout/test_compose_cell.py")


if __name__ == "__main__":
    raise SystemExit(main())
