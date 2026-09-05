#!/usr/bin/env python3
"""Shared sky130 PDK-variant-directory search.

Used by both ``design/netlist.py``'s ``find_pdk()`` and
``sim/bin/corner-run.py``'s ``resolve_pdk()``. Both tools locate an
installed sky130 PDK by walking the same fallback chain -- the
``SKY130_PDK_PATH`` env var, then ``PDK_ROOT`` + ``PDK``, then a
caller-supplied list of search roots (their own config file(s) plus this
module's :data:`BUILTIN_SEARCH_ROOTS`) -- differing only in:

* the validator predicate that recognizes a variant directory (sky130's
  xschem symbol layout lives at ``libs.tech/xschem``; its combined ngspice
  corner library lives at ``libs.tech/combined``), and
* where each caller's search-root list and config come from
  (``design/pdk.json`` vs. ``sim/pdk.json`` + ``sim/pdk.local.json`` --
  intentionally two separate files, see ``design/pdk.json``'s own comment
  and issue #9; this module shares the search *algorithm* only).

This module owns just the walk-and-validate part. See ``find_pdk()`` /
``resolve_pdk()`` in the two callers above for the config loading, the
resulting ``Pdk`` dataclass each builds, tool-specific error messages and
install hints, and (``corner-run.py`` only) the ``volare path`` fallback.

Extracted per issue #25, closing a gap ``design/netlist.py``'s own module
docstring flagged in advance: once a simulation harness landed (issue #9)
a second PDK resolver would exist, and it did -- as a near-line-for-line
copy of this one -- so both are now built on this shared search instead of
being left to drift apart independently.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

#: Directories expected to *contain* sky130 variant directories. Shared by
#: both callers; each also searches its own config-supplied roots first, in
#: the order it assembles them.
BUILTIN_SEARCH_ROOTS = (
    "~/.volare",
    "~/.ciel",
    "/usr/share/pdk",
    "/usr/local/share/pdk",
    "~/share/pdk",
    "/opt/pdk",
)


class PdkSearchError(RuntimeError):
    """An explicit ``SKY130_PDK_PATH`` override failed validation.

    Distinct from "not found anywhere" -- :func:`search_pdk` returns
    ``None`` in that case so each caller can raise its own tool-specific
    "not found" error with its own install hint. An explicit override that
    does not validate is almost always a typo, so it is reported
    immediately instead of silently falling through to the search-roots
    chain.
    """


class PdkLocation(NamedTuple):
    """One located sky130 variant directory.

    Each caller wraps this in its own richer ``Pdk`` dataclass (which also
    carries things this module knows nothing about, like corner-run.py's
    resolved ngspice library file or netlist.py's ``version`` property).
    """

    path: Path
    variant: str
    source: str  # how it was found, for provenance


def search_pdk(
    *,
    variant: str,
    is_variant_dir: Callable[[Path], bool],
    variant_dir_label: str,
    search_roots: Iterable[str],
    env: dict[str, str] | None = None,
) -> PdkLocation | None:
    """Walk the shared sky130 PDK resolution order; return the first hit.

    Order:

    1. ``SKY130_PDK_PATH`` -- absolute path to the *variant* directory
       itself. Raises :class:`PdkSearchError` if set but *is_variant_dir*
       rejects it, rather than silently falling through to the rest of the
       chain.
    2. ``PDK_ROOT`` (+ ``PDK``) -- the conventional open_pdks environment
       pair. Falls through to *search_roots* (does not raise) if
       ``PDK_ROOT``/*variant* does not validate.
    3. Every entry of *search_roots*, in the order given -- each caller
       assembles its own list (local-override roots, committed-config
       roots, :data:`BUILTIN_SEARCH_ROOTS`, etc.); the first
       ``<root>/<variant>`` that *is_variant_dir* accepts wins.

    *variant_dir_label* names, for the :class:`PdkSearchError` message
    only, the directory layout *is_variant_dir* actually checks for (e.g.
    ``"libs.tech/xschem directory"``), so each caller's error text matches
    what it validated rather than a generic placeholder.

    *env* defaults to ``os.environ``; overridable so a test can exercise
    the env-var branches without mutating process environment.

    Returns ``None`` -- not an exception -- if nothing above matches, so
    the caller can raise its own "not found" error with its own install
    hint.
    """
    env = os.environ if env is None else env

    explicit = env.get("SKY130_PDK_PATH")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not is_variant_dir(path):
            raise PdkSearchError(f"SKY130_PDK_PATH={explicit} has no {variant_dir_label}")
        return PdkLocation(path=path, variant=path.name, source="SKY130_PDK_PATH")

    pdk_root = env.get("PDK_ROOT")
    if pdk_root:
        path = (Path(pdk_root).expanduser() / variant).resolve()
        if is_variant_dir(path):
            return PdkLocation(path=path, variant=variant, source="PDK_ROOT")

    for root in search_roots:
        path = (Path(root).expanduser() / variant).resolve()
        if is_variant_dir(path):
            return PdkLocation(path=path, variant=variant, source=str(root))

    return None
