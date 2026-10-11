#!/usr/bin/env python3
"""Keep REPRODUCE.md tied to the tree (issue #292).  Stdlib only, no PDK.

Fails (exit 1) when:
  * a repo path REPRODUCE.md names does not exist (prose, code blocks, and
    file names in the table rows of a `sim/<dir>/` first column, resolved
    relative to that directory);
  * a sim/<slug>/ directory holding minted records (a non-empty records/) is
    not named in REPRODUCE.md;
  * design/pdk.json, sim/pdk.json and layout/pdk.json disagree on variant,
    open_pdks_commit or install_command;
  * REPRODUCE.md does not state the pinned open_pdks commit or the klt pin
    from layout/pdk.json.

Usage: check_reproduce.py [--root DIR]
"""
import argparse
import json
import re
import sys
from pathlib import Path

TOP = r"(?:design|digital|layout|sim|spec|signoff|docs|measurements|tools|\.github)"
PATH_RE = re.compile(r"(?<![\w/.-])(" + TOP + r"/[\w./-]*)")
TICK_RE = re.compile(r"`([^`\n]+)`")
BARE_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)*$")
PIN_FILES = ("design/pdk.json", "sim/pdk.json", "layout/pdk.json")
PIN_KEYS = ("variant", "open_pdks_commit", "install_command")


def _clean(tok):
    return tok.rstrip(".,;:)")


def check(root):
    root = Path(root)
    errs = []
    doc_path = root / "REPRODUCE.md"
    if not doc_path.is_file():
        return ["REPRODUCE.md is missing"]
    text = doc_path.read_text(encoding="utf-8")

    seen = set()
    for m in PATH_RE.finditer(text):
        p = _clean(m.group(1))
        if p and p not in seen:
            seen.add(p)
            if not (root / p).exists():
                errs.append("dangling reference: %s" % p)

    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.lstrip().startswith("|") or not cells:
            continue
        first = TICK_RE.findall(cells[0])
        if len(first) != 1 or not re.fullmatch(r"sim/[\w.-]+/", first[0]):
            continue
        base = first[0]
        for cell in cells[1:]:
            for tok in TICK_RE.findall(cell):
                if (BARE_RE.match(tok) and ("." in tok or "/" in tok)
                        and not PATH_RE.match(tok)):
                    if not (root / base / tok).exists():
                        errs.append("dangling reference: %s%s" % (base, tok))

    sim = root / "sim"
    if sim.is_dir():
        for d in sorted(sim.iterdir()):
            rec = d / "records"
            if rec.is_dir() and any(rec.iterdir()):
                if "sim/%s/" % d.name not in text:
                    errs.append("sim/%s/ holds records but is not covered "
                                "in REPRODUCE.md" % d.name)

    pins = {}
    for f in PIN_FILES:
        try:
            pins[f] = json.loads((root / f).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errs.append("cannot read %s: %s" % (f, e))
    for key in PIN_KEYS:
        vals = {f: d.get(key) for f, d in pins.items()}
        if len(set(map(repr, vals.values()))) > 1:
            errs.append("PDK pin mismatch on %r: %s" % (key, vals))
    commit = (pins.get("sim/pdk.json") or {}).get("open_pdks_commit")
    if commit and commit not in text:
        errs.append("REPRODUCE.md does not state open_pdks_commit %s" % commit)
    klt = (pins.get("layout/pdk.json") or {}).get("klt_version_pin")
    if klt and klt not in text:
        errs.append("REPRODUCE.md does not state klt pin %s" % klt)
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
    print("REPRODUCE.md consistent with the tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
