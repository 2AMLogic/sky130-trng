#!/usr/bin/env python3
"""Scan EVERY sky130_fd_pr device card of a flat netlist for model-bin coverage (issue #386).

For each card ``sky130_fd_pr__<model> ... L=<l> W=<w>`` (unitless, ``.option
scale=1u`` => metres x 1e-6) check that some ``.model`` bin of the pinned PDK
has ``lmin <= L < lmax`` and ``wmin <= W < wmax`` (ngspice's binning rule).
Bins are read from the PDK files that ``sky130.lib.spice tt`` loads; no ngspice
run, so it is fast and, unlike a whole-netlist parse, can fail on a bad netlist.

    check-bin-coverage.py NETLIST[.gz] --pdk <.../sky130A> [--json]

It also checks EVERY device card of any type (X/D/R/C/M/Q, ``+`` continuations
joined): the card's model/subckt name must be defined (``.model`` / ``.subckt``)
in the files ``sky130.lib.spice tt`` includes, or be the netlist's own subckt
(issue #422: a bare-model ``D`` card the bin scan could not see made it past a
re-pin and fails ngspice with "could not find a valid modelname").

Exit 0 = every card covered and defined, 1 = uncovered/undefined cards.
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


DEF_RE = re.compile(r"^\.(?:model|subckt)\s+(\S+)", re.M | re.I)
INC_RE = re.compile(r"^\.include\s+(\S+)", re.M | re.I)
PARAM_TOK = re.compile(r"^[A-Za-z_]\w*\s*=")


def pdk_defined_names(pdk: Path) -> set[str]:
    """Names of every .model/.subckt in the files the tt corner of sky130.lib.spice includes."""
    root = pdk / "libs.tech" / "combined"
    lib = (root / "sky130.lib.spice").read_text()
    tt = re.search(r"^\.lib\s+tt\s*$(.*?)^\.endl", lib, re.M | re.S | re.I).group(1)
    names: set[str] = set()
    seen: set[Path] = set()

    def walk(text: str, base: Path) -> None:
        for inc in INC_RE.findall(text):
            f = base / inc.strip("\"'")
            if f.exists() and f not in seen:
                seen.add(f)
                body = f.read_text()
                names.update(n.lower() for n in DEF_RE.findall(body))
                walk(body, f.parent)

    walk(tt, root)
    return names


def card_model(card: str) -> str | None:
    """Model/subckt token of one logical device card: the last token before the first NAME=value."""
    toks = card.split()
    end = len(toks)
    for i, t in enumerate(toks[1:], 1):
        if PARAM_TOK.match(t) or (i + 1 < len(toks) and toks[i + 1].startswith("=")):
            end = i
            break
    return toks[end - 1].lower() if end > 2 else None


def undefined_models(text: str, defined: set[str]) -> collections.Counter:
    """Count cards (by first letter + model) whose model is neither in the PDK nor a local subckt."""
    logical: list[str] = []
    for ln in text.splitlines():
        if not ln.strip() or ln.lstrip().startswith("*"):
            continue
        if ln.startswith("+") and logical:
            logical[-1] += " " + ln[1:]
        else:
            logical.append(ln)
    local = {m.lower() for ln in logical if ln.lower().startswith(".subckt")
             for m in [ln.split()[1]]}
    bad: collections.Counter = collections.Counter()
    for card in logical:
        if card[0] in ".":
            continue
        model = card_model(card)
        if card[0].upper() in "XDQMRC" and model and model not in defined | local:
            bad[(card[0].upper(), model)] += 1
    return bad


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
    undef = undefined_models(text, pdk_defined_names(args.pdk))
    for (kind, model), n in sorted(undef.items()):
        print(f"  {n:6d}  {kind}-card model {model!r} UNDEFINED in pinned PDK")
    print(f"undefined-model cards: {sum(undef.values())}")
    return 1 if bad or undef else 0


if __name__ == "__main__":
    sys.exit(main())
