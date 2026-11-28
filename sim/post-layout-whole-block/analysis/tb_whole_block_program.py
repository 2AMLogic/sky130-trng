"""cocotb 2.0 testbench replaying ``sim/post-layout-whole-block/program.py`` (#812).

Drives ``trng_digital`` with the exact directed bus program and ``raw_bit``
pattern used by ``make-gate-model.py`` at the gate model's 100 ns clock period
(``program.TS_NS``), recording all six observed outputs on every cycle:
``bus_rdata``, ``out_valid``, ``out_data``, ``alarm``, ``gated``, and
``startup_done``.

Unlike ``digital/tb/cocotb/test_trng_digital_fv.py`` (the untouched #222/#227
evidence testbench, which replays ``rtl-cosim.py::build_program``), this bench
replays ``program.build_program(N)`` so the SDF-annotated Icarus run and the
ngspice timed-delay gate model can be compared word for word on the same
stimulus.

Cycle convention (matching ``program.model_replay()`` and ``test_trng_digital_fv.py``):
* ``clk`` starts low at ``t = 0``, rises at ``CLK_NS/2``, falls at ``CLK_NS``;
* ``rst_n`` is low across the first rising edge and released at the first
  falling edge;
* on each cycle ``k = 0 .. N-1`` (at the falling edge, ``CLK_NS/2 = 50 ns =
  RDATA_NS`` after the preceding rising edge): observe the six outputs visible
  during cycle ``k``, then drive cycle ``k``'s inputs for cycle ``k``'s rising
  edge.

Unresolvable ``X``/``Z`` bits are recorded literally as strings (never coerced
to 0) so downstream comparison fails loudly on any unknown net.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

HERE = Path(__file__).resolve().parent
SLUG_DIR = HERE.parent
REPO_ROOT = SLUG_DIR.parents[1]
sys.path.insert(0, str(SLUG_DIR))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

import program as P
from loadmod import load_module

_GATE_GEN = load_module("make_gate_model_tb", SLUG_DIR / "make-gate-model.py")

_N_ENV = int(os.environ.get("TRNG_WB_CYCLES", "75"))
N_CYCLES: int | None = None if _N_ENV == 0 else _N_ENV
CLK_NS = int(os.environ.get("TRNG_WB_CLK_NS", str(round(P.TS_NS))))
OBS_OUT = os.environ.get("TRNG_WB_OBS_OUT")
TIMING_OUT = os.environ.get("TRNG_WB_TIMING_OUT")
RAW_PATTERN = os.environ.get("TRNG_WB_RAW_BITS", _GATE_GEN.RAW_BIT_PATTERN)

_OUTPUTS = ("bus_rdata", "out_valid", "out_data", "alarm", "gated", "startup_done")
PROBE: dict[str, dict[str, list[int]]] = {}
OBSERVED: list[dict] = []


def _build_vectors() -> list[dict]:
    cycles, _ = P.build_program(limit=N_CYCLES)
    inputs = P.cycle_inputs(cycles)
    n_samples = sum(1 for inp in inputs if inp["raw_valid"])
    if n_samples > len(RAW_PATTERN):
        raise ValueError(
            f"raw bit pattern has {len(RAW_PATTERN)} bits, need {n_samples}")
    bits = [int(c) for c in RAW_PATTERN[:n_samples]]
    vectors: list[dict] = []
    bit_i = 0
    raw_bit_cur = 0
    for k, inp in enumerate(inputs):
        if inp["raw_valid"]:
            raw_bit_cur = bits[bit_i]
            bit_i += 1
        vectors.append({
            "cycle": k,
            "raw_bit": raw_bit_cur,
            "raw_valid": inp["raw_valid"],
            "addr": inp["addr"],
            "we": inp["we"],
            "re": inp["re"],
            "wdata": inp["wdata"],
            "out_ready": inp["out_ready"],
        })
    return vectors


VECTORS = _build_vectors()


def _val_int_or_str(handle) -> int | str:
    v = handle.value
    return int(v) if v.is_resolvable else str(v)


def _fmt_word(val: int | str) -> str:
    return f"{val:08x}" if isinstance(val, int) else val


def _fmt_bit(val: int | str) -> str:
    return str(val)


def _observe(dut, cycle: int) -> dict:
    return {
        "cycle": cycle,
        "bus_rdata": _val_int_or_str(dut.bus_rdata),
        "out_valid": _val_int_or_str(dut.out_valid),
        "out_data": _val_int_or_str(dut.out_data),
        "alarm": _val_int_or_str(dut.alarm),
        "gated": _val_int_or_str(dut.gated),
        "startup_done": _val_int_or_str(dut.startup_done),
    }


async def _watch(sig, name: str) -> None:
    half_ps = CLK_NS * 500
    period_ps = CLK_NS * 1000
    while True:
        await sig.value_change
        t = int(get_sim_time("ps"))
        if t < half_ps:
            continue  # reset / X->0 initialisation
        ph = (t - half_ps) % period_ps  # 0 == rising edge
        rec = PROBE.setdefault(name, {"clk_to_out_ps": [], "in_to_out_ps": []})
        if ph < half_ps:
            rec["clk_to_out_ps"].append(ph)
        else:
            rec["in_to_out_ps"].append(ph - half_ps)


def _flush_outputs() -> None:
    if TIMING_OUT:
        tp = Path(TIMING_OUT)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(json.dumps(
            {"clock_period_ns": CLK_NS, "probe": PROBE}, sort_keys=True) + "\n")
    if not OBS_OUT:
        return
    out = Path(OBS_OUT)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stimulus.txt").write_text("".join(
        f"{v['raw_bit']} {v['raw_valid']} {v['addr']} {v['we']} {v['re']} "
        f"{v['wdata']:08x} {v['out_ready']}\n"
        for v in VECTORS
    ))
    (out / "observations.txt").write_text("".join(
        f"{_fmt_word(o['bus_rdata'])} {_fmt_bit(o['out_valid'])} "
        f"{_fmt_word(o['out_data'])} {_fmt_bit(o['alarm'])} "
        f"{_fmt_bit(o['gated'])} {_fmt_bit(o['startup_done'])}\n"
        for o in OBSERVED
    ))
    (out / "observations.json").write_text(
        json.dumps(OBSERVED, indent=2, sort_keys=True) + "\n")


@cocotb.test()
async def test_drive_whole_block_program(dut) -> None:
    """Replay ``program.build_program(N)`` cycle by cycle and record all outputs."""
    dut.rst_n.value = 0
    for sig in (dut.raw_bit, dut.raw_valid, dut.bus_addr, dut.bus_we,
                dut.bus_re, dut.bus_wdata, dut.out_ready):
        sig.value = 0
    if TIMING_OUT:
        PROBE.clear()
        for name in _OUTPUTS:
            cocotb.start_soon(_watch(getattr(dut, name), name))
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start(start_high=False))
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    OBSERVED.clear()
    for v in VECTORS:
        OBSERVED.append(_observe(dut, v["cycle"]))
        dut.raw_bit.value = v["raw_bit"]
        dut.raw_valid.value = v["raw_valid"]
        dut.bus_addr.value = v["addr"]
        dut.bus_we.value = v["we"]
        dut.bus_re.value = v["re"]
        dut.bus_wdata.value = v["wdata"]
        dut.out_ready.value = v["out_ready"]
        await FallingEdge(dut.clk)

    _flush_outputs()
    assert len(OBSERVED) == len(VECTORS), (
        f"observed {len(OBSERVED)} cycles, expected {len(VECTORS)}")
