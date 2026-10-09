#!/usr/bin/env python3
"""Reduction for the supply-ripple / injection-lock campaign (issue #200).

Standard library only; no simulator, no PDK.  Two halves:

* pure functions (`analyze_edges`, `tone_lock`, `pair_lock`, `row_verdict`,
  `tolerance`) -- unit-tested in sim/tests/test_ripple_reduction.py on synthetic
  edge trains, including a deliberately locked one, so the detector is shown to
  fire on data that is locked by construction, independent of any simulation;
* a CLI that turns `klt sim` batch responses (make-requests.py) into one
  append-only record per PVT point:

    ripple.py --emit-record REQDIR            # REQDIR/<corner>-<group>-<n>/{resp.json,plan.json}
    ripple.py --check sim/ro-array-supply-perturbation/records/<id>.json   # replay, writes nothing

What a row is
-------------
One klt sim unit: (process, temp, vnom) x (dv, ra, rf, rc).  The deck records the
rising-edge times t[r][k] of the four BUFFERED ring outputs (k = 3..42, i.e. 40
edges, 39 periods).  There is deliberately NO injected noise: every figure here
is the deterministic response of the rings to the ripple, so it is a
robustness measurement, not an entropy measurement.

Definitions (all from edge times alone)
---------------------------------------
period series      P_k = t_{k+1} - t_k; mean T = (t_last - t_first)/39.
period modulation  m = (max P - min P) / (2 T), a peak fraction.  The clean
                   baseline run's m is the measurement floor.
mean-period shift  T / T_clean - 1, T_clean from the same corner's clean baseline.
Q ratio            DR-0002: Q_ring = sigma_1^2 Ts / T0^3, so at fixed sigma_1
                   Q scales as T0^-3.  Q_array/Q_array,clean = mean_r (T_clean,r/T_r)^3.
                   This is the T0-only part of "jitter-derived Q": the run has no
                   noise, so sigma_1 under ripple is NOT measured here.
tone lock          ring r vs ripple tone f_rip: for each ratio p:q (p ring cycles
                   per q tone cycles, p,q in 1..4) the phase residual
                   psi_k = (p/q) f_rip t_k - k; its least-squares slope times 39 is
                   the number of ring cycles that slip across the window.  LOCKED
                   if min |drift| < DRIFT_LOCK (0.1 ring cycle) for some p:q.  A
                   ring that is within that of a rational in the CLEAN run too is
                   reported COINCIDENT (cannot be told apart from coincidence) and
                   still fails the tolerance, conservatively.
pair lock          same drift test between ring i and ring j (ring i's cycle count
                   interpolated at ring j's edge times), p:q in 1:1,2:1,3:2,4:3 and
                   inverses.  A pair counts only if it was NOT already inside the
                   window in the clean run (new lock caused by the ripple).
closeness          DR-0005's figure: min over rationals of |T_i/T_j / (p/q) - 1|,
                   for the DR-0005 set {2/1, 3/2, 4/3} and including 1/1.
bias               <v(xo)> / vnom over 60 ns..stop (quasi-static rows: / (vnom+dv)).

Tolerance criteria (DR-0003's margins, not new ones)
----------------------------------------------------
LOCK  no ring LOCKED to the tone (phase slip < 0.1 ring cycle over the 39-period
      window while the clean ring would have slipped more) and no new pair lock.
      A ring whose CLEAN frequency is already inside that resolution of a tone
      rational (a tone placed on a ring's own frequency) is COINCIDENT: the 40-edge
      window cannot separate lock from coincidence (resolution ~0.25% detuning), so
      the row is reported UNRESOLVED, not passed and not failed.  The detuned-tone
      rows bracket the lock range that the at-frequency rows cannot.
Q     (not applied to a tone row whose edge window holds < 2 ripple cycles -- the window
      mean is then not cycle-averaged; the quasi-static family covers that regime)
      Q ratio >= 1/1.036: DR-0003 sec. 3 puts Q_array at 1.036x the M*Q_H0
      requirement at the entropy-binding corner, so a 3.5% Q loss exhausts it.
BIAS  bias_xo inside [0.31, 0.53]: DR-0003 sec. 3 "DC bias at xo stays within
      0.31-0.53 x Vdd across the grid".

Simulation-derived; provisional until silicon.
"""
import datetime
import glob
import gzip
import json
import math
import os
import shutil
import sys
from bisect import bisect_right

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SLUG = "ro-array-supply-perturbation"
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))

