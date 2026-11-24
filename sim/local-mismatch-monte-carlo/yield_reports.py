#!/usr/bin/env python3
"""`klt yield` reduction of the committed local-mismatch Monte Carlo (issue #598).

    yield_reports.py            # derive per-PVT-point sample sets, run `klt yield`,
                                # write yield/<record-id>/{samples,klt-yield}.json
    yield_reports.py --check    # replay: re-derive and re-run, byte-compare against
                                # the committed reports; exit 1 on any difference

Pure arithmetic over the committed `corners/<id>/` raw responses (the same loader
`reduce.py --check` uses); no simulator, no new Monte Carlo. The reported quantity
is `H_bias = -log2(max(p, 1-p))` over all n_array x n_sampler pairings -- reduce.py's
own statistic, recomputed with its own `duty_at`/`h_bias` and cross-checked against
the committed record before anything is written.

`H_bias` is an UPPER bound on the raw bit's min-entropy from static bias alone
(each draw is a deterministic transient, no injected noise): a sample below the
floor fails the spec row; a sample above it does not prove the row. The candidate
statistical row ("Raw min-entropy per bit", README target table -- DRAFT, its
decision records Proposed) fixes H0 = 0.5 bit/sample and states NO target yield,
so none is added here: `klt yield` can only report the estimates (status
"reported", never "fail"). `klt signoff` item 6 stays unmet on the row for
unratification alone (issue #598): the row is covered -- these untagged
reports assert the manifest's rows, and klayout-tools#5490 only ever
affected tagged measurements -- so ratifying the row would render the item
met on estimates that carry no yield claim and no negative control, which
the ratification decision (issue #3) should weigh. At tt / 27 C / 1.8 V,
60 of the 1800 pairings sit below the floor (worst H_bias 0.472,
p = 0.279) -- the row finding tracked in issue #221, recorded here, not
tuned.

Run under the pinned toolchain (the host `klt` carries no `klt_yield_native`):

    uvx --from "klayout-tools[yield]==0.8.0" \\
        python sim/local-mismatch-monte-carlo/yield_reports.py
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from loadmod import load_module  # noqa: E402  (after sys.path)
from evidence_record import read_corner_bundle  # noqa: E402

red = load_module("mm_reduce", os.path.join(HERE, "reduce.py"))

KLT = os.environ.get("KLT_YIELD", "klt")
MEAS = "h_bias_bit"
# The spec row as written: H0 = 0.5 bit/sample (DR-0004 sec. 2.3, README target
# table). No target yield is stated on the row and none is invented (issue #598).
H_FLOOR = red.H_FLOOR
KLT_PIN = "klayout-tools[yield]==0.8.0"


def records():
    """Committed campaign records (this slug only), in record-id order."""
    rdir = os.path.join(HERE, "records")
    out = []
    for fn in sorted(os.listdir(rdir)):
        if fn.endswith(".json"):
            out.append(fn[:-len(".json")])
    return out


def derive(rid):
    """-> (sample-set document dict, summary S) from the committed raw responses.

    Refuses to write anything if the raw responses no longer replay to the
    committed record (the same guarantee `reduce.py --check` gives) or if the
    derived pairings disagree with the record's own raw-bit statistics.
    """
    rec = json.loads(Path(HERE, "records", rid + ".json").read_text())
    chunks = read_corner_bundle(__import__("pathlib").Path(os.path.join(HERE, "corners", rid)))
    by = red.build(chunks)
    corner = rec["summary"]["corner"]
    if corner not in by:
        raise SystemExit(f"{rid}: corner bundle has {sorted(by)}, record says {corner}")
    rows, S = by[corner]
    if json.loads(json.dumps(S, default=str)) != json.loads(json.dumps(rec["summary"], default=str)):
        raise SystemExit(f"{rid}: raw responses no longer replay to the committed record; "
                         "run reduce.py --check to diagnose before reducing into klt yield")
    vnom = S["pvt"]["vnom"]
    good_a = [r for r in rows if "duty" in r and r.get("ok")]
    good_s = [r for r in rows if "vtrip_v" in r and r.get("ok")]
    if len(good_a) != S["n_array_ok"] or len(good_s) != S["n_sampler_ok"]:
        raise SystemExit(f"{rid}: row kind counts disagree with the summary")
    p_all, samples = pairing_samples(rows, vnom)
    crosscheck(rid, p_all, samples, S)
    doc = build_doc(rid, rec, S, samples)
    return doc, S


def pairing_samples(rows, vnom):
    """-> (p_all, H_bias samples) over all array x sampler pairings.

    The pairing loop of reduce.summarize's raw_bit block, on its own functions:
    p_ij = duty of draw i at sampler j's threshold, in summarize's iteration
    order (array outer, sampler inner), so the sample list is identical in
    construction to the statistics the record carries.
    """
    good_a = [r for r in rows if "duty" in r and r.get("ok")]
    good_s = [r for r in rows if "vtrip_v" in r and r.get("ok")]
    p_all, samples = [], []
    for a in good_a:
        d = {int(k): v for k, v in a["duty"].items()}
        for s in good_s:
            p = red.duty_at(d, s["vtrip_v"] / vnom)
            p_all.append(p)
            samples.append(red.h_bias(p))
    return p_all, samples


def crosscheck(rid, p_all, samples, S):
    """Refuse unless the derived pairings reproduce the record's raw_bit stats."""
    R = S["raw_bit"]
    worst_p = max(p_all, key=lambda p: abs(p - 0.5))
    if (len(samples) != R["n_pairings"]
            or abs(min(samples) - R["h_bias_min"]) > 1e-12
            or sum(h < H_FLOOR for h in samples) != R["n_pairings_below_floor"]
            or abs(worst_p - R["worst_case"]["p1"]) > 1e-12
            or abs(min(p_all) - R["p1_all"]["min"]) > 1e-12
            or abs(max(p_all) - R["p1_all"]["max"]) > 1e-12):
        raise SystemExit(f"{rid}: derived pairings disagree with the record's raw_bit statistics")


