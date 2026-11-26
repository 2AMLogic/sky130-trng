#!/usr/bin/env python3
"""Compose the whole TRNG block: sampler_core (analog) + trng_digital.

Issue #172 (part of #170, contributes to #18 AC3). This is the whole-block
sibling of ``layout/bin/compose-cell.py`` -- and deliberately a *separate,
narrowly scoped* entry point rather than a mode of it. ``compose-cell.py``'s
contract is one chain, ``gen -> compose -> DRC -> extract -> LVS``, and its
``--check`` fails unless every link is clean. A whole-block mixed-level LVS
(transistor-level analog + a standard-cell digital macro whose committed
abstract netlist has zero devices) cannot be completed here -- that is #173's
scope -- so this script composes, audits the composition contract, and says
so in its own verdict:

    status = "composed; physical sign-off pending (#173 DRC/LVS, #174 characterization)"

It never reports DRC or LVS as passed, and ``compose-cell.py --check`` is
untouched (it keeps its full-chain semantics for every ``layout/*/cell.json``).

The PDK-free, ``klayout``-free half of this work (DEF/RTL/SPICE parsing,
the floorplan model and interface audit, request construction, response
verdicts, the combined reference and the report rendering) lives in
``layout/bin/compose_whole_lib.py`` (issue #775), imported by name -- the
same seam ``verify-whole.py`` uses with ``verify_whole_lib.py``. This file
keeps the ``klayout.db`` geometry audits and the ``klt`` compose/check/DRC
driver.

Usage
-----

    python3 layout/bin/compose-whole.py layout/trng_whole/floorplan.json
    python3 layout/bin/compose-whole.py layout/trng_whole/floorplan.json --check
    python3 layout/bin/compose-whole.py layout/trng_whole/floorplan.json \\
        --informational-drc        # also (re)write drc-informational.json

``--check`` rebuilds everything into a temporary directory (the committed
layout/ inputs are only ever *read*) and diffs the stable output fields:
input hashes, the tool's per-net routing verdicts, macro transforms, the
canonical geometry hash of the composed stream, the area verdict, every
generated text artifact byte-for-byte. A binary GDS difference with an
identical canonical geometry hash is reported as a timestamp-only
difference, not as drift.

What it does (all inputs are read from the committed macro artifacts)
--------------------------------------------------------------------

1. Reads the digital macro's *physical* interface from ``trng_digital.def``
   (pin shapes, layers, supply stripes) and cross-checks it against the GDS pin
   labels and the RTL port list -- it never infers pins from the signal-only
   routed Verilog.
2. Audits every hand-declared analog port against a flat connectivity
   extraction of ``sampler_core.gds`` (the analog macro carries no top-level pin
   shapes: ``compose.response.json`` reports ``ports: []``).
3. Draws the boundary pad cell with ``klt draw``, builds ONE ``klt gen-compose``
   request (explicit placement, both macros mirrored, ``top_metal`` routing
   with the tool's own via ladders, label-only ``pins[]`` for the 107 digital
   external pins) and runs it.
4. Inspects both the tool's *errors* and its *routing verdicts* -- parsing the
   JSON is not enough, because ``run_klt`` deliberately accepts a partial
   composition (exit 3): every net must be ``routed``, every leg routed with no
   reason, ``landed_on_block`` true, ``unrouted_nets`` empty.
5. Independently re-extracts the composed GDS and proves each net's terminals
   share one cluster, distinct nets stay distinct (the four ``vddr`` rails and
   ``vdd``/``vss`` included), and no stray interface label rides along.
6. Writes the combined LVS reference (``trng_whole.ref.spice``), the interface
   table (``interface.json`` / ``interface.md``), the area verdict and the
   provenance (``report.json``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gds_geometry import (canonical_geometry_hash, flat_extract,  # noqa: E402
                           net_labels, probe)
from _klt_common import (BuildError, klt_env, klayout_db as _klayout,  # noqa: E402
                         load_json, run_klt, write_json)
from compose_whole_lib import (  # noqa: E402
    STATUS_PENDING,
    Model,
    _LAYER_KEY,
    analog_macro_klt,
    area_verdict,
    audit_interface,
    build_reference,
    build_request,
    check_reference_structure,
    composed_terminals,
    diff_dict,
    input_hashes,
    interface_markdown,
    interface_rows,
    pad_draw_params,
    pin_center,
    published_names,
    read_text,
    sanitize_response,
    sha256_file,
    sha256_text,
    stable_view,
    verify_compose_response,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# flat connectivity extraction (pure klayout.db; no klt) -- flat_extract,
# net_labels, probe and canonical_geometry_hash live in _gds_geometry.py
# (issue #613); the composer imports them by name above.
# --------------------------------------------------------------------------


def drawn_bbox_um(gds_path: Path) -> dict:
    """Bounding box (um) of every non-text shape of the top cell, flattened."""
    db = _klayout()
    layout = db.Layout()
    layout.read(str(gds_path))
    top = layout.top_cell()
    box = db.Box()
    for idx in layout.layer_indexes():
        region = db.Region(top.begin_shapes_rec(idx))
        if region.count():
            box += region.bbox()
    dbu = layout.dbu
    return {
        "x0": round(box.left * dbu, 6),
        "y0": round(box.bottom * dbu, 6),
        "x1": round(box.right * dbu, 6),
        "y1": round(box.top * dbu, 6),
    }


# --------------------------------------------------------------------------
# interface geometry audits (klayout.db; no klt)
# --------------------------------------------------------------------------


def audit_digital_geometry(model: Model) -> dict:
    """DEF pins vs GDS pin labels; supply ports vs the DEF's met5 stripes."""
    db = _klayout()
    layout = db.Layout()
    layout.read(str(model.path["dig_gds"]))
    top = layout.top_cell()
    dbu = layout.dbu
    labels: dict[str, list] = {}
    for idx in layout.layer_indexes():
        info = layout.get_info(idx)
        for shape in top.shapes(idx).each():
            if shape.is_text():
                pos = shape.text.trans.disp
                labels.setdefault(shape.text_string, []).append(
                    (info.layer, info.datatype, pos.x * dbu, pos.y * dbu)
                )
    errors = []
    for pin in model.pins:
        found = labels.get(pin["name"])
        if not found:
            errors.append(f"{pin['name']}: no GDS label")
            continue
        cx, cy = pin_center(pin)
        want_layer = (pin["layer_gds"][0], 5)
        if pin["use"] != "signal":
            # supply pins: the GDS label sits on one of the stripes; require
            # it to lie inside one of the DEF rects.
            ok = any(
                x0 - 1e-6 <= lx <= x1 + 1e-6 and y0 - 1e-6 <= ly <= y1 + 1e-6
                for (_, _, lx, ly) in found
                for (x0, y0, x1, y1) in pin["rects_um"]
            )
        else:
            ok = any(
                (lnum, ldt) == want_layer and abs(lx - cx) < 1e-3 and abs(ly - cy) < 1e-3
                for (lnum, ldt, lx, ly) in found
            )
        if not ok:
            errors.append(f"{pin['name']}: GDS label {found} disagrees with DEF pin")
    for name, port in model.fp["digital_supply_ports"].items():
        pin = model.dig_by_name.get(name)
        if not pin:
            errors.append(f"supply port {name}: not in DEF")
            continue
        if list(port["layer"]) != pin["layer_gds"]:
            errors.append(f"supply port {name}: layer {port['layer']} != DEF {pin['layer_gds']}")
        inside = any(
            x0 - 1e-6 <= port["x_um"] <= x1 + 1e-6 and y0 - 1e-6 <= port["y_um"] <= y1 + 1e-6
            for (x0, y0, x1, y1) in pin["rects_um"]
        )
        if not inside:
            errors.append(f"supply port {name} at ({port['x_um']}, {port['y_um']}) is not on a DEF {name} stripe")
    if errors:
        raise BuildError("digital geometry audit failed:\n  " + "\n  ".join(errors))
    return {"def_pins_with_matching_gds_label": len(model.pins)}


