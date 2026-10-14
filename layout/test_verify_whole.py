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
  the LVS comparison and failed naming its nets;
- the DRC coverage audit (issue #281) must classify every rule klt did not run
  and every unruled stream layer, pinned to drc.json's deck hash; its verdict
  logic is exercised here on stubbed counts (controls 1-5), and the committed
  markdown must be exactly what the committed JSON renders to;
- the physical estimates (issue #283) must compute density windows and naive
  antenna ratios the same way their committed artifact says they do: exact
  window grids (clipped denominators, refused invalid grids), cumulative
  ratios over per-level areas, label-subset net attribution that counts
  ambiguous/zero-gate/unmatched nets instead of guessing, and a drift gate
  that catches value, parameter and staleness changes but ignores tool
  provenance. The klayout-dependent geometry controls skip themselves where
  klayout is absent (they run for real under pdk-nightly).
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "design"))
sys.path.insert(0, str(_HERE / "bin"))
from _test_check import Checker  # noqa: E402
import drc_coverage_audit as A  # noqa: E402
import physical_estimates as PE  # noqa: E402
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


# --------------------------------------------------------------------------
# DRC coverage audit (issue #281)
# --------------------------------------------------------------------------

_STUB_TABLE_NAMES = {
    (64, 18): "dnwell.drawing", (89, 44): "capm.drawing", (97, 44): "capm2.drawing",
    (70, 44): "via3.drawing", (70, 20): "met3.drawing", (68, 20): "met1.drawing",
}
_STUB_RULES = [
    {"id": "dnwell.angle.1", "check": "angle", "layers": ["dnwell.drawing"]},
    {"id": "capm.enclosing.via3.1", "check": "enclosing", "layers": ["capm.drawing", "via3.drawing"]},
    {"id": "met3.enclosing.capm.1", "check": "enclosing", "layers": ["met3.drawing", "capm.drawing"]},
]


def check_coverage_audit_logic() -> None:
    """Controls 1-5 with counts derived from the fixture spec (no klt, no GDS).
    The deck rules and layer table are a small stub carrying the committed pin:
    this exercises the verdict logic and the drift / hash gates, not the deck."""
    drc = json.loads((VERIFY / "drc.json").read_text())
    pin = A.pinned_deck_hash(drc)
    rules = {"content_hash": pin, "rules": _STUB_RULES}
    summary = A.run_controls(real_drc=drc, real_rules=rules, table=(pin, dict(_STUB_TABLE_NAMES)),
                             count_fn=lambda spec, extra: A.stub_layers_doc(spec, extra))
    for r in summary["controls"]:
        _check(f"audit control {r['id']} (stubbed counts)", r["passed"], r.get("observed") or r.get("cases"))
    ids = {r["id"].split("-")[0] for r in summary["controls"]}
    _check("audit controls cover 1 absent, 2 residual, 3 unresolved, 4 two-layer, 5 drift",
           {"1", "2", "3a", "3b", "3c", "4a", "4b", "5"} <= ids, ids)
    # a check kind the audit does not know never becomes vacuous on a shape count alone
    row = A.classify_rule({"rule": "x", "reason": None, "lists": []}, {"x": {"check": "isolated", "layers": ["dnwell.drawing"]}},
                          {"dnwell.drawing": ["64/18"]}, {"64/18"}, {})
    _check("unknown check kind with an empty layer stays unresolved", row["verdict"] == "unresolved", row)
    row = A.classify_rule({"rule": "x", "reason": None, "lists": []}, {"x": {"check": "angle", "layers": ["dnwell.drawing"]}},
                          {"dnwell.drawing": ["64/18"]}, set(), {})
    _check("a layer the pinned DRC run did not read stays unresolved", row["verdict"] == "unresolved", row)


