"""Library half of ``layout/bin/physical_estimates.py`` (issue #818): the
``klayout``-free, PDK-free pure-Python half of the whole-block metal/poly
density and naive antenna-ratio estimates (issue #283).

Everything here is stdlib work -- the artifact constants and the
``DEFINITIONS`` contract, the density window grid, the cumulative antenna
ratios, the label-subset gate-net attribution, the gate W*L accounting read
from the committed extraction, the deck layer-table resolution, the
``build_document`` / ``drift`` gate / Markdown rendering behind
``verify-whole.py check`` -- so ``layout/test_verify_whole.py`` exercises it
on the PR-blocking CI path with no ``klayout``, no ``klt`` and no PDK.
Nothing here imports ``klayout.db``, ``_gds_geometry``, ``_hashing`` or
``_klt_common``: the ``klayout.db`` geometry passes and the real-geometry
negative-control fixtures stay in the entry point
``layout/bin/physical_estimates.py``, which imports this module by name and
re-exports its public symbols so its ``PE.*`` callers are unchanged -- the
same seam ``verify_whole_lib.py`` (issue #173, extended by #495) and
``compose_whole_lib.py`` (issue #775) already cut.

Every number is still an **estimate for human review, never a foundry
sign-off**; the entry point's docstring says why the conductor side is a
flat extraction and why density is computed here at all.

The 16 definitions and their module constants moved verbatim out of
``physical_estimates.py``: a structural move only -- generated artifact
bytes, error messages and the ``generator`` string are unchanged.
"""

from __future__ import annotations

import math

SCHEMA_VERSION = 1
ISSUE = 283

# Conductor levels, in stack order (bottom-up). This is both the iteration
# order for cumulative antenna ratios and the row order of the density table.
LEVELS = ("li1", "met1", "met2", "met3", "met4", "met5")
DENSITY_LAYERS = ("poly",) + LEVELS
# _gds_geometry.py flat_extract's region keys for each conductor level.
FLAT_KEYS = {"li1": "li", "met1": "m1", "met2": "m2", "met3": "m3", "met4": "m4", "met5": "m5"}
# Deck layer-table names per counted layer (drawing datatypes only).
DECK_LAYER_NAMES = {"poly": "poly.drawing", "li1": "li1.drawing", "met1": "met1.drawing",
                    "met2": "met2.drawing", "met3": "met3.drawing", "met4": "met4.drawing",
                    "met5": "met5.drawing"}

# Density window parameters. The pinned curated deck defines no density rule
# and therefore no window size or stride; these values are a CHOICE, recorded
# as arbitrary in the artifact header -- they imply no foundry compliance.
WINDOW_UM = 100.0
STRIDE_UM = 100.0

JSON_NAME = "physical_estimates.json"
MD_NAME = "physical_estimates.md"
CONTROLS_JSON = "physical_estimates_controls.json"
CONTROLS_MD = "physical_estimates_controls.md"
CONTROL_TOP = "est_ctl"

NOT_SIGNOFF = (
    "Informational geometry estimates only -- NOT foundry sign-off. The pinned "
    "curated sky130 deck ships no density and no antenna rules, so no foundry "
    "window, threshold, runset or pass/fail stands behind any number here. "
    "Simulation- and extraction-derived estimates are provisional until silicon."
)

