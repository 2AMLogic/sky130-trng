#!/usr/bin/env python3
"""Unit test for ``make-netlist.py``'s ``$``-scrub collision guard.

Run directly (no pytest suite in this repo):

    python3 sim/post-layout-whole-block/test_make_netlist.py

Also covers the pw2nd diode card rewrite, the all-card-type model check, and
(issue #478) the two things about the committed evidence that need no klt,
no PDK and no GDS to verify:

* the port map path follows ``-o``, so only the default output writes the
  committed ``trng_whole.sim.ports.json``;
* the committed ``trng_whole.sim.spice.gz`` header port order still equals
  the committed ``trng_whole.sim.ports.json`` order.

Pure Python: no klt, no GDS, no ngspice.
"""
import contextlib
import gzip
import importlib.util
import io
import json
import sys
import tempfile
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


def _stub_extract(raw_text):
    """A ``run_extract`` replacement that writes ``raw_text`` and reads no GDS."""
    def _run(dest):
        dest.write_text(raw_text)
    return _run


def test_ports_path_follows_output() -> None:
    """Issue #478: the port map follows -o; only the default output writes
    the committed trng_whole.sim.ports.json.

    Before this, PORTS_JSON was hardcoded and passed unconditionally, so a
    run whose netlist went somewhere else still overwrote the committed map
    -- on a host whose klt orders the .SUBCKT header differently
    (klayout-tools#5534), with a port order that no longer described the
    committed netlist.
    """
    committed = HERE / "trng_whole.sim.ports.json"
    before = committed.read_bytes()

    # the derivation itself, including the no-.spice-suffix edge case
    assert mn.ports_path_for(mn.DEFAULT_OUT) == mn.PORTS_JSON, (
        "the default output must still write the committed port map")
    assert mn.ports_path_for(Path("/tmp/scratch.spice")) == Path("/tmp/scratch.ports.json")
    assert mn.ports_path_for(Path("/tmp/scratch")) == Path("/tmp/scratch.ports.json")
    assert mn.ports_path_for(Path("/tmp/d.v1/out.cir")) == Path("/tmp/d.v1/out.cir.ports.json")

    # and an end-to-end `-o` run through main(), with the extractor stubbed
    pins = ["vdd", "en", "bus_wdata[1]", "clk"]
    raw = (".SUBCKT trng_whole vdd|vddr2 en|en2|g_en A|bus_wdata[1] clk\n"
           "Xz1 vdd|vddr2 en|en2|g_en A|bus_wdata[1] n$1 sky130_fd_pr__nfet_01v8 W=1\n"
           "Xz2 clk D|X$31 n$1 sky130_fd_pr__nfet_01v8 W=1\n"
           ".ENDS trng_whole\n")
    saved = (mn.EXTRACT_REQUEST, mn.GDS, mn.UNUSED_BY_DESIGN,
             mn.run_extract, mn.klt_version)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        req = td / "extract.request.json"
        req.write_text(json.dumps({"pins": ",".join(pins)}))
        gds = td / "stand-in.gds"
        gds.write_bytes(b"not a GDS: only sha256_file reads it")
        try:
            mn.EXTRACT_REQUEST, mn.GDS = req, gds
            mn.UNUSED_BY_DESIGN = frozenset()  # synthetic block: every port used
            mn.run_extract = _stub_extract(raw)
            mn.klt_version = lambda: "0.0.0+stub"
            out = td / "scratch.spice"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = mn.main(["-o", str(out)])
            assert rc == 0, rc
            assert json.loads(buf.getvalue())["port_count"] == 4
            assert out.exists(), "the netlist did not land at -o"
            side = td / "scratch.ports.json"
            assert side.exists(), "the port map did not land next to -o"
            assert not (td / "trng_whole.sim.ports.json").exists()
            got = json.loads(side.read_text())
            assert [e["canonical"] for e in got["ports"]] == [
                "vdd", "en", "bus_wdata[1]", "clk"], got
        finally:
            (mn.EXTRACT_REQUEST, mn.GDS, mn.UNUSED_BY_DESIGN,
             mn.run_extract, mn.klt_version) = saved
            # restore in `finally`, not after: the pre-fix code overwrites
            # the tracked map INSIDE main(), so an assertion above can fail
            # with the committed evidence already damaged. A failing test
            # must never leave a tracked file rewritten.
            damaged = committed.read_bytes() != before
            if damaged:
                committed.write_bytes(before)

    assert not damaged, (
        "an -o-directed run rewrote the committed trng_whole.sim.ports.json "
        "(restored)")


def _committed_header_ports() -> list:
    """The port tokens of the committed netlist's .SUBCKT header, in order."""
    text = gzip.decompress((HERE / "trng_whole.sim.spice.gz").read_bytes()).decode()
    lines = text.split("\n")
    assert lines[0].startswith(".SUBCKT trng_whole "), lines[0][:40]
    logical, i = [lines[0]], 1
    while lines[i].startswith("+"):
        logical.append(lines[i])
        i += 1
    joined = " ".join(ln[2:] if ln.startswith("+") else ln for ln in logical)
    return joined.split()[2:]   # drop ".SUBCKT" and "trng_whole"


def test_committed_header_matches_ports_json() -> None:
    """Issue #478: the committed netlist and port map still agree.

    trng_whole.sim.ports.json's own comment declares "order = .subckt
    trng_whole port order", so the two committed files are a pair: the map
    describes THAT netlist's header. Nothing checked that they had not
    drifted apart, although the check needs no klt, PDK or GDS -- and the
    way they would drift apart (a stray `-o` run under a klt build that
    orders the header differently, klayout-tools#5534) rewrote exactly one
    of the two.
    """
    header = _committed_header_ports()
    doc = json.loads((HERE / "trng_whole.sim.ports.json").read_text())
    canonical = [mn._normalise_name(e["canonical"]) for e in doc["ports"]]
    assert len(header) == 123, len(header)
    assert len(canonical) == 123, len(canonical)
    assert set(header) == set(canonical), (
        "committed netlist header and port map describe different port sets: "
        f"{sorted(set(header) ^ set(canonical))[:5]}")
    assert header == canonical, (
        "committed netlist header order != committed ports.json order; first "
        "divergence at index "
        f"{next(i for i, (a, b) in enumerate(zip(header, canonical)) if a != b)}")
    # negative control: the comparison is order-sensitive, not a set compare
    shuffled = canonical[1:] + canonical[:1]
    assert set(shuffled) == set(header) and shuffled != header

    # every cluster carries exactly one canonical name as a component label
    for e in doc["ports"]:
        parts = e["cluster"].split("|")
        assert e["canonical"] in parts, e
    assert len({e["canonical"] for e in doc["ports"]}) == 123


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
    test_ports_path_follows_output()
    test_committed_header_matches_ports_json()
    print("test_make_netlist OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
