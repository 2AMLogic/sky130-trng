#!/usr/bin/env python3
"""Compare a gate-model run's digital responses with the normative model (#486).

AC3 of issue #486: the short program is run on the generated gate-level model
(``make-gate-model.py``) and "its digital responses are compared with the
normative behavioural model". This is that comparison, and the measured-rate
reduction that goes with it.

Inputs are the ``klt sim`` report and the generator's ``plan.json``; the oracle
is ``digital/model/digital_top.py`` driven through
``program.model_replay()`` -- the *same* normative function the transistor-level
reduction uses, not a second implementation of it.

Mapping (identical to ``make-requests.py``'s capture convention, which
``model_replay`` is written against):

* ``rdata_k<k>_b<bit>`` is sampled at ``t_edge(k+1) + RDATA_NS``, i.e. during
  cycle ``k+1``, so it is compared with the model row for cycle ``k+1``;
* ``<sig>_k<k>`` is sampled at ``t_edge(k) + RDATA_NS``, during cycle ``k``, so
  it is compared with the model row for cycle ``k``.

A measured voltage is decoded to a logical bit only if it sits within
``LEVEL_TOL`` of ``vss`` or of the supply. Anything in between -- in
particular ``dac_bridge``'s ``out_undef`` (supply/2), which is what an UNKNOWN
digital net reads as -- is reported as ``undecodable`` and makes the
comparison FAIL. It is never rounded to the nearer rail: an X that silently
decoded to 0 would turn a broken model into a passing one.

``--emit-record-json`` writes the reduced result (rate, margin, per-row
comparison) next to the report so the dated record can cite a file rather than
a transcript. Nothing here simulates anything.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUG = HERE.parent
REPO = SLUG.parents[1]
sys.path.insert(0, str(SLUG))
import program as P  # noqa: E402

sys.path.insert(0, str(REPO / "digital"))
sys.path.insert(0, str(REPO / "sim" / "bin"))

#: a measured level must be this close (V) to vss or to the supply to decode
LEVEL_TOL = 0.05

#: DR-0017's per-unit wall-clock ceiling (s) and the program the grid runs
UNIT_CEILING_S = 3480.0
#: measured analog-chain rate (s per simulated ns), records/20261105-analog-chain-probe.md
ANALOG_RATE_S_PER_NS = 0.057

_RDATA_RE = re.compile(r"^rdata_k(\d+)_b(\d+)$")
_ODATA_RE = re.compile(r"^odata_k(\d+)_b(\d+)$")
_SCALAR_RE = re.compile(r"^(alarm|gated|startup_done|out_valid)_k(\d+)$")


def decode(value: float | None, supply_v: float) -> int | None:
    """Logical bit, or ``None`` when the level is not a resolved rail."""
    if value is None:
        return None
    if abs(value) <= LEVEL_TOL:
        return 0
    if abs(value - supply_v) <= LEVEL_TOL:
        return 1
    return None


def duplicate_measurement_names(measurements: list[dict]) -> list[str]:
    """Sorted names that appear more than once in a measurement list.

    Every name-keyed read of the list (``{m["name"]: m["value"]}`` and
    friends) lets a repeat displace the entry it duplicates while the
    list-length count stays honest, so callers guard on this before
    deduplicating (#548 hardened the gate-model report this way; #642
    shares the guard with the 12-point reducer).
    """
    return sorted(name for name, n in
                  Counter(m["name"] for m in measurements).items() if n > 1)


def digital_budget_s_per_ns(t_stop_ns: float) -> float:
    """The budget this slice is measured against, stated before the run.

    The whole block has ``UNIT_CEILING_S`` for the full program's
    ``t_stop``; the analog chain is measured at ``ANALOG_RATE_S_PER_NS``, so
    what is left for the digital half is the difference. Declared assumption:
    the standalone gate-model rate is a LOWER BOUND on the digital half's
    contribution to a coupled run, and linear additivity of the two halves is
    an extrapolation, not a measurement.
    """
    return UNIT_CEILING_S / t_stop_ns - ANALOG_RATE_S_PER_NS


def response_checks(measured: dict, rows: list[dict], supply_v: float,
                    n_cycles: int) -> tuple[list[dict], list[dict]]:
    checks: list[dict] = []
    undecodable: list[dict] = []

    # -- 32-bit bus read data, per read cycle
    rdata_bits: dict[int, dict[int, float]] = {}
    for name, value in measured.items():
        m = _RDATA_RE.match(name)
        if m:
            rdata_bits.setdefault(int(m.group(1)), {})[int(m.group(2))] = value
    def decode_word(prefix: str, k: int, samples: dict[int, float]):
        # completeness is loud, by bit set: all 32 bits of a word are
        # generated as one .meas set with a single timestamp, so a word
        # legitimately clipped by the t_stop guard is absent as a WHOLE --
        # a partial word in the report is a dropped result, and an absent
        # bit would silently decode as 0 below.
        missing = sorted(set(range(32)) - set(samples))
        if missing:
            raise SystemExit(
                f"{prefix}_k{k}: bit measurements absent for {missing} -- "
                f"an absent .meas result would decode as 0, refusing")
        word = 0
        bad = False
        for bit, value in samples.items():
            b = decode(value, supply_v)
            if b is None:
                undecodable.append({"measurement": f"{prefix}_k{k}_b{bit}", "value": value})
                bad = True
            elif b:
                word |= 1 << bit
        return (None if bad else word)

    for k in sorted(rdata_bits):
        if k + 1 >= len(rows):
            continue  # no cycle to observe it in (guarded at generation too)
        word = decode_word("rdata", k, rdata_bits[k])
        expect = rows[k + 1]["model"]["bus_rdata"]
        checks.append({
            "what": f"bus_rdata after the read in cycle {k}",
            "measurement": f"rdata_k{k}_b*",
            "model_row": k + 1,
            "simulated": word,
            "model": expect,
            "match": word is not None and word == expect,
        })

    # -- 32-bit streaming word, only where the model reports out_valid = 1.
    # When out_valid is 0 the FIFO head the model exposes is not an output the
    # hardware is claiming, so asserting it would be comparing don't-cares.
    odata_bits: dict[int, dict[int, float]] = {}
    for name, value in measured.items():
        m = _ODATA_RE.match(name)
        if m:
            odata_bits.setdefault(int(m.group(1)), {})[int(m.group(2))] = value
    for k in sorted(odata_bits):
        if k >= len(rows):
            continue
        if not rows[k]["model"]["out_valid"]:
            checks.append({
                "what": f"out_data during cycle {k}",
                "measurement": f"odata_k{k}_b*",
                "model_row": k,
                "simulated": None,
                "model": None,
                "match": True,
                "not_compared": "model reports out_valid = 0 for this cycle",
            })
            continue
        word = decode_word("odata", k, odata_bits[k])
        expect = rows[k]["model"]["out_data"]
        checks.append({
            "what": f"out_data during cycle {k}",
            "measurement": f"odata_k{k}_b*",
            "model_row": k,
            "simulated": word,
            "model": expect,
            "match": word is not None and word == expect,
        })

    # -- scalar observables, per cycle
    for name, value in sorted(measured.items()):
        m = _SCALAR_RE.match(name)
        if not m:
            continue
        sig, k = m.group(1), int(m.group(2))
        if k >= n_cycles:
            continue
        b = decode(value, supply_v)
        if b is None:
            undecodable.append({"measurement": name, "value": value})
        expect = rows[k]["model"][sig]
        checks.append({
            "what": f"{sig} during cycle {k}",
            "measurement": name,
            "model_row": k,
            "simulated": b,
            "model": expect,
            "match": b is not None and b == expect,
        })

    return checks, undecodable


def compare_coupled(corner: dict, plan: dict) -> dict:
    """Replay actual sampler inputs and check the strobe schedule independently."""
    from loadmod import load_module
    requests = load_module("coupled_requests", SLUG / "make-requests.py")
    cycles, _ = P.build_program()
    stop = P.t_stop_ns(cycles)
    if plan["name"] != "coupled-full" or plan["analysis"]["args"].split()[-1] != f"{stop:.0f}n":
        raise SystemExit("digital replay requires the full coupled program")
    required = {m["name"] for m in requests.coupled_measurements(cycles)[0]}
    samples = corner.get("measurements", [])
    measured = {m["name"]: m.get("value") for m in samples}
    if len(measured) != len(samples) or measured.keys() - required:
        raise SystemExit("unexpected or duplicate measurement in coupled report")
    if plan["measurement_count"] != len(required):
        raise SystemExit("coupled plan measurement count differs from the program")
    # Keep missing values in the response set so an absent word cannot vanish.
    missing = []
    for name in sorted(required):
        v = measured.get(name)
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            measured[name] = None
            missing.append(name)
    supply = float(plan["reductions"]["supply_v"])
    bits = []
    strobes = []
    valid_mismatches = []
    undecodable = []
    for k, inp in enumerate(P.cycle_inputs(cycles)):
        name = f"raw_valid_k{k}"
        valid = decode(measured[name], supply)
        if valid is None:
            undecodable.append({"measurement": name, "value": measured[name]})
            continue
        strobes.append(valid)
        if valid != inp["raw_valid"]:
            valid_mismatches.append(k)
        if valid:
            name = f"raw_bit_k{k}"
            bit = decode(measured[name], supply)
            if bit is None:
                undecodable.append({"measurement": name, "value": measured[name]})
            else:
                bits.append(bit)
    checks = []
    if not undecodable:
        rows = P.model_replay(bits, captured_valid=strobes)
        checks, undecodable = response_checks(measured, rows, supply, len(cycles))
    compared = [c for c in checks if not c.get("not_compared")]
    mismatches = [c for c in compared if not c["match"]]
    runtime = corner.get("runtime_s")
    reached = stop if measured["clk_at_stop"] is not None else None
    rate = runtime / stop if reached and runtime and runtime > 0 else None
    budget = 3000.0 / stop  # records/20261121-coupled-rate.md, fixed before submission
    within = rate <= budget if rate is not None else None
    matches = len(compared) - len(mismatches)
    passed = (corner["status"] == "pass" and within and compared and not missing
              and not mismatches and not valid_mismatches and not undecodable)
    return {
        "issue": 596, "corner_id": corner["corner_id"], "corner_status": corner["status"],
        "oracle": "digital/model/digital_top.py via program.model_replay()",
        "checks": checks, "checks_total": len(compared), "checks_matched": matches,
        "mismatches": mismatches, "valid_mismatches": valid_mismatches,
        "missing_measurements": missing, "level_decode": {"tol_v": LEVEL_TOL, "undecodable": undecodable},
        "rate": {"runtime_s": runtime, "simulated_ns": reached, "s_per_simulated_ns": rate},
        "pass_criterion": {"coupled_budget_s_per_ns": budget, "within_budget": within},
        "verdict": "pass" if passed else "fail",
    }


def compare(report: dict, plan: dict) -> dict:
    corners = report.get("corners") or []
    if len(corners) != 1:
        raise SystemExit(f"expected exactly one corner in the report, got {len(corners)}")
    corner = corners[0]
    if plan.get("raw_source") == "analog_sampler":
        environment = report.get("environment", {})
        if environment.get("backend", {}).get("resolved") != "batch":
            raise SystemExit("a coupled fleet rate requires a batch report")
        if environment.get("netlist_sha256") != plan["netlist_sha256"]:
            raise SystemExit("batch report netlist differs from the coupled deck")
        expected_supply = {name: axis[0] for name, axis in plan["corners"]["supply_v"].items()}
        if (corner.get("process") != "tt" or corner.get("temperature_c") != 27.0
                or corner.get("supply_v") != expected_supply):
            raise SystemExit("batch report corner differs from the nominal coupled request")
        return compare_coupled(corner, plan)
    supply_v = float(plan["reductions"]["supply_v"])
    n_cycles = int(plan["program"]["cycles"])
    t_stop_ns = float(plan["program"]["t_stop_ns"])
    measured = {m["name"]: m["value"] for m in corner["measurements"]}

    # completeness is loud, by count: the plan states how many measurements
    # the deck was GENERATED with, so the report must carry every one. A
    # dropped entry would otherwise never be noticed below -- an absent name
    # simply matches no check -- and the run would pass with fewer checked
    # rows than the run was measured for.
    n_meas = len(corner["measurements"])
    if n_meas != int(plan["measurement_count"]):
        raise SystemExit(
            f"report carries {n_meas} measurements, plan.json declares "
            f"{int(plan['measurement_count'])}: a measurement the deck did "
            f"not produce must refuse the comparison, not shrink it")

    # completeness is loud, by name too: the checks below all read the
    # deduplicated dict, so a repeated name displaces the entry it
    # duplicates -- the count guard above (taken from the list length)
    # cannot see that, and the displaced measurement's check is silently
    # dropped while the verdict stays pass.
    if len(measured) != int(plan["measurement_count"]):
        duplicates = duplicate_measurement_names(corner["measurements"])
        raise SystemExit(
            f"report carries {len(measured)} distinct measurement names in "
            f"{n_meas} entries, plan.json declares "
            f"{int(plan['measurement_count'])}: duplicate measurement "
            f"name(s) {duplicates} displace the entries they repeat, "
            f"refusing")

    # the oracle: the FULL program replayed through the normative model. The
    # truncated program is a strict prefix of it (program.build_program(limit=k)
    # slices the same cycle list) and the model is causal, so rows 0..n-1 are
    # the truncated run's rows. The raw bits the deck drove are the committed
    # pattern's first bits, in the same order.
    bits = [int(c) for c in plan["raw_bit_pattern"]]
    full_bits = bits + [0] * (P.N_SAMPLES_REG + P.N_SAMPLES_STREAM - len(bits))
    rows = P.model_replay(full_bits)

    checks, undecodable = response_checks(measured, rows, supply_v, n_cycles)

    # -- rate
    runtime_s = float(corner["runtime_s"])
    rate = runtime_s / t_stop_ns
    budget = digital_budget_s_per_ns(float(P.t_stop_ns(P.build_program()[0])))
    mismatches = [c for c in checks if not c["match"]]
    compared = [c for c in checks if not c.get("not_compared")]
    return {
        "issue": 486,
        "realisation": plan["realisation"],
        "corner_id": corner["corner_id"],
        "corner_status": corner["status"],
        "oracle": "digital/model/digital_top.py via program.model_replay()",
        "level_decode": {"tol_v": LEVEL_TOL, "supply_v": supply_v,
                         "undecodable": undecodable},
        "checks": checks,
        "checks_total": len(compared),
        "checks_matched": len(compared) - len(mismatches),
        "checks_not_compared": len(checks) - len(compared),
        "mismatches": mismatches,
        "rate": {
            "runtime_s": runtime_s,
            "simulated_ns": t_stop_ns,
            "s_per_simulated_ns": rate,
            "peak_rss_bytes": corner.get("peak_rss_bytes"),
        },
        "pass_criterion": {
            "stated_before_the_run": True,
            "unit_ceiling_s": UNIT_CEILING_S,
            "full_program_t_stop_ns": float(P.t_stop_ns(P.build_program()[0])),
            "analog_rate_s_per_ns": ANALOG_RATE_S_PER_NS,
            "digital_budget_s_per_ns": budget,
            "margin_x": (budget / rate) if rate > 0 else None,
            "within_budget": rate <= budget,
            "assumption": "the standalone gate-model rate is a LOWER BOUND on the "
                          "digital half's contribution to a coupled run; linear "
                          "additivity of the two halves is an extrapolation, not a "
                          "measurement",
        },
        "verdict": ("pass" if (not mismatches and not undecodable
                              and corner["status"] == "pass" and rate <= budget)
                    else "fail"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report", type=Path, help="klt sim report.json of the gate-model run")
    ap.add_argument("plan", type=Path, help="plan.json make-gate-model.py wrote")
    ap.add_argument("--emit-record-json", type=Path, default=None,
                    help="also write the reduced result here")
    args = ap.parse_args(argv)
    result = compare(json.loads(args.report.read_text()),
                     json.loads(args.plan.read_text()))
    if args.emit_record_json:
        args.emit_record_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if result["issue"] == 596:
        print(json.dumps({k: v for k, v in result.items() if k != "checks"}, indent=2))
        return 0 if result["verdict"] == "pass" else 1
    print(f"corner {result['corner_id']}: {result['corner_status']}")
    print(f"oracle {result['oracle']}")
    for c in result["checks"]:
        if c.get("not_compared"):
            print(f"  --  {c['what']:<42} not compared ({c['not_compared']})")
            continue
        flag = "ok " if c["match"] else "MISMATCH"
        hexy = c["measurement"].startswith(("rdata", "odata"))
        sim, mod = c["simulated"], c["model"]
        sim_s = "UNDECODABLE" if sim is None else (f"0x{sim:08x}" if hexy else str(sim))
        mod_s = f"0x{mod:08x}" if hexy else str(mod)
        print(f"  {flag} {c['what']:<42} sim={sim_s:<12} model={mod_s}")
    r, pc = result["rate"], result["pass_criterion"]
    print(f"rate: {r['runtime_s']:.3f} s / {r['simulated_ns']:.0f} simulated ns = "
          f"{r['s_per_simulated_ns']:.5f} s per simulated ns")
    print(f"budget: {pc['digital_budget_s_per_ns']:.4f} s/sim-ns "
          f"({pc['unit_ceiling_s']:.0f} s / {pc['full_program_t_stop_ns']:.0f} ns "
          f"- {pc['analog_rate_s_per_ns']} analog) -> margin "
          f"{pc['margin_x']:.1f}x, within_budget={pc['within_budget']}")
    print(f"checks {result['checks_matched']}/{result['checks_total']} matched; "
          f"verdict: {result['verdict'].upper()}")
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
