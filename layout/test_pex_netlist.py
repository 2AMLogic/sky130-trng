#!/usr/bin/env python3
"""Unit test for ``layout/bin/pex-netlist.py``'s netlist rewrite.

Standalone script, following ``design/test_pdk_search.py``'s and
``design/test_netlist_erc.py``'s "run it directly" convention -- there is no
pytest suite in this repository:

    python3 layout/test_pex_netlist.py

Pure Python: no ``klt``, no KLayout, no PDK install, no ngspice, no GDS.
Everything here runs in any environment, which is why it is on this repo's
PR-blocking CI path while the real extraction is not.

Why this exists. ``layout/bin/pex-netlist.py`` turns an extracted netlist
into something ngspice will run, and every step it takes could silently
produce a *plausible but wrong* netlist -- a merged pair of nets, a device
scaled by 1e-6, a terminal on the wrong node -- whose simulation would
converge and report numbers with no error anywhere. ``--check``'s
byte-for-byte rebuild proves the committed library matches what the script
produces today; it cannot prove the script produces the right thing. This
test covers that half:

- the device-card CONTRACT is asserted, not assumed: `klt extract --pdk`
  already writes subcircuit calls on the PDK's own devices with unitless
  geometry, and the build must reject an ``M`` card, an undeclared model, or
  a unit-suffixed geometry value rather than pass any of them through (the
  "silently 1e-6 off" and "bound to the wrong device" cases)
- the joined-net rename is applied to the hub node AND to the per-terminal
  ``__tN`` leg nodes' prefixes, and is rejected if it would merge two nets
  (the "two nets became one" case)
- an extractor-joined name with no declared alias is an error, never a
  pass-through (the "new cell shape silently ships unrenamed" case)
- the wrapper's port order is the design's, its inner instance's port order
  is the extractor's, and a declared port the extraction does not have is an
  error (the "terminals on the wrong node" case)
- R and C element values are passed through untouched
- ``--check``'s report comparison canonicalizes the extractor's OWN net
  numbering (issue #93) -- an anonymous net relabelled ``\\$3`` -> ``\\$4``
  by a different ``klt`` build, or a permuted ``net_id``, is not verdict
  drift, while any change to an R, a C, a count, a terminal or a connection
  still is (the "a cosmetic upstream relabel reads as a failed
  reproducibility gate" case, and its far more dangerous inverse, "a real
  parasitic change hides inside a canonicalization that is too eager")
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "bin" / "pex-netlist.py"
_spec = importlib.util.spec_from_file_location("pex_netlist", _MODULE_PATH)
assert _spec and _spec.loader
pex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pex)

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "design"))
from _test_check import Checker  # noqa: E402

_checker = Checker()
_check = _checker.check

MODELS = ["sky130_fd_pr__nfet_01v8", "sky130_fd_pr__pfet_01v8"]

#: A minimal stand-in for a two-pass-composed cell's extracted netlist: one
#: joined net (pin label + net label on one physical net), one $-indexed
#: unnamed net, a continuation line, a star of leg resistors and a
#: net-to-substrate capacitor. Shaped exactly like layout/pex/raw/*.pex.spice.
SAMPLE = r"""* extracted by klt extract --deck sky130
* parasitic model (--parasitics):
* - resistance: single lumped series resistance per net

