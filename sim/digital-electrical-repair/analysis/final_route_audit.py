#!/usr/bin/env python3
"""Final-route max-slew / max-capacitance audit (issue #236).

klt 0.6.0 / 0.7.0 `klt sta` and the post-route SPEF path report slack, TNS
and skew only; no installed klt command checks Liberty slew/capacitance
against the extracted post-route SPEF. This script runs a sibling, fresh
OpenSTA session (OpenROAD, the same digest-pinned container wrapper that klt
itself uses; no host tool is changed) per Liberty corner over the *archived*
routed DEF + post-route SPEF of a run directory:

    read_lef (tech) ; read_lef (cells) ; read_def ; read_liberty <corner> ;
    create_clock ; read_spef ; report_check_types -max_slew/-max_capacitance
    -violators -digits 4

and reduces the result through ``electrical.reduce_evidence``. It does not
apply any `set_max_*` override: the checked limits are the Liberty limits
(library ``default_max_transition`` and per-pin ``max_capacitance``). No
`set_load` / `set_driving_cell` exists in the flow's constraint set, so
port loading/driving are whatever OpenSTA defaults to (zero); that is
recorded, not hidden.

Output: <run-dir>/electrical-audit.json (+ raw per-corner logs under
<run-dir>/electrical-audit/). A corner whose session fails is `unsupported`
(session error) -- never silently zero.
"""
from __future__ import annotations

import argparse, gzip, json, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import electrical as E  # noqa: E402

ROOT = HERE.parents[2]


def gunzip(src: Path, dst: Path) -> None:
    with gzip.open(src, "rb") as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)


