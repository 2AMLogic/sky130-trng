#!/usr/bin/env python3
"""Append-only record minting for **behavioural** evidence.

``sim/bin/corner-run.py`` mints records for ngspice runs. Everything
downstream of the raw tap is a behavioural model, not a SPICE deck
(``spec/porting-plan.md`` §1.1, gf180-trng DR-0009), so those runs need the
same record trail without going anywhere near a simulator. This module is
that half of the harness -- a library, not a runner: each behavioural
testbench under ``sim/<slug>/harness/`` or ``sim/<slug>/analysis/`` calls
:func:`mint_record` with what it measured.

It keeps every rule ``sim/README.md`` states for the SPICE path:

* record id ``<YYYYMMDD>-<HHMMSS>-<shortsha>``, never reused -- minting
  refuses to start if the id already exists;
* one ``.md`` (human) plus one ``.json`` (machine) per record;
* a ``level:`` field on every record (here always a ``behavioral`` flavour);
* every stochastic run states every seed;
* raw run artifacts committed alongside, under ``sim/<slug>/runs/<id>/``
  (``.txt``, not ``.log`` -- the repository's ``.gitignore`` exempts only
  ``sim/*/corners/**/*.log``, and these are not corner logs);
* append-only: a correction mints a new record and names the one it
  supersedes.
"""

from __future__ import annotations

import datetime as _dt
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def git_short_sha() -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip() or "unknown"
    except Exception:  # pragma: no cover - only when git is unavailable
        return "unknown"


def record_id(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return f"{now:%Y%m%d-%H%M%S}-{git_short_sha()}"


def mint_record(slug: str, claim: str, body_md: str, summary: dict, *,
                level: str = "behavioral",
                seeds: dict | None = None,
                artifacts: list[Path] | None = None,
                tools: dict | None = None,
                supersedes: str | None = None,
                author: str = "loom-builder@sky130-trng") -> str:
    """Write one append-only behavioural record. Returns its record id."""
    now = _dt.datetime.now(_dt.timezone.utc)
    rid = record_id(now)
    records_dir = REPO_ROOT / "sim" / slug / "records"
    runs_dir = REPO_ROOT / "sim" / slug / "runs" / rid
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
        f"- Repo commit: `{git_short_sha()}`",
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
        "repo_sha": git_short_sha(),
        "tools": tool_block,
        "artifacts": stored,
        **summary,
    }, indent=2, sort_keys=False) + "\n")
    print(f"record written: {md_path.relative_to(REPO_ROOT)}", file=sys.stderr)
    return rid
