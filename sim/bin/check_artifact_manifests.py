#!/usr/bin/env python3
"""Validate the artifact manifests under manifests/artifacts/ (issue #347).

New sim/signoff evidence bytes live in the fleet artifact store; git keeps only
a manifest (name, size, sha256 per object) and a Markdown summary.  This
checker is the CI half of that contract.  For one git tree it fails when

* a ``manifests/artifacts/*.manifest.json`` does not follow the ``klt artifact``
  manifest schema (``schema_version`` 1, entries with exactly the documented
  fields);
* an entry ``uri`` is anything but ``artifact:<key>`` (no ``s3://``, no
  ``https://``, no bare key);
* a manifest names a storage bucket / cloud account (``s3://``, ``arn:aws:``);
* an object a manifest says is stored (matched by sha256 and size) is also
  tracked as a file in the same tree -- the bytes must not be committed;
* anything is tracked under the git-ignored staging directory
  ``.artifact-staging/``.

Stdlib + git only; it never talks to the broker (the live ``klt artifact
verify`` is a separate, out-of-band step).

Usage:  check_artifact_manifests.py check [--tree SHA] [--repo DIR]
Exit:   0 ok, 1 violation, 2 usage/git error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST_DIR = "manifests/artifacts"
STAGING_DIR = ".artifact-staging"
MANIFEST_RE = re.compile(r"^manifests/artifacts/[^/]+\.manifest\.json$")
SCHEMA_VERSION = 1
KINDS = ("evidence", "transcript", "log", "pdk")
REQUIRED = ("sha256", "size", "kind", "producer", "uri")
OPTIONAL = ("name", "media_type")
PRODUCER_FIELDS = ("tool", "version", "loom.repo", "commit")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_RE = re.compile(r"s3://|arn:aws:")


def validate_manifest(text: str) -> tuple[list[str], list[dict]]:
    """Return (problems, entries) for one manifest's JSON text."""
    problems: list[str] = []
    m = FORBIDDEN_RE.search(text)
    if m:
        problems.append(f"names a storage location ({m.group(0)!r}); only artifact: URIs are allowed")
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return problems + [f"not valid JSON: {exc}"], []
    if not isinstance(doc, dict):
        return problems + ["top level is not an object"], []
    extra = sorted(set(doc) - {"schema_version", "entries"})
    if extra:
        problems.append(f"unknown top-level field(s) {extra}")
    if doc.get("schema_version") != SCHEMA_VERSION or isinstance(doc.get("schema_version"), bool):
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        return problems + ["entries must be a non-empty list"], []
    good: list[dict] = []
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(e, dict):
            problems.append(f"{where} is not an object")
            continue
        n0 = len(problems)
        missing = [k for k in REQUIRED if k not in e]
        unknown = sorted(set(e) - set(REQUIRED) - set(OPTIONAL))
        if missing:
            problems.append(f"{where} missing field(s) {missing}")
        if unknown:
            problems.append(f"{where} unknown field(s) {unknown}")
        sha = e.get("sha256")
        if "sha256" in e and not (isinstance(sha, str) and SHA_RE.match(sha)):
            problems.append(f"{where}.sha256 must be 64 lowercase hex characters")
        size = e.get("size")
        if "size" in e and not (isinstance(size, int) and not isinstance(size, bool) and size >= 0):
            problems.append(f"{where}.size must be a non-negative integer")
        if "kind" in e and e["kind"] not in KINDS:
            problems.append(f"{where}.kind {e['kind']!r} not one of {list(KINDS)}")
        prod = e.get("producer")
        if "producer" in e:
            if not isinstance(prod, dict):
                problems.append(f"{where}.producer must be an object")
            else:
                bad = sorted(set(prod) - set(PRODUCER_FIELDS))
                if bad:
                    problems.append(f"{where}.producer unknown field(s) {bad}")
                for k in ("tool", "version"):
                    if not isinstance(prod.get(k), str) or not prod.get(k):
                        problems.append(f"{where}.producer.{k} must be a non-empty string")
        uri = e.get("uri")
        if "uri" in e and not (isinstance(uri, str) and uri.startswith("artifact:") and len(uri) > len("artifact:")):
            problems.append(f"{where}.uri must be 'artifact:<key>', got {uri!r}")
        for k in OPTIONAL:
            if k in e and not isinstance(e[k], str):
                problems.append(f"{where}.{k} must be a string")
        if len(problems) == n0:
            good.append(e)
    return problems, good


def _git(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=text)


def check_tree(repo: Path, tree: str) -> list[str]:
    """Return the list of violations for `tree` in `repo` (raises RuntimeError on git failure)."""
    ls = _git(repo, "ls-tree", "-r", "-l", "-z", tree, text=False)
    if ls.returncode != 0:
        raise RuntimeError(f"git ls-tree {tree} failed: {ls.stderr.decode(errors='replace').strip()}")
    files: dict[str, tuple[str, int]] = {}  # path -> (blob oid, size)
    for rec in ls.stdout.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        parts = meta.split()
        if len(parts) != 4 or parts[1] != b"blob":
            continue  # submodules / symlinks carry no stored bytes we track
        files[path.decode("utf-8", "surrogateescape")] = (parts[2].decode(), int(parts[3]))

    problems: list[str] = []
    for p in sorted(files):
        if p.startswith(STAGING_DIR + "/"):
            problems.append(f"{p}: tracked under the git-ignored staging dir {STAGING_DIR}/")
        elif p.startswith(MANIFEST_DIR + "/") and not MANIFEST_RE.match(p) and p != f"{MANIFEST_DIR}/README.md":
            problems.append(f"{p}: only *.manifest.json (and README.md) belong under {MANIFEST_DIR}/")

    stored: dict[tuple[str, int], list[str]] = {}
    for p in sorted(files):
        if not MANIFEST_RE.match(p):
            continue
        blob = _git(repo, "cat-file", "blob", files[p][0], text=False)
        if blob.returncode != 0:
            raise RuntimeError(f"git cat-file for {p} failed")
        errs, entries = validate_manifest(blob.stdout.decode("utf-8", "replace"))
        problems += [f"{p}: {e}" for e in errs]
        for e in entries:
            if e["size"] > 0:  # an empty file is not meaningful evidence of duplication
                stored.setdefault((e["sha256"], e["size"]), []).append(p)

    sizes = {s for _, s in stored}
    for path, (oid, size) in sorted(files.items()):
        if size not in sizes or MANIFEST_RE.match(path):
            continue
        blob = _git(repo, "cat-file", "blob", oid, text=False)
        if blob.returncode != 0:
            raise RuntimeError(f"git cat-file for {path} failed")
        digest = hashlib.sha256(blob.stdout).hexdigest()
        for manifest in stored.get((digest, size), []):
            problems.append(f"{path}: bytes are committed but {manifest} says they are stored "
                            f"in the artifact store (sha256 {digest[:16]}...); remove the file")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate manifests in a git tree")
    c.add_argument("--tree", default="HEAD", help="commit/tree-ish to check (default HEAD)")
    c.add_argument("--repo", type=Path, default=REPO)
    args = ap.parse_args(argv[1:])
    try:
        problems = check_tree(args.repo, args.tree)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not problems:
        print(f"{MANIFEST_DIR}: manifests valid, artifact: URIs only, no stored object committed")
        return 0
    print("artifact manifest violation(s):", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
