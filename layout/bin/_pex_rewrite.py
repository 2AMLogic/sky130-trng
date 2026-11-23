#!/usr/bin/env python3
"""Shared extracted-netlist rewrite helpers (issue #638).

One implementation of the rename-and-verify pass every consumer of
``klt extract --pdk --parasitics`` output in this repo runs over an
extracted netlist before simulating it. Until #638 there were two, and they
had drifted in **both** directions -- each fork guarded against one silent
netlist corruption the other let through:

- ``layout/bin/pex-netlist.py``'s ``canonicalize`` matched alias keys in
  JSON dict order, so an alias map whose shorter key (``a|inv_q_y|...|q|y``,
  ``raw_bit``) happened to precede its strict prefix-extension
  (``...|q|y$1``, ``raw_valid``) silently rewrote five sampler ports onto
  ``raw_bitn1``..``raw_bitn5``. The ``pex-measure.py`` fork had fixed this
  (longest key first); the library builder had not.
- ``sim/pex-sampler-core/harness/pex-measure.py``'s device-card check
  accepted raw ``M`` cards and unit-suffixed geometry (``W=0.84U``), which
  mis-scale by 1e-6 under the ``.option scale=1u`` convention every deck
  here runs at -- exactly what its own docstring claimed to prevent. The
  library builder's ``check_device_card`` enforced all three legs (X card,
  declared model, unitless geometry); the measurement harness checked only
  the model.

Both gaps are closed here for every caller: alias matching is
longest-key-first regardless of key order, and every device card passes
:func:`check_device_card`.

Two framings, deliberately both kept
------------------------------------

The two consumers frame the rewritten text differently, so the module
offers two thin drivers over the same card-renaming core:

- :func:`rewrite_cell` (library framing, `pex-netlist.py`): the input is
  one cell of a multi-cell library. Extractor preamble comments are
  dropped (reproduced once, library-wide), the ``.SUBCKT`` line is
  re-emitted as ``.subckt <core_name>`` with renamed ports, and the
  substrate ``.global`` lives in the library header, not per cell.
- :func:`rewrite_standalone` (single-cell framing, `pex-measure.py` for
  ``klt pex --rename-declared-pins`` output): the input is one
  self-contained netlist. Comment lines, dot cards and the file's own
  ``.SUBCKT``/``.ENDS``/``.GLOBAL vsubs`` framing are preserved verbatim
  and only element-card node tokens are renamed, so the rewritten file
  stays a drop-in ``klt sim`` netlist.

Import it the way ``_gds_geometry`` / ``_klt_common`` are imported -- put
this file's directory on ``sys.path`` and import by bare module name::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))      # elsewhere
    from _pex_rewrite import Renamer, rewrite_cell  # noqa: E402
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klt_common import BuildError  # noqa: E402

#: Geometry parameters a device card may carry, all of which must be
#: unitless for this repo's `.option scale=1u` contract to hold.
GEOM_PARAMS = ("L", "W", "AS", "AD", "PS", "PD", "NRD", "NRS")

#: Remediation attached to the unaliased-joined-name error. The library
#: builder's default; the standalone harness passes its own (pointing at
#: net-aliases.json's re-derivation recipe) via ``remedy=``.
DEFAULT_REMEDY = "add one to the cell's descriptor entry"


def join_continuations(text: str) -> list[str]:
    """Fold ngspice ``+`` continuation lines into their logical line."""
    out: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("+"):
            if not out:
                raise BuildError("netlist starts with a continuation line")
            out[-1] = out[-1].rstrip() + " " + raw[1:].strip()
        else:
            out.append(raw.rstrip())
    return out


class Renamer:
    """Injective joined-name -> design-name token renamer.

    Joined extractor net names (and their ``\\x7c``-escaped spelling) map
    to the design-level name from the caller's alias map; ``__tN``
    star-leg suffixes ride along; ``$`` (ngspice in-line comment character)
    becomes ``n`` and ``\\`` is dropped, the same sanitization every
    committed ``layout/pex*/`` library applies. The rename is checked
    injective so it can never merge two nets, and any ``|``-bearing name
    with no alias entry is a hard error -- a regenerated layout must never
    silently measure or simulate the wrong net.

    Alias keys are matched **longest first**, so a ``...|y$1``-style name
    can never be captured by the shorter ``...|y`` entry that happens to
    precede it in JSON key order (issue #638's prefix-order gap: in
    sampler_core, ``a|inv_q_y|...|q|y`` is a strict prefix of
    ``...|q|y$1``..``y$5``, and an alphabetically sorted alias map put the
    short key first).
    """

    def __init__(self, aliases: dict[str, str], *, context: str = "",
                 remedy: str = DEFAULT_REMEDY):
        self.aliases = sorted(aliases.items(), key=lambda kv: -len(kv[0]))
        self._context = context
        self._remedy = remedy
        self._seen: dict[str, str] = {}

    def canonical(self, name: str) -> str:
        for joined, design in self.aliases:
            escaped = joined.replace("|", "\\x7c")
            if name == joined or name == design:
                return design
            if name.startswith(escaped):
                return design + name[len(escaped) :]
            if name.startswith(joined):
                return design + name[len(joined) :]
        if "|" in name or "\\x7c" in name:
            raise BuildError(
                f"net name {name!r} is a joined extractor name with no "
                f"net_aliases entry -- {self._remedy}"
            )
        return name

    def token(self, name: str) -> str:
        out = sanitize(self.canonical(name))
        previous = self._seen.setdefault(out, name)
        if previous != name:
            prefix = f"{self._context}: " if self._context else ""
            raise BuildError(
                f"{prefix}names {previous!r} and {name!r} both rewrite to "
                f"{out!r} -- renaming would merge two distinct nets"
            )
        return out


def canonicalize(name: str, aliases: dict[str, str],
                 remedy: str = DEFAULT_REMEDY) -> str:
    """Rename a joined net name (and its ``\\x7c``-escaped spelling).

    Longest key first -- see :class:`Renamer` for why key order must not
    decide the match.
    """
    return Renamer(aliases, remedy=remedy).canonical(name)


def sanitize(name: str) -> str:
    """Strip characters no ngspice deck should have to quote.

    The extractor names an unlabelled internal net after its own device
    index (``\\$3``, escaped) and its device instances the same way
    (``M$3``). ``$`` is an ngspice in-line comment character and ``\\`` is
    an escape, so both are replaced -- ``$`` by ``n`` (giving ``n3`` /
    ``Mn3``), ``\\`` dropped. :class:`Renamer` asserts the mapping stays
    injective, so a rename can never silently merge two nets.
    """
    return name.replace("\\", "").replace("$", "n")


def check_device_card(line: str, expected_models: list[str]) -> str:
    """Verify one extracted device card against this repo's contract.

    Returns the card unchanged. Raises :class:`BuildError` if the card has
    fewer tokens than ``<name> <4 nodes> <model>`` needs, if it is not an
    ``X`` (subcircuit-call) card, if its model is not one the caller
    declares, or if any geometry value carries a unit suffix.

    ``klt extract --pdk`` already emits exactly the form this repo's decks
    need, so the job here is to *hold* that contract, not to re-implement
    it. All three failure modes would otherwise be silent -- an ``M`` card
    would fail to bind at all (loud), but a wrong model name binds to the
    wrong device and a stray ``U`` suffix mis-scales the device by 1e-6
    under ``.option scale=1u``, and both of those simulate cleanly.

    A card with fewer than the six tokens of ``<name> <4 nodes> <model>``
    is also rejected (issue #647): such a card -- a hand-edited or
    truncated netlist, a future extractor writing fewer nodes -- would
    otherwise raise ``IndexError`` here instead of ``BuildError``, escaping
    the ``except BuildError`` translation every consumer wraps this in.
    """
    tokens = line.split()
    if len(tokens) < 6:
        name = tokens[0] if tokens else repr(line)
        raise BuildError(
            f"device card {name} has {len(tokens)} tokens -- an X card is "
            "<name> <node> <node> <node> <node> <model> [<param=value>...]; "
            f"pass --pdk to klt extract so it writes the PDK's own device "
            f"subcircuits (line: {line})"
        )
    name, model = tokens[0], tokens[5]
    if not name.upper().startswith("X"):
        raise BuildError(
            f"device card {name} is not a subcircuit call -- pass --pdk to "
            f"klt extract so it writes the PDK's own device subcircuits "
            f"(line: {line})"
        )
    if model not in expected_models:
        raise BuildError(
            f"device card {name} names model {model!r}, which is not in the "
            f"descriptor's expect_device_models {expected_models}"
        )
    for token in tokens[6:]:
        key, _, value = token.partition("=")
        if key.upper() not in GEOM_PARAMS:
            raise BuildError(f"unexpected device parameter {token!r} on {name}")
        if not re.fullmatch(r"[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", value):
            raise BuildError(
                f"device parameter {token!r} on {name} is not a bare unitless "
                "number -- this library's .option scale=1u contract requires "
                "unsuffixed geometry (klt extract --pdk emits it that way)"
            )
    return line


def rename_card(stripped: str, renamer: Renamer,
                expected_models: list[str]) -> str:
    """Rename one element card's node tokens; verify device cards.

    The card classification both framings share: a device card's trailing
    tokens are the model name and ``PARAM=value`` geometry, not node names
    -- only the instance name and its four terminals go through the
    renamer, then the whole card through :func:`check_device_card`. An
    ``R``/``C`` card's third token onwards is ``<value>`` (and geometry),
    not a name. Anything else the extractor emitted is a hard error:
    silently dropping it is unacceptable.
    """
    tokens = stripped.split()
    head = tokens[0].upper()[0]
    if head in ("X", "M"):
        renamed = [renamer.token(t) for t in tokens[:5]] + tokens[5:]
        return check_device_card(" ".join(renamed), expected_models)
    if head in "RC":
        # `<name> <node> <node> <value>` -- the value is not a name.
        renamed = [renamer.token(t) for t in tokens[:3]] + tokens[3:]
        return " ".join(renamed)
    raise BuildError(f"unhandled element card in extracted netlist: {stripped}")


def rewrite_cell(
    netlist_text: str,
    *,
    core_name: str,
    aliases: dict[str, str],
    expected_models: list[str],
) -> tuple[list[str], list[str]]:
    """Rewrite one extracted cell into ``<core_name>`` + its port list.

    Returns ``(lines, ports)``. Comment lines from the extractor's own
    parasitic-model preamble are dropped (they are reproduced once, at the
    top of the library, instead of once per cell); its per-device provenance
    comments are kept.
    """
    renamer = Renamer(aliases, context=core_name)

    lines: list[str] = []
    ports: list[str] = []
    in_cell = False
    for line in join_continuations(netlist_text):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith(".SUBCKT"):
            in_cell = True
            ports = [renamer.token(tok) for tok in stripped.split()[2:]]
            lines.append(f".subckt {core_name} {' '.join(ports)}")
            continue
        if upper.startswith(".ENDS"):
            in_cell = False
            lines.append(f".ends {core_name}")
            continue
        if not in_cell:
            continue  # extractor preamble comments, reproduced library-wide
        if stripped.startswith("*"):
            lines.append(stripped)
            continue
        lines.append(rename_card(stripped, renamer, expected_models))
    if not ports:
        raise BuildError(f"{core_name}: no .SUBCKT line in the extracted netlist")
    return lines, ports


def rewrite_standalone(
    netlist_text: str,
    *,
    aliases: dict[str, str],
    expected_models: list[str],
    remedy: str = DEFAULT_REMEDY,
) -> str:
    """Rewrite a self-contained extracted netlist to design-level names.

    Only names move: every device card, geometry value, R/C value and
    connection is byte-preserved apart from the rename -- the same contract
    :func:`rewrite_cell` states for its own output. The file's own framing
    is preserved verbatim: comment lines, dot cards (``.GLOBAL vsubs`` and
    friends -- no names to rename), the ``.SUBCKT``/``.ENDS`` header pair,
    and any element cards outside the cell all pass through untouched, so
    the result stays a drop-in netlist for ``klt sim``. Device cards are
    checked against *expected_models* through :func:`check_device_card`,
    and a netlist with no device card at all is an error (nothing was
    measured but everything would have looked fine).
    """
    renamer = Renamer(aliases, remedy=remedy)
    out: list[str] = []
    in_cell = False
    device_cards = 0
    for line in join_continuations(netlist_text):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("*"):
            out.append(stripped)
            continue
        head = stripped.split()[0].upper()
        if head.startswith("."):
            if head.startswith(".SUBCKT"):
                in_cell = True
            elif head.startswith(".ENDS"):
                in_cell = False
            out.append(stripped)
            continue
        if not in_cell:
            out.append(stripped)
            continue
        if head[0] in ("X", "M"):
            device_cards += 1
        out.append(rename_card(stripped, renamer, expected_models))
    if device_cards == 0:
        raise BuildError("extracted netlist carries no device cards")
    return "\n".join(out) + "\n"
