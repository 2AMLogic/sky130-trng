#!/usr/bin/env python3
"""Regression test for the ERC wiring in ``design/netlist.py`` (issue #16).

Not part of any pytest suite -- there is none for ``netlist.py`` in this
repository -- but a standalone script that follows ``netlist.py``'s own
"run it directly" convention:

    python3 design/test_netlist_erc.py

It exercises the exact gap ``--check``'s textual staleness diff cannot
close on its own (see the module docstring of ``design/netlist.py``,
"Connectivity, not just staleness"):

1. **A deliberately-broken schematic is caught.** A full copy of
   ``design/xschem/`` has one ``lab_pin`` moved off the net it is meant to
   tag -- ``xor2.sch``'s ``lan`` pin (``name=lan lab=an``), the precise
   reproduction from issue #16's curation pass. Exporting ``ro_array_core``
   (which reaches the broken ``xor2`` instance three hierarchy levels down,
   not standalone) with ``erc=True`` must raise
   :class:`netlist.ErcViolation`.
2. **The current TOP_CELLS still pass cleanly.** Every entry in
   ``netlist.TOP_CELLS`` must export with ``erc=True`` against the real,
   committed ``design/xschem/`` without raising -- wiring ERC into
   ``--check`` must not turn a currently-clean tree red.

Needs xschem and the sky130 PDK on the same terms ``design/netlist.py
--check`` does. If either is unavailable this prints a ``SKIP`` line and
exits 0, degrading the same way ``--check`` is kept off the PR-blocking
path for exactly that reason (see ``.github/workflows/ci.yml`` and
``.github/workflows/pdk-nightly.yml``).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import netlist  # path insert above must run before this import resolves

#: The exact reproduction from issue #16's curation pass: this lab_pin tags
#: the `an` net at its correct coordinate. Moving it elsewhere leaves `an`
#: undriven -- a wrong-but-internally-consistent netlist that a textual
#: staleness diff alone cannot catch, since a "before" and "after"
#: regeneration of the same broken schematic agree on the same wrong result.
_NEEDLE = "C {lab_pin.sym} -580 -250 0 0 {name=lan lab=an}"
_MOVED = "C {lab_pin.sym} -580 -900 0 0 {name=lan lab=an}"

#: ro_array_core reaches the broken xor2 instance three hierarchy levels
#: down (ro_array_core -> ... -> xor2), which is what actually reproduces
#: issue #16's scenario -- not a standalone xor2 netlist.
_HIERARCHY_TOP = "ro_array_core"


def _make_broken_schematic_dir(tmp: Path) -> Path:
    """A full copy of ``design/xschem/`` with ``xor2.sch``'s ``lan`` pin
    moved off its net."""
    broken = tmp / "xschem"
    shutil.copytree(netlist.SCHEMATIC_DIR, broken)
    xor2 = broken / "xor2.sch"
    text = xor2.read_text()
    if _NEEDLE not in text:
        raise RuntimeError(
            "design/xschem/xor2.sch no longer contains the lab_pin line "
            "this regression test moves off its net -- update _NEEDLE in "
            "design/test_netlist_erc.py to match the current schematic"
        )
    xor2.write_text(text.replace(_NEEDLE, _MOVED))
    return broken


def check_broken_schematic_is_caught() -> None:
    """(a) A lab_pin moved off its net makes ERC fail, through hierarchy."""
    with tempfile.TemporaryDirectory() as tmp:
        broken_dir = _make_broken_schematic_dir(Path(tmp))
        original_schematic_dir = netlist.SCHEMATIC_DIR
        netlist.SCHEMATIC_DIR = broken_dir
        try:
            with tempfile.TemporaryDirectory() as outdir:
                netlist.export(_HIERARCHY_TOP, Path(outdir), erc=True)
        except netlist.ErcViolation as exc:
            if "an" not in str(exc):
                raise AssertionError(
                    "ErcViolation raised, but its message does not mention "
                    f"the undriven net 'an' -- got:\n{exc}"
                ) from None
            print(
                f"ok     broken schematic ({_HIERARCHY_TOP} pulling in a "
                "mis-wired xor2.sch) is caught by ERC"
            )
        else:
            raise AssertionError(
                f"expected netlist.ErcViolation exporting {_HIERARCHY_TOP} "
                "against a schematic with a lab_pin moved off its net, but "
                "export() succeeded -- ERC did not catch the broken "
                "connectivity"
            )
        finally:
            netlist.SCHEMATIC_DIR = original_schematic_dir


def check_top_cells_still_pass() -> None:
    """(b) The real, committed TOP_CELLS still export cleanly with ERC on."""
    for top in netlist.TOP_CELLS:
        with tempfile.TemporaryDirectory() as outdir:
            try:
                netlist.export(top, Path(outdir), erc=True)
            except netlist.ErcViolation as exc:
                raise AssertionError(
                    f"{top}: committed schematic failed ERC -- wiring ERC "
                    f"into --check would turn this cell red:\n{exc}"
                ) from None
        print(f"ok     {top}: ERC clean (committed design/xschem/{top}.sch)")


def main() -> int:
    if shutil.which(netlist.XSCHEM) is None:
        print(f"SKIP   {netlist.XSCHEM} not found on PATH -- cannot run this test")
        return 0
    try:
        netlist.find_pdk()
    except netlist.ExportError as exc:
        print(f"SKIP   no sky130 PDK install found -- cannot run this test\n{exc}")
        return 0

    check_broken_schematic_is_caught()
    check_top_cells_still_pass()
    print("PASS   design/test_netlist_erc.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
