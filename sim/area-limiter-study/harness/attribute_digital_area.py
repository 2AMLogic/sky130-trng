#!/usr/bin/env python3
"""Attribute every mapped instance of the committed unconstrained
`trng_digital` netlist to one RTL function by traced fanout, and sum Liberty
cell area per function (issue #599, item 1).

Inputs (read-only, never modified):

* ``sim/digital-synthesis/runs/20260910-001436-a4c3194/
  unconstrained-trng_digital_synth.v`` -- the committed unconstrained mapped
  netlist of the 20260910-001436-a4c3194 gate record (#117), 2320 instances.
* ``unconstrained-synthesize-output.json`` next to it -- the committed
  instance_counts_by_type / area_um2 the attribution must reconcile to.
* the Liberty deck that record's provenance pins by content hash
  (``sha256:8e78e144...`` = sky130_fd_sc_hd ``tt_025C_1v80``), resolved from
  the installed sky130A PDK; the hash is asserted before anything is read.

Method (published in the record as the attribution rule):

1. Parse the structural netlist (instances + pin->net connections; escaped
   identifiers ``\\raw_mem[0] [30]`` normalise to ``raw_mem[0][30]``).
2. Sequential instances (``dfrtp``/``dfstp``) are attributed to the function
   owning the register their ``Q`` pin drives, via the published
   name->function table below.  The ``raw_mem[w][b]`` and ``cond_mem[w][b]``
   nets are the storage anchors: the script asserts they cover exactly 128
   distinct Q-driven bits each (issue #599 revision 2026-11-21).
3. For every combinational instance, collect the transitive set of
   *endpoints* reachable from its output: forward through other
   combinational cells until a register input pin (``D`` -> that register's
   function; ``CLK`` -> ``clock_distribution``; ``RESET_B``/``SET_B`` ->
   ``reset_distribution``) or a primary output (-> that output's function)
   is reached.  Memoised DFS, cycle-safe by a seen-set (the synthesis
   response reports ``comb_loops == 0``; the guard is belt and braces).
4. Exactly one owner per instance: a single-function endpoint set -> that
   function; a multi-function set -> ``shared``; an empty set (dangling)
   -> ``unassigned``.  Registers with unrecognised ``Q`` names are
   ``unassigned`` too.
5. Area = Liberty ``area`` of the cell type x instance count, summed per
   owner; every row (functions + shared + unassigned) reconciles to the
   committed totals 2320 instances / 22203.7952 um2, and per-type instance
   counts reconcile to ``instance_counts_by_type``.

No PDK file is written; nothing outside this study's own outputs is touched.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

COMMITTED_NETLIST = (REPO_ROOT / "sim" / "digital-synthesis" / "runs" /
                     "20260910-001436-a4c3194" / "unconstrained-trng_digital_synth.v")
COMMITTED_RESPONSE = (REPO_ROOT / "sim" / "digital-synthesis" / "runs" /
                      "20260910-001436-a4c3194" / "unconstrained-synthesize-output.json")
DECK_SHA256 = "8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135"

# The published name->function table.  Register names are matched against
# the normalised base name (bit-selects stripped); every RTL register in
# digital/rtl/trng_digital.v appears here, so an unmatched register is a
# real finding, not a bucket.
REG_FUNCTIONS: list[tuple[str, list[str]]] = [
    ("fifo_storage_raw", ["raw_mem"]),
    ("fifo_storage_cond", ["cond_mem"]),
    ("health_tests", ["rct_ref", "rct_armed", "rct_count", "apt_ref", "apt_index",
                      "apt_matches", "startup_count", "startup_done_r",
                      "al_rct", "al_apt", "al_startup"]),
    ("conditioner", ["crc_state", "cond_count"]),
    ("raw_packer", ["raw_sr", "raw_count"]),
    ("fifo_control", ["raw_level", "cond_level", "raw_ovf", "cond_ovf"]),
    ("control", ["ctrl"]),
    ("bus_interface", ["bus_rdata_r"]),
    ("status", ["raw_tap_valid"]),
]

# Primary-output -> function (outputs whose whole cone is one interface).
PO_FUNCTIONS: dict[str, str] = {
    "out_data": "stream_output",
    "out_valid": "stream_output",
    "bus_rdata": "bus_interface",
    "alarm": "status",
    "gated": "status",
    "startup_done": "status",
}

FF_CONTROL_PIN_FUNCTIONS = {"CLK": "clock_distribution",
                            "RESET_B": "reset_distribution",
                            "SET_B": "reset_distribution"}
SEQUENTIAL_TYPES = {"dfrtp_1", "dfstp_1", "dfrtp_2", "dfstp_2",
                    "dfxtp_1", "dfxtp_2", "dfrtn_1", "dfstn_1"}
# output pin names across the sky130_fd_sc_hd comb cells used here
COMB_OUT_PINS = {"X", "Y"}
# supply pins are not signal topology
SUPPLY_PINS = {"VPWR", "VGND", "VPB", "VNB"}

SHARED = "shared"
UNASSIGNED = "unassigned"


def parse_liberty_areas(liberty_path: Path) -> dict[str, float]:
    """{cell_type: area_um2} from each ``cell ("...")`` block's ``area :``."""
    text = liberty_path.read_text()
    areas: dict[str, float] = {}
    for cell_m in re.finditer(r'cell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{', text):
        block = text[cell_m.end():cell_m.end() + 200_000]
        # stop at a nested cell so a child's area is never picked up; the
        # window is generous because some cells carry dozens of
        # leakage_power() entries ahead of their area line (a222oi_1's
        # sits ~7.3 kB in, which is why this parse asserts the deck hash
        # and reconciles the total against the synthesis response)
        nested = re.search(r'cell\s*\(', block)
        if nested:
            block = block[:nested.start()]
        area_m = re.search(r'area\s*:\s*([0-9.]+)\s*;', block)
        if area_m:
            areas[cell_m.group(1)] = float(area_m.group(1))
    return areas


