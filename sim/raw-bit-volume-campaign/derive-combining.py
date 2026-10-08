#!/usr/bin/env python3
"""Turn `klt sim` batch responses for the combining deck (make-requests.py
--deck combining, issue #197) into append-only `ro-array-core-combining`
records, in the same JSON shape the 20260825-0945*/0947*/0948* records use, so
behavioral_raw_bit.calibration() consumes them unchanged.

    derive-combining.py REQDIR [--points 125:1.62,125:1.8,125:1.98] [--sha SHA]

REQDIR holds p1..pN/resp.json in the order of --points. The deck's own `let`
figures are recomputed here with the deck's formulas (klt sim `expr` cannot read
top-level .meas results). The raw response is kept at
sim/ro-array-core-combining/corners/<id>/klt-sim.json. A failed corner is
recorded with ok=false and its diagnostics -- never dropped.
"""
import datetime, importlib.util, json, os, sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SLUG = "ro-array-core-combining"
TB = "sim/ro-array-core-combining/testbench/tb_ro_array_core.spice"
sys.path.insert(0, os.path.join(REPO, "sim", "bin"))
from evidence_record import git_short_sha  # noqa: E402

_s = importlib.util.spec_from_file_location("make_requests", os.path.join(os.path.dirname(__file__), "make-requests.py"))
mr = importlib.util.module_from_spec(_s)
_s.loader.exec_module(mr)


def derive(m, vdd):
    """The deck's .control `let` block, verbatim formulas. KeyError if a raw
    measurement is missing (a failed .meas must not be papered over)."""
    d = dict(m)
    for i in (1, 2, 3, 4):
        d[f"tr{i}"] = (m[f"t{i}b"] - m[f"t{i}a"]) / 10
    d["f_ideal2"] = 1 / d["tr1"] + 1 / d["tr2"]
    d["f_ideal"] = sum(1 / d[f"tr{i}"] for i in (1, 2, 3, 4))
    d["skew_span"] = d["tr1"] / d["tr4"]
    d["swing_frac_xo"] = (m["vxo_max"] - m["vxo_min"]) / vdd
    d["f_xo"] = 48 / (m["txo_b"] - m["txo_a"])
    d["edge_retention"] = d["f_xo"] / d["f_ideal"]
    d["f_t1"] = 48 / (m["tt1b"] - m["tt1a"])
    d["retention_n2"] = d["f_t1"] / d["f_ideal2"]
    d["retention_n4"] = d["edge_retention"]
    d["bias_xo"] = m["vxo_avg"] / vdd
    d["bias_t1"] = m["vt1_avg"] / vdd
    d["i_rings"] = -(m["i1"] + m["i2"] + m["i3"] + m["i4"])
    d["i_block"] = -m["ib"]
    d["i_array_total"] = d["i_rings"] + d["i_block"]
    d["p_array_total"] = d["i_array_total"] * vdd
    return d