NEDGE = 40
DRIFT_LOCK = 0.1                 # ring cycles slipped over the window below which => locked
RATIOS = [(p, q) for p in range(1, 5) for q in range(1, 5) if math.gcd(p, q) == 1]
PAIR_RATIOS = [(1, 1), (2, 1), (3, 2), (4, 3)]
DR5_RATIOS = [(2, 1), (3, 2), (4, 3)]
Q_MARGIN = 1.036                 # DR-0003 sec. 3: Q_array / (M*Q_H0) at the binding corner
BIAS_BAND = (0.31, 0.53)         # DR-0003 sec. 3
PROV = "simulation-derived; provisional until silicon"


# ---------------------------------------------------------------- pure functions
def ls_slope(ys):
    n = len(ys)
    xm = (n - 1) / 2.0
    ym = sum(ys) / n
    num = sum((i - xm) * (y - ym) for i, y in enumerate(ys))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den


def periods(t):
    return [b - a for a, b in zip(t, t[1:])]


def analyze_edges(t):
    """t: list of rising-edge times (s) of one ring."""
    P = periods(t)
    T = (t[-1] - t[0]) / (len(t) - 1)
    return {"T": T, "mod_pk": (max(P) - min(P)) / (2 * T)}


def tone_lock(t, f_rip):
    """Best (smallest |drift|) ring-vs-tone rational. Returns (p, q, drift)."""
    best = None
    n = len(t) - 1
    for p, q in RATIOS:
        psi = [(p / q) * f_rip * tk - k for k, tk in enumerate(t)]
        d = ls_slope(psi) * n
        if best is None or abs(d) < abs(best[2]):
            best = (p, q, d)
    return best


def _cycles_at(t_i, when):
    """Ring i's fractional edge count at times `when` (linear between edges);
    None outside ring i's recorded span."""
    out = []
    for tw in when:
        j = bisect_right(t_i, tw) - 1
        if j < 0 or j >= len(t_i) - 1:
            out.append(None)
            continue
        out.append(j + (tw - t_i[j]) / (t_i[j + 1] - t_i[j]))
    return out


def pair_lock(t_i, t_j):
    """Best p:q (f_i/f_j = p/q) and the ring-i cycles slipped across the window."""
    best = None
    n_i = _cycles_at(t_i, t_j)
    ks = [(k, c) for k, c in enumerate(n_i) if c is not None]
    if len(ks) < 8:
        return None
    for p, q in PAIR_RATIOS + [(b, a) for a, b in PAIR_RATIOS if a != b]:
        resid = [c - k * p / q for k, c in ks]
        d = ls_slope(resid) * (len(ks) - 1)
        if best is None or abs(d) < abs(best[2]):
            best = (p, q, d)
    return best


def closeness(Ti, Tj, ratios):
    """min over (p/q) of |(f_i/f_j) / (p/q) - 1|; f_i/f_j = Tj/Ti.  Order-free."""
    r = Tj / Ti
    best = None
    for p, q in ratios:
        for x in (p / q, q / p):
            d = abs(r / x - 1)
            if best is None or d < best[0]:
                best = (d, p, q)
    return best


def row_metrics(edges, clean_edges, vnom, dv, xo_avg, f_rip=None):
    """edges[r] -> 40 rising-edge times of ring r+1.  clean_edges: same, baseline."""
    rings = [analyze_edges(e) for e in edges]
    cl = [analyze_edges(e) for e in clean_edges]
    out = {"T_ns": [r["T"] * 1e9 for r in rings],
           "mod_pk_pct": [r["mod_pk"] * 100 for r in rings],
           "shift_pct": [(r["T"] / c["T"] - 1) * 100 for r, c in zip(rings, cl)],
           "Q_ratio": sum((c["T"] / r["T"]) ** 3 for r, c in zip(rings, cl)) / 4}
    vref = vnom + dv
    out["bias_xo"] = xo_avg / vref
    out["cycles_in_window"] = f_rip * (edges[0][-1] - edges[0][0]) if f_rip else None
    # tone lock
    out["tone"] = None
    if f_rip:
        tl = []
        for r in range(4):
            p, q, d = tone_lock(edges[r], f_rip)
            cp, cq, cd = tone_lock(clean_edges[r], f_rip)
            locked = abs(d) < DRIFT_LOCK
            coincident = locked and abs(cd) < DRIFT_LOCK
            T_eq = (q / p) / f_rip                      # period a ring locked p:q to this tone would have
            pull = None if abs(cl[r]["T"] - T_eq) / cl[r]["T"] < 5e-4 else (cl[r]["T"] - rings[r]["T"]) / (cl[r]["T"] - T_eq)
            tl.append({"ring": r + 1, "p": p, "q": q, "drift_cycles": d, "clean_drift_cycles": cd, "pull_fraction": pull,
                       "state": "COINCIDENT" if coincident else ("LOCKED" if locked else "free")})
        out["tone"] = tl
    # pair lock and closeness
    pairs = []
    for i in range(4):
        for j in range(i + 1, 4):
            pl = pair_lock(edges[j], edges[i])      # ring i faster? use f_i/f_j with ring j as time base
            cpl = pair_lock(clean_edges[j], clean_edges[i])
            cd5 = closeness(rings[i]["T"], rings[j]["T"], DR5_RATIOS)
            c1 = closeness(rings[i]["T"], rings[j]["T"], PAIR_RATIOS)
            ccl5 = closeness(cl[i]["T"], cl[j]["T"], DR5_RATIOS)
            row = {"pair": f"{i+1}-{j+1}", "close_dr5_pct": cd5[0] * 100, "close_dr5_ratio": f"{cd5[1]}/{cd5[2]}",
                   "close_any_pct": c1[0] * 100, "close_any_ratio": f"{c1[1]}/{c1[2]}",
                   "clean_close_dr5_pct": ccl5[0] * 100}
            if pl:
                row.update(p=pl[0], q=pl[1], drift_cycles=pl[2], clean_drift_cycles=cpl[2] if cpl else None)
                row["locked"] = abs(pl[2]) < DRIFT_LOCK
                row["new_lock"] = row["locked"] and not (cpl and abs(cpl[2]) < DRIFT_LOCK)
            else:
                row["locked"] = row["new_lock"] = None
            pairs.append(row)
    out["pairs"] = pairs
    return out


