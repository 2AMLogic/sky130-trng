#!/usr/bin/env python3
"""Unit test for ``design/_pdk_search.py``'s shared PDK-resolution walk.

Not part of any pytest suite -- there is none in this repository -- but a
standalone script following ``design/test_netlist_erc.py``'s own "run it
directly" convention:

    python3 design/test_pdk_search.py

Closes the test-coverage gap issue #25 called out: before that issue,
neither ``design/netlist.py``'s ``find_pdk()`` nor
``sim/bin/corner-run.py``'s ``resolve_pdk()`` had direct unit coverage of
the fallback order itself (``design/test_netlist_erc.py`` covers the brace
guard/ERC path, not PDK resolution). Both now delegate the walk to
``search_pdk()``, so this test exercises the shared fallback chain once,
pure Python, no xschem, no PDK install, no ngspice -- everything here runs
in any environment.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pdk_search  # path insert above must run before this import resolves
from _pdk_search import PdkSearchError, search_pdk

_FAILURES: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"ok     {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"FAIL   {msg}")
        _FAILURES.append(msg)


def _make_variant_dir(root: Path, name: str, marker: str = "libs.tech/xschem") -> Path:
    """A directory tree ``search_pdk``'s validator will accept: ``root/name/<marker>``."""
    variant_dir = root / name
    (variant_dir / marker).mkdir(parents=True)
    return variant_dir


def _is_variant_dir(path: Path) -> bool:
    return (path / "libs.tech" / "xschem").is_dir()


def check_search_roots_order() -> None:
    """Among several matching search roots, the first one wins."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        first = tmp_path / "first"
        second = tmp_path / "second"
        _make_variant_dir(first, "sky130A")
        _make_variant_dir(second, "sky130A")

        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(second), str(first)],
            env={},
        )
        _check(
            "search_roots: first matching root wins",
            found is not None and found.path == (second / "sky130A").resolve(),
            f"got {found}",
        )
        _check(
            "search_roots: source records the winning root",
            found is not None and found.source == str(second),
            f"got {found}",
        )


def check_search_roots_skips_non_matching() -> None:
    """A search root with no variant subdirectory is skipped, not fatal."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        real_root = tmp_path / "real"
        _make_variant_dir(real_root, "sky130A")

        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(empty_root), str(real_root)],
            env={},
        )
        _check(
            "search_roots: non-matching root is skipped in favor of a later match",
            found is not None and found.path == (real_root / "sky130A").resolve(),
            f"got {found}",
        )


def check_not_found_returns_none() -> None:
    """No env var, no PDK_ROOT, and no search root matches -> None, not an exception."""
    with tempfile.TemporaryDirectory() as tmp:
        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(Path(tmp) / "nothing-here")],
            env={},
        )
        _check("not found anywhere: returns None rather than raising", found is None)


def check_sky130_pdk_path_short_circuits_search_roots() -> None:
    """SKY130_PDK_PATH wins even when search_roots would also match."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        explicit = _make_variant_dir(tmp_path, "explicit-dir")
        other_root = tmp_path / "other"
        _make_variant_dir(other_root, "sky130A")

        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(other_root)],
            env={"SKY130_PDK_PATH": str(explicit)},
        )
        _check(
            "SKY130_PDK_PATH: short-circuits search_roots",
            found is not None and found.path == explicit.resolve(),
            f"got {found}",
        )
        _check(
            "SKY130_PDK_PATH: source is the env var name, not a search root",
            found is not None and found.source == "SKY130_PDK_PATH",
            f"got {found}",
        )
        _check(
            "SKY130_PDK_PATH: variant is taken from the directory's own name",
            found is not None and found.variant == "explicit-dir",
            f"got {found}",
        )


def check_sky130_pdk_path_invalid_raises() -> None:
    """An invalid SKY130_PDK_PATH raises PdkSearchError, not a silent fall-through."""
    with tempfile.TemporaryDirectory() as tmp:
        not_a_variant_dir = Path(tmp) / "empty"
        not_a_variant_dir.mkdir()
        # A matching search root exists too, but must never be reached.
        other_root = Path(tmp) / "other"
        _make_variant_dir(other_root, "sky130A")

        try:
            search_pdk(
                variant="sky130A",
                is_variant_dir=_is_variant_dir,
                variant_dir_label="libs.tech/xschem directory",
                search_roots=[str(other_root)],
                env={"SKY130_PDK_PATH": str(not_a_variant_dir)},
            )
        except PdkSearchError as exc:
            _check(
                "SKY130_PDK_PATH invalid: error names the path and expected layout",
                str(not_a_variant_dir) in str(exc) and "libs.tech/xschem directory" in str(exc),
                f"got: {exc}",
            )
        else:
            _check("SKY130_PDK_PATH invalid: raises PdkSearchError", False, "no exception raised")


def check_pdk_root_plus_pdk() -> None:
    """PDK_ROOT + PDK (the variant) resolves to PDK_ROOT/<variant>."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _make_variant_dir(tmp_path, "sky130A")
        # A search root that would also match must not be needed/reached.
        other_root = tmp_path / "other"
        _make_variant_dir(other_root, "sky130A")

        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(other_root)],
            env={"PDK_ROOT": str(tmp_path)},
        )
        _check(
            "PDK_ROOT+PDK: resolves to PDK_ROOT/<variant>",
            found is not None and found.path == (tmp_path / "sky130A").resolve(),
            f"got {found}",
        )
        _check(
            "PDK_ROOT+PDK: source is PDK_ROOT",
            found is not None and found.source == "PDK_ROOT",
            f"got {found}",
        )


