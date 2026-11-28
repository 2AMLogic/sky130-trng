#!/usr/bin/env python3
"""The whole-block directed bus program (issue #174).

One committed, deterministic program that exercises, at transistor level,
the behaviours the campaign record claims: reset release, register reads
(``ID``, ``HT_STARTUP``, ``STATUS``, ``ALARM``), the ``CTRL.EN`` write,
raw-bit sampling off the real post-layout sampler, ``RAW_DATA`` register
pops, the gated ``DATA`` read (the start-up gate blocks the conditioned
path -- the 1024-sample start-up window cannot be reached inside a
transistor-level compute budget, so ``gated`` stays high by design and a
``DATA`` read is issued precisely to show the blocking), and streaming
``out_valid``/``out_data`` pops in raw mode with ``out_ready`` tied high.

Cycle ``k`` spans ``[t_edge(k), t_edge(k+1))`` where ``t_edge(k) = T0 + k*TS``
(T0 = 320 ns, TS = 100 ns -- the same disclosed, measured compute-budget
deviation from DR-0003's Ts = 20 us that every post-layout sampler deck in
this repo states; the *digital section* is synchronous, so the program is
identical at any Ts and the record carries the deviation explicitly).

The decks' ``.meas`` card sets are built here too (#804), from that same
cycle contract: ``gate_measurement_cards`` (the standalone digital run),
``coupled_measurements`` (the transistor sampler driving the gate model) and
``whole_block_measurement_cards`` (the transistor whole block), over one card
collector that drops a card sampling past ``t_stop`` and refuses a repeated
name. So is the normative-oracle response comparison every reducer scores a
corner through (``decode`` / ``response_checks``, beside ``model_replay``).

Consumed by:

* ``make-requests.py`` -- emits the PWL stimulus cards and the request's
  ``.meas`` capture windows from this program;
* ``make-gate-model.py`` -- the standalone digital deck's stimulus and
  ``.meas`` set;
* ``analysis/compare-gate-model.py`` and ``analysis/reduce-whole-block.py``,
  which replay the same program through the normative model
  (``digital/model/digital_top.py``) with the raw bits the transistor run
  captured, and compare per-cycle outputs.

Nothing here simulates anything.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "digital"))
sys.path.insert(0, str(REPO / "sim" / "bin"))

from model import regmap as rm  # noqa: E402

#: clk begins pulsing here (same convention as every post-layout sampler deck)
T0_NS = 320.0
#: rst_n rises here (make-requests.py Vrstn PULSE delay)
RST_N_RELEASE_NS = 300.0
#: sample period -- the disclosed compute-budget deviation, stated per record
TS_NS = 100.0
#: inputs change this long after each clock edge (settled well before the next)
SKEW_NS = 20.0
#: where in a cycle capture points sit (just before the next edge, after
#: the 32-bit word bus read data of the previous cycle is stable)
CAPTURE_NS = 80.0
#: mid-cycle point for reading bus_rdata latched at this cycle's edge
RDATA_NS = 50.0

#: the routed structural netlist of the digital half: the gate-level model's
#: source (make-gate-model.py) and one of the partition check's hash inputs
#: (make-requests.py)
ROUTED_V = REPO / "layout" / "trng_digital" / "trng_digital.routed.v"
#: digital input high level (V), fixed at every corner: 1.8 V is the sky130
#: 1.8 V device rating, VIH(1.62 V) = 1.05 V accepts it, and the supply sources
#: themselves -- not these cards -- carry the corner. A repo convention
#: disclosed in the record, not a published PDK figure.
VIH = 1.8
#: Liberty input threshold (%) the gate model's bridge band must be centred
#: on; make-gate-model.py asserts the deck against it
EXPECTED_THRESHOLD_PCT = 50.0
#: current-window integration window W1 (ns): rings running, digital
#: reset-held (clk has not started; rst_n low until 300 ns). W2 (every
#: program cycle, ending one Ts before t_stop) is derived per program.
W1 = (50.0, 250.0)
#: the supply sources the corner's ``supply_v`` axis steps (``Vvdd``,
#: ``Vvddr1..4``); ``vss`` is read by its own ``i_vss_w2`` card
RAILS = ("vdd", "vddr1", "vddr2", "vddr3", "vddr4")

N_SAMPLES_REG = 32   # first raw word: consumed by the RAW_DATA register pops
N_SAMPLES_STREAM = 32  # second raw word: consumed by the streaming port

# -- cycle opcodes -----------------------------------------------------------
# ("read", addr)            bus read, rdata latched at the NEXT edge
# ("write", addr, wdata)    bus write
# ("sample", out_ready)     raw_valid=1 cycle; raw_bit is whatever the
#                           analog sampler latches (captured for the oracle)
# ("idle",)                 bus quiet, raw_valid=0


def build_program(limit: int | None = None) -> tuple[list[dict], list[tuple[str, int, int]]]:
    """The full program, or its first ``limit`` cycles (the startup probe)."""
    cycles: list[dict] = []
    phases: list[tuple[str, int, int]] = []

    def phase(name: str):
        start = len(cycles)

        class _Ctx:
            def __enter__(self):
                return None

            def __exit__(self, *exc):
                phases.append((name, start, len(cycles)))
                return False
        return _Ctx()

    def read(addr: int):
        cycles.append({"op": "read", "addr": addr, "out_ready": 0})

    def write(addr: int, wdata: int):
        cycles.append({"op": "write", "addr": addr, "wdata": wdata, "out_ready": 0})

    def sample(out_ready: int = 0):
        cycles.append({"op": "sample", "addr": 0, "we": 0, "re": 0,
                       "wdata": 0, "out_ready": out_ready})

    def idle(out_ready: int = 0):
        cycles.append({"op": "idle", "addr": 0, "we": 0, "re": 0,
                       "wdata": 0, "out_ready": out_ready})

    with phase("reset-released register audit: ID, HT_STARTUP, STATUS (EN=0)"):
        read(rm.ID)
        read(rm.HT_STARTUP)
        read(rm.STATUS)

    with phase("enable"):
        write(rm.CTRL, rm.CTRL_EN)

    with phase(f"{N_SAMPLES_REG} samples, no out_ready (register path only)"):
        for _ in range(N_SAMPLES_REG):
            sample(out_ready=0)

    with phase("register pops + interleaved reads (first raw word readable)"):
        read(rm.STATUS)      # raw fifo level 1 expected
        read(rm.RAW_DATA)    # pops W0; rdata visible next cycle
        read(rm.ID)          # bus still alive beside the fifo
        read(rm.DATA)        # gated: the start-up window blocks this path
        read(rm.ALARM)       # no health alarm: 0 expected
        read(rm.STATUS)      # raw fifo empty again

    with phase(f"{N_SAMPLES_STREAM} samples with out_ready=1 (streaming pops)"):
        for _ in range(N_SAMPLES_STREAM):
            sample(out_ready=1)

    with phase("final STATUS"):
        read(rm.STATUS)

    if limit is not None:
        # keep only the first `limit` cycles; drop phases that start past it
        cycles = cycles[:limit]
        phases = [(n, a, min(b, limit)) for n, a, b in phases if a < limit]

    return cycles, phases


def t_edge_ns(k: int) -> float:
    return T0_NS + k * TS_NS


def t_stop_ns(cycles: list[dict]) -> float:
    """One settled half-cycle past the last edge."""
    return t_edge_ns(len(cycles)) + TS_NS / 2.0


def _word_measurements(prefix: str, k: int, bus: str,
                       t: float) -> Iterator[tuple[str, str, str, float]]:
    """Yield (name, SPICE card, save net, time in ns) for the 32 bits
    ``<prefix>_k<k>_b<bit>`` of one bus word, each read on ``bus.format(bit)``."""
    for bit in range(32):
        name = f"{prefix}_k{k}_b{bit}"
        net = bus.format(bit)
        yield name, f".meas tran {name} FIND v({net}) AT={t:.1f}n", net, t


def bus_read_measurements(inputs: list[dict]) -> Iterator[tuple[str, str, str, float]]:
    """Yield (name, SPICE card, save net, time in ns) for each observable read bit."""
    # A read in cycle k latches at its closing edge and is observed in cycle k+1.
    for k, inp in enumerate(inputs[:-1]):
        if inp["re"]:
            yield from _word_measurements("rdata", k, "bus_rdata_{}_", t_edge_ns(k + 1) + RDATA_NS)


class _MeasCollector:
    """One deck's ``measurements[]`` list and the set of nets its cards read.

    Shared by the card sets below (#804). A card whose sample time lies past
    ``t_stop`` is dropped whole -- it cannot resolve inside a truncated
    program's transient -- and :meth:`result` refuses a repeated name: ``klt``
    keys its coverage ids by measurement name, and a repeat displaces the
    entry it repeats in every name-keyed read of the report.
    """

    def __init__(self, t_stop: float, save: Iterable[str] = ()):
        self._t_stop = t_stop
        self.meas: list[dict] = []
        self.save: set[str] = set(save)

    def add(self, name: str, card: str, net: str | None = None, t: float | None = None) -> None:
        if t is not None and t > self._t_stop:
            return  # unreachable within this (truncated) program's stop time
        self.meas.append({"name": name, "spice": card})
        if net:
            self.save.add(net)

    def extend(self, cards: Iterable[tuple[str, str, str | None, float | None]]) -> None:
        for card in cards:
            self.add(*card)

    def word(self, prefix: str, k: int, bus: str, t: float) -> None:
        """Add the 32 cards of one bus word (:func:`_word_measurements`)."""
        self.extend(_word_measurements(prefix, k, bus, t))

    def result(self) -> tuple[list[dict], list[str]]:
        """``(measurements, sorted .save nets)``; a repeated name raises ``ValueError``."""
        names = [e["name"] for e in self.meas]
        if len(names) != len(set(names)):
            raise ValueError("duplicate measurement names")
        return self.meas, sorted(self.save)


def streaming_word_cycles(n: int) -> list[int]:
    """Cycles whose streaming ``out_data`` word (``odata_k<k>_b*``) the decks
    capture: the first completions and the program's tail. The comparison
    asserts a word only where the normative model reports ``out_valid = 1``
    for that cycle."""
    return sorted(k for k in {36, 37, 74} | set(range(max(0, n - 3), n)) if k < n)


def _gate_measurement_collector(cycles: list[dict], vih: float,
                                threshold_pct: float) -> _MeasCollector:
    """The standalone digital deck's cards, before the uniqueness check."""
    inputs = cycle_inputs(cycles)
    n = len(cycles)
    c = _MeasCollector(t_stop_ns(cycles), {"clk", "rst_n", "raw_bit", "raw_valid", "alarm", "gated",
                                            "startup_done", "out_valid", "vdd", "vss"})
    c.extend(bus_read_measurements(inputs))
    for k in streaming_word_cycles(n):
        c.word("odata", k, "out_data_{}_", t_edge_ns(k) + RDATA_NS)
    # scalar observables, measured DURING cycle k -- the same capture convention
    # make-requests.py uses, so the oracle mapping is identical: a `<sig>_k<k>`
    # sample is compared with the model row for cycle k, and a `rdata_k<k>`
    # sample (latched at the edge that ENDS cycle k) with the row for k+1.
    for k in range(n):
        t = t_edge_ns(k) + RDATA_NS
        for sig in ("alarm", "gated", "startup_done", "out_valid"):
            c.add(f"{sig}_k{k}", f".meas tran {sig}_k{k} FIND v({sig}) AT={t:.1f}n", sig, t)
    # the 50 % crossing of the clock the Liberty deck measures its delays at.
    # clk is driven 0..vih (make-gate-model.py stimulus_cards' Vclk PULSE), so
    # the threshold tracks vih -- NOT supply_v/2: --supply-v and --vih are
    # independent knobs that merely coincide today. :3g reproduces the
    # committed card's bare "0.9" at the pinned defaults (vih 1.8 V, 50 %)
    # byte for byte.
    clk_threshold_v = vih * threshold_pct / 100.0
    c.add("t_clk_first",
          f".meas tran t_clk_first WHEN v(clk)={clk_threshold_v:.3g} RISE=1", "clk")
    return c


def gate_measurement_cards(cycles: list[dict], vih: float,
                           threshold_pct: float) -> tuple[list[dict], list[str]]:
    """The standalone digital deck's ``.meas`` set: every digital response
    the model also predicts; returns ``(entries, .save nets)``."""
    return _gate_measurement_collector(cycles, vih, threshold_pct).result()


def coupled_measurements(cycles: list[dict]) -> tuple[list[dict], list[str]]:
    """The coupled deck's set: the gate model's responses, the sampler's tap
    on every cycle, and the clock's level at ``t_stop``."""
    c = _gate_measurement_collector(cycles, VIH, EXPECTED_THRESHOLD_PCT)
    for k in range(len(cycles)):
        t = t_edge_ns(k) + CAPTURE_NS
        for signal in ("raw_bit", "raw_valid"):
            name = f"{signal}_k{k}"
            c.add(name, f".meas tran {name} FIND v({signal}) AT={t:.1f}n")
    c.add("clk_at_stop",
          f".meas tran clk_at_stop FIND v(clk) AT={t_stop_ns(cycles):.0f}n")
    return c.result()


def whole_block_measurement_cards(cycles: list[dict]) -> tuple[list[dict], list[str]]:
    """The transistor whole-block request's ``measurements[]`` entries;
    returns ``(entries, .save nets)``."""
    n = len(cycles)
    inputs = cycle_inputs(cycles)
    t_stop = t_stop_ns(cycles)
    c = _MeasCollector(t_stop, {"clk", "rst_n", "raw_bit", "raw_valid", "ring_bit1", "ring_bit2",
                                "ring_bit3", "ring_bit4", "alarm", "gated", "startup_done",
                                "out_valid", "vdd", "vss", "vddr1", "vddr2", "vddr3", "vddr4"})

    # -- per-sample-cycle raw tap captures (the oracle's stimulus)
    for k, inp in enumerate(inputs):
        if inp["raw_valid"]:
            t = t_edge_ns(k) + CAPTURE_NS
            c.add(f"raw_bit_k{k}", f".meas tran raw_bit_k{k} FIND v(raw_bit) AT={t:.1f}n", "raw_bit", t)
            c.add(f"raw_valid_k{k}", f".meas tran raw_valid_k{k} FIND v(raw_valid) AT={t:.1f}n",
                  "raw_valid", t)

    c.extend(bus_read_measurements(inputs))

    # -- streaming-port captures: every cycle where a word can complete or pop
    words = set(streaming_word_cycles(n))
    for k in range(3, n):
        if inputs[k]["out_ready"] or inputs[k - 1]["out_ready"]:
            t = t_edge_ns(k) + RDATA_NS
            c.add(f"out_valid_k{k}", f".meas tran out_valid_k{k} FIND v(out_valid) AT={t:.1f}n",
                  "out_valid", t)
            if k in words:
                c.word("odata", k, "out_data_{}_", t)

    # -- scalar observables at every bus-quiet sample-phase boundary of interest
    for k in sorted({2, 3, 36, 42, 74, n - 1}):
        t = t_edge_ns(k) + RDATA_NS
        for sig in ("alarm", "gated", "startup_done"):
            c.add(f"{sig}_k{k}", f".meas tran {sig}_k{k} FIND v({sig}) AT={t:.1f}n", sig, t)

    # -- first stream-valid assertion time (throughput tap, see README)
    c.add("t_out_valid_first", ".meas tran t_out_valid_first WHEN v(out_valid)=1.4 RISE=1", "out_valid")

    # -- per-rail currents: W1 (rings running, digital reset-held) and W2 (active)
    w2 = (t_edge_ns(2), t_stop - TS_NS)
    for rail in RAILS:
        c.add(f"i_{rail}_w1", f".meas tran i_{rail}_w1 AVG i(V{rail}) FROM={W1[0]:.0f}n TO={W1[1]:.0f}n")
        c.add(f"i_{rail}_w2", f".meas tran i_{rail}_w2 AVG i(V{rail}) FROM={w2[0]:.0f}n TO={w2[1]:.0f}n")
        c.add(f"q_{rail}_w2", f".meas tran q_{rail}_w2 INTEG i(V{rail}) FROM={w2[0]:.0f}n TO={w2[1]:.0f}n")
    c.add("i_vss_w2", f".meas tran i_vss_w2 AVG i(Vvss) FROM={w2[0]:.0f}n TO={w2[1]:.0f}n")

    # -- sanity: the clock really toggled
    c.add("t_clk_first", ".meas tran t_clk_first WHEN v(clk)=0.9 RISE=1", "clk")

    c.save |= {f"i(V{r})" for r in (*RAILS, "vss")}
    return c.result()


def cycle_inputs(cycles: list[dict]) -> list[dict]:
    """Per-cycle input vector, in drive order (see make-requests.py)."""
    out = []
    for c in cycles:
        if c["op"] in ("read", "write"):
            we = 1 if c["op"] == "write" else 0
            re_ = 1 if c["op"] == "read" else 0
            out.append({"addr": c["addr"], "we": we, "re": re_,
                        "wdata": c.get("wdata", 0),
                        "out_ready": c["out_ready"], "raw_valid": 0})
        else:
            out.append({"addr": 0, "we": 0, "re": 0, "wdata": 0,
                        "out_ready": c["out_ready"],
                        "raw_valid": 1 if c["op"] == "sample" else 0})
    return out


# Hold each level to 100 ps before the change. Must stay >= 0.1: `f"{t:.1f}n"` would
# collapse the hold and the change onto one breakpoint (#488; enforced by
# test_breakpoint_hygiene). Do not tighten.
PWL_EDGE_NS = 0.1


def waveform_card(name: str, levels: list[int], stop_ns: float, vih: float) -> str:
    """Hold each logical value, then switch over the final 100 ps of its edge."""
    points = [(0.0, levels[0])]
    for k in range(1, len(levels)):
        if levels[k] != levels[k - 1]:
            change = t_edge_ns(k) + SKEW_NS
            points.extend(((change - PWL_EDGE_NS, levels[k - 1]), (change, levels[k])))
    points.append((stop_ns, levels[-1]))
    text = " ".join(f"{t:.1f}n {value * vih:.3f}" for t, value in points)
    return f"V{name} {name} 0 PWL({text})"


def input_cards(cycles: list[dict], n_cycles: int, vih: float, *, coupled: bool = False) -> list[str]:
    inputs = cycle_inputs(cycles)[:n_cycles]
    stop = t_stop_ns(cycles)
    cards = []
    for key, width in (("addr", 4), ("wdata", 32)):
        for bit in range(width):
            levels = [(row[key] >> bit) & 1 for row in inputs]
            cards.append(waveform_card(f"bus_{key}_{bit}_", levels, stop, vih))
    directions = boundary_signals()
    for name, key in (("bus_we", "we"), ("bus_re", "re"), ("raw_valid", "raw_valid"),
                      ("out_ready", "out_ready")):
        if not coupled or directions[name]["dir"] == "tb->digital":
            cards.append(waveform_card(name, [row[key] for row in inputs], stop, vih))
    return cards


#: DR-0017 option (b): the simulated detail of each half of the block. Written
#: into every request/plan and read by the reducer to label the result level.
PROVENANCE = {"analog": "transistor", "digital": "gate-level"}


def boundary_signals() -> dict[str, dict]:
    """The analog/digital boundary of DR-0017 as data (``{dir, width, domain}``).

    ``dir`` is the signal direction relative to the pair of halves:
    ``tb->both`` / ``tb->analog`` / ``tb->digital`` (testbench driven),
    ``analog->digital`` (inter-macro), ``analog->obs`` / ``digital->obs``
    (observed), ``supply``. ``domain`` names the supply group. Source of truth:
    ``layout/trng_whole/interface.md`` and ``trng_whole.sim.ports.json``.
    """
    s: dict[str, dict] = {}

    def add(name, direction, width, domain):
        s[name] = {"dir": direction, "width": width, "domain": domain}

    add("raw_bit", "analog->digital", 1, "vdd")
    add("raw_valid", "analog->digital", 1, "vdd")
    add("clk", "tb->both", 1, "vdd")
    add("rst_n", "tb->both", 1, "vdd")
    for i in range(1, 5):
        add(f"en{i}", "tb->analog", 1, f"vddr{i}")
        add(f"ring_bit{i}", "analog->obs", 1, f"vddr{i}")
        add(f"vddr{i}", "supply", 1, f"vddr{i}")
    add("bus_addr", "tb->digital", 4, "vdd")
    add("bus_we", "tb->digital", 1, "vdd")
    add("bus_re", "tb->digital", 1, "vdd")
    add("bus_wdata", "tb->digital", 32, "vdd")
    add("out_ready", "tb->digital", 1, "vdd")
    add("bus_rdata", "digital->obs", 32, "vdd")
    add("out_data", "digital->obs", 32, "vdd")
    for n in ("out_valid", "alarm", "gated", "startup_done"):
        add(n, "digital->obs", 1, "vdd")
    add("vdd", "supply", 1, "vdd")
    add("vss", "supply", 1, "vdd")
    return s


def digital_stimulus(cycles: list[dict]) -> list[dict]:
    """Per-cycle vectors for the gate-level digital block, no analog sources.

    ``cycle_inputs`` plus the clock/reset times of the whole-block deck, so the
    digital half can be driven standalone. ``raw_bit`` is not here: it is the
    analog sampler's output, carried across the boundary at run time.
    """
    out = []
    for k, inp in enumerate(cycle_inputs(cycles)):
        v = dict(inp)
        v.update({"cycle": k, "t_edge_ns": t_edge_ns(k),
                  "clk_start_ns": T0_NS, "ts_ns": TS_NS,
                  "rst_n_release_ns": RST_N_RELEASE_NS})
        out.append(v)
    return out


def model_replay(captured_bits: list[int], *, captured_valid: list[int] | None = None) -> list[dict]:
    """Replay the program through the normative model.

    ``captured_bits[k]`` is the raw_bit the transistor run latched at edge
    ``k+1`` (the program's k-th sample cycle). Returns one row per cycle
    with every observable output the deck measured. For coupled replay the
    measured valid vector selects the edges that consumed a captured bit.
    """
    from model.digital_top import TrngDigital  # noqa: E402  (repo model)
    cycles, phases = build_program()
    inputs = cycle_inputs(cycles)
    if captured_valid is not None:
        for inp, valid in zip(inputs, captured_valid, strict=True):
            inp["raw_valid"] = valid
        if sum(captured_valid) != len(captured_bits):
            raise ValueError("expected one captured bit per asserted sampler strobe")
    dut = TrngDigital()
    rows = []
    bit_i = 0
    for k, inp in enumerate(inputs):
        # the DUT samples its inputs at the edge that ENDS cycle k; the
        # model's cycle() returns the start-of-cycle registers visible
        # DURING cycle k (digital_top.cycle() observes before applying the
        # edge), exactly what the deck's capture windows measure.
        raw_bit = captured_bits[bit_i] if inp["raw_valid"] else 0
        if inp["raw_valid"]:
            bit_i += 1
        out = dut.cycle(raw_bit=raw_bit, raw_valid=inp["raw_valid"],
                        addr=inp["addr"], we=inp["we"], re=inp["re"],
                        wdata=inp["wdata"], out_ready=inp["out_ready"])
        rows.append({"cycle": k, "phase": next(p for p in phases if p[1] <= k < p[2])[0],
                     "inputs": inp, "model": out})
    if captured_valid is None:
        assert bit_i == N_SAMPLES_REG + N_SAMPLES_STREAM, "program bit budget drifted"
    return rows


# -- normative-oracle response comparison -------------------------------------
# One implementation for every reducer that scores a corner (#642): the
# 12-point reducer (analysis/reduce-whole-block.py) and the gate-model and
# coupled checkers (analysis/compare-gate-model.py). When the reducer carried
# its own copy it drifted unnoticed -- a 1-cycle off-by-one on every
# rdata_k*/odata_k*/<sig>_k* check, vdd/2 rounding to 0, and no duplicate
# measurement-name guard.

#: a measured level must be this close (V) to vss or to the supply to decode
LEVEL_TOL = 0.05

_RDATA_RE = re.compile(r"^rdata_k(\d+)_b(\d+)$")
_ODATA_RE = re.compile(r"^odata_k(\d+)_b(\d+)$")
_SCALAR_RE = re.compile(r"^(alarm|gated|startup_done|out_valid)_k(\d+)$")


def decode(value: float | None, supply_v: float) -> int | None:
    """Logical bit, or ``None`` when the level is not a resolved rail.

    A measured voltage decodes only within ``LEVEL_TOL`` of ``vss`` or of the
    supply. Anything in between -- in particular ``dac_bridge``'s
    ``out_undef`` (supply/2), which is what an UNKNOWN digital net reads as
    -- is undecodable and makes the comparison FAIL. It is never rounded to
    the nearer rail: an X that silently decoded to 0 would turn a broken
    model into a passing one.
    """
    if value is None:
        return None
    if abs(value) <= LEVEL_TOL:
        return 0
    if abs(value - supply_v) <= LEVEL_TOL:
        return 1
    return None


def response_checks(measured: dict, rows: list[dict], supply_v: float,
                    n_cycles: int) -> tuple[list[dict], list[dict]]:
    """``(checks, undecodable)``: every digital response in ``measured`` (name
    to voltage) against the :func:`model_replay` ``rows``.

    The mapping is the card sets' capture convention: ``rdata_k<k>`` is
    sampled at ``t_edge(k+1) + RDATA_NS``, i.e. during cycle ``k+1``, so it
    is compared with the model row for cycle ``k+1``; ``<sig>_k<k>`` and
    ``odata_k<k>`` are sampled at ``t_edge(k) + RDATA_NS``, during cycle
    ``k``, so with the model row for cycle ``k``.
    """
    checks: list[dict] = []
    undecodable: list[dict] = []

    # -- 32-bit bus read data, per read cycle
    rdata_bits: dict[int, dict[int, float]] = {}
    for name, value in measured.items():
        m = _RDATA_RE.match(name)
        if m:
            rdata_bits.setdefault(int(m.group(1)), {})[int(m.group(2))] = value
    def decode_word(prefix: str, k: int, samples: dict[int, float]):
        # completeness is loud, by bit set: all 32 bits of a word are
        # generated as one .meas set with a single timestamp, so a word
        # legitimately clipped by the t_stop guard is absent as a WHOLE --
        # a partial word in the report is a dropped result, and an absent
        # bit would silently decode as 0 below.
        missing = sorted(set(range(32)) - set(samples))
        if missing:
            raise SystemExit(
                f"{prefix}_k{k}: bit measurements absent for {missing} -- "
                f"an absent .meas result would decode as 0, refusing")
        word = 0
        bad = False
        for bit, value in samples.items():
            b = decode(value, supply_v)
            if b is None:
                undecodable.append({"measurement": f"{prefix}_k{k}_b{bit}", "value": value})
                bad = True
            elif b:
                word |= 1 << bit
        return (None if bad else word)

    for k in sorted(rdata_bits):
        if k + 1 >= len(rows):
            continue  # no cycle to observe it in (guarded at generation too)
        word = decode_word("rdata", k, rdata_bits[k])
        expect = rows[k + 1]["model"]["bus_rdata"]
        checks.append({
            "what": f"bus_rdata after the read in cycle {k}",
            "measurement": f"rdata_k{k}_b*",
            "model_row": k + 1,
            "simulated": word,
            "model": expect,
            "match": word is not None and word == expect,
        })

    # -- 32-bit streaming word, only where the model reports out_valid = 1.
    # When out_valid is 0 the FIFO head the model exposes is not an output the
    # hardware is claiming, so asserting it would be comparing don't-cares.
    odata_bits: dict[int, dict[int, float]] = {}
    for name, value in measured.items():
        m = _ODATA_RE.match(name)
        if m:
            odata_bits.setdefault(int(m.group(1)), {})[int(m.group(2))] = value
    for k in sorted(odata_bits):
        if k >= len(rows):
            continue
        if not rows[k]["model"]["out_valid"]:
            checks.append({
                "what": f"out_data during cycle {k}",
                "measurement": f"odata_k{k}_b*",
                "model_row": k,
                "simulated": None,
                "model": None,
                "match": True,
                "not_compared": "model reports out_valid = 0 for this cycle",
            })
            continue
        word = decode_word("odata", k, odata_bits[k])
        expect = rows[k]["model"]["out_data"]
        checks.append({
            "what": f"out_data during cycle {k}",
            "measurement": f"odata_k{k}_b*",
            "model_row": k,
            "simulated": word,
            "model": expect,
            "match": word is not None and word == expect,
        })

    # -- scalar observables, per cycle
    for name, value in sorted(measured.items()):
        m = _SCALAR_RE.match(name)
        if not m:
            continue
        sig, k = m.group(1), int(m.group(2))
        if k >= n_cycles:
            continue
        b = decode(value, supply_v)
        if b is None:
            undecodable.append({"measurement": name, "value": value})
        expect = rows[k]["model"][sig]
        checks.append({
            "what": f"{sig} during cycle {k}",
            "measurement": name,
            "model_row": k,
            "simulated": b,
            "model": expect,
            "match": b is not None and b == expect,
        })

    return checks, undecodable


if __name__ == "__main__":
    cycles, phases = build_program()
    print(f"{len(cycles)} cycles, t_stop = {t_stop_ns(cycles):.0f} ns")
    for name, a, b in phases:
        print(f"  [{a:3d},{b:3d}) {name}")
