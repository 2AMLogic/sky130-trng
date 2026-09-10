#!/usr/bin/env python3
"""Run `sim/digital-rtl-equivalence`'s directed stimulus program against a
**mapped `sky130_fd_sc_hd` gate netlist** instead of `digital/rtl/trng_digital.v`,
reusing that harness's own stimulus generator and behavioural-model trace
functions rather than re-deriving them (``rtl-cosim.py``'s hyphenated
filename makes it an executable script, not an importable module by name --
loaded here via :mod:`importlib.util`, the standard way to reuse a
hyphenated script's functions without renaming a file every other record
already cites).

Compiles the same testbench (`digital/tb/tb_trng_digital.v`, unmodified --
it names only `trng_digital`'s ports, which the mapped netlist's top module
still exposes byte-for-byte since `klt synthesize` never renames top-level
ports) against the gate netlist plus the two PDK Verilog sources every
`sky130_fd_sc_hd` gate-level simulation needs
(`sky130-modexp/verification/gate-level/README.md`'s own "Cell models"
table is the sibling-repo precedent this mirrors):

* `<libs_ref>/sky130_fd_sc_hd/verilog/primitives.v` -- the UDP primitives
  every cell's functional model instances.
* `<libs_ref>/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v` -- the cell
  functional models themselves.
* `` `define FUNCTIONAL `` -- required, not preferred: Icarus does not
  implement the delayed-signal outputs of `$setuphold`/`$recrem`, so the
  `` `ifndef FUNCTIONAL `` timing-check branch simulates every flop's data
  input as permanently `x`.
* `` `define UNIT_DELAY #1 `` -- gives the sequential UDPs a 1 ns output
  delay so a zero-delay gate netlist has no D/Q race at the clock edge; not
  a timing model (this run has no SDF, no parasitics, no placement).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_RTL_COSIM_PATH = REPO_ROOT / "sim" / "digital-rtl-equivalence" / "harness" / "rtl-cosim.py"
_spec = importlib.util.spec_from_file_location("rtl_cosim", _RTL_COSIM_PATH)
assert _spec is not None and _spec.loader is not None
rtl_cosim = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
_spec.loader.exec_module(rtl_cosim)

build_program = rtl_cosim.build_program
model_trace = rtl_cosim.model_trace
iverilog_version = rtl_cosim.iverilog_version

TB = REPO_ROOT / "digital" / "tb" / "tb_trng_digital.v"

_DEFINES = "`define FUNCTIONAL\n`define UNIT_DELAY #1\n"


def gate_trace(cycles, workdir: Path, netlist_path: Path,
               libs_ref: Path) -> tuple[list[str], str]:
    """Compile+run the gate netlist against the same stimulus/observation
    file protocol :func:`rtl_cosim.rtl_trace` uses, returning
    ``(observation_lines, sim_stdout)``.
    """
    defines_v = workdir / "sky130_fd_sc_hd_sim_defines.v"
    defines_v.write_text(_DEFINES)

    primitives_v = libs_ref / "sky130_fd_sc_hd" / "verilog" / "primitives.v"
    cells_v = libs_ref / "sky130_fd_sc_hd" / "verilog" / "sky130_fd_sc_hd.v"
    for f in (primitives_v, cells_v):
        if not f.exists():
            raise FileNotFoundError(f"expected PDK Verilog source not found: {f}")

    stim = workdir / "stimulus.txt"
    obs = workdir / "gate-observations.txt"
    stim.write_text("".join(
        f"{c[0]} {c[1]} {c[2]} {c[3]} {c[4]} {c[5]:08x} {c[6]}\n" for c in cycles))

    exe = workdir / "gate_tb.vvp"
    subprocess.run(
        ["iverilog", "-g2005", "-Wall", "-o", str(exe),
         str(defines_v), str(primitives_v), str(cells_v),
         str(netlist_path), str(TB)],
        check=True, capture_output=True, text=True)
    run = subprocess.run(["vvp", str(exe), f"+stim={stim}", f"+obs={obs}"],
                         check=True, capture_output=True, text=True)
    lines = obs.read_text().splitlines()
    return lines, run.stdout.strip()


def run(netlist_path: Path, libs_ref: Path, workdir: Path, seed: int):
    """Build the directed program, run gate-level cosim, and diff against
    the normative behavioural model. Returns a dict summary."""
    cycles, phases = build_program(seed)
    expected = model_trace(cycles)
    workdir.mkdir(parents=True, exist_ok=True)
    actual, sim_stdout = gate_trace(cycles, workdir, netlist_path, libs_ref)

    n = min(len(expected), len(actual))
    diffs = [i for i in range(n) if expected[i] != actual[i]]
    length_ok = len(expected) == len(actual)
    ok = length_ok and not diffs

    return {
        "ok": ok,
        "cycles": len(cycles),
        "mismatches": len(diffs),
        "length_ok": length_ok,
        "expected_len": len(expected),
        "actual_len": len(actual),
        "first_diffs": diffs[:20],
        "phases": [{"name": n_, "start": s, "end": e} for n_, s, e in phases],
        "sim_stdout": sim_stdout,
        "iverilog_version": iverilog_version(),
        "seed": seed,
        "stimulus_path": str(workdir / "stimulus.txt"),
        "observations_path": str(workdir / "gate-observations.txt"),
    }
