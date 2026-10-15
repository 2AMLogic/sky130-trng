#!/usr/bin/env python3
"""Area of the DR-0015 study lag-count monitor prototype, synthesised standalone.

Issue #301: ``digital/model/lagcount.py`` is the normative model of a bounded
lag-k match-count monitor; ``sim/digital-synthesis/prototypes/
lagcount_monitor.v`` is a straightforward parallel-counter implementation of
it. This harness maps that prototype alone against ``sky130_fd_sc_hd``
(``klt synthesize``, the same engine and PDK corner as
``synthesize-and-verify.py``) for a grid of ``(LAGS, WIN)`` and reports cell
count, area, sequential area and leakage, next to the area of the existing
``trng_digital`` block for scale.

What it is: a cell-count / area estimate of a prototype, nothing more. It is
NOT synthesised into ``digital/rtl/trng_digital.v`` (that file is untouched),
there is no ``klt equiv`` proof, no gate-level cosim, no place-and-route, and
no timing claim. RTL-vs-model agreement of the prototype is checked in
``sim/tests/test_health_detection_coverage.py`` with Icarus, on small
parameters.

Usage::

    python3 sim/digital-synthesis/harness/synthesize-lagcount-prototype.py
    python3 sim/digital-synthesis/harness/synthesize-lagcount-prototype.py --emit-record
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))
sys.path.insert(0, str(REPO_ROOT / "digital"))

import liberty_leakage as ll  # noqa: E402
from _klt_common import run_klt  # noqa: E402
from evidence_record import mint_behavioral_record  # noqa: E402
from model import lagcount  # noqa: E402

PROTO = REPO_ROOT / "sim" / "digital-synthesis" / "prototypes" / "lagcount_monitor.v"
BASELINE_RECORD = REPO_ROOT / "sim" / "digital-synthesis" / "records" / "20260910-001436-a4c3194.json"
GRID = ((8, 1024), (16, 1024), (16, 2048), (32, 1024), (32, 4096), (64, 4096), (128, 4096), (256, 4096))
SLUG = "digital-synthesis"


def specialise(src: str, lags: int, win: int, cutoff: int) -> str:
    """Override the three module parameter defaults (klt requests carry no -P overrides)."""
    win_bits = win.bit_length() - 1
    assert 1 << win_bits == win
    out = src
    for name, val in (("LAGS", lags), ("WIN_BITS", win_bits), ("CUTOFF", cutoff)):
        out, n = re.subn(rf"(parameter\s+{name}\s*=\s*)\d+", rf"\g<1>{val}", out, count=1)
        assert n == 1, name
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--klt", default=os.environ.get("KLT", "klt"))
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)

    if shutil.which(args.klt) is None:
        print(f"error: klt not found ({args.klt!r}) -- a missing tool is not evidence, "
              "so nothing is minted", file=sys.stderr)
        return 2
    env = {**os.environ, "PDK": args.pdk}
    pdk_info = run_klt(["pdk", "find", "--pdk", args.pdk], env=env, klt=args.klt)
    libs_ref = Path(pdk_info["assets"]["libs_ref"])

    work = Path(tempfile.mkdtemp(prefix="lagcount-synth-"))
    src = PROTO.read_text()
    rows = []
    for lags, win in GRID:
        cutoff = lagcount.c_lag(lags, win)
        d = work / f"L{lags}_W{win}"
        d.mkdir()
        (d / "lagcount_monitor.v").write_text(specialise(src, lags, win, cutoff))
        req = {"schema": "klt.synthesize.request/1", "engine": "yosys",
               "sources": ["lagcount_monitor.v"], "hdl_toplevel": "lagcount_monitor",
               "pdk": {"cell_library": "sky130_fd_sc_hd", "corner": "tt_025C_1v80"},
               "constraints": {"clock_period_ns": None}}
        (d / "request.json").write_text(json.dumps(req, indent=2))
        res = run_klt(["synthesize", str(d / "request.json"), "--pdk", args.pdk],
                      env=env, klt=args.klt)
        liberty = libs_ref / "sky130_fd_sc_hd" / "lib" / f"{res['provenance']['deck']['name']}.lib"
        leak, _ = ll.parse_cell_leakage_nw(liberty)
        leak_nw, missing = ll.total_leakage_nw(res["instance_counts_by_type"], leak)
        if missing:
            raise SystemExit(f"error: no leakage entry for {missing[:5]}")
        rows.append({"lags": lags, "win": win, "cutoff": cutoff,
                     "instances": res["instance_count"], "area_um2": res["area_um2"],
                     "seq_area_um2": res.get("sequential_area_um2"), "leakage_nw": leak_nw,
                     "engine_version": res.get("engine_version"),
                     "input_hash": res["provenance"]["input"]["content_hash"],
                     "deck_hash": res["provenance"]["deck"]["content_hash"]})
        print(f"L={lags} W={win} C={cutoff}: {res['instance_count']} cells, "
              f"{res['area_um2']} um2", file=sys.stderr)

    base = json.loads(BASELINE_RECORD.read_text())
    unc = next(c for c in base["configs"] if c["label"] == "unconstrained")
    base_area = unc["area_um2"]

    L = []
    a = L.append
    a("## Configuration")
    a("")
    a("- DUT: `sim/digital-synthesis/prototypes/lagcount_monitor.v` (STUDY PROTOTYPE, DR-0015 / #301), "
      "parallel per-lag counters, sticky alarm, verdict at window end; `LAGS`, `WIN_BITS`, `CUTOFF` "
      "specialised per row. **`digital/rtl/trng_digital.v` is not edited**; the monitor is not adopted.")
    a(f"- engine: yosys (`klt synthesize`) unconstrained; PDK: {pdk_info['variant']} ({pdk_info['version']}); "
      "`sky130_fd_sc_hd` / `tt_025C_1v80`")
    a("- **Estimate of a prototype only**: no `klt equiv`, no gate-level cosim, no place-and-route, no "
      "timing claim, no routing/utilisation overhead. RTL-vs-model agreement of the prototype is checked "
      "separately in `sim/tests/test_health_detection_coverage.py`.")
    a(f"- scale: `trng_digital` unconstrained area in record `20260910-001436-a4c3194` = {base_area} um2 "
      f"({unc['instance_count']} cells)")
    a("")
    a("## Results")
    a("")
    a("| LAGS | WIN | C_L | cells | area um2 | seq area um2 | leakage nW | area / `trng_digital` |")
    a("|---|---|---|---|---|---|---|---|")
    for r in rows:
        a(f"| {r['lags']} | {r['win']} | {r['cutoff']} | {r['instances']} | {r['area_um2']:.1f} | "
          f"{(r['seq_area_um2'] or 0):.1f} | {r['leakage_nw']:.3f} | {r['area_um2'] / base_area:.2f}x |")
    a("")
    a("## What this does and does not establish")
    a("")
    a("- It bounds the cost of the straightforward parallel implementation: area grows ~linearly in "
      "`LAGS x (log2(WIN)+1)` counter bits. It does not explore cheaper microarchitectures (a "
      "time-multiplexed scheme needs a clock faster than the 50 kHz sample clock, which DR-0004 §4.3 "
      "does not provide, and a stored window; both are unestimated here).")
    a("- It is not a statement about the entropy source, the coverage (see experiment J) or timing.")
    body = "\n".join(L)
    print(body)

    if args.emit_record:
        proto_copy = Path(tempfile.mkdtemp(prefix="lagcount-proto-")) / "lagcount_monitor.v"
        shutil.copy2(PROTO, proto_copy)
        rid = mint_behavioral_record(
            repo_root=REPO_ROOT, slug=SLUG,
            claim=("DR-0015 study: standalone sky130_fd_sc_hd synthesis (area/cell count, estimate of a "
                   "prototype, no equivalence proof) of a parallel lag-count monitor over a (LAGS, WIN) "
                   "grid, against the trng_digital area; not adopted"),
            body_md=body,
            summary={"rows": rows, "baseline_trng_digital_area_um2": base_area,
                     "baseline_record": "20260910-001436-a4c3194", "pdk": pdk_info.get("variant")},
            level="gate", seeds={}, tools={"yosys": rows[0]["engine_version"]},
            artifacts=[proto_copy])
        print(f"\nrecord id: {rid}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
