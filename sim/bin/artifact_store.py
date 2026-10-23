#!/usr/bin/env python3
"""Store a run's raw evidence in the fleet artifact store; commit only a manifest (issue #347).

New sim/signoff evidence bytes are private and live in the artifact store; git
keeps ``manifests/artifacts/<bench>-<run-id>.manifest.json`` (name, size,
sha256, ``artifact:<key>`` URI per object) and a Markdown summary
``sim/<bench>/artifacts/<run-id>.md``.  :func:`store_run` is the one writer:

1. :func:`preflight` -- ``$KLT_ARTIFACT_BROKER`` set and ``klt artifact put``
   available.  Callers run it before doing expensive work.
2. Raw files are copied into the git-ignored ``.artifact-staging/`` dir.
3. ``klt artifact put --manifest`` writes a manifest in the staging dir (never
   under ``manifests/``); entries are checked against the local bytes and by
   ``check_artifact_manifests``.
4. Only then are the manifest and summary published, without overwriting.

Fail closed: any failure raises :class:`ArtifactStoreError` with nothing
written under ``manifests/`` or ``sim/``; the staged bytes are kept for a
retry.  There is no fallback that commits the bytes.  The broker URL is read by
``klt`` from the environment; it is never put in argv, messages or files.

Stdlib + the ``klt`` executable.  Requires klayout-tools >= 7e3561f.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_artifact_manifests as cam  # noqa: E402

BROKER_ENV = "KLT_ARTIFACT_BROKER"
STAGING_DIR = cam.STAGING_DIR
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactStoreError(Exception):
    """The artifact store could not be used; nothing was committed-ready."""


@dataclass
class StoredRun:
    manifest: Path
    summary: Path
    entries: list[dict]


def _scrub(text: str, env) -> str:
    broker = (env.get(BROKER_ENV) or "").strip()
    return text.replace(broker, "<broker>") if broker else text


def preflight(klt: str = "klt", env=None) -> None:
    """Raise ArtifactStoreError unless a put can be attempted."""
    env = os.environ if env is None else env
    if not (env.get(BROKER_ENV) or "").strip():
        raise ArtifactStoreError(
            f"${BROKER_ENV} is unset; new evidence goes to the artifact store and there is no "
            "fallback that commits the bytes (sim/README.md, 'Artifact store')")
    if shutil.which(klt, path=env.get("PATH")) is None:
        raise ArtifactStoreError(f"{klt!r} not found on PATH (klayout-tools >= 7e3561f is required)")
    r = subprocess.run([klt, "artifact", "put", "--help"], capture_output=True, text=True, env=dict(env))
    if r.returncode != 0:
        raise ArtifactStoreError("this klt has no 'artifact put' (klayout-tools >= 7e3561f is required)")


def _sha_size(path: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def _publish(text: str, dst: Path) -> None:
    """Write `text` to `dst` without ever overwriting an existing file."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    stage = dst.with_name(f".{dst.name}.stage")
    stage.write_text(text)
    try:
        os.link(stage, dst)  # FileExistsError if dst exists
    finally:
        stage.unlink()


def summary_text(bench: str, run_id: str, manifest_rel: str, entries: list[dict]) -> str:
    lines = [
        f"# {bench} {run_id} -- stored evidence",
        "",
        "The raw outputs of this run are in the fleet artifact store, not in git.",
        f"Manifest: `{manifest_rel}`.  Check from a fleet worker with "
        f"`klt artifact verify {manifest_rel}`.",
        "",
        "| Name | Size (bytes) | sha256 |",
        "|---|---|---|",
    ]
    lines += [f"| `{e.get('name', '')}` | {e['size']} | `{e['sha256']}` |" for e in entries]
    return "\n".join(lines) + "\n"


