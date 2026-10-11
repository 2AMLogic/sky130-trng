#!/usr/bin/env python3
"""Keep docs/friction-ledger.md covering every klayout-tools issue the tree
cites (issue #295).  Stdlib only, offline: validates ledger coverage, not
upstream state.

Fails (exit 1) when a `klayout-tools#N` or `klayout-tools/issues/N`
reference anywhere in the tree (excluding the ledger itself, .git and the
vendored .loom/ tooling) has no row in the ledger table, or the ledger is
missing.

Usage: check_friction_ledger.py [--root DIR]
"""
import argparse
import os
import re
import sys
from pathlib import Path

LEDGER = "docs/friction-ledger.md"
REF_RE = re.compile(rb"klayout-tools(?:/issues/|#)(\d+)")
ROW_RE = re.compile(r"^\|\s*\[#(\d+)\]", re.M)
SKIP_DIRS = {".git", ".loom", "node_modules", "__pycache__"}


def referenced(root):
    refs = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            p = Path(dp) / fn
            rel = p.relative_to(root).as_posix()
            if rel == LEDGER:
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            for m in REF_RE.finditer(data):
                refs.setdefault(int(m.group(1)), rel)
    return refs


def check(root):
    root = Path(root)
    led = root / LEDGER
    if not led.is_file():
        return ["%s is missing" % LEDGER]
    listed = {int(n) for n in ROW_RE.findall(led.read_text(encoding="utf-8"))}
    refs = referenced(root)
    return ["klayout-tools#%d (first seen in %s) has no row in %s"
            % (n, refs[n], LEDGER) for n in sorted(refs) if n not in listed]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    errs = check(args.root)
    for e in errs:
        print("FAIL: " + e, file=sys.stderr)
    if errs:
        return 1
    print("friction ledger covers every cited klayout-tools issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
