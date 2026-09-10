#!/usr/bin/env python3
"""Synthesize `digital/rtl/trng_digital.v` against `sky130_fd_sc_hd`, gate the
result through `klt equiv`, re-run the RTL-equivalence stimulus program
against the mapped netlist, and mint the first `level: gate` evidence
record (`sim/digital-synthesis/records/`).

This is the harness `digital/README.md`/DR-0004's follow-up list/
`docs/chipalooza/challenge-4-proposal.md` row G all point at -- see
`spec/decision-records/DR-0004-sky130-digital-section-architecture.md`
"Follow-up required" and issue #117.

Runs (per `digital/flow/*/synthesize-trng-digital*.json`):

1. `klt synthesize` -- unconstrained (`clock_period_ns: null`, the
   reproducible cell-count baseline) and constrained at this design's own
   50 kHz sample clock (`clock_period_ns: 20000`) -- for each: cell count,
   area, ABC's pre-layout `timing.critical_path_ps` estimate.
2. Leakage at `tt_025C_1v80`, summed from the same Liberty file
   `klt synthesize` itself resolved (`liberty_leakage.py` -- `klt
   synthesize`'s own response has no leakage field; see that module's
   docstring and the friction issue it cites).
3. `klt equiv` (`"yosys-sequential"` engine -- the design has flip-flops,
   so the default combinational engine is a hard scope error) proving RTL
   <-> gate equivalence, for both netlists.
4. `sim/digital-rtl-equivalence/harness/rtl-cosim.py`'s own directed
   stimulus program and normative-model trace, re-run against each mapped
   netlist via Icarus + the `sky130_fd_sc_hd` Verilog cell models
   (`gate_cosim.py`).

Requires: `klt` (>= 0.4.0, `sky130_fd_sc_hd` + `yosys-sequential`
support), a native `yosys` on `$PATH` (not a YoWASP build -- see
`docs/cli/synthesize.md`'s "Which yosys matters"), `iverilog`, and an
installed `sky130A` PDK (`sim/pdk.json`'s pin).

Usage::

    python3 sim/digital-synthesis/harness/synthesize-and-verify.py
    python3 sim/digital-synthesis/harness/synthesize-and-verify.py --emit-record
    python3 sim/digital-synthesis/harness/synthesize-and-verify.py --skip-equiv  # fast iteration; no level:gate record without it
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HOME = Path.home().resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

import gate_cosim  # noqa: E402
import liberty_leakage as ll  # noqa: E402
from evidence_record import mint_behavioral_record  # noqa: E402

DEFAULT_SEED = 20260905

_EXTERNAL_PATH_MARKER = ("<external -- not recorded by absolute location; "
                         "see this record's PDK name/version and deck "
                         "content_hash instead>")


def _sanitize_paths(obj, repo_root: Path = REPO_ROOT, home: Path = HOME):
    """Recursively rewrite absolute-path-shaped strings for permanent,
    committed evidence.

    ``docs/design-evidence-tiers.md``'s "Provenance hygiene in evidence
    records" section (`klt env-provenance`'s own reference discipline,
    already followed by this repo's ``layout/bin/_klt_common.py``, issue
    #49) is the rule this implements: a path *inside* this repo is recorded
    repo-relative; a path *outside* it (a PDK install under the operator's
    home directory, a scratch dir, anything else home-shaped) is not
    recorded by absolute location at all -- an external input is pinned by
    **identity** (the PDK name/version and Liberty deck ``content_hash``
    this same record already carries), not by where it happened to sit on
    one machine. `klt synthesize`/`klt equiv`'s own JSON responses always
    resolve to absolute paths regardless of how the request was invoked
    (verified directly), so this is a necessary post-processing step, not a
    cwd/invocation trick -- applied only to the copies written into
    committed artifacts/the record body, never to the live paths this
    harness itself still needs to open files with.
    """
    if isinstance(obj, str) and obj.startswith("/"):
        p = Path(obj)
        try:
            return str(p.resolve().relative_to(repo_root))
        except ValueError:
            pass
        try:
            p.resolve().relative_to(home)
            return _EXTERNAL_PATH_MARKER
        except ValueError:
            pass
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_paths(v, repo_root, home) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_paths(v, repo_root, home) for v in obj]
    return obj


def _display_path(path, repo_root: Path = REPO_ROOT, home: Path = HOME) -> str:
    """Sanitized string form of a single path, for inline report text."""
    return _sanitize_paths(str(path), repo_root, home)

CONFIGS = [
    {
        "label": "unconstrained",
        "request": REPO_ROOT / "digital" / "flow" / "unconstrained" /
                   "synthesize-trng-digital.json",
        "clock_period_ns": None,
    },
    {
        "label": "50khz-constrained",
        "request": REPO_ROOT / "digital" / "flow" / "constrained-50khz" /
                   "synthesize-trng-digital-50khz.json",
        "clock_period_ns": 20000.0,
    },
]

RTL = REPO_ROOT / "digital" / "rtl" / "trng_digital.v"


def run_klt(args: list[str], pdk: str) -> dict:
    env = dict(os.environ)
    env["PDK"] = pdk
    proc = subprocess.run(args, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise SystemExit(
            f"error: `{' '.join(args)}` failed (exit {proc.returncode})\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return json.loads(proc.stdout)


def synthesize(klt: str, pdk: str, request: Path) -> dict:
    return run_klt([klt, "synthesize", str(request), "--pdk", pdk, "--format", "json"], pdk)


def equiv(klt: str, pdk: str, gold: Path, gate_netlist: Path, liberty: Path,
         timeout_s: float, workdir: Path) -> dict:
    req = {
        "gold": {"sources": [str(gold)], "top": "trng_digital"},
        "gate": {"sources": [str(gate_netlist)], "top": "trng_digital",
                "liberty": str(liberty)},
        "port_map": None,
        "engine": "yosys-sequential",
        "timeout_s": timeout_s,
    }
    req_path = workdir / "equiv-request.json"
    req_path.write_text(json.dumps(req, indent=2))
    return run_klt([klt, "equiv", str(req_path), "--format", "json"], pdk)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--klt", default=os.environ.get("KLT", "klt"))
    ap.add_argument("--pdk", default="sky130A")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--skip-equiv", action="store_true",
                    help="skip the klt equiv sequential proof (minutes per "
                         "netlist) -- fast local iteration only; refuses "
                         "--emit-record when given")
    ap.add_argument("--equiv-timeout-s", type=float, default=1800.0)
    ap.add_argument("--emit-record", action="store_true")
    ap.add_argument("--keep", type=Path, default=None,
                    help="keep run artifacts under this directory")
    args = ap.parse_args(argv)

    if shutil.which(args.klt) is None:
        print(f"error: klt not found ({args.klt!r}) -- a missing tool is not "
              "evidence, so nothing is minted", file=sys.stderr)
        return 2
    if shutil.which("iverilog") is None:
        print("error: iverilog not found -- a missing tool is not evidence, "
              "so nothing is minted", file=sys.stderr)
        return 2
    if args.emit_record and args.skip_equiv:
        print("error: --emit-record requires the klt equiv proof; refusing "
              "to mint a level:gate record without it (drop --skip-equiv, "
              "or drop --emit-record)", file=sys.stderr)
        return 2

    pdk_info = run_klt([args.klt, "pdk", "find", "--pdk", args.pdk, "--format", "json"],
                       args.pdk)
    libs_ref = Path(pdk_info["assets"]["libs_ref"])

    tmp = Path(tempfile.mkdtemp(prefix="digital-synthesis-"))
    workdir = args.keep or tmp
    workdir.mkdir(parents=True, exist_ok=True)

    results = []
    all_ok = True
    for cfg in CONFIGS:
        label = cfg["label"]
        cfg_dir = workdir / label
        cfg_dir.mkdir(parents=True, exist_ok=True)

        synth = synthesize(args.klt, args.pdk, cfg["request"])
        netlist_path = Path(synth["netlist_path"])
        deck = synth["provenance"]["deck"]
        liberty_path = libs_ref / "sky130_fd_sc_hd" / "lib" / f"{deck['name']}.lib"
        if not liberty_path.exists():
            raise SystemExit(f"error: expected liberty not found: {liberty_path}")

        leak_by_cell, _ = ll.parse_cell_leakage_nw(liberty_path)
        leakage_nw, missing = ll.total_leakage_nw(synth["instance_counts_by_type"],
                                                   leak_by_cell)
        if missing:
            raise SystemExit(
                f"error: {label}: {len(missing)} mapped cell type(s) have no "
                f"leakage entry in {liberty_path}: {missing[:10]}")

        equiv_result = None
        if not args.skip_equiv:
            equiv_result = equiv(args.klt, args.pdk, RTL, netlist_path, liberty_path,
                                 args.equiv_timeout_s, cfg_dir)
            if equiv_result["status"] != "equivalent":
                all_ok = False

        cosim = gate_cosim.run(netlist_path, libs_ref, cfg_dir / "gate-cosim", args.seed)
        if not cosim["ok"]:
            all_ok = False

        results.append({
            "label": label,
            "clock_period_ns": cfg["clock_period_ns"],
            "synth": synth,
            "netlist_path": netlist_path,
            "liberty_path": liberty_path,
            "leakage_nw": leakage_nw,
            "equiv": equiv_result,
            "cosim": cosim,
        })

    lines: list[str] = []
    a = lines.append
    a("## Configuration")
    a("")
    a(f"- RTL: `digital/rtl/trng_digital.v`; testbench (unmodified): "
      f"`digital/tb/tb_trng_digital.v`")
    a(f"- engine: yosys (`klt synthesize`); PDK: {pdk_info['variant']} "
      f"({pdk_info['version']})")
    a(f"- cell library / corner: `sky130_fd_sc_hd` / `tt_025C_1v80`")
    a(f"- equivalence engine: `klt equiv`, `\"yosys-sequential\"` "
      f"(register-correspondence; the default combinational engine is a "
      f"hard scope error on a design with flip-flops)"
      f"{' -- SKIPPED (--skip-equiv)' if args.skip_equiv else ''}")
    a(f"- gate-level cosim: `iverilog` + `sky130_fd_sc_hd` Verilog cell "
      f"models (`` `define FUNCTIONAL``, `` `define UNIT_DELAY #1``), same "
      f"stimulus program as `sim/digital-rtl-equivalence/`, seed {args.seed}")
    a("")
    a("## Results")
    a("")
    a("| Config | clock_period_ns | instance_count | area_um2 | "
      "seq_area_um2 | leakage_nW | critical_path_ps (ABC, wire-free) | "
      "equiv | gate cosim |")
    a("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        s = r["synth"]
        timing = s.get("timing") or {}
        cp = timing.get("critical_path_ps")
        eq = r["equiv"]
        eq_str = "SKIPPED" if eq is None else eq["status"]
        co = r["cosim"]
        co_str = (f"PASS ({co['cycles']} cyc)" if co["ok"]
                  else f"FAIL ({co['mismatches']} mismatches)")
        a(f"| {r['label']} | {r['clock_period_ns']} | {s['instance_count']} | "
          f"{s['area_um2']} | {s.get('sequential_area_um2')} | "
          f"{r['leakage_nw']:.4f} | {cp} | {eq_str} | {co_str} |")
    a("")
    for r in results:
        a(f"### {r['label']}")
        a("")
        s = r["synth"]
        a(f"- `klt synthesize` `engine_version`: {s.get('engine_version')}")
        a(f"- netlist: `{_display_path(r['netlist_path'])}`")
        a(f"- liberty: `{_display_path(r['liberty_path'])}`")
        a(f"- input `content_hash`: "
          f"`{s['provenance']['input']['content_hash']}`")
        a(f"- deck `content_hash`: "
          f"`{s['provenance']['deck']['content_hash']}`")
        if r["equiv"] is not None:
            eq = r["equiv"]
            a(f"- `klt equiv`: status **{eq['status']}**, engine "
              f"`{eq['engine']}` {eq.get('engine_version')}, "
              f"elapsed {eq.get('elapsed_s')}s")
        co = r["cosim"]
        a(f"- gate cosim: **{'PASS' if co['ok'] else 'FAIL'}** -- "
          f"{co['cycles']} cycles, {co['mismatches']} mismatches, "
          f"length_ok={co['length_ok']}")
        a("")
    a("## What this record does and does not establish")
    a("")
    a("- It establishes that `digital/rtl/trng_digital.v` maps cleanly onto "
      "`sky130_fd_sc_hd` at `tt_025C_1v80`, both unconstrained and at this "
      "design's own 50 kHz sample-clock period, that the mapped netlist is "
      "*sequentially* equivalent to the source RTL (`klt equiv "
      "yosys-sequential`, register-correspondence, not a per-cycle "
      "simulation-only check), and that the same directed stimulus program "
      "`sim/digital-rtl-equivalence/` uses reproduces the normative "
      "behavioural model's trace bit-for-bit through the mapped gate "
      "netlist.")
    a("- `timing.critical_path_ps` is ABC's own pre-layout, wire-free, "
      "largest-combinational-cone `stime -p` estimate -- not signoff STA, "
      "not a register-to-register path, no placement/no wire RCs. `klt "
      "sta` (a real per-hop timing-graph walk) requires an already-routed "
      "DEF; place-and-route is out of scope for this record (issue #117's "
      "own scope).")
    a("- Leakage is a Liberty `cell_leakage_power` sum over the mapped "
      "instance list, not a field `klt synthesize` reports itself -- see "
      "`liberty_leakage.py`'s docstring and the cited friction issue.")
    a("- No place-and-route, no DRC/LVS, no post-route/SDF simulation, no "
      "whole-block `trng_top` integration with the analog `sampler_core` "
      "layout -- all explicitly out of scope (issue #117).")

    body = "\n".join(lines)
    print(body)

    if args.emit_record:
        if not all_ok:
            print("\nrefusing to mint a record: at least one config's "
                  "equivalence/cosim result was not a clean pass",
                  file=sys.stderr)
            return 1
        artifact_stage = workdir / "artifacts"
        artifact_stage.mkdir(parents=True, exist_ok=True)
        artifacts: list[Path] = []

        def stage(path: Path, name: str) -> Path:
            dest = artifact_stage / name
            shutil.copy2(path, dest)
            artifacts.append(dest)
            return dest

        summary_configs = []
        for r in results:
            label = r["label"]
            s = r["synth"]
            stage(r["netlist_path"], f"{label}-trng_digital_synth.v")
            synth_json_path = artifact_stage / f"{label}-synthesize-output.json"
            synth_json_path.write_text(json.dumps(_sanitize_paths(s), indent=2))
            artifacts.append(synth_json_path)
            if r["equiv"] is not None:
                equiv_json_path = artifact_stage / f"{label}-equiv-output.json"
                equiv_json_path.write_text(
                    json.dumps(_sanitize_paths(r["equiv"]), indent=2))
                artifacts.append(equiv_json_path)
            co = r["cosim"]
            stage(Path(co["stimulus_path"]), f"{label}-gate-cosim-stimulus.txt")
            stage(Path(co["observations_path"]), f"{label}-gate-cosim-observations.txt")

            summary_configs.append({
                "label": label,
                "clock_period_ns": r["clock_period_ns"],
                "instance_count": s["instance_count"],
                "area_um2": s["area_um2"],
                "sequential_area_um2": s.get("sequential_area_um2"),
                "leakage_nw": r["leakage_nw"],
                "timing": s.get("timing"),
                "engine_version": s.get("engine_version"),
                "netlist_content_hash_input": s["provenance"]["input"]["content_hash"],
                "deck_content_hash": s["provenance"]["deck"]["content_hash"],
                "equivalence": _sanitize_paths(r["equiv"]),
                "gate_cosim": {k: v for k, v in co.items()
                              if k not in ("stimulus_path", "observations_path")},
                "klt_provenance": _sanitize_paths(s["provenance"]),
            })

        rid = mint_behavioral_record(
            repo_root=REPO_ROOT,
            slug="digital-synthesis",
            claim=("digital/rtl/trng_digital.v synthesizes cleanly against "
                   "sky130_fd_sc_hd at tt_025C_1v80, both unconstrained and "
                   "at the block's own 50 kHz sample-clock period; the "
                   "mapped netlist is klt-equiv-proven sequentially "
                   "equivalent to the source RTL and reproduces "
                   "sim/digital-rtl-equivalence/'s directed stimulus "
                   "program bit-for-bit"),
            body_md=body,
            summary={"configs": summary_configs,
                    "pdk": _sanitize_paths(pdk_info)},
            level="gate",
            seeds={"cosim_stimulus_seed": args.seed},
            tools={"klt": results[0]["synth"]["provenance"].get("klt_version"),
                  "yosys": results[0]["synth"].get("engine_version"),
                  "iverilog": results[0]["cosim"]["iverilog_version"]},
            artifacts=artifacts,
        )
        print(f"\nrecord id: {rid}", file=sys.stderr)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
