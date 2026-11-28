#!/usr/bin/env python3
"""Artifact-anchored `generic` envelopes for T1 items 1 (digital), 2, 9 and 10 (issues #320, #697).

Item 1 analog is NOT built here: `klt signoff --attest 1` mints it where xschem
exists (issue #360; .github/workflows/pdk-nightly.yml, netlist-check).

klayout-tools 0.8.0 (the CI pin since issue #363) grades these four items only from an opt-in `generic`
envelope that (a) declares `"t1_item": <id>`, (b) names the audited artifact in
`provenance.input.path` + `provenance.input.content_hash`, and (c) is cited by a
manifest entry pinning the same hash.  The artifact each envelope pins is the
committed INVENTORY `signoff/attest/<key>.inventory.json`: a versioned list of
repo files, each with a sha256.  This script supports four modes (DR-0021):

  * `--write`      re-resolves every inventory's selectors against the tree, runs
                   the row's mechanical checks, and rewrites inventory + envelope
                   + the row's pin in signoff/block-manifest.json;
  * `--check`      (default, read-only, main-time gate) fails when any committed
                   inventory no longer matches the tree (a file changed, appeared
                   or vanished), when a check outcome differs from the committed
                   envelope, or when an envelope / manifest pin differs;
  * `--check-pr`   (read-only, PR-time gate, DR-0021) runs full `--check` for
                   items 1.digital, 2.analog, 2.digital, and 10; for item 9,
                   verifies that a fresh `build(root, "9")` passes (`status ==
                   "pass"`), that the committed item-9 chain is internally
                   consistent (`member_count == len(members)`, envelope hash
                   matches inventory file, manifest pin matches envelope), and
                   (when `--base-ref` is given) that the PR did not edit
                   `9.inventory.json`, `9.json`, or `evidence["9"]`;
  * `--sync-main`  (post-merge `push: main` regeneration, DR-0021) regenerates
                   item 9 + `signoff/t1-report.json` on `main`, verifies the
                   full main-time gate (`--check` all items + `t1-report.json`
                   byte-diff + `member_count == len(members)`), pushes a
                   bot commit touching only the four item-9 artifacts when
                   needed, handles interleaved merges by retrying against the
                   newest head, and stamps the `attest-main` commit status on
                   the exact signoff-valid SHA.

Stdlib only; no simulator, no PDK, no xschem (`--sync-main` shells out to `git`
and `klt signoff`).  The checks are PRESENCE and CONSISTENCY checks over
committed files (see signoff/README.md "Items 1, 2, 9, 10 attestation" for what
they do NOT establish).  A row whose check cannot be made honestly is emitted
with `status: "fail"` and the reason in `failures`, so the grader renders it
unmet instead of going green.

    attest.py [--repo-root DIR] [--write | --check | --check-pr [--base-ref REF] | --sync-main ...] [KEY ...]

Exit 0: consistent (check) / written (write) / synced.  Exit 1: drift or failure.  Exit 2: usage.
"""
import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))
from _hashing import sha256_file as _sha256_file, sha256_text as _sha256_text  # noqa: E402

SCHEMA_VERSION = 1
ATTEST_DIR = "signoff/attest"
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_SUFFIXES = (".pyc",)

# Keys whose committed aggregate bytes are regenerated post-merge on `main`
# rather than per-PR (DR-0021 / issue #697).
PR_DEFERRED_KEYS = frozenset({"9"})
ITEM9_ARTIFACTS = (
    "signoff/attest/9.inventory.json",
    "signoff/attest/9.json",
    "signoff/block-manifest.json",
    "signoff/t1-report.json",
)
BOT_COMMIT_PREFIX = "chore(signoff): regenerate item-9 attestation"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

# key -> (t1 item, partition or None, one-line claim)
ROWS = {
    "1.digital": (1, "digital", "committed RTL plus the synthesized netlist derived from it"),
    "2.analog": (2, "analog", "committed GDS with documented provenance"),
    "2.digital": (2, "digital", "committed routed GDS from a committed P&R flow"),
    "9": (9, None, "testbenches committed, cold-start index, pinned PDK revision"),
    "10": (10, None, "README, license, CI keeping harness and evidence formats valid"),
}

