#!/usr/bin/env python3
"""Unit tests for sim/bin/request_dir.py and the five reducers' completeness
policies (issue #469).

The shared rule under test: a `klt sim` request with no usable response is
**returned to the caller**, never dropped on the floor. Each campaign reducer
then states its own policy on top of it -- and this file pins both halves, so
a "small tweak" to one reducer cannot silently re-fork the directory walk or
go back to dropping requests.

The headline regression it guards is the local-mismatch reducer's: a refused
Monte Carlo chunk used to vanish from the loader AND take its draws out of
`n_*_requested`, so a record could read "20/20 array" over 20 of the 30
requested draws, with no error and no trace but a short seed list.

Inputs are the repository's own committed corner bundle replayed back into a
request directory -- real `klt` responses, not synthesized ones -- plus
synthetic directories for the failure shapes no committed bundle contains (a
bundle only ever holds responses that arrived). No simulator, no PDK, no fleet.

    python3 sim/tests/test_request_dir.py
"""
import glob
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from loadmod import load_module  # noqa: E402
import request_dir as rd  # noqa: E402

MM = load_module("mm_reduce", os.path.join(REPO, "sim", "local-mismatch-monte-carlo", "reduce.py"))

#: A committed tt bundle of this campaign: 3 array requests x 10 draws = 30,
#: 2 sampler requests x 30 draws = 60, plus the two mismatch-free references.
BUNDLE = os.path.join(REPO, "sim", "local-mismatch-monte-carlo", "corners", "20261009-111127-e57ad27")


def write_request(root, name, plan, resp="omit", klt_log=None):
    """Create root/name/ as a request directory.

    ``resp``: ``"omit"`` writes no resp.json at all; ``None`` writes an empty
    one (what a refused or unfinished submit leaves behind); a string is
    written verbatim (malformed JSON); anything else is JSON-encoded.
    """
    d = os.path.join(root, name)
    os.makedirs(d)
    if plan is not None:
        json.dump(plan, open(os.path.join(d, "plan.json"), "w"))
    if resp is None:
        open(os.path.join(d, "resp.json"), "w").close()
    elif isinstance(resp, str) and resp != "omit":
        open(os.path.join(d, "resp.json"), "w").write(resp)
    elif resp != "omit":
        json.dump(resp, open(os.path.join(d, "resp.json"), "w"))
    if klt_log is not None:
        open(os.path.join(d, "klt.log"), "w").write(klt_log)
    return d


def rebuild_reqdir(bundle, out, emptied=()):
    """Replay a committed corner bundle back into a request directory.

    ``emptied`` names the requests whose ``resp.json`` is blanked instead --
    exactly what a `batch_no_capacity` refusal leaves on disk.
    """
    for p in sorted(glob.glob(os.path.join(bundle, "*.plan.json"))):
        nm = os.path.basename(p)[: -len(".plan.json")]
        d = os.path.join(out, nm)
        os.makedirs(d)
        for suffix, fn in ((".plan.json", "plan.json"),
                           (".request.json", "request.json"),
                           (".netlist.cir", "netlist.cir")):
            src = os.path.join(bundle, nm + suffix)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(d, fn))
        if nm in emptied:
            open(os.path.join(d, "resp.json"), "w").close()
            continue
        with gzip.open(os.path.join(bundle, nm + ".klt-sim.json.gz"), "rt") as fh:
            json.dump(json.load(fh), open(os.path.join(d, "resp.json"), "w"))
    return out


class TempReqdir(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="test-request-dir-")
        self.addCleanup(shutil.rmtree, self.root, True)


