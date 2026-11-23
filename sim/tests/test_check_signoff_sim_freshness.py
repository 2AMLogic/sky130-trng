#!/usr/bin/env python3
"""Test for sim/bin/check_signoff_sim_freshness.py (issue #285).
Builds throwaway fixture trees from the real cited record; stdlib only."""
import gzip
import json
import shutil
import subprocess
import tempfile
import sys
import os
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from loadmod import load_module  # noqa: E402
chk = load_module("chk", REPO / "sim" / "bin" / "check_signoff_sim_freshness.py")

SLUG = "sim/digital-sdf-timed-verification"
# Records are append-only evidence, so this one stays on disk even after the
# live citation is removed or moved on; it backs the fixtures in that case.
FALLBACK_RID = "20261009-172301-8cbd26a"
ITEM = chk.DEFAULT_ITEM


def live_rid(src):
    """Record id the manifest under src currently cites for ITEM, else None."""
    ev = json.loads((src / "signoff/block-manifest.json").read_text()).get("evidence", {})
    cite = ev.get(ITEM)
    cite = cite["file"] if isinstance(cite, dict) else cite
    return Path(cite).parts[3] if isinstance(cite, str) else None


RID = live_rid(REPO) or FALLBACK_RID

PEX_ITEM = "7.analog"
PEX_SLUG = "sim/pex-sampler-core"
PEX_EXEMPT_RID = "20261121-001303-7330672"
PEX_EXEMPT_REPORT = f"{PEX_SLUG}/runs/{PEX_EXEMPT_RID}/pex-report.json"
HARNESS_PIN = "sim/pex-sampler-core/harness/pex-measure.py"
HARNESS_EXEMPT_DIGEST = "sha256:ee46948b819ac1a7e50395d02bdf4523677dd5ae4c150fd11d0ac33748e119ca"
HARNESS_GATE = "sim/tests/test_pex_sampler_core.py::test_recorded_legs_match_every_delta"
PEX_FIXTURE_FILES = {
    chk.PEX_LAYOUT: b"original GDS\n",
    "design/sampler_core.spice": b"* synthetic sampler_core schematic\n",
    HARNESS_PIN: b"# synthetic PEX harness\n",
    "sim/pex-sampler-core/testbench/tb_sampler_core_body.spice": b"* synthetic body template\n",
    "sim/pex-sampler-core/net-aliases.json": b'{"ro1": "ro1_ext"}\n',
}


def make_pex_tree(dst, report=PEX_EXEMPT_REPORT, *, harness_digest=HARNESS_EXEMPT_DIGEST):
    """Build a self-consistent synthetic PEX fixture under dst independent of
    the live repository tree and manifest."""
    run = Path(report).parent
    files = dict(PEX_FIXTURE_FILES)
    files[f"{run.as_posix()}/pex/schematic-dut.flat.spice"] = b"* synthetic flat schematic\n"
    files[f"{run.as_posix()}/sampler_core.extracted.spice"] = b"* synthetic extracted netlist\n"
    hashes = {"_comment": ["synthetic PEX fixture"]}
    for rel, data in files.items():
        p = dst / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        hashes[rel] = chk.sha(data)
    if harness_digest is not None:
        hashes[HARNESS_PIN] = harness_digest
    gds_digest = hashes[chk.PEX_LAYOUT]
    (dst / run / "input-hashes.json").write_text(json.dumps(hashes))
    (dst / report).write_text(json.dumps({
        "status": "fail",
        "layout": {"scope": "repo", "path": chk.PEX_LAYOUT},
        "provenance": {"input": {"role": "layout", "content_hash": gds_digest}},
    }))
    (dst / "signoff").mkdir(exist_ok=True)
    (dst / "signoff/block-manifest.json").write_text(json.dumps(
        {"evidence": {PEX_ITEM: {"file": report,
                                 "content_hash": gds_digest}}}))
    return run


def make_tree(dst, src=REPO, rid=None):
    """Copy the record + every repo file it pins from src into dst.  The record
    is the one src's manifest cites (so a legitimate new citation just works),
    falling back to the historical record when nothing is cited."""
    rid = rid or live_rid(src) or FALLBACK_RID
    run = Path(SLUG) / "runs" / rid
    rel = [run / "input-hashes.json", run / "timed-declared.report.json", Path(SLUG) / "records" / f"{rid}.json",
           run / "trng_digital.baseline.sdf.gz", run / chk.ORACLE_FILE]
    hashes = json.loads((src / run / "input-hashes.json").read_text())
    rel += [Path(k) for k in hashes if "(" not in k and not k.startswith("$")]
    rel += [p.relative_to(src) for p in (src / chk.MODEL_DIR).glob("*.py")]
    for r in rel:
        (dst / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / r, dst / r)
    (dst / "signoff").mkdir()
    write_manifest(dst, f"{run}/timed-declared.report.json")