def build_doc(rid, rec, S, samples):
    """The per-PVT-point sample-set document (additive `derivation` block included)."""
    return {
        "schema_version": 1,
        "measurements": [
            {
                "name": MEAS,
                "unit": "bit",
                "samples": samples,
                "limits": {"min": H_FLOOR},
                "source_corners": [f"{S['pvt']['proc']}/{S['pvt']['vnom']:g}V/{S['pvt']['temp']:g}C"],
            }
        ],
        "derivation": {
            "tool": "sim/local-mismatch-monte-carlo/yield_reports.py",
            "pinned_klt": KLT_PIN,
            "campaign_record": f"sim/{red.SLUG}/records/{rid}.json",
            "raw_responses": f"sim/{red.SLUG}/corners/{rid}/",
            "quantity": ("H_bias = -log2(max(p,1-p)), p = duty of xo above the sampler's own "
                         "(mismatch-moved) threshold, interpolated from the nine comparator duties, "
                         "one sample per array x sampler pairing (independent devices; every pairing "
                         "is a legitimate draw). H_bias is an UPPER bound on the raw bit's "
                         "min-entropy from static bias alone -- a deterministic transient per draw, "
                         "no injected noise -- NOT the measured row quantity: a sample below the "
                         "floor fails the row, a sample above it does not prove it."),
            "spec_row": {"row": "Raw min-entropy per bit",
                         "limits": {"min": H_FLOOR},
                         "target_yield": None,
                         "status": ("README target table is DRAFT and its decision records "
                                    "(DR-0004 sec. 2.3) are Proposed; the row states no target "
                                    "yield and none is added (issue #598)")},
            "seeds": {"array": S["seeds_array"], "sampler": S["seeds_sampler"],
                      "per_sample": f"in the campaign record rows (sim/{red.SLUG}/records/{rid}.json)",
                      "rule": rec["seed"]["rule"]},
            "n_array": S["n_array_ok"], "n_sampler": S["n_sampler_ok"], "n_pairings": len(samples),
            "negative_control": ("the campaign's deterministic mismatch-free reference units "
                                 "(arr0/smp0, plain sections) of the same decks, one per corner, "
                                 f"committed under sim/{red.SLUG}/corners/{rid}/ and recorded in the "
                                 "campaign record; mismatch absent, the statistic stays clean "
                                 "(nominal H_bias >= 0.74 at every corner). They are not a "
                                 "seeded-defect variant, so they are not expressible as klt yield's "
                                 "negative_control field (which requires a known-bad variant that "
                                 "must show up as degraded yield); a defect-injection campaign is "
                                 "follow-up work."),
            "pvt": S["pvt"],
        },
    }


