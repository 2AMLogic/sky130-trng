#!/usr/bin/env python3
"""Keep spec/README.md's decision-record index tied to the records (issue #296).
Stdlib only, no PDK.

Fails (exit 1) when:
  * a spec/decision-records/DR-NNNN-*.md file is not linked from the index;
  * an index link to decision-records/ points at a missing file;
  * an index entry's status word is not one of STATUS_WORDS (a typo or an
    invented word must not be silently normalised away);
  * a record's `status:` front matter and the index disagree on status
    (Proposed vs Accepted/Ratified).  The front matter is authoritative.
    The index must never overstate: an index that says Accepted/Ratified for
    a record still Proposed is the serious case, but any disagreement fails;
  * a record carries no `status:` front matter, or one outside STATUS_WORDS
    (never a silent fallback to the `## Status` history -- that fallback is
    what let a stale index pass, issue #484);
  * a record contradicts itself: its `status:` front matter and the latest
    entry of its own `## Status` history disagree;
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
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)^---[ \t]*$", re.S | re.M)
FM_STATUS_RE = re.compile(r"^status:[ \t]*(\S+)[ \t]*$", re.M)
SECTION_RE = re.compile(r"^## Status\s*\n(.*?)(?=^## |\Z)", re.S | re.M)
STATUS_WORD_RE = re.compile(r"\*\*(%s)\b" % "|".join(STATUS_WORDS))


def _norm(word):
    return "Proposed" if word.lower() == "proposed" else "Accepted"


def record_status(text):
    """Return (front_matter_status, latest_status_entry) as raw status words.

    Either element is None when the record does not carry it.  The
    front-matter `status:` field is the authoritative one -- spec/README.md
    and every human reader treat it so -- and it is returned separately from
    the `## Status` history precisely so the caller can check that the two
    agree.

    The history value is the *last* bold status word in `## Status`, not the
    first.  DR-0017's section is a dated history that opens `**Proposed.**`
    (2026-11-03) and closes `**Accepted**` (2026-11-05); taking the first
    match made this checker agree with a stale index (issue #484).  Its
    middle entry reads `**Amended, still Proposed**` -- the bold run starts
    with "Amended", so it does not match STATUS_WORD_RE at all and is
    correctly skipped.
    """
    fm = None
    m = FRONT_MATTER_RE.match(text)
    if m:
        f = FM_STATUS_RE.search(m.group(1))
        if f:
            fm = f.group(1).rstrip(".")
    latest = None
    m = SECTION_RE.search(text)
    if m:
        found = STATUS_WORD_RE.findall(m.group(1))
        if found:
            latest = found[-1]
    return fm, latest


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
        if idx.lower() not in {w.lower() for w in STATUS_WORDS}:
            errs.append("index entry for %s has unknown status **%s** (expected "
                        "one of %s)" % (name, idx, "/".join(STATUS_WORDS)))
            continue
        fm, latest = record_status((recdir / name).read_text(encoding="utf-8"))
        if fm is None:
            errs.append("%s has no `status:` front matter (a record must "
                        "declare its own status; the ## Status history is "
                        "not a fallback)" % name)
            continue
        if fm.lower() not in {w.lower() for w in STATUS_WORDS}:
            errs.append("%s has unknown front-matter status `%s` (expected "
                        "one of %s)" % (name, fm, "/".join(STATUS_WORDS)))
            continue
        if latest is None:
            errs.append("%s has no recognizable ## Status" % name)
        elif _norm(fm) != _norm(latest):
            errs.append("%s front matter says %s but the latest entry of its "
                        "own ## Status history says %s" % (name, fm, latest))
        if _norm(idx) != _norm(fm):
            over = " (index overstates)" if _norm(idx) == "Accepted" else ""
            errs.append("status mismatch for %s: index %s, record %s%s"
                        % (name, idx, fm, over))

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
