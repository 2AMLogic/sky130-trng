#!/usr/bin/env python3
"""Test for signoff/attest.py (issues #320, #697): the artifact-anchored generic
envelopes cited for T1 items 1, 2, 9, 10, the PR-time vs main-time item-9 split
(DR-0021), stale-count guard, and which-SHA sync_main state machine.  Stdlib +
git only; fixture trees hold only the inventoried files, so no simulator, PDK
or klt is needed."""
import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from loadmod import load_module  # noqa: E402
attest = load_module("attest", REPO / "signoff" / "attest.py")


def run(root, *argv):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = attest.main(["--repo-root", str(root), *argv])
    return rc, err.getvalue()


def make_tree(dst, *, normalize_item9=True):
    """Copy every inventoried file (both committed and currently selector-matched)
    + the manifest + the committed attest dir + t1-report.json; create the
    records/ dirs check_9 enumerates.  When normalize_item9 is True (default for
    unit-test fixtures), regenerate item 9 inside `dst` so fixtures start from
    a clean main-equivalent state even when run on a PR branch where item 9 is
    intentionally un-regenerated (DR-0021)."""
    paths = {"signoff/block-manifest.json", "signoff/t1-report.json"}
    for key in attest.ROWS:
        inv = json.loads((REPO / f"signoff/attest/{key}.inventory.json").read_text())
        paths.update(m["path"] for m in inv["members"])
        matched, _ = attest.resolve(REPO, attest.SELECTORS[key])
        paths.update(matched)
        paths.update([f"signoff/attest/{key}.json", f"signoff/attest/{key}.inventory.json"])
    paths.update(["design/sampler_core.spice", "layout/sampler_core/README.md"])
    for rel in paths:
        src = REPO / rel
        if src.is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst / rel)
    for p in (REPO / "sim").glob("*/records"):
        (dst / p.relative_to(REPO)).mkdir(parents=True, exist_ok=True)
    if normalize_item9:
        run(dst, "--write", "9")


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=check,
    )


def _init_git_repo(path, *, initial_message="initial fixture"):
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test Author")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", initial_message)
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def _fake_render_report(root, out_path):
    """Deterministic report renderer for unit tests (no klt wheel required):
    fingerprints block-manifest.json + 9.json + 9.inventory.json."""
    root = Path(root)
    payload = {
        "fake_klt_signoff": True,
        "manifest_sha256": attest.sha256_file(root / "signoff/block-manifest.json"),
        "item9_envelope_sha256": attest.sha256_file(root / "signoff/attest/9.json"),
        "item9_inventory_sha256": attest.sha256_file(root / "signoff/attest/9.inventory.json"),
    }
    Path(out_path).write_text(json.dumps(payload, indent=2) + "\n")


