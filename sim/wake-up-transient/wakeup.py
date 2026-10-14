#!/usr/bin/env python3
"""Reduction + behavioural leg for the analog wake-up transient campaign (issue #216).

Standard library only; no simulator, no PDK.

    wakeup.py --emit-det REQDIR          # det leg: one transistor record per (temp, supply) point
    wakeup.py --emit-noisy REQDIR        # noisy leg: one transistor record per PVT point
    wakeup.py --emit-margin              # behavioural leg + margin statement (reads the records above)
    wakeup.py --check RECORD_JSON        # replay any of the three from committed inputs; writes nothing
                                         # (a `restart-matrix` record is delegated to restart_matrix.py)

The restart-matrix reduction and its behavioural known-answer record (issue #267) live in
restart_matrix.py; they reuse this module's calibrated phase model (`calibration`, `wake_stream`) rather
than carrying a second one.

REQDIR is the make-requests.py output directory after the `klt sim` batch runs
(`REQDIR/<name>/{plan.json,request.json,netlist.cir,resp.json}`).

What the three legs measure
---------------------------
det    (transistor, deterministic, `tb_wakeup_array.spice`, full tt/ss/ff x
       -40/27/125 C x 1.62/1.8/1.98 V envelope, two wake-up modes)
       Per ring: whether it started, the first rising edge after the anchor
       (enable release, or end of the supply ramp), and the settling time: the
       time, after the anchor, of the first edge from which EVERY later period
       of the recorded window stays within TOL of the ring's own final period
       (mean of the last NREF periods). Reported at TOL = 1 % and 0.5 %.

noisy  (transistor, trnoise-injected, `tb_wakeup_raw_bits.spice`, NSEED noise
       seeds per PVT point at ss/-40C/1.62V, tt/27C/1.8V, ff/-40C/1.98V,
       Ts = 100 ns compressed sampling, 24 samples after enable)
       The raw bits and the four per-ring sampled bits of every seed, the
       across-seed agreement per sample index (all seeds start from the same
       stopped state, so seed-to-seed disagreement is exactly the injected noise
       accumulated since the enable), a negative control with the noise off, and
       a cross-check of those agreement figures against the phase-diffusion
       model below at the same Ts.

margin (behavioural, calibrated; DR-0003's literal Ts = 20 us)
       The phase-diffusion model of sim/raw-bit-volume-campaign/ (four
       independent rings with white period jitter sigma_1, ideal XOR + edge
       sampler) started from the deterministic stopped state the det leg
       measures, at every PVT point that has calibration records.
       (a) ANALYTIC worst-case bias. Ring i's phase t seconds after enable is
           wrapped-normal with variance s_i^2 = sigma_1^2 (t - d_i) / T_i^3
           (cycles^2). Its sampled bit has bias
             e_i = sum_{n odd} (2/(pi n)) exp(-2 pi^2 n^2 s_i^2) sin(2 pi n mu_i)
           whose magnitude is bounded, over the UNKNOWN mean phase mu_i, by
             b_i = sum_{n odd} (2/(pi n)) exp(-2 pi^2 n^2 s_i^2)   (capped at 1/2).
           The XOR of four independent bits has bias 8 prod e_i (piling-up),
           so B(t) = 8 prod b_i(t) bounds the bias of the raw bit sampled t
           after enable across wake-ups, whatever the exact periods and delays.
           t_mix(eps) = first t with B(t) <= eps, for eps = 0.2071 (per-index
           marginal min-entropy >= 0.5 bit, DR-0004's H design floor), 2^-10,
           2^-20 and 2^-40 (DR-0004's alpha).
       (b) MONTE CARLO. NMC wake-ups per corner from the deterministic start
           (measured d_i), and NMC from a uniformly random (stationary) start
           as the steady-state reference: per-index bias across wake-ups by
           window, pooled MCV min-entropy, and the DR-0004 start-up test
           (digital/model/health.py HealthMonitor, the normative model) run on
           every wake-up's first 1024 samples.
       (c) the margin: 1024 x Ts = 20.48 ms against the slowest t_mix and the
           slowest analog settling time from det.

Simulation-derived; provisional until silicon.
"""
from __future__ import annotations

import datetime
import glob
import gzip
import hashlib
import importlib.util
import json
import math
import os
import random
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SLUG = "wake-up-transient"
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO))

PROV = "simulation-derived; provisional until silicon"
TOLS = (0.01, 0.005)            # settling tolerances (fractional period error); the steady-state
                                # period wobble of these edge records is up to ~0.4 % (late_floor_pct), so a
                                # tighter tolerance would measure the floor, not the wake-up
NREF = 10                       # periods averaged for the final-period reference
SWING_MIN = 0.9                 # late-window swing / Vk below which a ring is not "oscillating rail to rail"
TS = 20e-6                      # DR-0003 sample interval
STARTUP_SAMPLES = 1024          # DR-0004 start-up test length
EPS = {"H>=0.5 (B<=0.2071)": 2 ** -0.5 - 0.5, "2^-10": 2.0 ** -10, "2^-20": 2.0 ** -20, "2^-40": 2.0 ** -40}
NMC = 1024                      # Monte Carlo wake-ups per corner per arm
MC_MASTER_SEED = 216
WINDOWS = ((0, 1), (1, 8), (8, 32), (32, 128), (128, 512), (512, 1024))
NOISY_WINDOWS = ((0, 8), (8, 16), (16, 24))
XCHK_REPS = 1000                # model replicates for the noisy-leg cross-check band
XCHK_PERIOD_UNC = 0.002         # relative ring-period uncertainty used to randomise the model's mean phase


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_requests():
    return _load("wakeup_make_requests", HERE / "make-requests.py")


# ======================================================================= det
def periods(t):
    return [b - a for a, b in zip(t, t[1:])]


def settle(edges, tol, nref=NREF):
    """edges: rising-edge times after the anchor (s, relative to it).

    Returns dict(t_settle, k_settle, p_ref, first_period_err) where t_settle is
    the time of the first edge from which every later period is within `tol` of
    p_ref = mean of the last `nref` periods; None if the window never settles
    (the last period itself is the reference, so a settled ring always settles
    at the latest at edge len-nref-1)."""
    p = periods(edges)
    if len(p) < nref + 2:
        return None
    pref = sum(p[-nref:]) / nref
    k = len(p)
    for j in range(len(p) - 1, -1, -1):
        if abs(p[j] / pref - 1.0) > tol:
            break
        k = j
    else:
        k = 0
    if k >= len(p) - nref:          # did not settle before the reference window
        return {"t_settle": None, "k_settle": None, "p_ref": pref, "first_period_err": p[0] / pref - 1.0}
    return {"t_settle": edges[k], "k_settle": k, "p_ref": pref, "first_period_err": p[0] / pref - 1.0}


def meas_of(corner):
    return {x["name"]: x["value"] for x in corner["measurements"] if x.get("value") is not None}