# ---------------------------------------------------------------- the shared walk
class LoadRequestDir(TempReqdir):
    GOOD = {"corners": [{"status": "pass", "measurements": []}]}

    def test_usable_response_is_a_chunk(self):
        write_request(self.root, "tt-arr-1", {"kind": "arr"}, self.GOOD)
        chunks, missing = rd.load_request_dir(self.root)
        self.assertEqual(missing, [])
        self.assertEqual([c[0] for c in chunks], ["tt-arr-1"])
        self.assertEqual(chunks[0][1], {"kind": "arr"})
        self.assertEqual(chunks[0][2], self.GOOD)

    def test_absent_empty_malformed_and_cornerless_are_all_missing(self):
        cases = {
            "a-absent-1": "omit",                       # never submitted
            "a-empty-1": None,                          # refused / unfinished
            "a-truncated-1": '{"corners": [{"stat',     # killed mid-write
            "a-cornerless-1": {"status": "error"},      # klt reported an error
        }
        for nm, resp in cases.items():
            write_request(self.root, nm, {"kind": "arr"}, resp)
        chunks, missing = rd.load_request_dir(self.root)
        self.assertEqual(chunks, [], "no usable response should have become a chunk")
        self.assertEqual(sorted(m[0] for m in missing), sorted(cases))
        for nm, plan, why in missing:
            self.assertEqual(plan, {"kind": "arr"}, nm)
            self.assertTrue(why, f"{nm} must carry a reason")

    def test_directory_without_a_plan_is_not_a_request_at_all(self):
        write_request(self.root, "notes", None, self.GOOD)
        write_request(self.root, "tt-arr-1", {"kind": "arr"}, self.GOOD)
        chunks, missing = rd.load_request_dir(self.root)
        self.assertEqual([c[0] for c in chunks], ["tt-arr-1"])
        self.assertEqual(missing, [], "a non-request directory must not be reported as a missing request")

    def test_an_unreadable_plan_raises_instead_of_vanishing(self):
        # An absent plan.json means "not a request directory" (above); a
        # plan.json that IS there and cannot be read is a corrupt request, and
        # skipping it would drop the request from BOTH lists -- no caller could
        # then state a policy about it (PR #473 review). The five walks this
        # loader replaced all raised here.
        for label, payload in (("zero-byte", ""),
                               ("whitespace", "  \n"),
                               ("truncated", '{"kind": "arr", "monte_car'),
                               ("json null", "null"),
                               ("non-object", "[1, 2]")):
            with self.subTest(payload=label):
                root = os.path.join(self.root, label.replace(" ", "-"))
                d = write_request(root, "tt-arr-1", {"kind": "arr"}, self.GOOD)
                open(os.path.join(d, "plan.json"), "w").write(payload)
                with self.assertRaises(ValueError) as cm:
                    rd.load_request_dir(root)
                self.assertIn(os.path.join(d, "plan.json"), str(cm.exception),
                              "the error must name the file it could not read")

    def test_an_unreadable_plan_raises_even_with_a_good_response(self):
        # The regression shape: the response arrived, so nothing downstream
        # would ever have noticed the request going missing.
        d = write_request(self.root, "tt-arr-1", {"kind": "arr"}, self.GOOD)
        write_request(self.root, "tt-arr-2", {"kind": "arr"}, self.GOOD)
        open(os.path.join(d, "plan.json"), "w").close()
        with self.assertRaises(ValueError):
            rd.load_request_dir(self.root)

    def test_stray_file_beside_the_requests_is_ignored(self):
        open(os.path.join(self.root, "README"), "w").write("x")
        write_request(self.root, "tt-arr-1", {"kind": "arr"}, self.GOOD)
        self.assertEqual(rd.load_request_dir(self.root), ([("tt-arr-1", {"kind": "arr"}, self.GOOD)], []))

    def test_pattern_selects_the_leg(self):
        write_request(self.root, "det-1", {"leg": "det"}, self.GOOD)
        write_request(self.root, "noisy-1", {"leg": "noisy"}, self.GOOD)
        self.assertEqual([c[0] for c in rd.load_request_dir(self.root, "det-*")[0]], ["det-1"])
        self.assertEqual([c[0] for c in rd.load_request_dir(self.root, "noisy-*")[0]], ["noisy-1"])

    def test_name_from_plan(self):
        write_request(self.root, "0-dirname", {"name": "plan-name"}, self.GOOD)
        write_request(self.root, "1-also", {"name": "other"}, None)
        chunks, missing = rd.load_request_dir(self.root, name_from="plan")
        self.assertEqual([c[0] for c in chunks], ["plan-name"])
        self.assertEqual([m[0] for m in missing], ["other"])

    def test_name_from_is_validated(self):
        with self.assertRaises(ValueError):
            rd.load_request_dir(self.root, name_from="basename")

    def test_require_corners_off_keeps_the_raw_response(self):
        write_request(self.root, "a-1", {"kind": "arr"}, {"status": "error"})
        chunks, missing = rd.load_request_dir(self.root, require_corners=False)
        self.assertEqual([c[0] for c in chunks], ["a-1"])
        self.assertEqual(missing, [])
        write_request(self.root, "a-2", {"kind": "arr"}, None)
        self.assertEqual([m[0] for m in rd.load_request_dir(self.root, require_corners=False)[1]], ["a-2"],
                         "an empty resp.json is unusable whatever require_corners says")

    def test_both_lists_are_sorted_by_directory(self):
        for nm in ("c-3", "a-1", "b-2"):
            write_request(self.root, nm, {"kind": "arr"}, self.GOOD)
        for nm in ("z-9", "m-5"):
            write_request(self.root, nm, {"kind": "arr"}, None)
        chunks, missing = rd.load_request_dir(self.root)
        self.assertEqual([c[0] for c in chunks], ["a-1", "b-2", "c-3"])
        self.assertEqual([m[0] for m in missing], ["m-5", "z-9"])

    def test_empty_directory(self):
        self.assertEqual(rd.load_request_dir(self.root), ([], []))


