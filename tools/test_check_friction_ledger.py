#!/usr/bin/env python3
"""Negative controls for tools/check_friction_ledger.py (issue #295). Stdlib only."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_friction_ledger as cf  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
def ref(n, url=False):
    # built at runtime so this file carries no literal reference itself
    return "klayout-tools" + ("/issues/%d" if url else "#%d") % n


LEDGER = "| Issue | Gap |\n|---|---|\n| [#10](https://x/issues/10) | a |\n"


def make(root, ledger=LEDGER, files=None):
    def w(rel, content):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    if ledger is not None:
        w(cf.LEDGER, ledger)
    for rel, content in (files or {"a/README.md": "see " + ref(10) + "\n"}).items():
        w(rel, content)


class T(unittest.TestCase):
    def run_case(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            make(Path(d), **kw)
            return cf.check(d)

    def test_listed_reference_passes(self):
        self.assertEqual(self.run_case(), [])

    def test_unlisted_reference_fails(self):
        errs = self.run_case(files={"a/R.md": ref(11) + " and " + ref(10)})
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("#11", errs[0])

    def test_issue_url_form_is_checked(self):
        errs = self.run_case(files={
            "a/R.md": "github.com/2AMLogic/" + ref(12, True)})
        self.assertTrue(any("#12" in e for e in errs), errs)

    def test_ledger_itself_and_loom_dir_ignored(self):
        self.assertEqual(self.run_case(
            ledger=LEDGER + "mentions " + ref(99) + "\n",
            files={".loom/docs/x.md": ref(98)}), [])

    def test_missing_ledger_fails(self):
        self.assertTrue(self.run_case(ledger=None))

    def test_real_tree_is_covered(self):
        self.assertEqual(cf.check(REPO), [])


if __name__ == "__main__":
    unittest.main()
