#!/usr/bin/env python3
"""Idle / leakage survey reduction for the gated-off analog entropy block (issue #201).

Everything here is **simulation-derived and provisional until silicon**. This is a *survey*: it
measures and reports a standby figure per PVT corner and *recommends* an idle target. It ratifies
nothing, makes no claim that any README target "holds" for idle (README.md says the idle target is
unset pending this survey), and edits no spec.

Inputs
------
* `klt sim` responses (`corners/<rid>/*.klt-sim.json.gz`) of the `idle` leg (assembled
  `sampler_core`, rings gated off, sampler idle) and the `leaf` leg (the same leaf cells as
  independent instances), 27 units each (tt/ss/ff x -40/27/125 C x 1.62/1.8/1.98 V).
* The `sky130_fd_sc_hd` Liberty `cell_leakage_power` figures, summed over the mapped
  `trng_digital` instance counts with `sim/digital-synthesis/harness/liberty_leakage.py`.

Analog-to-Liberty corner mapping (fixed; the rule the issue's Revision section states)
-------------------------------------------------------------------------------------
For each analog point (process, T, Vdd) pick ONE Liberty view:

1. same process (tt / ss / ff);
2. temperature: the nearest *listed* temperature for that process (ties go to the colder view);
3. supply, among the views listed at that process and temperature: for `tt`/`ff` the nearest
   supply AT OR ABOVE the analog Vdd (conservative for leakage; if none is at or above, the
   highest listed supply); for `ss` the nearest listed supply (ties go to the higher).

The listed views are the non-ccsnoise views of the PDK (`VIEWS` below): there is no 125 C view
(hottest 100 C), no `tt` -40 C view and no `tt` 1.62/1.98 V view. Every point whose temperature
or supply is not matched is flagged; every 125 C point's Liberty figure is therefore a LOWER
bound. A second, clearly-labelled column (`p_digital_extrap_nw`) extrapolates the 125 C digital
leakage exponentially in T from the chosen view and the same-process, same-supply cold view; it
never replaces the Liberty-derived column.

Aggregation
-----------
    P_analog   = Vdd x (I_vdd + I_r1 + I_r2 + I_r3 + I_r4)          [rails tied to Vdd, as in the block]
    P_digital  = sum over mapped trng_digital cells of cell_leakage_power, at the mapped view
                 (a flat, state-independent per-cell Liberty figure: a state-averaged estimate,
                 NOT scaled to the analog Vdd, NOT a worst-state figure)
    P_standby  = P_analog + P_digital        (reported separately and summed, uW)
Worst-leakage corners are reported by analog alone, digital alone and combined.

Usage
-----
    python3 sim/ro-array-idle-leakage/analysis/idle_leakage.py --emit-record REQDIR
    python3 sim/ro-array-idle-leakage/analysis/idle_leakage.py --check sim/ro-array-idle-leakage/records/<rid>.json

`REQDIR` holds `<leg>-<process>/{request.json,plan.json,netlist.cir,resp.json}` (make-requests.py
output plus each request's `klt sim` JSON response saved as `resp.json`).
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import math
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
SLUG = "ro-array-idle-leakage"
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "layout" / "bin"))
from _hashing import sha256_file  # noqa: E402

SYNTH_OUTPUT = REPO / "sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-synthesize-output.json"
SYNTH_RECORD = "sim/digital-synthesis/records/20260910-001436-a4c3194"

# Non-ccsnoise sky130_fd_sc_hd Liberty views of the pinned PDK: (process, temperature_c) -> supplies (V).
VIEWS = {
    ("tt", 25.0): [1.80],
    ("tt", 100.0): [1.80],
    ("ff", -40.0): [1.56, 1.65, 1.76, 1.95],
    ("ff", 100.0): [1.65, 1.95],
    ("ss", -40.0): [1.28, 1.35, 1.40, 1.44, 1.60, 1.76],
    ("ss", 100.0): [1.40, 1.60],
}
TEMP_TOL_C = 10.0       # a view this close (or closer) in temperature counts as matched
SUPPLY_TOL_V = 0.005    # a view this close (or closer) in supply counts as matched
LEAF_RATIO_FLAG = 1.25  # assembled / leaf-sum above this is flagged (see README: bistable latch states)
CLAMP_SHARE_FLAG = 0.05  # latch clamps supplying more than this share of the block current are flagged
IDLE_LEVEL_FRAC = 0.1   # probes: xo, ro1 must be < 0.1 Vdd and rn1 > 0.9 Vdd for the intended idle state
RAILS = ["vdd", "r1", "r2", "r3", "r4"]
CLAIM = ("Standby (rings gated off, sampler idle) supply current of the pre-layout sampler_core across tt/ss/ff x "
         "-40/27/125 C x 1.62/1.8/1.98 V, with the digital trng_digital Liberty leakage mapped to each corner; a "
         "leakage SURVEY (simulation-derived, provisional until silicon) that recommends an idle target and ratifies none")


def view_name(process, temp_c, vdd):
    t = "n40C" if temp_c < 0 else f"{int(temp_c):03d}C"
    return f"sky130_fd_sc_hd__{process}_{t}_{str(f'{vdd:.2f}').replace('.', 'v')}"


def map_view(process, temp_c, vdd):
    """Apply the fixed mapping rule; return {view, view_temp_c, view_vdd, temp_extrapolated, supply_extrapolated}."""
    temps = sorted(t for (p, t) in VIEWS if p == process)
    if not temps:
        raise ValueError(f"no Liberty view for process {process!r}")
    vt = min(temps, key=lambda t: (abs(t - temp_c), t))          # ties -> colder
    sups = sorted(VIEWS[(process, vt)])
    if process in ("tt", "ff"):
        above = [s for s in sups if s >= vdd - 1e-9]
        vs = min(above) if above else max(sups)
    else:
        vs = min(sups, key=lambda s: (abs(s - vdd), -s))         # ties -> higher
    return {"view": view_name(process, vt, vs), "view_temp_c": vt, "view_vdd": vs,
            "temp_extrapolated": abs(vt - temp_c) > TEMP_TOL_C,
            "supply_extrapolated": abs(vs - vdd) > SUPPLY_TOL_V}


def extrapolate_digital_nw(p_by_view, process, temp_c, view):
    """Exponential-in-T extrapolation of the digital leakage to `temp_c` (> the hottest view), from the chosen
    (hottest) view and the same-process, same-supply cold view; None when it is not defined."""
    if temp_c <= view["view_temp_c"]:
        return None
    cold = [t for (p, t) in VIEWS if p == process and t < view["view_temp_c"] and view["view_vdd"] in VIEWS[(p, t)]]
    if not cold:
        return None
    tc = max(cold)
    hot = p_by_view[view["view"]]
    cold_p = p_by_view[view_name(process, tc, view["view_vdd"])]
    if hot <= 0 or cold_p <= 0:
        return None
    return hot * (hot / cold_p) ** ((temp_c - view["view_temp_c"]) / (view["view_temp_c"] - tc))


def needed_views():
    return sorted({view_name(p, t, s) for (p, t), ss in VIEWS.items() for s in ss})


def digital_leakage_by_view(liberty_dir, counts):
    """{view: total leakage nW} over `counts`, via the repo's own Liberty summer; plus per-file sha256."""
    spec = importlib.util.spec_from_file_location("liberty_leakage", REPO / "sim/digital-synthesis/harness/liberty_leakage.py")
    ll = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ll)
    out, sha = {}, {}
    for v in needed_views():
        path = Path(liberty_dir) / f"{v}.lib"
        leak, _ = ll.parse_cell_leakage_nw(path)
        total, missing = ll.total_leakage_nw(counts, leak)
        if missing:
            raise SystemExit(f"error: {path} has no leakage entry for {missing}: wrong Liberty for this netlist")
        out[v] = total
        sha[v] = sha256_file(path)
    return out, sha


