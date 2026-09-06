#!/usr/bin/env python3
"""Shared mini test-harness for this repo's standalone (no-pytest) test
scripts.

There is no pytest suite in this repository -- ``design/test_pdk_search.py``,
``layout/test_pex_netlist.py``, and ``layout/test_compose_cell.py`` are each
run directly (``python3 <path>``) on the PR-blocking CI path. All three used
to hand-roll an identical mini harness: a module-level list of failure
messages, a ``_check()`` helper that prints ``ok``/``FAIL`` per assertion and
records failures, and a ``main()`` that runs checks then prints a
``PASS``/``FAIL`` summary and returns an exit code. Two of the three copies
were byte-for-byte identical; the third had silently swapped its first two
parameters. Extracted per issue #55, following ``layout/bin/_klt_common.py``'s
precedent (issues #49/#52) and ``design/_pdk_search.py``'s before that
(issue #25): shared plumbing lives here once instead of as a copy per script.

Import it the way ``design/test_pdk_search.py`` already imports
``_pdk_search`` -- these are scripts, not an installed package, so the
importer puts this file's own directory on ``sys.path`` and imports it by
bare module name::

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _test_check import Checker  # noqa: E402

A script outside ``design/`` reaches this the way ``sim/bin/corner-run.py``
already reaches ``design/_pdk_search.py`` -- computing the repo root and
inserting ``REPO_ROOT / "design"``::

    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT / "design"))
    from _test_check import Checker  # noqa: E402
"""

from __future__ import annotations


class Checker:
    """Accumulates ``check()`` results and reports a ``PASS``/``FAIL`` summary.

    Matches the printed output format every prior hand-rolled copy already
    used, so consolidating onto this class changes no CI log output for the
    two scripts whose copies were already identical.
    """

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"ok     {label}")
        else:
            msg = f"{label}" + (f": {detail}" if detail else "")
            print(f"FAIL   {msg}")
            self.failures.append(msg)

    def summary(self, name: str) -> int:
        """Print the ``PASS``/``FAIL`` summary line and return an exit code."""
        if self.failures:
            print(f"FAIL   {len(self.failures)} check(s) failed")
            return 1
        print(f"PASS   {name}")
        return 0
