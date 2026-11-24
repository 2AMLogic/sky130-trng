#!/usr/bin/env python3
"""Unit test for the shared measurement-name uniqueness guard (issue #670).

    python3 sim/tests/test_measurement_names.py

A `klt sim` response carries each corner's `.meas` results as a LIST of
{name, value} entries.  Reducers deduplicate that list into a name-keyed
dict, and a repeated name silently displaces the entry it duplicates: the
displaced measurement's check is never made while the entry-count
bookkeeping stays honest (#548 documented the failure mode for the
whole-block reducer; #670 extends the guard to the campaigns whose
generator lifts measurement names verbatim out of a committed template
deck -- a pass-through with no uniqueness property of its own).

This test pins:

* unique names pass through to {name: value};
* a repeated name raises, naming the corner and the repeated names,
  instead of silently keeping the last entry;
* the guard counts names over the FULL list, BEFORE any
  `value is not None` filtering -- a repeated name is a defect whether or
  not the displaced entry happened to carry a value;
* empty and absent measurement lists behave like the plain dict
  comprehension they replace;
* the consolidation itself -- every can-collide site uses the shared
  module, and none of them re-forks an unguarded name-keyed dedupe.

Standard library only.  No simulator, no PDK, no file written anywhere.
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "sim" / "tests"))
from loadmod import load_module  # noqa: E402
import measurement_names as MN  # noqa: E402


def corner(measurements, **ident):
    c = {"measurements": measurements}
    c.update(ident)
    return c


class UniquePasses(unittest.TestCase):

    def test_unique_names_dedupe_to_a_name_keyed_dict(self):
        c = corner([{"name": "t1a", "value": 1.0}, {"name": "t1b", "value": 2.0},
                    {"name": "vxo_avg", "value": 0.9}], process="tt", corner_id="u7")
        self.assertEqual(MN.measurements_by_name(c), {"t1a": 1.0, "t1b": 2.0, "vxo_avg": 0.9})

    def test_none_valued_entries_are_dropped_by_default(self):
        c = corner([{"name": "t1a", "value": None}, {"name": "t1b", "value": 2.0}], process="tt")
        self.assertEqual(MN.measurements_by_name(c), {"t1b": 2.0})

    def test_keep_none_preserves_them(self):
        c = corner([{"name": "t1a", "value": None}, {"name": "t1b", "value": 2.0}], process="tt")
        self.assertEqual(MN.measurements_by_name(c, keep_none=True),
                         {"t1a": None, "t1b": 2.0})

    def test_empty_measurements_give_an_empty_dict(self):
        self.assertEqual(MN.measurements_by_name(corner([])), {})
        self.assertEqual(MN.measurements_by_name(corner([], process="ss")), {})

    def test_absent_measurements_key_gives_an_empty_dict(self):
        self.assertEqual(MN.measurements_by_name({}), {})


class RepeatedRaises(unittest.TestCase):

    REPEAT = corner([{"name": "t1a", "value": 1.0}, {"name": "t2a", "value": 2.0},
                     {"name": "t1a", "value": 3.0}], process="ss", corner_id="u9")

    def test_raise_names_the_repeated_name(self):
        with self.assertRaises(MN.DuplicateMeasurementName) as cm:
            MN.measurements_by_name(self.REPEAT)
        self.assertIn("'t1a'", str(cm.exception))
        self.assertIn("t1a", cm.exception.duplicates)

    def test_raise_names_the_corner(self):
        with self.assertRaises(MN.DuplicateMeasurementName) as cm:
            MN.measurements_by_name(self.REPEAT)
        self.assertIn("ss", str(cm.exception))
        self.assertIn("u9", str(cm.exception))

    def test_explicit_label_overrides_the_derived_one(self):
        c = corner([{"name": "t1a", "value": 1.0}, {"name": "t1a", "value": 3.0}])
        with self.assertRaises(MN.DuplicateMeasurementName) as cm:
            MN.measurements_by_name(c, label="array|ss|-40C|1.62V|60|60")
        self.assertIn("array|ss|-40C|1.62V|60|60", str(cm.exception))

    def test_unlabelled_corner_without_identity_fields_is_still_named(self):
        c = corner([{"name": "t1a", "value": 1.0}, {"name": "t1a", "value": 3.0}])
        with self.assertRaises(MN.DuplicateMeasurementName) as cm:
            MN.measurements_by_name(c)
        self.assertIn("corner", str(cm.exception))

    def test_the_last_entry_is_not_silently_kept(self):
        """The #548/#670 failure mode: deduplication must not succeed at all."""
        with self.assertRaises(MN.DuplicateMeasurementName):
            MN.measurements_by_name(self.REPEAT)


