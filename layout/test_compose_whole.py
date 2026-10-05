#!/usr/bin/env python3
"""Composition-contract tests for ``layout/bin/compose-whole.py`` (issue #172).

Standalone script, following ``layout/test_compose_cell.py``'s "run it
directly" convention (no pytest suite in this repository):

    python3 layout/test_compose_whole.py

Pure Python for everything on the PR-blocking CI path: no ``klt``, no PDK, no
GDS read. The only inputs are the committed macro artifacts under ``layout/``
and ``design/`` (text: DEF, RTL, SPICE, JSON) and the committed
``layout/trng_whole/`` evidence. Checks that need ``klayout.db`` (an
extraction of the analog GDS, canonical geometry hashing) run only where
python ``klayout`` is importable and are reported as ``skip`` otherwise.

Why this exists. The whole-block composition can fail in ways that still
produce a plausible GDS and a parseable JSON response:

- ``run_klt`` deliberately accepts a *partial* composition (``klt gen-compose``
  exit 3 with a parseable body), so "no exception" does not mean "routed";
- a mis-mapped boundary pin (a swapped ``raw_bit``/``raw_valid`` tap, a
  duplicated digital pin, a missing analog pin) composes and routes fine;
- an unreviewed edit to a committed input (``design/trng_top.spice``, the
  digital DEF, a macro GDS) would silently stale the committed evidence.

Each group below pins one of those so a future edit has to break a test, not a
verdict. These are composition-contract checks; extracted physical fault
controls (DRC/LVS negatives) belong to #173.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "design"))
from _test_check import Checker  # noqa: E402

_MODULE_PATH = _HERE / "bin" / "compose-whole.py"
_spec = importlib.util.spec_from_file_location("compose_whole", _MODULE_PATH)
assert _spec and _spec.loader
cw = importlib.util.module_from_spec(_spec)
sys.modules["compose_whole"] = cw
_spec.loader.exec_module(cw)

_checker = Checker()
_check = _checker.check

SPEC_DIR = _HERE / "trng_whole"
FP = json.loads((SPEC_DIR / "floorplan.json").read_text())


def _model(mutate=None) -> "cw.Model":
    fp = copy.deepcopy(FP)
    if mutate:
        mutate(fp)
    return cw.Model(fp, SPEC_DIR)


def _raises(label: str, fn, needle: str) -> None:
    try:
        fn()
    except cw.BuildError as exc:
        _check(label, needle in str(exc), f"BuildError without {needle!r}: {exc}")
    else:
        _check(label, False, "no BuildError raised")


# --------------------------------------------------------------------------
# input parsing: physical pins, RTL bits, analog pin types
# --------------------------------------------------------------------------


def check_digital_physical_interface() -> None:
    model = _model()
    pins = {p["name"]: p for p in model.pins}
    _check("DEF has 113 pins (111 signals + VPWR/VGND)", len(pins) == 113, len(pins))
    _check("RTL expands to 111 scalar bits", len(model.rtl_bits) == 111, len(model.rtl_bits))
    signals = {n for n in pins if n not in ("VPWR", "VGND")}
    _check("every RTL bit has a DEF pin and vice versa",
           signals == {b["name"] for b in model.rtl_bits})
    raw = pins["raw_bit"]
    _check("raw_bit is a 0.3 um met3 pin at (0.4, 69.7)",
           raw["layer"] == "met3" and cw.pin_center(raw) == (0.4, 69.7)
           and cw.pin_width(raw) == 0.3, (raw["layer"], cw.pin_center(raw)))
    south = pins["bus_wdata[3]"]
    _check("bus_wdata[3] is a met2 pin on the SOUTH edge (y = 0.242)",
           south["layer"] == "met2" and abs(cw.pin_center(south)[1] - 0.242) < 1e-3
           and cw.pin_edge_direction(south, model.die_um) == 270)
    _check("raw_bit's edge is west (180)", cw.pin_edge_direction(raw, model.die_um) == 180)
    _check("VPWR has 8 met5 stripes, VGND has 9",
           len(pins["VPWR"]["rects_um"]) == 8 and len(pins["VGND"]["rects_um"]) == 9
           and pins["VPWR"]["layer"] == "met5" and pins["VPWR"]["use"] == "power"
           and pins["VGND"]["use"] == "ground",
           (len(pins["VPWR"]["rects_um"]), len(pins["VGND"]["rects_um"])))
    bus = [b for b in model.rtl_bits if b["base"] == "bus_addr"]
    _check("bus bit order is LSB first (bus_addr[0..3])",
           [b["name"] for b in bus] == [f"bus_addr[{i}]" for i in range(4)])
    _check("bus_rdata pin label differs from its DEF net (net bus_rdata_r[N])",
           pins["bus_rdata[7]"]["net"] == "bus_rdata_r[7]")
    _check("die is 245.05 x 245.05 um", model.die_um == (245.05, 245.05), model.die_um)


def check_analog_pin_types() -> None:
    model = _model()
    names = [p["name"] for p in model.ana_pins]
    _check("trng_top has the 18 documented pins in header order",
           names == ["en1", "en2", "en3", "en4", "vddr1", "vddr2", "vddr3", "vddr4",
                     "vdd", "vss", "clk", "rst_n", "raw_bit", "raw_valid",
                     "ring_bit1", "ring_bit2", "ring_bit3", "ring_bit4"], names)
    types = {p["name"]: p["direction"] for p in model.ana_pins}
    _check("pin types come from the *.ipin/*.opin/*.iopin comments",
           types["en1"] == "input" and types["raw_bit"] == "output"
           and types["vddr3"] == "inout" and types["clk"] == "input")


def check_mirror_transform() -> None:
    p = cw.mirror_point("mirror_x", {"x": 200.0, "y": 0.0}, 0.4, 69.7)
    _check("mirror_x: local (0.4, 69.7) -> (199.6, 69.7)", p == (199.6, 69.7), p)
    p = cw.mirror_point("mirror_x", {"x": 328.77, "y": 268.64}, 44.9, 2.71)
    _check("mirror_x + translate on the analog macro", p == (283.87, 271.35), p)
    _raises("an unknown orientation is rejected",
            lambda: cw.mirror_point("rotate_90", {"x": 0, "y": 0}, 1, 1), "unsupported orientation")


# --------------------------------------------------------------------------
# the interface audit: coverage, duplicates, aliases, directions
# --------------------------------------------------------------------------


def check_interface_audit_accepts_committed_floorplan() -> None:
    summary = cw.audit_interface(_model())
    _check("committed floorplan passes the interface audit",
           summary["errors"] == 0 and summary["digital_external_pins"] == 107
           and summary["whole_block_nets"] == 18, summary)
    model = _model()
    _check("107 digital pins are external, 4 shared, 2 supply",
           len(model.external_digital) == 107 and len(model.shared_digital) == 4
           and model.supply_pins == {"VPWR", "VGND"})


def check_interface_audit_rejects_bad_mappings() -> None:
    def dup_digital(fp):
        next(n for n in fp["nets"] if n["name"] == "raw_valid")["digital"] = "raw_bit"

    _raises("a digital pin claimed twice is rejected", lambda: cw.audit_interface(_model(dup_digital)),
            "claimed by both")

    def drop_analog(fp):
        fp["nets"] = [n for n in fp["nets"] if n["name"] != "ring_bit3"]
        fp["analog_ports"].pop("ring_bit3")

    _raises("an uncovered analog pin is rejected", lambda: cw.audit_interface(_model(drop_analog)),
            "not covered by any net: ['ring_bit3']")

    def alias(fp):
        next(n for n in fp["nets"] if n["name"] == "clk")["analog"] = "rst_n"

    _raises("a conflicting alias is rejected", lambda: cw.audit_interface(_model(alias)),
            "conflicting aliases")

    def ghost_digital(fp):
        next(n for n in fp["nets"] if n["name"] == "raw_bit")["digital"] = "raw_bitt"

    _raises("a digital pin that does not exist is rejected",
            lambda: cw.audit_interface(_model(ghost_digital)), "does not exist")

    def ghost_analog(fp):
        next(n for n in fp["nets"] if n["name"] == "en1")["analog"] = "en9"

    _raises("an analog pin that does not exist is rejected",
            lambda: cw.audit_interface(_model(ghost_analog)), "does not exist")

    def dup_net(fp):
        fp["nets"][5]["name"] = "en1"

    _raises("a duplicate whole-block net name is rejected",
            lambda: cw.audit_interface(_model(dup_net)), "duplicate whole-block net name")

    def no_supply(fp):
        next(n for n in fp["nets"] if n["name"] == "vdd").pop("digital")

    _raises("an untied digital supply pin is rejected",
            lambda: cw.audit_interface(_model(no_supply)), "digital supply pins not tied")

    model = _model()
    model.pins = [p for p in model.pins if p["name"] != "bus_re"]
    _raises("an RTL bit with no physical pin is rejected",
            lambda: cw.audit_interface(model), "without a physical DEF pin")

    model = _model()
    model.pins.append(dict(model.pins[3]))
    _raises("a duplicated physical pin is rejected",
            lambda: cw.audit_interface(model), "duplicate digital physical pin")

    model = _model()
    next(p for p in model.pins if p["name"] == "clk")["direction"] = "output"
    _raises("a DEF/RTL direction conflict is rejected",
            lambda: cw.audit_interface(model), "direction conflict")


def check_missing_input_is_fatal() -> None:
    def bad_def(fp):
        fp["macros"]["digital"]["def"] = "../trng_digital/does-not-exist.def"

    _raises("a missing DEF aborts before any tool runs", lambda: _model(bad_def), "missing input")

    def bad_gds(fp):
        fp["macros"]["analog"]["gds"] = "../sampler_core/nope.gds"

    _raises("a missing analog GDS aborts", lambda: _model(bad_gds), "missing input")
    _raises("a missing JSON input aborts", lambda: cw.load_json(SPEC_DIR / "nope.json"), "missing input")


# --------------------------------------------------------------------------
# floorplan invariants the router and the pitch rules depend on
# --------------------------------------------------------------------------


def check_floorplan_invariants() -> None:
    model = _model()
    lanes = {}
    for net in FP["nets"]:
        lanes[net["name"]] = model.ana_port_global(net["analog"])[0]
    xs = sorted(lanes.values())
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    _check("every met5 lane is >= 7 um from its neighbours (met5 pitch rule 3.2 um)",
           min(gaps) >= 7.0, min(gaps))
    order = ["raw_bit", "raw_valid", "clk", "rst_n"]
    pin_y = [model.dig_xy(*cw.pin_center(model.dig_by_name[n]))[1] for n in order]
    tap_x = [lanes[n] for n in order]
    _check("digital pins ascend in y", pin_y == sorted(pin_y), pin_y)
    _check("analog taps descend in x (the non-crossing nested-L matching)",
           tap_x == sorted(tap_x, reverse=True), tap_x)
    digital_east = FP["macros"]["digital"]["origin_um"]["x"]
    _check("every shared tap lies east of the digital macro's east edge",
           all(x > digital_east + 4 for x in tap_x), (tap_x, digital_east))
    vddr = [FP["analog_ports"][f"vddr{i}"]["x_um"] for i in (1, 2, 3, 4)]
    _check("four distinct vddr ports", len(set(vddr)) == 4, vddr)
    _check("VPWR escape lane sits outside the digital bbox",
           FP["vpwr_escape"]["lane_x_um"] < digital_east - model.die_um[0] - 0.8,
           FP["vpwr_escape"])
    pads = cw.pad_draw_params(model)["shapes"]
    _check("16 boundary pads, one per padded net", len(pads) == 16 == len(model.pad_names()), len(pads))
    xs = sorted((s["rect_um"][0], s["rect_um"][2]) for s in pads)
    _check("pads do not overlap", all(a[1] < b[0] for a, b in zip(xs, xs[1:])), xs[:3])


def check_request_shape() -> None:
    model = _model()
    request = cw.build_request(model, absolute_inputs=False)
    nets = {e["net"]: e for e in request["connectivity"]}
    _check("18 connectivity nets, 107 label-only pins", len(nets) == 18
           and len(request["pins"]) == 107, (len(nets), len(request["pins"])))
    _check("routing is on top_metal at the 1.6 um met5 floor",
           request["routing"] == {"layer_role": "top_metal", "width_um": 1.6})
    _check("vdd is a 3-pin bundle with the VPWR escape waypoints spelled out",
           len(nets["vdd"]["pins"]) == 3
           and nets["vdd"]["legs"][0]["waypoints_um"][0][0] == FP["vpwr_escape"]["lane_x_um"])
    _check("raw_bit is a plain 2-pin net (digital + analog, no pad)",
           [p["block"] for p in nets["raw_bit"]["pins"]] == ["dig", "ana"])
    _check("no port is both routed and label-promoted",
           not ({(p["block"], p["port"]) for e in request["connectivity"] for p in e["pins"]}
                & {("dig", p["port"]) for p in request["pins"]}))
    rel = cw.build_request(model, absolute_inputs=False)
    absolute = cw.build_request(model, absolute_inputs=True)
    _check("relative request keeps repo-relative macro paths",
           rel["blocks"][0]["cell"]["gds_path"] == "../trng_digital/trng_digital.gds")
    _check("absolute request resolves them for the temp rebuild",
           Path(absolute["blocks"][1]["cell"]["gds_path"]).is_absolute())


# --------------------------------------------------------------------------
# the tool verdict: errors AND routing verdicts
# --------------------------------------------------------------------------


def _good_response(request: dict) -> dict:
    nets = []
    for entry in request["connectivity"]:
        legs = entry.get("legs") or [{"pins": entry["pins"]}]
        nets.append({
            "net": entry["net"], "routed": True, "status": "routed",
            "route_length_um": 10.0, "landed_on_block": True,
            "legs": [{"pins": leg.get("pins", []), "routed": True, "reason": None,
                      "route_length_um": 5.0, "landed_on_block": True} for leg in legs],
        })
    blocks = [
        {"id": b["id"], "orientation": b["orientation"],
         "offset_um": dict(request["placement"]["origins_um"][b["id"]])}
        for b in request["blocks"]
    ]
    return {"nets": nets, "blocks": blocks, "unrouted_nets": [], "warnings": [],
            "pins": [{"net": p["net"]} for p in request["pins"]]}


def check_verify_compose_response() -> None:
    request = cw.build_request(_model(), absolute_inputs=False)
    good = _good_response(request)
    verdict = cw.verify_compose_response(good, request)
    _check("a complete response is accepted", verdict["nets"] == 18 and verdict["pins_promoted"] == 107,
           verdict)

    def mutated(fn):
        response = copy.deepcopy(good)
        fn(response)
        return response

    cases = {
        "an unrouted_nets entry": (lambda r: r.__setitem__("unrouted_nets", ["vdd"]), "unrouted_nets"),
        "a partial net": (lambda r: r["nets"][-2].update(status="partial", routed=False), "status 'partial'"),
        "a net with no landing on its block": (lambda r: r["nets"][3].update(landed_on_block=False),
                                                "landed_on_block"),
        "a null landed_on_block (unchecked)": (lambda r: r["nets"][3].update(landed_on_block=None),
                                                "landed_on_block"),
        "a rejected leg with a reason": (lambda r: r["nets"][0]["legs"][0].update(
            routed=False, reason="plows through block"), "not routed"),
        "a net missing from the response": (lambda r: r["nets"].pop(5), "missing from the response"),
        "an unexpected extra net": (lambda r: r["nets"].append(dict(r["nets"][0], net="ghost")),
                                    "unexpected nets"),
        "missing pins[] promotions": (lambda r: r["pins"].pop(), "pins[] promotions not reported"),
        "a macro at the wrong origin": (lambda r: r["blocks"][0].update(offset_um={"x": 1.0, "y": 0.0}),
                                        "placed at"),
        "a wrong orientation": (lambda r: r["blocks"][1].update(orientation="none"), "orientation"),
        "a tool error body": (lambda r: r.update(error={"message": "boom"}), "tool error"),
    }
    for label, (fn, needle) in cases.items():
        _raises(f"verify rejects {label}", lambda fn=fn: cw.verify_compose_response(mutated(fn), request),
                needle)


def check_run_klt_accepts_partial_so_the_verdict_check_is_load_bearing() -> None:
    """``run_klt`` returns a body-reported partial result (exit 3) untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "fake-klt"
        fake.write_text(
            "#!/bin/sh\n"
            "echo '{\"nets\": [{\"net\": \"vdd\", \"status\": \"partial\", \"routed\": false}], "
            "\"unrouted_nets\": [\"vdd\"]}'\n"
            "exit 3\n"
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        response = cw.run_klt(["gen-compose", "x.json"], env=dict(os.environ), cwd=Path(tmp),
                              klt=str(fake))
        _check("run_klt hands back a partial composition without raising",
               response["unrouted_nets"] == ["vdd"])
        request = cw.build_request(_model(), absolute_inputs=False)
        _raises("...and verify_compose_response is what rejects it",
                lambda: cw.verify_compose_response(response, request), "unrouted_nets")


# --------------------------------------------------------------------------
# the combined reference
# --------------------------------------------------------------------------


def check_reference() -> None:
    model = _model()
    text = cw.build_reference(model)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ref.spice"
        path.write_text(text)
        summary = cw.check_reference_structure(path, model)
        _check("generated reference passes its structural audit",
               summary["top_ports"] == 123 and summary["internal_nets"] == ["raw_bit", "raw_valid"],
               summary)
        _check("analog wrapper is carried verbatim",
               (model.path["ana_spice"].read_text().rstrip("\n")) in text)

        def broken(old: str, new: str, label: str, needle: str) -> None:
            path.write_text(text.replace(old, new, 1))
            _raises(label, lambda: cw.check_reference_structure(path, model), needle)

        broken("xdg vdd vss ", "xdg vss vdd ", "swapped VPWR/VGND aliasing is rejected", "alias")
        broken(" raw_valid bus_addr[0]", " bus_addr[0]", "a dropped digital net is rejected",
               "nets for trng_digital")
        broken(".subckt trng_whole vdd vss", ".subckt trng_whole vss vdd",
               "a reordered top port list is rejected", "port list differs")
        broken("xan en1 en2", "xan en2 en1", "a permuted analog pin is rejected", "analog pin")


# --------------------------------------------------------------------------
# committed evidence self-consistency (no tool needed)
# --------------------------------------------------------------------------


def check_committed_evidence() -> None:
    report = json.loads((SPEC_DIR / "report.json").read_text())
    _check("status is the explicit pending verdict, not a sign-off",
           report["status"] == cw.STATUS_PENDING and "pending" in report["status"])
    _check("DRC/LVS/characterization are listed as not claimed",
           len(report["verification_not_claimed"]) == 3)
    stale = []
    for path, digest in report["inputs_sha256"].items():
        full = _REPO_ROOT / path
        if not full.is_file() or cw.sha256_file(full) != digest:
            stale.append(path)
    _check("every recorded input hash still matches the committed input (inputs unchanged)",
           not stale, stale)
    for name, info in report["outputs"].items():
        if cw.sha256_file(SPEC_DIR / name) != info["sha256"]:
            _check(f"output {name} matches its recorded hash", False, name)
            break
    else:
        _check("every output matches its recorded hash", True)
    area = report["area"]
    bbox = area["bbox_um"]
    width, height = bbox["x1"] - bbox["x0"], bbox["y1"] - bbox["y0"]
    _check("area is width x height of the recorded bbox",
           abs(area["area_um2"] - width * height) < 0.01 and area["width_um"] == round(width, 6),
           area)
    _check("Met/Unmet agrees with the unchanged 0.05 mm2 target",
           area["target_mm2"] == 0.05
           and area["result"] == ("Met" if area["area_mm2"] < 0.05 else "Unmet"), area)
    _check("trng_digital alone already exceeds the target (no placement can meet it)",
           area["macro_bbox_mm2"]["trng_digital"] > area["target_mm2"], area["macro_bbox_mm2"])
    nets = report["routing"]["nets"]
    _check("all 18 nets recorded routed with landed_on_block",
           len(nets) == 18 and all(n["status"] == "routed" and n["landed_on_block"] for n in nets))
    audits = report["audits"]
    _check("composed connectivity audit recorded 18 distinct clusters, 107 isolated digital pins",
           audits["composed_connectivity"]["distinct_clusters"] == 18
           and audits["composed_connectivity"]["digital_external_pins_isolated"] == 107
           and audits["composed_connectivity"]["vddr_rails_distinct"] is True)
    table = json.loads((SPEC_DIR / "interface.json").read_text())
    _check("interface.json covers all 18 nets and all 111 digital signal + 2 supply pins",
           len(table["whole_block_nets"]) == 18 and len(table["digital_pins"]) == 111)
    request = json.loads((SPEC_DIR / "compose.request.json").read_text())
    _check("committed request is the floorplan's relative-path request",
           request == cw.build_request(_model(), absolute_inputs=False))
    _check("no absolute home path in any committed text artifact",
           not any("/home/" in p.read_text() for p in SPEC_DIR.iterdir()
                   if p.suffix in (".json", ".md", ".spice")))
    response = json.loads((SPEC_DIR / "compose.response.json").read_text())
    _check("committed response: complete routing, empty unrouted_nets",
           response["unrouted_nets"] == [] and all(n["status"] == "routed" for n in response["nets"]))
    drc = json.loads((SPEC_DIR / "drc-informational.json").read_text())
    _check("informational DRC is labelled not-sign-off and attributes everything to a macro",
           drc["informational_only"] is True and set(drc["violations_by_origin"]) <= {"ana", "dig"},
           drc["violations_by_origin"])


# --------------------------------------------------------------------------
# geometry checks (need python klayout; skipped where it is absent)
# --------------------------------------------------------------------------


def check_geometry_audits() -> None:
    try:
        import klayout.db  # noqa: F401, PLC0415
    except ImportError:
        print("skip   geometry audits (python klayout not importable)")
        return
    model = _model()
    summary = cw.audit_analog_ports(model)
    _check("committed analog ports all land on their intended extracted nets",
           summary["ports_checked"] == 18 and summary["distinct_extracted_nets"] == 18, summary)

    def swapped_en(fp):
        a, b = fp["analog_ports"]["en1"], fp["analog_ports"]["en2"]
        a["x_um"], b["x_um"] = b["x_um"], a["x_um"]

    _raises("swapped en1/en2 ports are caught against the analog extraction",
            lambda: cw.audit_analog_ports(_model(swapped_en)), "analog port audit failed")

    def swapped_taps(fp):
        fp["analog_ports"]["raw_bit"]["sampler"] = "sv"
        fp["analog_ports"]["raw_valid"]["sampler"] = "sb"

    _raises("swapped raw_bit/raw_valid taps are caught against design/trng_top.spice",
            lambda: cw.audit_analog_ports(_model(swapped_taps)), "design/trng_top.spice drives")

    def off_conductor(fp):
        fp["analog_ports"]["vddr2"]["y_um"] += 1.0

    _raises("a port off any conductor is caught",
            lambda: cw.audit_analog_ports(_model(off_conductor)), "no m2 conductor")
    _check("digital DEF pins match the GDS labels",
           cw.audit_digital_geometry(model)["def_pins_with_matching_gds_label"] == 113)
    committed = SPEC_DIR / "trng_whole.gds"
    h1, counts = cw.canonical_geometry_hash(committed)
    h2, _ = cw.canonical_geometry_hash(committed)
    report = json.loads((SPEC_DIR / "report.json").read_text())
    _check("canonical geometry hash is stable and matches the committed report",
           h1 == h2 == report["outputs"]["trng_whole.gds"]["canonical_geometry_sha256"], h1)
    audit = cw.audit_composed_connectivity(model, committed)
    _check("the committed composed GDS passes the connectivity audit", audit["nets_checked"] == 18, audit)
    bbox = cw.drawn_bbox_um(committed)
    _check("recomputed drawn bbox matches the report", bbox == report["area"]["bbox_um"], bbox)


def main() -> int:
    check_digital_physical_interface()
    check_analog_pin_types()
    check_mirror_transform()
    check_interface_audit_accepts_committed_floorplan()
    check_interface_audit_rejects_bad_mappings()
    check_missing_input_is_fatal()
    check_floorplan_invariants()
    check_request_shape()
    check_verify_compose_response()
    check_run_klt_accepts_partial_so_the_verdict_check_is_load_bearing()
    check_reference()
    check_committed_evidence()
    check_geometry_audits()
    return _checker.summary("layout/test_compose_whole.py")


if __name__ == "__main__":
    raise SystemExit(main())
