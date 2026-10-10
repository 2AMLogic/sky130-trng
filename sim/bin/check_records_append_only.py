#!/usr/bin/env python3
"""PR-blocking guard for the sim/ append-only evidence rule (issue #232).

sim/README.md: a record under sim/<slug>/records/ is never edited or deleted
after it is written; a correction mints a new record that names the one it
supersedes via its `Supersedes` field.  This script fails when the diff
BASE...HEAD Modifies, Deletes, Renames (the old path counts as deleted) or
type-changes any existing file there.  Added files pass.

Issue #265 extends the same rule to the raw artifacts of a record: every
existing file, at any depth, under sim/<slug>/runs/<record-id>/ or
sim/<slug>/corners/<record-id>/ is protected when <record-id> names a record
in sim/<slug>/records/ of the PR's base tree (a record is <id>.md, <id>.json
or an <id>/ directory; deduplicated).  Association is by base tree, so
removing or renaming the record in the same PR does not unprotect its
artifacts.  New files/dirs pass.  Directories whose ID matches no record
(exact match only) are not protected.

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
ARTIFACT_RE = re.compile(r"^sim/([^/]+)/(?:runs|corners)/([^/]+)/.+")
BASE_RECORD_RE = re.compile(r"^sim/([^/]+)/records/([^/]+)(?:/.*)?$")
REMEDY = ("Records and the runs/corners artifacts of a record are append-only "
          "evidence. Do not edit/delete/rename; mint a new record (with a "
          "fresh runs/corners directory) whose `Supersedes` field names the "
          "one it corrects. A "
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


def base_record_ids(ls_tree_names):
    """Set of (slug, record-id) from newline-separated base-tree file paths."""
    ids = set()
    for line in ls_tree_names.splitlines():
        m = BASE_RECORD_RE.match(line)
        if m:
            name = m.group(2)
            for suf in (".md", ".json"):
                if name.endswith(suf):
                    name = name[: -len(suf)]
                    break
            ids.add((m.group(1), name))
    return ids


def is_protected(path, record_ids):
    if RECORD_RE.match(path):
        return True
    m = ARTIFACT_RE.match(path)
    return bool(m) and (m.group(1), m.group(2)) in record_ids


def violations(name_status_z, allow=frozenset(), record_ids=frozenset()):
    """Parse `git diff --name-status -z --no-renames` output."""
    toks = name_status_z.split("\0")
    bad = []
    i = 0
    while i + 1 < len(toks):
        status, path = toks[i], toks[i + 1]
        i += 2
        if status[:1] in "MDRT" and is_protected(path, record_ids) and path not in allow:
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
    t = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only",
         f"{base}", "--", "sim/"], capture_output=True, text=True)
    if t.returncode != 0:
        print(f"git ls-tree failed: {t.stderr.strip()}", file=sys.stderr)
        return 2
    bad = violations(r.stdout, load_allowlist(REPO / "sim" / ALLOWLIST.name), base_record_ids(t.stdout))
    if not bad:
        print("sim/*/{records,runs,corners}: append-only rule holds "
              "(no existing record or record artifact changed)")
        return 0
    print("append-only violation: existing sim record(s)/record artifact(s) "
          "changed:", file=sys.stderr)
    for s, p in bad:
        print(f"  {s}  {p}", file=sys.stderr)
    print(REMEDY, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
