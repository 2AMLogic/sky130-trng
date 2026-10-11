#!/usr/bin/env python3
"""Regression tests for artifact-name collisions in sim/bin/evidence_record.mint_behavioral_record (issue #273).

    python3 sim/tests/test_evidence_record_artifacts.py

Standard library only. Everything runs in temporary directories; nothing is written to the committed sim/ tree.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
import evidence_record as er  # noqa: E402


def mint(root: Path, artifacts):
    with mock.patch.object(er, "git_short_sha", return_value="abc1234"):
        return er.mint_behavioral_record(root, "slug", "claim", "body", {"k": 1}, artifacts=artifacts)


class ArtifactCollision(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "repo"
        self.root.mkdir()

    def write(self, rel, text):
        p = self.tmp / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_duplicate_basename_rejected_without_output(self):
        a = self.write("a/trace.txt", "first")
        b = self.write("b/trace.txt", "second")
        with self.assertRaises(SystemExit) as cm:
            mint(self.root, [a, b])
        msg = str(cm.exception)
        self.assertIn(str(a), msg)
        self.assertIn(str(b), msg)
        self.assertEqual(list(self.root.rglob("*")), [])

    def test_repeated_source_path_rejected_without_output(self):
        a = self.write("a/trace.txt", "first")
        with self.assertRaises(SystemExit) as cm:
            mint(self.root, [a, a])
        self.assertIn(str(a), str(cm.exception))
        self.assertEqual(list(self.root.rglob("*")), [])

    def test_unique_basenames_preserve_bytes_and_format(self):
        a = self.write("a/one.txt", "first")
        b = self.write("b/two.txt", "second")
        rid = mint(self.root, [a, b])
        runs = self.root / "sim" / "slug" / "runs" / rid
        self.assertEqual((runs / "one.txt").read_text(), "first")
        self.assertEqual((runs / "two.txt").read_text(), "second")
        rec = json.loads((self.root / "sim" / "slug" / "records" / f"{rid}.json").read_text())
        self.assertEqual(rec["artifacts"],
                         [f"sim/slug/runs/{rid}/one.txt", f"sim/slug/runs/{rid}/two.txt"])


def snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class PublicationIntegrity(unittest.TestCase):
    """Issue #277: complete bundles, exclusive id reservation, owned cleanup."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.art = self.tmp / "a.txt"
        self.art.write_text("data")
        self.recs = self.root / "sim" / "slug" / "records"

    def mint_rec(self, summary, rid="20260101-000000-abc1234"):
        import datetime as dt
        return er.mint_record(self.recs, self.root, rid, ["# h", ""], "body\n", summary,
                              author="t", now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                              sha="abc1234")

    def seed(self):
        """Mint one good behavioural record so there is existing evidence."""
        with mock.patch.object(er, "new_record_id", return_value=(
                __import__("datetime").datetime(2026, 1, 1), "abc1234", "20260101-000000-abc1234")):
            return er.mint_behavioral_record(self.root, "slug", "c", "b", {"k": 1},
                                             artifacts=[self.art])

    def behav(self, rid="20260101-000001-abc1234", summary=None, artifacts=None):
        import datetime as dt
        with mock.patch.object(er, "new_record_id",
                               return_value=(dt.datetime(2026, 1, 1), "abc1234", rid)):
            return er.mint_behavioral_record(self.root, "slug", "c", "b", summary or {"k": 2},
                                             artifacts=artifacts)

    def test_mint_record_invalid_json_leaves_nothing(self):
        with self.assertRaises(TypeError):
            self.mint_rec({"bad": object()})
        self.assertEqual(snapshot(self.root), {})

    def test_behavioral_invalid_json_leaves_nothing(self):
        with self.assertRaises(TypeError):
            self.behav(summary={"bad": {1, 2}}, artifacts=[self.art])
        self.assertEqual(snapshot(self.root), {})

    def test_missing_artifact_leaves_nothing(self):
        with self.assertRaises(SystemExit):
            self.behav(artifacts=[self.tmp / "nope.txt"])
        self.assertEqual(snapshot(self.root), {})

    def test_success_with_artifacts_both_apis(self):
        rid = self.seed()
        base = self.root / "sim" / "slug"
        self.assertTrue((base / "records" / f"{rid}.md").is_file())
        self.assertEqual((base / "runs" / rid / "a.txt").read_text(), "data")
        self.assertIsNotNone(self.mint_rec({"x": 1}, rid="20260101-000009-abc1234"))
        names = sorted(p.name for p in self.recs.iterdir())
        self.assertEqual(names, [f"{rid}.json", f"{rid}.md",
                                 "20260101-000009-abc1234.json", "20260101-000009-abc1234.md"])

    def _inject(self, target, call):
        self.seed()
        before = snapshot(self.root)
        with mock.patch.object(er, target, side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                call()
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(sorted(p.name for p in self.recs.iterdir() if p.name.startswith(".")), [])

    def test_artifact_copy_failure_behavioral(self):
        self._inject("_link_noreplace", lambda: self.behav(artifacts=[self.art]))

    def test_publication_failure_mint_record(self):
        self._inject("_link_noreplace", lambda: self.mint_rec({"x": 1}, rid="20260101-000009-abc1234"))

    def test_copy_failure_cleans_stage(self):
        self.seed()
        before = snapshot(self.root)
        with mock.patch.object(er.shutil, "copy2", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.behav(artifacts=[self.art])
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(any(p.name.startswith(".") for p in (self.root / "sim/slug/runs").iterdir()))

    def test_late_publication_failure_removes_published_pieces(self):
        self.seed()
        before = snapshot(self.root)
        real = er._link_noreplace
        calls = []

        def flaky(src, dst):
            calls.append(dst.name)
            if len(calls) == 2:  # the .md step, after runs dir + json published
                raise OSError("injected")
            real(src, dst)
        with mock.patch.object(er, "_link_noreplace", side_effect=flaky):
            with self.assertRaises(OSError):
                self.behav(artifacts=[self.art])
        self.assertEqual(snapshot(self.root), before)

    def test_same_id_collision_after_success_keeps_original(self):
        rid = self.seed()
        before = snapshot(self.root)
        with self.assertRaises(SystemExit) as cm:
            self.behav(rid=rid, artifacts=[self.art])
        self.assertIn("already exists", str(cm.exception))
        self.assertEqual(snapshot(self.root), before)
        self.assertIsNone(self.mint_rec({"x": 1}, rid=rid))
        self.assertEqual(snapshot(self.root), before)

    def test_concurrent_reservation_loses_cleanly(self):
        """A writer holding the reservation makes the other get a clear collision."""
        rid = "20260101-000002-abc1234"
        self.recs.mkdir(parents=True)
        (self.recs / f".{rid}.reserve").write_text("pid=1\n")
        before = snapshot(self.root)
        with self.assertRaises(SystemExit) as cm:
            self.behav(rid=rid, artifacts=[self.art])
        self.assertIn("reserved", str(cm.exception))
        self.assertIsNone(self.mint_rec({"x": 1}, rid=rid))
        # the other writer's reservation is not ours to remove
        self.assertEqual(snapshot(self.root), before)

    def test_two_writers_racing_same_id_one_wins(self):
        import threading
        rid = "20260101-000003-abc1234"
        barrier = threading.Barrier(2)
        orig = Path.exists

        def synced(self_, *a, **k):
            r = orig(self_, *a, **k)
            if self_.name == f"{rid}.md":
                try:
                    barrier.wait(timeout=2)
                except threading.BrokenBarrierError:
                    pass
            return r
        results = []

        def worker():
            try:
                results.append(("ok", self.behav(rid=rid, artifacts=[self.art])))
            except SystemExit as e:
                results.append(("collision", str(e)))
        with mock.patch.object(Path, "exists", synced):
            ts = [threading.Thread(target=worker) for _ in range(2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(sorted(r[0] for r in results), ["collision", "ok"])
        self.assertEqual((self.root / "sim/slug/runs" / rid / "a.txt").read_text(), "data")
        self.assertEqual(len(list(self.recs.glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
