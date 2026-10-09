#!/usr/bin/env python3
"""Generate the `klt sim` batch requests for the supply-ripple campaign (issue #200).

    make-requests.py OUTDIR [--corners ss,ff] [--probe]
    # writes OUTDIR/<corner>-<group>/{netlist.cir,request.json,plan.json}
    klt sim OUTDIR/<g>/request.json -o OUTDIR/<g>/out --format json > OUTDIR/<g>/resp.json

The grid is never hand-launched with ngspice: it is `klt sim` requests, which
go to the batch fleet (KLT_SIM_BACKEND=batch).

One request = one (process, temperature, supply) point x a list of ripple units.
Units are expressed through `corners.supply_v`, which klt sim zips by index and
applies as `alter <source>=<value>` per unit (rails move as a set), so a whole
ripple ladder is ONE request, not one request per tone:

    Vdv DC supply offset (V)         quasi-static family
    Vra common ripple amplitude (V pk)
    Vrf ripple frequency (Hz)
    Vri negative-control current injection into ring CTL_RING's node n2 (mA pk)
(DC knob sources the behavioural supply reads; see the testbench header for why a
`.param`/SIN() sweep does not work).

Groups per corner:
    a10 / a50 / a100 / a200   10 / 50 / 100 / 200 mV pk tones
    q    clean baseline + quasi-static supply nodes (50 kbps family) + negative control

Tone ladder (from the committed ro-array-core-combining record at the same
PVT point, so no tone depends on a number measured in this campaign): f1..f4 are
the four rings' own frequencies, fm their mean.
    f1 f2 f3 f4          each ring's own frequency (worst case for tone locking)
    0.9 f1, 1.1 f4       just outside the ladder
    fm/2, fm/3           sub-harmonics (2:1 / 3:1 sub-harmonic injection)
    2 fm                 second harmonic (1:2 injection)
    1.005*f1..f4         each ring's frequency detuned +0.5%: brackets the lock range that the
                         at-frequency rows cannot resolve (40-edge window, ~0.25% resolution)
    10 MHz               supply noise from the digital section, well below the ladder
The 50 kbps sample rate (and anything << ring frequency) is the quasi-static
family: the supply is stepped to the Gauss-Chebyshev nodes of the sine
(0, +-sqrt(3)/2 A) and its extremes (+-A) instead of simulating a 20 us period.
"""
import argparse, json, math, os, re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TB = os.path.join(REPO, "sim/ro-array-supply-perturbation/testbench/tb_ro_array_supply_perturbation.spice")
NETLIST = os.path.join(REPO, "design/ro_array_core.spice")
LIB = "libs.tech/combined/sky130.lib.spice"
EDGES = range(3, 43)            # rising-edge indices recorded per ring (40 edges, 39 periods)

# committed ring periods (s) of design/ro_array_core.spice at the corner, from
# sim/ro-array-core-combining/records/20260825-094545-53f1f7a.json (-40C/1.62V, ss)
# and 20260825-094856-53f1f7a.json (-40C/1.98V, ff).
CORNERS = {
    "ss": dict(proc="ss", temp=-40.0, vnom=1.62, stop="460n", tmax="10p",
               tr=[5.427116e-09, 5.216235e-09, 5.018784e-09, 4.83086e-09],
               why="DR-0002 entropy-binding corner"),
    "ff": dict(proc="ff", temp=-40.0, vnom=1.98, stop="300n", tmax="5p",
               tr=[1.5971e-09, 1.512093e-09, 1.437542e-09, 1.365115e-09],
               why="fast corner (DR-0003 combining-binding corner)"),
}
CTL_RING = 2


def tones(tr):
    f = [1.0 / t for t in tr]
    fm = sum(f) / 4
    out = [("f1", f[0]), ("f2", f[1]), ("f3", f[2]), ("f4", f[3]),
           ("1.005*f1", 1.005 * f[0]), ("1.005*f2", 1.005 * f[1]), ("1.005*f3", 1.005 * f[2]), ("1.005*f4", 1.005 * f[3]),
           ("0.9*f1", 0.9 * f[0]), ("1.1*f4", 1.1 * f[3]),
           ("fm/2", fm / 2), ("fm/3", fm / 3), ("2*fm", 2 * fm), ("10MHz", 10e6)]
    return out


