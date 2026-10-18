#!/usr/bin/env python3
"""Assemble the whole-block klt sim requests (issue #174).

Writes ``corners/<name>/{netlist.cir,request.json,plan.json}`` for two sets:

``--set controls``
    ``startup-probe`` -- the full deck truncated after the first program
    phases, one corner (``tt``, 27 C, 1.8 V), ``backend: local``. Run it
    locally first: it proves the flat netlist parses, the DC start-up
    converges, the rings start, reset releases and the first bus reads
    return before the 12-point grid is submitted to the batch fleet, and
    its wall-clock is the compute-budget measurement the record cites.

``--set grid``
    one request per (T, Vdd) point of this repo's established four-point
    post-layout grid -- (-40 C, 1.62 V), (27 C, 1.8 V), (-40 C, 1.98 V),
    (125 C, 1.98 V) -- each bundling the ``tt``/``ss``/``ff`` process axis
    (4 requests x 3 corners = the full 12-point matrix), ``backend: batch``:
    a ``klt sim`` corners request goes to the batch fleet; this is never a
    hand-launched local ngspice grid.

The deck body is::

    <the netlist body from make-netlist.py, inlined verbatim>
    <supplies (vdd, vss, vddr1..4 as DC sources the corners.supply_v axis
     alters), the en/rst_n/clk PULSE cards, the program's per-cycle PWL bus
     cards, the trng_whole instantiation, the .save list>

``klt sim`` owns ``.lib``/``.temp``/``.tran`` and the ``.control`` block
(its netlist convention: a circuit body, no ``.control``/``.end``), and
generates the corner ``.meas`` cards from the request's ``measurements[]``
-- which this script fills from ``program.py``.

Nothing here simulates anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import program as P  # noqa: E402

NETLIST_BODY = HERE / "trng_whole.sim.spice"
NETLIST_GZ = HERE / "trng_whole.sim.spice.gz"
OUTROOT = HERE / "corners"

LIB = "libs.tech/combined/sky130.lib.spice"
PDK = "sky130A"
TMAX = "20p"

#: the repo's established four-point post-layout grid x tt/ss/ff (12 points)
GRID = [(-40.0, 1.62), (27.0, 1.8), (-40.0, 1.98), (125.0, 1.98)]

#: per-corner wall-clock bound for the batch grid (set from the measured
#: startup-probe rate, see the record)
GRID_TIMEOUT_S = 21600

#: digital input high level, fixed at every corner (declared in the record:
#: 1.8 V is the sky130 1.8 V device rating; VIH(1.62 V) = 1.05 V accepts it,
#: and the supply sources themselves -- not these cards -- carry the corner)
VIH = 1.8

#: current-window current/power integration windows (ns): W1 rings-running /
#: digital reset-held (clk has not started; rst_n low until 300 ns); W2 active
#: (every program cycle; clipped to end one Ts before tstop)
W1 = (50.0, 250.0)


def _netlist_text() -> str:
    """The committed netlist body (gzip is the committed form; a plain copy wins if present)."""
    if NETLIST_BODY.exists():
        return NETLIST_BODY.read_text()
    import gzip
    return gzip.decompress(NETLIST_GZ.read_bytes()).decode()


def fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v)}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pwl_card(sig: str, net: str, points: list[tuple[float, float]]) -> str:
    # logical 0/1 -> volts: highs sit at the declared VIH, not at 1.000 V
    pts = " ".join(f"{t:.1f}n {v * VIH:.3f}" for t, v in points)
    return f"V{sig} {net} 0 PWL({pts})"


def input_cards(cycles: list[dict], n_cycles: int) -> list[str]:
    """One PWL card per driven input pin; value changes at t_edge+SKEW."""
    inputs = P.cycle_inputs(cycles)
    cards = []

    def points(get):
        pts = [(0.0, get(0))]
        for k in range(1, n_cycles):
            prev, cur = get(k - 1), get(k)
            if cur != prev:
                pts.append((P.t_edge_ns(k) + P.SKEW_NS, float(cur)))
        pts.append((P.t_stop_ns(cycles), get(n_cycles - 1)))
        return pts

    for bit in range(4):
        cards.append(pwl_card(f"bus_addr_{bit}_", f"bus_addr_{bit}_",
                              points(lambda k, b=bit: (inputs[k]["addr"] >> bit) & 1)))
    for bit in range(32):
        cards.append(pwl_card(f"bus_wdata_{bit}_", f"bus_wdata_{bit}_",
                              points(lambda k, b=bit: (inputs[k]["wdata"] >> b) & 1)))
    cards.append(pwl_card("bus_we", "bus_we", points(lambda k: inputs[k]["we"])))
    cards.append(pwl_card("bus_re", "bus_re", points(lambda k: inputs[k]["re"])))
    cards.append(pwl_card("raw_valid", "raw_valid", points(lambda k: inputs[k]["raw_valid"])))
    cards.append(pwl_card("out_ready", "out_ready", points(lambda k: inputs[k]["out_ready"])))
    return cards


def measurement_cards(cycles: list[dict]) -> tuple[list[dict], list[str]]:
    """The request's measurements[] entries; returns (entries, .save nets)."""
    n = len(cycles)
    inputs = P.cycle_inputs(cycles)
    t_stop = P.t_stop_ns(cycles)
    meas: list[dict] = []
    save = {"clk", "rst_n", "raw_bit", "raw_valid", "ring_bit1", "ring_bit2",
            "ring_bit3", "ring_bit4", "alarm", "gated", "startup_done",
            "out_valid", "vdd", "vss", "vddr1", "vddr2", "vddr3", "vddr4"}

    def add(name: str, card: str, save_net: str | None = None, t: float | None = None):
        if t is not None and t > t_stop:
            return  # unreachable within this (truncated) program's stop time
        meas.append({"name": name, "spice": card})
        if save_net:
            save.add(save_net)

    # -- per-sample-cycle raw tap captures (the oracle's stimulus)
    for k, inp in enumerate(inputs):
        if inp["raw_valid"]:
            t = P.t_edge_ns(k) + P.CAPTURE_NS
            add(f"raw_bit_k{k}", f".meas tran raw_bit_k{k} FIND v(raw_bit) AT={t:.1f}n", "raw_bit", t)
            add(f"raw_valid_k{k}", f".meas tran raw_valid_k{k} FIND v(raw_valid) AT={t:.1f}n", "raw_valid", t)

    # -- bus_rdata on every read cycle: visible during the NEXT cycle
    for k, inp in enumerate(inputs):
        if inp["re"]:
            t = P.t_edge_ns(k + 1) + P.RDATA_NS
            for bit in range(32):
                add(f"rdata_k{k}_b{bit}",
                    f".meas tran rdata_k{k}_b{bit} FIND v(bus_rdata_{bit}_) AT={t:.1f}n",
                    f"bus_rdata_{bit}_", t)

    # -- streaming-port captures: every cycle where a word can complete or pop
    for k in range(3, n):
        if inputs[k]["out_ready"] or inputs[k - 1]["out_ready"]:
            t = P.t_edge_ns(k) + P.RDATA_NS
            add(f"out_valid_k{k}", f".meas tran out_valid_k{k} FIND v(out_valid) AT={t:.1f}n", "out_valid", t)
            if k in (36, 37, 74) or k >= n - 3:
                for bit in range(32):
                    add(f"odata_k{k}_b{bit}",
                        f".meas tran odata_k{k}_b{bit} FIND v(out_data_{bit}_) AT={t:.1f}n",
                        f"out_data_{bit}_", t)

    # -- scalar observables at every bus-quiet sample-phase boundary of interest
    for k in sorted({2, 3, 36, 42, 74, n - 1}):
        t = P.t_edge_ns(k) + P.RDATA_NS
        for sig in ("alarm", "gated", "startup_done"):
            add(f"{sig}_k{k}", f".meas tran {sig}_k{k} FIND v({sig}) AT={t:.1f}n", sig, t)

    # -- first stream-valid assertion time (throughput tap, see README)
    add("t_out_valid_first", ".meas tran t_out_valid_first WHEN v(out_valid)=1.4 RISE=1", "out_valid")

    # -- per-rail currents: W1 (rings running, digital reset-held) and W2 (active)
    w2 = (P.t_edge_ns(2), t_stop - P.TS_NS)
    for rail in ("vdd", "vddr1", "vddr2", "vddr3", "vddr4"):
        add(f"i_{rail}_w1", f".meas tran i_{rail}_w1 AVG i(V{rail}) FROM={W1[0]:.0f}n TO={W1[1]:.0f}n")
        add(f"i_{rail}_w2", f".meas tran i_{rail}_w2 AVG i(V{rail}) FROM={w2[0]:.0f}n TO={w2[1]:.0f}n")
        add(f"q_{rail}_w2", f".meas tran q_{rail}_w2 INTEG i(V{rail}) FROM={w2[0]:.0f}n TO={w2[1]:.0f}n")
        meas[-3:][:0]  # no-op; keep ordering explicit
    add("i_vss_w2", f".meas tran i_vss_w2 AVG i(Vvss) FROM={w2[0]:.0f}n TO={w2[1]:.0f}n")

    # -- sanity: the clock really toggled
    add("t_clk_first", ".meas tran t_clk_first WHEN v(clk)=0.9 RISE=1", "clk")

    save |= {f"i(V{r})" for r in ("vdd", "vss", "vddr1", "vddr2", "vddr3", "vddr4")}
    names = [e["name"] for e in meas]
    assert len(names) == len(set(names)), "duplicate measurement names (klt coverage needs unique work ids)"
    return meas, sorted(save)