def row_verdict(m):
    """(pass, [reasons]) under the DR-0003 criteria."""
    why = []
    if m.get("tone"):
        bad = [t for t in m["tone"] if t["state"] == "LOCKED"]
        if bad:
            why.append("LOCK: ring(s) " + ",".join(f"{t['ring']}({t['state']} {t['p']}:{t['q']})" for t in bad))
    nl = [p["pair"] for p in m["pairs"] if p.get("new_lock")]
    if nl:
        why.append("LOCK: new pair lock " + ",".join(nl))
    partial = m.get("cycles_in_window") is not None and m["cycles_in_window"] < 2
    if m["Q_ratio"] < 1 / Q_MARGIN and not partial:
        why.append(f"Q: ratio {m['Q_ratio']:.4f} < {1 / Q_MARGIN:.4f}")
    lo, hi = BIAS_BAND
    if not (lo <= m["bias_xo"] <= hi):
        why.append(f"BIAS: {m['bias_xo']:.4f} outside [{lo}, {hi}]")
    return (not why), why


def tolerance(rows, amps=(0.010, 0.050)):
    """rows: dicts with amp (V), ok (bool). Return (statement, detail).
    Tolerance = largest tested amplitude A such that every row at every
    amplitude <= A passes (non-monotone failures are not skipped over)."""
    ok_upto = None
    for a in sorted(amps):
        sel = [r for r in rows if r["amp"] <= a + 1e-12]
        if sel and all(r["ok"] for r in sel):
            ok_upto = a
        else:
            break
    first_fail = next((a for a in sorted(amps) if a > (ok_upto or 0) - 1e-12 and a != ok_upto), None)
    if ok_upto is None:
        return f"no tolerance found at {min(amps)*1e3:g} mV"
    if first_fail is None:
        return f">= {ok_upto*1e3:g} mV pk tested-safe (largest amplitude tested; upper bound not found)"
    return f">= {ok_upto*1e3:g} mV pk, < {first_fail*1e3:g} mV pk (bracketed; resolution limited to the tested amplitudes)"


# ---------------------------------------------------------------- response handling
def unit_measurements(corner):
    return {x["name"]: x["value"] for x in corner["measurements"] if x.get("value") is not None}


def edges_of(meas):
    return [[meas[f"t{r}_{k}"] for k in range(3, 3 + NEDGE)] for r in range(1, 5)]


def load_reqdir(reqdir):
    chunks = []
    for d in sorted(glob.glob(os.path.join(reqdir, "*-*-*"))):
        resp = os.path.join(d, "resp.json")
        if os.path.isfile(resp) and os.path.getsize(resp) > 0:     # a refused/unfinished request leaves it empty
            chunks.append((os.path.basename(d), json.load(open(os.path.join(d, "plan.json"))),
                           json.load(open(os.path.join(d, "resp.json")))))
    return chunks


def plan_vnom(plan):
    return plan["pvt"]["vnom"] + 0.0


