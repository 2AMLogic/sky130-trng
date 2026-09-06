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
top of the same :func:`git_short_sha` this module already had, rather than
as a second, independent reimplementation of it.
"""

from __future__ import annotations

import datetime as _dt
import json
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
    out_records.mkdir(parents=True, exist_ok=True)
    md_path = out_records / f"{rid}.md"
    json_path = out_records / f"{rid}.json"
    if md_path.exists() or json_path.exists():
        print(f"error: record id {rid} already exists; wait a second and re-run",
              file=sys.stderr)
        return None

    footer = record_footer(author=author, now=now, sha=sha)
    md_path.write_text("\n".join(header) + body + "\n".join(footer) + "\n")
    json_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"\nrecord written: {md_path.relative_to(repo_root)}", file=sys.stderr)
    return md_path, json_path


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
    own ``rid`` (via :func:`git_short_sha`, same ``<YYYYMMDD>-<HHMMSS>-
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
    now = _dt.datetime.now(_dt.timezone.utc)
    sha = git_short_sha(repo_root)
    rid = f"{now:%Y%m%d-%H%M%S}-{sha}"
    records_dir = repo_root / "sim" / slug / "records"
    runs_dir = repo_root / "sim" / slug / "runs" / rid
    md_path = records_dir / f"{rid}.md"
    json_path = records_dir / f"{rid}.json"
    if md_path.exists() or json_path.exists() or runs_dir.exists():
        raise SystemExit(f"error: record id {rid} already exists under sim/{slug}/; "
                         "wait a second and re-run")
    records_dir.mkdir(parents=True, exist_ok=True)

    stored: list[str] = []
    if artifacts:
        runs_dir.mkdir(parents=True, exist_ok=True)
        for path in artifacts:
            path = Path(path)
            shutil.copy2(path, runs_dir / path.name)
            stored.append(f"sim/{slug}/runs/{rid}/{path.name}")

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

    md_path.write_text("\n".join(head) + body_md.rstrip("\n") + "\n" + "\n".join(tail))
    json_path.write_text(json.dumps({
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
        **summary,
    }, indent=2, sort_keys=False) + "\n")
    print(f"record written: {md_path.relative_to(repo_root)}", file=sys.stderr)
    return rid
