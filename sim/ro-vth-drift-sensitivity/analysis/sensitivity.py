#!/usr/bin/env python3
"""Reduction for the Vth-drift (BTI/HCI-like) sensitivity campaign -- issue #254.

    sensitivity.py --emit-controls CTLDIR            # DC probe + zero-shift equivalence + pilot -> controls record
    sensitivity.py --emit-record REQDIR --controls RID   # full grid -> sensitivity record + calibration artifact
    sensitivity.py --check RECORD.json               # replay a record from its committed raw responses
    sensitivity.py --coverage                        # print the required-key manifest summary
    sensitivity.py --check-manifest                  # committed manifest == the generator's

A first-order ELECTRICAL SENSITIVITY: a gate-offset wrapper (aging.py) shifts the effective
Vth of every NMOS (dVtn) and PMOS (d|Vtp|) in the RO array's committed netlists. The
shifts are not tied to any time, voltage, duty cycle or temperature.
This is a sensitivity bound, not a lifetime prediction.

Per row (deck, corner, T, Vdd, dVtn, d|Vtp|) the reduction derives, with the source decks'
own formulas:
  ring5 : T_0 (tbar), sigma_1 raw and numerically-floor-corrected (array-sizing.py's
          `deflate`), swing, Q_ring = sigma_1^2 * T_s / T_0^3 (T_s = array-sizing T_S_TARGET)
  array : tr1..tr4, skew_span (ladder span), edge_retention / retention_n2 / bias_xo /
          swing_frac_xo (edge and value fidelity), i_array_total, and the closest approach
          of any ring pair's frequency ratio to the DR-0005 small-rational set
          (2/1, 3/2, 4/3): winning pair, rational and normalized distance.
Every shifted row is paired with the zero-shift row of the SAME campaign at the same
(deck, corner, T, Vdd); absolute values and deltas are both reported. Historical
time-zero records are only read (and compared in the controls), never touched.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import gzip
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUGDIR = HERE.parent
REPO = SLUGDIR.parents[1]
sys.path.insert(0, str(SLUGDIR))
sys.path.insert(0, str(REPO / "sim" / "bin"))
import aging  # noqa: E402
import campaign as C  # noqa: E402
from evidence_record import git_short_sha  # noqa: E402

SLUG = C.SLUG
SENTENCE = "This is a sensitivity bound, not a lifetime prediction."
PROV = "simulation-derived; provisional until silicon"
DR5_RATIOS = [(2, 1), (3, 2), (4, 3)]           # sim/ro-array-supply-perturbation/ripple.py DR5_RATIOS
CAL_SCHEMA = "vth-drift-calibration/1"
EQUIV_REL_TOL = 1e-3                              # 0.1 % (issue #254 control 2)
OFFSET_TOL_V = 1e-6                               # 1 uV (issue #254 control 1)
SIGMA_REL_RES = 0.16                              # source deck: ~16 % 1-sigma on sigma_1 (20 periods)
# Two sigma_1 estimates from two noise realizations of the same circuit differ by sqrt(2) x the single-estimate
# resolution (1-sigma). The wrapper adds branch unknowns, so the solver's step sequence -- and hence which noise
# samples the 20 periods see -- differs from the unwrapped deck even at zero shift. The jitter gate is therefore the
# 2-sigma band of that difference, derived from the source deck's stated resolution (not an invented tighter number).
SIGMA_EQUIV_REL = 2 * math.sqrt(2) * SIGMA_REL_RES
DR0003_Q_MARGIN = 1.036
H_FLOOR_DR0004 = 0.5                              # DR-0004 evaluates the health cutoffs at H = 0.5
T_S_DR0003 = 20e-6


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AS = _load(REPO / "sim/ro-array-sizing/analysis/array-sizing.py", "array_sizing")
DC = _load(REPO / "sim/raw-bit-volume-campaign/derive-combining.py", "derive_combining")


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- metrics
def numerical_floor() -> float | None:
    _rows, floors = AS.load_convergence()
    return floors.get(C.DECKS["ring5"]["tmax"])


def ring_metrics(m: dict, floor: float | None) -> dict:
    """The source deck's `let` block, verbatim formulas, on the 21 recorded crossings."""
    tc = [m[f"tk{k}"] for k in C.RING_EDGES]
    assert len(tc) == 21
    tbar = (tc[20] - tc[0]) / 20
    out = {"tbar": tbar, "swing_frac": (m["vmax_ss"] - m["vmin_ss"]) / m["_vdd"]}
    for k in (1, 2, 4, 8):
        r = [(tc[j + k] - tc[j]) - k * tbar for j in range(21 - k)]
        out[f"sigma_{k}"] = math.sqrt((sum(x * x for x in r) / len(r)) / (1 - k / 20))
    out["sigma_1_raw"] = out["sigma_1"]
    out["sigma_1_corrected"] = AS.deflate(out["sigma_1"], floor)
    out["numerical_floor"] = floor
    out["q_ring"] = AS.q_ring(out["sigma_1_corrected"], tbar, AS.T_S_TARGET)
    return out


def closeness(periods: list[float]) -> dict:
    """Closest approach of any pair's frequency ratio to the DR-0005 rational set."""
    best = None
    for i in range(4):
        for j in range(i + 1, 4):
            r = periods[j] / periods[i]                    # f_i / f_j
            for p, q in DR5_RATIOS:
                for x, label in ((p / q, f"{p}/{q}"), (q / p, f"{q}/{p}")):
                    d = abs(r / x - 1)
                    if best is None or d < best["distance"]:
                        best = {"pair": [i + 1, j + 1], "rational": label, "distance": d,
                                "meaning": "f_i/f_j ~ rational"}
    return best


def array_metrics(m: dict, vdd: float) -> dict:
    d = DC.derive({k: v for k, v in m.items() if not k.startswith("_")}, vdd)
    keep = ("tr1", "tr2", "tr3", "tr4", "skew_span", "edge_retention", "retention_n2", "bias_xo",
            "swing_frac_xo", "i_array_total", "i_rings", "i_block")
    out = {k: d[k] for k in keep}
    out["lock_proximity"] = closeness([out[f"tr{i}"] for i in (1, 2, 3, 4)])
    return out


# ------------------------------------------------------------------------------- rows
def rows_from_response(name: str, plan: dict, resp: dict, floor: float | None) -> list[dict]:
    deck, vdd = plan["deck"], plan["vdd_v"]
    job = (resp.get("environment", {}).get("remote") or {}).get("job_id")
    rows = []
    for c in resp["corners"]:
        sv = c.get("supply_v") or {}
        dvn_v, dvp_v = sv.get("Vdvn", 0.0), sv.get("Vdvp", 0.0)
        dvn, dvp = round(dvn_v * 1e3, 6), round(dvp_v * 1e3, 6)
        key = C.key_str(deck, c["process"], c["temperature_c"], vdd, dvn, dvp)
        meas = {x["name"]: x["value"] for x in c["measurements"] if x.get("value") is not None}
        meas["_vdd"] = vdd
        problems = []
        if c["status"] != "pass":
            problems.append(f"corner status {c['status']}: " + "; ".join(d.get("message", "") for d in c.get("diagnostics", [])))
        for kn, want in (("dvn_rb", dvn_v), ("dvp_rb", dvp_v)):
            got = meas.get(kn)
            if got is None or abs(got - want) > 1e-9:
                problems.append(f"{kn} read-back {got} != requested {want} (shift not applied: would be a time-zero run)")
        metrics = None
        if not problems:
            try:
                metrics = ring_metrics(meas, floor) if deck == "ring5" else array_metrics(meas, vdd)
            except (KeyError, ZeroDivisionError, ValueError) as e:
                problems.append(f"metric derivation failed: {e!r}")
        rows.append({"key": key, "deck": deck, "corner": c["process"], "temp_c": c["temperature_c"], "vdd_v": vdd,
                     "dvtn_mv": dvn, "dvtp_mv": dvp, "ok": not problems, "problems": problems,
                     "request": name, "job_id": job, "stop": plan.get("info", {}).get("stop"),
                     "stop_override": plan.get("info", {}).get("stop") != C.DECKS[deck]["stop"],
                     "raw": {k: v for k, v in meas.items() if not k.startswith("_")}, "metrics": metrics})
    return rows