class SubmitError(TempReqdir):
    def test_klt_error_message_is_preferred(self):
        d = write_request(self.root, "a-1", {}, {"error": {"message": "batch_no_capacity"}})
        self.assertEqual(rd.submit_error(d), "batch_no_capacity")

    def test_falls_back_to_the_klt_log_tail(self):
        d = write_request(self.root, "a-1", {}, None, klt_log="line one\nfleet refused the submit\n")
        self.assertEqual(rd.submit_error(d), "line one\nfleet refused the submit")

    def test_log_tail_is_bounded(self):
        d = write_request(self.root, "a-1", {}, None, klt_log="x" * 5000)
        self.assertEqual(len(rd.submit_error(d)), 600)

    def test_nothing_written_at_all(self):
        d = write_request(self.root, "a-1", {})
        self.assertEqual(rd.submit_error(d), rd.NO_RESPONSE)

    def test_never_raises_on_a_missing_directory(self):
        self.assertEqual(rd.submit_error(os.path.join(self.root, "nope")), rd.NO_RESPONSE)

    def test_a_refused_request_reports_the_refusal_through_the_loader(self):
        write_request(self.root, "a-1", {"kind": "arr"},
                      {"error": {"message": "batch_no_capacity: fleet vCPU budget exhausted"}})
        (_nm, _plan, why), = rd.load_request_dir(self.root)[1]
        self.assertIn("batch_no_capacity", why)