def _meas(c):
    return {m["name"]: m["value"] for m in c["measurements"]}


def collect_units(chunks):
    """chunks: [(name, plan, response)] -> {(leg, process, temp, vdd): {name: value}}; non-passing units are dropped."""
    units, bad = {}, []
    for nm, plan, rs in chunks:
        if rs is None:
            bad.append((nm, "no response"))
            continue
        for c in rs["corners"]:
            key = (plan["leg"], c["process"], float(c["temperature_c"]), float(c["supply_v"]["Vk"]))
            if c["status"] != "pass" or any(m["value"] is None for m in c["measurements"]):
                bad.append((nm, f"{key} status={c['status']}"))
                continue
            # klt reports a unit that hit ngspice's nonconvergence fallbacks as `pass`; its currents are not valid
            nonconv = [d.get("message", d["code"]) for d in c.get("diagnostics", []) if d.get("code") == "nonconvergence"]
            neg = [m["name"] for m in c["measurements"] if m["name"].startswith("i_") and not m["name"].startswith("i_cl_") and m["value"] < 0]
            if nonconv or neg:
                bad.append((nm, f"{key} nonconvergence={nonconv} negative supply currents={neg}"))
                continue
            units[key] = _meas(c)
    return units, bad


def build_rows(units, p_by_view):
    rows = []
    for process in ("tt", "ss", "ff"):
        for temp in (-40.0, 27.0, 125.0):
            for vdd in (1.62, 1.8, 1.98):
                a, lf = units.get(("idle", process, temp, vdd)), units.get(("leaf", process, temp, vdd))
                if a is None:
                    rows.append({"process": process, "temp_c": temp, "vdd_v": vdd, "ok": False})
                    continue
                i_an = sum(a[f"i_{r}"] for r in RAILS)
                m = map_view(process, temp, vdd)
                p_an = vdd * i_an * 1e6                               # uW
                p_dg = p_by_view[m["view"]] * 1e-3                    # nW -> uW
                x = extrapolate_digital_nw(p_by_view, process, temp, m)
                i_leaf = sum(lf[f"i_{r}"] for r in RAILS) if lf else None
                i_cl = sum(abs(v) for k, v in a.items() if k.startswith("i_cl_"))   # latch clamps (assembled deck)
                row = {"process": process, "temp_c": temp, "vdd_v": vdd, "ok": True,
                       "i_rails_a": {r: a[f"i_{r}"] for r in RAILS}, "i_analog_a": i_an,
                       "i_leaf_sum_a": i_leaf, "leaf_ratio": (i_an / i_leaf) if i_leaf else None,
                       "p_analog_uw": p_an, **m, "p_digital_uw": p_dg,
                       "p_standby_uw": p_an + p_dg,
                       "p_digital_extrap_uw": None if x is None else x * 1e-3,
                       "p_standby_extrap_uw": None if x is None else p_an + x * 1e-3,
                       "i_clamp_abs_sum_a": i_cl, "clamp_share": (i_cl / i_an) if i_an > 0 else None,
                       "state_ok": (a["v_xo"] < IDLE_LEVEL_FRAC * vdd and a["v_ro1"] < IDLE_LEVEL_FRAC * vdd
                                    and a["v_rn1"] > (1 - IDLE_LEVEL_FRAC) * vdd),
                       "state_probes_v": {k: a[k] for k in ("v_xo", "v_ro1", "v_rn1")}}
                rows.append(row)
    return rows


