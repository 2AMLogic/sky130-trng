#!/usr/bin/env python3
"""Deterministic SPICE export of the xschem schematics in ``design/xschem/``.

    python3 design/netlist.py            # (re-)export every top cell
    python3 design/netlist.py --check    # export to a temp dir and diff; never writes
    python3 design/netlist.py --lint     # brace-in-T{} guard only; no xschem/PDK
    python3 design/netlist.py --pdk      # print the resolved PDK and exit

``--check`` verifies two independent things, both of which have to pass for
exit ``0``:

1. **Staleness** -- the committed ``.spice`` netlist matches what the
   current schematics produce. That is what makes a committed netlist
   evidence rather than a snapshot someone forgot to refresh -- an evidence
   record that names a ``netlist.sha`` is only meaningful if the netlist
   provably comes from the schematic it claims to.
2. **Connectivity** -- xschem's own ERC (electrical rule check,
   ``xschem netlist -erc``) finds no undriven node, open net, or shorted pin
   anywhere in each :data:`TOP_CELLS` entry's instantiated hierarchy. A
   schematic-level wiring defect (e.g. a label placed at the wrong
   coordinate relative to the net it is meant to tag) can produce a netlist
   that is *internally self-consistent* -- the "before" and "after" of a
   regeneration agree on the same wrong result -- so the staleness diff
   alone cannot catch it; a genuine connectivity check can (issue #16).

A connectivity failure is reported with an ``ERC`` print prefix and
:data:`EXIT_ERC`, distinct from a staleness failure's ``STALE`` prefix and
:data:`EXIT_STALE` -- see :class:`ErcViolation`. ERC only runs under
``--check`` (and under any direct ``export(..., erc=True)`` caller); the
default write path (``python3 design/netlist.py``, no flags) does not run
it, so a schematic that is intentionally mid-edit and not yet fully wired
can still be exported while iterating.

Ported from ``design/netlist.py`` in the sibling repo `2AMLogic/gf180-trng`,
whose structure (brace guard, deterministic path rewriting, continuation
re-wrapping) is reused unchanged in substance. What is adapted for sky130:

* PDK resolution targets a sky130 variant directory (``sky130A``) instead of
  a gf180mcu one, and is inlined here rather than imported from a simulation
  harness, because ``sim/`` in this repo is still empty. When a harness
  lands, this module should be repointed at its resolver rather than growing
  a second one.
* sky130's xschem symbol library lives at ``libs.tech/xschem`` and is
  addressed by sub-library path (``sky130_fd_pr/nfet_01v8.sym``), where
  gf180mcu's lives at ``libs.tech/xschem/symbols`` and is addressed by bare
  filename. The generated rc file appends the former.

Text-block brace guard
-----------------------
Every schematic carries one or more ``T {...}`` free-text elements -- the
prose headers that document each cell's rationale. That block has no
electrical meaning, but xschem's own line/element parser miscounts when the
block's *content* contains a literal ``{`` or ``}`` character, even a
balanced pair, and silently drops parts of the exported netlist with no
error from xschem or from this script. ``--lint`` (and every other
invocation of this script, which runs the same guard before shelling out to
xschem) scans every ``design/xschem/*.sch`` file's text directly for stray
braces inside ``T {...}`` blocks. That scan is pure Python over the
schematic's own text -- no xschem, no PDK -- so unlike ``--check`` it can run
in a PR-blocking CI job, catching the problem at the point of authorship.

Determinism
-----------
xschem writes absolute filesystem paths into the netlist header comments
(``** sch_path:``/``** sym_path:``) and resolves the PDK symbol library
through an rc file. Both are machine-specific, so this script:

* generates the xschem rc file itself, resolving the sky130 PDK through
  ``SKY130_PDK_PATH`` / ``PDK_ROOT`` + ``PDK`` / ``design/pdk.local.json`` /
  ``design/pdk.json`` / built-in search roots, so nothing here hardcodes a
  path; and
* rewrites every absolute path in the output to a repo-relative one; and
* re-wraps every SPICE continuation (``+``) line itself, at a width this
  file owns, instead of inheriting xschem's. Line *breaks* carry no circuit
  meaning -- a continuation is glued back on by any SPICE parser -- but they
  are the part of xschem's output that has actually moved between releases.
  Canonicalising the wrap here removes the whole class of difference, so the
  guard fires on circuit changes and only on circuit changes.

The result is byte-identical on any machine with the same PDK symbol set,
across xschem releases that differ only in line-wrapping. A change in what
xschem actually *emits* -- different tokens, different hierarchy -- still
makes ``--check`` say so loudly rather than letting the netlist and the
schematic drift apart silently.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DIR = REPO_ROOT / "design"
SCHEMATIC_DIR = DESIGN_DIR / "xschem"

#: Schematics exported as stand-alone netlists. Cells not listed here are
#: still netlisted, but only as subcircuits inside a top cell that uses them.
#:
#: A cell earns a place here when a testbench needs to instantiate it
#: directly, because an evidence record's ``netlist.path``/``netlist.sha``
#: should name the netlist that defines the DUT and nothing more. That is
#: why ``ro_ring5`` is exported separately: nothing in the shipped hierarchy
#: instantiates it, but it is the cheap transient-noise vehicle the jitter
#: characterization will drive directly, and a cell that no top cell pulls in
#: would otherwise fall outside the ``--check`` staleness guard entirely.
TOP_CELLS = (
    "ro_array_core",
    "ro_ring5",
    "sampler_core",
    "trng_top",
)

XSCHEM = "xschem"

#: Column at which this script re-wraps SPICE continuation lines. Any value
#: works as long as it is fixed here rather than inherited from xschem --
#: see the module docstring.
WRAP_COLUMN = 120

EXIT_OK = 0
EXIT_STALE = 1
EXIT_ERC = 2
EXIT_ENVIRONMENT = 3

DEFAULT_VARIANT = "sky130A"

#: Directories expected to *contain* sky130 variant directories.
BUILTIN_SEARCH_ROOTS = (
    "~/.volare",
    "~/.ciel",
    "/usr/share/pdk",
    "/usr/local/share/pdk",
    "~/share/pdk",
    "/opt/pdk",
)

INSTALL_HINT = """\
sky130 PDK not found.

