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
edges, 39 periods; the issue #288 lock-resolution campaign extends the window to
200/400 edges -- plans carry "nedge" and the detector math is window-generic).
There is deliberately NO injected noise: every figure here
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
LR = "lock-resolution"           # make-requests.py --campaign lr (issue #288): 200/400-edge windows
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


def edges_of(meas, nedge=NEDGE):
    return [[meas[f"t{r}_{k}"] for k in range(3, 3 + nedge)] for r in range(1, 5)]


def load_reqdir(reqdir):
    return load_reqdir_all(reqdir)[0]


def _submit_error(d):
    """Why a request directory has no usable response: the klt error message if
    the client wrote one, else a generic not-completed note.  Never raises."""
    for fn in ("resp.json", "klt.log"):
        p = os.path.join(d, fn)
        try:
            txt = open(p).read()
        except OSError:
            continue
        if not txt.strip():
            continue
        try:
            msg = json.loads(txt).get("error", {}).get("message")
            if msg:
                return msg
        except (ValueError, AttributeError):
            pass
        return txt.strip()[-600:]
    return "no response: request not submitted or submission did not complete"


def load_reqdir_all(reqdir):
    """-> (chunks, missing).  chunks = [(name, plan, resp)] for requests with a
    response; missing = [(name, plan, reason)] for requests that were refused,
    failed or never completed, so a record can carry them as explicit rows
    instead of silently dropping them (issue #288 evidence requirement)."""
    chunks, missing = [], []
    for d in sorted(glob.glob(os.path.join(reqdir, "*-*-*"))):
        nm = os.path.basename(d)
        if not os.path.isfile(os.path.join(d, "plan.json")):
            continue
        plan = json.load(open(os.path.join(d, "plan.json")))
        resp = os.path.join(d, "resp.json")
        rs = None
        if os.path.isfile(resp) and os.path.getsize(resp) > 0:     # a refused/unfinished request leaves it empty
            try:
                rs = json.load(open(resp))
            except ValueError:
                rs = None
        if rs is not None and "corners" in rs:
            chunks.append((nm, plan, rs))
        else:
            missing.append((nm, plan, _submit_error(d)))
    return chunks, missing


def observed_window(meas, nedge):
    """Observed window per ring: how many of the requested rising edges came
    back, and the time span they cover.  Recorded for every campaign row so an
    insufficient or truncated window is visible, not inferred."""
    obs, span = [], []
    for r in range(1, 5):
        ts = [meas[f"t{r}_{k}"] for k in range(3, 3 + nedge) if f"t{r}_{k}" in meas]
        obs.append(len(ts))
        span.append((max(ts) - min(ts)) * 1e9 if len(ts) > 1 else None)
    return {"edges_requested": nedge, "edges_observed": obs, "span_ns": span}


def _missing_row(name, plan, u, status, reason):
    row = {"chunk": name, "kind": u["kind"], "tone": u["tone"], "dv": u["dv"], "ra": u["ra"],
           "rf_hz": u["rf"] if u["kind"] in ("tone", "control") else None, "ri_mA": u["ri"],
           "amp": u.get("amp", u["ra"] if u["kind"] == "tone" else 0.0),
           "klt_status": status, "klt_corner_id": None}
    if "nedge" in plan:
        row["nedge"] = plan["nedge"]
    if "detune" in u:
        row["detune"] = u["detune"]
    row["metrics"], row["ok"], row["ok_nobias"], row["why"] = None, False, False, [f"{status}: {reason}"]
    return row


def plan_vnom(plan):
    return plan["pvt"]["vnom"] + 0.0


