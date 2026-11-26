#!/usr/bin/env python3
"""Emit the Ts = 20 us sampler_core active-power klt sim requests (issue #604).

`sampler_core` analog active power exceeds the README's < 500 uW row at the
ff / 1.98 V corners (issue #604), but every committed post-layout
sampler_core measurement -- including the two ff control records this study
pairs with -- clocks the sampler at Ts = 100 ns, a disclosed compute-budget
deviation from DR-0003's Ts = 20 us operating point (DR-0003 is Proposed). Whether the
overrun survives the real sampling rate is unmeasured. This generator emits
the 20 us side of that comparison as `klt sim` batch requests (one per
failing temperature), so the grid runs on the Spot batch fleet -- never as a
hand-launched local ngspice grid.

Per request: ONE unit = the committed control deck's own two-leg circuit
(flat-extracted `sampler_core_pex` DUT `xarr` + pre-layout
`.subckt sampler_core` same-deck control `xctl`), netlists inlined verbatim
(sha256 in plan.json), with exactly three stimulus deviations from the
committed template, each recorded in plan.json's `deviations`:

1. `clk` period Ts = 20 us (high 9.96 us, the control's exact 49.8 % duty),
   first rising edge still at 320 ns.
2. `en1`-`en4` / `rst_n` PULSE widths extended past tstop (the template's
   1 us / 10 us high times would drop `en` at 1.005 us and `rst_n` at
   10.3 us -- mid-run -- at this tstop). Release instants (5 ns / 300 ns)
   are unchanged, so the reset-held anchor window below is bit-identical
   stimulus to the committed controls.
3. tstep 50p (template: 5p). Measured on this deck family at ff / -40 C /
   1.98 V over the control's own 400-800 ns window: active-current totals
   move -0.56 % (schematic leg) / -0.20 % (extracted leg); the fleet's
   whole-job ceiling (3600 s, fleet_config) does not admit the 5p deck at
   this tstop. The 20p whole-block convention halves the error but not the
   runtime gap.

Windows (see analysis/active-power-budget.md for the reduction):

* W_RST = 50-250 ns: rings running, samplers reset-held, clk not started.
  Stimulus-identical to the committed 100 ns controls' own W_RST -- the
  cross-runner anchor: its currents must reproduce the committed records
  (same netlists, same PVT) to within cross-build agreement before any
  20 us number is read.
* W_ACT = 20.32-40.32 us: exactly ONE complete settled clk period, edges at
  both endpoints (E2 = 320 ns + Ts, E3 = E2 + Ts). A two-period window
  (tstop 60.4 us) exceeds the fleet whole-job ceiling at the cold corner.
  Halves W_LO/W_HI subdivide it as a stationarity indicator only.
* Snapshot at 35.3 us: mid-low (opaque-slave) phase of the sampled period,
  the analogue of the control's 50 ns-into-low-phase captures.

Nothing here simulates anything. Reproduce the request directories with:

    python3 sim/post-layout-sampler-core/make-ts20u-requests.py \\
        sim/post-layout-sampler-core/corners --points both

Submit (batch fleet; blocking, capacity-waiting):

    klt sim --batch-set corners/ts20u-m40C-1.98V/request.json \\
                     corners/ts20u-125C-1.98V/request.json \\
        -o <outdir> --wait-for-capacity 600
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "layout" / "bin"))
from _hashing import sha256_file  # noqa: E402

DESIGN_LIB = REPO / "design" / "sampler_core.spice"
PEX_LIB = REPO / "layout" / "pex-sampler-core" / "sampler_core_pex.spice"
CONTROL_TEMPLATE = HERE / "testbench" / "tb_post_layout_sampler_core.spice"

PDK = "sky130A"
LIB = "libs.tech/combined/sky130.lib.spice"

VDD = 1.98
#: the two failing temperatures of issue #604's table (ff / 1.98 V)
POINTS = [(-40.0, "m40C"), (125.0, "125C")]

TSTEP = "50p"
TSTOP = "40.4u"
TSTOP_S = 40.4e-6
#: DR-0003's sampling period
TS_S = 20e-6
CLK_T0_S = 320e-9
CLK_HIGH_S = 9.96e-6  # 49.8 % duty, the control template's own ratio
EN_WIDTH_S = 50e-6    # > tstop: en never falls inside the run
RST_WIDTH_S = 50e-6   # > tstop: rst_n never re-asserts inside the run

#: windows (seconds). E2 = CLK_T0 + Ts, E3 = E2 + Ts.
W_RST = (50e-9, 250e-9)
W_ACT = (CLK_T0_S + TS_S, CLK_T0_S + 2 * TS_S)          # one complete period
W_LO = (W_ACT[0], W_ACT[0] + TS_S / 2)                  # stationarity halves
W_HI = (W_ACT[0] + TS_S / 2, W_ACT[1])
SNAP_S = 35.3e-6   # mid-low phase of the sampled period (low: 30.28-40.32 us)

#: whole-job ceiling is 3600 s (fleet_config); 3480 s + 120 s overhead fits.
UNIT_TIMEOUT_S = 3480
POLL_TIMEOUT_S = 3700

#: the committed 100 ns control records this study pairs with (issue #604's
#: curator table; ff rows, active window 400-800 ns)
CONTROL_RECORDS = [
    "sim/post-layout-sampler-core/records/20260908-050034-ef0db50.json",
    "sim/post-layout-sampler-core/records/20260908-053634-ef0db50.json",
]

DEVIATIONS = [
    {
        "what": "clk period",
        "control": "100n (49.8n high)",
        "here": f"{TS_S * 1e6:g}u ({CLK_HIGH_S * 1e6:g}u high), first edge 320n",
        "why": "DR-0003's Ts = 20 us operating point; the committed controls' "
               "disclosed compute-budget deviation removed",
    },
    {
        "what": "en1-en4 / rst_n PULSE widths",
        "control": "1u / 10u high",
        "here": "50u / 50u high",
        "why": "the control widths fall mid-run at this tstop; release "
               "instants (5n / 300n) unchanged so W_RST stimulus is "
               "bit-identical to the committed controls",
    },
    {
        "what": ".tran tstep",
        "control": "5p",
        "here": TSTEP,
        "why": "fleet whole-job ceiling 3600 s; measured on the control deck "
               "at ff/-40C/1.98V: -0.56 %/-0.20 % active-total shift "
               "(schematic/extracted leg) vs 5p",
    },
    {
        "what": "active window",
        "control": "400-800n (4 clk periods, 0.8-period phase offset)",
        "here": "20.32-40.32us (exactly 1 complete settled clk period)",
        "why": "a 2-period window (tstop 60.4us) exceeds the fleet "
               "whole-job ceiling at the cold corner; a period-exact "
               "average needs no phase offset",
    },
]


def _t(x: float) -> str:
    """Format a seconds value the way this deck family writes time tokens."""
    if x >= 1e-6 or x == round(x, 6):
        for div, suf in ((1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
            if x >= div:
                v = x / div
                return f"{v:.6g}{suf}"
    for div, suf in ((1e-9, "n"), (1e-12, "p")):
        if x >= div:
            return f"{x / div:.6g}{suf}"
    return f"{x:.6g}"


def deck_body() -> str:
    """The two-leg circuit body (no .lib/.temp/.tran/.meas/.control: klt owns those)."""
    design = DESIGN_LIB.read_text()
    pex = PEX_LIB.read_text()
    h = []
    a = h.append
    a("* sampler_core analog active power at DR-0003's Ts = 20 us -- issue")
    a("* #604's operating-point batch experiment. Derived from the committed")
    a("* same-deck control sim/post-layout-sampler-core/testbench/")
    a("* tb_post_layout_sampler_core.spice (see plan.json: three stimulus")
    a("* deviations, all recorded). Both legs of that deck are preserved")
    a("* verbatim below: xarr = the flat-extracted sampler_core_pex DUT over")
    a("* layout/sampler_core/, xctl = design/sampler_core.spice's own")
    a("* .subckt sampler_core pre-layout control, netlists inlined from the")
    a("* committed libraries (sha256 in plan.json). Windows: W_RST = 50-250n")
    a("* (stimulus-identical to the committed controls' reset-held window);")
    a("* W_ACT = 20.32u-40.32u = exactly one complete settled clk period")
    a("* (edges at both endpoints); halves at 30.32u are a stationarity")
    a("* indicator. Snapshot at 35.3u = mid-low opaque-slave phase. klt sim")
    a("* appends .lib/.temp/.tran and the .meas cards from request.json;")
    a("* this body carries none of them.")
    a(".option scale=1u")
    a("")
    a("* ---- committed pre-layout library (design/sampler_core.spice) ----")
    h.extend(l.rstrip() for l in design.splitlines())
    a("")
    a("* ---- committed post-layout library (sampler_core_pex) ----")
    h.extend(l.rstrip() for l in pex.splitlines())
    a("")
    a("* ---- substrate return node: hard tie (control deck's own choice) ---")
    a("Vsub vsubs 0 dc 0")
    a("")
    a("* ---- post-layout WHOLE CELL (extracted leg, prefix p) --------------")
    for i in (1, 2, 3, 4):
        a(f"Vddrp{i} pvddr{i} 0 dc {VDD}")
    a(f"Vddp pvdd 0 dc {VDD}")
    for i in (1, 2, 3, 4):
        a(f"Venp{i} pen{i} 0 PULSE(0 {VDD} 5n 100p 100p {_t(EN_WIDTH_S)} {_t(2 * EN_WIDTH_S)})")
    a(f"Vrstnp prst_n 0 PULSE(0 {VDD} 300n 100p 100p {_t(RST_WIDTH_S)} {_t(2 * RST_WIDTH_S)})")
    a(f"Vclkp pclk 0 PULSE(0 {VDD} {_t(CLK_T0_S)} 100p 100p {_t(CLK_HIGH_S)} {_t(TS_S)})")
    a("xarr pen1 pen2 pen3 pen4 pvddr1 pvddr2 pvddr3 pvddr4 pvdd 0 pclk prst_n")
    a("+ praw_bit praw_valid pring_bit1 pring_bit2 pring_bit3 pring_bit4")
    a("+ sampler_core_pex")
    a("")
    a("* ---- pre-layout control (schematic leg, prefix-free) ---------------")
    for i in (1, 2, 3, 4):
        a(f"Vddr{i} vddr{i} 0 dc {VDD}")
    a(f"Vdd vdd 0 dc {VDD}")
    for i in (1, 2, 3, 4):
        a(f"Ven{i} en{i} 0 PULSE(0 {VDD} 5n 100p 100p {_t(EN_WIDTH_S)} {_t(2 * EN_WIDTH_S)})")
    a(f"Vrstn rst_n 0 PULSE(0 {VDD} 300n 100p 100p {_t(RST_WIDTH_S)} {_t(2 * RST_WIDTH_S)})")
    a(f"Vclk clk 0 PULSE(0 {VDD} {_t(CLK_T0_S)} 100p 100p {_t(CLK_HIGH_S)} {_t(TS_S)})")
    a("xctl en1 en2 en3 en4 vddr1 vddr2 vddr3 vddr4 vdd 0 clk rst_n")
    a("+ raw_bit raw_valid ring_bit1 ring_bit2 ring_bit3 ring_bit4")
    a("+ sampler_core")
    a("")
    a("* ---- ring start-up states (control deck's own .ic set) -------------")
    a(".ic v(xarr.ro1)=0 v(xarr.ro2)=0 v(xarr.ro3)=0 v(xarr.ro4)=0")
    a(".ic v(xctl.ro1)=0 v(xctl.ro2)=0 v(xctl.ro3)=0 v(xctl.ro4)=0")
    a("")
    a("* ---- saved trace set: exactly the .meas inputs (control deck's own")
    a("* ---- memory requirement; save_mode netlist in the request) ---------")
    a(".save v(xarr.ro1) v(xarr.ro2) v(xarr.ro3) v(xarr.ro4) v(xarr.xo)")
    a(".save v(xctl.ro1) v(xctl.ro2) v(xctl.ro3) v(xctl.ro4) v(xctl.xo)")
    a(".save v(praw_bit) v(praw_valid) v(pring_bit1) v(pring_bit2) v(pring_bit3) v(pring_bit4)")
    a(".save v(raw_bit) v(raw_valid) v(ring_bit1) v(ring_bit2) v(ring_bit3) v(ring_bit4)")
    a(".save i(Vddrp1) i(Vddrp2) i(Vddrp3) i(Vddrp4) i(Vddp)")
    a(".save i(Vddr1) i(Vddr2) i(Vddr3) i(Vddr4) i(Vdd)")
    return "\n".join(h) + "\n"


def measurements() -> list[dict]:
    """The request's measurements[] entries (plain {name, spice} .meas cards)."""
    meas: list[dict] = []

    def avg(name: str, expr: str, w: tuple[float, float], unit: str = "A"):
        meas.append({"name": name, "unit": unit,
                     "spice": f".meas tran {name} AVG {expr} FROM={_t(w[0])} TO={_t(w[1])}"})

    legs = {
        "x": dict(rails=[f"Vddrp{i}" for i in (1, 2, 3, 4)], blk="Vddp", dut="xarr",
                  outs=("praw_bit", "praw_valid", "pring_bit1", "pring_bit2",
                        "pring_bit3", "pring_bit4")),
        "s": dict(rails=[f"Vddr{i}" for i in (1, 2, 3, 4)], blk="Vdd", dut="xctl",
                  outs=("raw_bit", "raw_valid", "ring_bit1", "ring_bit2",
                        "ring_bit3", "ring_bit4")),
    }
    for p, L in legs.items():
        for i, rail in enumerate(L["rails"], 1):
            avg(f"{p}_ir{i}_rst", f"i({rail})", W_RST)
            avg(f"{p}_ir{i}_act", f"i({rail})", W_ACT)
            avg(f"{p}_ir{i}_lo", f"i({rail})", W_LO)
            avg(f"{p}_ir{i}_hi", f"i({rail})", W_HI)
        avg(f"{p}_ib_rst", f"i({L['blk']})", W_RST)
        avg(f"{p}_ib_act", f"i({L['blk']})", W_ACT)
        avg(f"{p}_ib_lo", f"i({L['blk']})", W_LO)
        avg(f"{p}_ib_hi", f"i({L['blk']})", W_HI)
        # ring periods, the control deck's own estimator (rise=3/rise=13)
        for i in (1, 2, 3, 4):
            for tag, rise in (("a", 3), ("b", 13)):
                meas.append({
                    "name": f"{p}_r{i}{tag}", "unit": "s",
                    "spice": f".meas tran {p}_r{i}{tag} when v({L['dut']}.ro{i})"
                             f"={0.5 * VDD:.6g} rise={rise}"})
        # combining-node swing / bias over the settled span
        for tag, kind in (("max", "MAX"), ("min", "MIN"), ("avg", "AVG")):
            meas.append({
                "name": f"{p}_xo_{tag}", "unit": "V",
                "spice": f".meas tran {p}_xo_{tag} {kind} v({L['dut']}.xo)"
                         f" FROM={_t(100e-9)} TO={TSTOP}"})
        # captured-value snapshot: mid-low opaque-slave phase of the sampled period
        for out in L["outs"]:
            meas.append({
                "name": f"{p}_snap_{'_'.join(out.split('_')[1:]) or out}",
                "unit": "V",
                "spice": f".meas tran {p}_snap_{'_'.join(out.split('_')[1:]) or out}"
                         f" FIND v({out}) AT={_t(SNAP_S)}"})
    # every card's window must sit inside the analysis
    for m in meas:
        for tok in m["spice"].replace("=", " ").split():
            pass  # (structural check lives in the unit test)
    return meas