def build_rows(chunks):
    """chunks: [(name, plan, resp)] -> {corner: [row...]} with metrics. Units are
    matched to plan entries by index; a failed unit is kept as an error row."""
    by_corner = {}
    for name, plan, resp in chunks:
        by_corner.setdefault(plan["corner"], []).append((name, plan, resp))
    result = {}
    for cn, items in by_corner.items():
        units = []
        for name, plan, resp in items:
            cs = resp["corners"]
            for u, c in zip(plan["units"], cs):
                units.append((name, plan, u, c))
        base = next((x for x in units if x[2]["kind"] == "baseline"), None)
        if base is None or base[3]["status"] != "pass":
            raise SystemExit(f"{cn}: no passing clean baseline unit; refusing to derive deltas")
        bm = unit_measurements(base[3])
        clean = edges_of(bm)
        bm_bias = bm["xo_avg"] / plan_vnom(base[1])
        rows = []
        for name, plan, u, c in units:
            row = {"chunk": name, "kind": u["kind"], "tone": u["tone"], "dv": u["dv"], "ra": u["ra"],
                   "rf_hz": u["rf"] if u["kind"] in ("tone", "control") else None, "ri_mA": u["ri"],
                   "amp": u.get("amp", u["ra"] if u["kind"] == "tone" else 0.0),
                   "klt_status": c["status"], "klt_corner_id": c["corner_id"]}
            pvt = plan["pvt"]
            try:
                m = unit_measurements(c)
                if c["status"] != "pass":
                    raise KeyError(f"klt status {c['status']}")
                row["vdd_pp_v"] = [m["vdd_min"], m["vdd_max"]]
                row["metrics"] = row_metrics(edges_of(m), clean, pvt["vnom"], u["dv"], m["xo_avg"], row["rf_hz"])
                row["metrics"]["edge_retention_proxy"] = 48 / (m["txo_b"] - m["txo_a"])
                row["metrics"]["xo_swing_frac"] = (m["xo_max"] - m["xo_min"]) / (pvt["vnom"] + u["dv"])
                ok, why = row_verdict(row["metrics"])
                row["ok"], row["why"] = ok, why
                row["ok_nobias"] = not any(w.startswith(("LOCK", "Q:")) for w in why)
                row["bias_shift"] = row["metrics"]["bias_xo"] - bm_bias
                row["unresolved"] = bool(row["metrics"]["tone"]) and any(t["state"] == "COINCIDENT" for t in row["metrics"]["tone"])
            except (KeyError, ZeroDivisionError, ValueError) as e:
                row["metrics"], row["ok"], row["ok_nobias"], row["why"] = None, False, False, [f"unusable unit: {e!r}"]
            rows.append(row)
        result[cn] = rows
    return result


def _qratio(T, T0):
    return sum((T0[i] / T[i]) ** 3 for i in range(4)) / 4


def quasi_static(rows, vnom):
    """Reduce the dv-stepped rows (ripple far below the ring frequency: the ring
    just tracks the instantaneous supply).  Per amplitude:
      Q_avg    time-average of the instantaneous Q ratio over one ripple cycle
               (Gauss-Chebyshev nodes 0, +-sqrt(3)/2 A, weight 1/3 each).  Variance
               accumulates per period as sigma_1^2/T^2 cycles^2, so the rate is
               ~ T^-3 and the cycle average is the mean of the node Q ratios, NOT
               the Q of the mean period.  Applies when the sample interval spans
               >= ~1 ripple cycle (f_rip >~ 1/Ts = 50 kHz).
      Q_worst  minimum node Q ratio (the trough).  Applies to a ripple slower than
               the sample interval, or a static droop of the same size.
    """
    out = {}
    base = next(r for r in rows if r["kind"] == "baseline")
    T0 = base["metrics"]["T_ns"]
    pts = [(0.0, 1.0, base["metrics"]["bias_xo"])]
    for amp in sorted({r["amp"] for r in rows if r["kind"] == "quasistatic"}):
        qs = {r["tone"].split("@")[0]: r for r in rows if r["kind"] == "quasistatic" and abs(r["amp"] - amp) < 1e-12}
        if len(qs) != 4 or any(r["metrics"] is None for r in qs.values()):
            out[amp] = {"error": "incomplete quasi-static node set"}
            continue
        mid = [qs["-0.866A"], qs["+0.866A"]]
        Qn = {k: _qratio(r["metrics"]["T_ns"], T0) for k, r in qs.items()}
        bn = {k: r["metrics"]["bias_xo"] for k, r in qs.items()}
        for k, r in qs.items():
            pts.append((r["dv"], Qn[k], bn[k]))
        mod = [(qs["+A"]["metrics"]["T_ns"][i] - qs["-A"]["metrics"]["T_ns"][i]) / (2 * T0[i]) * 100 for i in range(4)]
        Qavg = (1.0 + Qn["-0.866A"] + Qn["+0.866A"]) / 3
        Qworst = min(list(Qn.values()) + [1.0])
        bias_nodes = [base["metrics"]["bias_xo"]] + [r["metrics"]["bias_xo"] for r in mid]
        allb = bias_nodes + [qs["-A"]["metrics"]["bias_xo"], qs["+A"]["metrics"]["bias_xo"]]
        inband = lambda b: BIAS_BAND[0] <= b <= BIAS_BAND[1]
        out[amp] = {"mod_pk_pct": mod, "Q_nodes": Qn, "Q_avg": Qavg, "Q_worst": Qworst,
                    "bias_cycle_mean": sum(bias_nodes) / 3, "bias_min": min(allb), "bias_max": max(allb),
                    "ok_cycle_avg": Qavg >= 1 / Q_MARGIN and inband(sum(bias_nodes) / 3),
                    "ok_worst": Qworst >= 1 / Q_MARGIN and all(inband(b) for b in allb),
                    "ok_cycle_avg_nobias": Qavg >= 1 / Q_MARGIN, "ok_worst_nobias": Qworst >= 1 / Q_MARGIN}
    out["_droop_tol_mV"] = droop_tolerance(pts)
    return out


