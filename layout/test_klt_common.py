#!/usr/bin/env python3
"""Contract tests for ``layout/bin/_klt_common.py``'s shared ``klt`` readers
(issue #500).

Standalone script, following ``layout/test_hashing.py``'s convention:

    python3 layout/test_klt_common.py

No real ``klt``, no PDK: every case drives a fake ``klt`` shell script whose
response is written by the test, which is what lets the negative controls
exist at all (a real ``klt`` cannot be asked to emit a malformed response).

What these guard, because the two defects behind #500 were both invisible
while every producer happened to agree with itself:

- ``klt_version`` must return the BARE version (``"0.8.0"``), never the
  ``klt --version`` banner spelling (``"klt 0.8.0"``). Three string-equality
  pin gates compare ``klt_version`` across producers, and 391 of the 392
  committed ``klt_version`` values are bare -- so a prefixed read makes a
  correctly-pinned host fail the gate unconditionally (the #372 trap).
- ``pdk_find`` must always request ``--format json``. The outlier it replaces
  scraped ``klt pdk find``'s human-readable rendering with
  ``re.search(r"^\\s*libs_ref:\\s*(\\S+)\\s*$", out, re.M)``, which takes the
  FIRST match -- so a ``warning:`` line or a second install block bearing a
  ``libs_ref:`` silently won. The decoy control below is that exact shape.
- ``pdk_find`` must hand back the whole response, so ``compatibility`` /
  ``ambiguous_roots`` / ``broken_symlinks`` -- which the text scrape discarded
  -- reach the caller that is picking a Liberty deck.
- ``pdk_root`` must honour a preset ``$PDK_ROOT`` without invoking klt at all
  (the short-circuit ``verify-whole.py`` established), and must otherwise read
  ``root`` from the JSON response.
- a malformed response must raise ``BuildError``, never return a wrong answer:
  no ``version`` field, no ``assets.libs_ref``, an ``error`` object.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "bin"))
from _klt_common import (  # noqa: E402
    BuildError,
    compatibility_status,
    klt_version,
    libs_ref,
    libs_ref_of,
    pdk_find,
    pdk_root,
    run_klt_rc,
)

_RESULTS: list[bool] = []


def _check(name, ok, detail=None) -> bool:
    ok = bool(ok)
    print(("PASS" if ok else "FAIL") + ": " + name + ("" if ok or detail is None
                                                      else f"  [{detail!r}]"))
    _RESULTS.append(ok)
    return ok


def _raises(name, fn, needle) -> bool:
    try:
        got = fn()
    except BuildError as exc:
        return _check(name, needle in str(exc), str(exc))
    return _check(name, False, f"no BuildError; returned {got!r}")


def _fake_klt(directory: Path, body: str) -> str:
    """Write an executable fake ``klt`` whose Python *body* prints a response.

    *body* runs with ``argv`` bound to klt's arguments and may print anything
    and exit with any status -- the point of a fake is to be able to answer
    wrongly.
    """
    exe = directory / "klt"
    exe.write_text("#!/usr/bin/env python3\n"
                   "import json, sys\n"
                   "argv = sys.argv[1:]\n"
                   + body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


# ``klt version --format json``'s real shape, and the banner that is NOT it.
_VERSION_OK = """
if argv[:1] != ["version"]:
    sys.exit(2)
print(json.dumps({"version": "0.8.0", "schema_version": 1}))
"""

# The real ``klt pdk find --format json`` response shape, including the three
# fields the text scrape discarded.
_PDK_RESPONSE = {
    "root": "/fake/.ciel",
    "resolved_via": "search root: ~/.ciel",
    "assets": {"libs_ref": "/fake/.ciel/sky130A/libs.ref",
               "libs_tech": "/fake/.ciel/sky130A/libs.tech"},
    "compatibility": "mismatch",
    "ambiguous_roots": ["/fake/.volare"],
    "broken_symlinks": ["/fake/.ciel/sky130A/libs.ref/dangling"],
}

# A fake that REFUSES to answer unless --format json was requested, and whose
# text rendering carries a decoy ``libs_ref:`` warning line ahead of the real
# one -- the exact shape that defeats a first-match regex scrape.
_PDK_JSON_ONLY = """
if argv[:2] != ["pdk", "find"]:
    sys.exit(2)
if "--format" not in argv or argv[argv.index("--format") + 1] != "json":
    print("root: /fake/.ciel")
    print("warning: shadowed same-variant install: libs_ref: /DECOY/libs.ref")
    print("assets:")
    print("  libs_ref: /fake/.ciel/sky130A/libs.ref")
    sys.exit(0)
