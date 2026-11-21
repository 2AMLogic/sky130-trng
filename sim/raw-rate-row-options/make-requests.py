#!/usr/bin/env python3
"""Generate the `klt sim` batch requests for the raw-rate-row options study (issue #600).

    make-requests.py REQDIR
    # writes REQDIR/<config>-<temp>C-<vdd>V/{netlist.cir,request.json,plan.json}
    uvx --from "klayout-tools==0.8.0" klt sim REQDIR/<d>/request.json \\
        -o REQDIR/<d>/out --format json > REQDIR/<d>/resp.json

The 15-unit matrix is never hand-launched with ngspice: it is five `klt sim`
corner requests, each carrying the tt/ss/ff process axis as three units, which
go to the batch fleet (KLT_SIM_BACKEND=batch). design/ is read, never written.

Configurations
--------------
    ctrl5  the committed 5-stage jitter vehicle (ro_nand2 + 4 ro_stage) at
           -40 C / 1.62 V x {tt,ss,ff} -- the baseline control against
           committed record 20260825-060208-54f5715.
    ring3  the 3-inversion ring (ro_nand2 + 2 ro_stage) at DR-0002's three
           headline (T, V) points plus the 125 C / 1.98 V swing-risk point,
           each x {tt,ss,ff}.

The ring bodies, initial conditions, trnoise calibration (NA=2.0e-3,
NT=2e-10), seed (1), timestep (20p) and tstop (115n) replicate the committed
campaign deck sim/ro-ring-jitter-accumulation/testbench/tb_ro_ring5_jitter.spice
exactly; see the template header for the two klt-forced differences.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TB_JITTER = os.path.join(HERE, "testbench", "tb_ring_jitter_klt.spice")
TB_SC = os.path.join(HERE, "testbench", "tb_ring_swing_current_klt.spice")
DESIGN_JITTER = os.path.join(REPO, "design", "ro_ring5.spice")
DESIGN_SC = os.path.join(REPO, "design", "ro_array_core.spice")

PROCESSES = ["tt", "ss", "ff"]
# ctrl5 runs at the committed control record's single (T, V); ring3 covers
# DR-0002's three headline points (binding / nominal / fastest) plus the
# 125 C swing-risk corner (ro_ring5's own worst-swing point in the committed
# 27-point grid was ff / 125 C / 1.98 V). The swing/current configs (sc5
# control, sc3) run at the committed ro-ring5-swing-and-current grid's own
# four (T, V) points.
JITTER_POINTS = {
    "ctrl5": [(-40.0, 1.62)],
    "ring3": [(-40.0, 1.62), (27.0, 1.80), (-40.0, 1.98), (125.0, 1.98)],
}
SC_POINTS = [(-40.0, 1.62), (27.0, 1.80), (-40.0, 1.98), (125.0, 1.98)]
TMAX_J = "20p"
TMAX_SC = "5p"
TSTOP_J = "115n"
TSTOP_SC = "80n"
NA = "2.0e-3"
NT = "2e-10"

RING_BODIES = {
    "ctrl5": """\
xg gA en n1 vddr 0 ro_nand2
VnA gA ro dc 0 trnoise(%s %s 0 0)
x1 gB n2 vddr 0 ro_stage
VnB gB n1 dc 0 trnoise(%s %s 0 0)
x2 gC n3 vddr 0 ro_stage
VnC gC n2 dc 0 trnoise(%s %s 0 0)
x3 gD n4 vddr 0 ro_stage
VnD gD n3 dc 0 trnoise(%s %s 0 0)
x4 gE ro vddr 0 ro_stage
VnE gE n4 dc 0 trnoise(%s %s 0 0)""" % ((NA, NT) * 5),
    "ring3": """\