def check_committed_coverage_audit() -> None:
    path = VERIFY / "drc_coverage_audit.json"
    if not path.is_file():
        print("skip   committed coverage audit (drc_coverage_audit.json absent)")
        return
    doc = json.loads(path.read_text())
    drc = json.loads((VERIFY / "drc.json").read_text())
    rep = json.loads((VERIFY / "verify.json").read_text())
    cov = drc["coverage"]
    _check("audit is labelled evidence, not sign-off", "not sign-off" in doc["not_signoff"] and "antenna" in doc["not_signoff"])
    _check("audit is pinned to drc.json's deck hash", doc["inputs"]["deck"]["content_hash"] == drc["provenance"]["deck"]["content_hash"])
    _check("audit describes the committed composed GDS",
           doc["inputs"]["gds_sha256"] == rep["inputs_sha256"]["layout/trng_whole/trng_whole.gds"] and doc["inputs"]["drc_report_input_matches_gds"])
    want = {e["id"] for e in cov["inapplicable"]} | set(cov["rules_skipped"]) | {e["id"] if isinstance(e, dict) else e for e in cov["skipped"]}
    got = [r["rule"] for r in doc["rules"]]
    _check(f"every not-run rule is classified exactly once ({len(want)})", sorted(got) == sorted(want), sorted(want ^ set(got)))
    _check("every rule verdict is one of the three", all(r["verdict"] in ("vacuous-confirmed", "residual", "unresolved") for r in doc["rules"]))
    for r in doc["rules"]:
        if r["verdict"] != "vacuous-confirmed":
            continue
        empty = [lay for lay in r["deck_layers"] if lay["gds"] and lay["geometry"] == 0]
        _check(f"{r['rule']}: vacuous verdict backed by a mapped zero-geometry layer and a known kind",
               bool(empty) and r["check"] in A.SINGLE_LAYER_KINDS + A.TWO_LAYER_KINDS
               and len(r["deck_layers"]) == (1 if r["check"] in A.SINGLE_LAYER_KINDS else 2), r)
    _check("every unruled stream layer is listed in order",
           [u["gds"] for u in doc["unruled_layers"]] == cov["layers_in_stream_without_rules"])
    _check("no unruled layer is labelled absent", all(u["verdict"] in ("present-unruled", "text-or-marker-only") for u in doc["unruled_layers"]),
           [u for u in doc["unruled_layers"] if u["verdict"] not in ("present-unruled", "text-or-marker-only")])
    for u in doc["unruled_layers"]:
        _check(f"unruled {u['gds']}: verdict follows its counts",
               u["geometry"] == u["flattened_shapes"] - u["text_count"]
               and (u["verdict"] == "text-or-marker-only") == (u["geometry"] == 0 or u["annotation"]), u)
    _check("stream fully accounted (checked + unruled)", doc["summary"]["stream_layers_unaccounted"] == [], doc["summary"])
    md = (VERIFY / "drc_coverage_audit.md").read_text()
    _check("committed audit markdown is exactly what the JSON renders to", md == A.markdown(doc))
    _check("no home-directory path in the audit", "/home/" not in path.read_text() + md and "/Users/" not in path.read_text() + md)
    covj = json.loads((VERIFY / "coverage.json").read_text())
    l9 = next(item for item in covj["limitations"] if item["id"] == "L9")
    _check("coverage L9 cites both audit tables", "drc_coverage_audit.md" in l9["detail"] and "Table 1" in l9["detail"] and "Table 2" in l9["detail"], l9)
    _check("coverage L9 keeps the foundry/antenna/density/seal-ring/latch-up limitations",
           all(w in l9["detail"] for w in ("not foundry DRC clean", "antenna", "density", "seal-ring", "latch-up")), l9)
    ctl = VERIFY / "controls" / "drc_coverage_audit_controls.json"
    if ctl.is_file():
        c = json.loads(ctl.read_text())
        _check("committed audit controls (real klt counts) all passed", c["all_passed"] is True and len(c["controls"]) >= 9)
        _check("audit controls ran on the pinned deck", c["deck_content_hash"] == drc["provenance"]["deck"]["content_hash"])
    else:
        _check("committed audit controls present", False, str(ctl))


# --------------------------------------------------------------------------
# physical estimates (issue #283): pure calculator logic, committed contract
# --------------------------------------------------------------------------


