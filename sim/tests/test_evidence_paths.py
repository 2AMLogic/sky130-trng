#!/usr/bin/env python3
"""Unit test for the shared evidence path-hygiene rule (issue #465).

    python3 sim/tests/test_evidence_paths.py

``sim/bin/evidence_paths.sanitize_paths`` is the one rule both digital
harnesses now use to rewrite absolute paths before they are written into
committed evidence. Before this module existed each harness carried its own
copy and the two had drifted; nothing pinned either behaviour. This test
pins the union rule case by case -- including the two cases the old copies
got wrong -- and pins the consolidation itself, so a future "quick local
tweak" to one harness cannot silently re-fork the rule.

Standard library only. No file is written anywhere; every path in the
behaviour table is a synthetic string, so the expectations do not depend on
the host's real ``$HOME``, ``$TMPDIR`` or checkout location.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "sim" / "tests"))
import evidence_paths as ep  # noqa: E402
from loadmod import load_module  # noqa: E402

MARKER = ep.EXTERNAL_PATH_MARKER

# Synthetic stand-ins, so the table below is host-independent.
ROOT = "/srv/sky130-trng"
HOME = "/home/op"
MAC_TMP = "/var/folders/q/5s_1x0td2gd0/T"   # a macOS $TMPDIR-shaped scratch root


def sanitize(obj, tmp_roots=(MAC_TMP, "/tmp")):
    return ep.sanitize_paths(obj, repo_root=ROOT, home=HOME, tmp_roots=tmp_roots)


class BehaviourTable(unittest.TestCase):
    """The union rule: in-repo -> repo-relative, host-local -> marker, else verbatim."""

    def test_in_repo_path_is_repo_relative(self):
        self.assertEqual(sanitize(f"{ROOT}/digital/rtl/trng_digital.v"),
                         "digital/rtl/trng_digital.v")

    def test_repo_root_itself_is_dot(self):
        self.assertEqual(sanitize(ROOT), ".")

    def test_tmp_path_is_external(self):
        # The old synthesis copy returned this verbatim.
        self.assertEqual(sanitize("/tmp/klt-x/a.json"), MARKER)

    def test_non_tmp_temp_dir_is_external(self):
        # The gap both old copies had, and the one that actually leaked:
        # the synthesis harness works in tempfile.mkdtemp(), which on macOS
        # is under $TMPDIR, not /tmp.
        self.assertEqual(sanitize(f"{MAC_TMP}/digital-synthesis-ab12/net.v"),
                         MARKER)

    def test_home_path_is_external(self):
        self.assertEqual(sanitize(f"{HOME}/pdk/sky130A/x.lib"), MARKER)

    def test_home_sibling_sharing_the_prefix_is_verbatim(self):
        # The old P&R copy matched home by string prefix and called this
        # sibling directory external. Containment is a path question.
        self.assertEqual(sanitize(f"{HOME}2/x.lib"), f"{HOME}2/x.lib")

    def test_tmp_sibling_sharing_the_prefix_is_verbatim(self):
        self.assertEqual(sanitize("/tmpfoo/x.lib"), "/tmpfoo/x.lib")

    def test_unrelated_system_path_is_verbatim(self):
        # Not host-identifying: leave it alone rather than blanking it.
        self.assertEqual(sanitize("/usr/bin/yosys"), "/usr/bin/yosys")

    def test_repo_inside_home_still_wins(self):
        out = ep.sanitize_paths(f"{HOME}/src/repo/sim/pdk.json",
                                repo_root=f"{HOME}/src/repo", home=HOME,
                                tmp_roots=("/tmp",))
        self.assertEqual(out, "sim/pdk.json")


class Recursion(unittest.TestCase):
    def test_walks_nested_containers_and_keeps_other_types(self):
        obj = {
            "netlist": f"{ROOT}/layout/trng_digital/a.v",
            "liberty": f"{HOME}/pdk/x.lib",
            "runs": [f"{MAC_TMP}/scratch/b.json", {"deck": "/tmp/c.sp"}],
            "cells": 412,
            "ok": True,
            "note": None,
            "relative": "sim/pdk.json",
            "flag": "--liberty",
        }
        self.assertEqual(sanitize(obj), {
            "netlist": "layout/trng_digital/a.v",
            "liberty": MARKER,
            "runs": [MARKER, {"deck": MARKER}],
            "cells": 412,
            "ok": True,
            "note": None,
            "relative": "sim/pdk.json",
            "flag": "--liberty",
        })

    def test_input_is_not_mutated(self):
        obj = {"p": [f"{HOME}/x.lib"]}
        sanitize(obj)
        self.assertEqual(obj, {"p": [f"{HOME}/x.lib"]})

    def test_tuples_are_left_alone(self):
        # Not JSON-shaped; the harnesses never emit one, and silently
        # converting it to a list would be a surprise.
        self.assertEqual(sanitize(("/tmp/a",)), ("/tmp/a",))


class TempRoots(unittest.TestCase):
    def test_honours_the_interpreter_temp_dir(self):
        with mock.patch.object(ep.tempfile, "gettempdir", return_value=MAC_TMP):
            self.assertEqual(ep.temp_roots(), (Path(MAC_TMP), Path("/tmp")))

    def test_tmp_is_always_included_and_not_duplicated(self):
        with mock.patch.object(ep.tempfile, "gettempdir", return_value="/tmp"):
            self.assertEqual(ep.temp_roots(), (Path("/tmp"),))

    def test_default_catches_a_real_mkdtemp_directory(self):
        # End-to-end against this host's actual tempfile configuration:
        # whatever mkdtemp() hands out must never reach an evidence record.
        scratch = Path(tempfile.mkdtemp(prefix="test-evidence-paths-"))
        try:
            out = ep.sanitize_paths(str(scratch / "synth.json"),
                                    repo_root=ROOT, home=HOME)
            self.assertEqual(out, MARKER)
        finally:
            scratch.rmdir()

    def test_real_repo_root_default(self):
        self.assertEqual(ep.sanitize_paths(str(REPO / "sim" / "pdk.json")),
                         "sim/pdk.json")


class Consolidation(unittest.TestCase):
    """Both harnesses must use the shared rule, not a private copy of it."""

    HARNESSES = {
        "synthesize-and-verify":
            REPO / "sim" / "digital-synthesis" / "harness" / "synthesize-and-verify.py",
        "pnr-and-verify":
            REPO / "sim" / "digital-pnr" / "harness" / "pnr-and-verify.py",
    }
    FORKED = ("_sanitize", "_sanitize_paths", "_EXTERNAL", "_EXTERNAL_PATH_MARKER")

    def test_each_harness_uses_the_shared_function(self):
        for name, path in self.HARNESSES.items():
            with self.subTest(harness=name):
                mod = load_module(name.replace("-", "_"), path)
                self.assertIs(mod.sanitize_paths, ep.sanitize_paths)
                for attr in self.FORKED:
                    self.assertFalse(
                        hasattr(mod, attr),
                        f"{name} re-forked the path rule as {attr}; "
                        "extend sim/bin/evidence_paths.py instead (issue #465)")

    def test_marker_string_is_defined_once(self):
        for name, path in self.HARNESSES.items():
            with self.subTest(harness=name):
                self.assertNotIn("<external -- not recorded by absolute location",
                                 path.read_text())


if __name__ == "__main__":
    unittest.main()
