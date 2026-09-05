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
"""

from __future__ import annotations

import datetime as _dt
import json
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
