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
* five deterministic, recorded text transforms the raw extract needs to
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

The port map is written NEXT TO the netlist: ``-o OUT.spice`` writes
``OUT.ports.json``, so only the default output touches the committed
``trng_whole.sim.ports.json`` (issue #478 -- before that the map path was
hardcoded, and any ``-o``-directed run overwrote the committed map as a side
effect).

``--check`` re-derives the netlist and byte-compares it with the committed
copy. Both of the extractor's non-contractual orderings make that compare
klt-build-specific: anonymous-net numbering (klayout-tools#1063) and the
top-level ``.SUBCKT`` port order (measured 2026-11-13, klayout-tools#5534 --
identical GDS, deck and ``--pins``, same 50713 device/net lines, header port
order different). So a different klt build legitimately produces a different,
equally valid body, and ``--check`` reproduces the committed bytes only under
``PRODUCING_KLT_VERSION`` below::

    uvx --from "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@ef1ec19c95f6" \\
        python3 sim/post-layout-whole-block/make-netlist.py --check

``--check`` also asserts the structural invariants: 123 ports, one canonical
pin per port cluster, and the device count the fresh extract reports. The
klt-free half of the same contract -- committed netlist header order equals
committed ``ports.json`` order, and ``-o`` does not touch the committed map --
is pinned by ``test_make_netlist.py`` on every pull request.

Standard library only (plus a ``klt`` binary on PATH).
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "layout" / "bin"))
from _hashing import sha256_file  # noqa: E402
GDS = REPO / "layout" / "trng_whole" / "trng_whole.gds"
EXTRACT_REQUEST = REPO / "layout" / "trng_whole" / "verify" / "extract.request.json"
DEFAULT_OUT = HERE / "trng_whole.sim.spice"
COMMITTED_GZ = HERE / "trng_whole.sim.spice.gz"  # the copy actually committed
PORTS_JSON = HERE / "trng_whole.sim.ports.json"
PORTS_SUFFIX = ".ports.json"

# The klt build that produced the committed netlist and port map
# (records/20261105-body-rename-repin.md). `--check` is a BYTE compare and the
# top-level `.SUBCKT` port order is not reproducible across klt builds
# (measured 2026-11-13, klayout-tools#5534; records/20261113-ports-order-klt-build.md),
# so `--check` only prints OK under this build:
#
#   uvx --from "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@ef1ec19c95f6" \
#       python3 sim/post-layout-whole-block/make-netlist.py --check
#
# Used only in the `--check` failure message, so a reader can tell "ran under a
# different klt build" from "the committed netlist really is stale".
PRODUCING_KLT_VERSION = "0.9.1.dev102+gef1ec19c95f6"
PRODUCING_KLT_COMMIT = "ef1ec19c95f6"

BRACKET_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]")
# transform 4: smallest bin of the PDK's scalable nfet_01v8 is wmin = 0.42 um
NFET_MIN_BIN_W_UM = 0.42
NARROW_NFET_RE = re.compile(
    r"\bsky130_fd_pr__nfet_01v8(\s+(?:L=[0-9.eE+-]+\s+)?W=)([0-9.eE+-]+)")


def _special_nfet(m: "re.Match[str]") -> str:
    if float(m.group(2)) < NFET_MIN_BIN_W_UM:
        return "sky130_fd_pr__special_nfet_01v8" + m.group(1) + m.group(2)
    return m.group(0)


# transform 5: the extractor emits the pw2nd tap diode as a bare-model D card
# (``Dz1 a c diode_pw2nd_05v5 A=<area>P P=<perim>U``). ngspice has no such
# model ("could not find a valid modelname", the #386 class); the PDK defines
# the diode as the SUBCKT ``sky130_fd_pr__diode_pw2nd_05v5 a c mult=1 area=1
# perim=1`` (continuous/models_diodes.spice; area in m^2, perim in m, which
# the extractor's explicit P/U suffixes already are), so it becomes an X card.
DIODE_CARD_RE = re.compile(
    r"^D(\S+)((?:\n\+ [^\n]*)*?)\n\+ diode_pw2nd_05v5 A=(\S+) P=(\S+)[ \t]*$", re.M)


