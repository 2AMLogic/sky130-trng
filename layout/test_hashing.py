#!/usr/bin/env python3
"""Unit test for layout/bin/_hashing.py (shared sha256_file / _text / _bytes /
_json helpers) plus the repo-wide no-fork guard over hashlib.sha256 (issue #669)."""
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent / "bin"))
from _hashing import sha256_bytes, sha256_file, sha256_json, sha256_text  # noqa: E402


def _check(name, ok, detail=None):
    text = ("PASS" if ok else "FAIL") + ": " + name
    if not ok and detail:
        text += " -- " + detail
    print(text)
    return ok


# The nine helpers consolidated by issue #487 all hashed text as `t.encode()`
# (UTF-8, strict).  A non-ASCII case pins that encoding so a future change to
# sha256_text cannot silently re-encode and alter a recorded digest.
CASES = {
    "empty": b"",
    "small": b"hello",
    "non-ascii": "micro µV — é".encode(),
    "nul-and-high-bytes": bytes(range(256)),
    "multi-chunk": bytes(range(256)) * (((1 << 20) * 2 + 12345) // 256 + 1),
}


def _file_cases(results):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, data in CASES.items():
            f = tmp / name
            f.write_bytes(data)
            want = hashlib.sha256(data).hexdigest()
            results.append(_check(f"file {name}: bare", sha256_file(f) == want))
            results.append(_check(f"file {name}: prefix=True", sha256_file(f, prefix=True) == "sha256:" + want))
            results.append(_check(f"file {name}: str path", sha256_file(str(f)) == want))
        results.append(_check("multi-chunk exceeds one chunk", len(CASES["multi-chunk"]) > (1 << 20)))


def _bytes_cases(results):
    for name, data in CASES.items():
        want = hashlib.sha256(data).hexdigest()
        results.append(_check(f"bytes {name}: bare", sha256_bytes(data) == want))
        results.append(_check(f"bytes {name}: prefix=True", sha256_bytes(data, prefix=True) == "sha256:" + want))
        results.append(_check(f"bytes {name}: prefix relation",
                              sha256_bytes(data, prefix=True) == "sha256:" + sha256_bytes(data)))


def _text_cases(results):
    texts = ["", "hello", "micro µV — é", "line\nline\n", "trng_whole\n* x\n"]
    for text in texts:
        want = hashlib.sha256(text.encode()).hexdigest()
        label = repr(text)[:24]
        results.append(_check(f"text {label}: bare", sha256_text(text) == want))
        results.append(_check(f"text {label}: prefix=True", sha256_text(text, prefix=True) == "sha256:" + want))
        results.append(_check(f"text {label}: prefix relation",
                              sha256_text(text, prefix=True) == "sha256:" + sha256_text(text)))
        results.append(_check(f"text {label}: agrees with sha256_bytes",
                              sha256_text(text) == sha256_bytes(text.encode())))


def _json_cases(results):
    """sha256_json (issue #669) must be byte-identical to the two helpers it
    replaced (sensitivity.py's sha256_json, behavioral_raw_bit.py's
    _row_sha256): both hashed json.dumps(obj, sort_keys=True, default=str)
    .encode(), and sensitivity.py's recorded calibration pins still verify
    against behavioral_raw_bit.py's copy through this one definition."""
    objs = [
        {},
        {"corner": "tt", "temp_c": 27.0, "vdd_v": 1.8},
        {"rows": [{"key": "ring5|tt|27C|1.8V", "job_id": "j-1", "q_ring": 0.25}]},
        # default=str is load-bearing: record rows carry non-JSON scalars
        {"path": Path("sim/x/records/r.json"), "sigma": {1: 1.25e-3}},
    ]
    for obj in objs:
        want = hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
        label = repr(obj)[:24]
        results.append(_check(f"json {label}: matches the replaced spelling", sha256_json(obj) == want))
        results.append(_check(f"json {label}: prefix=True",
                              sha256_json(obj, prefix=True) == "sha256:" + want))
        results.append(_check(f"json {label}: agrees with sha256_text",
                              sha256_json(obj) == sha256_text(json.dumps(obj, sort_keys=True, default=str))))
    # sort_keys means insertion order cannot change a recorded digest
    a = {"alpha": 1, "beta": [2, 3], "gamma": {"d": 4, "e": 5}}
    b = {"gamma": {"e": 5, "d": 4}, "beta": [2, 3], "alpha": 1}
    results.append(_check("json key order is invariant", sha256_json(a) == sha256_json(b)))
    # the producer/consumer pair must agree through the shared definition
    producer_rows = [{"key": k, "job_id": f"j-{i}"} for i, k in enumerate(("ring5", "array"))]
    results.append(_check("json producer digest == consumer digest",
                          sha256_json(producer_rows[0]) == sha256_json(json.loads(json.dumps(producer_rows[0])))))


def _cross_agreement(results):
    """file / bytes / text must agree on the same payload -- one definition, three entries."""
    text = "trng_whole\n* probe µV\n"
    data = text.encode()
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "payload"
        f.write_bytes(data)
        results.append(_check("file == bytes == text (bare)",
                              sha256_file(f) == sha256_bytes(data) == sha256_text(text)))
        results.append(_check("file == bytes == text (prefix=True)",
                              sha256_file(f, prefix=True) == sha256_bytes(data, prefix=True)
                              == sha256_text(text, prefix=True)))


def _keyword_only(results):
    """prefix is keyword-only: a positional second argument must not be accepted."""
    for name, call in (("sha256_bytes", lambda: sha256_bytes(b"x", True)),
                       ("sha256_text", lambda: sha256_text("x", True)),
                       ("sha256_json", lambda: sha256_json({}, True))):
        try:
            call()
        except TypeError:
            results.append(_check(f"{name}: prefix is keyword-only", True))
        else:
            results.append(_check(f"{name}: prefix is keyword-only", False))


# ---------------------------------------------------------------------------
# Repo-wide no-fork guard (issue #669): ``hashlib.sha256`` is constructed in
# exactly one place (``layout/bin/_hashing.py::_new``) and every digest string
# in the repo derives from the shared helpers.  Each entry below is a site
# that keeps its own construction, with the reason; the map is exact in both
# directions -- a new fork fails, and so does a stale (drained) entry.

ALLOWED_SHA256_CONSTRUCTION_SITES = {
    # the shared home itself: _new is the one construction point.
    "layout/bin/_hashing.py": 1,
    # canonical_geometry_hash: a multi-update polygon/label stream digest,
    # not a one-shot digest of a single value.
    "layout/bin/_gds_geometry.py": 1,
    # _sha_size: single-pass chunked (hexdigest, size) over a file.
    "sim/bin/artifact_store.py": 1,
    # manifest keys_sha256: campaign.py's bytes are pinned in controls record
    # sim/ro-vth-drift-sensitivity/records/20261010-164921-7e279ab.json and
    # gated by analysis/sensitivity.py's emit_record provenance check.
    "sim/ro-vth-drift-sensitivity/campaign.py": 1,
    # sub_seed / restart_seed: binary .digest()[:8] 64-bit PRNG seed
    # derivations, not string digests (no hexdigest involved).
    "sim/bin/raw_bit_model.py": 1,
    "sim/wake-up-transient/restart_matrix.py": 1,
    "sim/wake-up-transient/wakeup.py": 1,
    # __import__("hashlib").sha256: the harness is itself pinned in the cited
    # 7.digital record's input-hashes.json (append-only evidence) and re-hashed
    # by sim/bin/check_signoff_sim_freshness.py REQUIRED_FILES, so it stays
    # byte-frozen until that record is re-minted (#372).
    "sim/digital-sdf-timed-verification/harness/fv-sdf-cosim.py": 1,
}


def _sha256_construction_sites(path) -> list[int]:
    """1-based line numbers of every ``hashlib.sha256`` construction in *path*.

    Catches ``hashlib.sha256(...)``, ``__import__("hashlib").sha256(...)``,
    a bare ``sha256(...)`` bound by ``from hashlib import sha256``, and
    ``hashlib.new("sha256", ...)`` (attribute or ``from hashlib import new``
    binding, first argument a string constant equal case-insensitively to
    ``"sha256"``; a non-constant algorithm name is undecidable by AST and
    stays silent); docstrings and comments are not AST nodes, so prose
    mentions stay silent.
    """
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    from_sha256_imports = set()
    from_new_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "hashlib":
            for alias in node.names:
                if alias.name == "sha256":
                    from_sha256_imports.add(alias.asname or "sha256")
                elif alias.name == "new":
                    from_new_imports.add(alias.asname or "new")

    def _is_hashlib(value):
        return (isinstance(value, ast.Name) and value.id == "hashlib") or (
            isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id == "__import__" and len(value.args) == 1
            and isinstance(value.args[0], ast.Constant) and value.args[0].value == "hashlib")

    def _names_sha256_constant(call):
        return (call.args and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
                and call.args[0].value.lower() == "sha256")

    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "sha256" and _is_hashlib(node.value):
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and from_sha256_imports and node.id in from_sha256_imports:
            lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "new"
                    and _is_hashlib(func.value) and _names_sha256_constant(node)):
                lines.append(node.lineno)
            elif (isinstance(func, ast.Name) and func.id in from_new_imports
                    and _names_sha256_constant(node)):
                lines.append(node.lineno)
    return sorted(lines)