print(json.dumps(%s))
""" % json.dumps(_PDK_RESPONSE)


def check_klt_version_is_bare() -> None:
    """The bare spelling, from the JSON response -- never the banner."""
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t), _VERSION_OK)
        got = klt_version(env=dict(os.environ), klt=klt)
        _check("klt_version returns the bare version", got == "0.8.0", got)
        _check("klt_version never returns the 'klt ' banner prefix",
               not got.startswith("klt "), got)
        _check("klt_version's result is what a bare pin compares equal to",
               got == "0.8.0" and got != "klt 0.8.0", got)
        _check("klt_version defaults env to the ambient environment",
               klt_version(klt=klt) == "0.8.0")


def check_klt_version_fails_closed() -> None:
    cases = {
        "no version field": ('print(json.dumps({"schema_version": 1}))',
                             "no 'version'"),
        "non-string version": ('print(json.dumps({"version": 80}))',
                               "no 'version'"),
        "empty version": ('print(json.dumps({"version": ""}))', "no 'version'"),
        "error object": ('print(json.dumps({"error": {"message": "boom"}}))',
                         "boom"),
        "not JSON at all": ('print("klt 0.8.0")', "no JSON response"),
    }
    for label, (body, needle) in cases.items():
        with tempfile.TemporaryDirectory() as t:
            klt = _fake_klt(Path(t), body)
            _raises(f"klt_version raises on {label}",
                    lambda klt=klt: klt_version(env=dict(os.environ), klt=klt),
                    needle)


def check_pdk_find_always_asks_for_json() -> None:
    """The defect: the outlier omitted --format json and scraped the text."""
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t), _PDK_JSON_ONLY)
        got = pdk_find("sky130A", env=dict(os.environ), klt=klt)
        _check("pdk_find requested --format json (fake refuses otherwise)",
               got.get("root") == "/fake/.ciel", got)
        _check("pdk_find hands back compatibility",
               got.get("compatibility") == "mismatch", got.get("compatibility"))
        _check("pdk_find hands back ambiguous_roots",
               got.get("ambiguous_roots") == ["/fake/.volare"])
        _check("pdk_find hands back broken_symlinks",
               got.get("broken_symlinks") == ["/fake/.ciel/sky130A/libs.ref/dangling"])


def check_libs_ref_is_not_fooled_by_a_decoy() -> None:
    """A first-match ``libs_ref:`` scrape would have returned /DECOY."""
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t), _PDK_JSON_ONLY)
        got = libs_ref("sky130A", env=dict(os.environ), klt=klt)
        _check("libs_ref reads assets.libs_ref from the JSON response",
               got == Path("/fake/.ciel/sky130A/libs.ref"), got)
        _check("libs_ref is not the decoy a first-match text scrape would take",
               "DECOY" not in str(got), got)
        _check("libs_ref returns a Path", isinstance(got, Path), type(got))


def check_libs_ref_fails_closed() -> None:
    cases = {
        "no assets": ('print(json.dumps({"root": "/fake"}))', "assets.libs_ref"),
        "assets without libs_ref":
            ('print(json.dumps({"root": "/fake", "assets": {"libs_tech": "/x"}}))',
             "assets.libs_ref"),
        "non-string libs_ref":
            ('print(json.dumps({"assets": {"libs_ref": None}}))', "assets.libs_ref"),
    }
    for label, (body, needle) in cases.items():
        with tempfile.TemporaryDirectory() as t:
            klt = _fake_klt(Path(t), body)
            _raises(f"libs_ref raises on {label}",
                    lambda klt=klt: libs_ref("sky130A", env=dict(os.environ),
                                             klt=klt),
                    needle)


def check_pdk_root_short_circuits_a_preset_root() -> None:
    """A preset $PDK_ROOT wins without invoking klt at all."""
    with tempfile.TemporaryDirectory() as t:
        # a fake that fails every invocation: reaching it at all is the failure
        klt = _fake_klt(Path(t), 'sys.exit(1)')
        env = {**os.environ, "PDK_ROOT": "/preset/root"}
        got = pdk_root("sky130A", env=env, klt=klt)
        _check("pdk_root returns a preset $PDK_ROOT without running klt",
               got == "/preset/root", got)

        env_empty = {**os.environ, "PDK_ROOT": ""}
        _raises("pdk_root treats an EMPTY $PDK_ROOT as unset and asks klt",
                lambda: pdk_root("sky130A", env=env_empty, klt=klt),
                "no JSON response")


def check_pdk_root_reads_root_from_the_response() -> None:
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t), _PDK_JSON_ONLY)
        env = {k: v for k, v in os.environ.items() if k != "PDK_ROOT"}
        got = pdk_root("sky130A", env=env, klt=klt)
        _check("pdk_root reads root from the JSON response",
               got == "/fake/.ciel", got)
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t), 'print(json.dumps({"assets": {}}))')
        env = {k: v for k, v in os.environ.items() if k != "PDK_ROOT"}
        _raises("pdk_root raises when the response carries no root",
                lambda: pdk_root("sky130A", env=env, klt=klt), "'root'")


def check_pdk_find_names_the_pdk_it_was_asked_for() -> None:
    body = ('print(json.dumps({"root": "/r", "asked": argv}))')
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t), body)
        got = pdk_find("sky130B", env=dict(os.environ), klt=klt)
        _check("pdk_find passes `pdk find --pdk <pdk>`",
               got["asked"][:4] == ["pdk", "find", "--pdk", "sky130B"],
               got["asked"])


def check_run_klt_rc_reports_the_exit_status() -> None:
    """``run_klt_rc`` exists so a caller recording klt's exit code can adopt
    the shared contract without losing it (erc-negative-controls.py's
    ``klt_exit`` field)."""
    body = ('print(json.dumps({"erc_status": "fail", "erc_finding_count": 2}))\n'
            'sys.exit(3)\n')
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t), body)
        rc, resp = run_klt_rc(["erc", "x.gds", "s.json", "--findings-only"],
                              env=dict(os.environ), klt=klt)
        _check("run_klt_rc hands back klt's exit status", rc == 3, rc)
        _check("run_klt_rc hands back the parsed response",
               resp["erc_finding_count"] == 2, resp)

    # an `error` object is still fatal, which is the divergence #133 retired
    with tempfile.TemporaryDirectory() as t:
        klt = _fake_klt(Path(t),
                        'print(json.dumps({"error": {"message": "bad deck"}}))\n'
                        'sys.exit(3)\n')
        _raises("run_klt_rc still refuses a response carrying an error object",
                lambda: run_klt_rc(["erc", "x.gds"], env=dict(os.environ),
                                   klt=klt),
                "bad deck")


def check_compatibility_status_accepts_both_klt_spellings() -> None:
    """klt reports ``compatibility`` as a bare string on older builds and as a
    dict with a ``status`` since 0.9.x. Reading the dict form as a string
    compares a dict against ``"match"`` -- never equal -- so every HEALTHY
    install would be reported as flagged. This host's klt uses the dict
    form, which is how that false alarm was found."""
    cases = {
        "bare string (the shape the issue's text rendering showed)":
            ({"compatibility": "match"}, "match"),
        "dict with status (klt 0.9.x, this host)":
            ({"compatibility": {"status": "match", "package": "open_pdks-sky130",
                                "expected": {"value": "open_pdks f6eeac7"},
                                "installed": {"value": "open_pdks f6eeac7"}}},
             "match"),
        "dict reporting a real mismatch":
            ({"compatibility": {"status": "mismatch"}}, "mismatch"),
        "bare string reporting a real mismatch":
            ({"compatibility": "mismatch"}, "mismatch"),
        "absent": ({}, None),
        "dict without a status": ({"compatibility": {"package": "x"}}, None),
        "a shape that is neither": ({"compatibility": 7}, None),
    }
    for label, (response, want) in cases.items():
        got = compatibility_status(response)
        _check(f"compatibility_status reads {label}", got == want, got)

    _check("a healthy dict-form install is NOT reported as flagged",
           compatibility_status({"compatibility": {"status": "match"}}) == "match")


def check_pdk_find_warns_only_on_actionable_flags(capsys=None) -> None:
    """``ambiguous_roots`` is non-empty on every healthy call from a host that
    has both ~/.ciel and ~/.volare, so it must not warn; a broken symlink and
    a real compatibility mismatch must."""
    import subprocess as sp
    runner = Path(__file__).resolve().parent / "bin"

    def stderr_of(payload: dict) -> str:
        with tempfile.TemporaryDirectory() as t:
            klt = _fake_klt(Path(t), "print(json.dumps(%s))" % json.dumps(payload))
            code = ("import sys; sys.path.insert(0, %r)\n"
                    "from _klt_common import pdk_find\n"
                    "pdk_find('sky130A', klt=%r)\n" % (str(runner), klt))
            r = sp.run([sys.executable, "-c", code], capture_output=True, text=True)
            return r.stderr

    healthy = {"root": "/r", "compatibility": {"status": "match"},
               "ambiguous_roots": [{"root": "/home/u/.volare"}],
               "broken_symlinks": []}
    out = stderr_of(healthy)
    _check("a healthy install (with a shadowed root) warns about nothing",
           out.strip() == "", out)

    out = stderr_of({**healthy, "compatibility": {"status": "mismatch"}})
    _check("a compatibility mismatch warns", "compatibility 'mismatch'" in out, out)

    out = stderr_of({**healthy, "broken_symlinks": ["/r/dangling"]})
    _check("a broken symlink warns", "broken_symlinks" in out, out)


def check_against_the_real_klt_response_shape() -> None:
    """The fakes above encode an ASSUMPTION about klt's response. Check that
    assumption against the real tool where one is installed, so a fake that
    has drifted from klt cannot keep the suite green on its own terms.

    Skipped (not failed) with no klt and no PDK, which is the CI path."""
    import shutil
    import subprocess as sp
    if shutil.which("klt") is None:
        print("SKIP: no klt on PATH (expected on the PR-blocking CI path)")
        return
    r = sp.run(["klt", "pdk", "find", "--pdk", "sky130A", "--format", "json"],
               capture_output=True, text=True)
    try:
        real = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"SKIP: no PDK install to resolve (klt exit {r.returncode})")
        return
    _check("the real response carries a string 'root'",
           isinstance(real.get("root"), str) and real["root"], real.get("root"))
    _check("the real response carries assets.libs_ref, and libs_ref_of reads it",
           libs_ref_of(real) == Path(real["assets"]["libs_ref"]))
    _check("compatibility_status reads the real response's compatibility",
           compatibility_status(real) in ("match", "mismatch", None),
           real.get("compatibility"))
    _check("the real response carries the three fields the text scrape dropped",
           all(k in real for k in ("compatibility", "ambiguous_roots",
                                   "broken_symlinks")),
           sorted(real))


def check_the_bare_spelling_is_the_repo_convention() -> None:
    """``klt_version`` returns the spelling this repo's pins are written in."""
    repo = Path(__file__).resolve().parent.parent
    pdk_json = json.loads((repo / "layout" / "pdk.json").read_text())
    pin = pdk_json["klt_version_pin"]
    _check("layout/pdk.json's klt_version_pin is bare, as klt_version() returns",
           not pin.startswith("klt "), pin)


