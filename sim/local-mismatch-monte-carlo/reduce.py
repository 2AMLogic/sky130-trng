#!/usr/bin/env python3
"""Reduction for the local-mismatch Monte Carlo (issue #215).

    reduce.py --emit-record REQDIR     # one record per corner, from REQDIR/<corner>-<kind>-<n>/{plan,resp}.json
    reduce.py --check RECORD.json      # replay a record from its committed raw responses; exit 1 on any difference

Pure arithmetic over `klt sim` responses (no simulator). Per corner it derives:

  RO array (kind `arr`, one unit = one mismatch draw of the whole array)
    * per-ring period T_i = (t_42 - t_3) / 39 from 40 rising-edge times
    * per-ring fractional spread (sample std of T_i / mean T_i), and of the
      pooled per-ring deviation from the mismatch-free nominal ladder
    * per pair: closeness = min over rationals of |(f_i/f_j) / (p/q) - 1|
      (DR-0005's figure, p/q in {2/1, 3/2, 4/3}; and the same including 1:1, the
      mutual-lock case of adjacent rings); per draw the minimum over the six pairs
    * Q ratio vs the nominal ladder (DR-0003's 1.036 margin, T0^-3 term only)
    * xo mean level / vnom (DR-0003's 0.31-0.53 bias band) and duty(f) at nine thresholds
  Sampler (kind `smp`, one unit = one mismatch draw of one sampler_dff)
    * decision threshold = mean of the D value where Q flips going up / going down
    * input-referred offset = threshold minus the mismatch-free (plain section) threshold
  Raw-bit bias = P(raw = 1) for array draw i and sampler draw j: duty_i(vtrip_j / vnom)
    (the sampler resolves xo at ITS threshold); all n_array x n_sampler pairings.
    H_bias = -log2(max(p, 1-p)), and the SP 800-90B MCV estimator
    (sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py) run on a seeded Bernoulli stream
    at the worst-case p.  H_bias is an UPPER bound on that bit's min-entropy, not a
    jitter-entropy measurement.
  Model extrapolation (labelled as such): per-ring Gaussian fit of ln T from the MC
    sample, 200000 seeded draws -> P(min pair closeness < x). Independent rings (mismatch
    is independent per device); this extends the empirical tail, it is not simulated.

Simulation-derived; provisional until silicon.
"""
import datetime
import glob
import gzip
import importlib.util
import json
import math
import os
import random
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SLUG = "local-mismatch-monte-carlo"
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))

NEDGE = 40
E0 = 3
THRS = (30, 35, 40, 45, 50, 55, 60, 65, 70)
DR5_RATIOS = [(2, 1), (3, 2), (4, 3)]
ANY_RATIOS = [(1, 1), (2, 1), (3, 2), (4, 3)]
Q_MARGIN = 1.036                  # DR-0003 sec. 3
BIAS_BAND = (0.31, 0.53)          # DR-0003 sec. 3 (xo mean level / vnom)
H_FLOOR = 0.5                     # DR-0004 sec. 2.3
CLOSE_THRESH_PCT = (1.0, 2.0, 5.0)
EXTRAP_DRAWS = 200000
EXTRAP_SEED = 215
BERNOULLI_N = 100000
BERNOULLI_SEED = 215
PROV = "simulation-derived; provisional until silicon"
CLAIM = ("Local random device mismatch (sky130 `*_mm` Monte Carlo, vary=mismatch) of the committed pre-layout "
         "design/ro_array_core.spice (per-ring frequency spread, ring-pair lock proximity, combining-node bias) and "
         "of the sampler_dff decision threshold, propagated to raw-bit bias and a min-entropy bound (issue #215)")


# ---------------------------------------------------------------- pure functions
def mean(x):
    return sum(x) / len(x)


def std(x):
    """Sample standard deviation (n-1); 0.0 for fewer than 2 points."""
    if len(x) < 2:
        return 0.0
    m = mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def quantile(x, q):
    s = sorted(x)
    if not s:
        return None
    k = q * (len(s) - 1)
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def ring_period(edges):
    """edges: rising-edge times (s) -> mean period (s)."""
    return (edges[-1] - edges[0]) / (len(edges) - 1)


