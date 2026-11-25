#!/usr/bin/env python3
"""Guard: every sim/tests/test_*.py must be run by a `run:` line in ci.yml (issue #717).

Stdlib only.  A suite named only in a YAML comment or a step `name:` does not
count -- only a `run:` line that executes it.  Fails printing the missing paths.
"""
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SUITE_DIR = "sim/tests"


def run_lines(workflow_text):
    """Return the text of every `run:` line (comments and `name:` excluded)."""
    out = []
    for line in workflow_text.splitlines():
        m = re.match(r"^\s*(?:-\s+)?run:\s*(.*)$", line)
        if m:
            out.append(m.group(1))
    return out


def uncovered(suites, workflow_text):
    """Suites (repo-relative paths) not named by any `run:` line."""
    runs = "\n".join(run_lines(workflow_text))
    return [s for s in suites if not re.search(re.escape(s) + r"(?![\w.])", runs)]


def repo_suites():
    return sorted(
        f"{SUITE_DIR}/{p.name}" for p in (REPO_ROOT / SUITE_DIR).glob("test_*.py")
    )


class CiSuiteCoverage(unittest.TestCase):
    def test_every_suite_is_run_by_ci(self):
        missing = uncovered(repo_suites(), CI_YML.read_text())
        self.assertEqual(
            missing, [], "sim/tests suites not run by any ci.yml run: line: %s" % missing
        )

    def test_negative_control_reports_uncovered_file(self):
        wf = (
            "steps:\n"
            "  # python3 sim/tests/test_b.py  (comment only)\n"
            "  - name: sim/tests/test_b.py in a name only\n"
            "    run: python3 sim/tests/test_a.py\n"
        )
        suites = ["sim/tests/test_a.py", "sim/tests/test_b.py"]
        self.assertEqual(uncovered(suites, wf), ["sim/tests/test_b.py"])

    def test_prefix_name_does_not_cover_longer_suite(self):
        wf = "    run: python3 sim/tests/test_ab.py\n"
        self.assertEqual(
            uncovered(["sim/tests/test_a.py"], wf), ["sim/tests/test_a.py"]
        )


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
