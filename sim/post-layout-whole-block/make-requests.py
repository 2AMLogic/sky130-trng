#!/usr/bin/env python3
"""Assemble the whole-block klt sim requests (issue #174).

Writes ``<reqdir>/<name>/{netlist.cir,request.json,plan.json}`` for the selected set:

``--set controls``
    ``startup-probe`` -- the full deck truncated after the first program
    phases, one corner (``tt``, 27 C, 1.8 V), ``backend: local``. Run it
    locally first: it proves the flat netlist parses, the DC start-up
    converges, the rings start, reset releases and the first bus reads
    return before the 12-point grid is submitted to the batch fleet, and
    its wall-clock is the compute-budget measurement the record cites.

``--set rate-probe``
    one short batch unit (issue #403) reporting simulated time reached.

``--set coupled-probe`` / ``--set coupled-full``
    One nominal batch unit with the transistor sampler driving the archived
    timed gate model. The 100 ns probe gates the full 7,870 ns run (#596).

``--set grid``
    one request per (T, Vdd) point of this repo's established four-point
    post-layout grid -- (-40 C, 1.62 V), (27 C, 1.8 V), (-40 C, 1.98 V),
    (125 C, 1.98 V) -- each bundling the ``tt``/``ss``/``ff`` process axis
    (4 requests x 3 corners = the full 12-point matrix), ``backend: batch``:
    a ``klt sim`` corners request goes to the batch fleet; this is never a
    hand-launched local ngspice grid. Since issue #595 each request's
    ``plan.json`` also carries ``gate_model_pvt``: the Liberty deck
    (path + sha256, per process corner) the digital half's gate model uses
    at that point plus the boundary-load option, from ``pvt_deck_map.py``.
    Its two timeouts are sized from the measured coupled run
    (``records/20261128-coupled-rate.md``): one request is one batch job of
    three units, whose bound must fit the fleet's whole-job ceiling, and
    generation refuses what it cannot hold. **The deck this set emits is still
    the flat transistor-level whole block**, which timed out at the 3480 s
    ceiling twice; the timeouts are those of the coupled deck the matrix runs
    under DR-0017 option (b) (issue #307).

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
import gzip
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "layout" / "bin"))
from _hashing import sha256_file, sha256_text  # noqa: E402
from _klt_common import libs_ref  # noqa: E402
sys.path.insert(0, str(HERE))
import program as P  # noqa: E402
import pvt_deck_map as PVT  # noqa: E402
# the deck's measurement sets and shared constants are program.py's (#804);
# re-exported here under the names this generator's callers use
from program import (  # noqa: E402
    RAILS,
    ROUTED_V,
    VIH,
    W1,
    coupled_measurements,
    whole_block_measurement_cards as measurement_cards,
)

NETLIST_BODY = HERE / "trng_whole.sim.spice"
NETLIST_GZ = HERE / "trng_whole.sim.spice.gz"

LIB = "libs.tech/combined/sky130.lib.spice"
PDK = "sky130A"
TMAX = "20p"

#: the repo's established four-point post-layout grid x tt/ss/ff (12 points)
GRID = [(-40.0, 1.62), (27.0, 1.8), (-40.0, 1.98), (125.0, 1.98)]

#: The batch fleet's whole-job ceiling and klt's per-job overhead (s). A job's
#: bound is ``timeout_s * units + 120``, so a one-unit job may give its worker
#: at most 3480 s (records/20261121-coupled-rate.md).
FLEET_JOB_CEILING_S = 3600
BATCH_OVERHEAD_S = 120
UNIT_TIMEOUT_CAP_S = FLEET_JOB_CEILING_S - BATCH_OVERHEAD_S
#: measured coupled whole-block runtime (s) for the 7,870 ns program at
#: tt / 27 C / 1.8 V on the batch fleet, job klt-sim-7d6f0e6f474f
#: (records/20261128-coupled-rate.md)
COUPLED_FULL_RUNTIME_S = 431.63
#: allowance on that runtime for the grid's unmeasured points (ss/ff,
#: -40..125 C, 1.62..1.98 V). Declared, not measured: no coupled run exists at
#: any other corner.
GRID_MARGIN_X = 2.0
#: instance boot, staging and collection around the simulation (36.7 s on the
#: 100 ns probe job, 15.4 s on the full job), widened
JOB_SLACK_S = 300
#: where the grid timeouts come from; written into every grid plan.json
GRID_TIMEOUT_RECORD = "records/20261128-coupled-rate.md"


def grid_timeouts() -> tuple[int, int]:
    """``(timeout_s, poll_timeout_s)`` of a grid request, from the measured coupled run.

    One grid request is one batch job of one unit per process corner. The
    unit timeout is the measured nominal runtime times ``GRID_MARGIN_X``; the
    job's serial bound must fit the fleet's ceiling; the caller waits for that
    bound plus ``JOB_SLACK_S``. Raises ``ValueError`` when it does not fit: a
    request the fleet would kill at the ceiling is not written.
    """
    units = len(PVT.MATRIX_PROCESSES)
    timeout_s = math.ceil(GRID_MARGIN_X * COUPLED_FULL_RUNTIME_S)
    if timeout_s > UNIT_TIMEOUT_CAP_S:
        raise ValueError(f"grid unit timeout {timeout_s} s: one unit can hold at most "
                         f"{UNIT_TIMEOUT_CAP_S:.0f} s")
    bound_s = units * timeout_s + BATCH_OVERHEAD_S
    if bound_s > FLEET_JOB_CEILING_S:
        raise ValueError(f"grid job bound {bound_s} s: {units} units exceed the "
                         f"{FLEET_JOB_CEILING_S:.0f} s fleet ceiling")
    return timeout_s, bound_s + JOB_SLACK_S


GRID_TIMEOUT_S, GRID_POLL_TIMEOUT_S = grid_timeouts()


def grid_timeout_basis() -> dict:
    """The grid timeouts and what they were sized from, for every grid ``plan.json``."""
    timeout_s, poll_s = grid_timeouts()
    return {"timeout_s": timeout_s, "poll_timeout_s": poll_s, "sized_from": GRID_TIMEOUT_RECORD,
            "measured_runtime_s": COUPLED_FULL_RUNTIME_S, "measured_point": "tt / 27 C / 1.8 V",
            "measured_simulated_ns": float(P.t_stop_ns(P.build_program()[0])),
            "margin_x": GRID_MARGIN_X, "job_slack_s": JOB_SLACK_S,
            "job_bound_s": len(PVT.MATRIX_PROCESSES) * timeout_s + BATCH_OVERHEAD_S,
            "fleet_job_ceiling_s": FLEET_JOB_CEILING_S}

EDGE_NS = P.PWL_EDGE_NS


def _netlist_text() -> str:
    """The committed netlist body (gzip is the committed form; a plain copy wins if present)."""
    if NETLIST_BODY.exists():
        return NETLIST_BODY.read_text()
    return gzip.decompress(NETLIST_GZ.read_bytes()).decode()


#: analog-chain probe (issue #431): the extract's device comments carry the
#: composed-frame (x, y) um; the analog macro (sampler_core) is placed at
#: origin y = 268.64 and the digital macro occupies y < 250 (the device-y
#: histogram has an empty band 240-260 um), so a y cut separates them.
ANALOG_Y_MIN_UM = 250.0
_DEV_RE = re.compile(r"^\* device instance \S+ \S+ \*1 ([-\d.]+),([-\d.]+) ")


def _partition_netlist_text(keep_analog: bool) -> str:
    """The flat netlist with only one macro's devices (the other absent)."""
    out: list[str] = []
    keep = True
    for ln in _netlist_text().splitlines():
        if ln.startswith("* device instance"):
            m = _DEV_RE.match(ln)
            assert m, ln
            y = float(m.group(2))
            keep = y >= ANALOG_Y_MIN_UM if keep_analog else y < ANALOG_Y_MIN_UM
        elif ln.upper().startswith(".ENDS"):
            keep = True
        if keep:
            out.append(ln)
    return "\n".join(out) + "\n"


