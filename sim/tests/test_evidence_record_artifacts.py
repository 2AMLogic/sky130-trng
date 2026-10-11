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


if __name__ == "__main__":
    unittest.main()
