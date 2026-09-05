#!/usr/bin/env python3
"""RTL vs. behavioural-model co-simulation for the digital section.

``digital/model/digital_top.py`` is the normative description of the block;
``digital/rtl/trng_digital.v`` is an implementation of it. This harness
drives **the same stimulus** into both, cycle for cycle, and requires every
observable output to be identical on every cycle:

    bus_rdata, out_valid, out_data, alarm, gated, startup_done

The stimulus is a scripted program, not a random walk, so that the record
says which behaviours were actually exercised: reset, register reads and
writes, the start-up window, FIFO pops through both the register and the
streaming port, an `OUT_MODE` switch, an induced health-test trip,
write-1-to-clear, and a soft reset. Random raw bits are used inside those
phases from a stated seed.

Requires ``iverilog`` (Icarus Verilog). If it is not installed the harness
exits non-zero and mints nothing -- a missing tool is not evidence.

Usage::

    python3 sim/digital-rtl-equivalence/harness/rtl-cosim.py
    python3 sim/digital-rtl-equivalence/harness/rtl-cosim.py --emit-record
"""

from __future__ import annotations

import argparse
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402
from model import regmap as rm  # noqa: E402
from model.digital_top import TrngDigital  # noqa: E402
from model.params import C_RCT, COND_BLOCK_BITS, STARTUP_SAMPLES  # noqa: E402

RTL = REPO_ROOT / "digital" / "rtl" / "trng_digital.v"
TB = REPO_ROOT / "digital" / "tb" / "tb_trng_digital.v"

DEFAULT_SEED = 20260905

# A stimulus cycle: (raw_bit, raw_valid, addr, we, re, wdata, out_ready)
Cycle = tuple


def build_program(seed: int) -> tuple[list[Cycle], list[tuple[str, int, int]]]:
    """Returns (cycles, phases) where a phase is (name, start, end)."""
    rng = random.Random(seed)
    cycles: list[Cycle] = []
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

    def idle(n: int = 1, **kw):
        for _ in range(n):
            emit(**kw)

    def emit(raw_bit: int = 0, raw_valid: int = 0, addr: int = 0, we: int = 0,
             re: int = 0, wdata: int = 0, out_ready: int = 0):
        cycles.append((raw_bit, raw_valid, addr, we, re, wdata, out_ready))

    def sample(n: int, bits=None, **kw):
        for i in range(n):
            bit = bits[i] if bits is not None else rng.getrandbits(1)
            emit(raw_bit=bit, raw_valid=1, **kw)

    with phase("post-reset idle + ID/parameter reads"):
        idle(2)
        for addr in (rm.ID, rm.HT_RCT_CUTOFF, rm.HT_APT_CUTOFF,
                     rm.HT_APT_WINDOW, rm.HT_STARTUP, rm.HT_COND_BLOCK,
                     rm.STATUS, rm.CTRL, rm.ALARM):
            emit(addr=addr, re=1)
            idle(1)

    with phase("sampling disabled: raw_valid high but CTRL.EN low"):
        sample(64)
        emit(addr=rm.STATUS, re=1)
        idle(1)

    with phase("enable, run the start-up window with interleaved STATUS reads"):
        emit(addr=rm.CTRL, we=1, wdata=rm.CTRL_EN)
        # a bus read in the SAME cycle as a sample, to pin the ordering
        for i in range(STARTUP_SAMPLES + 64):
            do_read = (i % 97 == 0)
            emit(raw_bit=rng.getrandbits(1), raw_valid=1,
                 addr=rm.STATUS if do_read else 0, re=1 if do_read else 0)

    with phase("drain the raw FIFO through RAW_DATA (pop-on-read)"):
        for _ in range(6):
            emit(addr=rm.RAW_DATA, re=1)
            idle(1)

    with phase("raw streaming port: out_ready pops while sampling"):
        sample(256, out_ready=1)

    with phase("simultaneous register pop and stream pop (register wins)"):
        for _ in range(8):
            emit(addr=rm.RAW_DATA, re=1, out_ready=1)
            sample(16)

    with phase("OUT_MODE switch to conditioned (flushes both paths)"):
        emit(addr=rm.CTRL, we=1, wdata=rm.CTRL_EN | rm.CTRL_OUT_MODE)
        emit(addr=rm.STATUS, re=1)
        idle(1)
        sample(3 * COND_BLOCK_BITS)
        for _ in range(4):
            emit(addr=rm.DATA, re=1)
            idle(1)
        sample(COND_BLOCK_BITS, out_ready=1)

    with phase("induce an RCT trip with a stuck source"):
        sample(C_RCT + 4, bits=[1] * (C_RCT + 4))
        emit(addr=rm.ALARM, re=1)
        emit(addr=rm.STATUS, re=1)
        idle(1)

    with phase("gated: DATA blocked, RAW_DATA still readable"):
        sample(3 * 32)
        for _ in range(4):
            emit(addr=rm.DATA, re=1)
            emit(addr=rm.RAW_DATA, re=1)
            idle(1)

    with phase("write-1-to-clear, then re-run the start-up test"):
        emit(addr=rm.ALARM, we=1, wdata=rm.AL_MASK)
        emit(addr=rm.ALARM, re=1)
        idle(1)
        sample(STARTUP_SAMPLES + COND_BLOCK_BITS + 8)
        emit(addr=rm.DATA, re=1)
        idle(1)
        emit(addr=rm.STATUS, re=1)
        idle(1)

    with phase("SOFT_RST, then resume sampling"):
        emit(addr=rm.CTRL, we=1, wdata=rm.CTRL_EN | rm.CTRL_SOFT_RST)
        emit(addr=rm.STATUS, re=1)
        idle(1)
        sample(128)
        emit(addr=rm.STATUS, re=1)
        idle(2)

    return cycles, phases


