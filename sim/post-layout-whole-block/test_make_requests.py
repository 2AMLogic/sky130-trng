#!/usr/bin/env python3
"""Unit test for ``make-requests.py``'s driven-input PWL stimulus shape.

Run directly (no pytest suite in this repo):

    python3 sim/post-layout-whole-block/test_make_requests.py

Issue #488: a SPICE ``PWL`` source interpolates **linearly** between its
breakpoints, so a breakpoint list carrying only the change instants emits every
driven input as a straight ramp across the whole hold interval instead of a hold
followed by an edge. Measured on this deck before the fix: ``bus_re`` came out
as ``PWL(0.0n 1.800 640.0n 0.000 970.0n 0.000)`` -- 1.8 V at t = 0 falling
linearly to 0 V at 640 ns, so 0.928 V at 310 ns -- and across the full 75-cycle
grid program **344 of 3000 (driven input x capture point) samples sat more than
10 % off a rail**, the worst at 0.905 V (``bus_addr[0]``, cycle 19, t = 2300 ns),
essentially mid-rail. ``test_capture_points_sit_at_a_rail`` is the control for
that: it fails on the pre-#488 shape and passes once each change carries a hold
breakpoint one ``EDGE_NS`` before it.

The assertions here are on the emitted card text, not on an internal helper, so
they hold against whatever ``points()``/``pwl_card()`` do internally:

* every driven input, evaluated at every cycle's capture point, is within 1 mV
  of either 0 V or ``VIH`` (the control);
* a mid-program change emits the hold/edge pair explicitly (``bus_re``'s
  ``639.9n`` at the old value immediately followed by ``640.0n`` at the new one);
* breakpoint hygiene: ``t = 0`` first, ``t_stop`` last, strictly increasing
  formatted timestamps (no duplicate breakpoint from an under-wide edge), and an
  input that never changes still emits exactly the two endpoints;
* the grid request timeouts this issue must not disturb are unchanged.

Pure Python: no klt, no PDK, no ngspice.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import program as P  # noqa: E402

spec = importlib.util.spec_from_file_location("make_requests", HERE / "make-requests.py")
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

#: how close to a rail a capture-point sample must sit (V). The pre-#488 ramp
#: missed by hundreds of mV, so this is loose enough to be about shape and tight
#: enough that a residual ramp of any practical width still fails.
RAIL_TOL_V = 1e-3

_PWL_RE = re.compile(r"^V(\S+) (\S+) 0 PWL\((.*)\)$")


def parse_card(card: str) -> tuple[str, str, list[tuple[float, float]]]:
    """``(signal, net, breakpoints)`` from one emitted PWL card."""
    m = _PWL_RE.match(card)
    assert m, f"not a PWL card: {card!r}"
    body = m.group(3).split()
    assert len(body) % 2 == 0 and body, f"odd breakpoint body: {card!r}"
    pts = []
    for i in range(0, len(body), 2):
        t_tok = body[i]
        assert t_tok.endswith("n"), f"time {t_tok!r} is not in ns: {card!r}"
        pts.append((float(t_tok[:-1]), float(body[i + 1])))
    return m.group(1), m.group(2), pts


def pwl_at(pts: list[tuple[float, float]], t: float) -> float:
    """What ngspice's PWL source produces at ``t``: linear between breakpoints."""
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    raise AssertionError(f"t={t} not covered by {pts}")


def off_rail_samples(limit: int | None) -> list[tuple[str, int, float, float]]:
    """``(signal, cycle, t_ns, volts)`` for every capture point off a rail."""
    cycles, _ = P.build_program(limit)
    n_cycles = len(cycles)
    bad = []
    for card in mr.input_cards(cycles, n_cycles):
        sig, _net, pts = parse_card(card)
        for k in range(n_cycles):
            t = P.t_edge_ns(k) + P.CAPTURE_NS
            v = pwl_at(pts, t)
            if min(abs(v - 0.0), abs(v - mr.VIH)) > RAIL_TOL_V:
                bad.append((sig, k, t, v))
    return bad


def test_capture_points_sit_at_a_rail() -> None:
    """THE CONTROL (issue #488): no driven input is mid-flight at a capture point.

    Fails on the pre-#488 change-instants-only shape with 14 off-rail samples on
    the limit=6 startup deck and 344 of 3000 on the full grid program.
    """
    for limit, label, n_expected in ((6, "limit=6 startup probe", 240),
                                     (None, "full grid program", 3000)):
        cycles, _ = P.build_program(limit)
        cards = mr.input_cards(cycles, len(cycles))
        n_samples = len(cards) * len(cycles)
        assert n_samples == n_expected, (label, n_samples, n_expected)
        bad = off_rail_samples(limit)
        assert not bad, (
            f"{label}: {len(bad)} of {n_samples} (input x capture point) samples "
            f"are off-rail by more than {RAIL_TOL_V * 1e3:.0f} mV -- the PWL "
            f"ramps between cycles instead of holding. Worst: "
            f"{min(bad, key=lambda r: abs(r[3] - mr.VIH / 2.0))}"
        )