# Selectors: repo-relative file or fnmatch glob on the posix relpath; a leading
# "!" removes matches (unit tests are not testbenches).
SELECTORS = {
    "1.digital": [
        "digital/rtl/trng_digital.v",
        "digital/flow/unconstrained/synthesize-trng-digital.json",
        "digital/flow/constrained-50khz/synthesize-trng-digital-50khz.json",
        "sim/digital-synthesis/runs/20260910-001436-a4c3194/unconstrained-synthesize-output.json",
        "sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-synthesize-output.json",
        "sim/digital-synthesis/runs/20260910-001436-a4c3194/unconstrained-trng_digital_synth.v",
        "sim/digital-synthesis/runs/20260910-001436-a4c3194/50khz-constrained-trng_digital_synth.v",
        "digital/flow/place-and-route/tool-pins.json",
    ],
    "2.analog": [
        "layout/sampler_core/sampler_core.gds",
        "layout/sampler_core/README.md",
        "layout/sampler_core/cell.json",
        "layout/sampler_core/compose.request.json",
        "layout/sampler_core/compose.response.json",
        "layout/bin/compose-cell.py",
        "layout/bin/_klt_common.py",
    ],
    "2.digital": [
        "layout/trng_digital/trng_digital.gds",
        "layout/trng_digital/trng_digital.def",
        "layout/trng_digital/trng_digital.routed.v",
        "digital/flow/place-and-route/pnr-trng-digital-50khz.json",
        "digital/flow/place-and-route/tool-pins.json",
        "sim/digital-pnr/harness/pnr-and-verify.py",
        "layout/bin/_hashing.py",
        "layout/bin/_klt_common.py",
        "sim/digital-pnr/records/*.json",
    ],
    "9": [
        "sim/*/testbench/*",
        "sim/*/harness/*",
        "sim/*/analysis/*",
        "sim/*/bin/*",
        "sim/*/requests/*",
        "sim/*/*.py",
        "!sim/tests/*",
        "digital/tb/*",
        "digital/tb/cocotb/*",
        "REPRODUCE.md",
        "design/pdk.json",
        "design/_pdk_search.py",
        "sim/pdk.json",
        "layout/pdk.json",
        "layout/bin/_hashing.py",
        "layout/bin/_klt_common.py",
        "layout/bin/_pex_rewrite.py",
    ],
    "10": ["README.md", "LICENSE", "REPRODUCE.md", ".github/workflows/*"],
}

sha256_file = partial(_sha256_file, prefix=True)  # recorded as "sha256:<hex>"
digest = partial(_sha256_text, prefix=True)      # recorded as "sha256:<hex>"


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIXES):
                continue
            yield Path(dirpath, name).relative_to(root).as_posix()


def resolve(root, selectors):
    """Sorted repo-relative files matched by any selector; also the selectors
    that matched nothing (a vanished input is drift, not a silent shrink)."""
    files = sorted(walk(root))
    chosen, unmatched = set(), []
    for sel in (s for s in selectors if not s.startswith("!")):
        hit = [f for f in files if fnmatch.fnmatchcase(f, sel)]
        if not hit:
            unmatched.append(sel)
        chosen.update(hit)
    for sel in (s[1:] for s in selectors if s.startswith("!")):
        chosen -= {f for f in chosen if fnmatch.fnmatchcase(f, sel)}
    return sorted(chosen), unmatched


def load_json(root, rel):
    return json.loads((root / rel).read_text())


# ---------------------------------------------------------------- row checks
# Each returns a list of failure strings (empty = every check passed).

