#!/usr/bin/env python3
"""Regenerate the ro-ring-timestep-convergence request set.

The family is a six-point sweep over the unmodified
sim/ro-ring-jitter-accumulation/testbench/tb_ro_ring5_jitter.spice deck, all at
tt / 27 C / 1.8 V, seed 1; only the transient max timestep (@@TMAX@@) and the
injected trnoise amplitude (@@NA@@) vary. This harness owns that point list and
renders the exact sim/bin/corner-run.py command for each point.

    run-convergence.py --list              # print the six points (default)
    run-convergence.py --point N           # print point N's command
    run-convergence.py --point N --run     # run point N (one ngspice, local)

There is deliberately no run-all: a multi-point grid is submitted to the batch
fleet as klt sim requests, not looped through local ngspice. Records land in
records/ and corners/ append-only; never edit the committed ones.
"""
import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SLUG = "ro-ring-timestep-convergence"
TESTBENCH = "sim/ro-ring-jitter-accumulation/testbench/tb_ro_ring5_jitter.spice"
SEED = "1"
NOMINAL_NA = "2.0e-3"  # corner-run.py's --noise-amp default

# (tmax, noise_amp) in the order of the committed records.
POINTS = [
    ("5p", NOMINAL_NA),
    ("10p", NOMINAL_NA),
    ("20p", NOMINAL_NA),
    ("40p", NOMINAL_NA),
    ("5p", "0"),
    ("20p", "0"),
]


def command(i):
    tmax, na = POINTS[i]
    if na == "0":
        claim = (f"ro_ring5 numerical floor: noise_amp=0 at @@TMAX@@={tmax}, "
                 "tt/27C/1.8V, seed 1")
    else:
        claim = (f"ro_ring5 jitter estimator convergence in the transient max timestep: "
                 f"T_0/sigma_1/swing at tt/27C/1.8V, seed 1, @@TMAX@@={tmax}")
    return [
        sys.executable, "sim/bin/corner-run.py", TESTBENCH,
        "--slug", SLUG, "--claim", claim, "--corners", "tt",
        "--temp", "27", "--vdd", "1.8", "--seed", SEED,
        "--tmax", tmax, "--noise-amp", na,
        "--subset-reason",
        "single process corner on purpose: this is a numerical-convergence claim "
        "about the transient step, not a PVT claim",
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="print all six points")
    ap.add_argument("--point", type=int, choices=range(len(POINTS)), metavar="N",
                    help="select one point, 0..5")
    ap.add_argument("--run", action="store_true",
                    help="execute the selected point locally (requires --point)")
    args = ap.parse_args(argv)
    if args.run and args.point is None:
        ap.error("--run requires --point N (no run-all: grids go to the batch fleet)")
    if args.point is None:
        for i, (tmax, na) in enumerate(POINTS):
            print(f"{i}: tmax={tmax} noise_amp={na}")
            print("   " + " ".join(shlex.quote(a) for a in command(i)[1:]))
        return 0
    cmd = command(args.point)
    if not args.run:
        print(" ".join(shlex.quote(a) for a in cmd))
        return 0
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