def normalise_net(token: str) -> str:
    """``\\raw_mem[0] [30]`` -> ``raw_mem[0][30]``; strip whitespace."""
    token = token.strip()
    if " " in token:
        parts = token.split()
        if len(parts) == 2 and parts[0].startswith("\\"):
            token = parts[0][1:] + parts[1]
        else:
            token = "".join(parts)
    if token.startswith("\\"):
        token = token[1:]
    return token


def base_name(net: str) -> str:
    """``raw_mem[0][30]`` -> ``raw_mem``; ``_0059_`` -> ``_0059_``."""
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", net)
    return m.group(1) if m else net


class Netlist:
    """Structural parse of the mapped Verilog netlist."""

    def __init__(self, path: Path):
        text = path.read_text()
        self.types_by_inst: dict[str, str] = {}
        self.pins_by_inst: dict[str, dict[str, str]] = {}
        inst_re = re.compile(
            r"sky130_fd_sc_hd__(\S+)\s+(\\?[A-Za-z0-9_]+)\s*\((.*?)\);",
            re.DOTALL)
        for m in inst_re.finditer(text):
            ctype, inst, body = m.group(1), m.group(2).lstrip("\\"), m.group(3)
            pins = {pm.group(1): normalise_net(pm.group(2))
                    for pm in re.finditer(r"\.(\w+)\(([^)]*)\)", body)}
            self.types_by_inst[inst] = ctype
            self.pins_by_inst[inst] = pins

        # module ports, bus widths expanded to bit nets
        self.outputs: set[str] = set()
        self.inputs: set[str] = set()
        for m in re.finditer(
                r"\b(output|input)\s+(?:wire\s+)?(?:\[(\d+):(\d+)\]\s*)?(\w+)\s*;",
                text):
            kind, hi, lo, name = m.groups()
            if hi is not None:
                bits = {f"{name}[{i}]" for i in range(int(lo), int(hi) + 1)}
            else:
                bits = {name}
            (self.outputs if kind == "output" else self.inputs).update(bits)

        # signal-input consumers per net: net -> [(inst, pin)].
        # Sequential Q / comb outputs are drivers, not consumers; supply
        # pins are not topology.
        self.consumers: dict[str, list[tuple[str, str]]] = {}
        for inst, pins in self.pins_by_inst.items():
            ctype = self.types_by_inst[inst]
            for pin, net in pins.items():
                if pin in SUPPLY_PINS:
                    continue
                if ctype in SEQUENTIAL_TYPES and pin in ("Q", "Q_N"):
                    continue
                if ctype not in SEQUENTIAL_TYPES and pin in COMB_OUT_PINS:
                    continue
                self.consumers.setdefault(net, []).append((inst, pin))

        # comb output net per instance (for owner lookup)
        self.out_net: dict[str, str] = {}
        for inst, pins in self.pins_by_inst.items():
            if self.types_by_inst[inst] in SEQUENTIAL_TYPES:
                continue
            for pin in COMB_OUT_PINS:
                if pin in pins:
                    self.out_net[inst] = pins[pin]
                    break

        # Q net per sequential instance
        self.q_net: dict[str, str] = {}
        for inst, pins in self.pins_by_inst.items():
            if self.types_by_inst[inst] in SEQUENTIAL_TYPES:
                q = pins.get("Q")
                if q:
                    self.q_net[inst] = q


