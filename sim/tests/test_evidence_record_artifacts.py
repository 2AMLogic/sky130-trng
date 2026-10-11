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


class ReservedSummaryKeys(unittest.TestCase):
    """Issue #276: summary keys may not shadow writer-owned metadata."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()

    def mint(self, summary, artifacts=None):
        with mock.patch.object(er, "git_short_sha", return_value="abc1234"):
            return er.mint_behavioral_record(self.root, "slug", "claim", "body", summary, artifacts=artifacts)

    def test_every_reserved_key_rejected_without_output(self):
        src = Path(self._tmp.name) / "a.txt"
        src.write_text("x")
        for key in er.RESERVED_BEHAVIORAL_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(SystemExit) as cm:
                    self.mint({key: "forged", "ok": 1}, artifacts=[src])
                self.assertIn(key, str(cm.exception))
                self.assertEqual(list(self.root.rglob("*")), [])

    def test_all_conflicting_keys_named(self):
        with self.assertRaises(SystemExit) as cm:
            self.mint({"level": "transistor", "repo_sha": "x", "fine": 1})
        msg = str(cm.exception)
        self.assertIn("level", msg)
        self.assertIn("repo_sha", msg)
        self.assertNotIn("'fine'", msg)

    def test_reserved_set_covers_writer_json_fields(self):
        rid = self.mint({})
        rec = json.loads((self.root / "sim" / "slug" / "records" / f"{rid}.json").read_text())
        self.assertEqual(set(rec), set(er.RESERVED_BEHAVIORAL_KEYS))

    def test_ordinary_summary_shape_and_provenance_agree(self):
        rid = self.mint({"verdict": "PASS", "n": 3})
        d = self.root / "sim" / "slug" / "records"
        rec = json.loads((d / f"{rid}.json").read_text())
        self.assertEqual(rec["verdict"], "PASS")
        self.assertEqual(rec["n"], 3)
        self.assertEqual(rec["record_id"], rid)
        self.assertEqual(rec["level"], "behavioral")
        md = (d / f"{rid}.md").read_text()
        self.assertIn(f"# {rid} -- slug", md)
        self.assertIn("**Level**: behavioral", md)
        self.assertIn(f"`{rec['repo_sha']}`", md)


if __name__ == "__main__":
    unittest.main()