Install it with volare (or ciel, its successor):

    pip install volare
    volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

That open_pdks commit is the one design/pdk.json pins and the one
spec/porting-plan.md was written against. volare installs into
~/.volare/<variant> and this script finds it there automatically.

If your PDK lives somewhere else, point this script at it:

    export SKY130_PDK_PATH=/path/to/sky130A     # variant dir, contains libs.tech/
    # or the conventional pair:
    export PDK_ROOT=/path/to/pdk-root
    export PDK=sky130A

...or commit-free machine-local config in design/pdk.local.json:

    {"variant": "sky130A", "search_roots": ["/my/pdks"]}
"""


class ExportError(RuntimeError):
    pass


class PdkNotFound(ExportError):
    """Raised when no usable sky130 install can be located."""


class ErcViolation(ExportError):
    """xschem's own ERC (electrical rule check) found a connectivity defect.

    A subclass of :class:`ExportError` so a caller that only wants "did the
    export fail" can still catch broadly, but distinct enough that
    ``main()`` can report it separately -- with its own exit code
    (:data:`EXIT_ERC`) and print prefix (``ERC``) -- from both a staleness
    diff (the committed netlist not matching a *correctly wired* schematic)
    and a plain environment failure (xschem/PDK missing, no schematic file).
    See the module docstring's "Connectivity, not just staleness" section.
    """


@dataclass(frozen=True)
class Pdk:
    """A located sky130 install."""

    path: Path      # .../sky130A
    variant: str    # sky130A
    source: str     # how we found it (for provenance)

    @property
    def symbol_dir(self) -> Path:
        """The xschem library root.

        sky130's open_pdks install puts ``xschemrc`` and the ``sky130_fd_pr/``
        symbol sub-library side by side under ``libs.tech/xschem``, and
        schematics address symbols as ``sky130_fd_pr/<device>.sym``. So the
        directory that goes on ``XSCHEM_LIBRARY_PATH`` is the parent, not the
        device directory -- the opposite of gf180mcu's flat
        ``libs.tech/xschem/symbols`` layout.
        """
        return self.path / "libs.tech" / "xschem"

    @property
    def version(self) -> str:
        """open_pdks commit recorded by volare/ciel, or ``unknown``."""
        sources = self.path / "SOURCES"
        if sources.is_file():
            for line in sources.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "open_pdks":
                    return parts[1]
            text = sources.read_text().strip()
            if text:
                return text.splitlines()[0]
        return "unknown"


def _load_config() -> dict:
    """``design/pdk.json`` overlaid by the git-ignored ``pdk.local.json``."""
    config: dict = {}
    for name in ("pdk.json", "pdk.local.json"):
        path = DESIGN_DIR / name
        if path.is_file():
            try:
                config.update(json.loads(path.read_text()))
            except json.JSONDecodeError as exc:
                raise ExportError(f"{path} is not valid JSON: {exc}") from exc
    return config


def _is_variant_dir(path: Path) -> bool:
    return (path / "libs.tech" / "xschem").is_dir()


def find_pdk() -> Pdk:
    """Locate a sky130 install. First hit wins:

    1. ``SKY130_PDK_PATH`` -- absolute path to the *variant* directory.
    2. ``PDK_ROOT`` (+ ``PDK``) -- the conventional open_pdks environment.
    3. ``design/pdk.local.json`` -- machine-local override, git-ignored.
    4. ``design/pdk.json`` -- committed defaults: variant + search roots.
    5. Built-in search roots -- volare/ciel stores, open_pdks prefixes.
    """
    config = _load_config()
    variant = os.environ.get("PDK") or config.get("variant") or DEFAULT_VARIANT

    explicit = os.environ.get("SKY130_PDK_PATH")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not _is_variant_dir(path):
            raise PdkNotFound(
                f"SKY130_PDK_PATH={explicit} has no libs.tech/xschem directory"
            )
        return Pdk(path=path, variant=path.name, source="SKY130_PDK_PATH")

    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        path = (Path(pdk_root).expanduser() / variant).resolve()
        if _is_variant_dir(path):
            return Pdk(path=path, variant=variant, source="PDK_ROOT")

    roots = list(config.get("search_roots") or ()) + list(BUILTIN_SEARCH_ROOTS)
    for root in roots:
        path = (Path(root).expanduser() / variant).resolve()
        if _is_variant_dir(path):
            return Pdk(path=path, variant=variant, source=str(root))

    raise PdkNotFound(INSTALL_HINT)


def _display_path(path: Path) -> str:
    """*path* relative to :data:`REPO_ROOT` when possible, else as given."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _text_block_violations(text: str) -> list[tuple[int, str]]:
    """Find stray braces inside every ``T {...}`` free-text block of *text*.

    Returns a list of ``(line_number, message)`` pairs, in document order.

    This walks the schematic's raw text with a simple brace-depth counter
    rather than trying to reproduce whatever xschem's own parser does --
    that parser is exactly what miscounts here. Depth starts at 1 right
    after a line-initial ``T {``; any ``{`` or ``}`` seen while depth is
    already >= 1 is, by construction, inside the block's content, so it is
    flagged unconditionally -- a balanced nested pair corrupts xschem's
    export just as surely as an unbalanced one, so this guard does not try
    to distinguish them.
    """
    violations: list[tuple[int, str]] = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        if text.startswith("T {", i) and (i == 0 or text[i - 1] == "\n"):
            block_start_line = line
            j = i + len("T {")
            depth = 1
            while j < n and depth > 0:
                ch = text[j]
                if ch == "\n":
                    line += 1
                if ch == "{":
                    depth += 1
                    if depth > 1:
                        violations.append((line, "stray '{' inside a T {...} text block"))
                elif ch == "}":
                    depth -= 1
                    if depth > 0:
                        violations.append((line, "stray '}' inside a T {...} text block"))
                j += 1
            if depth != 0:
                violations.append(
                    (block_start_line, "T {...} text block starting here never closes")
                )
            i = j
            continue
        if text[i] == "\n":
            line += 1
        i += 1
    return violations


