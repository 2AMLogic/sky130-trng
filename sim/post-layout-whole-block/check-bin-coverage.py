#!/usr/bin/env python3
"""Scan EVERY sky130_fd_pr device card of a flat netlist for model-bin coverage (issue #386).

For each card ``sky130_fd_pr__<model> ... L=<l> W=<w>`` (unitless, ``.option
scale=1u`` => metres x 1e-6) check that some ``.model`` bin of the pinned PDK
has ``lmin <= L < lmax`` and ``wmin <= W < wmax`` (ngspice's binning rule).
Bins are read from the PDK files that ``sky130.lib.spice tt`` loads; no ngspice
run, so it is fast and, unlike a whole-netlist parse, can fail on a bad netlist.

    check-bin-coverage.py NETLIST[.gz] --pdk <.../sky130A> [--json]

Exit 0 = every card covered, 1 = uncovered cards (count and breakdown printed).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import re
import sys
from pathlib import Path

# card model name -> PDK file (relative to sky130A/libs.tech/combined) defining its bins
BIN_FILES = {
    "sky130_fd_pr__nfet_01v8": "continuous/models_fet/sky130_fd_pr__nfet_01v8.spice",
    "sky130_fd_pr__pfet_01v8": "continuous/models_fet/sky130_fd_pr__pfet_01v8.spice",
    "sky130_fd_pr__special_nfet_01v8":
        "../../libs.ref/sky130_fd_pr/spice/sky130_fd_pr__special_nfet_01v8__tt.pm3.spice",
}
MODEL_RE = re.compile(r"^\.model\s+(\S+)\s+\w+[ \t]*((?:\n[+*].*)*)", re.M | re.I)
BOUND_RE = re.compile(r"\b([lw]m(?:in|ax))\s*=\s*([0-9.eE+-]+)", re.I)
CARD_RE = re.compile(r"\b(sky130_fd_pr__\w+)\s+L=([0-9.eE+-]+)\s+W=([0-9.eE+-]+)")


def load_bins(pdk: Path, model: str) -> list[tuple[float, float, float, float]]:
    text = (pdk / "libs.tech" / "combined" / BIN_FILES[model]).read_text()
    bins = []
    for m in MODEL_RE.finditer(text):
        b = {k.lower(): float(v) for k, v in BOUND_RE.findall(m.group(0))}
        if {"lmin", "lmax", "wmin", "wmax"} <= b.keys():
            bins.append((b["lmin"], b["lmax"], b["wmin"], b["wmax"]))
    if not bins:
        raise SystemExit(f"no bins parsed for {model}")
    return bins


def _nm(metres: float) -> int:
    """Round to integer nm so bin edges compare exactly (0.42*1e-6 != 4.2e-7 in floats)."""
    return round(metres * 1e9)


def covered(bins, l_um: float, w_um: float) -> bool:
    l, w = _nm(l_um * 1e-6), _nm(w_um * 1e-6)
    return any(_nm(lo) <= l < _nm(lh) and _nm(wl) <= w < _nm(wh)
               for lo, lh, wl, wh in bins)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist", type=Path)
    ap.add_argument("--pdk", type=Path, required=True, help="path to the sky130A dir")
    args = ap.parse_args()
    opener = gzip.open if args.netlist.suffix == ".gz" else open
    text = opener(args.netlist, "rt").read()
    bins = {m: load_bins(args.pdk, m) for m in BIN_FILES}
    total = collections.Counter()
    bad = collections.Counter()
    for model, l, w in CARD_RE.findall(text):
        if model not in bins:
            raise SystemExit(f"card model {model} has no bin source in BIN_FILES")
        key = (model, l, w)
        total[key] += 1
        if not covered(bins[model], float(l), float(w)):
            bad[key] += 1
    print(f"netlist: {args.netlist}")
    print(f"cards scanned: {sum(total.values())} ({len(total)} distinct model/L/W)")
    for (model, l, w), n in sorted(total.items()):
        flag = "UNCOVERED" if (model, l, w) in bad else "ok"
        print(f"  {n:6d}  {model} L={l} W={w}  {flag}")
    print(f"uncovered cards: {sum(bad.values())}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