class GuardCountsBeforeTheNullFilter(unittest.TestCase):
    """Uniqueness is a property of the name list, independent of the values.

    A repeated name with one `value: null` entry still displaces: which of
    the two survives a `value is not None` filter depends on list order, and
    the count bookkeeping stays honest either way, so the guard refuses it.
    """

    def test_repeated_name_with_a_null_value_still_raises(self):
        c = corner([{"name": "t1a", "value": 1.0}, {"name": "t1a", "value": None}], process="ff")
        with self.assertRaises(MN.DuplicateMeasurementName):
            MN.measurements_by_name(c)

    def test_duplicate_measurement_names_sees_the_full_list(self):
        ms = [{"name": "t1a", "value": 1.0}, {"name": "t1a", "value": None}]
        self.assertEqual(MN.duplicate_measurement_names(ms), ["t1a"])


class DuplicateHelper(unittest.TestCase):

    def test_sorted_and_counts_each_repeated_name_once(self):
        ms = [{"name": "b", "value": 1}, {"name": "b", "value": 2}, {"name": "b", "value": 3},
              {"name": "a", "value": 1}, {"name": "a", "value": 2}, {"name": "c", "value": 9}]
        self.assertEqual(MN.duplicate_measurement_names(ms), ["a", "b"])

    def test_unique_and_empty_give_no_duplicates(self):
        self.assertEqual(MN.duplicate_measurement_names([{"name": "a", "value": 1}]), [])
        self.assertEqual(MN.duplicate_measurement_names([]), [])
        self.assertEqual(MN.duplicate_measurement_names(None), [])

    def test_whole_block_caller_gets_returned_list_not_a_raise(self):
        wb = REPO / "sim" / "post-layout-whole-block"
        cgm = load_module("wb_cgm_probe", wb / "analysis" / "compare-gate-model.py")
        rwb = load_module("wb_reduce_probe", wb / "analysis" / "reduce-whole-block.py")
        self.assertIs(cgm.duplicate_measurement_names, MN.duplicate_measurement_names)
        self.assertEqual(cgm.duplicate_measurement_names([]), [])
        quad = [{"name": "i_vdd_w2", "value": -3e-6}] * 4 + [{"name": "clk_at_stop", "value": 0.0}]
        self.assertEqual(cgm.duplicate_measurement_names(quad), ["i_vdd_w2"])
        res = rwb.analyse_corner({"status": "pass", "measurements": quad}, 1.8)
        self.assertTrue(any("duplicate measurement name" in p for p in res["problems"]))