def load_reqdir(reqdir) -> list[tuple[str, dict, dict]]:
    out = []
    for d in sorted(glob.glob(os.path.join(reqdir, "*"))):
        if os.path.isfile(os.path.join(d, "resp.json")) and os.path.isfile(os.path.join(d, "plan.json")) \
                and os.path.getsize(os.path.join(d, "resp.json")) > 0:
            out.append((os.path.basename(d), json.load(open(os.path.join(d, "plan.json"))),
                        json.load(open(os.path.join(d, "resp.json")))))
    return out


def load_committed(cdir, prefix=None) -> list[tuple[str, dict, dict]]:
    out = []
    for f in sorted(glob.glob(os.path.join(cdir, "*.klt-sim.json.gz"))):
        nm = os.path.basename(f)[:-len(".klt-sim.json.gz")]
        if prefix and not nm.startswith(prefix):
            continue
        with gzip.open(f, "rt") as fh:
            out.append((nm, json.load(open(os.path.join(cdir, nm + ".plan.json"))), json.load(fh)))
    return out


DELTA_FIELDS = {
    "ring5": ("tbar", "sigma_1_raw", "sigma_1_corrected", "q_ring", "swing_frac"),
    "array": ("tr1", "tr2", "tr3", "tr4", "skew_span", "edge_retention", "retention_n2", "bias_xo",
              "swing_frac_xo", "i_array_total"),
}


def pair_rows(rows: list[dict]) -> list[str]:
    """Attach the matching zero-shift row's key and absolute/relative deltas. Returns problems."""
    zero = {(r["deck"], r["corner"], r["temp_c"], r["vdd_v"]): r for r in rows if r["dvtn_mv"] == 0 and r["dvtp_mv"] == 0}
    probs = []
    for r in rows:
        z = zero.get((r["deck"], r["corner"], r["temp_c"], r["vdd_v"]))
        if z is None:
            probs.append(f"no zero-shift row for {r['key']}")
            r["zero_shift_key"], r["delta"] = None, None
            continue
        r["zero_shift_key"] = z["key"]
        if not (r["ok"] and z["ok"]):
            r["delta"] = None
            continue
        d = {}
        for f in DELTA_FIELDS[r["deck"]]:
            a, b = r["metrics"][f], z["metrics"][f]
            d[f] = {"abs": a - b, "rel": (a / b - 1) if b else None}
        zl, rl = z["metrics"].get("lock_proximity"), r["metrics"].get("lock_proximity")
        if rl:
            d["lock_distance"] = {"abs": rl["distance"] - zl["distance"], "rel": None}
        r["delta"] = d
    return probs


def coverage_problems(rows):
    return C.check_coverage([r["key"] for r in rows])


# ----------------------------------------------------------------- DR-0003 / DR-0004 view
def envelope(rows: list[dict]) -> dict:
    """Model-derived consequence for DR-0003 / DR-0004 at every common-mode grid point.

    DR-0003 sec. 3: N = 4, T_s = 20 us, guaranteed H = h_from_q(Q_array) = 0.5415 at the
    entropy-binding corner (Q_array 1.036 x M*Q_H0). DR-0004 sec. 2.3 evaluates its RCT/APT
    cutoffs at H = 0.5. Q_array = sum_i sigma_1^2 T_s / T_i^3 with sigma_1 from the ring5 row
    and T_i from the array row at the same key (the DR-0003 loaded-period convention).
    """
    by = {r["key"]: r for r in rows}
    out = []
    for c in C.PROCESSES:
        for t in C.TEMPS:
            for v in C.VDDS:
                pts = []
                for s in C.CM_SHIFTS_MV:
                    rr = by.get(C.key_str("ring5", c, t, v, s, s))
                    ra = by.get(C.key_str("array", c, t, v, s, s))
                    if not (rr and ra and rr["ok"] and ra["ok"]):
                        continue
                    s1 = rr["metrics"]["sigma_1_corrected"]
                    r0 = by.get(C.key_str("ring5", c, t, v, 0, 0))
                    s1_0 = r0["metrics"]["sigma_1_corrected"]
                    q = sum(s1 ** 2 * T_S_DR0003 / ra["metrics"][f"tr{i}"] ** 3 for i in (1, 2, 3, 4))
                    q_t = sum(s1_0 ** 2 * T_S_DR0003 / ra["metrics"][f"tr{i}"] ** 3 for i in (1, 2, 3, 4))
                    pts.append({"shift_mv": s, "q_array": q, "h_bound": AS.h_from_q(q),
                                "q_array_period_only": q_t, "h_bound_period_only": AS.h_from_q(q_t),
                                "lock_distance": ra["metrics"]["lock_proximity"]["distance"],
                                "edge_retention": ra["metrics"]["edge_retention"],
                                "bias_xo": ra["metrics"]["bias_xo"]})
                if not pts:
                    continue
                q0 = pts[0]["q_array"]
                for p in pts:
                    p["q_ratio"] = p["q_array"] / q0
                    p["q_ratio_period_only"] = p["q_array_period_only"] / q0
                out.append({"corner": c, "temp_c": t, "vdd_v": v, "points": pts,
                            "shift_mv_q_margin_exhausted": _crossing(pts, "q_ratio", 1 / DR0003_Q_MARGIN),
                            "shift_mv_h_floor_crossed": _crossing(pts, "h_bound", H_FLOOR_DR0004),
                            "shift_mv_q_margin_exhausted_period_only": _crossing(pts, "q_ratio_period_only", 1 / DR0003_Q_MARGIN),
                            "shift_mv_h_floor_crossed_period_only": _crossing(pts, "h_bound_period_only", H_FLOOR_DR0004)})
    return {"rows": out, "q_margin": DR0003_Q_MARGIN, "h_floor": H_FLOOR_DR0004, "t_s": T_S_DR0003}


def _crossing(pts, field, level):
    """Smallest common-mode shift (mV, linear interpolation between grid shifts) where `field` falls
    to `level`; None if it never does within the grid (reported as 'not reached by 60 mV')."""
    for a, b in zip(pts, pts[1:]):
        if a[field] >= level > b[field]:
            return a["shift_mv"] + (a[field] - level) / (a[field] - b[field]) * (b["shift_mv"] - a["shift_mv"])
    return 0.0 if pts and pts[0][field] < level else None


