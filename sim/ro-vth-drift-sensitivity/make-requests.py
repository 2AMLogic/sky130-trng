#!/usr/bin/env python3
"""Write the `klt sim` requests for the Vth-drift sensitivity campaign (issue #254).

    make-requests.py OUTDIR --set controls     # DC probe + unwrapped control + tt/27C/1.8V pilot (local)
    make-requests.py OUTDIR --set grid         # the full common-mode grid + 6 asymmetric cases (batch)
    # writes OUTDIR/<name>/{netlist.cir,request.json,plan.json}
    klt sim OUTDIR/<name>/request.json -o OUTDIR/<name>/out --format json > OUTDIR/<name>/resp.json

The grid is never hand-launched with ngspice. Grid requests go to the batch fleet
(KLT_SIM_BACKEND=batch); the controls are single-point and run `--backend local`.
This is a sensitivity bound, not a lifetime prediction.
"""
import argparse
import json
from pathlib import Path

import campaign as C
import aging


def tname(t):
    return f"m{abs(int(t))}C" if t < 0 else f"{int(t)}C"


def write(outdir, name, req, netlist, plan):
    d = Path(outdir) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "netlist.cir").write_text(netlist)
    (d / "request.json").write_text(json.dumps(req, indent=2))
    (d / "plan.json").write_text(json.dumps(plan, indent=2))
    print(d, len(plan.get("keys", [])), "keys,", len(req["measurements"]), "measurements")


def probe_request(outdir):
    """DC gate-offset control: tt/27C, offsets 0/20/40/60 mV on both polarities."""
    tb = (C.HERE / "testbench/tb_dc_gate_offset.spice").read_text()
    netlist = aging.wrapper_definition() + tb
    meas = [{"name": n, "spice": f".meas dc {n} find v({v}) at=1.8"} for n, v in
            (("offn", "offn"), ("offp", "offp"), ("dvn_rb", "vth_dvn"), ("dvp_rb", "vth_dvp"))]
    meas += [{"name": "idn", "spice": ".meas dc idn find i(Vdn) at=1.8"},
             {"name": "idnr", "spice": ".meas dc idnr find i(Vdnr) at=1.8"},
             {"name": "idp", "spice": ".meas dc idp find i(Vdp) at=1.8"},
             {"name": "idpr", "spice": ".meas dc idpr find i(Vdpr) at=1.8"}]
    sh = [(s, s) for s in C.CM_SHIFTS_MV] + [tuple(x) for x in C.ASYM_SHIFTS_MV]
    req = {"netlist": "netlist.cir", "engine": "ngspice", "backend": "local", "netlist_source": "extracted",
           "models": {"pdk": "sky130A", "lib": C.LIB},
           "corners": {"process": ["tt"], "temperature_c": [27.0],
                       "supply_v": {"Vdvn": [s[0] * 1e-3 for s in sh], "Vdvp": [s[1] * 1e-3 for s in sh]}},
           "analysis": {"kind": "dc", "args": "Vsup 1.7 1.8 0.1"},
           "measurements": meas, "options": {"timeout_s": 600, "keep_artifacts": False}}
    plan = {"control": "dc-gate-offset", "shifts_mv": [list(s) for s in sh],
            "info": {"netlist_sha256": aging.sha256_text(netlist), "wrapper_sha256": aging.sha256_text(aging.wrapper_definition()),
                     "aging_sha256": aging.sha256_file(C.HERE / "aging.py"),
                     "testbench_sha256": aging.sha256_file(C.HERE / "testbench/tb_dc_gate_offset.spice")}}
    write(outdir, "dc-probe", req, netlist, plan)


def retry_requests(outdir, fallback_stop=None):
    """One single-process, single-shift request per failed unit of every response under OUTDIR (infra failures
    such as an ngspice abort on the fleet are not always reproducible; see the sensitivity record). Without
    --fallback-stop: `<name>--r<k>` at the original stop for units that failed in an original request. With it:
    `<name>--f<k>` at the fallback stop for units that failed again in a `--r<k>` request."""
    base = Path(outdir)
    for d in sorted(base.glob("*/resp.json")):
        name = d.parent.name
        if d.stat().st_size == 0:
            continue
        is_r = name.endswith(tuple(f"--r{i}" for i in range(1, 10)))
        if (fallback_stop is None) == is_r:
            continue
        plan = json.loads((d.parent / "plan.json").read_text())
        resp = json.loads(d.read_text())
        root = plan.get("retry_of", name)
        k = 0
        for c in resp["corners"]:
            if c["status"] == "pass":
                continue
            k += 1
            sh = (round(c["supply_v"]["Vdvn"] * 1e3), round(c["supply_v"]["Vdvp"] * 1e3))
            stop = fallback_stop or plan["info"]["stop"]
            req, nl, pl = C.make_request(plan["deck"], [c["process"]], plan["temp_c"], plan["vdd_v"], [sh], stop=stop)
            pl["retry_of"] = root
            tag = "f" if fallback_stop else "r"
            write(outdir, f"{name}--{tag}{k}", req, nl, pl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--set", choices=("controls", "grid"), default="controls")
    ap.add_argument("--retry", action="store_true",
                    help="OUTDIR already holds grid responses: write a single-unit `<name>--r<k>` request for every unit that failed")
    ap.add_argument("--fallback-stop", default=None,
                    help="with --retry: also re-run every unit that failed again in a `--r<k>` request, as `--f<k>`, with this .tran stop "
                    "(a deterministic ngspice 'timestep too small' at the final breakpoint is not cured by re-running at the same stop)")
    ap.add_argument("--stop-ring", default=None, help="override the ring deck's .tran stop (default: source deck's)")
    a = ap.parse_args()
    if a.retry:
        return retry_requests(a.outdir, a.fallback_stop)
    if a.set == "controls":
        probe_request(a.outdir)
        for deck in C.DECKS:
            # unwrapped control, tt/27C/1.8V, one unit, local
            req, nl, plan = C.make_request(deck, ["tt"], 27.0, 1.8, [(0, 0)], wrap=False,
                                           stop=a.stop_ring if deck == "ring5" else None, backend="local")
            write(a.outdir, f"{deck}-unwrapped", req, nl, plan)
            # pilot: common-mode 0/20/40/60 at tt/27C/1.8V (the 0 unit is the zero-shift wrapped control)
            req, nl, plan = C.make_request(deck, ["tt"], 27.0, 1.8, [(s, s) for s in C.CM_SHIFTS_MV],
                                           stop=a.stop_ring if deck == "ring5" else None, backend="local")
            write(a.outdir, f"{deck}-pilot", req, nl, plan)
        return
    for deck in C.DECKS:
        stop = a.stop_ring if deck == "ring5" else None
        for t in C.TEMPS:
            for v in C.VDDS:
                req, nl, plan = C.make_request(deck, C.PROCESSES, t, v, [(s, s) for s in C.CM_SHIFTS_MV], stop=stop)
                write(a.outdir, f"{deck}-cm-{tname(t)}-{v:g}V", req, nl, plan)
    for c, t, v in C.HEADLINE:
        req, nl, plan = C.make_request("array", [c], t, v, list(C.ASYM_SHIFTS_MV))
        write(a.outdir, f"array-asym-{c}-{tname(t)}-{v:g}V", req, nl, plan)


if __name__ == "__main__":
    main()