def check_1_digital(root, members):
    fails = []
    rtl = sha256_file(root / "digital/rtl/trng_digital.v")
    run = "sim/digital-synthesis/runs/20260910-001436-a4c3194/"
    for out in ("unconstrained-synthesize-output.json", "50khz-constrained-synthesize-output.json"):
        got = load_json(root, run + out).get("provenance", {}).get("input", {}).get("content_hash")
        if got != rtl:
            fails.append(f"RTL sha256 {rtl} != input content_hash {got} pinned by {run}{out} (synthesis stale)")
    pins = load_json(root, "digital/flow/place-and-route/tool-pins.json")
    if pins.get("input_netlist_klt_content_hash") != rtl:
        fails.append("tool-pins.json input_netlist_klt_content_hash != current RTL sha256")
    netlist = sha256_file(root / (run + "50khz-constrained-trng_digital_synth.v"))
    if pins.get("input_netlist_sha256") != netlist:
        fails.append("tool-pins.json input_netlist_sha256 != committed 50 kHz synthesized netlist sha256")
    return fails


def _manifest_pin(root, key):
    ev = load_json(root, "signoff/block-manifest.json")["evidence"].get(key)
    return ev.get("content_hash") if isinstance(ev, dict) else None


def check_2_analog(root, members):
    fails = []
    gds = sha256_file(root / "layout/sampler_core/sampler_core.gds")
    if _manifest_pin(root, "3.analog") != gds:
        fails.append("GDS sha256 != the content_hash the manifest pins for 3.analog (DRC ran on a different GDS)")
    readme = (root / "layout/sampler_core/README.md").read_text().lower()
    if "compose" not in readme:
        fails.append("layout/sampler_core/README.md documents no compose provenance")
    return fails


def check_2_digital(root, members):
    fails = []
    gds = sha256_file(root / "layout/trng_digital/trng_digital.gds")
    if _manifest_pin(root, "3.digital") != gds:
        fails.append("GDS sha256 != the content_hash the manifest pins for 3.digital")
    pins = load_json(root, "digital/flow/place-and-route/tool-pins.json")
    rtl = sha256_file(root / "digital/rtl/trng_digital.v")
    rec = load_json(root, "sim/digital-pnr/records/20261003-212010-fa76b17.json").get("input_hashes", {})
    if rec.get("rtl") != rtl:
        fails.append("P&R record input_hashes.rtl != current RTL sha256 (P&R stale vs RTL)")
    if rec.get("netlist") != pins.get("input_netlist_sha256"):
        fails.append("P&R record netlist hash != tool-pins.json input_netlist_sha256")
    return fails


def check_9(root, members):
    fails = []
    covered = {m["path"].split("/")[1] for m in members if m["path"].startswith("sim/") and m["path"].count("/") >= 2}
    for fam in sorted(p.name for p in (root / "sim").iterdir() if (p / "records").is_dir()):
        if fam not in covered:
            fails.append(f"sim/{fam} has records but no committed testbench/harness/analysis/script outside records/, runs/ and corners/")
    pins = {f: load_json(root, f).get("open_pdks_commit") for f in ("design/pdk.json", "sim/pdk.json", "layout/pdk.json")}
    if len(set(pins.values())) != 1 or None in pins.values():
        fails.append(f"open_pdks_commit disagrees across pdk.json files: {pins}")
    elif pins["sim/pdk.json"] not in (root / "REPRODUCE.md").read_text():
        fails.append("REPRODUCE.md does not state the pinned open_pdks_commit")
    return fails


def check_10(root, members):
    fails = []
    readme = (root / "README.md").read_text()
    if "REPRODUCE.md" not in readme:
        fails.append("README.md does not point to REPRODUCE.md (how to reproduce every result)")
    if "Target specification" not in readme:
        fails.append("README.md has no spec table section")
    if "Apache License" not in (root / "LICENSE").read_text()[:400]:
        fails.append("LICENSE is not recognisably Apache-2.0")
    ci = (root / ".github/workflows/ci.yml").read_text()
    for needle in ("tools/check_reproduce.py", "signoff-check", "check_records_append_only"):
        if needle not in ci:
            fails.append(f".github/workflows/ci.yml does not run {needle}")
    return fails


