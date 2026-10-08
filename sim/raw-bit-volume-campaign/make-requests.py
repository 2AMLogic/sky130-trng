#!/usr/bin/env python3
"""Generate `klt sim` batch requests for the transistor-level cross-check leg of
the raw-bit volume campaign (issue #188).

Each request re-runs the #21 testbench (sim/raw-bit-min-entropy/testbench/
tb_raw_bit_stream.spice, unmodified, Ts = 100 ns, 24 bits) at tt/ss/ff, 27 degC,
1.8 V, with ONE distinct noise seed per request. Independent seeds give
independent noise trajectories, so the pooled transistor-level p_hat has a
honest binomial SE (the #21 record had a single seed per corner).

    make-requests.py OUTDIR [--seeds 101,102,...]
    # writes OUTDIR/s<SEED>/{netlist.cir,request.json}
    klt sim OUTDIR/s<SEED>/request.json -o OUTDIR/s<SEED>/out --format json > OUTDIR/s<SEED>/resp.json

The grid is never hand-launched with ngspice: it goes to the batch backend.
Derivation mirrors sim/post-layout-ro-ring5-assembled-181/make-requests.py.
"""
import argparse, json, os, re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TB = os.path.join(REPO, "sim/raw-bit-min-entropy/testbench/tb_raw_bit_stream.spice")
SAMPLER = os.path.join(REPO, "design/sampler_core.spice")
TEMP, VDD, TMAX, NA = 27.0, 1.8, "40p", "2.0e-3"
NBITS, TS_NS = 24, 100
LIB = "libs.tech/combined/sky130.lib.spice"
DEFAULT_SEEDS = [101, 102, 103, 104, 105, 106, 107, 108]


def build(seed):
    text = open(TB).read()
    for k, v in {"@@VDD@@": repr(VDD), "@@TEMP@@": repr(TEMP), "@@TMAX@@": TMAX,
                 "@@RO_RING5@@": SAMPLER, "@@SEED@@": str(seed), "@@NA@@": NA}.items():
        text = text.replace(k, v)
    head, in_ctl = [], False
    for line in text.splitlines():
        low = line.strip().lower()
        if low == ".control":
            in_ctl = True
        elif low == ".endc":
            in_ctl = False
        elif not in_ctl:
            head.append(line)
    body = []
    for line in head:
        low = line.strip().lower()
        if low.startswith((".lib", ".temp", ".tran", ".save", ".end")):
            continue
        body.append(line)
    meas = []
    for k in range(NBITS):
        t = k * TS_NS * 1e-9 + 0.25 * TS_NS * 1e-9
        meas.append({"name": f"bit{k}", "spice": f".meas tran bit{k} find v(raw_bit) at={t:.6g}"})
        meas.append({"name": f"valid{k}", "spice": f".meas tran valid{k} find v(raw_valid) at={t:.6g}"})
    meas.append({"name": "ro1_max", "spice": ".meas tran ro1_max MAX v(ro1) from=1u to=2.5u"})
    meas.append({"name": "ro1_min", "spice": ".meas tran ro1_min MIN v(ro1) from=1u to=2.5u"})
    return "\n".join(body) + "\n", meas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    a = ap.parse_args()
    for seed in [int(s) for s in a.seeds.split(",")]:
        body, meas = build(seed)
        d = os.path.join(a.outdir, f"s{seed}")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "netlist.cir"), "w").write(body)
        req = {
            "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
            "netlist_source": "extracted",
            "models": {"pdk": "sky130A", "lib": LIB},
            "corners": {"process": ["tt", "ss", "ff"], "temperature_c": [TEMP]},
            "analysis": {"kind": "tran", "args": f"{TMAX} 2.5u uic"},
            "measurements": meas,
            "options": {"timeout_s": 3000, "keep_artifacts": False},
        }
        json.dump(req, open(os.path.join(d, "request.json"), "w"), indent=2)
        print(d, f"seed={seed}", len(meas), "measurements")


if __name__ == "__main__":
    main()
