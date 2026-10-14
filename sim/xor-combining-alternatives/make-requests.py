#!/usr/bin/env python3
"""Generate the `klt sim` batch requests for the XOR combining-gate alternatives (issue #282).

    make-requests.py OUTDIR
    # writes OUTDIR/<variant>-<temp>-<vdd>/{netlist.cir,request.json,plan.json}
    klt sim OUTDIR/<d>/request.json -o OUTDIR/<d>/out --format json > OUTDIR/<d>/resp.json

The 18-job matrix (2 variants x 9 PVT points) is never hand-launched with
ngspice: it is six `klt sim` corners requests (variant x (temperature, supply)),
each carrying the tt/ss/ff process axis as three units, which go to the batch
fleet (KLT_SIM_BACKEND=batch).

Variants
--------
    base   the committed design/ro_array_core.spice, byte for byte (control)
    w2x    the same text with EVERY MOS width in the `xor2` subcircuit multiplied
           by exactly 2 (lengths, topology and N = 4 untouched). The three gates
           xa1/xa2/xa3 of the depth-2 tree, and the pulse-bench gates, are all
           instances of that one subcircuit, so one substitution covers all of
           them. The width-dependent geometry parameters follow the relations
           the committed netlist itself obeys (ad = as = 0.29 W, pd = ps =
           2 (W + 0.29), nrd = nrs = 0.29 / W); the baseline is checked against
           those relations before they are applied.

The scaled subcircuit lives only in the generated deck under this directory;
design/ is read, never written.
"""
import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TB = os.path.join(HERE, "testbench", "tb_xor_alternatives.spice")
DESIGN = os.path.join(REPO, "design", "ro_array_core.spice")
SAMPLER_CORE = os.path.join(REPO, "design", "sampler_core.spice")
LIB = "libs.tech/combined/sky130.lib.spice"

VARIANTS = {"base": 1, "w2x": 2}
# DR-0003's nine-point grid: (temperature degC, supply V); the process axis is tt/ss/ff.
PVT_POINTS = [(-40.0, 1.62), (27.0, 1.80), (-40.0, 1.98)]
PROCESSES = ["tt", "ss", "ff"]
# Established steady-state window (sim/ro-array-core-combining/testbench/tb_ro_array_core.spice)
WIN_FROM, WIN_TO = "60n", "200n"
PW_WIDTHS = [500, 300, 200, 140, 100, 70, 50, 35, 25]    # ps, tb order; pulse bench swing keys
# ONE transient serves both benches. The batch fleet's runner (klt 0.5.0) and the client that can talk to it
# (0.6.0) have no `analysis_steps`, so the pulse-width bench cannot run its committed 0.5p/12n analysis
# separately from the array bench's 5p/200n one. 5p is the array bench's committed step; it was checked
# against the committed 0.5p step on the hardest pulse-width corner (ff/-40 C/1.98 V, w_90 = 121.99 ps):
# 5p 122.10, 2p 122.02, 1p 121.99, 0.5p 121.99 ps (+0.09 % at 5p) -- see README.md.
TRAN = "5p 200n"


def read(path):
    with open(path) as fh:
        return fh.read()


def _block(text, name):
    """The `.subckt <name> ... .ends` block of `text` (comment lines inside included)."""
    m = re.search(rf"^\.subckt {name}\b.*?^\.ends\b[^\n]*\n", text, re.S | re.M)
    if not m:
        raise SystemExit(f"error: .subckt {name} not found")
    return m.group(0)


def _join(block):
    """Fold `+` continuation lines into their parent line."""
    out = []
    for ln in block.splitlines():
        if ln.startswith("+") and out:
            out[-1] += " " + ln[1:].strip()
        else:
            out.append(ln)
    return out


def _num(tok, key):
    m = re.search(rf"\b{key}=([0-9.eE+-]+)", tok)
    return float(m.group(1)) if m else None


def mos_devices(xor_block):
    """(name, W, L, mult, line) for every MOS in a (joined) xor2 block."""
    out = []
    for ln in _join(xor_block):
        if ln.startswith("XM"):
            out.append((ln.split()[0], _num(ln, "W"), _num(ln, "L"), _num(ln, "mult") or 1.0, ln))
    return out


def scale_xor2(xor_block, factor):
    """Multiply every MOS width in the xor2 block by `factor`; return the new block text."""
    if factor == 1:
        return xor_block
    out = []
    for ln in _join(xor_block):
        if not ln.startswith("XM"):
            out.append(ln)
            continue
        w = _num(ln, "W")
        ad = _num(ln, "ad")
        pd = _num(ln, "pd")
        nrd = _num(ln, "nrd")
        # the baseline obeys the PDK-generated relations; refuse to scale if it does not
        for got, want, nm in ((ad, 0.29 * w, "ad"), (pd, 2 * (w + 0.29), "pd"), (nrd, 0.29 / w, "nrd")):
            if abs(got - want) > 1e-3 * max(1.0, abs(want)):
                raise SystemExit(f"error: {ln.split()[0]} {nm}={got} violates the geometry relation ({want})")
        w2 = w * factor

        def sub(key, val, s):
            return re.sub(rf"\b{key}=[0-9.eE+-]+", f"{key}={val:.12g}", s)

        ln = sub("W", w2, ln)
        for k in ("ad", "as"):
            ln = sub(k, 0.29 * w2, ln)
        for k in ("pd", "ps"):
            ln = sub(k, 2 * (w2 + 0.29), ln)
        for k in ("nrd", "nrs"):
            ln = sub(k, 0.29 / w2, ln)
        out.append(ln)
    return "\n".join(out) + "\n"