DEFINITIONS = {
    "density": {
        "quantity": "per-window drawn-area fraction of a layer: unioned geometry area inside the window / "
                    "clipped window area inside the boundary",
        "counted_layers": "poly, li1 and met1..met5 DRAWING layer/datatypes, resolved through the pinned deck "
                          "layer table (inputs.layer_map); pin, label and marker datatypes are not counted",
        "geometry": "unioned, hierarchy- and transform-flattened shapes of the layer under the top cell: "
                    "overlaps and repeated instances are counted once",
        "boundary": "the top cell's bounding box (density.boundary)",
        "window_um": WINDOW_UM,
        "stride_um": STRIDE_UM,
        "window_provenance": "ARBITRARY choice: the pinned curated deck has no density rule and no window "
                             "dimensions (see drc_coverage_audit.json), so nothing foundry-defined is implied. "
                             "Tiles run row-major from the boundary's lower-left corner and are clipped at the "
                             "boundary",
        "denominator": "the window's own area inside the boundary, so a partial window at the boundary edge is "
                       "judged against the area it actually has; zero-area windows are skipped and counted, "
                       "never divided by",
        "grid_validation": "the computation refuses window_um <= 0, stride_um <= 0 and stride_um > window_um",
    },
    "antenna": {
        "quantity": "naive cumulative antenna ratio per electrical net and level: (sum of li1..level conductor "
                    "area attributed to the net) / (summed MOS gate W*L on that net)",
        "levels": list(LEVELS),
        "ratio_convention": "cumulative from li1 upward is the primary, emitted ratio; the per-level areas "
                            "themselves are committed too, so any other convention is re-derivable from the "
                            "same artifact",
        "conductor_source": "a flat li1/met1..met5 + mcon/via connectivity extraction of the committed GDS "
                            "(compose-whole.py flat_extract: metal-level connectivity only, no device "
                            "recognition). A conductor component is attributed to a gate net only when every "
                            "label it carries is in that gate net's label set and in no other gate net's; "
                            "everything else is excluded and counted",
        "gate_source": "the committed klt extraction extract.json.gz: each analog MOSFET's gate net (named by "
                       "its own label set) and its params w_um * l_um",
        "gate_area": "W*L summed per gate net, um2; only the analog (non-abstracted) devices' gates are known",
        "digital_exclusion": "every gate inside the abstracted digital standard cells is EXCLUDED -- "
                             "cell-internal gate geometry does not exist in the committed extraction. The "
                             "exclusion is reported against a defined denominator (placed device-bearing "
                             "instances: analog devices + abstracted instances), never an invented area "
                             "fraction; see coverage.gate_area.digital_exclusion",
        "zero_gate_nets": "a conductor component whose only candidate net has zero known gate area is EXCLUDED "
                          "from the ratios and COUNTED; a zero-gate net never produces an infinite ratio or a "
                          "pass",
        "unmatched_gate_nets": "a gate net with no attributable conductor component is listed and excluded "
                               "(its metal cannot be identified by label alone)",
        "not_modelled": ["process sequencing (a real antenna rule applies per process step, not to the finished "
                         "stack)", "diode relief", "side-wall / perimeter conductor area",
                         "foundry threshold values"],
        "verdict": "none: ratios are estimates for human review; there is no pass/fail against any foundry "
                   "antenna rule anywhere in this artifact",
    },
}


class EstimateError(RuntimeError):
    """A definition- or input-level refusal (bad grid, missing layer mapping)."""


# --------------------------------------------------------------------------
# pure logic (no klayout): grid, ratios, matching, gate areas
# --------------------------------------------------------------------------


def validate_grid(window_um: float, stride_um: float) -> None:
    if not (window_um > 0):
        raise EstimateError(f"window_um must be > 0, got {window_um!r}")
    if not (stride_um > 0):
        raise EstimateError(f"stride_um must be > 0, got {stride_um!r}")
    if stride_um > window_um:
        raise EstimateError(f"stride_um {stride_um!r} must not exceed window_um {window_um!r} "
                            "(windows tile the boundary without gaps)")


def window_grid(bbox: tuple[float, float, float, float], window_um: float,
                stride_um: float) -> tuple[list[dict], int]:
    """Tiled windows over *bbox* (left, bottom, right, top), row-major from the
    lower-left corner, clipped to the boundary. Returns (windows, skipped)
    where each window is {ix, iy, left, bottom, right, top, area} and
    *skipped* counts tiles with zero clipped area (fully outside)."""
    validate_grid(window_um, stride_um)
    left, bottom, right, top = bbox
    nx = max(0, math.ceil(round((right - left) / stride_um, 9)))
    ny = max(0, math.ceil(round((top - bottom) / stride_um, 9)))
    windows, skipped = [], 0
    for iy in range(ny):
        for ix in range(nx):
            w = (left + ix * stride_um, bottom + iy * stride_um,
                 min(left + ix * stride_um + window_um, right),
                 min(bottom + iy * stride_um + window_um, top))
            area = max(0.0, w[2] - w[0]) * max(0.0, w[3] - w[1])
            if area <= 0:
                skipped += 1
                continue
            windows.append({"ix": ix, "iy": iy, "left": w[0], "bottom": w[1],
                            "right": w[2], "top": w[3], "area": area})
    return windows, skipped


def window_density(geometry_area: float, window_area: float) -> float | None:
    """Drawn-area fraction of one window; None where the window has no area
    (never divide by zero)."""
    if window_area <= 0:
        return None
    return geometry_area / window_area