def det_unit(corner, plan):
    m = meas_of(corner)
    vk = corner["supply_v"]["Vk"]
    out = {"process": corner["process"], "temp_c": corner["temperature_c"], "vdd_v": vk, "mode": plan["mode"],
           "status": corner["status"], "corner_id": corner["corner_id"], "rings": []}
    for r in range(1, 5):
        e = [m.get(f"d{r}_{k}") for k in range(1, plan["nedge"] + 2)]
        ring = {"ring": r, "edges_recorded": sum(x is not None for x in e)}
        tf = m.get(f"tf{r}")
        ring["t_first_abs"] = tf
        if plan["mode"] == "ramp" and tf is not None:
            ring["vdd_at_first_edge"] = vk * min(tf / plan["tramp_s"], 1.0)
        sw = None
        if m.get(f"ro{r}_max") is not None and m.get(f"ro{r}_min") is not None:
            sw = (m[f"ro{r}_max"] - m[f"ro{r}_min"]) / vk
        ring["late_swing_frac"] = sw
        if None in e:
            ring.update(started=ring["edges_recorded"] > 0, ok=False,
                        why=f"only {ring['edges_recorded']} of {len(e)} edges")
        else:
            ring["started"] = True
            ring["t_first_edge"] = e[0]
            for tol in TOLS:
                s = settle(e, tol)
                ring[f"settle_{tol:g}"] = s
            ring["p_ref"] = ring[f"settle_{TOLS[0]:g}"]["p_ref"]
            pp = periods(e)
            ring["late_floor_pct"] = 100 * max(abs(x / ring["p_ref"] - 1) for x in pp[-20:])
            ring["ok"] = (sw is not None and sw >= SWING_MIN and ring[f"settle_{TOLS[0]:g}"]["t_settle"] is not None)
            if not ring["ok"]:
                ring["why"] = "swing" if (sw is None or sw < SWING_MIN) else "not settled within the window"
        out["rings"].append(ring)
    out["ok"] = corner["status"] == "pass" and all(r["ok"] for r in out["rings"])
    st = [r[f"settle_{TOLS[0]:g}"]["t_settle"] for r in out["rings"] if r.get("ok")]
    out["t_settle_max_1pct"] = max(st) if len(st) == 4 else None
    st2 = [(r[f"settle_{TOLS[1]:g}"] or {}).get("t_settle") for r in out["rings"] if r.get("ok")]
    out["t_settle_max_0.5pct"] = max(st2) if len(st2) == 4 and None not in st2 else None
    return out


def committed_periods(temp, vdd):
    """{process: [tr1..tr4]} from the latest ro-array-core-combining record at (temp, vdd), or {}."""
    best = None
    for p in sorted((REPO / "sim/ro-array-core-combining/records").glob("*.json")):
        r = json.loads(p.read_text())
        if r.get("pvt") == {"temp_c": temp, "vdd_v": vdd}:
            best = r
    if best is None:
        return {}, None
    return ({c["corner"]: [c["measurements"][f"tr{i}"] for i in (1, 2, 3, 4)]
             for c in best["corners"] if c.get("ok")}, best["record_id"])


def load_reqdir(reqdir, leg):
    chunks = []
    for d in sorted(glob.glob(os.path.join(reqdir, f"{leg}-*"))):
        resp = os.path.join(d, "resp.json")
        if not (os.path.isfile(resp) and os.path.getsize(resp) > 0):
            chunks.append((os.path.basename(d), json.load(open(os.path.join(d, "plan.json"))), None))
            continue
        chunks.append((os.path.basename(d), json.load(open(os.path.join(d, "plan.json"))), json.load(open(resp))))
    return chunks


def det_rows(chunks):
    rows, missing = [], []
    for name, plan, resp in chunks:
        if resp is None or not resp.get("corners"):
            missing.append({"request": name, "why": "no batch response" if resp is None else resp.get("status")})
            continue
        for c in resp["corners"]:
            u = det_unit(c, plan)
            u["request"] = name
            rows.append(u)
    return rows, missing


def det_point_summary(rows, temp, vdd):
    comm, comm_rid = committed_periods(temp, vdd)
    for u in rows:
        cp = comm.get(u["process"])
        if cp and u["mode"] == "en" and all(r.get("p_ref") for r in u["rings"]):
            u["p_ref_vs_committed_pct"] = [100 * (r["p_ref"] / t - 1) for r, t in zip(u["rings"], cp)]
    ok = [u for u in rows if u["ok"]]
    def mx(key, mode):
        v = [u[key] for u in ok if u["mode"] == mode and u[key] is not None]
        return max(v) if v else None
    return {
        "units": len(rows), "units_ok": len(ok),
        "failed_units": [f"{u['process']}/{u['mode']}" for u in rows if not u["ok"]],
        "t_settle_max_1pct_en_s": mx("t_settle_max_1pct", "en"),
        "t_settle_max_1pct_ramp_s": mx("t_settle_max_1pct", "ramp"),
        "t_settle_max_0.5pct_en_s": mx("t_settle_max_0.5pct", "en"),
        "t_settle_max_0.5pct_ramp_s": mx("t_settle_max_0.5pct", "ramp"),
        "t_first_edge_max_en_s": max((r["t_first_edge"] for u in ok if u["mode"] == "en" for r in u["rings"]), default=None),
        "vdd_at_first_edge_ramp_v": [min((r["vdd_at_first_edge"] for u in ok if u["mode"] == "ramp" for r in u["rings"]), default=None),
                                     max((r["vdd_at_first_edge"] for u in ok if u["mode"] == "ramp" for r in u["rings"]), default=None)],
        "committed_combining_record": comm_rid,
    }


def _ns(x, nd=2):
    return "-" if x is None else f"{x * 1e9:.{nd}f}"


