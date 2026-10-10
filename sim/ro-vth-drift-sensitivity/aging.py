#!/usr/bin/env python3
"""Deterministic aged-netlist generator: signed gate-offset wrappers (issue #254).

First-order electrical model of a threshold shift (BTI/HCI-like), with NO assumption
that the pinned open PDK exposes an aging parameter. Every instance of the pinned
`sky130_fd_pr__nfet_01v8` / `sky130_fd_pr__pfet_01v8` subcircuits in a committed
design netlist is redirected to a repository-owned wrapper that places an ideal
voltage-controlled source in series with the gate:

    NMOS, dVtn >= 0:   V(g_device) = V(g_original) - dVtn     (|Vth| appears dVtn higher)
    PMOS, d|Vtp| >= 0: V(g_device) = V(g_original) + d|Vtp|   (|Vth| appears d|Vtp| higher)

Drain/source/body nets and every device parameter of the instance are preserved
byte-for-byte; only the model token changes. The committed schematic-generated
netlists and the PDK are never edited: the aged netlist is a derived text.

The two shifts are read from two global DC "knob" nodes, `vth_dvn` and `vth_dvp`
(volts, driven by `Vdvn` / `Vdvp` at the top level). The wrapper source is
`E g gd vth_dvn 0 +1` (NMOS) and `E g gd vth_dvp 0 -1` (PMOS), so the shifts are
swept with klt sim's `corners.supply_v` `alter` mechanism and are INDEPENDENT. A
knob left at 0 V is the exact zero-shift circuit (the zero-shift control checks it).
A dropped `alter` would silently be a time-zero run, so every unit also `.meas`-es the
knob nodes and the analysis rejects a row whose read-back differs from the request.

Only devices of exactly the supported shape are wrapped; anything else is a hard error
(`UnsupportedDevice`): an `X` card naming another `sky130_fd_pr__*` model, a supported
model with a different parameter set, or the wrong number of nets.

    aging.py DESIGN.spice [-o OUT.spice]      # print / write the aged netlist
    aging.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

NMOS = "sky130_fd_pr__nfet_01v8"
PMOS = "sky130_fd_pr__pfet_01v8"
WRAP_N = "vth_wrap_nfet"
WRAP_P = "vth_wrap_pfet"
KNOB_N = "vth_dvn"
KNOB_P = "vth_dvp"
# Exactly the parameter set every committed design instance passes (design/netlist.py).
PARAMS = ("L", "W", "nf", "ad", "as", "pd", "ps", "nrd", "nrs", "sa", "sb", "sd", "mult", "m")
WRAPPER_VERSION = "1"


class UnsupportedDevice(ValueError):
    pass


def wrapper_definition() -> str:
    """The wrapper subcircuits (text, deterministic). Parameters are forwarded by name."""
    plist = " ".join(f"{p}=1" for p in PARAMS)
    fwd = " ".join(f"{p}={p}" for p in PARAMS)
    return "\n".join([
        f"* --- vth-drift gate-offset wrappers v{WRAPPER_VERSION} (sim/ro-vth-drift-sensitivity/aging.py) ---",
        f".global {KNOB_N} {KNOB_P}",
        f".subckt {WRAP_N} d g s b {plist}",
        f"Esh g gd {KNOB_N} 0 1",
        f"Xdev d gd s b {NMOS} {fwd}",
        ".ends",
        f".subckt {WRAP_P} d g s b {plist}",
        f"Esh g gd {KNOB_P} 0 -1",
        f"Xdev d gd s b {PMOS} {fwd}",
        ".ends",
        "* --- end wrappers ---",
        "",
    ])


def _logical_lines(text: str) -> list[list[str]]:
    """Group physical lines into logical cards ('+' continues the previous line)."""
    cards: list[list[str]] = []
    for ln in text.split("\n"):
        if ln.startswith("+") and cards:
            cards[-1].append(ln)
        else:
            cards.append([ln])
    return cards


def _strip_quotes(s: str) -> str:
    return re.sub(r"'[^']*'", "''", s)


def _wrap_card(card: list[str]) -> tuple[list[str], str | None]:
    first = card[0]
    if not first[:1] in ("X", "x"):
        return card, None
    flat = _strip_quotes(" ".join([first] + [c[1:] for c in card[1:]]))
    toks = flat.split()
    model_idx = [i for i, t in enumerate(toks) if t.startswith("sky130_fd_pr__")]
    if not model_idx:
        return card, None
    if len(model_idx) != 1:
        raise UnsupportedDevice(f"{toks[0]}: more than one PDK model token")
    mi = model_idx[0]
    model = toks[mi]
    if model not in (NMOS, PMOS):
        raise UnsupportedDevice(f"{toks[0]}: unsupported PDK device {model}")
    if mi != 5:
        raise UnsupportedDevice(f"{toks[0]}: expected 4 nets before the model, got {mi - 1}")
    names = [t.split("=", 1)[0] for t in toks[mi + 1:]]
    if any("=" not in t for t in toks[mi + 1:]) or sorted(names) != sorted(PARAMS) or len(set(names)) != len(names):
        raise UnsupportedDevice(f"{toks[0]}: parameter set {sorted(names)} != {sorted(PARAMS)}")
    wrapper = WRAP_N if model == NMOS else WRAP_P
    # replace the model token in the physical line that carries it (exactly once)
    out, done = [], False
    for ln in card:
        if not done and re.search(rf"(?<![\w]){model}(?![\w])", ln):
            ln = re.sub(rf"(?<![\w]){model}(?![\w])", wrapper, ln, count=1)
            done = True
        out.append(ln)
    if not done:
        raise UnsupportedDevice(f"{toks[0]}: model token split across continuation lines")
    return out, "n" if model == NMOS else "p"


def age_netlist(text: str) -> tuple[str, dict]:
    """Return (aged netlist text, report). The wrapper definitions are prepended."""
    cards = _logical_lines(text)
    out: list[str] = []
    n = {"n": 0, "p": 0}
    for card in cards:
        new, kind = _wrap_card(card)
        out.extend(new)
        if kind:
            n[kind] += 1
    if not (n["n"] or n["p"]):
        raise UnsupportedDevice("no wrappable devices found")
    aged = wrapper_definition() + "\n".join(out)
    rep = {"wrapped_nfet": n["n"], "wrapped_pfet": n["p"], "wrapper_version": WRAPPER_VERSION,
           "wrapper_sha256": sha256_text(wrapper_definition()),
           "source_sha256": sha256_text(text), "aged_sha256": sha256_text(aged)}
    return aged, rep


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def unwrap(aged: str) -> str:
    """Inverse transform (test aid): wrapper tokens back to the PDK models, definitions dropped."""
    body = aged.split("* --- end wrappers ---\n", 1)[1]
    return re.sub(rf"\b{WRAP_N}\b", NMOS, re.sub(rf"\b{WRAP_P}\b", PMOS, body))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("design", nargs="?")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    if not a.design:
        ap.error("design netlist required")
    text = Path(a.design).read_text()
    aged, rep = age_netlist(text)
    if a.out:
        Path(a.out).write_text(aged)
    else:
        sys.stdout.write(aged)
    print(rep, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
