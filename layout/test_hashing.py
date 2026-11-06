#!/usr/bin/env python3
"""Unit test for layout/bin/_hashing.py (shared sha256_file helper)."""
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bin"))
from _hashing import sha256_file  # noqa: E402


def _check(name, ok):
    print(("PASS" if ok else "FAIL") + ": " + name)
    return ok


def main():
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cases = {
            "empty": b"",
            "small": b"hello",
            "multi-chunk": bytes(range(256)) * (((1 << 20) * 2 + 12345) // 256 + 1),
        }
        for name, data in cases.items():
            f = tmp / name
            f.write_bytes(data)
            want = hashlib.sha256(data).hexdigest()
            results.append(_check(f"{name}: bare", sha256_file(f) == want))
            results.append(_check(f"{name}: prefix=True", sha256_file(f, prefix=True) == "sha256:" + want))
            results.append(_check(f"{name}: str path", sha256_file(str(f)) == want))
        results.append(_check("multi-chunk exceeds one chunk", len(cases["multi-chunk"]) > (1 << 20)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