def deck_body(cycles: list[dict], header: list[str]) -> str:
    body = ["* " + line for line in header]
    body += [
        "",
        ".option scale=1u",
        "",
        *_netlist_text().splitlines(),
        "",
        "* ---- supplies (corners.supply_v alters the named sources) ----",
        "Vvdd vdd 0 dc 1.8",
        "Vvss vss 0 dc 0",
        "Vvddr1 vddr1 0 dc 1.8",
        "Vvddr2 vddr2 0 dc 1.8",
        "Vvddr3 vddr3 0 dc 1.8",
        "Vvddr4 vddr4 0 dc 1.8",
        "* ---- enables, reset, clock (fixed 1.8 V digital levels; see header) ----",
        f"Ven1 en1 0 PULSE(0 {VIH} 5n 100p 100p 1u 2u)",
        f"Ven2 en2 0 PULSE(0 {VIH} 5n 100p 100p 1u 2u)",
        f"Ven3 en3 0 PULSE(0 {VIH} 5n 100p 100p 1u 2u)",
        f"Ven4 en4 0 PULSE(0 {VIH} 5n 100p 100p 1u 2u)",
        f"Vrstn rst_n 0 PULSE(0 {VIH} 300n 100p 100p 10u 20u)",
        f"Vclk clk 0 PULSE(0 {VIH} {P.T0_NS:.0f}n 100p 100p 49.8n {P.TS_NS:.0f}n)",
        "* ---- directed program: one PWL card per driven input ----",
        *input_cards(cycles, len(cycles)),
        "* ---- device under test ----",
    ]
    ports = _subckt_ports()
    body.append("Xw " + " ".join(ports) + " trng_whole")
    meas, save = measurement_cards(cycles)
    body.append("* ---- saved trace set (memory: only measured nets) ----")
    for i in range(0, len(save), 8):
        body.append(".save " + " ".join(save[i:i + 8]))
    return "\n".join(body) + "\n", meas


