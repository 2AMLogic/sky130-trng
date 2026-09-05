#!/usr/bin/env python3
"""Derive the RCT/APT cutoffs for sky130-trng, and check the degeneracy floor.

**This runs no simulator.** It is exact arithmetic over SP 800-90B
§4.4.1/§4.4.2, evaluated at this repository's own numbers -- the min-entropy
design target from the README, and the 50 kbps raw rate DR-0003 measured for
sky130's array. That is the whole reason it exists as its own record: the
cutoff *formulas* are portable methodology (``spec/porting-plan.md`` §1.1),
the cutoff *values* are a formula evaluation that has to be redone for this
process (§2.3), and this file is where that evaluation happens rather than
inside a document nobody can re-run.

Three things it establishes, each independently checkable:

1. **The cutoff table over an ``H`` grid** -- so the number to use once
   issue #21 measures ``H`` is a lookup, not a re-derivation.
2. **The APT degeneracy floor**, closed-form and by direct evaluation:
   ``Pr(X >= W) = 2**(-H*W)``, so a cutoff exists only for
   ``H > alpha_log2/W`` = 0.0390625 at this block's parameters.
3. **The false-alarm interval at sky130's own raw rate** -- the argument
   that actually justifies keeping ``alpha = 2**-40``, re-derived at
   50 kbps rather than inherited from gf180-trng's 1 Mbps-era reasoning.

Usage::

    python3 sim/digital-health-test-parameters/analysis/health-test-cutoffs.py
    python3 sim/digital-health-test-parameters/analysis/health-test-cutoffs.py --emit-record
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402
from model import params  # noqa: E402

#: DR-0003 §2: the measured operating point of the analog block this digital
#: section sits behind. The health tests run at the raw tap, so this is the
#: rate every false-alarm interval below is expressed against.
RAW_RATE_BPS = 50_000.0

#: DR-0003 §3: the min-entropy the sizing law *models* at that operating
#: point. Reported for contrast; NOT what the cutoffs are evaluated at
#: (DR-0004 §2.3 explains the choice).
H_MODEL_DR0003 = 0.5415

#: gf180-trng's own ratified raw-rate row, for the alpha re-derivation.
GF180_RATE_BPS = 1_000_000.0


def seconds_human(seconds: float) -> str:
    if seconds < 86_400:
        return f"{seconds / 3600:.1f} hours"
    if seconds < 86_400 * 365.25:
        return f"{seconds / 86_400:.1f} days"
    return f"{seconds / (86_400 * 365.25):.1f} years"


def build_report() -> tuple[str, dict]:
    alpha_log2 = params.ALPHA_LOG2
    w = params.W_APT
    floor = params.apt_degeneracy_floor(w, alpha_log2)

    rows = params.cutoff_table(params.H_GRID)

    # Adopted values, recomputed here rather than trusted from params.py.
    c_rct_adopted = params.c_rct(params.H_DESIGN, alpha_log2)
    c_apt_adopted = params.c_apt(params.H_DESIGN, w, alpha_log2)
    c_rct_model = params.c_rct(H_MODEL_DR0003, alpha_log2)
    c_apt_model = params.c_apt(H_MODEL_DR0003, w, alpha_log2)

    # False-alarm intervals. RCT decides once per sample; APT once per window.
    alpha = 2.0 ** -alpha_log2
    rct_mtbf_sky = 1.0 / alpha / RAW_RATE_BPS
    apt_mtbf_sky = 1.0 / alpha * w / RAW_RATE_BPS
    rct_mtbf_gf = 1.0 / alpha / GF180_RATE_BPS

    # Detection latency of the adopted cutoffs, in real time at 50 kbps.
    rct_latency_s = c_rct_adopted / RAW_RATE_BPS
    apt_latency_s = w / RAW_RATE_BPS
    startup_s = params.STARTUP_SAMPLES / RAW_RATE_BPS
    first_cond_s = (params.STARTUP_SAMPLES + params.COND_BLOCK_BITS) / RAW_RATE_BPS
    first_raw_s = params.WORD_BITS / RAW_RATE_BPS

    # Degeneracy floor, checked two ways.
    tail_at_floor = float(Decimal(2) ** Decimal(str(-floor * w)))
    just_above = params.c_apt(floor + 0.001, w, alpha_log2)
    just_below = params.c_apt(floor - 0.001, w, alpha_log2)

    lines: list[str] = []
    a = lines.append
    a("## Parameters this evaluation is conditional on")
    a("")
    a("| Input | Value | Where it comes from |")
    a("|---|---|---|")
    a(f"| `alpha` | 2^-{alpha_log2} | false-alarm rate, re-derived below at this repo's own raw rate |")
    a(f"| `W` (APT window) | {w} | SP 800-90B §4.4.2, binary source |")
    a(f"| `H` (design target) | {params.H_DESIGN} bit/sample | README target-specification row -- a **design target**, not a measurement |")
    a(f"| raw rate | {RAW_RATE_BPS:,.0f} bps | DR-0003 §2, measured sky130 operating point |")
    a("")
    a("**No sky130 raw bitstream has been simulated yet** (issue #21), so no")
    a("measured `H` exists for this process. Every cutoff below is therefore")
    a("*provisional*: correct arithmetic on an assumed input.")
    a("")

    a("## 1. Cutoff table over an H grid")
    a("")
    a("`C_RCT = 1 + ceil(-log2(alpha)/H)`; `C_APT` = smallest `C` with")
    a("`Pr(X >= C) <= alpha` for `X ~ Binomial(W, 2^-H)`, evaluated with 80-digit")
    a("decimal arithmetic (a float sum of 1024 terms cannot resolve a 2^-40 tail).")
    a("")
    a("| `H` | `C_RCT` | `C_APT` | note |")
    a("|---|---|---|---|")
    for row in rows:
        note = ""
        if row["c_apt"] is None:
            note = "**degenerate** -- no valid cutoff exists"
        elif row["c_apt"] >= w - 2:
            note = "degenerate in practice (cutoff within 2 of the window)"
        elif abs(row["h"] - params.H_DESIGN) < 1e-9:
            note = "**adopted** (README design target)"
        elif abs(row["h"] - H_MODEL_DR0003) < 1e-9:
            note = "DR-0003 §3's model-derived H at the chosen operating point"
        a(f"| {row['h']:.7g} | {row['c_rct']} | "
          f"{'none' if row['c_apt'] is None else row['c_apt']} | {note} |")
    a("")
    a(f"**Adopted**: `C_RCT` = {c_rct_adopted}, `C_APT` = {c_apt_adopted} at `H` = {params.H_DESIGN}.")
    a("")
    a("These are the same two numbers gf180-trng's DR-0002 records, and that")
    a("is a **result, not a port**: the formulas are identical, `alpha` and `W`")
    a("are identical, and both repositories currently target `H = 0.5`. The")
    a("table above is the load-bearing artifact -- the moment sky130's measured")
    a("`H` differs, the cutoffs move with it, and the agreement disappears.")
    a("Recomputing them here from first principles also independently")
    a("reproduces gf180-trng's own published values, which is the cheapest")
    a("available check that this implementation of the formulas is right.")
    a("")

    a("## 2. APT degeneracy floor")
    a("")
    a("`Pr(X >= W) = p^W = 2^(-H*W)`, so a cutoff `C <= W` exists only while")
    a("`2^(-H*W) <= alpha`, i.e.")
    a("")
    a(f"    H > alpha_log2 / W = {alpha_log2} / {w} = {floor:.7f}")
    a("")
    a(f"- direct evaluation at the floor: `Pr(X >= W)` = {tail_at_floor:.6e} vs `alpha` = {alpha:.6e} (equal to the last bit -- the floor is an open bound)")
    a(f"- `H` = {floor - 0.001:.7f} (just below): `C_APT` = {'none' if just_below is None else just_below}")
    a(f"- `H` = {floor + 0.001:.7f} (just above): `C_APT` = {'none' if just_above is None else just_above} of {w} -- valid, and useless")
    a("")
    a("gf180-trng's DR-0002 states this floor as \"H ~ 0.03, marginal below")
    a("H ~ 0.05\". The exact value at these parameters is **0.0390625**, and")
    a(f"the practical floor is higher still: at `H` = 0.05 the cutoff is")
    a(f"{params.c_apt(0.05, w, alpha_log2)} of {w}, i.e. the test only fires when")
    a("essentially every sample in a window matches. Sky130's array is sized")
    a(f"to `H` = {params.H_DESIGN} (DR-0002/DR-0003), an order of magnitude clear of")
    a("the floor, so this is a stated risk boundary rather than an active")
    a("constraint -- but it is exactly the boundary issue #21's measurement")
    a("could move the design into, and it is checked here rather than assumed.")
    a("")

    a("## 3. Why `alpha = 2^-40` survives re-derivation at 50 kbps")
    a("")
    a("`alpha` is a false-alarm rate, and a false-alarm *rate* only becomes a")
    a("false-alarm *interval* once a sample rate is fixed. sky130-trng's rate")
    a("is 20x lower than the row gf180-trng's choice was argued against, so the")
    a("inherited number has to be re-justified rather than assumed:")
    a("")
    a("| Quantity | sky130-trng (50 kbps) | gf180-trng (1 Mbps row) |")
    a("|---|---|---|")
    a(f"| RCT false-alarm interval (one decision per sample) | {seconds_human(rct_mtbf_sky)} | {seconds_human(rct_mtbf_gf)} |")
    a(f"| APT false-alarm interval (one decision per {w}-sample window) | {seconds_human(apt_mtbf_sky)} | -- |")
    a("")
    a("At this rate `alpha = 2^-40` is **more** conservative than gf180-trng's")
    a("own justification needed it to be. It is kept anyway (DR-0004 §2.2):")
    a("relaxing it would tighten the cutoffs slightly while buying no")
    a("meaningful detection latency --")
    a(f"`C_RCT` at `alpha = 2^-30` is {params.c_rct(params.H_DESIGN, 30)} versus {c_rct_adopted} at 2^-40, i.e.")
    a(f"{(c_rct_adopted - params.c_rct(params.H_DESIGN, 30)) / RAW_RATE_BPS * 1e3:.2f} ms of detection latency at 50 kbps -- and it keeps this")
    a("block's parameters directly comparable with the sibling repository's.")
    a("")

    a("## 4. Latency consequences at the measured operating point")
    a("")
    a("| Quantity | Samples | Time at 50 kbps |")
    a("|---|---|---|")
    a(f"| RCT worst-case detection (a fully stuck source) | {c_rct_adopted} | {rct_latency_s * 1e3:.2f} ms |")
    a(f"| APT decision interval | {w} | {apt_latency_s * 1e3:.2f} ms |")
    a(f"| Start-up health test | {params.STARTUP_SAMPLES} | {startup_s * 1e3:.2f} ms |")
    a(f"| Time to first **raw** word (never gated) | {params.WORD_BITS} | {first_raw_s * 1e3:.2f} ms |")
    a(f"| Time to first **conditioned** word (start-up + one block) | {params.STARTUP_SAMPLES + params.COND_BLOCK_BITS} | {first_cond_s * 1e3:.2f} ms |")
    a("")
    a("The last row is the `time-to-first-valid` figure")
    a("`docs/chipalooza/challenge-4-proposal.md` row F had to leave as")
    a("\"N/A -- architecture not yet designed\".")

    summary = {
        "alpha_log2": alpha_log2,
        "w_apt": w,
        "h_design": params.H_DESIGN,
        "h_model_dr0003": H_MODEL_DR0003,
        "raw_rate_bps": RAW_RATE_BPS,
        "c_rct_adopted": c_rct_adopted,
        "c_apt_adopted": c_apt_adopted,
        "c_rct_at_h_model": c_rct_model,
        "c_apt_at_h_model": c_apt_model,
        "apt_degeneracy_floor_h": floor,
        "c_apt_just_above_floor": just_above,
        "c_apt_just_below_floor": just_below,
        "rct_false_alarm_interval_s": rct_mtbf_sky,
        "apt_false_alarm_interval_s": apt_mtbf_sky,
        "rct_detection_latency_s": rct_latency_s,
        "startup_time_s": startup_s,
        "time_to_first_raw_word_s": first_raw_s,
        "time_to_first_conditioned_word_s": first_cond_s,
        "cutoff_table": [
            {"h": r["h"], "c_rct": r["c_rct"], "c_apt": r["c_apt"]} for r in rows
        ],
    }
    return "\n".join(lines), summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true",
                    help="mint an append-only record under "
                         "sim/digital-health-test-parameters/records/")
    args = ap.parse_args(argv)

    body, summary = build_report()
    print(body)

    if args.emit_record:
        mint_behavioral_record(
            repo_root=REPO_ROOT,
            slug="digital-health-test-parameters",
            claim=("the SP 800-90B RCT/APT cutoffs for sky130-trng, evaluated "
                   "from the formulas at this repository's own H target and "
                   "50 kbps raw rate; the APT degeneracy floor; and the "
                   "false-alarm/latency consequences at that rate"),
            body_md=body,
            summary=summary,
            level="behavioral (derived -- exact arithmetic, no simulator)",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