def main(reqdir, points, sha):
    now = datetime.datetime.now(datetime.timezone.utc)
    for n, (t, v) in enumerate(points, 1):
        resp = json.load(open(f"{reqdir}/p{n}/resp.json"))
        rid = (now + datetime.timedelta(seconds=n)).strftime("%Y%m%d-%H%M%S") + "-" + sha
        corners = []
        for c in resp["corners"]:
            ok = c["status"] == "pass"
            raw = {x["name"]: x["value"] for x in c["measurements"] if x.get("value") is not None}
            try:
                meas = derive(raw, v)
            except (KeyError, ZeroDivisionError) as e:
                meas, ok = raw, False
                c = dict(c, diagnostics=list(c.get("diagnostics", [])) + [{"message": f"derive failed: {e!r}"}])
            corners.append({"corner": c["process"], "ok": ok, "status": c["status"], "measurements": meas,
                            "problems": [x["message"] for x in c.get("diagnostics", [])]})
        env = resp["environment"]
        rec = {
            "record_id": rid, "slug": SLUG,
            "claim": "ro_array_core combining/frequency-ladder/current deck, unmodified, run as a klt sim batch request at the 125 degC hot end of the operating envelope (issue #197), to complete the hot calibration of the raw-bit volume campaign",
            "level": "transistor", "seed": "N/A (deterministic transient)",
            "pvt": {"temp_c": t, "vdd_v": v},
            "tran": {"tmax": mr.COMB_TMAX, "stop": mr.COMB_STOP},
            "testbench": TB + " (via sim/raw-bit-volume-campaign/make-requests.py --deck combining)",
            "supersedes": "(none)",
            "klt_sim": {"job_id": env["remote"]["job_id"], "backend": "batch", "remote": env["remote"],
                        "engine_version": env["engine_version"], "models_lib_sha256": env["models_lib_sha256"],
                        "netlist_sha256": env["netlist_sha256"], "submitter_klt": resp["provenance"]["klt_version"],
                        "response": f"sim/{SLUG}/corners/{rid}/klt-sim.json"},
            "overall": "PASS" if resp["status"] == "pass" and all(c["ok"] for c in corners) else "FAIL",
            "corners": corners,
            "timestamp_utc": now.isoformat(),
        }
        cdir = os.path.join(REPO, "sim", SLUG, "corners", rid)
        rdir = os.path.join(REPO, "sim", SLUG, "records")
        if os.path.exists(os.path.join(rdir, rid + ".json")) or os.path.exists(cdir):
            raise SystemExit(f"error: {rid} exists")
        os.makedirs(cdir)
        json.dump(resp, open(os.path.join(cdir, "klt-sim.json"), "w"), indent=1)
        json.dump(rec, open(os.path.join(rdir, rid + ".json"), "w"), indent=2)
        L = [f"# {rid} -- {SLUG}", "",
             f"**Claim**: {rec['claim']}", "", "**Level**: transistor",
             f"**PVT point**: {t:g} degC, {v:g} V (tt/ss/ff bundled). **Verdict**: {rec['overall']} (klt sim status `{resp['status']}`).",
             f"**Testbench**: `{rec['testbench']}` (deck unmodified; `@@TMAX@@` = {mr.COMB_TMAX}, stop {mr.COMB_STOP}).",
             f"**Batch job**: `{env['remote']['job_id']}` ({env['remote']['instance_type']}, {env['remote']['lifecycle']}), ngspice {env['engine_version']}; submitter klt `{resp['provenance']['klt_version']}`.",
             "", "| corner | status | tr1 (ns) | tr2 | tr3 | tr4 | skew_span | edge_retention | retention_n2 | bias_xo | i_array_total (uA) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
        for c in corners:
            m = c["measurements"]
            if "tr1" in m and "i_array_total" in m:
                L.append(f"| {c['corner']} | {c['status']} | " + " | ".join(f"{m[k]*1e9:.4f}" for k in ("tr1", "tr2", "tr3", "tr4"))
                         + f" | {m['skew_span']:.4f} | {m['edge_retention']:.4f} | {m['retention_n2']:.4f} | {m['bias_xo']:.4f} | {m['i_array_total']*1e6:.2f} |")
            else:
                L.append(f"| {c['corner']} | **{c['status']}** | no usable measurements: {c['problems']} |")
        L += ["", "Simulation-derived; provisional until silicon. Derived figures use the deck's own `let` formulas "
              "(recomputed by `derive-combining.py`).", "", "---", "", "- Author: loom-builder@sky130-trng",
              f"- Timestamp (UTC): {now.isoformat()}", f"- Repo commit: `{sha}`", "- Supersedes: (none)"]
        open(os.path.join(rdir, rid + ".md"), "w").write("\n".join(L) + "\n")
        print(rid, rec["overall"], env["remote"]["job_id"])


if __name__ == "__main__":
    a = sys.argv
    pts = mr.parse_points(a[a.index("--points") + 1]) if "--points" in a else mr.HOT_POINTS
    main(a[1], pts, a[a.index("--sha") + 1] if "--sha" in a else git_short_sha(__import__("pathlib").Path(REPO)))