def closeness(Ti, Tj, ratios):
    """min over (p/q) >= 1 of |R / (p/q) - 1| where R = slower/faster period ratio (>= 1): DR-0005's
    figure (e.g. span 1.2096 against 4/3 -> 9.3 %).  Symmetric in i, j, so a mismatch-induced swap
    of two rings' order does not change it.  Returns (distance, p, q)."""
    R = max(Ti, Tj) / min(Ti, Tj)
    best = None
    for p, q in ratios:
        x = max(p, q) / min(p, q)
        d = abs(R / x - 1)
        if best is None or d < best[0]:
            best = (d, max(p, q), min(p, q))
    return best


def pair_closeness(T, ratios):
    """T: four ring periods -> (min closeness over the six pairs, 'i-j', 'p/q')."""
    best = None
    for i in range(len(T)):
        for j in range(i + 1, len(T)):
            d, p, q = closeness(T[i], T[j], ratios)
            if best is None or d < best[0]:
                best = (d, f"{i + 1}-{j + 1}", f"{p}/{q}")
    return best


def q_ratio(T, T0):
    return sum((T0[i] / T[i]) ** 3 for i in range(len(T))) / len(T)


def duty_at(duty, frac):
    """duty: {threshold percent -> P(xo > thr)}. Linear interpolation in the threshold
    fraction; linear extrapolation from the end segment outside 0.30..0.70, clamped to [0, 1]."""
    xs = sorted(duty)
    pts = [(x / 100.0, duty[x]) for x in xs]
    if frac <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    elif frac >= pts[-1][0]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
    else:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= frac <= x1:
                break
    y = y0 + (y1 - y0) * (frac - x0) / (x1 - x0)
    return min(1.0, max(0.0, y))


def h_bias(p):
    """Min-entropy of a Bernoulli(p) bit, bits per sample."""
    m = max(p, 1.0 - p)
    return -math.log2(m) if m < 1.0 else 0.0


def extrapolate_closeness(T_list, n_draws=EXTRAP_DRAWS, seed=EXTRAP_SEED):
    """Per-ring Gaussian fit of ln T from the MC sample, independent rings.
    Returns {x%: (P_dr5, P_any)} = P(min-pair closeness < x%)."""
    k = len(T_list[0])
    mu = [mean([math.log(t[r]) for t in T_list]) for r in range(k)]
    sd = [std([math.log(t[r]) for t in T_list]) for r in range(k)]
    rng = random.Random(seed)
    cnt5 = {x: 0 for x in CLOSE_THRESH_PCT}
    cnta = {x: 0 for x in CLOSE_THRESH_PCT}
    for _ in range(n_draws):
        T = [math.exp(rng.gauss(mu[r], sd[r])) for r in range(k)]
        c5 = pair_closeness(T, DR5_RATIOS)[0] * 100
        ca = pair_closeness(T, ANY_RATIOS)[0] * 100
        for x in CLOSE_THRESH_PCT:
            cnt5[x] += c5 < x
            cnta[x] += ca < x
    return {str(x): {"dr5": cnt5[x] / n_draws, "any": cnta[x] / n_draws} for x in CLOSE_THRESH_PCT}, mu, sd