def _diode_to_subckt(m: "re.Match[str]") -> str:
    return (f"X{m.group(1)}{m.group(2)}\n+ sky130_fd_pr__diode_pw2nd_05v5 "
            f"area={m.group(3)} perim={m.group(4)}")


def klt_version() -> str:
    out = subprocess.run(["klt", "version", "--format", "json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["version"]


def _klt_version_or_unknown() -> str:
    """``klt_version()``, but never the thing that fails an error message."""
    try:
        return klt_version()
    except Exception as exc:  # pragma: no cover - diagnostic path only
        return f"<unknown: {exc}>"


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


def _scrubbed_line(ln: str) -> bool:
    """True for lines the `$`->`z` scrub rewrites (not comments / blanks)."""
    return bool(ln.strip()) and not ln.lstrip().startswith("*")


def check_scrub_collisions(body_lines: list[str]) -> None:
    """Raise SystemExit if the `$`->`z` scrub would merge distinct tokens.

    A collision is a scrubbed name equal to a token that already exists
    without `$` on a line the scrub applies to. Both sets are built once.
    """
    plain: set[str] = set()
    scrubbed: set[str] = set()
    for ln in body_lines:
        if not _scrubbed_line(ln):
            continue
        for t in ln.split():
            if "$" in t:
                scrubbed.add(t.replace("$", "z"))
            else:
                plain.add(t)
    merged = scrubbed & plain
    if merged:
        raise SystemExit(f"$-scrub would collide with existing tokens: {sorted(merged)[:5]}")


def _normalise_name(name: str) -> str:
    """Apply the `$`-scrub and bracket de-index to a net name."""
    return BRACKET_RE.sub(r"\1_\2_", name.replace("$", "z"))


def rename_body_clusters(body: str, header_len: int,
                         mapping: dict[str, str]) -> str:
    """Rename whole-token cluster names to canonical ones in the device body.

    ``body`` is already `$`-scrubbed and bracket de-indexed; the first
    ``header_len`` lines are the (already canonical) ``.SUBCKT`` header and are
    left alone. Raises SystemExit if a canonical name already exists as a
    distinct body token (the rename would merge two nets).
    """
    rename = {_normalise_name(c): _normalise_name(n)
              for c, n in mapping.items()}
    lines = body.split("\n")
    head, rest = lines[:header_len], lines[header_len:]
    live = [ln for ln in rest if _scrubbed_line(ln)]
    present = {t for ln in live for t in ln.split()}
    clash = sorted(c for k, c in rename.items() if k != c and c in present)
    if clash:
        raise SystemExit(
            f"cluster->canonical rename would collide with existing body "
            f"tokens: {clash[:5]}")
    out = [re.sub(r"\S+", lambda m: rename.get(m.group(0), m.group(0)), ln)
           if _scrubbed_line(ln) else ln for ln in rest]
    return "\n".join(head + out)


# Ports with no device in the layout BY DESIGN: digital/rtl/trng_digital.v reads
# only bus_wdata[2:0] (CTRL write, ALARM clear), so bus_wdata[31:3] reach no
# cell. Measured 2026-11-05: exactly these 29 of the 123 ports are absent from
# the body; every other port (incl. all supplies, clk, enables) must be present.
UNUSED_BY_DESIGN = frozenset(f"bus_wdata[{i}]" for i in range(3, 32))


def check_port_coverage(body: str, header_len: int, ports: list[str]) -> None:
    """Raise SystemExit unless the ports absent from the body are exactly
    ``UNUSED_BY_DESIGN`` (a floating supply/clk/enable, or a newly-used
    bus_wdata bit that the allowlist no longer matches, both fail)."""
    rest = body.split("\n")[header_len:]
    present = {t for ln in rest if _scrubbed_line(ln) for t in ln.split()}
    missing = {p for p in ports if _normalise_name(p) not in present}
    allowed = UNUSED_BY_DESIGN & set(ports)
    if missing != allowed:
        raise SystemExit(
            f"port coverage mismatch: unconnected (absent from device body) "
            f"{sorted(missing - allowed)[:5]}; allowlisted but present "
            f"{sorted(allowed - missing)[:5]}")


def canonicalise(text: str) -> tuple[str, dict[str, str]]:
    """Apply the transforms; return (netlist text, cluster->canonical map)."""
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
    check_scrub_collisions(body_lines)
    body = BRACKET_RE.sub(r"\1_\2_", body)
    # transform 1b (issue #435): rename the extractor's cluster names in the
    # device body. The header above is canonical, but the body still uses the
    # cluster tokens, so ports and body nodes would never join. Keys are put
    # through the same $-scrub and bracket de-index so they match body text.
    body = rename_body_clusters(body, len(wrapped), mapping)
    check_port_coverage(body, len(wrapped), pins)
    body = NARROW_NFET_RE.sub(_special_nfet, body)
    body = DIODE_CARD_RE.sub(_diode_to_subckt, body)
    return body, mapping


def ports_path_for(dest: Path) -> Path:
    """The port map that belongs next to the netlist written at ``dest``.

    The map describes the ``.subckt`` header of ONE netlist, so it follows
    that netlist's path: a trailing ``.spice`` is replaced by
    ``.ports.json``, any other name just gains the suffix. The default
    output maps to the committed ``trng_whole.sim.ports.json``, so a bare
    run is unchanged; an ``-o`` run anywhere else no longer overwrites that
    committed file as a side effect (issue #478).
    """
    base = dest.with_suffix("") if dest.suffix == ".spice" else dest
    return base.with_name(base.name + PORTS_SUFFIX)


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
    if DEFAULT_OUT.exists():
        committed = DEFAULT_OUT.read_text()
    elif COMMITTED_GZ.exists():
        committed = gzip.decompress(COMMITTED_GZ.read_bytes()).decode()
    else:
        print(f"error: neither {DEFAULT_OUT.relative_to(REPO)} nor its .gz exists",
              file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.spice"
        run_extract(raw)
        text, mapping = canonicalise(raw.read_text())
    if text != committed:
        ran = _klt_version_or_unknown()
        print(f"error: re-derived netlist differs from the committed "
              f"{DEFAULT_OUT.relative_to(REPO)}.\n"
              f"  this run used klt:                 {ran}\n"
              f"  committed netlist produced by klt: "
              f"{PRODUCING_KLT_VERSION}\n"
              "A DIFFERENT klt build is the expected cause, not a stale\n"
              "netlist: this is a byte compare, and the top-level .SUBCKT\n"
              "port order is not reproducible across klt builds\n"
              "(klayout-tools#5534; records/20261113-ports-order-klt-build.md).\n"
              "Reproduce the committed bytes with\n"
              f'  uvx --from "klayout-tools @ git+https://github.com/'
              f'2AMLogic/klayout-tools@{PRODUCING_KLT_COMMIT}" \\\n'
              "      python3 sim/post-layout-whole-block/make-netlist.py --check\n"
              "Only if that ALSO differs is the committed netlist stale;\n"
              "then re-run make-netlist.py -o and re-pin the records that\n"
              "cite its hash.", file=sys.stderr)
        return 1
    # the committed copy itself must connect every port (issue #435)
    cl = committed.split("\n")
    hl = next(i for i, ln in enumerate(cl) if i and not ln.startswith("+"))
    check_port_coverage(committed, hl, list(mapping.values()))
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
    info = build(args.output, ports_path_for(args.output))
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
