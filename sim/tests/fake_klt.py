"""A fake ``klt`` executable for artifact-store tests (issue #347); stdlib only.

``install(dir, mode)`` writes ``dir/klt`` and returns an env patch (PATH +
a placeholder broker URL).  Modes: ``ok`` stores nothing but emits a manifest
like ``klt artifact put``; ``noverb`` has no ``artifact put``; ``unreachable``
fails every put and echoes the broker URL on stderr; ``partial`` writes a
manifest for the first file, then fails.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

BROKER = "https://broker.invalid/secret-path"

SCRIPT = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
mode = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode")).read().strip()
a = sys.argv[1:]
if a[:2] != ["artifact", "put"]:
    sys.exit(2)
if mode == "noverb":
    sys.exit(2)
if "--help" in a:
    print("usage: klt artifact put")
    sys.exit(0)
assert not any("broker.invalid" in x for x in a), "broker URL leaked into argv"
manifest = None
files = []
i = 2
while i < len(a):
    if a[i] == "--manifest":
        manifest = a[i + 1]; i += 2
    else:
        files.append(a[i]); i += 1
if mode == "unreachable":
    print("cannot reach " + os.environ["KLT_ARTIFACT_BROKER"], file=sys.stderr)
    sys.exit(1)
entries = []
for f in files:
    b = open(f, "rb").read()
    d = hashlib.sha256(b).hexdigest()
    entries.append({"sha256": d, "size": len(b), "kind": "evidence",
                    "producer": {"tool": "klt", "version": "0.0-fake"},
                    "uri": "artifact:fake/" + d, "name": f})
    if mode == "partial":
        break
json.dump({"schema_version": 1, "entries": entries}, open(manifest, "w"))
sys.exit(1 if mode == "partial" else 0)
'''


def install(directory, mode="ok"):
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    (d / "mode").write_text(mode)
    exe = d / "klt"
    exe.write_text(SCRIPT)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return {"PATH": f"{d}{os.pathsep}{os.environ.get('PATH', '')}", "KLT_ARTIFACT_BROKER": BROKER}