def check_physical_estimate_logic() -> None:
    window_grid, window_density = PE.window_grid, PE.window_density
    cumulative_areas, antenna_ratios, split_labels = PE.cumulative_areas, PE.antenna_ratios, PE.split_labels
    match_gate_components, gate_areas_from_extract = PE.match_gate_components, PE.gate_areas_from_extract
    build_document, drift, LEVELS = PE.build_document, PE.drift, PE.LEVELS
    _check("window grid tiles row-major with clipped edge windows",
           [(w["ix"], w["iy"], round(w["area"], 9)) for w in window_grid((0, 0, 250, 150), 100, 100)[0]]
           == [(0, 0, 10000.0), (1, 0, 10000.0), (2, 0, 5000.0),
               (0, 1, 5000.0), (1, 1, 5000.0), (2, 1, 2500.0)],
           window_grid((0, 0, 250, 150), 100, 100)[0])
    n, skipped = window_grid((0, 0, 250, 150), 100, 40)
    _check("overlapping strides tile ceil(dim/stride) per axis", (len(n), skipped) == (7 * 4, 0), (len(n), skipped))
    n, skipped = window_grid((0, 0, 0, 0), 100, 100)
    _check("a zero-area boundary yields no windows and nothing skipped", (n, skipped) == ([], 0), (n, skipped))
    for window, stride in ((0, 1), (1, 0), (1, 2), (-3, 1)):
        try:
            window_grid((0, 0, 10, 10), window, stride)
            _check(f"invalid grid (window={window}, stride={stride}) is refused", False, "no error")
        except PE.EstimateError:
            _check(f"invalid grid (window={window}, stride={stride}) is refused", True)
    _check("a zero-area window is never divided by", window_density(5.0, 0.0) is None and window_density(5.0, -1.0) is None)
    _check("window density is geometry / window area", window_density(5.0, 100.0) == 0.05)
    cum = cumulative_areas({"li1": 1.0, "met2": 2.0})
    _check("cumulative areas run bottom-up and carry forward",
           cum == {"li1": 1.0, "met1": 1.0, "met2": 3.0, "met3": 3.0, "met4": 3.0, "met5": 3.0}, cum)
    r = antenna_ratios({"li1": 1.0, "met1": 2.0}, 1.0)
    _check("ratios are cumulative area / gate area per level", r["li1"] == 1.0 and r["met1"] == 3.0 and r["met5"] == 3.0, r)
    _check("a zero-gate net produces no ratio (never infinity)", antenna_ratios({"li1": 1.0}, 0.0) == {})
    _check("anonymous $N escapes and empty tokens are dropped",
           split_labels("\\$12,a,,$x,b", ",") == {"a", "b"} and split_labels("n1|n2", "|") == {"n1", "n2"})
    gate_sets = {"n1": {"n1", "x"}, "n2": {"n2", "x"}}
    m, amb, unm = match_gate_components([{"x"}, {"n1"}, {"n3"}, set()], gate_sets)
    _check("label-subset matching: shared-only labels ambiguous, unique labels match, foreign labels unmatched",
           (len(m), amb, unm) == (1, 1, 1), (m, amb, unm))
    m, amb, unm = match_gate_components([{"n1", "x"}], {"n1": {"n1", "x"}})
    _check("a full label set still matches its own net", (len(m), amb, unm) == (1, 0, 0), (m, amb, unm))
    gate = gate_areas_from_extract({
        "devices": [
            {"nets": {"g": "n1"}, "params": {"w_um": 2.0, "l_um": 0.1}},
            {"nets": {"g": "n1"}, "params": {"w_um": 1.0, "l_um": 0.1}},
            {"nets": {"g": "n2"}, "params": {"w_um": 0.0, "l_um": 0.1}},
            {"nets": {"g": "n3"}, "params": {}},
        ],
        "abstracted_cells": [{"instance_count": 5}, {"instance_count": 7}],
    })
    _check("gate W*L sums per net and counts devices",
           abs(gate["gate_area_um2"]["n1"] - 0.3) < 1e-12 and gate["gate_area_um2"]["n2"] == 0.0
           and gate["analog_devices"] == 3 and gate["devices_missing_params"] == 1, gate)
    _check("a gate net whose only device lacked params is registered with zero known area",
           "n3" in gate["gate_area_um2"] and gate["gate_area_um2"]["n3"] == 0.0
           and gate["devices_missing_params"] == 1 and gate["devices_per_gate_net"]["n3"] == 1, gate)
    _check("abstracted instances sum with their type count",
           (gate["abstracted_instances"], gate["abstracted_cell_types"]) == (12, 2), gate)

    density = {
        "top": "t", "windows_total": 2, "windows_skipped": 0,
        "drawn_area_um2_by_level": {"li1": 4.0, "met1": 8.0, "met2": 0.0, "met3": 0.0, "met4": 0.0, "met5": 0.0},
        "layers": [
            {"name": "li1", "gds": "67/20", "empty_layer": False, "drawn_area_um2": 4.0,
             "whole_block_density": 0.04, "windows_counted": 2, "window_densities": [0.1, 0.0],
             "density_min": 0.0, "density_max": 0.1, "density_mean": 0.05},
            {"name": "met1", "gds": "68/20", "empty_layer": False, "drawn_area_um2": 8.0,
             "whole_block_density": 0.08, "windows_counted": 2, "window_densities": [0.1, 0.1],
             "density_min": 0.1, "density_max": 0.1, "density_mean": 0.1},
        ],
    }
    components = {
        "components": [
            {"labels": ["n1", "x"], "area_um2": {lvl: (1.0 if lvl == "li1" else 2.0 if lvl == "met1" else 0.0)
                                                 for lvl in LEVELS}, "gate_net": "n1"},
            {"labels": ["n2"], "area_um2": {lvl: (1.0 if lvl == "li1" else 0.0) for lvl in LEVELS},
             "gate_net": "n2"},
            {"labels": ["solo"], "area_um2": {lvl: 0.5 for lvl in LEVELS}, "gate_net": None},
        ],
        "component_tokens": [{"n1", "x"}, {"n2"}, {"solo"}],
        "flat_nets_total": 4, "labeled": 3, "unlabeled": 1, "matched": 2, "ambiguous": 0, "unmatched": 1,
    }
    doc = build_document(
        gds_rel="g.gds", gds_sha256="sha256:g", geometry_sha256="sha256:gg", geometry_counts={"polygons": 1},
        extract_rel="e.json.gz", extract_sha256="sha256:e", extract_matches_gds=True,
        layer_map={"li1": (67, 20), "met1": (68, 20), "met2": (69, 20), "met3": (70, 20), "met4": (71, 20),
                   "met5": (72, 20), "poly": (66, 20)},
        layer_table_hash="sha256:t", klayout_version="test", bbox=(0.0, 0.0, 100.0, 100.0),
        gate=gate, components=components, density=density)
    nets = {e["net"]: e for e in doc["antenna"]["nets"]}
    _check("a gate net with components is rated with aggregated per-level areas",
           nets["n1"]["area_um2"]["li1"] == 1.0 and nets["n1"]["cumulative_ratio"]["met1"] == 3.0 / 0.3, nets["n1"])
    _check("a zero-gate-area net with conductor geometry is listed, unrated, and never infinite",
           nets["n2"]["cumulative_ratio"] == {} and nets["n2"]["gate_area_um2"] == 0.0
           and nets["n2"]["components"] == 1, nets["n2"])
    _check("worst-per-level tables exclude unratable nets",
           all(w["nets_rated"] == 1 for w in doc["antenna"]["ratios_by_level"]), doc["antenna"]["ratios_by_level"])
    _check("a gate net without conductor geometry is listed and counted",
           doc["antenna"]["gate_nets_without_conductor_geometry"] == ["n3"]
           and doc["coverage"]["gate_area"]["gate_nets_without_conductor_geometry"] == 1)
    gac = doc["coverage"]["gate_area"]
    _check("gate-net accounting covers every distinct gate net",
           gac["gate_nets_rated"] + gac["gate_nets_listed_zero_known_area"]
           + gac["gate_nets_without_conductor_geometry"] == gac["distinct_gate_nets"], gac)
    _check("labeled components matching no gate net are counted, not guessed",
           doc["coverage"]["conductor_components"]["labeled_matching_no_gate_net"] == 1)
    frac = doc["coverage"]["conductor_components"]["attributed_area_fraction_by_level"]
    _check("attributed-area fractions compare matched area with drawn area per level",
           frac["li1"] == 0.5 and frac["met1"] == 0.25 and frac["met5"] is None, frac)
    _check("all committed ratios are finite", all(math.isfinite(v) for e in doc["antenna"]["nets"]
                                                  for v in e["cumulative_ratio"].values()))
    _check("markdown renders from the same document", PE.markdown(doc) == PE.markdown(json.loads(PE.dumps(doc))))
    _check("drift: unchanged reproduces", drift(doc, json.loads(PE.dumps(doc))) == [])
    for label, mutate in (
        ("a density value", lambda d: d["density"]["layers"][0].__setitem__("density_max", 0.2)),
        ("a window-densities entry", lambda d: d["density"]["layers"][1].__setitem__("window_densities", [0.2, 0.1])),
        ("the window parameter", lambda d: d["definitions"]["density"].__setitem__("window_um", 50.0)),
        ("a net's gate area", lambda d: d["antenna"]["nets"][0].__setitem__("gate_area_um2", 0.4)),
        ("an input hash", lambda d: d["inputs"].__setitem__("gds_sha256", "sha256:other")),
        ("a coverage count", lambda d: d["coverage"]["gate_area"].__setitem__("analog_devices", 9)),
    ):
        edited = json.loads(PE.dumps(doc))
        mutate(edited)
        _check(f"drift: {label} changed is caught", bool(drift(doc, edited)), drift(doc, edited))
    edited = json.loads(PE.dumps(doc))
    edited["provenance"]["klayout_version"] = "other"
    _check("drift: a provenance-only change does not drift (by design)", drift(doc, edited) == [], drift(doc, edited))


