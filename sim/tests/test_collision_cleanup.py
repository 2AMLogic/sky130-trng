#!/usr/bin/env python3
"""Collision-cleanup tests for the four `mint_record` emit sites (issue #525).

When `mint_record` refuses a colliding record id, each emit site must remove
the corner bundle it reserved for that invocation -- and ONLY that one. The
det leg shares one `corners/{store_rid}/` bundle across all its records, and
records 1..k-1 are already published citing it by the time a later id
collides, so a blanket rmtree there permanently destroys committed provenance
(verified correction on issue #525, 2026-11-15). The #515 static guard checks
for hand-rolled write tails, not rmtree scope: this is the one regression it
cannot catch, hence these tests.

The harness patches `new_record_id` for deterministic ids and pre-creates a
partial `<rid>.md` as the colliding state; everything runs in a temp sandbox
against the real `mint_record`/`_publish_bundle` collision detection and the
real cleanup branches (each module's `REPO` is re-pointed at the sandbox so
`mint_record`'s `relative_to` stderr line stays valid). Standard library
only: no ngspice, no PDK.

    python3 sim/tests/test_collision_cleanup.py
"""
import json
import shutil
import sys
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from loadmod import load_module  # noqa: E402
import evidence_record as er  # noqa: E402

w = load_module("wakeup", REPO / "sim/wake-up-transient/wakeup.py")
d181 = load_module("derive181", REPO / "sim/post-layout-ro-ring5-assembled-181/derive.py")
dcomb = load_module("derive_combining", REPO / "sim/raw-bit-volume-campaign/derive-combining.py")

NOW = datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
SHA = "abc1234"


def fake_new_id(offset=0):
    """The rid `new_record_id` would mint for `offset`, with the clock pinned."""
    return f"20990101-0000{offset:02d}-{SHA}"


@contextmanager
def deterministic_ids():
    """Pin `new_record_id` for wakeup.py's emit legs (they import it from
    `evidence_record` at call time; the derive scripts get their own
    module-level patch instead)."""
    real = er.new_record_id
    er.new_record_id = lambda repo_root, offset=0: (NOW, SHA, fake_new_id(offset))
    try:
        yield
    finally:
        er.new_record_id = real


def fake_chunk(name, plan):
    """A minimal load_reqdir chunk: enough for `_jobs`/`_backend` and the
    `klt_sim` provenance keys the rec dicts read."""
    resp = {"environment": {"engine_version": "ngspice-46", "models_lib_sha256": "aa" * 16,
                            "remote": {"job_id": "j-1"}},
            "provenance": {"klt_version": "0.8.0"}}
    return (name, plan, resp)


def store_bundle(sb):
    """A `_store_chunks` stand-in that reserves `corners/<rid>/` with one file."""
    def store(rid, reqdir, mine):
        cdir = Path(sb) / "corners" / rid
        cdir.mkdir(parents=True)
        (cdir / "resp.klt-sim.json.gz").write_text("{}\n")
    return store


class CollisionSandbox(unittest.TestCase):
    """Temp-dir plumbing shared by the per-site cases."""

    def sandbox(self):
        sb = Path(tempfile.mkdtemp(prefix="collision-cleanup-"))
        self.addCleanup(shutil.rmtree, sb, True)
        return sb

    def seed_collision(self, records_dir, rid):
        """Partial-bundle state that makes `mint_record` refuse `rid`."""
        records_dir.mkdir(parents=True, exist_ok=True)
        (records_dir / f"{rid}.md").write_text("partial\n")
        return rid