def build_rows(chunks, missing=()):
    """chunks: [(name, plan, resp)] -> {corner: [row...]} with metrics. Units are
    matched to plan entries by index; a failed unit is kept as an error row.

    Campaign plans (carrying "nedge") additionally get: a clean baseline matched
    to the row's own window length (a 400-edge row is compared with the 400-edge
    baseline, never a 200-edge one); explicit rows for units the response did not
    return and for every unit of a request in `missing` [(name, plan, reason)];
    and the observed window per row.  Legacy plans take the original path
    unchanged so the #200 records replay byte-for-byte."""
    by_corner = {}
    for name, plan, resp in chunks:
        by_corner.setdefault(plan["corner"], []).append((name, plan, resp))
    miss_by_corner = {}
    for name, plan, reason in missing:
        miss_by_corner.setdefault(plan["corner"], []).append((name, plan, reason))
        by_corner.setdefault(plan["corner"], [])
    result = {}
    for cn, items in by_corner.items():
        units, absent = [], []
        for name, plan, resp in items:
            cs = resp["corners"]
            for u, c in zip(plan["units"], cs):
                units.append((name, plan, u, c))
            if "nedge" in plan:
                for u in plan["units"][len(cs):]:   # response returned fewer units than planned
                    absent.append(_missing_row(name, plan, u, "not-returned",
                                               f"response carries {len(cs)} of {len(plan['units'])} units"))
        for name, plan, reason in miss_by_corner.get(cn, []):
            for u in plan["units"]:
                absent.append(_missing_row(name, plan, u, "missing", reason))
        campaign = any("nedge" in x[1] for x in units) or bool(absent)
        bases = {}
        for x in units:
            if x[2]["kind"] == "baseline" and x[3]["status"] == "pass":
                bases.setdefault(x[1].get("nedge", NEDGE), x)
        if not campaign:
            base = next((x for x in units if x[2]["kind"] == "baseline"), None)
            if base is None or base[3]["status"] != "pass":
                raise SystemExit(f"{cn}: no passing clean baseline unit; refusing to derive deltas")
            bases = {base[1].get("nedge", NEDGE): base}
        clean_by_n = {}
        for n, base in bases.items():
            bm = unit_measurements(base[3])
            clean_by_n[n] = (edges_of(bm, n), bm["xo_avg"] / plan_vnom(base[1]))
        rows = []
        for name, plan, u, c in units:
            n = plan.get("nedge", NEDGE)
            if n not in clean_by_n:
                row = _missing_row(name, plan, u, c["status"],
                                   f"no passing clean baseline at the {n}-edge window; deltas not derived")
                row["klt_corner_id"] = c["corner_id"]
                row["window"] = observed_window(unit_measurements(c), n)
                rows.append(row)
                continue
            clean, bm_bias = clean_by_n[n]
            row = {"chunk": name, "kind": u["kind"], "tone": u["tone"], "dv": u["dv"], "ra": u["ra"],
                   "rf_hz": u["rf"] if u["kind"] in ("tone", "control") else None, "ri_mA": u["ri"],
                   "amp": u.get("amp", u["ra"] if u["kind"] == "tone" else 0.0),
                   "klt_status": c["status"], "klt_corner_id": c["corner_id"]}
            if "nedge" in plan:                     # campaign rows carry their requested window;
                row["nedge"] = plan["nedge"]        # legacy rows stay key-free (replay-identical)
            if "detune" in u:
                row["detune"] = u["detune"]
            pvt = plan["pvt"]
            if "nedge" in plan:
                row["window"] = observed_window(unit_measurements(c), n)
            try:
                m = unit_measurements(c)
                if c["status"] != "pass":
                    raise KeyError(f"klt status {c['status']}")
                row["vdd_pp_v"] = [m["vdd_min"], m["vdd_max"]]
                row["metrics"] = row_metrics(edges_of(m, plan.get("nedge", NEDGE)), clean, pvt["vnom"], u["dv"], m["xo_avg"], row["rf_hz"])
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
        result[cn] = rows + absent
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


def _trio(r):
    """The three criteria SEPARATELY for a usable row (issue #288: a bias
    failure must not hide behind a lock-only result)."""
    why = r.get("why") or []
    return {"LOCK": not any(w.startswith("LOCK") for w in why),
            "Q": not any(w.startswith("Q:") for w in why),
            "BIAS": not any(w.startswith("BIAS") for w in why)}


def _tone_ring(tone):
    return int(tone[1]) if tone.startswith("f") and len(tone) > 1 and tone[1].isdigit() else 1