def analog_netlist_text() -> str:
    """The flat netlist with only the analog-macro devices (digital absent).

    Digital pins (raw_bit/raw_valid sinks, buses) are left unloaded -- the
    boundary is open, which is the 'absent' option of DR-0017's feasibility
    gate. Header, ports and net names are unchanged.
    """
    return _partition_netlist_text(keep_analog=True)


def digital_netlist_text() -> str:
    """The complementary partition: devices with composed y < ANALOG_Y_MIN_UM.

    This is the transistor-level view of the digital macro in the flat extract;
    it is used for the partition check only. The digital half of a (b) run is the
    gate-level ``layout/trng_digital/trng_digital.routed.v`` (hashed in plan.json).
    """
    return _partition_netlist_text(keep_analog=False)


def _device_blocks(text: str) -> list[tuple[str, set[str]]]:
    """[(model, nets)] per ``* device instance`` block of a netlist."""
    blocks: list[list[str]] = []
    for ln in text.splitlines():
        if ln.startswith("* device instance"):
            blocks.append([])
        elif blocks and not ln.upper().startswith(".ENDS"):
            blocks[-1].append(ln[1:] if ln.startswith("+") else ln)
    res = []
    for b in blocks:
        toks = " ".join(b).split()
        model = next(t for t in toks if t.startswith("sky130_fd_pr__"))
        nets = {t for t in toks[1:] if "=" not in t and not t.startswith("sky130_fd_pr__")}
        res.append((model, nets))
    return res