def cumulative_areas(level_areas: dict[str, float]) -> dict[str, float]:
    """Bottom-up running sum over LEVELS (unknown keys ignored)."""
    out, run = {}, 0.0
    for level in LEVELS:
        run += float(level_areas.get(level, 0.0))
        out[level] = run
    return out


def antenna_ratios(level_areas: dict[str, float], gate_area: float) -> dict[str, float]:
    """Cumulative conductor area / gate area per level. An empty dict for a
    zero-gate net: the caller excludes and counts it instead of dividing."""
    if gate_area <= 0:
        return {}
    return {k: v / gate_area for k, v in cumulative_areas(level_areas).items()}


def split_labels(name: str, separator: str) -> set[str]:
    """A net's label tokens: split on *separator*, drop the klt anonymous
    `\\$N` escapes and empties. Extract-net names join labels with '|', flat
    conductor components with ','."""
    return {t for t in name.replace("\\", "").split(separator) if t and not t.startswith("$")}


def match_gate_components(component_tokens: list[set[str]],
                          gate_sets: dict[str, set[str]]) -> tuple[dict[int, str], int, int]:
    """Attribute flat conductor components to gate nets by label subset.

    Component *i* maps to gate net *g* iff ``component_tokens[i] <= gate_sets[g]``
    and no other gate net's label set is also a superset. Returns
    (matches {component index: gate net}, ambiguous components, labeled
    components matching no gate net). Zero-gate accounting is the caller's:
    only gate nets reach this function, so a labeled component matching none
    of them lands in the third return value either because its net has no
    known gates or because its labels are shared -- both are counted, never
    guessed apart.
    """
    matches: dict[int, str] = {}
    ambiguous = unmatched = 0
    for i, toks in enumerate(component_tokens):
        if not toks:
            continue
        hits = [g for g, s in gate_sets.items() if toks <= s]
        if len(hits) == 1:
            matches[i] = hits[0]
        elif len(hits) > 1:
            ambiguous += 1
        else:
            unmatched += 1
    return matches, ambiguous, unmatched


def gate_areas_from_extract(extract: dict) -> dict:
    """Pure gate-side inputs from the committed extraction: gate W*L per gate
    net (label-set string), plus the counts the coverage section reports.
    analog_devices counts only devices with usable w/l (the gate-W*L-known
    denominator); a device without params is counted in
    devices_missing_params and still registers its gate net with zero known
    area -- a net is never silently dropped because one device lacked params."""
    areas: dict[str, float] = {}
    devices_per_net: dict[str, int] = {}
    missing = 0
    analog = 0
    for dev in extract.get("devices") or []:
        params = dev.get("params") or {}
        g = dev["nets"]["g"].replace("\\", "")
        devices_per_net[g] = devices_per_net.get(g, 0) + 1
        w, l = params.get("w_um"), params.get("l_um")
        if w is None or l is None:
            missing += 1
            areas.setdefault(g, 0.0)
            continue
        analog += 1
        areas[g] = areas.get(g, 0.0) + float(w) * float(l)
    abstracted = extract.get("abstracted_cells") or []
    instances = sum(int(c.get("instance_count", 0)) for c in abstracted)
    return {
        "gate_area_um2": areas,
        "devices_per_gate_net": devices_per_net,
        "analog_devices": analog,
        "devices_missing_params": missing,
        "abstracted_instances": instances,
        "abstracted_cell_types": len(abstracted),
    }


def layer_map_from_table(table: dict[tuple[int, int], str]) -> dict[str, tuple[int, int]]:
    """Resolve every counted layer's drawing datatype through the deck layer
    table. A missing or ambiguous mapping is a definition failure, not a zero."""
    out = {}
    for name in DENSITY_LAYERS:
        hits = [ld for ld, n in table.items() if n == DECK_LAYER_NAMES[name]]
        if len(hits) != 1:
            raise EstimateError(f"deck layer table has {len(hits)} entries for {DECK_LAYER_NAMES[name]}; "
                                "refusing to guess the drawing datatype")
        out[name] = hits[0]
    return out


# --------------------------------------------------------------------------
# document assembly (pure): build, drift, markdown
# --------------------------------------------------------------------------