* cell demo
* pin a
* pin mnt_g,vddr
* pin y
.SUBCKT demo a mnt_g|vddr y
* device instance $1 r0 *1 1.42,0.21 nfet
X$1 y__t0 a__t0 \$3__t0 mnt_g\x7cvddr__t2 sky130_fd_pr__nfet_01v8 L=2
+ W=0.42 AS=0.1764 AD=0.1764 PS=1.68 PD=1.68
* device instance a_t0 r0 *1 0,0
Ra_t0 a__t0 a 244.0639
* device instance mnt_g_vddr_t2 r0 *1 0,0
Rmnt_g_vddr_t2 mnt_g\x7cvddr__t2 mnt_g|vddr 51.1138625327
* device instance y r0 *1 0,0
Cy y vsubs 6.03733e-16
* device instance vsubs_dctie r0 *1 0,0
Rvsubs_dctie vsubs 0 1e+12
.ENDS demo
"""

ALIASES = {"mnt_g|vddr": "vddr"}


def _raises(fn, label: str, fragment: str) -> None:
    try:
        fn()
    except pex.BuildError as exc:
        _check(label, fragment in str(exc), f"message was {exc!r}")
    else:
        _check(label, False, "no BuildError raised")


def _rewrite(text: str = SAMPLE, aliases: dict | None = None):
    return pex.rewrite_cell(
        text,
        core_name="demo__core",
        aliases=ALIASES if aliases is None else aliases,
        expected_models=MODELS,
    )


# --------------------------------------------------------------------------
# geometry: unit suffixes vs. .option scale=1u
# --------------------------------------------------------------------------


def check_device_card_contract() -> None:
    """`klt extract --pdk`'s written form is asserted, never assumed."""
    good = (
        "X$1 d g s b sky130_fd_pr__nfet_01v8 L=2 W=0.42 AS=0.1764 AD=0.1764 "
        "PS=1.68 PD=1.68"
    )
    _check(
        "check_device_card: a conforming X card passes through unchanged",
        pex.check_device_card(good, MODELS) == good,
    )
    _raises(
        lambda: pex.check_device_card(
            "M$1 d g s b nfet L=2U W=0.42U", MODELS
        ),
        "check_device_card: a deck-native M card is an error",
        "is not a subcircuit call",
    )
    _raises(
        lambda: pex.check_device_card(
            "X$1 d g s b sky130_fd_pr__nfet_01v8_lvt L=2 W=0.42", MODELS
        ),
        "check_device_card: an undeclared device model is an error",
        "is not in the descriptor's expect_device_models",
    )
    _raises(
        lambda: pex.check_device_card(
            "X$1 d g s b sky130_fd_pr__nfet_01v8 L=2U W=0.42", MODELS
        ),
        "check_device_card: a unit-suffixed geometry value is an error",
        "not a bare unitless number",
    )
    _raises(
        lambda: pex.check_device_card(
            "X$1 d g s b sky130_fd_pr__nfet_01v8 L=2 SA=0.3", MODELS
        ),
        "check_device_card: an unexpected device parameter is an error",
        "unexpected device parameter",
    )


# --------------------------------------------------------------------------
# net renaming
# --------------------------------------------------------------------------


def check_joined_net_rename() -> None:
    lines, ports = _rewrite()
    body = "\n".join(lines)
    _check("rewrite_cell: joined name gone from the port list", ports[1] == "vddr", str(ports))
    _check(
        "rewrite_cell: no '|' or '\\x7c' survives anywhere outside comments",
        not any(
            ("|" in ln or "\\x7c" in ln) for ln in lines if not ln.startswith("*")
        ),
        body,
    )
    _check(
        "rewrite_cell: the escaped leg-node prefix is renamed with its hub",
        "vddr__t2" in body and "mnt_g\\x7cvddr" not in body,
        body,
    )
    _check(
        "rewrite_cell: leg node stays distinct from its hub node",
        "Rmnt_g_vddr_t2 vddr__t2 vddr 51.1138625327" in body,
        body,
    )
    _check(
        "rewrite_cell: '$' never reaches an emitted node or element name",
        not any("$" in ln for ln in lines if not ln.startswith("*")),
        body,
    )


def check_missing_alias_is_an_error() -> None:
    """An unrenamed joined name must never reach the library."""
    _raises(
        lambda: _rewrite(aliases={}),
        "rewrite_cell: joined name with no alias is an error",
        "no net_aliases entry",
    )


def check_rename_cannot_merge_two_nets() -> None:
    """Two DISTINCT extractor names must never collapse onto one node.

    The dangerous shape is a cell that carries both a joined name
    (``mnt_g|vddr``) and a separate net already literally called ``vddr``:
    the declared rename would silently make them one node, shorting a gate
    to a rail with no error anywhere downstream. The guard rejects it.
    """
    colliding = SAMPLE.replace("Cy y vsubs", "Cy vddr vsubs")
    _raises(
        lambda: pex.rewrite_cell(
            colliding, core_name="demo__core", aliases=ALIASES,
            expected_models=MODELS,
        ),
        "rewrite_cell: a rename that would merge two nets is an error",
        "renaming would merge two distinct nets",
    )
    # The same source name appearing many times is of course fine -- the
    # guard keys on (rewritten name -> source name), not on occurrences.
    repeated = SAMPLE.replace(
        "Cy y vsubs 6.03733e-16",
        "Cy y vsubs 6.03733e-16\nCv mnt_g|vddr vsubs 1.77e-15",
    )
    lines, _ = pex.rewrite_cell(
        repeated, core_name="demo__core", aliases=ALIASES, expected_models=MODELS
    )
    _check(
        "rewrite_cell: repeated occurrences of one source name are fine",
        "Cv vddr vsubs 1.77e-15" in "\n".join(lines),
        "\n".join(lines),
    )