def partition_check() -> dict:
    """Check that analog + digital partitions reproduce the flat whole extract.

    * instance count: every X-instance of the flat extract is in exactly one
      partition (25 356 = 25 355 transistors + the antenna diode);
    * port correspondence: the flat ``.SUBCKT`` ports are the canonical ports
      of ``trng_whole.sim.ports.json``, and each is a boundary_signals() member;
    * net correspondence: the nets the two partitions share (excluding supplies)
      are exactly the boundary nets the analog side and digital side both touch.

    Returns the three DR-0017 hashes with the counts. Raises AssertionError on
    any mismatch (a mismatch must never be recorded as a partition).
    """
    flat, ana, dig = _netlist_text(), analog_netlist_text(), digital_netlist_text()
    fb, ab, db = _device_blocks(flat), _device_blocks(ana), _device_blocks(dig)
    assert len(ab) + len(db) == len(fb), (len(ab), len(db), len(fb))
    is_tr = lambda m: not m.startswith("sky130_fd_pr__diode")  # noqa: E731
    n_tr = lambda blocks: sum(1 for m, _ in blocks if is_tr(m))  # noqa: E731
    assert n_tr(ab) + n_tr(db) == n_tr(fb)
    ports = [re.sub(r"_(\d+)_$", r"[\1]", q) for q in _subckt_ports()]
    declared = sorted(p["canonical"] for p in json.loads(
        (HERE / "trng_whole.sim.ports.json").read_text())["ports"])
    assert sorted(ports) == declared, "flat .SUBCKT ports differ from trng_whole.sim.ports.json"
    base = {re.sub(r"\[\d+\]$", "", p) for p in declared}
    bs = P.boundary_signals()
    inter = {n for n, v in bs.items() if v["dir"] == "analog->digital"}  # internal nets, not ports
    assert base == set(bs) - inter, "boundary_signals() differs from the port list"
    a_nets = set().union(*(n for _, n in ab))
    d_nets = set().union(*(n for _, n in db))
    # internal inter-macro nets keep the extractor's '|'-joined cluster name
    # (e.g. 'A|a|...|raw_bit|y'); the boundary signal is the segment that names it
    known = set(P.boundary_signals())
    norm = lambda n: next((x for x in n.split("|") if x in known), n)  # noqa: E731
    shared = sorted(norm(n) for n in a_nets & d_nets if n not in ("vdd", "vss"))
    # the nets both halves touch are exactly the inter-macro and shared-input
    # boundary signals (clk/rst_n reach both; raw_bit/raw_valid cross)
    expected = sorted(n for n, v in bs.items() if v["dir"] in ("analog->digital", "tb->both"))
    assert shared == expected, f"shared nets {shared} != boundary {expected}"
    return {
        "flat_whole_netlist_sha256": sha256_text(flat),
        "analog_partition_sha256": sha256_text(ana),
        "digital_gate_netlist_sha256": sha256_file(ROUTED_V),
        "total_instances": len(fb),
        "analog_transistors": n_tr(ab),
        "digital_transistors": n_tr(db),
        "diode_instances": sum(1 for m, _ in fb if not is_tr(m)),
        "shared_nets": shared,
        "port_count": len(declared),
        "analog_y_min_um": ANALOG_Y_MIN_UM,
    }


