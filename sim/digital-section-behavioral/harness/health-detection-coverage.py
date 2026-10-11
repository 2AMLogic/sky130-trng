#!/usr/bin/env python3
"""Experiment I: health-test detection coverage on correlated raw streams.

Sibling of ``digital-section-campaign.py`` (experiments A-H, i.i.d. stimuli
only). This harness drives ``digital/model/health.py`` (RCT + APT at the
DR-0004 cutoffs, nothing re-derived or relaxed) with serially-correlated and
quasi-periodic streams whose per-bit min-entropy is known *analytically*, and
records for each stream: the analytic min-entropy, whether the online tests
alarm, the detection latency, and what the non-MCV SP 800-90B estimators of
``sim/raw-bit-min-entropy/analysis/raw-bit-battery.py`` (issue #189) say.

Families (all seeded, all explicitly synthetic):

``markov``    two-state chain, P(1|1) = a, P(0|0) = b. Analytic min-entropy
              rate is -log2 of the maximum cycle geometric mean,
              max(a, b, sqrt((1-a)(1-b))).
``periodic``  a seeded balanced length-k pattern repeated, each bit flipped
              independently with probability eps. The pattern is treated as
              KNOWN to the adversary (a locked oscillator is repeatable), so
              the per-bit min-entropy is -log2(1 - eps).
``lock-mix``  alternating segments of length L: a locked segment (period-2
              pattern, flip noise eps_lock) for a fraction f of each L-bit
              period and a free-running fair-coin segment for the rest.
              Schedule treated as known: H = (1-f)*1 + f*(-log2(1-eps_lock)).

These are SYNTHETIC LOGIC STIMULI. No claim is made about sky130 silicon or
about the real source's entropy. "Caught by an estimator" means its point
estimate is below the design target H_DESIGN; the estimators are the repo's
labelled approximations, not a validated 90B implementation.

Usage::

    python3 sim/digital-section-behavioral/harness/health-detection-coverage.py
    python3 sim/digital-section-behavioral/harness/health-detection-coverage.py --emit-record
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import random
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402
from model.health import HealthMonitor  # noqa: E402
from model.params import C_APT, C_RCT, H_DESIGN, STARTUP_SAMPLES, W_APT  # noqa: E402

_BATTERY = REPO_ROOT / "sim" / "raw-bit-min-entropy" / "analysis" / "raw-bit-battery.py"
sys.path.insert(0, str(_BATTERY.parent))
_spec = importlib.util.spec_from_file_location("raw_bit_battery", _BATTERY)
battery = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(battery)

DEFAULT_SEED = 20261011
DEFAULT_N = 65536
RAW_RATE_BPS = 50_000.0
NON_MCV = ("collision", "markov", "compression", "t_tuple", "lrs")
SLUG = "digital-section-behavioral"


# ------------------------------------------------------------- generators

def gen_markov(rng, n, a, b):
    """P(1|1)=a, P(0|0)=b, started from the stationary distribution."""
    p1 = (1 - b) / ((1 - a) + (1 - b))
    x = 1 if rng.random() < p1 else 0
    out = [x]
    for _ in range(n - 1):
        stay = a if x else b
        if rng.random() >= stay:
            x ^= 1
        out.append(x)
    return out


def h_markov(a, b):
    return -math.log2(max(a, b, math.sqrt((1 - a) * (1 - b))))


def balanced_pattern(rng, k):
    pat = [1] * (k // 2) + [0] * (k - k // 2)
    rng.shuffle(pat)
    return pat


def gen_periodic(rng, n, k, eps, pattern=None):
    pat = pattern or balanced_pattern(rng, k)
    return [pat[i % k] ^ (1 if rng.random() < eps else 0) for i in range(n)]


def h_periodic(eps):
    return -math.log2(1 - eps) + 0.0


def gen_lockmix(rng, n, seg, frac, eps):
    locked_len = int(round(frac * seg))
    out = []
    while len(out) < n:
        out += [(i & 1) ^ (1 if rng.random() < eps else 0) for i in range(locked_len)]
        out += [rng.getrandbits(1) for _ in range(seg - locked_len)]
    return out[:n]


def h_lockmix(frac, eps):
    return (1 - frac) + frac * h_periodic(eps)


# ------------------------------------------------------------- measurement

def run_health(bits):
    hm = HealthMonitor()
    first = None
    kinds = 0
    n_alarm = 0
    for i, b in enumerate(bits):
        if hm.update(b):
            n_alarm += 1
            if first is None:
                first = i + 1
                kinds = (1 if hm.alarm_rct else 0) | (2 if hm.alarm_apt else 0)
    which = {0: "-", 1: "RCT", 2: "APT", 3: "RCT+APT"}[kinds]
    return first, which, n_alarm


def measure(label, family, params, h_true, bits):
    first, which, n_alarm = run_health(bits)
    est = battery.entropy_estimates(bits)
    ests = {k: v["h_bits"] for k, v in est["estimators"].items() if v["status"] == "OK"}
    nonmcv = {k: ests[k] for k in NON_MCV if k in ests}
    bind = min(nonmcv, key=nonmcv.get)
    catchers = sorted((k for k, v in nonmcv.items() if v < H_DESIGN), key=nonmcv.get)
    return {
        "label": label, "family": family, "params": params,
        "n": len(bits), "h_true": h_true,
        "mean_bit": sum(bits) / len(bits),
        "alarm": first is not None, "first_alarm_at": first,
        "latency_ms": None if first is None else first / RAW_RATE_BPS * 1e3,
        "alarm_kind": which, "alarm_events": n_alarm,
        "estimates": ests, "nonmcv_min": nonmcv[bind], "nonmcv_binding": bind,
        "estimator_catchers": catchers,
        "below_target": h_true < H_DESIGN,
    }


def sweep(seed, n):
    rng = random.Random(seed)
    rows = []

    def add(label, fam, params, h, bits):
        rows.append(measure(label, fam, params, h, bits))

    # control: fair coin
    add("control fair", "control", {}, 1.0, [rng.getrandbits(1) for _ in range(n)])

    # Markov: symmetric stay sweep, plus biased/asymmetric chains
    for s in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99):
        add(f"markov sym stay={s}", "markov", {"a": s, "b": s}, h_markov(s, s),
            gen_markov(rng, n, s, s))
    for a, b in ((0.7, 0.5), (0.8, 0.5), (0.9, 0.6), (0.9, 0.3), (0.95, 0.5), (0.98, 0.6)):
        add(f"markov asym a={a} b={b}", "markov", {"a": a, "b": b}, h_markov(a, b),
            gen_markov(rng, n, a, b))

    # period-k with flip noise
    for k in (2, 4, 8, 16, 64, 256):
        for eps in (0.0, 0.01, 0.05, 0.1, 0.2, 0.3):
            pat = balanced_pattern(rng, k)
            add(f"periodic k={k} eps={eps}", "periodic", {"k": k, "eps": eps},
                h_periodic(eps), gen_periodic(rng, n, k, 0.0 + eps, pat))

    # lock-fraction mixture
    for seg in (256, 4096):
        for eps in (0.0, 0.05):
            for f in (0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
                add(f"lockmix L={seg} f={f} eps={eps}", "lock-mix",
                    {"segment": seg, "frac": f, "eps_lock": eps}, h_lockmix(f, eps),
                    gen_lockmix(rng, n, seg, f, eps))
    return rows


# ------------------------------------------------------------- reporting

def fmt_h(x):
    return f"{x:.3f}"


def build_report(rows, seed, n):
    L = []
    a = L.append
    missed = [r for r in rows if r["below_target"] and not r["alarm"]]
    missed_caught = [r for r in missed if r["estimator_catchers"]]
    missed_uncaught = [r for r in missed if not r["estimator_catchers"]]
    low = [r for r in rows if r["below_target"]]
    a("## Configuration")
    a("")
    a(f"- DUT: `digital/model/health.py` `HealthMonitor` at `C_RCT` = {C_RCT}, `C_APT` = {C_APT}, "
      f"`W` = {W_APT}, start-up = {STARTUP_SAMPLES} (DR-0004; **not modified**)")
    a(f"- stimulus: **declared synthetic logic stimuli** -- seeded generators, `random.Random({seed})`, "
      f"{n:,} samples per stream. PVT-independent (no SPICE, no PDK). **No entropy claim on silicon.**")
    a(f"- `h_true` is the analytic per-bit min-entropy of the generator (adversary knows the pattern/schedule); "
      f"'below target' means `h_true` < `H_DESIGN` = {H_DESIGN}")
    a("- estimators: non-MCV SP 800-90B estimators from `raw-bit-battery.py` (#189): collision, Markov, "
      "compression, t-tuple, LRS; 'catches' = point estimate < `H_DESIGN`. Repo approximations, not validated 90B")
    a(f"- latency: samples to first alarm, ms at {RAW_RATE_BPS:,.0f} Hz")
    a("")
    a("## Summary")
    a("")
    a(f"- streams: {len(rows)}; below `H_DESIGN`: {len(low)}; alarmed by RCT/APT: "
      f"{sum(1 for r in low if r['alarm'])}")
    a(f"- **missed by online tests but below target: {len(missed)}**; of those, caught by at least one "
      f"non-MCV estimator: {len(missed_caught)}; caught by none: {len(missed_uncaught)}")
    fp = [r for r in rows if not r["below_target"] and r["alarm"]]
    a(f"- alarms on streams at/above target (informational): {len(fp)}")
    ff = [r for r in rows if not r["below_target"] and r["estimator_catchers"]]
    a(f"- streams at/above target that a non-MCV estimator nonetheless flags (conservative-estimator "
      f"false flags under this `h_true` definition): {len(ff)}"
      + (" -- " + ", ".join(f"`{r['label']}`" for r in ff) if ff else ""))
    a("")
    a("## All streams")
    a("")
    a("| stream | h_true | mean | alarm | first alarm @ | by | non-MCV min (binding) | estimator catchers |")
    a("|---|---|---|---|---|---|---|---|")
    for r in rows:
        a(f"| {r['label']} | {fmt_h(r['h_true'])} | {r['mean_bit']:.3f} | "
          f"{'YES' if r['alarm'] else 'no'} | {r['first_alarm_at'] if r['alarm'] else '-'} | "
          f"{r['alarm_kind']} | {fmt_h(r['nonmcv_min'])} ({r['nonmcv_binding']}) | "
          f"{', '.join(r['estimator_catchers']) or '-'} |")
    a("")
    a("## Missed-but-low-entropy cases (no RCT/APT alarm, `h_true` < `H_DESIGN`)")
    a("")
    if not missed:
        a("None.")
    else:
        a("| stream | h_true | non-MCV min (binding) | catching estimator(s), lowest first |")
        a("|---|---|---|---|")
        for r in missed:
            a(f"| {r['label']} | {fmt_h(r['h_true'])} | {fmt_h(r['nonmcv_min'])} ({r['nonmcv_binding']}) | "
              f"{', '.join(r['estimator_catchers']) or '**none**'} |")
    a("")
    if missed_uncaught:
        a("Missed by the online tests AND by every non-MCV estimator: "
          + ", ".join(f"`{r['label']}`" for r in missed_uncaught) + ".")
    else:
        a("Every missed-but-low-entropy stream is caught by at least one non-MCV estimator.")
    a("")
    a("## Notes")
    a("")
    a("- RCT/APT are *bias and run-length* detectors. A balanced period-k pattern has marginal bias 0.5 and run")
    a("  lengths bounded by k, so it is invisible to both regardless of how little entropy it carries; this is the")
    a("  expected, documented limit of SP 800-90B §4.4, quantified here, not a defect in the model.")
    a("- The estimators are offline (N >= 1000-12000 samples, run over a whole stream); they are not an online")
    a("  mitigation. Where they catch a case the online tests miss, the gap is in *what runs on-chip*.")
    a("- Estimator point estimates can over- or under-state `h_true`; 'catches' uses the design target as the")
    a("  threshold and is a detection statement, not an accuracy claim.")
    a("- Lock-mix streams are non-stationary, which the 90B estimators assume away: their flags on")
    a("  streams whose analytic `h_true` is at/above target reflect the repeated locked segments (a")
    a("  conservative reading), not an error in the analytic figure under the stated known-schedule model.")
    a("- Ratified cutoffs and spec text are unchanged. Any coverage hole is routed to a decision-record request.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)

    rows = sweep(args.seed, args.n)
    body = build_report(rows, args.seed, args.n)
    print(body)

    # Sanity checks on the harness itself (not on coverage): control must not
    # alarm, a locked period-2 eps=0 stream must be zero-entropy.
    ctrl = rows[0]
    ok = (not ctrl["alarm"]
          and all(r["h_true"] >= 0 for r in rows)
          and any(r["family"] == "periodic" and r["h_true"] == 0 for r in rows))
    if not ok:
        print("\nHARNESS SANITY FAILED", file=sys.stderr)

    if args.emit_record:
        artifact = Path(tempfile.gettempdir()) / "health-detection-coverage-rows.txt"
        artifact.write_text("\n".join(
            f"{r['label']}\th_true={r['h_true']:.4f}\talarm={r['alarm']}\t"
            f"first={r['first_alarm_at']}\tcatchers={','.join(r['estimator_catchers'])}"
            for r in rows) + "\n")
        mint_behavioral_record(
            repo_root=REPO_ROOT, slug=SLUG,
            claim=("experiment I: detection coverage of the DR-0004 RCT/APT health tests, and of the "
                   "non-MCV 90B estimators, against serially-correlated, periodic and lock-mixture "
                   "SYNTHETIC logic stimuli of known analytic min-entropy (no silicon entropy claim)"),
            body_md=body,
            summary={"ok": ok, "seed": args.seed, "n": args.n, "experiment": "I",
                     "h_design": H_DESIGN, "rows": rows},
            level="behavioral",
            seeds={"python_random": args.seed},
            artifacts=[artifact],
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
