#!/usr/bin/env python3
"""Per-axis delay/leakage sensitivity of the pinned ``sky130_fd_sc_hd`` decks.

The evidence source for the error-direction column of issue #595's
matrix-to-deck mapping (``../pvt_deck_map.py``, record
``../records/20261121-pvt-deck-and-boundary-load.md``): it parses the
shipped Liberty decks with ``make-gate-model.py``'s own parser and measures,
over the cell types ``layout/trng_digital/trng_digital.routed.v`` actually
uses, how the library-mean scalar delay and ``cell_leakage_power`` move
between deck pairs that isolate ONE axis each:

* temperature at fixed supply (``tt_025C_1v80`` vs ``tt_100C_1v80``; the
  ss/ff equivalents), and
* supply at fixed temperature (``ff_n40C_1v65`` vs ``ff_n40C_1v95``;
  ``ss_n40C_1v60`` vs ``ss_n40C_1v76``).

What it found (and the mapping's direction column leans on):

* **Both sensitivities have the same sign** -- this library gets FASTER
  warm (temperature inversion at 1.8 V-class supplies: the tt pair moves
  library-mean delay -4.4 % over 75 K) and faster at high supply (the ff
  pair -26.6 % over 0.30 V). So for every matrix point the two axes' deck
  errors push delay the SAME way or one dominates; no point's net delay
  direction is left "mixed" by opposing axes.
* Voltage dominates: roughly -89 %/V (ff) to -154 %/V (ss) against
  -0.059..-0.124 %/K -- which is why the mapping's nearest-deck rule
  minimises |dV| first and only tie-breaks on |dT|.
* Leakage rises steeply with both axes (library-mean ``cell_leakage_power``
  x9335 over the ss -40 C -> 100 C pair at 1.60 V), so a cold/low-V deck
  under-calls the point's leakage and a warm/high-V deck over-calls it.
* Per-cell spread: the temperature direction holds for the library MEAN at
  two operating points, but a minority of cells (11 of 63 on the tt pair)
  individually move the other way -- the directions are mean-level
  statements, not per-cell guarantees.

Nothing here simulates anything, interpolates, or picks decks; it only
measures the shipped decks against each other. Requires the pinned PDK
(``klt pdk find``) -- it is a run-on-request evidence tool, not a CI test.

Usage::

    python3 sim/post-layout-whole-block/analysis/deck-axis-sensitivity.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from loadmod import load_module  # noqa: E402

G = load_module("make_gate_model", HERE.parent / "make-gate-model.py")
PVT = load_module("pvt_deck_map", HERE.parent / "pvt_deck_map.py")

#: the two operating points the direction claims are checked at (slew ns,
#: load pF): the deck family's own stimulus edge + a mid-table load, and a
#: slower/wider point to show the direction is not an artefact of one.
OPERATING_POINTS = ((0.1, 0.006), (0.4, 0.020))

#: deck pairs isolating one axis each: (label, corner A, corner B, axis).
PAIRS = (
    ("T: tt 1.80 V, 25 C -> 100 C", "tt_025C_1v80", "tt_100C_1v80", "K"),
    ("T: ss 1.60 V, -40 C -> 100 C", "ss_n40C_1v60", "ss_100C_1v60", "K"),
    ("T: ff 1.95 V, -40 C -> 100 C", "ff_n40C_1v95", "ff_100C_1v95", "K"),
    ("V: ff -40 C, 1.65 V -> 1.95 V", "ff_n40C_1v65", "ff_n40C_1v95", "V"),
    ("V: ff -40 C, 1.65 V -> 1.76 V", "ff_n40C_1v65", "ff_n40C_1v76", "V"),
    ("V: ss -40 C, 1.60 V -> 1.76 V", "ss_n40C_1v60", "ss_n40C_1v76", "V"),
)


def deck_stats(corner: str, slew_ns: float, load_pf: float) -> tuple[dict[str, float], dict[str, float]]:
    """``(cell -> max rise/fall delay ns, cell -> cell_leakage_power)``.

    The delay is the generator's own reduction shape -- max over every delay
    arc reaching every output pin, bilinear at the operating point, clamped
    -- so the sensitivity is measured on exactly the numbers the gate model
    would carry, not on a proxy.
    """
    lib = G.resolve_liberty(None, corner)
    design = G.parse_verilog(G.ROUTED_V)
    blocks, _, templates = G.extract_cell_blocks(lib, set(design.cell_histogram()))
    delays: dict[str, float] = {}
    leakage: dict[str, float] = {}
    for name, grp in blocks.items():
        cm = G.CellModel(name, grp, templates)
        worst = 0.0
        for out in cm.outputs:
            if cm.arcs.get(out):
                rise, fall = cm.delays(slew_ns, load_pf, out)
                worst = max(worst, rise, fall)
        if worst:
            delays[name] = worst * 1e9  # s -> ns
        lk = grp.attrs.get("cell_leakage_power")
        if lk is not None:
            leakage[name] = float(lk)
    return delays, leakage


def axis_span(a: str, b: str, axis: str) -> float:
    (pa, ta, va), (pb, tb, vb) = PVT.deck_corner(f"sky130_fd_sc_hd__{a}.lib"), \
        PVT.deck_corner(f"sky130_fd_sc_hd__{b}.lib")
    return (tb - ta) if axis == "K" else (vb - va)


def mean_ratio(a: dict[str, float], b: dict[str, float]) -> tuple[float, float, int]:
    """(arithmetic mean, geometric mean) of ``b/a`` over the common keys."""
    keys = sorted(set(a) & set(b))
    rs = [b[k] / a[k] for k in keys if a[k] > 0]
    return sum(rs) / len(rs), math.exp(sum(math.log(r) for r in rs) / len(rs)), len(rs)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="per-axis deck sensitivity probe (issue #595)")
    ap.add_argument("--json", action="store_true", help="also emit machine-readable rows")
    args = ap.parse_args(argv)

    design = G.parse_verilog(G.ROUTED_V)
    print(f"cells: {len(set(design.cell_histogram()))} distinct types of "
          f"{len(design.instances)} routed instances; delays are the generator's "
          "own reduction (max over arcs, bilinear, clamped)\n")
    out_rows = []
    for label, a, b, axis in PAIRS:
        span = axis_span(a, b, axis)
        print(f"{label}:")
        for slew, load in OPERATING_POINTS:
            da, la = deck_stats(a, slew, load)
            db, lb = deck_stats(b, slew, load)
            d_mean, _, n = mean_ratio(da, db)
            l_mean, _, _ = mean_ratio(la, lb)
            per_k = (d_mean - 1.0) * 100.0 / span
            print(f"  @ (slew {slew} ns, load {load * 1000:.0f} fF): delay x{d_mean:.4f} "
                  f"over {n} cells = {(d_mean - 1.0) * 100:+.2f}% per {span:g} {axis} "
                  f"({per_k:+.3f}%/{axis}); cell_leakage_power x{l_mean:.4f}")
            out_rows.append({"pair": label, "slew_ns": slew, "load_pf": load,
                             "delay_ratio": round(d_mean, 4), "n_cells": n,
                             "leakage_ratio": round(l_mean, 4),
                             f"sensitivity_pct_per_{axis}": round(per_k, 3)})
        print()

    # per-row direction of the committed mapping, re-derived from the pairs
    print("per-point direction of the committed mapping "
          "(sign of sT*dT + sV*dV; sT per process pair, sV per process pair, "
          "tt has no voltage pair so ff's is the disclosed proxy):")
    sT = {"tt": None, "ss": None, "ff": None}
    sV = {"tt": None, "ss": None, "ff": None}
    for label, a, b, axis in PAIRS:
        da, _ = deck_stats(a, *OPERATING_POINTS[0])
        db, _ = deck_stats(b, *OPERATING_POINTS[0])
        d_mean, _, _ = mean_ratio(da, db)
        sens = (d_mean - 1.0) * 100.0 / axis_span(a, b, axis)
        proc = PVT.deck_corner(f"sky130_fd_sc_hd__{a}.lib")[0]
        if axis == "K":
            sT[proc] = sens
        elif sV[proc] is None:  # keep the widest-span pair per process
            sV[proc] = sens
    sV["tt"] = sV["ff"]
    for proc, temp, vdd in PVT.matrix_points():
        row = PVT.DECK_TABLE[(proc, temp, vdd)]
        net = sT[proc] * row["dT_K"] + sV[proc] * row["dV_V"]
        flag = "EXACT" if row["exact"] else row["delay_direction"]
        est = f"{row['est_delay_error_pct']:+.1f}% (committed)"
        print(f"  {proc} {temp:>6.0f} C {vdd:.2f} V -> {row['liberty_deck']:<36} "
              f"dT={row['dT_K']:+6.1f} K dV={row['dV_V']:+.2f} V "
              f"-> {sT[proc] * row['dT_K']:+6.2f}% + {sV[proc] * row['dV_V']:+6.2f}% "
              f"= {net:+6.2f}%  [{flag}, {est}]")
    if args.json:
        print("\n" + json.dumps(out_rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