def summarize_lr(rows):
    """Issue #288 lock-resolution summary. LOCK, Q and BIAS are reported
    separately; on-frequency rows stay drift-UNRESOLVED (exact coincidence is
    unidentifiable by drift at any window); the 400-edge subset checks that the
    representative rows converge under the longer window."""
    tone = [r for r in rows if r["kind"] == "tone"]
    ctl = [r for r in rows if r["kind"] == "control"]
    nedges = sorted({r.get("nedge", NEDGE) for r in rows})
    out = {"nedge": nedges,
           "detuning_resolution_pct": {n: round(DRIFT_LOCK / (n - 1) * 100, 4) for n in nedges},
           "baseline_T_ns": {n: next((r["metrics"]["T_ns"] for r in rows if r["kind"] == "baseline"
                                      and r.get("nedge", NEDGE) == n and r["metrics"]), None) for n in nedges},
           "rows_planned": len(rows),
           "rows_usable": sum(1 for r in rows if r["metrics"]),
           "rows_unusable": [{"chunk": r["chunk"], "kind": r["kind"], "tone": r["tone"],
                              "amp_mV": round(r["amp"] * 1e3, 3), "nedge": r.get("nedge", NEDGE),
                              "klt_status": r["klt_status"], "why": r["why"]}
                             for r in rows if r["metrics"] is None]}
    us = [r for r in tone if r["metrics"]]
    # measured lock brackets: per amplitude x ring x side, the state of the ring the
    # tone was placed next to, at each tested detuning.  Two readings:
    #   nominal  -- the ladder as designed (relative to the committed combining-record
    #               period); on-frequency rows excluded (drift-UNRESOLVED by design);
    #   eff      -- the tone's detuning from the CLEAN ring in this window,
    #               clean_drift/(N-1), which is what the drift criterion actually
    #               sees.  The clean ring can sit ~0.1-0.2 % off the committed period
    #               (ff), so a nominal +0.1 % row can be effectively on-frequency and a
    #               nominal on-frequency row effectively detuned.  Points within the
    #               window resolution of the clean ring are listed but bound nothing.
    res = DRIFT_LOCK / (nedges[0] - 1) * 100

    def _stmt(pts):
        lk = [d for d, s in pts if s == "LOCKED"]
        fr = [d for d, s in pts if s == "free"]
        if not lk and fr:
            return f"no lock at any tested detuning; lock range (if any) < {min(fr):.3g} %"
        if lk and not [d for d in fr if d > max(lk)]:
            return f"locked out to {max(lk):.3g} % (largest tested); edge not bracketed"
        if lk:
            nxt = min(d for d in fr if d > max(lk))
            st = f"lock-range edge in ({max(lk):.3g}, {nxt:.3g}] %"
            return st + (" (non-monotone: free below a locked detuning)" if any(d < max(lk) for d in fr) else "")
        return "no LOCKED/free reading at the tested detunings (unusable or COINCIDENT only)"

    per = {}
    for r in tone:
        if r.get("nedge", NEDGE) != nedges[0]:              # primary window only; 400-edge rows are the
            continue                                        # convergence check, reported separately
        ring = _tone_ring(r["tone"])
        d = r.get("detune", 0.0)
        st = r["metrics"]["tone"][ring - 1]["state"] if r["metrics"] else "unusable"
        eff = (r["metrics"]["tone"][ring - 1]["clean_drift_cycles"] / (nedges[0] - 1) * 100
               if r["metrics"] else None)
        per.setdefault((round(r["amp"] * 1e3, 3), ring), []).append((d * 100, eff, st))
    brackets = []
    for (amp, ring), pts in sorted(per.items()):
        for side, sg in (("+", 1), ("-", -1)):
            nom = sorted((abs(d), st) for d, _, st in pts if d * sg > 0)
            effp = sorted((abs(e), st) for _, e, st in pts if e is not None and e * sg > 0 and abs(e) >= res)
            if not nom and not effp:
                continue
            brackets.append({
                "amp_mV": amp, "ring": ring, "side": side,
                "states": {f"{abs(d):g}%": st for d, _, st in sorted(pts, key=lambda x: abs(x[0])) if d * sg > 0},
                "eff_detune_pct": {f"{abs(d):g}%": (None if e is None else round(e, 4))
                                   for d, e, _ in pts if d * sg > 0},
                "bracket": _stmt(nom) if nom else "no detuned row on this side",
                "bracket_eff": (_stmt(effp) if effp else "no point outside the window resolution on this side")})
    eff_on = [{"amp_mV": amp, "ring": ring, "eff_detune_pct": round(e, 4), "state": st}
              for (amp, ring), pts in sorted(per.items()) for d, e, st in pts if d == 0 and e is not None]
    out["on_frequency_effective"] = eff_on
    out["lock_brackets"] = brackets
    out["locked"] = [{"amp_mV": round(r["amp"] * 1e3), "tone": r["tone"], "ring": t["ring"],
                      "p_q": f"{t['p']}:{t['q']}", "drift_cycles": t["drift_cycles"],
                      "pull_fraction": t["pull_fraction"]}
                     for r in us for t in r["metrics"]["tone"] if t["state"] == "LOCKED"]
    lr_by_amp = {}
    for r in us:
        d = abs(r.get("detune", 0.0)) * 100
        if d and any(t["state"] == "LOCKED" for t in r["metrics"]["tone"]):
            a = round(r["amp"] * 1e3)
            lr_by_amp[a] = max(lr_by_amp.get(a, 0.0), d)
    out["lock_range_pct_by_amp"] = lr_by_amp
    out["on_frequency_unresolved"] = [
        {"amp_mV": round(r["amp"] * 1e3), "tone": r["tone"],
         "ring_states": {t["ring"]: t["state"] for t in r["metrics"]["tone"] if t["state"] != "free"},
         "mod_pk_pct": r["metrics"]["mod_pk_pct"], "shift_pct": r["metrics"]["shift_pct"],
         "pull_fractions": {t["ring"]: t["pull_fraction"] for t in r["metrics"]["tone"]
                            if t["pull_fraction"] is not None}}
        for r in us if r.get("unresolved")]
    out["verdict_counts"] = {"tone_rows_planned": len(tone), "tone_rows_unusable": len(tone) - len(us),
                             "tone_rows": len(us),
                             "LOCK_pass": sum(_trio(r)["LOCK"] for r in us),
                             "Q_pass": sum(_trio(r)["Q"] for r in us),
                             "BIAS_pass": sum(_trio(r)["BIAS"] for r in us)}
    def _lab(r):
        n = r.get("nedge", NEDGE)
        return f"{r['tone']}@{r['amp']*1e3:g}mV" + ("" if n == nedges[0] else f"/{n}e")
    out["failing_only_bias"] = [_lab(r) for r in us if r["ok_nobias"] and not r["ok"]]
    out["failing_lock_or_q"] = [_lab(r) for r in us if not r["ok_nobias"]]
    out["controls"] = [{"tone": r["tone"], "state": r["metrics"]["tone"][1]["state"],
                        "drift_cycles": r["metrics"]["tone"][1]["drift_cycles"],
                        "clean_drift_cycles": r["metrics"]["tone"][1]["clean_drift_cycles"],
                        "flagged": r["metrics"]["tone"][1]["state"] == "LOCKED"}
                       for r in ctl if r["metrics"]]
    at200 = {(r["tone"], round(r["amp"], 6)): r for r in us if r.get("nedge", NEDGE) == 200}
    conv = []
    conv_missing = []
    for r in tone:
        if r.get("nedge") != 400:
            continue
        m = at200.get((r["tone"], round(r["amp"], 6)))
        if not (r["metrics"] and m and m["metrics"]):
            conv_missing.append({"tone": r["tone"], "amp_mV": round(r["amp"] * 1e3),
                                 "have_400": bool(r["metrics"]), "have_200": bool(m and m["metrics"])})
            continue
        ring = _tone_ring(r["tone"]) - 1
        s2, s4 = m["metrics"]["tone"][ring], r["metrics"]["tone"][ring]
        conv.append({"tone": r["tone"], "amp_mV": round(r["amp"] * 1e3),
                     "at_200_edges": {"state": s2["state"], "drift_cycles": s2["drift_cycles"]},
                     "at_400_edges": {"state": s4["state"], "drift_cycles": s4["drift_cycles"]},
                     "drift_ratio_400_over_200": (s4["drift_cycles"] / s2["drift_cycles"]
                                                  if s2["drift_cycles"] else None),
                     "drift_ratio_free_running_expected": 399 / 199,
                     "converged": s2["state"] == s4["state"]})
    out["convergence_200_vs_400"] = conv
    out["convergence_unpaired"] = conv_missing
    out["converged_all"] = all(c["converged"] for c in conv) if conv else None
    return out


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


