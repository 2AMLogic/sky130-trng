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


class Artifacts(unittest.TestCase):
    ids = {("sim", "s", "r1")}

    def v(self, z, **k):
        return chk.violations(z, record_ids=self.ids, **k)

    def test_base_record_ids(self):
        ls = ("sim/s/records/r1.md\nsim/s/records/r1.json\nsim/s/records/d1/x.json\n"
              "sim/s/runs/u/a.txt\nsim/t/records/r2.md\n")
        self.assertEqual(chk.base_record_ids(ls), {("sim", "s", "r1"), ("sim", "s", "d1"), ("sim", "t", "r2")})

    def test_protected(self):
        z = ("M\0sim/s/runs/r1/a/b/c.json\0D\0sim/s/corners/r1/tt.log\0"
             "T\0sim/s/runs/r1/x.txt\0A\0sim/s/runs/r1/new.txt\0"
             "M\0sim/s/runs/other/a.txt\0M\0sim/s/harness/h.py\0"
             "M\0sim/t/runs/r1/a.txt\0")
        self.assertEqual([p for _, p in self.v(z)],
                         ["sim/s/runs/r1/a/b/c.json", "sim/s/corners/r1/tt.log",
                          "sim/s/runs/r1/x.txt"])

    def test_roots_do_not_cross_associate(self):
        z = "M\0measurements/s/runs/r1/a.txt\0M\0measurements/s/records/r1.md\0"
        self.assertEqual([p for _, p in self.v(z)], ["measurements/s/records/r1.md"])
        ids = {("measurements", "s", "r1")}
        z = "M\0sim/s/runs/r1/a.txt\0M\0measurements/s/corners/r1/a.txt\0"
        self.assertEqual([p for _, p in chk.violations(z, record_ids=ids)],
                         ["measurements/s/corners/r1/a.txt"])

    def test_allow(self):
        self.assertEqual(self.v("M\0sim/s/runs/r1/a.txt\0", allow={"sim/s/runs/r1/a.txt"}), [])


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

    def repo(self, d):
        self.git(d, "init", "-q", "-b", "main")
        for f in ("records/r1.json", "records/r1.md", "runs/r1/a/b.json",
                  "corners/r1/tt.log", "runs/old/x.txt", "harness/h.py"):
            p = Path(d, "sim/s", f); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("0\n")
        self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "base")
        self.git(d, "branch", "base")

    def test_artifacts(self):
        def case(mutate, rc_expected, needle=None):
            with tempfile.TemporaryDirectory() as d:
                self.repo(d)
                mutate(d)
                self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "m")
                rc, err = self.run_check(d)
                self.assertEqual(rc, rc_expected, err)
                if needle:
                    self.assertIn(needle, err)
        w = lambda d, f, t="1\n": Path(d, "sim/s", f).write_text(t)
        rm_rec = lambda d: self.git(d, "rm", "-q", "sim/s/records/r1.json", "sim/s/records/r1.md")
        case(lambda d: w(d, "runs/r1/a/b.json"), 1, "runs/r1/a/b.json")
        case(lambda d: w(d, "corners/r1/tt.log"), 1, "corners/r1/tt.log")
        case(lambda d: Path(d, "sim/s/runs/r1/a/b.json").unlink(), 1, "b.json")
        case(lambda d: self.git(d, "mv", "sim/s/runs/r1", "sim/s/runs/r9"), 1, "runs/r1/a/b.json")

        def typechange(d):
            p = Path(d, "sim/s/corners/r1/tt.log"); p.unlink(); p.symlink_to("x")
        case(typechange, 1, "corners/r1/tt.log")

        def gone(d):  # record removed in same PR must not unprotect
            rm_rec(d); w(d, "runs/r1/a/b.json")
        case(gone, 1, "runs/r1/a/b.json")

        def renamed(d):
            self.git(d, "mv", "sim/s/records/r1.json", "sim/s/records/r9.json")
            self.git(d, "mv", "sim/s/runs/r1", "sim/s/runs/r9")
        case(renamed, 1, "records/r1.json")

        def fresh(d):  # new record + new artifact dirs, additions inside old dirs
            w(d, "records/r2.json"); w(d, "records/r2.md")
            for f in ("runs/r2/a.txt", "corners/r2/tt.log"):
                Path(d, "sim/s", f).parent.mkdir(parents=True, exist_ok=True); w(d, f)
            w(d, "runs/r1/extra.txt")
        case(fresh, 0)
        case(lambda d: w(d, "harness/h.py"), 0)
        case(lambda d: w(d, "runs/old/x.txt"), 0)  # unassociated dir

        def allowed(d):
            w(d, "runs/r1/a/b.json")
            Path(d, "sim/records-append-only-allowlist.txt").write_text(
                "sim/s/runs/r1/a/b.json\n")
        case(allowed, 0)

    def test_measurements_and_collision(self):
        def mk(d, roots):
            self.git(d, "init", "-q", "-b", "main")
            for root in roots:
                for f in ("records/r1.json", "records/r1.md", "runs/r1/a/b.txt", "runs/old/x.txt"):
                    p = Path(d, root, "s", f); p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("0\n")
            self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "base")
            self.git(d, "branch", "base")

        def case(roots, mutate, rc_expected, needle=None):
            with tempfile.TemporaryDirectory() as d:
                mk(d, roots)
                mutate(d)
                self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "m")
                rc, err = self.run_check(d)
                self.assertEqual(rc, rc_expected, err)
                if needle:
                    self.assertIn(needle, err)
        M = ("measurements",)
        w = lambda d, f, t="1\n": Path(d, "measurements/s", f).write_text(t)
        case(M, lambda d: w(d, "records/r1.json"), 1, "measurements/s/records/r1.json")
        case(M, lambda d: w(d, "runs/r1/a/b.txt"), 1, "measurements/s/runs/r1/a/b.txt")
        case(M, lambda d: Path(d, "measurements/s/runs/r1/a/b.txt").unlink(), 1, "b.txt")
        case(M, lambda d: Path(d, "measurements/s/records/r1.md").unlink(), 1, "records/r1.md")
        case(M, lambda d: self.git(d, "mv", "measurements/s/runs/r1", "measurements/s/runs/r9"),
             1, "runs/r1/a/b.txt")
        case(M, lambda d: self.git(d, "mv", "measurements/s/records/r1.json",
                                   "measurements/s/records/r9.json"), 1, "records/r1.json")

        def typechange(d):
            p = Path(d, "measurements/s/runs/r1/a/b.txt"); p.unlink(); p.symlink_to("x")
        case(M, typechange, 1, "b.txt")

        def gone(d):  # record removed + capture mutated in the same change
            self.git(d, "rm", "-q", "measurements/s/records/r1.json", "measurements/s/records/r1.md")
            w(d, "runs/r1/a/b.txt")
        case(M, gone, 1, "runs/r1/a/b.txt")

        def fresh(d):
            w(d, "records/r2.json")
            Path(d, "measurements/s/runs/r2").mkdir(); w(d, "runs/r2/c.txt")
            w(d, "runs/r1/extra.txt"); w(d, "runs/old/x.txt")
            Path(d, "measurements/index.md").write_text("idx\n")
            Path(d, "measurements/README.md").write_text("doc\n")
        case(M, fresh, 0)

        def allowed(d):
            w(d, "runs/r1/a/b.txt")
            Path(d, "sim").mkdir(exist_ok=True)
            Path(d, "sim/records-append-only-allowlist.txt").write_text(
                "measurements/s/runs/r1/a/b.txt\n")
        case(M, allowed, 0)

        # root collision: record r1 exists only under sim/ -> measurements scratch
        # dir of the same slug/id is unassociated, and vice versa.
        def scratch(d, root):
            p = Path(d, root, "s/runs/r1/a/b.txt"); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("1\n")
        for rec_root, scratch_root, rc in (("sim", "measurements", 0), ("measurements", "sim", 0)):
            with tempfile.TemporaryDirectory() as d:
                self.git(d, "init", "-q", "-b", "main")
                for root, kind in ((rec_root, "records/r1.json"), (scratch_root, "runs/r1/a/b.txt")):
                    p = Path(d, root, "s", kind); p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("0\n")
                self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "base")
                self.git(d, "branch", "base")
                scratch(d, scratch_root)
                self.git(d, "add", "-A"); self.git(d, "commit", "-qm", "m")
                self.assertEqual(self.run_check(d)[0], rc)


if __name__ == "__main__":
    unittest.main()
