#!/usr/bin/env python3
"""Shared file-digest helper for this repo's ``layout/`` and ``signoff/`` scripts.

Replaces six hand-rolled ``sha256_file`` / ``sha`` definitions that had drifted
into two output formats for the same operation. The formats are preserved per
call site (recorded digest strings must not change): ``prefix=True`` yields
``"sha256:<hex>"``, the default yields a bare ``<hex>``.

Import it the way ``_klt_common`` is imported -- put this file's directory on
``sys.path`` and import by bare module name::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))      # elsewhere
    from _hashing import sha256_file  # noqa: E402
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def sha256_file(path, *, prefix: bool = False) -> str:
    """SHA-256 of the file at ``path`` (chunked read), as hex.

    With ``prefix=True`` the digest is returned as ``"sha256:<hex>"``.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    hexdigest = digest.hexdigest()
    return "sha256:" + hexdigest if prefix else hexdigest
