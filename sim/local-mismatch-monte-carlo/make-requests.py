#!/usr/bin/env python3
"""Generate the `klt sim` batch requests for the local-mismatch Monte Carlo (issue #215).

    make-requests.py OUTDIR [--corners tt,ss,ff] [--n-array 30 --n-sampler 60 --chunk 10 --chunk-sampler 30] [--seed 215]
    # writes OUTDIR/<corner>-<kind>-<n>/{netlist.cir,request.json,plan.json}
    klt sim OUTDIR/<d>/request.json -o OUTDIR/<d>/out --format json > OUTDIR/<d>/resp.json   # KLT_SIM_BACKEND=batch

The grid is never hand-launched with ngspice: it is `klt sim` requests with a
`monte_carlo` block (`vary: "mismatch"`), which go to the batch fleet.

Kinds (per corner):
    arr   ro_array_core MC: 40 rising-edge times per ring + xo duty at 9 thresholds
    smp   sampler_dff MC: D value where Q flips going up / going down
    arr0  / smp0   the same decks on the plain (non-`_mm`) section, ONE unit each:
                   the mismatch-free reference the offsets are taken against.
                   (These carry no `monte_carlo` block: they are the control.)

The MC process sections are sky130's own `tt_mm` / `ss_mm` / `ff_mm`
(MC_MM_SWITCH=1): selectable through the harness's ordinary `corners.process`,
so no PDK switch beyond what the pinned `klt sim` exposes is needed.

Seeds: request i of a kind uses `monte_carlo.seed = seed0 + i` (recorded in
plan.json).  Every corner uses the SAME seeds, so the mismatch draws are paired
across corners (common random numbers: a device that is +1 sigma at tt is the
same +1 sigma draw at ss/ff), which isolates the corner effect from sample noise.
"""
import argparse, json, os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
TB_ARR = os.path.join(HERE, "testbench/tb_ro_array_mismatch.spice")
TB_SMP = os.path.join(HERE, "testbench/tb_sampler_dff_offset.spice")
RO_ARRAY = os.path.join(REPO, "design/ro_array_core.spice")
SAMPLER = os.path.join(REPO, "design/sampler_core.spice")
LIB = "libs.tech/combined/sky130.lib.spice"
EDGES = range(3, 43)              # rising-edge indices recorded per ring (40 edges, 39 periods)
THRS = (30, 35, 40, 45, 50, 55, 60, 65, 70)

# tt/27C/1.8V is the nominal point; ss and ff are the two envelope extremes the repo already uses
# (sim/ro-array-supply-perturbation: DR-0002 entropy-binding corner and DR-0003 combining-binding corner).
CORNERS = {
    "tt": dict(proc="tt", temp=27.0, vnom=1.8, stop="300n", tmax="10p", why="typical, nominal"),
    "ss": dict(proc="ss", temp=-40.0, vnom=1.62, stop="460n", tmax="10p", why="DR-0002 entropy-binding corner"),
    "ff": dict(proc="ff", temp=-40.0, vnom=1.98, stop="300n", tmax="5p", why="fast corner (DR-0003 combining-binding corner)"),
}
SMP_STOP, SMP_TMAX = "3.04u", "100p"


def arr_meas(c):
    half = repr(round(0.5 * c["vnom"], 6))
    m = []
    for r in range(1, 5):
        for k in EDGES:
            m.append({"name": f"t{r}_{k}", "spice": f".meas tran t{r}_{k} when v(ro{r})={half} rise={k}"})
    for f in THRS:
        m.append({"name": f"duty{f}", "spice": f".meas tran duty{f} AVG v(d{f}) from=60n to={c['stop']}"})
    m.append({"name": "xo_avg", "spice": f".meas tran xo_avg AVG v(xo) from=60n to={c['stop']}"})
    return m