def check_passthrough_of_parasitic_values() -> None:
    lines, _ = _rewrite()
    body = "\n".join(lines)
    for element in (
        "Ra_t0 a__t0 a 244.0639",
        "Cy y vsubs 6.03733e-16",
        "Rvsubs_dctie vsubs 0 1e+12",
    ):
        _check(f"rewrite_cell: passes through `{element}` untouched", element in body, body)


def check_continuation_lines_are_folded() -> None:
    lines = pex.join_continuations("M$1 a b\n+ c d\nRx 1 2 3\n")
    _check(
        "join_continuations: folds a `+` line into its logical line",
        lines == ["M$1 a b c d", "Rx 1 2 3"],
        str(lines),
    )
    _raises(
        lambda: pex.join_continuations("+ orphan\n"),
        "join_continuations: leading continuation is an error",
        "starts with a continuation line",
    )


def check_unknown_element_card_is_an_error() -> None:
    """Silently dropping an element the extractor emitted is unacceptable."""
    with_diode = SAMPLE.replace("Cy y vsubs 6.03733e-16", "Dpar y vsubs dmodel")
    _raises(
        lambda: _rewrite(with_diode),
        "rewrite_cell: an unhandled element card is an error",
        "unhandled element card",
    )


# --------------------------------------------------------------------------
# the design-port-order wrapper
# --------------------------------------------------------------------------


def check_wrapper_port_order() -> None:
    core_ports = ["a", "vddr", "vss", "ny", "py", "y"]
    cell = {"name": "demo_pex", "ports": ["a", "y", "vddr", "vss"]}
    out = pex.wrapper_lines(cell, "demo_pex__core", core_ports)
    _check(
        "wrapper: .subckt line carries the DESIGN port order",
        ".subckt demo_pex a y vddr vss" in out,
        str(out),
    )
    _check(
        "wrapper: inner instance carries the EXTRACTOR port order",
        "xpex a vddr vss ny py y demo_pex__core" in out,
        str(out),
    )
    _check(
        "wrapper: promoted-internal pins are named in a comment",
        any("ny, py" in line for line in out),
        str(out),
    )
    _raises(
        lambda: pex.wrapper_lines(
            {"name": "demo_pex", "ports": ["a", "y", "vddr", "vss", "nope"]},
            "demo_pex__core",
            core_ports,
        ),
        "wrapper: a declared port the layout does not have is an error",
        "are not pins of the extracted cell",
    )


# --------------------------------------------------------------------------
# canonicalizing the extractor's own net numbering (issue #93)
# --------------------------------------------------------------------------

#: An extraction report's `parasitics` block for a two-device cell with one
#: named net (`y`) and one extractor-anonymous net (`\$3`), shaped exactly
#: like layout/pex/reports/*.extract.json's. `_renumbered()` below produces
#: the SAME cell as a different klt build spells it: the anonymous net is
#: `\$4`, and every net_id is permuted. That is the whole of the drift
#: measured on this repo's ro_nand2 cells in issue #93.
PARASITICS = {
    "r_count": 4,
    "c_count": 2,
    "total_resistance_ohm": 100.0,
    "total_capacitance_ff": 1.5,
    "substrate_dc_tie": {"resistance_ohm": 1e12},
    "nets": [
        {
            "net": "\\$3",
            "net_id": 3,
            "resistance_ohm": 25.6,
            "capacitance_ff": 0.115618,
            "hub_net": "\\$3",
            "rc_model": "lumped",
            "terminals": [
                {"device": "$2", "terminal": "D", "leg_net": "\\$3__t0",
                 "resistance_ohm": 12.8},
                {"device": "$3", "terminal": "S", "leg_net": "\\$3__t1",
                 "resistance_ohm": 12.8},
            ],
            "segments": [],
            "coupled": [],
        },
        {
            "net": "y",
            "net_id": 6,
            "resistance_ohm": 74.4,
            "capacitance_ff": 1.384382,
            "hub_net": "y",
            "rc_model": "lumped",
            "terminals": [
                {"device": "$2", "terminal": "S", "leg_net": "y__t0",
                 "resistance_ohm": 74.4},
            ],
            "segments": [],
            "coupled": [{"net": "\\$3", "capacitance_ff": 0.0159, "levels": [[0, 1]]}],
        },
    ],
}