def audit_analog_ports(model: Model) -> dict:
    """Each declared analog port vs the analog GDS's own extracted nets."""
    db, l2n, regions = flat_extract(model.path["ana_gds"])
    recipe = load_json(model.path["ana_recipe"])
    place = next(s for s in recipe["stages"] if s.get("name") == "place")
    origins = {k: v["x"] for k, v in place["placement"]["origins_um"].items()}
    cfg_origins = model.fp["sampler_origins_um"]
    if origins != cfg_origins:
        raise BuildError(
            f"sampler origins in floorplan {cfg_origins} disagree with "
            f"layout/sampler_core/cell.json 'place' stage {origins}"
        )
    # design/trng_top.spice instance order -> which sampler drives which tap
    spice = read_text(model.path["ana_spice"])
    inst_to_tap = {}
    for match in re.finditer(r"^(xs\w+)\s+(\S+)\s+clk\s+rst_n\s+(\S+)\s+vdd\s+vss\s+sampler_dff",
                             spice, re.M):
        inst_to_tap.setdefault(match.group(1)[1:], match.group(3))
    label_universe = {
        "en1", "en2", "en3", "en4", "vddr1", "vddr2", "vddr3", "vddr4",
        "vdd", "vss", "clk", "rst_n",
    }
    errors = []
    clusters = {}
    for name, port in model.fp["analog_ports"].items():
        key = _LAYER_KEY.get(tuple(port["layer"]))
        net = probe(db, l2n, regions, key, port["x_um"], port["y_um"])
        if net is None:
            errors.append(f"{name}: no {key} conductor at ({port['x_um']}, {port['y_um']})")
            continue
        labels = net_labels(net)
        clusters[name] = net.cluster_id
        if "label" in port:
            if port["label"] not in labels:
                errors.append(f"{name}: net there carries {sorted(labels & label_universe)}, not {port['label']!r}")
            stray = (labels & label_universe) - {port["label"]}
            if stray:
                errors.append(f"{name}: net also carries {sorted(stray)}")
        else:
            sampler = port["sampler"]
            if inst_to_tap.get(sampler) != name:
                errors.append(f"{name}: design/trng_top.spice drives {inst_to_tap.get(sampler)!r} from x{sampler}")
            if "q" not in labels:
                errors.append(f"{name}: not a sampler q net (labels {sorted(labels)[:6]})")
            offset = port["x_um"] - origins[sampler]
            if abs(offset - model.fp["sampler_q_pad_offset_um"]) > 1e-6:
                errors.append(f"{name}: x offset {offset} in {sampler} != q pad offset")
            if label_universe & labels:
                errors.append(f"{name}: tap net carries {sorted(label_universe & labels)}")
    dup = {cid for cid in clusters.values() if list(clusters.values()).count(cid) > 1}
    if dup:
        errors.append(f"analog ports share extracted nets: {sorted(dup)}")
    if errors:
        raise BuildError("analog port audit failed:\n  " + "\n  ".join(errors))
    return {"ports_checked": len(clusters), "distinct_extracted_nets": len(set(clusters.values()))}


