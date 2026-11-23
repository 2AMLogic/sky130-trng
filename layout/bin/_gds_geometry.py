#!/usr/bin/env python3
"""Shared GDS geometry helpers for the whole-block toolchain (issue #613).

Four functions -- :func:`flat_extract`, :func:`net_labels`, :func:`probe` and
:func:`canonical_geometry_hash` -- plus the private layer tables they read,
extracted verbatim from ``layout/bin/compose-whole.py`` (issue #172), where
they were the entire shared interface between the composer and its two
consumers. Before this module, ``verify-whole.py`` and
``physical_estimates.py`` each loaded the 1,700-line composition CLI by
filename with ``importlib.util.spec_from_file_location`` (under two different
module names, so one ``physical_estimates.compute()`` that hashes the GDS and
then runs the conductor pass executed the CLI twice and got two distinct
module objects). Direct imports of this module give every consumer one
extraction implementation and one geometry hash while the CLI keeps its
command-line entry point and its lazy ``klayout.db`` import (via
``_klt_common.klayout_db``).

Import it the way ``_hashing`` / ``_klt_common`` are imported -- put this
file's directory on ``sys.path`` and import by bare module name::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))      # elsewhere
    from _gds_geometry import flat_extract, net_labels, probe, canonical_geometry_hash  # noqa: E402
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klt_common import klayout_db as _klayout  # noqa: E402

_STACK = (
    ("li", (67, 20)),
    ("mcon", (67, 44)),
    ("m1", (68, 20)),
    ("v1", (68, 44)),
    ("m2", (69, 20)),
    ("v2", (69, 44)),
    ("m3", (70, 20)),
    ("v3", (70, 44)),
    ("m4", (71, 20)),
    ("v4", (71, 44)),
    ("m5", (72, 20)),
)
_LABEL_LAYER = {
    "li": (67, 5),
    "m1": (68, 5),
    "m2": (69, 5),
    "m3": (70, 5),
    "m4": (71, 5),
    "m5": (72, 5),
}


def flat_extract(gds_path: Path):
    """Metal-stack connectivity of a GDS, flattened. Returns (db, l2n, regions).

    Connectivity is li1/mcon/met1/via/met2/via2/met3/via3/met4/via4/met5 plus
    the pin-label layers of each metal; there is no device extraction and no
    substrate/well model, so this proves *metal-level* terminal connectivity
    and label identity only (it is not LVS and does not stand in for it).
    """
    db = _klayout()
    layout = db.Layout()
    layout.read(str(gds_path))
    top = layout.top_cell()
    top.flatten(True)
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))
    regions = {}
    for key, (num, dt) in _STACK:
        if layout.find_layer(num, dt) is not None:
            regions[key] = l2n.make_layer(layout.layer(num, dt), key)
    for lower, upper in zip(_STACK, _STACK[1:]):
        if lower[0] in regions and upper[0] in regions:
            l2n.connect(regions[lower[0]], regions[upper[0]])
    for key in regions:
        l2n.connect(regions[key])
    for key, (num, dt) in _LABEL_LAYER.items():
        if key in regions and layout.find_layer(num, dt) is not None:
            text = l2n.make_text_layer(layout.layer(num, dt), "t_" + key)
            l2n.connect(regions[key], text)
    l2n.extract_netlist()
    return db, l2n, regions


def net_labels(net) -> set[str]:
    return {tok for tok in re.split(r"[,|]", net.expanded_name()) if tok}


def probe(db, l2n, regions, layer_key: str, x_um: float, y_um: float):
    """The extracted net under a point on one metal layer, or None."""
    if layer_key not in regions:
        return None
    return l2n.probe_net(regions[layer_key], db.DPoint(x_um, y_um))


def canonical_geometry_hash(gds_path: Path) -> tuple[str, dict]:
    """Order- and timestamp-independent hash of a GDS stream's drawn geometry.

    For every (layer, datatype): the merged flat polygons, sorted; plus every
    text label (layer, datatype, string, position), sorted. The GDS header's
    timestamps and the cell/instance ordering of the stream do not enter it.
    Returns (hash, {"polygons": N, "labels": N, "layers": N}).
    """
    db = _klayout()
    layout = db.Layout()
    layout.read(str(gds_path))
    top = layout.top_cell()
    digest = hashlib.sha256()
    n_poly = n_lab = n_layers = 0
    infos = sorted(
        (layout.get_info(i).layer, layout.get_info(i).datatype, i)
        for i in layout.layer_indexes()
    )
    for num, dt, idx in infos:
        region = db.Region(top.begin_shapes_rec(idx))
        region.merge()
        polys = sorted(poly.to_s() for poly in region.each())
        labels = []
        for it in top.begin_shapes_rec(idx):
            shape = it.shape()
            if shape.is_text():
                point = it.trans().trans(db.Point(shape.text.trans.disp))
                labels.append(f"{shape.text_string}@{point.x},{point.y}")
        labels.sort()
        if not polys and not labels:
            continue
        n_layers += 1
        n_poly += len(polys)
        n_lab += len(labels)
        digest.update(f"L{num}/{dt}\n".encode())
        for poly in polys:
            digest.update(poly.encode() + b"\n")
        for label in labels:
            digest.update(b"T" + label.encode() + b"\n")
    return "sha256:" + digest.hexdigest(), {
        "polygons": n_poly,
        "labels": n_lab,
        "layers": n_layers,
    }
