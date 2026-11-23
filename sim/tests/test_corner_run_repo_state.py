"""corner-run.py repo_state() must report dirty as a tri-state (issue #692):
True / False, and None -- never False -- when `git status` cannot run."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
from loadmod import load_module  # noqa: E402


class RepoStateTriState(unittest.TestCase):
    def setUp(self):
        self.cr = load_module("corner_run_repo_state_under_test",
                              REPO / "sim" / "bin" / "corner-run.py", register=True)

    def test_unrunnable_git_status_is_unknown_not_clean(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(self.cr, "REPO_ROOT", Path(d)):  # not a git repo
            self.assertIsNone(self.cr.repo_state()["dirty"])

    def test_clean_and_dirty(self):
        for paths, want in (([], False), (["a.txt"], True)):
            with mock.patch.object(self.cr, "git_dirty_paths", return_value=paths):
                self.assertIs(self.cr.repo_state()["dirty"], want)

    def test_suffix_names_unknown(self):
        self.assertIn("unknown", self.cr._dirty_suffix(None))
        self.assertEqual(self.cr._dirty_suffix(False), "")
        self.assertIn("dirty", self.cr._dirty_suffix(True))


if __name__ == "__main__":
    unittest.main()
