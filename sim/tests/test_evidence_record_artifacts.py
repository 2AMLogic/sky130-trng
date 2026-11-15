#!/usr/bin/env python3
"""Regression tests for artifact-name collisions in sim/bin/evidence_record.mint_behavioral_record (issue #273).

    python3 sim/tests/test_evidence_record_artifacts.py

Standard library only. Everything runs in temporary directories; nothing is written to the committed sim/ tree.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim" / "bin"))
sys.path.insert(0, str(REPO / "sim" / "tests"))
import evidence_record as er  # noqa: E402
import fake_klt  # noqa: E402


def use_fake_klt(case, tmp, mode="ok"):
    """Put a fake `klt` + broker env in front of the test (issue #347)."""
    patcher = mock.patch.dict(os.environ, fake_klt.install(tmp / "bin", mode))
    patcher.start()
    case.addCleanup(patcher.stop)


# --- static guard: no hand-rolled record tails outside the minter (issue #515) ---

# A line that names a `<rid>.md` / `<rid>.json` path the way the hand-rolled
# tails do (f-string or string concat) AND carries a write call on the same
# line. Doc back-references (`--check sim/<slug>/records/{rid}.json`) and
# prints never carry both, so they stay unflagged.
_RID_WRITE_TOKEN = re.compile(r"""\{rid\}\.(?:md|json)|rid \+ "\.(?:md|json)"|f'\{rid\}\.(?:md|json)'""")
_WRITE_CALL = re.compile(r"\.write_text\(|\.write\(|\bopen\(|json\.dump\(")

# The split shape (`record_json = records_dir / f"{rid}.json"` ... later
# `record_json.write_text(...)`), which `sim/bin/corner-run.py` uses.
_RID_BIND = re.compile(
    r"""^\s*(\w+)\s*=.*(?:\{rid\}\.(?:md|json)|rid \+ "\.(?:md|json)"|f'\{rid\}\.(?:md|json)')""")

# Known hand-rolled tails, allowed only until drained. `sim/bin/corner-run.py`
# is the `klt sim` record minter with its own `supersedes` handling (#504's
# reasoning, restated by #515's scope note); the other four are tracked by
# issue #525. `sensitivity.py` was converted by #515 and must NOT return here.
ALLOWED_HAND_ROLLED_TAILS = frozenset({
    "sim/bin/corner-run.py",
    "sim/digital-electrical-repair/analysis/record.py",
    "sim/post-layout-ro-ring5-assembled-181/derive.py",
    "sim/raw-bit-volume-campaign/derive-combining.py",
    "sim/wake-up-transient/wakeup.py",
})


def hand_rolled_record_tails(root: Path = REPO) -> set[str]:
    """Sim-relative paths under `sim/` that write a `<rid>.md`/`<rid>.json`
    record directly instead of going through `mint_record`/`_publish_bundle`.

    `sim/bin/evidence_record.py` is the minter itself; `sim/tests/` mint fake
    records by design (including this guard's own fixtures).
    """
    hits = set()
    for path in sorted((root / "sim").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == "sim/bin/evidence_record.py" or rel.startswith("sim/tests/"):
            continue
        lines = path.read_text().splitlines()
        bound = {m.group(1) for line in lines if (m := _RID_BIND.match(line))}
        for line in lines:
            direct = _RID_WRITE_TOKEN.search(line) and _WRITE_CALL.search(line)
            via_bound = any(re.search(rf"\b{name}\s*\.\s*(?:write_text|write)\(", line) for name in bound)
            if direct or via_bound:
                hits.add(rel)
                break
    return hits


def mint(root: Path, artifacts):
    with mock.patch.object(er, "git_short_sha", return_value="abc1234"):
        return er.mint_behavioral_record(root, "slug", "claim", "body", {"k": 1}, artifacts=artifacts)


class ArtifactCollision(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        use_fake_klt(self, self.tmp)
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
        self.assertFalse((self.root / "sim" / "slug" / "runs").exists())  # bytes are not committed
        man = json.loads((self.root / "manifests/artifacts" / f"slug-{rid}.manifest.json").read_text())
        self.assertEqual([e["name"] for e in man["entries"]],
                         [f"sim/slug/runs/{rid}/one.txt", f"sim/slug/runs/{rid}/two.txt"])
        self.assertTrue(all(e["uri"].startswith("artifact:") for e in man["entries"]))
        rec = json.loads((self.root / "sim" / "slug" / "records" / f"{rid}.json").read_text())
        self.assertEqual(rec["artifacts"],
                         [f"sim/slug/runs/{rid}/one.txt", f"sim/slug/runs/{rid}/two.txt"])


def snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class RecordFooterSupersedes(unittest.TestCase):
    """`record_footer(supersedes=...)` / `mint_record(supersedes=...)`: the
    correction mechanism the append-only rule requires (issue #504). The
    default must keep every pre-existing caller's footer byte-for-byte."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        use_fake_klt(self, self.tmp)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.recs = self.root / "sim" / "slug" / "records"

    def mint(self, supersedes=None, rid="20260101-000000-abc1234"):
        import datetime as dt
        kw = {} if supersedes is None else {"supersedes": supersedes}
        return er.mint_record(self.recs, self.root, rid, ["# h", ""], "body\n",
                              {"k": 1}, author="t",
                              now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                              sha="abc1234", **kw)

    def test_default_footer_names_no_correction(self):
        import datetime as dt
        md_path, _ = self.mint()
        expected = er.record_footer(author="t", now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                                    sha="abc1234")
        self.assertEqual(md_path.read_text().splitlines()[-len(expected):], expected)
        self.assertEqual(md_path.read_text().splitlines()[-1], "- Supersedes: (none)")

    def test_named_supersedes_replaces_the_last_footer_line_only(self):
        import datetime as dt
        md_path, _ = self.mint(supersedes="20251231-235959-0000000")
        lines = md_path.read_text().splitlines()
        self.assertEqual(lines[-1], "- Supersedes: 20251231-235959-0000000")
        self.assertEqual(lines[-7:-1],
                         ["", "---", "", "- Author: t", "- Timestamp (UTC): 2026-01-01T00:00:00+00:00",
                          "- Repo commit: `abc1234`"])
        self.assertEqual(lines[-8], "body")  # nothing above the footer moved

    def test_default_mint_record_matches_record_footer_default(self):
        import datetime as dt
        md_path, _ = self.mint()
        self.assertTrue(md_path.read_text().startswith("# h\nbody\n"))
        self.assertEqual(md_path.read_text().splitlines()[-4:],
                         list(er.record_footer(author="t", now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                                               sha="abc1234"))[-4:])

    def test_new_record_id_offset_gives_distinct_ids_same_sha(self):
        import datetime as dt

        class _FixedClock:
            class datetime(dt.datetime):
                @classmethod
                def now(cls, tz=None):
                    return dt.datetime(2026, 1, 1, 0, 0, 3, tzinfo=dt.timezone.utc)
            timedelta = dt.timedelta
            timezone = dt.timezone

        with mock.patch.object(er, "git_short_sha", return_value="abc1234"):
            with mock.patch.object(er, "_dt", _FixedClock):
                _, sha0, rid0 = er.new_record_id(self.root)
                _, sha1, rid1 = er.new_record_id(self.root, offset=1)
        self.assertEqual((sha0, sha1), ("abc1234", "abc1234"))
        self.assertEqual(rid0, "20260101-000003-abc1234")
        self.assertEqual(rid1, "20260101-000004-abc1234")


class PublicationIntegrity(unittest.TestCase):
    """Issue #277: complete bundles, exclusive id reservation, owned cleanup."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        use_fake_klt(self, self.tmp)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.art = self.tmp / "a.txt"
        self.art.write_text("data")
        self.recs = self.root / "sim" / "slug" / "records"

    def mint_rec(self, summary, rid="20260101-000000-abc1234"):
        import datetime as dt
        return er.mint_record(self.recs, self.root, rid, ["# h", ""], "body\n", summary,
                              author="t", now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                              sha="abc1234")

    def seed(self):
        """Mint one good behavioural record so there is existing evidence."""
        with mock.patch.object(er, "new_record_id", return_value=(
                __import__("datetime").datetime(2026, 1, 1), "abc1234", "20260101-000000-abc1234")):
            return er.mint_behavioral_record(self.root, "slug", "c", "b", {"k": 1},
                                             artifacts=[self.art])

    def behav(self, rid="20260101-000001-abc1234", summary=None, artifacts=None):
        import datetime as dt
        with mock.patch.object(er, "new_record_id",
                               return_value=(dt.datetime(2026, 1, 1), "abc1234", rid)):
            return er.mint_behavioral_record(self.root, "slug", "c", "b", summary or {"k": 2},
                                             artifacts=artifacts)

    def test_mint_record_invalid_json_leaves_nothing(self):
        loop: dict = {}
        loop["self"] = loop  # default=str cannot rescue a circular reference
        with self.assertRaises(ValueError):
            self.mint_rec(loop)
        self.assertEqual(snapshot(self.root), {})

    def test_behavioral_invalid_json_leaves_nothing(self):
        with self.assertRaises(TypeError):
            self.behav(summary={"bad": {1, 2}}, artifacts=[self.art])
        self.assertEqual(snapshot(self.root), {})

    def test_missing_artifact_leaves_nothing(self):
        with self.assertRaises(SystemExit):
            self.behav(artifacts=[self.tmp / "nope.txt"])
        self.assertEqual(snapshot(self.root), {})

    def test_success_with_artifacts_both_apis(self):
        rid = self.seed()
        base = self.root / "sim" / "slug"
        self.assertTrue((base / "records" / f"{rid}.md").is_file())
        self.assertFalse((base / "runs").exists())
        self.assertTrue((self.root / "manifests/artifacts" / f"slug-{rid}.manifest.json").is_file())
        self.assertTrue((base / "artifacts" / f"{rid}.md").is_file())
        self.assertIsNotNone(self.mint_rec({"x": 1}, rid="20260101-000009-abc1234"))
        names = sorted(p.name for p in self.recs.iterdir())
        self.assertEqual(names, [f"{rid}.json", f"{rid}.md",
                                 "20260101-000009-abc1234.json", "20260101-000009-abc1234.md"])

    def _inject(self, target, call):
        self.seed()
        before = snapshot(self.root)
        with mock.patch.object(er, target, side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                call()
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(sorted(p.name for p in self.recs.iterdir() if p.name.startswith(".")), [])

    def test_artifact_copy_failure_behavioral(self):
        self._inject("_link_noreplace", lambda: self.behav(artifacts=[self.art]))

    def test_publication_failure_mint_record(self):
        self._inject("_link_noreplace", lambda: self.mint_rec({"x": 1}, rid="20260101-000009-abc1234"))

    def test_late_publication_failure_removes_published_pieces(self):
        self.seed()
        before = snapshot(self.root)
        real = er._link_noreplace
        calls = []

        def flaky(src, dst):
            calls.append(dst.name)
            if len(calls) == 2:  # the .md step, after runs dir + json published
                raise OSError("injected")
            real(src, dst)
        with mock.patch.object(er, "_link_noreplace", side_effect=flaky):
            with self.assertRaises(OSError):
                self.behav(artifacts=[self.art])
        self.assertEqual(snapshot(self.root), before)

    def test_same_id_collision_after_success_keeps_original(self):
        rid = self.seed()
        before = snapshot(self.root)
        with self.assertRaises(SystemExit) as cm:
            self.behav(rid=rid, artifacts=[self.art])
        self.assertIn("already exists", str(cm.exception))
        self.assertEqual(snapshot(self.root), before)
        self.assertIsNone(self.mint_rec({"x": 1}, rid=rid))
        self.assertEqual(snapshot(self.root), before)

    def test_concurrent_reservation_loses_cleanly(self):
        """A writer holding the reservation makes the other get a clear collision."""
        rid = "20260101-000002-abc1234"
        self.recs.mkdir(parents=True)
        (self.recs / f".{rid}.reserve").write_text("pid=1\n")
        before = snapshot(self.root)
        with self.assertRaises(SystemExit) as cm:
            self.behav(rid=rid, artifacts=[self.art])
        self.assertIn("reserved", str(cm.exception))
        self.assertIsNone(self.mint_rec({"x": 1}, rid=rid))
        # the other writer's reservation is not ours to remove
        self.assertEqual(snapshot(self.root), before)

    def test_two_writers_racing_same_id_one_wins(self):
        import datetime as dt
        import threading
        rid = "20260101-000003-abc1234"
        barrier = threading.Barrier(2)
        orig = Path.exists

        def synced(self_, *a, **k):
            r = orig(self_, *a, **k)
            if self_.name == f"{rid}.md":
                try:
                    barrier.wait(timeout=2)
                except threading.BrokenBarrierError:
                    pass
            return r
        results = []

        def worker():
            try:
                results.append(("ok", er.mint_behavioral_record(self.root, "slug", "c", "b", {"k": 2},
                                                                artifacts=[self.art])))
            except SystemExit as e:
                results.append(("collision", str(e)))
        # One shared patch entered once: per-thread mock.patch.object on the same
        # target races its own save/restore and can leak a mock into the module
        # for every test that runs after this one.
        with mock.patch.object(Path, "exists", synced), \
                mock.patch.object(er, "new_record_id",
                                  return_value=(dt.datetime(2026, 1, 1), "abc1234", rid)):
            ts = [threading.Thread(target=worker) for _ in range(2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(sorted(r[0] for r in results), ["collision", "ok"])
        self.assertTrue((self.root / "manifests/artifacts" / f"slug-{rid}.manifest.json").is_file())
        self.assertEqual(len(list(self.recs.glob("*.md"))), 1)


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


class WriteCornerBundle(unittest.TestCase):
    """er.write_corner_bundle: shared corner-bundle writer + collision guard (issue #392)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.reqdir = self.root / "req"
        (self.reqdir / "a").mkdir(parents=True)
        (self.reqdir / "a" / "request.json").write_text('{"r": 1}')
        (self.reqdir / "a" / "netlist.cir").write_text("* deck\n")
        self.rdir = self.root / "records"
        self.cdir = self.root / "corners" / "rid1"
        self.chunks = [("a", {"corner": "tt"}, {"environment": {"remote": {"job_id": "job-1"}}})]

    def write(self):
        return er.write_corner_bundle(self.cdir, self.reqdir, self.chunks, records_dir=self.rdir, rid="rid1")

    def test_writes_bundle_and_returns_jobs(self):
        import gzip
        self.assertEqual(self.write(), ["job-1"])
        self.assertEqual(sorted(p.name for p in self.cdir.iterdir()),
                         ["a.klt-sim.json.gz", "a.netlist.cir", "a.plan.json", "a.request.json"])
        with gzip.open(self.cdir / "a.klt-sim.json.gz", "rt") as fh:
            self.assertEqual(fh.read(), json.dumps(self.chunks[0][2], indent=1))
        self.assertEqual((self.cdir / "a.plan.json").read_text(), json.dumps({"corner": "tt"}, indent=1))

    def test_local_job_label(self):
        self.chunks[0] = ("a", {}, {"environment": {}})
        self.assertEqual(self.write(), ["local (single-unit reference run)"])

    def test_refuses_existing_record_json(self):
        self.rdir.mkdir()
        (self.rdir / "rid1.json").write_text("{}")
        with self.assertRaisesRegex(SystemExit, "rid1 exists"):
            self.write()
        self.assertFalse(self.cdir.exists())

    def test_refuses_existing_cdir_untouched(self):
        self.cdir.mkdir(parents=True)
        (self.cdir / "keep").write_text("x")
        with self.assertRaisesRegex(SystemExit, "rid1 exists"):
            self.write()
        self.assertEqual([p.name for p in self.cdir.iterdir()], ["keep"])

    def test_missing_netlist_leaves_nothing_behind(self):
        (self.reqdir / "a" / "netlist.cir").unlink()
        with self.assertRaises(SystemExit):
            self.write()
        self.assertFalse(self.cdir.exists())
        self.assertFalse(self.rdir.exists())


class ReadCornerBundle(unittest.TestCase):
    """er.read_corner_bundle: the inverse of write_corner_bundle (issue #497)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.reqdir = self.root / "req"
        self.rdir = self.root / "records"
        self.cdir = self.root / "corners" / "rid1"

    def store(self, chunks):
        for n, _pl, _rs in chunks:
            d = self.reqdir / n
            d.mkdir(parents=True)
            (d / "request.json").write_text('{"r": 1}')
            (d / "netlist.cir").write_text("* deck\n")
        er.write_corner_bundle(self.cdir, self.reqdir, chunks, records_dir=self.rdir, rid="rid1")

    def test_roundtrip_sorted_names(self):
        chunks = [("b", {"corner": "tt"}, {"v": "beta"}), ("a", {"corner": "ff"}, {"v": "alpha"})]
        self.store(chunks)
        self.assertEqual(er.read_corner_bundle(self.cdir),
                         [("a", {"corner": "ff"}, {"v": "alpha"}), ("b", {"corner": "tt"}, {"v": "beta"})])

    def test_prefix_filter(self):
        self.store([("ctl-1", {}, {"v": 1}), ("ctl-2", {}, {"v": 2}), ("pert-1", {}, {"v": 3})])
        self.assertEqual([nm for nm, _, _ in er.read_corner_bundle(self.cdir, prefix="ctl-")],
                         ["ctl-1", "ctl-2"])

    def test_with_missing_pairs_notes_with_plans(self):
        self.store([("kept", {}, {"v": 1})])
        (self.cdir / "gone.missing.json").write_text(json.dumps({"request": "gone", "reason": "timeout"}))
        (self.cdir / "gone.plan.json").write_text(json.dumps({"corner": "gone"}, indent=1))
        chunks, missing = er.read_corner_bundle(self.cdir, with_missing=True)
        self.assertEqual([nm for nm, _, _ in chunks], ["kept"])
        self.assertEqual(missing, [("gone", {"corner": "gone"}, "timeout")])
        self.assertEqual(er.read_corner_bundle(self.cdir), chunks)  # default hides the notes

    def test_malformed_plan_fails_loudly(self):
        self.store([("a", {}, {"v": 1})])
        (self.cdir / "a.plan.json").write_text("{not json")
        with self.assertRaises(json.JSONDecodeError):
            er.read_corner_bundle(self.cdir)

    def test_missing_cdir_reads_empty(self):
        self.assertEqual(er.read_corner_bundle(self.root / "corners" / "nothing"), [])
class NoNewHandRolledRecordTails(unittest.TestCase):
    """Static guard (issue #515): every `sim/**/*.py` record write must go
    through `mint_record`/`_publish_bundle`. A direct `<rid>.md`/`<rid>.json`
    write has no completion boundary (a kill between the two writes strands a
    JSON-only record that `check_records_append_only.py` then protects from
    deletion forever -- the #277 boundary) and no shared provenance footer."""

    def test_allowlist_is_exact(self):
        found = hand_rolled_record_tails()
        new = sorted(found - ALLOWED_HAND_ROLLED_TAILS)
        drained = sorted(ALLOWED_HAND_ROLLED_TAILS - found)
        self.assertFalse(
            new,
            "new hand-rolled record tail(s) -- route them through mint_record/"
            "_publish_bundle (issue #515), or extend ALLOWED_HAND_ROLLED_TAILS "
            f"in {Path(__file__).name} with a tracked issue: {new}")
        self.assertFalse(
            drained,
            "allowlist entr(y/ies) no longer hand-roll their tails -- remove "
            f"them from ALLOWED_HAND_ROLLED_TAILS: {drained}")

    def test_detector_flags_a_deliberate_tail_and_passes_references(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slug = root / "sim" / "slug"
            slug.mkdir(parents=True)
            clean = slug / "clean.py"
            clean.write_text('print(f"--check sim/slug/records/{rid}.json`")\n')
            dirty = slug / "dirty.py"
            dirty.write_text('(rdir / f"{rid}.md").write_text(md)\n'
                             'json.dump(rec, open(os.path.join(rdir, rid + ".json"), "w"))\n')
            split = slug / "split.py"
            split.write_text('record_json = records_dir / f"{rid}.json"\n'
                             'record_json.write_text("{}")\n')
            self.assertEqual(hand_rolled_record_tails(root), {"sim/slug/dirty.py", "sim/slug/split.py"})


if __name__ == "__main__":
    unittest.main()