def _renumbered() -> dict:
    """The same cell as a different klt build numbers it."""
    other = copy.deepcopy(PARASITICS)
    anon, named = other["nets"]
    anon["net"] = anon["hub_net"] = "\\$4"
    anon["net_id"] = 4
    for index, terminal in enumerate(anon["terminals"]):
        terminal["leg_net"] = f"\\$4__t{index}"
    named["net_id"] = 2
    named["coupled"][0]["net"] = "\\$4"
    # ...and emits the nets in the new counter's order, not the old one's.
    other["nets"] = [named, anon]
    return other


def check_canonicalization_absorbs_pure_renumbering() -> None:
    left = pex.canonical_parasitics(PARASITICS)
    right = pex.canonical_parasitics(_renumbered())
    _check(
        "canonical_parasitics: a pure \\$3->\\$4 relabel + net_id permutation "
        "compares equal",
        left == right,
        f"{left!r}\n!=\n{right!r}",
    )
    _check(
        "canonical_parasitics: the anonymous net is keyed on its own device "
        "terminals, not on the extractor's counter",
        left["nets"][0]["net"] == "\\$anon($2.D,$3.S)",
        str([n["net"] for n in left["nets"]]),
    )
    _check(
        "canonical_parasitics: net_id is dropped on both sides",
        not any("net_id" in n for n in left["nets"]),
        str(left["nets"]),
    )
    _check(
        "canonical_parasitics: a named net keeps its own name",
        any(n["net"] == "y" for n in left["nets"]),
        str([n["net"] for n in left["nets"]]),
    )
    for field in ("r_count", "c_count", "total_resistance_ohm",
                  "total_capacitance_ff", "substrate_dc_tie"):
        _check(
            f"canonical_parasitics: passes `{field}` through untouched",
            left[field] == PARASITICS[field],
            f"{left[field]!r}",
        )
    _check(
        "compare_report: a pure relabel is not reported as drift",
        pex.compare_report(
            {"parasitics": PARASITICS}, {"parasitics": _renumbered()}, "demo"
        )
        == [],
    )


def _net(parasitics: dict, name: str) -> dict:
    """The net entry called *name*, whatever order the block lists nets in."""
    return next(n for n in parasitics["nets"] if n["net"] == name)


def check_canonicalization_still_sees_real_change() -> None:
    """The dangerous inverse: a real parasitic change must NOT be absorbed."""
    for label, mutate in (
        ("a per-net resistance",
         lambda p: _net(p, "y").update(resistance_ohm=99.9)),
        ("a per-net capacitance",
         lambda p: _net(p, "\\$4").update(capacitance_ff=0.9)),
        ("a total", lambda p: p.update(total_resistance_ohm=101.0)),
        ("a count", lambda p: p.update(r_count=5)),
        ("a coupling value",
         lambda p: _net(p, "y")["coupled"][0].update(capacitance_ff=0.5)),
        ("a coupling partner",
         lambda p: _net(p, "y")["coupled"][0].update(net="vss")),
        ("a terminal's device",
         lambda p: _net(p, "y")["terminals"][0].update(device="$9")),
        ("a terminal's leg resistance",
         lambda p: _net(p, "\\$4")["terminals"][0].update(resistance_ohm=1.0)),
        ("the substrate tie",
         lambda p: p.update(substrate_dc_tie={"resistance_ohm": 1.0})),
        ("a dropped net", lambda p: p["nets"].remove(_net(p, "y"))),
    ):
        changed = _renumbered()
        mutate(changed)
        drift = pex.compare_report(
            {"parasitics": PARASITICS}, {"parasitics": changed}, "demo"
        )
        _check(
            f"compare_report: canonicalization does NOT hide a change to {label}",
            drift != [],
            "no drift reported",
        )
    _check(
        "compare_report: a non-parasitic verdict field is still compared",
        pex.compare_report(
            {"device_count": 6, "parasitics": PARASITICS},
            {"device_count": 7, "parasitics": _renumbered()},
            "demo",
        )
        != [],
    )


def check_canonicalization_cannot_merge_two_nets() -> None:
    """Two anonymous nets that share a structural key must be an error.

    A collision would make two distinct nets compare as one, which is the
    same class of silent failure `rewrite_cell`'s injectivity guard exists
    to prevent -- so it is loud here too rather than "close enough".
    """
    colliding = copy.deepcopy(PARASITICS)
    twin = copy.deepcopy(colliding["nets"][0])
    twin["net"] = twin["hub_net"] = "\\$7"
    colliding["nets"].append(twin)
    _raises(
        lambda: pex.canonical_parasitics(colliding),
        "canonical_parasitics: two anonymous nets sharing a structural key is "
        "an error",
        "share the structural key",
    )
    detached = copy.deepcopy(PARASITICS)
    detached["nets"][0]["terminals"] = []
    _raises(
        lambda: pex.canonical_parasitics(detached),
        "canonical_parasitics: an anonymous net with no terminals is an error",
        "no device terminals",
    )


