#!/usr/bin/env python3
"""Generate the `klt sim` batch requests for the wake-up transient campaign (issue #216).

    make-requests.py OUTDIR [--legs det,noisy] [--probe]
    # writes OUTDIR/<name>/{netlist.cir,request.json,plan.json}
    klt sim OUTDIR/<name>/request.json -o OUTDIR/<name>/out --format json > OUTDIR/<name>/resp.json

The grid is never hand-launched with ngspice: every unit below is a `klt sim`
request, which goes to the batch fleet (KLT_SIM_BACKEND=batch). `--probe` writes
ONE single-unit request per leg for a local debug run (`--backend local`).

Leg `det` -- deterministic wake-up of design/ro_array_core.spice
---------------------------------------------------------------
Testbench `testbench/tb_wakeup_array.spice` (mode `ramp`: `tb_wakeup_array_ramp.spice`, identical but
for a PWL ramp source; the B-source ramp hit the 3000 s timeout on the fleet). One request per (mode, process
corner); each request is the full temperature x supply envelope of DR-0001 /
spec/porting-plan.md sec. 3.1 at that process corner:

    process      tt, ss, ff                       (one request each)
    temperature  -40, 27, 125 degC                (corners.temperature_c)
    supply       1.62, 1.8, 1.98 V                (knob Vk, corners.supply_v)

so 2 modes x 3 x 3 x 3 = 54 units. Modes (knob Vm): `en` = enable-gated wake
(supply up, en1..4 released at TEN), `ramp` = supply ramp 0 -> Vk over TRAMP
with en tied to the rail (no gating). Per unit the deck records the first
NEDGE + 1 rising-edge times of each buffered ring output after the anchor
(TEN, or the end of the ramp), the first rising edge at all (mode `ramp`: when,
during the ramp, the ring started), and late-window min/max of ro1..ro4.

Leg `noisy` -- first raw bits after enable, many noise seeds
------------------------------------------------------------
Testbench `testbench/tb_wakeup_raw_bits.spice`: the issue #21 raw-bit deck
topology (four rings built in place with per-stage trnoise(), the committed
ro_buf / xor2 tree / sampler_dff from design/sampler_core.spice) with the rings
HELD STOPPED until TEN_NOISY and released by a behavioural enable. A
`monte_carlo` block (vary = "mismatch") fans each corner out into NSEED samples,
each with its own `.options seed=` -- the trnoise() sources draw from that
seed. The sky130 MOS mismatch switch (`MC_MM_SWITCH`) is NOT set by the deck,
so device mismatch stays off and the only thing that differs between samples
is the injected noise realisation (the monte_carlo `family_mismatch` report in
each response says so). One request per (PVT point, chunk) so the fleet can run
chunks in parallel.
"""
import argparse, json, os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
TB_DET = os.path.join(HERE, "testbench", "tb_wakeup_array.spice")
TB_DET_RAMP = os.path.join(HERE, "testbench", "tb_wakeup_array_ramp.spice")   # PWL ramp source, mode ramp
TB_NOISY = os.path.join(HERE, "testbench", "tb_wakeup_raw_bits.spice")
ARRAY = os.path.join(REPO, "design", "ro_array_core.spice")
SAMPLER = os.path.join(REPO, "design", "sampler_core.spice")
LIB = "libs.tech/combined/sky130.lib.spice"

# ---- det leg
PROCESSES = ["tt", "ss", "ff"]
TEMPS = [-40.0, 27.0, 125.0]
SUPPLIES = [1.62, 1.8, 1.98]
TEN = 5e-9                     # enable release (mode en)
TRAMP = 1e-6                   # supply ramp duration (mode ramp)
NEDGE = 40                     # periods recorded after the anchor (NEDGE + 1 edges)
SPAN = 240e-9                  # >= (NEDGE + 2) x the slowest committed ring period (5.52 ns, ss/125C/1.62V)
LATE = 30e-9                   # late window for the swing check
TMAX_DET = "10p"
MODES = {"en": dict(vm=0.0, anchor=TEN), "ramp": dict(vm=1.0, anchor=TRAMP)}

