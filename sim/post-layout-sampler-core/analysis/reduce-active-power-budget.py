#!/usr/bin/env python3
"""Reduce issue #604's sampler_core active-power budget (analysis generator).

Inputs (all committed):
* the two historical ff / 1.98 V control records (Ts = 100 ns, active window 400-800 ns)
  -- the curator-verified reproduction base;
* the two Ts = 20 us batch-run corner reports emitted by
  sim/post-layout-sampler-core/make-ts20u-requests.py (one per temperature);
* the corresponding ts100n control reports when collected from the fleet.

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
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUG = HERE.parent
REPO = SLUG.parents[1]
sys.path.insert(0, str(REPO / "layout" / "bin"))
from _hashing import sha256_text  # noqa: E402

VDD = 1.98
TARGET_UW = 500.0
BOUND = "README target row: < 500 uW active (analog-partition share)"

CONTROL_RECORDS = {
    -40.0: SLUG / "records" / "20260908-050034-ef0db50.json",
    125.0: SLUG / "records" / "20260908-053634-ef0db50.json",
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
        "netlists": rec["netlists"],
        "ngspice": rec["tools"]["ngspice"],
    }


def checked_init_digest(directory: Path, env: dict, requested: list[str]) -> str | None:
    """Check effective .spiceinit evidence wherever the fleet recorded it."""
    worker = env["remote"]["worker_environment"]
    candidates = [requested]
    threads = worker.get("threads_per_worker")
    if threads is not None:
        # klt can prepend its worker thread pin to the requested file.
        candidates.append([f"set num_threads={threads}", *requested])
    expected = {sha256_text("\n".join(lines) + "\n"): lines
                for lines in candidates}
    verified = None
    for record in (env.get("ngspice_init"), worker.get("ngspice_init")):
        if record is None:
            continue
        if not isinstance(record, dict):
            raise EvidenceError(f"{directory}: invalid runner ngspice_init")
        lines, digest = record.get("lines"), record.get("sha256")
        if record.get("source") == "none" and requested:
            raise EvidenceError(f"{directory}: runner reports no ngspice_init")
        if lines is None and digest is None:
            continue
        expected = {key: candidate for key, candidate in expected.items()
                    if (lines is None or lines == candidate)
                    and (digest is None or digest in (key, f"sha256:{key}"))}
        if not expected:
            raise EvidenceError(f"{directory}: contradictory runner ngspice_init")
        verified = next(iter(expected))  # Either lines or digest identifies the file.
    return verified


def fleet_run(directory: Path, temp: float, period: str) -> dict:
    """Bind this report to its planned deck, PVT and transient settings."""
    plan = json.loads((directory / "plan.json").read_text())
    request = json.loads((directory / "request.json").read_text())
    report = json.loads((directory / "report.json").read_text())
    if report["status"] != "pass" or len(report["corners"]) != 1:
        raise EvidenceError(f"{directory}: expected one passing fleet corner")
    c = report["corners"][0]
    env = report["environment"]
    short = period == "100n"
    stop = "850n" if short else "40.4u"
    axes = request["corners"]
    if (c["status"] != "pass" or c["process"] != "ff" or c["temperature_c"] != temp
            or axes["temperature_c"] != [temp] or axes["process"] != ["ff"]
            or {rail: [v] for rail, v in c["supply_v"].items()} != axes["supply_v"]
            or len(c["supply_v"]) != 10 or set(c["supply_v"].values()) != {VDD}
            or plan["corners"] != axes):
        raise EvidenceError(f"{directory}: incorrect PVT")
    if (request["analysis"] != {"kind": "tran", "args": f"50p {stop} uic"}
            or plan["analysis"] != request["analysis"]
            or plan["timing"]["ts_s"] != (100e-9 if short else 20e-6)):
        raise EvidenceError(f"{directory}: incorrect clock or transient settings")
    if (env["netlist_sha256"] != plan["netlist_sha256"]
            or not re.fullmatch("[0-9a-f]{64}", plan["netlist_sha256"] or "")):
        raise EvidenceError(f"{directory}: report and plan netlist hashes differ")
    job = env["remote"]
    match = {
        "design_lib": plan["design_lib"]["sha256"],
        "pex_lib": plan["pex_lib"]["sha256"],
        "models_lib": job["runner_models_lib_sha256"],
        "pdk_stamp": job["worker_environment"]["pdk"]["stamp_sha256"],
    }
    for name, value in match.items():
        if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
            raise EvidenceError(f"{directory}: missing or invalid {name} hash")
    build = env["engine_build"]["version_banner"]
    if (not build or not job["job_id"] or job["state"] != "done"
            or env["engine"] != "ngspice" or request["engine"] != "ngspice"):
        raise EvidenceError(f"{directory}: incomplete simulator or job provenance")
    match.update(engine_build=build, models=request["models"], ngspice_init=request["options"]["ngspice_init"],
                 save_mode=request["options"]["save_mode"])
    init_digest = checked_init_digest(directory, env, match["ngspice_init"])
    got = {m["name"]: m["value"] for m in c["measurements"] if m["status"] == "pass"}
    required = [f"{leg}_{rail}_{window}" for leg in ("s", "x")
                for rail in ("ir1", "ir2", "ir3", "ir4", "ib") for window in ("act", "rst")]
    if not short:
        required += ["s_ib_lo", "s_ib_hi", "x_ib_lo", "x_ib_hi"]
    for name in required:
        if got.get(name) is None or not math.isfinite(got[name]):
            raise EvidenceError(f"{directory}: missing or invalid measurement {name}")
    out = {"plan": plan, "match": match, "init_digest": init_digest, "job_id": job.get("job_id"), "state": job.get("state"),
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
        }
        if not short:
            out[leg]["half_delta_pp"] = ((got[f"{p}_ib_lo"] - got[f"{p}_ib_hi"])
                                         / abs(got[f"{p}_ib_act"]) * 100)
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
        tag = "m40C" if t < 0 else "125C"
        ts = fleet_run(SLUG / "corners" / f"ts20u-{tag}-1.98V", t, "20u")
        control_dir = SLUG / "corners" / f"ts100n-{tag}-1.98V"
        matched = None
        if (control_dir / "report.json").is_file():
            matched = fleet_run(control_dir, t, "100n")
            for key, value in ts["match"].items():
                if matched["match"][key] != value:
                    raise EvidenceError(f"{control_dir}: 100 ns and 20 us differ in {key}")
            if (ts["init_digest"] and matched["init_digest"]
                    and ts["init_digest"] != matched["init_digest"]):
                raise EvidenceError(f"{control_dir}: 100 ns and 20 us differ in effective ngspice_init")
        data[t] = {"ctrl": ctrl, "ts": ts, "matched": matched,
                   "anchor": anchor_delta_pp(ctrl, ts)}
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
    for t in TEMPS:
        historical = data[t]["ctrl"]["netlists"]
        plan = data[t]["ts"]["plan"]
        a(f"| Historical 100 ns, {t:+.0f} C | schematic `{historical['RO_RING5']['sha256'][:16]}`, "
          f"PEX `{historical['PEX_LIB']['sha256'][:16]}` | outputs unloaded | 100 ns | "
          "rst 50-250 ns, act 400-800 ns, step 5 ps |")
        a(f"| Fleet requests at {t:+.0f} C | schematic `{plan['design_lib']['sha256'][:16]}`, "
          f"PEX `{plan['pex_lib']['sha256'][:16]}` | outputs unloaded | 100 ns / 20 us | "
          "rst 50-250 ns, act 420-820 ns / 20.32-40.32 us, step 50 ps |")
    a("")
    a("Each deck contains both legs with their own buffers, XOR tree and samplers.")
    a("Section 1 reproduces the historical records. Section 3 uses only fleet pairs")
    a("with matching schematic, PEX and executed model hashes, simulator builds")
    a("and requested settings. Section 3 gives the runner evidence for ngspice initialization.")
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
    a("## 2. The Ts = 20 us measurements (this issue's batch experiment)")
    a("")
    a("At Ts = 20 us the first rising edge is at 320 ns and the clock duty is 49.8%.")
    a("W_RST covers 50-250 ns before the first edge. W_ACT covers 20.32-40.32 us,")
    a("one complete period between rising edges. The two half-window means show")
    a("phase-dependent current within that period. The plans record the transient")
    a("step and the enable and reset pulse widths.")
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
        a(f"Shared-VDD half-window spread: schematic "
          f"{ts['schematic']['half_delta_pp']:+.2f} %, extracted "
          f"{ts['extracted']['half_delta_pp']:+.2f} % of the leg's W_ACT mean.")
        a("")
    a("### Historical reset-window comparison (W_RST, 50-250 ns)")
    a("")
    a("These differences describe reset-held operation across extractions.")
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
    for t in TEMPS:
        ctrl = data[t]["matched"]
        source = f"job `{ctrl['job_id']}`" if ctrl else "awaiting fleet report"
        ts = data[t]["ts"]
        long_init = "verified" if ts["init_digest"] else "requested only"
        short_init = "pending"
        if ctrl:
            short_init = "verified" if ctrl["init_digest"] else "requested only"
        settings = ", ".join(f"`{line}`" for line in ts["match"]["ngspice_init"])
        a(f"- At {t:+.0f} C the 100 ns control is {source}. "
          f"Requested ngspice settings {settings} (100 ns {short_init}, 20 us {long_init}).")
    a("")
    a("The verdict uses the unrounded 20 us total. A total of exactly 500 uW fails.")
    a("Where a runner omits both init lines and digest, any clock-rate delta assumes")
    a("the runner applied the requested settings.")
    a("")
    a("| T | leg | Matched 100 ns total (uW) | 20 us total (uW) | delta | 20 us verdict vs 500 uW |")
    a("|---|---|---:|---:|---:|---|")
    for t in TEMPS:
        for leg in ("schematic", "extracted"):
            ctrl = data[t]["matched"]
            c20 = uw(data[t]["ts"][leg]["total_a"])
            verdict = "PASS" if c20 < TARGET_UW else "FAIL"
            fast, delta = "pending", "pending"
            if ctrl:
                c100 = uw(ctrl[leg]["total_a"])
                fast, delta = fmt(c100), f"{c20 - c100:+.1f}"
            a(f"| {t:+.0f} C | {leg} | {fast} | {fmt(c20)} | {delta} | {verdict} |")
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
