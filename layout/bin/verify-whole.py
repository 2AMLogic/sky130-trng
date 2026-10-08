#!/usr/bin/env python3
"""Whole-block physical verification of the composed TRNG: DRC, extraction,
mixed-level LVS, coverage matrix and isolated fault controls.

Issue #173 (part of #170, contributes to #18 AC3). Consumes the composition
artifacts from issue #172 (``layout/trng_whole/``) as **immutable inputs** and
writes only into ``layout/trng_whole/verify/``. Provisional until silicon. This
is whole-block *project* verification on the curated open-source sky130 decks
-- it is **not** foundry sign-off, and says so in every artifact it writes.

Usage (from the repo root, with the pinned klt first on PATH or via --klt)::

    python3 layout/bin/verify-whole.py run          # DRC + extract + LVS + coverage -> verify/
    python3 layout/bin/verify-whole.py controls     # fault controls + baseline re-run -> verify/controls/
    python3 layout/bin/verify-whole.py check        # isolated baseline re-run, diff vs committed
    python3 layout/bin/verify-whole.py all          # run + controls

``run`` and ``controls`` take a few minutes each (``klt extract`` of the 8605
placed cells dominates; one extraction per variant). The interpreter must be
the one that carries ``klayout_tools`` and ``klayout`` (the pinned venv's
``python``), because the reference is built with ``klayout_tools.
verilog_netlist`` and the controls edit GDS with ``klayout.db``.

Mixed-level comparison boundary
-------------------------------

See ``verify_whole_lib`` for the exact statement. In short: the analog macro is
compared at transistor level (264 MOSFETs, flat), the digital macro at
standard-cell level (every placed cell an opaque pin-only black box, power pins
included except the substrate-only ``VNB``), and the check that the black boxes
do not hide boundary defects is the independent per-port *endpoint audit*
below plus ``options.anchor_top_level_pins`` in the LVS request.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _klt_common import BuildError, run_klt, write_json  # noqa: E402
import verify_whole_lib as V  # noqa: E402

REPO_ROOT = HERE.parents[1]
SPEC_DIR = REPO_ROOT / "layout" / "trng_whole"
VERIFY_DIR = SPEC_DIR / "verify"
CONTROLS_DIR = VERIFY_DIR / "controls"
TOP = "trng_whole"
LEF_REL = "sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
SPICE_REL = "sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
REUSE = False  # set by --reuse-extract (debugging); refused when publishing
NOT_SIGNOFF = (
    "Whole-block project verification on klt's curated sky130 decks and the open_pdks "
    "install pinned in layout/pdk.json. NOT foundry sign-off: no foundry DRC/LVS/antenna/"
    "density runset, no parasitic extraction, no electrical or entropy characterisation. "
    "Provisional until silicon."
)

_cw_spec = importlib.util.spec_from_file_location("compose_whole", HERE / "compose-whole.py")
assert _cw_spec and _cw_spec.loader
cw = importlib.util.module_from_spec(_cw_spec)
sys.modules["compose_whole"] = cw
_cw_spec.loader.exec_module(cw)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def host_path_hits(text: str) -> list[str]:
    home = str(Path.home())
    hits = []
    for pat in (re.escape(home), r"/tmp/[A-Za-z0-9_.-]+", r"/var/folders/", r"/private/"):
        hits += re.findall(pat + r"[^\"\s,]*", text)
    return hits


def scrub(text: str, replacements: dict[str, str]) -> str:
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def klt_env(pdk_root: str | None) -> dict[str, str]:
    env = {**os.environ, "PDK": "sky130A"}
    if pdk_root:
        env["PDK_ROOT"] = pdk_root
    return env


def resolve_pdk_root(klt: str, env: dict[str, str]) -> str:
    if env.get("PDK_ROOT"):
        return env["PDK_ROOT"]
    info = run_klt(["pdk", "find", "--pdk", "sky130A"], env=env, klt=klt)
    return info["root"]


def tool_pins(klt: str, env: dict[str, str], pdk_root: str) -> dict:
    ver = run_klt(["version"], env=env, klt=klt)
    pdk_json = load_json(REPO_ROOT / "layout" / "pdk.json")
    lef = Path(pdk_root) / LEF_REL
    lib = Path(pdk_root) / SPICE_REL
    pins = {
        "klt_version": ver.get("version") or ver.get("klt_version") or ver,
        "klt_pin_expected": pdk_json["klt_version_pin"],
        "klt_pin_source": pdk_json["ci_klt_install"],
        "open_pdks_commit_expected": pdk_json["open_pdks_commit"],
        "pdk_variant": pdk_json["variant"],
        "deck": pdk_json["klt_deck"],
        "std_cell_lef_sha256": sha256_file(lef),
        "std_cell_spice_sha256": sha256_file(lib),
    }
    try:
        import klayout.db as db  # noqa: PLC0415

        pins["python_klayout"] = db.__version__ if hasattr(db, "__version__") else "unknown"
    except ImportError:
        pins["python_klayout"] = "not importable"
    return pins


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------


class Inputs:
    """The immutable #172 inputs plus the child evidence the reference needs."""

    def __init__(self) -> None:
        self.gds = SPEC_DIR / "trng_whole.gds"
        self.ref172 = SPEC_DIR / "trng_whole.ref.spice"
        self.iface = load_json(SPEC_DIR / "interface.json")
        self.report172 = load_json(SPEC_DIR / "report.json")
        ref_text = self.ref172.read_text()
        m = re.search(r"^\.subckt trng_whole\s+(.*)$", ref_text, re.M)
        if not m:
            raise BuildError("trng_whole.ref.spice has no .subckt trng_whole")
        self.ports = m.group(1).split()
        dm = re.search(r"^\.subckt trng_digital\s+(.*)$", ref_text, re.M)
        if not dm:
            raise BuildError("trng_whole.ref.spice has no .subckt trng_digital")
        self.digital_ports = dm.group(1).split()
        self.analog_ref = REPO_ROOT / "layout/sampler_core/sampler_core.ref.spice"
        self.verilog = REPO_ROOT / "layout/trng_digital/trng_digital.routed.v"
        self.deff = REPO_ROOT / "layout/trng_digital/trng_digital.def"
        self.hashes = {
            rel(p): sha256_file(p)
            for p in (
                self.gds,
                self.ref172,
                SPEC_DIR / "interface.json",
                SPEC_DIR / "report.json",
                self.analog_ref,
                self.verilog,
                self.deff,
                REPO_ROOT / "layout/sampler_core/sampler_core.gds",
                REPO_ROOT / "layout/trng_digital/trng_digital.gds",
                REPO_ROOT / "layout/pdk.json",
            )
        }
        # cross-check #172's own recorded hashes against the files on disk
        recorded = self.report172["inputs_sha256"]
        for path, digest in recorded.items():
            if path in self.hashes and "sha256:" + self.hashes[path] != digest:
                raise BuildError(f"{path}: hash differs from layout/trng_whole/report.json")
        out = self.report172["outputs"]
        flat = json.dumps(out)
        for path in (self.gds, self.ref172, SPEC_DIR / "interface.json"):
            if self.hashes[rel(path)] not in flat:
                raise BuildError(f"{path.name} hash is not the one recorded in layout/trng_whole/report.json")

    def port_class(self) -> dict[str, dict]:
        classes: dict[str, dict] = {}
        for net in self.iface["whole_block_nets"]:
            classes[net["whole_block_pin"]] = {
                "class": net["class"],
                "direction": net["direction"],
                "analog_pin": net.get("analog_pin"),
                "digital_pin": net.get("digital_pin"),
            }
        for pin in self.iface["digital_pins"]:
            classes.setdefault(
                pin["pin"],
                {"class": "digital_external", "direction": pin["direction"], "analog_pin": None, "digital_pin": pin["pin"]},
            )
        return classes


# --------------------------------------------------------------------------
# reference
# --------------------------------------------------------------------------