def check_the_migrated_sites_no_longer_scrape_text() -> None:
    """Defect 2's regression guard: the resolver this consolidated must not
    grow a text scrape back. A ``libs_ref:``-matching regex over klt's
    human-readable rendering is the exact shape that was retired -- it took
    the first match, so a ``warning:`` line could win."""
    repo = Path(__file__).resolve().parent.parent
    for rel in ("sim/post-layout-whole-block/make-gate-model.py",
                "sim/digital-electrical-repair/analysis/final_route_audit.py",
                "sim/digital-electrical-repair/analysis/derive_limits.py",
                "layout/bin/verify-whole.py"):
        text = (repo / rel).read_text()
        # the regex form, not the prose: a docstring may name the retired shape
        code = "\n".join(ln for ln in text.splitlines()
                          if "libs_ref:" in ln and "re.search" in ln)
        _check(f"{rel} does not regex-scrape a libs_ref: line", not code, code)
        _check(f"{rel} runs no raw `klt pdk find` subprocess",
               'subprocess.run([a.klt, "pdk"' not in text
               and 'subprocess.run(["klt", "pdk"' not in text
               and 'subprocess.run([args.klt, "pdk"' not in text)


def main() -> int:
    check_klt_version_is_bare()
    check_klt_version_fails_closed()
    check_pdk_find_always_asks_for_json()
    check_libs_ref_is_not_fooled_by_a_decoy()
    check_libs_ref_fails_closed()
    check_pdk_root_short_circuits_a_preset_root()
    check_pdk_root_reads_root_from_the_response()
    check_pdk_find_names_the_pdk_it_was_asked_for()
    check_run_klt_rc_reports_the_exit_status()
    check_compatibility_status_accepts_both_klt_spellings()
    check_pdk_find_warns_only_on_actionable_flags()
    check_against_the_real_klt_response_shape()
    check_the_bare_spelling_is_the_repo_convention()
    check_the_migrated_sites_no_longer_scrape_text()
    print(f"\n{sum(_RESULTS)}/{len(_RESULTS)} checks passed")
    return 0 if all(_RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