# ------------------------------------------- the regression this issue is about
class MismatchSampleCount(TempReqdir):
    """`n_*_requested` must mean *requested*, whatever came back (issue #469)."""

    def reqdir(self, emptied=()):
        return rebuild_reqdir(BUNDLE, os.path.join(self.root, "req"), emptied)

    def test_the_committed_bundle_replays_as_a_complete_set(self):
        chunks, missing = MM.load_reqdir(self.reqdir())
        self.assertEqual(missing, [])
        self.assertEqual(len(chunks), 7)
        _rows, S = MM.build(chunks)["tt"]
        self.assertEqual((S["n_array_ok"], S["n_array_requested"]), (30, 30))
        self.assertEqual((S["n_sampler_ok"], S["n_sampler_requested"]), (60, 60))

    def test_a_refused_chunk_no_longer_reports_a_full_sample_count(self):
        # One array request (10 of 30 draws) and one sampler request (30 of 60)
        # refused, as `batch_no_capacity` leaves them on disk.
        chunks, missing = MM.load_reqdir(self.reqdir(("tt-arr-1", "tt-smp-1")))
        self.assertEqual(sorted(m[0] for m in missing), ["tt-arr-1", "tt-smp-1"],
                         "a refused request must be returned, not dropped")
        self.assertEqual(len(chunks), 5)
        _rows, S = MM.build(chunks, missing)["tt"]
        self.assertEqual(S["n_array_requested"], 30, "the denominator is what the plans asked for")
        self.assertEqual(S["n_sampler_requested"], 60)
        self.assertEqual(S["n_array_ok"], 20)
        self.assertEqual(S["n_sampler_ok"], 30)
        # the defect: the headline line used to read "20/20" and "30/30"
        self.assertLess(S["n_array_ok"], S["n_array_requested"])
        self.assertLess(S["n_sampler_ok"], S["n_sampler_requested"])

    def test_an_unreadable_plan_cannot_shrink_the_denominator_silently(self):
        # The plan carries the requested draws, so a dropped plan takes 10 of
        # the 30 array draws out of `n_array_requested` with it and the record
        # reads a complete "20/20 array" with no error -- the issue's own
        # symptom, reached by a different route (PR #473 review). Measured at
        # 6055833 as `chunks 6 missing 0  array 20/20`.
        for payload in ("", '{"kind": "arr", "monte_car'):
            with self.subTest(payload=payload[:12] or "zero-byte"):
                req = rebuild_reqdir(BUNDLE, os.path.join(self.root, f"req-{len(payload)}"))
                open(os.path.join(req, "tt-arr-1", "plan.json"), "w").write(payload)
                with self.assertRaises(ValueError):
                    MM.load_reqdir(req)

    def test_the_shortfall_is_visible_in_the_rendered_headline(self):
        chunks, missing = MM.load_reqdir(self.reqdir(("tt-arr-1",)))
        _rows, S = MM.build(chunks, missing)["tt"]
        md = MM.render_md("rid", "tt", S, ["job"], "sha", __import__("datetime").datetime.now())
        self.assertIn("**Samples**: 20/30 array, 60/60 sampler.", md)

    SLUGDIR = ("sim", "local-mismatch-monte-carlo")

    def sandboxed_repo(self):
        """Redirect the reducer's record output into a temp tree -> records dir.

        `emit_record` writes into REPO/sim/<slug>/{records,corners}, which is
        append-only committed evidence: if a future change ever stopped the
        refusal from firing, an unsandboxed test would mint a record straight
        into it. The sandbox is a symlink farm rather than an empty directory
        because REPO also locates the reducer's inputs (the raw-bit entropy
        estimator it imports, the testbenches it cites) -- only `records/` and
        `corners/` are real temp directories.
        """
        fake = os.path.join(self.root, "repo")
        mirror = {fake: MM.REPO}
        for depth in range(len(self.SLUGDIR) + 1):
            here, real = (os.path.join(fake, *self.SLUGDIR[:depth]),
                          os.path.join(MM.REPO, *self.SLUGDIR[:depth]))
            os.makedirs(here, exist_ok=True)
            keep = self.SLUGDIR[depth] if depth < len(self.SLUGDIR) else None
            for entry in os.listdir(real):
                if entry == keep or entry in ("records", "corners"):
                    continue
                os.symlink(os.path.join(real, entry), os.path.join(here, entry))
            mirror[here] = real
        out = os.path.join(fake, *self.SLUGDIR)
        os.makedirs(os.path.join(out, "records"))
        os.makedirs(os.path.join(out, "corners"))
        real_repo = MM.REPO
        MM.REPO = fake
        self.addCleanup(setattr, MM, "REPO", real_repo)
        return os.path.join(out, "records")

    def test_emit_record_refuses_a_partial_monte_carlo_set(self):
        records = self.sandboxed_repo()
        with self.assertRaises(SystemExit) as cm:
            MM.emit_record(self.reqdir(("tt-smp-2",)), sha="deadbee")
        self.assertIn("refusing to record a partial Monte Carlo set", str(cm.exception))
        self.assertEqual(os.listdir(records), [], "a refusal must mint nothing")

    def test_a_complete_set_still_emits(self):
        records = self.sandboxed_repo()
        MM.emit_record(self.reqdir(), sha="deadbee")
        self.assertEqual(sorted(os.path.basename(f).split(".")[-1] for f in os.listdir(records)),
                         ["json", "md"], "the refusal must not block a complete set")

    def test_the_committed_records_directory_is_never_written_to(self):
        live = os.path.join(REPO, "sim", "local-mismatch-monte-carlo", "records")
        before = sorted(os.listdir(live))
        self.sandboxed_repo()
        with self.assertRaises(SystemExit):
            MM.emit_record(self.reqdir(("tt-arr-2",)), sha="deadbee")
        self.assertEqual(sorted(os.listdir(live)), before)

    def test_requested_counts_come_from_the_plans_not_the_units_returned(self):
        # A response that came back short -- 8 corners for a 10-draw plan --
        # is a shortfall too, and used to report itself as 8/8.
        d = self.reqdir()
        p = os.path.join(d, "tt-arr-1", "resp.json")
        resp = json.load(open(p))
        resp["corners"] = resp["corners"][:8]
        json.dump(resp, open(p, "w"))
        chunks, missing = MM.load_reqdir(d)
        self.assertEqual(missing, [])
        _rows, S = MM.build(chunks, missing)["tt"]
        self.assertEqual(S["n_array_requested"], 30)
        self.assertEqual(S["n_array_ok"], 28)

    def test_a_plan_that_cannot_say_how_many_draws_it_asked_for_is_refused(self):
        # A missing request contributes only its requested count, so a plan that
        # cannot state one must stop the reduction rather than quietly count 0.
        d = self.reqdir(("tt-arr-1",))
        p = os.path.join(d, "tt-arr-1", "plan.json")
        plan = json.load(open(p))
        plan["monte_carlo"] = None
        json.dump(plan, open(p, "w"))
        chunks, missing = MM.load_reqdir(d)
        self.assertEqual([m[0] for m in missing], ["tt-arr-1"])
        with self.assertRaises(SystemExit) as cm:
            MM.build(chunks, missing)
        self.assertIn("monte_carlo.n", str(cm.exception))

    def test_missing_requests_are_attributed_to_their_own_corner(self):
        chunks, missing = MM.load_reqdir(self.reqdir(("tt-arr-1",)))
        other = [(nm, dict(pl, corner="ff"), why) for nm, pl, why in missing]
        _rows, S = MM.build(chunks, other)["tt"]
        self.assertEqual(S["n_array_requested"], 20,
                         "a missing request at another corner must not inflate this corner's denominator")