def reg_function(q_net: str) -> str | None:
    base = base_name(q_net)
    for func, names in REG_FUNCTIONS:
        if base in names:
            return func
    return None


def po_function(net: str) -> str | None:
    base = base_name(net)
    return PO_FUNCTIONS.get(net) or PO_FUNCTIONS.get(base)


def attribute(netlist: Netlist, areas: dict[str, float]) -> dict:
    # ABC-optimised cones can chain far deeper than Python's default limit
    sys.setrecursionlimit(100_000)
    # 1) sequential anchors and functions
    ff_func: dict[str, str] = {}
    anchors = {"fifo_storage_raw": set(), "fifo_storage_cond": set()}
    for inst, q in netlist.q_net.items():
        func = reg_function(q)
        ff_func[inst] = func if func else UNASSIGNED
        if func in anchors:
            anchors[func].add(q)

    # 2) endpoint sets per net (memoised, cycle-safe DFS).
    #
    # A net's value is cached only when computed as its own DFS root (never
    # while an ancestor frame is still open), so a cycle cut can never
    # freeze a partial set into the cache.  The committed response's
    # structural checks report comb_loops == 0, so cuts never fire in
    # practice; the seen-set is belt and braces.
    endpoints_cache: dict[str, set[str]] = {}
    on_stack: set[str] = set()

    def endpoints_of(net: str) -> set[str]:
        cached = endpoints_cache.get(net)
        if cached is not None:
            return cached
        out: set[str] = set()
        po = po_function(net)
        if po:
            out.add(po)
        for inst, pin in netlist.consumers.get(net, []):
            ctype = netlist.types_by_inst[inst]
            if ctype in SEQUENTIAL_TYPES:
                if pin == "D":
                    out.add(ff_func[inst])
                elif pin in FF_CONTROL_PIN_FUNCTIONS:
                    out.add(FF_CONTROL_PIN_FUNCTIONS[pin])
                continue
            onet = netlist.out_net.get(inst)
            if onet is None or onet in on_stack:
                continue  # cycle back-edge: cut, do not cache below
            on_stack.add(onet)
            out |= endpoints_of(onet)
            on_stack.discard(onet)
        return out

    def compute(net: str) -> set[str]:
        if net in endpoints_cache:
            return endpoints_cache[net]
        on_stack.add(net)
        result = endpoints_of(net)
        on_stack.discard(net)
        endpoints_cache[net] = result
        return result

    nets = (set(netlist.consumers.keys()) | set(netlist.out_net.values())
            | set(netlist.outputs))
    for net in sorted(nets):
        compute(net)

    # 3) one owner per combinational instance
    comb_owner: dict[str, str] = {}
    for inst, onet in netlist.out_net.items():
        eps = endpoints_cache.get(onet, set())
        if len(eps) == 0:
            comb_owner[inst] = UNASSIGNED
        elif len(eps) == 1:
            comb_owner[inst] = next(iter(eps))
        else:
            comb_owner[inst] = SHARED

    # 4) per-owner instance counts and Liberty area
    rows: dict[str, dict] = {}
    for inst in netlist.pins_by_inst:
        ctype = netlist.types_by_inst[inst]
        owner = ff_func.get(inst) or comb_owner.get(inst) or UNASSIGNED
        row = rows.setdefault(owner, {"instances": 0, "area_um2": 0.0})
        row["instances"] += 1
        row["area_um2"] += areas.get(f"sky130_fd_sc_hd__{ctype}", 0.0)

    return {
        "rows": {k: {"instances": v["instances"],
                     "area_um2": round(v["area_um2"], 4)}
                 for k, v in rows.items()},
        "anchors": {k: sorted(v) for k, v in anchors.items()},
        "n_anchors": {k: len(v) for k, v in anchors.items()},
        "n_instances": len(netlist.pins_by_inst),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--liberty", required=True, type=Path,
                    help="path to the sky130_fd_sc_hd tt_025C_1v80 Liberty deck")
    ap.add_argument("--netlist", type=Path, default=COMMITTED_NETLIST)
    ap.add_argument("--response", type=Path, default=COMMITTED_RESPONSE)
    ap.add_argument("--out", type=Path, required=True,
                    help="output JSON path for the attribution table")
    ap.add_argument("--expect-raw-bits", type=int, default=128,
                    help="asserted count of Q-driven raw_mem bits in the "
                         "storage anchor (128 committed; 64 at FIFO depth 2)")
    ap.add_argument("--expect-cond-bits", type=int, default=128,
                    help="asserted count of Q-driven cond_mem bits")
    args = ap.parse_args(argv)

    digest = hashlib.sha256(args.liberty.read_bytes()).hexdigest()
    if digest != DECK_SHA256:
        print(f"error: liberty sha256 {digest} != pinned {DECK_SHA256}",
              file=sys.stderr)
        return 2

    areas = parse_liberty_areas(args.liberty)
    response = json.loads(args.response.read_text())
    netlist = Netlist(args.netlist)

    # reconcile per-type counts against the committed response first
    type_counts: dict[str, int] = {}
    for ctype in netlist.types_by_inst.values():
        key = f"sky130_fd_sc_hd__{ctype}"
        type_counts[key] = type_counts.get(key, 0) + 1
    if type_counts != response["instance_counts_by_type"]:
        print("error: parsed instance_counts_by_type does not match the "
              "committed response", file=sys.stderr)
        return 3

    result = attribute(netlist, areas)
    total_area = sum(r["area_um2"] for r in result["rows"].values())
    result["liberty_sha256"] = f"sha256:{digest}"
    result["liberty_path"] = ("<external -- resolved from the installed "
                              "sky130A PDK; pinned by content hash>")
    result["reconciliation"] = {
        "instances_total": result["n_instances"],
        "instances_expected": response["instance_count"],
        "instances_match": result["n_instances"] == response["instance_count"],
        "area_total_um2": round(total_area, 4),
        "area_expected_um2": response["area_um2"],
        "area_matches": abs(total_area - response["area_um2"]) < 5e-4,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    ok = (result["n_anchors"]["fifo_storage_raw"] == args.expect_raw_bits
          and result["n_anchors"]["fifo_storage_cond"] == args.expect_cond_bits
          and result["reconciliation"]["instances_match"]
          and result["reconciliation"]["area_matches"])
    print(json.dumps({
        "anchors": result["n_anchors"],
        "reconciliation": result["reconciliation"],
        "rows": dict(sorted(result["rows"].items(),
                            key=lambda kv: -kv[1]["area_um2"])),
    }, indent=2))
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
