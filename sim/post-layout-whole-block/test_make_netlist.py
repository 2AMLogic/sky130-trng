#!/usr/bin/env python3
"""Unit test for ``make-netlist.py``'s ``$``-scrub collision guard.

Run directly (no pytest suite in this repo):

    python3 sim/post-layout-whole-block/test_make_netlist.py

Also covers the pw2nd diode card rewrite and the all-card-type model check.

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


def _canon(text, pins):
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        req = Path(td) / "extract.request.json"
        req.write_text(json.dumps({"pins": ",".join(pins)}))
        old, mn.EXTRACT_REQUEST = mn.EXTRACT_REQUEST, req
        try:
            return mn.canonicalise(text)
        finally:
            mn.EXTRACT_REQUEST = old


def test_body_rename() -> None:
    """Issue #435: header AND body use canonical port names."""
    pins = ["vdd", "en", "bus_wdata[1]", "clk"]
    mn.UNUSED_BY_DESIGN = frozenset()  # synthetic block: every port is used
    hdr = ".SUBCKT trng_whole vdd|vddr2 en|en2|g_en A|bus_wdata[1] clk\n"
    body = ("Xz1 vdd|vddr2 en|en2|g_en A|bus_wdata[1] n$1 sky130_fd_pr__nfet_01v8 W=1\n"
            "Xz2 clk D|X$31 n$1 sky130_fd_pr__nfet_01v8 W=1\n"
            "* vdd|vddr2 stays in comments\n.ENDS trng_whole\n")
    text, mapping = _canon(hdr + body, pins)
    lines = text.splitlines()
    assert lines[0] == ".SUBCKT trng_whole vdd en bus_wdata_1_ clk", lines[0]
    assert lines[1] == "Xz1 vdd en bus_wdata_1_ nz1 sky130_fd_pr__nfet_01v8 W=1", lines[1]
    assert lines[2] == "Xz2 clk D|Xz31 nz1 sky130_fd_pr__nfet_01v8 W=1", lines[2]
    assert "* vdd|vddr2 stays in comments" in lines  # comments untouched
    assert not any("vddr2" in ln or "en2" in ln for ln in lines if not ln.startswith("*"))
    # a port left unreferenced by the body (clk only in the header) fails
    unref = body.replace("Xz2 clk ", "Xz2 other ")
    try:
        _canon(hdr + unref, pins)
    except SystemExit as e:
        assert "clk" in str(e), e
    else:
        raise AssertionError("unreferenced port not detected")
    # a canonical name already used as a distinct body token fails
    clash = body + "Xz3 vdd n$1 sky130_fd_pr__nfet_01v8 W=1\n"
    try:
        _canon(hdr + clash, pins)
    except SystemExit as e:
        assert "collide" in str(e), e
    else:
        raise AssertionError("canonical-name collision not detected")


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
    # D card with the extractor's bare model becomes a PDK-subckt X card
    d = ("Dz1\n+ VSS|a\n+ A|b\n+ diode_pw2nd_05v5 A=0.4347P P=2.64U\nXz2 a b c vss n W=1\n")
    out = mn.DIODE_CARD_RE.sub(mn._diode_to_subckt, d)
    assert out.startswith("Xz1\n+ VSS|a\n+ A|b\n+ sky130_fd_pr__diode_pw2nd_05v5 "
                          "area=0.4347P perim=2.64U\nXz2"), out
    # all-card-type model check (control: must flag an undefined D model)
    spec2 = importlib.util.spec_from_file_location(
        "cbc", HERE / "check-bin-coverage.py")
    cbc = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(cbc)
    defined = {"sky130_fd_pr__diode_pw2nd_05v5", "sky130_fd_pr__nfet_01v8"}
    nl = (".SUBCKT top a b\n* comment diode_x\nDz1 a\n+ b diode_pw2nd_05v5 A=1P P=2U\n"
          "Xz2 a b sky130_fd_pr__nfet_01v8 L=0.15 W=0.42\n"
          "Xz3 a\n+ b sky130_fd_pr__diode_pw2nd_05v5 area=1P perim=2U\n"
          "R1 a b res_missing W=1\n.ENDS top\n")
    bad = cbc.undefined_models(nl, defined)
    assert dict(bad) == {("D", "diode_pw2nd_05v5"): 1, ("R", "res_missing"): 1}, bad
    assert not cbc.undefined_models(nl.replace("Dz1", "Xz1").replace(
        "diode_pw2nd_05v5 A=1P P=2U", "sky130_fd_pr__diode_pw2nd_05v5 area=1P perim=2U"
    ).replace("res_missing", "sky130_fd_pr__nfet_01v8"), defined)
    test_body_rename()
    print("test_make_netlist OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