def units_for(group, c):
    f = [1.0 / t for t in c["tr"]]
    u = []
    if group in ("a10", "a50", "a100", "a200"):
        amp = {"a10": 0.010, "a50": 0.050, "a100": 0.100, "a200": 0.200}[group]
        for name, fr in tones(c["tr"]):
            u.append(dict(kind="tone", tone=name, dv=0.0, ra=amp, rf=fr, ri=0.0))
    else:
        u.append(dict(kind="baseline", tone="-", dv=0.0, ra=0.0, rf=1e6, ri=0.0))
        s3 = math.sqrt(3) / 2
        for amp in (0.010, 0.050):
            for lab, k in (("-A", -1.0), ("-0.866A", -s3), ("+0.866A", s3), ("+A", 1.0)):
                u.append(dict(kind="quasistatic", tone=f"{lab}@{amp*1e3:g}mV",
                              dv=round(k * amp, 6), ra=0.0, rf=1e6, ri=0.0, amp=amp))
        # negative control: a CURRENT tone injected into ring CTL_RING's node n2, at the
        # ring's own frequency, +2% and +20%. +2% is the decisive one (the clean ring would
        # slip 0.8 cycles over the window, so only a true lock reads as locked); +20% is
        # far outside any lock range and must NOT be flagged (specificity).
        fc = f[CTL_RING - 1]
        for ima in (0.01, 0.05):
            for lab, k in (("own", 1.0), ("+2%", 1.02), ("+20%", 1.2)):
                u.append(dict(kind="control", tone=f"ctl:{lab}@{ima*1e3:g}uA", dv=0.0, ra=0.0, rf=fc * k, ri=ima))
    return u


def meas_cards():
    m = []
    for r in range(1, 5):
        for k in EDGES:
            m.append((f"t{r}_{k}", f".meas tran t{r}_{k} when v(ro{r})=HALF rise={k}"))
    m.append(("xo_avg", ".meas tran xo_avg AVG v(xo) from=60n to=STOP"))
    m.append(("xo_max", ".meas tran xo_max MAX v(xo) from=60n to=STOP"))
    m.append(("xo_min", ".meas tran xo_min MIN v(xo) from=60n to=STOP"))
    m.append(("txo_a", ".meas tran txo_a when v(xo)=HALF rise=2"))
    m.append(("txo_b", ".meas tran txo_b when v(xo)=HALF rise=50"))
    m.append(("vdd_max", ".meas tran vdd_max MAX v(vdd) from=20n to=STOP"))
    m.append(("vdd_min", ".meas tran vdd_min MIN v(vdd) from=20n to=STOP"))
    return m


def build(c):
    text = open(TB).read()
    sub = {"@@VNOM@@": repr(c["vnom"]), "@@RO_ARRAY@@": NETLIST}
    for k, v in sub.items():
        text = text.replace(k, v)
    half = repr(round(0.5 * c["vnom"], 6))
    meas = [{"name": n, "spice": s.replace("HALF", half).replace("STOP", c["stop"])}
            for n, s in meas_cards()]
    return text, meas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--corners", default="ss,ff")
    ap.add_argument("--groups", default="a10,a50,a200,q")
    ap.add_argument("--chunk", type=int, default=8, help="units per request (parallelism on the fleet)")
    a = ap.parse_args()
    for cn in a.corners.split(","):
        c = CORNERS[cn]
        text, meas = build(c)
        for g in a.groups.split(","):
            allus = units_for(g, c)
            for ci in range(0, len(allus), a.chunk):
              us = allus[ci:ci + a.chunk]
              d = os.path.join(a.outdir, f"{cn}-{g}-{ci // a.chunk + 1}")
              os.makedirs(d, exist_ok=True)
              open(os.path.join(d, "netlist.cir"), "w").write(text)
              req = {
                  "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
                  "netlist_source": "extracted",
                  "models": {"pdk": "sky130A", "lib": LIB},
                  "corners": {"process": [c["proc"]], "temperature_c": [c["temp"]],
                              "supply_v": {"V" + k: [u[k] for u in us] for k in ("dv", "ra", "rf", "ri")}},
                  "analysis": {"kind": "tran", "args": f"{c['tmax']} {c['stop']} uic"},
                  "measurements": meas,
                  "options": {"timeout_s": 3000, "keep_artifacts": False},
              }
              json.dump(req, open(os.path.join(d, "request.json"), "w"), indent=2)
              json.dump({"corner": cn, "group": g, "chunk": ci // a.chunk + 1, "pvt": dict(c, tr=None), "ctl_ring": CTL_RING,
                         "units": us}, open(os.path.join(d, "plan.json"), "w"), indent=2)
              print(d, f"{c['proc']} {c['temp']}C {c['vnom']}V", len(us), "units", len(meas), "measurements")


if __name__ == "__main__":
    main()