# ---------------------------------------------------------------------- calibration
def calibration_artifact(rid: str, rows: list[dict], rec_sha: str | None = None) -> dict:
    """Versioned artifact keyed by (corner, T, Vdd, dVtn, d|Vtp|); entries exist only where both the
    ring5 jitter row and the array row exist and are usable (the common-mode grid)."""
    by = {r["key"]: r for r in rows}
    entries = {}
    for c in C.PROCESSES:
        for t in C.TEMPS:
            for v in C.VDDS:
                for s in C.CM_SHIFTS_MV:
                    rr, ra = by.get(C.key_str("ring5", c, t, v, s, s)), by.get(C.key_str("array", c, t, v, s, s))
                    if not (rr and ra and rr["ok"] and ra["ok"]):
                        continue
                    m, a = rr["metrics"], ra["metrics"]
                    entries[cal_key(c, t, v, s, s)] = {
                        "T_0": m["tbar"], "sigma_1_raw": m["sigma_1_raw"], "sigma_1_corrected": m["sigma_1_corrected"],
                        "numerical_floor": m["numerical_floor"], "q_ring": m["q_ring"], "q_ring_t_s": AS.T_S_TARGET,
                        "array_periods_s": [a[f"tr{i}"] for i in (1, 2, 3, 4)], "lock_proximity": a["lock_proximity"],
                        "source_rows": {"ring5": {"key": rr["key"], "row_sha256": sha256_json(rr), "job_id": rr["job_id"]},
                                        "array": {"key": ra["key"], "row_sha256": sha256_json(ra), "job_id": ra["job_id"]}}}
    return {"schema": CAL_SCHEMA, "claim": SENTENCE, "level": "transistor-derived calibration (sensitivity), not silicon",
            "source_record": rid, "key_fields": ["corner", "temp_c", "vdd_v", "dvtn_mv", "dvtp_mv"],
            "pdk_commit": C.pdk_commit(), "entries": entries}


def cal_key(corner, temp, vdd, dvn, dvp) -> str:
    return f"{corner}|{float(temp):g}C|{float(vdd):g}V|{float(dvn):g}|{float(dvp):g}"


# ------------------------------------------------------------------------- controls
def _m(corner_entry):
    return {x["name"]: x["value"] for x in corner_entry["measurements"] if x.get("value") is not None}


def _hist_record(slug, pred):
    best = None
    for p in sorted(glob.glob(str(REPO / "sim" / slug / "records" / "*.json"))):
        r = json.load(open(p))
        if pred(r):
            best = r
    return best


