#!/usr/bin/env python3
"""Shared ``klt``-invocation plumbing for this repo's build/verify scripts.

Used by ``layout/bin/compose-cell.py`` (the per-cell
gen/compose/DRC/extract/LVS chain), ``layout/bin/pex-netlist.py`` (the
post-layout parasitic-netlist library build), and
``sim/digital-synthesis/harness/synthesize-and-verify.py`` (the
synthesize/equiv/gate-cosim chain behind the ``level: gate`` evidence
record). All three drive the same tool the same way -- shell out to ``klt
... --format json``, treat a missing/unparsable JSON response as fatal,
treat an ``error`` object in an otherwise well-formed response as fatal,
and (for the two that write artifacts) serialize their JSON with one fixed
spelling -- so the contract lives here once instead of in a copy per
script.

Extracted per issue #49, following ``design/_pdk_search.py``'s precedent
(issue #25): before the extraction, ``pex-netlist.py``'s own ``run_klt``
docstring said "Same contract as ``layout/bin/compose-cell.py``'s helper of
the same name", which is a duplication note, not a shared contract. Now it
is one. The digital-synthesis harness adopted it per issue #133, which
retired a fourth-copy reimplementation that had quietly diverged (it never
checked for the ``error`` object, and it treated *every* non-zero exit as
fatal -- see :func:`run_klt`'s note on ``klt equiv``'s 3/4).

Issue #500 finished that migration and extended it from "how to invoke klt"
to "how to READ two specific klt responses", because the un-migrated sites
had drifted in what they read rather than in how they called:
:func:`klt_version` fixes one spelling of the version (bare, as 391 of the
392 committed provenance values spell it) for the three string-equality pin
gates that compare it, and :func:`pdk_find` / :func:`pdk_root` /
:func:`libs_ref` fix one way of reading ``klt pdk find`` -- always
``--format json``, never a regex over klt's human-readable rendering.
:func:`run_klt_rc` exposes klt's exit status for the one adopter that
records it.

Import it the way ``design/netlist.py`` imports ``_pdk_search`` -- these are
scripts, not an installed package, so the importer puts this file's own
directory on ``sys.path`` and imports it by bare module name. It lives under
``layout/bin/`` because that is where it was extracted from; an importer
outside that tree spells the same insert with an explicit path::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))      # elsewhere
    from _klt_common import BuildError, run_klt, write_json  # noqa: E402
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class BuildError(RuntimeError):
    """A step of the chain failed."""


def run_klt_rc(
    args: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
    klt: str = "klt",
    timeout: float | None = None,
) -> tuple[int, dict]:
    """:func:`run_klt`, but also returning klt's own exit status.

    Same contract in every other respect -- this is the one function that
    actually shells out, and :func:`run_klt` is the wrapper that drops the
    status for the callers that do not record it.

    It exists because a caller that *does* record the status should not have
    to re-fork the invocation contract to keep it:
    ``layout/trng_digital/erc-negative-controls.py`` writes klt's exit code
    into each control's record (``klt_exit``), which is how a reader tells a
    detected-finding run (``klt erc`` exits 3/4) from a clean one, and that
    was the reason it had grown a fourth private ``run_klt`` -- the exact
    divergence issue #133 retired and issue #500 finished retiring.
    """
    proc = subprocess.run(
        [klt, *args, "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
        timeout=timeout,
    )
    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BuildError(
            f"{klt} {' '.join(args)} produced no JSON response "
            f"(exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        ) from exc
    if "error" in response:
        raise BuildError(
            f"{klt} {' '.join(args)} failed: {response['error'].get('message')}"
        )
    return proc.returncode, response


def run_klt(
    args: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
    klt: str = "klt",
    timeout: float | None = None,
) -> dict:
    """Run ``klt`` with ``--format json``, from *cwd*, and parse its response.

    The ``layout/bin/`` callers always invoke from the artifact's own output
    directory with *relative* paths, so that every committed response records
    repo-relative provenance and no absolute home path leaks into the
    evidence (the leak ``klt env-provenance --scan`` exists to catch). *cwd*
    defaults to the caller's own working directory for the callers that
    cannot do that -- ``klt synthesize``/``klt equiv`` resolve every path in
    their responses to an absolute path regardless of how the request was
    invoked, so the digital-synthesis harness gets the same hygiene by
    sanitizing the response on the way into its record instead.

    *klt* is the binary to invoke, for callers that expose a ``--klt``/``$KLT``
    override; it defaults to whatever ``klt`` is on ``$PATH``.

    A non-zero exit is not automatically fatal. Several subcommands "ran
    fine, here is the bad news" through the response body, and the callers
    want to report that from the body rather than from a traceback:
    ``klt gen-compose`` exits 3 for a partial success (some net unrouted),
    ``klt lvs`` exits 3 for a clean-run mismatch, and ``klt equiv`` exits 3
    for a proven counterexample / 4 for an inconclusive (timed-out) proof.
    A response that is not JSON at all is fatal, as is a well-formed
    response carrying an ``error`` object -- note that under ``--format
    json`` klt writes the error envelope to *stderr* and leaves stdout
    empty, so a genuine failure normally lands in the first of those two
    cases, with the envelope surfaced through the captured stderr.

    *timeout* is an optional wall-clock ceiling, for the callers that want a
    hung klt to fail rather than hang; it raises
    ``subprocess.TimeoutExpired``, not :class:`BuildError`, because a timeout
    is not a response.
    """
    return run_klt_rc(args, env=env, cwd=cwd, klt=klt, timeout=timeout)[1]


def klt_version(*, env: dict[str, str] | None = None, klt: str = "klt") -> str:
    """The pinned tool's own version, BARE -- ``"0.8.0"``, never ``"klt 0.8.0"``.

    klt offers the same value two ways, and they are not the same string::

        $ klt --version                 klt 0.8.0
        $ klt version --format json     {"version": "0.8.0", ...}

    This reads the second. That is not a style preference: 391 of the 392
    ``klt_version`` values in this repo's committed evidence are bare, every
    klt pin in the repo is bare (``layout/pdk.json``'s ``klt_version_pin``,
    ``ci.yml``'s and ``pdk-nightly.yml``'s ``klayout-tools==X.Y.Z``), and
    three producers gate on ``klt_version`` by string equality
    (``sim/digital-pnr/harness/pnr-and-verify.py``,
    ``sim/digital-repaired-compaction/analysis/repaired_compaction.py``,
    ``sim/digital-functional-verification/harness/fv-cosim.py``). A
    banner-spelled read compared against a bare pin fails on a *correctly*
    pinned host, which is exactly what issue #500 found waiting for the
    0.8.0 pin bump (#372) -- so the banner spelling has no second reader here.

    *env* defaults to the ambient environment, for the callers that do not
    manage one; the version read does not depend on ``$PDK``/``$PDK_ROOT``.
    """
    response = run_klt(["version"], env=dict(os.environ if env is None else env),
                       klt=klt)
    version = response.get("version")
    if not isinstance(version, str) or not version:
        raise BuildError(
            f"{klt} version --format json carried no 'version' string: {response!r}"
        )
    return version


def pdk_find(
    pdk: str,
    *,
    env: dict[str, str] | None = None,
    klt: str = "klt",
    cwd: Path | None = None,
    timeout: float | None = None,
    warn: bool = True,
) -> dict:
    """``klt pdk find --pdk <pdk>``'s full JSON response -- never scraped text.

    Always ``--format json``. klt's human-readable rendering is a rendering,
    not a machine contract: it interleaves ``warning:`` lines into the same
    stream, so a first-match regex over it ("the first ``libs_ref:`` line")
    silently loses to a shadowed-install warning or a second install block.
    That was a live fragility in this repo's Liberty-deck resolver until
    issue #500; the JSON response names each field once.

    Returning the WHOLE response is the other half of the fix. The text
    scrape could only recover the one path it grepped for, discarding
    ``compatibility``, ``ambiguous_roots`` and ``broken_symlinks`` -- the
    fields by which klt says "I found an install, and you should look at
    it". They are now the caller's to read; with *warn* (the default) the two
    that are unambiguously actionable are also reported on stderr, so a
    caller choosing a Liberty deck cannot be unaware that klt flagged the
    install:

    * ``compatibility`` -- a PDK whose installed sources are not the expected
      ones. Two shapes exist in the wild and both are accepted: a bare status
      string (``"match"``) and a dict carrying ``status`` plus the
      expected/installed detail (klt 0.9.x). See :func:`compatibility_status`.
    * ``broken_symlinks`` -- a non-empty list is wrong under every reading.

    ``ambiguous_roots`` is deliberately NOT warned on: a host with both
    ``~/.ciel`` and ``~/.volare`` reports the shadowed one on every healthy
    call, so warning would be noise on every run and would train readers to
    ignore the other two. It is in the returned response for a caller that
    wants to be strict about it.

    These are notes, never verdicts: this helper resolves paths and does not
    decide whether a flagged install is acceptable -- that belongs to the
    caller's own fail-closed gate.
    """
    response = run_klt(["pdk", "find", "--pdk", pdk],
                       env=dict(os.environ if env is None else env),
                       klt=klt, cwd=cwd, timeout=timeout)
    if warn:
        status = compatibility_status(response)
        if status is not None and status != "match":
            print(f"warning: klt pdk find --pdk {pdk}: compatibility "
                  f"{status!r} (not 'match')", file=sys.stderr)
        broken = response.get("broken_symlinks")
        if broken:
            print(f"warning: klt pdk find --pdk {pdk}: broken_symlinks "
                  f"{broken!r}", file=sys.stderr)
    return response


def compatibility_status(response: dict) -> str | None:
    """``compatibility``'s status out of a :func:`pdk_find` response, or None.

    klt spells this field two ways depending on its version -- a bare string
    (``"compatibility": "match"``) and, since 0.9.x, a dict whose ``status``
    carries the verdict and whose siblings carry the expected/installed
    package detail. Reading it as a string against the dict form compares a
    dict to ``"match"``, which is never equal: that would report every
    healthy install as flagged, i.e. exactly the false alarm that teaches a
    reader to ignore the warning. Normalising here keeps the two spellings
    from becoming a third drift of the kind issue #500 removed.
    """
    compat = response.get("compatibility")
    if isinstance(compat, dict):
        status = compat.get("status")
        return status if isinstance(status, str) else None
    return compat if isinstance(compat, str) else None


def pdk_root(
    pdk: str,
    *,
    env: dict[str, str] | None = None,
    klt: str = "klt",
    cwd: Path | None = None,
) -> str:
    """The PDK install root: a preset ``$PDK_ROOT`` wins, else klt resolves it.

    The short-circuit is ``layout/bin/verify-whole.py``'s: an operator who
    has already pinned ``$PDK_ROOT`` has named the install, and asking klt to
    search again can only disagree with them. An empty ``$PDK_ROOT`` counts
    as unset rather than as the root ``""``.
    """
    source = os.environ if env is None else env
    preset = source.get("PDK_ROOT")
    if preset:
        return preset
    response = pdk_find(pdk, env=env, klt=klt, cwd=cwd)
    root = response.get("root")
    if not isinstance(root, str) or not root:
        raise BuildError(
            f"{klt} pdk find --pdk {pdk} carried no 'root' string: {response!r}"
        )
    return root


def libs_ref_of(response: dict) -> Path:
    """``assets.libs_ref`` out of an already-fetched :func:`pdk_find` response.

    Separate from :func:`libs_ref` so that a caller which needs *other*
    fields of the same response too (the functional-verification harnesses
    record ``variant`` and ``version`` in their evidence) reads one response
    rather than invoking ``klt pdk find`` twice to get two fields out of it.

    A missing or non-string field is fatal here rather than a ``KeyError``,
    or -- worse -- a ``Path(None)`` that fails later and somewhere else.
    """
    ref = (response.get("assets") or {}).get("libs_ref")
    if not isinstance(ref, str) or not ref:
        raise BuildError(
            f"klt pdk find carried no 'assets.libs_ref' string: {response!r}"
        )
    return Path(ref)


def libs_ref(
    pdk: str,
    *,
    env: dict[str, str] | None = None,
    klt: str = "klt",
    cwd: Path | None = None,
    timeout: float | None = None,
) -> Path:
    """The install's ``libs.ref`` tree, from :func:`pdk_find`'s ``assets``.

    The three callers that want this (the two functional-verification
    harnesses, for the sky130_fd_sc_hd Verilog cell models, and the
    gate-level model generator, for the Liberty deck) each read
    ``assets.libs_ref`` out of the same response. Use :func:`libs_ref_of`
    instead where the response is wanted for more than this one field.
    """
    return libs_ref_of(pdk_find(pdk, env=env, klt=klt, cwd=cwd, timeout=timeout))


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