def tcl(corner, tlef, lef, deff, spef, libdir, cons):
    return f"""read_lef {tlef}
read_lef {lef}
read_def {deff}
read_liberty {libdir}/sky130_fd_sc_hd__{corner}.lib
create_clock -name {cons['clock_port']} -period {cons['clock_period_ns']} [get_ports {cons['clock_port']}]
read_spef {spef}
puts "===KLT_AUDIT_SLEW_BEGIN==="
report_check_types -max_slew -violators -digits 4
puts "===KLT_AUDIT_SLEW_END==="
puts "===KLT_AUDIT_CAP_BEGIN==="
report_check_types -max_capacitance -violators -digits 4
puts "===KLT_AUDIT_CAP_END==="
puts "===KLT_AUDIT_SLEW_WORST_BEGIN==="
report_check_types -max_slew -digits 4
puts "===KLT_AUDIT_SLEW_WORST_END==="
puts "===KLT_AUDIT_CAP_WORST_BEGIN==="
report_check_types -max_capacitance -digits 4
puts "===KLT_AUDIT_CAP_WORST_END==="
set_max_transition 0.0001 [current_design]
puts "===KLT_AUDIT_SENS_BEGIN==="
report_check_types -max_slew -violators -digits 4
puts "===KLT_AUDIT_SENS_END==="
puts "===KLT_AUDIT_DONE==="
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--klt", default="klt")
    ap.add_argument("--request", type=Path, default=None,
                    help="default: <repo>/sim/digital-electrical-repair/requests/<run-dir name>.json")
    a = ap.parse_args(argv)
    rd = a.run_dir.resolve()
    req = (a.request.resolve() if a.request else None) or ROOT / "sim/digital-electrical-repair/requests" / f"{rd.name}.json"
    cons = json.loads(req.read_text())["constraints"]
    pnr = json.loads((rd / "pnr-output.json").read_text())
    corners = [c["name"] for c in pnr["corners"]]
    env = {**os.environ, "PDK": "sky130A"}
    if "PDK_ROOT" not in env:
        out = subprocess.run([a.klt, "pdk", "find", "--pdk", "sky130A", "--format", "json"],
                             capture_output=True, text=True, check=True, cwd=ROOT)
        env["PDK_ROOT"] = json.loads(out.stdout)["root"]
    ref = Path(env["PDK_ROOT"]) / "sky130A" / "libs.ref" / "sky130_fd_sc_hd"
    tmp = ROOT / f".audit-tmp-{rd.parent.name}-{rd.name}"
    tmp.mkdir(exist_ok=True)
    deff, spef = tmp / "r.def", tmp / "r.spef"
    gunzip(rd / "trng_digital.def.gz", deff)
    gunzip(rd / "trng_digital_route.spef.gz", spef)
    logs = rd / "electrical-audit"
    logs.mkdir(exist_ok=True)
    per, raw = {}, {}
    for c in corners:
        script = tmp / f"audit_{c}.tcl"
        script.write_text(tcl(c, ref / "techlef/sky130_fd_sc_hd__nom.tlef",
                              ref / "lef/sky130_fd_sc_hd.lef", deff, spef,
                              ref / "lib", cons))
        p = subprocess.run(["openroad", "-no_splash", "-exit", str(script)],
                           capture_output=True, text=True, cwd=ROOT, env=env)
        # the sensitivity listing (every pin, ~7400 rows) is summarised, not stored
        keep = re.sub(r"(===KLT_AUDIT_SENS_BEGIN===\n).*?(===KLT_AUDIT_SENS_END===)",
                      r"\1<pin rows omitted; count recorded in electrical-audit.json>\n\2", p.stdout, flags=re.S)
        with gzip.GzipFile(filename="", mode="wb", fileobj=open(logs / f"{c}.log.gz", "wb"), mtime=0) as fo:
            fo.write((keep + ("\n--stderr--\n" + p.stderr if p.stderr else "")).encode())
        if p.returncode != 0 or "===KLT_AUDIT_DONE===" not in p.stdout:
            per[c] = {"status": "unsupported",
                      "reason": f"OpenSTA session failed rc={p.returncode}"}
            continue
        sl = E.block(p.stdout, "AUDIT_SLEW")
        cp = E.block(p.stdout, "AUDIT_CAP")
        if sl is None or cp is None:
            per[c] = {"status": "unsupported", "reason": "report blocks absent"}
            continue
        sens = E.block(p.stdout, "AUDIT_SENS")
        n_sens = len(E.parse_violators(sens)) if sens is not None else 0
        if n_sens == 0:
            per[c] = {"status": "unsupported",
                      "reason": "sensitivity probe (SDC limit forced to 0.0001 ns) listed no pins: the session cannot see slews"}
            continue
        worst = {}
        for cls, tag in (("max_slew", "AUDIT_SLEW_WORST"), ("max_capacitance", "AUDIT_CAP_WORST")):
            wb = E.block(p.stdout, tag)
            wm = E.parse_margin(wb) if wb is not None else None
            if wm is None:
                worst = None
                break
            worst[cls] = wm
        if worst is None:
            per[c] = {"status": "unsupported", "reason": "worst-margin report absent or unparsable"}
            continue
        rows = {"max_slew": E.parse_violators(sl), "max_capacitance": E.parse_violators(cp)}
        # guard: the text must not contain more VIOLATED lines than parsed
        for cls, txt in (("max_slew", sl), ("max_capacitance", cp)):
            if txt.count("(VIOLATED)") != len(rows[cls]):
                per[c] = {"status": "unsupported", "reason": f"{cls}: unparsed VIOLATED rows"}
                break
        else:
            per[c] = {"status": "audited", "sensitivity_pins_listed": n_sens,
                      **{k: {**E.summarise(v), "worst_margin": worst[k]} for k, v in rows.items()}}
            raw[c] = rows
    shutil.rmtree(tmp, ignore_errors=True)
    red = E.reduce_evidence(corners, per, "final")
    res = {"schema": "sky130-trng.electrical-audit/1",
           "stage": "final route: routed DEF + extracted post-route SPEF, fresh OpenSTA session per corner",
           "limits_checked": "Liberty default_max_transition (ns) and per-pin max_capacitance (pF); no set_max_* override; no set_load/set_driving_cell",
           "units": {"slew": "ns", "capacitance": "pF"},
           "request": str(req.relative_to(ROOT)), "corners": per, "reduction": red,
           "violators": raw}
    (rd / "electrical-audit.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(red))
    return 0


if __name__ == "__main__":
    sys.exit(main())
