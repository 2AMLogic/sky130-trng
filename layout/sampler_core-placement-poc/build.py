#!/usr/bin/env python3
"""Placement-only exploration of ``sampler_core``'s six ``sampler_dff`` bank.

Issue #22's own acceptance bar names ``sampler_core`` (alongside
``ro_array_core``) as the minimum layout scope. ``design/sampler_core.spice``'s
own ``.subckt sampler_core`` is *not* "six samplers" alone, though -- it is
``xdut`` (one ``ro_array_core`` instance) plus six ``sampler_dff`` instances,
all wired together (``design/README.md``'s own line: "sampler_core  the
sampler, wired to the source"). There is no standalone "just the six
samplers" ``.subckt`` anywhere under ``design/*.spice`` to LVS against at
this narrower scope -- confirmed by grepping every ``.subckt`` line in
``design/*.spice``.

Every previous hierarchy level in this repo (``layout/ro_ring5/``,
``layout/sampler_dff/`` itself) started from an *unrouted placement* stage
before attempting the harder net-by-net routing -- ``layout/README.md``'s
"Why the `place` stage exists on its own" section gives the rationale this
directory reuses: prove the floorplan has no DRC collisions before spending
effort deriving exact routing geometry. This directory is that first stage
for the sampler bank half of ``sampler_core`` -- six already-composed,
individually DRC-clean and LVS-clean ``layout/sampler_dff/sampler_dff.gds``
instances, placed side by side in ``design/sampler_core.spice``'s own
instance order (``xsb``, ``xsv``, ``xsr1``-``xsr4``), with **zero** routing:
no ``vdd``/``vss``/``clk``/``rst_n`` bus, no wiring to a (not-yet-placed)
``ro_array_core`` instance, no per-instance ``d``/``q`` promotion. It is a
proof-of-concept directory (like ``layout/ro_array_core-placement-poc/``
before it), not a committed final cell -- the follow-on routing work is
tracked in #27 and #22.

Usage (from this directory)::

    python3 build.py

Produces ``compose.request.json``/``compose.response.json`` (the
``klt gen-compose`` placement call), ``drc.json`` (``klt drc --deck sky130``)
and ``extract.json`` (``klt extract --deck sky130``) -- no ``klt lvs`` call,
since (as above) no reference ``.subckt`` exists at this exact scope; LVS
sign-off is deferred to whichever later increment assembles the full
``sampler_core`` (source + samplers + shared bus) that
``design/sampler_core.spice``'s own ``.subckt`` actually describes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "bin"))
from _klt_common import run_klt, write_json  # noqa: E402

CELL_NAME = "sampler_core_placement_poc"
SAMPLER_DFF_GDS = "../sampler_dff/sampler_dff.gds"
SAMPLER_DFF_CELL = "sampler_dff"

#: sampler_dff.gds's own bbox (layout/sampler_dff/compose.response.json,
#: unchanged since PR #99 completed its routing): x0=-2.19 x1=50.47 -> a
#: 52.66 um-wide block. Six instances placed with the same 3.0 um
#: bbox-to-bbox spacing layout/sampler_dff/README.md's own "place" stage
#: used for its nine leaf-cell instances (and layout/ro_ring5/ before it) --
#: 52.66 + 3.0 = 55.66 um pitch. Every instance sits at the same y=0.0 origin
#: so a later bus-routing increment sees every instance's own vdd/vss/clk/
#: rst_n pad at an identical y, the same alignment ro_ring5's own row used.
PITCH_UM = 55.66

#: design/sampler_core.spice's own instance order and names:
#:   xsb  xo   clk rst_n raw_bit   vdd vss  -- combining-node tap
#:   xsv  vdd  clk rst_n raw_valid vdd vss  -- tied-high "always 1" reference
#:   xsr1 ro1  clk rst_n ring_bit1 vdd vss  -- per-ring taps
#:   xsr2 ro2  clk rst_n ring_bit2 vdd vss
#:   xsr3 ro3  clk rst_n ring_bit3 vdd vss
#:   xsr4 ro4  clk rst_n ring_bit4 vdd vss
INSTANCE_ORDER = ["sb", "sv", "sr1", "sr2", "sr3", "sr4"]


def main() -> None:
    env = {**os.environ, "PDK": "sky130A"}

    blocks = [
        {
            "id": inst_id,
            "orientation": "none",
            "cell": {"gds_path": SAMPLER_DFF_GDS, "cell_name": SAMPLER_DFF_CELL},
        }
        for inst_id in INSTANCE_ORDER
    ]
    origins_um = {
        inst_id: {"x": i * PITCH_UM, "y": 0.0}
        for i, inst_id in enumerate(INSTANCE_ORDER)
    }
    request = {
        "pdk": {"variant": "sky130A"},
        "blocks": blocks,
        "placement": {
            "strategy": "explicit",
            "order": INSTANCE_ORDER,
            "origins_um": origins_um,
        },
        "routing": {"layer_role": "metal", "width_um": 0.17},
        "connectivity": [],
        "pins": [],
        "options": {"cell_name": CELL_NAME, "output": f"{CELL_NAME}.gds"},
    }
    write_json(HERE / "compose.request.json", request)
    compose = run_klt(
        ["gen-compose", "compose.request.json"], env=env, cwd=HERE
    )
    write_json(HERE / "compose.response.json", compose)

    drc = run_klt(["drc", f"{CELL_NAME}.gds", "--deck", "sky130"], env=env, cwd=HERE)
    write_json(HERE / "drc.json", drc)

    extract = run_klt(
        ["extract", f"{CELL_NAME}.gds", "--deck", "sky130"], env=env, cwd=HERE
    )
    write_json(HERE / "extract.json", extract)

    print(f"bbox_um: {compose.get('bbox_um')}")
    print(f"drc: {drc['status']} ({drc['violation_count']} violations)")
    print(
        f"extract: {extract['status']}: {extract['device_count']} devices, "
        f"{extract['net_count']} nets, {extract.get('device_counts')}"
    )


if __name__ == "__main__":
    main()