# --------------------------------------------------------------------------
# post-compose connectivity audit
# --------------------------------------------------------------------------


def audit_composed_connectivity(model: Model, gds_path: Path) -> dict:
    db, l2n, regions = flat_extract(gds_path)
    terms = composed_terminals(model)
    names = set(model.net_by_name)
    universe = names | set(model.external_digital) | model.supply_pins
    expected_labels = {
        name: ({name} | ({net["digital"]} if net.get("digital") in model.supply_pins else set()))
        for name, net in model.net_by_name.items()
    }
    errors = []
    cluster_of: dict[str, int] = {}
    for name, rows in terms.items():
        ids = set()
        labels_union = set()
        for row in rows:
            net = probe(db, l2n, regions, row["layer"], row["x"], row["y"])
            if net is None:
                errors.append(f"{name}: no conductor under {row['kind']} {row['name']} at ({row['x']}, {row['y']})")
                continue
            ids.add(net.cluster_id)
            labels_union |= net_labels(net)
        if len(ids) != 1:
            errors.append(f"{name}: terminals fall in {len(ids)} extracted nets (want 1)")
        else:
            cluster_of[name] = next(iter(ids))
        iface = labels_union & universe
        if iface != expected_labels[name]:
            errors.append(f"{name}: interface labels on its net are {sorted(iface)}, want {sorted(expected_labels[name])}")
    seen: dict[int, str] = {}
    for name, cid in cluster_of.items():
        if cid in seen:
            errors.append(f"nets {seen[cid]!r} and {name!r} are SHORTED (one extracted net)")
        seen[cid] = name
    # digital external pins must stay on their own clusters
    ext_clusters = {}
    for name in model.external_digital:
        pin = model.dig_by_name[name]
        x, y = model.dig_xy(*pin_center(pin))
        net = probe(db, l2n, regions, _LAYER_KEY[tuple(pin["layer_gds"])], x, y)
        if net is None:
            errors.append(f"digital external pin {name}: no conductor at ({x}, {y})")
            continue
        if net.cluster_id in seen:
            errors.append(f"digital external pin {name} is shorted to net {seen[net.cluster_id]!r}")
        if net.cluster_id in ext_clusters:
            errors.append(f"digital external pins {ext_clusters[net.cluster_id]!r} and {name!r} are shorted")
        ext_clusters[net.cluster_id] = name
    rails = [cluster_of.get(f"vddr{i}") for i in (1, 2, 3, 4)]
    if len(set(rails)) != 4 or None in rails:
        errors.append("the four vddr rails are not four distinct extracted nets")
    if cluster_of.get("vdd") in rails or cluster_of.get("vss") in rails:
        errors.append("a vddr rail is merged with vdd/vss")
    if errors:
        raise BuildError("composed connectivity audit failed:\n  " + "\n  ".join(errors))
    return {
        "nets_checked": len(cluster_of),
        "distinct_clusters": len(set(cluster_of.values())),
        "digital_external_pins_isolated": len(ext_clusters),
        "vddr_rails_distinct": True,
        "vdd_alias": sorted(expected_labels["vdd"]),
        "vss_alias": sorted(expected_labels["vss"]),
        "scope": "metal-stack (li1..met5) terminal connectivity and label identity only; "
                 "no device/well/substrate model -- not LVS",
    }


