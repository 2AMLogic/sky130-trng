#!/usr/bin/env python3
"""Reduce issue #604's sampler_core active-power budget (analysis generator).

Inputs (all committed):
* the two ff / 1.98 V control records (Ts = 100 ns, active window 400-800 ns)
  -- the curator-verified reproduction base;
* the two Ts = 20 us batch-run corner reports emitted by
  sim/post-layout-sampler-core/make-ts20u-requests.py (one per temperature).

Output: ``analysis/active-power-budget.md`` -- the per-rail budget at both
ff temperatures (ring rails vs shared VDD, schematic vs extracted leg,
signed headroom to the README's < 500 uW row), the 100 ns-vs-20 us
sampling-rate comparison with the reset-window cross-run anchor, and the
disposition recommendation.

Level of every number here: transistor-level transient simulation of the
committed pre-layout netlist and the flat-extracted parasitic netlist,
provisional and simulation-derived, not silicon.

Nothing here simulates anything; it reads committed JSON evidence only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUG = HERE.parent
REPO = SLUG.parents[1]

VDD = 1.98
TARGET_UW = 500.0
BOUND = "README target row: < 500 uW active (analog-partition share)"

CONTROL_RECORDS = {
    -40.0: SLUG / "records" / "20260908-050034-ef0db50.json",
    125.0: SLUG / "records" / "20260908-053634-ef0db50.json",
}
TS20U_REPORTS = {
    -40.0: SLUG / "corners" / "ts20u-m40C-1.98V" / "report.json",
    125.0: SLUG / "corners" / "ts20u-125C-1.98V" / "report.json",
}
TEMPS = (-40.0, 125.0)

#: DR-0003 section 7 / DR-0010 R3 array-only (rings + buffers + XOR)
#: comparison points at the ff / 1.98 V corners
ARRAY_ONLY = {-40.0: 431.6, 125.0: 473.9}


def uw(amps: float) -> float:
    return amps * VDD * 1e6


class EvidenceError(RuntimeError):
    """A structural problem in the inputs; the budget is not emitted."""


def control_rows(rec: dict) -> dict:
    """ff-corner per-leg rail currents of a committed control record."""
    corner = next((c for c in rec["corners"] if c["corner"] == "ff"), None)
    if corner is None or not corner.get("ok"):
        raise EvidenceError(f"{rec['record_id']}: no ok ff corner")
    m = corner["measurements"]
    return {
        "record_id": rec["record_id"],
        "schematic": {
            "rings_a": m["i_rings_act"], "block_a": m["i_block_act"],
            "total_a": m["i_total_act"],
            "rings_rst_a": m["i_rings_rst"], "block_rst_a": m["i_block_rst"],
        },
        "extracted": {
            "rings_a": m["p_i_rings_act"], "block_a": m["p_i_block_act"],
            "total_a": m["p_i_total_act"],
            "rings_rst_a": m["p_i_rings_rst"], "block_rst_a": m["p_i_block_rst"],
        },
        "windows": {"rst_ns": (50, 250), "act_ns": (400, 800)},
        "deck": rec["testbench"],
        "netlists": {k: v["path"] for k, v in rec["netlists"].items()},
        "ngspice": rec["tools"]["ngspice"],
    }


def ts20u_rows(report: dict) -> dict:
    """Per-leg rail currents of one Ts = 20 us corner report + anchor deltas."""
    if report.get("status") not in ("pass", "partial", "complete"):
        raise EvidenceError(f"ts20u report status={report.get('status')!r}")
    corners = report.get("corners") or []
    if len(corners) != 1:
        raise EvidenceError(f"expected 1 corner, got {len(corners)}")
    c = corners[0]
    got = {m["name"]: m["value"] for m in c["measurements"]}
    missing = [n for n in (
        "x_ir1_act", "x_ir2_act", "x_ir3_act", "x_ir4_act", "x_ib_act",
        "s_ir1_act", "s_ir2_act", "s_ir3_act", "s_ir4_act", "s_ib_act",
        "x_ir1_rst", "x_ir2_rst", "x_ir3_rst", "x_ir4_rst", "x_ib_rst",
        "s_ir1_rst", "s_ir2_rst", "s_ir3_rst", "s_ir4_rst", "s_ib_rst",
        "x_ir1_lo", "x_ir1_hi", "s_ir1_lo", "s_ir1_hi", "x_ib_lo", "x_ib_hi",
        "s_ib_lo", "s_ib_hi") if got.get(n) is None]
    if missing:
        raise EvidenceError(f"missing measurements: {missing[:5]}...")
    job = report.get("environment", {}).get("remote", {})
    out = {"job_id": job.get("job_id"), "state": job.get("state"),
           "runner_klt": job.get("runner_klt_version"),
           "compat": job.get("runner_compatibility"),
           "runtime_s": c.get("runtime_s"), "corner_id": c.get("corner_id")}
    for leg, p in (("extracted", "x"), ("schematic", "s")):
        rst_rails = sum(-got[f"{p}_ir{i}_rst"] for i in (1, 2, 3, 4))
        act_rails = sum(-got[f"{p}_ir{i}_act"] for i in (1, 2, 3, 4))
        out[leg] = {
            "rings_a": act_rails, "block_a": -got[f"{p}_ib_act"],
            "total_a": act_rails - got[f"{p}_ib_act"],
            "rings_rst_a": rst_rails, "block_rst_a": -got[f"{p}_ib_rst"],
            "total_rst_a": rst_rails - got[f"{p}_ib_rst"],
            "rail_act_a": [-got[f"{p}_ir{i}_act"] for i in (1, 2, 3, 4)],
            # stationarity halves (indicator, not period averages)
            "half_delta_pp": (got[f"{p}_ib_lo"] - got[f"{p}_ib_hi"])
                             / abs(got[f"{p}_ib_act"]) * 100,
        }
    return out


def anchor_delta_pp(ctrl: dict, ts: dict) -> dict:
    """W_RST (stimulus-identical window) cross-run agreement, in %."""
    out = {}
    for leg in ("schematic", "extracted"):
        c = ctrl[leg]["rings_rst_a"] + ctrl[leg]["block_rst_a"]
        t = ts[leg]["total_rst_a"]
        out[leg] = (t - c) / c * 100
    return out


def fmt(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}"


def main(argv: list[str] | None = None) -> int:
    out_path = SLUG / "analysis" / "active-power-budget.md"
    data = {}
    for t in TEMPS:
        ctrl = control_rows(json.loads(CONTROL_RECORDS[t].read_text()))
        ts = ts20u_rows(json.loads(TS20U_REPORTS[t].read_text()))
        data[t] = {"ctrl": ctrl, "ts": ts,
                   "anchor": anchor_delta_pp(ctrl, ts)}
    plan = json.loads((SLUG / "corners" / "ts20u-m40C-1.98V" /
                       "plan.json").read_text())
    lines: list[str] = []
    a = lines.append
    a("# sampler_core analog active-power budget (issue #604)")
    a("")
    a(f"Bound: **{BOUND}**. Every number below is transistor-level transient")
    a("simulation (ngspice) of the committed `design/sampler_core.spice`")
    a("pre-layout netlist and the flat-extracted parasitic netlist")
    a("`layout/pex-sampler-core/sampler_core_pex.spice` (sha256 in each cited")
    a("record/plan) -- provisional, simulation-derived, not silicon. The")
    a("failing corners are exactly the two ff / 1.98 V temperatures of the")
    a("four-point post-layout PVT grid; the other ten corners of issue #597's")
    a("grid pass extracted and are not re-derived here.")
    a("")
    a("## 0. Provenance")
    a("")
    a("| comparison leg | netlist | loading | clk period | windows |")
    a("|---|---|---|---|---|")
    nl = data[-40.0]["ctrl"]["netlists"]
    a(f"| 100 ns control (both legs, same deck) | `{nl['RO_RING5']}` + "
      f"`{nl['PEX_LIB']}` (sha256 in each cited record) | each leg's own "
      f"buffers/XOR/samplers; outputs unloaded | 100 ns, first edge 320 ns | "
      f"rst 50-250 ns, act 400-800 ns |")
    a(f"| 20 us runs (both legs, same deck) | `{plan['design_lib']['path']}` "
      f"(sha256 `{plan['design_lib']['sha256'][:16]}...`) + "
      f"`{plan['pex_lib']['path']}` (sha256 `{plan['pex_lib']['sha256'][:16]}...`) | "
      f"identical to the control deck (netlists inlined verbatim) | 20 us, "
      f"first edge 320 ns, 49.8 % duty | rst 50-250 ns, act 20.32-40.32 us "
      f"(one complete settled period; deviations recorded in each "
      f"corners/ts20u-*/plan.json) |")
    a("")
    a("Supply 1.98 V on all rails; process ff; temperatures -40 / +125 C.")
    a("")
    a("## 1. The 100 ns control budget (committed records, reproduced)")
    a("")
    a("Active window 400-800 ns (four complete 100 ns clk periods), reset-held")
    a("window 50-250 ns; per-rail currents x 1.98 V. Sums reproduce the")
    a("issue's table; the rail split (ring rails vs shared VDD = buffers +")
    a("XOR tree + six samplers) is the budget line assignment.")
    a("")
    for t in TEMPS:
        c = data[t]["ctrl"]
        a(f"### {t:+.0f} C (record `{c['record_id']}`, ff/1.98 V, ngspice build: {c['ngspice']})")
        a("")
        a("| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |")
        a("|---|---:|---:|---:|---:|")
        for leg in ("schematic", "extracted"):
            r, b, tot = (uw(c[leg][k]) for k in ("rings_a", "block_a", "total_a"))
            a(f"| {leg} | {fmt(r)} | {fmt(b)} | {fmt(tot)} | {fmt(TARGET_UW - tot)} |")
        a("")
    a("Rail-sum consistency (rings + block vs the record's own total):")
    a("")
    for t in TEMPS:
        c = data[t]["ctrl"]
        for leg in ("schematic", "extracted"):
            s = (c[leg]["rings_a"] + c[leg]["block_a"] - c[leg]["total_a"]) * VDD * 1e6
            a(f"- {t:+.0f} C {leg}: {s:+.3f} uW (source rounding)")
    a("")
    a("## 2. The Ts = 20 us matched runs (this issue's batch experiment)")
    a("")
    a("Stimulus and windows: DR-0003's ratified sampling period Ts = 20 us")
    a("(49.8 % duty, first edge 320 ns -- the control deck's own timing at the")
    a("real rate); W_RST = 50-250 ns bit-identical to the controls'; W_ACT =")
    a("20.32-40.32 us = exactly one complete settled clk period (edges at both")
    a("endpoints); halves at 30.32 us reported as a stationarity indicator.")
    a("Recorded deviations (tstep 50p vs the control's 5p; en/rst pulse widths")
    a("extended past tstop) and their measured error bars live in each")
    a("request's `plan.json`.")
    a("")
    for t in TEMPS:
        ts = data[t]["ts"]
        a(f"### {t:+.0f} C (job `{ts['job_id']}`, state {ts['state']}, "
          f"runner klt {ts['runner_klt']}, compat {ts['compat']}, "
          f"engine {ts['runtime_s']:.0f} s)")
        a("")
        a("| leg | ring rails (uW) | shared VDD (uW) | total (uW) | headroom to 500 uW |")
        a("|---|---:|---:|---:|---:|")
        for leg in ("schematic", "extracted"):
            r, b, tot = (uw(ts[leg][k]) for k in ("rings_a", "block_a", "total_a"))
            a(f"| {leg} | {fmt(r)} | {fmt(b)} | {fmt(tot)} | {fmt(TARGET_UW - tot)} |")
        a("")
        a(f"Stationarity (shared-VDD half-window spread): schematic "
          f"{ts['schematic']['half_delta_pp']:+.2f} %, extracted "
          f"{ts['extracted']['half_delta_pp']:+.2f} % of the leg's W_ACT mean.")
        a("")
    a("### Cross-run anchor (W_RST, stimulus-identical)")
    a("")
    a("| T | schematic total (uW) | extracted total (uW) |")
    a("|---|---:|---:|")
    for t in TEMPS:
        c, ts, an = data[t]["ctrl"], data[t]["ts"], data[t]["anchor"]
        a(f"| {t:+.0f} C | {uw(c['schematic']['rings_rst_a'] + c['schematic']['block_rst_a']):.1f} -> "
          f"{uw(ts['schematic']['total_rst_a']):.1f} ({an['schematic']:+.2f} %) | "
          f"{uw(c['extracted']['rings_rst_a'] + c['extracted']['block_rst_a']):.1f} -> "
          f"{uw(ts['extracted']['total_rst_a']):.1f} ({an['extracted']:+.2f} %) |")
    a("")
    a("## 3. Sampling-rate comparison and verdicts")
    a("")
    a("| T | leg | 100 ns total (uW) | 20 us total (uW) | delta | 20 us verdict vs 500 uW |")
    a("|---|---|---:|---:|---:|---|")
    for t in TEMPS:
        for leg in ("schematic", "extracted"):
            c100 = uw(data[t]["ctrl"][leg]["total_a"])
            c20 = uw(data[t]["ts"][leg]["total_a"])
            verdict = "PASS" if c20 < TARGET_UW else "FAIL"
            if abs(c20 - TARGET_UW) <= max(5.0, 0.01 * c20):
                verdict = "AT BOUND (within cross-run agreement)"
            a(f"| {t:+.0f} C | {leg} | {fmt(c100)} | {fmt(c20)} | "
              f"{c20 - c100:+.1f} | {verdict} |")
    a("")
    a("## 4. Array-only context (DR-0003 section 7 / DR-0010 R3)")
    a("")
    a("| T | array-only, 100 ns decks (uW) | schematic leg 20 us (uW) |")
    a("|---|---:|---:|")
    for t in TEMPS:
        a(f"| {t:+.0f} C | {ARRAY_ONLY[t]:.1f} | "
          f"{uw(data[t]['ts']['schematic']['total_a']):.1f} |")
    a("")
    text = "\n".join(lines)
    disp = SLUG / "analysis" / "disposition.md"
    if disp.is_file():
        text += "\n" + disp.read_text().rstrip() + "\n"
    if "--stdout" in (argv or []):
        print(text)
        return 0
    out_path.write_text(text)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