CHECKS = {
    "1.digital": check_1_digital,
    "2.analog": check_2_analog, "2.digital": check_2_digital,
    "9": check_9, "10": check_10,
}


# ------------------------------------------------------------------ builders
def build(root, key):
    item, partition, claim = ROWS[key]
    files, unmatched = resolve(root, SELECTORS[key])
    members = [{"path": f, "sha256": sha256_file(root / f)} for f in files]
    fails = [f"selector matched no file: {s}" for s in unmatched]
    if not fails:
        fails = CHECKS[key](root, members)
    inventory = {
        "schema_version": SCHEMA_VERSION,
        "key": key,
        "t1_item": item,
        "partition": partition,
        "claim": claim,
        "selectors": SELECTORS[key],
        "member_count": len(members),
        "members": members,
    }
    inv_rel = f"{ATTEST_DIR}/{key}.inventory.json"
    inv_text = dump(inventory)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "kind": "generic",
        "t1_item": item,
        "status": "fail" if fails else "pass",
        "source": "signoff/attest.py",
        "failures": fails,
        "provenance": {"input": {"path": inv_rel, "content_hash": digest(inv_text)}},
    }
    return {
        f"{ATTEST_DIR}/{key}.inventory.json": inv_text,
        f"{ATTEST_DIR}/{key}.json": dump(envelope),
    }


def manifest_entry(files, key):
    env = json.loads(files[f"{ATTEST_DIR}/{key}.json"])
    return {"file": f"{ATTEST_DIR}/{key}.json", "content_hash": env["provenance"]["input"]["content_hash"]}


def dump(obj):
    return json.dumps(obj, indent=2, sort_keys=False) + "\n"


# -------------------------------------------------- DR-0021 PR & main helpers

def verify_committed_chain(root, key, manifest):
    """Verify structural integrity and internal hash consistency of the
    committed inventory -> envelope -> manifest pin chain for `key` without
    requiring inventory members to match the current working tree.

    Catches stale-count clean merges (e.g. two branches adding members where
    `git merge-file` leaves `member_count != len(members)`), duplicate paths,
    and hand-edited inventories whose bytes diverge from the pinned envelope.
    """
    errs = []
    item = ROWS[key][0]
    inv_rel = f"{ATTEST_DIR}/{key}.inventory.json"
    env_rel = f"{ATTEST_DIR}/{key}.json"
    inv_path = root / inv_rel
    env_path = root / env_rel

    if not inv_path.is_file():
        return [f"{key}: missing {inv_rel}"]
    try:
        inv = json.loads(inv_path.read_text())
    except (OSError, ValueError) as exc:
        return [f"{key}: unreadable {inv_rel}: {exc}"]
    if not isinstance(inv, dict) or not isinstance(inv.get("members"), list):
        return [f"{key}: malformed {inv_rel}: missing members list"]

    members = inv["members"]
    if inv.get("member_count") != len(members):
        errs.append(
            f"{key}: stale member_count in {inv_rel}: "
            f"member_count={inv.get('member_count')} != len(members)={len(members)}"
        )
    seen = set()
    for m in members:
        if not isinstance(m, dict) or not isinstance(m.get("path"), str) or not isinstance(m.get("sha256"), str):
            errs.append(f"{key}: malformed member entry in {inv_rel}: {m!r}")
            continue
        if not m["sha256"].startswith("sha256:"):
            errs.append(f"{key}: invalid sha256 format for {m['path']} in {inv_rel}")
        if m["path"] in seen:
            errs.append(f"{key}: duplicate member path {m['path']} in {inv_rel}")
        seen.add(m["path"])

    if not env_path.is_file():
        errs.append(f"{key}: missing {env_rel}")
        return errs
    try:
        env = json.loads(env_path.read_text())
    except (OSError, ValueError) as exc:
        errs.append(f"{key}: unreadable {env_rel}: {exc}")
        return errs

    if env.get("kind") != "generic" or env.get("t1_item") != item:
        errs.append(f"{key}: {env_rel} has unexpected kind/t1_item: {env.get('kind')}/{env.get('t1_item')}")
    prov_in = env.get("provenance", {}).get("input", {})
    if prov_in.get("path") != inv_rel:
        errs.append(f"{key}: {env_rel} provenance.input.path={prov_in.get('path')!r} != {inv_rel!r}")
    actual_inv_hash = sha256_file(inv_path)
    if prov_in.get("content_hash") != actual_inv_hash:
        errs.append(
            f"{key}: {env_rel} pins {prov_in.get('content_hash')} != "
            f"actual {inv_rel} sha256 {actual_inv_hash}"
        )
    if manifest is not None:
        want = {"file": env_rel, "content_hash": prov_in.get("content_hash")}
        have = manifest.get("evidence", {}).get(key)
        if have != want:
            errs.append(f"{key}: signoff/block-manifest.json evidence[{key!r}]={have!r} != {want!r}")
    return errs