def build_document(*, gds_rel: str, gds_sha256: str, geometry_sha256: str, geometry_counts: dict,
                   extract_rel: str, extract_sha256: str, extract_matches_gds: bool,
                   layer_map: dict[str, tuple[int, int]], layer_table_hash: str,
                   klayout_version: str, bbox: tuple[float, float, float, float],
                   gate: dict, components: dict, density: dict) -> dict:
    """Assemble the committed-artifact document from computed parts. Pure."""
    matched_nets: dict[str, list[dict]] = {}
    for comp in components["components"]:
        if comp.get("gate_net"):
            matched_nets.setdefault(comp["gate_net"], []).append(comp)

    nets, unmatched_gate_nets = [], []
    for g, area in gate["gate_area_um2"].items():
        comps = matched_nets.get(g, [])
        areas = {lvl: round(sum(c["area_um2"][lvl] for c in comps), 9) for lvl in LEVELS}
        ratios = antenna_ratios(areas, area)
        entry = {
            "net": g,
            "gate_area_um2": round(area, 9),
            "gate_devices": gate["devices_per_gate_net"].get(g, 0),
            "components": len(comps),
            "area_um2": areas,
            "cumulative_ratio": {k: round(v, 6) for k, v in ratios.items()},
        }
        if comps:
            nets.append(entry)
        else:
            unmatched_gate_nets.append(g)
    nets.sort(key=lambda e: (-e["cumulative_ratio"].get(LEVELS[-1], 0.0), e["net"]))

    worst = []
    for lvl in LEVELS:
        rated = sorted(((e["cumulative_ratio"][lvl], e["net"]) for e in nets if lvl in e["cumulative_ratio"]),
                       reverse=True)
        worst.append({"level": lvl, "nets_rated": len(rated),
                      "worst_ratio": round(rated[0][0], 6) if rated else None,
                      "worst_net": rated[0][1] if rated else None})

    attributed = {lvl: sum(e["area_um2"][lvl] for e in nets) for lvl in LEVELS}
    zero_area_listed = [e["net"] for e in nets if not e["cumulative_ratio"]]
    drawn = density["drawn_area_um2_by_level"]
    denom = gate["analog_devices"] + gate["abstracted_instances"]
    return {
        "schema_version": SCHEMA_VERSION,
        "issue": ISSUE,
        "not_signoff": NOT_SIGNOFF,
        "generator": "layout/bin/verify-whole.py estimates (layout/bin/physical_estimates.py)",
        "definitions": DEFINITIONS,
        "inputs": {
            "gds": gds_rel,
            "gds_sha256": gds_sha256,
            "gds_geometry_sha256": geometry_sha256,
            "gds_geometry": geometry_counts,
            "gate_source": extract_rel,
            "gate_source_sha256": extract_sha256,
            "gate_source_matches_gds": extract_matches_gds,
            "layer_map": {name: f"{ld[0]}/{ld[1]}" for name, ld in layer_map.items()},
            "layer_map_source": "klayout_tools.decks sky130 layer table; the resolved mapping above is "
                                "drift-compared key by key (the deck module hash that produced it is "
                                "recorded under provenance, because the installed klt build churns "
                                "between sessions while the mapping itself stays stable)",
            "top": density["top"],
        },
        "density": {
            "boundary": {"source": "top-cell bounding box", "left": bbox[0], "bottom": bbox[1],
                         "right": bbox[2], "top": bbox[3],
                         "area_um2": round(max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1]), 9)},
            "grid": {"window_um": WINDOW_UM, "stride_um": STRIDE_UM, "arbitrary": True},
            "windows_total": density["windows_total"],
            "windows_skipped_zero_area": density["windows_skipped"],
            "layers": density["layers"],
        },
        "antenna": {
            "ratios_by_level": worst,
            "nets": nets,
            "gate_nets_without_conductor_geometry": unmatched_gate_nets,
        },
        "coverage": {
            "gate_area": {
                "analog_devices": gate["analog_devices"],
                "devices_missing_params": gate["devices_missing_params"],
                "distinct_gate_nets": len(gate["gate_area_um2"]),
                "gate_nets_rated": len(nets) - len(zero_area_listed),
                "gate_nets_listed_zero_known_area": len(zero_area_listed),
                "gate_nets_without_conductor_geometry": len(unmatched_gate_nets),
                "known_gate_area_um2": round(sum(gate["gate_area_um2"].values()), 9),
                "digital_exclusion": {
                    "abstracted_instances": gate["abstracted_instances"],
                    "abstracted_cell_types": gate["abstracted_cell_types"],
                    "device_bearing_instances": denom,
                    "known_gate_area_fraction_of_instances":
                        round(gate["analog_devices"] / denom, 6) if denom else None,
                    "statement": "gate W*L is known only for the analog devices; every gate inside the "
                                 f"{gate['abstracted_instances']} abstracted digital instances is excluded. The "
                                 "denominator is the count of placed device-bearing instances the extraction "
                                 "saw (analog + abstracted), not an invented area fraction",
                },
            },
            "conductor_components": {
                "flat_nets_total": components["flat_nets_total"],
                "labeled": components["labeled"],
                "unlabeled": components["unlabeled"],
                "matched_to_gate_nets": components["matched"],
                "ambiguous": components["ambiguous"],
                "labeled_matching_no_gate_net": components["unmatched"],
                "attributed_area_fraction_by_level": {
                    lvl: (round(attributed[lvl] / drawn[lvl], 6) if drawn[lvl] else None) for lvl in LEVELS
                },
                "statement": "only conductor components whose entire label set belongs to one gate net are "
                             "attributed; the attributed-area fractions above quantify how much drawn metal "
                             "per level that covers. The rest belongs to nets without analog gates or to "
                             "geometry whose labels are shared between nets -- excluded, not guessed",
            },
        },
        "provenance": {
            "klayout_version": klayout_version,
            "deck_layer_table_module_sha256": layer_table_hash,
            "note": "informational; excluded from the drift comparison by design (a tool change that moves "
                    "the numbers shows up as drift in the values themselves; the resolved layer map in "
                    "inputs IS compared)",
        },
    }