def render_lr_md(rid, pvt, rows, summ, jobs, sha, now, inputs=None, history=None):
    inputs = inputs or {}
    nmiss = len(summ["rows_unusable"])
    L = [f"# {rid} -- {SLUG} (lock-resolution, issue #288)", "",
         f"**Claim**: {LR_CLAIM}", "",
         "**Level**: transistor (pre-layout `design/ro_array_core.spice`; deterministic transient, NO injected noise)",
         f"**PVT point**: {pvt['proc']} / {pvt['temp']:g} degC / {pvt['vnom']:g} V ({pvt['why']}). "
         f"**Seed**: N/A (deterministic; every row is one unit of a `klt sim` corners request).",
         f"**Status**: {PROV}. Pre-layout, deterministic, ideal sources; not a silicon result, not an entropy "
         "measurement, no spec or threshold change.", "",
         "**Batch jobs**: " + (", ".join(f"`{j}`" for j in jobs) or "none returned"), "",
         f"**Coverage**: {summ['rows_usable']} of {summ['rows_planned']} planned rows usable; {nmiss} missing / "
         "failed / unusable rows are listed below, never silently dropped.", "",
         "**Window & resolution**: a free-running ring detuned by delta from the tone slips delta*(N-1) ring cycles "
         "across an N-edge window, so the 0.1-cycle DRIFT_LOCK criterion resolves "
         + ", ".join(f"{n} edges -> {DRIFT_LOCK / (n - 1) * 100:.3g} %" for n in summ["nedge"]) +
         "; the campaign claims +-0.1 % (2x margin at the 200-edge window) and checks convergence at 400 edges. "
         "Every usable row carries all of its requested edge measurements; the observed edge count and span per "
         "ring are in `rows[].window`.", "",
         "## Measured brackets", "",
         "Only what the tested ladder shows (amplitudes 5, 20, 50 mV pk; detunings +-0.1, +-0.25, +-0.4 % at "
         "20/50 mV and +-0.25 % at 5 mV), nominal detuning relative to the committed ring period; `eff` is the tone's "
         "detuning from the CLEAN ring in this window (clean drift / (N-1)), which is what the drift criterion sees. "
         "LOCKED means the mean slip stayed under 0.1 cycle over the window: a ring pulled to within the resolution but "
         "still slipping slowly (just outside an Adler lock range) is indistinguishable here and reads LOCKED -- the "
         "conservative direction for the LOCK criterion. State of the ring the tone was placed next to:", "",
         f"| amp (mV) | ring | nominal side | states by nominal detuning ({summ['nedge'][0]}-edge window) | bracket (nominal) | bracket (eff, same-sign points) |",
         "|---|---|---|---|---|---|"]
    for b in summ["lock_brackets"]:
        st = ", ".join(f"{k}" + (f" (eff {b['eff_detune_pct'][k]:+.3f}%)" if b["eff_detune_pct"].get(k) is not None else "")
                       + f": {v}" for k, v in b["states"].items())
        L.append(f"| {b['amp_mV']:g} | {b['ring']} | {b['side']} | {st} | {b['bracket']} | {b['bracket_eff']} |")
    if summ.get("on_frequency_effective"):
        L += ["", "Nominal on-frequency rows, with the tone's effective detuning from the clean ring in this window "
              f"(|eff| < {DRIFT_LOCK / (summ['nedge'][0] - 1) * 100:.3g} % is within the window resolution, hence "
              "COINCIDENT/UNRESOLVED; outside it the row is an ordinary detuned reading): "
              + "; ".join(f"{o['amp_mV']:g} mV f{o['ring']}: eff {o['eff_detune_pct']:+.3f} % -> {o['state']}"
                          for o in summ["on_frequency_effective"]) + "."]
    L += ["",
          f"- Rows with any ring LOCKED to the tone: {len(summ['locked'])}. Largest locked detune per amplitude "
          f"(mV: max detune %): {summ['lock_range_pct_by_amp'] or 'none'}.",
          f"- On-frequency rows drift-UNRESOLVED: {len(summ['on_frequency_unresolved'])} (exact coincidence is "
          "unidentifiable by drift at any window; read them with the detuned neighbours in the table above).",
          f"- Criterion verdicts over usable tone rows, reported separately: {summ['verdict_counts']}. "
          f"Failing ONLY the bias band (LOCK and Q pass): {summ['failing_only_bias'] or 'none'}. "
          f"Failing LOCK or Q: {summ['failing_lock_or_q'] or 'none'}. A bias failure does not disappear behind a "
          "lock-only result.",
          "- 200- vs 400-edge convergence: "
          + ("no pair available" if summ["converged_all"] is None else
             ("all paired rows converged" if summ["converged_all"] else "NOT all converged -- see table"))
          + (f"; unpaired: {summ['convergence_unpaired']}" if summ["convergence_unpaired"] else "") + ".", "",
          "## Hypotheses (not measured here)", "",
          "- The lock range between tested detunings, and at amplitudes between/above the tested rungs, is "
          "interpolation only.",
          "- Whether an on-frequency tone locks a ring or merely coincides with it is not decided by drift; the "
          "detuned-neighbour reading is an inference.",
          "- Per-ring (uncorrelated) ripple, supply impedance, substrate coupling and layout parasitics are not "
          "modelled; post-layout and silicon may differ.", "",
          "## Tone rows", "",
          "The LOCK / Q / BIAS columns are the three criteria SEPARATELY; verdict = PASS only if all three hold. "
          "An on-frequency row (detune 0 %) is drift-UNRESOLVED by construction, not passed and not failed.", "",
          "| N | amp (mV) | tone | rf (MHz) | max mod pk % | max shift % | Q ratio | bias_xo (shift) | non-free rings (state p:q drift) | LOCK | Q | BIAS | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] not in ("tone", "baseline"):
            continue
        m = r["metrics"]
        N = r.get("nedge", NEDGE)
        if m is None:
            L.append(f"| {N} | {r['amp']*1e3:g} | {r['tone']} | - | - | - | - | - | - | - | - | - | "
                     f"**{r['klt_status'].upper()}** {'; '.join(r['why'])[:300]} |")
            continue
        nf = " ".join(f"r{t['ring']}:{t['state']} {t['p']}:{t['q']} {t['drift_cycles']:+.2f}" +
                      (f" pull {t['pull_fraction']:.2f}" if t["state"] == "LOCKED" and t.get("pull_fraction") is not None else "")
                      for t in (m["tone"] or []) if t["state"] != "free") or "none"
        t3 = _trio(r)
        verdict = "PASS" if r["ok"] else "**FAIL** " + "; ".join(r["why"])
        if r.get("unresolved"):
            verdict += " (drift-UNRESOLVED: on-frequency)"
        L.append(f"| {N} | {r['amp']*1e3:g} | {r['tone']} | {_f(r['rf_hz']/1e6 if r['rf_hz'] else None, 3)} | {max(m['mod_pk_pct']):.3f} | "
                 f"{max(abs(x) for x in m['shift_pct']):.3f} | {m['Q_ratio']:.4f} | {m['bias_xo']:.4f} ({r['bias_shift']:+.3f}) | {nf} | "
                 f"{'pass' if t3['LOCK'] else 'FAIL'} | {'pass' if t3['Q'] else 'FAIL'} | {'pass' if t3['BIAS'] else 'FAIL'} | {verdict} |")
    L += ["", "## Current-injection controls (ring 2, node n2)", "",
          "Detector controls. At +2/+5/+20 % the CLEAN ring slips ~0.4/~10/~40 cycles against the injected tone over "
          "the 200-edge window, so the clean run is the free-running reference and a LOCKED reading there can only be a "
          "true injection lock (sensitivity); the own-frequency rows are COINCIDENT by construction. Whether the injected "
          "ring stays free at a given detuning is the measurement, not an assumption (#200 already saw +20 % lock at "
          "these injection levels).", "",
          "| tone | ring-2 state | drift (ring cycles) | clean drift | flagged |", "|---|---|---|---|---|"]
    for c in summ["controls"]:
        L.append(f"| {c['tone']} | {c['state']} | {c['drift_cycles']:+.3f} | {c['clean_drift_cycles']:+.3f} | "
                 f"{'YES' if c['flagged'] else 'no'} |")
    for r in rows:
        if r["kind"] == "control" and r["metrics"] is None:
            L.append(f"| {r['tone']} | **{r['klt_status'].upper()}** | - | - | - |")
    L += ["", "## 200- vs 400-edge convergence subset (ring 2, +-0.25 % @ 50 mV)", "",
          "Converged = same state at both windows. The 400/200 drift ratio is 399/199 = 2.005 only for an unperturbed "
          "ring; a pulled-but-unlocked ring slips non-uniformly within a beat period, so its ratio departs from that "
          "without changing the state.", "",
          "| tone | amp (mV) | 200-edge state (drift cyc) | 400-edge state (drift cyc) | drift ratio 400/200 | converged |",
          "|---|---|---|---|---|---|"]
    for c in summ["convergence_200_vs_400"]:
        L.append(f"| {c['tone']} | {c['amp_mV']} | {c['at_200_edges']['state']} ({c['at_200_edges']['drift_cycles']:+.2f}) | "
                 f"{c['at_400_edges']['state']} ({c['at_400_edges']['drift_cycles']:+.2f}) | "
                 f"{_f(c['drift_ratio_400_over_200'])} | {'yes' if c['converged'] else 'NO'} |")
    for c in summ["convergence_unpaired"]:
        L.append(f"| {c['tone']} | {c['amp_mV']} | {'have' if c['have_200'] else 'MISSING'} | "
                 f"{'have' if c['have_400'] else 'MISSING'} | - | unpaired |")
    L += ["", "## Requests, inputs and pins", "",
          "| request | status | units returned | request sha256 | netlist sha256 | job | client / runner klt | PDK | models lib sha256 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for nm in sorted(inputs):
        i = inputs[nm]
        pv = i.get("provenance") or {}
        pdk = pv.get("pdk") or {}
        L.append(f"| {nm} | {i['status']} | {i['units_returned']}/{i['units']} | `{i['request_sha256'][:16]}` | "
                 f"`{i['netlist_sha256'][:16]}` | {pv.get('job_id') or '-'} | {pv.get('client_klt') or '-'} / "
                 f"{pv.get('runner_klt') or '-'} | {pdk.get('name', '-')} {pdk.get('version', '')} | "
                 f"`{(pv.get('models_lib_sha256') or '-')[:16]}` |")
    if summ["rows_unusable"]:
        L += ["", "## Missing / failed / unusable rows", "", "| request | kind | tone | amp (mV) | N | status | reason |",
              "|---|---|---|---|---|---|---|"]
        for u in summ["rows_unusable"]:
            L.append(f"| {u['chunk']} | {u['kind']} | {u['tone']} | {u['amp_mV']:g} | {u['nedge']} | {u['klt_status']} | "
                     f"{'; '.join(u['why'])[:300]} |")
    if history:
        L += ["", "## Submission history (refused, timed-out, orphaned and reused earlier requests)", "",
              history.get("summary", ""), "", "| request | job | outcome |", "|---|---|---|"]
        for h in history.get("attempts", []):
            if h.get("corner") in (None, pvt["proc"]):
                L.append(f"| {h['request']} | {h.get('job_id') or '-'} | {h['outcome']} |")
    L += ["", "Full hashes, netlist closure and per-row observed windows are in the `.json`; requests, netlists, plans, "
          "raw responses and missing-request notes are in `../corners/<id>/` (append-only; the #200 records are "
          "untouched).", "",
          "---", "", "- Author: loom-builder@sky130-trng", f"- Timestamp (UTC): {now.isoformat()}", f"- Repo commit: `{sha}`",
          "- Supersedes: (none; extends the #200 records)"]
    return "\n".join(L) + "\n"


CLAIM = ("Supply-ripple / injection-lock robustness of the committed pre-layout ro_array_core (issue #200): "
         "common-mode sinusoidal ripple of 10, 50, 100 and 200 mV pk on vdd and vddr1..4 at the ring-ladder frequencies "
         "(own, +0.5% detuned, just outside), sub-harmonics, 2x, 10 MHz and the quasi-static (50 kbps) limit; per-ring "
         "period modulation, ring-vs-tone and ring-vs-ring injection-lock closeness, combining-node bias; ring-local "
         "current-injection negative control; deterministic, no injected noise")
LR_CLAIM = ("Lock-resolution follow-up on the same pre-layout ro_array_core (issue #288, DR-0012 follow-up 5): "
            "200-edge observation windows resolving +-0.1 % detuning (0.1-cycle drift criterion, 2x margin; a "
            "free-running ring detuned by delta slips delta*(N-1) cycles over N edges) with a 400-edge convergence "
            "subset; detuning ladder +-0.1 / +-0.25 / +-0.4 % on both sides of each ring's own frequency at 20 and "
            "50 mV pk (inside the #200 10-50 mV lock bracket) and +-0.25 % at 5 mV pk (below its 10 mV floor); "
            "on-frequency rows kept drift-UNRESOLVED and decided, where at all, by detuned neighbours and pull "
            "evidence; current-injection controls at own/+2/+5/+20 % detuning against the clean free-running reference; LOCK, Q "
            "and BIAS reported separately; deterministic, no injected noise, no entropy claim")
PVTS = None


def _jload(path):
    with open(path) as fh:
        return json.load(fh)


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 16), b""):
            h.update(blk)
    return h.hexdigest()


