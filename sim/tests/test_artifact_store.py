#!/usr/bin/env python3
"""Tests for sim/bin/artifact_store.py and check_artifact_manifests.py (issue #347).

    python3 sim/tests/test_artifact_store.py

Stdlib only; uses a fake ``klt`` (sim/tests/fake_klt.py) so no broker is needed.
Everything runs in temporary directories.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "sim" / "tests"))
import artifact_store as ast  # noqa: E402
import check_artifact_manifests as cam  # noqa: E402
import fake_klt  # noqa: E402
from loadmod import load_module  # noqa: E402


def snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class Base(unittest.TestCase):
    mode = "ok"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        p = mock.patch.dict(os.environ, fake_klt.install(self.tmp / "bin", self.mode))
        p.start()
        self.addCleanup(p.stop)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.src = self.tmp / "src"
        self.src.mkdir()

    def f(self, name, data=b"bytes"):
        p = self.src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p


class StoreRun(Base):
    def test_success_writes_artifact_uri_manifest_and_summary(self):
        a, b = self.f("a.log", b"alpha"), self.f("b.txt", b"beta")
        run = ast.store_run(self.root, "bench", "20260101-000000-abc", [a, b])
        doc = json.loads(run.manifest.read_text())
        self.assertEqual(run.manifest, self.root / "manifests/artifacts/bench-20260101-000000-abc.manifest.json")
        self.assertTrue(all(e["uri"].startswith("artifact:") for e in doc["entries"]))
        self.assertEqual([e["name"] for e in doc["entries"]],
                         ["sim/bench/runs/20260101-000000-abc/a.log", "sim/bench/runs/20260101-000000-abc/b.txt"])
        self.assertEqual(doc["entries"][0]["sha256"], hashlib.sha256(b"alpha").hexdigest())
        md = run.summary.read_text()
        self.assertIn(hashlib.sha256(b"beta").hexdigest(), md)
        self.assertEqual(cam.validate_manifest(run.manifest.read_text())[0], [])
        self.assertEqual(run.summary, self.root / "sim/bench/artifacts/20260101-000000-abc.md")
        # no raw bytes and no staging left in the tree
        self.assertEqual(sorted(snapshot(self.root)), [
            "manifests/artifacts/bench-20260101-000000-abc.manifest.json",
            "sim/bench/artifacts/20260101-000000-abc.md"])

    def test_empty_output_file_is_stored(self):
        run = ast.store_run(self.root, "bench", "r1", [self.f("empty.txt", b"")])
        self.assertEqual(json.loads(run.manifest.read_text())["entries"][0]["size"], 0)

    def test_rerun_same_run_id_refused_and_first_kept(self):
        a = self.f("a.txt")
        ast.store_run(self.root, "bench", "r1", [a])
        before = snapshot(self.root)
        with self.assertRaises(ast.ArtifactStoreError):
            ast.store_run(self.root, "bench", "r1", [a])
        self.assertEqual(snapshot(self.root), before)

    def test_bad_inputs_refused_without_output(self):
        a, b = self.f("x/a.txt"), self.f("y/a.txt")
        for args in (("bench", "r1", [a, b]), ("bench", "r1", [self.src / "nope"]), ("bench", "r1", []),
                     ("../x", "r1", [a]), ("bench", "r/1", [a])):
            with self.assertRaises(ast.ArtifactStoreError):
                ast.store_run(self.root, *args)
        self.assertEqual(snapshot(self.root), {})

    def test_broker_url_never_in_argv_or_files(self):
        run = ast.store_run(self.root, "bench", "r1", [self.f("a.txt")])
        for text in snapshot(self.root).values():
            self.assertNotIn(b"broker.invalid", text)
        self.assertNotIn("s3://", run.manifest.read_text())


class FailClosed(Base):
    def assert_nothing_committed(self):
        left = [p for p in snapshot(self.root) if not p.startswith(".artifact-staging/")]
        self.assertEqual(left, [])

    def test_broker_unset(self):
        a = self.f("a.txt")
        with mock.patch.dict(os.environ):
            del os.environ["KLT_ARTIFACT_BROKER"]
            with self.assertRaises(ast.ArtifactStoreError) as cm:
                ast.store_run(self.root, "bench", "r1", [a])
        self.assertIn("KLT_ARTIFACT_BROKER", str(cm.exception))
        self.assertEqual(snapshot(self.root), {})

    def test_klt_missing(self):
        with self.assertRaises(ast.ArtifactStoreError):
            ast.store_run(self.root, "bench", "r1", [self.f("a.txt")], klt="klt-does-not-exist")
        self.assertEqual(snapshot(self.root), {})


class NoVerb(FailClosed):
    mode = "noverb"

    def test_klt_without_artifact_put(self):
        with self.assertRaises(ast.ArtifactStoreError) as cm:
            ast.store_run(self.root, "bench", "r1", [self.f("a.txt")])
        self.assertIn("artifact put", str(cm.exception))
        self.assertEqual(snapshot(self.root), {})


class Unreachable(FailClosed):
    mode = "unreachable"

    def test_put_failure_keeps_staged_bytes_and_hides_broker(self):
        with self.assertRaises(ast.ArtifactStoreError) as cm:
            ast.store_run(self.root, "bench", "r1", [self.f("a.txt", b"keep")])
        self.assertNotIn("broker.invalid", str(cm.exception))
        self.assert_nothing_committed()
        self.assertEqual((self.root / ".artifact-staging/bench-r1/a.txt").read_bytes(), b"keep")


class Partial(FailClosed):
    mode = "partial"

    def test_put_failure_midway_commits_no_partial_manifest(self):
        with self.assertRaises(ast.ArtifactStoreError):
            ast.store_run(self.root, "bench", "r1", [self.f("a.txt"), self.f("b.txt")])
        self.assert_nothing_committed()


class Checker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")

    def git(self, *a):
        subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)

    def commit(self, files: dict):
        for rel, data in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data if isinstance(data, bytes) else data.encode())
        self.git("add", "-A")
        self.git("commit", "-qm", "c")

    @staticmethod
    def manifest(data=b"payload", **over):
        e = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "kind": "evidence",
             "producer": {"tool": "klt", "version": "1"}, "uri": "artifact:k/1", "name": "n"}
        e.update(over)
        return json.dumps({"schema_version": 1, "entries": [e]})

    def check(self):
        return cam.check_tree(self.repo, "HEAD")

    def test_valid_manifest_passes(self):
        self.commit({"manifests/artifacts/a-1.manifest.json": self.manifest(), "manifests/artifacts/README.md": "x"})
        self.assertEqual(self.check(), [])

    def test_no_manifests_passes(self):
        self.commit({"README.md": "x"})
        self.assertEqual(self.check(), [])

    def test_non_artifact_uris_rejected(self):
        for uri in ("s3://bucket/key", "https://example.invalid/x", "", "artifact:", "bare-key"):
            with self.subTest(uri=uri):
                self.commit({"manifests/artifacts/a-1.manifest.json": self.manifest(uri=uri)})
                self.assertTrue(any("uri" in p for p in self.check()))

    def test_bucket_or_account_text_rejected_anywhere(self):
        self.commit({"manifests/artifacts/a-1.manifest.json": self.manifest(name="arn:aws:iam::1:role/x")})
        self.assertTrue(any("arn:aws:" in p for p in self.check()))

    def test_schema_violations(self):
        bad = [json.dumps({"schema_version": 2, "entries": []}), "not json", json.dumps([]),
               self.manifest(sha256="ABC"), self.manifest(size=-1), self.manifest(size=True),
               self.manifest(kind="other"), self.manifest(extra=1),
               json.dumps({"schema_version": 1, "entries": [{"sha256": "0" * 64}]})]
        for text in bad:
            with self.subTest(text=text[:60]):
                self.commit({"manifests/artifacts/a-1.manifest.json": text})
                self.assertTrue(self.check())

    def test_committed_bytes_of_stored_object_rejected(self):
        self.commit({"manifests/artifacts/a-1.manifest.json": self.manifest(b"payload"),
                     "sim/b/runs/r/out.log": b"payload"})
        probs = self.check()
        self.assertEqual(len(probs), 1)
        self.assertIn("sim/b/runs/r/out.log", probs[0])

    def test_same_size_different_bytes_and_empty_files_pass(self):
        self.commit({"manifests/artifacts/a-1.manifest.json": self.manifest(b"payload"),
                     "sim/b/other.log": b"PAYLOAD", "sim/b/empty": b""})
        self.assertEqual(self.check(), [])

    def test_tracked_staging_dir_and_stray_file_rejected(self):
        self.commit({".artifact-staging/b-r/x": b"1", "manifests/artifacts/notes.txt": "x"})
        self.assertEqual(len(self.check()), 2)

    def test_cli_exit_codes(self):
        script = REPO / "sim" / "bin" / "check_artifact_manifests.py"
        self.commit({"manifests/artifacts/a-1.manifest.json": self.manifest()})
        run = lambda *a: subprocess.run([sys.executable, str(script), "check", "--repo", str(self.repo), *a],
                                        capture_output=True, text=True).returncode
        self.assertEqual(run("--tree", "HEAD"), 0)
        self.assertEqual(run("--tree", "nonexistent-ref"), 2)
        self.commit({"manifests/artifacts/a-1.manifest.json": self.manifest(uri="s3://x/y")})
        self.assertEqual(run(), 1)


class CornerRunFailClosed(unittest.TestCase):
    """corner-run.py must refuse before running ngspice when the store is unusable."""

    def test_exits_nonzero_without_broker_and_writes_nothing(self):
        cr = load_module("corner_run_under_test", REPO / "sim" / "bin" / "corner-run.py", register=True)
        with tempfile.TemporaryDirectory() as d:
            tb = Path(d) / "tb.spice"
            tb.write_text("* tb\n.end\n")
            env = {k: v for k, v in os.environ.items() if k != "KLT_ARTIFACT_BROKER"}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(cr, "load_pin", return_value={"process_corners": ["tt"], "default_corners": ["tt"]}), \
                    mock.patch.object(cr, "resolve_pdk", return_value=mock.Mock(matches_pin=True)), \
                    mock.patch.object(cr.shutil, "which", return_value="/bin/true"), \
                    mock.patch.object(cr, "run_corner", side_effect=AssertionError("ngspice must not run")), \
                    mock.patch.object(cr, "SIM_DIR", Path(d) / "sim"):
                rc = cr.main([str(tb), "--slug", "s", "--claim", "c"])
            self.assertEqual(rc, 1)
            self.assertFalse((Path(d) / "sim").exists())


class CornerRunWriteRecord(Base):
    """write_record stores logs in the artifact store and commits no corners/ bytes."""

    def test_record_points_at_manifest_and_commits_no_logs(self):
        cr = load_module("corner_run_wr_under_test", REPO / "sim" / "bin" / "corner-run.py", register=True)
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        (scratch / "tt.log").write_text("log bytes")
        (scratch / "tt.onoise.txt").write_text("1 2\n")
        res = cr.CornerResult(corner="tt", ok=True, returncode=0, deck_path=scratch / "tt.spice",
                              log_path=scratch / "tt.log", measurements={"x": 1.0})
        pdk = mock.Mock(variant="v", installed_commit="c", matches_pin=True, lib_file="/l",
                        pin={"open_pdks_commit": "c"})
        tb = self.root / "tb.spice"
        tb.parent.mkdir(exist_ok=True)
        tb.write_text("* tb")
        with mock.patch.object(cr, "REPO_ROOT", self.root), mock.patch.object(cr, "SIM_DIR", self.root / "sim"), \
                mock.patch.object(cr, "repo_state", return_value={"sha": "s", "dirty": False, "branch": "b"}), \
                mock.patch.object(cr, "first_line", return_value="v"):
            cr.write_record(rid="20260101-000000-abc", slug="bench", claim="c", level="transistor", seed="n/a",
                            testbench=tb, pdk=pdk, netlists={}, results=[res], author="t", subset_reason=None,
                            supersedes=None, temp_c=27.0, vdd_v=1.8, tmax="5p", noise_amp="0")
        rec = json.loads((self.root / "sim/bench/records/20260101-000000-abc.json").read_text())
        self.assertEqual(rec["artifact_manifest"], "manifests/artifacts/bench-20260101-000000-abc.manifest.json")
        man = json.loads((self.root / rec["artifact_manifest"]).read_text())
        self.assertEqual(sorted(Path(e["name"]).name for e in man["entries"]), ["tt.log", "tt.onoise.txt"])
        self.assertFalse((self.root / "sim/bench/corners").exists())
        self.assertFalse(any(n.endswith((".log", "onoise.txt")) for n in snapshot(self.root)))


if __name__ == "__main__":
    unittest.main()