def _brief_net(entry: dict | None) -> str:
    if entry is None:
        return "absent"
    return (f"gate={entry['gate_area_um2']} comps={entry['components']} "
            f"met5ratio={entry['cumulative_ratio'].get(LEVELS[-1])}")


def drift(committed: dict, fresh: dict) -> list[str]:
    """Human-readable differences between two estimate documents (empty:
    none). `provenance` is excluded by design (see its own note); everything
    else -- definitions, inputs, hashes, grid, per-layer and per-net values,
    coverage -- must reproduce byte-stable in the pinned environment."""
    if committed.get("schema_version") != fresh.get("schema_version"):
        return [f"schema_version {committed.get('schema_version')} -> {fresh.get('schema_version')}"]
    out = []
    for key in sorted(set(committed) | set(fresh)):
        if key == "provenance" or committed.get(key) == fresh.get(key):
            continue
        if key in ("density", "antenna", "coverage", "definitions", "inputs"):
            out.extend(_sub_drift(key, committed.get(key) or {}, fresh.get(key) or {}))
        else:
            out.append(f"{key} differs")
    return out


def _sub_drift(section: str, a: dict, b: dict) -> list[str]:
    out = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) == b.get(key):
            continue
        if section == "antenna" and key == "nets":
            old = {e["net"]: e for e in a.get(key) or []}
            new = {e["net"]: e for e in b.get(key) or []}
            for net in sorted(set(old) | set(new)):
                if old.get(net) != new.get(net):
                    out.append(f"antenna.nets[{net[:48]}]: {_brief_net(old.get(net))} -> {_brief_net(new.get(net))}")
        elif section == "density" and key == "layers":
            old = {e["name"]: e for e in a.get(key) or []}
            new = {e["name"]: e for e in b.get(key) or []}
            for name in sorted(set(old) | set(new)):
                if old.get(name) != new.get(name):
                    o, n = old.get(name), new.get(name)
                    out.append(f"density.layers[{name}]: "
                               f"{o['density_max'] if o else 'absent'} -> {n['density_max'] if n else 'absent'}")
        else:
            out.append(f"{section}.{key} differs")
    return out


def _short_net(name: str, limit: int = 56) -> str:
    """Distinguishing short form for a pipe-joined net label set: sibling nets
    in this block differ at the END of their label list (vddr3 vs vddr4), so a
    plain prefix cut would render them identically."""
    if len(name) <= limit:
        return name
    head, tail = limit * 2 // 3, limit // 3
    return name[:head] + ".." + name[-tail:]


