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
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "bin" / "pex-netlist.py"
_spec = importlib.util.spec_from_file_location("pex_netlist", _MODULE_PATH)
assert _spec and _spec.loader
pex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pex)

_FAILURES: list[str] = []

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


def _check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"ok     {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"FAIL   {msg}")
        _FAILURES.append(msg)


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


def main() -> int:
    check_device_card_contract()
    check_joined_net_rename()
    check_missing_alias_is_an_error()
    check_rename_cannot_merge_two_nets()
    check_passthrough_of_parasitic_values()
    check_continuation_lines_are_folded()
    check_unknown_element_card_is_an_error()
    check_wrapper_port_order()

    if _FAILURES:
        print(f"FAIL   {len(_FAILURES)} check(s) failed")
        return 1
    print("PASS   layout/test_pex_netlist.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