def flags(rows):
    """Non-monotone-with-temperature points, leaf-sum exceedances, and idle-state violations."""
    out = {"non_monotone_in_temperature": [], "exceeds_leaf_sum": [], "leaf_cross_check_unavailable": [], "idle_state_violations": [], "clamp_share_above": [],
           "missing_units": []}
    for r in rows:
        if not r["ok"]:
            out["missing_units"].append(f"{r['process']}/{r['temp_c']:g}C/{r['vdd_v']}V")
            continue
        if r["leaf_ratio"] is not None and r["leaf_ratio"] > LEAF_RATIO_FLAG:
            out["exceeds_leaf_sum"].append({"corner": f"{r['process']}/{r['temp_c']:g}C/{r['vdd_v']}V", "ratio": r["leaf_ratio"]})
        if r["clamp_share"] is not None and r["clamp_share"] > CLAMP_SHARE_FLAG:
            out["clamp_share_above"].append({"corner": f"{r['process']}/{r['temp_c']:g}C/{r['vdd_v']}V", "share": r["clamp_share"]})
        if not r["state_ok"]:
            out["idle_state_violations"].append(f"{r['process']}/{r['temp_c']:g}C/{r['vdd_v']}V")
    for process in ("tt", "ss", "ff"):
        for vdd in (1.62, 1.8, 1.98):
            seq = sorted((r for r in rows if r["ok"] and r["process"] == process and r["vdd_v"] == vdd), key=lambda r: r["temp_c"])
            for lo, hi in zip(seq, seq[1:]):
                if hi["i_analog_a"] < lo["i_analog_a"]:
                    out["non_monotone_in_temperature"].append(
                        {"process": process, "vdd_v": vdd, "from_c": lo["temp_c"], "to_c": hi["temp_c"],
                         "i_from_a": lo["i_analog_a"], "i_to_a": hi["i_analog_a"]})
    return out