def check_committed_physical_estimates() -> None:
    path = VERIFY / "physical_estimates.json"
    if not path.is_file():
        print("skip   committed physical estimates (physical_estimates.json absent)")
        return
    doc = json.loads(path.read_text())
    md = (VERIFY / "physical_estimates.md").read_text()
    _check("estimates are labelled estimate, not foundry sign-off",
           "NOT foundry sign-off" in doc["not_signoff"] and "not a density-rule verdict" in md)
    _check("definitions are in the artifact header",
           {"quantity", "window_um", "stride_um", "denominator"} <= set(doc["definitions"]["density"])
           and {"quantity", "conductor_source", "gate_source", "digital_exclusion", "zero_gate_nets",
                "not_modelled", "verdict"} <= set(doc["definitions"]["antenna"])
           and "ARBITRARY" in doc["definitions"]["density"]["window_provenance"])
    _check("the window grid is validated by definition",
           "window_um <= 0" in doc["definitions"]["density"]["grid_validation"])
    gds = _REPO_ROOT / "layout" / "trng_whole" / "trng_whole.gds"
    ext = VERIFY / "extract.json.gz"
    _check("committed hashes still describe the committed inputs",
           doc["inputs"]["gds_sha256"] == sha(gds) and doc["inputs"]["gate_source_sha256"] == sha(ext))
    _check("the gate source is pinned to the committed GDS", doc["inputs"]["gate_source_matches_gds"] is True)
    _check("no home-directory path in the estimates", "/home/" not in path.read_text() + md and "/Users/" not in path.read_text() + md)
    ga = doc["coverage"]["gate_area"]
    _check("gate-side coverage accounts for every gate net",
           ga["gate_nets_rated"] + ga["gate_nets_listed_zero_known_area"]
           + ga["gate_nets_without_conductor_geometry"] == ga["distinct_gate_nets"]
           and len(doc["antenna"]["nets"]) == ga["gate_nets_rated"] + ga["gate_nets_listed_zero_known_area"])
    de = ga["digital_exclusion"]
    _check("digital exclusion uses the defined instance denominator",
           de["device_bearing_instances"] == ga["analog_devices"] + de["abstracted_instances"]
           and de["abstracted_instances"] > 0 and 0 < de["known_gate_area_fraction_of_instances"] < 1, de)
    nets = doc["antenna"]["nets"]
    _check("every committed ratio is finite and positive",
           all(math.isfinite(v) and v > 0 for e in nets for v in e["cumulative_ratio"].values()))
    for w in doc["antenna"]["ratios_by_level"]:
        rated = [e["cumulative_ratio"][w["level"]] for e in nets if w["level"] in e["cumulative_ratio"]]
        _check(f"worst {w['level']} ratio is the max over the rated nets",
               w["nets_rated"] == len(rated) and (w["worst_ratio"] == max(rated) if rated else w["worst_ratio"] is None), w)
    d = doc["density"]
    _check("density rows cover exactly the counted windows",
           all(len(lay["window_densities"]) == lay["windows_counted"]
               and lay["density_max"] == max(lay["window_densities"] or [0.0])
               and lay["density_min"] == min(lay["window_densities"] or [0.0]) for lay in d["layers"]))
    _check("whole-block densities are the drawn area over the boundary",
           all(abs(lay["whole_block_density"] - lay["drawn_area_um2"] / d["boundary"]["area_um2"]) < 1e-6
               for lay in d["layers"] if not lay["empty_layer"]))
    _check("committed markdown is exactly what the JSON renders to", md == PE.markdown(doc))
    _check("markdown has no unsubstituted template fields", not re.search(r"\{[a-zA-Z_]+\[", md), md)
    ctl = VERIFY / "controls" / "physical_estimates_controls.json"
    if ctl.is_file():
        c = json.loads(ctl.read_text())
        _check("committed estimate controls (real klayout) all passed", c["all_passed"] is True and len(c["controls"]) >= 9)
    else:
        _check("committed estimate controls present", False, str(ctl))