# --------------------------------------------------------------------------
# build / check
# --------------------------------------------------------------------------


def klt_version(env: dict[str, str]) -> dict:
    return run_klt(["version"], env=env)


def compose_whole(fp: dict, spec_dir: Path, out_dir: Path, *, runner=run_klt) -> dict:
    """Build every artifact into *out_dir* (a scratch directory).

    Macro inputs are always passed to klt as absolute paths, so the build is
    independent of where *out_dir* is; :func:`publish` writes the committed
    spelling (repo-relative request) and copies the results into the layout
    directory only after every audit passed.
    """
    model = Model(fp, spec_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = klt_env()
    top = fp["top_cell"]

    interface = audit_interface(model)
    dig_audit = audit_digital_geometry(model)
    ana_audit = audit_analog_ports(model)

    # boundary pad cell, drawn by klt (committed request + response)
    draw_params = pad_draw_params(model)
    write_json(out_dir / "pins.draw.request.json", draw_params)
    cell = fp["pad_row"]["cell_name"]
    draw = runner(
        ["draw", "--params", "pins.draw.request.json", "--cell-name", cell, "-o", f"{cell}.gds"],
        env=env, cwd=out_dir,
    )
    write_json(out_dir / "pins.draw.response.json", draw)

    request = build_request(model, absolute_inputs=True)
    write_json(out_dir / "compose.request.json", request)
    response = runner(["gen-compose", "compose.request.json"], env=env, cwd=out_dir)
    verdict = verify_compose_response(response, request)
    sanitize_response(response, model)
    write_json(out_dir / "compose.response.json", response)

    gds_path = out_dir / f"{top}.gds"
    connectivity = audit_composed_connectivity(model, gds_path)
    geometry_hash, geometry_counts = canonical_geometry_hash(gds_path)
    bbox = drawn_bbox_um(gds_path)
    blocks = {b["id"]: b for b in response["blocks"]}
    area = area_verdict(model, bbox, blocks["ana"]["bbox_um"], blocks["dig"]["bbox_um"])

    ref_text = build_reference(model)
    (out_dir / f"{top}.ref.spice").write_text(ref_text)
    reference = check_reference_structure(out_dir / f"{top}.ref.spice", model)

    table = interface_rows(model)
    write_json(out_dir / "interface.json", table)
    (out_dir / "interface.md").write_text(interface_markdown(table, area))

    version = klt_version(env)
    pdk = load_json(REPO_ROOT / "layout/pdk.json")
    digital_pins = load_json(REPO_ROOT / "digital/flow/place-and-route/tool-pins.json")
    db = _klayout()
    routing = [
        {
            "net": net["net"],
            "status": net["status"],
            "route_length_um": round(net["route_length_um"], 3),
            "legs": len(net["legs"]),
            "landed_on_block": net["landed_on_block"],
        }
        for net in response["nets"]
    ]
    report = {
        "schema_version": 1,
        "top_cell": top,
        "status": STATUS_PENDING,
        "provisional": "geometry/connectivity composition evidence only; provisional until silicon",
        "verification_not_claimed": [
            "whole-block DRC (#173)",
            "whole-block LVS / mixed-level reference comparison (#173)",
            "post-layout PVT characterization, supply coupling, IR, period scatter (#174)",
        ],
        "inputs_sha256": input_hashes(model),
        "tool": {
            "klt": version["version"],
            "klt_git_commit": version.get("git_commit"),
            "klt_is_release": version.get("is_release"),
            "klayout_via_klt": version.get("klayout_version"),
            "python_klayout_db": getattr(db, "__version__", None) or __import__("klayout").__version__,
            "open_pdks_commit": pdk["open_pdks_commit"],
            "pdk_variant": pdk["variant"],
            "macro_tool_pins": {
                "trng_digital": {"klt": digital_pins["klt_version"], "openroad": digital_pins["openroad"],
                                 "klayout": digital_pins["klayout"],
                                 "source": "digital/flow/place-and-route/tool-pins.json"},
                "sampler_core": {"klt": analog_macro_klt(),
                                 "source": "layout/sampler_core/*.json provenance.klt_version"},
            },
            "reconciliation": "the two macros were produced by different klt builds; this composition "
                              "only places and wires their committed GDS and re-extracts metal "
                              "connectivity, so it pins the composing klt rather than assuming the "
                              "macro environments are identical.",
        },
        "request_sha256": sha256_text(json.dumps(build_request(model, absolute_inputs=False), indent=2) + "\n"),
        "macros": {
            blk: {
                "cell": blocks[blk]["cell_name"],
                "orientation": blocks[blk]["orientation"],
                "offset_um": blocks[blk]["offset_um"],
                "bbox_um": blocks[blk]["bbox_um"],
                "source_digest": blocks[blk]["source_digest"],
            }
            for blk in ("dig", "ana")
        },
        "routing": {
            "layer_role": fp["routing"]["layer_role"],
            "layer": fp["routing"]["layer"],
            "width_um": fp["routing"]["width_um"],
            "tool_verdict": verdict,
            "nets": routing,
        },
        "audits": {
            "interface": interface,
            "digital_geometry": dig_audit,
            "analog_ports": ana_audit,
            "composed_connectivity": connectivity,
            "reference_structure": reference,
        },
        "outputs": {
            f"{top}.gds": {"sha256": sha256_file(gds_path),
                           "canonical_geometry_sha256": geometry_hash,
                           "canonical_counts": geometry_counts},
            f"{cell}.gds": {"sha256": sha256_file(out_dir / f"{cell}.gds")},
            f"{top}.ref.spice": {"sha256": sha256_text(ref_text)},
            "interface.json": {"sha256": sha256_file(out_dir / "interface.json")},
            "interface.md": {"sha256": sha256_file(out_dir / "interface.md")},
        },
        "area": area,
    }
    write_json(out_dir / "report.json", report)
    return report


def publish(fp: dict, spec_dir: Path) -> dict:
    """Build in a scratch directory; commit to *spec_dir* only on success.

    A failed composition (unrouted/partial net, failed audit, missing input)
    raises BuildError BEFORE anything is copied, so a failing run can never
    overwrite the committed evidence with a partial result.
    """
    with tempfile.TemporaryDirectory(prefix="klt-compose-whole-") as tmp:
        tmp_dir = Path(tmp)
        report = compose_whole(fp, spec_dir, tmp_dir)
        # the committed request spells the macro inputs repo-relative
        write_json(tmp_dir / "compose.request.json",
                   build_request(Model(fp, spec_dir), absolute_inputs=False))
        for name in published_names(fp):
            (spec_dir / name).write_bytes((tmp_dir / name).read_bytes())
    return report


def check_whole(fp: dict, spec_dir: Path) -> int:
    committed_path = spec_dir / "report.json"
    if not committed_path.exists():
        print(f"error: {committed_path} is missing -- nothing to check against", file=sys.stderr)
        return 1
    committed = json.loads(committed_path.read_text())
    top = fp["top_cell"]
    cell = fp["pad_row"]["cell_name"]
    with tempfile.TemporaryDirectory(prefix="klt-compose-whole-") as tmp:
        tmp_dir = Path(tmp)
        rebuilt = compose_whole(fp, spec_dir, tmp_dir)
        drift = diff_dict(stable_view(committed), stable_view(rebuilt))
        # the committed macro inputs must not have been touched by the rebuild
        for name in (f"{top}.ref.spice", "interface.json", "interface.md",
                     "pins.draw.request.json"):
            if (spec_dir / name).read_text() != (tmp_dir / name).read_text():
                drift.append(f"{name}: text differs from rebuild")
        for name in (f"{top}.gds", f"{cell}.gds"):
            a, b = sha256_file(spec_dir / name), sha256_file(tmp_dir / name)
            if a != b:
                gds_hash_a = canonical_geometry_hash(spec_dir / name)[0]
                gds_hash_b = canonical_geometry_hash(tmp_dir / name)[0]
                if gds_hash_a == gds_hash_b:
                    print(f"note: {name} binary hash differs but canonical geometry is "
                          "identical (header timestamps only)")
                else:
                    drift.append(f"{name}: canonical geometry differs")
        # committed request normalised to repo-relative paths
        rel_request = build_request(Model(fp, spec_dir), absolute_inputs=False)
        if json.loads((spec_dir / "compose.request.json").read_text()) != rel_request:
            drift.append("compose.request.json: committed request disagrees with the floorplan")
    if drift:
        print(f"DRIFT in {spec_dir}:", file=sys.stderr)
        for line in drift:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"{spec_dir}: rebuild matches committed evidence (status: {committed['status']})")
    return 0