def worst(rows):
    ok = [r for r in rows if r["ok"]]
    if not ok:
        return {}
    def pick(key):
        r = max(ok, key=lambda x: x[key])
        return {"corner": f"{r['process']}/{r['temp_c']:g}C/{r['vdd_v']}V", "value_uw": r[key], "view": r["view"]}
    out = {"analog": pick("p_analog_uw"), "digital": pick("p_digital_uw"), "combined": pick("p_standby_uw")}
    ex = [r for r in ok if r["p_standby_extrap_uw"] is not None or r["temp_c"] <= 100]
    if ex:
        r = max(ex, key=lambda x: x["p_standby_extrap_uw"] if x["p_standby_extrap_uw"] is not None else x["p_standby_uw"])
        out["combined_with_hot_extrapolation"] = {
            "corner": f"{r['process']}/{r['temp_c']:g}C/{r['vdd_v']}V",
            "value_uw": r["p_standby_extrap_uw"] if r["p_standby_extrap_uw"] is not None else r["p_standby_uw"]}
    return out


RECOMMEND_MARGIN = 1.5


def recommend_idle_target_uw(worst_uw, margin=RECOMMEND_MARGIN):
    """Provisional recommendation: `margin` x the worst combined standby estimate, rounded UP to the next 1-2-5 value."""
    x = worst_uw * margin
    if x <= 0:
        return None
    dec = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * dec >= x * (1 - 1e-12):
            return m * dec


# ----------------------------------------------------------------------------------------------- IO
def read_reqdir(reqdir):
    chunks = []
    for d in sorted(os.listdir(reqdir)):
        p = Path(reqdir) / d
        if not (p / "request.json").exists():
            continue
        rs = json.load(open(p / "resp.json")) if (p / "resp.json").exists() else None
        chunks.append((d, json.load(open(p / "plan.json")), rs))
    return chunks


def store_chunks(rid, reqdir, chunks):
    cdir = HERE / "corners" / rid
    if cdir.exists():
        raise SystemExit(f"error: {cdir} exists")
    cdir.mkdir(parents=True)
    for nm, pl, rs in chunks:
        with gzip.open(cdir / f"{nm}.klt-sim.json.gz", "wt") as fh:
            json.dump(rs, fh, indent=1)
        json.dump(pl, open(cdir / f"{nm}.plan.json", "w"), indent=1)
        for fn, dst in (("request.json", f"{nm}.request.json"), ("netlist.cir", f"{nm}.netlist.cir")):
            shutil.copyfile(Path(reqdir) / nm / fn, cdir / dst)