def make_request(outdir: Path, temp_c: float) -> dict:
    body = deck_body()
    meas = measurements()
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "netlist.cir").write_text(body)
    request = {
        "netlist": "netlist.cir",
        "engine": "ngspice",
        "backend": "batch",
        "netlist_source": "extracted",
        "models": {"pdk": PDK, "lib": LIB},
        "corners": {
            "process": ["ff"],
            "temperature_c": [temp_c],
            "supply_v": {n: [VDD] for n in
                         (*[f"Vddrp{i}" for i in (1, 2, 3, 4)], "Vddp",
                           *[f"Vddr{i}" for i in (1, 2, 3, 4)], "Vdd")},
        },
        "analysis": {"kind": "tran", "args": f"{TSTEP} {TSTOP} uic"},
        "measurements": meas,
        "options": {"timeout_s": UNIT_TIMEOUT_S, "keep_artifacts": True,
                    "save_mode": "netlist",
                    "ngspice_init": ["set measureprec=12", "set numdgt=12"]},
        "batch": {"poll_timeout_s": POLL_TIMEOUT_S},
    }
    (outdir / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    plan = {
        "name": outdir.name,
        "purpose": "issue #604: sampler_core analog active power at DR-0003's "
                   "Ts = 20 us, ff / 1.98 V -- the 20 us leg of the "
                   "100 ns-vs-20 us sampling-rate comparison",
        "netlist_sha256": sha256_file(outdir / "netlist.cir"),
        "design_lib": {"path": str(DESIGN_LIB.relative_to(REPO)),
                       "sha256": sha256_file(DESIGN_LIB)},
        "pex_lib": {"path": str(PEX_LIB.relative_to(REPO)),
                    "sha256": sha256_file(PEX_LIB)},
        "control_template": {"path": str(CONTROL_TEMPLATE.relative_to(REPO)),
                             "sha256": sha256_file(CONTROL_TEMPLATE)},
        "control_records_paired": CONTROL_RECORDS,
        "timing": {"ts_s": TS_S, "clk_t0_s": CLK_T0_S,
                   "clk_high_s": CLK_HIGH_S, "duty": CLK_HIGH_S / TS_S,
                   "en_release_s": 5e-9, "rst_release_s": 300e-9,
                   "en_width_s": EN_WIDTH_S, "rst_width_s": RST_WIDTH_S,
                   "tstep": TSTEP, "tstop": TSTOP, "uic": True},
        "windows": {"w_rst_s": list(W_RST), "w_act_s": list(W_ACT),
                    "w_lo_s": list(W_LO), "w_hi_s": list(W_HI),
                    "snapshot_s": SNAP_S},
        "deviations": DEVIATIONS,
        "analysis": request["analysis"],
        "corners": request["corners"],
        "measurement_count": len(meas),
        "fleet": {"unit_timeout_s": UNIT_TIMEOUT_S,
                  "poll_timeout_s": POLL_TIMEOUT_S,
                  "whole_job_ceiling_s": 3600,
                  "submit": "klt sim --batch-set <both request.json> -o <dir> "
                            "--wait-for-capacity 600"},
    }
    (outdir / "plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n")
    return request


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir", type=Path,
                    help="output directory (usually sim/post-layout-sampler-core/corners)")
    ap.add_argument("--points", choices=("both", "m40", "hot"), default="both",
                    help="which failing temperatures to emit (default both)")
    args = ap.parse_args(argv)
    sel = {"m40": [POINTS[0]], "hot": [POINTS[1]], "both": POINTS}[args.points]
    for temp_c, tag in sel:
        req = make_request(args.outdir / f"ts20u-{tag}-1.98V", temp_c)
        print(f"wrote {args.outdir / f'ts20u-{tag}-1.98V'} "
              f"({req['corners']['temperature_c'][0]:+g} C, "
              f"{len(req['measurements'])} measurements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
