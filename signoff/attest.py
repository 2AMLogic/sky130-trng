#!/usr/bin/env python3
"""Artifact-anchored `generic` envelopes for T1 items 1 (digital), 2, 9 and 10 (issue #320).

Item 1 analog is NOT built here: `klt signoff --attest 1` mints it where xschem
exists (issue #360; .github/workflows/pdk-nightly.yml, netlist-check).

klayout-tools 0.7.0 grades these four items only from an opt-in `generic`
envelope that (a) declares `"t1_item": <id>`, (b) names the audited artifact in
`provenance.input.path` + `provenance.input.content_hash`, and (c) is cited by a
manifest entry pinning the same hash.  The artifact each envelope pins is the
committed INVENTORY `signoff/attest/<key>.inventory.json`: a versioned list of
repo files, each with a sha256.  This script

  * `--write`  re-resolves every inventory's selectors against the tree, runs the
               row's mechanical checks, and rewrites inventory + envelope + the
               row's pin in signoff/block-manifest.json;
  * `--check`  (default, read-only, CI) fails when a committed inventory no
               longer matches the tree (a file changed, appeared or vanished),
               when a check outcome differs from the committed envelope, or when
               an envelope no longer pins its inventory.

Stdlib only; no simulator, no PDK, no xschem.  The checks are PRESENCE and
CONSISTENCY checks over committed files (see signoff/README.md "Items 1, 2, 9,
10 attestation" for what they do NOT establish).  A row whose check cannot be
made honestly is emitted with `status: "fail"` and the reason in `failures`,
so the grader renders it unmet instead of going green.

    attest.py [--repo-root DIR] [--write | --check] [KEY ...]

Exit 0: consistent (check) / written (write).  Exit 1: drift.  Exit 2: usage.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path

SCHEMA_VERSION = 1
ATTEST_DIR = "signoff/attest"
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_SUFFIXES = (".pyc",)

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
    ],
    "2.digital": [
        "layout/trng_digital/trng_digital.gds",
        "layout/trng_digital/trng_digital.def",
        "layout/trng_digital/trng_digital.routed.v",
        "digital/flow/place-and-route/pnr-trng-digital-50khz.json",
        "digital/flow/place-and-route/tool-pins.json",
        "sim/digital-pnr/harness/pnr-and-verify.py",
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
        "sim/pdk.json",
        "layout/pdk.json",
    ],
    "10": ["README.md", "LICENSE", "REPRODUCE.md", ".github/workflows/*"],
}

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


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


def digest(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    ap.add_argument("keys", nargs="*")
    args = ap.parse_args(argv)
    root = Path(args.repo_root)
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
        status = json.loads(files[f"{ATTEST_DIR}/{key}.json"])["status"]
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