def _tracked_non_test_py(repo: Path) -> list[str]:
    """Repo-relative paths of every tracked .py file that is not a test."""
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--", "*.py"],
                         capture_output=True, text=True, check=True)
    rels = []
    for rel in out.stdout.split("\0"):
        if not rel:
            continue
        posix = PurePosixPath(rel)
        if posix.name.startswith("test_") or "tests" in posix.parts:
            continue
        rels.append(rel)
    return sorted(rels)


def _no_fork_guard(results):
    repo = Path(__file__).resolve().parent.parent
    found = {}
    for rel in _tracked_non_test_py(repo):
        sites = _sha256_construction_sites(repo / rel)
        if sites:
            found[rel] = len(sites)
    allowed = ALLOWED_SHA256_CONSTRUCTION_SITES
    new = sorted(set(found) - set(allowed))
    drained = sorted(set(allowed) - set(found))
    mismatched = sorted(rel for rel in set(found) & set(allowed) if found[rel] != allowed[rel])
    results.append(_check(f"no hashlib.sha256 construction site outside the allowlist "
                          f"({len(found)}/{len(allowed)} files carry one)", not new,
                          "; ".join(f"{p}: {found[p]} site(s) -- digest through layout/bin/_hashing.py "
                                    "(issue #669)" for p in new)))
    results.append(_check("allowlist carries no drained (stale) entry", not drained,
                          "; ".join(f"{p} no longer constructs hashlib.sha256 -- remove its entry" for p in drained)))
    results.append(_check("every allowlisted file keeps exactly its allowed site count", not mismatched,
                          "; ".join(f"{p}: allowed {allowed[p]}, found {found[p]}" for p in mismatched)))
    # Positive and negative controls (#617's convention): each fork shape must
    # be shown catchable, and the near-misses that share a token but not a
    # construction must stay silent, so the guard cannot rot into a no-op.
    with tempfile.TemporaryDirectory() as td:
        fork_shapes = {
            "attribute": 'import hashlib\nd = hashlib.sha256(b"x").hexdigest()\n',
            "from-import": 'from hashlib import sha256\nd = sha256("x".encode()).hexdigest()\n',
            "from-import-as": 'from hashlib import sha256 as _sha\nd = _sha(b"x").hexdigest()\n',
            "dunder-import": 'd = __import__("hashlib").sha256(b"x").hexdigest()\n',
            "hashlib-new": 'import hashlib\nd = hashlib.new("sha256", b"x").hexdigest()\n',
            "hashlib-new-upper": 'import hashlib\nd = hashlib.new("SHA256", b"x").hexdigest()\n',
            "from-import-new": 'from hashlib import new as h\nd = h("sha256", b"x").hexdigest()\n',
        }
        for name, text in fork_shapes.items():
            p = Path(td) / (name + ".py")
            p.write_text(text)
            results.append(_check(f"guard catches the {name} fork shape",
                                  _sha256_construction_sites(p) == [2] if "dunder" not in name
                                  else _sha256_construction_sites(p) == [1]))
        near_misses = {
            "shared-helper": "from _hashing import sha256_text\nd = sha256_text('x')\n",
            "other-module": 'import zlib\nd = zlib.sha256(b"x")\n',
            "other-attr": 'import foo\nd = foo.sha256(b"x")\n',
            "local-def": 'def sha256(data):\n    return data\n\nd = sha256(b"x")\n',
            "other-algo": 'import hashlib\nd = hashlib.sha3_256(b"x").hexdigest()\n',
            "hashlib-new-md5": 'import hashlib\nd = hashlib.new("md5", b"x").hexdigest()\n',
            "hashlib-new-var": 'import hashlib\nalgo = "sha256"\nd = hashlib.new(algo, b"x").hexdigest()\n',
        }
        for name, text in near_misses.items():
            p = Path(td) / (name + ".py")
            p.write_text(text)
            results.append(_check(f"guard stays silent on the {name} near-miss",
                                  _sha256_construction_sites(p) == []))


def main():
    results = []
    _file_cases(results)
    _bytes_cases(results)
    _text_cases(results)
    _json_cases(results)
    _cross_agreement(results)
    _keyword_only(results)
    _no_fork_guard(results)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