def xor_area_proxy_um2(xor_block, instances=3):
    """Sum W x L x mult over the MOS of `instances` xor2 instances (um^2). NOT placed/routed area."""
    return instances * sum(w * l * m for _n, w, l, m, _ln in mos_devices(xor_block))


def build_deck(variant, vdd):
    """Self-contained netlist text for (variant, vdd). Reads design/, never writes it."""
    factor = VARIANTS[variant]
    design = read(DESIGN)
    xor_base = _block(design, "xor2")
    xor_var = scale_xor2(xor_base, factor)
    design_text = design.replace(xor_base, xor_var) if factor != 1 else design
    sampler = _block(read(SAMPLER_CORE), "sampler_dff")
    tb = read(TB)
    tb = tb.replace("@@DESIGN_NETLIST@@", design_text.rstrip() + "\n")
    tb = tb.replace("@@SAMPLER_DFF@@", sampler.rstrip() + "\n")
    tb = tb.replace("@@VDD@@", repr(vdd))
    return tb, xor_area_proxy_um2(xor_var), xor_area_proxy_um2(xor_base)


def pulse_measurements():
    m = []
    for i in range(1, 10):
        m.append({"name": f"vx{i}", "spice": f".meas tran vx{i} MAX v(y{i}) from=8n to=12n"})
        m.append({"name": f"vn{i}", "spice": f".meas tran vn{i} MIN v(y{i}) from=8n to=12n"})
    return m


def array_measurements():
    f, t = WIN_FROM, WIN_TO
    m = []
    for r in range(1, 5):
        m.append(("t%da" % r, f".meas tran t{r}a when v(ro{r})=HALFV rise=3"))
        m.append(("t%db" % r, f".meas tran t{r}b when v(ro{r})=HALFV rise=13"))
    m += [
        ("vxo_max", f".meas tran vxo_max MAX v(xo) from={f} to={t}"),
        ("vxo_min", f".meas tran vxo_min MIN v(xo) from={f} to={t}"),
        ("vxo_avg", f".meas tran vxo_avg AVG v(xo) from={f} to={t}"),
        ("vt1_avg", f".meas tran vt1_avg AVG v(xdut.t1) from={f} to={t}"),
        ("txo_a", ".meas tran txo_a when v(xo)=HALFV rise=2"),
        ("txo_b", ".meas tran txo_b when v(xo)=HALFV rise=50"),
        ("tt1a", ".meas tran tt1a when v(xdut.t1)=HALFV rise=2"),
        ("tt1b", ".meas tran tt1b when v(xdut.t1)=HALFV rise=50"),
    ]
    for k, src in (("i1", "Vddr1"), ("i2", "Vddr2"), ("i3", "Vddr3"), ("i4", "Vddr4"), ("ib", "Vdd")):
        m.append((k, f".meas tran {k} AVG i({src}) from={f} to={t}"))
    for k, src in (("qa", "Vcina"), ("qb", "Vcinb"), ("qs", "Vcins")):
        m.append((k, f".meas tran {k} INTEG i({src}) from=19.9n to=21n"))
    return m


def build_request(variant, temp, vdd):
    half = repr(round(0.5 * vdd, 6))
    arr = [{"name": n, "spice": s.replace("HALFV", half)} for n, s in array_measurements()]
    return {
        "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
        "netlist_source": "extracted",
        "models": {"pdk": "sky130A", "lib": LIB},
        "corners": {"process": list(PROCESSES), "temperature_c": [temp]},
        "analysis": {"kind": "tran", "args": TRAN},
        "measurements": pulse_measurements() + arr,
        "options": {"timeout_s": 7200, "keep_artifacts": False},
    }


def req_name(variant, temp, vdd):
    return f"{variant}-{temp:g}C-{vdd:.2f}V"


def build_matrix():
    """The full request set: list of (name, variant, temp, vdd, request-dict)."""
    out = []
    for variant in VARIANTS:
        for temp, vdd in PVT_POINTS:
            out.append((req_name(variant, temp, vdd), variant, temp, vdd, build_request(variant, temp, vdd)))
    return out


def jobs_of(matrix):
    """Expand to one identity per (variant, temp, vdd, process) job -- must be exactly 18, all unique."""
    jobs = []
    for _name, variant, temp, vdd, req in matrix:
        for proc in req["corners"]["process"]:
            for t in req["corners"]["temperature_c"]:
                jobs.append((variant, t, vdd, proc))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    a = ap.parse_args()
    matrix = build_matrix()
    jobs = jobs_of(matrix)
    assert len(jobs) == 18 and len(set(jobs)) == 18, f"expected 18 unique jobs, got {len(jobs)}/{len(set(jobs))}"
    for name, variant, temp, vdd, req in matrix:
        d = os.path.join(a.outdir, name)
        os.makedirs(d, exist_ok=True)
        deck, area, area_base = build_deck(variant, vdd)
        with open(os.path.join(d, "netlist.cir"), "w") as fh:
            fh.write(deck)
        with open(os.path.join(d, "request.json"), "w") as fh:
            json.dump(req, fh, indent=2)
        with open(os.path.join(d, "plan.json"), "w") as fh:
            json.dump({"name": name, "variant": variant, "width_factor": VARIANTS[variant], "temp_c": temp,
                       "vdd_v": vdd, "processes": PROCESSES, "xor_area_proxy_um2": area,
                       "xor_area_proxy_base_um2": area_base}, fh, indent=2)
        print(d, variant, f"{temp:g}C {vdd}V", len(PROCESSES), "units")
    print(len(jobs), "jobs")


if __name__ == "__main__":
    main()
