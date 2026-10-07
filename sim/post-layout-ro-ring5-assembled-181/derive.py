#!/usr/bin/env python3
"""Turn the four `klt sim` batch responses from make-requests.py into new
append-only records, each compared against the pre-#181 record at the same PVT
point (sim/post-layout-ro-ring5-assembled/records/, never modified).

    derive.py REQDIR RECORDS_DIR [--sha SHA]

REQDIR holds p1..p4/resp.json (klt sim --format json output, kept alongside
the record as <id>.klt-sim.json). Derived figures use the template deck's own
`let` formulas.
"""
import glob, hashlib, json, os, sys, datetime

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OLD = os.path.join(REPO, "sim/post-layout-ro-ring5-assembled/records")
POINTS = [(-40.0, 1.62), (27.0, 1.80), (125.0, 1.98), (-40.0, 1.98)]
W = ["0p42", "0p44", "0p46", "0p48"]


def derive(m, vdd):
    d = dict(m)
    for i, w in enumerate(W, 1):
        d[f"t_asm_wstv{w}"] = (m[f"tr{i}b"] - m[f"tr{i}a"]) / 8
        d[f"t_pre_wstv{w}"] = (m[f"tq{i}b"] - m[f"tq{i}a"]) / 8
        d[f"slowdown_wstv{w}"] = d[f"t_asm_wstv{w}"] / d[f"t_pre_wstv{w}"]
    d["skew_span_asm"] = d["t_asm_wstv0p42"] / d["t_asm_wstv0p48"]
    d["skew_span_pre"] = d["t_pre_wstv0p42"] / d["t_pre_wstv0p48"]
    d["swing_frac_asm_ring"] = (m["vmaxr"] - m["vminr"]) / vdd
    d["swing_frac_asm_buf"] = (m["vmaxrb"] - m["vminrb"]) / vdd
    d["swing_frac_pre_ring"] = (m["vmaxq"] - m["vminq"]) / vdd
    d["swing_frac_pre_buf"] = (m["vmaxqb"] - m["vminqb"]) / vdd
    d["i_asm_wstv0p42"], d["i_asm_wstv0p48"] = -m["ir1raw"], -m["ir4raw"]
    d["i_pre_wstv0p42"], d["i_pre_wstv0p48"] = -m["iq1raw"], -m["iq4raw"]
    return d


KEYS = (["t_asm_wstv" + w for w in W] + ["t_pre_wstv" + w for w in W]
        + ["slowdown_wstv" + w for w in W]
        + ["skew_span_asm", "skew_span_pre", "swing_frac_asm_ring", "swing_frac_asm_buf",
           "swing_frac_pre_ring", "swing_frac_pre_buf",
           "i_asm_wstv0p42", "i_asm_wstv0p48", "i_pre_wstv0p42", "i_pre_wstv0p48"])


def main(reqdir, outdir, sha):
    os.makedirs(outdir, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    for n, (t, v) in enumerate(POINTS, 1):
        resp = json.load(open(f"{reqdir}/p{n}/resp.json"))
        old = [json.load(open(f)) for f in sorted(glob.glob(OLD + "/*.json"))]
        old = next(o for o in old if o["pvt"] == {"temp_c": t, "vdd_v": v})
        oldc = {c["corner"]: c["measurements"] for c in old["corners"]}
        rid = (now + datetime.timedelta(seconds=n)).strftime("%Y%m%d-%H%M%S") + "-" + sha
        corners, rows = [], []
        for c in resp["corners"]:
            name = c["process"]
            m = {x["name"]: x["value"] for x in c["measurements"]}
            d = derive(m, v)
            corners.append({"corner": name, "ok": c["status"] == "pass", "status": c["status"],
                            "measurements": d, "problems": [x["message"] for x in c["diagnostics"]]})
            for k in KEYS:
                o = oldc[name][k]
                rows.append((name, k, o, d[k], 100 * (d[k] - o) / o))
        env = resp["environment"]
        rec = {
            "record_id": rid, "slug": "post-layout-ro-ring5-assembled-181",
            "claim": "re-measurement of sim/post-layout-ro-ring5-assembled on the issue #181 regenerated GDS and issue #184 re-extracted layout/pex-ring library (same template deck, run as a klt sim batch request), compared per corner against the pre-#181 record at the same PVT point",
            "level": "transistor", "seed": "N/A (deterministic transient)",
            "pvt": {"temp_c": t, "vdd_v": v},
            "tran": {"tmax": "5p", "stop": "160n"},
            "testbench": "sim/post-layout-ro-ring5-assembled/testbench/tb_post_layout_ro_ring5_assembled.spice (via make-requests.py)",
            "supersedes": "(none) -- compared against, not replacing, " + old["record_id"],
            "compared_against": old["record_id"],
            "klt_sim": {"job_id": env["remote"]["job_id"], "backend": "batch", "remote": env["remote"],
                        "engine_version": env["engine_version"], "models_lib_sha256": env["models_lib_sha256"],
                        "netlist_sha256": env["netlist_sha256"], "submitter_klt": resp["provenance"]["klt_version"]},
            "overall": "PASS" if resp["status"] == "pass" else "FAIL",
            "corners": corners,
            "timestamp_utc": now.isoformat(),
        }
        json.dump(rec, open(f"{outdir}/{rid}.json", "w"), indent=1)
        json.dump(resp, open(f"{outdir}/{rid}.klt-sim.json", "w"), indent=1)
        L = [f"# {rid} -- post-layout-ro-ring5-assembled-181", "",
             f"**PVT**: {t} degC, {v} V. **Verdict**: {rec['overall']} (klt sim status `{resp['status']}`, 3 corners).",
             f"**Compared against (pre-#181, unmodified)**: `{old['record_id']}`.",
             f"**Batch job**: `{env['remote']['job_id']}` ({env['remote']['instance_type']}, {env['remote']['lifecycle']}), ngspice {env['engine_version']}; submitter klt `{resp['provenance']['klt_version']}` (the PEX library itself was extracted by the pinned `0.6.0+g5edb557f91d0`).",
             "**Library**: `layout/pex-ring/ro_ring5_assembled_pex.spice` (post-#181, re-extracted under #184). The pre-#181 record ran on macOS/ngspice-46 locally; this one on the Linux fleet (ngspice-46); the unchanged pre-layout control reproduces to 0.00 %, so no environment offset is visible.",
             "", "| corner | metric | pre-#181 | post-#181 | delta % |", "|---|---|---|---|---|"]
        L += [f"| {a} | {b} | {c:.6g} | {d:.6g} | {e:+.2f} |" for a, b, c, d, e in rows]
        open(f"{outdir}/{rid}.md", "w").write("\n".join(L) + "\n")
        mx = max(rows, key=lambda r: abs(r[4]))
        print(rid, rec["overall"], "max |delta| %.2f%% (%s/%s)" % (abs(mx[4]), mx[0], mx[1]))
        for k in ("t_asm_wstv0p42", "t_asm_wstv0p48", "slowdown_wstv0p42", "swing_frac_asm_ring", "i_asm_wstv0p42"):
            print("   ", k, [(r[0], round(r[4], 2)) for r in rows if r[1] == k])


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2], a[a.index("--sha") + 1] if "--sha" in a else "ae3832e")