def _git(root, *args, check=True, text=True):
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=text,
        check=check,
    )


def check_pr_no_item9_edit(root, base_ref):
    """Contract item 1 (DR-0021): a PR must not modify item-9's committed
    aggregate files (`9.inventory.json`, `9.json`, `block-manifest.json`
    `evidence["9"]`); only the `main` regeneration job writes them."""
    errs = []
    for rel in ("signoff/attest/9.inventory.json", "signoff/attest/9.json"):
        res = _git(root, "show", f"{base_ref}:{rel}", check=False, text=False)
        if res.returncode != 0:
            errs.append(f"9: cannot read {base_ref}:{rel} to check PR immutability")
            continue
        cur = root / rel
        if not cur.is_file() or cur.read_bytes() != res.stdout:
            errs.append(
                f"9: PR must not modify {rel} (DR-0021: only attest-main writes item-9 artifacts on main)"
            )
    res_m = _git(root, "show", f"{base_ref}:signoff/block-manifest.json", check=False)
    if res_m.returncode != 0:
        errs.append(f"9: cannot read {base_ref}:signoff/block-manifest.json to check PR immutability")
    else:
        try:
            base_ev9 = json.loads(res_m.stdout).get("evidence", {}).get("9")
            cur_ev9 = load_json(root, "signoff/block-manifest.json").get("evidence", {}).get("9")
        except (OSError, ValueError) as exc:
            errs.append(f"9: cannot compare evidence['9'] against {base_ref}: {exc}")
        else:
            if cur_ev9 != base_ev9:
                errs.append(
                    "9: PR must not modify signoff/block-manifest.json evidence['9'] "
                    "(DR-0021: only attest-main writes item-9 artifacts on main)"
                )
    return errs


def _render_t1_report(root, out_path):
    """Run the documented `klt signoff` command verbatim and write `out_path`."""
    res = subprocess.run(
        [
            "klt", "signoff",
            "--manifest", "signoff/block-manifest.json",
            "--tiers-doc", "signoff/design-evidence-tiers.md",
            "--format", "json",
        ],
        cwd=str(root),
        capture_output=True,
    )
    if res.returncode not in (0, 3):
        msg = res.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"klt signoff exited {res.returncode}: {msg}")
    Path(out_path).write_bytes(res.stdout)