# ---- noisy leg
TEN_NOISY = 20e-9              # enable release in the noisy deck
TS_NOISY = 100e-9              # compressed sample interval (#21's), see the deck header
NBITS_NOISY = 24               # samples after enable
TMAX_NOISY = "40p"             # #188 cross-check timestep for this deck topology
NA = "2.0e-3"                  # trnoise rms, the repo-wide anchor
# Stop time deliberately OFF the trnoise 0.2 ns grid: a local probe aborted with "Timestep too
# small" exactly at a stop time that sat on it (see the deck header's breakpoint note).
STOP_NOISY = TEN_NOISY + NBITS_NOISY * TS_NOISY + 13.7e-9
NOISY_POINTS = [               # (name, process, temp, vdd, why)
    ("ss-m40-1v62", "ss", -40.0, 1.62, "slowest / cold-SS corner and the DR-0002 entropy-binding corner"),
    ("tt-27-1v8", "tt", 27.0, 1.8, "nominal"),
    ("ff-m40-1v98", "ff", -40.0, 1.98, "fastest corner (DR-0003 combining-binding)"),
]
NSEED = 32                     # noise seeds per PVT point
CHUNK = 8                      # seeds per request
CTL_SEEDS = 4                  # negative control: NA = 0, these many seeds, at the first NOISY_POINT
MC_SEED = 216


def det_meas(anchor):
    m = []
    for r in range(1, 5):
        m.append({"name": f"tf{r}", "spice": f".meas tran tf{r} when v(ro{r})=v(half) rise=1"})
        for k in range(1, NEDGE + 2):
            m.append({"name": f"t{r}_{k}", "spice": f".meas tran t{r}_{k} when v(ro{r})=v(half) rise={k} td={anchor:.6g}"})
            # ngspice prints a .meas result to 6 significant digits, i.e. 10 ps at t ~ 1.2 us -- too coarse
            # for a 1 % period criterion at ff. A param measurement is computed from the stored double, so
            # the edge time RELATIVE to the anchor keeps ~1e-13 s resolution.
            m.append({"name": f"d{r}_{k}", "spice": f".meas tran d{r}_{k} param='t{r}_{k}-{anchor:.6g}'"})
        stop = anchor + SPAN
        m.append({"name": f"ro{r}_max", "spice": f".meas tran ro{r}_max MAX v(ro{r}) from={stop - LATE:.6g} to={stop:.6g}"})
        m.append({"name": f"ro{r}_min", "spice": f".meas tran ro{r}_min MIN v(ro{r}) from={stop - LATE:.6g} to={stop:.6g}"})
    m.append({"name": "vdd_end", "spice": f".meas tran vdd_end FIND v(vdd) AT={anchor + SPAN:.6g}"})
    return m


def det_body(mode="en"):
    t = open(TB_DET_RAMP if mode == "ramp" else TB_DET).read()
    for k, v in {"@@RO_ARRAY@@": ARRAY, "@@TEN@@": repr(TEN), "@@TRAMP@@": repr(TRAMP)}.items():
        t = t.replace(k, v)
    return t


def noisy_body(vdd, na=NA):
    t = open(TB_NOISY).read()
    for k, v in {"@@SAMPLER@@": SAMPLER, "@@VDD@@": repr(vdd), "@@NA@@": na,
                 "@@TEN@@": repr(TEN_NOISY), "@@TS@@": repr(TS_NOISY)}.items():
        t = t.replace(k, v)
    return t


def noisy_meas():
    m = []
    for k in range(NBITS_NOISY):
        # the k-th sample is captured by the clock rising edge at TEN + (k+1)*Ts - Ts/2 ... see deck; read
        # raw_bit in the latched half of the following period, as #21 does (0.25 Ts after the capturing edge)
        t = TEN_NOISY + k * TS_NOISY + 0.75 * TS_NOISY
        m.append({"name": f"bit{k}", "spice": f".meas tran bit{k} find v(raw_bit) at={t:.6g}"})
        m.append({"name": f"valid{k}", "spice": f".meas tran valid{k} find v(raw_valid) at={t:.6g}"})
        for r in range(1, 5):
            m.append({"name": f"rb{r}_{k}", "spice": f".meas tran rb{r}_{k} find v(ring_bit{r}) at={t:.6g}"})
    tend = TEN_NOISY + NBITS_NOISY * TS_NOISY
    for r in range(1, 5):
        m.append({"name": f"tf{r}", "spice": f".meas tran tf{r} when v(ro{r})=v(half) rise=1 td={TEN_NOISY:.6g}"})
        m.append({"name": f"ro{r}_max", "spice": f".meas tran ro{r}_max MAX v(ro{r}) from={tend - 200e-9:.6g} to={tend:.6g}"})
        m.append({"name": f"ro{r}_min", "spice": f".meas tran ro{r}_min MIN v(ro{r}) from={tend - 200e-9:.6g} to={tend:.6g}"})
        m.append({"name": f"ro{r}_pre", "spice": f".meas tran ro{r}_pre MAX v(ro{r}) from=1e-9 to={TEN_NOISY - 1e-9:.6g}"})
        m.append({"name": f"ro{r}_prelo", "spice": f".meas tran ro{r}_prelo MIN v(ro{r}) from=1e-9 to={TEN_NOISY - 1e-9:.6g}"})
    return m