def _provenance(rs):
    """Tool / PDK pins and input hashes carried by one klt sim response."""
    env, prov = rs.get("environment", {}), rs.get("provenance", {})
    rem = env.get("remote") or {}
    return {"job_id": rem.get("job_id"), "client_klt": prov.get("klt_version"),
            "runner_klt": rem.get("runner_klt_version"), "runner_compatibility": rem.get("runner_compatibility"),
            "klayout": prov.get("klayout_version"), "engine": env.get("engine"),
            "engine_version": env.get("engine_version"), "pdk": prov.get("pdk"),
            "models_lib_sha256": env.get("models_lib_sha256"), "netlist_sha256": env.get("netlist_sha256"),
            "netlist_closure": [{"path": x.get("path"), "sha256": x.get("sha256")}
                                for x in env.get("netlist_closure", [])],
            "budget": env.get("budget")}


def emit_record(reqdir, sha=None):
    import importlib.util
    from evidence_record import git_short_sha
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("make_requests", os.path.join(os.path.dirname(__file__), "make-requests.py"))
    mr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mr)
    sha = sha or git_short_sha(Path(REPO))
    chunks, missing = load_reqdir_all(reqdir)
    campaigns = {pl.get("campaign") for _, pl, _ in chunks} | {pl.get("campaign") for _, pl, _ in missing}
    if len(campaigns) > 1:
        raise SystemExit(f"error: mixed campaigns in one request dir: {campaigns}")
    campaign = next(iter(campaigns), None)
    if campaign != LR:
        missing = []          # legacy path unchanged: unreturned requests were never recorded there
    allrows = build_rows(chunks, missing)
    base_now = datetime.datetime.now(datetime.timezone.utc)
    for n, cn in enumerate(sorted(allrows), 1):
        now = base_now + datetime.timedelta(seconds=n)
        rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
        pvt = dict(mr.CORNERS[cn])
        pvt.pop("tr")
        rows = allrows[cn]
        if campaign == LR:
            summ = summarize_lr(rows)
            claim = LR_CLAIM
        else:
            summ = summarize(rows, pvt["vnom"], (0.010, 0.050))
            claim = CLAIM
        mine = [(nm, pl, rs) for nm, pl, rs in chunks if pl["corner"] == cn]
        mine_missing = [(nm, pl, why) for nm, pl, why in missing if pl["corner"] == cn]
        jobs = [(rs.get("environment", {}).get("remote") or {}).get("job_id") for _, _, rs in mine]
        cdir = os.path.join(REPO, "sim", SLUG, "corners", rid)
        rdir = os.path.join(REPO, "sim", SLUG, "records")
        if os.path.exists(os.path.join(rdir, rid + ".json")) or os.path.exists(cdir):
            raise SystemExit(f"error: {rid} exists")
        os.makedirs(cdir)
        os.makedirs(rdir, exist_ok=True)
        inputs = {}
        for nm, pl, rs in mine:
            with gzip.open(os.path.join(cdir, f"{nm}.klt-sim.json.gz"), "wt") as fh:   # raw response, verbatim
                json.dump(rs, fh, indent=1)
            json.dump(pl, open(os.path.join(cdir, f"{nm}.plan.json"), "w"), indent=1)
            for fn, dst in (("request.json", f"{nm}.request.json"), ("netlist.cir", f"{nm}.netlist.cir")):
                shutil.copyfile(os.path.join(reqdir, nm, fn), os.path.join(cdir, dst))   # exactly what was submitted
            inputs[nm] = {"status": "returned", "units": len(pl["units"]), "units_returned": len(rs["corners"]),
                          "request_sha256": _sha256(os.path.join(cdir, f"{nm}.request.json")),
                          "netlist_sha256": _sha256(os.path.join(cdir, f"{nm}.netlist.cir")),
                          "provenance": _provenance(rs)}
        for nm, pl, why in mine_missing:                  # refused / failed / never completed: kept, not dropped
            json.dump(pl, open(os.path.join(cdir, f"{nm}.plan.json"), "w"), indent=1)
            json.dump({"request": nm, "reason": why}, open(os.path.join(cdir, f"{nm}.missing.json"), "w"), indent=1)
            for fn, dst in (("request.json", f"{nm}.request.json"), ("netlist.cir", f"{nm}.netlist.cir")):
                shutil.copyfile(os.path.join(reqdir, nm, fn), os.path.join(cdir, dst))
            inputs[nm] = {"status": "missing", "units": len(pl["units"]), "units_returned": 0, "reason": why,
                          "request_sha256": _sha256(os.path.join(cdir, f"{nm}.request.json")),
                          "netlist_sha256": _sha256(os.path.join(cdir, f"{nm}.netlist.cir"))}
        criteria = {"drift_lock_ring_cycles": DRIFT_LOCK, "q_margin": Q_MARGIN, "bias_band": list(BIAS_BAND)}
        if campaign == LR:
            criteria.update(nedge=summ["nedge"], detuning_resolution_pct=summ["detuning_resolution_pct"],
                            claimed_resolution_pct=0.1)
        first = mine[0][2] if mine else {}
        rec = {"record_id": rid, "slug": SLUG, "claim": claim, "level": "transistor", "status": PROV,
               "seed": "N/A (deterministic transient, no injected noise)", "pvt": pvt, "campaign": campaign,
               "criteria": criteria,
               "testbench": "sim/ro-array-supply-perturbation/testbench/tb_ro_array_supply_perturbation.spice "
                            "(via sim/ro-array-supply-perturbation/make-requests.py)",
               "klt_sim": {"jobs": jobs, "backend": "batch",
                           "remote": [rs.get("environment", {}).get("remote") for _, _, rs in mine],
                           "engine_version": first.get("environment", {}).get("engine_version"),
                           "models_lib_sha256": first.get("environment", {}).get("models_lib_sha256"),
                           "submitter_klt": first.get("provenance", {}).get("klt_version"),
                           "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"},
               "supersedes": "(none)", "summary": summ, "rows": rows, "timestamp_utc": now.isoformat()}
        if campaign == LR:
            rec["inputs"] = inputs
            rec["requests_missing"] = [{"request": nm, "reason": why} for nm, _, why in mine_missing]
            hist = os.path.join(reqdir, "submission-history.json")
            if os.path.isfile(hist):            # earlier refused / timed-out submissions of this campaign
                rec["submission_history"] = _jload(hist)
                shutil.copyfile(hist, os.path.join(cdir, "submission-history.json"))
        json.dump(rec, open(os.path.join(rdir, rid + ".json"), "w"), indent=2, default=str)
        md = (render_lr_md(rid, pvt, rows, summ, jobs, sha, now, inputs, rec.get("submission_history"))
              if campaign == LR
              else render_md(rid, cn, pvt, rows, summ, jobs, sha, now, claim))
        open(os.path.join(rdir, rid + ".md"), "w").write(md)
        tail = (f"locked at: {summ['lock_range_pct_by_amp'] or 'none'} | converged: {summ['converged_all']} | "
                f"usable {summ['rows_usable']}/{summ['rows_planned']}"
                if campaign == LR else summ["tolerance_rf_cycle_avg"])
        print(rid, cn, tail, "| detector fires:", summ.get("detector_fires_on_negative_control",
                                                            any(c["flagged"] for c in summ.get("controls", []))))


