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
    One coupled request per point of the 12-point matrix (issue #815):
    ``tt``/``ss``/``ff`` x (-40 C, 1.62 V), (27 C, 1.8 V), (-40 C, 1.98 V),
    (125 C, 1.98 V), each ``grid-<proc>-<m40C|27C|125C>-<supply>V`` and
    ``backend: batch``. One request embeds one netlist, and a gate model is
    per point, so each request is a single-process batch job of one unit
    (``grid_timeouts(units=1)``): 864 s unit timeout, 984 s job bound, 1284 s
    poll, from the measured coupled run (``records/20261128-coupled-rate.md``).
    The deck is the DR-0017 option (b) coupled deck -- the extracted analog
    partition driving the routed gate model built for THAT point from the
    Liberty deck ``pvt_deck_map.py`` maps it to (the 8 distinct decks are
    parsed once) -- with the 75-cycle program, the fixed 1.8 V input-high
    convention and the sampler as the sole source of both raw signals, plus
    the ring-rail W1/W2 currents and the throughput tap
    (``program.coupled_matrix_measurements``). Its ``plan.json`` records the
    three partition hashes, the emitted netlist, gate model and Liberty
    sha256s and the point's ``gate_model_pvt`` deviations. Needs the PDK's
    decks: resolved through ``klt pdk find``, or given explicitly with
    ``--libs-ref <dir>`` (a sky130A install's ``libs.ref``); with neither,
    generation refuses before writing anything. The four committed
    ``corners/grid-*`` requests are the archived FLAT-deck grid (three
    processes per request, 21,600 s / 6,600 s) and are never regenerated.

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
# the gate model the coupled decks drive is the generator's emitter, imported
# (never the sibling CLI executed, #804): one model per matrix point (#815)
from gate_model_lib import (  # noqa: E402
    DEFAULT_PORT_LOAD_PF,
    DEFAULT_SLEW_NS,
    GateModelError,
    build_gate_model,
    load_liberty_cells,
    parse_verilog,
)
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
#: any other corner. #814 re-derives it from the slow-corner measurement.
GRID_MARGIN_X = 2.0
#: instance boot, staging and collection around the simulation (36.7 s on the
#: 100 ns probe job, 15.4 s on the full job), widened
JOB_SLACK_S = 300
#: where the grid timeouts come from; written into every grid plan.json
GRID_TIMEOUT_RECORD = "records/20261128-coupled-rate.md"
#: one grid request is one batch job of ONE unit (#815): the deck embeds one
#: gate model, and a gate model is per point, so the matrix is 12
#: single-process requests. The archived flat grid bundled tt/ss/ff per
#: request (three units); ``grid_timeouts(units=3)`` still sizes that shape.
GRID_UNITS = 1


def grid_timeouts(units: int = GRID_UNITS) -> tuple[int, int]:
    """``(timeout_s, poll_timeout_s)`` of a grid request of ``units`` units,
    from the measured coupled run.

    The unit timeout is the measured nominal runtime times ``GRID_MARGIN_X``;
    the job's serial bound (``units`` x that, plus klt's overhead) must fit
    the fleet's ceiling; the caller waits for that bound plus
    ``JOB_SLACK_S``. Raises ``ValueError`` when it does not fit: a request the
    fleet would kill at the ceiling is not written.
    """
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


def grid_timeout_basis(units: int = GRID_UNITS) -> dict:
    """The grid timeouts and what they were sized from, for every grid ``plan.json``."""
    timeout_s, poll_s = grid_timeouts(units)
    return {"timeout_s": timeout_s, "poll_timeout_s": poll_s, "sized_from": GRID_TIMEOUT_RECORD,
            "measured_runtime_s": COUPLED_FULL_RUNTIME_S, "measured_point": "tt / 27 C / 1.8 V",
            "measured_simulated_ns": float(P.t_stop_ns(P.build_program()[0])),
            "margin_x": GRID_MARGIN_X, "job_slack_s": JOB_SLACK_S,
            "units": units, "job_bound_s": units * timeout_s + BATCH_OVERHEAD_S,
            "fleet_job_ceiling_s": FLEET_JOB_CEILING_S}


#: the repo's established four-point post-layout grid x tt/ss/ff (12 points);
#: the request directories of ``--set grid``, named for the reducer's
#: ``grid-*`` scan (one process per request since #815)
GRID = [(-40.0, 1.62), (27.0, 1.8), (-40.0, 1.98), (125.0, 1.98)]


def grid_name(proc: str, temp_c: float, supply_v: float) -> str:
    """``grid-ss-m40C-1.62V``: the ``--set grid`` request directory of one
    matrix point (the archived flat grid's ``grid-m40C-1.62V`` carries no
    process, so the two families never collide)."""
    return f"grid-{proc}-{'m' if temp_c < 0 else ''}{abs(temp_c):.0f}C-{supply_v:.2f}V"

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


#: the plan-level wording of the gate model's ``input_load`` reduction: the
#: manifest text predates #595 (kept byte-stable as #486 evidence); in a plan
#: it must agree with ``boundary_load_option``. Same wording as
#: make-gate-model.py's plan writer.
INPUT_LOAD_SETTLED = ("Liberty input-pin capacitance per d_genlut input; the "
                      "DR-0017 boundary-load choice is settled as option 2 "
                      "(#595, see boundary_load_option)")


class CoupledDeck:
    """The digital half of a coupled request: the gate-level body the analog
    partition drives, the ``plan.json`` fields that identify it, and the
    deck's measurement set (``program.py``'s, over the full program)."""

    def __init__(self, text: str, fields: dict, measurements):
        self.text = text
        self.fields = fields
        self._measurements = measurements

    def measurements(self, cycles: list[dict]) -> tuple[list[dict], list[str]]:
        return self._measurements(cycles)


def nominal_gate_model() -> CoupledDeck:
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
    return CoupledDeck(gate, {
        "gate_manifest": str(manifest_path), "gate_model_sha256": sha256_text(gate),
        "liberty_sha256": manifest["liberty_sha256"], "liberty_deck": manifest["liberty_deck"],
        "realisation": manifest["realisation"],
        "reductions": {**manifest["reductions"], "input_load": INPUT_LOAD_SETTLED},
        "boundary_load_option": PVT.boundary_load_block(),
        "raw_source": "analog_sampler"}, P.coupled_measurements)


class _DeckCache:
    """The Liberty cells of each distinct deck the matrix points map to,
    parsed once per generation (8 decks serve the 12 points, #815), each deck
    verified against its pinned sha256 before it is read -- the same guard
    ``make-gate-model.py --point`` applies, so an install that is not the PDK
    ``pvt_deck_map.py`` was derived from fails closed here too."""

    def __init__(self, libs_ref_dir: Path, wanted: set[str]):
        self.libs_ref_dir = Path(libs_ref_dir)
        self.wanted = wanted
        self._cells: dict[str, tuple[dict, float]] = {}

    def cells_for(self, row: dict) -> tuple[Path, dict, float]:
        path = (self.libs_ref_dir / PVT.LIB_SUBDIR / row["liberty_deck"]).resolve()
        if not path.is_file():
            raise PVT.DeckMapError(f"pinned deck {row['liberty_deck']} is absent from "
                                   f"{self.libs_ref_dir} (PDK version bump?)")
        if row["liberty_deck"] not in self._cells:
            lib_sha = sha256_file(path)
            if lib_sha != row["liberty_sha256"]:
                raise PVT.DeckMapError(
                    f"{row['liberty_deck']}: on-disk sha256 {lib_sha} != pinned "
                    f"{row['liberty_sha256']} -- the install is not the PDK the "
                    "table was derived from; re-derive the mapping (issue #595), "
                    "do not ignore the mismatch")
            self._cells[row["liberty_deck"]] = load_liberty_cells(
                path, self.wanted, P.EXPECTED_THRESHOLD_PCT)
        cells, threshold_pct = self._cells[row["liberty_deck"]]
        return path, cells, threshold_pct


def point_gate_models(libs_ref_dir: Path) -> dict[tuple[str, float, float], CoupledDeck]:
    """``{(process, temp_c, supply_v): CoupledDeck}`` for the 12 matrix points.

    Each digital half is the generator's emitter (``gate_model_lib``) applied
    to the routed Verilog at the point's supply, from the Liberty deck
    ``pvt_deck_map.py`` maps the point to, at the nominal model's operating
    point (slew, port load) so every point's model is the measured nominal
    one re-cornered and nothing else. An unmapped point raises
    ``DeckMapError`` -- and nothing has been written.
    """
    design = parse_verilog(ROUTED_V)
    decks = _DeckCache(libs_ref_dir, set(design.cell_histogram()))
    out: dict[tuple[str, float, float], CoupledDeck] = {}
    for temp, supply in GRID:
        for proc in PVT.MATRIX_PROCESSES:
            row = PVT.deck_row(proc, temp, supply)
            path, cells, threshold_pct = decks.cells_for(row)
            model = build_gate_model(
                design, cells, supply_v=supply, slew_ns=DEFAULT_SLEW_NS,
                port_load_pf=DEFAULT_PORT_LOAD_PF, liberty_path=path,
                liberty_sha256=row["liberty_sha256"], threshold_pct=threshold_pct)
            m = model.manifest
            out[(proc, temp, supply)] = CoupledDeck(model.text(), {
                "gate_model_sha256": sha256_text(model.text()),
                "routed_netlist_sha256": m["source_netlist_sha256"],
                "liberty_deck": str(path), "liberty_sha256": row["liberty_sha256"],
                "realisation": m["realisation"],
                "gate_model_counts": {
                    "routed_instances": m["routed_instances"],
                    "primitives": m["primitives"],
                    "polarity_inverters": m["polarity_inverters"],
                    "declared_no_op_instances": len(m["declared_no_op_instances"]),
                    "widest_genlut_inputs": m["widest_genlut_inputs"]},
                "reductions": {**m["reductions"], "input_load": INPUT_LOAD_SETTLED},
                "boundary_load_option": PVT.boundary_load_block(),
                "raw_source": "analog_sampler"},
                lambda cycles, supply=supply: P.coupled_matrix_measurements(cycles, supply))
    return out


_UNSET = object()
_KLT_LIBS_REF: Path | None | object = _UNSET


def resolve_libs_ref(explicit: str | None) -> Path | None:
    """Where the PDK's decks come from: ``--libs-ref`` (a sky130A install's
    ``libs.ref`` directory, e.g. ``.../sky130A/libs.ref``), else what ``klt pdk
    find`` resolves, else ``None``.

    Only ``--set grid`` needs the decks (it builds a gate model per point);
    ``None`` there is a refusal, never a fallback to the nominal model. The
    klt resolution is remembered per process: a resolved install that does
    not match the pins still fails closed inside ``_DeckCache``.
    """
    global _KLT_LIBS_REF
    if explicit is not None:
        ref = Path(explicit).expanduser().resolve()
        if not (ref / PVT.LIB_SUBDIR).is_dir():
            raise ValueError(f"--libs-ref {ref} is not a sky130A libs.ref directory: "
                             f"{PVT.LIB_SUBDIR} not found under it")
        return ref
    if _KLT_LIBS_REF is _UNSET:
        try:
            _KLT_LIBS_REF = Path(libs_ref(PDK, klt="klt", timeout=120)).resolve()
        except Exception:
            _KLT_LIBS_REF = None
    return _KLT_LIBS_REF  # type: ignore[return-value]


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
              analog_only: bool = False, gate: CoupledDeck | None = None):
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
        *(gate.text.splitlines() if gate is not None else ["Vvdd vdd 0 dc 1.8", "Vvss vss 0 dc 0"]),
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
        meas, save = gate.measurements(cycles)
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


def make_request(name: str, outdir: Path, *, processes: list[str], temp_c: float,
                 supply: float, backend: str, analysis_args: str,
                 header: list[str], cycles: list[dict] | None = None,
                 timeout_s: int = 1800, poll_timeout_s: int | None = None,
                 rate_probe_stop: float | None = None,
                 analog_only: bool = False, gate: CoupledDeck | None = None,
                 gate_model_pvt: dict | None = None, timeouts: dict | None = None) -> None:
    if cycles is None:
        cycles, _ = P.build_program()
    if gate is not None:
        plan_fields = {**gate.fields, "analysis_stop_ns": rate_probe_stop or P.t_stop_ns(cycles)}
    else:
        plan_fields = {"windows": {"w1_ns": list(W1),
                                   "w2_ns": [P.t_edge_ns(2), P.t_stop_ns(cycles) - P.TS_NS]}}
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
    ap.add_argument("--libs-ref", default=None, metavar="DIR",
                    help="--set grid only: a sky130A install's libs.ref directory "
                         "(.../sky130A/libs.ref) to read the mapped Liberty decks from; "
                         "default is what `klt pdk find` resolves. With neither, --set grid "
                         "refuses: it never falls back to the nominal model")
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
                     rate_probe_stop=stop if probe else None, gate=nominal_gate_model())
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

    # issues #431 / #596 / #815: the measured coupled run sizes the grid
    # (one single-process unit per point) and refuses what the fleet's
    # ceiling cannot hold, before anything is written
    timeout_s, poll_timeout_s = grid_timeouts()
    timeout_basis = grid_timeout_basis()
    try:
        libs_ref_dir = resolve_libs_ref(args.libs_ref)
    except ValueError as exc:
        ap.error(str(exc))
    if libs_ref_dir is None:
        ap.error("--set grid builds a gate model per matrix point and needs the PDK's "
                 "Liberty decks: pass --libs-ref <sky130A libs.ref dir> or run where "
                 "`klt pdk find --pdk sky130A` resolves. It never falls back to the "
                 "nominal model or the flat deck")
    cycles, _ = P.build_program()
    stop = P.t_stop_ns(cycles)
    # everything that can fail closed fails HERE, with no request directory
    # written: the per-point gate models (deck identity), the deck mapping
    # (unmapped point) and the deck hashes on disk (PDK version bump)
    try:
        decks = point_gate_models(libs_ref_dir)
        plans = {(proc, temp, supply): PVT.plan_entry([proc], temp, supply, libs_ref_dir=libs_ref_dir)
                 for (proc, temp, supply) in decks}
    except PVT.DeckMapError as exc:
        ap.error(str(exc))
    except GateModelError as exc:
        ap.error(f"gate model: {exc}")
    for (proc, temp, supply), deck in decks.items():
        name = grid_name(proc, temp, supply)
        hdr = [
            f"post-layout-whole-block 12-point matrix: {proc} / {temp:.0f} C / {supply:.2f} V "
            "(issues #174, #815)",
            "DR-0017 option (b): extracted analog partition driving the routed gate model "
            "built for this point; sampler is the sole source of raw_bit/raw_valid",
            "the repo's established four-point post-layout grid; klt sim owns .lib/.temp/.tran",
        ]
        make_request(name, reqdir / name, processes=[proc],
                     temp_c=temp, supply=supply, backend="batch", timeout_s=timeout_s,
                     poll_timeout_s=poll_timeout_s, analysis_args=f"{stop:.0f}n", header=hdr,
                     cycles=cycles, gate=deck, gate_model_pvt=plans[(proc, temp, supply)],
                     timeouts=timeout_basis)
        print(f"wrote {reqdir/name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