def write(outdir, name, body, req, plan):
    d = os.path.join(outdir, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "netlist.cir"), "w").write(body)
    json.dump(req, open(os.path.join(d, "request.json"), "w"), indent=2)
    json.dump(plan, open(os.path.join(d, "plan.json"), "w"), indent=2)
    print(d, req["corners"], len(req["measurements"]), "measurements",
          f"x {req['monte_carlo']['n']} seeds" if "monte_carlo" in req else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--legs", default="det,noisy")
    ap.add_argument("--probe", action="store_true", help="one single-unit request per leg (local debug)")
    a = ap.parse_args()
    legs = a.legs.split(",")
    if "det" in legs:
        for mode, mc in MODES.items():
            body = det_body(mode)
            stop = mc["anchor"] + SPAN
            for proc in (["ss"] if a.probe else PROCESSES):
                temps = [-40.0] if a.probe else TEMPS
                sups = [1.62] if a.probe else SUPPLIES
                req = {
                    "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
                    "netlist_source": "extracted",
                    "models": {"pdk": "sky130A", "lib": LIB},
                    "corners": {"process": [proc], "temperature_c": temps,
                                "supply_v": {"Vk": sups, "Vm": [mc["vm"]] * len(sups)}},
                    "analysis": {"kind": "tran", "args": f"{TMAX_DET} {stop:.6g}"},
                    "measurements": det_meas(mc["anchor"]),
                    "options": {"timeout_s": 3000, "keep_artifacts": False},
                    "batch": {"capacity_wait_s": 3600},
                }
                plan = {"leg": "det", "mode": mode, "process": proc, "temps": temps, "supplies": sups,
                        "anchor_s": mc["anchor"], "ten_s": TEN, "tramp_s": TRAMP, "nedge": NEDGE,
                        "span_s": SPAN, "late_s": LATE, "tmax": TMAX_DET}
                write(a.outdir, f"det-{mode}-{proc}" + ("-probe" if a.probe else ""), body, req, plan)
    if "noisy" in legs:
        jobs = [(name, proc, temp, vdd, why, NA, c0, 1 if a.probe else CHUNK, "")
                for name, proc, temp, vdd, why in NOISY_POINTS
                if not a.probe or name == NOISY_POINTS[0][0]
                for c0 in range(0, 1 if a.probe else NSEED, 1 if a.probe else CHUNK)]
        if not a.probe:
            # negative control: identical deck and seeds with the injected noise switched off
            # (trnoise amplitude 0). Every seed must then produce the same bits -- proving that the
            # seed-to-seed spread of the real chunks comes from the injected noise and nothing else.
            name, proc, temp, vdd, why = NOISY_POINTS[0]
            jobs.append((name, proc, temp, vdd, why, "0", 0, CTL_SEEDS, "-ctl"))
        for name, proc, temp, vdd, why, na, c0, chunk, tag in jobs:
            if True:
                req = {
                    "netlist": "netlist.cir", "engine": "ngspice", "backend": "batch",
                    "netlist_source": "extracted",
                    "models": {"pdk": "sky130A", "lib": LIB},
                    "corners": {"process": [proc], "temperature_c": [temp]},
                    # one klt sim monte_carlo seed per chunk, so every chunk's samples have distinct derived seeds
                    "monte_carlo": {"n": chunk, "seed": MC_SEED * 1000 + c0, "vary": "mismatch"},
                    "analysis": {"kind": "tran",
                                 "args": f"{TMAX_NOISY} {STOP_NOISY:.6g} uic"},
                    "measurements": noisy_meas(),
                    "options": {"timeout_s": 6000, "keep_artifacts": False},
                    "batch": {"capacity_wait_s": 3600},
                }
                plan = {"leg": "noisy", "point": name, "process": proc, "temp": temp, "vdd": vdd, "why": why,
                        "ten_s": TEN_NOISY, "ts_s": TS_NOISY, "nbits": NBITS_NOISY, "na": na, "tmax": TMAX_NOISY,
                        "control": bool(tag), "chunk_first_seed_index": c0, "n": chunk}
                write(a.outdir, f"noisy-{name}-{tag[1:] if tag else c0 // chunk + 1}" + ("-probe" if a.probe else ""),
                      noisy_body(vdd, na), req, plan)


if __name__ == "__main__":
    main()
