#!/usr/bin/env python3
"""Unit + end-to-end test for sim/bin/check_records_append_only.py (issue #232).
Builds a throwaway git repo; stdlib only."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "check_records_append_only.py"
spec = importlib.util.spec_from_file_location("chk", SCRIPT)
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)


class Parse(unittest.TestCase):
    def test_statuses(self):
        z = "A\0sim/a/records/new.json\0M\0sim/a/records/x.json\0D\0sim/a/records/y.md\0M\0sim/a/other.md\0"
        self.assertEqual(chk.violations(z), [("M", "sim/a/records/x.json"), ("D", "sim/a/records/y.md")])

    def test_allowlist(self):
        z = "M\0sim/a/records/x.json\0"
        self.assertEqual(chk.violations(z, {"sim/a/records/x.json"}), [])


class EndToEnd(unittest.TestCase):
    def git(self, d, *a):
        subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                       check=True, capture_output=True)

    def run_check(self, d):
        # run the real script's logic against the temp repo
        chk.REPO = Path(d)
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = chk.main(["x", "base"])
        return rc, err.getvalue()

    def test_flow(self):
        with tempfile.TemporaryDirectory() as d:
            self.git(d, "init", "-q", "-b", "main")
            rec = Path(d, "sim/s/records"); rec.mkdir(parents=True)
            (rec / "r1.json").write_text("{}\n")
            self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "base")
            self.git(d, "branch", "base")
            (rec / "r2.json").write_text("{}\n")
            self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "add")
            self.assertEqual(self.run_check(d)[0], 0)
            (rec / "r1.json").write_text('{"x":1}\n')
            self.git(d, "commit", "-qam", "edit")
            rc, err = self.run_check(d)
            self.assertEqual(rc, 1); self.assertIn("sim/s/records/r1.json", err)
            self.git(d, "checkout", "-q", "-B", "ren", "base")
            self.git(d, "mv", "sim/s/records/r1.json", "sim/s/records/r9.json")
            self.git(d, "commit", "-qm", "rename")
            rc, err = self.run_check(d)
            self.assertEqual(rc, 1); self.assertIn("records/r1.json", err)


if __name__ == "__main__":
    unittest.main()
