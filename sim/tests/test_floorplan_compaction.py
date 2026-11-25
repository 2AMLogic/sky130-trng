#!/usr/bin/env python3
"""Contract tests for the issue #226 floorplan-compaction study (no klt,
no OpenROAD needed):

- the harness refuses `--emit-record` with a non-default `--request`, so a
  study run can never replace `layout/trng_digital/`;
- the re-stacked area model reproduces the committed whole-block bbox
  exactly at the baseline digital size, and shrinks monotonically;
- the study requests differ from the committed request only in
  `floorplan.utilization_pct` (netlist path rebased to the same file);
- `_exit_from_codes` handles both exit-codes.txt line formats with
  last-match-wins retry semantics (issues #501, #658);
- the consolidated repaired-compaction reducer reproduces the committed
  #251 record byte-for-byte, and both run-study.sh entrypoints route
  requests/run dirs to their own study (issue #658).
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim" / "bin"))
from loadmod import load_module  # noqa: E402
STUDY = ROOT / "sim" / "digital-floorplan-compaction"


class HarnessGuard(unittest.TestCase):
    def test_emit_record_refused_for_study_request(self):
        h = load_module("pnr_and_verify", ROOT / "sim" / "digital-pnr" / "harness" / "pnr-and-verify.py")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = h.main(["--request", str(STUDY / "requests" / "util55.json"), "--emit-record"])
        self.assertEqual(rc, 2)
        self.assertIn("refused", err.getvalue())
        # default target unchanged
        self.assertEqual(h.REQUEST, ROOT / "digital" / "flow" / "place-and-route" / "pnr-trng-digital-50khz.json")


class AreaModel(unittest.TestCase):
    def setUp(self):
        self.m = load_module("compaction", STUDY / "analysis" / "compaction.py")
        self.whole = json.loads((ROOT / "layout" / "trng_whole" / "report.json").read_text())

    def test_reproduces_committed_bbox(self):
        a = self.m.area_model(245.05, 245.05, self.whole)
        self.assertAlmostEqual(a["estimate_restacked_same_topology_mm2"], self.whole["area"]["area_mm2"], places=5)
        self.assertAlmostEqual(a["estimate_additive_overhead_mm2"], self.whole["area"]["area_mm2"], places=5)

    def test_monotone(self):
        sizes = [245.05, 210.0, 190.0, 150.0]
        b = [self.m.area_model(s, s, self.whole)["estimate_restacked_same_topology_mm2"] for s in sizes]
        self.assertEqual(b, sorted(b, reverse=True))
        for s in sizes:
            a = self.m.area_model(s, s, self.whole)
            self.assertLessEqual(a["lower_bound_macros_only_mm2"], a["estimate_restacked_same_topology_mm2"])


class Requests(unittest.TestCase):
    def test_only_utilization_differs(self):
        committed = json.loads((ROOT / "digital" / "flow" / "place-and-route" / "pnr-trng-digital-50khz.json").read_text())
        net_c = (ROOT / "digital" / "flow" / "place-and-route" / committed["netlist"]).resolve()
        for u in (40, 55, 65):
            p = STUDY / "requests" / f"util{u}.json"
            r = json.loads(p.read_text())
            self.assertEqual((p.parent / r["netlist"]).resolve(), net_c)
            self.assertEqual(r["floorplan"]["utilization_pct"], u)
            a, b = dict(committed), dict(r)
            for d in (a, b):
                d.pop("netlist")
                d["floorplan"] = {k: v for k, v in d["floorplan"].items() if k != "utilization_pct"}
            self.assertEqual(a, b)


class ExitFromCodes(unittest.TestCase):
    """Regression (issue #501 review): exit-codes.txt is append-only, so a
    retried run name appears twice; the LAST matching line is the final rc."""

    def setUp(self):
        self.m = load_module("compaction", STUDY / "analysis" / "compaction.py")

    def test_last_match_wins_on_retry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "util40"
            run.mkdir()
            (Path(t) / "exit-codes.txt").write_text(
                "util40 exit 1 start 2026-01-01T00:00:00Z end 2026-01-01T00:10:00Z\n"
                "util40 exit 0 start 2026-01-01T01:00:00Z end 2026-01-01T01:10:00Z\n"
            )
            self.assertEqual(self.m._exit_from_codes(run), 0)

    def test_single_match_and_missing_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "util55"
            run.mkdir()
            (Path(t) / "exit-codes.txt").write_text(
                "util40 exit 1 start 2026-01-01T00:00:00Z end 2026-01-01T00:10:00Z\n"
                "util55 exit 3 start 2026-01-01T01:00:00Z end 2026-01-01T01:10:00Z\n"
            )
            self.assertEqual(self.m._exit_from_codes(run), 3)
            self.assertIsNone(self.m._exit_from_codes(Path(t) / "util65"))

    def test_step_last_match_wins_on_retry(self):
        # Regression (issue #658): the retired repaired-compaction pnr_exit
        # loop returned the FIRST "<name> pnr-verify exit <rc>" match, so a
        # retried rep* point reported the stale failed rc. With step=, the
        # last pnr-verify line wins and the audit lines are ignored.
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "rep40-slew0531"
            run.mkdir()
            (Path(t) / "exit-codes.txt").write_text(
                "rep40-slew0531 pnr-verify exit 1 start 2026-01-01T00:00:00Z end 2026-01-01T00:10:00Z\n"
                "rep40-slew0531 audit exit 1 end 2026-01-01T00:12:00Z\n"
                "rep40-slew0531 pnr-verify exit 0 start 2026-01-01T01:00:00Z end 2026-01-01T01:10:00Z\n"
                "rep40-slew0531 audit exit 0 end 2026-01-01T01:12:00Z\n"
            )
            self.assertEqual(self.m._exit_from_codes(run, step="pnr-verify"), 0)

    def test_step_ignores_audit_and_manual_rerun_lines(self):
        # The committed 20261010-092825-main exit-codes.txt shape: one
        # pnr-verify line per run plus retried/manual audit lines, including
        # "(manual rerun ...)" prose between the step token and "exit".
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "rep55-slew0531"
            run.mkdir()
            (Path(t) / "exit-codes.txt").write_text(
                "rep55-slew0531 pnr-verify exit 0 start 2026-01-01T00:00:00Z end 2026-01-01T00:30:00Z\n"
                "rep55-slew0531 audit exit 2 end 2026-01-01T00:30:22Z\n"
                "rep55-slew0531 audit (manual rerun after script path bug) exit 1 end 2026-01-01T00:30:57Z\n"
                "rep55-slew0531 audit (manual rerun after script path bug) exit 0 end 2026-01-01T00:31:35Z\n"
                "unrepaired-util55 audit exit 0 end 2026-01-01T00:32:11Z\n"
            )
            self.assertEqual(self.m._exit_from_codes(run, step="pnr-verify"), 0)
            self.assertIsNone(self.m._exit_from_codes(Path(t) / "unrepaired-util55", step="pnr-verify"))

    def test_no_step_ignores_step_lines(self):
        # "<name> audit exit <rc>" must never be read as a bare exit line.
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            run = Path(t) / "rep65-slew0531"
            run.mkdir()
            (Path(t) / "exit-codes.txt").write_text(
                "rep65-slew0531 pnr-verify exit 0 start 2026-01-01T00:00:00Z end 2026-01-01T00:30:00Z\n"
                "rep65-slew0531 audit exit 0 end 2026-01-01T00:30:51Z\n"
            )
            self.assertIsNone(self.m._exit_from_codes(run))


class RepairedCompactionRecord(unittest.TestCase):
    """Record neutrality (issue #658): the consolidated reducer (C.load,
    C.sha256, partial(C._exit_from_codes, step="pnr-verify") -- no local jl/
    sha/pnr_exit forks) reproduces the committed #251 record byte-for-byte
    from the committed run directories. No --emit-record: nothing is written
    and the append-only records/ tree is untouched."""

    RID = "20261010-092825-main"
    RECORD = "20261010-105914-824542d"

    def test_run_reproduces_committed_record(self):
        import contextlib
        import io
        rc_mod = load_module("repaired_compaction",
                             ROOT / "sim/digital-repaired-compaction/analysis/repaired_compaction.py")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = rc_mod.main(["--run", self.RID])
        self.assertEqual(rc, 0)
        committed = (ROOT / "sim/digital-repaired-compaction/records" / f"{self.RECORD}.md").read_text()
        header, sep, _footer = committed.rpartition("\n---\n\n- Author:")
        self.assertTrue(sep, "committed record has no mint_record footer to strip")
        self.assertEqual(out.getvalue(), header + "\n")


class RunStudySh(unittest.TestCase):
    """The repaired-compaction runner is a STUDY_REL exec wrapper over the
    parameterised electrical-repair runner (issue #658). bash -n keeps both
    entrypoints (REPRODUCE.md CLI unchanged) syntactically valid; the stubbed
    end-to-end run pins the request/run-dir routing without klt or P&R."""

    def test_bash_n(self):
        import subprocess
        for rel in ("sim/digital-electrical-repair/bin/run-study.sh",
                    "sim/digital-repaired-compaction/bin/run-study.sh"):
            subprocess.run(["bash", "-n", str(ROOT / rel)], check=True)

    @staticmethod
    def _tree(d):
        if not d.exists():
            return None
        return sorted((str(p.relative_to(d)), p.is_dir(), p.lstat().st_size, p.lstat().st_mtime_ns)
                      for p in d.rglob("*"))

    def _stubbed_run(self, script, study_rel, rid, name):
        import os
        import shutil
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp_root = Path(t)
            log = tmp_root / "calls.log"
            bindir = tmp_root / "bin"
            bindir.mkdir()
            (bindir / "klt").write_text("#!/bin/sh\necho fake-klt 0.0.0-test\n")
            (bindir / "python3").write_text(
                "#!/bin/sh\n"
                f'printf \'%s\\n\' "$*" >> {log}\n'
                "exit 0\n")
            (bindir / "klt").chmod(0o755)
            (bindir / "python3").chmod(0o755)
            for rel in ("sim/digital-electrical-repair/bin/run-study.sh",
                        "sim/digital-repaired-compaction/bin/run-study.sh"):
                (tmp_root / rel).parent.mkdir(parents=True)
                shutil.copy2(ROOT / rel, tmp_root / rel)
            rdir = tmp_root / study_rel / "runs" / rid
            checkout_rdir = ROOT / study_rel / "runs" / rid
            before = self._tree(checkout_rdir)
            env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
            subprocess.run(["bash", str(tmp_root / script), str(bindir / "klt"), rid, name],
                           cwd=tmp_root, env=env, check=True, capture_output=True, text=True)
            self.assertEqual(self._tree(checkout_rdir), before,
                             msg=f"stubbed run touched the checkout run dir: {checkout_rdir}")
            calls = log.read_text().splitlines()
            out_dir = rdir / name
            self.assertTrue(any("sim/digital-pnr/harness/pnr-and-verify.py" in c
                                and f"--request {study_rel}/requests/{name}.json" in c
                                and f"--out-dir {out_dir}" in c for c in calls),
                            msg=f"pnr-and-verify not routed via {study_rel}: {calls}")
            self.assertTrue(any("final_route_audit.py" in c
                                and f"--request {study_rel}/requests/{name}.json" in c for c in calls),
                            msg=f"final_route_audit not routed via {study_rel}: {calls}")
            ec = (rdir / "exit-codes.txt").read_text()
            self.assertIn(f"{name} pnr-verify exit 0", ec)
            self.assertIn(f"{name} audit exit 0", ec)

    def test_wrapper_routes_to_repaired_compaction(self):
        self._stubbed_run("sim/digital-repaired-compaction/bin/run-study.sh",
                          "sim/digital-repaired-compaction", "wrapper-selftest-658", "rep40-slew0531")

    def test_default_routes_to_electrical_repair(self):
        self._stubbed_run("sim/digital-electrical-repair/bin/run-study.sh",
                          "sim/digital-electrical-repair", "wrapper-selftest-658", "slew0531")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
