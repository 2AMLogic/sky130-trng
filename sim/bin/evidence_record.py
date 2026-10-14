#!/usr/bin/env python3
"""Shared "mint an append-only evidence record" scaffolding.

Every reduction script under ``sim/*/analysis/`` (e.g.
``sim/ro-array-sizing/analysis/array-sizing.py``,
``sim/ro-array-operating-point/analysis/operating-point.py``) is pure
arithmetic over already-committed evidence that, on ``--emit-record``, mints
a markdown+JSON pair under ``sim/<slug>/records/<rid>.{md,json}`` -- the same
``<YYYYMMDD>-<HHMMSS>-<shortsha>`` id scheme ``sim/bin/corner-run.py`` uses,
append-only (refuses to overwrite an existing id).

That scaffolding -- ``git_short_sha()``, record-id generation, the
``OUT_RECORDS.mkdir`` + collision guard, the shared markdown footer, and the
final JSON write -- was independently duplicated (and had already drifted:
one call site's ``json.dumps`` was missing ``default=str``) across each
reduction script before this module existed (see issue #26). This module is
the one place that owns it going forward; new reductions should use it
rather than re-copying the pattern.

Each reduction script still owns its own markdown header (claim text, source
record listing) and JSON summary content -- those differ genuinely between
reductions -- so this module's contract is deliberately narrow: give it a
record id, an already-assembled header/body/summary, and it handles the
common tail.

:func:`mint_behavioral_record` is the second flavour of this scaffolding.
``sim/bin/corner-run.py`` mints records for ngspice runs; everything
downstream of the raw tap is a behavioural model, not a SPICE deck
(``spec/porting-plan.md`` §1.1, gf180-trng DR-0009), so those runs need the
same record trail without going anywhere near a simulator. It was
introduced as a separate module, ``sim/bin/behavioral_record.py`` (see
issue #31), which re-duplicated the id/collision-guard/footer logic this
module already owned (see issue #39) under a single-call, higher-level API
convenient for ``sim/*/harness/`` scripts: it derives the record id
internally, embeds ``seeds``/``artifacts``/``tools``/``level`` fields, and
appends the "Provisional, simulation-derived" CLAUDE.md disclaimer block.
That convenience API now lives here as ``mint_behavioral_record``, built on
top of the same :func:`new_record_id` this module already had, rather than
as a second, independent reimplementation of it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def git_short_sha(repo_root: Path) -> str:
    """Return the short SHA of HEAD in `repo_root`, or "unknown" on failure."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def new_record_id(repo_root: Path) -> tuple[_dt.datetime, str, str]:
    """Return `(now, sha, rid)` for a fresh record.

    `rid` follows the shared `<YYYYMMDD>-<HHMMSS>-<shortsha>` scheme
    `sim/bin/corner-run.py` uses, so reduction records and simulation
    records sort together.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    sha = git_short_sha(repo_root)
    rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
    return now, sha, rid


def record_footer(*, author: str, now: _dt.datetime, sha: str) -> list[str]:
    """The shared markdown footer lines appended to every evidence record."""
    return [
        "",
        "---",
        "",
        f"- Author: {author}",
        f"- Timestamp (UTC): {now.isoformat()}",
        f"- Repo commit: `{sha}`",
        "- Supersedes: (none)",
    ]


class RecordCollision(Exception):
    """The record id is already taken (published, or reserved by another writer)."""


def _link_noreplace(src: Path, dst: Path) -> None:
    """Publish `src` as `dst` without ever overwriting (hard link, then unlink src)."""
    os.link(src, dst)  # raises FileExistsError if dst exists
    os.unlink(src)


def _check_artifacts(artifacts: list[Path]) -> None:
    for path in artifacts:
        if not (path.is_file() and os.access(path, os.R_OK)):
            raise SystemExit(f"error: artifact {str(path)!r} is missing or unreadable")


def _publish_bundle(
    records_dir: Path,
    rid: str,
    md_text: str,
    json_text: str,
    *,
    runs_dir: Path | None = None,
    artifacts: list[Path] | None = None,
    what: str,
) -> tuple[Path, Path]:
    """Publish one evidence bundle (md + json [+ runs dir]) for `rid`.

    Completion boundary and recovery
    --------------------------------
    All payloads are fully serialized by the caller before this is called.
    The id is then reserved exclusively with ``os.open(O_CREAT|O_EXCL)`` on
    ``<records_dir>/.<rid>.reserve``; a second writer for the same id fails
    with :class:`RecordCollision`. Payloads and copied artifacts are staged
    next to their final locations (same filesystem) and published in this
    order: artifacts directory, then ``<rid>.json``, then ``<rid>.md``. Each
    step refuses to overwrite. The bundle is COMPLETE only once ``<rid>.md``
    exists; the ``.md`` is published last. Separate renames are not one
    atomic transaction: if the process is killed (SIGKILL, power loss)
    between steps, a partial bundle can remain. On an ordinary exception
    this function removes exactly what this invocation created (staged
    files, anything it already published, its reservation) and re-raises.
    After a hard kill the leftover ``.<rid>.reserve`` makes later writers
    refuse that id with a message naming it; recovery is to delete the
    ``.<rid>.reserve`` file, any ``.<rid>.*`` staging leftovers, and any
    partial ``<rid>.json`` / ``runs/<rid>/`` that has no ``<rid>.md``.
    Complete (``.md`` present) records are never touched.
    """
    records_dir.mkdir(parents=True, exist_ok=True)
    md_path = records_dir / f"{rid}.md"
    json_path = records_dir / f"{rid}.json"
    reserve = records_dir / f".{rid}.reserve"
    stage_md = records_dir / f".{rid}.md.stage"
    stage_json = records_dir / f".{rid}.json.stage"
    stage_runs = runs_dir.parent / f".{rid}.runs.stage" if runs_dir else None

    try:
        fd = os.open(reserve, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise RecordCollision(
            f"record id {rid} is already reserved by another writer or an interrupted "
            f"attempt ({reserve.name}); wait a second and re-run, or see "
            "_publish_bundle docs for recovery") from None
    owned_files: list[Path] = []  # created by this invocation, removed on failure
    owned_dirs: list[Path] = []
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(f"pid={os.getpid()}\n")
        if (md_path.exists() or json_path.exists()
                or (runs_dir is not None and runs_dir.exists())):
            raise RecordCollision(f"record id {rid} already exists")

        stage_md.write_text(md_text)
        owned_files.append(stage_md)
        stage_json.write_text(json_text)
        owned_files.append(stage_json)
        if runs_dir is not None and artifacts:
            stage_runs.mkdir(parents=True)
            owned_dirs.append(stage_runs)
            for path in artifacts:
                shutil.copy2(path, stage_runs / path.name)

        if stage_runs is not None and artifacts:
            os.rename(stage_runs, runs_dir)  # fails if runs_dir is a non-empty dir
            owned_dirs.remove(stage_runs)
            owned_dirs.append(runs_dir)
        _link_noreplace(stage_json, json_path)
        owned_files.remove(stage_json)
        owned_files.append(json_path)
        _link_noreplace(stage_md, md_path)
        owned_files.remove(stage_md)
        owned_files.append(md_path)
    except BaseException:
        for f in owned_files:
            try:
                f.unlink()
            except OSError:
                pass
        for d in owned_dirs:
            shutil.rmtree(d, ignore_errors=True)
        raise
    finally:
        try:
            reserve.unlink()
        except OSError:
            pass
    return md_path, json_path


def mint_record(
    out_records: Path,
    repo_root: Path,
    rid: str,
    header: list[str],
    body: str,
    summary: dict,
    *,
    author: str,
    now: _dt.datetime,
    sha: str,
) -> tuple[Path, Path] | None:
    """Mint an append-only evidence record under `out_records`.

    Owns: `out_records.mkdir`, the `md_path`/`json_path` collision guard
    (refusing to overwrite an existing `rid`), the shared markdown footer,
    and the final `json.dumps(..., indent=2, default=str)` write plus the
    "record written" stderr print.

    `header` and `body` are the caller's already-assembled markdown content
    (the footer is appended by this function); `summary` is the caller's
    already-assembled JSON summary dict, in whatever key order the caller
    wants (this function writes it as-is -- it does not inject `record_id`/
    `author`/`timestamp_utc`/`repo_sha`, since those are typically
    interleaved with reduction-specific fields at call-site-chosen
    positions; see each analysis script's `main()`).

    Returns `(md_path, json_path)` on success, or `None` (after printing an
    error to stderr) if a record with this `rid` already exists.
    """
    md_path = out_records / f"{rid}.md"
    json_path = out_records / f"{rid}.json"
    if md_path.exists() or json_path.exists():
        print(f"error: record id {rid} already exists; wait a second and re-run",
              file=sys.stderr)
        return None

    footer = record_footer(author=author, now=now, sha=sha)
    md_text = "\n".join(header) + body + "\n".join(footer) + "\n"
    json_text = json.dumps(summary, indent=2, default=str) + "\n"  # before any publication
    try:
        _publish_bundle(out_records, rid, md_text, json_text, what="record")
    except RecordCollision as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    print(f"\nrecord written: {md_path.relative_to(repo_root)}", file=sys.stderr)
    return md_path, json_path


# JSON fields the writer itself owns in mint_behavioral_record(); a caller
# summary may not use any of these names (issue #276).
RESERVED_BEHAVIORAL_KEYS = (
    "record_id", "slug", "level", "claim", "seeds", "supersedes", "author",
    "timestamp_utc", "repo_sha", "tools", "artifacts",
)


def mint_behavioral_record(
    repo_root: Path,
    slug: str,
    claim: str,
    body_md: str,
    summary: dict,
    *,
    level: str = "behavioral",
    seeds: dict | None = None,
    artifacts: list[Path] | None = None,
    tools: dict | None = None,
    supersedes: str | None = None,
    author: str = "loom-builder@sky130-trng",
) -> str:
    """Write one append-only behavioural record. Returns its record id.

    The single-call counterpart to :func:`mint_record` above: it derives its
    own ``rid`` (via :func:`new_record_id`, same ``<YYYYMMDD>-<HHMMSS>-
    <shortsha>`` scheme), assembles its own markdown header/footer -- with a
    ``Level``/``Seeds``/``Supersedes`` preamble, an optional copied-artifacts
    section, and the "Provisional, simulation-derived" CLAUDE.md disclaimer
    -- and writes the ``.md``/``.json`` pair under
    ``sim/<slug>/records/<rid>.{md,json}``, refusing to overwrite an
    existing id. Used by behavioural harnesses under ``sim/*/harness/`` and
    ``sim/*/analysis/`` that don't go anywhere near ngspice (see
    ``spec/porting-plan.md`` §1.1, gf180-trng DR-0009) but still owe the same
    record trail ``sim/bin/corner-run.py`` keeps for SPICE runs, including:

    * a ``level:`` field on every record (here always a ``behavioral``
      flavour);
    * every stochastic run states every seed;
    * raw run artifacts committed alongside, under
      ``sim/<slug>/runs/<id>/`` (``.txt``, not ``.log`` -- the repository's
      ``.gitignore`` exempts only ``sim/*/corners/**/*.log``, and these are
      not corner logs);
    * append-only: a correction mints a new record and names the one it
      supersedes.
    """
    # Writer-owned metadata must not be overridden by the caller's summary:
    # the markdown and returned id would disagree with the JSON (issue #276).
    # Checked first, before any id is minted or anything is created.
    clash = sorted(set(summary or {}) & set(RESERVED_BEHAVIORAL_KEYS))
    if clash:
        raise SystemExit(f"error: summary keys {clash} collide with writer-owned record "
                         f"metadata {list(RESERVED_BEHAVIORAL_KEYS)}; rename them or pass the "
                         "value through the matching mint_behavioral_record argument")

    now, sha, rid = new_record_id(repo_root)
    records_dir = repo_root / "sim" / slug / "records"
    runs_dir = repo_root / "sim" / slug / "runs" / rid
    md_path = records_dir / f"{rid}.md"
    json_path = records_dir / f"{rid}.json"
    if md_path.exists() or json_path.exists() or runs_dir.exists():
        raise SystemExit(f"error: record id {rid} already exists under sim/{slug}/; "
                         "wait a second and re-run")

    # Artifacts are stored flat under runs/<rid>/ by basename, so two inputs
    # sharing a basename (or one input listed twice) would silently overwrite
    # each other while the record still listed both. Refuse before creating
    # any record or run directory (issue #273).
    seen: dict[str, Path] = {}
    for path in artifacts or []:
        path = Path(path)
        prior = seen.get(path.name)
        if prior is not None:
            if prior.resolve() == path.resolve():
                raise SystemExit(f"error: artifact {str(path)!r} is supplied more than once; "
                                 "list each source file once")
            raise SystemExit(f"error: artifacts {str(prior)!r} and {str(path)!r} share the "
                             f"basename {path.name!r} and would overwrite each other in "
                             f"sim/{slug}/runs/{rid}/; supply uniquely named files")
        seen[path.name] = path

    art_paths = [Path(p) for p in artifacts or []]
    _check_artifacts(art_paths)
    stored = [f"sim/{slug}/runs/{rid}/{p.name}" for p in art_paths]

    tool_block = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    tool_block.update(tools or {})

    head = [
        f"# {rid} -- {slug}",
        "",
        f"**Claim**: {claim}",
        "",
        f"**Level**: {level}",
        f"**Seeds**: {json.dumps(seeds) if seeds else 'N/A (deterministic run; no stochastic input)'}",
        f"**Supersedes**: {supersedes or '(none)'}",
        "",
        "---",
        "",
    ]
    tail = [
        "",
        "---",
        "",
        "## Provenance",
        "",
        f"- Author: {author}",
        f"- Timestamp (UTC): {now.isoformat()}",
        f"- Repo commit: `{sha}`",
        f"- Tools: {json.dumps(tool_block)}",
    ]
    if stored:
        tail += ["- Artifacts (committed alongside this record):"]
        tail += [f"  - `{p}`" for p in stored]
    tail += [
        "",
        "> **Provisional, simulation-derived.** Nothing in this record is a "
        "measurement of silicon, and nothing in it is an SP 800-90B entropy "
        "assessment. Per the root `CLAUDE.md`, simulation-derived entropy "
        "claims stay provisional until measured on silicon.",
        "",
    ]

    md_text = "\n".join(head) + body_md.rstrip("\n") + "\n" + "\n".join(tail)
    json_text = json.dumps({
        "record_id": rid,
        "slug": slug,
        "level": level,
        "claim": claim,
        "seeds": seeds or {},
        "supersedes": supersedes,
        "author": author,
        "timestamp_utc": now.isoformat(),
        "repo_sha": sha,
        "tools": tool_block,
        "artifacts": stored,
        **(summary or {}),
    }, indent=2, sort_keys=False) + "\n"  # serialize before touching the filesystem
    try:
        _publish_bundle(records_dir, rid, md_text, json_text,
                        runs_dir=runs_dir, artifacts=art_paths, what="record")
    except RecordCollision as exc:
        raise SystemExit(f"error: {exc} (under sim/{slug}/)") from None
    print(f"record written: {md_path.relative_to(repo_root)}", file=sys.stderr)
    return rid
