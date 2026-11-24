#!/usr/bin/env python3
"""The one path-hygiene rule for absolute paths written into committed evidence.

``docs/design-evidence-tiers.md``'s "Provenance hygiene in evidence records"
section (`klt env-provenance`'s own reference discipline, already followed by
this repo's ``layout/bin/_klt_common.py``, issue #49) is the rule this module
implements, in one place:

* a path **inside** this repository is recorded repo-relative;
* a path **outside** it -- a PDK install under the operator's home directory,
  a `tempfile.mkdtemp` scratch tree, anything else host-local -- is not
  recorded by absolute location at all. An external input is pinned by
  **identity** (the PDK name/version and deck ``content_hash`` the record
  already carries), not by where it happened to sit on one machine;
* anything else absolute (a system path such as ``/usr/bin/yosys``) is left
  verbatim -- it is not host-identifying.

`klt`'s JSON responses always resolve to absolute paths regardless of how the
request was invoked, so this is a necessary post-processing step, not a
cwd/invocation trick. Apply it only to the **copies** written into committed
artifacts and record bodies, never to the live paths a harness still needs to
open files with.

Both digital harnesses (``sim/digital-synthesis/harness/synthesize-and-verify.py``
and ``sim/digital-pnr/harness/pnr-and-verify.py``) used to carry their own
recursive copy of this function and their own copy of the marker string. The
two had drifted -- the P&R copy grew a ``/tmp/`` rule the synthesis copy never
got, and matched home by string prefix (so ``${HOME}2/x.lib``, a *sibling*
directory, was wrongly called external); neither handled a temp directory
outside ``/tmp``, which is how host-local ``/var/folders/.../T/
digital-synthesis-*`` scratch paths reached a committed synthesis record
(``sim/digital-synthesis/records/20260910-001436-a4c3194.json``; that record
is append-only evidence and stays as it is). This module is the union of the
two rules, with containment tested by :meth:`pathlib.Path.relative_to` rather
than string prefix. Issue #465; same consolidation shape as #133.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home().resolve()

EXTERNAL_PATH_MARKER = ("<external -- not recorded by absolute location; "
                        "see this record's PDK name/version and deck "
                        "content_hash instead>")


def temp_roots():
    """Resolved scratch roots whose contents are host-local, never evidence.

    ``tempfile.gettempdir()`` is what ``tempfile.mkdtemp()`` actually uses
    (``$TMPDIR`` on macOS -- a per-user ``/var/folders/.../T`` tree -- and
    normally ``/tmp`` on Linux); ``/tmp`` is included unconditionally so a
    path produced under a different ``$TMPDIR`` than the current process's is
    still caught. Resolved, because ``/var`` is a symlink to ``/private/var``
    on macOS and ``Path.relative_to`` is purely lexical.
    """
    roots = []
    for raw in (tempfile.gettempdir(), "/tmp"):
        p = Path(raw).resolve()
        if p not in roots:
            roots.append(p)
    return tuple(roots)


def _under(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def sanitize_paths(obj, repo_root=REPO_ROOT, home=HOME, tmp_roots=None):
    """Recursively rewrite absolute-path-shaped strings in ``obj`` for
    permanent, committed evidence.

    ``obj`` may be any JSON-shaped value; dicts and lists are walked, every
    other type is returned unchanged. Returns a new object -- ``obj`` itself
    is never mutated.
    """
    repo_root = Path(repo_root).resolve()
    home = Path(home).resolve()
    externals = (home, *(temp_roots() if tmp_roots is None else
                         tuple(Path(t).resolve() for t in tmp_roots)))
    return _walk(obj, repo_root, externals)


def _walk(obj, repo_root, externals):
    if isinstance(obj, str) and obj.startswith("/"):
        p = Path(obj).resolve()
        if _under(p, repo_root):
            return str(p.relative_to(repo_root))
        if any(_under(p, base) for base in externals):
            return EXTERNAL_PATH_MARKER
        return obj
    if isinstance(obj, dict):
        return {k: _walk(v, repo_root, externals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, repo_root, externals) for v in obj]
    return obj
