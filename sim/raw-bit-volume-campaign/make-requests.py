#!/usr/bin/env python3
"""Generate `klt sim` batch requests for the transistor-level cross-check leg of
the raw-bit volume campaign (issue #188).

Each request re-runs the #21 testbench (sim/raw-bit-min-entropy/testbench/
tb_raw_bit_stream.spice, unmodified, Ts = 100 ns, 24 bits) at tt/ss/ff, 27 degC,
1.8 V, with ONE distinct noise seed per request. Independent seeds give
independent noise trajectories, so the pooled transistor-level p_hat has a
honest binomial SE (the #21 record had a single seed per corner).

    make-requests.py OUTDIR [--seeds 101,102,...]            # raw-bit cross-check (default)
    make-requests.py OUTDIR --pvt -40:1.62,125:1.8 --seeds 101,102,103,104   # issue #289
    make-requests.py OUTDIR --deck combining [--points 125:1.62,125:1.8,125:1.98]
    # writes OUTDIR/s<SEED>/{netlist.cir,request.json}
    klt sim OUTDIR/s<SEED>/request.json -o OUTDIR/s<SEED>/out --format json > OUTDIR/s<SEED>/resp.json

The grid is never hand-launched with ngspice: it goes to the batch backend.
`--deck combining` (issue #197) instead derives, mechanically and with the deck
unmodified, one request per (temperature, supply) point from
sim/ro-array-core-combining/testbench/tb_ro_array_core.spice, tt/ss/ff bundled
per request, to fill the 125 C combining-calibration gap. The deck's `let`
figures are recomputed by derive-combining.py (klt sim `expr` cannot read
top-level .meas results, see sim/post-layout-ro-ring5-assembled-181/).

Derivation mirrors sim/post-layout-ro-ring5-assembled-181/make-requests.py.
"""
import argparse, hashlib, json, os, re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TB = os.path.join(REPO, "sim/raw-bit-min-entropy/testbench/tb_raw_bit_stream.spice")
SAMPLER = os.path.join(REPO, "design/sampler_core.spice")
TEMP, VDD, TMAX, NA = 27.0, 1.8, "40p", "2.0e-3"
NBITS, TS_NS = 24, 100
DEFAULT_PVT = "-40:1.62,-40:1.98,125:1.62,125:1.8,125:1.98"   # calibrated non-nominal set (issue #289)
COMB_TB = os.path.join(REPO, "sim/ro-array-core-combining/testbench/tb_ro_array_core.spice")
COMB_NETLIST = os.path.join(REPO, "design/ro_array_core.spice")
COMB_TMAX = "5p"                     # same as the committed 20260825-0945*/0947*/0948* records
COMB_STOP = "200n"
HOT_POINTS = [(125.0, 1.62), (125.0, 1.8), (125.0, 1.98)]
LIB = "libs.tech/combined/sky130.lib.spice"
DEFAULT_SEEDS = [101, 102, 103, 104, 105, 106, 107, 108]


def build(seed, temp=TEMP, vdd=VDD):
    text = open(TB).read()
    for k, v in {"@@VDD@@": repr(vdd), "@@TEMP@@": repr(temp), "@@TMAX@@": TMAX,
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


def pvt_key(temp, vdd, seed, ts_ns=TS_NS):
    """Collision-free unit name: PVT, sample interval and seed are all in it (issue #289)."""
    return f"pvt_{temp:g}C_{vdd:g}V_Ts{ts_ns}ns_seed{seed}"


def main_pvt(a):
    """One request per (temperature, supply, seed); tt/ss/ff bundled. Writes
    OUTDIR/<key>/{netlist.cir,request.json,manifest.json}; the manifest is the unit's
    declared identity, which the reducer cross-checks against the tool response."""
    seen = set()
    for temp, vdd in parse_points(a.pvt):
        for seed in [int(s) for s in a.seeds.split(",")]:
            key = pvt_key(temp, vdd, seed)
            if key in seen:
                raise SystemExit(f"error: duplicate request key {key}")
            seen.add(key)
            body, meas = build(seed, temp, vdd)
            d = os.path.join(a.outdir, key)
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "netlist.cir"), "w").write(body)
            req = {
                "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
                "netlist_source": "extracted",
                "models": {"pdk": "sky130A", "lib": LIB},
                "corners": {"process": ["tt", "ss", "ff"], "temperature_c": [temp]},
                "analysis": {"kind": "tran", "args": f"{TMAX} 2.5u uic"},
                "measurements": meas,
                "options": {"timeout_s": 3000, "keep_artifacts": False},
            }
            rtext = json.dumps(req, indent=2)
            open(os.path.join(d, "request.json"), "w").write(rtext)
            manifest = {
                "schema": "raw-bit-pvt-request/1", "key": key, "temp_c": temp, "vdd_v": vdd,
                "seed": seed, "ts_ns": TS_NS, "nbits": NBITS, "processes": ["tt", "ss", "ff"],
                "netlist_sha256": hashlib.sha256(open(os.path.join(d, "netlist.cir"), "rb").read()).hexdigest(),
                "request_sha256": hashlib.sha256(rtext.encode()).hexdigest(),
                "testbench": os.path.relpath(TB, REPO),
                "testbench_sha256": hashlib.sha256(open(TB, "rb").read()).hexdigest(),
                "sampler_sha256": hashlib.sha256(open(SAMPLER, "rb").read()).hexdigest(),
            }
            json.dump(manifest, open(os.path.join(d, "manifest.json"), "w"), indent=2, sort_keys=True)
            print(d, f"T={temp:g} Vdd={vdd:g} seed={seed}", len(meas), "measurements")