def text_block_violations(schematic: Path) -> list[tuple[int, str]]:
    """``_text_block_violations`` over one schematic file's committed text."""
    return _text_block_violations(schematic.read_text())


def lint_schematics(paths: list[Path] | None = None) -> int:
    """Fail loudly if any schematic has a stray brace in a ``T {...}`` block.

    Pure Python over the schematics' own text: no xschem, no PDK. *paths*
    defaults to every ``design/xschem/*.sch`` file.
    """
    status = EXIT_OK
    for schematic in paths if paths is not None else sorted(SCHEMATIC_DIR.glob("*.sch")):
        rel = _display_path(schematic)
        for lineno, message in text_block_violations(schematic):
            print(f"BRACE  {rel}:{lineno}: {message}")
            status = EXIT_STALE
    if status == EXIT_OK:
        print(f"ok     no stray braces in any T {{...}} text block under {_display_path(SCHEMATIC_DIR)}")
    return status


def _write_rcfile(target: Path, symbol_dir: Path, netlist_dir: Path) -> None:
    target.write_text(
        "# generated by design/netlist.py -- do not edit, do not commit\n"
        "set XSCHEM_LIBRARY_PATH {}\n"
        "append XSCHEM_LIBRARY_PATH :${XSCHEM_SHAREDIR}/xschem_library/devices\n"
        f"append XSCHEM_LIBRARY_PATH :{symbol_dir}\n"
        f"append XSCHEM_LIBRARY_PATH :{SCHEMATIC_DIR}\n"
        f"set netlist_dir {netlist_dir}\n"
        "set netlist_type spice\n"
        "set hspice_netlist 0\n"
    )