def build_reference_text(inp: Inputs, pdk_root: str) -> tuple[str, dict]:
    from klayout_tools import verilog_netlist as vn  # noqa: PLC0415

    lib = Path(pdk_root) / SPICE_REL
    orders = vn.parse_subckt_pin_orders(lib.read_text())
    to_whole = {p: p for p in inp.digital_ports}
    to_whole["VPWR"] = "vdd"
    to_whole["VGND"] = "vss"
    header = [
        "* trng_whole -- mixed-level whole-block LVS reference, GENERATED by",
        "* layout/bin/verify-whole.py (issue #173). Do not edit by hand; `verify-whole.py check`",
        "* rebuilds it and fails on drift.",
        "*",
        "* Analog sampler_core: TRANSISTOR LEVEL. The committed, LVS-matched",
        "*   layout/sampler_core/sampler_core.ref.spice hierarchy flattened into this circuit",
        "*   (every MOSFET kept; internal nets/instances carry an a_ path prefix).",
        "* Digital trng_digital: STANDARD-CELL LEVEL. Each placed sky130_fd_sc_hd cell is a",
        "*   pin-only black box (stub at the end of this file). Signal pins come from",
        "*   layout/trng_digital/trng_digital.routed.v; VPWR/VPB -> vdd, VGND -> vss (the",
        "*   macro's documented supply aliases); cells the Verilog never instantiates (fill,",
        "*   tap) come from the routed DEF COMPONENTS and must be power-only. Internal nets",
        "*   carry a d_ prefix; unconnected output pins get unique NC_ nets.",
        "* VNB (substrate-only pin) is omitted from every stub: klt extract drops it from the",
        "*   layout-side stubs (the deck's global substrate net), so substrate/VNB",
        "*   connectivity of the digital cells is NOT checked by this reference.",
        "* The digital module boundary (trng_digital) is flattened away: the extraction is flat.",
        "* Port order/names: layout/trng_whole/trng_whole.ref.spice (.subckt trng_whole).",
    ]
    return V.build_reference(
        analog_ref_text=inp.analog_ref.read_text(),
        analog_top="sampler_core",
        whole_ports=inp.ports,
        verilog_text=inp.verilog.read_text(),
        def_text=inp.deff.read_text(),
        lib_pin_orders=orders,
        digital_module="trng_digital",
        digital_to_whole=to_whole,
        header=header,
        verilog_parser=vn.parse_gate_level_verilog,
    )


# --------------------------------------------------------------------------
# one verification pass over a stream (extract -> canonicalise -> LVS)
# --------------------------------------------------------------------------


def write_requests(workdir: Path, gds: Path, ref: Path, ports: list[str], lef: str, *, layout_name: str = "trng_whole.layout.spice") -> dict:
    """Write extract/LVS request documents into *workdir*; paths relative to it."""

    def r(p: Path) -> str:
        return os.path.relpath(p, workdir)

    extract_req = {
        "schema": "klt.extract.request/1",
        "file": r(gds),
        "deck": "sky130",
        "top": TOP,
        "pins": ",".join(ports),
        "abstract_cells": "sky130_fd_sc_hd__*",
        "abstract_cell_lef": lef,
        "output": "trng_whole.layout.raw.spice",
    }
    lvs_req = {
        "layout": {"netlist": layout_name, "top": TOP},
        "reference": {"netlist": r(ref), "form": "subckt-call", "deck": "sky130", "top": TOP},
        "options": {"anchor_top_level_pins": True},
    }
    return {"extract": extract_req, "lvs": lvs_req}