def imported_modules(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


HELPER_DIRS = ("layout/bin", "design")


def helper_candidates(root):
    """Importable .py modules under the helper dirs, keyed by stem, discovered
    from the repository tree -- never from a selector or an inventory -- so
    removing a selector and regenerating cannot shrink the closure the test
    asserts (issue #650)."""
    cands = {}
    for d in HELPER_DIRS:
        for p in (root / d).glob("*.py"):
            cands.setdefault(p.stem, []).append(p.relative_to(root).as_posix())
    return cands


def helper_closure(root, scripts):
    """The helper-dir modules `scripts` import, followed through those modules' own imports."""
    cands = helper_candidates(root)
    closure, queue = set(), list(scripts)
    while queue:
        for name in imported_modules(root / queue.pop()) & set(cands):
            for tgt in cands[name]:
                if tgt not in closure:
                    closure.add(tgt)
                    queue.append(tgt)
    return closure


class AttestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._template = Path(tempfile.mkdtemp())
        make_tree(cls._template)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._template, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(self._template, self.tmp, dirs_exist_ok=True)

    def test_committed_tree_is_consistent(self):
        # PR-time gate on the live repo: strict byte-match for items 1/2/10,
        # fresh build(REPO, "9") pass + committed chain self-consistency for item 9.
        rc, err = run(REPO, "--check-pr")
        self.assertEqual(rc, 0, err)
        # Full-tree logic against the regenerated tree (self.tmp normalized item 9):
        rc2, err2 = run(self.tmp, "--check")
        self.assertEqual(rc2, 0, err2)
        inv9 = json.loads((self.tmp / "signoff/attest/9.inventory.json").read_text())
        self.assertEqual(inv9["member_count"], len(inv9["members"]))
        for m in inv9["members"]:
            self.assertEqual(attest.sha256_file(REPO / m["path"]), m["sha256"], m["path"])

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
            self.assertEqual(inv["member_count"], len(inv["members"]), key)
            if key not in attest.PR_DEFERRED_KEYS:
                for m in inv["members"]:
                    self.assertEqual(attest.sha256_file(REPO / m["path"]), m["sha256"], m["path"])
            else:
                fresh = attest.build(REPO, key)
                fresh_env = json.loads(fresh[f"signoff/attest/{key}.json"])
                fresh_inv = json.loads(fresh[f"signoff/attest/{key}.inventory.json"])
                self.assertEqual(fresh_env["status"], "pass", fresh_env.get("failures"))
                self.assertEqual(fresh_inv["member_count"], len(fresh_inv["members"]))
                for m in fresh_inv["members"]:
                    self.assertEqual(attest.sha256_file(REPO / m["path"]), m["sha256"], m["path"])

    def test_fixture_tree_checks_clean(self):
        rc, err = run(self.tmp, "--check")
        self.assertEqual(rc, 0, err)

    def test_each_inventory_pins_the_helper_import_closure_of_its_members(self):
        # Compute pinned members from a fresh build(REPO, key) so a PR adding a
        # new sim/*/*.py that imports an unpinned helper fails at PR time even
        # though item 9 is not regenerated on PR branches (DR-0021).
        for key in attest.ROWS:
            with self.subTest(key=key):
                fresh = attest.build(REPO, key)
                inv = json.loads(fresh[f"signoff/attest/{key}.inventory.json"])
                pinned = {m["path"] for m in inv["members"]}
                closure = helper_closure(REPO, {p for p in pinned if p.endswith(".py")})
                self.assertEqual(closure - pinned, set(), key)

    def test_negative_control_edited_inventoried_file_is_stale(self):
        for rel, key in (("digital/rtl/trng_digital.v", "1.digital"),
                         ("layout/sampler_core/sampler_core.gds", "2.analog"),
                         ("layout/bin/_hashing.py", "9"),
                         ("layout/bin/_klt_common.py", "9"),
                         ("layout/bin/_pex_rewrite.py", "9"),
                         ("design/_pdk_search.py", "9"),
                         ("layout/bin/_klt_common.py", "2.analog"),
                         ("layout/bin/_hashing.py", "2.digital"),
                         ("layout/bin/_klt_common.py", "2.digital")):
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

    # ------------------------------------------------- DR-0021 / issue #697

    def test_pr_check_allows_unregenerated_item9_and_rejects_items_1_2_10(self):
        # Adding a sim/*/*.py without regenerating item 9 passes --check-pr,
        # while strict --check flags item 9 STALE.
        new_script = self.tmp / "sim/synthetic-pr/new_script.py"
        new_script.parent.mkdir(parents=True, exist_ok=True)
        new_script.write_text("# synthetic testbench helper\n")
        rc_pr, err_pr = run(self.tmp, "--check-pr")
        self.assertEqual(rc_pr, 0, err_pr)
        rc_strict, err_strict = run(self.tmp, "--check", "9")
        self.assertEqual(rc_strict, 1)
        self.assertIn("STALE", err_strict)

        # Negative controls: edits to inventoried files for items 1.digital,
        # 2.analog, 2.digital, and 10 MUST still fail --check-pr.
        for rel, key in (
            ("digital/rtl/trng_digital.v", "1.digital"),
            ("layout/sampler_core/sampler_core.gds", "2.analog"),
            ("layout/trng_digital/trng_digital.gds", "2.digital"),
            ("README.md", "10"),
        ):
            with self.subTest(rel=rel, key=key):
                p = self.tmp / rel
                orig = p.read_bytes()
                p.write_bytes(orig + b"\n")
                rc, err = run(self.tmp, "--check-pr")
                p.write_bytes(orig)
                self.assertEqual(rc, 1)
                self.assertIn("STALE", err)
                self.assertIn(key, err)

    def test_pr_check_negative_control_check9_failure(self):
        # A sim/<family>/records dir with no committed testbench/harness/script
        # MUST fail --check-pr even though item-9 committed bytes are deferred.
        (self.tmp / "sim/orphan-family/records").mkdir(parents=True, exist_ok=True)
        rc, err = run(self.tmp, "--check-pr")
        self.assertEqual(rc, 1)
        self.assertIn("orphan-family", err)

        # Clean up orphan family and verify pdk.json mismatch also fails --check-pr.
        shutil.rmtree(self.tmp / "sim/orphan-family")
        pdk_path = self.tmp / "sim/pdk.json"
        orig_pdk = pdk_path.read_text()
        pdk = json.loads(orig_pdk)
        pdk["open_pdks_commit"] = "0" * 40
        pdk_path.write_text(json.dumps(pdk, indent=2) + "\n")
        rc2, err2 = run(self.tmp, "--check-pr")
        pdk_path.write_text(orig_pdk)
        self.assertEqual(rc2, 1)
        self.assertIn("open_pdks_commit", err2)

    def test_stale_count_guard_champion_scenario(self):
        # Reproduce Champion's clean git merge-file scenario: two branches each
        # add a distinct member to 9.inventory.json and bump member_count from
        # N to N+1.  git merge-file exits 0 cleanly with N+2 members and stored
        # member_count == N+1.  Both --check-pr and --check MUST fail.
        inv_path = self.tmp / "signoff/attest/9.inventory.json"
        base_text = inv_path.read_text()
        base_inv = json.loads(base_text)
        base_count = base_inv["member_count"]

        side_a_dir = self.tmp / "_side_a"
        side_b_dir = self.tmp / "_side_b"
        shutil.copytree(self.tmp, side_a_dir, ignore=shutil.ignore_patterns("_side_*"))
        shutil.copytree(self.tmp, side_b_dir, ignore=shutil.ignore_patterns("_side_*"))

        # Pick two paths that sort far apart in members[] so git merge-file
        # merges cleanly with exit 0 (non-adjacent hunks).
        a_file = side_a_dir / "sim/aaa-branch/tool_a.py"
        a_file.parent.mkdir(parents=True, exist_ok=True)
        a_file.write_text("# branch A\n")
        run(side_a_dir, "--write", "9")

        b_file = side_b_dir / "sim/zzz-branch/tool_b.py"
        b_file.parent.mkdir(parents=True, exist_ok=True)
        b_file.write_text("# branch B\n")
        run(side_b_dir, "--write", "9")

        merged_inv_path = self.tmp / "_merged_9.inventory.json"
        base_inv_file = self.tmp / "_base_9.inventory.json"
        base_inv_file.write_text(base_text)
        shutil.copy2(side_a_dir / "signoff/attest/9.inventory.json", merged_inv_path)
        res = subprocess.run(
            [
                "git", "merge-file",
                str(merged_inv_path),
                str(base_inv_file),
                str(side_b_dir / "signoff/attest/9.inventory.json"),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)

        merged_inv = json.loads(merged_inv_path.read_text())
        self.assertEqual(len(merged_inv["members"]), base_count + 2)
        self.assertEqual(merged_inv["member_count"], base_count + 1)

        # Install the merged inventory and both scripts into self.tmp (without
        # regenerating) and clean up scratch dirs.
        shutil.rmtree(side_a_dir)
        shutil.rmtree(side_b_dir)
        base_inv_file.unlink()
        (self.tmp / "sim/aaa-branch").mkdir(parents=True, exist_ok=True)
        (self.tmp / "sim/aaa-branch/tool_a.py").write_text("# branch A\n")
        (self.tmp / "sim/zzz-branch").mkdir(parents=True, exist_ok=True)
        (self.tmp / "sim/zzz-branch/tool_b.py").write_text("# branch B\n")
        shutil.move(str(merged_inv_path), str(inv_path))

        rc_pr, err_pr = run(self.tmp, "--check-pr")
        self.assertEqual(rc_pr, 1)
        self.assertIn("member_count", err_pr)

        rc_strict, err_strict = run(self.tmp, "--check")
        self.assertEqual(rc_strict, 1)

        # Even if someone re-pinned 9.json and block-manifest.json to the
        # stale-count 9.inventory.json bytes, --check-pr MUST still fail on
        # member_count != len(members).
        new_hash = attest.sha256_file(inv_path)
        env_path = self.tmp / "signoff/attest/9.json"
        env = json.loads(env_path.read_text())
        env["provenance"]["input"]["content_hash"] = new_hash
        env_path.write_text(attest.dump(env))
        mp = self.tmp / "signoff/block-manifest.json"
        manifest = json.loads(mp.read_text())
        manifest["evidence"]["9"]["content_hash"] = new_hash
        mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

        rc_pr2, err_pr2 = run(self.tmp, "--check-pr")
        self.assertEqual(rc_pr2, 1)
        self.assertIn("member_count", err_pr2)

    def test_concurrent_pr_branches_merge_without_conflict_and_regenerate_clean(self):
        _init_git_repo(self.tmp)

        # Branch A adds sim/alpha/tool_a.py; touches none of the 4 signoff files.
        _git(self.tmp, "checkout", "-b", "pr-a", "main")
        (self.tmp / "sim/alpha").mkdir(parents=True, exist_ok=True)
        (self.tmp / "sim/alpha/tool_a.py").write_text("# pr-a\n")
        _git(self.tmp, "add", "sim/alpha/tool_a.py")
        _git(self.tmp, "commit", "-m", "feat(sim): add alpha tool")
        rc_a, err_a = run(self.tmp, "--check-pr", "--base-ref", "main")
        self.assertEqual(rc_a, 0, err_a)

        # Branch B adds sim/beta/tool_b.py; touches none of the 4 signoff files.
        _git(self.tmp, "checkout", "-b", "pr-b", "main")
        (self.tmp / "sim/beta").mkdir(parents=True, exist_ok=True)
        (self.tmp / "sim/beta/tool_b.py").write_text("# pr-b\n")
        _git(self.tmp, "add", "sim/beta/tool_b.py")
        _git(self.tmp, "commit", "-m", "feat(sim): add beta tool")
        rc_b, err_b = run(self.tmp, "--check-pr", "--base-ref", "main")
        self.assertEqual(rc_b, 0, err_b)

        # Negative control for Contract item 1: a PR branch that modifies
        # signoff/attest/9.inventory.json fails --check-pr --base-ref main.
        _git(self.tmp, "checkout", "-b", "pr-bad-edit", "pr-b")
        run(self.tmp, "--write", "9")
        rc_bad, err_bad = run(self.tmp, "--check-pr", "--base-ref", "main")
        self.assertEqual(rc_bad, 1)
        self.assertIn("must not modify", err_bad)
        _git(self.tmp, "checkout", "--", ".")

        # git merge-tree --write-tree between pr-a and pr-b has ZERO conflicts.
        mt = _git(self.tmp, "merge-tree", "--write-tree", "pr-a", "pr-b", check=False)
        self.assertEqual(mt.returncode, 0, mt.stdout + mt.stderr)
        self.assertNotIn("CONFLICT", mt.stdout)

        # Merge both into main and regenerate item 9 -> --check is green and
        # member_count == len(members) with both scripts present.
        _git(self.tmp, "checkout", "main")
        _git(self.tmp, "merge", "--no-ff", "pr-a", "-m", "merge pr-a")
        _git(self.tmp, "merge", "--no-ff", "pr-b", "-m", "merge pr-b")
        rc_w, err_w = run(self.tmp, "--write", "9")
        self.assertEqual(rc_w, 0, err_w)
        rc_c, err_c = run(self.tmp, "--check")
        self.assertEqual(rc_c, 0, err_c)
        inv = json.loads((self.tmp / "signoff/attest/9.inventory.json").read_text())
        self.assertEqual(inv["member_count"], len(inv["members"]))
        paths = {m["path"] for m in inv["members"]}
        self.assertIn("sim/alpha/tool_a.py", paths)
        self.assertIn("sim/beta/tool_b.py", paths)

    def test_sync_main_which_sha_guard(self):
        # Set up a bare origin + working clone with a deterministic fake report
        # renderer so we test real git push / non-fast-forward / status transitions.
        work_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work_root, True)
        origin = work_root / "origin.git"
        clone = work_root / "clone"
        peer = work_root / "peer"

        _fake_render_report(self.tmp, self.tmp / "signoff/t1-report.json")
        _init_git_repo(self.tmp)
        _git(work_root, "clone", "--bare", str(self.tmp), str(origin))
        _git(work_root, "clone", str(origin), str(clone))
        _git(clone, "config", "user.name", "Test Runner")
        _git(clone, "config", "user.email", "runner@example.invalid")
        _git(work_root, "clone", str(origin), str(peer))
        _git(peer, "config", "user.name", "Peer Merger")
        _git(peer, "config", "user.email", "peer@example.invalid")

        history = []

        def record_status(sha, state, description):
            history.append((sha, state, description))

        def latest_status(sha):
            matches = [st for s, st, _ in history if s == sha]
            return matches[-1] if matches else None

        def ever_succeeded(sha):
            return any(s == sha and st == "success" for s, st, _ in history)

        def run_sync(**kwargs):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return attest.sync_main(
                    clone,
                    render_report=_fake_render_report,
                    post_status=record_status,
                    **kwargs,
                )

        # 1. No-op merge commit M0 (non-inventoried doc): valid on its exact SHA,
        #    no bot commit created.
        (peer / "DOC_NOTE.md").write_text("docs only\n")
        _git(peer, "add", "DOC_NOTE.md")
        _git(peer, "commit", "-m", "docs: add note")
        _git(peer, "push", "origin", "main")
        m0 = _git(peer, "rev-parse", "HEAD").stdout.strip()

        rc = run_sync(target_sha=m0)
        self.assertEqual(rc, 0)
        self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout.strip(), m0)
        self.assertEqual(latest_status(m0), "success")

        # 2. Pending merge commit M1 (adds sim/gamma/tool_g.py): M1 stays
        #    pending (never success); bot commit B1 touches only ITEM9_ARTIFACTS
        #    and gets success; --check passes at B1.
        (peer / "sim/gamma").mkdir(parents=True, exist_ok=True)
        (peer / "sim/gamma/tool_g.py").write_text("# gamma\n")
        _git(peer, "add", "sim/gamma/tool_g.py")
        _git(peer, "commit", "-m", "feat(sim): add gamma")
        _git(peer, "push", "origin", "main")
        m1 = _git(peer, "rev-parse", "HEAD").stdout.strip()

        rc = run_sync(target_sha=m1)
        self.assertEqual(rc, 0)
        b1 = _git(origin, "rev-parse", "refs/heads/main").stdout.strip()
        self.assertNotEqual(b1, m1)
        self.assertFalse(ever_succeeded(m1))
        self.assertEqual(latest_status(m1), "pending")
        self.assertEqual(latest_status(b1), "success")
        changed_in_b1 = set(
            _git(clone, "diff-tree", "--no-commit-id", "--name-only", "-r", b1).stdout.splitlines()
        )
        self.assertTrue(changed_in_b1.issubset(set(attest.ITEM9_ARTIFACTS)), changed_in_b1)
        self.assertGreater(len(changed_in_b1), 0)
        rc_chk, err_chk = run(clone, "--check")
        self.assertEqual(rc_chk, 0, err_chk)

        # 3. No-loop: re-running sync_main on B1 is a no-op (creates no new commit).
        rc_noop = run_sync(target_sha=b1)
        self.assertEqual(rc_noop, 0)
        self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout.strip(), b1)
        self.assertEqual(latest_status(b1), "success")

        # 4. Interleaved second merge: M2 lands on origin/main while M1b is
        #    regenerating (simulated via pre_push_hook before git push).
        #    Only the single newest bot commit B2 becomes valid; M1b and M2 stay pending.
        _git(peer, "pull", "--ff-only", "origin", "main")
        (peer / "sim/delta").mkdir(parents=True, exist_ok=True)
        (peer / "sim/delta/one.py").write_text("# one\n")
        _git(peer, "add", "sim/delta/one.py")
        _git(peer, "commit", "-m", "feat(sim): add delta one")
        _git(peer, "push", "origin", "main")
        m1b = _git(peer, "rev-parse", "HEAD").stdout.strip()

        interleaved = {"done": False, "m2": None}

        def push_interleaved_m2(_cur_sha, _bot_sha):
            if not interleaved["done"]:
                interleaved["done"] = True
                (peer / "sim/delta/two.py").write_text("# two\n")
                _git(peer, "add", "sim/delta/two.py")
                _git(peer, "commit", "-m", "feat(sim): add delta two")
                _git(peer, "push", "origin", "main")
                interleaved["m2"] = _git(peer, "rev-parse", "HEAD").stdout.strip()

        rc_inter = run_sync(target_sha=m1b, pre_push_hook=push_interleaved_m2)
        self.assertEqual(rc_inter, 0)
        m2 = interleaved["m2"]
        self.assertIsNotNone(m2)
        b2 = _git(origin, "rev-parse", "refs/heads/main").stdout.strip()
        self.assertNotIn(b2, (m1b, m2))
        self.assertFalse(ever_succeeded(m1b))
        self.assertFalse(ever_succeeded(m2))
        self.assertEqual(latest_status(m1b), "pending")
        self.assertEqual(latest_status(m2), "pending")
        self.assertEqual(latest_status(b2), "success")
        inv_b2 = json.loads((clone / "signoff/attest/9.inventory.json").read_text())
        self.assertEqual(inv_b2["member_count"], len(inv_b2["members"]))
        paths_b2 = {m["path"] for m in inv_b2["members"]}
        self.assertIn("sim/delta/one.py", paths_b2)
        self.assertIn("sim/delta/two.py", paths_b2)

        # 5. Failed push without remote advance (e.g. branch protection / permission
        #    refusal): fails closed loudly and leaves the SHA red (failure).
        _git(peer, "pull", "--ff-only", "origin", "main")
        (peer / "sim/epsilon").mkdir(parents=True, exist_ok=True)
        (peer / "sim/epsilon/tool_e.py").write_text("# epsilon\n")
        _git(peer, "add", "sim/epsilon/tool_e.py")
        _git(peer, "commit", "-m", "feat(sim): add epsilon")
        _git(peer, "push", "origin", "main")
        m_prot = _git(peer, "rev-parse", "HEAD").stdout.strip()

        hook = origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
        hook.chmod(0o755)
        rc_prot = run_sync(target_sha=m_prot)
        hook.unlink()
        self.assertEqual(rc_prot, 1)
        self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout.strip(), m_prot)
        self.assertFalse(ever_succeeded(m_prot))
        self.assertEqual(latest_status(m_prot), "failure")

        # 6. Failed regeneration: commit introduces a check_9 failure (orphan
        #    records dir).  sync_main fails, pushes nothing, leaves SHA red.
        (peer / "sim/broken-fam/records").mkdir(parents=True, exist_ok=True)
        (peer / "sim/broken-fam/records/r.json").write_text("{}\n")
        _git(peer, "add", "sim/broken-fam/records/r.json")
        _git(peer, "commit", "-m", "bad: orphan records dir")
        _git(peer, "push", "origin", "main")
        m_bad = _git(peer, "rev-parse", "HEAD").stdout.strip()

        rc_bad = run_sync(target_sha=m_bad)
        self.assertEqual(rc_bad, 1)
        self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout.strip(), m_bad)
        self.assertFalse(ever_succeeded(m_bad))
        self.assertEqual(latest_status(m_bad), "failure")


if __name__ == "__main__":
    unittest.main()
