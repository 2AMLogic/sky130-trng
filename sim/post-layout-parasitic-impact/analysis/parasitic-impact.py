#!/usr/bin/env python3
"""Reduce sim/post-layout-ro-ring5/'s three decks to the two answers issue #22 asks for.

    python3 sim/post-layout-parasitic-impact/analysis/parasitic-impact.py
    python3 sim/post-layout-parasitic-impact/analysis/parasitic-impact.py --emit-record

**Pure arithmetic over already-committed evidence.** It runs no simulator and
reads only `sim/post-layout-ro-ring5/records/*.json` (twelve records, thirty-six
corner runs, three decks x four (temp, Vdd) points x {tt, ss, ff}) plus one
figure from `sim/ro-ring-timestep-convergence/` for the estimator's own
numerical floor.

The two questions
-----------------

1. **What do the extracted parasitics cost?** (issue #22 acceptance criterion 2)
   `tb_post_layout_ro_ring5.spice` runs the post-layout ring and the pre-layout
   ring in one deck at one corner, so the ratio of their periods isolates the
   parasitic contribution. This script reduces that to a slowdown range over the
   whole PVT grid, per `wstv` width, plus what the same parasitics do to ring
   swing and per-ring supply current.

2. **Does the `wstv` ladder still decorrelate the rings?** (acceptance criterion
   4, DR-0003 section 8) Two parts, and they are separate claims:

   a. *Does the frequency ladder survive?* DR-0003 section 8's stated criterion
      is that the realized ring-period ratios stay clear of the small rationals
      (2/1, 3/2, 4/3) that mutually injection-lock. This script re-derives every
      pairwise ratio among the four post-layout rings and reports the closest
      approach to any of those rationals.

   b. *How large is the coupling itself?* This is the part DR-0003 section 8
      says cannot be answered at the netlist level, because a schematic netlist
      contains no shared node between rings. Extracted parasitics do contain one
      -- the substrate return node every net-to-substrate capacitance lands on --
      so the question becomes answerable, but only as a bound, because the
      extractor models no substrate or tap resistance (klayout-tools#1503). The
      three decks bracket it:

          tied  : `vsubs` hard to 0, four rings running   -> zero coupling by
                  construction (an ideal substrate cannot carry a signal), and
                  therefore also the zero-coupling baseline for ring 1
          solo  : `vsubs` floating, rings 2/3/4 present but STOPPED -> the
                  floating node's LOADING effect alone
          float : `vsubs` floating, four rings running    -> loading + coupling

      loading  = t(solo)  - t(tied)
      coupling = t(float) - t(solo)

      Reporting `t(float) - t(tied)` without the solo control -- which an
      earlier pass over this evidence did -- attributes the whole difference to
      coupling and overstates it.

Both answers are stated against the estimator's own resolution: the period is
the mean of 8 whole ring periods, and `sim/ro-ring-timestep-convergence/`'s
zero-injected-noise control measured what the transient solver alone
manufactures at the same 5 ps timestep. A shift smaller than that is an upper
bound, not a measurement, and this script says so rather than quoting it as a
result.

`--emit-record` mints an append-only reduction record under
`sim/post-layout-parasitic-impact/records/` in the same
`<YYYYMMDD>-<HHMMSS>-<shortsha>` id scheme `sim/bin/corner-run.py` uses, and
refuses to overwrite one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PL_RECORDS = REPO_ROOT / "sim" / "post-layout-ro-ring5" / "records"
FLOOR_RECORDS = REPO_ROOT / "sim" / "ro-ring-timestep-convergence" / "records"
OUT_RECORDS = REPO_ROOT / "sim" / "post-layout-parasitic-impact" / "records"

sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
from evidence_record import mint_record, new_record_id  # noqa: E402

WIDTHS = ["0p42", "0p44", "0p46", "0p48"]
WIDTH_UM = {"0p42": 0.42, "0p44": 0.44, "0p46": 0.46, "0p48": 0.48}

DECK_TIED = "tb_post_layout_ro_ring5.spice"
DECK_FLOAT = "tb_post_layout_substrate_float.spice"
DECK_SOLO = "tb_post_layout_substrate_float_solo.spice"

#: The small rationals DR-0003 section 8 names as the mutual-injection-lock
#: hazard a `wstv` ladder has to stay clear of.
LOCK_RATIOS = {"4/3": 4 / 3, "3/2": 3 / 2, "2/1": 2.0}


def load_points() -> dict[tuple, dict[str, dict]]:
    """{(temp, vdd, corner): {deck filename: measurements}} plus record ids."""
    points: dict[tuple, dict[str, dict]] = {}
    record_ids: dict[str, set] = {}
    for path in sorted(PL_RECORDS.glob("*.json")):
        rec = json.loads(path.read_text())
        deck = rec["testbench"].split("/")[-1]
        record_ids.setdefault(deck, set()).add(rec["record_id"])
        for corner in rec["corners"]:
            key = (rec["pvt"]["temp_c"], rec["pvt"]["vdd_v"], corner["corner"])
            points.setdefault(key, {})[deck] = corner["measurements"]
    return points, record_ids


def numerical_floor() -> tuple[float, str]:
    """(per-period scatter as a fraction of T_0, source record id).

    From `sim/ro-ring-timestep-convergence/`'s zero-injected-noise control at
    the same 5 ps timestep this campaign runs at: `sigma_1 / tbar`. That is
    what the transient solver manufactures by itself, with no noise sources
    in the deck at all -- the resolution floor under any period-shift claim.
    """
    best = None
    for path in sorted(FLOOR_RECORDS.glob("*.json")):
        rec = json.loads(path.read_text())
        if str(rec.get("tran", {}).get("noise_amp")).strip() not in ("0", "0.0"):
            continue
        if rec.get("tran", {}).get("tmax") != "5p":
            continue
        meas = rec["corners"][0]["measurements"]
        best = (meas["sigma_1"] / meas["tbar"], rec["record_id"])
    if best is None:
        raise SystemExit(
            "error: no zero-noise 5p control record found under "
            f"{FLOOR_RECORDS.relative_to(REPO_ROOT)}"
        )
    return best


def fmt_point(key: tuple) -> str:
    temp, vdd, corner = key
    return f"{temp:g} degC / {vdd:g} V / {corner}"


def reduce_all(points: dict, floor_frac: float) -> dict:
    rows = []
    for key in sorted(points):
        decks = points[key]
        if not all(d in decks for d in (DECK_TIED, DECK_FLOAT, DECK_SOLO)):
            raise SystemExit(f"error: {fmt_point(key)} is missing a deck: {sorted(decks)}")
        tied, float_, solo = decks[DECK_TIED], decks[DECK_FLOAT], decks[DECK_SOLO]

        t_pex = {w: tied[f"t_pex_wstv{w}"] for w in WIDTHS}
        t_pre = {w: tied[f"t_pre_wstv{w}"] for w in WIDTHS}
        slowdown = {w: t_pex[w] / t_pre[w] for w in WIDTHS}

        # Pairwise ladder ratios (slower / faster, so every ratio is >= 1) and
        # the closest approach to any mutual-injection-lock rational.
        ratios = {}
        for i, wi in enumerate(WIDTHS):
            for wj in WIDTHS[i + 1 :]:
                ratios[f"{wi}/{wj}"] = t_pex[wi] / t_pex[wj]
        closest = min(
            (
                (abs(r - v) / v, name, label, r)
                for name, r in ratios.items()
                for label, v in LOCK_RATIOS.items()
            ),
            key=lambda t: t[0],
        )

        t_tied1, t_solo1, t_float1 = (
            tied["t_pex_wstv0p42"],
            solo["t_solo_wstv0p42"],
            float_["t_float_wstv0p42"],
        )
        rows.append(
            {
                "point": fmt_point(key),
                "temp_c": key[0],
                "vdd_v": key[1],
                "corner": key[2],
                "t_pex_s": t_pex,
                "t_pre_s": t_pre,
                "slowdown": slowdown,
                "skew_span_pex": tied["skew_span_pex"],
                "skew_span_pre": tied["skew_span_pre"],
                "ladder_ratios_pex": ratios,
                "closest_lock_ratio": {
                    "pair": closest[1],
                    "rational": closest[2],
                    "ratio": closest[3],
                    "relative_margin": closest[0],
                },
                "swing_frac_pex_ring": tied["swing_frac_pex_ring"],
                "swing_frac_pre_ring": tied["swing_frac_pre_ring"],
                "swing_frac_pex_buf": tied["swing_frac_pex_buf"],
                "swing_frac_pre_buf": tied["swing_frac_pre_buf"],
                "i_ratio_wstv0p42": tied["i_pex_wstv0p42"] / tied["i_pre_wstv0p42"],
                "i_ratio_wstv0p48": tied["i_pex_wstv0p48"] / tied["i_pre_wstv0p48"],
                "substrate": {
                    "t_tied_s": t_tied1,
                    "t_solo_s": t_solo1,
                    "t_float_s": t_float1,
                    "loading_frac": (t_solo1 - t_tied1) / t_tied1,
                    "coupling_frac": (t_float1 - t_solo1) / t_solo1,
                    "vsubs_pp_frac_4ring": float_["vsubs_pp_frac"],
                    "vsubs_pp_frac_1ring": solo["vsubs_pp_solo_frac"],
                    "skew_span_float": float_["skew_span_float"],
                },
            }
        )

    slow_all = [r["slowdown"][w] for r in rows for w in WIDTHS]
    coup = [abs(r["substrate"]["coupling_frac"]) for r in rows]
    load = [r["substrate"]["loading_frac"] for r in rows]
    return {
        "points": rows,
        "slowdown_min": min(slow_all),
        "slowdown_max": max(slow_all),
        "slowdown_by_width": {
            w: {
                "min": min(r["slowdown"][w] for r in rows),
                "max": max(r["slowdown"][w] for r in rows),
            }
            for w in WIDTHS
        },
        "skew_span_pex_min": min(r["skew_span_pex"] for r in rows),
        "skew_span_pex_max": max(r["skew_span_pex"] for r in rows),
        "skew_span_pre_min": min(r["skew_span_pre"] for r in rows),
        "skew_span_pre_max": max(r["skew_span_pre"] for r in rows),
        "ladder_margin_min": min(
            r["closest_lock_ratio"]["relative_margin"] for r in rows
        ),
        "ladder_margin_min_point": min(
            rows, key=lambda r: r["closest_lock_ratio"]["relative_margin"]
        )["point"],
        "coupling_frac_absmax": max(coup),
        "coupling_points_above_floor": sum(1 for c in coup if c > floor_frac),
        "coupling_points_total": len(coup),
        # A real frequency pull has a consistent sign across the grid; a
        # scatter that changes sign point to point is the estimator's own
        # noise wearing a coupling costume.
        "coupling_sign_consistent": (
            all(r["substrate"]["coupling_frac"] > 0 for r in rows)
            or all(r["substrate"]["coupling_frac"] < 0 for r in rows)
        ),
        "coupling_resolvable": (
            sum(1 for c in coup if c > floor_frac) * 2 > len(coup)
            and (
                all(r["substrate"]["coupling_frac"] > 0 for r in rows)
                or all(r["substrate"]["coupling_frac"] < 0 for r in rows)
            )
        ),
        "loading_frac_min": min(load),
        "loading_frac_max": max(load),
        "vsubs_pp_frac_4ring_max": max(
            r["substrate"]["vsubs_pp_frac_4ring"] for r in rows
        ),
        "vsubs_pp_frac_1ring_max": max(
            r["substrate"]["vsubs_pp_frac_1ring"] for r in rows
        ),
        "numerical_floor_frac": floor_frac,
    }


def render(summary: dict, floor_rid: str) -> str:
    out: list[str] = []
    a = out.append
    rows = summary["points"]

    a("## 1. What the extracted parasitics cost")
    a("")
    a("Post-layout period / pre-layout period, same deck, same corner, per ring.")
    a("")
    a("| PVT point | wstv 0.42 | 0.44 | 0.46 | 0.48 |")
    a("|---|---|---|---|---|")
    for r in rows:
        a(
            f"| {r['point']} | "
            + " | ".join(f"{r['slowdown'][w]:.3f}x" for w in WIDTHS)
            + " |"
        )
    a("")
    a(
        f"**Slowdown over the whole grid: {summary['slowdown_min']:.3f}x - "
        f"{summary['slowdown_max']:.3f}x.** Per width: "
        + ", ".join(
            f"{WIDTH_UM[w]:g} um {summary['slowdown_by_width'][w]['min']:.3f}-"
            f"{summary['slowdown_by_width'][w]['max']:.3f}x"
            for w in WIDTHS
        )
        + "."
    )
    a("")
    a("| PVT point | ring swing pre -> post | buffered swing pre -> post | I(vddr) post/pre, 0.42 / 0.48 |")
    a("|---|---|---|---|")
    for r in rows:
        a(
            f"| {r['point']} | {r['swing_frac_pre_ring']:.3f} -> "
            f"{r['swing_frac_pex_ring']:.3f} x Vdd | "
            f"{r['swing_frac_pre_buf']:.3f} -> {r['swing_frac_pex_buf']:.3f} x Vdd | "
            f"{r['i_ratio_wstv0p42']:.3f} / {r['i_ratio_wstv0p48']:.3f} |"
        )
    a("")

    a("## 2a. Does the wstv frequency ladder survive the parasitics?")
    a("")
    a(
        "Ladder span is the slowest ring's period over the fastest ring's "
        "(`wstv` 0.42 / 0.48). Every pairwise ratio is checked against the "
        "mutual-injection-lock rationals DR-0003 section 8 names (4/3, 3/2, 2/1)."
    )
    a("")
    a("| PVT point | span pre-layout | span post-layout | closest lock rational | margin |")
    a("|---|---|---|---|---|")
    for r in rows:
        c = r["closest_lock_ratio"]
        a(
            f"| {r['point']} | {r['skew_span_pre']:.4f} | {r['skew_span_pex']:.4f} | "
            f"{c['pair']} = {c['ratio']:.4f} vs {c['rational']} | "
            f"{c['relative_margin'] * 100:.1f}% |"
        )
    a("")
    a(
        f"**Post-layout span {summary['skew_span_pex_min']:.4f} - "
        f"{summary['skew_span_pex_max']:.4f}x** (pre-layout "
        f"{summary['skew_span_pre_min']:.4f} - {summary['skew_span_pre_max']:.4f}x). "
        f"The closest any ring pair comes to a locking rational anywhere on the "
        f"grid is **{summary['ladder_margin_min'] * 100:.1f}%** away, at "
        f"{summary['ladder_margin_min_point']}."
    )
    a("")

    a("## 2b. How large is the inter-ring coupling itself?")
    a("")
    a(
        "Ring 1's period under the three decks, and the loading/coupling split "
        "the solo control makes possible. Positive = slower."
    )
    a("")
    a("| PVT point | t tied | t solo (float) | t float (4 running) | loading | coupling | vsubs pp, 4 rings / 1 ring |")
    a("|---|---|---|---|---|---|---|")
    for r in rows:
        s = r["substrate"]
        a(
            f"| {r['point']} | {s['t_tied_s'] * 1e9:.4f} ns | "
            f"{s['t_solo_s'] * 1e9:.4f} ns | {s['t_float_s'] * 1e9:.4f} ns | "
            f"{s['loading_frac'] * 100:+.3f}% | {s['coupling_frac'] * 100:+.4f}% | "
            f"{s['vsubs_pp_frac_4ring'] * 100:.2f}% / "
            f"{s['vsubs_pp_frac_1ring'] * 100:.2f}% of Vdd |"
        )
    a("")
    floor = summary["numerical_floor_frac"]
    a(
        f"**Coupling-attributable period shift: at most "
        f"{summary['coupling_frac_absmax'] * 100:.4f}% of the ring period**, "
        f"anywhere on the grid, at the pessimistic (infinite-impedance shared "
        f"substrate) bound."
    )
    a("")
    a(
        f"The transient solver's own numerical period scatter, measured with no "
        f"injected noise at the same 5 ps timestep, is **{floor * 100:.4f}% of "
        f"T_0** (`sim/ro-ring-timestep-convergence/records/{floor_rid}`). "
        f"{summary['coupling_points_above_floor']} of "
        f"{summary['coupling_points_total']} grid points exceed it, and the "
        f"shift's sign is "
        + ("consistent" if summary["coupling_sign_consistent"] else "NOT consistent")
        + " across the grid."
    )
    a("")
    if summary["coupling_resolvable"]:
        a(
            "A majority of points stand above the numerical floor with a "
            "consistent sign, so the coupling shift is a resolved (if small) "
            "measurement rather than estimator noise."
        )
    else:
        a(
            "So the coupling shift is an **upper bound, not a resolved "
            "measurement**. A real frequency pull would move every ring the "
            "same way; this one does not clear the solver's own period scatter "
            "at most points and does not keep a consistent sign. What IS "
            "resolved is that the shared node genuinely carries all four rings' "
            "activity -- it swings "
            f"{summary['vsubs_pp_frac_4ring_max'] * 100:.2f}% of Vdd peak to "
            f"peak with four rings running against "
            f"{summary['vsubs_pp_frac_1ring_max'] * 100:.2f}% with one -- and "
            "that even so, the frequency pull it produces stays under "
            f"{summary['coupling_frac_absmax'] * 100:.3f}% of the ring period."
        )
    a("")
    a(
        f"The floating node's *loading* effect, which the solo control separates "
        f"out, is {summary['loading_frac_min'] * 100:+.3f}% to "
        f"{summary['loading_frac_max'] * 100:+.3f}% -- an artifact of the "
        "unmodelled substrate tie, not a statement about ring independence."
    )
    a("")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--emit-record",
        action="store_true",
        help="mint an append-only reduction record under "
        "sim/post-layout-parasitic-impact/records/",
    )
    parser.add_argument("--author", default="loom-builder@sky130-trng")
    args = parser.parse_args(argv)

    points, record_ids = load_points()
    if not points:
        print(
            f"error: no records found under {PL_RECORDS.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )
        return 1
    floor_frac, floor_rid = numerical_floor()
    summary = reduce_all(points, floor_frac)
    body = render(summary, floor_rid)
    print(body)

    if not args.emit_record:
        return 0

    now, sha, rid = new_record_id(REPO_ROOT)
    header = [
        f"# {rid} -- post-layout-parasitic-impact",
        "",
        "**Claim**: what `klt extract --parasitics` costs the five-stage ring "
        "(period, swing, supply current) over the PVT grid; whether the `wstv` "
        "frequency ladder survives it; and a bounded first answer to DR-0003 "
        "section 8's inter-ring decorrelation question, now that extracted "
        "parasitics give the rings a shared node to couple through.",
        "",
        "**Level**: transistor (derived -- this record introduces no new "
        "simulation; it is arithmetic over the cited transistor-level records)",
        "**Seed**: N/A (deterministic reduction; the underlying runs are "
        "deterministic transients with no injected noise)",
        "**Analysis**: `sim/post-layout-parasitic-impact/analysis/"
        "parasitic-impact.py` (re-run to reproduce)",
        "",
        "## Source records",
        "",
        "Post-layout ring campaign (`sim/post-layout-ro-ring5/records/`):",
        "",
    ]
    for deck in (DECK_TIED, DECK_FLOAT, DECK_SOLO):
        header.append(f"- `{deck}`:")
        header += [f"  - `{r}`" for r in sorted(record_ids.get(deck, ()))]
    header += [
        "",
        "Estimator numerical floor (`sim/ro-ring-timestep-convergence/records/`):",
        "",
        f"- `{floor_rid}`",
        "",
        "---",
        "",
    ]

    summary_out = {
        "record_id": rid,
        "slug": "post-layout-parasitic-impact",
        "level": "transistor (derived)",
        "analysis": "sim/post-layout-parasitic-impact/analysis/parasitic-impact.py",
        "source_records": {
            deck: sorted(record_ids.get(deck, ()))
            for deck in (DECK_TIED, DECK_FLOAT, DECK_SOLO)
        }
        | {"numerical_floor": [floor_rid]},
        "author": args.author,
        "timestamp_utc": now.isoformat(),
        "repo_sha": sha,
        **summary,
    }
    if mint_record(
        OUT_RECORDS, REPO_ROOT, rid, header, body, summary_out,
        author=args.author, now=now, sha=sha,
    ) is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