def droop_tolerance(pts):
    """Static supply droop (mV, below nominal) at which Q ratio falls to 1/Q_MARGIN,
    piecewise-linear through the measured (dv, Q) points on the negative side.
    None if no tested droop reaches the threshold."""
    neg = sorted({(dv, q) for dv, q, _ in pts if dv <= 0}, key=lambda x: -x[0])   # 0, -8.66, -10, ...
    thr = 1 / Q_MARGIN
    for (d0, q0), (d1, q1) in zip(neg, neg[1:]):
        if q0 >= thr > q1:
            return -(d0 + (q0 - thr) / (q0 - q1) * (d1 - d0)) * 1e3
    return None


def summarize(rows, vnom, amps):
    tone_rows = [r for r in rows if r["kind"] == "tone"]
    qs = quasi_static(rows, vnom)
    droop = qs.pop("_droop_tol_mV")
    tamps = sorted({r["amp"] for r in tone_rows})
    qrows_avg = [{"amp": a, "ok": v["ok_cycle_avg"]} for a, v in qs.items() if "ok_cycle_avg" in v]
    qrows_worst = [{"amp": a, "ok": v["ok_worst"]} for a, v in qs.items() if "ok_worst" in v]
    ctl = [r for r in rows if r["kind"] == "control"]
    fired = [r["tone"] for r in ctl if r["metrics"] and r["metrics"]["tone"][1]["state"] == "LOCKED"]
    # specificity: the clean baseline and every low-amplitude tone row read "free" for every ring
    # (the detector does not fire on unperturbed rings); counted over tone rows <= 50 mV
    lo = [t for r in tone_rows if r["amp"] <= 0.050 + 1e-12 and r["metrics"] for t in r["metrics"]["tone"]]
    spec = {"ring_tone_pairs_assessed": len(lo), "LOCKED": sum(t["state"] == "LOCKED" for t in lo),
            "COINCIDENT": sum(t["state"] == "COINCIDENT" for t in lo), "free": sum(t["state"] == "free" for t in lo)}
    # decisive = a control row detuned enough (>= 2%) that the clean ring slips > 0.1 cycle,
    # so LOCKED (not COINCIDENT) is the only state that can fire
    detector_ok = any("+2%" in t for t in fired)
    base = next(r for r in rows if r["kind"] == "baseline")
    return {"tolerance_rf_cycle_avg": tolerance([{"amp": r["amp"], "ok": r["ok"]} for r in tone_rows], tamps),
            "tolerance_rf_cycle_avg_ignoring_bias": tolerance([{"amp": r["amp"], "ok": r["ok_nobias"]} for r in tone_rows], tamps),
            "tolerance_slow_worst_node_ignoring_bias": tolerance([{"amp": a, "ok": v["ok_worst_nobias"]} for a, v in qs.items() if "ok_worst_nobias" in v], amps),
            "tolerance_slow_cycle_avg": tolerance(qrows_avg, amps),
            "tolerance_slow_worst_node": tolerance(qrows_worst, amps),
            "static_droop_tolerance_mV": droop,
            "quasi_static": {f"{a*1e3:g}mV": v for a, v in qs.items()},
            "baseline_mod_floor_pk_pct": base["metrics"]["mod_pk_pct"],
            "control_fired": fired, "detector_state_counts_le_50mV": spec,
            "detector_fires_on_negative_control": detector_ok,
            "tone_rows_failing": [(f"{r['amp']*1e3:g}mV", r["tone"], r["why"]) for r in tone_rows if not r["ok"]],
            "tone_rows_unresolved": [(f"{r['amp']*1e3:g}mV", r["tone"]) for r in tone_rows if r.get("unresolved")],
            "tone_rows_locked": [(f"{r['amp']*1e3:g}mV", r["tone"]) for r in tone_rows
                                 if r["metrics"] and any(t["state"] == "LOCKED" for t in r["metrics"]["tone"])]}


