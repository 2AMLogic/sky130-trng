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
2. **Connectivity** -- xschem's own ERC (electrical rule check, reached
   here via ``klt netlist --erc``) finds no undriven node, open net, or shorted pin
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
  a gf180mcu one. The walk-a-list-of-roots search itself is shared with
  ``sim/bin/corner-run.py`` via ``design/_pdk_search.py`` (issue #25);
  ``find_pdk()`` below supplies only this tool's validator predicate
  (``libs.tech/xschem``) and config source (``design/pdk.json`` /
  ``design/pdk.local.json``). ``sim/`` has its own independent resolver by
  design (see ``sim/pdk.json`` and ``sim/bin/corner-run.py``), so the two
  intentionally don't share a config source.
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

Minimum xschem version
----------------------
Determinism above handles *formatting* drift between xschem releases. One
difference is not formatting, and is not negotiable: sky130's device symbols
carry their device-area parameters as ``expr()`` templates over the symbol's
own ``@W``/``@nf`` attributes (``ad=expr('int((@nf + 2)/2) * @W / @nf *
0.29')``). xschem **3.4.7** is the first release that evaluates those
templates at netlist time; every earlier release copies them through
verbatim, ``@``-attributes and all, producing a netlist ngspice rejects
outright (``Undefined parameter [ad]`` / ``Cannot compute substitute`` /
``ERROR: fatal error in ngspice, exit(1)``).

``--check`` alone cannot catch that: it verifies staleness and ERC, never
simulability, so an unsimulable netlist regenerated by a too-old xschem
would diff clean against itself and pass. Since every ``design/*.spice`` is
``.include``d by testbenches under ``sim/``, the failure would surface only
as a broken simulation much later. So this module treats
``design/pdk.json``'s ``xschem_version_min`` as a **hard gate**: too old and
:func:`export` raises :class:`ExportError` (exit :data:`EXIT_ENVIRONMENT`)
before xschem is ever asked for a netlist, naming the reason. It is a
minimum, not an equality pin -- a *newer* xschem that reformats its output
is still meant to turn ``--check`` red, with "regenerate and commit the
diff" still the right remedy for that direction. See ``design/pdk.json``'s
own comment block and issue #151.

Who runs xschem
---------------
This module does not spawn ``xschem`` to netlist. It shells out to ``klt
netlist`` (klayout-tools), which owns that invocation: it always forces
``-n -s -q -x -r`` and bounds the run, escalating SIGTERM to SIGKILL across
the whole process group when :data:`NETLIST_TIMEOUT_S` is exceeded. The
flags matter more than they look -- dropping ``-x`` does not fail, it makes
xschem initialise its GUI, write a plausible-looking netlist and then hang
in the Tk event loop, where it can stop responding to SIGTERM. A hand-rolled
call therefore fails as an idle process and a stale artifact rather than as
an error, which is what this module used to do, with no timeout at all.

``klt netlist`` is a **replacement for the xschem invocation only**, not for
the post-processing below it. Measured on all four :data:`TOP_CELLS`, klt's
raw output does not reproduce the committed netlists under any combination
of its flags (``--block``, and even the unreleased ``--relative-paths`` /
``--no-provenance-header``, still leave 17-45 differing lines per cell:
different continuation wrap points, repo-relative instead of bare schematic
paths, and a top ``.subckt`` line without the top schematic's own parameter
block). So :func:`_normalize` and its helpers stay exactly as they were, and
run on klt's output. The one thing that is dropped first is klt's own
``** klt-netlist-inputs:`` provenance comment -- see
:func:`_strip_klt_provenance`. Each gap is filed upstream as generic tool
friction and indexed in ``docs/friction-ledger.md``:

* ``klayout-tools#5085`` -- no opt-out for the ``** klt-netlist-inputs:``
  line. Closed upstream, but the ``--no-provenance-header`` flag that closes
  it is not in a tagged release yet, so :func:`_strip_klt_provenance` is
  still needed here.
* ``klayout-tools#4091`` -- the ``** sch_path:``/``** sym_path:`` stamps are
  absolute, so a committed netlist differs between checkouts. Still open.
* ``klayout-tools#3324`` -- ``--check`` cannot gate a netlist whose
  ``.subckt`` wrapper and line wrapping a project normalises. Closed by
  ``--block``, which this module does not use, because of:
* ``klayout-tools#5439`` -- ``--block`` restores the ``.subckt`` line
  without the top schematic's own parameter block, so the emitted block
  references parameters it never declares. :func:`_schematic_params`
  restores them here instead.

Because klt owns the run, its failures are classified by the structured
``--format json`` report rather than by an exit status: every failure exits
1, and only ``error.code == "erc_findings"`` is a connectivity defect. A
timeout, an unresolved symbol or a missing PDK carries no such code and is
raised as :class:`ExportError` (exit :data:`EXIT_ENVIRONMENT`), so a wedged
tool is never reported as a ``STALE`` netlist or an ERC finding. ``klt
netlist --erc`` first ships in klayout-tools 0.9.1, which is why
``design/pdk.json`` carries a ``klt_version_min`` floor beside the xschem
one -- see :func:`check_klt_version`.
"""

from __future__ import annotations

import argparse
import difflib
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pdk_search import (  # noqa: E402
    BUILTIN_SEARCH_ROOTS,
    PdkSearchError,
    read_open_pdks_commit,
    search_pdk,
)

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

#: The klayout-tools CLI. This module never spawns ``xschem`` itself: the
#: netlist run goes through ``klt netlist``, which owns the xschem
#: invocation (it always forces ``-n -s -q -x -r``, and bounds the run with
#: an escalated SIGTERM -> SIGKILL over the whole process group). Omitting
#: ``-x`` does not fail loudly -- xschem brings up its GUI, writes a
#: plausible-looking netlist and then hangs in the Tk event loop, where it
#: can stop responding to SIGTERM -- so a hand-rolled invocation's failure
#: mode is an idle process and a stale artifact, with no timeout at all.
#: Letting klt own it is the host rule, and it is why the bound below exists.
KLT = "klt"

#: Fallback for ``design/pdk.json``'s ``klt_version_min`` when the config
#: file does not carry one. 0.9.1 is the first tagged klayout-tools release
#: whose ``klt netlist`` has ``--erc``, which ``--check`` requires.
DEFAULT_KLT_VERSION_MIN = "0.9.1"

#: ``klt --version`` prints e.g. ``klt 0.9.1``. The numeric release prefix is
#: all that is captured, so a development build (``0.9.2.dev887+gec7400b``)
#: compares as ``0.9.2`` rather than failing to parse.
_KLT_VERSION_RE = re.compile(r"klt\s+v?(\d+(?:\.\d+)*)", re.IGNORECASE)

#: Wall-clock bound handed to ``klt netlist --timeout-s``. A real batch
#: netlist of the largest top cell here takes well under a second; this is
#: the hang guard, not a work budget, so it is generous. Exceeding it is an
#: export failure naming the cell -- never a STALE verdict (which would
#: blame the schematic for a wedged tool) and never an ERC verdict.
NETLIST_TIMEOUT_S = 120

#: Fallback for ``design/pdk.json``'s ``xschem_version_min`` when the config
#: file does not carry one. 3.4.7 is the first xschem release that evaluates
#: ``expr(...)`` device-parameter templates -- see the module docstring's
#: "Minimum xschem version" section for why anything older is unusable here
#: rather than merely differently formatted.
DEFAULT_XSCHEM_VERSION_MIN = "3.4.7"

#: ``xschem --version`` prints e.g. ``XSCHEM V3.4.7`` on its first line.
_XSCHEM_VERSION_RE = re.compile(r"XSCHEM\s+V?(\d+(?:\.\d+)*)", re.IGNORECASE)

#: Column at which this script re-wraps SPICE continuation lines. Any value
#: works as long as it is fixed here rather than inherited from xschem --
#: see the module docstring.
WRAP_COLUMN = 120

EXIT_OK = 0
EXIT_STALE = 1
EXIT_ERC = 2
EXIT_ENVIRONMENT = 3

DEFAULT_VARIANT = "sky130A"

#: sky130's xschem symbol library layout; the validator predicate this
#: module's ``find_pdk()`` hands to the shared search (see
#: ``design/_pdk_search.py``).
_VARIANT_DIR_LABEL = "libs.tech/xschem directory"

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
        """open_pdks commit recorded by volare/ciel, or ``unknown``.

        Delegates to ``design/_pdk_search.py``'s
        :func:`read_open_pdks_commit`, shared with
        ``sim/bin/corner-run.py``'s ``Pdk.installed_commit`` (issue #62).
        """
        return read_open_pdks_commit(self.path)


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


def _version_tuple(text: str) -> tuple[int, ...]:
    """``"3.4.7"`` -> ``(3, 4, 7)``, for ordering comparisons."""
    return tuple(int(part) for part in text.split("."))


@functools.lru_cache(maxsize=1)
def xschem_version() -> str | None:
    """Version reported by the ``xschem`` on PATH, or ``None`` if unreadable.

    ``None`` covers "no xschem on PATH", "it would not run", and "it ran but
    printed nothing matching :data:`_XSCHEM_VERSION_RE`". Callers treat all
    three the same way, because none of them can establish that the
    netlister meets :func:`xschem_version_min`.
    """
    exe = shutil.which(XSCHEM)
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _XSCHEM_VERSION_RE.search(f"{proc.stdout}\n{proc.stderr}")
    return match.group(1) if match else None


def xschem_version_min() -> str:
    """``design/pdk.json``'s ``xschem_version_min``, or the built-in default."""
    configured = _load_config().get("xschem_version_min")
    return str(configured).strip() if configured else DEFAULT_XSCHEM_VERSION_MIN


def check_xschem_version() -> None:
    """Raise :class:`ExportError` unless PATH's xschem meets the floor.

    A hard gate, deliberately, and the one place this module refuses to
    proceed on a *tool* version rather than reporting a diff. See the module
    docstring's "Minimum xschem version" section and ``design/pdk.json``'s
    comment block: below 3.4.7, xschem emits sky130's device-area
    ``expr(...)`` templates unevaluated, and the resulting netlist is not
    merely formatted differently, it is one ngspice refuses to run. Running
    that export to completion would either overwrite the committed netlists
    with unsimulable ones (write path) or report four unattributable
    ``STALE`` diffs (``--check``); saying so up front does neither.
    """
    floor = xschem_version_min()
    found = xschem_version()
    hint = (
        f"\n  design/pdk.json pins xschem_version_min = {floor}; sky130's device\n"
        "  symbols carry device-area parameters as expr() templates over @W/@nf,\n"
        f"  and xschem below {floor} emits them unevaluated -- ngspice then rejects\n"
        "  the netlist with 'Undefined parameter [ad]' / 'Cannot compute\n"
        "  substitute'. See design/pdk.json's comment block (issue #151).\n"
        "  Ubuntu/Debian package xschem 3.4.4, which is BELOW this floor; build\n"
        "  from https://github.com/StefanSchippers/xschem at tag "
        f"{floor} instead\n"
        "  (or `brew install xschem` on macOS).\n"
        "  A machine where this check is wrong can override the floor in the\n"
        "  git-ignored design/pdk.local.json: {\"xschem_version_min\": \"...\"}."
    )
    if found is None:
        raise ExportError(
            "could not determine the version of the xschem on PATH, so it "
            f"cannot be shown to meet the required minimum ({floor})." + hint
        )
    if _version_tuple(found) < _version_tuple(floor):
        raise ExportError(
            f"xschem {found} is too old to netlist this design "
            f"(minimum {floor})." + hint
        )


@functools.lru_cache(maxsize=1)
def klt_version() -> str | None:
    """Version reported by the ``klt`` on PATH, or ``None`` if unreadable.

    ``None`` covers "no klt on PATH", "it would not run", and "it ran but
    printed nothing matching :data:`_KLT_VERSION_RE`", for the same reason
    :func:`xschem_version` collapses those three: none of them establishes
    that the installed klt meets :func:`klt_version_min`.
    """
    exe = shutil.which(KLT)
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _KLT_VERSION_RE.search(f"{proc.stdout}\n{proc.stderr}")
    return match.group(1) if match else None


def klt_version_min() -> str:
    """``design/pdk.json``'s ``klt_version_min``, or the built-in default."""
    configured = _load_config().get("klt_version_min")
    return str(configured).strip() if configured else DEFAULT_KLT_VERSION_MIN


def check_klt_version() -> None:
    """Raise :class:`ExportError` unless PATH's klt meets the floor.

    A hard gate, on the same terms as :func:`check_xschem_version`, and for
    a related reason: ``klt netlist --erc`` is what ``--check`` uses to
    establish connectivity, and it does not exist before klayout-tools
    0.9.1. An older klt would reject ``--erc`` with an argparse usage error
    on stderr and exit 2 -- which this module would otherwise have to guess
    the meaning of, and which reads as neither "stale netlist" nor "broken
    schematic". Refusing up front with the floor named is the same contract
    the xschem floor already has: a tool problem is reported as a tool
    problem (:data:`EXIT_ENVIRONMENT`), never as a design finding.
    """
    floor = klt_version_min()
    found = klt_version()
    hint = (
        f"\n  design/pdk.json pins klt_version_min = {floor}; design netlisting\n"
        "  runs through `klt netlist` rather than a raw xschem call, because klt\n"
        "  forces xschem's headless flags and bounds the run (a GUI-mode xschem\n"
        "  hangs in its Tk event loop instead of failing). `klt netlist --erc`,\n"
        f"  which --check needs for connectivity, first ships in klayout-tools {floor}.\n"
        "  Install it without touching a shared tool install, e.g.\n"
        f'    uvx --from "klayout-tools=={floor}" python3 design/netlist.py --check\n'
        "  A machine where this check is wrong can override the floor in the\n"
        '  git-ignored design/pdk.local.json: {"klt_version_min": "..."}.'
    )
    if found is None:
        raise ExportError(
            "could not determine the version of the klt on PATH (klayout-tools), "
            f"so it cannot be shown to meet the required minimum ({floor})." + hint
        )
    if _version_tuple(found) < _version_tuple(floor):
        raise ExportError(
            f"klt {found} is too old to netlist this design "
            f"(minimum {floor})." + hint
        )


def _is_variant_dir(path: Path) -> bool:
    return (path / "libs.tech" / "xschem").is_dir()


def find_pdk() -> Pdk:
    """Locate a sky130 install. First hit wins:

    1. ``SKY130_PDK_PATH`` -- absolute path to the *variant* directory.
    2. ``PDK_ROOT`` (+ ``PDK``) -- the conventional open_pdks environment.
    3. ``design/pdk.local.json`` -- machine-local override, git-ignored.
    4. ``design/pdk.json`` -- committed defaults: variant + search roots.
    5. Built-in search roots -- volare/ciel stores, open_pdks prefixes.

    The walk itself (steps 1, 2 and 5, plus the ``~`` expansion and
    validator-predicate check applied at every step) is
    ``design/_pdk_search.py``'s ``search_pdk()``, shared with
    ``sim/bin/corner-run.py``'s ``resolve_pdk()`` -- this function supplies
    only the xschem-specific validator (:func:`_is_variant_dir`) and this
    tool's own config source (steps 3-4, loaded by :func:`_load_config`).
    """
    config = _load_config()
    variant = os.environ.get("PDK") or config.get("variant") or DEFAULT_VARIANT

    try:
        found = search_pdk(
            variant=variant,
            is_variant_dir=_is_variant_dir,
            variant_dir_label=_VARIANT_DIR_LABEL,
            search_roots=list(config.get("search_roots") or ()) + list(BUILTIN_SEARCH_ROOTS),
        )
    except PdkSearchError as exc:
        raise PdkNotFound(str(exc)) from exc
    if found is None:
        raise PdkNotFound(INSTALL_HINT)
    return Pdk(path=found.path, variant=found.variant, source=found.source)


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


def _klt_report(stream: str) -> dict:
    """``klt --format json``'s report object, or ``{}`` if the stream is not one.

    Never raises: this is only ever used to make a failure *more* legible,
    so a klt that printed something unparseable (a Python traceback, a
    truncated stream) must degrade to "no structured detail" rather than
    replace the original failure with a :class:`json.JSONDecodeError`.
    """
    try:
        parsed = json.loads(stream)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


#: klt stamps one provenance comment into the netlist it writes, e.g.
#: ``** klt-netlist-inputs: {"pdk_variant": null, "rcfile": "xschemrc", ...}``.
#: It is dropped here, before :func:`_normalize`, for the same reason
#: :func:`_normalize` strips absolute paths: the committed netlists have to
#: be machine-independent, and that line carries the rcfile's *temp-directory*
#: basename and the netlisting host's xschem version. Keeping it would make
#: every committed ``design/*.spice`` churn on a klt or xschem bump and would
#: have changed all four of them in the commit that introduced klt here.
#: Filed upstream as klayout-tools#5085, which is closed by a
#: ``--no-provenance-header`` flag that no tagged release carries yet -- so
#: this stays until the klt floor can move past the release that ships it.
#: Deliberately ``count=1`` and anchored: klt writes the line once, and a
#: broader sweep could eat a legitimate netlist comment.
_KLT_PROVENANCE_RE = re.compile(r"^\*\* klt-netlist-inputs:.*$\n?", re.MULTILINE)


def _strip_klt_provenance(text: str) -> str:
    """Drop klt's ``** klt-netlist-inputs:`` provenance comment line."""
    return _KLT_PROVENANCE_RE.sub("", text, count=1)


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
            "  macOS: brew install xschem\n"
            "  or build from https://github.com/StefanSchippers/xschem at tag "
            f"{xschem_version_min()} or later\n"
            "  (NOT `apt-get install xschem`: Debian/Ubuntu package 3.4.4, which "
            "is below\n"
            "  this repo's required minimum -- see design/pdk.json, issue #151)"
        )
    # Before any netlisting: a too-old xschem produces an unsimulable
    # netlist, not a differently-formatted one. See check_xschem_version().
    # klt is checked on the same terms -- it is what actually runs xschem,
    # and --erc (which --check depends on) has a floor of its own.
    check_xschem_version()
    check_klt_version()
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
        produced = tmpdir / f"{top}.spice"
        cmd = [
            KLT, "netlist", str(schematic),
            "-o", str(produced),
            "--rcfile", str(rcfile),
            "--timeout-s", str(NETLIST_TIMEOUT_S),
            "--format", "json",
        ]
        if erc:
            # Walks ERC over *top*'s full instantiated hierarchy, the same
            # reach the raw `xschem netlist -erc` Tcl call had. klt reports
            # a finding as a structured error and writes NO netlist, where
            # xschem used to write the electrically-broken one and signal
            # only through its exit status.
            cmd.append("--erc")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=tmpdir,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            # Every klt netlist failure exits 1, so the exit status alone
            # cannot tell an ERC finding from a timeout or an unresolved
            # symbol. The discriminator is the structured report's
            # `error.code`, which is `erc_findings` for an ERC finding and
            # absent for a timeout -- so anything without that code is an
            # environment/tool failure, reported as one rather than as a
            # design defect. klt prints the failure report on stderr and
            # the success report on stdout; read both rather than assuming.
            report = _klt_report(proc.stderr) or _klt_report(proc.stdout) or {}
            error = report.get("error") or {}
            detail = str(error.get("message") or (proc.stderr or proc.stdout or "")).strip()
            if erc and error.get("code") == "erc_findings":
                findings = error.get("findings") or []
                listed = "\n".join(f"  {line}" for line in findings)
                raise ErcViolation(
                    f"klt netlist --erc failed for {top} -- the schematic has "
                    "a connectivity defect (e.g. an undriven node, open net, "
                    "or shorted pin), not merely a stale netlist:\n"
                    f"{listed or detail}"
                )
            raise ExportError(
                f"klt netlist failed for {top} (exit {proc.returncode}); this "
                "is a tool or environment failure, not a stale netlist and "
                f"not an ERC finding:\n{detail}"
            )
        if not produced.is_file():
            raise ExportError(
                f"klt netlist reported success but wrote no netlist for {top}\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
            )
        text = _normalize(_strip_klt_provenance(produced.read_text()),
                          _schematic_params(schematic))
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
        help=(
            "print the resolved sky130 install, its open_pdks commit, and the "
            "resolved xschem and klt versions against their required "
            "minimums, then exit"
        ),
    )
    parser.add_argument("--top", action="append", metavar="CELL", help="cell to export (repeatable)")
    args = parser.parse_args(argv)

    if args.lint:
        return lint_schematics()

    if args.pdk:
        # Reported, never enforced here: --pdk is the attribution step CI
        # runs *before* --check so a later failure is readable without
        # bisecting a diff. The xschem floor is enforced in export() (see
        # check_xschem_version()); the open_pdks pin is a provenance note
        # and never enforced at all. Both are printed the same way, with
        # the same "matches / DIFFERS FROM"-style verdict.
        floor = xschem_version_min()
        found = xschem_version()
        print(f"xschem    {found or 'unknown'}")
        if found is None:
            verdict = "CANNOT VERIFY against the installed xschem"
        elif _version_tuple(found) < _version_tuple(floor):
            verdict = "TOO OLD -- netlisting will refuse to run"
        else:
            verdict = "satisfied by the installed xschem"
        print(f"xschem>=  {floor} ({verdict})")
        # klt is reported beside xschem because it is what actually runs
        # xschem now; a klt below the floor is the same class of failure as
        # a too-old xschem, and --pdk exists to make that attributable
        # before anyone has to read a --check diff to find out.
        klt_floor = klt_version_min()
        klt_found = klt_version()
        print(f"klt       {klt_found or 'unknown'}")
        if klt_found is None:
            klt_verdict = "CANNOT VERIFY against the installed klt"
        elif _version_tuple(klt_found) < _version_tuple(klt_floor):
            klt_verdict = "TOO OLD -- netlisting will refuse to run"
        else:
            klt_verdict = "satisfied by the installed klt"
        print(f"klt>=     {klt_floor} ({klt_verdict})")
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
