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

Issue #288 lock-resolution campaign (--campaign lock-resolution): groups lr (200-edge
windows, +-0.1/0.25/0.4 % detuning ladder at 20/50 mV plus 5 mV, on-frequency rows,
current-injection controls incl. a clearly free-running +5 % detuned control) and lrc
(400-edge convergence subset); see README.md for the matrix and the resolution
derivation. The enable pulse is parameterized (@@ENW@@/@@ENP@@): legacy decks expand
to the identical 1u/2u literals, the campaign holds the enable high 3 us.

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
NEDGE = 40                      # the #200 window; kept as the default so legacy output is unchanged

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

# ---- issue #288 lock-resolution campaign ------------------------------------
# A free-running ring detuned by delta from a tone slips delta*(N-1) ring cycles
# across an N-edge window, so the detector's DRIFT_LOCK = 0.1-cycle threshold
# resolves delta_min = DRIFT_LOCK/(N-1): 0.256 % at the #200 40-edge window,
# 0.050 % at 200 edges, 0.025 % at 400 edges.  The campaign claims +-0.1 %
# resolution (2x margin at 200 edges) and checks convergence at 400 edges on a
# 3-unit subset; the on-frequency rows stay drift-UNRESOLVED (exact coincidence
# is unidentifiable by drift at any window) and are decided, where at all, by
# detuned neighbours + pull evidence.  Bounded matrix, per corner:
#   lr   1 baseline + 8 on-frequency (f1..f4 x 20/50 mV) + 48 detuned
#        (f1..f4 x {+-0.1, +-0.25, +-0.4} % x 20/50 mV) + 8 detuned below the old
#        10 mV floor (f1..f4 x {+-0.25} % x 5 mV) + 8 current-injection controls
#        (ring 2 x {1.00, 1.02, 1.05, 1.20} x 10/50 uA; +5 % is the clearly
#        free-running detuned control)                        = 73 units
#   lrc  400-edge convergence subset: 1 baseline + ring 2 x {+-0.25} % @ 50 mV
#                                                             = 3 units
LR = "lock-resolution"
LR_EDGES = 200
LR_EDGES_CONV = 400
LR_AMPS = (0.020, 0.050)        # inside the #200 10-50 mV bracket, at the known-lock amplitude
LR_DETUNES = (0.001, 0.0025, 0.004)
LR_AMP_BELOW = 0.005            # below the 10 mV floor of the #200 brackets
LR_DETUNE_BELOW = 0.0025
LR_CTL_KNOBS = (("own", 1.0), ("+2%", 1.02), ("+5%", 1.05), ("+20%", 1.2))
# Units per request.  The fleet powers a job off unconditionally after
# BATCH_MAX_JOB_SECONDS = 3600 s and returns NO unit of a job that hits it
# (every unit `batch_job_timeout`).  The first submission used 8-unit
# requests: ff-lr-1 and ss-lr-1 both hit the cap at 3604 s with nothing
# returned, while the 3-unit lrc requests finished (ff 65 s, ss 400-edge
# 2329 s).  3 units keeps a 200-edge ss request at about half the cap.
# Only the packaging changes; the unit matrix is identical.
LR_CHUNK = 3


def lr_nedge(group):
    return LR_EDGES_CONV if group == "lrc" else LR_EDGES


def lr_stop(c, nedge):
    """tran stop long enough for `nedge` recorded rises after the 5 ns release,
    with margin for start-up and lock drag (locked period = tone period <=
    max(tr)*(1+max detuning))."""
    s = 5e-9 + (nedge + 3) * max(c["tr"]) * 1.18
    return f"{math.ceil(s * 1e9):g}n"


def detuned_unit(i, dd, amp, f):
    return dict(kind="tone", tone=f"f{i}{'+' if dd > 0 else '-'}{abs(dd) * 100:g}%",
                dv=0.0, ra=amp, rf=f[i - 1] * (1 + dd), ri=0.0, detune=dd)


def lr_units(group, c):
    f = [1.0 / t for t in c["tr"]]
    u = [dict(kind="baseline", tone="-", dv=0.0, ra=0.0, rf=1e6, ri=0.0)]
    if group == "lrc":                      # convergence subset at 400 edges
        return u + [detuned_unit(2, s * LR_DETUNE_BELOW, 0.050, f) for s in (1, -1)]
    for amp in LR_AMPS:                     # on-frequency rows: drift stays UNRESOLVED;
        for i in range(1, 5):               # pull evidence + detuned neighbours decide
            u.append(dict(kind="tone", tone=f"f{i}", dv=0.0, ra=amp, rf=f[i - 1], ri=0.0, detune=0.0))
    for amp in LR_AMPS:
        for i in range(1, 5):
            for d in LR_DETUNES:
                for s in (1, -1):
                    u.append(detuned_unit(i, s * d, amp, f))
    for i in range(1, 5):                   # below the #200 10 mV floor
        for s in (1, -1):
            u.append(detuned_unit(i, s * LR_DETUNE_BELOW, LR_AMP_BELOW, f))
    fc = f[CTL_RING - 1]
    for ima in (0.01, 0.05):
        for lab, k in LR_CTL_KNOBS:
            u.append(dict(kind="control", tone=f"ctl:{lab}@{ima * 1e3:g}uA", dv=0.0, ra=0.0, rf=fc * k, ri=ima))
    return u


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