# ---------------------------------------------------------------- records
def _f(x, nd=3):
    return "-" if x is None else f"{x:.{nd}f}"


def render_md(rid, cn, pvt, rows, summ, jobs, sha, now, claim, supersedes="(none)"):
    fl = summ["baseline_mod_floor_pk_pct"]
    dt = summ["static_droop_tolerance_mV"]
    L = [f"# {rid} -- {SLUG}", "", f"**Claim**: {claim}", "",
         "**Level**: transistor (pre-layout `design/ro_array_core.spice`; deterministic transient, NO injected noise)",
         f"**PVT point**: {pvt['proc']} / {pvt['temp']:g} degC / {pvt['vnom']:g} V ({pvt['why']}). "
         f"**Seed**: N/A (deterministic; every row is one unit of a `klt sim` corners request).",
         f"**Status**: {PROV}. Not a silicon result, not an entropy measurement.", "",
         "**Batch jobs**: " + ", ".join(f"`{j}`" for j in jobs), "",
         "## Ripple tolerance (common-mode on vdd and vddr1..4)", "",
         f"- **RF ripple, 10 MHz up through the ring ladder and 2x (cycle-averaged Q; tone rows, 10/50/100/200 mV pk): {summ['tolerance_rf_cycle_avg']}**",
         f"  - the same, ignoring the bias band (LOCK + Q only): {summ['tolerance_rf_cycle_avg_ignoring_bias']}",
         f"- **Ripple far below the ring frequency, f_rip >~ 50 kHz (cycle-averaged Q, quasi-static family): {summ['tolerance_slow_cycle_avg']}**",
         f"- **Ripple slower than the sample interval, or static droop (trough Q): {summ['tolerance_slow_worst_node']}**",
         f"  - the same, ignoring the bias band: {summ['tolerance_slow_worst_node_ignoring_bias']}",
         "- **Static supply droop at which Q falls to 1/1.036 (interpolated): " +
         (f"{dt:.2f} mV below nominal**" if dt is not None else "not reached within the tested nodes**"), "",
         "Criteria are DR-0003's own margins: no ring/pair injection LOCK; Q_array ratio >= 1/1.036 "
         f"(T0^-3 term only, sigma_1 NOT re-measured under ripple); bias_xo in [{BIAS_BAND[0]}, {BIAS_BAND[1]}]. "
         f"Edge-time measurement floor from the clean run (peak period modulation per ring, %): {' '.join(f'{x:.2f}' for x in fl)} "
         "(timestep interpolation, not physics).", "",
         f"Negative control (current tone into ring 2's node n2): detector fires on the decisive (+2% detuned) control = "
         f"**{summ['detector_fires_on_negative_control']}**; LOCKED on: {summ['control_fired'] or 'none'}. "
         f"Detector state counts over all ring x tone pairs in the <= 50 mV rows: {summ['detector_state_counts_le_50mV']} (the LOCKED ones are real: see the tone table; the unperturbed baseline is not a tone row).", "",
         f"Rows LOCKED by the supply ripple itself: {summ['tone_rows_locked'] or 'none'}. "
         f"Rows with the tone inside the window resolution of a ring frequency (lock vs coincidence UNRESOLVED): "
         f"{len(summ['tone_rows_unresolved'])}.", "",
         "## Tone rows (common ripple)", "",
         "| amp (mV pk) | tone | rf (MHz) | max mod pk % | max shift % | Q ratio | bias_xo (shift vs clean) | tone lock (ring:state p:q drift) | min DR-0005 closeness % | verdict |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] not in ("tone", "baseline"):
            continue
        m = r["metrics"]
        if m is None:
            L.append(f"| {r['amp']*1e3:g} | {r['tone']} | - | - | - | - | - | - | - | **FAIL** {r['why']} |")
            continue
        tl = "-" if not m["tone"] else " ".join(f"{t['ring']}:{t['state']} {t['p']}:{t['q']} {t['drift_cycles']:+.2f}" + (f" pull {t['pull_fraction']:.2f}" if t["state"] == "LOCKED" and t.get("pull_fraction") is not None else "") for t in m["tone"] if t["state"] != "free") or "none"
        close = min(p["close_dr5_pct"] for p in m["pairs"])
        L.append(f"| {r['amp']*1e3:g} | {r['tone']} | {_f(r['rf_hz']/1e6 if r['rf_hz'] else None, 2)} | {max(m['mod_pk_pct']):.3f} | "
                 f"{max(abs(x) for x in m['shift_pct']):.3f} | {m['Q_ratio']:.4f} | {m['bias_xo']:.4f} ({r['bias_shift']:+.3f}) | {tl} | {close:.2f} | "
                 + (("PASS" if r["ok"] else "**FAIL** " + "; ".join(r["why"])) + (" (lock UNRESOLVED: tone within window resolution of a ring frequency)" if r.get("unresolved") else "")) + " |")
    L += ["", "## Quasi-static family (ripple far below the ring frequency, incl. the 50 kbps sample rate)", "",
          "The ring tracks the instantaneous supply, so the supply is stepped to the sine's extremes and Gauss-Chebyshev nodes "
          "instead of simulating a 20 us period. Q_avg = cycle average of the per-node Q ratio (applies when a sample interval spans "
          ">= 1 ripple cycle); Q_worst = trough node (a slower ripple, or a static droop).", "",
          "| amp | per-ring pk period mod % (r1..r4) | Q ratio at nodes -A / -0.866A / +0.866A / +A | Q_avg | Q_worst | bias cycle mean | bias min..max | cycle-avg verdict | trough verdict |",
          "|---|---|---|---|---|---|---|---|---|"]
    for a, v in summ["quasi_static"].items():
        if "error" in v:
            L.append(f"| {a} | {v['error']} |")
            continue
        qn = v["Q_nodes"]
        L.append(f"| {a} | {' '.join(f'{x:.3f}' for x in v['mod_pk_pct'])} | "
                 f"{qn['-A']:.4f} / {qn['-0.866A']:.4f} / {qn['+0.866A']:.4f} / {qn['+A']:.4f} | {v['Q_avg']:.4f} | {v['Q_worst']:.4f} | "
                 f"{v['bias_cycle_mean']:.4f} | {v['bias_min']:.4f}..{v['bias_max']:.4f} | {'PASS' if v['ok_cycle_avg'] else 'FAIL'} | {'PASS' if v['ok_worst'] else 'FAIL'} |")
    L += ["", "## Negative control rows (ring 2, sinusoidal current into node n2)", "",
          "| tone | rf (MHz) | ring-2 state | p:q | drift (ring cycles) | clean drift | flagged |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] != "control" or not r["metrics"]:
            continue
        t = r["metrics"]["tone"][1]
        L.append(f"| {r['tone']} | {r['rf_hz']/1e6:.2f} | {t['state']} | {t['p']}:{t['q']} | {t['drift_cycles']:+.3f} | {t['clean_drift_cycles']:+.3f} | {'YES' if t['state'] == 'LOCKED' else 'no'} |")
    L += ["", "## Per-row pair data", "",
          "Per-pair DR-0005 closeness (to 2/1, 3/2, 4/3), closeness including 1:1, and pair-lock drift are in the `.json` "
          "(`rows[].metrics.pairs`). Clean-baseline DR-0005 closeness per pair: " +
          ", ".join(f"{p['pair']} {p['clean_close_dr5_pct']:.2f}%" for p in next(r for r in rows if r["kind"] == "baseline")["metrics"]["pairs"]) + ".", ""]
    L += ["---", "", "- Author: loom-builder@sky130-trng", f"- Timestamp (UTC): {now.isoformat()}", f"- Repo commit: `{sha}`",
          f"- Supersedes: {supersedes}"]
    return "\n".join(L) + "\n"


CLAIM = ("Supply-ripple / injection-lock robustness of the committed pre-layout ro_array_core (issue #200): "
         "common-mode sinusoidal ripple of 10, 50, 100 and 200 mV pk on vdd and vddr1..4 at the ring-ladder frequencies "
         "(own, +0.5% detuned, just outside), sub-harmonics, 2x, 10 MHz and the quasi-static (50 kbps) limit; per-ring "
         "period modulation, ring-vs-tone and ring-vs-ring injection-lock closeness, combining-node bias; ring-local "
         "current-injection negative control; deterministic, no injected noise")
PVTS = None


def emit_record(reqdir, sha=None):
    import importlib.util
    from evidence_record import git_short_sha
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("make_requests", os.path.join(os.path.dirname(__file__), "make-requests.py"))
    mr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mr)
    sha = sha or git_short_sha(Path(REPO))
    chunks = load_reqdir(reqdir)
    allrows = build_rows(chunks)
    base_now = datetime.datetime.now(datetime.timezone.utc)
    for n, cn in enumerate(sorted(allrows), 1):
        now = base_now + datetime.timedelta(seconds=n)
        rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
        pvt = dict(mr.CORNERS[cn])
        pvt.pop("tr")
        rows = allrows[cn]
        summ = summarize(rows, pvt["vnom"], (0.010, 0.050))
        mine = [(nm, pl, rs) for nm, pl, rs in chunks if pl["corner"] == cn]
        jobs = [rs["environment"]["remote"]["job_id"] for _, _, rs in mine]
        cdir = os.path.join(REPO, "sim", SLUG, "corners", rid)
        rdir = os.path.join(REPO, "sim", SLUG, "records")
        if os.path.exists(os.path.join(rdir, rid + ".json")) or os.path.exists(cdir):
            raise SystemExit(f"error: {rid} exists")
        os.makedirs(cdir)
        os.makedirs(rdir, exist_ok=True)
        for nm, pl, rs in mine:
            with gzip.open(os.path.join(cdir, f"{nm}.klt-sim.json.gz"), "wt") as fh:   # raw response, verbatim
                json.dump(rs, fh, indent=1)
            json.dump(pl, open(os.path.join(cdir, f"{nm}.plan.json"), "w"), indent=1)
            for fn, dst in (("request.json", f"{nm}.request.json"), ("netlist.cir", f"{nm}.netlist.cir")):
                shutil.copyfile(os.path.join(reqdir, nm, fn), os.path.join(cdir, dst))   # exactly what was submitted
        rec = {"record_id": rid, "slug": SLUG, "claim": CLAIM, "level": "transistor", "status": PROV,
               "seed": "N/A (deterministic transient, no injected noise)", "pvt": pvt,
               "criteria": {"drift_lock_ring_cycles": DRIFT_LOCK, "q_margin": Q_MARGIN, "bias_band": list(BIAS_BAND)},
               "testbench": "sim/ro-array-supply-perturbation/testbench/tb_ro_array_supply_perturbation.spice "
                            "(via sim/ro-array-supply-perturbation/make-requests.py)",
               "klt_sim": {"jobs": jobs, "backend": "batch", "remote": [rs["environment"]["remote"] for _, _, rs in mine],
                           "engine_version": mine[0][2]["environment"]["engine_version"],
                           "models_lib_sha256": mine[0][2]["environment"]["models_lib_sha256"],
                           "submitter_klt": mine[0][2]["provenance"]["klt_version"],
                           "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"},
               "supersedes": "(none)", "summary": summ, "rows": rows, "timestamp_utc": now.isoformat()}
        json.dump(rec, open(os.path.join(rdir, rid + ".json"), "w"), indent=2, default=str)
        open(os.path.join(rdir, rid + ".md"), "w").write(render_md(rid, cn, pvt, rows, summ, jobs, sha, now, CLAIM))
        print(rid, cn, summ["tolerance_rf_cycle_avg"], "| detector fires:", summ["detector_fires_on_negative_control"])


def check(recpath):
    """Replay a record from its committed raw responses; exit 1 on any difference."""
    rec = json.load(open(recpath))
    cdir = os.path.join(REPO, "sim", SLUG, "corners", rec["record_id"])
    chunks = []
    for f in sorted(glob.glob(os.path.join(cdir, "*.klt-sim.json.gz"))):
        nm = os.path.basename(f)[:-len(".klt-sim.json.gz")]
        with gzip.open(f, "rt") as fh:
            chunks.append((nm, json.load(open(os.path.join(cdir, nm + ".plan.json"))), json.load(fh)))
    rows = build_rows(chunks)[next(iter({pl["corner"] for _, pl, _ in chunks}))]
    summ = summarize(rows, rec["pvt"]["vnom"], (0.010, 0.050))
    same = json.loads(json.dumps(rows, default=str)) == rec["rows"] and json.loads(json.dumps(summ, default=str)) == rec["summary"]
    print("replay", "MATCHES" if same else "DIFFERS", recpath)
    return 0 if same else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "--emit-record":
        emit_record(a[1])
    elif len(a) == 2 and a[0] == "--check":
        sys.exit(check(a[1]))
    else:
        print(__doc__)
        sys.exit(2)