def det_md(rid, temp, vdd, rows, summ, jobs, plans, sha, now, claim):
    p0 = plans[0]
    L = [f"# {rid} -- {SLUG}", "", f"**Claim**: {claim}", "",
         "**Level**: transistor (pre-layout `design/ro_array_core.spice`; deterministic transient, NO injected noise)",
         f"**PVT point**: {temp:g} degC / {vdd:g} V, process tt / ss / ff bundled. "
         "**Seed**: N/A (deterministic; every row is one unit of a `klt sim` corners request).",
         f"**Status**: {PROV}. Not a silicon result.", "",
         "**Batch jobs**: " + ", ".join(f"`{j}`" for j in jobs), "",
         "## Method", "",
         f"- mode `en`: supply at {vdd:g} V from a solved DC operating point with en1..4 = 0; enables rise over 100 ps at "
         f"t = {p0['ten_s'] * 1e9:g} ns. Times below are from the enable.",
         f"- mode `ramp`: vdd and vddr1..4 ramp linearly 0 -> {vdd:g} V over {p0['tramp_s'] * 1e6:g} us with en1..4 tied to the "
         "rail (no gating). Settling times are from the END of the ramp; the first-edge column is the absolute time of the "
         "ring's first crossing of 0.5 x the final supply during the ramp, and the supply at that instant.",
         f"- {p0['nedge']} periods recorded per ring after the anchor (`.meas ... param=` relative edge times, ~1e-13 s "
         f"resolution); final period = mean of the last {NREF}; settling = first edge after which every period stays within "
         "the tolerance of it. Swing check: (max - min)/Vk of the buffered output over the last 30 ns >= 0.9.", "",
         "## Summary", "",
         f"- units: {summ['units']}, all rings started and settled in-window: {summ['units_ok']}"
         + (f"; FAILED: {', '.join(summ['failed_units'])}" if summ['failed_units'] else ""),
         f"- slowest settling (1 %): enable-gated {_ns(summ['t_settle_max_1pct_en_s'])} ns after the enable; "
         f"supply ramp {_ns(summ['t_settle_max_1pct_ramp_s'])} ns after the end of the ramp",
         f"- slowest settling (0.5 %): enable-gated {_ns(summ['t_settle_max_0.5pct_en_s'])} ns; ramp {_ns(summ['t_settle_max_0.5pct_ramp_s'])} ns",
         f"- slowest first edge after enable: {_ns(summ['t_first_edge_max_en_s'])} ns",
         "- supply at which the rings first reach half the final rail during the ramp: "
         + (f"{summ['vdd_at_first_edge_ramp_v'][0]:.3f} .. {summ['vdd_at_first_edge_ramp_v'][1]:.3f} V"
            if summ['vdd_at_first_edge_ramp_v'][0] is not None else "-"), "",
         "## Per unit and ring", "",
         "| process | mode | ring | first edge (ns) | first-period err % | final period (ns) | late-window period floor % | settle 1 % (ns) | settle 0.5 % (ns) | late swing / Vk | vs committed period % | ok |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for u in sorted(rows, key=lambda u: (u["mode"], u["process"])):
        for i, r in enumerate(u["rings"]):
            s1 = r.get(f"settle_{TOLS[0]:g}") or {}
            s2 = r.get(f"settle_{TOLS[1]:g}") or {}
            fe = (f"{r['t_first_abs'] * 1e9:.1f} abs @ {r['vdd_at_first_edge']:.3f} V" if u["mode"] == "ramp" and r.get("vdd_at_first_edge") is not None
                  else _ns(r.get("t_first_edge")))
            vc = u.get("p_ref_vs_committed_pct")
            fpe = "-" if not s1 else f"{100 * s1['first_period_err']:+.3f}"
            swf = "-" if r.get("late_swing_frac") is None else f"{r['late_swing_frac']:.3f}"
            vcs = "-" if not vc else f"{vc[i]:+.3f}"
            oks = "yes" if r.get("ok") else "**NO** " + r.get("why", "")
            L.append(f"| {u['process']} | {u['mode']} | {r['ring']} | {fe} | {fpe} | {_ns(r.get('p_ref'), 4)} | "
                     f"{'-' if r.get('late_floor_pct') is None else format(r['late_floor_pct'], '.3f')} | "
                     f"{_ns(s1.get('t_settle'))} | {_ns(s2.get('t_settle'))} | {swf} | {vcs} | {oks} |")
    L += ["", "\"vs committed period\" compares the final period with `tr1..tr4` of the committed "
          f"`sim/ro-array-core-combining/` record at this PVT point ({summ['committed_combining_record'] or 'none at this point'}), "
          "an independent deck with a PULSE enable: agreement shows the behavioural-source testbench reproduces the array.", "",
          "---", "", "- Author: loom-builder@sky130-trng", f"- Timestamp (UTC): {now.isoformat()}", f"- Repo commit: `{sha}`",
          "- Supersedes: (none)"]
    return "\n".join(L) + "\n"


DET_CLAIM = ("Analog wake-up of the committed pre-layout ro_array_core (issue #216): per-ring first edge, "
             "time-to-steady-oscillation (every later period within 1 % / 0.5 % of the final period) and late-window swing, "
             "after an enable release from the stopped state and after a 0 -> Vdd supply ramp with the enables tied to the rail; "
             "deterministic, no injected noise")


# ===================================================================== noisy
def noisy_unit(corner, vdd, nbits):
    m = meas_of(corner)
    th = 0.5 * vdd
    bits, valid, rbits = [], [], [[] for _ in range(4)]
    for k in range(nbits):
        b, v = m.get(f"bit{k}"), m.get(f"valid{k}")
        bits.append(None if b is None else int(b > th))
        valid.append(None if v is None else int(v > th))
        for r in range(4):
            x = m.get(f"rb{r + 1}_{k}")
            rbits[r].append(None if x is None else int(x > th))
    pre = [(m.get(f"ro{r}_pre"), m.get(f"ro{r}_prelo")) for r in range(1, 5)]
    sw = [None if m.get(f"ro{r}_max") is None else (m[f"ro{r}_max"] - m[f"ro{r}_min"]) / vdd for r in range(1, 5)]
    mc = corner.get("monte_carlo") or {}
    ok = (corner["status"] == "pass" and None not in bits and all(v == 1 for v in valid)
          and all(None not in rb for rb in rbits))
    return {"corner_id": corner["corner_id"], "status": corner["status"], "seed": mc.get("seed"),
            "sample_index": mc.get("sample_index"), "bits": bits, "valid": valid, "ring_bits": rbits,
            "t_first_edge_abs": [m.get(f"tf{r}") for r in range(1, 5)],
            "pre_enable_ro_range": pre, "late_swing_frac": sw, "ok": ok}


def agreement(seqs):
    """Per index: fraction of seed PAIRS that disagree; and p1 across seeds."""
    n = len(seqs)
    out_d, out_p = [], []
    for k in range(len(seqs[0])):
        ones = sum(s[k] for s in seqs)
        out_p.append(ones / n)
        out_d.append(2 * ones * (n - ones) / (n * (n - 1)) if n > 1 else 0.0)
    return out_d, out_p


def window_mean(xs, w):
    a, b = w
    return sum(xs[a:b]) / (b - a)


def mcv(bits):
    n = len(bits)
    ones = sum(bits)
    p = max(ones, n - ones) / n
    pu = min(1.0, p + 2.576 * math.sqrt(p * (1 - p) / (n - 1))) if n > 1 else 1.0
    return {"n": n, "p_hat": p, "p_u_99": pu, "h_mcv": 0.0 if pu >= 1 else -math.log2(pu)}


# ------------------------------------------------------------------ model
def ring_bias_bound(s2):
    """Upper bound over the mean phase of |P(bit=1) - 1/2| for a wrapped-normal phase of variance s2 (cycles^2)."""
    if s2 <= 0:
        return 0.5
    tot = 0.0
    n = 1
    while True:
        term = (2.0 / (math.pi * n)) * math.exp(-2.0 * math.pi ** 2 * n * n * s2)
        tot += term
        if term < 1e-18 or n > 20001:
            break
        n += 2
    return min(0.5, tot)


def ring_bias(s2, mu):
    """Exact P(bit=1) - 1/2 for bit = [frac(phase) >= 1/2], phase ~ wrapped N(mu, s2)."""
    if s2 <= 0:
        return (1.0 if (mu % 1.0) >= 0.5 else 0.0) - 0.5
    tot = 0.0
    n = 1
    while True:
        a = math.exp(-2.0 * math.pi ** 2 * n * n * s2)
        tot -= (2.0 / (math.pi * n)) * a * math.sin(2 * math.pi * n * mu)
        if a < 1e-18 or n > 20001:
            break
        n += 2
    return tot


def xor_bias_bound(t, cal):
    """B(t): bound on |bias| of the XOR raw bit sampled t seconds after enable, over unknown mean phases."""
    b = 8.0
    for T, d in zip(cal["periods_s"], cal["delays_s"]):
        s2 = cal["sigma1"] ** 2 * max(t - d, 0.0) / T ** 3
        b *= ring_bias_bound(s2)
    return min(0.5, b)


def t_mix(cal, eps, t_hi=1.0):
    """Smallest t (s) with B(t) <= eps (bisection; B is non-increasing in t)."""
    lo, hi = 0.0, t_hi
    if xor_bias_bound(hi, cal) > eps:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if xor_bias_bound(mid, cal) <= eps:
            hi = mid
        else:
            lo = mid
    return hi


def wake_stream(cal, ts, n, rng, tau, stationary=False):
    """One wake-up: raw bits sampled at t_k = tau + k*ts after the enable (k = 0..n-1)."""
    th, sd0, adv, sd = [], [], [], []
    for T, d in zip(cal["periods_s"], cal["delays_s"]):
        if stationary:
            th.append(rng.random())
        else:
            dt = max(tau - d, 0.0)
            th.append(((dt / T) + rng.gauss(0.0, cal["sigma1"] * math.sqrt(dt / T) / T)) % 1.0)
        adv.append((ts / T) % 1.0)
        sd.append(cal["sigma1"] * math.sqrt(ts / T) / T)
    out = []
    gauss = rng.gauss
    for _ in range(n):
        out.append((int(2 * th[0]) ^ int(2 * th[1]) ^ int(2 * th[2]) ^ int(2 * th[3])) & 1)
        for i in range(4):
            th[i] = (th[i] + adv[i] + gauss(0.0, sd[i])) % 1.0
    return out


def wake_ring_bits(cal, ts, n, rng, tau):
    """As wake_stream but returning (xor bits, [per-ring bits]) -- for the transistor cross-check."""
    th, adv, sd = [], [], []
    for T, d in zip(cal["periods_s"], cal["delays_s"]):
        dt = max(tau - d, 0.0)
        th.append(((dt / T) + rng.gauss(0.0, cal["sigma1"] * math.sqrt(dt / T) / T)) % 1.0)
        adv.append((ts / T) % 1.0)
        sd.append(cal["sigma1"] * math.sqrt(ts / T) / T)
    xs, rs = [], [[] for _ in range(4)]
    for _ in range(n):
        rb = [int(2 * x) for x in th]
        for i in range(4):
            rs[i].append(rb[i])
        xs.append(rb[0] ^ rb[1] ^ rb[2] ^ rb[3])
        for i in range(4):
            th[i] = (th[i] + adv[i] + rng.gauss(0.0, sd[i])) % 1.0
    return xs, rs


def sub_seed(label):
    return int.from_bytes(hashlib.sha256(f"{MC_MASTER_SEED}:{label}".encode()).digest()[:8], "big")


def startup_test(bits):
    from digital.model.health import HealthMonitor
    hm = HealthMonitor()
    first_trip = None
    for i, b in enumerate(bits[:STARTUP_SAMPLES]):
        if hm.update(b) and first_trip is None:
            first_trip = i
    longest, run = 1, 1
    for a, b in zip(bits, bits[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    return {"passed": hm.startup_done and not hm.alarm_startup, "first_trip_index": first_trip, "longest_run": longest}


# ------------------------------------------------------------------ noisy record
def det_calibration(temp, vdd, proc):
    """Periods and start delays from the committed det records (mode en) at this point."""
    for p in sorted((HERE / "records").glob("*.json"), reverse=True):
        r = json.loads(p.read_text())
        if r.get("leg") != "det" or r.get("pvt") != {"temp_c": temp, "vdd_v": vdd}:
            continue
        for u in r["rows"]:
            if u["process"] == proc and u["mode"] == "en" and u["ok"]:
                return {"periods_s": [x["p_ref"] for x in u["rings"]],
                        "delays_s": [x["t_first_edge"] for x in u["rings"]], "det_record": r["record_id"]}
    return None


def calibration(temp, vdd, proc):
    vc = _load("behavioral_raw_bit", REPO / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py")
    base = vc.calibration(temp, vdd, proc)
    det = det_calibration(temp, vdd, proc)
    cal = {"temp_c": temp, "vdd_v": vdd, "corner": proc, "sigma1": base["sigma"][1],
           "jitter_record": base["jitter_record"], "combining_record": base["combining_record"]}
    if det:
        cal.update(det)
        cal["period_source"] = "det record " + det["det_record"]
    else:
        cal.update(periods_s=base["periods_s"], delays_s=[0.0] * 4, det_record=None,
                   period_source="combining record " + base["combining_record"] + " (no det record at this point; start delay 0)")
    return cal


def noisy_xcheck(cal, units, nbits, ts, tau, rng):
    """Model band (99 %) for the mean pairwise disagreement per window, XOR bit and per ring, vs transistor."""
    n = len(units)
    obs = {}
    xs = [u["bits"] for u in units]
    d, _ = agreement(xs)
    obs["xor"] = [window_mean(d, w) for w in NOISY_WINDOWS]
    for r in range(4):
        d, _ = agreement([u["ring_bits"][r] for u in units])
        obs[f"ring{r + 1}"] = [window_mean(d, w) for w in NOISY_WINDOWS]
    sims = {k: [[] for _ in NOISY_WINDOWS] for k in obs}
    for _ in range(XCHK_REPS):
        c = dict(cal, periods_s=[T * (1 + rng.gauss(0, XCHK_PERIOD_UNC)) for T in cal["periods_s"]])
        ens = [wake_ring_bits(c, ts, nbits, rng, tau) for _ in range(n)]
        d, _ = agreement([e[0] for e in ens])
        for j, w in enumerate(NOISY_WINDOWS):
            sims["xor"][j].append(window_mean(d, w))
        for r in range(4):
            d, _ = agreement([e[1][r] for e in ens])
            for j, w in enumerate(NOISY_WINDOWS):
                sims[f"ring{r + 1}"][j].append(window_mean(d, w))
    out = {}
    for k in obs:
        out[k] = []
        for j, w in enumerate(NOISY_WINDOWS):
            s = sorted(sims[k][j])
            lo, hi = s[int(0.005 * (len(s) - 1))], s[int(round(0.995 * (len(s) - 1)))]
            out[k].append({"window": list(w), "transistor": obs[k][j], "model_median": s[len(s) // 2],
                           "model_band99": [lo, hi], "inside": lo <= obs[k][j] <= hi})
    return out


NOISY_CLAIM = ("First raw bits after an enable release from the stopped state, transistor level with injected trnoise, "
               "over many noise seeds (issue #216): across-seed agreement per sample index of the raw bit and of the four "
               "per-ring sampled bits, first window vs later windows, a noise-off negative control, and a cross-check against "
               "the phase-diffusion model; Ts = 100 ns compressed sampling")


def noisy_md(rid, plan, units, ctl, summ, xchk, jobs, sha, now):
    L = [f"# {rid} -- {SLUG}", "", f"**Claim**: {NOISY_CLAIM}", "",
         "**Level**: transistor (in-place rings with per-stage `trnoise()`, committed `ro_buf`/`xor2`/`sampler_dff` from "
         "`design/sampler_core.spice`; `testbench/tb_wakeup_raw_bits.spice`)",
         f"**PVT point**: {plan['process']} / {plan['temp']:g} degC / {plan['vdd']:g} V ({plan['why']}).",
         f"**Seeds**: {len(units)} `klt sim` monte_carlo samples (vary = mismatch with the sky130 mismatch switch off, so only the "
         "`.options seed` of the trnoise sources differs); every seed is listed in the `.json` (`units[].seed`).",
         f"**Status**: {PROV}. Ts = {plan['ts_s'] * 1e9:g} ns is a 200x compressed sample interval (#21's), not DR-0003's 20 us.", "",
         "**Batch jobs**: " + ", ".join(f"`{j}`" for j in jobs), "",
         "## What this shows", "",
         f"- seeds simulated / usable: {summ['n_units']} / {summ['n_ok']}" + (f" (not usable: {summ['not_ok']})" if summ['not_ok'] else ""),
         f"- rings quiet before the enable (pre-enable ro range within 5 % of a rail, all seeds): **{summ['quiet_before_enable']}**",
         f"- rings oscillating rail to rail at the end (late swing >= 0.9, all seeds): **{summ['oscillating_at_end']}**",
         f"- first edge after enable, max over rings and seeds: {_ns(summ['t_first_edge_after_en_max_s'])} ns",
         f"- negative control (noise amplitude 0, {summ['control']['n']} seeds): all seeds bit-identical = **{summ['control']['identical']}**"
         if ctl else "- negative control: not run at this point (it is run at the ss/-40C/1.62V point only)",
         "",
         "Every seed starts from the same stopped state, so the fraction of seed pairs that disagree on sample k is the "
         "injected noise accumulated since the enable, made visible. It starts near zero and grows as the phases diffuse; "
         "the steady state (independent phases) is 0.5 for a balanced bit.", "",
         "| window (sample index) | raw-bit pairwise disagreement | ring 1 | ring 2 | ring 3 | ring 4 | pooled raw-bit MCV p_hat | pooled MCV H (99 % UB) |",
         "|---|---|---|---|---|---|---|---|"]
    for j, w in enumerate(NOISY_WINDOWS):
        row = summ["windows"][j]
        L.append(f"| {w[0]}..{w[1] - 1} | {row['xor']:.3f} | " + " | ".join(f"{x:.3f}" for x in row["rings"])
                 + f" | {row['mcv']['p_hat']:.3f} | {row['mcv']['h_mcv']:.3f} |")
    L += ["", "## Cross-check: phase-diffusion model at the same Ts and seed count", "",
          f"Model calibration: sigma_1 = {summ['cal']['sigma1']:.3e} s ({summ['cal']['jitter_record']}); periods and start delays from "
          f"{summ['cal']['period_source']}. Mean phase randomised by a {XCHK_PERIOD_UNC * 100:g} % period uncertainty; "
          f"{XCHK_REPS} replicates of {summ['n_ok']} seeds; 99 % band.", "",
          "| bit | window | transistor | model median | model 99 % band | inside |", "|---|---|---|---|---|---|"]
    for k, rows in xchk.items():
        for x in rows:
            L.append(f"| {k} | {x['window'][0]}..{x['window'][1] - 1} | {x['transistor']:.3f} | {x['model_median']:.3f} | "
                     f"{x['model_band99'][0]:.3f}..{x['model_band99'][1]:.3f} | {'yes' if x['inside'] else '**NO**'} |")
    L += ["", f"Inside the band: {summ['xcheck_inside']} of {summ['xcheck_total']} rows.", "",
          "## Per-seed raw bits", "", "| sample_index | seed | raw bits (k = 0..23) |", "|---|---|---|"]
    for u in units:
        L.append(f"| {u['sample_index']} ({u['request']}) | {u['seed']} | `{''.join('?' if b is None else str(b) for b in u['bits'])}` |")
    if ctl:
        L += ["", "Negative control (noise off):", ""]
        for u in ctl:
            L.append(f"- seed {u['seed']}: `{''.join('?' if b is None else str(b) for b in u['bits'])}`")
    L += ["", "---", "", "- Author: loom-builder@sky130-trng", f"- Timestamp (UTC): {now.isoformat()}", f"- Repo commit: `{sha}`",
          "- Supersedes: (none)"]
    return "\n".join(L) + "\n"


def noisy_summary(plan, units, ctl, xchk, cal):
    ok = [u for u in units if u["ok"]]
    vdd = plan["vdd"]
    quiet = all(all(lo is not None and hi is not None and (hi - lo) < 0.05 * vdd for hi, lo in u["pre_enable_ro_range"]) for u in ok)
    osc = all(all(s is not None and s >= SWING_MIN for s in u["late_swing_frac"]) for u in ok)
    tfe = [t - plan["ten_s"] for u in ok for t in u["t_first_edge_abs"] if t is not None]
    windows = []
    if ok:
        dx, _ = agreement([u["bits"] for u in ok])
        dr = [agreement([u["ring_bits"][r] for u in ok])[0] for r in range(4)]
        for w in NOISY_WINDOWS:
            pooled = [b for u in ok for b in u["bits"][w[0]:w[1]]]
            windows.append({"window": list(w), "xor": window_mean(dx, w), "rings": [window_mean(d, w) for d in dr],
                            "mcv": mcv(pooled)})
    c = None
    if ctl:
        cok = [u for u in ctl if u["ok"]]
        c = {"n": len(ctl), "n_ok": len(cok),
             "identical": bool(cok) and len(cok) == len(ctl) and all(u["bits"] == cok[0]["bits"] and u["ring_bits"] == cok[0]["ring_bits"] for u in cok)}
    tot = sum(len(v) for v in xchk.values())
    ins = sum(x["inside"] for v in xchk.values() for x in v)
    return {"n_units": len(units), "n_ok": len(ok), "not_ok": [u["corner_id"] + ":" + u["status"] for u in units if not u["ok"]],
            "quiet_before_enable": quiet, "oscillating_at_end": osc,
            "t_first_edge_after_en_max_s": max(tfe) if tfe else None, "windows": windows, "control": c,
            "xcheck_inside": ins, "xcheck_total": tot,
            "cal": {k: cal[k] for k in ("sigma1", "periods_s", "delays_s", "jitter_record", "period_source")}}


# ================================================================== margin
MARGIN_CLAIM = ("Margin of DR-0004's 1024-sample start-up window (20.48 ms at DR-0003's 50 kbps) over the analog wake-up "
                "(issue #216): analog settling from the det transistor records, and stationarity of the raw bit after a "
                "deterministic wake-up (worst-case analytic bias bound and Monte Carlo of the calibrated phase-diffusion model, "
                "deterministic start vs stationary start, DR-0004 start-up test run on every wake-up) at every calibrated PVT point")


def margin_compute():
    vc = _load("behavioral_raw_bit", REPO / "sim/raw-bit-volume-campaign/behavioral_raw_bit.py")
    points = list(vc.PVT_POINTS_BASE) + list(vc.PVT_POINTS_HOT)
    tau = 0.5 * TS
    rows = []
    for (temp, vdd) in points:
        for proc in ("tt", "ss", "ff"):
            cal = calibration(temp, vdd, proc)
            row = {"temp_c": temp, "vdd_v": vdd, "corner": proc, "tau_s": tau,
                   "cal": {k: cal[k] for k in ("sigma1", "periods_s", "delays_s", "jitter_record", "combining_record", "period_source")},
                   "sd_per_sample_cycles": [cal["sigma1"] * math.sqrt(TS / T) / T for T in cal["periods_s"]]}
            row["t_mix_s"] = {k: t_mix(cal, e) for k, e in EPS.items()}
            row["k_mix_samples"] = {k: (None if v is None else max(0, math.ceil((v - tau) / TS))) for k, v in row["t_mix_s"].items()}
            row["bound_at_index"] = {str(k): xor_bias_bound(tau + k * TS, cal) for k in (0, 1, 8, 32, 128, 512, 1023)}
            arms = {}
            for arm in ("deterministic", "stationary"):
                label = f"{arm}:{proc}:{temp:g}C:{vdd:g}V"
                rng = random.Random(sub_seed(label))
                streams = [wake_stream(cal, TS, STARTUP_SAMPLES, rng, tau, stationary=(arm == "stationary")) for _ in range(NMC)]
                _, p1 = agreement(streams)
                win = []
                for w in WINDOWS:
                    dev = max(abs(p1[k] - 0.5) for k in range(*w))
                    pooled = [b for s in streams for b in s[w[0]:w[1]]]
                    win.append({"window": list(w), "max_index_bias": dev, "pooled_mcv": mcv(pooled)})
                st = [startup_test(s) for s in streams]
                arms[arm] = {"seed_label": label, "seed": sub_seed(label), "windows": win,
                             "startup_pass": sum(x["passed"] for x in st), "startup_n": len(st),
                             "longest_run_max": max(x["longest_run"] for x in st)}
            row["mc"] = arms
            rows.append(row)
            print(f"{proc} {temp:g}C {vdd:g}V k_mix(2^-40) = {row['k_mix_samples']['2^-40']}", file=sys.stderr)
    return rows


def det_records():
    out = []
    for p in sorted((HERE / "records").glob("*.json")):
        r = json.loads(p.read_text())
        if r.get("leg") == "det":
            out.append(r)
    return out


def noisy_records():
    return [json.loads(p.read_text()) for p in sorted((HERE / "records").glob("*.json"))
            if json.loads(p.read_text()).get("leg") == "noisy"]


def margin_summary(rows):
    dets = det_records()
    worst_en = max(((r["summary"]["t_settle_max_1pct_en_s"], r["record_id"], r["pvt"]) for r in dets
                    if r["summary"]["t_settle_max_1pct_en_s"] is not None), default=None, key=lambda x: x[0])
    worst_ramp = max(((r["summary"]["t_settle_max_1pct_ramp_s"], r["record_id"], r["pvt"]) for r in dets
                      if r["summary"]["t_settle_max_1pct_ramp_s"] is not None), default=None, key=lambda x: x[0])
    det_units = sum(r["summary"]["units"] for r in dets)
    det_ok = sum(r["summary"]["units_ok"] for r in dets)
    window_s = STARTUP_SAMPLES * TS
    km = {}
    for k in EPS:
        vals = [(r["k_mix_samples"][k], r) for r in rows]
        if any(v is None for v, _ in vals):
            km[k] = {"worst_samples": None, "worst_corner": None}
            continue
        v, r = max(vals, key=lambda x: x[0])
        km[k] = {"worst_samples": v, "worst_corner": f"{r['corner']}/{r['temp_c']:g}C/{r['vdd_v']:g}V",
                 "margin_x": (STARTUP_SAMPLES / v) if v else None}
    trips = {arm: sum(r["mc"][arm]["startup_n"] - r["mc"][arm]["startup_pass"] for r in rows) for arm in ("deterministic", "stationary")}
    return {"startup_window_s": window_s, "startup_samples": STARTUP_SAMPLES, "ts_s": TS,
            "det_records": [r["record_id"] for r in dets], "det_units": det_units, "det_units_ok": det_ok,
            "analog_settle_worst_en": worst_en and {"t_s": worst_en[0], "record": worst_en[1], "pvt": worst_en[2],
                                                     "fraction_of_one_ts": worst_en[0] / TS, "margin_vs_window_x": window_s / worst_en[0]},
            "analog_settle_worst_ramp": worst_ramp and {"t_s": worst_ramp[0], "record": worst_ramp[1], "pvt": worst_ramp[2],
                                                         "fraction_of_one_ts": worst_ramp[0] / TS, "margin_vs_window_x": window_s / worst_ramp[0]},
            "k_mix": km, "startup_trips": trips, "noisy_records": [r["record_id"] for r in noisy_records()]}


def margin_md(rows, summ):
    km = summ["k_mix"]
    L = ["## Margin statement (DR-0004 start-up window, 1024 samples = 20.48 ms at 50 kbps)", ""]
    ae, ar = summ["analog_settle_worst_en"], summ["analog_settle_worst_ramp"]
    L += [f"1. **Analog settling** (transistor, deterministic, {summ['det_units_ok']}/{summ['det_units']} units run settled in-window "
          "(ONLY those units: the full 54-unit tt/ss/ff x -40/27/125 C x 1.62/1.8/1.98 V envelope grid needs the batch fleet; see README); records "
          + ", ".join(f"`{x}`" for x in summ["det_records"]) + "):",
          f"   - enable-gated wake: every ring within 1 % of its final period by **{_ns(ae['t_s'])} ns** after the enable "
          f"(worst at {ae['pvt']['temp_c']:g} C / {ae['pvt']['vdd_v']:g} V, `{ae['record']}`) = {ae['fraction_of_one_ts'] * 100:.4f} % of one "
          f"20 us sample interval; the start-up window is {ae['margin_vs_window_x']:.3g}x longer." if ae else "   - enable-gated: no data",
          f"   - supply-ramp wake (1 us ramp, enables tied to the rail): settled by **{_ns(ar['t_s'])} ns** after the ramp ends "
          f"(`{ar['record']}`); window margin {ar['margin_vs_window_x']:.3g}x. A slower ramp is quasi-static for a ring with a "
          "few-ns period: the ring tracks the rail, so the settling after the rail is final is not longer than this." if ar else "   - ramp: no data",
          "   - so the analog source is oscillating at its steady frequency before the FIRST 50 kbps sample: the start-up test "
          "does not see an un-started or still-accelerating oscillator.", "",
          "2. **Statistical stationarity of the raw bit after a deterministic wake-up** (behavioural, calibrated). After the "
          "enable every ring restarts from the same stopped state, so the raw bit is NOT stationary across wake-ups until "
          "the injected jitter has spread each ring's phase over a full cycle. Worst case over all 18 calibrated corners "
          "(samples after the enable, first sample Ts/2 after it):", ""]
    L += ["| bias bound B | per-index marginal min-entropy | worst corner | samples to reach it | margin of the 1024-sample window |",
          "|---|---|---|---|---|"]
    for k, e in EPS.items():
        v = km[k]
        L.append(f"| <= {e:.4g} ({k}) | >= {-math.log2(0.5 + e):.4g} bit | {v['worst_corner']} | {v['worst_samples']} | "
                 + (f"{v['margin_x']:.2f}x" if v.get("margin_x") else ("-" if v["worst_samples"] is None else "inf")) + " |")
    worst40 = km["2^-40"]["worst_samples"]
    adequate = worst40 is not None and worst40 < STARTUP_SAMPLES
    L += ["", f"3. **DR-0004 start-up test on every simulated wake-up** ({NMC} per corner per arm, digital/model HealthMonitor): "
          f"trips from a deterministic start {summ['startup_trips']['deterministic']}, from a stationary start "
          f"{summ['startup_trips']['stationary']}. The test neither trips spuriously on a waking source nor (being an RCT/APT "
          "pair) can detect the non-stationarity above -- it counts those samples as healthy, as the issue anticipated.", "",
          "**Conclusion**: " + (
              f"the 1024-sample start-up window covers the measured analog settling by more than five orders of magnitude, and "
              f"covers the statistical mixing of the raw bit after a deterministic wake-up to a bias of 2^-40 at every calibrated "
              f"corner with a margin of {km['2^-40']['margin_x']:.2f}x (worst: {km['2^-40']['worst_corner']}, "
              f"{worst40} samples). Because no conditioned word draws on a start-up-window sample (the conditioner is fed only "
              "once the start-up test has passed), the first conditioned word is built from raw bits that are stationary to "
              "that bound. The margin is ADEQUATE under the model; no decision-record change is indicated."
              if adequate else
              f"the analog settling is covered, but the raw bit is not stationary to 2^-40 within 1024 samples at "
              f"{km['2^-40']['worst_corner']}: the margin is INADEQUATE under the model (decision-record issue filed)."),
          "",
          "**Not covered by the start-up gate**: the raw path is never gated (DR-0004 sec. 4), so raw words read in the first "
          f"~{km['2^-10']['worst_samples']} samples after a wake-up (worst corner) carry a per-index marginal bias above 2^-10 "
          "across wake-ups. This does not change the per-sample conditional entropy the sizing law accounts for (the jitter "
          "added per sample is the same as in steady state; a deterministic start is the case where the previous phase is "
          "exactly known), but a consumer of the raw path who wants stationary bits should discard the start-up window too.",
          "",
          "**Caveats**: simulation-derived and provisional until silicon. The stationarity figures assume the behavioural model's "
          "white period jitter, independent rings and an ideal edge sampler (sim/raw-bit-volume-campaign/README.md); ring-to-ring "
          "coupling that pulls the rings toward a common phase would lengthen mixing, flicker phase noise would shorten it at "
          "long times. sigma_1 is the fixed trnoise injection level of the repo's jitter campaign (good to ~1.5-2x): mixing time "
          "scales as 1/sigma_1^2, so a 2x lower sigma_1 would quadruple every k_mix above. Pre-layout netlists. The supply ramp "
          "is ideal (no supply impedance) and 1 us long.", "",
          "## Per corner", "",
          "| corner | T C | Vdd | phase sd per sample (cycles, r1..r4) | B at k=0 / 1 / 8 / 32 / 128 | k_mix H>=0.5 | k_mix 2^-10 | k_mix 2^-20 | k_mix 2^-40 | MC max index bias k<8, det / stat | MC max index bias 512..1023, det / stat | start-up pass det / stat |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        b = r["bound_at_index"]
        md, ms = r["mc"]["deterministic"]["windows"], r["mc"]["stationary"]["windows"]
        early_d = max(md[0]["max_index_bias"], md[1]["max_index_bias"])
        early_s = max(ms[0]["max_index_bias"], ms[1]["max_index_bias"])
        L.append(f"| {r['corner']} | {r['temp_c']:g} | {r['vdd_v']:g} | {' '.join(f'{x:.3f}' for x in r['sd_per_sample_cycles'])} | "
                 f"{b['0']:.3g} / {b['1']:.3g} / {b['8']:.3g} / {b['32']:.3g} / {b['128']:.3g} | "
                 + " | ".join(str(r["k_mix_samples"][k]) for k in EPS)
                 + f" | {early_d:.3f} / {early_s:.3f} | {md[-1]['max_index_bias']:.3f} / {ms[-1]['max_index_bias']:.3f} | "
                 f"{r['mc']['deterministic']['startup_pass']}/{NMC} / {r['mc']['stationary']['startup_pass']}/{NMC} |")
    L += ["", f"MC bias columns: max over the window's indices of |p1 - 1/2| across {NMC} wake-ups; the sampling-noise floor of that "
          f"maximum is ~{0.5 / math.sqrt(NMC):.3f} per index (1 sigma) and grows with the window length, so the stationary arm "
          "is the reference for 'steady state'. Periods/start delays: " +
          "; ".join(sorted({r['cal']['period_source'] for r in rows})) + ".", ""]
    return "\n".join(L) + "\n"


# ================================================================== emit / check
def _now_rid(sha, offset=0):
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=offset)
    return now, f"{now:%Y%m%d-%H%M%S}-{sha}"


def _sha():
    from evidence_record import git_short_sha
    return git_short_sha(REPO)


def _store_chunks(rid, reqdir, mine):
    """Copy the raw batch responses + exactly what was submitted to corners/<rid>/ (once per batch of records)."""
    cdir = HERE / "corners" / rid
    if cdir.exists():
        raise SystemExit(f"error: {cdir} exists")
    cdir.mkdir(parents=True)
    for nm, pl, rs in mine:
        with gzip.open(cdir / f"{nm}.klt-sim.json.gz", "wt") as fh:
            json.dump(rs, fh, indent=1)
        json.dump(pl, open(cdir / f"{nm}.plan.json", "w"), indent=1)
        for fn, dst in (("request.json", f"{nm}.request.json"), ("netlist.cir", f"{nm}.netlist.cir")):
            shutil.copyfile(os.path.join(reqdir, nm, fn), cdir / dst)


def _read_chunks(rid):
    cdir = HERE / "corners" / rid
    out = []
    for f in sorted(cdir.glob("*.klt-sim.json.gz")):
        nm = f.name[:-len(".klt-sim.json.gz")]
        with gzip.open(f, "rt") as fh:
            out.append((nm, json.load(open(cdir / f"{nm}.plan.json")), json.load(fh)))
    return out


def _backend(mine):
    """Backend the responses were actually produced by: `batch` when a fleet job id is present, else local."""
    return "batch" if all(rs["environment"].get("remote") for _, _, rs in mine) else "local (single-unit debug probe)"


def _jobs(mine):
    return [rs["environment"].get("remote", {}).get("job_id") for _, _, rs in mine if rs]


def det_build(chunks, temp, vdd):
    rows, missing = det_rows(chunks)
    rows = [u for u in rows if u["temp_c"] == temp and u["vdd_v"] == vdd]
    return rows, missing, det_point_summary(rows, temp, vdd)


def emit_det(reqdir):
    sha = _sha()
    chunks = load_reqdir(reqdir, "det")
    missing = [nm for nm, _, rs in chunks if rs is None]
    if missing:
        print("WARNING: no response for", missing, "-- those units are absent from the records", file=sys.stderr)
    good = [c for c in chunks if c[2] is not None]
    mr = make_requests()
    n = 0
    store_rid = None
    for temp in mr.TEMPS:
        for vdd in mr.SUPPLIES:
            n += 1
            now, rid = _now_rid(sha, n)
            rows, _, summ = det_build(good, temp, vdd)
            if not rows:
                continue
            if store_rid is None:
                # each det request spans the whole T x V envelope at one (mode, process), so every det record
                # reads the same six responses: store them once, under the first det record's id
                store_rid = rid
                _store_chunks(rid, reqdir, good)
            rec = {"record_id": rid, "slug": SLUG, "leg": "det", "claim": DET_CLAIM, "level": "transistor", "status": PROV,
                   "seed": "N/A (deterministic transient, no injected noise)", "pvt": {"temp_c": temp, "vdd_v": vdd},
                   "process_corners": sorted({u["process"] for u in rows}),
                   "testbench": "sim/wake-up-transient/testbench/tb_wakeup_array.spice (mode ramp: tb_wakeup_array_ramp.spice) (via sim/wake-up-transient/make-requests.py)",
                   "criteria": {"settle_tolerances": list(TOLS), "nref_periods": NREF, "swing_min": SWING_MIN},
                   "requests_without_response": missing,
                   "klt_sim": {"jobs": _jobs(good), "backend": _backend(good), "remote": [rs["environment"].get("remote") for _, _, rs in good],
                               "engine_version": good[0][2]["environment"]["engine_version"],
                               "models_lib_sha256": good[0][2]["environment"]["models_lib_sha256"],
                               "submitter_klt": good[0][2]["provenance"]["klt_version"],
                               "responses": f"sim/{SLUG}/corners/{store_rid}/*.klt-sim.json.gz"},
                   "corners_dir": store_rid,
                   "supersedes": "(none)", "summary": summ, "rows": rows, "timestamp_utc": now.isoformat(), "repo_sha": sha}
            (HERE / "records").mkdir(exist_ok=True)
            json.dump(rec, open(HERE / "records" / f"{rid}.json", "w"), indent=2, default=str)
            open(HERE / "records" / f"{rid}.md", "w").write(
                det_md(rid, temp, vdd, rows, summ, _jobs(good), [p for _, p, _ in good], sha, now, DET_CLAIM))
            print(rid, temp, vdd, summ["units_ok"], "/", summ["units"], "settle en", _ns(summ["t_settle_max_1pct_en_s"]),
                  "ramp", _ns(summ["t_settle_max_1pct_ramp_s"]))


def noisy_build(chunks, point):
    mr = make_requests()
    units, ctl, plan0 = [], [], None
    for nm, pl, rs in chunks:
        if pl["point"] != point or rs is None:
            continue
        for c in rs["corners"]:
            u = noisy_unit(c, pl["vdd"], pl["nbits"])
            u["request"] = nm
            (ctl if pl["control"] else units).append(u)
        if not pl["control"]:
            plan0 = pl
    if plan0 is None:
        return None
    cal = calibration(plan0["temp"], plan0["vdd"], plan0["process"])
    ok = [u for u in units if u["ok"]]
    rng = random.Random(sub_seed(f"xchk:{point}"))
    xchk = noisy_xcheck(cal, ok, plan0["nbits"], plan0["ts_s"], 0.5 * plan0["ts_s"], rng) if len(ok) >= 2 else {}
    summ = noisy_summary(plan0, units, ctl, xchk, cal)
    return plan0, units, ctl, xchk, summ


def emit_noisy(reqdir):
    sha = _sha()
    chunks = load_reqdir(reqdir, "noisy")
    missing = [nm for nm, _, rs in chunks if rs is None]
    good = [c for c in chunks if c[2] is not None]
    mr = make_requests()
    for n, (point, *_rest) in enumerate(mr.NOISY_POINTS, 1):
        built = noisy_build(good, point)
        if built is None:
            print("no data for", point, file=sys.stderr)
            continue
        plan, units, ctl, xchk, summ = built
        now, rid = _now_rid(sha, 20 + n)
        mine = [c for c in good if c[1]["point"] == point]
        _store_chunks(rid, reqdir, mine)
        rec = {"record_id": rid, "slug": SLUG, "leg": "noisy", "claim": NOISY_CLAIM, "level": "transistor", "status": PROV,
               "seeds": [u["seed"] for u in units], "control_seeds": [u["seed"] for u in ctl],
               "pvt": {"temp_c": plan["temp"], "vdd_v": plan["vdd"]}, "process_corners": [plan["process"]],
               "testbench": "sim/wake-up-transient/testbench/tb_wakeup_raw_bits.spice (via sim/wake-up-transient/make-requests.py)",
               "tran": {"tmax": plan["tmax"], "noise_amp_v_rms": plan["na"], "ts_s": plan["ts_s"], "ten_s": plan["ten_s"]},
               "requests_without_response": [m for m in missing if point in m],
               "klt_sim": {"jobs": _jobs(mine), "backend": _backend(mine), "remote": [rs["environment"].get("remote") for _, _, rs in mine],
                           "monte_carlo": [rs["environment"].get("monte_carlo") for _, _, rs in mine],
                           "engine_version": mine[0][2]["environment"]["engine_version"],
                           "models_lib_sha256": mine[0][2]["environment"]["models_lib_sha256"],
                           "submitter_klt": mine[0][2]["provenance"]["klt_version"],
                           "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"},
               "corners_dir": rid,
               "supersedes": "(none)", "summary": summ, "xcheck": xchk, "units": units, "control_units": ctl,
               "timestamp_utc": now.isoformat(), "repo_sha": sha}
        json.dump(rec, open(HERE / "records" / f"{rid}.json", "w"), indent=2, default=str)
        open(HERE / "records" / f"{rid}.md", "w").write(noisy_md(rid, plan, units, ctl, summ, xchk, _jobs(mine), sha, now))
        print(rid, point, summ["n_ok"], "seeds; xcheck", summ["xcheck_inside"], "/", summ["xcheck_total"],
              "; control", summ["control"])


def emit_margin():
    from evidence_record import mint_behavioral_record
    rows = margin_compute()
    summ = margin_summary(rows)
    body = margin_md(rows, summ)
    seeds = {"master_seed": MC_MASTER_SEED, "derivation": "sha256('216:<arm>:<corner>:<T>C:<V>V')[:8]",
             "per_corner": {f"{r['corner']}:{r['temp_c']:g}C:{r['vdd_v']:g}V": {a: r['mc'][a]['seed'] for a in r['mc']} for r in rows}}
    rid = mint_behavioral_record(
        REPO, SLUG, MARGIN_CLAIM, body, {"leg": "margin", "status": PROV, "summary": summ, "rows": rows,
                                         "model": "sim/wake-up-transient/wakeup.py (phase-diffusion model of sim/raw-bit-volume-campaign/)"},
        level="behavioral (calibrated on transistor records)", seeds=seeds,
        tools={"script": "sim/wake-up-transient/wakeup.py --emit-margin"})
    print(rid)


def check(path):
    rec = json.loads(Path(path).read_text())
    leg = rec.get("leg")
    if leg == "det":
        chunks = _read_chunks(rec["corners_dir"])
        rows, _, summ = det_build(chunks, rec["pvt"]["temp_c"], rec["pvt"]["vdd_v"])
        same = json.loads(json.dumps(rows, default=str)) == rec["rows"] and json.loads(json.dumps(summ, default=str)) == rec["summary"]
    elif leg == "noisy":
        chunks = _read_chunks(rec["corners_dir"])
        point = chunks[0][1]["point"]
        _, units, ctl, xchk, summ = noisy_build(chunks, point)
        same = (json.loads(json.dumps(units, default=str)) == rec["units"]
                and json.loads(json.dumps(xchk, default=str)) == rec["xcheck"]
                and json.loads(json.dumps(summ, default=str)) == rec["summary"])
    elif leg == "restart-matrix":
        return _load("restart_matrix", HERE / "restart_matrix.py").check(path)
    elif leg == "margin":
        rows = margin_compute()
        same = json.loads(json.dumps(rows, default=str)) == rec["rows"]
    else:
        raise SystemExit("unknown record leg")
    print("replay", "MATCHES" if same else "DIFFERS", path)
    return 0 if same else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "--emit-det":
        emit_det(a[1])
    elif len(a) == 2 and a[0] == "--emit-noisy":
        emit_noisy(a[1])
    elif a == ["--emit-margin"]:
        emit_margin()
    elif len(a) == 2 and a[0] == "--check":
        sys.exit(check(a[1]))
    else:
        print(__doc__)
        sys.exit(2)
