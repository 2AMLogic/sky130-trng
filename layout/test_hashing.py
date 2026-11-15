#!/usr/bin/env python3
"""Unit test for layout/bin/_hashing.py (shared sha256_file / _text / _bytes helpers)."""
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bin"))
from _hashing import sha256_bytes, sha256_file, sha256_text  # noqa: E402


def _check(name, ok):
    print(("PASS" if ok else "FAIL") + ": " + name)
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
                       ("sha256_text", lambda: sha256_text("x", True))):
        try:
            call()
        except TypeError:
            results.append(_check(f"{name}: prefix is keyword-only", True))
        else:
            results.append(_check(f"{name}: prefix is keyword-only", False))


def main():
    results = []
    _file_cases(results)
    _bytes_cases(results)
    _text_cases(results)
    _cross_agreement(results)
    _keyword_only(results)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