def check_library_header_names_its_own_descriptor() -> None:
    """The generated banner names the descriptor that was actually invoked.

    Issue #94: ``build_library``'s header used to hardcode the literal
    string ``layout/pex/pex.json`` regardless of which descriptor produced
    the library, so ``layout/pex/sampler_dff_pex.spice`` (built from
    ``pex-sampler.json``) opened with a banner naming the wrong descriptor
    and the wrong ``--check`` command. Covers two distinct descriptor paths
    so a fix that hardcodes a second wrong filename (special-casing one
    path instead of threading the real one through) is caught too.
    """
    for descriptor in ("layout/pex/pex.json", "layout/pex/pex-sampler.json"):
        header = pex.library_header("vsubs", descriptor)
        body = "\n".join(header)
        _check(
            f"library_header({descriptor!r}): names itself in the "
            "'GENERATED by ... from' line",
            f"from {descriptor}." in body,
            body,
        )
        _check(
            f"library_header({descriptor!r}): the quoted --check command "
            "re-checks itself, not a different descriptor",
            f"python3 layout/bin/pex-netlist.py {descriptor} --check" in body,
            body,
        )
        others = {"layout/pex/pex.json", "layout/pex/pex-sampler.json"} - {descriptor}
        for other in others:
            _check(
                f"library_header({descriptor!r}): does not also name {other!r}",
                other not in body,
                body,
            )


def check_descriptor_path_is_not_hardcoded_to_layout_pex() -> None:
    """``main``'s descriptor string is derived from the real path, issue #22.

    ``check_library_header_names_its_own_descriptor`` above covers
    ``library_header`` itself; this covers the caller that used to compute
    the string it passes in. The old ``main`` did
    ``f"layout/pex/{spec_path.name}"`` -- varying only the filename -- so a
    descriptor living in a sibling directory (``layout/pex-ring/pex.json``,
    ``layout/pex-array/pex.json``, or any future ``layout/pex-*/`` directory)
    got a header naming the WRONG directory, silently: the banner's own
    quoted ``--check`` command would re-verify a different descriptor (or
    none at all) than the one that actually built the library.
    """
    repo_root = Path("/repo")
    cases = (
        (repo_root / "layout" / "pex" / "pex.json", "layout/pex/pex.json"),
        (repo_root / "layout" / "pex" / "pex-sampler.json", "layout/pex/pex-sampler.json"),
        (repo_root / "layout" / "pex-ring" / "pex.json", "layout/pex-ring/pex.json"),
        (repo_root / "layout" / "pex-array" / "pex.json", "layout/pex-array/pex.json"),
        (
            repo_root / "layout" / "pex-sampler-dff-assembled" / "pex.json",
            "layout/pex-sampler-dff-assembled/pex.json",
        ),
    )
    for spec_path, expected in cases:
        got = pex.descriptor_path(spec_path, repo_root=repo_root)
        _check(
            f"descriptor_path({spec_path}) -> {expected!r}",
            got == expected,
            got,
        )


def check_anonymous_base() -> None:
    for name, expected in (
        ("\\$3", "\\$3"),
        ("\\$3__t0", "\\$3"),
        ("$12", "$12"),
        ("$12__t7", "$12"),
        ("a", None),
        ("a__t0", None),
        ("vsubs", None),
        ("mnab_y|mpa_y|mpb_y|y", None),
        ("n3", None),
    ):
        _check(
            f"anonymous_base({name!r}) -> {expected!r}",
            pex.anonymous_base(name) == expected,
            repr(pex.anonymous_base(name)),
        )


def main() -> int:
    check_device_card_contract()
    check_joined_net_rename()
    check_missing_alias_is_an_error()
    check_rename_cannot_merge_two_nets()
    check_passthrough_of_parasitic_values()
    check_continuation_lines_are_folded()
    check_unknown_element_card_is_an_error()
    check_wrapper_port_order()
    check_library_header_names_its_own_descriptor()
    check_descriptor_path_is_not_hardcoded_to_layout_pex()
    check_anonymous_base()
    check_canonicalization_absorbs_pure_renumbering()
    check_canonicalization_still_sees_real_change()
    check_canonicalization_cannot_merge_two_nets()

    return _checker.summary("layout/test_pex_netlist.py")


if __name__ == "__main__":
    raise SystemExit(main())