def run_pass(
    label: str,
    gds: Path,
    ref: Path,
    inp: Inputs,
    workdir: Path,
    *,
    klt: str,
    env: dict[str, str],
    pdk_root: str,
) -> dict:
    """extract (abstracted std cells, declared pins) -> canonicalise -> LVS.

    Returns the responses plus the canonical layout netlist path. Nothing
    outside *workdir* is written.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    lef = str(Path(pdk_root) / LEF_REL)
    reqs = write_requests(workdir, gds, ref, inp.ports, lef)
    ext_req_path = workdir / "extract.request.json"
    write_json(ext_req_path, reqs["extract"])
    raw = workdir / "trng_whole.layout.raw.spice"
    saved = workdir / "extract.response.json"
    if REUSE and raw.is_file() and saved.is_file():
        extract = load_json(saved)  # debugging aid only: never used for committed evidence
    else:
        extract = run_klt(["extract", str(ext_req_path)], env=env, cwd=workdir, klt=klt)
        write_json(saved, extract)
    if extract.get("status") != "extracted" or not raw.is_file():
        raise BuildError(f"{label}: klt extract did not produce a netlist (status {extract.get('status')!r})")
    canon_text, canon = V.canonicalise_pins(raw.read_text(), TOP, inp.ports)
    layout = workdir / "trng_whole.layout.spice"
    layout.write_text(canon_text)
    lvs_req_path = workdir / "lvs.request.json"
    write_json(lvs_req_path, reqs["lvs"])
    lvs = run_klt(["lvs", str(lvs_req_path)], env=env, cwd=workdir, klt=klt)
    return {
        "label": label,
        "extract": extract,
        "extract_request": reqs["extract"],
        "canon": canon,
        "layout_netlist": layout,
        "raw_netlist_sha256": sha256_file(raw),
        "lvs": lvs,
        "lvs_request": reqs["lvs"],
    }


# --------------------------------------------------------------------------
# audits
# --------------------------------------------------------------------------


def summarise_endpoints(counter: Counter, limit: int = 6) -> list[list]:
    return [[k, n] for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def endpoint_audit(inp: Inputs, layout_text: str, ref_text: str) -> dict:
    """Per-port connection multisets, layout vs reference, independent of the
    LVS comparer. Equality means: the net carrying each whole-block port has
    exactly the same standard-cell pins and transistor terminals attached on
    both sides -- a defect at a black box's pin cannot hide behind the box.
    """
    lay = V.endpoints(layout_text, TOP, set())
    ref = V.endpoints(ref_text, TOP, set())
    lay_stubs = V.stub_pin_sets(layout_text)
    ref_stubs = V.stub_pin_sets(ref_text)
    stub_diff = {}
    order_only = []
    for cell in sorted(set(lay_stubs) | set(ref_stubs)):
        a, b = lay_stubs.get(cell), ref_stubs.get(cell)
        if a is None or b is None or sorted(a) != sorted(b):
            stub_diff[cell] = {"layout": a, "reference": b}
        elif a != b:
            order_only.append(cell)
    classes = inp.port_class()
    rows = []
    bad = []
    for port in inp.ports:
        a, b = lay.get(port, Counter()), ref.get(port, Counter())
        equal = a == b
        row = {
            "unloaded": sum(a.values()) == 0 and sum(b.values()) == 0,
            "port": port,
            "class": classes.get(port, {}).get("class", "unclassified"),
            "direction": classes.get(port, {}).get("direction"),
            "layout_endpoints": sum(a.values()),
            "reference_endpoints": sum(b.values()),
            "endpoint_multiset_equal": equal,
            "top_endpoints": summarise_endpoints(a),
        }
        if not equal:
            row["layout_only"] = summarise_endpoints(a - b)
            row["reference_only"] = summarise_endpoints(b - a)
            bad.append(port)
        rows.append(row)
    return {"rows": rows, "mismatched_ports": bad, "stub_pin_differences": stub_diff,
            "stub_pin_order_only_differences": order_only}


def lvs_pairing(lvs: dict, ports: list[str]) -> dict:
    """Which ports the comparer paired layout<->reference by name as pins."""
    pairs = {(e["layout"], e["reference"]) for e in lvs.get("net_correspondence", []) if e.get("pin")}
    paired = [p for p in ports if (p.upper(), p.upper()) in pairs]
    return {"ports_paired_by_name": len(paired), "ports_not_paired": sorted(set(ports) - set(paired))}


def coverage_matrix(inp: Inputs, run: dict, endpoint: dict, ref_facts: dict, drc: dict) -> dict:
    lvs = run["lvs"]
    pairing = lvs_pairing(lvs, inp.ports)
    unpaired = set(pairing["ports_not_paired"])
    canon = run["canon"]
    rows = []
    for row in endpoint["rows"]:
        port = row["port"]
        rows.append(
            {
                "port": port,
                "class": row["class"],
                "direction": row["direction"],
                "extracted_pin_unique": port not in canon["ports_missing"] and port not in canon["ports_duplicated"],
                "joined_with_other_port": any(port in v for v in canon["joined_pins"].values()),
                "lvs_paired_by_name": port not in unpaired,
                "endpoints_layout": row["layout_endpoints"],
                "endpoints_reference": row["reference_endpoints"],
                "endpoint_multiset_equal": row["endpoint_multiset_equal"],
                "no_cell_or_device_loads": row["unloaded"],
                "top_endpoints": row["top_endpoints"],
            }
        )
    supplies = {
        "vdd": "digital VPWR + VPB of every placed cell + analog vdd; tap/fill VPWR",
        "vss": "digital VGND of every placed cell + analog vss; tap/fill VGND",
        "vddr1": "ring 1 supply only (analog); never merged with vdd/vss or another vddr",
        "vddr2": "ring 2 supply only (analog)",
        "vddr3": "ring 3 supply only (analog)",
        "vddr4": "ring 4 supply only (analog)",
    }
    for r in rows:
        if r["port"] in supplies:
            r["supply_note"] = supplies[r["port"]]
    layers = drc["coverage"]
    unloaded = [r["port"] for r in endpoint["rows"] if r["unloaded"]]
    limitations = [
        {
            "id": "L1",
            "item": "digital standard-cell internals",
            "status": "not checked",
            "detail": "Every sky130_fd_sc_hd cell is an opaque pin-only black box on both sides "
            "(klt extract --abstract-cells). Transistor-level LVS of the cell internals is not done; the cells "
            "are the PDK's own, and the macro-level digital LVS (layout/trng_digital/lvs.json) is cell level too. "
            "What IS checked: every cell's signal and power pin lands on the same net as in the as-built netlist.",
        },
        {
            "id": "L2",
            "item": "digital substrate / VNB and well-body ties",
            "status": "not checked",
            "detail": "klt extract drops VNB from every abstracted stub (substrate-only; deck global net 'vsubs'), "
            "so the reference omits it and nothing here verifies digital substrate or p-well connectivity. "
            "VPB (n-well) IS carried as a stub pin and tied to vdd on the reference; the endpoint audit proves "
            "every VPB sits on the same net as VPWR.",
        },
        {
            "id": "L3",
            "item": "analog device bodies and well/substrate-tap convention",
            "status": "not checked",
            "detail": "lvs.json body_verification.status is 'unchecked': the pre-extracted-netlist request form "
            "gives klt no layout.deck to establish a tap convention. The four MOSFET terminals (including bulk) "
            "are compared topologically against the reference, nothing more.",
        },
        {
            "id": "L4",
            "item": "device parameters",
            "status": "klt default only",
            "detail": "lvs.json device_parameter_coverage is [] (same as layout/sampler_core/lvs.json); the "
            "comparer's own parameter handling applies and no tolerance or compare_parameters option was set. "
            "No claim beyond 'klt lvs reports no device.property mismatch'.",
        },
        {
            "id": "L5",
            "item": "filler / tap / diode cells",
            "status": "compared as power-only / signal cells, not pruned",
            "detail": f"{ref_facts['power_only_instances']} fill/tap instances (from the routed DEF) are carried as "
            "power-pin-only stubs and compared, not pruned (the subckt-call form has no power-only pruning). The one "
            "antenna diode (sky130_fd_sc_hd__diode_2) is a signal cell from the as-built Verilog. Fill/tap counts "
            "come from the DEF, not from the layout extraction, so a missing tap would mismatch.",
        },
        {
            "id": "L6",
            "item": "power connectivity check (klt power_connectivity)",
            "status": "not applicable to this form",
            "detail": "power_connectivity.status is 'unchecked' for reference.form 'subckt-call'. Power is "
            "instead part of the ordinary compare: every cell's VPWR/VPB/VGND pin is an explicit stub pin on both "
            "sides, tied to vdd/vss in the reference, and the endpoint audit compares the vdd/vss endpoint "
            "multisets in full.",
        },
        {
            "id": "L7",
            "item": "hierarchy",
            "status": "flattened",
            "detail": "Reference and layout are flat: sampler_core's subcircuit hierarchy is expanded in the "
            "reference, the digital module boundary does not exist in the comparison. Which macro a net lives in "
            "is not part of the verdict.",
        },
        {
            "id": "L8",
            "item": "pin names",
            "status": "canonicalised",
            "detail": "klt names an extracted net by all its labels joined with '|'. Each top pin whose label set "
            "contains exactly one whole-block port name is renamed to that port name (verify-whole.py; 123 of 123); "
            "pins with zero or several port names are never repaired (they stay composite and fail the compare). "
            "Pin identity is then anchored by name through options.anchor_top_level_pins.",
        },
        {
            "id": "L9",
            "item": "curated DRC deck",
            "status": "partial rule coverage",
            "detail": f"klt's curated sky130 deck checks {len(layers['rules_checked'])} rules on "
            f"{len(layers['layers_checked'])} layers; {len(layers['layers_in_stream_without_rules'])} layer/datatype "
            f"pairs in the stream have no rules and {len(layers['rules_skipped'])} deck rules are skipped (see drc.json "
            "coverage). Clean here is not foundry DRC clean: no antenna, density, seal-ring, latch-up or "
            "foundry-only rules.",
        },
        {
            "id": "L10",
            "item": "analog-origin DRC history",
            "status": "resolved upstream, re-verified",
            "detail": "The 5664 licon1.ongrid.1 findings #172 reported on sampler_core came from klayout-tools#2648 "
            "(cut centres off the 0.005 um grid). Issue #181 regenerated sampler_core on the fixed generator "
            "(klt 0.6.0+g5edb557f91d0) with new provenance; this run re-verifies the composed stream on that build "
            "with the rule still enabled (licon1.ongrid.1 is in rules_checked) and finds 0 violations. No rule was "
            "waived, relaxed or removed.",
        },
        {
            "id": "L11",
            "item": "extraction is not parasitic / electrical",
            "status": "out of scope",
            "detail": "Schematic-equivalent connectivity only. Coupling between the vdd/vddr routes, IR drop, period "
            "scatter and every DR-0003 section 8 / DR-0009 measurement obligation stay open for #174 and #170.",
        },
        {
            "id": "L13",
            "item": "unloaded boundary pins",
            "status": "endpoint audit vacuous for these ports",
            "detail": f"{len(unloaded)} digital input ports ({unloaded[0]} .. {unloaded[-1]}) have no standard-cell "
            "load in the as-built netlist (the RTL does not use bus_wdata[31:3]), so their endpoint multisets are "
            "empty on both sides and prove nothing. Their identity is covered only by: exactly one extracted pin carries "
            "the name, it is not joined with another port, and options.anchor_top_level_pins pairs it by name with the "
            "reference pin. A short from one of them to a loaded net is still caught (joined pin / net mismatch). "
            "Exchanging the names of two UNLOADED pins is electrically a no-op and is undetectable by construction "
            "(a trial swap of bus_wdata[3]/[4] compared 'match'); the digital swap control therefore uses two loaded bits.",
        },
        {
            "id": "L14",
            "item": "stub pin order",
            "status": "differs, compared by name",
            "detail": "klt extract lists an abstracted stub's pins alphabetically, the reference uses the PDK's pin "
            "order (" + ", ".join(endpoint["stub_pin_order_only_differences"]) + "); the pin sets are identical "
            "and each file's X cards follow its own order, so the endpoint audit (by pin name) is unaffected.",
        },
        {
            "id": "L15",
            "item": "extraction warnings (reviewed, none hidden)",
            "status": "reviewed",
            "detail": warning_review(run["extract"]),
        },
        {
            "id": "L12",
            "item": "area target",
            "status": "Unmet (unchanged)",
            "detail": "0.126116 mm2 against the unchanged < 0.05 mm2 target (layout/trng_whole/README.md). Not "
            "touched by this increment.",
        },
    ]
    return {
        "schema_version": 1,
        "not_signoff": NOT_SIGNOFF,
        "ports": len(rows),
        "ports_clean": sum(
            1
            for r in rows
            if r["extracted_pin_unique"] and not r["joined_with_other_port"] and r["lvs_paired_by_name"] and r["endpoint_multiset_equal"]
        ),
        "rows": rows,
        "stub_pin_differences": endpoint["stub_pin_differences"],
        "stub_pin_order_only_differences": endpoint["stub_pin_order_only_differences"],
        "unloaded_ports": unloaded,
        "limitations": limitations,
    }


def warning_review(ext: dict) -> str:
    warns = ext.get("warnings") or []
    merged = sum(1 for w in warns if w.startswith("net ") and " merges " in w)
    vsubs = sum(1 for w in warns if "vsubs" in w)
    ignored = ext.get("ignored_layers") or []
    same = [w for w in warns if "onto the same net" in w and "VPB, VPWR" in w]
    n_same = int(same[0].split()[0]) if same else 0
    return (
        f"{len(warns)} klt extract warnings, all classified: {merged} 'net merges N distinct labels' (the analog "
        "macro labels its internal nodes; harmless to connectivity, and the reason pin names need canonicalising, L8); "
        f"{vsubs} '--abstract-cells ... resolve only through the deck's global net vsubs' (VNB dropped from those stubs, L2); "
        f"one 'abstract-cells instances resolved VPB and VPWR onto the same net' ({n_same} instances: this is the documented "
        "VPB=VPWR well tie, confirmed rather than hidden); one 'promoted nets from labels below the top cell' (three "
        "analog internal nodes, demoted by the declared pin set - the extracted top has exactly 123 pins); one 'kept N nets "
        "internal: not in the declared pin set'; one dead-metal notice (see verify.json extract.dead_metal: all li1/mcon/met1 "
        "inside the digital macro's hidden cell artwork, none on met2..met5 or in the analog macro or the composition "
        f"routing); one 'layers outside the deck's connectivity graph' ({len(ignored)} layer/datatype pairs listed in "
        "extract.json.gz ignored_layers[]: geometry the curated deck does not treat as conductors; it is invisible to "
        "extraction and therefore NOT examined by this verification)."
    )


def coverage_markdown(cov: dict) -> str:
    lines = [
        "# Whole-block verification coverage matrix",
        "",
        "Generated by `layout/bin/verify-whole.py` (issue #173). " + NOT_SIGNOFF,
        "",
        f"**{cov['ports_clean']} of {cov['ports']} whole-block ports are clean** on all four per-port checks: "
        "exactly one extracted pin carries the port name (not joined with another port), the LVS comparer paired it by "
        "name with the reference pin, and the independent endpoint audit finds the identical multiset of "
        "standard-cell pins / transistor terminals on its layout and reference nets.",
        "",
        "## Per-port",
        "",
        "| port | class | dir | pin unique | not joined | LVS paired | endpoints L/R | equal |",
        "|---|---|---|---|---|---|---|---|",
    ]
    yes = lambda b: "yes" if b else "**NO**"  # noqa: E731
    for r in cov["rows"]:
        lines.append(
            f"| `{r['port']}` | {r['class']} | {r['direction']} | {yes(r['extracted_pin_unique'])} | "
            f"{yes(not r['joined_with_other_port'])} | {yes(r['lvs_paired_by_name'])} | "
            f"{r['endpoints_layout']}/{r['endpoints_reference']} | {yes(r['endpoint_multiset_equal'])} |"
        )
    lines += ["", "## Named limitations (carried into #174 and #170)", "", "| id | item | status | detail |", "|---|---|---|---|"]
    for l in cov["limitations"]:
        lines.append(f"| {l['id']} | {l['item']} | {l['status']} | {l['detail']} |")
    if cov["stub_pin_differences"]:
        lines += ["", "## Stub pin-set differences (layout vs reference)", ""]
        for cell, d in cov["stub_pin_differences"].items():
            lines.append(f"- `{cell}`: layout {d['layout']}, reference {d['reference']}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# baseline
# --------------------------------------------------------------------------


def warn_summary(lvs: dict) -> list[dict]:
    out = []
    for cat, n in sorted(lvs.get("category_counts", {}).items()):
        errors = lvs.get("category_error_counts", {}).get(cat, 0)
        out.append({"category": cat, "count": n, "error_count": errors})
    return out


def accepted_warnings(lvs: dict) -> list[dict]:
    explained = {
        "topology.top_level_pins_anchored": "intended: options.anchor_top_level_pins asserts each of the 123 top "
        "pins by name; reported as a warning-severity disclosure, not a defect.",
    }
    return [{**w, "explanation": explained.get(w["category"], "UNEXPLAINED")} for w in warn_summary(lvs)]


def baseline_checks(inp: Inputs, run: dict, endpoint: dict) -> list[str]:
    lvs, ext, canon = run["lvs"], run["extract"], run["canon"]
    errs = []
    if lvs["status"] != "match" or lvs["error_count"] != 0:
        errs.append(f"LVS status {lvs['status']!r}, error_count {lvs['error_count']}")
    if any(w["explanation"] == "UNEXPLAINED" for w in accepted_warnings(lvs)):
        errs.append("LVS reports a warning category with no recorded explanation")
    if canon["ports_missing"] or canon["ports_duplicated"] or canon["joined_pins"]:
        errs.append(f"pin canonicalisation: {canon}")
    if endpoint["mismatched_ports"]:
        errs.append(f"endpoint audit mismatches on ports {endpoint['mismatched_ports']}")
    if endpoint["stub_pin_differences"]:
        errs.append(f"stub pin lists differ: {endpoint['stub_pin_differences']}")
    if lvs["counts"]["pins"]["layout"] != len(inp.ports) or lvs["counts"]["pins"]["reference"] != len(inp.ports):
        errs.append(f"LVS pin counts {lvs['counts']['pins']} != {len(inp.ports)} ports")
    if ext.get("device_count") != 264:
        errs.append(f"extract device_count {ext.get('device_count')} != 264")
    dead = dead_metal_review(inp, ext)
    if dead["outside_digital_macro"] or dead["on_layers_above_met1"]:
        errs.append(f"dead metal outside the digital macro's standard-cell artwork: {dead}")
    return errs


def dead_metal_review(inp: Inputs, ext: dict) -> dict:
    """klt reports routing-stack clusters that join no extracted net. Inside the
    abstracted digital cells that is the hidden artwork (li1/mcon/met1 of cells
    that are black boxes); anywhere else it would mean an intended connection is
    missing (a stub of composition routing, an unconnected pad), so it is an error."""
    dig = inp.report172["macros"]["dig"]["bbox_um"]
    entries = ext.get("dead_metal") or []
    outside = []
    above = []
    for e in entries:
        bb = e["bbox_um"]
        if not (dig["x0"] <= bb["left"] and bb["right"] <= dig["x1"] and dig["y0"] <= bb["bottom"] and bb["top"] <= dig["y1"]):
            outside.append(e)
        if e["layer"] > 68:
            above.append(e)
    return {
        "clusters": len(entries),
        "by_layer": dict(sorted(Counter(f"{e['layer']}/{e['datatype']}" for e in entries).items())),
        "inside_digital_macro_bbox": len(entries) - len(outside),
        "outside_digital_macro": outside[:5],
        "on_layers_above_met1": above[:5],
        "reading": "all inside the digital macro and all li1/mcon/met1: standard-cell internal artwork hidden by the "
        "abstraction (L1); none on met2..met5 and none in the analog macro or the composition routing",
    }


def stage(root: Path, gds_src: Path | None, ref_text: str, *, copy: bool = False) -> tuple[Path, Path, Path]:
    """Lay out a scratch tree that mirrors the committed one::

        <root>/trng_whole.gds        (symlink to / copy of the stream under test)
        <root>/verify/lvs.ref.spice  (+ every request, netlist and report of a pass)

    so the requests and the reports klt writes carry the same relative paths as
    the committed evidence (``../trng_whole.gds``, ``lvs.ref.spice``) and
    ``klt drc|lvs --check`` works on the committed files.
    """
    vdir = root / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    link = root / "trng_whole.gds"
    if gds_src is not None:
        if link.exists() or link.is_symlink():
            link.unlink()
        if copy:
            shutil.copy2(gds_src, link)
        else:
            link.symlink_to(gds_src)
    ref = vdir / "lvs.ref.spice"
    ref.write_text(ref_text)
    return link, vdir, ref


def run_drc(gds: Path, workdir: Path, *, klt: str, env: dict[str, str]) -> tuple[dict, dict]:
    req = {"schema": "klt.drc.request/1", "file": os.path.relpath(gds, workdir), "deck": "sky130", "top": TOP}
    path = workdir / "drc.request.json"
    write_json(path, req)
    resp = run_klt(["drc", str(path)], env=env, cwd=workdir, klt=klt)
    return req, resp


def stable_lvs_view(lvs: dict) -> dict:
    return {
        "status": lvs["status"],
        "mismatch_count": lvs["mismatch_count"],
        "error_count": lvs["error_count"],
        "category_counts": lvs["category_counts"],
        "counts": lvs["counts"],
        "layout_sha256": lvs["environment"]["layout_sha256"],
        "reference_sha256": lvs["environment"]["reference_sha256"],
    }


def build_baseline(args, workdir: Path) -> dict:
    inp = Inputs()
    env = klt_env(os.environ.get("PDK_ROOT"))
    pdk_root = resolve_pdk_root(args.klt, env)
    env["PDK_ROOT"] = pdk_root
    pins = tool_pins(args.klt, env, pdk_root)
    if pins["klt_version"] != pins["klt_pin_expected"]:
        print(
            f"warning: klt {pins['klt_version']!r} != layout/pdk.json pin {pins['klt_pin_expected']!r}",
            file=sys.stderr,
        )
        if not args.allow_tool_drift:
            raise BuildError("tool drift vs layout/pdk.json (use --allow-tool-drift to proceed and record it)")
    gds_before = sha256_file(inp.gds)

    ref_text, ref_facts = build_reference_text(inp, pdk_root)
    gds_link, vdir, ref_path = stage(workdir / "trng_whole", inp.gds, ref_text)

    drc_req, drc = run_drc(gds_link, vdir, klt=args.klt, env=env)
    if drc["status"] != "clean" or drc["violation_count"] != 0:
        raise BuildError(f"whole-block DRC is not clean: {drc['violation_count']} violations {drc.get('rule_counts')}")
    if "licon1.ongrid.1" not in drc["coverage"]["rules_checked"]:
        raise BuildError("licon1.ongrid.1 is not among the checked DRC rules -- a clean verdict would be vacuous")

    run = run_pass("baseline", gds_link, ref_path, inp, vdir, klt=args.klt, env=env, pdk_root=pdk_root)
    layout_text = run["layout_netlist"].read_text()
    endpoint = endpoint_audit(inp, layout_text, ref_text)
    errs = baseline_checks(inp, run, endpoint)
    if errs:
        raise BuildError("baseline verification failed:\n  " + "\n  ".join(errs))
    cov = coverage_matrix(inp, run, endpoint, ref_facts, drc)
    if sha256_file(inp.gds) != gds_before:
        raise BuildError("trng_whole.gds changed during verification")
    return {
        "inp": inp,
        "env": env,
        "pdk_root": pdk_root,
        "pins": pins,
        "ref_text": ref_text,
        "ref_facts": ref_facts,
        "ref_path": ref_path,
        "drc_request": drc_req,
        "drc": drc,
        "run": run,
        "endpoint": endpoint,
        "coverage": cov,
    }


def sanitized_extract_request(req: dict) -> dict:
    out = copy.deepcopy(req)
    out["abstract_cell_lef"] = "${PDK_ROOT}/" + LEF_REL
    out["file"] = "../trng_whole.gds"
    out["output"] = "trng_whole.layout.raw.spice"
    return out


def sanitized_lvs_request(req: dict) -> dict:
    out = copy.deepcopy(req)
    out["reference"]["netlist"] = "lvs.ref.spice"
    return out


def verify_report(b: dict) -> dict:
    run, drc, pins = b["run"], b["drc"], b["pins"]
    ext, lvs = run["extract"], run["lvs"]
    return {
        "schema_version": 1,
        "issue": 173,
        "parent": 170,
        "provisional": True,
        "not_signoff": NOT_SIGNOFF,
        "verdict": "DRC clean (0 violations) and LVS match (0 errors) on the declared mixed-level coverage; "
        "named limitations in coverage.md; no foundry sign-off",
        "inputs_sha256": b["inp"].hashes,
        "reference": {
            "path": "layout/trng_whole/verify/lvs.ref.spice",
            "sha256": sha256_text(b["ref_text"]),
            "facts": b["ref_facts"],
            "generator": "layout/bin/verify-whole.py (build_reference_text) + layout/bin/verify_whole_lib.py",
        },
        "tool_pins": pins,
        "drc": {
            "request": "layout/trng_whole/verify/drc.request.json",
            "report": "layout/trng_whole/verify/drc.json",
            "status": drc["status"],
            "violation_count": drc["violation_count"],
            "deck": drc["provenance"]["deck"],
            "input_content_hash": drc["provenance"]["input"]["content_hash"],
            "rules_checked": len(drc["coverage"]["rules_checked"]),
        },
        "extract": {
            "request": "layout/trng_whole/verify/extract.request.json",
            "report": "layout/trng_whole/verify/extract.json.gz",
            "status": ext["status"],
            "device_count": ext["device_count"],
            "device_counts": ext["device_counts"],
            "net_count": ext["net_count"],
            "pin_count_raw": ext["pin_count"],
            "dead_metal": {k: v for k, v in dead_metal_review(b["inp"], ext).items() if k not in ("outside_digital_macro", "on_layers_above_met1")},
            "abstracted_cell_types": len(ext.get("abstracted_cells") or []),
            "abstracted_instances": sum(c["instance_count"] for c in (ext.get("abstracted_cells") or [])),
            "warning_count": len(ext.get("warnings") or []),
            "raw_netlist_sha256": run["raw_netlist_sha256"],
            "raw_netlist_note": "anonymous $N net numbering is not a stable cross-host contract (klt extract --help); "
            "the canonical netlist hash below is what the LVS report pins",
            "deck": ext["provenance"]["deck"],
        },
        "pin_canonicalisation": run["canon"],
        "lvs": {
            "request": "layout/trng_whole/verify/lvs.request.json",
            "report": "layout/trng_whole/verify/lvs.json",
            "layout_netlist": "layout/trng_whole/verify/trng_whole.layout.spice",
            "layout_netlist_sha256": lvs["environment"]["layout_sha256"],
            "reference_sha256": lvs["environment"]["reference_sha256"],
            "status": lvs["status"],
            "mismatch_count": lvs["mismatch_count"],
            "error_count": lvs["error_count"],
            "counts": lvs["counts"],
            "warnings_reviewed": accepted_warnings(lvs),
            "power_connectivity": lvs["power_connectivity"]["status"],
            "body_verification": lvs["body_verification"]["status"],
        },
        "endpoint_audit": {
            "ports": len(b["endpoint"]["rows"]),
            "mismatched_ports": b["endpoint"]["mismatched_ports"],
            "stub_pin_differences": b["endpoint"]["stub_pin_differences"],
        },
        "coverage": {"matrix": "layout/trng_whole/verify/coverage.json", "ports_clean": b["coverage"]["ports_clean"], "ports": b["coverage"]["ports"]},
    }


def publish_baseline(b: dict) -> None:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    run = b["run"]
    files: dict[str, str | bytes] = {}
    files["lvs.ref.spice"] = b["ref_text"]
    files["drc.request.json"] = json.dumps(b["drc_request"] | {"file": "../trng_whole.gds"}, indent=2) + "\n"
    files["drc.json"] = json.dumps(b["drc"], indent=2) + "\n"
    files["extract.request.json"] = json.dumps(sanitized_extract_request(run["extract_request"]), indent=2) + "\n"
    files["extract.json.gz"] = gzip.compress((json.dumps(run["extract"], indent=2) + "\n").encode(), mtime=0)
    files["trng_whole.layout.spice"] = run["layout_netlist"].read_text()
    files["lvs.request.json"] = json.dumps(sanitized_lvs_request(run["lvs_request"]), indent=2) + "\n"
    files["lvs.json"] = json.dumps(run["lvs"], indent=2) + "\n"
    files["coverage.json"] = json.dumps(b["coverage"], indent=2) + "\n"
    files["coverage.md"] = coverage_markdown(b["coverage"])
    files["verify.json"] = json.dumps(verify_report(b), indent=2) + "\n"
    pdk_root = b["pdk_root"]
    for name, content in files.items():
        data = content if isinstance(content, bytes) else content.encode()
        text_hits = [] if isinstance(content, bytes) else host_path_hits(content)
        if isinstance(content, bytes):
            text_hits = host_path_hits(gzip.decompress(content).decode())
        if text_hits:
            # report-local absolute paths (work dir, PDK root): strip, never commit
            if isinstance(content, bytes):
                plain = gzip.decompress(content).decode()
                plain = scrub_host(plain, pdk_root)
                data = gzip.compress(plain.encode(), mtime=0)
            else:
                data = scrub_host(content, pdk_root).encode()
        (VERIFY_DIR / name).write_bytes(data)
    leftovers = []
    for name in files:
        p = VERIFY_DIR / name
        text = gzip.decompress(p.read_bytes()).decode() if name.endswith(".gz") else p.read_text()
        leftovers += [f"{name}: {h}" for h in host_path_hits(text)]
    if leftovers:
        raise BuildError("host paths remain in committed evidence:\n  " + "\n  ".join(leftovers[:10]))


def scrub_host(text: str, pdk_root: str) -> str:
    """Make a klt report host-independent: scratch-tree paths become the
    relative paths of the committed layout (files next to the report, the
    stream one level up), repo paths become repo-relative, the PDK root a
    placeholder."""
    text = re.sub(r"/tmp/verify-whole-[^/\"]+/(?:[^/\"]+/)*?trng_whole/verify/", "", text)
    text = re.sub(r"/tmp/verify-whole-[^/\"]+/(?:[^/\"]+/)*?trng_whole/", "../", text)
    text = text.replace(str(REPO_ROOT) + "/layout/trng_whole/verify/", "")
    text = text.replace(str(REPO_ROOT) + "/layout/trng_whole/", "../")
    text = text.replace(str(REPO_ROOT) + "/", "")
    text = text.replace(pdk_root, "${PDK_ROOT}")
    text = text.replace(str(Path.home()), "~")
    return text


# --------------------------------------------------------------------------
# fault controls
# --------------------------------------------------------------------------


def _klayout():
    import klayout.db as db  # noqa: PLC0415

    return db


def swap_texts_everywhere(gds_in: Path, gds_out: Path, a: str, b: str) -> dict:
    """Exchange two label strings in every cell of a GDS copy (a consistent
    identity swap of two nets). Returns per-name edit counts."""
    db = _klayout()
    ly = db.Layout()
    ly.read(str(gds_in))
    counts = Counter()
    for cell in ly.each_cell():
        for li in ly.layer_indexes():
            for sh in cell.shapes(li).each():
                if sh.is_text() and sh.text_string in (a, b):
                    other = b if sh.text_string == a else a
                    counts[sh.text_string] += 1
                    sh.text_string = other
    if counts[a] == 0 or counts[b] == 0:
        raise BuildError(f"swap {a}<->{b}: label not found ({dict(counts)})")
    ly.write(str(gds_out))
    return dict(counts)


def _met5_region(ly, top):
    db = _klayout()
    li = ly.find_layer(72, 20)
    region = db.Region()
    for sh in top.shapes(li).each():
        if sh.is_polygon() or sh.is_box() or sh.is_path():
            region.insert(sh.polygon if not sh.is_path() else sh.path.polygon())
    return li, region


def cut_route(gds_in: Path, gds_out: Path, probe_um: tuple[float, float], cut_center_um: tuple[float, float], half_um: float) -> dict:
    """Open a gap in the top-cell met5 route that passes through *probe_um*."""
    db = _klayout()
    ly = db.Layout()
    ly.read(str(gds_in))
    top = ly.top_cell()
    li, region = _met5_region(ly, top)
    merged = region.merged()
    dbu = ly.dbu
    pt = db.Region(db.Box(int(probe_um[0] / dbu) - 1, int(probe_um[1] / dbu) - 1, int(probe_um[0] / dbu) + 1, int(probe_um[1] / dbu) + 1))
    target = merged.interacting(pt)
    if target.count() != 1:
        raise BuildError(f"expected one met5 polygon under {probe_um}, found {target.count()}")
    cx, cy = int(cut_center_um[0] / dbu), int(cut_center_um[1] / dbu)
    h = int(half_um / dbu)
    box = db.Region(db.Box(cx - h, cy - h, cx + h, cy + h))
    hit = merged.interacting(box)
    if hit.count() != 1:
        raise BuildError(f"cut box touches {hit.count()} met5 polygons (want only the target)")
    new = (target - box)
    if new.count() < 2:
        raise BuildError("cut did not split the route polygon")
    others = merged - target
    # rewrite the whole top-cell met5 geometry: untouched polygons + the cut route
    _clear_geometry(top.shapes(li))
    for poly in others.each():
        top.shapes(li).insert(poly)
    for poly in new.each():
        top.shapes(li).insert(poly)
    ly.write(str(gds_out))
    return {"route_pieces_after_cut": new.count(), "cut_um": {"x": cut_center_um[0], "y": cut_center_um[1], "half_width": half_um}}


def _clear_geometry(shapes) -> None:
    for sh in list(shapes.each()):
        if sh.is_polygon() or sh.is_box() or sh.is_path():
            sh.delete()


def bridge_pads(gds_in: Path, gds_out: Path, a_um: tuple[float, float], b_um: tuple[float, float]) -> dict:
    """Add a met5 rectangle joining the two met5 polygons under *a_um* and
    *b_um*, choosing the first candidate row that touches exactly those two."""
    db = _klayout()
    ly = db.Layout()
    ly.read(str(gds_in))
    top = ly.top_cell()
    li, region = _met5_region(ly, top)
    merged = region.merged()
    dbu = ly.dbu

    def at(p):
        return merged.interacting(db.Region(db.Box(int(p[0] / dbu) - 1, int(p[1] / dbu) - 1, int(p[0] / dbu) + 1, int(p[1] / dbu) + 1)))

    ta, tb = at(a_um), at(b_um)
    if ta.count() != 1 or tb.count() != 1:
        raise BuildError("expected one met5 polygon under each supply terminal")
    x0, x1 = sorted((a_um[0], b_um[0]))
    chosen = None
    for y in [a_um[1] + d for d in (0.0, 1.0, -1.0, 2.0, -2.0, 3.0, -3.0, 6.0, -6.0)]:
        box = db.Box(int(x0 / dbu), int((y - 0.8) / dbu), int(x1 / dbu), int((y + 0.8) / dbu))
        hit = merged.interacting(db.Region(box))
        if hit.count() == 2 and (hit & ta).count() == 1 and (hit & tb).count() == 1:
            chosen = (y, box)
            break
    if chosen is None:
        raise BuildError("no bridge row touches exactly the two supply polygons")
    top.shapes(li).insert(chosen[1])
    ly.write(str(gds_out))
    return {"bridge_y_um": chosen[0], "bridge_x_um": [x0, x1], "layer": "72/20 (met5)"}


def probe_clusters(gds: Path, points: dict[str, tuple[float, float, str]]) -> dict:
    """Metal-level cluster id and labels under named points (independent of klt)."""
    db, l2n, regions = cw.flat_extract(gds)
    out = {}
    for name, (x, y, layer) in points.items():
        net = cw.probe(db, l2n, regions, layer, x, y)
        out[name] = None if net is None else {"cluster": net.cluster_id, "labels": sorted(cw.net_labels(net))}
    return out


_LAYER_BY_GDS = {(69, 20): "m2", (70, 20): "m3", (71, 20): "m4", (72, 20): "m5"}


def terminals(inp: Inputs, pin: str) -> dict[str, tuple[float, float, str]]:
    nets = [n for n in inp.iface["whole_block_nets"] if n["whole_block_pin"] == pin]
    if not nets:
        dp = next(p for p in inp.iface["digital_pins"] if p["pin"] == pin)
        return {"digital_port": (dp["composed_um"]["x"], dp["composed_um"]["y"], _LAYER_BY_GDS[tuple(dp["layer"])])}
    net = nets[0]
    pts = {}
    a = net["analog_port_composed_um"]
    pts["analog_port"] = (a["x"], a["y"], _LAYER_BY_GDS[tuple(net["analog_port_layer"])])
    if net.get("digital_port_composed_um"):
        d = net["digital_port_composed_um"]
        pts["digital_port"] = (d["x"], d["y"], _LAYER_BY_GDS[tuple(net["digital_port_layer"])])
    if net.get("boundary_pad"):
        p = net["boundary_pad"]
        pts["pad"] = (p["x_um"], p["y_um"], "m5")
    return pts


def swap_reference_nets(ref_text: str, a: str, b: str) -> tuple[str, int]:
    """Swap nets *a* and *b* on every digital standard-cell card of the reference."""
    head, rest = ref_text.split("* ---- digital", 1)
    dig, tail = rest.split(".ends trng_whole", 1)
    count = 0
    out = []
    for line in dig.split("\n"):
        if line.startswith("X"):
            toks = line.split(" ")
            new = [b if t == a else a if t == b else t for t in toks]
            count += sum(1 for x, y in zip(toks, new) if x != y)
            line = " ".join(new)
        out.append(line)
    return head + "* ---- digital" + "\n".join(out) + ".ends trng_whole" + tail, count


def ref_neighbors(ref_text: str, nets: list[str]) -> tuple[set[str], set[str]]:
    """Names (as klt reports them: upper-case, leading ``X`` dropped) of the
    reference cards attached to *nets*, plus the instance-path prefixes of the
    analog ones (``Xa_sr1_Misp`` -> ``A_SR1_``). An LVS error that cannot name
    a net by label (a swapped identity makes the *devices around it* differ)
    is still about that net when it names one of these."""
    top = V.parse_subckts(ref_text)[TOP]
    exact: set[str] = set()
    prefixes: set[str] = set()
    for card in top["cards"]:
        body = [t for t in card[1:] if "=" not in t]
        if any(n in body[:-1] for n in nets):
            name = card[0][1:].upper()
            exact.add(name)
            if name.startswith("A_"):
                prefixes.add(name.rsplit("_", 1)[0] + "_")
    return exact, prefixes


def lvs_evidence(lvs: dict, nets: list[str], ref_text: str) -> dict:
    """Error-severity mismatches about *nets*: those that name a net directly
    (KLayout upper-cases names) or name a reference device/instance attached to
    one of them in the unmodified reference."""
    want = [n.upper() for n in nets]
    exact, prefixes = ref_neighbors(ref_text, nets)
    hits = []
    for m in lvs.get("mismatches", []):
        if m["severity"] != "error":
            continue
        blob = json.dumps(m.get("net")).upper() + json.dumps(m.get("details")).upper()
        via = None
        if any(w in blob for w in want):
            via = "net name"
        else:
            for key in ("device", "instance"):
                ref_name = ((m.get(key) or {}).get("reference") or "").upper()
                if ref_name and (ref_name in exact or any(ref_name.startswith(pf) for pf in prefixes)):
                    via = "device/instance attached to the net in the reference"
                    break
        if via:
            hits.append(
                {
                    "matched_via": via,
                    "category": m["category"],
                    "description": m["description"],
                    "net": m.get("net"),
                    "instance": m.get("instance"),
                    "device": m.get("device"),
                    "property": m.get("property"),
                }
            )
    return {
        "named_nets": nets,
        "errors_naming_them": len(hits),
        "reference_cards_attached": sorted(exact)[:12],
        "examples": hits[:4],
    }


def error_sample(lvs: dict, limit: int = 12) -> list[dict]:
    out = []
    for m in lvs.get("mismatches", []):
        if m["severity"] != "error":
            continue
        out.append({k: m.get(k) for k in ("category", "description", "side", "net", "device", "property", "instance", "subcircuit", "details")})
        if len(out) >= limit:
            break
    return out


def pin_evidence(canon: dict, nets: list[str]) -> dict:
    return {
        "ports_missing": [n for n in nets if n in canon["ports_missing"]],
        "joined_pins": {k: v for k, v in canon["joined_pins"].items() if any(n in v for n in nets)},
    }


def run_control(spec: dict, b: dict, work: Path, args) -> dict:
    inp: Inputs = b["inp"]
    gds_base = sha256_file(inp.gds)
    ref_base = sha256_text(b["ref_text"])
    root = work / spec["id"] / "trng_whole"
    gds, vdir, ref = stage(root, None, b["ref_text"])
    defect: dict = {}
    # 1. build the variant and PROVE the defect is present before verification
    if spec["kind"] == "swap_labels":
        a, bb = spec["nets"]
        defect["edit"] = swap_texts_everywhere(inp.gds, gds, a, bb)
        before = {n: probe_clusters(inp.gds, terminals(inp, n)) for n in spec["nets"]}
        after = {n: probe_clusters(gds, terminals(inp, n)) for n in spec["nets"]}
        for n in spec["nets"]:
            other = bb if n == a else a
            for term, info in after[n].items():
                labs = set(info["labels"]) if info else set()
                if other not in labs or n in labs:
                    raise BuildError(f"{spec['id']}: defect not present at {n} {term}: labels {sorted(labs)}")
        defect["pre_verification_proof"] = {
            "baseline_labels_at_terminals": {n: {t: i["labels"] for t, i in before[n].items() if i} for n in spec["nets"]},
            "variant_labels_at_terminals": {n: {t: i["labels"] for t, i in after[n].items() if i} for n in spec["nets"]},
        }
    elif spec["kind"] == "swap_reference":
        a, bb = spec["nets"]
        new_ref, count = swap_reference_nets(b["ref_text"], a, bb)
        if count < 2:
            raise BuildError(f"{spec['id']}: reference swap touched {count} pins")
        ref.write_text(new_ref)
        shutil.copy2(inp.gds, gds)
        old_lines = b["ref_text"].split("\n")
        new_lines = new_ref.split("\n")
        changed = [i for i, (x, y) in enumerate(zip(old_lines, new_lines)) if x != y]
        defect["edit"] = {"reference_cards_changed": len(changed), "net_pins_exchanged": count,
                          "analog_cards_changed": sum(1 for i in changed if "sky130_fd_pr__" in old_lines[i])}
        if defect["edit"]["analog_cards_changed"]:
            raise BuildError(f"{spec['id']}: swap touched analog cards")
        defect["pre_verification_proof"] = {"reference_sha256_before": ref_base, "reference_sha256_after": sha256_text(new_ref)}
    elif spec["kind"] == "disconnect":
        pin = spec["nets"][0]
        t = terminals(inp, pin)
        before = probe_clusters(inp.gds, t)
        defect["edit"] = cut_route(inp.gds, gds, tuple(spec["probe_um"]), tuple(spec["cut_um"]), spec["half_um"])
        after = probe_clusters(gds, t)
        if len({v["cluster"] for v in before.values() if v}) != 1:
            raise BuildError(f"{spec['id']}: baseline terminals of {pin} are not one cluster")
        if len({v["cluster"] for v in after.values() if v}) < 2:
            raise BuildError(f"{spec['id']}: {pin} terminals are still one cluster after the cut")
        defect["pre_verification_proof"] = {
            "terminals": {k: [v[0], v[1], v[2]] for k, v in t.items()},
            "baseline_distinct_clusters": len({v["cluster"] for v in before.values() if v}),
            "variant_distinct_clusters": len({v["cluster"] for v in after.values() if v}),
        }
    elif spec["kind"] == "supply_short":
        a, bb = spec["nets"]
        ta, tb = terminals(inp, a)["pad"], terminals(inp, bb)["pad"]
        before = probe_clusters(inp.gds, {a: ta, bb: tb})
        defect["edit"] = bridge_pads(inp.gds, gds, (ta[0], ta[1]), (tb[0], tb[1]))
        after = probe_clusters(gds, {a: ta, bb: tb})
        if before[a]["cluster"] == before[bb]["cluster"]:
            raise BuildError(f"{spec['id']}: {a} and {bb} already share a cluster in the baseline")
        if after[a]["cluster"] != after[bb]["cluster"]:
            raise BuildError(f"{spec['id']}: bridge did not join {a} and {bb}")
        defect["pre_verification_proof"] = {
            "baseline_clusters_distinct": True,
            "variant_cluster_shared": True,
            "variant_labels_on_shared_net": after[a]["labels"],
        }
    else:
        raise BuildError(f"unknown control kind {spec['kind']}")

    # 2. run the SAME verification (extract -> canonicalise -> LVS) on the variant
    run = run_pass(spec["id"], gds, ref, inp, vdir, klt=args.klt, env=b["env"], pdk_root=b["pdk_root"])
    lvs = run["lvs"]
    layout_text = run["layout_netlist"].read_text()
    ep = endpoint_audit(inp, layout_text, ref.read_text())
    # 3. judge: must have reached the compare and failed for the intended reason
    cats_err = {c: n for c, n in lvs.get("category_error_counts", {}).items() if n}
    ev = lvs_evidence(lvs, spec["evidence_nets"], b["ref_text"])
    reached = lvs.get("status") in ("match", "mismatch") and "counts" in lvs and run["extract"]["status"] == "extracted"
    ep_hits = sorted(set(ep["mismatched_ports"]) & set(spec.get("expect_endpoint_ports", [])))
    pin_ev = pin_evidence(run["canon"], spec["evidence_nets"])
    detected = (
        reached
        and lvs["status"] == "mismatch"
        and lvs["error_count"] > 0
        and ev["errors_naming_them"] > 0
        and (not spec.get("expect_categories") or bool(set(spec["expect_categories"]) & set(cats_err)))
    )
    result = {
        "id": spec["id"],
        "kind": spec["kind"],
        "intent": spec["intent"],
        "detected": bool(detected),
        "reached_lvs_comparison": bool(reached),
        "defect": defect,
        "variant_gds_sha256": sha256_file(gds),
        "variant_reference_sha256": sha256_file(ref),
        "lvs": {
            "status": lvs["status"],
            "mismatch_count": lvs["mismatch_count"],
            "error_count": lvs["error_count"],
            "error_categories": cats_err,
            "category_counts": lvs["category_counts"],
            "counts": lvs["counts"],
            "evidence": ev,
            "error_sample": error_sample(lvs),
            "expected_categories_any_of": spec.get("expect_categories"),
        },
        "pin_canonicalisation": {k: run["canon"][k] for k in ("pins_after", "renamed", "ports_missing", "ports_duplicated", "joined_pins")},
        "pin_evidence": pin_ev,
        "endpoint_audit": {
            "mismatched_ports": ep["mismatched_ports"],
            "expected_ports_flagged": ep_hits,
            "detail": [r for r in ep["rows"] if r["port"] in ep["mismatched_ports"]][:6],
        },
        "golden_unchanged": sha256_file(inp.gds) == gds_base and sha256_text(b["ref_text"]) == ref_base,
    }
    if not result["golden_unchanged"]:
        raise BuildError(f"{spec['id']}: golden inputs changed while injecting the fault")
    return result


def control_specs(inp: Inputs) -> list[dict]:
    return [
        {
            "id": "swap-analog-ring-bits",
            "kind": "swap_labels",
            "intent": "swapped signal: the identities of two distinct analog boundary outputs (ring_bit1, ring_bit2) "
            "are exchanged on a copy of the composed GDS (every label of both nets, all cells)",
            "nets": ["ring_bit1", "ring_bit2"],
            "evidence_nets": ["ring_bit1", "ring_bit2"],
            "expect_categories": None,
            "expect_endpoint_ports": ["ring_bit1", "ring_bit2"],
        },
        {
            "id": "swap-digital-bus-bits",
            "kind": "swap_labels",
            "intent": "swapped signal: the identities of two distinct digital boundary inputs (bus_wdata[0], "
            "bus_wdata[1]) are exchanged on a copy of the composed GDS (macro pin labels and top promotions)",
            "nets": ["bus_wdata[0]", "bus_wdata[1]"],
            "evidence_nets": ["bus_wdata[0]", "bus_wdata[1]"],
            "expect_categories": None,
            "expect_endpoint_ports": ["bus_wdata[0]", "bus_wdata[1]"],
        },
        {
            "id": "swap-interface-reference",
            "kind": "swap_reference",
            "intent": "swapped signal at the analog-to-digital interface: raw_bit and raw_valid are exchanged on the "
            "digital standard-cell pins of a copy of the reference (the composed GDS is unchanged), so the digital "
            "black boxes' own pins must expose it",
            "nets": ["raw_bit", "raw_valid"],
            "evidence_nets": ["raw_bit", "raw_valid"],
            "expect_categories": ["topology"],
        },
        {
            "id": "disconnect-raw-bit",
            "kind": "disconnect",
            "intent": "disconnected interface: a gap is cut in the met5 route that carries raw_bit from the analog "
            "sampler output to the digital input (copy of the composed GDS)",
            "nets": ["raw_bit"],
            "probe_um": [240.0, 69.7],
            "cut_um": [240.0, 69.7],
            "half_um": 4.0,
            "evidence_nets": ["raw_bit"],
            "expect_categories": None,
        },
        {
            "id": "short-ring-supply-to-logic-supply",
            "kind": "supply_short",
            "intent": "distinct-supply short: the interface contract declares vddr4 (ring 4 supply) and vdd (logic "
            "supply) distinct nets; a met5 bridge joins their boundary pads on a copy of the composed GDS (every "
            "pad-to-pad row between vddr1..vddr3 and their neighbours crosses a third net's route, so this adjacent "
            "pair is the one a single rectangle can short without touching anything else)",
            "nets": ["vddr4", "vdd"],
            "evidence_nets": ["vddr4", "vdd"],
            "expect_categories": None,
            "expect_endpoint_ports": ["vddr4", "vdd"],
        },
    ]


def run_controls(args, b: dict) -> dict:
    inp: Inputs = b["inp"]
    results = []
    gds_before = sha256_file(inp.gds)
    with tempfile.TemporaryDirectory(prefix="verify-whole-controls-") as tmp:
        work = Path(tmp)
        for spec in control_specs(inp):
            if args.only and spec["id"] not in args.only:
                continue
            print(f"control {spec['id']} ...", flush=True)
            res = run_control(spec, b, work, args)
            print(f"  detected={res['detected']} lvs={res['lvs']['status']} errors={res['lvs']['error_count']}", flush=True)
            results.append(res)
        # baseline re-run from the untouched golden inputs after every control
        print("baseline re-run after controls ...", flush=True)
        link, vdir, ref2 = stage(work / "baseline-again" / "trng_whole", inp.gds, b["ref_text"])
        again = run_pass("baseline-after-controls", link, ref2, inp, vdir, klt=args.klt, env=b["env"], pdk_root=b["pdk_root"])
    first, second = stable_lvs_view(b["run"]["lvs"]), stable_lvs_view(again["lvs"])
    rerun = {
        "status": again["lvs"]["status"],
        "error_count": again["lvs"]["error_count"],
        "stable_fields_equal_to_first_baseline": first == second,
        "stable_view": second,
        "pin_canonicalisation_clean": not (again["canon"]["ports_missing"] or again["canon"]["ports_duplicated"] or again["canon"]["joined_pins"]),
    }
    return {
        "schema_version": 1,
        "issue": 173,
        "not_signoff": NOT_SIGNOFF,
        "golden_gds_sha256": gds_before,
        "golden_gds_unchanged": sha256_file(inp.gds) == gds_before,
        "reference_sha256": sha256_text(b["ref_text"]),
        "all_detected": all(r["detected"] for r in results),
        "controls": results,
        "baseline_rerun_after_controls": rerun,
    }


def publish_controls(summary: dict, pdk_root: str) -> None:
    CONTROLS_DIR.mkdir(parents=True, exist_ok=True)
    text = scrub_host(json.dumps(summary, indent=2) + "\n", pdk_root)
    (CONTROLS_DIR / "controls.json").write_text(text)
    md = [
        "# Fault controls (issue #173)",
        "",
        NOT_SIGNOFF,
        "",
        "Each control is a disposable copy of the composed GDS (or of the LVS reference, where stated) run through the "
        "SAME extract -> pin canonicalisation -> mixed-level LVS pipeline as the baseline. The defect is proven present "
        "by an independent metal-level probe (klayout.db) *before* verification; the golden `trng_whole.gds` and "
        "`verify/lvs.ref.spice` hashes are re-checked after each control, and the unmodified baseline is re-run at the "
        "end.",
        "",
        "| control | kind | reached LVS | LVS | errors | error categories | evidence naming the net(s) | detected |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["controls"]:
        md.append(
            f"| `{r['id']}` | {r['kind']} | {'yes' if r['reached_lvs_comparison'] else '**NO**'} | {r['lvs']['status']} | "
            f"{r['lvs']['error_count']} | {r['lvs']['error_categories']} | {r['lvs']['evidence']['errors_naming_them']} errors name "
            f"{r['lvs']['evidence']['named_nets']} | {'yes' if r['detected'] else '**NO**'} |"
        )
    rr = summary["baseline_rerun_after_controls"]
    md += [
        "",
        f"Baseline re-run after all controls: LVS `{rr['status']}`, {rr['error_count']} errors, stable report fields "
        f"{'identical to' if rr['stable_fields_equal_to_first_baseline'] else '**DIFFER FROM**'} the first baseline.",
        "",
        "Per-control defect proofs, LVS categories and mismatch examples are in `controls.json`.",
    ]
    (CONTROLS_DIR / "controls.md").write_text("\n".join(md) + "\n")


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


def check(args) -> int:
    if not VERIFY_DIR.joinpath("verify.json").is_file():
        raise BuildError("no committed layout/trng_whole/verify/verify.json -- run `verify-whole.py run` first")
    committed = load_json(VERIFY_DIR / "verify.json")
    with tempfile.TemporaryDirectory(prefix="verify-whole-check-") as tmp:
        b = build_baseline(args, Path(tmp))
        fresh = verify_report(b)
        drifts = []
        for key in ("inputs_sha256", "reference", "verdict"):
            if committed[key] != fresh[key]:
                drifts.append(key)
        for key in ("status", "violation_count", "input_content_hash", "rules_checked"):
            if committed["drc"][key] != fresh["drc"][key]:
                drifts.append(f"drc.{key}")
        for key in ("status", "device_count", "device_counts", "net_count", "pin_count_raw", "abstracted_cell_types", "abstracted_instances", "warning_count", "dead_metal"):
            if committed["extract"][key] != fresh["extract"][key]:
                drifts.append(f"extract.{key}")
        for key in ("status", "mismatch_count", "error_count", "counts", "layout_netlist_sha256", "reference_sha256", "warnings_reviewed"):
            if committed["lvs"][key] != fresh["lvs"][key]:
                drifts.append(f"lvs.{key}")
        if committed["coverage"] != fresh["coverage"]:
            drifts.append("coverage")
        cov_committed = load_json(VERIFY_DIR / "coverage.json")
        if cov_committed != b["coverage"]:
            drifts.append("coverage.json")
        if (VERIFY_DIR / "lvs.ref.spice").read_text() != b["ref_text"]:
            drifts.append("lvs.ref.spice")
        # the committed canonical netlist is only reproducible where klt's anonymous
        # $N numbering is: report, do not fail, on a raw-netlist hash difference
        note = []
        if committed["extract"]["raw_netlist_sha256"] != fresh["extract"]["raw_netlist_sha256"]:
            note.append("raw extracted netlist hash differs (anonymous $N numbering is not stable across hosts); "
                        "compared the structural fields instead")
    if drifts:
        print("DRIFT in: " + ", ".join(drifts))
        return 1
    print("verify-whole check: committed evidence reproduced" + (" (" + "; ".join(note) + ")" if note else ""))
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["run", "controls", "check", "all"])
    ap.add_argument("--klt", default=shutil.which("klt") or "klt")
    ap.add_argument("--allow-tool-drift", action="store_true")
    ap.add_argument("--only", action="append", help="run only this control id (repeatable)")
    ap.add_argument("--no-publish", action="store_true", help="run and report but write nothing under layout/ (debugging)")
    ap.add_argument("--workdir", help="keep scratch output here (debugging; not deleted)")
    ap.add_argument("--reuse-extract", action="store_true", help="reuse an extraction already in --workdir (debugging; refuses to publish)")
    args = ap.parse_args(argv)
    global REUSE
    REUSE = args.reuse_extract
    if args.reuse_extract and (not args.workdir or args.command != "run" or not args.no_publish):
        ap.error("--reuse-extract needs --workdir and only applies to `run --no-publish`")
    try:
        if args.command == "check":
            return check(args)
        import contextlib  # noqa: PLC0415

        ctx = contextlib.nullcontext(args.workdir) if args.workdir else tempfile.TemporaryDirectory(prefix="verify-whole-")
        with ctx as tmp:
            Path(tmp).mkdir(parents=True, exist_ok=True)
            b = build_baseline(args, Path(tmp))
            if args.command in ("run", "all"):
                if not args.no_publish:
                    publish_baseline(b)
                print(f"baseline: DRC {b['drc']['status']} ({b['drc']['violation_count']}), "
                      f"LVS {b['run']['lvs']['status']} ({b['run']['lvs']['error_count']} errors), "
                      f"{b['coverage']['ports_clean']}/{b['coverage']['ports']} ports clean")
            if args.command in ("controls", "all"):
                summary = run_controls(args, b)
                publish_controls(summary, b["pdk_root"])
                print(f"controls: all_detected={summary['all_detected']} baseline_rerun={summary['baseline_rerun_after_controls']['status']}")
                if not summary["all_detected"] or summary["baseline_rerun_after_controls"]["status"] != "match":
                    return 1
        return 0
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