class WakeUpDetCollision(CollisionSandbox):
    """emit_det: the rid == store_rid guard at the shared corners/{store_rid}/ bundle."""

    def _install(self, sb, supplies):
        w.HERE = sb
        w.REPO = sb
        w.make_requests = lambda: SimpleNamespace(TEMPS=[125.0], SUPPLIES=supplies)
        w.load_reqdir = lambda reqdir, leg: ([fake_chunk("det-p1", {"mode": "en"})], [])
        rows = [{"process": "tt", "mode": "en"}]
        summ = {"units": 1, "units_ok": 1, "t_settle_max_1pct_en_s": 1e-8,
                "t_settle_max_1pct_ramp_s": 2e-8}
        w.det_build = lambda chunks, temp, vdd: (rows, [], dict(summ))
        w.det_md = lambda *a, **k: (["# rid -- wake-up-transient"], "")
        w._store_chunks = store_bundle(sb)
        (sb / "reqdir").mkdir(parents=True, exist_ok=True)

    def test_later_collision_keeps_shared_bundle_and_published_records(self):
        # (A) collide on the 3rd det record: 1..2 are already published citing
        # the shared bundle minted under record 1, so it must survive.
        sb = self.sandbox()
        self._install(sb, [1.62, 1.80, 1.98])
        colliding = self.seed_collision(sb / "records", fake_new_id(3))
        with deterministic_ids():
            with self.assertRaises(SystemExit) as cm:
                w.emit_det(str(sb / "reqdir"))
        self.assertIn("already exists", str(cm.exception))
        store_rid = fake_new_id(1)
        # the shared bundle record 1 created (and 1..2 cite) is intact
        self.assertTrue((sb / "corners" / store_rid / "resp.klt-sim.json.gz").is_file())
        for off in (1, 2):
            rid = fake_new_id(off)
            self.assertTrue((sb / "records" / f"{rid}.md").is_file(), rid)
            self.assertTrue((sb / "records" / f"{rid}.json").is_file(), rid)
        self.assertEqual(json.loads((sb / "records" / f"{store_rid}.json").read_text())["corners_dir"],
                         store_rid)
        # the colliding invocation left nothing behind
        self.assertFalse((sb / "corners" / colliding).exists())
        self.assertEqual(sorted(p.name for p in (sb / "records").iterdir()),
                         sorted([f"{fake_new_id(1)}.md", f"{fake_new_id(1)}.json",
                                 f"{fake_new_id(2)}.md", f"{fake_new_id(2)}.json",
                                 f"{colliding}.md"]))
        self.assertFalse(any(p.name.startswith(f".{colliding}") for p in (sb / "records").iterdir()),
                         "stale reservation/staging file left behind")

    def test_store_record_collision_removes_its_own_bundle(self):
        # (B) collide on the store record itself (rid == store_rid): the bundle
        # is this invocation's own and nothing published cites it yet, so the
        # cleanup must remove it and leave nothing else.
        sb = self.sandbox()
        self._install(sb, [1.62])
        rid = self.seed_collision(sb / "records", fake_new_id(1))
        with deterministic_ids():
            with self.assertRaises(SystemExit):
                w.emit_det(str(sb / "reqdir"))
        self.assertFalse((sb / "corners" / rid).exists())
        self.assertEqual([p.name for p in (sb / "records").iterdir()], [f"{rid}.md"])


class WakeUpNoisyCollision(CollisionSandbox):
    """emit_noisy: every noisy record owns its corners/<rid>/ bundle."""

    def test_noisy_collision_removes_its_own_bundle(self):
        sb = self.sandbox()
        name = "tt-27-1v8"
        plan = {"point": name, "temp": 125.0, "vdd": 1.98, "process": "tt",
                "tmax": "50n", "na": 0.05, "ts_s": 1e-8, "ten_s": 1e-7}
        w.HERE = sb
        w.REPO = sb
        w.make_requests = lambda: SimpleNamespace(
            NOISY_POINTS=[(name, "tt", 125.0, 1.98, "nominal")])
        w.load_reqdir = lambda reqdir, leg: ([fake_chunk("noisy-p1", plan)], [])
        w.noisy_build = lambda chunks, p: (plan, [{"seed": "s1"}], [{"seed": "c1"}], {},
                                           {"n_ok": 2, "xcheck_inside": 1, "xcheck_total": 1,
                                            "control": 1})
        w.noisy_md = lambda *a, **k: (["# rid -- wake-up-transient"], "")
        w._store_chunks = store_bundle(sb)
        (sb / "reqdir").mkdir(parents=True)
        rid = self.seed_collision(sb / "records", fake_new_id(21))
        with deterministic_ids():
            with self.assertRaises(SystemExit):
                w.emit_noisy(str(sb / "reqdir"))
        self.assertFalse((sb / "corners" / rid).exists())
        self.assertEqual([p.name for p in (sb / "records").iterdir()], [f"{rid}.md"])


