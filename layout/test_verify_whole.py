#!/usr/bin/env python3
"""Contract tests for ``layout/bin/verify-whole.py`` / ``verify_whole_lib.py``
(issue #173).

Standalone script, following ``layout/test_compose_whole.py``'s "run it
directly" convention:

    python3 layout/test_verify_whole.py

No ``klt``, no PDK and no GDS read on the PR-blocking CI path: the library
logic is exercised on small synthetic SPICE, and the committed evidence under
``layout/trng_whole/verify/`` is checked for self-consistency (hashes, verdict
fields, coverage matrix, fault-control results). Groups that need the
``klayout_tools`` package skip themselves where it is not importable.

What these guard, because a verdict string alone is not evidence:

- the pin canonicaliser must NEVER repair a net that carries zero or several
  whole-block port names (a short between two ports must stay visible);
- the endpoint audit must flag a single moved standard-cell pin;
- the committed reports must still describe the committed inputs and the
  committed canonical layout netlist, and every fault control must have reached
  the LVS comparison and failed naming its nets.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "design"))
sys.path.insert(0, str(_HERE / "bin"))
from _test_check import Checker  # noqa: E402
import verify_whole_lib as V  # noqa: E402

_checker = Checker()
_check = _checker.check
VERIFY = _HERE / "trng_whole" / "verify"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# library: reference building blocks
# --------------------------------------------------------------------------

ANALOG = """\
.subckt inner a y vdd vss
XMp y a vdd vdd sky130_fd_pr__pfet_01v8 L=0.15u W='int((1 + 1)/2) * w'
XMn y a vss vss sky130_fd_pr__nfet_01v8 L=0.15u W=0.42u
.ends

.subckt top a y vdd vss
Xi1 a m vdd vss inner
Xi2 m y vdd vss inner
.ends
"""


def check_flatten() -> None:
    subs = V.parse_subckts(ANALOG)
    _check("parse_subckts keeps a quoted expression as one token",
           any("W='int((1 + 1)/2) * w'" in c for c in subs["inner"]["cards"][0]), subs["inner"]["cards"][0])
    cards, n = V.flatten_analog(subs, "top", {p: p for p in subs["top"]["ports"]}, "a_")
    _check("flatten_analog expands 2 instances x 2 devices", n == 4, n)
    names = {c[0] for c in cards}
    _check("flattened instance names are unique and path-prefixed", len(names) == 4 and all(x.startswith("Xa_") for x in names), names)
    # i1.y and i2.a are the same internal net m
    nets = Counter(t for c in cards for t in c[1:5])
    _check("the internal net m joins the two instances", nets["a_m"] == 4, dict(nets))


def check_canonicalise() -> None:
    ports = ["vdd", "vss", "a", "b"]
    text = "\n".join([
        "* extracted",
        ".SUBCKT top",
        "+ VGND|vss|junk",
        "+ VPWR|vdd",
        "+ a|internal_a",
        "+ b|a2",           # carries port b only
        "+ lonely",         # no port name
        ".ENDS top",
    ])
    out, info = V.canonicalise_pins(text, "top", ports)
    _check("a net with exactly one port name is renamed to it", info["renamed"] == 4 and "VGND|vss|junk" not in out, info)
    _check("the renamed pin list is the port names", V.top_pins(out, "top")[:4] == ["vss", "vdd", "a", "b"], V.top_pins(out, "top"))
    _check("a pin with no port name stays unnamed and is reported", info["unnamed_pins"] == ["lonely"], info)
    bad = text.replace("+ VGND|vss|junk", "+ VGND|vss|vdd")
    out2, info2 = V.canonicalise_pins(bad, "top", ports)
    _check("a net joining two ports is never repaired (short stays visible)", len(info2["joined_pins"]) == 1 and "VGND|vss|vdd" in V.top_pins(out2, "top"), info2)
    _check("a port that only exists on a joined net is reported missing as a pin", "vss" in info2["ports_missing"], info2)
    dup = text.replace("+ lonely", "+ vss|again")
    _, info3 = V.canonicalise_pins(dup, "top", ports)
    _check("two nets claiming one port are reported as duplicated", info3["ports_duplicated"] == ["vss"], info3)


LAYOUT = """\
.SUBCKT trng_whole vss vdd x y
Xc1 x y vdd vss cellA
Xc2 y vdd vss cellB
M$1 y x vss vss nfet L=0.15U W=0.42U
.ENDS trng_whole
.SUBCKT cellA A B VPWR VGND
.ENDS cellA
.SUBCKT cellB A VPWR VGND
.ENDS cellB
"""


def check_endpoints() -> None:
    ep = V.endpoints(LAYOUT, "trng_whole", set())
    _check("endpoint audit maps stub pins to nets", ep["x"]["cellA.A"] == 1 and ep["y"]["cellA.B"] == 1, dict(ep["x"]))
    _check("MOSFET terminals are counted by role", ep["y"]["nfet.ds"] == 1 and ep["x"]["nfet.g"] == 1 and ep["vss"]["nfet.b"] == 1, dict(ep["vss"]))
    moved = LAYOUT.replace("Xc1 x y vdd vss cellA", "Xc1 y x vdd vss cellA")
    ep2 = V.endpoints(moved, "trng_whole", set())
    _check("a single moved cell pin changes both nets' endpoint multisets", ep2["x"] != ep["x"] and ep2["y"] != ep["y"])
    wrong = LAYOUT.replace("Xc2 y vdd vss cellB", "Xc2 y vdd cellB")
    try:
        V.endpoints(wrong, "trng_whole", set())
        _check("a wrong pin count is an error, not a silent skip", False)
    except V.VerifyError:
        _check("a wrong pin count is an error, not a silent skip", True)
    _check("stub_pin_sets lists only body-less subckts", V.stub_pin_sets(LAYOUT) == {"cellA": ["A", "B", "VPWR", "VGND"], "cellB": ["A", "VPWR", "VGND"]}, V.stub_pin_sets(LAYOUT))


def check_build_reference() -> None:
    try:
        from klayout_tools import verilog_netlist as vn  # noqa: PLC0415
    except ImportError:
        print("skip   build_reference (klayout_tools not importable)")
        return
    verilog = """\