def _post_github_status(sha, state, description, *, context="attest-main"):
    """Post a GitHub commit status for `context` on `sha` via GITHUB_TOKEN."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPOSITORY are required for --status-mode github")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    payload = {
        "state": state,
        "context": context,
        "description": description[:140],
    }
    server = os.environ.get("GITHUB_SERVER_URL")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and run_id:
        payload["target_url"] = f"{server.rstrip('/')}/{repo}/actions/runs/{run_id}"
    req = urllib.request.Request(
        f"{api_url}/repos/{repo}/statuses/{sha}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"GitHub status API returned HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub status API HTTP {exc.code}: {body}") from exc


def _verify_main_gate(root, render_report, *, run_tests=False):
    """Full main-time verification gate (DR-0021 contract item 3):
      1. `attest.py --check` passes for ALL items (1.digital, 2.analog, 2.digital, 9, 10)
      2. Committed item-9 chain has `status == "pass"`, `member_count == len(members)`,
         and every member sha256 matches the file on disk
      3. Fresh `t1-report.json` render is byte-identical to committed `signoff/t1-report.json`
      4. Optionally (`run_tests=True` in CI), `sim/tests/test_signoff_attest.py` passes
    """
    rc = main(["--repo-root", str(root), "--check"])
    if rc != 0:
        return "attest.py --check failed"

    mpath = root / "signoff/block-manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.is_file() else None
    chain_errs = verify_committed_chain(root, "9", manifest)
    if chain_errs:
        return "; ".join(chain_errs)

    env9 = load_json(root, "signoff/attest/9.json")
    if env9.get("status") != "pass":
        return f"item-9 envelope status is {env9.get('status')!r}: {env9.get('failures')}"

    inv9 = load_json(root, "signoff/attest/9.inventory.json")
    if inv9["member_count"] != len(inv9["members"]):
        return f"item-9 member_count {inv9['member_count']} != len(members) {len(inv9['members'])}"
    for m in inv9["members"]:
        if sha256_file(root / m["path"]) != m["sha256"]:
            return f"item-9 member hash mismatch for {m['path']}"

    with tempfile.TemporaryDirectory() as td:
        fresh_report = Path(td) / "t1-report.json"
        try:
            render_report(root, fresh_report)
        except Exception as exc:
            return f"t1-report re-render failed: {exc}"
        committed = root / "signoff/t1-report.json"
        if not committed.is_file() or committed.read_bytes() != fresh_report.read_bytes():
            return "signoff/t1-report.json differs from fresh klt signoff render"

    if run_tests:
        test_res = subprocess.run(
            [sys.executable, "sim/tests/test_signoff_attest.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if test_res.returncode != 0:
            return f"sim/tests/test_signoff_attest.py failed (rc {test_res.returncode})"
    return None


def _porcelain_paths(root):
    res = _git(root, "status", "--porcelain")
    paths = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1 format: XY <path> (or XY <old> -> <new>)
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        paths.append(path_part)
    return paths


def sync_main(
    root,
    *,
    target_sha,
    remote="origin",
    branch="main",
    render_report=None,
    post_status=None,
    max_push_retries=3,
    pre_push_hook=None,
    run_tests=False,
):
    """Post-merge item-9 regeneration and `attest-main` SHA-validity state
    machine (DR-0021 contract items 3, 4, 5, 7).

    Invariants enforced:
      * A SHA on `main` receives `attest-main: success` iff the full main-time
        gate passes on that exact SHA AND regeneration is a no-op on that SHA.
      * A merge commit that needed regeneration stays `pending` (superseded by
        its bot commit) and NEVER receives `success`.
      * Any regeneration, verification, or non-race push failure stamps the
        current SHA `failure` and exits 1 without pushing a bot commit.
      * An interleaved merge that advances `remote/branch` before push causes
        the prior SHA to stay `pending` (superseded) and retries cleanly on the
        newest `remote/branch` head so only the newest bot commit is valid.
    """
    root = Path(root)
    if render_report is None:
        render_report = _render_t1_report
    if post_status is None:
        post_status = lambda _sha, _state, _desc: None

    current_sha = target_sha
    post_status(current_sha, "pending", "Checking/regenerating item-9 attestation")

    for _attempt in range(max_push_retries):
        _git(root, "fetch", remote, branch)
        remote_sha = _git(root, "rev-parse", f"{remote}/{branch}").stdout.strip()
        if remote_sha != current_sha:
            post_status(
                current_sha,
                "pending",
                f"Superseded by newer {branch} head {remote_sha[:8]}; not signoff-valid",
            )
            current_sha = remote_sha
            post_status(current_sha, "pending", "Checking/regenerating item-9 attestation")

        _git(root, "checkout", "--detach", current_sha)
        _git(root, "reset", "--hard", current_sha)

        try:
            built = build(root, "9")
        except (OSError, ValueError, KeyError) as exc:
            post_status(current_sha, "failure", f"Item-9 build failed: {exc}")
            print(f"attest-main: item-9 build failed at {current_sha[:8]}: {exc}", file=sys.stderr)
            return 1
        built_env = json.loads(built[f"{ATTEST_DIR}/9.json"])
        if built_env["status"] != "pass":
            reason = "; ".join(built_env.get("failures", [])) or "status != pass"
            post_status(current_sha, "failure", f"Item-9 check failed: {reason}")
            print(f"attest-main: item-9 check failed at {current_sha[:8]}: {reason}", file=sys.stderr)
            return 1

        rc_write = main(["--repo-root", str(root), "--write", "9"])
        if rc_write != 0:
            post_status(current_sha, "failure", "attest.py --write 9 failed")
            return 1

        try:
            render_report(root, root / "signoff/t1-report.json")
        except Exception as exc:
            post_status(current_sha, "failure", f"t1-report render failed: {exc}")
            print(f"attest-main: t1-report render failed at {current_sha[:8]}: {exc}", file=sys.stderr)
            return 1

        changed = _porcelain_paths(root)
        unexpected = [p for p in changed if p not in ITEM9_ARTIFACTS]
        if unexpected:
            post_status(current_sha, "failure", f"Unexpected modified files outside item-9 artifacts: {unexpected}")
            print(f"attest-main: unexpected modified files: {unexpected}", file=sys.stderr)
            return 1

        gate_err = _verify_main_gate(root, render_report, run_tests=run_tests)
        if gate_err is not None:
            post_status(current_sha, "failure", f"Main-time verification failed: {gate_err}")
            print(f"attest-main: verification failed at {current_sha[:8]}: {gate_err}", file=sys.stderr)
            return 1

        if not changed:
            post_status(
                current_sha,
                "success",
                f"Signoff attestation valid at {current_sha[:8]} (no-op regen, --check + t1-report verified)",
            )
            return 0

        # Idempotence check: a second --write 9 must not alter anything further.
        snapshot = {p: (root / p).read_bytes() for p in ITEM9_ARTIFACTS if (root / p).is_file()}
        main(["--repo-root", str(root), "--write", "9"])
        if any((root / p).read_bytes() != b for p, b in snapshot.items()):
            post_status(current_sha, "failure", "Item-9 regeneration is not idempotent")
            return 1

        _git(root, "add", "--", *changed)
        commit_msg = (
            f"{BOT_COMMIT_PREFIX} for {current_sha[:8]}\n\n"
            f"Regenerated by attest-main from {current_sha}.\n"
            "Touches only the four item-9 attestation artifacts (DR-0021).\n"
            f"Attest-Main-Source: {current_sha}\n"
        )
        _git(
            root,
            "-c", f"user.name={BOT_NAME}",
            "-c", f"user.email={BOT_EMAIL}",
            "commit", "-m", commit_msg,
        )
        bot_sha = _git(root, "rev-parse", "HEAD").stdout.strip()

        if pre_push_hook is not None:
            pre_push_hook(current_sha, bot_sha)

        push_res = _git(root, "push", remote, f"HEAD:refs/heads/{branch}", check=False)
        if push_res.returncode == 0:
            post_status(
                current_sha,
                "pending",
                f"Superseded by bot commit {bot_sha[:8]}; not signoff-valid",
            )
            post_status(
                bot_sha,
                "success",
                f"Signoff attestation valid at {bot_sha[:8]} (regenerated from {current_sha[:8]})",
            )
            return 0

        # Push failed: distinguish an interleaved merge (retry) from a real
        # permission / branch-protection refusal (fail closed loudly).
        _git(root, "fetch", remote, branch)
        new_remote_sha = _git(root, "rev-parse", f"{remote}/{branch}").stdout.strip()
        if new_remote_sha != current_sha:
            post_status(
                current_sha,
                "pending",
                f"Superseded by newer {branch} head {new_remote_sha[:8]}; not signoff-valid",
            )
            current_sha = new_remote_sha
            continue

        err_detail = (push_res.stderr or push_res.stdout).strip().splitlines()
        summary = err_detail[-1] if err_detail else "git push rejected"
        post_status(
            current_sha,
            "failure",
            f"Failed to push regenerated item-9 commit: {summary}",
        )
        print(f"attest-main: git push failed without remote advance: {summary}", file=sys.stderr)
        return 1

    post_status(
        current_sha,
        "failure",
        f"Exceeded {max_push_retries} push retries under concurrent merges",
    )
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-pr", action="store_true")
    mode.add_argument("--sync-main", action="store_true")
    ap.add_argument(
        "--base-ref",
        default=None,
        help="With --check-pr: git ref of the PR base to enforce that item-9 artifacts were not edited",
    )
    ap.add_argument("--target-sha", default=None, help="With --sync-main: pushed SHA that triggered the run")
    ap.add_argument("--remote", default="origin", help="With --sync-main: git remote name")
    ap.add_argument("--branch", default="main", help="With --sync-main: default branch name")
    ap.add_argument(
        "--status-mode",
        choices=("none", "github"),
        default="none",
        help="With --sync-main: where to post the attest-main commit status",
    )
    ap.add_argument(
        "--run-tests",
        action="store_true",
        help="With --sync-main: also run sim/tests/test_signoff_attest.py before committing",
    )
    ap.add_argument("keys", nargs="*")
    args = ap.parse_args(argv)
    root = Path(args.repo_root)

    if args.sync_main:
        target_sha = args.target_sha or _git(root, "rev-parse", "HEAD").stdout.strip()
        poster = _post_github_status if args.status_mode == "github" else None
        return sync_main(
            root,
            target_sha=target_sha,
            remote=args.remote,
            branch=args.branch,
            post_status=poster,
            run_tests=args.run_tests,
        )

    keys = args.keys or list(ROWS)
    bad = [k for k in keys if k not in ROWS]
    if bad:
        print(f"unknown key(s): {bad}; known: {list(ROWS)}", file=sys.stderr)
        return 2
    rc = 0
    mpath = root / "signoff/block-manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.is_file() else None
    manifest_dirty = False
    for key in keys:
        try:
            files = build(root, key)
        except (OSError, ValueError, KeyError) as exc:
            print(f"{key}: cannot build: {type(exc).__name__}: {exc}", file=sys.stderr)
            rc = 1
            continue
        env_obj = json.loads(files[f"{ATTEST_DIR}/{key}.json"])
        status = env_obj["status"]

        if args.check_pr and key in PR_DEFERRED_KEYS:
            if status != "pass":
                for f in env_obj.get("failures", []):
                    print(f"{key}: FAIL {f}", file=sys.stderr)
                rc = 1
            for err in verify_committed_chain(root, key, manifest):
                print(err, file=sys.stderr)
                rc = 1
            if args.base_ref:
                for err in check_pr_no_item9_edit(root, args.base_ref):
                    print(err, file=sys.stderr)
                    rc = 1
            print(f"{key}: PR check fresh envelope status {status}")
            continue

        for rel, text in files.items():
            path = root / rel
            if args.write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            elif not path.is_file() or path.read_text() != text:
                print(f"{key}: STALE {rel} (run `python3 signoff/attest.py --write {key}` and regenerate signoff/t1-report.json)", file=sys.stderr)
                rc = 1
        want = manifest_entry(files, key)
        have = manifest["evidence"].get(key) if manifest else None
        if have != want:
            if args.write and manifest is not None:
                manifest["evidence"][key] = want
                manifest_dirty = True
            else:
                print(f"{key}: STALE signoff/block-manifest.json evidence[{key!r}] != {want}", file=sys.stderr)
                rc = 1
        print(f"{key}: envelope status {status}")
    if manifest_dirty:
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
