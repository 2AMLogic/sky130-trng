#!/usr/bin/env python3
"""Negative controls for tools/check_reproduce.py (issue #292). Stdlib only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_reproduce as cr  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PIN = {"variant": "sky130A", "open_pdks_commit": "abc123",
       "install_command": "volare enable --pdk sky130 abc123"}
DOC = """# R
open_pdks abc123, klt 9.9.9
```
python3 sim/foo/run.py
```
| Directory | Entry |
|---|---|
| `sim/foo/` | `testbench/t.spice`, `run.py` |
"""


def make(root, doc=DOC, sim_pin=None):
    def w(rel, content=""):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    w("REPRODUCE.md", doc)
    w("design/pdk.json", json.dumps(PIN))
    w("sim/pdk.json", json.dumps(sim_pin or PIN))
    w("layout/pdk.json", json.dumps(dict(PIN, klt_version_pin="9.9.9")))
    w("sim/foo/run.py")
    w("sim/foo/testbench/t.spice")
    w("sim/foo/records/r.json", "{}")


class T(unittest.TestCase):
    def run_case(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            make(Path(d), **kw)
            return cr.check(d)

    def test_clean_fixture_passes(self):
        self.assertEqual(self.run_case(), [])

    def test_dangling_prose_path_fails(self):
        errs = self.run_case(doc=DOC + "\nsee `sim/foo/missing.py`\n")
        self.assertTrue(any("sim/foo/missing.py" in e for e in errs), errs)

    def test_dangling_table_file_fails(self):
        errs = self.run_case(doc=DOC.replace("`run.py`", "`gone.py`"))
        self.assertTrue(any("sim/foo/gone.py" in e for e in errs), errs)

    def test_uncovered_records_dir_fails(self):
        errs = self.run_case(doc=DOC.replace("sim/foo/", "sim/bar/")
                             .replace("python3 sim/bar/run.py", ""))
        self.assertTrue(any("sim/foo/ holds records" in e for e in errs), errs)

    def test_pdk_pin_mismatch_fails(self):
        errs = self.run_case(sim_pin=dict(PIN, open_pdks_commit="def456"))
        self.assertTrue(any("pin mismatch" in e for e in errs), errs)

    def test_variant_mismatch_fails(self):
        errs = self.run_case(sim_pin=dict(PIN, variant="sky130B"))
        self.assertTrue(any("'variant'" in e for e in errs), errs)

    def test_real_tree_is_consistent(self):
        self.assertEqual(cr.check(REPO), [])


if __name__ == "__main__":
    unittest.main()
