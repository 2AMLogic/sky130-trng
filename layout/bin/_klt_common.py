#!/usr/bin/env python3
"""Shared ``klt``-invocation plumbing for the ``layout/bin/`` build scripts.

Used by both ``layout/bin/compose-cell.py`` (the per-cell
gen/compose/DRC/extract/LVS chain) and ``layout/bin/pex-netlist.py`` (the
post-layout parasitic-netlist library build). Both drive the same tool the
same way -- shell out to ``klt ... --format json`` from the artifact
directory, treat a missing/unparsable JSON response as fatal, treat an
``error`` object in an otherwise well-formed response as fatal, and write
their JSON artifacts with one fixed serialization -- so the contract lives
here once instead of in a copy per script.

Extracted per issue #49, following ``design/_pdk_search.py``'s precedent
(issue #25): before the extraction, ``pex-netlist.py``'s own ``run_klt``
docstring said "Same contract as ``layout/bin/compose-cell.py``'s helper of
the same name", which is a duplication note, not a shared contract. Now it
is one.

Import it the way ``design/netlist.py`` imports ``_pdk_search`` -- these are
scripts, not an installed package, so the importer puts this file's own
directory on ``sys.path`` and imports it by bare module name::

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _klt_common import BuildError, run_klt, write_json  # noqa: E402
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class BuildError(RuntimeError):
    """A step of the chain failed."""


def run_klt(args: list[str], *, env: dict[str, str], cwd: Path) -> dict:
    """Run ``klt`` with ``--format json``, from *cwd*, and parse its response.

    Always invoked from the artifact's own output directory with *relative*
    paths, so that every committed response records repo-relative provenance
    and no absolute home path leaks into the evidence (the leak ``klt
    env-provenance --scan`` exists to catch).

    A non-zero exit is not automatically fatal: ``klt gen-compose`` exits 3
    for a partial success (some net unrouted) and ``klt lvs`` exits 3 for a
    clean-run mismatch, both of which the callers want to report from the
    response body rather than from a traceback. A response that is not JSON
    at all is fatal, as is a well-formed response carrying an ``error``
    object.
    """
    proc = subprocess.run(
        ["klt", *args, "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
    )
    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BuildError(
            f"klt {' '.join(args)} produced no JSON response "
            f"(exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        ) from exc
    if "error" in response:
        raise BuildError(
            f"klt {' '.join(args)} failed: {response['error'].get('message')}"
        )
    return response


def write_json(path: Path, payload: dict) -> None:
    """Write *payload* as this repo's committed-artifact JSON spelling.

    Two-space indent, insertion order preserved (``sort_keys=False``, so a
    response's own field order survives into the committed file and stays
    diffable against the tool's output), one trailing newline. Parent
    directories are created if missing, so a caller writing into a
    not-yet-existing output tree (``layout/pex/raw/`` on a fresh build) does
    not have to pre-create it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