def model_trace(cycles: list[Cycle]) -> list[str]:
    dut = TrngDigital()
    out = []
    for (raw_bit, raw_valid, addr, we, re, wdata, ready) in cycles:
        obs = dut.cycle(raw_bit=raw_bit, raw_valid=raw_valid, addr=addr,
                        we=we, wdata=wdata, re=re, out_ready=ready)
        out.append(f"{obs['bus_rdata']:08x} {obs['out_valid']} "
                   f"{obs['out_data']:08x} {obs['alarm']} {obs['gated']} "
                   f"{obs['startup_done']}")
    return out


def rtl_trace(cycles: list[Cycle], workdir: Path) -> tuple[list[str], str]:
    stim = workdir / "stimulus.txt"
    obs = workdir / "rtl-observations.txt"
    stim.write_text("".join(
        f"{c[0]} {c[1]} {c[2]} {c[3]} {c[4]} {c[5]:08x} {c[6]}\n" for c in cycles))

    exe = workdir / "tb.vvp"
    subprocess.run(["iverilog", "-g2005", "-Wall", "-o", str(exe), str(RTL), str(TB)],
                   check=True, capture_output=True, text=True)
    run = subprocess.run(["vvp", str(exe), f"+stim={stim}", f"+obs={obs}"],
                         check=True, capture_output=True, text=True)
    lines = obs.read_text().splitlines()
    return lines, run.stdout.strip()


