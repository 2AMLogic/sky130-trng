#!/usr/bin/env python3
"""Test for sim/bin/check_signoff_sim_freshness.py (issue #285).
Builds throwaway fixture trees from the real cited record; stdlib only."""
import gzip
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("chk", REPO / "sim" / "bin" / "check_signoff_sim_freshness.py")
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)

SLUG = "sim/digital-sdf-timed-verification"
RID = "20261009-172301-8cbd26a"
ITEM = chk.DEFAULT_ITEM


def make_tree(dst):
    """Copy the cited record + every repo file it pins into dst."""
    real = json.loads((REPO / "signoff/block-manifest.json").read_text())
    cite = real["evidence"][ITEM]
    cite = cite["file"] if isinstance(cite, dict) else cite
    assert RID in cite, "cited record changed; update RID"
    run = Path(SLUG) / "runs" / RID
    rel = [run / "input-hashes.json", run / "timed-declared.report.json", Path(SLUG) / "records" / f"{RID}.json",
           run / "trng_digital.baseline.sdf.gz", run / chk.ORACLE_FILE]
    hashes = json.loads((REPO / run / "input-hashes.json").read_text())
    rel += [Path(k) for k in hashes if "(" not in k and not k.startswith("$")]
    rel += [p.relative_to(REPO) for p in (REPO / chk.MODEL_DIR).glob("*.py")]
    for r in rel:
        (dst / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / r, dst / r)
    (dst / "signoff").mkdir()
    write_manifest(dst, f"{run}/timed-declared.report.json")


def write_manifest(root, cite):
    (root / "signoff/block-manifest.json").write_text(
        json.dumps({"evidence": {ITEM: {"file": cite}}}))


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

    def test_removed_mandatory_pin(self):
        for key in ["layout/trng_digital/trng_digital.sdf.gz", "digital/model/params.py",
                    "$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/primitives.v", chk.ORACLE_KEY]:
            with self.subTest(key):
                self.setUp()
                self.edit_hashes(lambda h: h.pop(key))
                self.assert_fails(f"mandatory pin missing: {key}")

    def test_malformed_digest(self):
        for bad in ["sha256:abc", "md5:" + "0" * 32, 5, "sha256:" + "G" * 64]:
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

    def test_bad_citation_is_usage_error(self):
        write_manifest(self.root, "somewhere/else/report.json")
        with self.assertRaises(chk.Usage):
            self.run_chk()


if __name__ == "__main__":
    unittest.main()
