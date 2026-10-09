#!/usr/bin/env python3
"""Derive layout/trng_digital/erc-supply-spec.json from the committed routed
GDS and pnr.json (issue #223).  Nothing here is carried over from the analog
sampler_core spec: the stackup comes from the layers the routed GDS actually
draws, the supplies from pnr.json's power block, and the substrate-tie boxes
from the p-tap geometry in the GDS.

Cold-start (needs the `klayout` Python module, same 0.30.12 klt records):

    uv run --no-project --with klayout==0.30.12 python -I \
        layout/trng_digital/erc-gen-supply-spec.py

It cross-checks, and refuses to write the spec if any check fails:
  * every pnr.json power.straps[].layer is a stackup role of the spec;
  * every routed metal layer present in the DEF's special nets is a role;
  * pnr.json placed.tapcells == DEF tap component count == n-tap count ==
    p-tap count in the GDS (all taps come from the tapcell master);
  * the GDS carries the pnr.json power_net / ground_net as labels.
"""
import gzip, hashlib, json, re, sys
from pathlib import Path
import klayout.db as db

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "layout" / "trng_digital"
GDS, PNR, DEF = D / "trng_digital.gds", D / "pnr.json", D / "trng_digital.def"
OUT = D / "erc-supply-spec.json"

# sky130 GDS numbers: layout/pdk.json's open_pdks pin, sky130A.lyp, and
# klayout-tools' curated sky130 deck table.
METALS = [("li1", 67), ("met1", 68), ("met2", 69), ("met3", 70), ("met4", 71), ("met5", 72)]
VIAS = [("licon1", "66/44", ["poly", "li1"]), ("mcon", "67/44", ["li1", "met1"]),
        ("via1", "68/44", ["met1", "met2"]), ("via2", "69/44", ["met2", "met3"]),
        ("via3", "70/44", ["met3", "met4"]), ("via4", "71/44", ["met4", "met5"])]


def main():
    pnr = json.loads(PNR.read_text())
    pw = pnr["power"]
    assert pw["pdn"] is True and pw["tapcell_master"], "pnr.json has no PDN/tapcell"
    layout = db.Layout(); layout.read(str(GDS)); top = layout.top_cell()
    layer = lambda a, b: layout.layer(a, b)

    # labels on each candidate label layer (top + children), to declare only
    # label layers that carry text (klt warns/zeroes islands otherwise)
    texts = {}
    for name, n in METALS:
        li = layer(n, 5)
        s = set()
        for c in layout.each_cell():
            for sh in c.shapes(li).each():
                if sh.is_text():
                    s.add(sh.text.string)
        texts[name] = s
    for net in (pw["power_net"], pw["ground_net"]):
        assert any(net in s for s in texts.values()), f"{net} label not in GDS"
    stack = [{"name": "poly", "layer": "66/20", "role": "gate"}]
    for name, n in METALS:
        e = {"name": name, "layer": f"{n}/20"}
        if texts[name]:
            e["label_layer"] = f"{n}/5"
        stack.append(e)
    roles = {e["name"] for e in stack}
    straps = [s["layer"] for s in pw["straps"]]
    assert set(straps) <= roles, f"strap layers {straps} not covered by stackup"

    # DEF special-net layers must be covered too (the placed PDN, not just
    # the requested straps)
    defl = set(pnr["power"]["placed"]["special_nets"][0]["stripe_layers"])
    for sn in pnr["power"]["placed"]["special_nets"]:
        assert set(sn["stripe_layers"]) <= roles, sn

    tap = db.Region(top.begin_shapes_rec(layer(65, 44))).merged()
    nwell = db.Region(top.begin_shapes_rec(layer(64, 20))).merged()
    ptaps = tap - nwell
    ntaps = tap & nwell
    n_def = len(re.findall(rf"\b{re.escape(pw['tapcell_master'])}\b", DEF.read_text()))
    assert pw["placed"]["tapcells"] == n_def == ntaps.count() == ptaps.count(), \
        (pw["placed"]["tapcells"], n_def, ntaps.count(), ptaps.count())
    boxes = sorted([round(p.bbox().left * layout.dbu, 3), round(p.bbox().bottom * layout.dbu, 3),
                    round(p.bbox().right * layout.dbu, 3), round(p.bbox().top * layout.dbu, 3)]
                   for p in ptaps.each())
    # p-taps must sit outside the nwell by construction
    assert (ptaps & nwell).is_empty()

    tie = lambda name, **kw: dict(name=name, tap_layer="65/44", tap_is_dedicated=True,
                                  connect_to="li1", **kw)
    spec = {
        "stackup": stack,
        "vias": [{"name": n, "layer": l, "between": b} for n, l, b in VIAS],
        "nets": [{"name": pw["power_net"], "kind": "supply"},
                 {"name": pw["ground_net"], "kind": "supply"}],
        "ties": [
            tie("nwell_vpwr", well_layer="64/20", net=pw["power_net"]),
            tie("substrate_vgnd", well_layer=None, well_boxes=boxes, net=pw["ground_net"]),
        ],
    }
    # key order: ties entries put name/well first for readability
    # klt 0.7.0 rejects unknown top-level keys (no _comment); rationale lives in
    # layout/trng_digital/ERC.md
    OUT.write_text(json.dumps(spec, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: roles={sorted(roles)} nwells={nwell.count()} "
          f"ntaps={ntaps.count()} ptap_boxes={len(boxes)}")


main()