def parse_points(text):
    return [(float(t), float(v)) for t, v in (p.split(":") for p in text.split(","))]


def build_combining(temp, vdd):
    """(netlist body, measurements, derived-figure names) for one PVT point of the
    combining deck. Same lift-out scheme as sim/post-layout-ro-ring5-assembled-181."""
    text = open(COMB_TB).read()
    for k, v in {"@@VDD@@": repr(vdd), "@@TEMP@@": repr(temp), "@@TMAX@@": COMB_TMAX,
                 "@@RO_RING5@@": COMB_NETLIST}.items():
        text = text.replace(k, v)
    # ngspice .meas WHEN rejects `0.5*1.62`: fold the half-supply to a literal.
    text = re.sub(r"0\.5\*([0-9.]+)", lambda m: repr(round(0.5 * float(m.group(1)), 6)), text)
    head, ctl, in_ctl = [], [], False
    for line in text.splitlines():
        low = line.strip().lower()
        if low == ".control":
            in_ctl = True
        elif low == ".endc":
            in_ctl = False
        else:
            (ctl if in_ctl else head).append(line)
    body = [l for l in head
            if not l.strip().lower().startswith((".lib", ".temp", ".tran", ".save", ".end"))
            or l.strip().lower().startswith(".option")]
    meas = []
    for line in ctl:
        m = re.match(r"\s*meas tran (\w+) ", line)
        if m:
            meas.append({"name": m.group(1), "spice": "." + line.strip()})
    return "\n".join(body) + "\n", meas


def main_combining(a):
    for n, (t, v) in enumerate(parse_points(a.points), 1):
        body, meas = build_combining(t, v)
        d = os.path.join(a.outdir, f"p{n}")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "netlist.cir"), "w").write(body)
        req = {
            "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
            "netlist_source": "extracted",
            "models": {"pdk": "sky130A", "lib": LIB},
            "corners": {"process": ["tt", "ss", "ff"], "temperature_c": [t]},
            "analysis": {"kind": "tran", "args": f"{COMB_TMAX} {COMB_STOP} uic"},
            "measurements": meas,
            "options": {"timeout_s": 3000, "keep_artifacts": False},
        }
        json.dump(req, open(os.path.join(d, "request.json"), "w"), indent=2)
        print(d, f"T={t} Vdd={v}", len(meas), "measurements")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--deck", choices=("raw-bit", "combining"), default="raw-bit")
    ap.add_argument("--points", default=",".join(f"{t:g}:{v:g}" for t, v in HOT_POINTS),
                    help="combining deck only: TEMP_C:VDD,... (default: the 125 C hot grid)")
    ap.add_argument("--pvt", default=None,
                    help="raw-bit deck only (issue #289): TEMP_C:VDD,... non-nominal points (default set: "
                    "DEFAULT_PVT); writes one OUTDIR/pvt_<T>C_<V>V_Ts100ns_seed<S>/ per (point, seed) "
                    "with a manifest.json")
    ap.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    a = ap.parse_args()
    if a.deck == "combining":
        return main_combining(a)
    if a.pvt:
        return main_pvt(a)
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
