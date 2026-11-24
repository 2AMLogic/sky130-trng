#!/usr/bin/env python3
"""Unit test for the shared lock-proximity rule (issue #467).

    python3 sim/tests/test_lock_proximity.py

``sim/bin/lock_proximity.py`` is the one definition of "closest approach of a
ring pair to a mutual-injection-lock rational" -- DR-0003 section 8's rational
set and DR-0005 section 2's slower-over-faster convention.  Five reducers used
to implement it separately and two of them had drifted into an *order-dependent*
form that reported more margin from the lock rational than DR-0005's own
definition gives.  Nothing pinned any of the five.

This test pins:

* **symmetry** -- the property whose absence was the bug: a non-exact pair gives
  the same number in either argument order;
* **DR-0005's known answer** -- 1.2096 against 4/3 is 9.3 %, the figure
  ``spec/decision-records/DR-0005-post-layout-parasitics-and-wstv-decorrelation.md``
  reports, in both argument orders;
* **the exact hit** -- a true 4:3 pair is distance 0 and names ``(4, 3)``, not
  ``(3, 4)``;
* **the consolidation itself** -- every reducer uses the shared module, and none
  of them re-declares the rational set, so a future "quick local tweak" cannot
  silently re-fork the convention a sixth time.

Standard library only.  No simulator, no PDK, no file written anywhere.
"""
from __future__ import annotations

import sys
import tempfile
import tokenize
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "sim" / "tests"))
import lock_proximity as LP  # noqa: E402


class RationalSets(unittest.TestCase):
    """DR-0003 section 8 / DR-0005 section 2's set, and the same set including 1:1."""

    def test_dr5_set(self):
        self.assertEqual(tuple(LP.DR5_RATIOS), ((2, 1), (3, 2), (4, 3)))

    def test_any_set_is_dr5_plus_one_to_one(self):
        self.assertEqual(tuple(LP.ANY_RATIOS), ((1, 1),) + tuple(LP.DR5_RATIOS))

    def test_every_rational_is_written_slower_over_faster(self):
        for p, q in tuple(LP.ANY_RATIOS):
            self.assertGreaterEqual(p, q, f"({p}, {q}) is not written p >= q")


class Symmetry(unittest.TestCase):
    """The property the two drifted copies did not have."""

    PAIRS = [(1.0, 1.2096), (1.45, 1.0), (1.59524e-9, 1.26005e-9), (2.0, 1.0001), (1.0, 1.9)]

    def test_argument_order_does_not_change_the_result(self):
        for a, b in self.PAIRS:
            for ratios in (LP.DR5_RATIOS, LP.ANY_RATIOS):
                with self.subTest(pair=(a, b), ratios=tuple(ratios)):
                    self.assertEqual(LP.closeness(a, b, ratios), LP.closeness(b, a, ratios))

    def test_a_non_exact_pair_really_is_non_exact(self):
        # Otherwise the symmetry assertion above would be satisfied trivially by 0 == 0.
        for a, b in self.PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertGreater(LP.closeness(a, b)[0], 1e-6)

    def test_ratio_entry_point_is_order_free_too(self):
        # `1 / (1 / r)` is not bit-identical to `r`, so this is the one place
        # the symmetry is to float precision rather than exact; `closeness`
        # itself IS exact, because `max(a, b) / min(a, b)` is literally the
        # same division whichever order the pair arrives in (asserted above).
        for r in (1.2096, 1.45, 1.9, 2.0001):
            with self.subTest(r=r):
                a, b = LP.closeness_ratio(r), LP.closeness_ratio(1 / r)
                self.assertAlmostEqual(a[0], b[0], places=12)
                self.assertEqual(a[1:], b[1:])

    def test_scale_invariant(self):
        # Periods in seconds or in nanoseconds are the same question.
        self.assertEqual(LP.closeness(1.0, 1.2096), LP.closeness(1e-9, 1.2096e-9))