def read_stored(rid):
    cdir = HERE / "corners" / rid
    out = []
    for f in sorted(cdir.glob("*.klt-sim.json.gz")):
        nm = f.name[: -len(".klt-sim.json.gz")]
        with gzip.open(f, "rt") as fh:
            out.append((nm, json.load(open(cdir / f"{nm}.plan.json")), json.load(fh)))
    return out


def default_liberty_dir():
    for c in (os.environ.get("SKY130_LIBERTY_DIR"), "~/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib"):
        if c and Path(c).expanduser().is_dir():
            return Path(c).expanduser()
    raise SystemExit("error: no sky130_fd_sc_hd Liberty directory (set SKY130_LIBERTY_DIR or pass --liberty-dir)")


def load_counts():
    return json.load(open(SYNTH_OUTPUT))["instance_counts_by_type"]


def reduce_all(chunks, liberty_dir):
    p_by_view, lib_sha = digital_leakage_by_view(liberty_dir, load_counts())
    units, bad = collect_units(chunks)
    rows = build_rows(units, p_by_view)
    return rows, flags(rows), worst(rows), p_by_view, lib_sha, bad


def _jobs(chunks):
    out = []
    for _, _, rs in chunks:
        remote = ((rs or {}).get("environment") or {}).get("remote") or {}
        out += [f["job_id"] for f in remote.get("fleet", []) if f.get("job_id")] or [remote.get("job_id")]
    return [j for j in out if j]


def fmt_i(a):
    return f"{a * 1e9:.4g}"


