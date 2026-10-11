#!/usr/bin/env python3
"""Keep spec/README.md's decision-record index tied to the records (issue #296).
Stdlib only, no PDK.

Fails (exit 1) when:
  * a spec/decision-records/DR-NNNN-*.md file is not linked from the index;
  * an index link to decision-records/ points at a missing file;
  * a record's `## Status` section and the index disagree on status
    (Proposed vs Accepted/Ratified).  The index must never overstate: an
    index that says Accepted/Ratified for a record still Proposed is the
    serious case, but any disagreement fails;
  * a number between DR-0001 and the highest record is absent and not named
    in ALLOWED_GAPS (so a skipped number is a decision, not an accident).

Read-only: never edits a record or its status.

Usage: check_spec_index.py [--root DIR]
"""
import argparse
import re
import sys
from pathlib import Path

# Deliberately unassigned numbers.  DR-0013 is held by the open #221 proposal.
ALLOWED_GAPS = {13}

LINK_RE = re.compile(r"\]\((decision-records/[^)\s]+)\)")
ENTRY_RE = re.compile(r"\[`decision-records/(DR-(\d{4})-[^`]*\.md)`\]"
                      r"\(decision-records/[^)]+\)\s*\n\s*(?:—|--|-)\s*"
                      r"\*\*([A-Za-z]+)\*\*")
FILE_RE = re.compile(r"^DR-(\d{4})-.+\.md$")
STATUS_WORDS = ("Proposed", "Accepted", "Ratified")


def _norm(word):
    return "Proposed" if word.lower() == "proposed" else "Accepted"


def record_status(text):
    m = re.search(r"^## Status\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        return None
    found = re.search(r"\*\*(Proposed|Accepted|Ratified)\b", m.group(1))
    return _norm(found.group(1)) if found else None


def check(root):
    root = Path(root)
    errs = []
    readme = root / "spec" / "README.md"
    recdir = root / "spec" / "decision-records"
    if not readme.is_file():
        return ["spec/README.md is missing"]
    text = readme.read_text(encoding="utf-8")

    files = {}
    if recdir.is_dir():
        for f in sorted(recdir.iterdir()):
            m = FILE_RE.match(f.name)
            if m:
                files[f.name] = int(m.group(1))

    linked = {Path(l).name for l in LINK_RE.findall(text)}
    for name in sorted(files):
        if name not in linked:
            errs.append("record not indexed in spec/README.md: %s" % name)
    for name in sorted(linked):
        if name not in files:
            errs.append("index link to missing record: decision-records/%s"
                        % name)

    entries = {m.group(1): m.group(3) for m in ENTRY_RE.finditer(text)}
    for name in sorted(files):
        if name not in linked:
            continue
        idx = entries.get(name)
        if idx is None:
            errs.append("index entry for %s has no **Status** marker" % name)
            continue
        rec = record_status((recdir / name).read_text(encoding="utf-8"))
        if rec is None:
            errs.append("%s has no recognizable ## Status" % name)
        elif _norm(idx) != rec:
            over = " (index overstates)" if _norm(idx) == "Accepted" else ""
            errs.append("status mismatch for %s: index %s, record %s%s"
                        % (name, idx, rec, over))

    nums = set(files.values())
    if nums:
        for n in range(1, max(nums) + 1):
            if n not in nums and n not in ALLOWED_GAPS:
                errs.append("unlisted numbering gap: DR-%04d (add to "
                            "ALLOWED_GAPS only by decision)" % n)
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    errs = check(args.root)
    for e in errs:
        print("FAIL: " + e, file=sys.stderr)
    if errs:
        return 1
    print("spec/README.md decision-record index consistent with the records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
