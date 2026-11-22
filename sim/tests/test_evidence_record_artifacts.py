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

# The detector walks the AST (issue #531) rather than matching source text, so
# it does not depend on how the path is spelled (`rid+".md"`, `'{rid}.md'`,
# `"%s.md" % rid`, `.format(rid)`, `.with_suffix(".md")`, ...). Each path
# expression is *rendered* to a string with `rid` as a sentinel and every other
# interpolation as an opaque wildcard (so `f"{outdir}/{rid}.md"` still ends in
# `<rid>.md`). A write is a record tail only when the rendered path ends in
# EXACTLY `<rid>.md`/`<rid>.json`: `endswith(".json")` would also flag the
# legitimate `<rid>.calibration.json` sidecar. Doc back-references, prints,
# `.exists()` checks and read-only `open()`s (omitted mode or a literal read
# mode such as `"rb"` -- issue #618) never reach a write call, so they stay
# unflagged.
_RID, _ANY = "\x00", "\x01"
_RID_TAIL = re.compile(r"\x00\.(?:md|json)\Z")
_WRITE_ATTRS = {"write_text", "write_bytes", "write", "open"}
_WRITE_MODE_CHARS = frozenset("wax+")
_PLACEHOLDER = re.compile(r"%[sdr]|\{[^{}]*\}")


def _render(node, bound=frozenset()) -> str:
    """Render a path expression to a string; `rid` -> _RID, unknown -> _ANY."""
    import ast
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else _ANY
    if isinstance(node, ast.Name):
        return _RID if node.id == "rid" else _ANY
    if isinstance(node, ast.JoinedStr):
        return "".join(_render(v.value, bound) if isinstance(v, ast.FormattedValue)
                       else _render(v, bound) for v in node.values)
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return _render(node.left, bound) + _render(node.right, bound)
        if isinstance(node.op, ast.Div):
            return _render(node.left, bound) + "/" + _render(node.right, bound)
        if isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) \
                and isinstance(node.left.value, str):
            right = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
            vals = iter(_render(r, bound) for r in right)
            return _PLACEHOLDER.sub(lambda _m: next(vals, _ANY), node.left.value)
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "format" \
                and isinstance(f.value, ast.Constant) and isinstance(f.value.value, str):
            pos = iter(_render(a, bound) for a in node.args)
            kw = {k.arg: _render(k.value, bound) for k in node.keywords}
            return _PLACEHOLDER.sub(
                lambda m: kw.get(m.group(0)[1:-1], _ANY) if m.group(0)[1:-1] in kw
                else next(pos, _ANY), f.value.value)
        if isinstance(f, ast.Attribute) and f.attr == "with_suffix" and node.args:
            return _render(f.value, bound) + _render(node.args[0], bound)
        if isinstance(f, ast.Attribute) and f.attr == "join" and node.args:  # os.path.join
            return "/".join(_render(a, bound) for a in node.args)
        if isinstance(f, ast.Name) and f.id == "Path" and node.args:
            return _render(node.args[0], bound)
    return _ANY


def _is_tail(node) -> bool:
    return bool(_RID_TAIL.search(_render(node)))


def _open_mode(n, mode_index: int):
    """The `mode` argument of an `open()` call: positional slot `mode_index`
    (2nd arg for the built-in, 1st for the method), else the `mode=` keyword,
    else None when omitted."""
    if len(n.args) > mode_index:
        return n.args[mode_index]
    return next((k.value for k in n.keywords if k.arg == "mode"), None)


def _mode_implies_write(mode) -> bool:
    """False only for a mode the AST establishes as read-only: omitted (which
    reads) or a literal without `w`/`a`/`x`/`+`. Anything else -- a variable,
    a call result -- is conservatively a write (issue #618)."""
    import ast
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return bool(_WRITE_MODE_CHARS.intersection(mode.value.lower()))
    return True


