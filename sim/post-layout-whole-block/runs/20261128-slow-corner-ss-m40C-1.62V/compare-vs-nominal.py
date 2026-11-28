#!/usr/bin/env python3
"""The slow-corner run's digital responses beside the nominal run's (#814).

Not an oracle: ``analysis/compare-gate-model.py`` is the nominal run's
comparator and refuses a non-nominal corner (``compare-refused.log``), and the
matrix's per-point oracle is #307's (``analysis/reduce-whole-block.py``). This
only counts how many of the run's digital responses equal the nominal run's,
cycle for cycle, once a logic high is scaled by the rail (1.62 V here, 1.8 V
there) -- a consistency observation that supports the run being the same
program at the same cycles, nothing more. Writes ``compare-vs-nominal.json``.

    python3 sim/post-layout-whole-block/runs/20261128-slow-corner-ss-m40C-1.62V/compare-vs-nominal.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RUN = Path(__file__).resolve().parent
BLOCK = RUN.parents[1]
NOMINAL = BLOCK / "runs/20261128-coupled-full/report.json"
#: a response counts as equal when the rail-scaled levels are within 5 % of the
#: nominal rail (a resolved logic level, never an X)
TOL_V = 0.05 * 1.8
RESPONSE = re.compile(r"^(alarm|gated|startup_done|out_valid)_k\d+(_b\d+)?$"
                     r"|^(rdata|odata)_k\d+(_b\d+)?$")


def responses(report_path: Path) -> dict[str, float]:
    corner, = json.loads(report_path.read_text())["corners"]
    rail = corner["supply_v"]["Vvdd"]
    return {m["name"]: m["value"] * (1.8 / rail) for m in corner["measurements"]
            if RESPONSE.match(m["name"])}


def main() -> int:
    here, nominal = responses(RUN / "report.json"), responses(NOMINAL)
    assert sorted(here) == sorted(nominal), "the two decks do not capture the same responses"
    by_signal: dict[str, list[int]] = {}
    differing = []
    for name in sorted(here):
        signal = name.split("_k")[0]
        counts = by_signal.setdefault(signal, [0, 0])
        counts[1] += 1
        if abs(here[name] - nominal[name]) <= TOL_V:
            counts[0] += 1
        else:
            differing.append(name)
    words = sorted({f"{n.split('_')[0]} cycle {n.split('_k')[1].split('_')[0]}" for n in differing})
    out = {
        "compared": len(here), "equal": len(here) - len(differing),
        "by_signal": {s: {"equal": c[0], "compared": c[1]} for s, c in sorted(by_signal.items())},
        "differing": differing,
        "differing_words": words,
        "tolerance_v_after_rail_scaling": TOL_V,
        "note": "consistency with the nominal run after rail scaling; not an oracle comparison",
    }
    (RUN / "compare-vs-nominal.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"{out['equal']} of {out['compared']} digital responses equal the nominal run's")
    for signal, c in out["by_signal"].items():
        print(f"  {signal:13s} {c['equal']}/{c['compared']}")
    print("differing words:", out["differing_words"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
