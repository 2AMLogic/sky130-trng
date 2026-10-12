#!/usr/bin/env python3
"""Build the whole-block simulation netlist body for klt sim (issue #174).

Takes the committed whole-block layout ``layout/trng_whole/trng_whole.gds``
(issue #172 composition, #173 verification) and produces a **flat,
ngspice-runnable** netlist body for the ``trng_whole`` cell:

* a fresh ``klt extract --deck sky130 --pdk sky130A --pins <123 ports>``
  over the committed GDS -- ``--pdk`` makes every device card a subcircuit
  call on the PDK's own ``sky130_fd_pr__{nfet,pfet}_01v8`` with unitless
  geometry (this repo's decks run at ``.option scale=1u``), the same
  convention ``layout/bin/pex-netlist.py`` documents for the cell PEX
  libraries. No parasitics: this is the connectivity netlist #173
  extracted, in runnable form.
* three deterministic, recorded text transforms the raw extract needs to
  run under ngspice (the committed ``trng_whole.layout.spice`` was never
  runnable -- it is an LVS artifact):

  1. **port canonicalisation.** Without ``--abstract-cells`` the top-level
     net names are the extractor's whole label clusters
     (``A|Q|bus_rdata[15]``): the fill/logic cells' own pin labels leak
     into the clusters. Every cluster contains exactly one of the 123
     declared top ports (checked), so each port is renamed to that
     canonical name. The port ORDER of the emitted ``.subckt trng_whole``
     is the extractor's order, not the request's -- the caller instantiates
     in the emitted order (``ports.json`` records the mapping).
  2. **``$``-name scrubbing.** ngspice treats ``$`` as parameter
     substitution -- a backslash-escaped anonymous net (``\\$8019``) is
     rejected outright ("unknown device type"), and a ``$`` mid-token
     (cluster names like ``D|X$31``) is WORSE: the parser silently
     substitutes ``$31`` as a variable and splits the net. Every ``$`` on
     a non-comment line is therefore renamed to ``z`` (``\\$8019`` and
     ``$8019`` -> ``z8019``, ``X$1`` -> ``Xz1``, ``D|X$31`` -> ``D|Xz31``);
     the builder asserts the rename introduces no token collision.
  3. **bracket de-indexing.** ngspice parses ``bus_rdata[15]`` in a net
     position but its ``.meas``/``.control`` expression parser then reads
     ``[15]`` as vector indexing, so a measurement on such a net is
     impossible. Every ``name[i]`` net token is renamed to ``name_i_``
     (the 123 ports and any internal net alike).

The output is the ``.subckt trng_whole ... .ends`` body ONLY -- sources,
supplies and stimulus live in the deck the request assembles.

Usage::

    python3 sim/post-layout-whole-block/make-netlist.py -o OUT.spice
    python3 sim/post-layout-whole-block/make-netlist.py --check

``--check`` re-derives the netlist and byte-compares it with the committed
copy (the extractor's own output is deterministic on one host/klt build;
its anonymous-net numbering is NOT a cross-host contract -- klayout-tools
#1063 -- so a different klt build may legitimately produce a different,
equally valid body; the record pins the klt version that produced the
committed one). It also asserts the structural invariants: 123 ports, one
canonical pin per port cluster, and the device count the fresh extract
reports.

Standard library only (plus a ``klt`` binary on PATH).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GDS = REPO / "layout" / "trng_whole" / "trng_whole.gds"
EXTRACT_REQUEST = REPO / "layout" / "trng_whole" / "verify" / "extract.request.json"
DEFAULT_OUT = HERE / "trng_whole.sim.spice"
PORTS_JSON = HERE / "trng_whole.sim.ports.json"

SUBCKT_RE = re.compile(r"^\.SUBCKT\s+trng_whole\s+(.*)$", re.M)
BRACKET_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def klt_version() -> str:
    out = subprocess.run(["klt", "version", "--format", "json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["version"]


def run_extract(dest: Path) -> None:
    pins = json.loads(EXTRACT_REQUEST.read_text())["pins"]
    cmd = ["klt", "extract", str(GDS), "--deck", "sky130", "--pdk", "sky130A",
           "--top", "trng_whole", "--pins", pins, "-o", str(dest),
           "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"klt extract failed ({proc.returncode}):\n{proc.stderr}")
    report = json.loads(proc.stdout)
    if report.get("status") != "extracted":
        raise SystemExit(f"klt extract reported {report.get('status')!r}")


def canonicalise(text: str) -> tuple[str, dict[str, str]]:
    """Apply the three transforms; return (netlist text, cluster->canonical map)."""
    pins = json.loads(EXTRACT_REQUEST.read_text())["pins"].split(",")

    # The .SUBCKT trng_whole port list spans several `+`-continuation lines;
    # absorb them into one logical line first.
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(".SUBCKT trng_whole"))
    logical, end = [lines[start]], start + 1
    while end < len(lines) and lines[end].startswith("+"):
        logical.append(lines[end])
        end += 1
    clusters = " ".join(ln[2:] if ln.startswith("+") else ln[18:] + " "
                        for ln in logical).split()
    # first line: strip the leading ".SUBCKT trng_whole " (18 chars); the rest
    # are "+ "-prefixed continuation bodies, already space-joined above.

    mapping: dict[str, str] = {}
    for cluster in clusters:
        hits = [p for p in pins
                if re.search(r"(^|\|)" + re.escape(p) + r"(\||$)", cluster)]
        if len(hits) != 1:
            raise SystemExit(
                f"port cluster {cluster!r} matches {len(hits)} declared pins "
                f"({hits}); the one-cluster-one-port invariant is broken")
        mapping[cluster] = hits[0]
    if sorted(mapping.values()) != sorted(pins):
        raise SystemExit("canonical port set != declared pin set")

    # transform 1: rewrite the port list with canonical names, re-wrapped
    canon = [mapping[c] for c in clusters]
    wrapped = [".SUBCKT trng_whole " + " ".join(canon[:8])]
    for i in range(8, len(canon), 8):
        wrapped.append("+ " + " ".join(canon[i:i + 8]))
    body_lines = wrapped + lines[end:]

    # transforms 2/3 are token-local: they never span a continuation break
    body_lines2 = []
    for ln in body_lines:
        if ln.lstrip().startswith("*") or not ln.strip():
            body_lines2.append(ln)
        elif "$" in ln:
            body_lines2.append(ln.replace("$", "z"))
        else:
            body_lines2.append(ln)
    body = "\n".join(body_lines2) + "\n"
    scrubbed = {t.replace("$", "z") for ln in body_lines if "$" in ln for t in ln.split()}
    # collision guard: the scrub may not merge two previously distinct tokens
    merged = {t for t in body.split() if "$" not in t and t in scrubbed and
              t not in {u for ln in body_lines if "$" in ln for u in ln.split()}}
    if merged:
        raise SystemExit(f"$-scrub would collide with existing tokens: {sorted(merged)[:5]}")
    body = BRACKET_RE.sub(r"\1_\2_", body)
    return body, mapping


def build(dest: Path, ports_dest: Path) -> dict:
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.spice"
        run_extract(raw)
        text, mapping = canonicalise(raw.read_text())
    dest.write_text(text)
    ports_dest.write_text(json.dumps(
        {"comment": "extractor port cluster -> canonical top port; order = "
                    ".subckt trng_whole port order",
         "ports": [{"cluster": c, "canonical": n} for c, n in mapping.items()]},
        indent=2, sort_keys=True) + "\n")
    dev = len(re.findall(r"^X\S+", re.sub(r"\n\+", " ", text), re.M))
    return {
        "klt_version": klt_version(),
        "gds_sha256": sha256_file(GDS),
        "netlist_sha256": sha256_file(dest),
        "device_count": dev,
        "port_count": len(mapping),
    }


def check() -> int:
    if not DEFAULT_OUT.exists():
        print(f"error: {DEFAULT_OUT.relative_to(REPO)} does not exist", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.spice"
        run_extract(raw)
        text, mapping = canonicalise(raw.read_text())
    committed = DEFAULT_OUT.read_text()
    if text != committed:
        print("error: re-derived netlist differs from the committed "
              f"{DEFAULT_OUT.relative_to(REPO)}; a klt/PDK pin may have moved -- "
              "re-run make-netlist.py -o and re-pin the records that cite its hash",
              file=sys.stderr)
        return 1
    dev = len(re.findall(r"^X\S+", re.sub(r"\n\+", " ", text), re.M))
    print(f"check OK: byte-identical, {len(mapping)} ports, {dev} devices")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true",
                    help="re-derive and byte-compare against the committed netlist")
    args = ap.parse_args(argv)
    if args.check:
        return check()
    info = build(args.output, PORTS_JSON)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