class Derive181Collision(CollisionSandbox):
    """derive.py: the reserved corners/<rid>/klt-sim.json bundle is its own."""

    ENV = {"remote": {"job_id": "j-1", "instance_type": "c5.xlarge", "lifecycle": "spot"},
           "engine_version": "ngspice-46", "models_lib_sha256": "aa" * 16,
           "netlist_sha256": "bb" * 16}

    @staticmethod
    def _resp(corner, vdd):
        m = {"tr1a": 1e-9, "tr1b": 2e-9, "tr2a": 1.1e-9, "tr2b": 2.2e-9,
             "tr3a": 1.2e-9, "tr3b": 2.4e-9, "tr4a": 1.3e-9, "tr4b": 2.6e-9,
             "tq1a": 0.5e-9, "tq1b": 1.5e-9, "tq2a": 0.6e-9, "tq2b": 1.7e-9,
             "tq3a": 0.7e-9, "tq3b": 1.9e-9, "tq4a": 0.8e-9, "tq4b": 2.1e-9,
             "vmaxr": 1.7, "vminr": 0.1, "vmaxrb": 1.6, "vminrb": 0.2,
             "vmaxq": 1.75, "vminq": 0.05, "vmaxqb": 1.65, "vminqb": 0.15,
             "ir1raw": -1e-4, "ir4raw": -9e-5, "iq1raw": -8e-5, "iq4raw": -7e-5}
        return {"process": corner, "status": "pass",
                "measurements": [{"name": k, "value": v} for k, v in m.items()],
                "diagnostics": []}

    def test_collision_removes_own_corner_bundle(self):
        sb = self.sandbox()
        reqdir = sb / "req"
        (reqdir / "p1").mkdir(parents=True)
        resp = {"status": "pass", "environment": self.ENV,
                "provenance": {"klt_version": "0.8.0"},
                "corners": [self._resp(c, 1.62) for c in ("tt", "ss", "ff")]}
        json.dump(resp, open(reqdir / "p1" / "resp.json", "w"))
        out = sb / "out"
        rid = self.seed_collision(out, fake_new_id(1))
        real = (d181.REPO, d181.new_record_id)
        d181.REPO = str(sb)
        d181.new_record_id = lambda repo_root, offset=0: (NOW, SHA, fake_new_id(offset))
        try:
            with self.assertRaises(SystemExit):
                d181.main(str(reqdir), str(out))
        finally:
            d181.REPO, d181.new_record_id = real
        cdir = sb / "sim" / "post-layout-ro-ring5-assembled-181" / "corners" / rid
        self.assertFalse(cdir.exists(), "reserved corner bundle left behind")
        self.assertEqual([p.name for p in out.iterdir()], [f"{rid}.md"])


class DeriveCombiningCollision(CollisionSandbox):
    """derive-combining.py: same rule for the ro-array-core-combining bundle."""

    ENV = Derive181Collision.ENV

    def test_collision_removes_own_corner_bundle(self):
        sb = self.sandbox()
        reqdir = sb / "req"
        (reqdir / "p1").mkdir(parents=True)
        m = {"t1a": 1e-9, "t1b": 2e-9, "t2a": 1.1e-9, "t2b": 2.2e-9,
             "t3a": 1.2e-9, "t3b": 2.4e-9, "t4a": 1.3e-9, "t4b": 2.6e-9,
             "vxo_max": 1.7, "vxo_min": 0.1, "vxo_avg": 0.9,
             "txo_a": 1e-9, "txo_b": 1.1e-6, "tt1a": 1e-9, "tt1b": 3e-9,
             "i1": -1e-4, "i2": -1e-4, "i3": -1e-4, "i4": -1e-4, "ib": -4e-4}
        resp = {"status": "pass", "environment": self.ENV,
                "provenance": {"klt_version": "0.8.0"},
                "corners": [{"process": "tt", "status": "pass",
                             "measurements": [{"name": k, "value": v} for k, v in m.items()],
                             "diagnostics": []}]}
        json.dump(resp, open(reqdir / "p1" / "resp.json", "w"))
        rdir = sb / "sim" / "ro-array-core-combining" / "records"
        rid = self.seed_collision(rdir, fake_new_id(1))
        real = (dcomb.REPO, dcomb.new_record_id)
        dcomb.REPO = str(sb)
        dcomb.new_record_id = lambda repo_root, offset=0: (NOW, SHA, fake_new_id(offset))
        try:
            with self.assertRaises(SystemExit):
                dcomb.main(str(reqdir), [(125.0, 1.98)])
        finally:
            dcomb.REPO, dcomb.new_record_id = real
        cdir = sb / "sim" / "ro-array-core-combining" / "corners" / rid
        self.assertFalse(cdir.exists(), "reserved corner bundle left behind")
        self.assertEqual([p.name for p in rdir.iterdir()], [f"{rid}.md"])


if __name__ == "__main__":
    unittest.main()
