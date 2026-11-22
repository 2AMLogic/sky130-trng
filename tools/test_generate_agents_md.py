#!/usr/bin/env python3
"""Unit tests for .loom/scripts/generate-agents-md.sh's {{INSTALL_DATE}}
substitution (issue #533). Stdlib only; every case stages its own
.loom/scripts/ + .loom/CLAUDE.md (+ optional .loom/install-metadata.json) in
a temp tree and never reads or writes the repo's live .loom/.

The pinned script is a local delta (PDR-0001 + #533, .loom/resync-ignore):
in this flattened install .loom/AGENTS.md is the already-substituted
artifact, so the generator must resolve the placeholder itself — the
recorded install_date from .loom/install-metadata.json, else today's date,
exactly mirroring resync-installed.sh's create_loom_agents_md_if_missing —
and must refuse (exit 3, nothing written) when any unknown placeholder
survives rendering, instead of quietly de-substituting checked-in lines.
"""
import datetime
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / ".loom" / "scripts" / "generate-agents-md.sh"

CLAUDE_MD = """# Loom

prose outside the markers must not reach AGENTS.md

<!-- agents-md:include:start -->
## Shared section

Included body line one.
<!-- agents-md:include:end -->

trailing prose
"""

META_DATE = "2020-02-29"


def stage(root, script_text=None, meta=None, claude=CLAUDE_MD, sentinel=None):
    """Build a hermetic .loom/ tree under *root* and return its paths.

    script_text -- replacement text for the generator copy (default: the
                   repo's pinned script verbatim); used to seed an unknown
                   placeholder for the negative control.
    meta        -- bytes for .loom/install-metadata.json, or None to omit
                   the file entirely.
    sentinel    -- when set, pre-seeds .loom/AGENTS.md with these bytes so a
                   test can prove a refused render left it byte-identical.
    """
    loom = root / ".loom"
    (loom / "scripts").mkdir(parents=True)
    (loom / "CLAUDE.md").write_text(claude)
    if meta is not None:
        (loom / "install-metadata.json").write_bytes(meta)
    script = loom / "scripts" / "generate-agents-md.sh"
    script.write_text(script_text if script_text is not None
                      else SCRIPT.read_text())
    os.chmod(script, 0o755)
    agents = loom / "AGENTS.md"
    if sentinel is not None:
        agents.write_bytes(sentinel)
    return script, agents


class T(unittest.TestCase):
    def run_gen(self, script, *args, cwd=None):
        return subprocess.run(
            [str(script), *args], capture_output=True, text=True,
            cwd=str(cwd or script.parent.parent))

    def test_stdout_substitutes_install_date_from_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            script, _ = stage(Path(d), meta=('{"install_date": "%s"}'
                                             % META_DATE).encode())
            r = self.run_gen(script, "--stdout")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("**Installation Date**: " + META_DATE, r.stdout)
            self.assertIn("Last updated: " + META_DATE, r.stdout)
            self.assertNotIn("{{", r.stdout)
            # The extracted body made it through; the outside prose did not.
            self.assertIn("Included body line one.", r.stdout)
            self.assertNotIn("prose outside the markers", r.stdout)

    def test_no_arg_write_substitutes_into_default_out(self):
        with tempfile.TemporaryDirectory() as d:
            script, agents = stage(Path(d), meta=('{"install_date": "%s"}'
                                                  % META_DATE).encode())
            r = self.run_gen(script)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(agents.is_file())
            text = agents.read_text()
            self.assertIn("**Installation Date**: " + META_DATE, text)
            self.assertIn("Last updated: " + META_DATE, text)
            self.assertNotIn("{{", text)

    def test_path_argument_matches_stdout_byte_for_byte(self):
        # One render path (#533 requirement 1): <path> and --stdout cannot
        # diverge. The metadata fixture pins the date so both runs are
        # deterministic.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            script, _ = stage(root, meta=('{"install_date": "%s"}'
                                          % META_DATE).encode())
            out = root / "nested" / "out.md"
            out.parent.mkdir()
            r1 = self.run_gen(script, str(out))
            r2 = self.run_gen(script, "--stdout")
            self.assertEqual(r1.returncode, 0, r1.stderr)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertEqual(out.read_bytes(), r2.stdout.encode())

    def test_metadata_absent_falls_back_to_today(self):
        with tempfile.TemporaryDirectory() as d:
            script, _ = stage(Path(d), meta=None)
            r = self.run_gen(script, "--stdout")
            self.assertEqual(r.returncode, 0, r.stderr)
            today = datetime.date.today().isoformat()
            self.assertIn("**Installation Date**: " + today, r.stdout)
            self.assertIn("Last updated: " + today, r.stdout)
            self.assertNotIn("{{", r.stdout)

    def test_metadata_without_install_date_key_falls_back_to_today(self):
        # A metadata file that lacks the key must fall back to today, not
        # substitute an empty string.
        with tempfile.TemporaryDirectory() as d:
            script, _ = stage(Path(d), meta=b'{"loom_version": "0.19"}')
            r = self.run_gen(script, "--stdout")
            self.assertEqual(r.returncode, 0, r.stderr)
            today = datetime.date.today().isoformat()
            self.assertIn("**Installation Date**: " + today, r.stdout)
            self.assertNotIn("{{", r.stdout)
            self.assertNotIn("**Installation Date**: \n", r.stdout)

    def test_unknown_placeholder_refuses_and_leaves_output_intact(self):
        # Negative control: seed the generator copy's HEADER with a
        # placeholder the substitution does not know. The run must exit
        # non-zero naming it on stderr and must NOT write or truncate the
        # pre-existing output (nor litter .tmp.* files beside it).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sentinel = b"PRE-EXISTING ARTIFACT\n"
            script, agents = stage(
                root,
                script_text=SCRIPT.read_text().replace(
                    "**Installation Date**: {{INSTALL_DATE}}",
                    "**Installation Date**: {{SOMETHING_ELSE}}"),
                meta=('{"install_date": "%s"}' % META_DATE).encode(),
                sentinel=sentinel)
            r = self.run_gen(script)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("{{SOMETHING_ELSE}}", r.stderr)
            self.assertEqual(agents.read_bytes(), sentinel)
            self.assertEqual(list((root / ".loom").glob("*.tmp.*")), [])

    def test_readonly_output_dir_fails_without_truncating(self):
        if os.geteuid() == 0:
            self.skipTest("chmod is not enforced for root")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sentinel = b"PRE-EXISTING ARTIFACT\n"
            script, agents = stage(
                root, meta=('{"install_date": "%s"}' % META_DATE).encode(),
                sentinel=sentinel)
            loom = root / ".loom"
            mode = loom.stat().st_mode
            os.chmod(loom, 0o500)
            try:
                r = self.run_gen(script)
            finally:
                os.chmod(loom, mode)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(agents.read_bytes(), sentinel)
            self.assertEqual(list(loom.glob("*.tmp.*")), [])


if __name__ == "__main__":
    unittest.main()