def input_cards(cycles: list[dict], n_cycles: int) -> list[str]:
    return P.input_cards(cycles, n_cycles, VIH)


#: rate-probe (issue #403): .tran stop (ns). Rings start at 5 ns, the clock at
#: T0_NS, so this covers DC start-up + ring oscillation only; short enough to
#: finish inside one unit ceiling and yield a sec-per-ns figure.
RATE_PROBE_STOP_NS = 100.0
RATE_PROBE_FROM_NS = 20.0
#: analog-chain probe (issue #431): rings from 5 ns, clock from T0_NS (320 ns).
ANALOG_PROBE_STOP_NS = 500.0


def rate_probe_measurements(t_stop: float) -> tuple[list[dict], list[str]]:
    """Measurements for the rate probe; every one bounded by ``t_stop``."""
    assert RATE_PROBE_FROM_NS < t_stop
    f, t = f"{RATE_PROBE_FROM_NS:.0f}n", f"{t_stop:.0f}n"
    meas = [{"name": f"i_{r}_probe",
             "spice": f".meas tran i_{r}_probe AVG i(V{r}) FROM={f} TO={t}"}
            for r in ("vdd", "vddr1", "vddr2", "vddr3", "vddr4")]
    meas += [{"name": f"v_ring_bit{i}_end",
              "spice": f".meas tran v_ring_bit{i}_end FIND v(ring_bit{i}) AT={t}"}
             for i in (1, 2, 3, 4)]
    save = ["vdd", "vss", "vddr1", "vddr2", "vddr3", "vddr4",
            "ring_bit1", "ring_bit2", "ring_bit3", "ring_bit4"]
    save += [f"i(V{r})" for r in ("vdd", "vss", "vddr1", "vddr2", "vddr3", "vddr4")]
    return meas, sorted(save)


def nominal_gate_model() -> tuple[str, dict]:
    """Use the measured nominal gate model, with its exact bridges and input loads."""
    base = Path("corners/gate-model-full")
    manifest_path = base / "gate-model.manifest.json"
    manifest = json.loads((HERE / manifest_path).read_text())
    plan = json.loads((HERE / base / "plan.json").read_text())
    gate = gzip.decompress((HERE / "runs/20261114-gate-model-full/gate-model.cir.gz").read_bytes()).decode()
    if (sha256_text(gate) != plan["gate_model_sha256"]
            or sha256_file(ROUTED_V) != manifest["source_netlist_sha256"]
            or manifest["source_netlist_sha256"] != plan["routed_netlist_sha256"]
            or manifest["liberty_sha256"] != plan["liberty_sha256"]):
        raise ValueError("nominal model, routed Verilog or Liberty identity differs from the gate record")
    return gate, {"gate_manifest": str(manifest_path), "gate_model_sha256": sha256_text(gate),
                  "liberty_sha256": manifest["liberty_sha256"], "liberty_deck": manifest["liberty_deck"],
                  "realisation": manifest["realisation"],
                  "reductions": {
                      **manifest["reductions"],
                      # the manifest text predates #595 (kept byte-stable as #486
                      # evidence); in a plan it must agree with boundary_load_option.
                      # Same wording as make-gate-model.py's plan writer.
                      "input_load": "Liberty input-pin capacitance per d_genlut input; the "
                                    "DR-0017 boundary-load choice is settled as option 2 "
                                    "(#595, see boundary_load_option)",
                  },
                  "boundary_load_option": PVT.boundary_load_block(),
                  "raw_source": "analog_sampler"}