def _tokens(line: str) -> list[str]:
    """Split a SPICE line on whitespace, keeping quoted expressions whole.

    ``ad='int((1 + 1)/2) * wstv / 1 * 0.29'`` is one token even though it
    contains spaces: breaking a line inside it would produce a netlist that
    no longer parses.
    """
    out: list[str] = []
    current: list[str] = []
    quote = ""
    for char in line:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char.isspace():
            if current:
                out.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        out.append("".join(current))
    return out


def _rewrap(line: str) -> list[str]:
    """Re-wrap one logical SPICE line at :data:`WRAP_COLUMN`.

    Greedy, and deliberately so: the rule has to be reproducible by reading
    this function, not by matching a particular xschem release's output.
    A token longer than the column is emitted on its own line rather than
    split, because splitting it would change the netlist.
    """
    tokens = _tokens(line)
    if not tokens:
        return [line]
    wrapped: list[str] = []
    current = tokens[0]
    for token in tokens[1:]:
        candidate = f"{current} {token}"
        if len(candidate) <= WRAP_COLUMN:
            current = candidate
            continue
        wrapped.append(current)
        current = f"+ {token}"
    wrapped.append(current)
    return wrapped


def _join_continuations(lines: list[str]) -> list[str]:
    """Glue ``+`` continuation lines back onto the line they continue."""
    joined: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("+") and joined:
            joined[-1] = f"{joined[-1]} {stripped[1:].strip()}".rstrip()
        else:
            joined.append(line)
    return joined