module dig (a, y);
 input a; output y;
 wire n1;
 sky130_fd_sc_hd__inv_1 u1 (.A(a), .Y(n1));
 sky130_fd_sc_hd__inv_1 u2 (.A(n1), .Y(y));
endmodule
"""
    deff = """COMPONENTS 4 ;
    - u1 sky130_fd_sc_hd__inv_1 + PLACED ( 0 0 ) N ;
    - u2 sky130_fd_sc_hd__inv_1 + PLACED ( 0 0 ) N ;
    - TAP_1 sky130_fd_sc_hd__tapvpwrvgnd_1 + PLACED ( 0 0 ) N ;
    - FILL_1 sky130_fd_sc_hd__fill_1 + PLACED ( 0 0 ) N ;
END COMPONENTS
"""
    orders = {
        "sky130_fd_sc_hd__inv_1": ["A", "VGND", "VNB", "VPB", "VPWR", "Y"],
        "sky130_fd_sc_hd__tapvpwrvgnd_1": ["VGND", "VPWR"],
        "sky130_fd_sc_hd__fill_1": ["VGND", "VNB", "VPB", "VPWR"],
    }
    analog = ".subckt sampler_core en vdd vss\nXMn en vdd vss vss sky130_fd_pr__nfet_01v8 L=0.15u W=0.42u\n.ends\n"
    text, facts = V.build_reference(
        analog_ref_text=analog, analog_top="sampler_core", whole_ports=["vdd", "vss", "en", "a", "y"],
        verilog_text=verilog, def_text=deff, lib_pin_orders=orders, digital_module="dig",
        digital_to_whole={"a": "a", "y": "y"}, header=["* t"], verilog_parser=vn.parse_gate_level_verilog)
    _check("reference carries the transistor and every placed cell", facts["analog_devices"] == 1 and facts["digital_cell_instances"] == 4, facts)
    _check("fill/tap come from the DEF as power-only instances", facts["power_only_instances"] == 2, facts)
    _check("VNB is not a stub pin", ".subckt sky130_fd_sc_hd__inv_1 A VGND VPB VPWR Y" in text, text)
    _check("VPB and VPWR are tied to vdd, VGND to vss", "Xu1 a vss vdd vdd d_n1 sky130_fd_sc_hd__inv_1" in text, text)
    ep = V.endpoints(text, "trng_whole", set())
    _check("every placed cell's power pin is on vdd/vss", ep["vdd"]["sky130_fd_sc_hd__inv_1.VPB"] == 2 and ep["vss"]["sky130_fd_sc_hd__tapvpwrvgnd_1.VGND"] == 1, dict(ep["vdd"]))
    for label, bad_def in (
        ("a DEF component with signal pins missing from the Verilog is an error",
         deff.replace("COMPONENTS 4", "COMPONENTS 5").replace("END COMPONENTS", "    - u9 sky130_fd_sc_hd__inv_1 + PLACED ( 0 0 ) N ;\nEND COMPONENTS")),
    ):
        try:
            V.build_reference(
                analog_ref_text=analog, analog_top="sampler_core", whole_ports=["vdd", "vss", "en", "a", "y"],
                verilog_text=verilog, def_text=bad_def, lib_pin_orders=orders, digital_module="dig",
                digital_to_whole={"a": "a", "y": "y"}, header=[], verilog_parser=vn.parse_gate_level_verilog)
            _check(label, False)
        except V.VerifyError:
            _check(label, True)


# --------------------------------------------------------------------------
# committed evidence
# --------------------------------------------------------------------------


def check_committed_evidence() -> None:
    if not (VERIFY / "verify.json").is_file():
        print("skip   committed evidence (layout/trng_whole/verify/verify.json absent)")
        return
    rep = json.loads((VERIFY / "verify.json").read_text())
    _check("verify.json states it is not sign-off", "NOT foundry sign-off" in rep["not_signoff"] and rep["provisional"] is True)
    for path, digest in rep["inputs_sha256"].items():
        _check(f"input hash current: {path}", sha(_REPO_ROOT / path) == digest, path)
    _check("reference hash current", sha(VERIFY / "lvs.ref.spice") == rep["reference"]["sha256"])
    lvs = json.loads((VERIFY / "lvs.json").read_text())
    drc = json.loads((VERIFY / "drc.json").read_text())
    _check("DRC is clean with zero violations", drc["status"] == "clean" and drc["violation_count"] == 0 and rep["drc"]["violation_count"] == 0)
    _check("the licon1.ongrid.1 rule that failed in #172 is enforced", "licon1.ongrid.1" in drc["coverage"]["rules_checked"])
    _check("DRC ran on the committed composed GDS",
           drc["provenance"]["input"]["content_hash"].split(":")[-1] == rep["inputs_sha256"]["layout/trng_whole/trng_whole.gds"] or
           drc["provenance"]["input"]["content_hash"] == rep["drc"]["input_content_hash"])
    _check("LVS is a match with zero error mismatches", lvs["status"] == "match" and lvs["error_count"] == 0 and rep["lvs"]["error_count"] == 0)
    _check("the LVS report pins the committed canonical netlist and reference",
           lvs["environment"]["layout_sha256"] == rep["lvs"]["layout_netlist_sha256"] and lvs["environment"]["reference_sha256"] == rep["lvs"]["reference_sha256"])
    _check("every LVS warning category has a recorded explanation", all(w["explanation"] != "UNEXPLAINED" for w in rep["lvs"]["warnings_reviewed"]), rep["lvs"]["warnings_reviewed"])
    _check("anchoring covered all 123 whole-block ports", lvs["counts"]["pins"]["layout"] == 123 and lvs["counts"]["pins"]["reference"] == 123, lvs["counts"]["pins"])
    _check("power_connectivity / body_verification are disclosed as unchecked", rep["lvs"]["power_connectivity"] == "unchecked" and rep["lvs"]["body_verification"] == "unchecked")
    req = json.loads((VERIFY / "lvs.request.json").read_text())
    _check("the LVS request anchors top-level pins by name", req["options"].get("anchor_top_level_pins") is True)
    cov = json.loads((VERIFY / "coverage.json").read_text())
    _check("coverage matrix: all 123 ports clean on all four checks", cov["ports"] == 123 and cov["ports_clean"] == 123, (cov["ports"], cov["ports_clean"]))
    classes = Counter(r["class"] for r in cov["rows"])
    _check("coverage matrix names the four ring supplies and both supplies", all(any(r["port"] == p for r in cov["rows"]) for p in ("vddr1", "vddr2", "vddr3", "vddr4", "vdd", "vss")))
    _check("coverage matrix has every interface class", {"ring_supply", "logic_supply", "logic_ground", "shared_input", "analog_external", "digital_external"} <= set(classes), dict(classes))
    ids = {l["id"] for l in cov["limitations"]}
    _check("limitations name substrate/VNB, bodies, hierarchy, filler/tap and power checks", {"L1", "L2", "L3", "L5", "L6", "L7"} <= ids, ids)
    _check("no stub pin-list difference between layout and reference", cov["stub_pin_differences"] == {}, cov["stub_pin_differences"])
    ext = json.loads(gzip.decompress((VERIFY / "extract.json.gz").read_bytes()))
    _check("extract report: 264 devices, abstraction applied", ext["device_count"] == 264 and len(ext["abstracted_cells"]) == rep["extract"]["abstracted_cell_types"] > 0)
    # no host paths in any committed text
    for name in ("verify.json", "lvs.json", "drc.json", "extract.request.json", "lvs.request.json", "coverage.json"):
        text = (VERIFY / name).read_text()
        _check(f"no home-directory path in {name}", "/home/" not in text and "/Users/" not in text)


def check_committed_controls() -> None:
    path = VERIFY / "controls" / "controls.json"
    if not path.is_file():
        print("skip   committed controls (controls.json absent)")
        return
    c = json.loads(path.read_text())
    rep = json.loads((VERIFY / "verify.json").read_text())
    _check("controls ran against the committed golden GDS", c["golden_gds_sha256"] == rep["inputs_sha256"]["layout/trng_whole/trng_whole.gds"])
    _check("golden inputs were unchanged by the controls", c["golden_gds_unchanged"] is True and c["reference_sha256"] == rep["reference"]["sha256"])
    kinds = {r["kind"] for r in c["controls"]}
    _check("swapped signal, disconnected interface and supply short are all covered", {"swap_labels", "swap_reference", "disconnect", "supply_short"} <= kinds, kinds)
    for r in c["controls"]:
        _check(f"{r['id']}: reached the LVS comparison", r["reached_lvs_comparison"] is True)
        _check(f"{r['id']}: LVS mismatch with error-severity evidence naming the nets", r["lvs"]["status"] == "mismatch" and r["lvs"]["error_count"] > 0 and r["lvs"]["evidence"]["errors_naming_them"] > 0, r["lvs"]["evidence"])
        _check(f"{r['id']}: detected", r["detected"] is True)
        _check(f"{r['id']}: the defect was proven present before verification", bool(r["defect"].get("pre_verification_proof")))
        _check(f"{r['id']}: golden inputs unchanged", r["golden_unchanged"] is True)
    _check("every control detected", c["all_detected"] is True)
    _check("controls' baseline re-run pins the same canonical netlist and reference as verify.json",
           c["baseline_rerun_after_controls"]["stable_view"]["layout_sha256"] == rep["lvs"]["layout_netlist_sha256"]
           and c["baseline_rerun_after_controls"]["stable_view"]["reference_sha256"] == rep["lvs"]["reference_sha256"])
    rr = c["baseline_rerun_after_controls"]
    _check("the untouched baseline still matches after the controls", rr["status"] == "match" and rr["error_count"] == 0 and rr["stable_fields_equal_to_first_baseline"] is True, rr)


def main() -> int:
    check_flatten()
    check_canonicalise()
    check_endpoints()
    check_build_reference()
    check_committed_evidence()
    check_committed_controls()
    return _checker.summary("layout/test_verify_whole.py")


if __name__ == "__main__":
    raise SystemExit(main())