def markdown(rid, rows, fl, wst, rec, p_by_view, jobs, backend, rep):
    L = [f"# {rid} -- {SLUG}", "", f"**Claim**: {CLAIM}", "", "**Level**: circuit (pre-layout, `.op`)",
         "**Seed**: N/A (deterministic `.op`; every row is one unit of a `klt sim` corners request).",
         "**Supersedes**: (none)", "", "---", "", "## Configuration", "",
         f"- Decks: `sim/{SLUG}/testbench/tb_idle.spice` (assembled `design/sampler_core.spice`, en1..4 = 0, clk = 0, rst_n = Vk, sampler latches clamped to their stable idle state -- see the deck header for why) and "
         f"`tb_idle_leaf.spice` (the same leaf cells as independent instances at their idle input levels); per-rail zero-volt current sensors",
         "- Grid: tt/ss/ff x -40/27/125 C x 1.62/1.8/1.98 V (DR-0001 envelope, porting-plan 3.1), one `klt sim` corners request per process and leg "
         "(3 x 2 requests, 27 units each, `analysis.kind = op`, currents as `expr` measurements)",
         f"- Backend: {backend}; fleet jobs: {', '.join(jobs) if jobs else '(none)'}",
         f"- Digital leakage: `sky130_fd_sc_hd` Liberty `cell_leakage_power` summed over `instance_counts_by_type` of "
         f"`sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-synthesize-output.json` (record `{SYNTH_RECORD}`, "
         f"`trng_digital` at its own 50 kHz period, 2320 instances), via `sim/digital-synthesis/harness/liberty_leakage.py`. "
         "Liberty leakage is a flat, state-independent per-cell figure: a state-averaged estimate, not a worst-state figure. "
         "(The issue text cites record 20261015-214950-df2fc8b for the counts; that record is the lag-count prototype study and has "
         "no `trng_digital` instance list, so the `trng_digital` synthesis record is used instead.)",
         "- Corner mapping (fixed rule, module docstring of `analysis/idle_leakage.py`): same process; nearest listed temperature; supply "
         "at-or-above Vdd for tt/ff, nearest for ss. The library has no 125 C view (hottest 100 C), no tt -40 C view, and no tt 1.62/1.98 V "
         "view, so every 125 C point's digital figure is a LOWER bound and flagged; the exponential-in-T column is a separate, labelled extrapolation.",
         "- Aggregation: `P_standby = Vdd x I_analog_idle + P_digital_liberty(mapped view)`, analog and digital also reported separately.",
         "", "## Standby table", "",
         "I in nA (sum of the five rails). P in uW. `*T` / `*V`: the mapped Liberty view's temperature / supply is not matched. "
         "`P_dig x-T` is the separate exponential extrapolation (125 C rows only).", "",
         "| process | T C | Vdd V | I_analog nA | I_leaf-sum nA | ratio | Liberty view | flags | P_analog uW | P_digital uW | P_standby uW | P_dig x-T uW | P_standby x-T uW |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["ok"]:
            L.append(f"| {r['process']} | {r['temp_c']:g} | {r['vdd_v']} | no result | | | | | | | | | |")
            continue
        fg = ("*T" if r["temp_extrapolated"] else "") + (" *V" if r["supply_extrapolated"] else "")
        x = lambda v: "-" if v is None else f"{v:.4g}"
        L.append(f"| {r['process']} | {r['temp_c']:g} | {r['vdd_v']} | {fmt_i(r['i_analog_a'])} | "
                 f"{x(None if r['i_leaf_sum_a'] is None else r['i_leaf_sum_a'] * 1e9)} | {x(r['leaf_ratio'])} | "
                 f"`{r['view'].replace('sky130_fd_sc_hd__', '')}` | {fg.strip()} | {r['p_analog_uw']:.4g} | {r['p_digital_uw']:.4g} | "
                 f"{r['p_standby_uw']:.4g} | {x(r['p_digital_extrap_uw'])} | {x(r['p_standby_extrap_uw'])} |")
    L += ["", "## Worst-leakage corner", ""]
    for k, lbl in (("analog", "analog alone"), ("digital", "digital alone (Liberty)"), ("combined", "combined (Liberty)"),
                   ("combined_with_hot_extrapolation", "combined, with the 125 C digital extrapolation")):
        w = wst.get(k)
        if w:
            L.append(f"- **{lbl}**: {w['corner']} at {w['value_uw']:.4g} uW" + (f" (view `{w['view']}`)" if "view" in w else ""))
    L += ["", "The worst corner is whatever the table says, not presupposed: porting-plan 2.5 warns that gf180mcu's ff / hot direction need not transfer.",
          "", "## Flags", ""]
    L.append("- non-monotone analog standby current vs temperature (at fixed process and Vdd): " +
             ("none" if not fl["non_monotone_in_temperature"] else "; ".join(
                 f"{f['process']}/{f['vdd_v']}V {f['from_c']:g}->{f['to_c']:g} C: {fmt_i(f['i_from_a'])}->{fmt_i(f['i_to_a'])} nA"
                 for f in fl["non_monotone_in_temperature"])))
    L.append(f"- assembled current above {LEAF_RATIO_FLAG}x the independent leaf-cell sum (contention-path signature, DR-0007): " +
             ("none" if not fl["exceeds_leaf_sum"] else "; ".join(f"{f['corner']} ({f['ratio']:.3f}x)" for f in fl["exceeds_leaf_sum"])))
    ratios = [r["leaf_ratio"] for r in rows if r["ok"] and r["leaf_ratio"]]
    if ratios:
        L.append(f"  - assembled / leaf-sum ratio over the grid: min {min(ratios):.3f}, max {max(ratios):.3f} (the two decks are independent "
                 "instantiations of the same leaf cells with the sampler latches clamped to the same state; a ratio near 1 means no extra "
                 f"path in the assembled block; the flag threshold ({LEAF_RATIO_FLAG}x) is a stated tolerance, not a derived limit).")
    L.append(f"- latch clamps supplying more than {CLAMP_SHARE_FLAG:.0%} of the block's analog standby current (the clamp holds each sampler "
             "flip-flop's slave node at its rail to exclude the solver's mid-rail solution; a large share means the clamp, not the block, is "
             "setting the number): " + ("none" if not fl["clamp_share_above"] else "; ".join(
                 f"{f['corner']} ({f['share']:.1%})" for f in fl["clamp_share_above"])))
    shares = [r["clamp_share"] for r in rows if r["ok"] and r["clamp_share"] is not None]
    if shares:
        L.append(f"  - clamp share over the grid: median {sorted(shares)[len(shares) // 2]:.2%}, max {max(shares):.2%}.")
    L.append("- idle-state probes (v(xo) and v(ro1) below 10 % Vdd, ring node rn1 above 90 % Vdd -- the hand-derived gated-off state): " +
             ("all units in the intended state" if not fl["idle_state_violations"] else "VIOLATED at " + ", ".join(fl["idle_state_violations"])))
    if fl.get("leaf_cross_check_unavailable"):
        L.append("- leaf-sum cross-check UNAVAILABLE (the leaf-deck unit did not converge: ngspice nonconvergence diagnostic and/or negative supply "
                 "current; rejected, not used; the assembled-deck standby figure at that corner is unaffected): " +
                 "; ".join(fl["leaf_cross_check_unavailable"]))
    if fl["missing_units"]:
        L.append("- units with no passing result: " + ", ".join(fl["missing_units"]))
    L += ["", "## Measured range and recommendation (provisional)", ""]
    ok = [r for r in rows if r["ok"]]
    if ok:
        lo = min(ok, key=lambda r: r["p_standby_uw"])
        hi = max(ok, key=lambda r: r["p_standby_uw"])
        L.append(f"- Measured combined standby range over the grid: **{lo['p_standby_uw']:.4g} uW** ({lo['process']}/{lo['temp_c']:g}C/{lo['vdd_v']}V) "
                 f"to **{hi['p_standby_uw']:.4g} uW** ({hi['process']}/{hi['temp_c']:g}C/{hi['vdd_v']}V), Liberty-derived digital term.")
    if rec is not None:
        L.append(f"- **Recommended idle-target value (provisional, recommendation only): <= {rec:g} uW**, = {RECOMMEND_MARGIN}x the worst combined "
                 "estimate (including the 125 C digital extrapolation) rounded up to the next 1-2-5 value. The margin is a stated choice, not derived. "
                 "It is a worst-corner ENVELOPE (ff / 125 C / 1.98 V), where the digital term is a labelled extrapolation beyond the library's hottest "
                 "view; the typical point (tt / 27 C / 1.8 V) is orders of magnitude lower (see the table), so a typical-condition idle figure is a "
                 "separate choice for the decision record.")
    L += ["- This record makes **no** claim that any README target holds for idle. README.md:75 reads \"< 500 uW active; idle target set after a "
          "sky130 leakage survey\": the idle target is unset, and the 500 uW active figure is not an idle limit. It is context only: the "
          "worst combined standby estimate is a small fraction of it, but that is not a comparison against an idle requirement.",
          "- Any adoption of the recommended value, or any violation of an existing budget, goes to a separate decision-record issue; no `README.md` / `spec/` edit is made here.",
          "", "## What this record does and does not establish", "",
          "- Establishes: pre-layout `.op` standby supply current of the assembled analog block with its enable low, per PVT corner, and a combined estimate with the library's digital leakage.",
          "- Does not establish: any silicon figure; post-layout leakage (parasitic and well/substrate leakage not in the pre-layout netlist); a worst-state digital figure; "
          "leakage at 125 C from the Liberty library (no such view); the idle current of any other state (e.g. rst_n low, clk toggling). fs/sf corners and Monte Carlo are out of scope.",
          "- Simulation-derived; provisional until measured on silicon."]
    return "\n".join(L) + "\n"


def emit_record(reqdir, liberty_dir):
    from evidence_record import mint_record, new_record_id
    chunks = read_reqdir(reqdir)
    if any(rs is None for _, _, rs in chunks):
        raise SystemExit("error: a request has no resp.json; run the grid first")
    rows, fl, wst, p_by_view, lib_sha, bad = reduce_all(chunks, liberty_dir)
    fatal = [b for b in bad if not b[1].startswith("('leaf'")]
    if fatal:
        raise SystemExit(f"error: assembled-deck units without a valid result: {fatal}")
    fl["leaf_cross_check_unavailable"] = [b[1] for b in bad]
    now, sha, rid = new_record_id(REPO)
    store_chunks(rid, reqdir, chunks)
    jobs = _jobs(chunks)
    backend = "batch" if all((rs["environment"].get("remote")) for _, _, rs in chunks) else "local (single-unit debug probe)"
    rec_val = recommend_idle_target_uw((wst.get("combined_with_hot_extrapolation") or wst["combined"])["value_uw"])
    env = chunks[0][2]["environment"]
    md = markdown(rid, rows, fl, wst, rec_val, p_by_view, jobs, backend, None)
    summary = {
        "record_id": rid, "slug": SLUG, "level": "circuit", "claim": CLAIM, "seeds": "N/A (deterministic .op)",
        "supersedes": "(none)", "author": "loom-builder@sky130-trng", "timestamp_utc": now.isoformat(), "repo_sha": sha,
        "pdk": "sky130A", "rows": rows, "flags": fl, "worst": wst, "recommended_idle_target_uw": rec_val,
        "recommendation_rule": f"{RECOMMEND_MARGIN}x the worst combined standby (with the 125 C digital extrapolation), rounded up to the next 1-2-5 value; recommendation only",
        "digital": {"source": SYNTH_RECORD, "instance_counts_from": str(SYNTH_OUTPUT.relative_to(REPO)),
                    "leakage_nw_by_view": p_by_view, "liberty_sha256": lib_sha},
        "mapping_rule": "analysis/idle_leakage.py module docstring; VIEWS table",
        "thresholds": {"leaf_ratio_flag": LEAF_RATIO_FLAG, "clamp_share_flag": CLAMP_SHARE_FLAG, "idle_level_frac": IDLE_LEVEL_FRAC},
        "klt_sim": {"jobs": jobs, "backend": backend, "engine_version": env["engine_version"],
                    "models_lib_sha256": env["models_lib_sha256"],
                    "netlist_sha256": {nm: rs["environment"]["netlist_sha256"] for nm, _, rs in chunks},
                    "submitter_klt": chunks[0][2]["provenance"]["klt_version"],
                    "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"},
        "corners_dir": rid, "tools": {"script": f"sim/{SLUG}/analysis/idle_leakage.py --emit-record"},
    }
    got = mint_record(HERE / "records", REPO, rid, [], md, summary, author="loom-builder@sky130-trng", now=now, sha=sha)
    if got is None:
        raise SystemExit(1)
    print(rid, "worst combined:", wst["combined"], "recommended <=", rec_val, "uW")


def check(record_json, liberty_dir):
    rec = json.load(open(record_json))
    rows, fl, wst, *_ = reduce_all(read_stored(rec["corners_dir"]), liberty_dir)
    if json.loads(json.dumps(rows)) != rec["rows"]:
        raise SystemExit("MISMATCH: recomputed rows differ from the record")
    print("OK: recomputed rows match", record_json)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--emit-record", metavar="REQDIR")
    ap.add_argument("--check", metavar="RECORD_JSON")
    ap.add_argument("--liberty-dir")
    a = ap.parse_args()
    lib = Path(a.liberty_dir) if a.liberty_dir else default_liberty_dir()
    if a.emit_record:
        emit_record(a.emit_record, lib)
    elif a.check:
        check(a.check, lib)
    else:
        ap.error("one of --emit-record / --check is required")


if __name__ == "__main__":
    main()