def coupled_analog() -> tuple[str, list[str]]:
    """Export each actual extracted sampler cluster as an additional positional port."""
    analog = analog_netlist_text()
    header, marker, devices = analog.partition("* device instance")
    nets = set().union(*(pins for _, pins in _device_blocks(analog)))
    outputs = [n for n, spec in P.boundary_signals().items() if spec["dir"] == "analog->digital"]
    pins = []
    for name in outputs:
        matches = [net for net in nets if name in net.split("|")]
        if len(matches) != 1:
            raise ValueError(f"expected one sampler cluster for {name}, got {matches}")
        pins.extend(matches)
    return header + "+ " + " ".join(pins) + "\n" + marker + devices, outputs


def deck_body(cycles: list[dict], header: list[str], rate_probe_stop: float | None = None,
              analog_only: bool = False, gate: str | None = None):
    ports = list(_subckt_ports())
    if gate is not None:
        analog, outputs = coupled_analog()
        ports.extend(outputs)
    else:
        analog = analog_netlist_text() if analog_only else _netlist_text()
    body = ["* " + line for line in header]
    body += [
        "",
        ".option scale=1u",
        "",
        analog.rstrip("\n"),
        "",
        "* ---- supplies (corners.supply_v alters the named sources) ----",
        *(gate.splitlines() if gate is not None else ["Vvdd vdd 0 dc 1.8", "Vvss vss 0 dc 0"]),
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
        *P.input_cards(cycles, len(cycles), VIH, coupled=gate is not None),
        "* ---- device under test ----",
    ]
    body.append("Xw " + " ".join(ports) + " trng_whole")
    if rate_probe_stop is not None:
        meas, save = rate_probe_measurements(rate_probe_stop)
    elif gate is not None:
        meas, save = coupled_measurements(cycles)
    else:
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


_UNSET = object()
_LIBS_REF: Path | None | object = _UNSET


def _best_effort_libs_ref() -> Path | None:
    """The PDK's ``libs.ref`` when the install is resolvable, else None.

    Only the deck sha256 verification and the absolute deck path in
    ``plan.json.gate_model_pvt`` need it (issue #595): with None the plan
    records the install-relative path and the committed table's sha256 --
    equal to the on-disk hash whenever the install matches the pin, which
    ``pvt_deck_map.verify_against_disk`` checks wherever the PDK exists
    (real runs, the PDK-gated test). Best-effort so CI's klt-free unit
    tests keep generating the grid set; a RESOLVED install with a wrong
    hash still fails closed inside ``plan_entry``.
    """
    global _LIBS_REF
    if _LIBS_REF is _UNSET:
        try:
            _LIBS_REF = libs_ref(PDK, klt="klt", timeout=120)
        except Exception:
            _LIBS_REF = None
    return _LIBS_REF  # type: ignore[return-value]