def _replay_equal(a, b, rel=1e-9):
    """Structural equality where floats match to `rel` (relative) instead of bit-for-bit.
    Python 3.12 made float `sum()` compensated, so a record emitted on 3.12 replays
    1-ulp different on 3.11 (the CI interpreter); anything above 1e-9 is a real change."""
    if isinstance(a, float) or isinstance(b, float):
        return (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool)
                and not isinstance(b, bool) and (a == b or math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_replay_equal(a[k], b[k], rel) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_replay_equal(x, y, rel) for x, y in zip(a, b))
    return a == b


def check(recpath):
    """Replay a record from its committed raw responses (and, for campaign
    records, the committed `*.missing.json` notes); exit 1 on any difference."""
    rec = json.load(open(recpath))
    cdir = os.path.join(REPO, "sim", SLUG, "corners", rec["record_id"])
    chunks, missing = [], []
    for f in sorted(glob.glob(os.path.join(cdir, "*.klt-sim.json.gz"))):
        nm = os.path.basename(f)[:-len(".klt-sim.json.gz")]
        with gzip.open(f, "rt") as fh:
            chunks.append((nm, _jload(os.path.join(cdir, nm + ".plan.json")), json.load(fh)))
    for f in sorted(glob.glob(os.path.join(cdir, "*.missing.json"))):
        nm = os.path.basename(f)[:-len(".missing.json")]
        missing.append((nm, _jload(os.path.join(cdir, nm + ".plan.json")), _jload(f)["reason"]))
    corner = next(iter({pl["corner"] for _, pl, _ in chunks + missing}))
    rows = build_rows(chunks, missing)[corner]
    if rec.get("campaign") == LR:
        summ = summarize_lr(rows)
    else:
        summ = summarize(rows, rec["pvt"]["vnom"], (0.010, 0.050))
    same = (_replay_equal(json.loads(json.dumps(rows, default=str)), rec["rows"])
            and _replay_equal(json.loads(json.dumps(summ, default=str)), rec["summary"]))
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