class DR0005KnownAnswer(unittest.TestCase):
    """DR-0005 section 2: span 1.2096 against 4/3 is 9.3 %."""

    def test_both_argument_orders_give_the_dr5_figure(self):
        for a, b in ((1.0, 1.2096), (1.2096, 1.0)):
            with self.subTest(order=(a, b)):
                d, p, q = LP.closeness(a, b, LP.DR5_RATIOS)
                self.assertAlmostEqual(d * 100, 9.28, places=1)
                self.assertEqual((p, q), (4, 3))

    def test_the_old_order_dependent_form_gave_a_different_number(self):
        """Pin the defect this consolidation corrected, so it cannot come back.

        The removed form took ``r = Tj / Ti`` in the order the caller passed the
        rings and searched both ``p/q`` and ``q/p``.  With the slower ring first
        -- which is how both callers enumerated their pairs -- it reported
        10.23 %, i.e. MORE margin than DR-0005's definition gives.
        """
        def old_order_dependent(Ti, Tj, ratios):
            r, best = Tj / Ti, None
            for p, q in ratios:
                for x in (p / q, q / p):
                    d = abs(r / x - 1)
                    if best is None or d < best[0]:
                        best = (d, p, q)
            return best

        self.assertAlmostEqual(old_order_dependent(1.2096, 1.0, LP.DR5_RATIOS)[0] * 100, 10.23, places=2)
        self.assertAlmostEqual(LP.closeness(1.2096, 1.0, LP.DR5_RATIOS)[0] * 100, 9.28, places=2)
        # ... and the shared rule is never the larger of the two.
        for a, b in Symmetry.PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertLessEqual(LP.closeness(a, b, LP.DR5_RATIOS)[0],
                                     old_order_dependent(a, b, LP.DR5_RATIOS)[0] + 1e-15)


class ExactHits(unittest.TestCase):

    def test_exact_four_to_three_is_zero_and_names_four_over_three(self):
        d, p, q = LP.closeness(3.0, 4.0, LP.DR5_RATIOS)
        self.assertEqual(d, 0.0)
        self.assertEqual((p, q), (4, 3))
        self.assertEqual(LP.ratio_label(p, q), "4/3")
        self.assertEqual(LP.closeness(4.0, 3.0, LP.DR5_RATIOS), (0.0, 4, 3))

    def test_exact_two_to_one_and_three_to_two(self):
        self.assertEqual(LP.closeness(1.0, 2.0, LP.DR5_RATIOS), (0.0, 2, 1))
        self.assertEqual(LP.closeness(2.0, 3.0, LP.DR5_RATIOS), (0.0, 3, 2))

    def test_equal_periods_hit_one_to_one_only_in_the_with_1_1_set(self):
        self.assertEqual(LP.closeness(1.0, 1.0, LP.ANY_RATIOS), (0.0, 1, 1))
        self.assertGreater(LP.closeness(1.0, 1.0, LP.DR5_RATIOS)[0], 0.2)


class PairHelper(unittest.TestCase):

    def test_pair_closeness_reports_the_closest_pair_with_1_based_indices(self):
        T = [1.0, 1.02, 1.41, 1.93]                    # rings 1-2 are 2 % from 1:1, no exact hit anywhere
        d, pair, rational = LP.pair_closeness(T, LP.ANY_RATIOS)
        self.assertAlmostEqual(d, 0.02, places=6)
        self.assertEqual(pair, "1-2")
        self.assertEqual(rational, "1/1")

    def test_pair_closeness_is_invariant_to_the_enumeration_order(self):
        T = [1.59524, 1.26005, 1.41, 1.02]
        self.assertAlmostEqual(LP.pair_closeness(T)[0], LP.pair_closeness(list(reversed(T)))[0])


class Rejects(unittest.TestCase):

    def test_non_positive_periods_are_refused(self):
        for a, b in ((0.0, 1.0), (1.0, -1.0)):
            with self.subTest(pair=(a, b)), self.assertRaises(ValueError):
                LP.closeness(a, b)

    def test_non_positive_ratio_is_refused(self):
        with self.assertRaises(ValueError):
            LP.closeness_ratio(0.0)


