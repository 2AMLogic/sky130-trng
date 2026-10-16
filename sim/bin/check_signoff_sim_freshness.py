#!/usr/bin/env python3
"""Freshness guard for the signoff-cited 7.digital SDF verification record (issue #285).

signoff/block-manifest.json cites the SDF functional-verification report
unpinned (the native envelope records no input hash), so the signoff-check
re-render alone cannot notice that the DUT, SDF, testbench or oracle changed
after the simulation ran.  The record's input-hashes.json does pin them; this
checker compares those pins with the bytes in the working tree.

Read-only, stdlib only, no simulator and no PDK.  Only the *currently cited*
record is checked; historical records are never compared with today's sources.

    check_signoff_sim_freshness.py [--repo-root DIR] [--manifest PATH] [--item ID]

Exit 0: every checkable pin matches, or the item carries no citation (nothing
to revalidate; a present but malformed citation is still exit 2).  Exit 1: drift / missing / malformed
(each problem names the path and record).  Exit 2: usage or unreadable input.

On drift: mint a NEW verification record (never edit hashes of an old one) and
update the manifest citation, or remove the citation with a stated reason and
regenerate signoff/t1-report.json.

Pin categories (the declared input contract; unknown keys are rejected):
  repository file      "<repo-relative path>"          re-hashed
  decompressed         "<path> (decompressed)"         gunzip(<path>.gz) re-hashed
  record-local         baseline SDF + oracle trace     re-hashed from the run dir
  derived, not kept    other "derived SDF: ..." pins   present + well-formed only
  external (PDK)       "$PDK_LIBS_REF/..."             present + well-formed only
"""
import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_ITEM = "7.digital"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

# Mandatory repository-file pins: the inputs fv-sdf-cosim.py hashes (routed
# netlist, compressed SDF, STA report, P&R request, cocotb testbench, the
# timing harness itself, the RTL-cosim oracle).  digital/model/*.py is
# mandatory per file as it exists today, except STUDY_ONLY_MODELS.
REQUIRED_FILES = [
    "layout/trng_digital/trng_digital.routed.v",
    "layout/trng_digital/trng_digital.sdf.gz",
    "layout/trng_digital/sta.json",
    "digital/flow/place-and-route/pnr-trng-digital-50khz.json",
    "digital/tb/cocotb/test_trng_digital_fv.py",
    "sim/digital-rtl-equivalence/harness/rtl-cosim.py",
    "sim/digital-sdf-timed-verification/harness/fv-sdf-cosim.py",
]
MODEL_DIR = "digital/model"
# Deliberate, named exclusions from the MODEL_DIR pin rule (DR-0015): additive
# study models that are not part of the signed-off digital section (nothing in
# digital_top / the routed netlist imports them) and so cannot appear in an
# append-only signoff record.  Every other digital/model/*.py stays mandatory;
# a new model file is still a failure until it is pinned or listed here by an
# explicit, reviewed edit.
STUDY_ONLY_MODELS = frozenset({"lagcount.py"})
REQUIRED_DECOMPRESSED = ["layout/trng_digital/trng_digital.sdf (decompressed)"]
# pin key -> run-dir file holding its bytes
RECORD_LOCAL_SDF = {"derived SDF: baseline (uncompressed)": "trng_digital.baseline.sdf.gz"}
ORACLE_KEY = "model-observations.txt (oracle trace)"
ORACLE_FILE = "timed-declared.model-observations.txt"
REQUIRED_DERIVED = [f"derived SDF: {n} (uncompressed)"
                    for n in ("baseline", "mistargeted", "delay-shift", "delay-fail")]
REQUIRED_EXTERNAL = ["$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/primitives.v",
                     "$PDK_LIBS_REF/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"]


class Usage(Exception):
    pass


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise Usage(f"cannot read {path}: {e}")


def locate(root, manifest_path, item):
    """(report path, run dir, hashes path, record path) for the cited item, or
    None when the manifest carries no citation for it (the documented recovery
    path: citation removed, nothing active to revalidate)."""
    evidence = load_json(manifest_path).get("evidence", {})
    if not isinstance(evidence, dict):
        raise Usage(f"{manifest_path}: evidence is not an object")
    if item not in evidence:
        return None
    ev = evidence[item]
    cite = ev.get("file") if isinstance(ev, dict) else ev
    if isinstance(cite, list):
        cite = cite[0] if len(cite) == 1 else None
    if not isinstance(cite, str):
        raise Usage(f"{manifest_path}: evidence[{item!r}] is not a single cited file")
    report = root / cite
    run_dir = report.parent
    parts = Path(cite).parts
    if len(parts) < 4 or parts[0] != "sim" or parts[2] != "runs":
        raise Usage(f"{item} citation {cite} is not under sim/<slug>/runs/<record-id>/")
    record = root / "sim" / parts[1] / "records" / f"{parts[3]}.json"
    return report, run_dir, run_dir / "input-hashes.json", record


