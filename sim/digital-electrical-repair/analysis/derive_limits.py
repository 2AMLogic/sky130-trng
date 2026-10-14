#!/usr/bin/env python3
"""Derive transition / capacitance repair budgets from the Liberty limits
(issue #236). Reads a run directory's routed DEF + post-route SPEF and the
sky130_fd_sc_hd Liberty decks. Units: slew ns, capacitance pF (the units of
klt.place-and-route.request/1 constraints.max_transition_ns / max_capacitance_pf).

The in-flow repair (`repair_design`) only sees the request's single
`pdk.corner` (tt_025C_1v80). The limits it can be steered to meet are
tt-deck quantities, so the budget must be the tt-deck value that keeps every
other corner under *its* limit:

  slew:  T_c = L_c / r_c,   r_c = max over pins (slew_c(pin) / slew_tt(pin))
         with L_c = the corner deck's default_max_transition and the ratio
         taken from the same routed DEF+SPEF at both corners (all pins whose
         tt slew >= 0.05 ns; below that the ratio is dominated by the
         intrinsic edge and not by loading);
         budget = min_c T_c, then a stated safety margin.
  cap:   per cell used by the netlist, the Liberty output max_capacitance at
         tt vs at each corner; rho = min_c lim_c / lim_tt. A single
         design-wide scalar cannot express a per-cell ratio, so the table is
         reported and the scalar is a candidate choice, not a derivation.

Every number is computed here from files; nothing is typed in.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import electrical as E  # noqa: E402

ROOT = HERE.parents[2]


def lib_default_max_transition(lib: Path) -> float:
    m = re.search(r"default_max_transition\s*:\s*([0-9.]+)", lib.read_text())
    return float(m[1])


def lib_cell_caps(lib: Path, cells: set[str]) -> dict[str, float]:
    """cell -> smallest output-pin max_capacitance (pF)."""
    t = lib.read_text()
    out = {}
    for cell in cells:
        i = t.find(f'cell ("{cell}")')
        if i < 0:
            continue
        j = t.find('\n    cell (', i + 10)
        vals = [float(v) for v in re.findall(r"max_capacitance\s*:\s*([0-9.]+)",
                                             t[i:j if j > 0 else None])]
        if vals:
            out[cell] = min(vals)
    return out


def probe(corner, kind, tmp, ref, env):
    """All-pin slew (or capacitance) table: a near-zero SDC limit makes
    report_check_types list every pin with its value."""
    s = tmp / f"probe_{kind}_{corner}.tcl"
    cls = "-max_slew" if kind == "slew" else "-max_capacitance"
    setc = "set_max_transition 0.0001" if kind == "slew" else "set_max_capacitance 0.0000001"
    s.write_text(f"""read_lef {ref}/techlef/sky130_fd_sc_hd__nom.tlef
read_lef {ref}/lef/sky130_fd_sc_hd.lef
read_def {tmp}/r.def
read_liberty {ref}/lib/sky130_fd_sc_hd__{corner}.lib
create_clock -name clk -period 20000 [get_ports clk]
read_spef {tmp}/r.spef
{setc} [current_design]
report_check_types {cls} -violators -digits 4
""")
    p = subprocess.run(["openroad", "-no_splash", "-exit", str(s)], capture_output=True,
                       text=True, cwd=ROOT, env=env)
    if p.returncode:
        raise SystemExit(f"probe failed {corner} {kind}: {p.stderr[-300:]}")
    return {r["pin"]: r["value"] for r in E.parse_violators(p.stdout)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--klt", default="klt")
    ap.add_argument("--margin", type=float, default=0.10)
    a = ap.parse_args()
    rd = a.run_dir.resolve()
    pnr = json.loads((rd / "pnr-output.json").read_text())
    corners = [c["name"] for c in pnr["corners"]]
    env = dict(os.environ, PDK="sky130A")
    if "PDK_ROOT" not in env:
        env["PDK_ROOT"] = json.loads(subprocess.run(
            [a.klt, "pdk", "find", "--pdk", "sky130A", "--format", "json"],
            capture_output=True, text=True, check=True, cwd=ROOT).stdout)["root"]
    ref = Path(env["PDK_ROOT"]) / "sky130A/libs.ref/sky130_fd_sc_hd"
    tmp = ROOT / f".derive-tmp-{rd.name}"
    tmp.mkdir(exist_ok=True)
    for src, dst in (("trng_digital.def.gz", "r.def"), ("trng_digital_route.spef.gz", "r.spef")):
        with gzip.open(rd / src, "rb") as fi, open(tmp / dst, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    cells = set(re.findall(r"\- \S+ (sky130_fd_sc_hd__\w+)", (tmp / "r.def").read_text()))
    tt = "tt_025C_1v80"
    slew_tt = probe(tt, "slew", tmp, ref, env)
    slew = {}
    for c in corners:
        L = lib_default_max_transition(ref / "lib" / f"sky130_fd_sc_hd__{c}.lib")
        sc = slew_tt if c == tt else probe(c, "slew", tmp, ref, env)
        rat = [(sc[p] / slew_tt[p], p) for p in sc if p in slew_tt and slew_tt[p] >= 0.05]
        r, pin = max(rat)
        slew[c] = {"limit_ns": L, "ratio_to_tt_max": round(r, 4), "ratio_pin": pin,
                   "worst_slew_ns": max(sc.values()), "tt_budget_ns": round(L / r, 4)}
    budget = min(v["tt_budget_ns"] for v in slew.values())
    lim_tt = lib_cell_caps(ref / "lib" / f"sky130_fd_sc_hd__{tt}.lib", cells)
    cap = {}
    for c in corners:
        lc = lib_cell_caps(ref / "lib" / f"sky130_fd_sc_hd__{c}.lib", cells)
        rr = {k: lc[k] / lim_tt[k] for k in lim_tt if k in lc}
        k = min(rr, key=rr.get)
        cap[c] = {"min_ratio_to_tt": round(rr[k], 4), "cell": k,
                  "cell_limit_pf": lc[k], "cell_tt_limit_pf": lim_tt[k]}
    rho = min(v["min_ratio_to_tt"] for v in cap.values())
    res = {"schema": "sky130-trng.limit-derivation/1", "run_dir": str(rd.relative_to(ROOT)),
           "units": {"slew": "ns", "capacitance": "pF"},
           "stage": "routed DEF + extracted post-route SPEF (final route), tt vs corner decks",
           "slew": slew, "slew_tt_budget_ns": budget,
           "slew_budget_with_margin_ns": round(budget * (1 - a.margin), 3), "margin": a.margin,
           "cap_per_corner": cap, "cap_min_ratio_to_tt": rho,
           "cap_note": "per-cell ratios; a design-wide scalar cannot express them"}
    (rd / "limit-derivation.json").write_text(json.dumps(res, indent=1) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({k: res[k] for k in ("slew_tt_budget_ns", "slew_budget_with_margin_ns",
                                          "cap_min_ratio_to_tt")}))


if __name__ == "__main__":
    main()
