#!/usr/bin/env python3
"""Net-level diagnosis of final-route violators (issue #236).

Reads <run-dir>/electrical-audit.json (violating pins per corner) and the
routed as-built Verilog, and groups the violating pins by the net they sit
on. A pin-level count overstates the number of electrical defects: one weak
driver on a high-fanout net produces one slew violation per sink pin.
Writes <run-dir>/violator-nets.json.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_PINS = {"X", "Y", "Q", "Q_N", "GCLK", "COUT", "SUM", "HI", "LO"}


def netlist(path: Path):
    txt = gzip.open(path, "rt").read()
    inst = {}
    for m in re.finditer(r"\n\s*(sky130_fd_sc_hd__\w+)\s+(\S+)\s*\((.*?)\);", txt, re.S):
        cell, name, body = m.groups()
        inst[name] = (cell, {p: n.strip() for p, n in re.findall(r"\.(\w+)\(([^)]*)\)", body)})
    return inst


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    rd = a.run_dir.resolve()
    audit = json.loads((rd / "electrical-audit.json").read_text())
    inst = netlist(rd / "trng_digital.v.gz")
    net_pins = defaultdict(list)
    for n, (cell, pins) in inst.items():
        for p, net in pins.items():
            net_pins[net].append((n, cell, p))
    out = {"schema": "sky130-trng.violator-nets/1", "per_corner": {}}
    for corner, byclass in audit["violators"].items():
        rec = {}
        for cls, rows in byclass.items():
            nets = Counter()
            worst = {}
            for r in rows:
                name, pin = r["pin"].rsplit("/", 1)
                if name not in inst:
                    nets[f"<port or unmapped:{r['pin']}>"] += 1
                    continue
                net = inst[name][1].get(pin, "?")
                nets[net] += 1
                worst[net] = max(worst.get(net, 0), r["excess"])
            top = []
            for net, cnt in nets.most_common(8):
                drivers = [(n, c) for n, c, p in net_pins.get(net, []) if p in OUT_PINS]
                top.append({"net": net, "violating_pins": cnt, "worst_excess": worst.get(net),
                            "fanout_pins": len(net_pins.get(net, [])) - len(drivers),
                            "driver_cells": sorted({c.replace("sky130_fd_sc_hd__", "") for _, c in drivers})})
            rec[cls] = {"violating_pins": len(rows), "distinct_nets": len(nets), "top_nets": top}
        if any(v["violating_pins"] for v in rec.values()):
            out["per_corner"][corner] = rec
    (rd / "violator-nets.json").write_text(json.dumps(out, indent=1) + "\n")
    for c, rec in out["per_corner"].items():
        print(c, {k: (v["violating_pins"], v["distinct_nets"]) for k, v in rec.items()})


if __name__ == "__main__":
    main()
