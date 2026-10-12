#!/usr/bin/env python3
"""Whole-block power-grid extraction / static IR evidence (issue #174).

Runs ``klt power`` over the committed composed ``layout/trng_whole/trng_whole.gds``
(top ``trng_whole``) with a spec derived from three declared sources:

* stackup / via resistances: the sky130A magic tech file
  (``~/.volare/sky130A/libs.tech/magic/sky130A.tech`` ``extract`` section:
  li 12.8, met1/met2 0.125, met3/met4 0.047, met5 0.029 ohm/sq; mcon 9.3,
  via 4.5, via2 3.41, via3 3.41, via4 0.38 ohm);
* supply pads: the boundary pad table in ``layout/trng_whole/interface.json``;
* li1/mcon are DELIBERATELY OMITTED from the stackup: with li1 declared,
  ``klt power`` cannot decompose the whole-block li1 polygons (4096-mesh-cell
  cap) and every island comes back unsolved. Omitting li1 models the met1-met5
  grid only (cell-internal li1 straps and mcon are not in the network), so the
  result is a met1+ grid droop, NOT a full-stack one; this is recorded as a
  scope limit.
* loads: ONLY the four ring-supply loads, taken from a stated assumption --
  DR-0003's measured per-ring running supply current maximum
  (20.55 uA, ff / -40 C / 1.98 V). Logic-supply (``vdd``/``vss``) loads are
  NOT modelled: the whole-block transistor-level transient that would supply
  them did not complete (see the record), so that coverage stays Unmet.

Digital-macro rails ``VPWR``/``VGND`` are requested too; ``klt power`` reports
them unsolved (decomposition cap) and this script records that verbatim.

Usage: run-ir.py OUTDIR      (writes OUTDIR/spec.json, OUTDIR/response.json)
"""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GDS = REPO / "layout" / "trng_whole" / "trng_whole.gds"
IFACE = REPO / "layout" / "trng_whole" / "interface.json"

RING_I_A = 20.55e-6   # DR-0003: per-ring running current max (ff/-40C/1.98V)
VDD_NOM = 1.8


def spec() -> dict:
    iface = json.loads(IFACE.read_text())
    pads_by = {n["whole_block_pin"]: n["boundary_pad"] for n in iface["whole_block_nets"]
               if n.get("boundary_pad")}
    nets = ["vdd", "vss", "vddr1", "vddr2", "vddr3", "vddr4", "VPWR", "VGND"]
    pads = []
    for pin in ("vdd", "vss", "vddr1", "vddr2", "vddr3", "vddr4"):
        p = pads_by[pin]
        pads.append({"name": f"pad_{pin}", "net": pin, "x_um": p["x_um"], "y_um": p["y_um"],
                     "voltage_v": 0.0 if pin == "vss" else VDD_NOM})
    return {
        "power_nets": nets,
        "stackup": [
            {"name": "met1", "layer": "68/20", "label_layer": "68/5", "sheet_resistance_ohm_per_sq": 0.125},
            {"name": "met2", "layer": "69/20", "label_layer": "69/5", "sheet_resistance_ohm_per_sq": 0.125},
            {"name": "met3", "layer": "70/20", "label_layer": "70/5", "sheet_resistance_ohm_per_sq": 0.047},
            {"name": "met4", "layer": "71/20", "label_layer": "71/5", "sheet_resistance_ohm_per_sq": 0.047},
            {"name": "met5", "layer": "72/20", "label_layer": "72/5", "sheet_resistance_ohm_per_sq": 0.029},
        ],
        "vias": [
            {"name": "via", "layer": "68/44", "between": ["met1", "met2"], "resistance_ohm": 4.5},
            {"name": "via2", "layer": "69/44", "between": ["met2", "met3"], "resistance_ohm": 3.41},
            {"name": "via3", "layer": "70/44", "between": ["met3", "met4"], "resistance_ohm": 3.41},
            {"name": "via4", "layer": "71/44", "between": ["met4", "met5"], "resistance_ohm": 0.38},
        ],
        "pads": pads,
    }


def node_centroid(resp: dict, net: str) -> tuple[float, float]:
    for n in resp["networks"]:
        if n["net"] == net:
            nodes = [v for i in n["islands"] for v in i["nodes"]]
            return (sum(v["x_um"] for v in nodes) / len(nodes),
                    sum(v["y_um"] for v in nodes) / len(nodes))
    raise KeyError(net)


def klt_power(spec_path: Path) -> dict:
    out = subprocess.run(["klt", "power", str(GDS), str(spec_path), "--top", "trng_whole",
                          "--format", "json"], capture_output=True, text=True)
    # exit 4 = EM verdict "not_checked" (no current limits declared): benign here
    if out.returncode not in (0, 4):
        raise SystemExit(f"klt power failed rc={out.returncode}: {out.stderr[-500:]}")
    return json.loads(out.stdout)


def main(argv: list[str]) -> int:
    outdir = Path(argv[1]).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    s = spec()
    p0 = outdir / "spec.pads-only.json"
    p0.write_text(json.dumps(s, indent=2) + "\n")
    base = klt_power(p0)       # pads only: degenerate check + island census
    # ring loads at each ring island's node centroid
    s2 = json.loads(json.dumps(s))
    s2["current_model"] = {"supply_net": "vdd", "ground_net": "vss", "instances": [
        {"name": f"ring{k}_assumed", "x_um": round(node_centroid(base, f"vddr{k}")[0], 3),
         "y_um": round(node_centroid(base, f"vddr{k}")[1], 3), "current_a": RING_I_A,
         "supply_net": f"vddr{k}", "ground_net": "vss"} for k in (1, 2, 3, 4)]}
    p1 = outdir / "spec.ring-loads.json"
    p1.write_text(json.dumps(s2, indent=2) + "\n")
    solved = klt_power(p1)
    for name, doc in (("response.pads-only.json.gz", base), ("response.ring-loads.json.gz", solved)):
        with gzip.GzipFile(outdir / name, "wb", mtime=0) as fh:   # ~25 MB plain; gzip is the committed form
            fh.write((json.dumps(doc, indent=1) + "\n").encode())
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    summary = {
        "gds": str(GDS.relative_to(REPO)), "gds_sha256": sha(GDS), "top": "trng_whole",
        "specs": {p.name: sha(p) for p in (p0, p1)},
        "ring_current_a_assumed": RING_I_A,
        "ring_current_source": "DR-0003 max per-ring running supply current (ff/-40C/1.98V), NOT a whole-block measurement",
        "islands": {n["net"]: [{k: i[k] for k in ("island_id", "node_count", "edge_count", "unsolved_reason")}
                               for i in n["islands"]] for n in solved["networks"]},
        "worst_case_droop_mv": solved.get("worst_case_droop_mv"),
        "ir_drop_nets": [{k: v for k, v in n.items() if k != "islands"} | {
            "islands": [{k: i.get(k) for k in ("island_id", "solved", "unsolved_reason", "worst_droop_mv", "worst_node", "total_current_a")}
                        for i in n.get("islands", [])]}
                         for n in (solved.get("ir_drop_map") or {}).get("nets", [])],
        "em_verdict_status": (solved.get("em_verdict") or {}).get("status"),
        "klt_status": solved.get("status"),
        "warnings_unsolved": [w for w in solved.get("warnings", []) if "unsolved" in w],
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("worst_case_droop_mv", "em_verdict_status", "klt_status")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
