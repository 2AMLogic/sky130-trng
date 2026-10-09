"""cocotb 2.0 testbench for `klt functional-verification` -- the directed,
bit-exact `trng_digital` suite of `sim/digital-rtl-equivalence`, expressed in
the pinned tool's native test-report contract (issue #222).

What it is
----------
The SAME stimulus program (`rtl-cosim.py::build_program`) and the SAME
independent oracle (`digital/model/digital_top.py` via
`rtl-cosim.py::model_trace`) that the Verilog file-driven bench
(`digital/tb/tb_trng_digital.v`) is checked against -- only the transcriber is
different. This bench holds no golden vectors of its own: it drives the DUT
per the stimulus, records the six observed outputs once per cycle exactly as
`tb_trng_digital.v` does (record at the falling edge, THEN drive the inputs
for the next rising edge), and compares them to the model's trace.

One `@cocotb.test()` per directed phase (named after `build_program`'s phase
list), plus `test_00_drive_program` (drives the whole program, asserts the
DUT ran to completion) and `test_zz_trace_length_exact` (observation count ==
model count == stimulus count). Tests run in definition order within the one
simulation, so the phase tests are slices of a single continuous program, not
independent resets -- the program is stateful by design.

Fail-closed rules (the point of the exercise)
---------------------------------------------
* a phase test fails if ANY observation in its cycle range is missing (the
  record is shorter than the range) or differs from the model (a missing observation is never "no mismatch");
* the length test fails unless len(observations) == len(model) == len(stim);
* X/Z on any output is recorded literally and therefore mismatches.

Negative-control hook (test-of-the-test, NOT a mode of the suite)
-----------------------------------------------------------------
`TRNG_FV_FAULT` damages the *observation record* so the harness can prove the
reporting path rejects incomplete evidence: `truncate:K` stops recording after
K cycles; `drop:I` omits cycle I's observation. Unset in every real run.

Environment (inherited from the `klt` process): `TRNG_FV_SEED` (stimulus seed),
`TRNG_FV_OBS_OUT` (directory for the observed/model/stimulus traces),
`TRNG_FV_FAULT` (above).

This is functional / unit-delay coverage (no SDF); see the sim record's
coverage section. It is not item-7 timed evidence.
"""

import importlib.util
import os
import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

_p = REPO_ROOT / "sim" / "digital-rtl-equivalence" / "harness" / "rtl-cosim.py"
_spec = importlib.util.spec_from_file_location("rtl_cosim", _p)
rtl_cosim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtl_cosim)

SEED = int(os.environ.get("TRNG_FV_SEED", rtl_cosim.DEFAULT_SEED))
FAULT = os.environ.get("TRNG_FV_FAULT", "")
OBS_OUT = os.environ.get("TRNG_FV_OBS_OUT")

CYCLES, PHASES = rtl_cosim.build_program(SEED)
EXPECTED = rtl_cosim.model_trace(CYCLES)     # independent oracle

OBSERVED: list = []      # one entry per recorded cycle


def _fmt_int(handle, width_hex):
    v = handle.value
    if not v.is_resolvable:
        return str(v)                         # x/z literal -> mismatches
    return f"{int(v):0{width_hex}x}"


def _bit(handle):
    v = handle.value
    return str(int(v)) if v.is_resolvable else str(v)


def _observe(dut) -> str:
    return (f"{_fmt_int(dut.bus_rdata, 8)} {_bit(dut.out_valid)} "
            f"{_fmt_int(dut.out_data, 8)} {_bit(dut.alarm)} {_bit(dut.gated)} "
            f"{_bit(dut.startup_done)}")


def _fault_skips(i: int) -> bool:
    kind, _, arg = FAULT.partition(":")
    if kind == "truncate" and arg:
        return i >= int(arg)
    if kind == "drop" and arg:
        return i == int(arg)
    return False


async def _drive_program(dut):
    # Match tb_trng_digital.v: clk low at t=0, rising at t=5; async reset is
    # applied by the first posedge; released at the first falling edge.
    dut.rst_n.value = 0
    for sig in (dut.raw_bit, dut.raw_valid, dut.bus_addr, dut.bus_we,
                dut.bus_re, dut.bus_wdata, dut.out_ready):
        sig.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start(start_high=False))
    # The X->0 clock initialisation is itself a FallingEdge in cocotb, so wait
    # for the first real rising edge (t=5, which applies the reset) first.
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    OBSERVED.clear()
    for i, (raw_bit, raw_valid, addr, we, re, wdata, ready) in enumerate(CYCLES):
        # 1. record the outputs visible DURING this cycle
        if not _fault_skips(i):       # injected fault: no record at all
            OBSERVED.append(_observe(dut))
        # 2. drive the inputs this cycle's posedge will act on
        dut.raw_bit.value = raw_bit
        dut.raw_valid.value = raw_valid
        dut.bus_addr.value = addr
        dut.bus_we.value = we
        dut.bus_re.value = re
        dut.bus_wdata.value = wdata
        dut.out_ready.value = ready
        await FallingEdge(dut.clk)


def _flush_traces():
    if not OBS_OUT:
        return
    out = Path(OBS_OUT)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stimulus.txt").write_text("".join(
        f"{c[0]} {c[1]} {c[2]} {c[3]} {c[4]} {c[5]:08x} {c[6]}\n" for c in CYCLES))
    (out / "observations.txt").write_text(
        "".join(f"{o}\n" for o in OBSERVED))
    (out / "model-observations.txt").write_text("\n".join(EXPECTED) + "\n")


@cocotb.test()
async def test_00_drive_program(dut):
    """Drive the full directed program; every cycle must yield an observation."""
    await _drive_program(dut)
    _flush_traces()
    assert len(OBSERVED) == len(CYCLES), (
        f"observed {len(OBSERVED)} cycles, stimulus has {len(CYCLES)}: "
        f"{len(CYCLES) - len(OBSERVED)} observation(s) missing")


def _make_phase_test(index: int, name: str, start: int, end: int):
    async def _t(dut):
        assert len(OBSERVED) > 0, "program was not driven"
        got = OBSERVED[start:end]
        want = EXPECTED[start:end]
        assert len(got) == end - start == len(want), (
            f"phase {name!r}: {len(got)} observations for {end - start} cycles")
        bad = [start + k for k, (g, w) in enumerate(zip(got, want)) if g != w]
        assert not bad, (
            f"phase {name!r}: {len(bad)}/{end - start} cycles differ from the "
            f"model, first at cycle {bad[0]}: dut={OBSERVED[bad[0]]!r} "
            f"model={EXPECTED[bad[0]]!r}")
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:48]
    _t.__name__ = f"test_phase_{index:02d}_{slug}"
    _t.__qualname__ = _t.__name__
    _t.__doc__ = f"cycles {start}-{end - 1}: {name}"
    return cocotb.test()(_t)


for _i, (_n, _s, _e) in enumerate(PHASES, start=1):
    _tc = _make_phase_test(_i, _n, _s, _e)
    globals()[_tc.name] = _tc
del _tc   # a leftover module-level alias would be collected as a duplicate test


@cocotb.test()
async def test_zz_trace_length_exact(dut):
    """len(observations) == len(model trace) == len(stimulus), none missing."""
    assert len(OBSERVED) == len(EXPECTED) == len(CYCLES), (
        f"trace lengths differ: observed {len(OBSERVED)}, model "
        f"{len(EXPECTED)}, stimulus {len(CYCLES)}")
    assert OBSERVED == EXPECTED, "full trace differs from the model"
