#!/usr/bin/env python3
"""Shared campaign definition for the Vth-drift sensitivity study (issue #254).

Owns: the PVT x shift grid, the required-key manifest, and the deterministic derivation of
a `klt sim` request (netlist + measurements) from the UNMODIFIED source testbenches and
committed design netlists. Nothing here simulates anything.

The source decks are lifted mechanically (same scheme as sim/raw-bit-volume-campaign/
make-requests.py `build_combining`): header cards kept, `.lib/.temp/.tran/.save/.end`
dropped (klt sim owns them), the `.include` of the design netlist replaced by the aged
(wrapped) design netlist inlined verbatim, the `.control` block's `meas` lines turned into
`.meas` cards, and the jitter loop unrolled to explicit cards. The seed, `.tran` max step,
sample count, noise amplitude and measurement windows are the source deck's own.

This is a sensitivity study. This is a sensitivity bound, not a lifetime prediction.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import aging  # noqa: E402

SLUG = "ro-vth-drift-sensitivity"
LIB = "libs.tech/combined/sky130.lib.spice"
PROCESSES = ("tt", "ss", "ff")
TEMPS = (-40.0, 27.0, 125.0)
VDDS = (1.62, 1.8, 1.98)
CM_SHIFTS_MV = (0, 20, 40, 60)                       # common-mode (dVtn, d|Vtp|) in mV
ASYM_SHIFTS_MV = ((60, 0), (0, 60))
HEADLINE = (("ss", -40.0, 1.62), ("tt", 27.0, 1.8), ("ff", -40.0, 1.98))
DECKS = {
    "ring5": dict(
        tb="sim/ro-ring-jitter-accumulation/testbench/tb_ro_ring5_jitter.spice",
        design="design/ro_ring5.spice", tmax="20p", stop="175n", seed=1, na="2.0e-3",
        source_slug="ro-ring-jitter-accumulation"),
    "array": dict(
        tb="sim/ro-array-core-combining/testbench/tb_ro_array_core.spice",
        design="design/ro_array_core.spice", tmax="5p", stop="300n", seed=None, na=None,
        source_slug="ro-array-core-combining"),
}
# The source deck's .tran stop is 115n, sized for the slowest TIME-ZERO corner (4.82 ns/period, ss/-40C/1.62V:
# 5 + 20 x 4.82 = 101 ns). A threshold-shifted ring is slower (tt/27C/1.8V: +20 % at 60 mV in the pilot), so the
# 21-crossing window would not fit; the stop is raised to 175n uniformly for every shifted AND zero-shift row of
# this campaign (same trajectory prefix, same seed/max-step/edge window). The swing window stays 20n..115n.
# Same reason for the array deck: its `tt1b` / `txo_b` measurements need the 50th rising edge of the 2- and 4-ring
# XOR nodes; at ss/-40C/1.62V with a 60 mV common-mode shift that edge falls after the source deck's 200n stop
# (the first grid attempt lost exactly that unit, `tt1b produced no value`). Stop raised to 300n for every array
# row; the averaging windows (60n..200n) are the source deck's own and are unchanged.
RING_EDGES = range(2, 23)                            # rising crossings used by the source deck
MEAS_WINDOW_RING = ("20n", "115n")                   # swing window of the source deck (fixed)


def key_str(deck, corner, temp, vdd, dvn, dvp):
    return f"{deck}|{corner}|{temp:g}C|{vdd:g}V|{dvn:g}|{dvp:g}"


def required_keys() -> list[str]:
    """Every (deck, corner, T, V, dVtn mV, d|Vtp| mV) the campaign must contain exactly once."""
    keys = []
    for deck in DECKS:
        for c in PROCESSES:
            for t in TEMPS:
                for v in VDDS:
                    for s in CM_SHIFTS_MV:
                        keys.append(key_str(deck, c, t, v, s, s))
    for c, t, v in HEADLINE:
        for dn, dp in ASYM_SHIFTS_MV:
            keys.append(key_str("array", c, t, v, dn, dp))
    assert len(keys) == len(set(keys))
    return keys


def manifest() -> dict:
    keys = required_keys()
    return {"version": 1, "issue": 254, "n_keys": len(keys), "keys": sorted(keys),
            "keys_sha256": hashlib.sha256("\n".join(sorted(keys)).encode()).hexdigest(),
            "common_mode_shifts_mv": list(CM_SHIFTS_MV),
            "asymmetric_shifts_mv": [list(x) for x in ASYM_SHIFTS_MV],
            "headline_points": [list(h) for h in HEADLINE]}


def check_coverage(found: list[str], required: list[str] | None = None) -> list[str]:
    """Problems (empty list = exact coverage): missing keys, duplicate keys, unexpected keys."""
    req = required_keys() if required is None else required
    probs = []
    seen: dict[str, int] = {}
    for k in found:
        seen[k] = seen.get(k, 0) + 1
    probs += [f"duplicate key {k} x{n}" for k, n in sorted(seen.items()) if n > 1]
    probs += [f"missing key {k}" for k in sorted(set(req) - set(seen))]
    probs += [f"unexpected key {k}" for k in sorted(set(seen) - set(req))]
    return probs


def _split_deck(text: str):
    head, ctl, in_ctl = [], [], False
    for line in text.splitlines():
        low = line.strip().lower()
        if low == ".control":
            in_ctl = True
        elif low == ".endc":
            in_ctl = False
        else:
            (ctl if in_ctl else head).append(line)
    return head, ctl


def _half(text: str) -> str:
    return re.sub(r"0\.5\*([0-9.]+)", lambda m: repr(round(0.5 * float(m.group(1)), 6)), text)


def build_deck(deck: str, vdd: float, *, wrap: bool = True, stop: str | None = None):
    """-> (netlist text, measurements [{name, spice}], info dict). Deterministic."""
    d = DECKS[deck]
    stop = stop or d["stop"]
    tb = (REPO / d["tb"]).read_text()
    design_text = (REPO / d["design"]).read_text()
    subs = {"@@VDD@@": repr(vdd), "@@TMAX@@": d["tmax"], "@@RO_RING5@@": "@@DESIGN@@",
            "@@TEMP@@": "0", "@@CORNER@@": "tt", "@@PDK_LIB@@": "x"}
    if d["seed"] is not None:
        subs["@@SEED@@"] = str(d["seed"])
        subs["@@NA@@"] = d["na"]
    for k, v in subs.items():
        tb = tb.replace(k, v)
    tb = _half(tb)
    head, ctl = _split_deck(tb)
    body = []
    for l in head:
        low = l.strip().lower()
        if low.startswith(".include"):
            continue
        if low.startswith((".lib", ".temp", ".tran", ".save", ".end")) and not low.startswith(".option"):
            continue
        body.append(l)
    half = repr(round(0.5 * vdd, 6))
    meas = []
    if deck == "ring5":
        lo, hi = MEAS_WINDOW_RING
        meas.append(("vmax_ss", f".meas tran vmax_ss MAX v(ro) from={lo} to={hi}"))
        meas.append(("vmin_ss", f".meas tran vmin_ss MIN v(ro) from={lo} to={hi}"))
        for k in RING_EDGES:
            meas.append((f"tk{k}", f".meas tran tk{k} when v(ro)={half} rise={k}"))
    else:
        for line in ctl:
            m = re.match(r"\s*meas tran (\w+) ", line)
            if m:
                meas.append((m.group(1), "." + line.strip()))
    knob_cards = ["* shift knobs (volts), swept by klt sim supply_v alter; see aging.py",
                  "Vdvn vth_dvn 0 dc 0", "Vdvp vth_dvp 0 dc 0"]
    meas.append(("dvn_rb", ".meas tran dvn_rb find v(vth_dvn) at=1n"))
    meas.append(("dvp_rb", ".meas tran dvp_rb find v(vth_dvp) at=1n"))
    if wrap:
        design, rep = aging.age_netlist(design_text)
    else:
        design, rep = design_text, {"source_sha256": aging.sha256_text(design_text)}
        knob_cards = []
        meas = [m for m in meas if m[0] not in ("dvn_rb", "dvp_rb")]
    netlist = "\n".join([f"* {SLUG}: {deck} deck at Vdd={vdd:g} V, generated by sim/{SLUG}/campaign.py",
                         "* source testbench: " + d["tb"], "* design netlist: " + d["design"]
                         + (" (wrapped)" if wrap else " (UNWRAPPED control)"),
                         design, *body, *knob_cards, ""])
    info = {"deck": deck, "vdd": vdd, "stop": stop, "tmax": d["tmax"], "wrap": wrap,
            "source_testbench": d["tb"], "source_testbench_sha256": aging.sha256_file(REPO / d["tb"]),
            "design_netlist": d["design"], "generator_sha256": aging.sha256_file(HERE / "campaign.py"),
            "aging_sha256": aging.sha256_file(HERE / "aging.py"), **rep,
            "netlist_sha256": aging.sha256_text(netlist)}
    return netlist, [{"name": n, "spice": s} for n, s in meas], info


def make_request(deck, process, temp, vdd, shifts_mv, *, wrap=True, stop=None, backend="batch"):
    """-> (request dict, netlist text, plan dict). One request = one (T, V) point, the given
    process list, and the zipped list of (dVtn, d|Vtp|) shift units (mV)."""
    netlist, meas, info = build_deck(deck, vdd, wrap=wrap, stop=stop)
    d = DECKS[deck]
    corners = {"process": list(process), "temperature_c": [temp]}
    if wrap:
        corners["supply_v"] = {"Vdvn": [round(s[0] * 1e-3, 9) for s in shifts_mv],
                               "Vdvp": [round(s[1] * 1e-3, 9) for s in shifts_mv]}
    req = {"netlist": "netlist.cir", "engine": "ngspice", "backend": backend,
           "netlist_source": "extracted", "models": {"pdk": "sky130A", "lib": LIB},
           "corners": corners,
           "analysis": {"kind": "tran", "args": f"{d['tmax']} {info['stop']} uic"},
           "measurements": meas, "options": {"timeout_s": 3000, "keep_artifacts": False}}
    plan = {"deck": deck, "processes": list(process), "temp_c": temp, "vdd_v": vdd,
            "shifts_mv": [list(s) for s in shifts_mv], "info": info,
            "keys": [key_str(deck, c, temp, vdd, s[0], s[1]) for c in process for s in shifts_mv]
            if wrap else []}
    return req, netlist, plan


def pdk_commit() -> str:
    return json.loads((REPO / "sim/pdk.json").read_text())["open_pdks_commit"]