def markdown(doc: dict) -> str:
    """The committed human-readable rendering, generated from the document
    (never hand-edited: `verify-whole.py check` regenerates and compares)."""
    d, a, c = doc["density"], doc["antenna"], doc["coverage"]
    b = d["boundary"]
    lines = [
        "# Whole-block physical estimates (issue #283)",
        "",
        f"**{doc['not_signoff']}**",
        "",
        "## Definitions (part of the artifact's contract)",
        "",
    ]
    for section in ("density", "antenna"):
        lines += [f"### {section}", ""]
        for k, v in doc["definitions"][section].items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")
    lines += [
        "## Density",
        "",
        f"Boundary: top-cell bbox ({b['left']}, {b['bottom']}) .. ({b['right']}, {b['top']}) um, "
        f"{b['area_um2']} um2. Grid: {d['grid']['window_um']} um x {d['grid']['stride_um']} um tiles "
        f"(arbitrary choice -- see definitions), {d['windows_total']} counted windows, "
        f"{d['windows_skipped_zero_area']} skipped as zero-area. Denominator is the clipped window area "
        "inside the boundary. No threshold is applied: a density number here is not a density-rule verdict.",
        "",
        "| layer | drawn um2 | whole-block density | windows | density min | max | mean |",
        "|---|---|---|---|---|---|---|",
    ]
    for lay in d["layers"]:
        note = " (empty layer)" if lay["empty_layer"] else ""
        lines.append(
            f"| `{lay['name']}` ({lay['gds']}){note} | {lay['drawn_area_um2']:.3f} | "
            f"{lay['whole_block_density']:.6f} | {lay['windows_counted']} | "
            f"{lay['density_min']:.6f} | {lay['density_max']:.6f} | {lay['density_mean']:.6f} |"
        )
    lines += [
        "",
        "## Naive antenna ratios",
        "",
        "Cumulative conductor area / gate W*L per net and level. Estimates only: process sequencing, "
        "diode relief, side-wall area and foundry thresholds are not modelled, and there is no pass/fail "
        "here.",
        "",
        "| level | nets rated | worst ratio | worst net |",
        "|---|---|---|---|",
    ]
    for w in a["ratios_by_level"]:
        ratio = "-" if w["worst_ratio"] is None else f"{w['worst_ratio']:.2f}"
        net = "-" if w["worst_net"] is None else "`" + _short_net(w["worst_net"]) + "`"
        lines.append(f"| `{w['level']}` | {w['nets_rated']} | {ratio} | {net} |")
    lines += [
        "",
        f"Worst nets by cumulative {LEVELS[-1]} ratio (of {len(a['nets'])} rated):",
        "",
        "| net | gate um2 | gates | components | cumulative ratio per level |",
        "|---|---|---|---|---|",
    ]
    for e in a["nets"][:8]:
        rr = " ".join(f"{lvl}={e['cumulative_ratio'][lvl]:.1f}" for lvl in LEVELS
                      if lvl in e["cumulative_ratio"])
        lines.append(f"| `{_short_net(e['net'])}` | {e['gate_area_um2']:.3f} | {e['gate_devices']} | "
                     f"{e['components']} | {rr} |")
    ga, cc = c["gate_area"], c["conductor_components"]
    de = ga["digital_exclusion"]
    fracs = ", ".join(f"{lvl}={cc['attributed_area_fraction_by_level'][lvl]}" for lvl in LEVELS)
    lines += [
        "",
        "## Coverage and exclusions",
        "",
        f"- Gate W*L known for {ga['analog_devices']} analog devices over {ga['distinct_gate_nets']} gate "
        f"net(s), {ga['known_gate_area_um2']} um2 total; {ga['devices_missing_params']} device(s) lacked "
        "params and are counted, not dropped.",
        f"- Digital exclusion: all gates inside {de['abstracted_instances']} abstracted standard-cell "
        f"instances ({de['abstracted_cell_types']} cell types) are excluded -- "
        f"{de['known_gate_area_fraction_of_instances']} of {de['device_bearing_instances']} placed "
        f"device-bearing instances have known gate area. Gate-net side: {ga['gate_nets_rated']} rated, "
        f"{ga['gate_nets_listed_zero_known_area']} listed with zero known gate area (never rated, never "
        f"infinite), {ga['gate_nets_without_conductor_geometry']} with no attributable conductor geometry "
        "(listed in the JSON).",
        f"- Conductor side: {cc['flat_nets_total']} flat components, {cc['labeled']} labeled, "
        f"{cc['matched_to_gate_nets']} attributed to a gate net, {cc['ambiguous']} ambiguous (label set "
        f"shared between gate nets), {cc['labeled_matching_no_gate_net']} labeled but matching no gate net, "
        f"{cc['unlabeled']} unlabeled. Attributed-area fraction per level: {fracs}.",
        "",
        "## Regeneration",
        "",
        "```",
        "python3 layout/bin/verify-whole.py estimates   # regenerate both files",
        "python3 layout/bin/verify-whole.py check       # drift gate (fails on any difference)",
        "```",
        "",
        "Both files are generated from one document; neither is hand-edited.",
        "",
    ]
    return "\n".join(lines)