def check_physical_estimate_geometry() -> None:
    """klayout-gated: the real-geometry calculator controls and the
    verify-whole.py estimates_check glue on a redirected scratch copy."""
    try:
        import klayout.db  # noqa: F401, PLC0415
    except ImportError:
        print("skip   physical-estimate geometry controls (klayout not importable; pdk-nightly runs them)")
        return
    summary = PE.run_controls()
    for r in summary["controls"]:
        _check(f"estimate control {r['id']} (real klayout)", r["passed"], r.get("observed"))
    _check("real-geometry estimate controls all passed", summary["all_passed"])

    try:
        vw = _load_verify_whole()
    except Exception as exc:  # noqa: BLE001 -- optional deps of the entry point
        print(f"skip   estimates_check glue (cannot import verify-whole.py: {exc})")
        return
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    def snapshot(d: Path) -> dict:
        return {str(f.relative_to(d)): sha(f) for f in sorted(d.rglob("*")) if f.is_file()} if d.is_dir() else {}

    repo_before = snapshot(VERIFY)
    with tempfile.TemporaryDirectory(prefix="test-estimates-check-") as t:
        # a fake repo root mirroring layout/trng_whole: the whole block is
        # symlinked in (the GDS is read-only input), while the two committed
        # estimate artifacts are real copies that the negative controls edit.
        # rel() then yields the same repo-relative strings as the real run, so
        # an unchanged check can reproduce byte-for-byte.
        root = Path(t)
        whole = root / "layout" / "trng_whole"
        whole.mkdir(parents=True)
        (whole / "trng_whole.gds").symlink_to(_REPO_ROOT / "layout" / "trng_whole" / "trng_whole.gds")
        live = root / "live"
        live.mkdir()
        (live / "extract.json.gz").symlink_to(_REPO_ROOT / "layout" / "trng_whole" / "verify" / "extract.json.gz")
        (live / "physical_estimates.json").write_text((VERIFY / PE.JSON_NAME).read_text())
        (live / "physical_estimates.md").write_text((VERIFY / PE.MD_NAME).read_text())
        (whole / "verify").symlink_to(live)
        committed = json.loads((live / PE.JSON_NAME).read_text())
        vw.REPO_ROOT = root
        vw.SPEC_DIR = whole
        vw.VERIFY_DIR = whole / "verify"
        # the real rel() resolves symlinks (Path.resolve), which would leak the
        # temp absolute path into the inputs; scope a non-resolving rel to this
        # fake root instead -- same repo-relative strings as the real run
        vw.rel = lambda p: str(Path(p).relative_to(root))
        _check("estimates_check: unchanged committed estimates reproduce", vw.estimates_check() == [],
               vw.estimates_check())
        (live / PE.JSON_NAME).unlink()
        _check("estimates_check: a missing artifact is an explicit failure, not a pass",
               len(vw.estimates_check()) == 1 and "missing" in vw.estimates_check()[0], vw.estimates_check())
        doc = json.loads(json.dumps(committed))
        doc["density"]["layers"][0]["density_max"] += 0.01
        (live / PE.JSON_NAME).write_text(PE.dumps(doc))
        out = vw.estimates_check()
        _check("estimates_check: a perturbed density value drifts", bool(out) and "density" in out[0], out)
        (live / PE.JSON_NAME).write_text(PE.dumps(committed))
        doc = json.loads(json.dumps(committed))
        doc["definitions"]["density"]["window_um"] = 42.0
        (live / PE.JSON_NAME).write_text(PE.dumps(doc))
        _check("estimates_check: a changed window parameter drifts", bool(vw.estimates_check()))
        (live / PE.JSON_NAME).write_text(PE.dumps(committed))
        md = live / PE.MD_NAME
        md.write_text(md.read_text().replace("## Density", "## Density EDITED"))
        _check("estimates_check: an edited markdown drifts",
               any(PE.MD_NAME in line for line in vw.estimates_check()), vw.estimates_check())
        _check("estimates_check: the check republishes nothing",
               snapshot(live) == {PE.JSON_NAME: sha(live / PE.JSON_NAME), PE.MD_NAME: sha(md),
                                  "extract.json.gz": sha(live / "extract.json.gz")}
               and md.read_text() != PE.markdown(committed))
    _check("estimates_check tests left the committed estimates untouched", snapshot(VERIFY) == repo_before)


