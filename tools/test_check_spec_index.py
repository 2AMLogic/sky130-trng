#!/usr/bin/env python3
"""Negative controls for tools/check_spec_index.py (issue #296). Stdlib only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_spec_index as ci  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def rec(status="Proposed"):
    return "---\ndr: x\n---\n\n# T\n\n## Status\n\n- 2026-01-01: **%s.** x\n\n## Context\n\nc\n" % status


def entry(n, status="Proposed"):
    name = "DR-%04d-x.md" % n
    return ("- [`decision-records/%s`](decision-records/%s)\n  — **%s**. blurb\n\n"
            % (name, name, status))


def make(root, nums=(11, 12, 14), skip_index=(), extra_index="",
         rec_status=None, idx_status=None):
    d = root / "spec" / "decision-records"
    d.mkdir(parents=True)
    idx = "# spec\n\n## Decision records\n\n"
    for n in nums:
        (d / ("DR-%04d-x.md" % n)).write_text(
            rec((rec_status or {}).get(n, "Proposed")))
        if n not in skip_index:
            idx += entry(n, (idx_status or {}).get(n, "Proposed"))
    (root / "spec" / "README.md").write_text(idx + extra_index)


class T(unittest.TestCase):
    def run_case(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            make(Path(d), **kw)
            return ci.check(d)

    def test_clean_fixture_passes(self):
        # DR-0001..0010 absent would be gaps; fixture starts at 1 via nums
        self.assertEqual(self.run_case(nums=tuple(range(1, 13)) + (14,)), [])

    def test_unindexed_record_fails(self):
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,), skip_index=(11,))
        self.assertTrue(any("not indexed" in e and "DR-0011" in e for e in errs), errs)

    def test_dangling_link_fails(self):
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             extra_index=entry(99))
        self.assertTrue(any("missing record" in e and "DR-0099" in e for e in errs), errs)

    def test_index_overstating_status_fails(self):
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             idx_status={3: "Accepted"})
        self.assertTrue(any("mismatch" in e and "overstates" in e for e in errs), errs)

    def test_record_ahead_of_index_fails(self):
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             rec_status={3: "Accepted"})
        self.assertTrue(any("status mismatch" in e and "DR-0003" in e for e in errs), errs)

    def test_unlisted_gap_fails(self):
        errs = self.run_case(nums=tuple(range(1, 8)) + tuple(range(9, 13)) + (14,))
        self.assertTrue(any("gap: DR-0008" in e for e in errs), errs)

    def test_allowlisted_gap_does_not_fail(self):
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,))
        self.assertFalse(any("DR-0013" in e for e in errs), errs)

    def test_real_tree_is_consistent(self):
        self.assertEqual(ci.check(REPO), [])


if __name__ == "__main__":
    unittest.main()