def meas_cards(nedge=NEDGE):
    m = []
    for r in range(1, 5):
        for k in range(3, 3 + nedge):
            m.append((f"t{r}_{k}", f".meas tran t{r}_{k} when v(ro{r})=HALF rise={k}"))
    m.append(("xo_avg", ".meas tran xo_avg AVG v(xo) from=60n to=STOP"))
    m.append(("xo_max", ".meas tran xo_max MAX v(xo) from=60n to=STOP"))
    m.append(("xo_min", ".meas tran xo_min MIN v(xo) from=60n to=STOP"))
    m.append(("txo_a", ".meas tran txo_a when v(xo)=HALF rise=2"))
    m.append(("txo_b", ".meas tran txo_b when v(xo)=HALF rise=50"))
    m.append(("vdd_max", ".meas tran vdd_max MAX v(vdd) from=20n to=STOP"))
    m.append(("vdd_min", ".meas tran vdd_min MIN v(vdd) from=20n to=STOP"))
    return m


def build(c, nedge=NEDGE, stop=None, enw="1u", enp="2u"):
    text = open(TB).read()
    sub = {"@@VNOM@@": repr(c["vnom"]), "@@RO_ARRAY@@": NETLIST,
           "@@ENW@@": enw, "@@ENP@@": enp}
    for k, v in sub.items():
        text = text.replace(k, v)
    half = repr(round(0.5 * c["vnom"], 6))
    meas = [{"name": n, "spice": s.replace("HALF", half).replace("STOP", stop or c["stop"])}
            for n, s in meas_cards(nedge)]
    return text, meas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--corners", default="ss,ff")
    ap.add_argument("--groups", default=None,
                    help="legacy amplitude groups; ignored/defaulted by --campaign")
    ap.add_argument("--chunk", type=int, default=None,
                    help="units per request (default 8; 3 for --campaign lock-resolution, see LR_CHUNK)")
    ap.add_argument("--campaign", choices=[LR], default=None,
                    help="issue #288 lock-resolution campaign (groups lr,lrc; longer edge windows)")
    a = ap.parse_args()
    if a.chunk is None:
        a.chunk = LR_CHUNK if a.campaign == LR else 8
    if a.campaign == LR:
        groups = ("lr", "lrc")
    else:
        groups = (a.groups or "a10,a50,a200,q").split(",")
    for cn in a.corners.split(","):
        c = CORNERS[cn]
        for g in groups:
            if a.campaign == LR:
                nedge, allus = lr_nedge(g), lr_units(g, c)
                stop = lr_stop(c, nedge)
                text, meas = build(c, nedge=nedge, stop=stop, enw="3u", enp="4u")
                extra = {"campaign": LR, "nedge": nedge}
            else:
                allus = units_for(g, c)
                text, meas = build(c)
                extra = {}
            for ci in range(0, len(allus), a.chunk):
              us = allus[ci:ci + a.chunk]
              d = os.path.join(a.outdir, f"{cn}-{g}-{ci // a.chunk + 1}")
              os.makedirs(d, exist_ok=True)
              open(os.path.join(d, "netlist.cir"), "w").write(text)
              req = {
                  "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
                  "netlist_source": "extracted",
                  "models": {"pdk": "sky130A", "lib": LIB},
                  # runner_version_check=warn: the fleet image's klt build string
                  # lags the submitting client, and enforce (the default) then
                  # preflight-rejects every job before any simulation (exit 87,
                  # probed). The skew is recorded in environment.remote instead.
                  "batch": {"runner_version_check": "warn", "capacity_wait_s": 240}
                  if a.campaign == LR else {},
                  "corners": {"process": [c["proc"]], "temperature_c": [c["temp"]],
                              "supply_v": {"V" + k: [u[k] for u in us] for k in ("dv", "ra", "rf", "ri")}},
                  "analysis": {"kind": "tran",
                               "args": (f"{c['tmax']} {stop} uic" if a.campaign == LR
                                        else f"{c['tmax']} {c['stop']} uic")},
                  "measurements": meas,
                  # the long-window transients are ~3x the #200 length; give the
                  # fleet headroom over the legacy 3000 s before calling a unit lost
                  "options": {"timeout_s": 5400 if a.campaign == LR else 3000, "keep_artifacts": False},
              }
              json.dump(req, open(os.path.join(d, "request.json"), "w"), indent=2)
              json.dump({"corner": cn, "group": g, "chunk": ci // a.chunk + 1, "pvt": dict(c, tr=None), "ctl_ring": CTL_RING,
                         "units": us, **extra}, open(os.path.join(d, "plan.json"), "w"), indent=2)
              print(d, f"{c['proc']} {c['temp']}C {c['vnom']}V", len(us), "units", len(meas), "measurements")


if __name__ == "__main__":
    main()
