#!/usr/bin/env python3
"""Unit test for ``make-netlist.py``'s ``$``-scrub collision guard.

Run directly (no pytest suite in this repo):

    python3 sim/post-layout-whole-block/test_make_netlist.py

Pure Python: no klt, no GDS, no ngspice.
"""
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("make_netlist", HERE / "make-netlist.py")
mn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mn)


def raises(lines):
    try:
        mn.check_scrub_collisions(lines)
    except SystemExit:
        return True
    return False


def main() -> int:
    # a `$` name alone is not a collision (old guard flagged it)
    assert not raises(["XM1 A$1 B$2 vss nfet", "XM2 A$1 vdd pfet"])
    # `A$1` scrubs to `Az1`, which already exists without `$`: collision
    assert raises(["XM1 A$1 B vss nfet", "XM2 Az1 vdd pfet"])
    # a `$` token on a comment line is not scrubbed, so it cannot collide
    assert not raises(["* A$1 note", "XM2 Az1 vdd pfet"])
    assert not raises(["XM1 A$1 b nfet", "* Az1 note"])
    # linear time on a large netlist (old guard was quadratic)
    big = [f"XM{i} n$%d n{i} vss nfet" % i for i in range(200000)]
    t0 = time.time()
    assert not raises(big)
    assert time.time() - t0 < 10, "guard is not linear"
    print("test_make_netlist OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
