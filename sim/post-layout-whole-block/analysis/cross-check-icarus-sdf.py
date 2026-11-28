#!/usr/bin/env python3
"""Cross-check the ngspice timed-delay gate model against Icarus + SDF (#812).

Residual verification of #486: drives the SDF-annotated routed netlist
(``layout/trng_digital/trng_digital.routed.v`` +
``layout/trng_digital/trng_digital.sdf.gz``, ``tt_025C_1v80``) under Icarus
Verilog via ``klt functional-verification`` with the exact same
``program.build_program(N)`` stimulus and ``raw_bit`` sequence that drives the
standalone ngspice gate model (``make-gate-model.py``) at the gate model's
100 ns clock period (``program.TS_NS``), then compares both runs word for word
with each other and with the normative model (``program.model_replay()``).

Reuses the SDF preparation and ``klt functional-verification`` invocation of
``sim/digital-sdf-timed-verification/harness/fv-sdf-cosim.py`` (routed netlist,
timing ``specify`` cell models, the 39-entry zero-delay bit-selected-port
``INTERCONNECT`` scrub, ``options.sdf``) without forking a second SDF path.

Scope and limitations:
* One corner only: ``tt_025C_1v80`` (matching the committed #486 gate-model
  run and the committed #227 SDF).
* Icarus 13.0 does not implement SDF ``TIMINGCHECK`` (``sdf.partial: true``):
  setup/hold/recovery/removal limits are not checked in simulation; agreement
  covers output values and cycle timing only.
* Disagreements are always reported and produce a non-zero exit code.

Usage (worktree-local venv, touches nothing host-wide)::

    uv venv --python 3.13 .venv
    uv pip install --python .venv/bin/python "klayout-tools==0.8.0" "cocotb==2.0.1"
    python3 sim/post-layout-whole-block/analysis/cross-check-icarus-sdf.py \\
        --klt "$PWD/.venv/bin/klt" --cycles 75 --emit-json /tmp/xcheck.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLUG = HERE.parent
REPO = SLUG.parents[1]

sys.path.insert(0, str(SLUG))
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "layout" / "bin"))

import program as P
from _hashing import sha256_file, sha256_text
from _klt_common import BuildError, klt_version, libs_ref
from evidence_paths import sanitize_paths
from loadmod import load_module
from measurement_names import duplicate_measurement_names

_GATE_GEN = load_module("make_gate_model_cc", SLUG / "make-gate-model.py")
_FV_SDF = load_module(
    "fv_sdf_cosim_cc",
    REPO / "sim" / "digital-sdf-timed-verification" / "harness" / "fv-sdf-cosim.py",
)

TB_MODULE = "tb_whole_block_program"
TB_FILE = HERE / f"{TB_MODULE}.py"
DEFAULT_GATE_REPORT = SLUG / "runs" / "20261114-gate-model-full" / "report.json"
DEFAULT_GATE_PLAN = SLUG / "corners" / "gate-model-full" / "plan.json"

SCALAR_SIGNALS = ("out_valid", "alarm", "gated", "startup_done")
_RDATA_RE = re.compile(r"^rdata_k(\d+)_b(\d+)$")
_ODATA_RE = re.compile(r"^odata_k(\d+)_b(\d+)$")
_SCALAR_RE = re.compile(r"^(alarm|gated|startup_done|out_valid)_k(\d+)$")


class CrossCheckError(ValueError):
    """Fail-closed error on malformed inputs, missing measurements, or bad runs."""


# ---------------------------------------------------------------------------
# Pure, stdlib-only stimulus / extraction / comparison logic (unit-tested)
# ---------------------------------------------------------------------------

def build_stimulus_vectors(
    n_cycles: int,
    raw_bit_pattern: str | None = None,
) -> dict:
    """Build the shared ``program.build_program(n_cycles)`` stimulus and hashes.

    ``shared_input_cards_sha256`` matches ``test_standalone_waveform_bytes``'s
    40-card request hash; ``gate_stimulus_cards_sha256`` matches its full
    gate-model stimulus hash (``Vrst_n``, ``Vclk``, ``Vraw_bit`` + 40 cards).
    """
    if n_cycles <= 0:
        raise CrossCheckError(f"n_cycles must be positive, got {n_cycles}")
    cycles, phases = P.build_program(limit=n_cycles)
    if len(cycles) != n_cycles:
        raise CrossCheckError(
            f"program has only {len(cycles)} cycles, cannot take N={n_cycles}")
    inputs = P.cycle_inputs(cycles)
    n_samples = sum(1 for inp in inputs if inp["raw_valid"])
    pattern = _GATE_GEN.RAW_BIT_PATTERN if raw_bit_pattern is None else raw_bit_pattern
    if n_samples > len(pattern):
        raise CrossCheckError(
            f"raw_bit_pattern has {len(pattern)} bits, need {n_samples}")
    used_pattern = pattern[:n_samples]
    bits = [int(c) for c in used_pattern]

    vectors: list[dict] = []
    bit_i = 0
    raw_bit_cur = 0
    for k, inp in enumerate(inputs):
        if inp["raw_valid"]:
            raw_bit_cur = bits[bit_i]
            bit_i += 1
        vectors.append({
            "cycle": k,
            "raw_bit": raw_bit_cur,
            "raw_valid": inp["raw_valid"],
            "addr": inp["addr"],
            "we": inp["we"],
            "re": inp["re"],
            "wdata": inp["wdata"],
            "out_ready": inp["out_ready"],
        })

    stimulus_text = "".join(
        f"{v['raw_bit']} {v['raw_valid']} {v['addr']} {v['we']} {v['re']} "
        f"{v['wdata']:08x} {v['out_ready']}\n"
        for v in vectors
    )
    shared_cards = P.input_cards(cycles, n_cycles, P.VIH)
    gate_cards = _GATE_GEN.stimulus_cards(cycles, P.VIH)
    return {
        "n_cycles": n_cycles,
        "cycles": cycles,
        "phases": phases,
        "vectors": vectors,
        "raw_bit_pattern": used_pattern,
        "stimulus_text": stimulus_text,
        "stimulus_text_sha256": sha256_text(stimulus_text),
        "shared_input_cards_count": len(shared_cards),
        "shared_input_cards_sha256": sha256_text("\n".join(shared_cards) + "\n"),
        "gate_stimulus_cards_sha256": sha256_text("\n".join(gate_cards) + "\n"),
    }


def _decode_word(
    prefix: str,
    k: int,
    samples: dict[int, float | None],
    supply_v: float,
    undecodable: list[dict],
) -> int | None:
    missing = sorted(set(range(32)) - set(samples))
    if missing:
        raise CrossCheckError(
            f"{prefix}_k{k}: bit measurements absent for {missing} -- refusing")
    word = 0
    bad = False
    for bit, value in samples.items():
        b = P.decode(value, supply_v)
        if b is None:
            undecodable.append({"measurement": f"{prefix}_k{k}_b{bit}", "value": value})
            bad = True
        elif b:
            word |= 1 << bit
    return None if bad else word


def extract_gate_model_trace(report: dict, plan: dict, n_cycles: int) -> dict:
    """Decode ``n_cycles`` of digital responses from a gate-model ``klt sim`` report."""
    corners = report.get("corners") or []
    if len(corners) != 1:
        raise CrossCheckError(
            f"expected exactly one corner in gate-model report, got {len(corners)}")
    corner = corners[0]
    plan_cycles = int(plan["program"]["cycles"])
    if n_cycles > plan_cycles:
        raise CrossCheckError(
            f"requested N={n_cycles} cycles exceeds gate-model plan ({plan_cycles})")

    measurements = corner.get("measurements") or []
    declared_count = int(plan["measurement_count"])
    if len(measurements) != declared_count:
        raise CrossCheckError(
            f"gate-model report carries {len(measurements)} measurements, "
            f"plan.json declares {declared_count}")
    duplicates = duplicate_measurement_names(measurements)
    if duplicates:
        raise CrossCheckError(
            f"gate-model report carries duplicate measurement name(s) {duplicates}")
    measured = {m["name"]: m["value"] for m in measurements}

    supply_v = float(plan["reductions"]["supply_v"])
    undecodable: list[dict] = []

    rdata_bits: dict[int, dict[int, float | None]] = {}
    odata_bits: dict[int, dict[int, float | None]] = {}
    scalars: dict[int, dict[str, int | None]] = {}
    for name, value in measured.items():
        m = _RDATA_RE.match(name)
        if m:
            k = int(m.group(1))
            if k + 1 < n_cycles:
                rdata_bits.setdefault(k, {})[int(m.group(2))] = value
            continue
        m = _ODATA_RE.match(name)
        if m:
            k = int(m.group(1))
            if k < n_cycles:
                odata_bits.setdefault(k, {})[int(m.group(2))] = value
            continue
        m = _SCALAR_RE.match(name)
        if m:
            sig, k = m.group(1), int(m.group(2))
            if k < n_cycles:
                b = P.decode(value, supply_v)
                if b is None:
                    undecodable.append({"measurement": name, "value": value})
                scalars.setdefault(k, {})[sig] = b

    rdata = {
        k: _decode_word("rdata", k, rdata_bits[k], supply_v, undecodable)
        for k in sorted(rdata_bits)
    }
    odata = {
        k: _decode_word("odata", k, odata_bits[k], supply_v, undecodable)
        for k in sorted(odata_bits)
    }

    for k in range(n_cycles):
        row = scalars.get(k, {})
        missing_sigs = [s for s in SCALAR_SIGNALS if s not in row]
        if missing_sigs:
            raise CrossCheckError(
                f"gate-model report missing scalar measurements {missing_sigs} at cycle {k}")

    env = report.get("environment") or {}
    return {
        "n_cycles": n_cycles,
        "plan_cycles": plan_cycles,
        "corner_id": corner.get("corner_id"),
        "corner_status": corner.get("status"),
        "supply_v": supply_v,
        "ngspice_version": (
            plan.get("tools", {}).get("ngspice")
            or f"ngspice-{env.get('engine_version', 'unknown')}"
        ),
        "ngspice_binary_sha256": (env.get("engine_build") or {}).get("binary_sha256"),
        "liberty_deck": plan.get("liberty_deck"),
        "liberty_sha256": plan.get("liberty_sha256"),
        "routed_netlist_sha256": plan.get("routed_netlist_sha256"),
        "netlist_sha256": plan.get("netlist_sha256"),
        "gate_model_sha256": plan.get("gate_model_sha256"),
        "raw_bit_pattern": plan.get("raw_bit_pattern"),
        "rdata": rdata,
        "odata": odata,
        "scalars": scalars,
        "undecodable": undecodable,
    }


def _is_resolved_int(val) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _first_out_valid(values: list) -> tuple[int | None, list[int]]:
    """Return ``(first_cycle_with_1, unresolvable_cycles)``."""
    first: int | None = None
    bad: list[int] = []
    for k, v in enumerate(values):
        if not _is_resolved_int(v) or v not in (0, 1):
            bad.append(k)
        elif v == 1 and first is None:
            first = k
    return first, bad


def _fmt_val(val, *, is_word: bool) -> str:
    if val is None:
        return "UNDECODABLE"
    if _is_resolved_int(val):
        return f"0x{val:08x}" if is_word else str(val)
    return str(val)


def compare_traces(
    gate_obs: dict,
    icarus_rows: list[dict],
    model_rows: list[dict],
    n_cycles: int,
) -> dict:
    """Compare gate-model, Icarus + SDF, and normative model traces word for word.

    Fail-closed rules:
    * Refuses truncated traces (``len(icarus_rows) != n_cycles`` or missing
      gate cycles) via :class:`CrossCheckError`.
    * Never coerces unresolvable ``X``/``Z`` strings or ``None`` to 0.
    * When ``N`` is shorter than the first ``out_valid`` assertion,
      ``first_out_valid["status"]`` is ``"not_reached"``, never ``"match"``.
    * Any disagreement across gate/Icarus/model sets ``verdict = "fail"``.
    """
    if len(icarus_rows) != n_cycles:
        raise CrossCheckError(
            f"Icarus trace has {len(icarus_rows)} cycles, expected {n_cycles}")
    if len(model_rows) < n_cycles:
        raise CrossCheckError(
            f"model trace has {len(model_rows)} cycles, need at least {n_cycles}")
    for k, row in enumerate(icarus_rows):
        if row.get("cycle") != k:
            raise CrossCheckError(
                f"Icarus row {k} carries cycle={row.get('cycle')!r}, expected {k}")

    disagreements: list[dict] = []
    word_checks: list[dict] = []
    scalar_checks: list[dict] = []

    if gate_obs.get("corner_status") != "pass":
        disagreements.append({
            "kind": "gate_status",
            "cycle": None,
            "signal": "corner_status",
            "gate": gate_obs.get("corner_status"),
            "icarus": None,
            "model": "pass",
            "detail": f"gate-model corner status is {gate_obs.get('corner_status')!r}",
        })
    for u in gate_obs.get("undecodable") or []:
        disagreements.append({
            "kind": "undecodable",
            "cycle": None,
            "signal": u["measurement"],
            "gate": u["value"],
            "icarus": None,
            "model": None,
            "detail": f"gate-model measurement {u['measurement']} undecodable ({u['value']!r})",
        })

    # -- 1. bus_rdata words captured by the gate model (read in k, observed in k+1)
    for read_k in sorted(gate_obs["rdata"]):
        obs_k = read_k + 1
        if obs_k >= n_cycles:
            continue
        g_val = gate_obs["rdata"][read_k]
        i_val = icarus_rows[obs_k]["bus_rdata"]
        m_val = int(model_rows[obs_k]["model"]["bus_rdata"])
        gi_ok = _is_resolved_int(g_val) and _is_resolved_int(i_val) and g_val == i_val
        gm_ok = _is_resolved_int(g_val) and g_val == m_val
        im_ok = _is_resolved_int(i_val) and i_val == m_val
        entry = {
            "signal": "bus_rdata",
            "measurement": f"rdata_k{read_k}_b*",
            "read_cycle": read_k,
            "cycle": obs_k,
            "gate": g_val,
            "icarus": i_val,
            "model": m_val,
            "gate_vs_icarus": gi_ok,
            "gate_vs_model": gm_ok,
            "icarus_vs_model": im_ok,
            "all_match": gi_ok and gm_ok and im_ok,
        }
        word_checks.append(entry)
        if not entry["all_match"]:
            disagreements.append({
                "kind": "word",
                "cycle": obs_k,
                "signal": "bus_rdata",
                "measurement": entry["measurement"],
                "gate": _fmt_val(g_val, is_word=True),
                "icarus": _fmt_val(i_val, is_word=True),
                "model": _fmt_val(m_val, is_word=True),
                "detail": (
                    f"bus_rdata mismatch at cycle {obs_k} (read in cycle {read_k}): "
                    f"gate={_fmt_val(g_val, is_word=True)} "
                    f"icarus={_fmt_val(i_val, is_word=True)} "
                    f"model={_fmt_val(m_val, is_word=True)}"
                ),
            })

    # -- 2. out_data words captured by the gate model (observed in cycle k)
    for obs_k in sorted(gate_obs["odata"]):
        if obs_k >= n_cycles:
            continue
        g_ov = gate_obs["scalars"][obs_k]["out_valid"]
        i_ov = icarus_rows[obs_k]["out_valid"]
        m_ov = int(model_rows[obs_k]["model"]["out_valid"])
        if g_ov == 0 and i_ov == 0 and m_ov == 0:
            word_checks.append({
                "signal": "out_data",
                "measurement": f"odata_k{obs_k}_b*",
                "read_cycle": None,
                "cycle": obs_k,
                "gate": None,
                "icarus": None,
                "model": None,
                "not_compared": "out_valid = 0 in model, gate model and Icarus",
                "gate_vs_icarus": True,
                "gate_vs_model": True,
                "icarus_vs_model": True,
                "all_match": True,
            })
            continue
        g_val = gate_obs["odata"][obs_k]
        i_val = icarus_rows[obs_k]["out_data"]
        m_val = int(model_rows[obs_k]["model"]["out_data"])
        gi_ok = _is_resolved_int(g_val) and _is_resolved_int(i_val) and g_val == i_val
        gm_ok = _is_resolved_int(g_val) and g_val == m_val
        im_ok = _is_resolved_int(i_val) and i_val == m_val
        entry = {
            "signal": "out_data",
            "measurement": f"odata_k{obs_k}_b*",
            "read_cycle": None,
            "cycle": obs_k,
            "gate": g_val,
            "icarus": i_val,
            "model": m_val,
            "gate_vs_icarus": gi_ok,
            "gate_vs_model": gm_ok,
            "icarus_vs_model": im_ok,
            "all_match": gi_ok and gm_ok and im_ok,
        }
        word_checks.append(entry)
        if not entry["all_match"]:
            disagreements.append({
                "kind": "word",
                "cycle": obs_k,
                "signal": "out_data",
                "measurement": entry["measurement"],
                "gate": _fmt_val(g_val, is_word=True),
                "icarus": _fmt_val(i_val, is_word=True),
                "model": _fmt_val(m_val, is_word=True),
                "detail": (
                    f"out_data mismatch at cycle {obs_k}: "
                    f"gate={_fmt_val(g_val, is_word=True)} "
                    f"icarus={_fmt_val(i_val, is_word=True)} "
                    f"model={_fmt_val(m_val, is_word=True)}"
                ),
            })

    # -- 3. scalar observables across all N cycles
    for k in range(n_cycles):
        for sig in SCALAR_SIGNALS:
            g_val = gate_obs["scalars"][k][sig]
            i_val = icarus_rows[k][sig]
            m_val = int(model_rows[k]["model"][sig])
            gi_ok = _is_resolved_int(g_val) and _is_resolved_int(i_val) and g_val == i_val
            gm_ok = _is_resolved_int(g_val) and g_val == m_val
            im_ok = _is_resolved_int(i_val) and i_val == m_val
            entry = {
                "signal": sig,
                "measurement": f"{sig}_k{k}",
                "cycle": k,
                "gate": g_val,
                "icarus": i_val,
                "model": m_val,
                "gate_vs_icarus": gi_ok,
                "gate_vs_model": gm_ok,
                "icarus_vs_model": im_ok,
                "all_match": gi_ok and gm_ok and im_ok,
            }
            scalar_checks.append(entry)
            if not entry["all_match"]:
                disagreements.append({
                    "kind": "scalar",
                    "cycle": k,
                    "signal": sig,
                    "measurement": entry["measurement"],
                    "gate": _fmt_val(g_val, is_word=False),
                    "icarus": _fmt_val(i_val, is_word=False),
                    "model": _fmt_val(m_val, is_word=False),
                    "detail": (
                        f"{sig} mismatch at cycle {k}: "
                        f"gate={_fmt_val(g_val, is_word=False)} "
                        f"icarus={_fmt_val(i_val, is_word=False)} "
                        f"model={_fmt_val(m_val, is_word=False)}"
                    ),
                })

    # -- 4. Icarus vs normative model across ALL N cycles (including non-read
    #       cycles where the gate model had no bus_rdata/out_data .meas card)
    checked_rdata_cycles = {w["cycle"] for w in word_checks if w["signal"] == "bus_rdata"}
    checked_odata_cycles = {
        w["cycle"] for w in word_checks
        if w["signal"] == "out_data" and not w.get("not_compared")
    }
    icarus_full_total = 0
    icarus_full_matched = 0
    for k in range(n_cycles):
        m_row = model_rows[k]["model"]
        # bus_rdata on every cycle
        i_rd = icarus_rows[k]["bus_rdata"]
        m_rd = int(m_row["bus_rdata"])
        ok_rd = _is_resolved_int(i_rd) and i_rd == m_rd
        icarus_full_total += 1
        if ok_rd:
            icarus_full_matched += 1
        elif k not in checked_rdata_cycles:
            disagreements.append({
                "kind": "icarus_vs_model",
                "cycle": k,
                "signal": "bus_rdata",
                "measurement": None,
                "gate": None,
                "icarus": _fmt_val(i_rd, is_word=True),
                "model": _fmt_val(m_rd, is_word=True),
                "detail": (
                    f"Icarus bus_rdata vs model mismatch at cycle {k}: "
                    f"icarus={_fmt_val(i_rd, is_word=True)} "
                    f"model={_fmt_val(m_rd, is_word=True)}"
                ),
            })
        # out_data wherever model or Icarus reports out_valid != 0
        if int(m_row["out_valid"]) == 1 or icarus_rows[k]["out_valid"] != 0:
            i_od = icarus_rows[k]["out_data"]
            m_od = int(m_row["out_data"])
            ok_od = _is_resolved_int(i_od) and i_od == m_od
            icarus_full_total += 1
            if ok_od:
                icarus_full_matched += 1
            elif k not in checked_odata_cycles:
                disagreements.append({
                    "kind": "icarus_vs_model",
                    "cycle": k,
                    "signal": "out_data",
                    "measurement": None,
                    "gate": None,
                    "icarus": _fmt_val(i_od, is_word=True),
                    "model": _fmt_val(m_od, is_word=True),
                    "detail": (
                        f"Icarus out_data vs model mismatch at cycle {k}: "
                        f"icarus={_fmt_val(i_od, is_word=True)} "
                        f"model={_fmt_val(m_od, is_word=True)}"
                    ),
                })

    # -- 5. First out_valid assertion cycle across all three
    g_first, g_bad = _first_out_valid([gate_obs["scalars"][k]["out_valid"] for k in range(n_cycles)])
    i_first, i_bad = _first_out_valid([icarus_rows[k]["out_valid"] for k in range(n_cycles)])
    m_first, m_bad = _first_out_valid([int(model_rows[k]["model"]["out_valid"]) for k in range(n_cycles)])

    if g_bad or i_bad or m_bad:
        fov_status = "mismatch"
        disagreements.append({
            "kind": "first_out_valid",
            "cycle": None,
            "signal": "out_valid",
            "gate": g_first,
            "icarus": i_first,
            "model": m_first,
            "detail": (
                f"unresolvable out_valid cycles prevent first-assertion match: "
                f"gate_bad={g_bad} icarus_bad={i_bad} model_bad={m_bad}"
            ),
        })
    elif g_first is None and i_first is None and m_first is None:
        fov_status = "not_reached"
    elif g_first == i_first == m_first:
        fov_status = "match"
    else:
        fov_status = "mismatch"
        disagreements.append({
            "kind": "first_out_valid",
            "cycle": None,
            "signal": "out_valid",
            "gate": g_first,
            "icarus": i_first,
            "model": m_first,
            "detail": (
                f"first out_valid assertion cycle disagrees: "
                f"gate={g_first} icarus={i_first} model={m_first}"
            ),
        })

    first_out_valid = {
        "gate": g_first,
        "icarus": i_first,
        "model": m_first,
        "status": fov_status,
    }

    compared_words = [w for w in word_checks if not w.get("not_compared")]
    matched_words = [w for w in compared_words if w["all_match"]]
    matched_scalars = [s for s in scalar_checks if s["all_match"]]
    gi_total = len(compared_words) + len(scalar_checks)
    gi_matched = (
        sum(1 for w in compared_words if w["gate_vs_icarus"])
        + sum(1 for s in scalar_checks if s["gate_vs_icarus"])
    )

    return {
        "issue": 812,
        "n_cycles": n_cycles,
        "first_out_valid": first_out_valid,
        "word_checks": word_checks,
        "scalar_checks": scalar_checks,
        "disagreements": disagreements,
        "counts": {
            "words_compared": len(compared_words),
            "words_matched": len(matched_words),
            "words_not_compared": len(word_checks) - len(compared_words),
            "scalars_compared": len(scalar_checks),
            "scalars_matched": len(matched_scalars),
            "gate_vs_icarus_total": gi_total,
            "gate_vs_icarus_matched": gi_matched,
            "icarus_full_word_checks_total": icarus_full_total,
            "icarus_full_word_checks_matched": icarus_full_matched,
            "disagreements": len(disagreements),
        },
        "verdict": "pass" if not disagreements else "fail",
    }


# ---------------------------------------------------------------------------
# Live simulator execution (Icarus + SDF via klt functional-verification,
# reusing fv-sdf-cosim.py's SDF setup; optional fresh ngspice gate-model run)
# ---------------------------------------------------------------------------

def _iverilog_banner() -> str:
    out = subprocess.run(["iverilog", "-V"], capture_output=True, text=True, check=True)
    return (out.stdout or out.stderr).splitlines()[0].strip()


def _run_icarus_sdf(
    klt: str,
    pdk: str,
    n_cycles: int,
    raw_bit_pattern: str,
    work: Path,
) -> dict:
    """Run ``trng_digital`` routed netlist + ``tt_025C_1v80`` SDF under Icarus.

    Reuses ``fv-sdf-cosim.py``'s ``read_sdf_gz``,
    ``drop_zero_port_source_interconnects``, ``sdf_census``, and ``run_fv`` --
    no second SDF-prep path.
    """
    try:
        lref = libs_ref(pdk, klt=klt, timeout=300)
    except (BuildError, OSError, subprocess.SubprocessError) as exc:
        raise CrossCheckError(f"klt pdk find --pdk {pdk} failed: {exc}") from exc

    prim = lref / "sky130_fd_sc_hd" / "verilog" / "primitives.v"
    cells = lref / "sky130_fd_sc_hd" / "verilog" / "sky130_fd_sc_hd.v"
    for f in (prim, cells):
        if not f.is_file():
            raise CrossCheckError(f"PDK Verilog source missing: {f}")

    sdf_src = _FV_SDF.read_sdf_gz(_FV_SDF.SDF_GZ)
    routed_text = _FV_SDF.ROUTED.read_text()
    census = _FV_SDF.sdf_census(sdf_src, routed_text)
    sdf_clean, dropped = _FV_SDF.drop_zero_port_source_interconnects(
        sdf_src, ("bus_addr", "bus_wdata"))
    if not dropped or any("0.000:0.000:0.000" not in d for d in dropped):
        raise CrossCheckError("derived SDF drop set is empty or contains non-zero delay")

    sdf_path = work / "trng_digital.clean.sdf"
    sdf_path.write_text(sdf_clean)

    clk_ns = round(P.TS_NS)
    request = {
        "schema": "klt.functional_verification.request/1",
        "engine": "icarus",
        # Non-FUNCTIONAL (specify) cell models, matching fv-sdf-cosim.py
        "sources": [str(prim), str(cells), str(_FV_SDF.ROUTED)],
        "hdl_toplevel": "trng_digital",
        "testbench": {"module": TB_MODULE, "search_path": str(HERE)},
        "options": {
            "random_seed": 1,
            "sdf": {"file": str(sdf_path), "corner": _FV_SDF.SDF_CORNER},
        },
    }
    rdir = work / "icarus-sdf"
    obs_dir = rdir / "traces"
    probe_path = rdir / "timing-probe.json"
    run = _FV_SDF.run_fv(
        klt,
        request,
        rdir,
        env_extra={
            "TRNG_WB_CYCLES": str(n_cycles),
            "TRNG_WB_CLK_NS": str(clk_ns),
            "TRNG_WB_OBS_OUT": str(obs_dir),
            "TRNG_WB_TIMING_OUT": str(probe_path),
            "TRNG_WB_RAW_BITS": raw_bit_pattern,
        },
    )
    report = run.get("report")
    if not isinstance(report, dict):
        raise CrossCheckError(
            f"klt functional-verification produced no JSON report (rc={run['rc']}): "
            f"{run.get('stderr', '')[:400]}")
    if run["rc"] != 0 or report.get("status") != "pass":
        raise CrossCheckError(
            f"Icarus + SDF run failed (rc={run['rc']}, status={report.get('status')}): "
            f"{run.get('stderr', '')[:400]}")

    envr = report.get("environment") or {}
    sdf_env = envr.get("sdf")
    if not isinstance(sdf_env, dict) or sdf_env.get("annotated") is not True:
        raise CrossCheckError(f"SDF was not annotated: environment.sdf={sdf_env!r}")
    if sdf_env.get("corner") != _FV_SDF.SDF_CORNER:
        raise CrossCheckError(
            f"unexpected SDF corner {sdf_env.get('corner')!r} != {_FV_SDF.SDF_CORNER!r}")

    obs_json_path = obs_dir / "observations.json"
    stim_txt_path = obs_dir / "stimulus.txt"
    if not obs_json_path.is_file() or not stim_txt_path.is_file():
        raise CrossCheckError(f"cocotb testbench did not write trace files in {obs_dir}")

    probe_raw = json.loads(probe_path.read_text())["probe"] if probe_path.is_file() else {}
    probe_stats = {
        sig: {
            kind: {"n": len(vals), "min_ps": min(vals), "max_ps": max(vals)}
            for kind, vals in data.items() if vals
        }
        for sig, data in sorted(probe_raw.items())
    }
    clk_to_out_all = [
        v
        for d in probe_raw.values()
        for v in (d.get("clk_to_out_ps") or [])
    ]
    if not clk_to_out_all or min(clk_to_out_all) <= 0:
        raise CrossCheckError(
            f"SDF timing probe found no positive clk->out delays: {probe_stats!r}")

    return {
        "observations": json.loads(obs_json_path.read_text()),
        "observations_txt": (obs_dir / "observations.txt").read_text(),
        "stimulus_txt": stim_txt_path.read_text(),
        "stimulus_txt_sha256": sha256_file(stim_txt_path),
        "observations_txt_sha256": sha256_file(obs_dir / "observations.txt"),
        "clk_ns": clk_ns,
        "klt_version": klt_version(klt=klt),
        "engine_version": envr.get("engine_version"),
        "cocotb_version": envr.get("cocotb_version"),
        "iverilog_banner": _iverilog_banner(),
        "sdf_env": sdf_env,
        "sdf_gz_sha256": sha256_file(_FV_SDF.SDF_GZ),
        "sdf_plain_sha256": sha256_text(sdf_src),
        "sdf_clean_sha256": sha256_file(sdf_path),
        "sdf_dropped_count": len(dropped),
        "sdf_census": census,
        "routed_netlist_sha256": sha256_file(_FV_SDF.ROUTED),
        "primitives_v_sha256": sha256_file(prim),
        "cells_v_sha256": sha256_file(cells),
        "tb_sha256": sha256_file(TB_FILE),
        "probe_stats": probe_stats,
        "fv_report_status": report.get("status"),
        "fv_test_count": report.get("test_count"),
        "fv_passed_count": report.get("passed_count"),
    }


def _run_fresh_gate_model(klt: str, n_cycles: int, work: Path) -> tuple[dict, dict]:
    """Generate and run a fresh local single-corner gate-model ngspice sim."""
    gm_dir = work / "gate-model"
    rc = _GATE_GEN.main([str(gm_dir), "--cycles", str(n_cycles), "--backend", "local"])
    if rc != 0:
        raise CrossCheckError(f"make-gate-model.py exited {rc}")
    req_path = (gm_dir / "request.json").resolve()
    rep_path = (gm_dir / "report.json").resolve()
    proc = subprocess.run(
        [klt, "sim", str(req_path), "--backend", "local", "-o", str(rep_path)],
        check=False, capture_output=True, text=True,
    )
    if proc.returncode != 0 or not rep_path.is_file():
        raise CrossCheckError(
            f"klt sim --backend local failed (rc={proc.returncode}): {proc.stderr[:400]}")
    return json.loads(rep_path.read_text()), json.loads((gm_dir / "plan.json").read_text())


def _print_summary(result: dict) -> None:
    c = result["counts"]
    fov = result["first_out_valid"]
    print(f"Cross-check (N={result['n_cycles']} cycles, tt_025C_1v80, Ts={P.TS_NS:.0f} ns):")
    print(f"  stimulus shared input cards sha256: {result['stimulus']['shared_input_cards_sha256']}")
    print(f"  stimulus gate cards sha256:         {result['stimulus']['gate_stimulus_cards_sha256']}")
    print(f"  stimulus Icarus trace sha256:       {result['stimulus']['icarus_stimulus_sha256']} "
          f"(match={result['stimulus']['icarus_matches_program']})")
    print(f"  first out_valid: gate={fov['gate']} icarus={fov['icarus']} "
          f"model={fov['model']} -> {fov['status'].upper()}")
    print("  word-for-word comparison:")
    for w in result["word_checks"]:
        if w.get("not_compared"):
            print(f"    --  cycle {w['cycle']:2d} {w['signal']:<9} ({w['measurement']:<14}) "
                  f"not compared ({w['not_compared']})")
            continue
        flag = "OK  " if w["all_match"] else "DIFF"
        print(f"    {flag} cycle {w['cycle']:2d} {w['signal']:<9} ({w['measurement']:<14}) "
              f"gate={_fmt_val(w['gate'], is_word=True)} "
              f"icarus={_fmt_val(w['icarus'], is_word=True)} "
              f"model={_fmt_val(w['model'], is_word=True)}")
    print(f"  words matched:  {c['words_matched']}/{c['words_compared']} "
          f"({c['words_not_compared']} not compared)")
    print(f"  scalars matched:{c['scalars_matched']}/{c['scalars_compared']}")
    print(f"  gate vs Icarus: {c['gate_vs_icarus_matched']}/{c['gate_vs_icarus_total']}")
    print(f"  Icarus vs model (all {result['n_cycles']} cycles words): "
          f"{c['icarus_full_word_checks_matched']}/{c['icarus_full_word_checks_total']}")
    print(f"  disagreements:  {c['disagreements']}")
    for d in result["disagreements"]:
        print(f"    ! {d['detail']}")
    print(f"  verdict: {result['verdict'].upper()}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--klt", default=os.environ.get("KLT", "klt"),
                    help="path to klt binary (prefer worktree .venv/bin/klt with cocotb)")
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--cycles", type=int, default=75,
                    help="program cycles N to compare (1..75; 0 means full 75)")
    ap.add_argument("--gate-report", type=Path, default=DEFAULT_GATE_REPORT,
                    help="gate-model klt sim report.json (default: committed #486 full run)")
    ap.add_argument("--gate-plan", type=Path, default=DEFAULT_GATE_PLAN,
                    help="gate-model plan.json (default: committed #486 full plan)")
    ap.add_argument("--run-gate-model", action="store_true",
                    help="run a fresh local single-corner ngspice gate-model sim instead "
                         "of reading --gate-report/--gate-plan")
    ap.add_argument("--emit-json", type=Path, default=None,
                    help="write structured cross-check JSON artifact here")
    args = ap.parse_args(argv)

    for tool in (args.klt, "iverilog"):
        if shutil.which(tool) is None:
            print(f"error: {tool!r} not found", file=sys.stderr)
            return 2

    full_cycles, _ = P.build_program()
    n_cycles = len(full_cycles) if args.cycles == 0 else args.cycles
    if not (1 <= n_cycles <= len(full_cycles)):
        print(f"error: --cycles must be in 1..{len(full_cycles)}, got {args.cycles}",
              file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="wb-icarus-sdf-xcheck-") as tmp:
        work = Path(tmp)
        try:
            if args.run_gate_model:
                gate_report, gate_plan = _run_fresh_gate_model(args.klt, n_cycles, work)
                gate_source = "fresh local klt sim run"
            else:
                gate_report = json.loads(args.gate_report.read_text())
                gate_plan = json.loads(args.gate_plan.read_text())
                gate_source = str(args.gate_report.resolve().relative_to(REPO)) \
                    if args.gate_report.resolve().is_relative_to(REPO) else str(args.gate_report)

            gate_obs = extract_gate_model_trace(gate_report, gate_plan, n_cycles)
            stim = build_stimulus_vectors(n_cycles, raw_bit_pattern=gate_obs["raw_bit_pattern"])
            if gate_obs["raw_bit_pattern"][:len(stim["raw_bit_pattern"])] != stim["raw_bit_pattern"]:
                raise CrossCheckError("gate-model raw_bit_pattern does not match stimulus")

            icarus = _run_icarus_sdf(
                args.klt, args.pdk, n_cycles, stim["raw_bit_pattern"], work)

            # Verify Icarus drove the exact same cycle-by-cycle stimulus
            stim_match = (icarus["stimulus_txt_sha256"] == stim["stimulus_text_sha256"])
            if not stim_match:
                raise CrossCheckError(
                    f"Icarus stimulus trace sha256 {icarus['stimulus_txt_sha256']} != "
                    f"expected program stimulus {stim['stimulus_text_sha256']}")
            if icarus["routed_netlist_sha256"] != gate_obs["routed_netlist_sha256"]:
                raise CrossCheckError(
                    f"routed netlist sha256 mismatch: Icarus {icarus['routed_netlist_sha256']} "
                    f"!= gate model {gate_obs['routed_netlist_sha256']}")

            bits = [int(c) for c in stim["raw_bit_pattern"]]
            full_bits = bits + [0] * (P.N_SAMPLES_REG + P.N_SAMPLES_STREAM - len(bits))
            model_rows = P.model_replay(full_bits)
            comparison = compare_traces(gate_obs, icarus["observations"], model_rows, n_cycles)
        except CrossCheckError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    payload = {
        **comparison,
        "clock_period_ns": P.TS_NS,
        "stimulus": {
            "program": "sim/post-layout-whole-block/program.py::build_program",
            "n_cycles": n_cycles,
            "raw_bit_pattern": stim["raw_bit_pattern"],
            "shared_input_cards_count": stim["shared_input_cards_count"],
            "shared_input_cards_sha256": stim["shared_input_cards_sha256"],
            "gate_stimulus_cards_sha256": stim["gate_stimulus_cards_sha256"],
            "program_stimulus_sha256": stim["stimulus_text_sha256"],
            "icarus_stimulus_sha256": icarus["stimulus_txt_sha256"],
            "icarus_matches_program": stim_match,
        },
        "gate_model": {
            "source": gate_source,
            "ngspice_version": gate_obs["ngspice_version"],
            "ngspice_binary_sha256": gate_obs["ngspice_binary_sha256"],
            "liberty_corner": "tt_025C_1v80",
            "liberty_sha256": gate_obs["liberty_sha256"],
            "routed_netlist_sha256": gate_obs["routed_netlist_sha256"],
            "netlist_sha256": gate_obs["netlist_sha256"],
            "gate_model_sha256": gate_obs["gate_model_sha256"],
            "corner_id": gate_obs["corner_id"],
            "corner_status": gate_obs["corner_status"],
            "supply_v": gate_obs["supply_v"],
        },
        "icarus_sdf": {
            "klt_version": icarus["klt_version"],
            "engine_version": icarus["engine_version"],
            "cocotb_version": icarus["cocotb_version"],
            "iverilog_banner": icarus["iverilog_banner"],
            "sdf_corner_pdk": "tt_025C_1v80",
            "sdf_selector": _FV_SDF.SDF_CORNER,
            "sdf_gz_sha256": icarus["sdf_gz_sha256"],
            "sdf_plain_sha256": icarus["sdf_plain_sha256"],
            "sdf_clean_sha256": icarus["sdf_clean_sha256"],
            "sdf_dropped_zero_port_interconnects": icarus["sdf_dropped_count"],
            "sdf_env": icarus["sdf_env"],
            "sdf_census": icarus["sdf_census"],
            "routed_netlist_sha256": icarus["routed_netlist_sha256"],
            "primitives_v_sha256": icarus["primitives_v_sha256"],
            "cells_v_sha256": icarus["cells_v_sha256"],
            "tb_sha256": icarus["tb_sha256"],
            "observations_txt_sha256": icarus["observations_txt_sha256"],
            "probe_stats": icarus["probe_stats"],
            "timingcheck_note": (
                "Icarus 13.0 does not implement SDF TIMINGCHECK (sdf.partial=true); "
                "setup/hold/recovery/removal limits are not checked in simulation. "
                "Agreement covers output values and cycle timing only."
            ),
        },
    }

    if args.emit_json:
        args.emit_json.parent.mkdir(parents=True, exist_ok=True)
        args.emit_json.write_text(
            json.dumps(sanitize_paths(payload), indent=2, sort_keys=True) + "\n")

    _print_summary(payload)
    return 0 if payload["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
