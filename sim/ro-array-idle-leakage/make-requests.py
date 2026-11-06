#!/usr/bin/env python3
"""Generate the `klt sim` requests for the idle / leakage survey (issue #201).

    make-requests.py OUTDIR [--probe]
    # writes OUTDIR/<name>/{netlist.cir,request.json,plan.json}
    klt sim OUTDIR/<name>/request.json -o OUTDIR/<name>/out --format json > OUTDIR/<name>/resp.json

The grid is never hand-launched with ngspice: it is `klt sim` corners requests,
which go to the batch fleet (KLT_SIM_BACKEND=batch). `--probe` writes ONE
single-unit request (ss / -40 C / 1.62 V ... see PROBE) for a local debug run
(`klt sim --backend local`).

Grid (DR-0001 envelope, spec/porting-plan.md sec. 3.1 flagship grid):
    process      tt, ss, ff           one request each (corners.process is a list,
                                      but one request per process keeps units small)
    temperature  -40, 27, 125 degC    corners.temperature_c
    supply       1.62, 1.8, 1.98 V    knob Vk, corners.supply_v
= 27 units for the assembled block (`idle`), plus the same 27 for the leaf-cell
sum (`leaf`).  analysis.kind = "op"; the currents are `expr` measurements
(a `.meas` card cannot search an op).
"""
import argparse, json, os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLER = os.path.join(REPO, "design", "sampler_core.spice")
LIB = "libs.tech/combined/sky130.lib.spice"

PROCESSES = ["tt", "ss", "ff"]
TEMPS = [-40.0, 27.0, 125.0]
SUPPLIES = [1.62, 1.8, 1.98]
PROBE = ("tt", 27.0, 1.8)

# The fleet kills a job whose bound (klt per-job overhead + units-per-job x timeout_s) exceeds its 3600 s
# ceiling. A unit is one ~30 s `.op` (mostly model parse); 9 units per job x 300 s + 120 s overhead = 2820 s.
FLEET_CEILING_S = 3600
BATCH_JOB_OVERHEAD_S = 120
MAX_UNITS_PER_JOB = 9
TIMEOUT_S = 300
assert BATCH_JOB_OVERHEAD_S + MAX_UNITS_PER_JOB * TIMEOUT_S <= FLEET_CEILING_S

RAILS = {"idle": ["vdd", "r1", "r2", "r3", "r4"], "leaf": ["vdd", "r1", "r2", "r3", "r4"]}
SENSE = {"vdd": "Vsvdd", "r1": "Vsr1", "r2": "Vsr2", "r3": "Vsr3", "r4": "Vsr4"}
# leg -> (testbench file, extra state probes (assembled deck only))
LEGS = {"idle": "tb_idle.spice", "leaf": "tb_idle_leaf.spice"}
CLAMPS = {"idle": ["xsb", "xsv", "xsr1", "xsr2", "xsr3", "xsr4"], "leaf": ["xsb", "xsv", "xs1", "xs2", "xs3", "xs4"]}
CLAMP_SRC = {"xsb": "Bcl_xsb", "xsv": "Vcl_xsv"}      # every other flip-flop is a d = 0 (high-s) clamp: Bcl_<inst>
PROBES = {"idle": [("v_xo", "v(xdut.xo)"), ("v_ro1", "v(xdut.ro1)"), ("v_rn1", "v(xdut.xdut.rn1)")], "leaf": []}


def measurements(leg):
    # i(V) is the current flowing from the source's + node (the supply) into the circuit, so it is
    # already the delivered supply current (positive = drawn from the supply)
    m = [{"name": f"i_{r}", "expr": f"i({SENSE[r]})"} for r in RAILS[leg]]
    m += [{"name": n, "expr": e} for n, e in PROBES[leg]]
    # current each latch clamp supplies (~0 when the clamp sits on the true stable state), and the latch node itself
    for inst in CLAMPS[leg]:
        src = "Vcl_" + inst if inst == "xsv" else "Bcl_" + inst
        node = ("xdut." if leg == "idle" else "") + inst + ".s"
        m.append({"name": f"i_cl_{inst}", "expr": f"i({src})"})
        m.append({"name": f"v_s_{inst}", "expr": f"v({node})"})
    return m


def body(leg):
    t = open(os.path.join(HERE, "testbench", LEGS[leg])).read()
    return t.replace("@@SAMPLER@@", SAMPLER)


def request(proc, temps, sups, leg):
    return {
        "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
        "netlist_source": "extracted",
        "models": {"pdk": "sky130A", "lib": LIB},
        "corners": {"process": [proc], "temperature_c": temps, "supply_v": {"Vk": sups}},
        "analysis": {"kind": "op", "args": ""},
        "measurements": measurements(leg),
        "options": {"timeout_s": TIMEOUT_S, "keep_artifacts": False},
        "batch": {"capacity_wait_s": 3600, "max_units_per_job": MAX_UNITS_PER_JOB, "max_concurrent_jobs": 2},
    }


def write(outdir, name, leg, req, plan):
    d = os.path.join(outdir, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "netlist.cir"), "w").write(body(leg))
    json.dump(req, open(os.path.join(d, "request.json"), "w"), indent=2)
    json.dump(plan, open(os.path.join(d, "plan.json"), "w"), indent=2)
    print(d, req["corners"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--probe", action="store_true", help="one single-unit request per leg (local debug)")
    a = ap.parse_args()
    for leg in LEGS:
        procs = [PROBE[0]] if a.probe else PROCESSES
        temps = [PROBE[1]] if a.probe else TEMPS
        sups = [PROBE[2]] if a.probe else SUPPLIES
        for proc in procs:
            plan = {"leg": leg, "process": proc, "temps": temps, "supplies": sups, "rails": RAILS[leg],
                    "testbench": f"testbench/{LEGS[leg]}"}
            write(a.outdir, f"{leg}-{proc}" + ("-probe" if a.probe else ""), leg,
                  request(proc, temps, sups, leg), plan)


if __name__ == "__main__":
    main()