# --------------------------------------------------------------------------
# dispatcher: publication guards for `controls` / `all`
# --------------------------------------------------------------------------


def _load_verify_whole():
    spec = importlib.util.spec_from_file_location("verify_whole_entry", _HERE / "bin" / "verify-whole.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_control(cid: str) -> dict:
    return {
        "id": cid, "kind": "swap_labels", "reached_lvs_comparison": True, "detected": True,
        "lvs": {"status": "mismatch", "error_count": 1, "error_categories": {"net": 1},
                "evidence": {"errors_naming_them": 1, "named_nets": [cid]}},
    }


def check_dispatcher_publication() -> None:
    """``controls``/``all`` must honour --no-publish and must never let a
    partial ``--only`` campaign replace the canonical full-campaign evidence.
    The expensive stages are stubbed and every evidence directory is redirected
    to a temporary directory, so no repository evidence is read or written."""
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    try:
        vw = _load_verify_whole()
    except Exception as exc:  # noqa: BLE001 -- optional deps of the entry point
        print(f"skip   dispatcher publication guards (cannot import verify-whole.py: {exc})")
        return

    def snapshot(d: Path) -> dict:
        return {str(f.relative_to(d)): sha(f) for f in sorted(d.rglob("*")) if f.is_file()} if d.is_dir() else {}

    repo_controls_before = snapshot(VERIFY / "controls")
    repo_verify_before = snapshot(VERIFY)

    def run(argv: list[str], tmp: Path) -> tuple[int, list[str], list[str]]:
        calls: dict[str, list[str]] = {"baseline": [], "controls": []}
        vw.VERIFY_DIR = tmp / "verify"
        vw.CONTROLS_DIR = tmp / "verify" / "controls"
        vw.build_baseline = lambda args, workdir: {
            "pdk_root": "/nonexistent-pdk",
            "drc": {"status": "clean", "violation_count": 0},
            "run": {"lvs": {"status": "match", "error_count": 0}},
            "coverage": {"ports": 1, "ports_clean": 1},
        }
        vw.publish_baseline = lambda b: calls["baseline"].append("published")

        def fake_run_controls(args, b):
            ids = args.only or ["control-a", "control-b"]
            return {"controls": [_fake_control(i) for i in ids], "all_detected": True,
                    "baseline_rerun_after_controls": {"status": "match", "error_count": 0,
                                                      "stable_fields_equal_to_first_baseline": True}}

        vw.run_controls = fake_run_controls
        real_publish = vw.publish_controls

        def recording_publish(summary, pdk_root):
            calls["controls"].append(",".join(r["id"] for r in summary["controls"]))
            real_publish(summary, pdk_root)

        vw.publish_controls = recording_publish
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc = vw.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, calls["baseline"], calls["controls"]

    for cmd in ("controls", "all"):
        with tempfile.TemporaryDirectory(prefix="test-verify-whole-") as t:
            tmp = Path(t)
            rc, base, ctl = run([cmd, "--no-publish", "--only", "swap-analog-ring-bits"], tmp)
            _check(f"{cmd} --no-publish --only: runs (exit 0)", rc == 0, rc)
            _check(f"{cmd} --no-publish --only: publishes nothing", not base and not ctl and not (tmp / "verify").exists(), (base, ctl))
        with tempfile.TemporaryDirectory(prefix="test-verify-whole-") as t:
            tmp = Path(t)
            rc, base, ctl = run([cmd, "--no-publish"], tmp)
            _check(f"{cmd} --no-publish: publishes nothing", rc == 0 and not base and not ctl and not (tmp / "verify").exists(), (rc, base, ctl))
        with tempfile.TemporaryDirectory(prefix="test-verify-whole-") as t:
            tmp = Path(t)
            rc, base, ctl = run([cmd, "--only", "swap-analog-ring-bits"], tmp)
            _check(f"{cmd} --only without --no-publish: refused before any stage runs",
                   rc != 0 and not base and not ctl and not (tmp / "verify").exists(), (rc, base, ctl))
        with tempfile.TemporaryDirectory(prefix="test-verify-whole-") as t:
            tmp = Path(t)
            rc, base, ctl = run([cmd], tmp)
            published = json.loads((tmp / "verify" / "controls" / "controls.json").read_text()) if (tmp / "verify" / "controls" / "controls.json").is_file() else None
            _check(f"{cmd}: full campaign publishes the controls evidence",
                   rc == 0 and ctl == ["control-a,control-b"] and published is not None and len(published["controls"]) == 2
                   and (tmp / "verify" / "controls" / "controls.md").is_file(), (rc, ctl))
            _check(f"{cmd}: baseline published only for `all`", base == (["published"] if cmd == "all" else []), base)
    _check("dispatcher tests left the committed controls evidence untouched", snapshot(VERIFY / "controls") == repo_controls_before)
    _check("dispatcher tests left the committed verify evidence untouched", snapshot(VERIFY) == repo_verify_before)


def main() -> int:
    check_flatten()
    check_canonicalise()
    check_endpoints()
    check_build_reference()
    check_committed_evidence()
    check_committed_controls()
    check_coverage_audit_logic()
    check_committed_coverage_audit()
    check_physical_estimate_logic()
    check_committed_physical_estimates()
    check_physical_estimate_geometry()
    check_dispatcher_publication()
    return _checker.summary("layout/test_verify_whole.py")


if __name__ == "__main__":
    raise SystemExit(main())