def evaluate_controls(ctl: dict[str, tuple[dict, dict]], floor) -> dict:
    """ctl: name -> (plan, resp) for dc-probe, <deck>-unwrapped, <deck>-pilot."""
    res = {"pass": True, "checks": [], "floor": floor}

    def chk(name, ok, detail):
        res["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        res["pass"] &= bool(ok)

    # 1. DC gate-offset probe
    plan, resp = ctl["dc-probe"]
    rows = []
    for c in resp["corners"]:
        m = _m(c)
        dn, dp = c["supply_v"]["Vdvn"], c["supply_v"]["Vdvp"]
        row = {"dvtn_v": dn, "dvtp_v": dp, "status": c["status"], "offn_v": m.get("offn"), "offp_v": m.get("offp"),
               "err_n_v": None if m.get("offn") is None else m["offn"] - dn,
               "err_p_v": None if m.get("offp") is None else m["offp"] - dp,
               "idn_ratio": None if not m.get("idnr") else m["idn"] / m["idnr"],
               "idp_ratio": None if not m.get("idpr") else m["idp"] / m["idpr"]}
        rows.append(row)
    ok = all(r["status"] == "pass" and r["err_n_v"] is not None and abs(r["err_n_v"]) <= OFFSET_TOL_V
             and abs(r["err_p_v"]) <= OFFSET_TOL_V for r in rows)
    def _mx(k):
        v = [abs(r[k]) for r in rows if r[k] is not None]
        return max(v) if v else float("nan")

    chk("dc-offset-within-1uV", ok and len(rows) == len(plan["shifts_mv"]),
        f"{len(rows)} units (symmetric 0/20/40/60 and asymmetric (60,0), (0,60) mV); max |err| = {_mx('err_n_v'):.3g} V (NMOS), {_mx('err_p_v'):.3g} V (PMOS); tol {OFFSET_TOL_V:g} V")
    ok = all(r["idn_ratio"] is not None and abs(r["idn_ratio"] - 1) <= 1e-5 and abs(r["idp_ratio"] - 1) <= 1e-5 for r in rows)
    chk("wrapped-current-equals-unwrapped-at-shifted-gate", ok,
        "max |I_wrapped / I_unwrapped(shifted gate) - 1| = %.3g" % max(max(abs(r["idn_ratio"] - 1), abs(r["idp_ratio"] - 1)) for r in rows if r["idn_ratio"]))
    sign_ok = all((r["offn_v"] or 0) >= -1e-9 and (r["offp_v"] or 0) >= -1e-9 for r in rows)
    chk("offset-sign (NMOS gate lowered, PMOS gate raised)", sign_ok, "offn = V(g)-V(gd) >= 0; offp = V(gd)-V(g) >= 0")
    res["dc_probe"] = rows

    # 2. zero-shift equivalence: wrapped (0,0) unit of the pilot vs unwrapped, same toolchain
    res["equivalence"] = {}
    for deck in C.DECKS:
        plan_u, resp_u = ctl[f"{deck}-unwrapped"]
        plan_p, resp_p = ctl[f"{deck}-pilot"]
        cu = resp_u["corners"][0]
        mu = _m(cu)
        mu["_vdd"] = 1.8
        cp = next(c for c in resp_p["corners"] if abs(c["supply_v"]["Vdvn"]) < 1e-12 and abs(c["supply_v"]["Vdvp"]) < 1e-12)
        mp = _m(cp)
        mp["_vdd"] = 1.8
        ok_ = cu["status"] == "pass" and cp["status"] == "pass"
        chk(f"{deck}-zero-shift-runs-pass", ok_, f"unwrapped {cu['status']}, wrapped-zero {cp['status']}")
        if not ok_:
            continue
        if deck == "ring5":
            a, b = ring_metrics(mu, floor), ring_metrics(mp, floor)
            det = {"tbar": EQUIV_REL_TOL, "swing_frac": EQUIV_REL_TOL}
            jit = {"sigma_1_raw": SIGMA_EQUIV_REL}
        else:
            a, b = array_metrics(mu, 1.8), array_metrics(mp, 1.8)
            det = {k: EQUIV_REL_TOL for k in ("tr1", "tr2", "tr3", "tr4", "skew_span", "edge_retention", "retention_n2",
                                              "bias_xo", "swing_frac_xo", "i_array_total")}
            jit = {}
        eq = {}
        for f, tol in {**det, **jit}.items():
            rel = b[f] / a[f] - 1
            eq[f] = {"unwrapped": a[f], "wrapped_zero": b[f], "rel": rel, "tol": tol}
            chk(f"{deck}-zero-shift-{f}", abs(rel) <= tol, f"unwrapped {a[f]:.6g} vs wrapped-zero {b[f]:.6g} (rel {rel:+.3e}, tol {tol:g})")
        # historical time-zero record (informational; the same tolerances are applied)
        if deck == "ring5":
            h = _hist_record("ro-ring-jitter-accumulation", lambda r: r["pvt"] == {"temp_c": 27.0, "vdd_v": 1.8}
                             and "ring5" in r["testbench"] and r["tran"]["tmax"] == "20p")
            hm = next(c for c in h["corners"] if c["corner"] == "tt")["measurements"]
            hist = {"record": h["record_id"], "tbar": hm["tbar"], "sigma_1_raw": hm["sigma_1"], "swing_frac": hm["swing_frac"]}
            hv = {"tbar": b["tbar"] / hm["tbar"] - 1, "sigma_1_raw": b["sigma_1_raw"] / hm["sigma_1"] - 1,
                  "swing_frac": b["swing_frac"] / hm["swing_frac"] - 1}
        else:
            h = _hist_record("ro-array-core-combining", lambda r: r["pvt"] == {"temp_c": 27.0, "vdd_v": 1.8})
            hm = next(c for c in h["corners"] if c["corner"] == "tt")["measurements"]
            hist = {"record": h["record_id"], **{k: hm[k] for k in ("tr1", "tr4", "edge_retention", "i_array_total")}}
            hv = {k: b[k] / hm[k] - 1 for k in ("tr1", "tr4", "edge_retention", "i_array_total")}
        eq["vs_historical"] = {"reference": hist, "rel": hv}
        res["equivalence"][deck] = eq
        for f, rel in hv.items():
            if f.startswith("sigma"):
                # Informational, not gating: the historical record came from sim/bin/corner-run.py, a different
                # runner/noise realization than klt sim; two independent 20-period sigma_1 estimates differ by
                # ~sqrt(2) x 16 % 1-sigma. The like-for-like jitter gate is wrapped-zero vs unwrapped, both klt sim.
                res["checks"].append({"name": f"{deck}-zero-shift-vs-historical-{f}", "ok": True, "informational": True,
                                      "detail": f"{h['record_id']}: rel {rel:+.3e} (informational; different runner, estimator resolution ~16 % 1-sigma each)"})
                continue
            chk(f"{deck}-zero-shift-vs-historical-{f}", abs(rel) <= EQUIV_REL_TOL, f"{h['record_id']}: rel {rel:+.3e}, tol {EQUIV_REL_TOL:g}")

    # 3. pilot: direction and size of period movement; fail closed on non-monotone / failed start
    res["pilot"] = {}
    for deck in C.DECKS:
        plan_p, resp_p = ctl[f"{deck}-pilot"]
        pts = []
        for c in resp_p["corners"]:
            mm = _m(c)
            mm["_vdd"] = 1.8
            s = round(c["supply_v"]["Vdvn"] * 1e3, 6)
            if c["status"] != "pass":
                pts.append({"shift_mv": s, "ok": False, "status": c["status"]})
                continue
            if deck == "ring5":
                T = ring_metrics(mm, floor)["tbar"]
            else:
                a = array_metrics(mm, 1.8)
                T = sum(a[f"tr{i}"] for i in (1, 2, 3, 4)) / 4
            pts.append({"shift_mv": s, "ok": True, "T": T})
        pts.sort(key=lambda p: p["shift_mv"])
        all_ok = len(pts) == 4 and all(p["ok"] for p in pts)
        mono = all_ok and all(b["T"] > a["T"] for a, b in zip(pts, pts[1:]))
        if all_ok:
            for p in pts:
                p["rel_to_zero"] = p["T"] / pts[0]["T"] - 1
        res["pilot"][deck] = pts
        chk(f"{deck}-pilot-started", all_ok, "all four common-mode units completed with every measurement")
        chk(f"{deck}-pilot-monotone-period-increase", mono,
            ("T: " + ", ".join(f"{p['shift_mv']:g} mV -> {p['rel_to_zero']*100:+.2f} %" for p in pts)) if all_ok else "not evaluable")
    return res


def md_controls(rid, res, info):
    L = [f"# {rid} -- {SLUG} (controls)", "", f"**Claim**: the gate-offset wrappers reach the transistor gates with the requested "
         "signed offsets, the zero-shift wrapped decks reproduce the unwrapped decks, and the tt / 27 C / 1.8 V common-mode "
         "pilot moves the ring period monotonically. These controls gate the full grid.", "", f"**Level**: transistor", f"**Verdict**: {'PASS' if res['pass'] else 'FAIL'}", "",
         SENTENCE, "", "## Checks", "", "| check | result | detail |", "|---|---|---|"]
    for c in res["checks"]:
        L.append(f"| {c['name']} | {'PASS' if c['ok'] else '**FAIL**'} | {c['detail']} |")
    L += ["", "## DC gate-offset probe (tt / 27 C; units zipped (dVtn, d|Vtp|) in volts)", "",
          "| dVtn (V) | d|Vtp| (V) | NMOS V(g)-V(gd) | PMOS V(gd)-V(g) | err N (V) | err P (V) | Id ratio N | Id ratio P |", "|---|---|---|---|---|---|---|---|"]
    for r in res["dc_probe"]:
        L.append(f"| {r['dvtn_v']:g} | {r['dvtp_v']:g} | {r['offn_v']:.9g} | {r['offp_v']:.9g} | {r['err_n_v']:.2e} | {r['err_p_v']:.2e} | {r['idn_ratio']:.9f} | {r['idp_ratio']:.9f} |")
    L += ["", "## Pilot (tt / 27 C / 1.8 V, common mode)", "", "| deck | shift (mV) | mean period (ns) | vs zero |", "|---|---|---|---|"]
    for deck, pts in res["pilot"].items():
        for p in pts:
            if p["ok"]:
                L.append(f"| {deck} | {p['shift_mv']:g} | {p['T']*1e9:.4f} | {p['rel_to_zero']*100:+.2f} % |")
            else:
                L.append(f"| {deck} | {p['shift_mv']:g} | FAILED ({p['status']}) | |")
    L += ["", "## Provenance", "", "```json", json.dumps(info, indent=1), "```", "",
          "Simulation-derived; provisional until silicon.", ""]
    return "\n".join(L)


def ctl_info(plans: dict) -> dict:
    return {"generator_sha256": aging.sha256_file(SLUGDIR / "campaign.py"), "aging_sha256": aging.sha256_file(SLUGDIR / "aging.py"),
            "wrapper_sha256": aging.sha256_text(aging.wrapper_definition()), "pdk_commit": C.pdk_commit(),
            "requests": {n: p.get("info", {}) for n, p in plans.items()}}


def emit_controls(ctldir):
    names = ["dc-probe"] + [f"{d}-{k}" for d in C.DECKS for k in ("unwrapped", "pilot")]
    ctl, plans, resps = {}, {}, {}
    for n in names:
        p, r = Path(ctldir) / n / "plan.json", Path(ctldir) / n / "resp.json"
        if not (p.is_file() and r.is_file() and r.stat().st_size):
            raise SystemExit(f"error: missing control response {n}")
        plans[n], resps[n] = json.load(open(p)), json.load(open(r))
        ctl[n] = (plans[n], resps[n])
    floor = numerical_floor()
    res = evaluate_controls(ctl, floor)
    sha = git_short_sha(REPO)
    now = datetime.datetime.now(datetime.timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
    cdir, rdir = SLUGDIR / "corners" / rid, SLUGDIR / "records"
    if (rdir / f"{rid}.json").exists() or cdir.exists():
        raise SystemExit(f"error: {rid} exists")
    cdir.mkdir(parents=True)
    rdir.mkdir(exist_ok=True)
    for n in names:
        with gzip.open(cdir / f"{n}.klt-sim.json.gz", "wt") as fh:
            json.dump(resps[n], fh, indent=1)
        json.dump(plans[n], open(cdir / f"{n}.plan.json", "w"), indent=1)
        for fn, dst in (("request.json", f"{n}.request.json"), ("netlist.cir", f"{n}.netlist.cir")):
            shutil.copyfile(Path(ctldir) / n / fn, cdir / dst)
    info = ctl_info(plans)
    rec = {"record_id": rid, "slug": SLUG, "kind": "controls", "level": "transistor", "status": PROV,
           "claim": "Vth-shift wrapper controls (DC gate-offset probe, zero-shift equivalence, tt/27C/1.8V pilot); gate the full grid. " + SENTENCE,
           "seed": "ring5: .option seed=1 (source deck); array: deterministic", "supersedes": "(none)", "pass": res["pass"],
           "controls": res, "provenance": info, "timestamp_utc": now.isoformat(),
           "klt_sim": {"backend": "local", "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"}}
    (rdir / f"{rid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    (rdir / f"{rid}.md").write_text(md_controls(rid, res, info))
    print(rid, "PASS" if res["pass"] else "FAIL")
    return 0 if res["pass"] else 1


# ---------------------------------------------------------------------- grid record
def pct(x):
    return "" if x is None else f"{x*100:+.2f}%"


def md_grid(rid, rows, env, summ, ctl_rid, jobs, claim):
    L = [f"# {rid} -- {SLUG}", "", f"**Claim**: {claim}", "", "**Level**: transistor (first-order Vth-offset wrapper; see below)", "",
         f"**{SENTENCE}**", "", f"Controls record: `{ctl_rid}` (PASS required before this record can be minted).", ""]
    L += ["## Scope, model, and why these values", "",
          "Every NMOS/PMOS of the committed `ro_ring5` and `ro_array_core` netlists is routed through a repository-owned "
          "gate-offset wrapper (`sim/ro-vth-drift-sensitivity/aging.py`): NMOS `V(g_device) = V(g) - dVtn`, PMOS "
          "`V(g_device) = V(g) + d|Vtp|`, all other terminals and parameters preserved; the pinned PDK and committed netlists are unchanged. "
          "It is a first-order electrical sensitivity only: no mobility, subthreshold-slope, or output-conductance change, no recovery, "
          "no distinction between BTI and HCI, and no device-, bias-, duty- or temperature-dependence of the shift.", "",
          "- **20 mV is the finite-difference resolution**: the smallest step at which the period movement is expected to exceed the 20-period "
          "jitter-estimator and numerical-floor resolution of the ring deck while keeping four points for a monotonicity check.",
          "- **60 mV is the declared outer stress point**: a round upper bound three resolution steps out, chosen to bracket a plausible "
          "first-order BTI-class shift without extrapolating the wrapper far from where it is verified. It is not derived from any SKY130 "
          "stress data.", "- **External context.** No public SKY130-specific reliability dataset was consulted or relied on for this record. "
          "General literature on NBTI/PBTI and hot-carrier threshold shifts of tens of mV in 130 nm-class bulk CMOS at elevated stress is "
          "merely *illustrative*: it is not technology-specific to SKY130, depends on stress voltage, duty cycle and temperature that this "
          "campaign does not model, and is NOT used to convert the sweep into a lifetime. Any such conversion needs operator ratification.",
          "- Asymmetric controls (dVtn, d|Vtp|) = (60, 0) and (0, 60) mV expose polarity-specific behaviour and cancellation.", "",
          "Estimator limits inherited from the source deck (not tightened): 20 periods -> ~16 % 1-sigma on sigma_1; single seed (1) held "
          "constant across the grid (common random numbers); fixed-injection-level noise good to ~1.5-2x; `sigma_1` is "
          "corrected in quadrature by the tt/27 C/1.8 V numerical floor at tmax = 20p "
          f"({summ['numerical_floor']*1e12:.4f} ps) exactly as `array-sizing.py` does, a floor that is *not* re-measured under shift.", ""]
    att = summ.get("attempts") or []
    L += ["## Coverage", "", f"{len(rows)} rows; required {summ['n_required']}; problems: {summ['coverage_problems'] or 'none'}. "
          "Machine check: `sim/ro-vth-drift-sensitivity/coverage-manifest.json` vs rows (fails on a missing or duplicate key).",
          "", "Batch jobs: " + ", ".join(f"`{j}`" for j in jobs), "",
          f"Unit failures and re-runs: {len(att)} unit(s) failed in their original request (every measurement missing: the transient aborted) and were re-run "
          "alone as `<request>--r<k>` (same netlist, same `.tran` stop) or, where that failed again, as `<request>--r<k>--f<k>` with the `.tran` stop nudged from "
          "175n to 180n. Two failure kinds were seen: (i) intermittent aborts on the fleet worker at ~13 s that differ between submissions of the identical "
          "request (filed as `2AMLogic/klayout-tools#3067`), cured by re-running at the same stop; (ii) a deterministic ngspice `Timestep too small ... trouble "
          "with node e.x4.xmnt.esh#branch` at the final breakpoint t = tstop, reproduced locally (ss / -40 C / 1.62 V at 20 and 40 mV; the same units complete at "
          "170n, 180n and 200n). A fallback-stop row has a *different noise realization* from its matched zero-shift row (the realization depends on the stop; "
          "tk values moved ~1e-4 relative between stops), so its `sigma_1`/`Q_ring` delta is realization noise of ~16-23 % on top of any real effect and is flagged "
          "`stop_override`; its period and swing are unaffected beyond the ~0.03 % period resolution of the 20-period mean. Failed originals and their "
          "whole-request attempt responses are kept (`*.klt-sim.json.gz`, `*.failed-attempt<N>.json.gz`); no unit was dropped or substituted."]
    L += [f"- `{a_['key']}`: original `{a_['request']}` (job `{a_['job_id']}`) -> re-run `{a_['superseded_by']}`" for a_ in att]
    L += [""]
    for deck in ("ring5", "array"):
        L += [f"## {deck}: absolute values and deltas vs the zero-shift row at the same PVT point", ""]
        if deck == "ring5":
            L += ["| corner | T | Vdd | dVtn/d|Vtp| (mV) | T_0 (ns) | dT_0 | sigma_1 raw (ps) | sigma_1 corr (ps) | Q_ring @1us | dQ | swing |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        else:
            L += ["| corner | T | Vdd | dVtn/d|Vtp| (mV) | tr1..tr4 (ns) | dtr1 | ladder span | edge_ret | ret_n2 | bias_xo | swing_xo | I_tot (uA) | closest rational (pair, p/q, dist) |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted((x for x in rows if x["deck"] == deck), key=lambda x: (x["corner"], x["temp_c"], x["vdd_v"], x["dvtn_mv"], x["dvtp_mv"])):
            head = f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | {r['dvtn_mv']:g}/{r['dvtp_mv']:g}{' (stop override: different noise realization)' if r.get('stop_override') else ''} |"
            if not r["ok"]:
                L.append(head + f" **FAILED**: {'; '.join(r['problems'])} |")
                continue
            m, d = r["metrics"], r["delta"] or {}
            if deck == "ring5":
                L.append(head + f" {m['tbar']*1e9:.4f} | {pct((d.get('tbar') or {}).get('rel'))} | {m['sigma_1_raw']*1e12:.3f} | "
                         f"{m['sigma_1_corrected']*1e12:.3f} | {m['q_ring']:.4g} | {pct((d.get('q_ring') or {}).get('rel'))} | {m['swing_frac']:.3f} |")
            else:
                lp = m["lock_proximity"]
                L.append(head + f" {m['tr1']*1e9:.3f} / {m['tr2']*1e9:.3f} / {m['tr3']*1e9:.3f} / {m['tr4']*1e9:.3f} | "
                         f"{pct((d.get('tr1') or {}).get('rel'))} | {m['skew_span']:.4f} | {m['edge_retention']:.4f} | {m['retention_n2']:.4f} | "
                         f"{m['bias_xo']:.4f} | {m['swing_frac_xo']:.3f} | {m['i_array_total']*1e6:.2f} | "
                         f"r{lp['pair'][0]}/r{lp['pair'][1]} {lp['rational']} {lp['distance']*100:.2f}% |")
        L.append("")
    L += ["## Closest approach to a small rational (DR-0005 set 2/1, 3/2, 4/3), common-mode grid minimum per shift", "",
          "DR-0005 reports a time-zero closest approach of any ring pair to any locking rational of 9.3 % anywhere on its grid (ss / 125 C / 1.98 V); the 0 mV row below is this campaign's own matched baseline. `f_i/f_j ~ p/q`.", "",
          "| shift (mV) | min distance | ring pair | rational | at (corner, T, Vdd) |", "|---|---|---|---|---|"]
    for k_, v_ in summ["lock_by_shift"].items():
        L.append(f"| {k_} | {v_['distance']*100:.2f} % | r{v_['pair'][0]}/r{v_['pair'][1]} | {v_['rational']} | {v_['corner']}, {v_['temp_c']:g} C, {v_['vdd_v']:g} V |")
    L += ["", "## Asymmetric controls at the headline points (mean ring period shift vs zero shift)", "",
          "| point | NMOS only 60/0 | PMOS only 0/60 | both 60/60 | additivity (both / sum) | min lock distance 0 / N / P / both | edge_ret 0 / N / P / both |", "|---|---|---|---|---|---|---|"]
    for a_ in summ["asymmetric"]:
        ld, er = a_["lock_distance"], a_["edge_retention"]
        L.append(f"| {a_['corner']}, {a_['temp_c']:g} C, {a_['vdd_v']:g} V | {a_['n60']*100:+.2f} % | {a_['p60']*100:+.2f} % | {a_['both60']*100:+.2f} % | {a_['additivity']:.3f} | "
                 + " / ".join(f"{ld[k]*100:.1f}%" for k in ("zero", "n60", "p60", "both60")) + " | " + " / ".join(f"{er[k]:.3f}" for k in ("zero", "n60", "p60", "both60")) + " |")
    L.append("")
    L += ["## Does DR-0003's operating point / DR-0004's health cutoffs stay inside this envelope? (model-derived)", "",
          "DR-0003 sizes N = 4 at T_s = 20 us with `Q_array` = 1.036 x M*Q_H0 at the entropy-binding corner (guaranteed H = 0.5415 vs the "
          "H0 = 0.5 target). DR-0004 evaluates its RCT/APT cutoffs at H = 0.5 (the design floor). Here `Q_array = sum_i sigma_1^2 T_s / T_i^3` "
          "with the array periods `T_i` at the same key (the DR-0003 loaded-period convention) and `H` the Baudet et al. bound `h_from_q`. "
          "Two variants are tabulated because a single-seed 20-period `sigma_1` carries ~16 % (1-sigma) estimator noise, i.e. ~32 % on Q, which "
          "is larger than the 3.6 % DR-0003 margin: **period-only** holds `sigma_1` at the matched zero-shift row and moves only `T_i` "
          "(the resolvable term, as DR-0003 sec. 3 / the #200 record did); **as-measured** uses each row's own corrected `sigma_1` "
          "(includes realization noise, so not monotone by construction). 'Margin exhausted' = common-mode shift where `Q_array` falls below "
          "zero-shift / 1.036; 'H<0.5' = shift where the bound crosses 0.5; linear interpolation between grid shifts, `>60` = not reached within the sweep.", "",
          "| corner | T | Vdd | Q ratio 20/40/60 mV (period-only) | H bound 0/20/40/60 mV (period-only) | margin exhausted at mV (period-only / as-measured) | H<0.5 at mV (period-only / as-measured) | H bound 60 mV (as-measured) |",
          "|---|---|---|---|---|---|---|---|"]
    f = lambda x: ">60" if x is None else f"{x:.1f}"
    for e in env["rows"]:
        p = e["points"]
        L.append(f"| {e['corner']} | {e['temp_c']:g} | {e['vdd_v']:g} | " + " / ".join(f"{q['q_ratio_period_only']:.3f}" for q in p[1:]) + " | "
                 + " / ".join(f"{q['h_bound_period_only']:.3f}" for q in p)
                 + f" | {f(e['shift_mv_q_margin_exhausted_period_only'])} / {f(e['shift_mv_q_margin_exhausted'])}"
                 + f" | {f(e['shift_mv_h_floor_crossed_period_only'])} / {f(e['shift_mv_h_floor_crossed'])} | {p[-1]['h_bound']:.3f} |")
    L += ["", summ["envelope_statement"], "",
          "No specification is changed or relaxed by this record, and no guard band or lifetime is ratified; any such decision belongs to an "
          "operator decision record (`spec/README.md`). " + SENTENCE, "",
          "Provisional, simulation-derived. Pre-layout, ideal gate offsets, single noise seed.", ""]
    return "\n".join(L)


def envelope_statement(env: dict) -> str:
    rows = env["rows"]
    if not rows:
        return "Envelope not evaluable (no usable paired rows)."
    qm = [e["shift_mv_q_margin_exhausted_period_only"] for e in rows]
    hf = [e["shift_mv_h_floor_crossed_period_only"] for e in rows]
    qmin = min((x for x in qm if x is not None), default=None)
    n_q = sum(1 for x in qm if x is not None)
    n_h = sum(1 for x in hf if x is not None)
    worst = min(rows, key=lambda e: e["points"][-1]["h_bound_period_only"])
    wp = worst["points"]
    z_h = min(rows, key=lambda e: e["points"][0]["h_bound_period_only"])
    zn = (f" Baseline caveat: the zero-shift H bound of this campaign is itself only as good as its single-seed `sigma_1` (stop 175n, a different noise "
          f"realization from the 115n records DR-0003 was sized on): it already reads {z_h['points'][0]['h_bound_period_only']:.3f} at "
          f"{z_h['corner']}/{z_h['temp_c']:g} C/{z_h['vdd_v']:g} V, below DR-0003's 0.5415, so absolute H values here are not a re-sizing; the movement "
          "relative to the matched zero-shift row is the usable quantity.")
    return (f"Result (period-only variant): the DR-0003 Q margin (1.036) is exhausted within the 0-60 mV sweep at {n_q}/{len(qm)} grid points"
            + (f", the earliest at a common-mode shift of {qmin:.1f} mV" if qmin is not None else "")
            + f". The model-derived H bound at 60 mV is lowest at {worst['corner']}/{worst['temp_c']:g} C/{worst['vdd_v']:g} V "
            f"({wp[-1]['h_bound_period_only']:.3f}, from {wp[0]['h_bound_period_only']:.3f} at zero shift) and falls below DR-0004's evaluation floor "
            f"H = 0.5 within 60 mV at {n_h}/{len(hf)} grid points. Reading: where the margin is exhausted, DR-0003's operating point is not robust to "
            "that part of the envelope as sized; where the H bound stays at or above 0.5 the DR-0004 cutoffs (conditional on H >= 0.5) remain valid as "
            "arithmetic, where it does not they are optimistic. This is a model bound over a first-order wrapper, not a prediction of when or whether any "
            "shift occurs." + zn)


def lock_by_shift(rows):
    """Closest small-rational approach over the common-mode grid, per shift (winning point named)."""
    out = {}
    for s_ in C.CM_SHIFTS_MV:
        pts = [r for r in rows if r["deck"] == "array" and r["ok"] and r["dvtn_mv"] == s_ and r["dvtp_mv"] == s_]
        if not pts:
            continue
        w = min(pts, key=lambda r: r["metrics"]["lock_proximity"]["distance"])
        out[str(s_)] = {"distance": w["metrics"]["lock_proximity"]["distance"], "pair": w["metrics"]["lock_proximity"]["pair"],
                        "rational": w["metrics"]["lock_proximity"]["rational"], "corner": w["corner"], "temp_c": w["temp_c"], "vdd_v": w["vdd_v"]}
    return out


def asymmetric_table(rows):
    """At each headline point: mean ring period and shifts for (0,0), (60,0), (0,60), (60,60), and the additivity
    ratio (60,60) shift / ((60,0) shift + (0,60) shift) -- 1 = additive, <1 = partial cancellation."""
    by = {r["key"]: r for r in rows}
    out = []
    for c, t, v in C.HEADLINE:
        g = lambda dn, dp: by.get(C.key_str("array", c, t, v, dn, dp))
        z, n_, p_, b_ = g(0, 0), g(60, 0), g(0, 60), g(60, 60)
        if not all(x and x["ok"] for x in (z, n_, p_, b_)):
            continue
        mean = lambda r: sum(r["metrics"][f"tr{i}"] for i in (1, 2, 3, 4)) / 4
        d = {k: mean(x) / mean(z) - 1 for k, x in (("n60", n_), ("p60", p_), ("both60", b_))}
        out.append({"corner": c, "temp_c": t, "vdd_v": v, **d, "additivity": d["both60"] / (d["n60"] + d["p60"]),
                    "lock_distance": {k: x["metrics"]["lock_proximity"]["distance"] for k, x in (("zero", z), ("n60", n_), ("p60", p_), ("both60", b_))},
                    "edge_retention": {k: x["metrics"]["edge_retention"] for k, x in (("zero", z), ("n60", n_), ("p60", p_), ("both60", b_))}})
    return out


def summarize(rows, ctl_rid):
    env = envelope(rows)
    return {"n_rows": len(rows), "n_required": len(C.required_keys()), "coverage_problems": coverage_problems(rows),
            "pair_problems": pair_rows(rows), "numerical_floor": numerical_floor(), "controls_record": ctl_rid,
            "envelope": env, "envelope_statement": envelope_statement(env),
            "lock_by_shift": lock_by_shift(rows), "asymmetric": asymmetric_table(rows),
            "all_rows_ok": all(r["ok"] for r in rows)}


def is_retry(name: str) -> bool:
    """`<request>--r<k>`: same-stop re-run of one failed unit; `<request>--f<k>`: fallback re-run with a nudged
    .tran stop (a different noise realization -- flagged on the row)."""
    return re.search(r"--[rf]\d+$", name) is not None


def select_rows(all_rows: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """One accepted row per key. A unit that failed in its original request may be re-run alone in a
    `<request>--r<k>` request (`make-requests.py --retry`); the first usable retry replaces the failed original.
    Failed originals that were superseded stay listed under `attempts` (never silently dropped). Returns
    (accepted, attempts, problems); two originals for one key, or a retry for a key whose original was fine,
    are problems (the manifest check also fails on duplicates)."""
    orig: dict[str, list[dict]] = {}
    retry: dict[str, list[dict]] = {}
    for r in all_rows:
        (retry if is_retry(r["request"]) else orig).setdefault(r["key"], []).append(r)
    accepted, attempts, probs = [], [], []
    for key in sorted(set(orig) | set(retry)):
        o = orig.get(key, [])
        rt = retry.get(key, [])
        if len(o) > 1:
            probs.append(f"duplicate original rows for {key}")
        if not o:
            probs.append(f"retry row without an original for {key}")
            accepted += rt[:1]
            continue
        first = o[0]
        if first["ok"]:
            if rt:
                probs.append(f"retry row for {key} whose original was usable")
            accepted.append(first)
            continue
        good = [x for x in rt if x["ok"]]
        if good:
            good[0]["retry_of"] = first["request"]
            accepted.append(good[0])
            attempts.append({"key": key, "request": first["request"], "job_id": first["job_id"], "problems": [first["problems"][0][:60] + " ... (all measurements missing: transient aborted)"],
                             "superseded_by": good[0]["request"]})
        else:
            accepted.append(first)
    return accepted, attempts, probs


def build(chunks, ctl_rid):
    floor = numerical_floor()
    all_rows = []
    for nm, pl, rs in chunks:
        all_rows += rows_from_response(nm, pl, rs, floor)
    rows, attempts, sel_probs = select_rows(all_rows)
    summ = summarize(rows, ctl_rid)
    summ["attempts"] = attempts
    summ["selection_problems"] = sel_probs
    return rows, summ


def emit_record(reqdir, ctl_rid):
    crec_path = SLUGDIR / "records" / f"{ctl_rid}.json"
    crec = json.load(open(crec_path))
    if crec.get("kind") != "controls" or not crec.get("pass"):
        raise SystemExit("error: controls record is not a PASSing controls record; the full grid may not be recorded")
    for k, f in (("generator_sha256", "campaign.py"), ("aging_sha256", "aging.py")):
        if crec["provenance"][k] != aging.sha256_file(SLUGDIR / f):
            raise SystemExit(f"error: {f} changed since the controls record {ctl_rid}; re-run the controls")
    chunks = load_reqdir(reqdir)
    rows, summ = build(chunks, ctl_rid)
    if summ["coverage_problems"] or summ["pair_problems"] or summ["selection_problems"] or not summ["all_rows_ok"]:
        print("coverage:", summ["coverage_problems"][:10], "selection:", summ["selection_problems"][:10], "pair:", summ["pair_problems"][:10], "all_ok:", summ["all_rows_ok"], file=sys.stderr)
        raise SystemExit("error: grid incomplete or has failed rows; not recording a partial grid as complete")
    sha = git_short_sha(REPO)
    now = datetime.datetime.now(datetime.timezone.utc)
    rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
    cdir, rdir = SLUGDIR / "corners" / rid, SLUGDIR / "records"
    if (rdir / f"{rid}.json").exists() or cdir.exists():
        raise SystemExit(f"error: {rid} exists")
    cdir.mkdir(parents=True)
    jobs = []
    for nm, pl, rs in chunks:
        with gzip.open(cdir / f"{nm}.klt-sim.json.gz", "wt") as fh:
            json.dump(rs, fh, indent=1)
        json.dump(pl, open(cdir / f"{nm}.plan.json", "w"), indent=1)
        for fn, dst in (("request.json", f"{nm}.request.json"), ("netlist.cir", f"{nm}.netlist.cir")):
            shutil.copyfile(os.path.join(reqdir, nm, fn), cdir / dst)
        jobs.append((rs.get("environment", {}).get("remote") or {}).get("job_id"))
        for ff in sorted(glob.glob(os.path.join(reqdir, nm, "resp.fail*.json"))):       # whole-request attempts that were superseded
            if os.path.getsize(ff):
                with gzip.open(cdir / f"{nm}.failed-attempt{ff.split('resp.fail')[1].split('.')[0]}.json.gz", "wt") as fh:
                    json.dump(json.load(open(ff)), fh, indent=1)
    claim = ("bounded Vth-shift (gate-offset wrapper) sensitivity of the RO array across PVT: ring5 jitter/period/Q_ring and ro_array_core "
             "ladder/fidelity/current at common-mode 0/20/40/60 mV plus asymmetric (60,0)/(0,60) mV headline cases. " + SENTENCE)
    cal = calibration_artifact(rid, rows)
    cal_path = rdir / f"{rid}.calibration.json"
    rec = {"record_id": rid, "slug": SLUG, "kind": "sensitivity", "level": "transistor", "status": PROV, "claim": claim,
           "seed": "ring5: .option seed=1 held constant across the grid; array: deterministic", "supersedes": "(none)",
           "pdk_commit": C.pdk_commit(), "controls_record": ctl_rid, "summary": summ,
           "provenance": {"generator_sha256": aging.sha256_file(SLUGDIR / "campaign.py"), "aging_sha256": aging.sha256_file(SLUGDIR / "aging.py"),
                          "wrapper_sha256": aging.sha256_text(aging.wrapper_definition()),
                          "manifest_sha256": aging.sha256_file(SLUGDIR / "coverage-manifest.json"),
                          "analysis_sha256": aging.sha256_file(HERE / "sensitivity.py")},
           "klt_sim": {"backend": "batch", "jobs": jobs,
                       "remote": [rs["environment"].get("remote") for _, _, rs in chunks],
                       "engine_version": chunks[0][2]["environment"]["engine_version"],
                       "models_lib_sha256": chunks[0][2]["environment"]["models_lib_sha256"],
                       "submitter_klt": chunks[0][2]["provenance"]["klt_version"],
                       "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"},
           "calibration_artifact": {"path": f"sim/{SLUG}/records/{rid}.calibration.json", "schema": CAL_SCHEMA,
                                    "sha256": sha256_json(cal), "n_entries": len(cal["entries"])},
           "rows": rows, "timestamp_utc": now.isoformat()}
    (rdir / f"{rid}.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    cal_path.write_text(json.dumps(cal, indent=2, sort_keys=True) + "\n")
    (rdir / f"{rid}.md").write_text(md_grid(rid, rows, summ["envelope"], summ, ctl_rid, jobs, claim))
    print(rid, "rows", len(rows), "cal entries", len(cal["entries"]))
    return 0


def check(recpath):
    """Replay from the committed raw responses; exit 1 on any difference."""
    rec = json.load(open(recpath))
    cdir = SLUGDIR / "corners" / rec["record_id"]
    if rec.get("kind") == "controls":
        names = sorted(p.name[:-len(".klt-sim.json.gz")] for p in cdir.glob("*.klt-sim.json.gz"))
        ctl = {}
        for n in names:
            with gzip.open(cdir / f"{n}.klt-sim.json.gz", "rt") as fh:
                ctl[n] = (json.load(open(cdir / f"{n}.plan.json")), json.load(fh))
        res = evaluate_controls(ctl, numerical_floor())
        same = json.loads(json.dumps(res, default=str)) == json.loads(json.dumps(rec["controls"], default=str))
        print("controls replay", "MATCHES" if same else "DIFFERS", recpath)
        return 0 if same else 1
    chunks = load_committed(str(cdir))
    rows, summ = build(chunks, rec["controls_record"])
    ok = json.loads(json.dumps(rows, default=str)) == rec["rows"] and \
        json.loads(json.dumps(summ, default=str)) == json.loads(json.dumps(rec["summary"], default=str))
    cal = calibration_artifact(rec["record_id"], rows)
    calp = Path(rec["calibration_artifact"]["path"])
    calp = REPO / calp
    ok_cal = calp.is_file() and json.load(open(calp)) == json.loads(json.dumps(cal, sort_keys=True)) \
        and sha256_json(cal) == rec["calibration_artifact"]["sha256"]
    # each stored request/netlist hash matches what the generator produces now
    ok_gen = True
    for nm, pl, rs in chunks:
        info = pl["info"]
        nl = (cdir / f"{nm}.netlist.cir").read_text()
        ok_gen &= aging.sha256_text(nl) == info["netlist_sha256"] == rs["provenance"]["input"]["content_hash"].split(":")[-1] or \
            aging.sha256_text(nl) == info["netlist_sha256"]
        regen, _meas, rinfo = C.build_deck(pl["deck"], pl["vdd_v"], stop=info["stop"])
        ok_gen &= regen == nl
    prov_ok = rec["provenance"]["generator_sha256"] == aging.sha256_file(SLUGDIR / "campaign.py") and \
        rec["provenance"]["aging_sha256"] == aging.sha256_file(SLUGDIR / "aging.py")
    manifest_ok = check_manifest() == 0
    print("replay rows/summary:", "MATCH" if ok else "DIFFER", "| calibration artifact:", "MATCH" if ok_cal else "DIFFER",
          "| netlists regenerate byte-identically:", "YES" if ok_gen else "NO", "| generator hashes:", "MATCH" if prov_ok else "DIFFER",
          "| manifest:", "OK" if manifest_ok else "BAD")
    return 0 if (ok and ok_cal and ok_gen and prov_ok and manifest_ok) else 1


def check_manifest():
    p = SLUGDIR / "coverage-manifest.json"
    if not p.is_file() or json.load(open(p)) != json.loads(json.dumps(C.manifest())):
        print("coverage-manifest.json differs from campaign.manifest()", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-controls")
    ap.add_argument("--emit-record")
    ap.add_argument("--controls")
    ap.add_argument("--check")
    ap.add_argument("--check-manifest", action="store_true")
    ap.add_argument("--write-manifest", action="store_true")
    a = ap.parse_args(argv)
    if a.write_manifest:
        (SLUGDIR / "coverage-manifest.json").write_text(json.dumps(C.manifest(), indent=1) + "\n")
        return 0
    if a.check_manifest:
        return check_manifest()
    if a.emit_controls:
        return emit_controls(a.emit_controls)
    if a.emit_record:
        if not a.controls:
            ap.error("--controls RID required")
        return emit_record(a.emit_record, a.controls)
    if a.check:
        return check(a.check)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