def iverilog_version() -> str:
    try:
        out = subprocess.run(["iverilog", "-V"], capture_output=True, text=True)
        return out.stdout.splitlines()[0].strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--keep", type=Path, default=None,
                    help="keep the run artifacts in this directory")
    args = ap.parse_args(argv)

    if shutil.which("iverilog") is None:
        print("error: iverilog not found -- a missing tool is not evidence, "
              "so nothing is minted", file=sys.stderr)
        return 2

    cycles, phases = build_program(args.seed)
    expected = model_trace(cycles)

    tmp = Path(tempfile.mkdtemp(prefix="rtl-cosim-"))
    workdir = args.keep or tmp
    workdir.mkdir(parents=True, exist_ok=True)
    actual, sim_stdout = rtl_trace(cycles, workdir)

    n = min(len(expected), len(actual))
    diffs = [i for i in range(n) if expected[i] != actual[i]]
    length_ok = len(expected) == len(actual)

    def phase_of(index: int) -> str:
        for name, start, end in phases:
            if start <= index < end:
                return name
        return "(outside any phase)"

    lines: list[str] = []
    a = lines.append
    a("## Configuration")
    a("")
    a(f"- RTL: `digital/rtl/trng_digital.v`; testbench: `digital/tb/tb_trng_digital.v`")
    a(f"- reference: `digital/model/digital_top.py` (normative)")
    a(f"- simulator: `{iverilog_version()}`")
    a(f"- stimulus: scripted program, {len(cycles)} cycles, random raw bits from "
      f"`random.Random({args.seed})`")
    a(f"- compared every cycle: `bus_rdata`, `out_valid`, `out_data`, `alarm`, "
      f"`gated`, `startup_done`")
    a("")
    a("## Stimulus phases")
    a("")
    a("| Cycles | Phase | Mismatches |")
    a("|---|---|---|")
    for name, start, end in phases:
        bad = sum(1 for i in diffs if start <= i < end)
        a(f"| {start}-{end - 1} | {name} | {bad} |")
    a("")
    a("## Result")
    a("")
    if length_ok and not diffs:
        a(f"**PASS** -- {len(expected)} of {len(expected)} cycles identical on all "
          f"six observed outputs. The RTL and the behavioural model are "
          f"cycle-for-cycle equivalent over this program.")
    else:
        a(f"**FAIL** -- {len(diffs)} mismatched cycles"
          f"{'' if length_ok else f'; trace lengths differ ({len(expected)} model vs {len(actual)} RTL)'}.")
        a("")
        a("| Cycle | Phase | model | RTL |")
        a("|---|---|---|---|")
        for i in diffs[:20]:
            a(f"| {i} | {phase_of(i)} | `{expected[i]}` | `{actual[i]}` |")
    a("")
    a("## What this record does and does not establish")
    a("")
    a("- It **does** establish that the committed RTL implements the")
    a("  committed behavioural model over the programmed stimulus, including")
    a("  the ordering the model's cycle contract fixes (sample before bus")
    a("  access, register pop beating a streaming pop on the same FIFO).")
    a("- It is **not** exhaustive: it is a directed program, not a formal")
    a("  equivalence proof or a constrained-random campaign. The phase table")
    a("  above is the honest statement of what was exercised.")
    a("- It is **RTL simulation only** -- no synthesis, no `sky130_fd_sc_hd`")
    a("  mapping, no timing. There is therefore no `Fmax`, area or power")
    a("  claim here, and none should be read into it.")

    body = "\n".join(lines)
    print(body)
    ok = length_ok and not diffs

    if args.emit_record:
        if not ok:
            print("\nrefusing to mint a record for a failing run", file=sys.stderr)
        else:
            model_file = workdir / "model-observations.txt"
            model_file.write_text("\n".join(expected) + "\n")
            mint_behavioral_record(
                repo_root=REPO_ROOT,
                slug="digital-rtl-equivalence",
                claim=("digital/rtl/trng_digital.v is cycle-for-cycle "
                       "equivalent to the normative behavioural model "
                       "digital/model/digital_top.py over a directed "
                       f"{len(cycles)}-cycle program"),
                body_md=body,
                summary={
                    "ok": ok,
                    "cycles": len(cycles),
                    "mismatches": len(diffs),
                    "phases": [{"name": n_, "start": s, "end": e}
                               for n_, s, e in phases],
                    "simulator": iverilog_version(),
                    "sim_stdout": sim_stdout,
                },
                level="behavioral (RTL co-simulation)",
                seeds={"python_random": args.seed},
                tools={"iverilog": iverilog_version()},
                artifacts=[workdir / "stimulus.txt",
                           workdir / "rtl-observations.txt",
                           model_file],
            )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