def _load_raw_bit_entropy():
    p = os.path.join(REPO, "sim", "raw-bit-min-entropy", "analysis", "raw-bit-entropy.py")
    spec = importlib.util.spec_from_file_location("raw_bit_entropy", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mcv_on_bernoulli(p, n=BERNOULLI_N, seed=BERNOULLI_SEED):
    """Run the repo's SP 800-90B MCV estimator on a seeded Bernoulli(p) stream."""
    rbe = _load_raw_bit_entropy()
    rng = random.Random(seed)
    bits = [1 if rng.random() < p else 0 for _ in range(n)]
    est = rbe.mcv_estimate(bits)
    return {"n": n, "seed": seed, "p_target": p, "p_hat": est["p_hat"], "p_u_99": est["p_u_99"],
            "h_hat_bits": est["h_hat_bits"]}


# ---------------------------------------------------------------- response handling
def unit_meas(corner):
    return {x["name"]: x["value"] for x in corner["measurements"] if x.get("value") is not None}


def array_unit(c, plan):
    """One array corner entry -> row dict (or an error row)."""
    row = {"klt_status": c["status"], "klt_corner_id": c.get("corner_id"), "mc": c.get("monte_carlo")}
    try:
        if c["status"] != "pass":
            raise KeyError(f"klt status {c['status']}")
        m = unit_meas(c)
        vnom = plan["pvt"]["vnom"]
        T = [ring_period([m[f"t{r}_{k}"] for k in range(E0, E0 + NEDGE)]) for r in range(1, 5)]
        row["T_ns"] = [t * 1e9 for t in T]
        row["bias_xo"] = m["xo_avg"] / vnom
        row["duty"] = {str(f): m[f"duty{f}"] for f in THRS}
        d5 = pair_closeness(T, DR5_RATIOS)
        da = pair_closeness(T, ANY_RATIOS)
        row["close_dr5_pct"], row["close_dr5_pair"], row["close_dr5_ratio"] = d5[0] * 100, d5[1], d5[2]
        row["close_any_pct"], row["close_any_pair"], row["close_any_ratio"] = da[0] * 100, da[1], da[2]
        row["ok"] = True
    except (KeyError, ZeroDivisionError, ValueError) as e:
        row["ok"], row["error"] = False, repr(e)
    return row


def sampler_unit(c, plan):
    row = {"klt_status": c["status"], "klt_corner_id": c.get("corner_id"), "mc": c.get("monte_carlo")}
    try:
        if c["status"] != "pass":
            raise KeyError(f"klt status {c['status']}")
        m = unit_meas(c)
        row["vtrip_up_v"], row["vtrip_dn_v"] = m["vtrip_up"], m["vtrip_dn"]
        row["vtrip_v"] = 0.5 * (m["vtrip_up"] + m["vtrip_dn"])
        row["ok"] = True
    except (KeyError, ValueError) as e:
        row["ok"], row["error"] = False, repr(e)
    return row


def load_reqdir(reqdir):
    chunks = []
    for d in sorted(glob.glob(os.path.join(reqdir, "*-*-*"))):
        resp = os.path.join(d, "resp.json")
        if os.path.isfile(resp) and os.path.getsize(resp) > 0:
            r = json.load(open(resp))
            if "corners" in r:
                chunks.append((os.path.basename(d), json.load(open(os.path.join(d, "plan.json"))), r))
    return chunks


def summarize(corner, chunks):
    """chunks: [(name, plan, resp)] for ONE corner -> (rows, summary)."""
    pvt = chunks[0][1]["pvt"]
    vnom = pvt["vnom"]
    arr, smp, arr0, smp0 = [], [], [], []
    for name, plan, resp in chunks:
        for c in resp["corners"]:
            kind = plan["kind"]
            if kind == "arr":
                r = array_unit(c, plan)
                r["chunk"], r["seed"] = name, plan["monte_carlo"]["seed"]
                arr.append(r)
            elif kind == "smp":
                r = sampler_unit(c, plan)
                r["chunk"], r["seed"] = name, plan["monte_carlo"]["seed"]
                smp.append(r)
            elif kind == "arr0":
                arr0.append(array_unit(c, plan))
            elif kind == "smp0":
                smp0.append(sampler_unit(c, plan))
    if not (arr0 and arr0[0]["ok"] and smp0 and smp0[0]["ok"]):
        raise SystemExit(f"{corner}: no passing mismatch-free reference unit; refusing to derive offsets/ratios")
    nom_a, nom_s = arr0[0], smp0[0]
    T0 = [t * 1e-9 for t in nom_a["T_ns"]]
    good_a = [r for r in arr if r["ok"]]
    good_s = [r for r in smp if r["ok"]]
    S = {"corner": corner, "pvt": pvt, "n_array_requested": len(arr), "n_array_ok": len(good_a),
         "n_sampler_requested": len(smp), "n_sampler_ok": len(good_s),
         "seeds": sorted({r["seed"] for r in arr + smp}),
         "seeds_array": sorted({r["seed"] for r in arr}), "seeds_sampler": sorted({r["seed"] for r in smp})}
    # ---- nominal
    S["nominal"] = {"T_ns": nom_a["T_ns"], "span": max(nom_a["T_ns"]) / min(nom_a["T_ns"]),
                    "close_dr5_pct": nom_a["close_dr5_pct"], "close_dr5_pair": nom_a["close_dr5_pair"],
                    "close_dr5_ratio": nom_a["close_dr5_ratio"],
                    "close_any_pct": nom_a["close_any_pct"], "close_any_pair": nom_a["close_any_pair"],
                    "close_any_ratio": nom_a["close_any_ratio"],
                    "bias_xo": nom_a["bias_xo"], "vtrip_v": nom_s["vtrip_v"],
                    "vtrip_up_v": nom_s["vtrip_up_v"], "vtrip_dn_v": nom_s["vtrip_dn_v"],
                    "p1": duty_at(nom_a["duty"] and {int(k): v for k, v in nom_a["duty"].items()}, nom_s["vtrip_v"] / vnom)}
    S["nominal"]["h_bias"] = h_bias(S["nominal"]["p1"])
    if len(good_a) < 2 or len(good_s) < 2:
        S["error"] = "fewer than 2 usable Monte Carlo units"
        return arr + smp, S
    # ---- RO array
    Ts = [[t * 1e-9 for t in r["T_ns"]] for r in good_a]
    per_ring = []
    for k in range(4):
        col = [t[k] for t in Ts]
        per_ring.append({"ring": k + 1, "T_nom_ns": T0[k] * 1e9, "T_mean_ns": mean(col) * 1e9,
                         "sigma_T_pct": std(col) / mean(col) * 100,
                         "mean_shift_pct": (mean(col) / T0[k] - 1) * 100,
                         "T_min_ns": min(col) * 1e9, "T_max_ns": max(col) * 1e9})
    dev = [t[k] / T0[k] - 1 for t in Ts for k in range(4)]
    spans = [max(t) / min(t) for t in Ts]
    c5 = [r["close_dr5_pct"] for r in good_a]
    ca = [r["close_any_pct"] for r in good_a]
    worst5 = min(good_a, key=lambda r: r["close_dr5_pct"])
    worsta = min(good_a, key=lambda r: r["close_any_pct"])
    qs = [q_ratio(t, T0) for t in Ts]
    bx = [r["bias_xo"] for r in good_a]
    ext, mu, sd = extrapolate_closeness(Ts)
    S["array"] = {
        "per_ring": per_ring,
        "sigma_T_pct_pooled": std(dev) * 100,
        "ladder_span": {"min": min(spans), "mean": mean(spans), "max": max(spans)},
        "close_dr5_pct": {"min": min(c5), "p05": quantile(c5, 0.05), "median": quantile(c5, 0.5), "max": max(c5),
                          "worst_pair": worst5["close_dr5_pair"], "worst_ratio": worst5["close_dr5_ratio"],
                          "worst_sample": [worst5["chunk"], worst5["mc"]["sample_index"] if worst5.get("mc") else None],
                          "n_below": {str(x): sum(v < x for v in c5) for x in CLOSE_THRESH_PCT}},
        "close_any_pct": {"min": min(ca), "p05": quantile(ca, 0.05), "median": quantile(ca, 0.5), "max": max(ca),
                          "worst_pair": worsta["close_any_pair"], "worst_ratio": worsta["close_any_ratio"],
                          "worst_sample": [worsta["chunk"], worsta["mc"]["sample_index"] if worsta.get("mc") else None],
                          "n_below": {str(x): sum(v < x for v in ca) for x in CLOSE_THRESH_PCT}},
        "q_ratio": {"min": min(qs), "mean": mean(qs), "max": max(qs),
                    "n_below_margin": sum(q < 1 / Q_MARGIN for q in qs), "margin": 1 / Q_MARGIN},
        "bias_xo": {"min": min(bx), "mean": mean(bx), "max": max(bx),
                    "n_outside_band": sum(not (BIAS_BAND[0] <= b <= BIAS_BAND[1]) for b in bx), "band": list(BIAS_BAND)},
        "extrapolation": {"model": "independent per-ring Gaussian fit of ln T", "draws": EXTRAP_DRAWS, "seed": EXTRAP_SEED,
                          "ln_T_mean": mu, "ln_T_sd": sd, "p_min_close_below_pct": ext},
    }
    # ---- sampler
    vt = [r["vtrip_v"] for r in good_s]
    off = [(v - nom_s["vtrip_v"]) * 1e3 for v in vt]
    hyst = [(r["vtrip_up_v"] - r["vtrip_dn_v"]) * 1e3 for r in good_s]
    S["sampler"] = {"vtrip_v": {"mean": mean(vt), "min": min(vt), "max": max(vt)},
                    "vtrip_frac_vnom": {"mean": mean(vt) / vnom, "min": min(vt) / vnom, "max": max(vt) / vnom},
                    "offset_mv": {"mean": mean(off), "sigma": std(off), "min": min(off), "max": max(off),
                                  "max_abs": max(abs(o) for o in off)},
                    "hysteresis_mv": {"nominal": (nom_s["vtrip_up_v"] - nom_s["vtrip_dn_v"]) * 1e3,
                                      "mean": mean(hyst), "min": min(hyst), "max": max(hyst)},
                    "offset_resolution_mv": 1000 * 0.5 * vnom / 1.5e-6 * 10e-9}
    # ---- raw-bit bias over all array x sampler pairings
    duties = [{int(k): v for k, v in r["duty"].items()} for r in good_a]
    p_all, p_arr, p_smp = [], [], []
    worst = None
    for ia, d in enumerate(duties):
        p_arr.append(duty_at(d, nom_s["vtrip_v"] / vnom))
        for js, v in enumerate(vt):
            p = duty_at(d, v / vnom)
            p_all.append(p)
            if worst is None or abs(p - 0.5) > abs(worst[0] - 0.5):
                worst = (p, ia, js)
    nd = {int(k): v for k, v in nom_a["duty"].items()}
    p_smp = [duty_at(nd, v / vnom) for v in vt]
    pw = worst[0]
    S["raw_bit"] = {
        "n_pairings": len(p_all),
        "p1_all": {"min": min(p_all), "max": max(p_all), "mean": mean(p_all), "sigma": std(p_all),
                   "p05": quantile(p_all, 0.05), "p95": quantile(p_all, 0.95)},
        "p1_array_only": {"min": min(p_arr), "max": max(p_arr), "mean": mean(p_arr)},
        "p1_sampler_only": {"min": min(p_smp), "max": max(p_smp), "mean": mean(p_smp)},
        "worst_case": {"p1": pw, "bias": abs(pw - 0.5), "h_bias": h_bias(pw),
                       "array_sample": [good_a[worst[1]]["chunk"], (good_a[worst[1]].get("mc") or {}).get("sample_index")],
                       "sampler_sample": [good_s[worst[2]]["chunk"], (good_s[worst[2]].get("mc") or {}).get("sample_index")]},
        "h_bias_min": min(h_bias(p) for p in p_all),
        "h_bias_p05": quantile([h_bias(p) for p in p_all], 0.05),
        "n_pairings_below_floor": sum(h_bias(p) < H_FLOOR for p in p_all),
        "mcv_worst_case": mcv_on_bernoulli(pw),
        "mcv_nominal": mcv_on_bernoulli(S["nominal"]["p1"]),
    }
    S["verdict"] = {
        "h_floor": H_FLOOR,
        "h_floor_survives_bias_alone": S["raw_bit"]["h_bias_min"] >= H_FLOOR,
        "bias_band_n_outside": S["array"]["bias_xo"]["n_outside_band"],
        "q_margin_n_below": S["array"]["q_ratio"]["n_below_margin"],
        "lock_any_n_below_2pct": S["array"]["close_any_pct"]["n_below"]["2.0"],
    }
    return arr + smp, S


def build(chunks):
    by = {}
    for ch in chunks:
        by.setdefault(ch[1]["corner"], []).append(ch)
    return {cn: summarize(cn, chs) for cn, chs in by.items()}


# ---------------------------------------------------------------- rendering
def f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_md(rid, cn, S, jobs, sha, now):
    pv, nm = S["pvt"], S["nominal"]
    L = [f"# {rid} -- {SLUG}", "", f"**Claim**: {CLAIM}.", "",
         f"**Level**: transistor (pre-layout `design/ro_array_core.spice` and `sampler_dff`; deterministic transient per mismatch draw, NO injected noise)",
         f"**PVT point**: {pv['proc']} / {pv['temp']:g} degC / {pv['vnom']} V ({pv['why']}); MC section `{pv['proc']}_mm`, "
         f"`monte_carlo.vary = mismatch`. **Seeds**: array requests {S['seeds_array']}, sampler requests {S['seeds_sampler']} "
         f"(request i: seed0 + i - 1; per-sample seeds are in the .json rows).",
         f"**Status**: {PROV}. Not a silicon result, not an entropy measurement.", "",
         f"**Batch jobs**: " + ", ".join(f"`{j}`" for j in jobs), ""]
    if "error" in S:
        L += [f"**ERROR**: {S['error']}"]
        return "\n".join(L) + "\n"
    A, M, R = S["array"], S["sampler"], S["raw_bit"]
    L += [f"**Samples**: {S['n_array_ok']}/{S['n_array_requested']} array, {S['n_sampler_ok']}/{S['n_sampler_requested']} sampler.", "",
          "## RO array", "",
          f"Nominal (mismatch-free, plain `{pv['proc']}`) periods: " + ", ".join(f"{t:.4f}" for t in nm["T_ns"]) + f" ns; span {nm['span']:.4f}x; "
          f"closest approach DR-0005 rationals {nm['close_dr5_pct']:.2f}% ({nm['close_dr5_pair']} vs {nm['close_dr5_ratio']}); "
          f"adjacent-pair / 1:1 included {nm['close_any_pct']:.2f}% ({nm['close_any_pair']} vs {nm['close_any_ratio']}).", "",
          "| ring | T nominal (ns) | T mean (ns) | sigma_T (%) | mean shift (%) | T min..max (ns) |", "|---|---|---|---|---|---|"]
    for r in A["per_ring"]:
        L.append(f"| {r['ring']} | {r['T_nom_ns']:.4f} | {r['T_mean_ns']:.4f} | {r['sigma_T_pct']:.2f} | {r['mean_shift_pct']:+.2f} | {r['T_min_ns']:.3f}..{r['T_max_ns']:.3f} |")
    c5, ca = A["close_dr5_pct"], A["close_any_pct"]
    L += ["", f"Pooled sigma of T_i / T_i,nominal: **{A['sigma_T_pct_pooled']:.2f} %**. Ladder span (slowest/fastest) per draw: "
          f"{A['ladder_span']['min']:.3f} / {A['ladder_span']['mean']:.3f} / {A['ladder_span']['max']:.3f} (min / mean / max).", "",
          "**Lock proximity (minimum over the six ring pairs, per draw)**", "",
          "| measure | min | p05 | median | max | worst pair (ratio) | draws < 1% | < 2% | < 5% |", "|---|---|---|---|---|---|---|---|---|",
          f"| DR-0005 rationals 2/1, 3/2, 4/3 (%) | {c5['min']:.2f} | {c5['p05']:.2f} | {c5['median']:.2f} | {c5['max']:.2f} | {c5['worst_pair']} ({c5['worst_ratio']}) | {c5['n_below']['1.0']} | {c5['n_below']['2.0']} | {c5['n_below']['5.0']} |",
          f"| including 1:1 (%) | {ca['min']:.2f} | {ca['p05']:.2f} | {ca['median']:.2f} | {ca['max']:.2f} | {ca['worst_pair']} ({ca['worst_ratio']}) | {ca['n_below']['1.0']} | {ca['n_below']['2.0']} | {ca['n_below']['5.0']} |",
          "", "Model extrapolation (independent per-ring Gaussian fit of ln T, "
          f"{EXTRAP_DRAWS} seeded draws; NOT simulated): P(min pair closeness < x)", "",
          "| x | DR-0005 rationals | including 1:1 |", "|---|---|---|"]
    for x in CLOSE_THRESH_PCT:
        e = A["extrapolation"]["p_min_close_below_pct"][str(x)]
        L.append(f"| {x:g} % | {e['dr5']:.4f} | {e['any']:.4f} |")
    q, b = A["q_ratio"], A["bias_xo"]
    L += ["", f"Q_array ratio vs the nominal ladder (T0^-3 term only, sigma_1 not re-measured): min {q['min']:.4f} / mean {q['mean']:.4f} / max {q['max']:.4f}; "
          f"draws below DR-0003's 1/1.036 = {q['margin']:.4f}: **{q['n_below_margin']}**.",
          f"Combining-node bias `<v(xo)>/vnom`: min {b['min']:.4f} / mean {b['mean']:.4f} / max {b['max']:.4f} (nominal {nm['bias_xo']:.4f}); "
          f"draws outside DR-0003's band [{b['band'][0]}, {b['band'][1]}]: **{b['n_outside_band']}**.", "",
          "## Sampler", "",
          f"Decision threshold (mean of up/down trip): nominal {nm['vtrip_v']:.4f} V ({nm['vtrip_v'] / pv['vnom']:.4f} vnom); MC mean {M['vtrip_v']['mean']:.4f} V, "
          f"range {M['vtrip_v']['min']:.4f}..{M['vtrip_v']['max']:.4f} V.",
          f"Input-referred offset vs nominal: mean {M['offset_mv']['mean']:+.1f} mV, **sigma {M['offset_mv']['sigma']:.1f} mV**, range {M['offset_mv']['min']:+.1f}..{M['offset_mv']['max']:+.1f} mV "
          f"(measurement resolution ~{M['offset_resolution_mv']:.1f} mV). Hysteresis (up trip - down trip): nominal {M['hysteresis_mv']['nominal']:.1f} mV, MC {M['hysteresis_mv']['min']:.1f}..{M['hysteresis_mv']['max']:.1f} mV.", "",
          "## Raw-bit bias and min-entropy", "",
          f"P(raw = 1) = duty of xo above the sampler's threshold; {R['n_pairings']} array x sampler pairings. Nominal p = {nm['p1']:.4f}.", "",
          "| set | min | mean | max |", "|---|---|---|---|",
          f"| all pairings | {R['p1_all']['min']:.4f} | {R['p1_all']['mean']:.4f} | {R['p1_all']['max']:.4f} |",
          f"| array mismatch only (nominal sampler) | {R['p1_array_only']['min']:.4f} | {R['p1_array_only']['mean']:.4f} | {R['p1_array_only']['max']:.4f} |",
          f"| sampler mismatch only (nominal array) | {R['p1_sampler_only']['min']:.4f} | {R['p1_sampler_only']['mean']:.4f} | {R['p1_sampler_only']['max']:.4f} |", "",
          f"**Worst case**: p = {R['worst_case']['p1']:.4f}, bias |p - 0.5| = {R['worst_case']['bias']:.4f}, H_bias = {R['worst_case']['h_bias']:.4f} bit "
          f"(array {R['worst_case']['array_sample']}, sampler {R['worst_case']['sampler_sample']}). Min H_bias over all pairings {R['h_bias_min']:.4f}, "
          f"p05 {R['h_bias_p05']:.4f}; pairings below DR-0004's floor {H_FLOOR}: **{R['n_pairings_below_floor']}** of {R['n_pairings']}.",
          f"SP 800-90B MCV on a seeded Bernoulli stream ({BERNOULLI_N} bits, seed {BERNOULLI_SEED}): worst-case p -> H_hat {R['mcv_worst_case']['h_hat_bits']:.4f} "
          f"(p_u99 {R['mcv_worst_case']['p_u_99']:.4f}); nominal p -> H_hat {R['mcv_nominal']['h_hat_bits']:.4f}.", "",
          "H_bias bounds the bit's min-entropy from above (a biased bit cannot exceed it); it is not the jitter-limited entropy of DR-0003. "
          "The xo duty is measured at the nominal operating point's 40-edge window starting at 60 ns, not over a 20 us sample interval.", ""]
    L += ["---", f"Generated by `sim/{SLUG}/reduce.py` at {now.isoformat()} (git {sha}). {PROV}."]
    return "\n".join(L) + "\n"


def emit_record(reqdir, sha=None):
    from evidence_record import git_short_sha
    from pathlib import Path
    sha = sha or git_short_sha(Path(REPO))
    chunks = load_reqdir(reqdir)
    allc = build(chunks)
    base_now = datetime.datetime.now(datetime.timezone.utc)
    for n, cn in enumerate(sorted(allc), 1):
        rows, S = allc[cn]
        mine = [(nm, pl, rs) for nm, pl, rs in chunks if pl["corner"] == cn]
        now = base_now + datetime.timedelta(seconds=n)
        rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
        cdir = os.path.join(REPO, "sim", SLUG, "corners", rid)
        rdir = os.path.join(REPO, "sim", SLUG, "records")
        if os.path.exists(os.path.join(rdir, rid + ".json")) or os.path.exists(cdir):
            raise SystemExit(f"error: {rid} exists")
        os.makedirs(cdir)
        os.makedirs(rdir, exist_ok=True)
        jobs = []
        for nm, pl, rs in mine:
            with gzip.open(os.path.join(cdir, f"{nm}.klt-sim.json.gz"), "wt") as fh:
                json.dump(rs, fh, indent=1)
            json.dump(pl, open(os.path.join(cdir, f"{nm}.plan.json"), "w"), indent=1)
            for fn, dst in (("request.json", f"{nm}.request.json"), ("netlist.cir", f"{nm}.netlist.cir")):
                shutil.copyfile(os.path.join(reqdir, nm, fn), os.path.join(cdir, dst))
            jobs.append(((rs["environment"].get("remote") or {}).get("job_id")) or "local (single-unit reference run)")
        rec = {"record_id": rid, "slug": SLUG, "claim": CLAIM, "level": "transistor", "status": PROV,
               "seed": {"array": S["seeds_array"], "sampler": S["seeds_sampler"],
                        "rule": "klt monte_carlo.seed of request i = seed0 + i - 1; same seeds at every corner (paired draws)"},
               "pvt": S["pvt"],
               "testbench": f"sim/{SLUG}/testbench/ (via sim/{SLUG}/make-requests.py)",
               "klt_sim": {"jobs": jobs, "backend": "batch", "engine_version": mine[0][2]["environment"]["engine_version"],
                           "models_lib_sha256": mine[0][2]["environment"]["models_lib_sha256"],
                           "submitter_klt": sorted({rs["provenance"]["klt_version"] for _, _, rs in mine}),
                           "responses": f"sim/{SLUG}/corners/{rid}/*.klt-sim.json.gz"},
               "supersedes": "(none)", "summary": S, "rows": rows, "timestamp_utc": now.isoformat()}
        json.dump(rec, open(os.path.join(rdir, rid + ".json"), "w"), indent=2, default=str)
        open(os.path.join(rdir, rid + ".md"), "w").write(render_md(rid, cn, S, jobs, sha, now))
        print(rid, cn, S.get("verdict"))


def check(recpath):
    rec = json.load(open(recpath))
    cdir = os.path.join(REPO, "sim", SLUG, "corners", rec["record_id"])
    chunks = []
    for fn in sorted(glob.glob(os.path.join(cdir, "*.klt-sim.json.gz"))):
        nm = os.path.basename(fn)[:-len(".klt-sim.json.gz")]
        with gzip.open(fn, "rt") as fh:
            chunks.append((nm, json.load(open(os.path.join(cdir, nm + ".plan.json"))), json.load(fh)))
    rows, S = build(chunks)[rec["summary"]["corner"]]
    same = (json.loads(json.dumps(rows, default=str)) == rec["rows"]
            and json.loads(json.dumps(S, default=str)) == rec["summary"])
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
