#!/usr/bin/env python3
"""Reduce the digitized `raw_bit` sequence to a Most-Common-Value min-entropy
point estimate (SP 800-90B section 6.3.1 style), per corner.

**This runs no simulator.** It is pure arithmetic over an already-committed
`sim/raw-bit-min-entropy/records/*.json` record minted by
`sim/bin/corner-run.py` from `sim/raw-bit-min-entropy/testbench/
tb_raw_bit_stream.spice` -- the noise-injected, assembled `ro_array_core` +
`sampler_dff` transient run issue #21 adds. Re-running this script on an
unchanged record set reproduces the reduction byte-for-byte, the same
"arithmetic over cited evidence" discipline
`sim/ro-array-sizing/analysis/array-sizing.py` established for this repo.

What it computes, and what it does NOT claim
---------------------------------------------
For each PVT corner in the cited campaign record, this script:

1. Recovers the raw 0/1 sequence from that corner's `bit0..bitN-1`
   measurements (thresholded at 0.5 x Vdd) and `valid0..validN-1` (samples
   where `raw_valid` was not asserted are excluded, though the testbench's
   own reset/enable release timing means none are expected to be).
2. Computes the **Most Common Value (MCV) estimate**, the simplest
   estimator SP 800-90B section 6.3.1 defines for a non-IID source: the
   sample proportion of the more frequent symbol, `p_hat`, upper-bounded at
   99% confidence via the normal approximation
   `p_u = min(1, p_hat + z_0.99 * sqrt(p_hat*(1-p_hat)/(n-1)))`,
   `z_0.99 = 2.5758293035489004`, and the point estimate
   `H_hat = -log2(p_u)`.
3. Reports the **naive per-sample standard error**
   `sqrt(p_hat*(1-p_hat)/n)` alongside -- explicitly labeled as an
   UNDER-estimate of the true uncertainty, because every corner's `n`
   samples share ONE noise trajectory (one seed), not `n` independent
   draws (see the testbench's own header and `sim/README.md`'s standing
   "one seed per PVT point" caveat for this repo's other transient-noise
   campaigns).

This is explicitly a **Tier 2 design estimate** in the three-tier claim
discipline `spec/porting-plan.md` cites from gf180-trng's own DR-0004
("SP 800-90B path pre-silicon"): a labelled, bounded, simulation-derived
estimate, NOT an SP 800-90B validation assessment (Tier 3, which needs a
full non-IID estimator suite run against measured silicon, per this
repository's own `CLAUDE.md` standing caveat that "simulation-derived
entropy claims are provisional until measured on silicon"). It is also NOT
a measurement at DR-0003's actual Ts = 20 us operating point -- the cited
testbench runs at Ts = 100 ns, a disclosed compute-budget deviation (see
its own header) -- so this script's `H_hat` characterizes a shorter-window,
higher-rate hypothetical sampler on the same physical array, not the
literal DR-0003 design point.

Usage
-----
    python3 sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py
    python3 sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py --emit-record

`--emit-record` mints an append-only reduction record under
`sim/raw-bit-min-entropy/records/` (the SAME slug's records directory the
cited campaign record lives in -- this is a derived record, not a new
simulation, following `sim/digital-health-test-parameters/`'s precedent of
keeping a slug's simulated-or-measured record and its own reduction
together rather than `sim/ro-array-sizing/`'s separate-slug convention),
in the same `<YYYYMMDD>-<HHMMSS>-<shortsha>` id scheme, refusing to
overwrite one.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDS_DIR = REPO_ROOT / "sim" / "raw-bit-min-entropy" / "records"

sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_record, new_record_id  # noqa: E402

#: SP 800-90B section 6.3.1's 99%-confidence one-sided normal-approximation
#: multiplier (the z-score whose upper tail is 1%).
Z_99 = 2.5758293035489004

BIT_RE = re.compile(r"^bit(\d+)$")


def campaign_records(records_dir: Path = RECORDS_DIR) -> list[dict]:
    """Raw `corner-run.py` campaign records under `records_dir`.

    Distinguished from this script's own derived records by the presence of
    a `testbench` key (every `corner-run.py` record has one; a derived
    record minted by `evidence_record.mint_record` instead carries an
    `analysis` key and no `testbench` key).
    """
    out = []
    if not records_dir.is_dir():
        return out
    for path in sorted(records_dir.glob("*.json")):
        rec = json.loads(path.read_text())
        if "testbench" in rec:
            out.append(rec)
    return out


def extract_sequence(measurements: dict, vdd_v: float) -> tuple[list[int], int, int]:
    """Recover the `raw_bit` 0/1 sequence from one corner's measurements.

    Returns `(bits, n_total, n_excluded)` where `n_excluded` counts samples
    whose paired `validK` measurement did not read as asserted (high) --
    excluded from the returned sequence rather than coerced to a value.
    """
    indices = sorted(
        int(m.group(1)) for name in measurements if (m := BIT_RE.match(name))
    )
    bits: list[int] = []
    excluded = 0
    threshold = 0.5 * vdd_v
    for i in indices:
        valid_key = f"valid{i}"
        if valid_key in measurements and measurements[valid_key] <= threshold:
            excluded += 1
            continue
        bits.append(1 if measurements[f"bit{i}"] > threshold else 0)
    return bits, len(indices), excluded


def mcv_estimate(bits: list[int]) -> dict:
    """SP 800-90B section 6.3.1 Most-Common-Value estimate over `bits`."""
    n = len(bits)
    if n == 0:
        raise ValueError("mcv_estimate: empty bit sequence")
    ones = sum(bits)
    zeros = n - ones
    mode_count = max(ones, zeros)
    p_hat = mode_count / n
    # Naive per-sample SE -- an UNDER-estimate here; see module docstring.
    se_naive = math.sqrt(p_hat * (1.0 - p_hat) / n) if n > 0 else float("nan")
    if n > 1:
        p_u = min(1.0, p_hat + Z_99 * math.sqrt(p_hat * (1.0 - p_hat) / (n - 1)))
    else:
        p_u = 1.0
    h_hat = 0.0 if p_u >= 1.0 else -math.log2(p_u)
    return {
        "n": n,
        "ones": ones,
        "zeros": zeros,
        "p_hat": p_hat,
        "p_u_99": p_u,
        "h_hat_bits": h_hat,
        "se_naive": se_naive,
    }


def build_report(rec: dict) -> tuple[str, dict]:
    lines: list[str] = []
    lines.append(f"Source campaign record: `{rec['record_id']}` "
                 f"(`{rec['testbench']}`)")
    lines.append("")
    lines.append(f"Sample clock `Ts` used by this run (see testbench header for "
                 f"why it deviates from DR-0003's Ts = 20 us): 100 ns.")
    lines.append("")
    lines.append("| Corner | verdict | n (used/total, excl.) | ones | p_hat | "
                  "naive SE(p_hat) | p_u (99%) | H_hat (bit/sample) |")
    lines.append("|---|---|---|---|---|---|---|---|")

    per_corner = []
    for corner in rec["corners"]:
        m = corner.get("measurements", {})
        bits, n_total, n_excl = extract_sequence(m, rec["pvt"]["vdd_v"])
        if not bits:
            lines.append(f"| `{corner['corner']}` | SKIP | 0/{n_total} ({n_excl}) | "
                          "- | - | - | - | - |")
            continue
        est = mcv_estimate(bits)
        swing = m.get("ro1_swing_frac")
        degenerate = est["p_hat"] >= 0.999 or (swing is not None and swing < 0.1)
        verdict = "DEGENERATE" if degenerate else "OK"
        lines.append(
            f"| `{corner['corner']}` | {verdict} | {est['n']}/{n_total} ({n_excl}) | "
            f"{est['ones']} | {est['p_hat']:.4f} | {est['se_naive']:.4f} | "
            f"{est['p_u_99']:.4f} | {est['h_hat_bits']:.4f} |"
        )
        per_corner.append({
            "corner": corner["corner"],
            "temp_c": rec["pvt"]["temp_c"],
            "vdd_v": rec["pvt"]["vdd_v"],
            "bits": "".join(str(b) for b in bits),
            "ro1_swing_frac": swing,
            "verdict": verdict,
            **est,
        })

    lines.append("")
    lines.append(
        "`DEGENERATE` means either the recovered sequence is (near-)constant "
        "(`p_hat >= 0.999`) or `ro1_swing_frac` (the testbench's own ring-"
        "oscillation health check) reads below 0.1 -- i.e. ring 1 did not "
        "actually oscillate at that corner, which would make any `H_hat` "
        "computed from it meaningless rather than merely low."
    )
    lines.append("")
    if per_corner:
        binding = min(per_corner, key=lambda p: p["h_hat_bits"])
        lines.append(
            f"Lowest `H_hat` over the corners run: **{binding['h_hat_bits']:.4f} "
            f"bit/sample** at `{binding['corner']}` / {binding['temp_c']:g} degC / "
            f"{binding['vdd_v']:g} V."
        )
    lines.append("")
    lines.append("## Caveats that bound how this estimate may be cited")
    lines.append("")
    lines.append(
        "- **Design estimate, not an SP 800-90B validation.** This is a "
        "Tier 2 (per gf180-trng's own DR-0004 three-tier claim discipline, "
        "cited by `spec/porting-plan.md`) labelled, bounded, "
        "simulation-derived point estimate from a single MCV-style "
        "estimator -- not the full non-IID estimator suite section 800-90B "
        "requires for an assessment, and not a Tier 3 measurement of "
        "silicon."
    )
    lines.append(
        "- **Simulation-derived entropy claims are provisional until "
        "measured on silicon** -- the root `CLAUDE.md` standing caveat, "
        "restated here explicitly because this is the first record in this "
        "repository the caveat actually binds against a real bitstream."
    )
    lines.append(
        "- **Sample-count-limited.** `n` is small (tens of samples per "
        "corner, see the table above) -- the reported `se_naive` and the "
        "99%-confidence `p_u` both widen sharply at this `n`; do not read "
        "`H_hat` as precise to more than roughly one significant figure."
    )
    lines.append(
        "- **One seed per corner, not independent trials.** Every bit in a "
        "given corner's sequence is drawn from a single continuous "
        "`trnoise()` realization (see the testbench header) -- `se_naive` "
        "assumes independent samples and is therefore an UNDER-estimate of "
        "the true uncertainty. Seed-to-seed spread is not characterized by "
        "this campaign, matching this repository's standing gap for every "
        "other transient-noise deck (`sim/README.md`)."
    )
    lines.append(
        "- **Fixed, unre-measured noise injection level**, anchored once to "
        "`sim/ro-stage-noise-mechanism-check/`'s measured near-band noise "
        "density -- the same ~1.5-2x caveat as every other trnoise() "
        "campaign in this repository."
    )
    lines.append(
        "- **Not DR-0003's operating point.** The cited testbench runs at "
        "Ts = 100 ns, not DR-0003's Ts = 20 us (a disclosed compute-budget "
        "deviation -- see the testbench's own header for the wall-clock "
        "calibration behind that choice). `H_hat` here characterizes a "
        "shorter-window, higher-rate hypothetical sampler on the literal "
        "committed array, not the actual DR-0003 design point; the sizing "
        "law's `Q` is linear in `Ts`, so this estimate should not be "
        "rescaled to DR-0003's Ts without re-running at that Ts."
    )

    summary = {"per_corner": per_corner, "z_99": Z_99}
    return "\n".join(lines), summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit-record", action="store_true",
                     help="mint an append-only reduction record under "
                          "sim/raw-bit-min-entropy/records/")
    ap.add_argument("--author", default="loom-builder@sky130-trng")
    args = ap.parse_args(argv)

    records = campaign_records()
    if not records:
        print(f"error: no corner-run.py campaign records found under "
              f"{RECORDS_DIR.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    rec = records[-1]  # most recent by record-id sort order

    body, summary = build_report(rec)
    print(body)

    if not args.emit_record:
        return 0

    now, sha, rid = new_record_id(REPO_ROOT)
    header = [
        f"# {rid} -- raw-bit-min-entropy (reduction)",
        "",
        "**Claim**: Most-Common-Value (SP 800-90B section 6.3.1 style) "
        "min-entropy point estimate, per PVT corner, reduced from the "
        f"noise-injected raw `raw_bit` sequence in campaign record "
        f"`{rec['record_id']}`.",
        "",
        "**Level**: transistor (derived -- this record introduces no new "
        "simulation; it is arithmetic over the cited transistor-level "
        "record)",
        "**Seed**: N/A (deterministic reduction; the underlying run states "
        "its own per-corner seed)",
        f"**Analysis**: `sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py` "
        "(re-run to reproduce)",
        "",
        "## Source record",
        "",
        f"- `{rec['record_id']}` (`{rec['testbench']}`)",
        "",
        "---",
        "",
    ]
    summary_out = {
        "record_id": rid,
        "slug": "raw-bit-min-entropy",
        "level": "transistor (derived)",
        "analysis": "sim/raw-bit-min-entropy/analysis/raw-bit-entropy.py",
        "source_record": rec["record_id"],
        "author": args.author,
        "timestamp_utc": now.isoformat(),
        "repo_sha": sha,
        **summary,
    }
    result = mint_record(RECORDS_DIR, REPO_ROOT, rid, header, body, summary_out,
                          author=args.author, now=now, sha=sha)
    return 0 if result is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