_SUBCKT_PORTS: list[str] | None = None


def _subckt_ports() -> list[str]:
    global _SUBCKT_PORTS
    if _SUBCKT_PORTS is None:
        lines = _netlist_text().splitlines()
        i = next(i for i, ln in enumerate(lines) if ln.startswith(".SUBCKT trng_whole"))
        ports: list[str] = []
        while i < len(lines):
            ln = lines[i]
            if ln.startswith(".SUBCKT"):
                ports += ln.split()[2:]
            elif ln.startswith("+"):
                ports += ln[1:].split()
            else:
                break
            i += 1
        _SUBCKT_PORTS = ports
    return _SUBCKT_PORTS


def make_request(name: str, outdir: Path, *, processes: list[str], temp_c: float,
                 supply: float, backend: str, analysis_args: str,
                 header: list[str], cycles: list[dict] | None = None,
                 timeout_s: int = 1800, poll_timeout_s: int | None = None) -> None:
    if cycles is None:
        cycles, _ = P.build_program()
    body, meas = deck_body(cycles, header)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "netlist.cir").write_text(body)
    request = {
        "netlist": "netlist.cir",
        "engine": "ngspice",
        "backend": backend,
        "netlist_source": "extracted",
        "models": {"pdk": PDK, "lib": LIB},
        "corners": {
            "process": processes,
            "temperature_c": [temp_c],
            "supply_v": {f"V{r}": [supply] for r in ("vdd", "vddr1", "vddr2", "vddr3", "vddr4")},
        },
        "analysis": {"kind": "tran", "args": f"{TMAX} {analysis_args}"},
        "measurements": meas,
        "options": {"timeout_s": timeout_s, "keep_artifacts": True,
                    "save_mode": "netlist"},
    }
    if poll_timeout_s is not None:
        request["batch"] = {"poll_timeout_s": poll_timeout_s}
    (outdir / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    (outdir / "plan.json").write_text(json.dumps({
        "name": name,
        "netlist_sha256": sha256_file(outdir / "netlist.cir"),
        "trng_whole_gds_sha256": sha256_file(REPO / "layout" / "trng_whole" / "trng_whole.gds"),
        "program": {"t0_ns": P.T0_NS, "ts_ns": P.TS_NS, "cycles": len(cycles),
                    "t_stop_ns": P.t_stop_ns(cycles)},
        "analysis": request["analysis"],
        "corners": request["corners"],
        "measurement_count": len(meas),
        "vih_fixed": VIH,
        "windows": {"w1_ns": list(W1), "w2_ns": [P.t_edge_ns(2), P.t_stop_ns(cycles) - P.TS_NS]},
    }, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reqdir", type=Path, help="output directory (usually corners/<id>)")
    ap.add_argument("--set", dest="which", choices=("controls", "grid"), required=True)
    args = ap.parse_args(argv)
    reqdir: Path = args.reqdir
    if reqdir.exists() and any(reqdir.iterdir()):
        ap.error(f"{reqdir} exists and is not empty; refusing to mix sets")
    if args.which == "controls":
        cut = 6
        cycles, phases = P.build_program(limit=cut)
        t_stop = P.t_stop_ns(cycles)
        hdr = [
            "post-layout-whole-block startup-probe (issue #174)",
            f"full-deck program truncated after cycle {cut - 1}; t_stop {t_stop:.0f} ns",
            "netlist body: sim/post-layout-whole-block/trng_whole.sim.spice",
        ]
        make_request("startup-probe", reqdir / "startup-probe",
                     processes=["tt"], temp_c=27.0, supply=1.8, backend="local",
                     analysis_args=f"{t_stop:.0f}n", header=hdr, cycles=cycles, timeout_s=3600)
        print(f"wrote {reqdir/'startup-probe'}")
        # the same deck on the batch fleet: the local probe did not finish in
        # 60 min on a shared 8-vCPU host (17 GB RSS), so the rate question goes
        # to the fleet (one unit; poll bounded so the caller gets a report)
        make_request("startup-probe-batch", reqdir / "startup-probe-batch",
                     processes=["tt"], temp_c=27.0, supply=1.8, backend="batch",
                     analysis_args=f"{t_stop:.0f}n", header=hdr, cycles=cycles,
                     timeout_s=3480, poll_timeout_s=3700)
        print(f"wrote {reqdir/'startup-probe-batch'}")
        return 0

    for temp, supply in GRID:
        name = f"grid-{'m' if temp < 0 else ''}{abs(temp):.0f}C-{supply:.2f}V"
        hdr = [
            f"post-layout-whole-block 12-point matrix: {temp:.0f} C, {supply:.2f} V x tt/ss/ff (issue #174)",
            f"the repo's established four-point post-layout grid; klt sim owns .lib/.temp/.tran",
        ]
        make_request(name, reqdir / name, processes=["tt", "ss", "ff"],
                     temp_c=temp, supply=supply, backend="batch", timeout_s=GRID_TIMEOUT_S, poll_timeout_s=6600,
                     analysis_args=f"{P.t_stop_ns(P.build_program()[0]):.0f}n", header=hdr)
        print(f"wrote {reqdir/name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