class Consolidation(unittest.TestCase):
    """Every reducer uses the shared rule; none of them re-declares the set."""

    #: slug -> the analysis script that reports a lock-proximity figure.
    REDUCERS = {
        "local-mismatch-monte-carlo": REPO / "sim" / "local-mismatch-monte-carlo" / "reduce.py",
        "post-layout-parasitic-impact":
            REPO / "sim" / "post-layout-parasitic-impact" / "analysis" / "parasitic-impact.py",
        "post-layout-sampler-core":
            REPO / "sim" / "post-layout-sampler-core" / "analysis" / "substrate-bracket.py",
        "ro-array-supply-perturbation": REPO / "sim" / "ro-array-supply-perturbation" / "ripple.py",
        "ro-vth-drift-sensitivity":
            REPO / "sim" / "ro-vth-drift-sensitivity" / "analysis" / "sensitivity.py",
    }

    def test_each_reducer_imports_the_shared_module(self):
        for slug, path in self.REDUCERS.items():
            with self.subTest(reducer=slug):
                self.assertRegex(path.read_text(), r"(?m)^from lock_proximity import ",
                                 f"{path.name} does not import the shared rule")

    #: Token runs that spell the DR-0005 rational 4:3 as a literal.
    DECLARATIONS = (("(", "4", ",", "3", ")"), ("4", "/", "3"))

    @staticmethod
    def _code_tokens(path):
        """The file's executable tokens: strings, docstrings and comments dropped.

        Prose is allowed to name the set -- a *declaration* is code.
        """
        skip = {tokenize.STRING, tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
        skip |= {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                 if hasattr(tokenize, n)}                    # 3.12+ splits f-strings into tokens
        with open(path, "rb") as fh:
            return [t for t in tokenize.tokenize(fh.readline) if t.type not in skip]

    def _assert_no_declaration(self, path):
        """Fail if `path` spells the DR-0005 rational 4:3 as a literal in code."""
        toks = self._code_tokens(path)
        words = [t.string for t in toks]
        for run in self.DECLARATIONS:
            for i in range(len(words) - len(run) + 1):
                self.assertNotEqual(
                    tuple(words[i:i + len(run)]), run,
                    f"{path.name}:{toks[i].start[0]} re-declares the rational set "
                    f"({' '.join(run)}); import it from sim/bin/lock_proximity.py instead")

    def test_no_reducer_declares_the_rational_set_itself(self):
        """The one acceptance criterion of #467: one declaration, in this module.

        A *declaration* is the literal ``(4, 3)`` or ``4 / 3`` appearing in
        code -- docstrings and comments may still name the set in prose.
        ``ripple.py``'s generated coprime grid (``RATIOS``, used by
        ``tone_lock``) is not the DR-0005 set and is built from ``range``, so
        it does not match.
        """
        for slug, path in self.REDUCERS.items():
            with self.subTest(reducer=slug):
                self._assert_no_declaration(path)

    def test_the_detector_would_catch_a_re_fork(self):
        """Negative control: the scan above must actually fire on a declaration."""
        for src in ("DR5 = [(2, 1), (3, 2), (4, 3)]\n",
                    "LOCK = {'four_thirds': 4 / 3}\n",
                    "x = 4/3\n"):
            with self.subTest(source=src.strip()):
                with tempfile.TemporaryDirectory() as td:
                    planted = Path(td) / "planted.py"
                    planted.write_text(src)
                    with self.assertRaises(AssertionError):
                        self._assert_no_declaration(planted)

    def test_prose_naming_the_set_is_not_a_declaration(self):
        """A docstring or comment may still say "2/1, 3/2, 4/3" -- and they do."""
        with tempfile.TemporaryDirectory() as td:
            prose = Path(td) / "prose.py"
            prose.write_text('"""The DR-0005 set {2/1, 3/2, 4/3}, (4, 3) included."""\n'
                             "# also 4 / 3 and (4, 3) in a comment\n"
                             "from lock_proximity import DR5_RATIOS\n")
            self._assert_no_declaration(prose)       # must not raise

    def test_the_shared_module_is_where_the_set_is_declared(self):
        src = (REPO / "sim" / "bin" / "lock_proximity.py").read_text()
        self.assertIn("((2, 1), (3, 2), (4, 3))", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