xg gA en n1 vddr 0 ro_nand2
VnA gA ro dc 0 trnoise(%s %s 0 0)
x1 gB n2 vddr 0 ro_stage
VnB gB n1 dc 0 trnoise(%s %s 0 0)
x2 gC ro vddr 0 ro_stage
VnC gC n2 dc 0 trnoise(%s %s 0 0)""" % ((NA, NT) * 3),
}

# The committed deck's .ic pattern: alternate 0 / Vdd around the loop
# starting from ro = 0 (v(ro)=0, v(n1)=V, v(n2)=0, ...). Mirrored per config.
def ic_card(config, vdd):
    nodes = ["ro", "n1", "n2", "n3", "n4"][: 1 + {"ctrl5": 4, "ring3": 2}[config]]
    return " ".join(f"v({nm})={vdd if i % 2 else 0}" for i, nm in enumerate(nodes))


def measurements(vthr):
    """21 rising-crossing times (tc2..tc22) + steady-state swing extremes.

    tc<k> replicates the committed `.control` loop's `meas tran tk when
    v(ro)=0.5*VDD rise=$&k` for k = 2..22; vmax/vmin replicate its 20n..115n
    window. tbar / sigma_1..8 are recomputed from tc2..tc22 by reduce.py.
    """
    ms = [
        {"name": f"tc{k}", "spice": f".meas tran tc{k} when v(ro)={vthr} rise={k}"}
        for k in range(2, 23)
    ]
    ms += [
        {"name": "vmax_ss", "spice": ".meas tran vmax_ss max v(ro) from=20n to=115n"},
        {"name": "vmin_ss", "spice": ".meas tran vmin_ss min v(ro) from=20n to=115n"},
    ]
    return ms


def sc_ring_bodies(stages):
    """Instance lines for the swing/current deck's running (A) and stopped (B)
    rings: `stages` inverting elements = 1 ro_nand2 + (stages-1) ro_stage, the
    committed deck's explicit wstv/lstv/cld parameters included."""
    lines_a = ["xgA roA enA a1 vddrA 0 ro_nand2 wstv=0.42 lstv=2 cld=0.5f"]
    for i in range(1, stages - 1):
        lines_a.append(f"x{i}A a{i} a{i+1} vddrA 0 ro_stage wstv=0.42 lstv=2 cld=0.5f")
    lines_a.append(f"x{stages-1}A a{stages-1} roA vddrA 0 ro_stage wstv=0.42 lstv=2 cld=0.5f")
    lines_b = ["xgB roB enB b1 vddrB 0 ro_nand2 wstv=0.42 lstv=2 cld=0.5f"]
    for i in range(1, stages - 1):
        lines_b.append(f"x{i}B b{i} b{i+1} vddrB 0 ro_stage wstv=0.42 lstv=2 cld=0.5f")
    lines_b.append(f"x{stages-1}B b{stages-1} roB vddrB 0 ro_stage wstv=0.42 lstv=2 cld=0.5f")
    return "\n".join(lines_a), "\n".join(lines_b)


def sc_measurements(vthr):
    """The committed swing/current deck's `.control` block as `.meas` cards:
    ring/buffer swing extremes, tc3/tc11 (period), tfall3/tc4 (duty), and the
    three AVG supply currents (sign-flipped by reduce.py, as committed)."""
    return [
        {"name": "vmax_ring", "spice": ".meas tran vmax_ring max v(roA) from=20n to=80n"},
        {"name": "vmin_ring", "spice": ".meas tran vmin_ring min v(roA) from=20n to=80n"},
        {"name": "vmax_buf", "spice": ".meas tran vmax_buf max v(robA) from=20n to=80n"},
        {"name": "vmin_buf", "spice": ".meas tran vmin_buf min v(robA) from=20n to=80n"},
        {"name": "tc3", "spice": f".meas tran tc3 when v(roA)={vthr} rise=3"},
        {"name": "tc11", "spice": f".meas tran tc11 when v(roA)={vthr} rise=11"},
        {"name": "tfall3", "spice": f".meas tran tfall3 when v(roA)={vthr} fall=3"},
        {"name": "tc4", "spice": f".meas tran tc4 when v(roA)={vthr} rise=4"},
        {"name": "iddr_run", "spice": ".meas tran iddr_run avg i(VddrA) from=20n to=80n"},
        {"name": "iddr_stop", "spice": ".meas tran iddr_stop avg i(VddrB) from=20n to=80n"},
        {"name": "ibuf", "spice": ".meas tran ibuf avg i(Vdd) from=20n to=80n"},
    ]


def build_deck(config, vdd):
    if config in ("ctrl5", "ring3"):
        design_path, tb_path = DESIGN_JITTER, TB_JITTER
        ring = RING_BODIES[config]
        ringa = ringb = ic = None
    else:
        design_path, tb_path = DESIGN_SC, TB_SC
        stages = 5 if config == "sc5" else 3
        ringa, ringb = sc_ring_bodies(stages)
        ring = None
        nodes = ["roA"] + [f"a{i}" for i in range(1, stages)]
        ic = " ".join(f"v({nm})={vdd if i % 2 else 0}" for i, nm in enumerate(nodes))
    with open(design_path) as fh:
        design = fh.read()
    with open(tb_path) as fh:
        tb = fh.read()
    subs = [("@@DESIGN@@", design), ("@@VDD@@", f"{vdd:.2f}")]
    if ring is not None:
        subs += [("@@RING@@", ring), ("@@IC@@", ic_card(config, f"{vdd:.2f}"))]
    else:
        subs += [("@@RINGA@@", ringa), ("@@RINGB@@", ringb), ("@@IC@@", ic)]
    for token, value in subs:
        if token not in tb:
            raise SystemExit(f"error: token {token} missing from template")
        tb = tb.replace(token, value)
    leftovers = re.findall(r"@@[A-Z0-9_]+@@", tb)
    if leftovers:
        raise SystemExit(f"error: unsubstituted tokens {sorted(set(leftovers))}")
    return tb


def request_for(config, temp, vdd):
    if config in ("ctrl5", "ring3"):
        args = f"{TMAX_J} {TSTOP_J} uic"
        meas = measurements(f"{0.5 * vdd:.6g}")
        pvt_extra = {"na": NA, "seed": 1}
    else:
        args = f"{TMAX_SC} {TSTOP_SC} uic"
        meas = sc_measurements(f"{0.5 * vdd:.6g}")
        pvt_extra = {"deterministic": True}
    return {
        "netlist": "netlist.cir",
        "engine": "ngspice",
        "backend": "batch",
        "netlist_source": "extracted",
        "models": {
            "pdk": "sky130A",
            "lib": "libs.tech/combined/sky130.lib.spice",
        },
        "corners": {"process": PROCESSES, "temperature_c": [temp]},
        "analysis": {"kind": "tran", "args": args},
        "measurements": meas,
        "options": {"timeout_s": 3000, "keep_artifacts": False},
    }, pvt_extra


WHY_JITTER = {
    (-40.0, 1.62): "DR-0002 entropy-binding corner (control point of "
                   "committed record 20260825-060208-54f5715; ring3 "
                   "re-derives Q at its own binding corner)",
    (27.0, 1.80): "nominal headline point",
    (-40.0, 1.98): "fastest committed ring5 corner; N_max_combine binds here",
    (125.0, 1.98): "ro_ring5's own worst-swing corner in the committed "
                   "grid -- the 3-stage swing re-check DR-0002 Sec 2 requires",
}
WHY_SC = {
    "sc5": "committed ro-ring5-swing-and-current grid point re-run: the "
           "deterministic baseline control (loaded tbar, i_ring_run, i_buf, "
           "swing fractions)",
    "sc3": "the same measurement on the 3-inversion ring: its own loaded "
           "period, per-ring supply current, and buffered-output swing "
           "(DR-0002 Sec 2's open question below five stages)",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir")
    args = ap.parse_args(argv)

    jobs = 0
    requests = 0
    families = [(cfg, pts) for cfg, pts in JITTER_POINTS.items()]
    families += [("sc5", SC_POINTS), ("sc3", SC_POINTS)]
    for config, points in families:
        for (temp, vdd) in points:
            name = "%s-%gC-%gV" % (config, temp, vdd)
            d = os.path.join(args.outdir, name)
            os.makedirs(d, exist_ok=True)
            deck = build_deck(config, vdd)
            with open(os.path.join(d, "netlist.cir"), "w") as fh:
                fh.write(deck)
            request, pvt_extra = request_for(config, temp, vdd)
            with open(os.path.join(d, "request.json"), "w") as fh:
                json.dump(request, fh, indent=1, sort_keys=True)
                fh.write("\n")
            plan = {
                "config": config,
                "pvt": {"temp": temp, "vnom": vdd,
                        "tmax": TMAX_J if config in ("ctrl5", "ring3") else TMAX_SC,
                        "stop": TSTOP_J if config in ("ctrl5", "ring3") else TSTOP_SC,
                        **pvt_extra},
                "n": len(PROCESSES),
                "why": WHY_JITTER[(temp, vdd)] if config in ("ctrl5", "ring3")
                       else WHY_SC[config] + f" ({temp:g} C / {vdd:g} V)",
            }
            with open(os.path.join(d, "plan.json"), "w") as fh:
                json.dump(plan, fh, indent=1, sort_keys=True)
                fh.write("\n")
            requests += 1
            jobs += len(PROCESSES)
            print(name)
    expected = (sum(len(p) for p in JITTER_POINTS.values()) + 2 * len(SC_POINTS)) * len(PROCESSES)
    if jobs != expected:
        raise SystemExit(f"error: wrote {jobs} jobs, expected {expected}")
    print(f"{requests} requests, {jobs} jobs (process axis per request)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