def _schematic_params(schematic: Path) -> str:
    """The top schematic's own parameter block (the xschem ``G {...}`` line).

    xschem treats a top schematic as a deck, so it drops that block from the
    ``.subckt`` line it comments out -- which leaves a parameterised top cell
    exporting instance lines that reference names nothing declares.
    Restoring the block alongside the ``.subckt`` wrapper is the same fix,
    for the same reason: here the top cell IS a cell, and a testbench needs
    to override its parameters.
    """
    text = schematic.read_text()
    match = re.search(r"^G \{(.*?)\}\s*$", text, re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    return " ".join(match.group(1).split())


def _normalize(text: str, top_params: str = "") -> str:
    """Make the netlist machine-independent and stable line-for-line."""
    out = []
    #: True while walking the commented-out top ``.subckt`` header, so its
    #: ``*+`` continuation lines get un-commented along with the head. xschem
    #: wraps a long pin list, and it prefixes the wrapped lines with the same
    #: ``*`` it used to comment the header out -- so a top cell with enough
    #: pins to wrap emitted ``.subckt <name> <first pins>`` followed by a
    #: still-commented ``*+ <remaining pins>``, silently dropping those pins
    #: from the restored declaration while every instance line kept passing
    #: them. Nothing downstream noticed: ``--check`` compares the regenerated
    #: netlist against the committed one, so a consistently wrong netlist
    #: passes it. Found when ro_array_core went from 9 pins to 28 (issue #13).
    restoring_top_subckt = False
    top_name = ""
    for line in text.splitlines():
        # xschem stamps absolute paths into header comments.
        line = re.sub(r"(?<=[ :])/[^\s]*/(?=[^/\s]+\.(?:sch|sym))", "", line)
        line = line.replace(str(REPO_ROOT) + "/", "")
        # The export is a library of subcircuits that a testbench deck
        # `.include`s, not a deck of its own: a bare `.end` would truncate
        # every deck that includes it. `.ends` is kept, obviously.
        if line.strip().lower() == ".end":
            continue
        # xschem comments out the TOP cell's own .subckt/.ends wrapper,
        # because from its point of view the top schematic is a deck rather
        # than a cell. Here the top cell is exactly what a testbench wants
        # to instantiate, so the wrapper is restored. Every lower-level cell
        # is already emitted uncommented and is untouched by this.
        if line.startswith("**.subckt "):
            line = line[2:]
            restoring_top_subckt = True
            parts = line.split()
            top_name = parts[1] if len(parts) > 1 else ""
        elif restoring_top_subckt and line.startswith("*+"):
            line = line[1:]
        else:
            restoring_top_subckt = False
            if line.strip() == "**.ends":
                line = line[2:]
        out.append(line.rstrip())
    while out and not out[-1]:
        out.pop()
    # The parameter block is appended AFTER continuations are glued back
    # together, so it lands at the end of the whole logical `.subckt` line
    # rather than in the middle of the pin list. A cell cannot instantiate
    # itself, so `.subckt <top_name>` occurs exactly once.
    joined = _join_continuations(out)
    if top_params and top_name:
        head = f".subckt {top_name} "
        joined = [
            f"{line} {top_params}" if line.startswith(head) else line
            for line in joined
        ]
    reflowed: list[str] = []
    for line in joined:
        if line.startswith("*") or not line.strip():
            reflowed.append(line)
        else:
            reflowed.extend(_rewrap(line))
    text_out = "\n".join(reflowed) + "\n"
    # Structural guard, not a style check: a surviving `*+` is a continuation
    # of some line this normalizer decided was a comment while xschem meant it
    # as circuit text. That is exactly the failure above, and it is invisible
    # to --check (which only compares regenerated against committed), so it is
    # asserted here where it is cheap and certain.
    stray = [ln for ln in reflowed if ln.startswith("*+")]
    if stray:
        raise ExportError(
            "normalized netlist still contains a commented continuation line, "
            "which means pins or devices were dropped from a restored "
            f"declaration:\n  " + "\n  ".join(stray)
        )
    return text_out


def export(top: str, outdir: Path, *, erc: bool = False) -> str:
    """Export *top* to *outdir*/*top*.spice and return the normalized text.

    If *erc* is set, xschem's own ERC (electrical rule check) runs in the
    same batch-mode invocation (``--command "xschem netlist -erc"`` --
    the same Tcl call the GUI's Netlist toolbar button uses) and a nonzero
    xschem exit status raises :class:`ErcViolation` instead of returning a
    netlist. ERC walks *top*'s full instantiated hierarchy, so running it
    only on a handful of top cells (as ``--check`` does, over
    :data:`TOP_CELLS`) still covers every schematic those cells pull in.

    *erc* defaults to off because the default write path
    (``python3 design/netlist.py``, no flags) is also used mid-edit, on a
    schematic that is intentionally incomplete -- ERC failing there would
    make the plain export command unusable while iterating. ``--check``
    passes ``erc=True`` explicitly; see ``main()``.
    """
    schematic = SCHEMATIC_DIR / f"{top}.sch"
    if not schematic.is_file():
        raise ExportError(f"no schematic {schematic}")
    # Refuse before ever invoking xschem: a stray brace in any schematic's
    # T {...} block corrupts xschem's own parse silently, and `top`'s export
    # can pull in any other schematic in SCHEMATIC_DIR hierarchically, so the
    # whole directory is in scope here, not just `top`.sch.
    violations = [
        (sch, lineno, message)
        for sch in sorted(SCHEMATIC_DIR.glob("*.sch"))
        for lineno, message in text_block_violations(sch)
    ]
    if violations:
        detail = "\n".join(
            f"  {_display_path(sch)}:{lineno}: {message}" for sch, lineno, message in violations
        )
        raise ExportError(
            "stray brace(s) found in a T {...} text block -- xschem's own "
            "parser miscounts these and silently corrupts the exported "
            f"netlist; run `python3 design/netlist.py --lint` for detail:\n{detail}"
        )
    if shutil.which(XSCHEM) is None:
        raise ExportError(
            "xschem not found on PATH.\n"
            "  Debian/Ubuntu: apt-get install xschem\n"
            "  or build from https://github.com/StefanSchippers/xschem"
        )
    pdk = find_pdk()
    symbols = pdk.symbol_dir
    if not symbols.is_dir():
        raise ExportError(
            f"{pdk.path} has no libs.tech/xschem directory -- this PDK "
            "install does not carry the xschem symbol library"
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        rcfile = tmpdir / "xschemrc"
        _write_rcfile(rcfile, symbols, tmpdir)
        env = dict(os.environ)
        env.pop("XSCHEM_LIBRARY_PATH", None)
        cmd = [
            XSCHEM, "-n", "-q", "-x", "-s", "-r",
            "--rcfile", str(rcfile),
            "-o", str(tmpdir),
            "-N", f"{top}.spice",
        ]
        if erc:
            # The same Tcl call xschem's own GUI "Netlist" toolbar button
            # runs. Appending it to the same batch-mode invocation walks
            # ERC over *top*'s full instantiated hierarchy -- no second
            # xschem invocation, no new flags.
            cmd += ["--command", "xschem netlist -erc"]
        cmd.append(str(schematic))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=tmpdir,
            env=env,
            check=False,
        )
        produced = tmpdir / f"{top}.spice"
        if not produced.is_file():
            raise ExportError(
                f"xschem produced no netlist for {top}\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
            )
        if erc and proc.returncode != 0:
            # xschem still writes the (electrically broken) netlist file
            # even when ERC fails, so the `produced.is_file()` check above
            # does not catch this -- the signal is the exit code, not
            # whether a file landed. Every violation class observed so far
            # (undriven node, at minimum) reports on stderr, so surface
            # whichever stream has content.
            detail = (proc.stderr or proc.stdout or "").strip()
            raise ErcViolation(
                f"xschem ERC failed for {top} (exit {proc.returncode}) -- "
                "the schematic has a connectivity defect (e.g. an undriven "
                "node, open net, or shorted pin), not merely a stale "
                f"netlist:\n{detail}"
            )
        text = _normalize(produced.read_text(), _schematic_params(schematic))
    header = (
        f"* {top} -- GENERATED by design/netlist.py from design/xschem/{top}.sch\n"
        "* Do not edit by hand: `python3 design/netlist.py --check` fails if this\n"
        "* file and the schematic disagree. Regenerate with `python3 design/netlist.py`.\n"
    )
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{top}.spice").write_text(header + text)
    return header + text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="netlist.py",
        description="Export (or verify) the SPICE netlists of design/xschem/.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help=(
            "do not write: re-export and fail if the committed netlist is "
            "stale, or if xschem's own ERC finds a connectivity defect"
        ),
    )
    parser.add_argument(
        "--lint", action="store_true",
        help=(
            "only run the T {...} text-block brace guard over every schematic "
            "and exit; needs neither xschem nor the PDK"
        ),
    )
    parser.add_argument(
        "--pdk", action="store_true",
        help="print the resolved sky130 install and its open_pdks commit, then exit",
    )
    parser.add_argument("--top", action="append", metavar="CELL", help="cell to export (repeatable)")
    args = parser.parse_args(argv)

    if args.lint:
        return lint_schematics()

    if args.pdk:
        try:
            pdk = find_pdk()
        except ExportError as exc:
            print(f"ERROR  {exc}", file=sys.stderr)
            return EXIT_ENVIRONMENT
        pinned = (_load_config().get("open_pdks_commit") or "").strip()
        print(f"path      {pdk.path}")
        print(f"variant   {pdk.variant}")
        print(f"source    {pdk.source}")
        print(f"open_pdks {pdk.version}")
        if pinned:
            match = "matches" if pdk.version == pinned else "DIFFERS FROM"
            print(f"pin       {pinned} ({match} the installed PDK)")
        return EXIT_OK

    tops = tuple(args.top) if args.top else TOP_CELLS
    status = EXIT_OK
    erc_failed = False
    for top in tops:
        committed = DESIGN_DIR / f"{top}.spice"
        try:
            if args.check:
                # erc=True: --check verifies connectivity as well as
                # staleness -- see the module docstring and ErcViolation.
                with tempfile.TemporaryDirectory() as tmp:
                    fresh = export(top, Path(tmp), erc=True)
                if not committed.is_file():
                    print(f"STALE  {top}: {committed.relative_to(REPO_ROOT)} does not exist")
                    status = EXIT_STALE
                    continue
                current = committed.read_text()
                if current != fresh:
                    diff = difflib.unified_diff(
                        current.splitlines(True), fresh.splitlines(True),
                        fromfile=f"committed/{top}.spice", tofile=f"regenerated/{top}.spice",
                    )
                    print(f"STALE  {top}: committed netlist does not match the schematic")
                    sys.stdout.writelines(diff)
                    status = EXIT_STALE
                else:
                    print(f"ok     {top}: committed netlist matches design/xschem/{top}.sch (ERC clean)")
            else:
                export(top, DESIGN_DIR)
                print(f"wrote  design/{top}.spice")
        except ErcViolation as exc:
            # Distinct from STALE: this is a wiring defect in the
            # schematic, not a committed netlist that fell out of sync with
            # an otherwise-correct one. Keep checking the remaining tops
            # rather than aborting, same as a STALE finding does, so one CI
            # run reports every offending cell.
            print(f"ERC    {top}: {exc}", file=sys.stderr)
            erc_failed = True
        except ExportError as exc:
            print(f"ERROR  {top}: {exc}", file=sys.stderr)
            return EXIT_ENVIRONMENT
    if erc_failed:
        return EXIT_ERC
    return status


if __name__ == "__main__":
    raise SystemExit(main())