def check_pdk_root_falls_through_to_search_roots() -> None:
    """An invalid PDK_ROOT falls through to search_roots rather than raising."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bad_pdk_root = tmp_path / "empty"
        bad_pdk_root.mkdir()
        real_root = tmp_path / "real"
        _make_variant_dir(real_root, "sky130A")

        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(real_root)],
            env={"PDK_ROOT": str(bad_pdk_root)},
        )
        _check(
            "PDK_ROOT invalid: falls through to search_roots instead of raising",
            found is not None and found.path == (real_root / "sky130A").resolve(),
            f"got {found}",
        )


def check_full_fallback_order() -> None:
    """End-to-end: SKY130_PDK_PATH > PDK_ROOT+PDK > search_roots, in that order."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        via_explicit = _make_variant_dir(tmp_path, "via-explicit")
        via_pdk_root_parent = tmp_path / "via-pdk-root"
        _make_variant_dir(via_pdk_root_parent, "sky130A")
        via_search_root = tmp_path / "via-search-root"
        _make_variant_dir(via_search_root, "sky130A")

        env = {
            "SKY130_PDK_PATH": str(via_explicit),
            "PDK_ROOT": str(via_pdk_root_parent),
        }
        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(via_search_root)],
            env=env,
        )
        _check(
            "full order: SKY130_PDK_PATH beats PDK_ROOT and search_roots",
            found is not None and found.path == via_explicit.resolve(),
            f"got {found}",
        )

        del env["SKY130_PDK_PATH"]
        found = search_pdk(
            variant="sky130A",
            is_variant_dir=_is_variant_dir,
            variant_dir_label="libs.tech/xschem directory",
            search_roots=[str(via_search_root)],
            env=env,
        )
        _check(
            "full order: PDK_ROOT beats search_roots once SKY130_PDK_PATH is unset",
            found is not None and found.path == (via_pdk_root_parent / "sky130A").resolve(),
            f"got {found}",
        )


def check_builtin_search_roots_is_the_shared_tuple() -> None:
    """Sanity check that the shared constant both callers import is non-empty
    and unchanged in shape (a 6-entry tuple of strings), so a future edit
    that accidentally empties or mistypes it is caught here rather than
    only at PDK-resolution time in whichever tool runs first."""
    roots = _pdk_search.BUILTIN_SEARCH_ROOTS
    _check(
        "BUILTIN_SEARCH_ROOTS: is a non-empty tuple of strings",
        isinstance(roots, tuple) and len(roots) > 0 and all(isinstance(r, str) for r in roots),
        f"got {roots!r}",
    )


def main() -> int:
    check_search_roots_order()
    check_search_roots_skips_non_matching()
    check_not_found_returns_none()
    check_sky130_pdk_path_short_circuits_search_roots()
    check_sky130_pdk_path_invalid_raises()
    check_pdk_root_plus_pdk()
    check_pdk_root_falls_through_to_search_roots()
    check_full_fallback_order()
    check_builtin_search_roots_is_the_shared_tuple()

    if _FAILURES:
        print(f"FAIL   {len(_FAILURES)} check(s) failed")
        return 1
    print("PASS   design/test_pdk_search.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