def check(root, manifest_path, item=DEFAULT_ITEM):
    """Returns (problems, notes)."""
    root = Path(root)
    problems, notes = [], []
    located = locate(root, manifest_path, item)
    if located is None:
        notes.append(f"no active evidence cited for {item}; nothing to revalidate")
        return problems, notes
    report, run_dir, hashes_path, record_path = located
    rid = run_dir.name
    tag = f"record {rid}"
    for p in (report, hashes_path):
        if not p.is_file():
            raise Usage(f"{tag}: {p.relative_to(root)} is missing")
    hashes = load_json(hashes_path)
    if not isinstance(hashes, dict):
        raise Usage(f"{tag}: input-hashes.json is not an object")

    # citation <-> record association
    if not record_path.is_file():
        problems.append(f"{tag}: no matching record {record_path.relative_to(root)}")
    else:
        rec = load_json(record_path)
        if rec.get("record_id") != rid:
            problems.append(f"{tag}: {record_path.relative_to(root)} has record_id "
                            f"{rec.get('record_id')!r}")
        if rec.get("input_hashes") != hashes:
            problems.append(f"{tag}: record input_hashes differ from the run's input-hashes.json")

    # declared contract: required pins present
    required = list(REQUIRED_FILES + REQUIRED_DECOMPRESSED + [ORACLE_KEY]
                    + REQUIRED_DERIVED + REQUIRED_EXTERNAL)
    required += sorted(p.relative_to(root).as_posix() for p in (root / MODEL_DIR).glob("*.py")
                       if p.name not in STUDY_ONLY_MODELS)
    for key in required:
        if key not in hashes:
            problems.append(f"{tag}: mandatory pin missing: {key}")

    for key, digest in hashes.items():
        if not isinstance(digest, str) or not DIGEST.match(digest):
            problems.append(f"{tag}: malformed digest for {key}: {digest!r}")
            continue
        if key.startswith("$"):
            notes.append(f"external, not revalidated (no PDK here): {key}")
        elif key in RECORD_LOCAL_SDF:
            _cmp(problems, tag, key, digest, run_dir / RECORD_LOCAL_SDF[key], root, gz=True)
        elif key == ORACLE_KEY:
            _cmp(problems, tag, key, digest, run_dir / ORACLE_FILE, root)
        elif key.startswith("derived SDF: ") and key.endswith(" (uncompressed)"):
            notes.append(f"derived artifact bytes not retained, not revalidated: {key}")
        elif key.endswith(" (decompressed)"):
            _cmp(problems, tag, key, digest, root / (key[: -len(" (decompressed)")] + ".gz"),
                 root, gz=True)
        elif "(" not in key and not key.startswith("/") and ".." not in Path(key).parts:
            _cmp(problems, tag, key, digest, root / key, root)
        else:
            problems.append(f"{tag}: pin {key!r} is outside the declared input contract")
    return problems, notes


def _cmp(problems, tag, key, digest, path, root, gz=False):
    try:
        data = path.read_bytes()
        if gz:
            data = gzip.decompress(data)
    except (OSError, EOFError, gzip.BadGzipFile) as e:
        problems.append(f"{tag}: {key}: cannot read {path.relative_to(root)}: {e}")
        return
    if sha(data) != digest:
        problems.append(f"{tag}: DRIFT {key}: recorded {digest[:19]}…, "
                        f"now {sha(data)[:19]}… ({path.relative_to(root)})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    default_root = Path(__file__).resolve().parents[2]
    ap.add_argument("--repo-root", type=Path, default=default_root)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--item", default=DEFAULT_ITEM)
    a = ap.parse_args(argv)
    manifest = a.manifest or a.repo_root / "signoff" / "block-manifest.json"
    try:
        problems, notes = check(a.repo_root, manifest, a.item)
    except Usage as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for n in notes:
        print(f"note: {n}")
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        print("The cited simulation record no longer describes the current inputs: mint a new "
              "verification record and update the manifest citation (or remove the citation "
              "with a reason and regenerate signoff/t1-report.json). Do not edit old hashes.",
              file=sys.stderr)
        return 1
    if any(n.startswith("no active evidence") for n in notes):
        return 0
    print(f"ok: {a.item} cited record's pins match the working tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