class Consolidation(unittest.TestCase):
    """Every can-collide site uses the shared guard; none re-forks a bare dedupe.

    The four guarded sites are the reducers whose campaign generator lifts
    measurement names verbatim out of a committed template deck (issue #670's
    measured split: the other six sites' generators build names structurally,
    from f-strings over ``range()`` indices and disjoint literal names, and
    are documented in the PR instead).  The two whole-block analysis scripts
    (#642, consolidated in #690) share ``duplicate_measurement_names`` rather
    than ``measurements_by_name`` because they act on the returned list
    (raising ``SystemExit`` with plan context or marking the corner ``UNMET``).
    """

    GUARDED = {
        "raw-bit-volume combining deck": REPO / "sim" / "raw-bit-volume-campaign" / "derive-combining.py",
        "vth-drift grid/pilot rows": REPO / "sim" / "ro-vth-drift-sensitivity" / "analysis" / "sensitivity.py",
        "post-layout-ro-ring5-assembled-181": REPO / "sim" / "post-layout-ro-ring5-assembled-181" / "derive.py",
    }

    WHOLE_BLOCK = {
        "whole-block gate-model comparator": (
            REPO / "sim" / "post-layout-whole-block" / "analysis" / "compare-gate-model.py"
        ),
        "whole-block 12-point reducer": (
            REPO / "sim" / "post-layout-whole-block" / "analysis" / "reduce-whole-block.py"
        ),
    }

    #: the dedupe the guarded files must no longer spell out unguarded.
    BARE_DEDUPE = re.compile(r'[emx]\["name"\]\s*:\s*[emx]\["value"\]')
    #: a local duplicate-name helper or Counter fork that whole-block scripts must not carry.
    DUPLICATE_FORK = re.compile(r"(?m)^\s*def\s+duplicate_measurement_names\b|\bCounter\s*\(")
    DEF_DUPLICATE_HELPER = re.compile(r"(?m)^\s*def\s+duplicate_measurement_names\b")

    def test_each_guarded_file_imports_the_shared_module(self):
        for slug, path in self.GUARDED.items():
            with self.subTest(site=slug):
                self.assertRegex(path.read_text(), r"(?m)^from measurement_names import ",
                                 f"{path.name} does not import the shared guard")

    def test_no_guarded_file_keeps_a_bare_name_keyed_dedupe(self):
        for slug, path in self.GUARDED.items():
            with self.subTest(site=slug):
                text = path.read_text()
                m = self.BARE_DEDUPE.search(text)
                self.assertIsNone(
                    m, f"{path.name} still dedupes measurements into a name-keyed dict "
                    f"without the guard (offset {m and m.start()}); "
                    f"use sim/bin/measurement_names.measurements_by_name")

    def test_the_detector_would_catch_a_re_fork(self):
        with tempfile.TemporaryDirectory() as td:
            probe = Path(td) / "probe.py"
            probe.write_text('m = {x["name"]: x["value"] for x in c["measurements"]}\n')
            self.assertIsNotNone(self.BARE_DEDUPE.search(probe.read_text()))

    def test_whole_block_sites_delegate_to_the_shared_helper(self):
        cgm_text = self.WHOLE_BLOCK["whole-block gate-model comparator"].read_text()
        rwb_text = self.WHOLE_BLOCK["whole-block 12-point reducer"].read_text()
        self.assertRegex(
            cgm_text,
            r"(?m)^from measurement_names import .*\bduplicate_measurement_names\b",
            "compare-gate-model.py does not import duplicate_measurement_names from measurement_names",
        )
        self.assertRegex(
            rwb_text,
            r"(?m)(?:\bCGM\.duplicate_measurement_names\s*\(|^from measurement_names import .*\bduplicate_measurement_names\b)",
            "reduce-whole-block.py does not reach the shared duplicate_measurement_names helper",
        )

    def test_no_whole_block_file_forks_duplicate_measurement_names(self):
        for slug, path in self.WHOLE_BLOCK.items():
            with self.subTest(site=slug):
                text = path.read_text()
                m = self.DUPLICATE_FORK.search(text)
                self.assertIsNone(
                    m, f"{path.name} carries its own duplicate-name fork ({m and m.group(0)!r} "
                    f"at offset {m and m.start()}); delegate to sim/bin/measurement_names")

    def test_shared_module_is_the_sole_duplicate_measurement_names_definition(self):
        defs = [
            p.relative_to(REPO).as_posix()
            for p in sorted((REPO / "sim").rglob("*.py"))
            if self.DEF_DUPLICATE_HELPER.search(p.read_text())
        ]
        self.assertEqual(defs, ["sim/bin/measurement_names.py"])

    def test_the_whole_block_detector_would_catch_a_third_fork(self):
        fork_def = "def " + "duplicate_measurement_names(ms):\n    return []\n"
        self.assertIsNotNone(self.DUPLICATE_FORK.search(fork_def))
        self.assertIsNotNone(self.DUPLICATE_FORK.search('Counter(m["name"] for m in ms)\n'))


if __name__ == "__main__":
    unittest.main()