# ---------------------------------------------------------- one walk, five policies
class Consolidation(unittest.TestCase):
    """All five reducers must use the shared walk, not a private copy."""

    REDUCERS = {
        "ripple": "sim/ro-array-supply-perturbation/ripple.py",
        "wakeup": "sim/wake-up-transient/wakeup.py",
        "sensitivity": "sim/ro-vth-drift-sensitivity/analysis/sensitivity.py",
        "xor": "sim/xor-combining-alternatives/reduce.py",
        "mismatch": "sim/local-mismatch-monte-carlo/reduce.py",
    }
    FORKED = ("_submit_error", "_submit_err", "NO_RESPONSE")

    def mod(self, name):
        return load_module(f"reducer_{name}", os.path.join(REPO, self.REDUCERS[name]))

    def test_each_reducer_uses_the_shared_loader(self):
        for name in self.REDUCERS:
            with self.subTest(reducer=name):
                m = self.mod(name)
                self.assertIs(m.load_request_dir, rd.load_request_dir)
                for attr in self.FORKED:
                    self.assertFalse(hasattr(m, attr),
                                     f"{name} re-forked the request walk as {attr}; "
                                     "extend sim/bin/request_dir.py instead (issue #469)")

    def test_no_reducer_rewalks_a_request_directory_itself(self):
        """No reducer may glob or size-check resp.json to build its own chunk list.

        Narrower than "never names resp.json" on purpose: sensitivity.py's
        `emit_controls` still fetches a FIXED list of control requests by name
        (and already refuses loudly if one is absent), and archives superseded
        `resp.fail*.json` attempts. Neither is a directory walk, and neither is
        what drifted five ways."""
        for name, rel in self.REDUCERS.items():
            with self.subTest(reducer=name):
                for n, line in enumerate(open(os.path.join(REPO, rel)), 1):
                    if "resp.json" not in line:
                        continue
                    for idiom in ("glob", "getsize", "listdir", "scandir", "iterdir"):
                        self.assertNotIn(idiom, line,
                                         f"{rel}:{n} walks a request directory with {idiom}; "
                                         "the walk belongs in sim/bin/request_dir.py (issue #469)")

    def test_the_reason_string_is_defined_once(self):
        for name, rel in self.REDUCERS.items():
            with self.subTest(reducer=name):
                self.assertNotIn("request not submitted or submission did not complete",
                                 open(os.path.join(REPO, rel)).read())


