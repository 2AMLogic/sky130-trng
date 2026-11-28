#!/usr/bin/env python3
"""Informational whole-block metal/poly density and naive antenna-ratio
estimates (issue #283, split from #281's DRC coverage audit).

Everything this module computes is an **estimate for human review, never a
foundry sign-off**: the pinned curated sky130 deck ships no density or antenna
rules at all (that is exactly what `drc_coverage_audit.json` records), so
there is no foundry window, threshold or runset behind any number here. The
definitions below are part of the contract and are written verbatim into the
committed artifact's header (`physical_estimates.md` / `.json` under
`layout/trng_whole/verify/`).

Inputs are read-only committed evidence: `layout/trng_whole/trng_whole.gds`
(conductor and density geometry) and `layout/trng_whole/verify/extract.json.gz`
(the committed klt extraction: analog device gate `w_um`/`l_um`, gate-net
label sets, abstracted-instance counts). Nothing under `layout/` is modified
by a computation; publishing is the caller's decision.

Pure logic (window grid, cumulative ratios, label-set matching, drift) lives
in the sibling library `layout/bin/physical_estimates_lib.py` (issue #818),
imported and re-exported here by name, so `layout/test_verify_whole.py` can
exercise it on PR CI with no klayout, no klt and no PDK; the klayout-dependent
geometry and the real-geometry fixture controls stay in this file and are run
by `verify-whole.py estimates` / `estimates-controls` in the pinned
environment.

Why the conductor side is a *flat* extraction: `_gds_geometry
flat_extract` proves metal-level connectivity only (no device recognition).
Gate nets are therefore associated to conductor components purely through
their drawn pin labels -- a component belongs to a gate net only when *every*
label it carries is in that gate net's label set and in no other gate net's.
Components and gate nets that do not meet that bar are excluded and counted,
never guessed (label strings are deliberately shared between sibling nets in
this block -- e.g. `vddr`, `vddr3`, `vddr4` -- so an intersection rule would
silently mis-attribute them).

Why density is computed here rather than with `klt stats` / `klt economy`
(both were checked first): `stats --per-layer` reports the plain sum of
polygon areas without a boolean merge, so overlapping drawing geometry is
double-counted, and neither command provides foundry-density-style windowed
per-layer reporting. Filed as klayout-tools#3107; until it moves, this module
merges regions and tiles windows itself through klayout.db (the unioned
semantics are part of the artifact's definition, and `klt stats`'s unmerged
per-layer sums will NOT reproduce these numbers by design).
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gds_geometry import canonical_geometry_hash, flat_extract  # noqa: E402
from _hashing import sha256_file  # noqa: E402
from _klt_common import dumps  # noqa: E402
from physical_estimates_lib import (  # noqa: E402
    CONTROLS_JSON,
    CONTROLS_MD,
    CONTROL_TOP,
    DEFINITIONS,
    DECK_LAYER_NAMES,
    DENSITY_LAYERS,
    FLAT_KEYS,
    ISSUE,
    JSON_NAME,
    LEVELS,
    MD_NAME,
    NOT_SIGNOFF,
    SCHEMA_VERSION,
    STRIDE_UM,
    WINDOW_UM,
    EstimateError,
    antenna_ratios,
    build_document,
    cumulative_areas,
    drift,
    gate_areas_from_extract,
    layer_map_from_table,
    markdown,
    match_gate_components,
    split_labels,
    validate_grid,
    window_density,
    window_grid,
)


# --------------------------------------------------------------------------
# klayout-dependent geometry
# --------------------------------------------------------------------------


def load_extract(path: Path) -> dict:
    with gzip.open(path) as fh:
        return json.load(fh)


def conductor_pass(gds: Path, dbu: float) -> dict:
    """Flat conductor components with per-level drawn areas and label sets.

    Reuses _gds_geometry.flat_extract (li1..met5 + mcon/via connectivity,
    pin-label text layers). Areas are per level in um2. Anonymous component
    numbering never reaches the document -- components are identified by their
    label sets only, and only aggregate counts of the rest are committed.
    """
    _, l2n, regions = flat_extract(gds)
    top = l2n.netlist().top_circuit()
    dbu2 = dbu * dbu
    components, tokens = [], []
    labeled = unlabeled = 0
    for net in top.each_net():
        toks = split_labels(net.expanded_name(), ",")
        if not toks:
            unlabeled += 1
            continue
        labeled += 1
        areas = {}
        for lvl in LEVELS:
            region = regions.get(FLAT_KEYS[lvl])
            areas[lvl] = l2n.shapes_of_net(net, region, True).area() * dbu2 if region is not None else 0.0
        tokens.append(toks)
        components.append({"labels": sorted(toks), "area_um2": areas})
    return {
        "components": components,
        "component_tokens": tokens,
        "flat_nets_total": labeled + unlabeled,
        "labeled": labeled,
        "unlabeled": unlabeled,
    }


def density_pass(gds: Path, top: str, layer_map: dict[str, tuple[int, int]], dbu: float,
                 bbox: tuple[float, float, float, float]) -> dict:
    """Per-layer unioned drawn areas: whole-block and per clipped window."""
    import klayout.db as db  # noqa: PLC0415

    windows, skipped = window_grid(bbox, WINDOW_UM, STRIDE_UM)
    ly = db.Layout()
    ly.read(str(gds))
    cell = ly.cell(top)
    if cell is None:
        raise EstimateError(f"top cell {top!r} not found in {gds}")
    dbu2 = dbu * dbu
    boundary_area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
    layers, drawn_by_level = [], {}
    for name in DENSITY_LAYERS:
        num, dt = layer_map[name]
        li = ly.find_layer(num, dt)
        empty = li is None
        region = db.Region(cell.begin_shapes_rec(li)).merged() if not empty else db.Region()
        drawn = region.area() * dbu2
        drawn_by_level[name] = drawn
        per_window, count = [], 0
        for w in windows:
            box = db.Box(int(round(w["left"] / dbu)), int(round(w["bottom"] / dbu)),
                         int(round(w["right"] / dbu)), int(round(w["top"] / dbu)))
            dens = window_density((region & db.Region(box)).area() * dbu2, w["area"])
            if dens is not None:
                count += 1
                # rounded once here so the committed list, min, max and mean are
                # the same numbers a reader recomputes by hand
                per_window.append(round(dens, 9))
        layers.append({
            "name": name,
            "gds": f"{num}/{dt}",
            "empty_layer": empty,
            "drawn_area_um2": round(drawn, 9),
            "whole_block_density": round(window_density(drawn, boundary_area), 9)
            if boundary_area else None,
            "windows_counted": count,
            # row-major densities per counted window, so a single window can be
            # spot-checked by hand against the committed artifact
            "window_densities": per_window,
            "density_min": min(per_window) if per_window else 0.0,
            "density_max": max(per_window) if per_window else 0.0,
            "density_mean": round(sum(per_window) / len(per_window), 9) if per_window else 0.0,
        })
    return {"top": top, "windows_total": len(windows), "windows_skipped": skipped,
            "drawn_area_um2_by_level": drawn_by_level,
            "layers": layers}


def compute(gds: Path, extract: Path, *, top: str,
            layer_table: tuple[str, dict[tuple[int, int], str]],
            extract_rel: str, gds_rel: str) -> dict:
    """Full estimate document from the committed inputs (klayout required)."""
    import klayout  # noqa: PLC0415
    import klayout.db as db  # noqa: PLC0415

    table_hash, table = layer_table
    layer_map = layer_map_from_table(table)
    geometry_sha256, geometry_counts = canonical_geometry_hash(gds)
    gds_sha = sha256_file(gds)
    ext = load_extract(extract)
    matches_gds = (ext.get("provenance", {}).get("input", {}).get("content_hash")
                   == "sha256:" + gds_sha)

    ly = db.Layout()
    ly.read(str(gds))
    cell = ly.cell(top)
    if cell is None:
        raise EstimateError(f"top cell {top!r} not found in {gds}")
    dbu = ly.dbu
    box = cell.bbox()
    bbox = (box.left * dbu, box.bottom * dbu, box.right * dbu, box.top * dbu)

    gate = gate_areas_from_extract(ext)
    cond = conductor_pass(gds, dbu)
    gate_sets = {g: set(g.split("|")) for g in gate["gate_area_um2"]}
    matches, ambiguous, unmatched = match_gate_components(cond["component_tokens"], gate_sets)
    for i, comp in enumerate(cond["components"]):
        comp["gate_net"] = matches.get(i)
    cond |= {"matched": sum(1 for c in cond["components"] if c["gate_net"]),
             "ambiguous": ambiguous, "unmatched": unmatched}

    dens = density_pass(gds, top, layer_map, dbu, bbox)
    # antenna attribution is against the conductor levels' drawn areas only
    dens["drawn_area_um2_by_level"] = {lvl: dens["drawn_area_um2_by_level"][lvl] for lvl in LEVELS}
    return build_document(
        gds_rel=gds_rel, gds_sha256=gds_sha, geometry_sha256=geometry_sha256,
        geometry_counts=geometry_counts,
        extract_rel=extract_rel, extract_sha256=sha256_file(extract),
        extract_matches_gds=matches_gds,
        layer_map=layer_map, layer_table_hash=table_hash,
        klayout_version=klayout.__version__,
        bbox=bbox, gate=gate, components=cond, density=dens,
    )


# --------------------------------------------------------------------------
# real-geometry controls (klayout required; run by verify-whole.py
# estimates-controls and mirrored by the klayout-gated test group)
# --------------------------------------------------------------------------


def write_fixture(path: Path, boxes: dict[str, dict[str, list[tuple[float, float, float, float]]]],
                  texts: dict[str, list[tuple[str, float, float]]] | None = None,
                  instances: list[tuple[str, str, float, float]] | None = None) -> None:
    """A small synthetic GDS. *boxes* maps cell name -> {'layer/datatype':
    rects (um)}; *texts* are (string, x, y) um on the top cell; *instances*
    places (child, parent, x, y) um translations for hierarchy controls."""
    import klayout.db as db  # noqa: PLC0415

    ly = db.Layout()
    ly.dbu = 0.001
    cells = {CONTROL_TOP: ly.create_cell(CONTROL_TOP)}
    for cell_name, layers in boxes.items():
        if cell_name not in cells:
            cells[cell_name] = ly.create_cell(cell_name)
        for spec, rects in layers.items():
            li = ly.layer(*(int(x) for x in spec.split("/")))
            for l, b, r, t in rects:
                cells[cell_name].shapes(li).insert(
                    db.Box(int(l * 1000), int(b * 1000), int(r * 1000), int(t * 1000)))
    for spec, items in (texts or {}).items():
        li = ly.layer(*(int(x) for x in spec.split("/")))
        for s, x, y in items:
            cells[CONTROL_TOP].shapes(li).insert(
                db.Text(s, db.Trans(db.Vector(int(x * 1000), int(y * 1000)))))
    for child, parent, x, y in (instances or []):
        cells[parent].insert(db.CellInstArray(cells[child].cell_index(),
                                              db.Trans(db.Vector(int(x * 1000), int(y * 1000)))))
    ly.write(str(path))


def _fixture_extract(devices: list[dict]) -> dict:
    return {"devices": devices, "abstracted_cells": [],
            "provenance": {"input": {"content_hash": None}}}


# the fixed deck-layer table the controls resolve drawing datatypes through
FIXTURE_TABLE = {(66, 20): "poly.drawing", (67, 20): "li1.drawing", (68, 20): "met1.drawing",
                 (69, 20): "met2.drawing", (70, 20): "met3.drawing", (71, 20): "met4.drawing",
                 (72, 20): "met5.drawing"}


def run_controls() -> dict:
    """Known-answer controls on synthetic GDS fixtures written and read with
    the real klayout: union (no double counting), hierarchy, boundary
    clipping, empty layer, invalid grids, cumulative ratios over two levels,
    a zero-gate net, an ambiguous label set, and the drift gate itself."""
    import tempfile  # noqa: PLC0415

    results: list[dict] = []
    fixed_map = layer_map_from_table(FIXTURE_TABLE)
    with tempfile.TemporaryDirectory(prefix="physical-estimates-controls-") as tmp:
        tmp = Path(tmp)

        # --- density: union, hierarchy, clipping, empty layer -----------------
        # met1: two overlapping rects, union = 3x2 + (1..3)x(0..1) - shared
        # 2x1 = 6 um2. poly: one 2x1 rect in a child cell placed twice
        # disjoint = 2 x 2 um2 = 4 um2. met5 has no geometry at all (its GDS
        # layer is absent -> empty-layer handling).
        gds = tmp / "density.gds"
        write_fixture(
            gds,
            boxes={
                CONTROL_TOP: {"68/20": [(0.0, 0.0, 3.0, 2.0), (1.0, 0.0, 3.0, 1.0)]},
                "poly_cell": {"66/20": [(0.0, 10.0, 2.0, 11.0)]},
            },
            instances=[("poly_cell", CONTROL_TOP, 0.0, 0.0), ("poly_cell", CONTROL_TOP, 5.0, 0.0)],
        )
        import klayout.db as db  # noqa: PLC0415

        ly = db.Layout()
        ly.read(str(gds))
        cell = ly.cell(CONTROL_TOP)
        dbu = ly.dbu
        box = cell.bbox()
        bbox = (box.left * dbu, box.bottom * dbu, box.right * dbu, box.top * dbu)
        dens = density_pass(gds, CONTROL_TOP, fixed_map, dbu, bbox)
        rows = {r["name"]: r for r in dens["layers"]}
        results.append({
            "id": "1-density-union",
            "intent": "overlapping met1 rects union to exactly 6 um2 (no double counting); a child cell "
                      "placed twice counts both placements (poly 4 um2); absent met5 layer is the "
                      "empty-layer case (zero density, no error)",
            "expected": {"met1": 6.0, "poly": 4.0, "met5_empty": True},
            "observed": {"met1": rows["met1"]["drawn_area_um2"], "poly": rows["poly"]["drawn_area_um2"],
                         "met5_empty": rows["met5"]["empty_layer"]},
            "passed": abs(rows["met1"]["drawn_area_um2"] - 6.0) < 1e-9
                      and abs(rows["poly"]["drawn_area_um2"] - 4.0) < 1e-9
                      and rows["met5"]["empty_layer"] and rows["met5"]["density_max"] == 0.0,
        })
        # a 3x3 window at the lower-left corner: denominator 9 um2, met1 area
        # 6 um2 inside it -> density exactly 6/9
        dens3 = density_pass(gds, CONTROL_TOP, fixed_map, dbu, (0.0, 0.0, 3.0, 3.0))
        r3 = {r["name"]: r for r in dens3["layers"]}
        results.append({
            "id": "2-density-window",
            "intent": "one 3x3 window over a 9 um2 denominator: met1 density exactly 6/9; geometry "
                      "outside the boundary (poly at y=10) never leaks into the windows",
            "expected": {"met1_density_max": 6.0 / 9.0, "poly_density_max": 0.0},
            "observed": {"met1_density_max": r3["met1"]["density_max"],
                         "poly_density_max": r3["poly"]["density_max"]},
            "passed": abs(r3["met1"]["density_max"] - 6.0 / 9.0) < 1e-9 and r3["poly"]["density_max"] == 0.0,
        })
        # boundary clipping: bbox smaller than one window -> a single clipped
        # window whose denominator is the boundary area itself
        densc = density_pass(gds, CONTROL_TOP, fixed_map, dbu, (0.0, 0.0, 2.5, 1.0))
        rc = {r["name"]: r for r in densc["layers"]}
        results.append({
            "id": "3-density-clip",
            "intent": "a window larger than the boundary clips to the boundary (denominator 2.5 um2, one "
                      "window, none skipped, met1 fills it completely: density 1.0)",
            "expected": {"windows": 1, "skipped": 0, "met1_density_max": 1.0},
            "observed": {"windows": densc["windows_total"], "skipped": densc["windows_skipped"],
                         "met1_density_max": rc["met1"]["density_max"]},
            "passed": densc["windows_total"] == 1 and densc["windows_skipped"] == 0
                      and abs(rc["met1"]["density_max"] - 1.0) < 1e-9,
        })
        for window, stride in ((0.0, 1.0), (1.0, 0.0), (1.0, 2.0)):
            try:
                window_grid((0.0, 0.0, 10.0, 10.0), window, stride)
                caught, msg = False, "no error raised"
            except EstimateError as exc:
                caught, msg = True, str(exc)
            results.append({
                "id": f"4-invalid-grid-w{window}-s{stride}",
                "intent": f"invalid grid (window={window}, stride={stride}) is refused, not silently tiled",
                "expected": {"refused": True},
                "observed": {"error": msg},
                "passed": caught,
            })

        # --- antenna: known ratios, zero-gate net, ambiguous labels ----------
        # net n1: li1 1 um2 + met1 2 um2 (separate components: no mcon drawn,
        # which is itself the point -- per-level areas aggregate per NET, not
        # per component). net n2: li1 1 um2, zero known gates.
        gds2 = tmp / "antenna.gds"
        write_fixture(
            gds2,
            boxes={CONTROL_TOP: {"67/20": [(0.0, 0.0, 1.0, 1.0), (10.0, 0.0, 11.0, 1.0)],
                                 "68/20": [(0.0, 0.0, 2.0, 1.0)]}},
            texts={"67/5": [("n1", 0.5, 0.5), ("n2", 10.5, 0.5)], "68/5": [("n1", 1.5, 0.5)]},
        )
        extract = _fixture_extract([
            {"name": "$1", "class": "nfet", "nets": {"g": "n1"}, "params": {"w_um": 0.42, "l_um": 0.15}},
            {"name": "$2", "class": "pfet", "nets": {"g": "n1"}, "params": {"w_um": 0.84, "l_um": 0.15}},
            {"name": "$3", "class": "nfet", "nets": {"g": "n3"}, "params": {"w_um": 1.0, "l_um": 0.1}},
        ])
        gate = gate_areas_from_extract(extract)
        cond = conductor_pass(gds2, dbu)
        gate_sets = {g: set(g.split("|")) for g in gate["gate_area_um2"]}
        matches, amb, unm = match_gate_components(cond["component_tokens"], gate_sets)
        for i, comp in enumerate(cond["components"]):
            comp["gate_net"] = matches.get(i)
        gate_a = 0.42 * 0.15 + 0.84 * 0.15
        n1_areas = {lvl: sum(c["area_um2"][lvl] for i, c in enumerate(cond["components"])
                             if matches.get(i) == "n1") for lvl in LEVELS}
        ratios = antenna_ratios(n1_areas, gate["gate_area_um2"]["n1"])
        results.append({
            "id": "5-antenna-known",
            "intent": "two gates on one net: gate area 0.42*0.15 + 0.84*0.15; cumulative li1 ratio 1/ga, "
                      "met1 ratio (1+2)/ga; a zero-gate net (n2) is excluded and counted; a gate net with "
                      "no conductor geometry (n3) is excluded and listed",
            "expected": {"gate_area": gate_a, "li1": 1.0 / gate_a, "met1": 3.0 / gate_a,
                         "matched/amb/unmatched": "2/0/1"},
            "observed": {"gate_area": gate["gate_area_um2"]["n1"], "li1": ratios.get("li1"),
                         "met1": ratios.get("met1"),
                         "matched/amb/unmatched": f"{len(matches)}/{amb}/{unm}"},
            "passed": abs(gate["gate_area_um2"]["n1"] - gate_a) < 1e-12
                      and abs(ratios["li1"] - 1.0 / gate_a) < 1e-9
                      and abs(ratios["met1"] - 3.0 / gate_a) < 1e-9
                      and (len(matches), amb, unm) == (2, 0, 1),
        })
        m2, amb2, unm2 = match_gate_components(
            [{"x"}, {"n1"}, set()], {"n1": {"n1", "x"}, "n2": {"n2", "x"}})
        results.append({
            "id": "6-antenna-ambiguous",
            "intent": "a component carrying only a label shared by two gate nets (the vddr/vddr3/vddr4 "
                      "pattern) is ambiguous -- excluded and counted; a component with a unique label "
                      "still matches; an unlabeled component is counted separately",
            "expected": {"matched": 1, "ambiguous": 1, "unmatched": 0},
            "observed": {"matched": len(m2), "ambiguous": amb2, "unmatched": unm2},
            "passed": len(m2) == 1 and amb2 == 1 and unm2 == 0,
        })

        # --- drift gate -------------------------------------------------------
        doc = build_document(
            gds_rel="fixture.gds", gds_sha256="sha256:a", geometry_sha256="sha256:g",
            geometry_counts={"polygons": 3, "labels": 3, "layers": 3},
            extract_rel="fixture.json.gz", extract_sha256="sha256:e", extract_matches_gds=True,
            layer_map=fixed_map, layer_table_hash="sha256:t",
            klayout_version="test", bbox=(0.0, 0.0, 12.0, 12.0),
            gate=gate, components=cond | {"matched": len(matches), "ambiguous": amb, "unmatched": unm},
            density=dens,
        )
        same = drift(doc, doc)
        cases = []
        for label, mutate, expect_caught in (
            ("one density value nudged", lambda d: d["density"]["layers"][0].__setitem__(
                "density_max", d["density"]["layers"][0]["density_max"] + 1e-9), True),
            ("window parameter changed", lambda d: d["definitions"]["density"].__setitem__(
                "window_um", 50.0), True),
            ("a net's gate area changed", lambda d: d["antenna"]["nets"][0].__setitem__(
                "gate_area_um2", d["antenna"]["nets"][0]["gate_area_um2"] * 1.001), True),
            ("stale gate-source flag", lambda d: d["inputs"].__setitem__(
                "gate_source_matches_gds", False), True),
            ("provenance-only change", lambda d: d["provenance"].__setitem__(
                "klayout_version", "other"), False),
        ):
            edited = json.loads(json.dumps(doc))
            mutate(edited)
            d = drift(doc, edited)
            cases.append({"change": label, "caught": bool(d), "expected_caught": expect_caught,
                          "drift": d})
        results.append({
            "id": "7-drift",
            "intent": "drift is caught for density, parameter, gate-area and staleness changes; a "
                      "provenance-only change does not drift; unchanged reproduces",
            "expected": {"unchanged_reproduces": True, "per-case": [c["expected_caught"] for c in cases]},
            "observed": {"unchanged": same, "per-case": [c["caught"] for c in cases]},
            "passed": not same and all(c["caught"] == c["expected_caught"] for c in cases),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "issue": ISSUE,
        "not_signoff": NOT_SIGNOFF,
        "klayout_required": True,
        "all_passed": all(r["passed"] for r in results),
        "controls": results,
    }


def controls_markdown(summary: dict) -> str:
    lines = [
        "# Whole-block physical estimate controls (issue #283)",
        "",
        summary["not_signoff"],
        "",
        "Synthetic GDS fixtures written and read with the real pinned klayout (version recorded in the "
        "generating environment). These are calculator controls: they pin union, hierarchy, clipping, "
        "empty-layer, grid-validation, cumulative-ratio, zero-gate/ambiguous-accounting and drift "
        "behaviour with hand-computed expected values.",
        "",
        "| control | intent | passed |",
        "|---|---|---|",
    ]
    for r in summary["controls"]:
        lines.append(f"| `{r['id']}` | {r['intent']} | {'yes' if r['passed'] else '**NO**'} |")
    lines += ["", f"All passed: **{'yes' if summary['all_passed'] else 'NO'}**.", ""]
    return "\n".join(lines) + "\n"
