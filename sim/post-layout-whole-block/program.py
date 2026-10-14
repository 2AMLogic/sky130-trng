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

Consumed by:

* ``make-requests.py``  -- emits the PWL stimulus cards and the ``.meas``
  capture windows from this program;
* ``analysis/verify-block.py`` -- replays the same program through the
  normative model (``digital/model/digital_top.py``) with the raw bits the
  transistor run captured, and compares per-cycle outputs.

Nothing here simulates anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "digital"))
sys.path.insert(0, str(REPO / "sim" / "bin"))

from model import regmap as rm  # noqa: E402

#: clk begins pulsing here (same convention as every post-layout sampler deck)
T0_NS = 320.0
#: sample period -- the disclosed compute-budget deviation, stated per record
TS_NS = 100.0
#: inputs change this long after each clock edge (settled well before the next)
SKEW_NS = 20.0
#: where in a cycle capture points sit (just before the next edge, after
#: the 32-bit word bus read data of the previous cycle is stable)
CAPTURE_NS = 80.0
#: mid-cycle point for reading bus_rdata latched at this cycle's edge
RDATA_NS = 50.0

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


def model_replay(captured_bits: list[int]) -> list[dict]:
    """Replay the program through the normative model.

    ``captured_bits[k]`` is the raw_bit the transistor run latched at edge
    ``k+1`` (the program's k-th sample cycle). Returns one row per cycle
    with every observable output the deck measured.
    """
    from model.digital_top import TrngDigital  # noqa: E402  (repo model)
    cycles, phases = build_program()
    inputs = cycle_inputs(cycles)
    dut = TrngDigital()
    rows = []
    bit_i = 0
    for k, inp in enumerate(inputs):
        # the DUT samples its inputs at the edge that ENDS cycle k; the
        # model's cycle() returns the outputs visible DURING the next cycle,
        # exactly what the deck's capture windows measure.
        raw_bit = captured_bits[bit_i] if inp["raw_valid"] else 0
        if inp["raw_valid"]:
            bit_i += 1
        out = dut.cycle(raw_bit=raw_bit, raw_valid=inp["raw_valid"],
                        addr=inp["addr"], we=inp["we"], re=inp["re"],
                        wdata=inp["wdata"], out_ready=inp["out_ready"])
        rows.append({"cycle": k, "phase": next(p for p in phases if p[1] <= k < p[2])[0],
                     "inputs": inp, "model": out})
    assert bit_i == N_SAMPLES_REG + N_SAMPLES_STREAM, "program bit budget drifted"
    return rows


if __name__ == "__main__":
    cycles, phases = build_program()
    print(f"{len(cycles)} cycles, t_stop = {t_stop_ns(cycles):.0f} ns")
    for name, a, b in phases:
        print(f"  [{a:3d},{b:3d}) {name}")