def dump(doc):
    return (json.dumps(doc, indent=1) + "\n").encode()


def rel(rid, fn):
    return f"sim/{red.SLUG}/yield/{rid}/{fn}"


def run_klt_yield(rid):
    """Run the pinned `klt yield` on the committed samples path; -> report bytes."""
    if shutil.which(KLT) is None:
        raise SystemExit(f"'{KLT}' not found; run under the pinned toolchain, e.g. "
                         f"uvx --from \"{KLT_PIN}\" python sim/{red.SLUG}/yield_reports.py")
    # Repo-relative samples path (cwd=REPO) so the report's `samples` echo is a
    # committed-artifact-safe relative path (docs/json-contract.md) that
    # `klt signoff` resolves from the repo root.
    proc = subprocess.run([KLT, "yield", rel(rid, "samples.json"), "--format", "json"],
                          cwd=REPO, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode(errors="replace"))
        raise SystemExit(f"{rid}: klt yield exited {proc.returncode}")
    return proc.stdout


def validate_report(rid, report_bytes, doc):
    r = json.loads(report_bytes)
    if r.get("samples") != rel(rid, "samples.json"):
        raise SystemExit(f"{rid}: report names samples {r.get('samples')!r}; re-run from the repo root")
    if r.get("measurement_count") != 1 or r["measurements"][0]["name"] != MEAS:
        raise SystemExit(f"{rid}: expected exactly the {MEAS} measurement")
    m = r["measurements"][0]
    if m["limits"].get("min") != H_FLOOR or "target_yield" in m["limits"]:
        raise SystemExit(f"{rid}: merged limits are {m['limits']}; the row states min 0.5 and no target yield")
    if m["n"] != doc["derivation"]["n_pairings"]:
        raise SystemExit(f"{rid}: klt analysed n={m['n']}, expected {doc['derivation']['n_pairings']}")
    if r["status"] not in ("pass", "reported"):
        raise SystemExit(f"{rid}: unexpected run status {r['status']!r}")
    return r


def emit():
    for rid in records():
        doc, S = derive(rid)
        ydir = os.path.join(HERE, "yield", rid)
        os.makedirs(ydir, exist_ok=True)
        with open(os.path.join(ydir, "samples.json"), "wb") as fh:
            fh.write(dump(doc))
        report = run_klt_yield(rid)
        validate_report(rid, report, doc)
        with open(os.path.join(ydir, "klt-yield.json"), "wb") as fh:
            fh.write(report)
        m = json.loads(report)["measurements"][0]
        print(f"{rid} {S['corner']}: "
              f"n={m['n']} empirical={m['yield']['empirical']['estimate']:.6f} "
              f"CI=[{m['yield']['empirical']['confidence_interval']['low']:.6f}, "
              f"{m['yield']['empirical']['confidence_interval']['high']:.6f}] "
              f"sample_size={m['sample_size']['verdict']} status={m['status']} "
              f"(run status {json.loads(report)['status']})")


def check():
    ok = True
    for rid in records():
        doc, _ = derive(rid)
        spath = os.path.join(HERE, "yield", rid, "samples.json")
        rpath = os.path.join(HERE, "yield", rid, "klt-yield.json")
        for path, want, what in ((spath, dump(doc), "samples"),
                                 (rpath, run_klt_yield(rid), "report")):
            have = open(path, "rb").read() if os.path.isfile(path) else None
            same = have == want
            ok &= same
            print(f"{rid} {what:8s} {'MATCHES' if same else 'DIFFERS'} {os.path.relpath(path, REPO)}")
            if not same and have is not None:
                validate_report(rid, want, doc)
    print("replay", "MATCHES" if ok else "DIFFERS")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) == 1:
        emit()
    elif len(sys.argv) == 2 and sys.argv[1] == "--check":
        sys.exit(check())
    else:
        print(__doc__)
        sys.exit(2)
