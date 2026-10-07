#!/usr/bin/env python3
"""Generate `klt sim` requests re-measuring sim/post-layout-ro-ring5-assembled/
on the issue #181 / #184 refreshed layout/pex-ring/ library.

The original campaign ran through sim/bin/corner-run.py (a local, per-corner
ngspice loop). Issue #184 must not hand-launch a corner grid, so the same
testbench is expressed here as `klt sim` requests (three process corners per
PVT point, four PVT points) that submit to the batch fleet.

Each request is derived MECHANICALLY from the committed template deck
sim/post-layout-ro-ring5-assembled/testbench/tb_post_layout_ro_ring5_assembled.spice:
  * @@VDD@@/@@TEMP@@/@@TMAX@@ literals are substituted,
  * the .lib/.temp/.tran/.save/.control/.end cards are lifted out (klt sim owns
    them) and
  * every `meas ...` line inside .control becomes a measurements[] spice card;
    the deck's `let` derived figures are recomputed by derive.py.
Usage: make-requests.py OUTDIR   (writes OUTDIR/p<N>/{netlist.cir,request.json})
"""
import json, os, re, sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TB = os.path.join(REPO, "sim/post-layout-ro-ring5-assembled/testbench/tb_post_layout_ro_ring5_assembled.spice")
PEX = os.path.join(REPO, "layout/pex-ring/ro_ring5_assembled_pex.spice")
PRE = os.path.join(REPO, "design/ro_array_core.spice")
POINTS = [(-40.0, 1.62), (27.0, 1.80), (125.0, 1.98), (-40.0, 1.98)]
TMAX = "5p"
LIB = "libs.tech/combined/sky130.lib.spice"


def split_deck(text):
    head, ctl = [], []
    in_ctl = False
    for line in text.splitlines():
        s = line.strip()
        low = s.lower()
        if low == ".control":
            in_ctl = True
            continue
        if low == ".endc":
            in_ctl = False
            continue
        (ctl if in_ctl else head).append(line)
    return head, ctl


def build(temp, vdd):
    sub = {"@@VDD@@": repr(vdd), "@@TEMP@@": repr(temp), "@@TMAX@@": TMAX,
           "@@RO_RING5@@": PRE, "@@PEX_LIB@@": PEX}
    text = open(TB).read()
    for k, v in sub.items():
        text = text.replace(k, v)
    # ngspice .meas WHEN rejects `0.5*1.62`-style expressions (probed on the
    # batch fleet's ngspice, 2026-10-07): fold the half-supply to a literal.
    text = re.sub(r"0\.5\*([0-9.]+)", lambda m: repr(round(0.5 * float(m.group(1)), 6)), text)
    head, ctl = split_deck(text)
    body = []
    for line in head:
        low = line.strip().lower()
        if low.startswith((".lib", ".temp", ".tran", ".save", ".end", ".option")) and not low.startswith(".option scale"):
            continue
        body.append(line)
    meas, names = [], []
    for line in ctl:
        s = line.strip()
        if not s or s.startswith("*") or s == "run":
            continue
        if s.startswith("meas "):
            m = re.match(r"meas tran (\w+) ", s)
            meas.append({"name": m.group(1), "spice": "." + s})
        # `let` lines (derived figures) are NOT sent as expr: klt sim's expr
        # cannot reference top-level .meas results (probed 2026-10-07, they
        # print nothing). They are recomputed from the raw .meas values by
        # derive.py, using the same formulas as the template deck.
        elif s.startswith("print "):
            names.append(s.split()[1])
    # The `.meas ... when` raw crossings (tr1a..) stay as spice cards; the let-
    # derived values need the .meas results as vectors; klt exposes each `.meas`
    # result by its name inside the .control block (ngspice behaviour).
    return "\n".join(body) + "\n", meas, names


def main(out):
    for i, (t, v) in enumerate(POINTS, 1):
        body, meas, names = build(t, v)
        d = os.path.join(out, f"p{i}")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "netlist.cir"), "w").write(body)
        req = {
            "netlist": "netlist.cir",
            "engine": "ngspice",
            "backend": "batch",
            "netlist_source": "extracted",
            "models": {"pdk": "sky130A", "lib": LIB},
            "corners": {"process": ["tt", "ss", "ff"], "temperature_c": [t]},
            "analysis": {"kind": "tran", "args": f"{TMAX} 160n uic"},
            "measurements": meas,
            "options": {"timeout_s": 3000, "keep_artifacts": True},
        }
        json.dump(req, open(os.path.join(d, "request.json"), "w"), indent=2)
        print(d, f"T={t} Vdd={v}", len(meas), "measurements")


if __name__ == "__main__":
    main(sys.argv[1])