def write_manifest(root, cite):
    (root / "signoff/block-manifest.json").write_text(
        json.dumps({"evidence": {ITEM: {"file": cite}}}))


class PexFreshness(unittest.TestCase):
    def run_chk(self, root):
        return chk.check(root, root / "signoff/block-manifest.json", PEX_ITEM)

    def test_failing_report_checks_its_own_layout_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_pex_tree(root, f"{PEX_SLUG}/runs/fixture/pex-report.json", harness_digest=None)
            manifest = root / "signoff/block-manifest.json"
            cite = f"{run.as_posix()}/pex-report.json"
            self.assertEqual(self.run_chk(root)[0], [])

            gds = root / chk.PEX_LAYOUT
            gds.write_bytes(b"regenerated GDS")
            problems, _ = self.run_chk(root)
            self.assertIn(f"DRIFT {chk.PEX_LAYOUT}", problems[0])
            ev = {"file": cite, "content_hash": chk.sha(gds.read_bytes())}
            manifest.write_text(json.dumps({"evidence": {PEX_ITEM: ev}}))
            problems, _ = self.run_chk(root)
            self.assertTrue(any("differs from PEX input" in p for p in problems))
            self.assertTrue(any("DRIFT" in p for p in problems))

    def test_real_cited_pex_run_passes(self):
        manifest = REPO / "signoff/block-manifest.json"
        problems, notes = chk.check(REPO, manifest, PEX_ITEM)
        self.assertEqual(problems, [])
        located = chk.locate(REPO, manifest, PEX_ITEM)
        if located is None:
            self.assertTrue(any("no active evidence" in n for n in notes))
            return
        _, report, _, hashes_path, _ = located
        digest = json.loads(hashes_path.read_text())[HARNESS_PIN]
        self.assertEqual(any(HARNESS_PIN in n and HARNESS_GATE in n for n in notes),
                         report == REPO / PEX_EXEMPT_REPORT and digest == HARNESS_EXEMPT_DIGEST,
                         notes)

    def test_removed_citation_is_no_active_evidence(self):
        """Recovery path: withdrawing evidence['7.analog'] and editing sources passes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_pex_tree(root)
            (root / "signoff/block-manifest.json").write_text(json.dumps({"evidence": {}}))
            (root / "design/sampler_core.spice").write_bytes(b"* edited after withdrawal\n")
            problems, notes = self.run_chk(root)
            self.assertEqual(problems, [])
            self.assertTrue(any("no active evidence" in n for n in notes), notes)
            self.assertEqual(chk.main(["--repo-root", str(root), "--item", PEX_ITEM]), 0)

    def test_drifted_non_layout_pins_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_pex_tree(root)
            for rel in ["design/sampler_core.spice",
                        "sim/pex-sampler-core/testbench/tb_sampler_core_body.spice",
                        "sim/pex-sampler-core/net-aliases.json",
                        f"{run.as_posix()}/pex/schematic-dut.flat.spice",
                        f"{run.as_posix()}/sampler_core.extracted.spice"]:
                with self.subTest(rel):
                    p = root / rel
                    orig = p.read_bytes()
                    p.write_bytes(orig + b"\n* drift\n")
                    problems, _ = self.run_chk(root)
                    self.assertTrue(any(f"DRIFT {rel}" in p for p in problems), problems)
                    p.write_bytes(orig)
            self.assertEqual(self.run_chk(root)[0], [])

    def test_missing_pin_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_pex_tree(root)
            (root / "sim/pex-sampler-core/net-aliases.json").unlink()
            problems, _ = self.run_chk(root)
            self.assertTrue(any("net-aliases.json: cannot read" in p for p in problems), problems)

    def test_incomplete_pin_set_fails(self):
        """Empty pin objects and individually removed required pins must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_pex_tree(root)
            hashes_path = root / run / "input-hashes.json"
            orig_hashes = json.loads(hashes_path.read_text())

            hashes_path.write_text(json.dumps({}))
            problems, _ = self.run_chk(root)
            for key in chk.PEX_REQUIRED_FILES:
                self.assertTrue(any(f"mandatory pin missing: {key}" in p for p in problems), problems)

            for key in chk.PEX_REQUIRED_FILES:
                with self.subTest(missing=key):
                    trimmed = dict(orig_hashes)
                    trimmed.pop(key)
                    hashes_path.write_text(json.dumps(trimmed))
                    p = root / key
                    orig = p.read_bytes()
                    p.write_bytes(orig + b"\n* drift\n")
                    try:
                        problems, _ = self.run_chk(root)
                    finally:
                        p.write_bytes(orig)
                        hashes_path.write_text(json.dumps(orig_hashes))
                    self.assertTrue(any(f"mandatory pin missing: {key}" in m for m in problems), problems)

    def test_malformed_exempt_digest_fails(self):
        """Malformed digests (including trailing newlines) must fail even on the exempt pin."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_pex_tree(root)
            hashes_path = root / run / "input-hashes.json"
            orig_hashes = json.loads(hashes_path.read_text())
            for bad in [HARNESS_EXEMPT_DIGEST + "\n", "sha256:abc", 5, "sha256:" + "G" * 64]:
                with self.subTest(bad=bad):
                    edited = dict(orig_hashes)
                    edited[HARNESS_PIN] = bad
                    hashes_path.write_text(json.dumps(edited))
                    problems, notes = self.run_chk(root)
                    self.assertTrue(
                        any(f"malformed digest for {HARNESS_PIN}" in p for p in problems),
                        problems,
                    )
                    self.assertFalse(any(HARNESS_PIN in n for n in notes), notes)

    def test_drifted_harness_pin_passes_with_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_pex_tree(root)
            h = root / HARNESS_PIN
            h.write_bytes(h.read_bytes() + b"\n# drift\n")
            problems, notes = self.run_chk(root)
            self.assertEqual(problems, [])
            self.assertTrue(any(HARNESS_PIN in n and HARNESS_GATE in n for n in notes), notes)

            # A different valid digest on the same run is not covered by the exemption.
            hashes_path = root / run / "input-hashes.json"
            edited = json.loads(hashes_path.read_text())
            edited[HARNESS_PIN] = "sha256:" + "1" * 64
            hashes_path.write_text(json.dumps(edited))
            problems, notes = self.run_chk(root)
            self.assertTrue(any(f"DRIFT {HARNESS_PIN}" in p for p in problems), problems)
            self.assertFalse(any(HARNESS_PIN in n for n in notes), notes)

    def test_second_run_harness_drift_fails(self):
        """A later PEX run is not covered by the historical run's replay exemption."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = make_pex_tree(root, f"{PEX_SLUG}/runs/20270101-000000-second/pex-report.json",
                                harness_digest=None)
            problems, notes = self.run_chk(root)
            self.assertEqual(problems, [])
            self.assertFalse(any(HARNESS_PIN in n for n in notes), notes)

            h = root / HARNESS_PIN
            h.write_bytes(h.read_bytes() + b"\n# drift\n")
            problems, notes = self.run_chk(root)
            self.assertTrue(any(f"DRIFT {HARNESS_PIN}" in p for p in problems), problems)
            self.assertFalse(any(HARNESS_PIN in n for n in notes), notes)

            # Even recording the historical exempt digest on a second run must fail.
            hashes_path = root / run / "input-hashes.json"
            edited = json.loads(hashes_path.read_text())
            edited[HARNESS_PIN] = HARNESS_EXEMPT_DIGEST
            hashes_path.write_text(json.dumps(edited))
            problems, notes = self.run_chk(root)
            self.assertTrue(any(f"DRIFT {HARNESS_PIN}" in p for p in problems), problems)
            self.assertFalse(any(HARNESS_PIN in n for n in notes), notes)

    def test_unreplayed_reports_with_historical_run_id_fail_harness_drift(self):
        for report in (f"sim/pex-repeat/runs/{PEX_EXEMPT_RID}/pex-report.json",
                       f"{PEX_SLUG}/runs/{PEX_EXEMPT_RID}/other-report.json"):
            with self.subTest(report=report), tempfile.TemporaryDirectory() as tmp:
                make_pex_tree(Path(tmp), report)
                result = subprocess.run([sys.executable, chk.__file__, "--repo-root", tmp,
                                         "--item", PEX_ITEM], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f"DRIFT {HARNESS_PIN}", result.stderr)
                self.assertNotIn(HARNESS_GATE, result.stdout)

    def test_harness_exemption_is_exact(self):
        """Widening the exemption must stay an explicit, reviewed edit."""
        self.assertEqual(
            set(chk.PEX_PIN_EXEMPTIONS),
            {(PEX_EXEMPT_REPORT, HARNESS_PIN, HARNESS_EXEMPT_DIGEST)},
        )
        (reason,) = chk.PEX_PIN_EXEMPTIONS.values()
        self.assertIn(HARNESS_GATE, reason)

    def test_widened_exemption_does_not_cover_the_harness(self):
        """The exemption is keyed by exact (report, pin, digest), never by prefix or glob."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_pex_tree(root)
            h = root / HARNESS_PIN
            h.write_bytes(h.read_bytes() + b"\n# drift\n")
            saved = chk.PEX_PIN_EXEMPTIONS
            chk.PEX_PIN_EXEMPTIONS = {
                (PEX_EXEMPT_REPORT, f"{PEX_SLUG}/harness/", HARNESS_EXEMPT_DIGEST): HARNESS_GATE,
            }
            try:
                problems, _ = self.run_chk(root)
            finally:
                chk.PEX_PIN_EXEMPTIONS = saved
            self.assertTrue(any(f"DRIFT {HARNESS_PIN}" in p for p in problems), problems)


class Freshness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_tree(self.root)
        self.addCleanup(self.tmp.cleanup)

    def run_chk(self):
        return chk.check(self.root, self.root / "signoff/block-manifest.json")

    def hashes_path(self, rid=RID):
        return self.root / SLUG / "runs" / rid / "input-hashes.json"

    def edit_hashes(self, fn):
        p = self.hashes_path()
        h = json.loads(p.read_text())
        fn(h)
        p.write_text(json.dumps(h))
        # keep the record association consistent so only the edit under test fails
        rp = self.root / SLUG / "records" / f"{RID}.json"
        r = json.loads(rp.read_text())
        r["input_hashes"] = h
        rp.write_text(json.dumps(r))

    def assert_fails(self, needle):
        problems, _ = self.run_chk()
        self.assertTrue(any(needle in p for p in problems), problems)

    def test_real_cited_record_passes(self):
        problems, notes = chk.check(REPO, REPO / "signoff/block-manifest.json")
        self.assertEqual(problems, [])
        if live_rid(REPO) is None:
            self.assertTrue(any("no active evidence" in n for n in notes))
        else:
            self.assertTrue(any("external" in n for n in notes))
            self.assertTrue(any("not retained" in n for n in notes))

    def test_fixture_passes(self):
        self.assertEqual(self.run_chk()[0], [])

    def test_changed_inputs_drift(self):
        for rel in ["layout/trng_digital/trng_digital.routed.v", "digital/model/health.py",
                    "digital/tb/cocotb/test_trng_digital_fv.py",
                    "sim/digital-rtl-equivalence/harness/rtl-cosim.py"]:
            with self.subTest(rel):
                p = self.root / rel
                orig = p.read_bytes()
                p.write_bytes(orig + b"\n# drift\n")
                self.assert_fails(f"DRIFT {rel}")
                p.write_bytes(orig)
        self.assertEqual(self.run_chk()[0], [])

    def test_changed_sdf_drift(self):
        p = self.root / "layout/trng_digital/trng_digital.sdf.gz"
        p.write_bytes(gzip.compress(b"(DELAYFILE changed)"))
        self.assert_fails("DRIFT layout/trng_digital/trng_digital.sdf.gz")
        self.assert_fails("DRIFT layout/trng_digital/trng_digital.sdf (decompressed)")

    def test_record_local_drift(self):
        (self.root / SLUG / "runs" / RID / chk.ORACLE_FILE).write_text("tampered")
        self.assert_fails(f"DRIFT {chk.ORACLE_KEY}")

    def test_missing_file(self):
        (self.root / "layout/trng_digital/sta.json").unlink()
        self.assert_fails("layout/trng_digital/sta.json: cannot read")

    def test_new_unpinned_model_file(self):
        (self.root / "digital/model/extra.py").write_text("x = 1\n")
        self.assert_fails("mandatory pin missing: digital/model/extra.py")

    def test_study_only_model_needs_no_pin(self):
        (self.root / "digital/model/lagcount.py").write_text("x = 1\n")
        self.assertEqual(self.run_chk()[0], [])

    def test_study_only_exclusion_is_exact(self):
        self.assertEqual(chk.STUDY_ONLY_MODELS, {"lagcount.py"})
        (self.root / "digital/model/lagcount_v2.py").write_text("x = 1\n")
        self.assert_fails("mandatory pin missing: digital/model/lagcount_v2.py")

    def test_removed_mandatory_pin(self):
        for key in ["layout/trng_digital/trng_digital.sdf.gz", "digital/model/params.py",
                    "$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/primitives.v", chk.ORACLE_KEY]:
            with self.subTest(key):
                self.setUp()
                self.edit_hashes(lambda h: h.pop(key))
                self.assert_fails(f"mandatory pin missing: {key}")

    def test_malformed_digest(self):
        for bad in ["sha256:abc", "md5:" + "0" * 32, 5, "sha256:" + "G" * 64,
                    "sha256:" + "0" * 64 + "\n"]:
            with self.subTest(bad):
                self.edit_hashes(lambda h: h.update({"layout/trng_digital/sta.json": bad}))
                self.assert_fails("malformed digest for layout/trng_digital/sta.json")

    def test_unknown_pin_rejected(self):
        self.edit_hashes(lambda h: h.update({"surprise (thing)": "sha256:" + "0" * 64}))
        self.assert_fails("outside the declared input contract")

    def test_stale_citation_record_association(self):
        # record json no longer matches the run's input-hashes.json
        rp = self.root / SLUG / "records" / f"{RID}.json"
        r = json.loads(rp.read_text())
        r["input_hashes"]["layout/trng_digital/sta.json"] = "sha256:" + "1" * 64
        rp.write_text(json.dumps(r))
        self.assert_fails("record input_hashes differ")
        # record missing entirely
        rp.unlink()
        self.assert_fails("no matching record")

    def test_manifest_citation_is_followed(self):
        """Citing a second record makes the checker validate that record's pins."""
        rid2 = "20270101-000000-fixture"
        src, dst = self.root / SLUG / "runs" / RID, self.root / SLUG / "runs" / rid2
        shutil.copytree(src, dst)
        rec = json.loads((self.root / SLUG / "records" / f"{RID}.json").read_text())
        rec["record_id"] = rid2
        (self.root / SLUG / "records" / f"{rid2}.json").write_text(json.dumps(rec))
        write_manifest(self.root, f"{SLUG}/runs/{rid2}/timed-declared.report.json")
        self.assertEqual(self.run_chk()[0], [])
        # drift visible only in the second record's pins; the first stays untouched
        p2 = dst / "input-hashes.json"
        h = json.loads(p2.read_text())
        h["layout/trng_digital/sta.json"] = "sha256:" + "2" * 64
        p2.write_text(json.dumps(h))
        problems, _ = self.run_chk()
        self.assertTrue(any(rid2 in p and "DRIFT layout/trng_digital/sta.json" in p for p in problems), problems)
        write_manifest(self.root, f"{SLUG}/runs/{RID}/timed-declared.report.json")
        self.assertEqual(self.run_chk()[0], [])

    def test_removed_citation_is_no_active_evidence(self):
        """Recovery path: dropping evidence['7.digital'] must go green, not Usage."""
        (self.root / "signoff/block-manifest.json").write_text(json.dumps({"evidence": {}}))
        problems, notes = self.run_chk()
        self.assertEqual(problems, [])
        self.assertTrue(any("no active evidence" in n for n in notes), notes)
        self.assertEqual(chk.main(["--repo-root", str(self.root)]), 0)
        (self.root / "signoff/block-manifest.json").write_text(json.dumps({}))
        self.assertEqual(self.run_chk()[0], [])

    def test_malformed_present_citation_still_rejected(self):
        for bad in [None, 5, [], ["a", "b"], {"file": 3}]:
            with self.subTest(bad):
                (self.root / "signoff/block-manifest.json").write_text(
                    json.dumps({"evidence": {ITEM: bad}}))
                with self.assertRaises(chk.Usage):
                    self.run_chk()

    def test_fixtures_follow_a_changed_live_citation(self):
        """A legitimate new record/citation must not break fixture setup."""
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            live, fx = Path(t1), Path(t2)
            make_tree(live)
            rid2 = "20270101-000000-newlive"
            shutil.copytree(live / SLUG / "runs" / RID, live / SLUG / "runs" / rid2)
            rec = json.loads((live / SLUG / "records" / f"{RID}.json").read_text())
            rec["record_id"] = rid2
            (live / SLUG / "records" / f"{rid2}.json").write_text(json.dumps(rec))
            write_manifest(live, f"{SLUG}/runs/{rid2}/timed-declared.report.json")
            make_tree(fx, src=live)
            self.assertEqual(live_rid(fx), rid2)
            self.assertEqual(chk.check(fx, fx / "signoff/block-manifest.json")[0], [])

    def test_fixtures_independent_of_removed_live_citation(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            live, fx = Path(t1), Path(t2)
            make_tree(live)
            (live / "signoff/block-manifest.json").write_text(json.dumps({"evidence": {}}))
            make_tree(fx, src=live)
            self.assertEqual(chk.check(fx, fx / "signoff/block-manifest.json")[0], [])

    def test_bad_citation_is_usage_error(self):
        write_manifest(self.root, "somewhere/else/report.json")
        with self.assertRaises(chk.Usage):
            self.run_chk()


if __name__ == "__main__":
    unittest.main()