def informational_drc(fp: dict, spec_dir: Path) -> dict:
    """`klt drc` on the composed GDS, attributed by origin. NOT sign-off."""
    env = klt_env()
    top = fp["top_cell"]
    response = run_klt(["drc", f"{top}.gds", "--deck", "sky130"], env=env, cwd=spec_dir)
    by_origin: dict[str, dict[str, int]] = {}
    for violation in response.get("violations", []):
        path = violation.get("source_path") or []
        origin = path[0].split("__")[0] if path else "top"
        by_origin.setdefault(origin, {}).setdefault(violation["rule"], 0)
        by_origin[origin][violation["rule"]] += 1
    summary = {
        "schema_version": 1,
        "informational_only": True,
        "not_signoff": "Whole-block DRC sign-off is #173. This run only attributes violations "
                       "klt reports on the composed stream: those whose source_path starts in a "
                       "macro (ana__ = sampler_core, dig__ = trng_digital) are pre-existing "
                       "macro-internal findings of this klt/deck build, not composition-added.",
        "klt": response.get("provenance", {}).get("klt_version"),
        "deck": response.get("provenance", {}).get("deck"),
        "status": response["status"],
        "violation_count": response["violation_count"],
        "rule_counts": response.get("rule_counts"),
        "violations_by_origin": by_origin,
        "input_content_hash": response.get("provenance", {}).get("input", {}).get("content_hash"),
        "coverage": {
            key: (response.get("coverage") or {}).get(key)
            for key in ("layers_checked", "layers_in_stream_without_rules", "rules_skipped")
        },
    }
    write_json(spec_dir / "drc-informational.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("floorplan", type=Path, help="path to layout/trng_whole/floorplan.json")
    parser.add_argument("--check", action="store_true",
                        help="rebuild into a temp dir and diff against the committed evidence")
    parser.add_argument("--informational-drc", action="store_true",
                        help="after composing, also write drc-informational.json (NOT sign-off)")
    args = parser.parse_args(argv)

    fp_path = args.floorplan.resolve()
    spec_dir = fp_path.parent
    try:
        fp = load_json(fp_path)
        if args.check:
            return check_whole(fp, spec_dir)
        report = publish(fp, spec_dir)
        if args.informational_drc:
            drc = informational_drc(fp, spec_dir)
            print(f"drc (informational): {drc['status']}, {drc['violation_count']} violations, "
                  f"by origin {json.dumps(drc['violations_by_origin'])}")
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    area = report["area"]
    print(f"cell:      {report['top_cell']}")
    print(f"status:    {report['status']}")
    print(f"routing:   {report['routing']['tool_verdict']['nets']} nets / "
          f"{report['routing']['tool_verdict']['legs']} legs routed, "
          f"{report['routing']['tool_verdict']['pins_promoted']} pins promoted")
    print(f"area:      {area['width_um']} x {area['height_um']} um = {area['area_mm2']} mm2 "
          f"vs {area['target_mm2']} mm2 -> {area['result']}")
    print(f"geometry:  {report['outputs'][report['top_cell'] + '.gds']['canonical_geometry_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
