#!/usr/bin/env python3
"""The measurement request of issue #814: the coupled deck of ONE matrix point.

``make-requests.py --set grid`` emits twelve single-process requests, each with
the grid's timeouts (the measured nominal runtime x ``GRID_MARGIN_X``). This
writes one of them -- ss / -40 C / 1.62 V, the slowest-expected point -- through
the generator's own ``make_request()``, with the same deck and the same plan
fields, but with the one-unit MEASUREMENT timeouts #596 measured the nominal
point with (``records/20261128-coupled-rate.md``: 3,360 s worker + 120 s batch
overhead = the 3,480 s one-unit cap), so a slow corner that runs longer than
the grid's timeout is measured, not killed. The margin is then set from the
result (``records/20261128-slow-corner-runtime.md``).

    python3 sim/post-layout-whole-block/runs/20261128-slow-corner-ss-m40C-1.62V/make-request.py <reqdir>

Nothing here simulates anything.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BLOCK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BLOCK))
_spec = importlib.util.spec_from_file_location("make_requests", BLOCK / "make-requests.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)
import pvt_deck_map as PVT  # noqa: E402
import program as P  # noqa: E402

#: the point measured: the slowest-expected of the 12 (issue #814)
POINT = ("ss", -40.0, 1.62)
#: as the nominal measurement (runs/20261128-coupled-full): the largest timeout
#: one unit can hold, not a figure derived from a rate
MEASURE_TIMEOUT_S = mr.UNIT_TIMEOUT_CAP_S - mr.BATCH_OVERHEAD_S
MEASURE_POLL_TIMEOUT_S = mr.UNIT_TIMEOUT_CAP_S


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    out = Path(argv[0])
    proc, temp, supply = POINT
    libs_ref_dir = mr.resolve_libs_ref(None)
    if libs_ref_dir is None:
        print("needs the PDK's Liberty decks (a resolvable `klt pdk find`); see "
              "make-requests.py --set grid", file=sys.stderr)
        return 2
    deck = mr.point_gate_models(libs_ref_dir)[POINT]
    plan_entry = PVT.plan_entry([proc], temp, supply, libs_ref_dir=libs_ref_dir)
    cycles, _ = P.build_program()
    stop = P.t_stop_ns(cycles)
    name = mr.grid_name(proc, temp, supply)
    hdr = [
        f"post-layout-whole-block 12-point matrix: {proc} / {temp:.0f} C / {supply:.2f} V "
        "(issues #174, #815)",
        "DR-0017 option (b): extracted analog partition driving the routed gate model "
        "built for this point; sampler is the sole source of raw_bit/raw_valid",
        "the repo's established four-point post-layout grid; klt sim owns .lib/.temp/.tran",
    ]
    mr.make_request(name, out / name, processes=[proc], temp_c=temp, supply=supply,
                    backend="batch", timeout_s=MEASURE_TIMEOUT_S,
                    poll_timeout_s=MEASURE_POLL_TIMEOUT_S, analysis_args=f"{stop:.0f}n",
                    header=hdr, cycles=cycles, gate=deck, gate_model_pvt=plan_entry,
                    timeouts={"timeout_s": MEASURE_TIMEOUT_S,
                              "poll_timeout_s": MEASURE_POLL_TIMEOUT_S,
                              "sized_from": "records/20261128-coupled-rate.md",
                              "sizing": "measurement: the largest timeout one unit holds "
                                        "(3360 s + 120 s = 3480 s), as the nominal point was "
                                        "measured; not a grid request (#814)",
                              "units": 1, "job_bound_s": MEASURE_TIMEOUT_S + mr.BATCH_OVERHEAD_S,
                              "fleet_job_ceiling_s": mr.FLEET_JOB_CEILING_S})
    print(f"wrote {out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
