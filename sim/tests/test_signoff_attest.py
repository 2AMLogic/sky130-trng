#!/usr/bin/env python3
"""Test for signoff/attest.py (issue #320): the artifact-anchored generic
envelopes cited for T1 items 1, 2, 9, 10.  Stdlib only.  Fixture trees hold
only the inventoried files, so no simulator, PDK or klt is needed."""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("attest", REPO / "signoff" / "attest.py")
attest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attest)


def run(root, *argv):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = attest.main(["--repo-root", str(root), *argv])
    return rc, err.getvalue()


def make_tree(dst):
    """Copy every inventoried file + the manifest + the committed attest dir;
    create the records/ dirs check_9 enumerates."""
    paths = {"signoff/block-manifest.json"}
    for key in attest.ROWS:
        inv = json.loads((REPO / f"signoff/attest/{key}.inventory.json").read_text())
        paths.update(m["path"] for m in inv["members"])
        paths.update([f"signoff/attest/{key}.json", f"signoff/attest/{key}.inventory.json"])
    paths.update(["design/sampler_core.spice", "layout/sampler_core/README.md"])
    for rel in paths:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst / rel)
    for p in (REPO / "sim").glob("*/records"):
        (dst / p.relative_to(REPO)).mkdir(parents=True, exist_ok=True)


class AttestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        make_tree(self.tmp)

    def test_committed_tree_is_consistent(self):
        rc, err = run(REPO, "--check")
        self.assertEqual(rc, 0, err)

    def test_envelope_pins_inventory_and_manifest_pins_envelope(self):
        manifest = json.loads((REPO / "signoff/block-manifest.json").read_text())["evidence"]
        for key, (item, _, _) in attest.ROWS.items():
            env = json.loads((REPO / f"signoff/attest/{key}.json").read_text())
            self.assertEqual((env["kind"], env["t1_item"]), ("generic", item))
            inv_rel = env["provenance"]["input"]["path"]
            self.assertEqual(env["provenance"]["input"]["content_hash"], attest.sha256_file(REPO / inv_rel))
            self.assertEqual(manifest[key], {"file": f"signoff/attest/{key}.json",
                                             "content_hash": env["provenance"]["input"]["content_hash"]})
            inv = json.loads((REPO / inv_rel).read_text())
            for m in inv["members"]:
                self.assertEqual(attest.sha256_file(REPO / m["path"]), m["sha256"], m["path"])

    def test_fixture_tree_checks_clean(self):
        rc, err = run(self.tmp, "--check")
        self.assertEqual(rc, 0, err)

    def test_negative_control_edited_inventoried_file_is_stale(self):
        for rel, key in (("digital/rtl/trng_digital.v", "1.digital"),
                         ("layout/sampler_core/sampler_core.gds", "2.analog")):
            with self.subTest(rel=rel):
                p = self.tmp / rel
                orig = p.read_bytes()
                p.write_bytes(orig + b"\n")
                rc, err = run(self.tmp, "--check", key)
                p.write_bytes(orig)
                self.assertEqual(rc, 1)
                self.assertIn("STALE", err)

    def test_stale_rtl_flips_digital_envelope_to_fail_on_write(self):
        (self.tmp / "digital/rtl/trng_digital.v").write_bytes(
            (self.tmp / "digital/rtl/trng_digital.v").read_bytes() + b"\n")
        run(self.tmp, "--write", "1.digital")
        env = json.loads((self.tmp / "signoff/attest/1.digital.json").read_text())
        self.assertEqual(env["status"], "fail")
        self.assertTrue(any("synthesis stale" in f for f in env["failures"]))

    def test_vanished_input_is_not_a_silent_shrink(self):
        (self.tmp / "digital/flow/place-and-route/tool-pins.json").unlink()
        files = attest.build(self.tmp, "1.digital")
        env = json.loads(files["signoff/attest/1.digital.json"])
        self.assertEqual(env["status"], "fail")
        self.assertTrue(any("matched no file" in f for f in env["failures"]))

    def test_manifest_pin_drift_is_stale(self):
        mp = self.tmp / "signoff/block-manifest.json"
        m = json.loads(mp.read_text())
        m["evidence"]["10"]["content_hash"] = "sha256:" + "0" * 64
        mp.write_text(json.dumps(m, indent=2) + "\n")
        rc, err = run(self.tmp, "--check", "10")
        self.assertEqual(rc, 1)
        self.assertIn("block-manifest.json", err)

    def test_analog_item_1_is_not_self_attested(self):
        self.assertNotIn("1.analog", attest.ROWS)


if __name__ == "__main__":
    unittest.main()
