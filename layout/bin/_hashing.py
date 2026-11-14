#!/usr/bin/env python3
"""Shared SHA-256 digest helpers for this repo's ``layout/``, ``sim/`` and ``signoff/`` scripts.

Replaces six hand-rolled ``sha256_file`` / ``sha`` definitions (issues #452,
#455) and nine hand-rolled in-memory ``sha256_text`` / ``sha256_bytes`` /
``digest`` / ``sha`` definitions (issue #487) that had drifted into two output
formats for the same operation -- including two same-named ``sha256_text``
functions in this very directory that returned different strings. The formats
are preserved per call site (recorded digest strings must not change):
``prefix=True`` yields ``"sha256:<hex>"``, the default yields a bare ``<hex>``.

``hashlib.sha256`` is constructed in exactly one place here (``_new``) and
formatted in exactly one place (``_fmt``), so "digest this value" has one
definition for the whole repo. ``sha256_file`` reads in ``_CHUNK``-sized blocks
rather than via ``sha256_bytes`` -- this repo hashes GDS streams, which must not
be read into memory whole -- but shares that construction and formatting.

Import it the way ``_klt_common`` is imported -- put this file's directory on
``sys.path`` and import by bare module name::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))      # elsewhere
    from _hashing import sha256_file, sha256_text  # noqa: E402
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def _new(data: bytes = b""):
    """The one ``hashlib.sha256`` construction point for this repo's digests."""
    return hashlib.sha256(data)


def _fmt(digest, prefix: bool) -> str:
    """The one place a digest object becomes a recorded string."""
    hexdigest = digest.hexdigest()
    return "sha256:" + hexdigest if prefix else hexdigest


def sha256_bytes(data: bytes, *, prefix: bool = False) -> str:
    """SHA-256 of the in-memory ``data``, as hex.

    With ``prefix=True`` the digest is returned as ``"sha256:<hex>"``.
    """
    return _fmt(_new(data), prefix)


def sha256_text(text: str, *, prefix: bool = False) -> str:
    """SHA-256 of ``text`` encoded as UTF-8, as hex.

    The encoding is load-bearing: every digest this replaced hashed
    ``text.encode()``, so changing it would change recorded digest strings.
    With ``prefix=True`` the digest is returned as ``"sha256:<hex>"``.
    """
    return sha256_bytes(text.encode(), prefix=prefix)


def sha256_file(path, *, prefix: bool = False) -> str:
    """SHA-256 of the file at ``path`` (chunked read), as hex.

    Chunked on purpose -- a GDS stream must not be read into memory whole --
    so this does not route through ``sha256_bytes``.
    With ``prefix=True`` the digest is returned as ``"sha256:<hex>"``.
    """
    digest = _new()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return _fmt(digest, prefix)
