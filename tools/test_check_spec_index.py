#!/usr/bin/env python3
"""Negative controls for tools/check_spec_index.py (issue #296). Stdlib only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_spec_index as ci  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def rec(status="Proposed", fm_status=None, history=None):
    """Build a fixture record.

    status    -- the single bold word in the ## Status section.  Ignored when
                 `history` is given.
    fm_status -- the `status:` front-matter field.  Defaults to `status`, but
                 is settable *independently* so a fixture can disagree with
                 its own ## Status section -- the DR-0017 shape behind issue
                 #484, which the checker must now catch.
    history   -- bold status words for a dated multi-entry ## Status section,
                 oldest first, so a fixture can open Proposed and close
                 Accepted.
    """
    words = list(history) if history else [status]
    body = "".join("- 2026-01-%02d: **%s.** x\n" % (i + 1, w)
                   for i, w in enumerate(words))
    fm = status if fm_status is None else fm_status
    return ("---\ndr: x\nstatus: %s\n---\n\n# T\n\n## Status\n\n%s\n"
            "## Context\n\nc\n" % (fm, body))


def entry(n, status="Proposed"):
    name = "DR-%04d-x.md" % n
    return ("- [`decision-records/%s`](decision-records/%s)\n  — **%s**. blurb\n\n"
            % (name, name, status))


def make(root, nums=(11, 12, 14), skip_index=(), extra_index="",
         rec_status=None, idx_status=None, fm_status=None, rec_history=None,
         raw_rec=None):
    d = root / "spec" / "decision-records"
    d.mkdir(parents=True)
    idx = "# spec\n\n## Decision records\n\n"
    for n in nums:
        if n in (raw_rec or {}):
            (d / ("DR-%04d-x.md" % n)).write_text((raw_rec or {})[n])
        else:
            (d / ("DR-%04d-x.md" % n)).write_text(
                rec((rec_status or {}).get(n, "Proposed"),
                    fm_status=(fm_status or {}).get(n),
                    history=(rec_history or {}).get(n)))
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

    def test_unknown_index_status_word_fails(self):
        # An index word outside STATUS_WORDS used to normalise to "Accepted" and
        # pass silently against an Accepted record (issue #471).
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             rec_status={3: "Accepted"},
                             idx_status={3: "Rejected"})
        self.assertTrue(any("unknown status" in e and "DR-0003" in e for e in errs), errs)

    def test_misspelled_index_status_word_fails(self):
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             rec_status={3: "Accepted"},
                             idx_status={3: "Propsed"})
        self.assertTrue(any("unknown status" in e and "DR-0003" in e for e in errs), errs)

    def test_ratified_index_word_is_accepted(self):
        # Ratified is in STATUS_WORDS and stays equivalent to Accepted.
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             rec_status={3: "Accepted"},
                             idx_status={3: "Ratified"})
        self.assertEqual(errs, [])

    def test_unlisted_gap_fails(self):
        errs = self.run_case(nums=tuple(range(1, 8)) + tuple(range(9, 13)) + (14,))
        self.assertTrue(any("gap: DR-0008" in e for e in errs), errs)

    def test_allowlisted_gap_does_not_fail(self):
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,))
        self.assertFalse(any("DR-0013" in e for e in errs), errs)

    # --- issue #484: the front matter is what the index is checked against ---

    def test_history_first_word_does_not_mask_accepted_front_matter(self):
        """The negative control for the DR-0017 bug (issue #484).

        A record whose ## Status history *opens* Proposed and *closes*
        Accepted, whose front matter says Accepted, indexed as Proposed, must
        FAIL.  Reading the first bold word of the history -- what
        record_status() used to do -- made this exact shape pass CI while
        spec/README.md was wrong about DR-0017.
        """
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             fm_status={3: "Accepted"},
                             rec_history={3: ["Proposed", "Accepted"]},
                             idx_status={3: "Proposed"})
        self.assertTrue(
            any("status mismatch" in e and "DR-0003" in e for e in errs), errs)

    def test_front_matter_disagreeing_with_latest_status_entry_fails(self):
        """AC4's second half: the record must not contradict itself.

        Front matter Accepted, latest ## Status entry Proposed -- the index
        agrees with the front matter, so the index/front-matter check passes
        and only the self-consistency check can catch it.
        """
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             fm_status={3: "Accepted"},
                             rec_history={3: ["Proposed"]},
                             idx_status={3: "Accepted"})
        self.assertTrue(
            any("front matter" in e and "DR-0003" in e for e in errs), errs)

    def test_multi_entry_history_agreeing_with_front_matter_passes(self):
        """DR-0017's real shape, correctly indexed, is clean.

        Guards against a fix that merely inverts the bug by failing any record
        whose history is not single-entry.
        """
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             fm_status={3: "Accepted"},
                             rec_history={3: ["Proposed", "Accepted"]},
                             idx_status={3: "Accepted"})
        self.assertEqual(errs, [])

    def test_amended_still_proposed_entry_is_not_a_status_word(self):
        """DR-0017's middle entry reads `**Amended, still Proposed**`.

        The bold run starts with "Amended", so it must not register as a
        status entry at all -- the latest *real* entry is the one that counts.
        """
        errs = self.run_case(
            nums=tuple(range(1, 13)) + (14,),
            fm_status={3: "Accepted"},
            rec_history={3: ["Proposed", "Amended, still Proposed",
                             "Accepted"]},
            idx_status={3: "Accepted"})
        self.assertEqual(errs, [])

    def test_record_without_front_matter_status_fails(self):
        """A missing `status:` field is an error, never a silent fallback.

        Falling back to the ## Status history is what let the DR-0017
        disagreement hide.
        """
        errs = self.run_case(
            nums=tuple(range(1, 13)) + (14,),
            raw_rec={3: "---\ndr: x\n---\n\n# T\n\n## Status\n\n"
                        "- 2026-01-01: **Proposed.** x\n\n## Context\n\nc\n"})
        self.assertTrue(
            any("front matter" in e and "DR-0003" in e for e in errs), errs)

    def test_unknown_front_matter_status_word_fails(self):
        """`status: Rejected` must not normalise to Accepted and pass."""
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             fm_status={3: "Rejected"},
                             idx_status={3: "Accepted"})
        self.assertTrue(
            any("unknown" in e and "DR-0003" in e for e in errs), errs)

    def test_ratified_front_matter_matches_accepted_index(self):
        """_norm keeps Ratified equivalent to Accepted in front matter."""
        errs = self.run_case(nums=tuple(range(1, 13)) + (14,),
                             fm_status={3: "Ratified"},
                             rec_history={3: ["Accepted"]},
                             idx_status={3: "Accepted"})
        self.assertEqual(errs, [])

    def test_real_tree_is_consistent(self):
        self.assertEqual(ci.check(REPO), [])


if __name__ == "__main__":
    unittest.main()
