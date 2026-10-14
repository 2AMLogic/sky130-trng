"""Electrical-limit (max slew / max capacitance) parsing and reduction for
issue #236. Pure functions, no tool invocation.

Two evidence kinds are kept strictly apart:

* ``estimate``  -- klt's in-flow ``report_check_types`` under
  ``estimate_parasitics -global_routing`` (a global-route estimate; the
  numbers in the pnr response ``corners[]``). Parsed from the retained
  OpenROAD stdout logs so the per-pin limit and excess survive.
* ``final``     -- a fresh OpenSTA session over the routed DEF + the
  extracted post-route SPEF (``final_route_audit.py``).

The reduction never turns an absent report, a missing corner, a failed
session, or a setup/hold pass into electrical success.
"""

from __future__ import annotations

import re

CLASSES = ("max_slew", "max_capacitance")

# Row of `report_check_types -max_slew|-max_capacitance -violators`.
_ROW = re.compile(
    r"^(?P<pin>\S+)\s+(?P<limit>[0-9.]+)\s+(?P<value>[0-9.]+)\s+"
    r"(?P<slack>-[0-9.]+)\s+\(VIOLATED\)\s*$")


def parse_violators(text: str) -> list[dict]:
    """Rows of every VIOLATED pin in a ``report_check_types -violators`` text.
    Slack is value-limit (negative); excess is reported as a positive number
    at the printed precision."""
    rows = []
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if m:
            rows.append({"pin": m["pin"], "limit": float(m["limit"]),
                         "value": float(m["value"]),
                         "excess": -float(m["slack"])})
    return rows


_MARGIN = re.compile(
    r"^(?P<pin>\S+)\s+(?P<limit>[0-9.]+)\s+(?P<value>[0-9.]+)\s+(?P<slack>-?[0-9.]+)\s+\((?P<st>MET|VIOLATED)\)\s*$")


def parse_margin(text: str) -> dict | None:
    """Worst row of a non-`-violators` report_check_types block (MET or
    VIOLATED). None when no row is present."""
    for line in text.splitlines():
        m = _MARGIN.match(line.strip())
        if m:
            return {"pin": m["pin"], "limit": float(m["limit"]), "value": float(m["value"]),
                    "slack": float(m["slack"]), "state": m["st"]}
    return None


def block(text: str, name: str) -> str | None:
    """Text between ===KLT_<name>_BEGIN=== and ===KLT_<name>_END===; None if
    the markers are absent (absent is not 'zero violators')."""
    m = re.search(rf"===KLT_{name}_BEGIN===\n(.*?)===KLT_{name}_END===", text,
                  re.S)
    return m.group(1) if m else None


def summarise(rows: list[dict]) -> dict:
    """Per-class summary: count, unique pins, limit set, worst excess."""
    if not rows:
        return {"count": 0, "unique_pins": 0, "worst_excess": 0.0,
                "worst_pin": None, "limits": []}
    w = max(rows, key=lambda r: (r["excess"], r["value"]))
    return {"count": len(rows), "unique_pins": len({r["pin"] for r in rows}),
            "worst_excess": w["excess"], "worst_pin": w["pin"],
            "worst_value": w["value"], "worst_limit": w["limit"],
            "limits": sorted({r["limit"] for r in rows})}


# --- reduction -------------------------------------------------------------

def reduce_evidence(expected_corners: list[str], per_corner: dict | None,
                    kind: str) -> dict:
    """Reduce per-corner evidence to a single verdict.

    ``per_corner[name]`` must be ``{"status": "audited", "max_slew":
    summary, "max_capacitance": summary}``. Anything else is carried through
    as ``unsupported`` or ``missing`` and blocks a clean verdict:

      verdict  'violations'  at least one audited class has count > 0
               'incomplete'  no violation seen, but some corner/class is
                             missing, unsupported, or malformed
               'clean'       every expected corner audited, every class
                             present, all counts zero

    A corner outside ``expected_corners`` is ignored for the verdict but
    reported (a surplus corner cannot stand in for a missing one).
    """
    if kind not in ("estimate", "final"):
        raise ValueError(f"unknown evidence kind {kind!r}")
    per_corner = per_corner or {}
    coverage, totals, bad = {}, {c: 0 for c in CLASSES}, []
    for name in expected_corners:
        rec = per_corner.get(name)
        if rec is None:
            coverage[name] = "missing"
            continue
        st = rec.get("status")
        if st != "audited":
            coverage[name] = "unsupported" if st == "unsupported" else "missing"
            continue
        ok = True
        for c in CLASSES:
            s = rec.get(c)
            if not isinstance(s, dict) or not isinstance(s.get("count"), int):
                ok = False
                continue
            totals[c] += s["count"]
        coverage[name] = "audited" if ok else "missing"
    n_bad = sum(v != "audited" for v in coverage.values())
    violating = any(totals[c] > 0 for c in CLASSES)
    if violating:
        verdict = "violations"
    elif n_bad or not expected_corners:
        verdict = "incomplete"
    else:
        verdict = "clean"
    label = verdict
    if kind == "estimate" and verdict == "clean":
        label = "estimate-clean, final-route unaudited"
    return {"kind": kind, "verdict": verdict, "label": label,
            "totals": totals, "coverage": coverage,
            "corners_expected": len(expected_corners),
            "corners_audited": sum(v == "audited" for v in coverage.values()),
            "surplus_corners": sorted(set(per_corner) - set(expected_corners))}


def candidate_verdict(estimate: dict, final: dict) -> str:
    """A 'clean candidate' needs a clean FINAL-route reduction. An estimate
    alone, however clean, is never enough; setup/hold is not an input."""
    if final["verdict"] == "clean":
        return "clean candidate (final-route audit, all expected corners)"
    if final["verdict"] == "violations":
        return "not clean: final-route violations"
    if estimate["verdict"] == "clean":
        return "estimate-clean, final-route unaudited"
    if estimate["verdict"] == "violations":
        return "not clean: estimate violations, final-route unaudited"
    return "no electrical conclusion (incomplete evidence)"