# Known hand-rolled tails, allowed only until drained. `sim/bin/corner-run.py`
# is the `klt sim` record minter with its own `supersedes` handling (#504's
# reasoning, restated by #515's scope note). The four #525 reducers were
# converted through `mint_record` and drained from this list; `sensitivity.py`
# was converted by #515. Neither may return here.
ALLOWED_HAND_ROLLED_TAILS = frozenset({
    "sim/bin/corner-run.py",
})


def hand_rolled_record_tails(root: Path = REPO) -> set[str]:
    """Sim-relative paths under `sim/` that write a `<rid>.md`/`<rid>.json`
    record directly instead of going through `mint_record`/`_publish_bundle`.

    `sim/bin/evidence_record.py` is the minter itself; `sim/tests/` mint fake
    records by design (including this guard's own fixtures). A file that does
    not parse is skipped.
    """
    import ast
    hits = set()
    for path in sorted((root / "sim").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == "sim/bin/evidence_record.py" or rel.startswith("sim/tests/"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, ValueError, UnicodeDecodeError):
            continue
        nodes = list(ast.walk(tree))
        # The split shape (`record_md = records_dir / f"{rid}.md"` ... later
        # `record_md.write_text(...)`), which `sim/bin/corner-run.py` uses.
        bound = {t.id for n in nodes if isinstance(n, ast.Assign) and _is_tail(n.value)
                 for t in n.targets if isinstance(t, ast.Name)}
        for n in nodes:
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            mode_index = None
            if isinstance(f, ast.Name) and f.id == "open" and n.args:
                target = n.args[0]
                mode_index = 1  # open(path, mode, ...)
            elif isinstance(f, ast.Attribute) and f.attr in _WRITE_ATTRS:
                target = f.value
                if f.attr == "open":
                    mode_index = 0  # path.open(mode, ...)
            else:
                continue
            if mode_index is not None and not _mode_implies_write(_open_mode(n, mode_index)):
                continue  # read-only open() of a record path is not a tail
            if _is_tail(target) or (isinstance(target, ast.Name) and target.id in bound):
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

    def test_prefix_filters_missing_notes_too(self):
        self.store([("ctl-1", {}, {"v": 1}), ("pert-1", {}, {"v": 2})])
        (self.cdir / "ctl-gone.missing.json").write_text(json.dumps({"request": "ctl-gone", "reason": "timeout"}))
        (self.cdir / "ctl-gone.plan.json").write_text(json.dumps({"corner": "ctl"}, indent=1))
        (self.cdir / "pert-gone.missing.json").write_text(json.dumps({"request": "pert-gone", "reason": "refused"}))
        (self.cdir / "pert-gone.plan.json").write_text(json.dumps({"corner": "pert"}, indent=1))
        chunks, missing = er.read_corner_bundle(self.cdir, prefix="ctl-", with_missing=True)
        self.assertEqual([nm for nm, _, _ in chunks], ["ctl-1"])
        self.assertEqual(missing, [("ctl-gone", {"corner": "ctl"}, "timeout")])

    def test_prefix_matching_no_notes_returns_empty_missing(self):
        self.store([("ctl-1", {}, {"v": 1})])
        (self.cdir / "pert-gone.missing.json").write_text(json.dumps({"request": "pert-gone", "reason": "timeout"}))
        (self.cdir / "pert-gone.plan.json").write_text(json.dumps({"corner": "pert"}, indent=1))
        self.assertEqual(er.read_corner_bundle(self.cdir, prefix="ctl-", with_missing=True),
                         ([("ctl-1", {}, {"v": 1})], []))

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

    def _scan(self, files: dict[str, str]) -> set[str]:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slug = root / "sim" / "slug"
            slug.mkdir(parents=True)
            for name, text in files.items():
                (slug / name).write_text(text)
            return {Path(h).name for h in hand_rolled_record_tails(root)}

    def test_detector_flags_every_spelling(self):
        spellings = [
            '(rdir / f"{rid}.md").write_text(md)',
            '(rdir / (rid + ".md")).write_text(md)',
            '(rdir / (rid+".md")).write_text(md)',
            "(rdir / (rid + '.md')).write_text(md)",
            '(rdir / ("%s.md" % rid)).write_text(md)',
            '(rdir / "{}.md".format(rid)).write_text(md)',
            '(rdir / rid).with_suffix(".md").write_text(md)',
            'open(os.path.join(rdir, f"{rid}.md"), "w").write(md)',
            'open(f"{outdir}/{rid}.md", "w").write(md)',  # unknown interpolation
            'json.dump(rec, open(os.path.join(rdir, rid + ".json"), "w"))',
        ]
        for i, src in enumerate(spellings):
            with self.subTest(src):
                self.assertEqual(self._scan({f"v{i}.py": src + "\n"}), {f"v{i}.py"})

    def test_open_reads_not_flagged(self):
        """Issue #618: a read-only `open()` of a record path is not a tail."""
        reads = {
            "nested.py": 'rec = json.load(open(os.path.join(HERE, "records", rid + ".json")))\n',
            "pos_r.py": 'open(rdir / f"{rid}.json", "r")\n',
            "pos_rb.py": 'open(rdir / f"{rid}.md", "rb")\n',
            "pos_rt.py": 'open(rdir / f"{rid}.json", "rt")\n',
            "kw_mode.py": 'open(rdir / f"{rid}.json", mode="rb")\n',
            "attr_none.py": '(rdir / f"{rid}.json").open()\n',
            "attr_pos.py": '(rdir / f"{rid}.md").open("rb")\n',
            "attr_kw.py": '(rdir / f"{rid}.json").open(mode="r")\n',
            "bound_read.py": 'record_json = rdir / f"{rid}.json"\n'
                             'json.load(open(record_json, "r"))\n',
        }
        self.assertEqual(self._scan(reads), set())

    def test_open_write_modes_flagged_across_call_forms(self):
        """Issue #618: writing/appending/exclusive/updating modes and modes the
        AST cannot establish as read-only still hit on a record path."""
        writes = {
            "w.py": 'open(rdir / f"{rid}.json", "w").write(md)\n',
            "wb.py": 'json.dump(rec, open(rdir / f"{rid}.json", "wb"))\n',
            "append.py": 'open(rdir / f"{rid}.md", "a").write(line)\n',
            "exclusive.py": 'open(rdir / f"{rid}.md", "x").write(md)\n',
            "update.py": 'open(rdir / f"{rid}.json", "r+").write(data)\n',
            "kw_mode.py": 'open(rdir / f"{rid}.json", mode="wb").write(md)\n',
            "attr_pos.py": '(rdir / f"{rid}.json").open("wb").write(md)\n',
            "attr_kw.py": '(rdir / f"{rid}.md").open(mode="a").write(line)\n',
            "bound_write.py": 'record_md = rdir / f"{rid}.md"\n'
                              'open(record_md, "w").write(md)\n',
            "var_mode.py": 'mode = "r"\nopen(rdir / f"{rid}.json", mode).write(md)\n',
        }
        self.assertEqual(self._scan(writes), set(writes))

    def test_detector_flags_split_bound_write(self):
        self.assertEqual(
            self._scan({"split.py": 'record_json = records_dir / f"{rid}.json"\n'
                                    'record_json.write_text("{}")\n'}), {"split.py"})

    def test_detector_passes_references_and_sidecars(self):
        clean = {
            "doc.py": 'print(f"--check sim/slug/records/{rid}.json`")\n',
            "sidecar.py": 'cal_path = rdir / f"{rid}.calibration.json"\n'
                          '(rdir / f"{rid}.calibration.json").write_text("{}")\n'
                          'cal_path.write_text("{}")\n',
            "heading.py": 'md = f"# {rid} -- slug"\nmint_record(root, md)\n',
            "bound_reads.py": 'record_md = records_dir / f"{rid}.md"\n'
                              'if record_md.exists():\n    raise SystemExit(1)\n'
                              "print(f\"written: {(records_dir / f'{rid}.md')}\")\n",
            "broken.py": "def (:\n",
        }
        self.assertEqual(self._scan(clean), set())


if __name__ == "__main__":
    unittest.main()
