#!/usr/bin/env python3
"""klt-free unit test of the Ts = 20 us request generator (issue #604).

Covers the contract the batch fleet run and the issue's acceptance criteria
depend on, with no klt, no PDK, no ngspice:

* the emitted netlist body is a circuit BODY -- both committed netlists
  inlined, both legs instantiated, no .lib/.temp/.tran/.meas/.control/.end
  (klt sim owns those), and no title card (line 1 is a comment);
* the three recorded stimulus deviations are actually in the cards: clk at
  Ts = 20 us with the control's own 49.8 % duty and 320 ns first edge;
  en/rst PULSE widths that never fall inside tstop while keeping the 5 ns /
  300 ns release instants (the W_RST anchor's bit-identity); tstep 50p with
  the 3480 s unit timeout that fits the fleet's 3600 s whole-job ceiling;
* every measurement window sits inside the .tran stop, W_RST is exactly the
  committed control's own 50-250 ns, W_ACT is exactly one complete clk
  period with edges at both endpoints, and the halves subdivide it;
* request/plan shape: backend batch, save_mode netlist, 12-digit
  measurement precision, all ten supplies on the 1.98 V axis, process ff,
  the two committed control record paths, and netlist sha256 consistency;
* determinism: two emissions are byte-identical.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GEN = HERE / "make-ts20u-requests.py"
DESIGN = REPO / "design" / "sampler_core.spice"
PEX = REPO / "layout" / "pex-sampler-core" / "sampler_core_pex.spice"

TSTOP_S = 40.4e-6
TS_S = 20e-6
CLK_T0_S = 320e-9
FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok: {msg}")
    else:
        FAILURES.append(msg)
        print(f"  FAIL: {msg}")


def parse_t(tok: str) -> float:
    mult = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3}
    return float(tok[:-1]) * mult[tok[-1]] if tok[-1].isalpha() else float(tok)


def emit(tmp: Path, period: str = "20u") -> dict[str, Path]:
    out = tmp / "corners"
    subprocess.run([sys.executable, str(GEN), str(out), "--points", "both", "--period", period],
                   check=True, capture_output=True)
    return {tag: out / f"ts{period}-{tag}-1.98V" for tag in ("m40C", "125C")}


def test_body(d: Path) -> None:
    body = (d / "netlist.cir").read_text()
    print("netlist body:")
    check(body.splitlines()[0].startswith("*"), "line 1 is a comment, not a title card")
    for card in (".control", ".endc", ".end\n", ".tran ", ".lib ", ".temp",
                 ".meas "):
        check(not re.search(r"(?m)^\s*" + re.escape(card.strip()) + r"\b",
                            body) if card != ".end\n" else
              not re.search(r"(?m)^\.end\s*$", body),
              f"body carries no klt-owned card {card.strip()!r}")
    check(".option scale=1u" in body, ".option scale=1u preserved")
    check("Vsub vsubs 0 dc 0" in body, "substrate hard tie preserved")
    check(DESIGN.read_text() in body, "design/sampler_core.spice inlined verbatim")
    check(PEX.read_text() in body, "sampler_core_pex.spice inlined verbatim")
    check(re.search(r"(?m)^xarr ", body) and "sampler_core_pex" in body,
          "extracted leg xarr instantiates sampler_core_pex")
    check(re.search(r"(?m)^xctl ", body) and re.search(r"(?m)^\+ sampler_core$",
          body), "control leg xctl instantiates .subckt sampler_core")
    check(".ic v(xarr.ro1)=0 v(xarr.ro2)=0 v(xarr.ro3)=0 v(xarr.ro4)=0" in body and
          ".ic v(xctl.ro1)=0 v(xctl.ro2)=0 v(xctl.ro3)=0 v(xctl.ro4)=0" in body,
          "both legs' .ic ring start-up states present")
    save_ok = all(t in body for t in (
        ".save v(xarr.ro1)", "v(xctl.ro4) v(xctl.xo)", ".save v(praw_bit)",
        "v(raw_bit) v(raw_valid)", "v(ring_bit3)",
        ".save i(Vddrp1) i(Vddrp2) i(Vddrp3) i(Vddrp4) i(Vddp)",
        ".save i(Vddr1) i(Vddr2) i(Vddr3) i(Vddr4) i(Vdd)"))
    check(save_ok, ".save set covers the measured vectors")


def test_stimulus(d: Path) -> None:
    body = (d / "netlist.cir").read_text()
    print("stimulus deviations:")
    for name in ("Vclkp", "Vclk"):
        m = re.search(rf"(?m)^{name} \S+ 0 PULSE\(0 1\.98 (\S+) 100p 100p (\S+) (\S+)\)$", body)
        check(bool(m), f"{name} card found")
        if m:
            check(abs(parse_t(m.group(1)) - CLK_T0_S) < 1e-15,
                  f"{name} first edge at 320n")
            check(abs(parse_t(m.group(2)) - 9.96e-6) < 1e-12,
                  f"{name} high width 9.96u (49.8 % duty)")
            check(abs(parse_t(m.group(3)) - TS_S) < 1e-15,
                  f"{name} period 20u")
    for name in ("Venp1", "Ven4"):
        m = re.search(rf"(?m)^{name} \S+ 0 PULSE\(0 1\.98 (\S+) 100p 100p (\S+) (\S+)\)$", body)
        check(bool(m) and abs(parse_t(m.group(1)) - 5e-9) < 1e-15,
              f"{name} releases at 5n")
        check(bool(m) and parse_t(m.group(2)) > TSTOP_S,
              f"{name} stays high past tstop")
    for name in ("Vrstnp", "Vrstn"):
        m = re.search(rf"(?m)^{name} \S+ 0 PULSE\(0 1\.98 (\S+) 100p 100p (\S+) (\S+)\)$", body)
        check(bool(m) and abs(parse_t(m.group(1)) - 300e-9) < 1e-15,
              f"{name} releases at 300n (W_RST anchor)")
        check(bool(m) and parse_t(m.group(2)) > TSTOP_S,
              f"{name} stays high past tstop")


def test_request(d: Path, temp_c: float) -> None:
    req = json.loads((d / "request.json").read_text())
    plan = json.loads((d / "plan.json").read_text())
    print(f"request ({temp_c:+g} C):")
    check(req["backend"] == "batch", "backend batch (never a local grid)")
    check(req["corners"]["process"] == ["ff"], "process axis ff only")
    check(req["corners"]["temperature_c"] == [temp_c], "temperature axis")
    supplies = req["corners"]["supply_v"]
    check(sorted(supplies) == sorted(
        [f"Vddrp{i}" for i in (1, 2, 3, 4)] + ["Vddp"] +
        [f"Vddr{i}" for i in (1, 2, 3, 4)] + ["Vdd"]),
        "all ten supplies on the axis")
    check(all(v == [1.98] for v in supplies.values()), "supply axis 1.98 V")
    check(req["analysis"] == {"kind": "tran", "args": "50p 40.4u uic"},
          "analysis .tran 50p 40.4u uic (recorded tstep deviation)")
    check(req["options"]["timeout_s"] + 120 <= 3600,
          "unit timeout + overhead fits the fleet whole-job ceiling")
    check(req["options"]["save_mode"] == "netlist",
          "save_mode netlist (the deck's own .save set is the memory bound)")
    init = req["options"]["ngspice_init"]
    check("set measureprec=12" in init and "set numdgt=12" in init,
          "12-digit measurement precision requested")
    names = {m["name"] for m in req["measurements"]}
    check(len(names) == len(req["measurements"]) == 74,
          "74 uniquely-named measurements")
    in_window = True
    for m in req["measurements"]:
        for tok in re.findall(r"(?:FROM|TO|AT)=([0-9.]+[a-z]?)", m["spice"]):
            in_window &= parse_t(tok) <= TSTOP_S + 1e-15
    check(in_window, "every window/AT inside the .tran stop")
    rst = [m for m in req["measurements"] if m["name"].endswith("_rst")]
    check(rst and all("FROM=50n TO=250n" in m["spice"] for m in rst),
          "W_RST exactly the committed control's 50-250 ns")
    act = [m for m in req["measurements"] if m["name"].endswith("_act")]
    check(act and all("FROM=20.32u TO=40.32u" in m["spice"] for m in act),
          "W_ACT exactly one complete clk period, edges at both endpoints")
    lo = [m for m in req["measurements"] if m["name"].endswith("_lo")]
    hi = [m for m in req["measurements"] if m["name"].endswith("_hi")]
    check(lo and all("FROM=20.32u TO=30.32u" in m["spice"] for m in lo) and
          hi and all("FROM=30.32u TO=40.32u" in m["spice"] for m in hi),
          "stationarity halves subdivide W_ACT")
    snap = [m for m in req["measurements"] if "_snap_" in m["name"]]
    check(len(snap) == 12 and all("AT=35.3u" in m["spice"] for m in snap),
          "12 snapshots at the mid-low opaque-slave phase")
    per = [m for m in req["measurements"] if re.search(r"_r[1-4][ab]$", m["name"])]
    check(len(per) == 16 and all("rise=3" in m["spice"] or "rise=13" in m["spice"]
                                 for m in per),
          "ring periods use the control deck's rise=3/rise=13 estimator")
    check(plan["netlist_sha256"] == _sha(d / "netlist.cir"),
          "plan.json netlist sha256 matches the emitted file")
    check(plan["design_lib"]["sha256"] == _sha(DESIGN) and
          plan["pex_lib"]["sha256"] == _sha(PEX),
          "plan.json pins both inlined netlists")
    check(plan["historical_records"] == [
        "sim/post-layout-sampler-core/records/20260908-050034-ef0db50.json",
        "sim/post-layout-sampler-core/records/20260908-053634-ef0db50.json"],
        "plan.json names the historical reference records")
    check(len(plan["deviations"]) == 4, "four recorded deviations")
    check(plan["timing"]["ts_s"] == TS_S and plan["timing"]["uic"] is True,
          "plan.json timing block")


def _sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        dirs = emit(tmp)
        for tag, temp_c in (("m40C", -40.0), ("125C", 125.0)):
            print(f"[{tag}]")
            test_body(dirs[tag])
            test_stimulus(dirs[tag])
            test_request(dirs[tag], temp_c)
        short = emit(tmp, "100n")
        for tag, d in short.items():
            # Apart from the clock widths and periods, all circuit cards must match.
            cards = [line for line in (d / "netlist.cir").read_text().splitlines()
                     if line and not line.startswith("*")]
            slow_cards = [line for line in (dirs[tag] / "netlist.cir").read_text().splitlines()
                          if line and not line.startswith("*")]
            clocks = [line for line in cards if line.startswith(("Vclk ", "Vclkp "))]
            check(len(clocks) == 2 and all("320n 100p 100p 49.8n 100n)" in c for c in clocks),
                  f"{tag}: both controls use the 100 ns clock")
            check(cards == [c.replace("9.96u 20u)", "49.8n 100n)") for c in slow_cards],
                  f"{tag}: control preserves the slow deck's netlists, load and other stimulus")
            req = json.loads((d / "request.json").read_text())
            check(req["analysis"]["args"] == "50p 850n uic" and len(req["measurements"]) == 20,
                  f"{tag}: short control measures ten rails in two windows")
            for window, span in (("_act", "FROM=420n TO=820n"), ("_rst", "FROM=50n TO=250n")):
                cards = [m["spice"] for m in req["measurements"] if m["name"].endswith(window)]
                check(len(cards) == 10 and all(span in c for c in cards), f"{tag}: {window} window")
            for path in (d, dirs[tag]):
                for name in ("request.json", "plan.json"):
                    check((path / name).read_bytes() == (HERE / "corners" / path.name / name).read_bytes(),
                          f"{path.name}: reproduces committed {name}")
        again = emit(tmp / "again")
        for tag in ("m40C", "125C"):
            check((again[tag] / "netlist.cir").read_bytes() ==
                  (dirs[tag] / "netlist.cir").read_bytes() and
                  (again[tag] / "request.json").read_bytes() ==
                  (dirs[tag] / "request.json").read_bytes(),
                  f"{tag}: deterministic re-emission")
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