def smp_meas(c):
    half = repr(round(0.5 * c["vnom"], 6))
    return [
        {"name": "t_up", "spice": f".meas tran t_up when v(q)={half} rise=1 td=100n"},
        {"name": "vtrip_up", "spice": f".meas tran vtrip_up find v(d) when v(q)={half} rise=1 td=100n"},
        {"name": "t_dn", "spice": f".meas tran t_dn when v(q)={half} fall=1 td=1.6u"},
        {"name": "vtrip_dn", "spice": f".meas tran vtrip_dn find v(d) when v(q)={half} fall=1 td=1.6u"},
    ]


def inline(text, token, path):
    """Replace the `.include "<token>"` card by the design file's text: the submitted deck is then
    self-contained (no host path for the fleet to resolve) and the exact design bytes are in the record."""
    card = f'.include "{token}"'
    assert card in text
    return text.replace(card, f"* ---- inlined from {os.path.relpath(path, REPO)} ----\n" + open(path).read())


def netlist(kind, c):
    if kind.startswith("arr"):
        text = inline(open(TB_ARR).read(), "@@RO_ARRAY@@", RO_ARRAY).replace("@@VNOM@@", repr(c["vnom"]))
    else:
        text = (inline(open(TB_SMP).read(), "@@SAMPLER@@", SAMPLER).replace("@@VNOM@@", repr(c["vnom"]))
                .replace("@@VLO@@", repr(round(0.25 * c["vnom"], 6))).replace("@@VHI@@", repr(round(0.75 * c["vnom"], 6))))
    return text


def request(kind, c, section, mc):
    arr = kind.startswith("arr")
    req = {
        "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch", "netlist_source": "extracted",
        "models": {"pdk": "sky130A", "lib": LIB},
        "corners": {"process": [section], "temperature_c": [c["temp"]]},
        "analysis": {"kind": "tran", "args": f"{c['tmax']} {c['stop']} uic" if arr else f"{SMP_TMAX} {SMP_STOP}"},
        "measurements": arr_meas(c) if arr else smp_meas(c),
        "options": {"timeout_s": 3000, "keep_artifacts": False},
    }
    if mc:
        req["monte_carlo"] = mc
    return req


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--corners", default="tt,ss,ff")
    ap.add_argument("--n-array", type=int, default=30)
    ap.add_argument("--n-sampler", type=int, default=60)
    ap.add_argument("--chunk", type=int, default=10, help="MC samples per request (fleet parallelism)")
    ap.add_argument("--chunk-sampler", type=int, default=30, help="MC samples per sampler request")
    ap.add_argument("--seed", type=int, default=215, help="seed of request 1; request i uses seed+i-1")
    ap.add_argument("--no-nominal", action="store_true")
    a = ap.parse_args()
    for cn in a.corners.split(","):
        c = CORNERS[cn]
        plans = []
        for kind, ntot, ch in (("arr", a.n_array, a.chunk), ("smp", a.n_sampler, a.chunk_sampler)):
            for i, lo in enumerate(range(0, ntot, ch)):
                plans.append((f"{cn}-{kind}-{i + 1}", kind, c["proc"] + "_mm",
                              {"n": min(ch, ntot - lo), "seed": a.seed + i, "vary": "mismatch"}))
            if not a.no_nominal:
                plans.append((f"{cn}-{kind}0-1", kind + "0", c["proc"], None))
        for name, kind, section, mc in plans:
            d = os.path.join(a.outdir, name)
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "netlist.cir"), "w").write(netlist(kind, c))
            json.dump(request(kind, c, section, mc), open(os.path.join(d, "request.json"), "w"), indent=2)
            json.dump({"corner": cn, "kind": kind, "section": section, "monte_carlo": mc,
                       "pvt": dict(c), "n": (mc or {}).get("n", 1)},
                      open(os.path.join(d, "plan.json"), "w"), indent=2)
            print(d, section, f"{c['temp']}C {c['vnom']}V", mc or "nominal (no MC)")


if __name__ == "__main__":
    main()