def test_change_emits_hold_then_edge() -> None:
    """A mid-program change is a hold breakpoint plus a ~100 ps edge, not a ramp.

    ``bus_re`` is 1 in the limit=6 startup deck's first cycle and 0 from the
    fourth on, so its single change lands at t_edge(3)+SKEW = 640 ns.
    """
    cycles, _ = P.build_program(6)
    cards = {parse_card(c)[0]: parse_card(c)[2] for c in mr.input_cards(cycles, len(cycles))}
    pts = cards["bus_re"]
    t_change = P.t_edge_ns(3) + P.SKEW_NS
    assert t_change == 640.0, t_change
    idx = [i for i, (t, _v) in enumerate(pts) if t == t_change]
    assert len(idx) == 1, (f"expected exactly one breakpoint at {t_change}n", pts)
    i = idx[0]
    assert i > 0, ("change breakpoint must be preceded by a hold point", pts)
    t_hold, v_hold = pts[i - 1]
    t_edge, v_edge = pts[i]
    assert (t_hold, v_hold) == (t_change - mr.EDGE_NS, mr.VIH), (
        f"hold point before the {t_change}n change should be "
        f"({t_change - mr.EDGE_NS}n, {mr.VIH}) -- got ({t_hold}n, {v_hold})", pts)
    assert v_edge == 0.0, (f"bus_re should switch to 0 V at {t_change}n", pts)
    # the edge itself is the declared edge width, not a cycle-long ramp
    assert abs((t_edge - t_hold) - mr.EDGE_NS) < 1e-9, (t_hold, t_edge)
    # and the formatted card really carries both timestamps distinctly
    card = next(c for c in mr.input_cards(cycles, len(cycles)) if c.startswith("Vbus_re "))
    assert "639.9n 1.800 640.0n 0.000" in card, card


def test_breakpoint_hygiene() -> None:
    """Endpoints, strict monotonicity in the FORMATTED times, and a constant input."""
    for limit in (6, None):
        cycles, _ = P.build_program(limit)
        n_cycles = len(cycles)
        t_stop = P.t_stop_ns(cycles)
        for card in mr.input_cards(cycles, n_cycles):
            sig, _net, pts = parse_card(card)
            assert pts[0][0] == 0.0, (sig, "first breakpoint must be t=0", pts[:2])
            assert pts[-1][0] == t_stop, (sig, "last breakpoint must be t_stop", pts[-2:])
            # duplicate formatted timestamps are what an under-wide EDGE_NS
            # produces; pwl_card writes times as f"{t:.1f}n", so compare those
            shown = [f"{t:.1f}" for t, _v in pts]
            assert len(set(shown)) == len(shown), (
                sig, "two breakpoints share a formatted timestamp", shown)
            assert shown == sorted(shown, key=float), (sig, "times not increasing", shown)
            assert all(v in (0.0, mr.VIH) for _t, v in pts), (
                sig, "every breakpoint value is a rail", pts)

    # an input that never changes still emits exactly its two endpoints. In the
    # limit=6 startup deck out_ready is 0 in every cycle.
    cycles, _ = P.build_program(6)
    inputs = P.cycle_inputs(cycles)
    assert len({i["out_ready"] for i in inputs}) == 1, [i["out_ready"] for i in inputs]
    card = next(c for c in mr.input_cards(cycles, len(cycles)) if c.startswith("Vout_ready "))
    _sig, _net, pts = parse_card(card)
    assert len(pts) == 2, ("a constant input needs no hold point", pts)
    assert pts == [(0.0, 0.0), (P.t_stop_ns(cycles), 0.0)], pts


def test_grid_timeouts_unchanged() -> None:
    """Issue #488 acceptance criterion 4: this fix touches no timeout.

    Both the source constant and the four committed grid ``request.json`` files
    (which is what a re-submit would actually use).
    """
    assert mr.GRID_TIMEOUT_S == 21600, mr.GRID_TIMEOUT_S
    grids = sorted((HERE / "corners").glob("grid-*/request.json"))
    assert len(grids) == 4, [str(p) for p in grids]
    for req in grids:
        d = json.loads(req.read_text())
        assert d["options"]["timeout_s"] == mr.GRID_TIMEOUT_S, (str(req), d["options"])
        assert d["batch"]["poll_timeout_s"] == 6600, (str(req), d["batch"])


def main() -> int:
    test_capture_points_sit_at_a_rail()
    test_change_emits_hold_then_edge()
    test_breakpoint_hygiene()
    test_grid_timeouts_unchanged()
    print("test_make_requests OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