def make_request(name: str, outdir: Path, *, processes: list[str], temp_c: float,
                 supply: float, backend: str, analysis_args: str,
                 header: list[str], cycles: list[dict] | None = None,
                 timeout_s: int = 1800, poll_timeout_s: int | None = None,
                 rate_probe_stop: float | None = None,
                 analog_only: bool = False, coupled: bool = False,
                 gate_model_pvt: dict | None = None, timeouts: dict | None = None) -> None:
    if cycles is None:
        cycles, _ = P.build_program()
    if coupled and (processes != ["tt"] or temp_c != 27.0 or supply != VIH):
        raise ValueError("the recorded gate model is only for the tt / 27 C / 1.8 V rate experiment")
    gate, plan_fields = nominal_gate_model() if coupled else (None, {})
    if coupled:
        plan_fields["analysis_stop_ns"] = rate_probe_stop or P.t_stop_ns(cycles)
    else:
        plan_fields["windows"] = {"w1_ns": list(W1), "w2_ns": [P.t_edge_ns(2), P.t_stop_ns(cycles) - P.TS_NS]}
    body, meas = deck_body(cycles, header, rate_probe_stop, analog_only, gate)
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
            "supply_v": {f"V{r}": [supply] for r in RAILS},
        },
        "analysis": {"kind": "tran", "args": f"{TMAX} {analysis_args}"},
        "measurements": meas,
        "options": {"timeout_s": timeout_s, "keep_artifacts": True,
                    "save_mode": "netlist"},
    }
    if poll_timeout_s is not None:
        request["batch"] = {"poll_timeout_s": poll_timeout_s}
    (outdir / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    plan = {
        "name": name,
        "netlist_sha256": sha256_file(outdir / "netlist.cir"),
        "trng_whole_gds_sha256": sha256_file(REPO / "layout" / "trng_whole" / "trng_whole.gds"),
        "program": {"t0_ns": P.T0_NS, "ts_ns": P.TS_NS, "cycles": len(cycles),
                    "t_stop_ns": P.t_stop_ns(cycles)},
        "analysis": request["analysis"],
        "corners": request["corners"],
        "measurement_count": len(meas),
        "vih_fixed": VIH,
        "provenance": P.PROVENANCE,
        **_partition_plan(),
        **plan_fields,
    }
    if gate_model_pvt is not None:
        # issue #595: the digital half's deck per process corner of THIS
        # request plus the boundary-load option, one block per request
        plan["gate_model_pvt"] = gate_model_pvt
    if timeouts is not None:
        # issues #431 / #596: what the request's two timeouts were sized from
        plan["timeouts"] = timeouts
    (outdir / "plan.json").write_text(json.dumps(
        plan, indent=2, sort_keys=True) + "\n")


_PARTITION: dict | None = None


def _partition_plan() -> dict:
    """DR-0017 plan.json fields: the three hashes + the partition check result.

    Computed once; ``partition_check`` raises (no plan is written) if analog +
    digital do not reproduce the whole extract.
    """
    global _PARTITION
    if _PARTITION is None:
        _PARTITION = partition_check()
    pc = _PARTITION
    return {k: pc[k] for k in ("flat_whole_netlist_sha256", "analog_partition_sha256",
                               "digital_gate_netlist_sha256")} | {
        "partition_check": {k: v for k, v in pc.items() if not k.endswith("_sha256")}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reqdir", type=Path, help="output directory (usually corners/<id>)")
    ap.add_argument("--set", dest="which", required=True, choices=(
        "controls", "grid", "rate-probe", "analog-probe", "coupled-probe", "coupled-full"))
    args = ap.parse_args(argv)
    reqdir: Path = args.reqdir
    if reqdir.exists() and any(reqdir.iterdir()):
        ap.error(f"{reqdir} exists and is not empty; refusing to mix sets")
    if args.which in ("coupled-probe", "coupled-full"):
        cycles, _ = P.build_program()
        probe = args.which == "coupled-probe"
        stop = RATE_PROBE_STOP_NS if probe else P.t_stop_ns(cycles)
        make_request(args.which, reqdir / args.which, processes=["tt"], temp_c=27.0,
                     supply=1.8, backend="batch", analysis_args=f"{stop:.0f}n",
                     header=[f"DR-0017 nominal coupled rate experiment: {args.which}"],
                     # 3360 s worker + 120 s batch overhead fits the 3480 s ceiling.
                     cycles=cycles, timeout_s=3360, poll_timeout_s=3480,
                     rate_probe_stop=stop if probe else None, coupled=True)
        print(f"wrote {reqdir / args.which}")
        return 0
    if args.which == "analog-probe":
        # issue #431 Step 1 (DR-0017 feasibility gate): analog chain only
        # (rings + sampler, 264 transistors), digital absent; one batch unit.
        cycles, _ = P.build_program(limit=6)
        stop = ANALOG_PROBE_STOP_NS
        hdr = ["post-layout-whole-block analog-chain probe (issue #431)",
               f".tran stop {stop:.0f} ns: rings + sampler transistor-level, digital absent",
               f"devices with composed y >= {ANALOG_Y_MIN_UM:.0f} um only"]
        make_request("analog-probe-batch", reqdir / "analog-probe-batch",
                     processes=["tt"], temp_c=27.0, supply=1.8, backend="batch",
                     analysis_args=f"{stop:.0f}n", header=hdr, cycles=cycles,
                     timeout_s=3480, poll_timeout_s=3700, rate_probe_stop=stop,
                     analog_only=True)
        print(f"wrote {reqdir/'analog-probe-batch'}")
        return 0
    if args.which == "rate-probe":
        # issue #403: one short batch unit; the 970 ns probe timed out at 3480 s
        # with zero measurements, so this one reports how far time got instead.
        cycles, _ = P.build_program(limit=6)
        stop = RATE_PROBE_STOP_NS
        hdr = ["post-layout-whole-block rate-probe (issue #403)",
               f".tran stop {stop:.0f} ns: DC start-up + rings only, before the clock",
               "netlist body: sim/post-layout-whole-block/trng_whole.sim.spice"]
        make_request("rate-probe-batch", reqdir / "rate-probe-batch",
                     processes=["tt"], temp_c=27.0, supply=1.8, backend="batch",
                     analysis_args=f"{stop:.0f}n", header=hdr, cycles=cycles,
                     timeout_s=3480, poll_timeout_s=3700, rate_probe_stop=stop)
        print(f"wrote {reqdir/'rate-probe-batch'}")
        return 0
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

    # issues #431 / #596: the measured coupled run sizes the grid and refuses
    # what the fleet's ceiling cannot hold, before anything is written
    timeout_s, poll_timeout_s = grid_timeouts()
    processes, timeout_basis = list(PVT.MATRIX_PROCESSES), grid_timeout_basis()
    for temp, supply in GRID:
        name = f"grid-{'m' if temp < 0 else ''}{abs(temp):.0f}C-{supply:.2f}V"
        hdr = [
            f"post-layout-whole-block 12-point matrix: {temp:.0f} C, {supply:.2f} V x tt/ss/ff (issue #174)",
            f"the repo's established four-point post-layout grid; klt sim owns .lib/.temp/.tran",
        ]
        # issue #595: each request's plan records the digital half's Liberty
        # deck per process corner and the boundary-load option (option 2).
        # Unmapped points fail closed here; a resolved-but-changed install
        # fails closed inside plan_entry's sha256 check.
        gate_pvt = PVT.plan_entry(processes, temp, supply, libs_ref_dir=_best_effort_libs_ref())
        make_request(name, reqdir / name, processes=processes,
                     temp_c=temp, supply=supply, backend="batch", timeout_s=timeout_s,
                     poll_timeout_s=poll_timeout_s,
                     analysis_args=f"{P.t_stop_ns(P.build_program()[0]):.0f}n", header=hdr,
                     gate_model_pvt=gate_pvt, timeouts=timeout_basis)
        print(f"wrote {reqdir/name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
