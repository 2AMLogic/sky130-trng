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
import gzip
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artifact_store  # noqa: E402


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


# Cap on the record's repo_dirty_paths list (issue #666): the JSON carries at
# most this many paths; the markdown footer always names the untruncated total.
_DIRTY_PATHS_CAP = 20


def git_dirty_paths(repo_root: Path) -> list[str] | None:
    """Sorted repo-relative paths whose content differs from HEAD (staged,
    unstaged, or non-ignored untracked), or ``None`` when git status cannot
    run -- the caller must record that as *unknown*, never as clean
    (issue #666).

    ``--porcelain -z`` keeps paths with spaces or other unusual characters
    unquoted and NUL-delimited. A rename/copy entry carries a second NUL
    field (the original path); it is listed too, since that path also
    differs from HEAD.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "-z",
             "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except Exception:
        return None
    paths: list[str] = []
    recs = out.split("\0")
    i = 0
    while i < len(recs):
        rec = recs[i]
        i += 1
        if not rec:
            continue  # trailing NUL / empty record
        code, path = rec[:2], rec[3:]
        paths.append(path)
        if ("R" in code or "C" in code) and i < len(recs):
            paths.append(recs[i])  # original path of the rename/copy pair
            i += 1
    return sorted(set(paths))


def new_record_id(repo_root: Path, *, offset: int = 0) -> tuple[_dt.datetime, str, str]:
    """Return `(now, sha, rid)` for a fresh record.

    `rid` follows the shared `<YYYYMMDD>-<HHMMSS>-<shortsha>` scheme
    `sim/bin/corner-run.py` uses, so reduction records and simulation
    records sort together. `offset` seconds are added to the clock so one
    run minting several records gets distinct ids (one per loop iteration,
    as the per-corner reducers do).
    """
    now = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=offset)
    sha = git_short_sha(repo_root)
    rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
    return now, sha, rid


def record_footer(*, author: str, now: _dt.datetime, sha: str,
                  supersedes: str = "(none)") -> list[str]:
    """The shared markdown footer lines appended to every evidence record.

    `supersedes` names the record id this one corrects (sim/README.md's
    append-only rule); the default is the no-correction marker, which keeps
    every pre-existing caller's footer byte-for-byte.
    """
    return [
        "",
        "---",
        "",
        f"- Author: {author}",
        f"- Timestamp (UTC): {now.isoformat()}",
        f"- Repo commit: `{sha}`",
        f"- Supersedes: {supersedes}",
    ]


class RecordCollision(Exception):
    """The record id is already taken (published, or reserved by another writer)."""


def _link_noreplace(src: Path, dst: Path) -> None:
    """Publish `src` as `dst` without ever overwriting (hard link, then unlink src)."""
    os.link(src, dst)  # raises FileExistsError if dst exists
    os.unlink(src)


def reserve_corner_dir(cdir: Path, records_dir: Path, rid: str) -> None:
    """Refuse (``SystemExit "error: <rid> exists"``) if ``<records_dir>/<rid>.json`` or `cdir` exists.

    Otherwise creates `records_dir` (if needed) and `cdir`; the `cdir` creation is
    ``Path.mkdir(exist_ok=False)``, so the check and the claim are one atomic step
    (not a check-then-write).
    """
    cdir, records_dir = Path(cdir), Path(records_dir)
    if (records_dir / f"{rid}.json").exists():
        raise SystemExit(f"error: {rid} exists")
    records_dir.mkdir(parents=True, exist_ok=True)
    try:
        cdir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(f"error: {rid} exists") from None


def write_corner_bundle(
    cdir: Path, reqdir: Path, chunks: list[tuple[str, dict, dict]],
    *, records_dir: Path, rid: str,
) -> list[str]:
    """Write the raw ``klt sim`` response bundle for one record under `cdir`.

    chunks = [(name, plan, response)]. Refuses (SystemExit "error: <rid> exists") if
    ``<records_dir>/<rid>.json`` or `cdir` exists; every source file under
    ``reqdir/<name>/`` is checked before anything is created, so a missing
    ``netlist.cir`` leaves nothing behind (and a failed write removes `cdir` again).
    Writes ``<name>.klt-sim.json.gz`` (indent=1), ``<name>.plan.json``,
    ``<name>.request.json`` and ``<name>.netlist.cir`` (copied from ``reqdir/<name>/``).
    Returns the remote job ids (or "local (single-unit reference run)").
    Read back with :func:`read_corner_bundle`.
    """
    cdir, reqdir, records_dir = Path(cdir), Path(reqdir), Path(records_dir)
    for name, _plan, _resp in chunks:
        for fn in ("request.json", "netlist.cir"):
            if not (reqdir / name / fn).is_file():
                raise SystemExit(f"error: {reqdir / name / fn} is missing")
    reserve_corner_dir(cdir, records_dir, rid)
    jobs: list[str] = []
    try:
        for name, plan, resp in chunks:
            with gzip.open(cdir / f"{name}.klt-sim.json.gz", "wt") as fh:
                json.dump(resp, fh, indent=1)
            with open(cdir / f"{name}.plan.json", "w") as fh:
                json.dump(plan, fh, indent=1)
            for fn, dst in (("request.json", f"{name}.request.json"), ("netlist.cir", f"{name}.netlist.cir")):
                shutil.copyfile(reqdir / name / fn, cdir / dst)
            jobs.append(((resp.get("environment", {}).get("remote") or {}).get("job_id")) or "local (single-unit reference run)")
    except BaseException:
        shutil.rmtree(cdir, ignore_errors=True)
        raise
    return jobs


def read_corner_bundle(
    cdir: Path, *, prefix: str | None = None, with_missing: bool = False,
) -> list[tuple[str, dict, dict]] | tuple[list, list]:
    """Read back a ``corners/<rid>/`` bundle written by :func:`write_corner_bundle`.

    The documented inverse of :func:`write_corner_bundle`, whose docstring is
    the on-disk layout this walks. Returns ``[(name, plan, response)]`` in
    sorted-name order, one entry per ``<name>.klt-sim.json.gz``; `plan` comes
    from the sibling ``<name>.plan.json`` and is loaded strictly -- these feed
    replay gates that must fail loudly on a malformed plan. ``prefix=`` keeps
    only names starting with it, applied to both the chunk names and the
    missing-note names. With ``with_missing=True`` returns
    ``(chunks, missing)`` instead, where `missing` is ``[(name, plan, reason)]``
    for the ``<name>.missing.json`` refused/timed-out-attempt notes recorded
    beside the bundle by a campaign runner (this module never writes those).
    """
    cdir = Path(cdir)
    chunks: list[tuple[str, dict, dict]] = []
    for f in sorted(cdir.glob("*.klt-sim.json.gz")):
        nm = f.name[: -len(".klt-sim.json.gz")]
        if prefix and not nm.startswith(prefix):
            continue
        with open(cdir / f"{nm}.plan.json") as pfh, gzip.open(f, "rt") as fh:
            chunks.append((nm, json.load(pfh), json.load(fh)))
    if not with_missing:
        return chunks
    missing: list[tuple[str, dict, str]] = []
    for f in sorted(cdir.glob("*.missing.json")):
        nm = f.name[: -len(".missing.json")]
        if prefix and not nm.startswith(prefix):
            continue
        with open(f) as fh:
            reason = json.load(fh)["reason"]
        with open(cdir / f"{nm}.plan.json") as pfh:
            missing.append((nm, json.load(pfh), reason))
    return chunks, missing


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
    supersedes: str = "(none)",
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
    positions; see each analysis script's `main()`). `supersedes` names the
    record id this one corrects; the default footer line is unchanged.

    Returns `(md_path, json_path)` on success, or `None` (after printing an
    error to stderr) if a record with this `rid` already exists.
    """
    md_path = out_records / f"{rid}.md"
    json_path = out_records / f"{rid}.json"
    if md_path.exists() or json_path.exists():
        print(f"error: record id {rid} already exists; wait a second and re-run",
              file=sys.stderr)
        return None

    footer = record_footer(author=author, now=now, sha=sha, supersedes=supersedes)
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
    "timestamp_utc", "repo_sha", "repo_dirty", "repo_dirty_paths", "tools",
    "artifacts", "artifact_manifest",
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
    * raw run artifacts stored in the fleet artifact store (issue #347):
      only ``manifests/artifacts/<slug>-<id>.manifest.json`` and the summary
      ``sim/<slug>/artifacts/<id>.md`` are committed, never the bytes. Fail
      closed -- no broker, no ``klt artifact put`` or an unreachable broker
      aborts with nothing written; there is no committing fallback (see
      ``sim/bin/artifact_store.py``);
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
    # Working-tree state at pin time, sampled once here -- before the
    # artifact store or publication writes anything -- so this invocation's
    # own outputs (always untracked at mint time) cannot mask real
    # divergence from HEAD, and a dirty tree is disclosed in the record
    # instead of silently hiding behind the HEAD pin (issue #666).
    dirty_paths = git_dirty_paths(repo_root)
    if dirty_paths is None:
        dirty_fields: dict = {"repo_dirty": None}
        worktree_line = "- Working tree: unknown (git status unavailable; repo_dirty is null)"
    elif not dirty_paths:
        dirty_fields = {"repo_dirty": False}
        worktree_line = "- Working tree: clean (matches the cited commit)"
    else:
        n = len(dirty_paths)
        listed = dirty_paths[:_DIRTY_PATHS_CAP]
        dirty_fields = {"repo_dirty": True, "repo_dirty_paths": listed}
        noun = "path" if n == 1 else "paths"
        verb = "differs" if n == 1 else "differ"
        stem = f"- Working tree: dirty ({n} {noun} {verb} from the cited commit"
        worktree_line = (stem + f"; repo_dirty_paths lists the first {_DIRTY_PATHS_CAP})"
                         if n > _DIRTY_PATHS_CAP else stem + ")")
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
    manifest_rel = f"manifests/artifacts/{slug}-{rid}.manifest.json"
    if art_paths:  # fail closed before any record output exists
        try:
            artifact_store.preflight()
        except artifact_store.ArtifactStoreError as exc:
            raise SystemExit(f"error: {exc}") from None

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
        worktree_line,
        f"- Tools: {json.dumps(tool_block)}",
    ]
    if stored:
        tail += [f"- Artifacts (stored in the artifact store, manifest `{manifest_rel}`):"]
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
        **dirty_fields,
        "tools": tool_block,
        "artifacts": stored,
        "artifact_manifest": manifest_rel if stored else None,
        **(summary or {}),
    }, indent=2, sort_keys=False) + "\n"  # serialize before touching the filesystem
    run = None
    if art_paths:
        try:
            run = artifact_store.store_run(repo_root, slug, rid, art_paths)
        except artifact_store.ArtifactStoreError as exc:
            raise SystemExit(f"error: {exc}") from None
    try:
        _publish_bundle(records_dir, rid, md_text, json_text, what="record")
    except BaseException as exc:
        if run is not None:  # the objects stay in the store; drop the manifest this call wrote
            run.manifest.unlink(missing_ok=True)
            run.summary.unlink(missing_ok=True)
        if isinstance(exc, RecordCollision):
            raise SystemExit(f"error: {exc} (under sim/{slug}/)") from None
        raise
    print(f"record written: {md_path.relative_to(repo_root)}", file=sys.stderr)
    return rid