def store_run(repo_root: Path, bench: str, run_id: str, files, *, klt: str = "klt", env=None) -> StoredRun:
    """Store `files` (a list of paths, unique basenames) for one run.  See the module docstring."""
    env = dict(os.environ if env is None else env)
    repo_root = Path(repo_root)
    for label, v in (("bench", bench), ("run id", run_id)):
        if not NAME_RE.match(v):
            raise ArtifactStoreError(f"invalid {label} {v!r}")
    paths = [Path(p) for p in files]
    if not paths:
        raise ArtifactStoreError("no files to store")
    seen: dict[str, Path] = {}
    for p in paths:
        if not p.is_file() or not os.access(p, os.R_OK):
            raise ArtifactStoreError(f"file {str(p)!r} is missing or unreadable")
        if p.name in seen:
            raise ArtifactStoreError(f"{str(seen[p.name])!r} and {str(p)!r} share the basename "
                                     f"{p.name!r}; supply uniquely named files")
        seen[p.name] = p

    stem = f"{bench}-{run_id}"
    manifest = repo_root / cam.MANIFEST_DIR / f"{stem}.manifest.json"
    summary = repo_root / "sim" / bench / "artifacts" / f"{run_id}.md"
    for out in (manifest, summary):
        if out.exists():
            raise ArtifactStoreError(f"{out.relative_to(repo_root)} already exists; evidence is append-only")
    staging = repo_root / STAGING_DIR / stem
    if staging.exists():
        raise ArtifactStoreError(f"staging dir {staging.relative_to(repo_root)} already exists from an "
                                 "earlier attempt; inspect it, remove it, and re-run")

    preflight(klt, env)

    staged = []
    try:
        staging.mkdir(parents=True)
    except FileExistsError:  # a concurrent writer for the same run id
        raise ArtifactStoreError(f"staging dir {staging.relative_to(repo_root)} was just created by "
                                 "another writer for this run id") from None
    for p in paths:
        shutil.copy2(p, staging / p.name)
        staged.append(staging / p.name)
    tmp_manifest = staging / "manifest.json"
    r = subprocess.run([klt, "artifact", "put", "--manifest", str(tmp_manifest), *map(str, staged)],
                       capture_output=True, text=True, cwd=repo_root, env=env)
    if r.returncode != 0:
        tail = _scrub((r.stderr or r.stdout).strip(), env)[-1000:]
        raise ArtifactStoreError(f"klt artifact put failed (exit {r.returncode}); nothing was "
                                 f"written, staged bytes kept in {staging.relative_to(repo_root)}: {tail}")
    try:
        doc = json.loads(tmp_manifest.read_text())
    except (OSError, ValueError) as exc:
        raise ArtifactStoreError(f"klt wrote no readable manifest: {exc}") from None

    by_name = {p.name: _sha_size(p) for p in staged}
    for e in doc.get("entries", []):
        base = Path(e.get("name", "")).name
        if base not in by_name or (e.get("sha256"), e.get("size")) != by_name[base]:
            raise ArtifactStoreError(f"manifest entry {e.get('name')!r} does not match the staged bytes")
        e["name"] = f"sim/{bench}/runs/{run_id}/{base}"
    if sorted(Path(e["name"]).name for e in doc.get("entries", [])) != sorted(by_name):
        raise ArtifactStoreError("manifest entries do not cover exactly the staged files")
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    problems, entries = cam.validate_manifest(text)
    if problems:
        raise ArtifactStoreError("klt produced an invalid manifest: " + "; ".join(problems))

    try:
        _publish(text, manifest)
    except FileExistsError:
        raise ArtifactStoreError(f"{manifest.relative_to(repo_root)} already exists") from None
    try:
        _publish(summary_text(bench, run_id, str(manifest.relative_to(repo_root)), entries), summary)
    except BaseException:
        manifest.unlink(missing_ok=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    try:
        (repo_root / STAGING_DIR).rmdir()
    except OSError:
        pass
    return StoredRun(manifest=manifest, summary=summary, entries=entries)
