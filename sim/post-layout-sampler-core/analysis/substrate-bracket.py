#!/usr/bin/env python3
"""Reduce `sim/post-layout-sampler-core/`'s three decks to the sampler_core-scope
tied/float/solo substrate bracket DR-0003 section 8 asks about.

    python3 sim/post-layout-sampler-core/analysis/substrate-bracket.py

**Pure arithmetic over already-committed evidence.** It runs no simulator, reads
no PDK, and touches only `sim/post-layout-sampler-core/records/*.json`. It is the
sampler_core-scope sibling of
`sim/post-layout-parasitic-impact/analysis/parasitic-impact.py`'s own
`loading`/`coupling` decomposition (ring scope, DR-0005), re-run at the one
hierarchy level DR-0006's own "Follow-up required" section names as having no
substrate-coupling measurement of its own.

The three decks
---------------

    tied  : tb_post_layout_sampler_core.spice          -- `vsubs` hard to 0,
            four rings running, six samplers clocked. Zero coupling by
            construction (an ideal zero-impedance substrate cannot carry a
            signal), and therefore the zero-coupling baseline for ring 1.
    solo  : ..._substrate_float_solo.spice             -- `vsubs` untied,
            rings 2-4 present but STOPPED, six samplers clocked. The floating
            node's LOADING effect alone.
    float : ..._substrate_float.spice                  -- `vsubs` untied,
            four rings running, six samplers clocked. Loading + coupling.

        loading  = t(solo)  - t(tied)
        coupling = t(float) - t(solo)

Reporting `t(float) - t(tied)` without the solo control attributes the whole
difference to coupling and overstates it -- the mistake DR-0005 documents an
earlier pass over the ring-scope evidence making.

Two estimators, and what separates them
---------------------------------------

`p_tr1` (rise=3 -> rise=13) is the estimator all three decks share, so it is the
only one on which the full three-way decomposition can be computed. At this
design's post-layout ring periods it falls entirely inside the first ~100 ns of
the run -- before `rst_n` releases at 300 ns -- so the six samplers are present,
placed and loading their `d` pins, but not switching.

`p_tr1_clk` (ten periods from the first rising edge past 400 ns) exists only in
the float and solo decks, which were authored together after the tied records
were already minted. It therefore yields a `coupling` figure with the digitizer
bank actively latching, but no `loading` figure. That asymmetry is reported, not
hidden.

Resolution
----------

Every shift is stated against the transient solver's own numerical period
scatter. `sim/ro-ring-timestep-convergence/` measured that with no injected
noise at all, at the same 5 ps timestep, on the *ring-only* deck: 0.024% of
`T_0`. DR-0006 already names re-deriving it at array scale as an open follow-up;
this script inherits that limitation and prints the comparison as a bound, not
as a measurement.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDS = REPO_ROOT / "sim" / "post-layout-sampler-core" / "records"

# sim/ro-ring-timestep-convergence/: period scatter the transient solver alone
# manufactures at 5 ps with zero injected noise, as a fraction of T_0. Measured
# on the ring-only deck; DR-0006 flags re-deriving it at larger scale as open.
NUMERICAL_FLOOR_FRAC = 0.00024

DECKS = {
    "tied": "tb_post_layout_sampler_core.spice",
    "float": "tb_post_layout_sampler_core_substrate_float.spice",
    "solo": "tb_post_layout_sampler_core_substrate_float_solo.spice",
}


def load() -> dict:
    """{(deck, temp, vdd, corner): measurements} over every passing corner run.

    Records are append-only, so the same (deck, PVT point, corner) can appear
    more than once -- e.g. an early run whose `ff` corner timed out under host
    contention, kept alongside the clean re-run that superseded it. Only corner
    runs that individually succeeded (`ok`) are read, and where two surviving
    runs cover the same key the later record id wins (ids sort chronologically).
    """
    out: dict = {}
    superseded = set()
    docs = []
    for path in sorted(RECORDS.glob("*.json")):
        doc = json.load(path.open())
        docs.append(doc)
        sup = (doc.get("supersedes") or "").strip()
        if sup and sup != "(none)":
            superseded.add(sup)
    for doc in docs:
        if doc["record_id"] in superseded:
            continue
        name = Path(doc["testbench"]).name
        deck = next((k for k, v in DECKS.items() if v == name), None)
        if deck is None:
            continue
        temp = doc["pvt"]["temp_c"]
        vdd = doc["pvt"]["vdd_v"]
        for corner in doc.get("corners", []):
            if not corner.get("ok"):
                continue
            out[(deck, temp, vdd, corner["corner"])] = corner["measurements"]
    return out


def main() -> int:
    meas = load()
    points = sorted(
        {(t, v, c) for (_d, t, v, c) in meas},
        key=lambda p: (p[0], p[1], p[2]),
    )

    print("Sampler_core-scope substrate bracket (tied / float / solo)")
    print("Records:", RECORDS.relative_to(REPO_ROOT))
    print()
    header = (
        f"{'temp':>6} {'vdd':>5} {'corner':>6} "
        f"{'t_tied(ns)':>11} {'t_solo(ns)':>11} {'t_float(ns)':>12} "
        f"{'loading%':>9} {'coupling%':>10}"
    )
    print(header)
    print("-" * len(header))

    loadings, couplings = [], []
    for temp, vdd, corner in points:
        try:
            tied = meas[("tied", temp, vdd, corner)]["p_tr1"]
            solo = meas[("solo", temp, vdd, corner)]["p_tr1"]
            flt = meas[("float", temp, vdd, corner)]["p_tr1"]
        except KeyError:
            continue
        loading = (solo - tied) / tied * 100.0
        coupling = (flt - solo) / solo * 100.0
        loadings.append(loading)
        couplings.append(coupling)
        print(
            f"{temp:>6.0f} {vdd:>5.2f} {corner:>6} "
            f"{tied * 1e9:>11.4f} {solo * 1e9:>11.4f} {flt * 1e9:>12.4f} "
            f"{loading:>+9.3f} {coupling:>+10.3f}"
        )

    if not loadings:
        print("(no complete tied/solo/float triples found)")
        return 1

    print()
    print(f"n = {len(loadings)} grid points (reset-held estimator, p_tr1)")
    print(f"loading  = t(solo)  - t(tied)  : {min(loadings):+.3f}% to {max(loadings):+.3f}%")
    print(f"coupling = t(float) - t(solo)  : {min(couplings):+.3f}% to {max(couplings):+.3f}%")
    pos = sum(1 for c in couplings if c > 0)
    print(f"coupling sign consistency      : {pos} of {len(couplings)} positive")
    floor = NUMERICAL_FLOOR_FRAC * 100.0
    above = sum(1 for c in couplings if abs(c) > floor)
    print(
        f"points whose |coupling| exceeds the ring-scale numerical floor "
        f"({floor:.3f}%): {above} of {len(couplings)}"
    )

    # --- clocked-window estimator: coupling only (no tied counterpart) ------
    print()
    print("Clocked-window estimator (p_tr1_clk, six samplers latching):")
    header2 = (
        f"{'temp':>6} {'vdd':>5} {'corner':>6} "
        f"{'t_solo(ns)':>11} {'t_float(ns)':>12} {'coupling%':>10} "
        f"{'vsub_rst':>9} {'vsub_clk':>9}"
    )
    print(header2)
    print("-" * len(header2))
    couplings_clk = []
    for temp, vdd, corner in points:
        try:
            solo_m = meas[("solo", temp, vdd, corner)]
            flt_m = meas[("float", temp, vdd, corner)]
            solo = solo_m["p_tr1_clk"]
            flt = flt_m["p_tr1_clk"]
        except KeyError:
            continue
        coupling = (flt - solo) / solo * 100.0
        couplings_clk.append(coupling)
        print(
            f"{temp:>6.0f} {vdd:>5.2f} {corner:>6} "
            f"{solo * 1e9:>11.4f} {flt * 1e9:>12.4f} {coupling:>+10.3f} "
            f"{flt_m['vsub_swing_rst'] * 100:>8.2f}% {flt_m['vsub_swing_clk'] * 100:>8.2f}%"
        )
    if couplings_clk:
        pos = sum(1 for c in couplings_clk if c > 0)
        print()
        print(
            f"coupling (clocked window)      : {min(couplings_clk):+.3f}% to "
            f"{max(couplings_clk):+.3f}%, {pos} of {len(couplings_clk)} positive"
        )

    # --- substrate node swing: float (four rings) vs solo (one ring) --------
    swings = [
        (
            meas[("float", t, v, c)]["vsub_swing_rst"] * 100,
            meas[("solo", t, v, c)]["vsub_swing_rst"] * 100,
            meas[("float", t, v, c)]["vsub_swing_clk"] * 100,
            meas[("solo", t, v, c)]["vsub_swing_clk"] * 100,
        )
        for (t, v, c) in points
        if ("float", t, v, c) in meas and ("solo", t, v, c) in meas
    ]
    if swings:
        print()
        print("Shared substrate node peak-to-peak swing, as % of Vdd:")
        print(
            f"  reset-held window (rings only)  : "
            f"four rings {min(s[0] for s in swings):.2f}-{max(s[0] for s in swings):.2f}%, "
            f"one ring {min(s[1] for s in swings):.2f}-{max(s[1] for s in swings):.2f}%"
        )
        print(
            f"  clocked window (rings+samplers) : "
            f"four rings {min(s[2] for s in swings):.2f}-{max(s[2] for s in swings):.2f}%, "
            f"one ring {min(s[3] for s in swings):.2f}-{max(s[3] for s in swings):.2f}%"
        )
        # The comparison that says how big an aggressor the digitizer bank is:
        # ONE ring plus a clocking sampler bank, against FOUR free-running rings
        # with the bank static -- same corner, same deck family, same node.
        n_gt = sum(1 for s in swings if s[3] > s[0])
        print(
            f"  one ring + clocked samplers exceeds four rings + static samplers "
            f"at {n_gt} of {len(swings)} grid points"
        )

    # --- DR-0003 section 8's own ladder criterion, whole-chain scope -------
    # Section 8 asks that the realized ring-period ratios stay clear of the
    # small rationals that mutually injection-lock. Checked here on the FLOAT
    # deck (the pessimistic substrate terminal) in both windows.
    rationals = {"2/1": 2.0, "3/2": 1.5, "4/3": 4 / 3}
    print()
    print("`wstv` ladder against DR-0003 section 8's injection-lock rationals")
    print("(float deck, all four rings, closest approach over every ring pair):")
    for label, suffix in (("reset-held", ""), ("clocked", "_clk")):
        spans, closest = [], None
        for temp, vdd, corner in points:
            m = meas.get(("float", temp, vdd, corner))
            if not m:
                continue
            try:
                t = [m[f"p_tr{i}{suffix}"] for i in (1, 2, 3, 4)]
            except KeyError:
                continue
            spans.append(max(t) / min(t))
            for i in range(4):
                for j in range(4):
                    if i == j:
                        continue
                    r = t[i] / t[j]
                    for name, val in rationals.items():
                        d = abs(r - val) / val
                        if closest is None or d < closest[0]:
                            closest = (d, name, temp, vdd, corner)
        if spans and closest:
            d, name, temp, vdd, corner = closest
            print(
                f"  {label:>10} window: ladder span {min(spans):.4f}x-{max(spans):.4f}x; "
                f"closest approach to any rational is {d * 100:.1f}% "
                f"(from {name}, {temp:.0f} degC / {vdd:.2f} V / {corner})"
            )

    print()
    print(
        "Every figure above is a bracket terminal, not a physical coupling\n"
        "magnitude: the extractor emits no substrate or tap resistance at all\n"
        "(klayout-tools#1503), so tied and float are the two ends of a range\n"
        "whose interior is unmodelled. See\n"
        "spec/decision-records/DR-0009-sampler-core-substrate-bracket-and-wstv-decorrelation.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
