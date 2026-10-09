#!/usr/bin/env python3
"""PR-blocking guard for the sim/ append-only evidence rule (issue #232).

sim/README.md: a record under sim/<slug>/records/ is never edited or deleted
after it is written; a correction mints a new record that names the one it
supersedes via its `Supersedes` field.  This script fails when the diff
BASE...HEAD Modifies, Deletes, Renames (the old path counts as deleted) or
type-changes any existing file there.  Added files pass.

Stdlib + git only.  Usage:  check_records_append_only.py [BASE_REF]
(default origin/main).  A sanctioned exception goes in
sim/records-append-only-allowlist.txt (one repo-relative path per line, '#'
comments) -- a reviewed diff to that file, not a bypass.
Exit: 0 ok, 1 violation, 2 usage/git error.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO / "sim" / "records-append-only-allowlist.txt"
RECORD_RE = re.compile(r"^sim/[^/]+/records/.+")
REMEDY = ("Records are append-only evidence. Do not edit/delete/rename; mint a "
          "new record whose `Supersedes` field names the one it corrects. A "
          "sanctioned exception must be listed in "
          "sim/records-append-only-allowlist.txt (reviewed).")


def load_allowlist(path=ALLOWLIST):
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def violations(name_status_z, allow=frozenset()):
    """Parse `git diff --name-status -z --no-renames` output."""
    toks = name_status_z.split("\0")
    bad = []
    i = 0
    while i + 1 < len(toks):
        status, path = toks[i], toks[i + 1]
        i += 2
        if status[:1] in "MDRT" and RECORD_RE.match(path) and path not in allow:
            bad.append((status[:1], path))
    return bad


def main(argv):
    base = argv[1] if len(argv) > 1 else "origin/main"
    r = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--name-status", "-z", "--no-renames",
         f"{base}...HEAD", "--", "sim/"],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(f"git diff failed: {r.stderr.strip()}", file=sys.stderr)
        return 2
    bad = violations(r.stdout, load_allowlist())
    if not bad:
        print("sim/*/records: append-only rule holds (no existing record changed)")
        return 0
    print("append-only violation: existing sim record(s) changed:", file=sys.stderr)
    for s, p in bad:
        print(f"  {s}  {p}", file=sys.stderr)
    print(REMEDY, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