class PreservedPolicies(TempReqdir):
    """Consolidating the walk must not change what any campaign records."""

    GOOD = {"corners": [{"status": "pass", "measurements": []}]}

    def test_ripple_still_returns_missing_requests_for_explicit_rows(self):
        m = load_module("reducer_ripple", os.path.join(REPO, self.REDUCERS_RIPPLE))
        write_request(self.root, "tt-tone-1", {"kind": "tone"}, self.GOOD)
        write_request(self.root, "tt-tone-2", {"kind": "tone"}, None)
        chunks, missing = m.load_reqdir_all(self.root)
        self.assertEqual([c[0] for c in chunks], ["tt-tone-1"])
        self.assertEqual([x[0] for x in missing], ["tt-tone-2"])
        self.assertEqual([c[0] for c in m.load_reqdir(self.root)], ["tt-tone-1"],
                         "the chunks-only wrapper keeps its signature")

    REDUCERS_RIPPLE = "sim/ro-array-supply-perturbation/ripple.py"

    def test_xor_still_refuses_unless_all_six_came_back(self):
        m = load_module("reducer_xor", os.path.join(REPO, "sim", "xor-combining-alternatives", "reduce.py"))
        for i in range(6):
            write_request(self.root, f"v{i}", {"name": f"v{i}"}, self.GOOD)
        self.assertEqual(len(m.load_reqdir(self.root)), 6)
        # one refused: named, not a bare "found 5"
        open(os.path.join(self.root, "v3", "resp.json"), "w").close()
        with self.assertRaises(m.ReductionError) as cm:
            m.load_reqdir(self.root)
        self.assertIn("v3", str(cm.exception))

    def test_xor_still_refuses_a_short_set(self):
        m = load_module("reducer_xor2", os.path.join(REPO, "sim", "xor-combining-alternatives", "reduce.py"))
        for i in range(5):
            write_request(self.root, f"v{i}", {"name": f"v{i}"}, self.GOOD)
        with self.assertRaises(m.ReductionError) as cm:
            m.load_reqdir(self.root)
        self.assertIn("expected 6", str(cm.exception))

    def test_wakeup_still_separates_the_legs_and_names_the_absent(self):
        m = load_module("reducer_wakeup", os.path.join(REPO, "sim", "wake-up-transient", "wakeup.py"))
        write_request(self.root, "det-1", {"leg": "det"}, self.GOOD)
        write_request(self.root, "det-2", {"leg": "det"}, None)
        write_request(self.root, "noisy-1", {"leg": "noisy"}, self.GOOD)
        chunks, missing = m.load_reqdir(self.root, "det")
        self.assertEqual([c[0] for c in chunks], ["det-1"])
        self.assertEqual([x[0] for x in missing], ["det-2"])
        self.assertEqual([c[0] for c in m.load_reqdir(self.root, "noisy")[0]], ["noisy-1"])

    def test_sensitivity_still_drops_and_leaves_the_gate_to_the_caller(self):
        m = load_module("reducer_sens", os.path.join(REPO, "sim", "ro-vth-drift-sensitivity",
                                                     "analysis", "sensitivity.py"))
        write_request(self.root, "p-1", {"key": "a"}, self.GOOD)
        write_request(self.root, "p-2", {"key": "b"}, None)
        chunks, missing = m.load_reqdir(self.root)
        self.assertEqual([c[0] for c in chunks], ["p-1"], "an unusable response contributes no row")
        self.assertEqual([x[0] for x in missing], ["p-2"], "but is still reported, for the refusal message")


if __name__ == "__main__":
    unittest.main()
