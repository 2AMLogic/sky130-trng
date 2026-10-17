"""Issue #174: the whole-block reducer must count coverage honestly.

Builds synthetic ``klt sim`` reports whose digital measurements are generated
from the normative model itself, then checks: a complete matrix is MET, an
omitted point is UNMET (incomplete coverage named), a flipped bus bit is an
oracle mismatch, a klt error envelope / errored corner stays UNMET, and an
absent measurement never passes.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BLOCK = REPO / "sim" / "post-layout-whole-block"
sys.path.insert(0, str(BLOCK))
sys.path.insert(0, str(REPO / "sim" / "bin"))

_spec = importlib.util.spec_from_file_location("reduce_wb", BLOCK / "analysis" / "reduce-whole-block.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
_mr = importlib.util.spec_from_file_location("make_requests", BLOCK / "make-requests.py")
MR = importlib.util.module_from_spec(_mr)
_mr.loader.exec_module(MR)
P = R.P

BITS = [(i * 7 + 3) % 5 % 2 for i in range(64)]


def synth_corner(proc, temp, vdd, flip=None, drop=None, omit=None, status="pass"):
    cycles, _ = P.build_program()
    meas_entries, _ = MR.measurement_cards(cycles)
    rows = P.model_replay(BITS)
    inputs = P.cycle_inputs(cycles)
    hi = vdd
    vals = {}
    bit_i = 0
    for k, inp in enumerate(inputs):
        if inp["raw_valid"]:
            vals[f"raw_bit_k{k}"] = hi * BITS[bit_i]
            vals[f"raw_valid_k{k}"] = hi
            bit_i += 1
    for e in meas_entries:
        n = e["name"]
        if n in vals:
            continue
        if n.startswith("rdata_k"):
            k, b = n[len("rdata_k"):].split("_b")
            v = (rows[int(k)]["model"]["bus_rdata"] >> int(b)) & 1
            vals[n] = hi * v
        elif n.startswith("odata_k"):
            k, b = n[len("odata_k"):].split("_b")
            vals[n] = hi * ((rows[int(k) - 1]["model"]["out_data"] >> int(b)) & 1)
        elif n.startswith(("alarm_k", "gated_k", "startup_done_k", "out_valid_k")):
            sig, k = n.rsplit("_k", 1)
            vals[n] = hi * int(rows[int(k) - 1]["model"][sig])
        elif n.startswith("i_") and n.endswith("_w1"):
            vals[n] = -1e-6
        elif n.startswith("i_") and n.endswith("_w2"):
            vals[n] = -3e-6
        elif n.startswith("q_"):
            vals[n] = -1e-12
        else:
            vals[n] = 1e-6
    if flip:
        vals[flip] = hi - vals[flip]
    if drop:
        vals[drop] = None
    if omit:
        del vals[omit]
    return {"process": proc, "temperature_c": temp, "supply_v": {"Vvdd": vdd}, "status": status,
            "diagnostics": [], "measurements": [{"name": k, "value": v} for k, v in vals.items()]}


def write_report(d: Path, name, corners, extra=None):
    (d / name).mkdir(parents=True)
    doc = {"status": "pass", "corners": corners}
    doc.update(extra or {})
    (d / name / "report.json").write_text(json.dumps(doc))
    return d / name


class WholeBlockReduction(unittest.TestCase):
    def test_complete_matrix_met(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="wbred-"))
        for t, v in R.GRID:
            write_report(tmp_path, f"grid-{t}-{v}", [synth_corner(p, t, v) for p in R.PROCESSES])
        red = R.reduce(tmp_path, None)
        self.assertTrue(red["matrix"] == {"expected": 12, "met": 12, "unmet": 0, "complete": True})
        pw = red["points"][0]["power"]
        self.assertTrue(abs(pw["p_active_w"] - pw["recompute_check_w"]) < 1e-18)
        self.assertTrue(abs(pw["p_active_w"] - 1.62 * 5 * 3e-6) < 1e-12)  # independent V*I recompute


    def test_omitted_point_is_unmet(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="wbred-"))
        for t, v in R.GRID[:3]:
            write_report(tmp_path, f"grid-{t}-{v}", [synth_corner(p, t, v) for p in R.PROCESSES])
        red = R.reduce(tmp_path, None)
        self.assertTrue(not red["matrix"]["complete"] and red["matrix"]["unmet"] == 3)
        self.assertTrue(all("no report covers" in p["reasons"][0] for p in red["points"] if p["status"] == "UNMET"))


    def test_oracle_mismatch_and_absent_measurement(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="wbred-"))
        t, v = R.GRID[1]
        write_report(tmp_path, "grid-a", [synth_corner("tt", t, v, flip="rdata_k0_b0"),
                                     synth_corner("ss", t, v, drop="i_vdd_w2"),
                                     synth_corner("ff", t, v, status="error")])
        red = R.reduce(tmp_path, None)
        by = {p["process"]: p for p in red["points"] if p["temperature_c"] == t}
        self.assertTrue(by["tt"]["status"] == "UNMET" and any("oracle" in r for r in by["tt"]["reasons"]))
        self.assertTrue(by["ss"]["status"] == "UNMET" and any("absent" in r for r in by["ss"]["reasons"]))
        self.assertTrue(by["ff"]["status"] == "UNMET")
        self.assertTrue(red["ac3_claimable"] is False)


    def test_omitted_measurement_is_unmet(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="wbred-"))
        t, v = R.GRID[1]
        write_report(tmp_path, "grid-a", [synth_corner("tt", t, v, omit="i_vdd_w2"),
                                          synth_corner("ss", t, v, omit="rdata_k0_b0"),
                                          synth_corner("ff", t, v)])
        red = R.reduce(tmp_path, None)
        by = {p["process"]: p for p in red["points"] if p["temperature_c"] == t}
        for proc in ("tt", "ss"):
            self.assertTrue(by[proc]["status"] == "UNMET" and any("omitted" in r for r in by[proc]["reasons"]))
        self.assertTrue(by["ff"]["status"] == "MET")

    def test_nonfinite_measurement_is_unmet(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="wbred-"))
        t, v = R.GRID[1]
        c = synth_corner("tt", t, v)
        c["measurements"][0]["value"] = float("nan")
        write_report(tmp_path, "grid-a", [c])
        red = R.reduce(tmp_path, None)
        pt = next(p for p in red["points"] if p["process"] == "tt" and p["temperature_c"] == t)
        self.assertTrue(pt["status"] == "UNMET")

    def test_pwl_highs_use_declared_vih(self):
        cycles, _ = P.build_program()
        cards = MR.input_cards(cycles, len(cycles))
        peaks = [max(float(x) for x in c.split("PWL(")[1].rstrip(")").split()[1::2]) for c in cards]
        self.assertTrue(max(peaks) == MR.VIH and all(p in (0.0, MR.VIH) for p in peaks))

    def test_probe_measurements_within_stop_time(self):
        cycles, _ = P.build_program(limit=6)
        t_stop = P.t_stop_ns(cycles)
        meas, _ = MR.measurement_cards(cycles)
        import re
        for e in meas:
            mt = re.search(r"AT=([0-9.]+)n", e["spice"])
            if mt:
                self.assertTrue(float(mt.group(1)) <= t_stop, e["name"])

    def test_error_envelope_stays_unmet(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="wbred-"))
        d = tmp_path / "grid-b"
        d.mkdir()
        (d / "report.json").write_text(json.dumps({"error": {"message": "launch failed: cap"}}))
        (d / "plan.json").write_text(json.dumps({"corners": {"process": ["tt", "ss", "ff"],
                                                             "temperature_c": [27.0],
                                                             "supply_v": {"Vvdd": [1.8]}}}))
        red = R.reduce(tmp_path, None)
        um = [p for p in red["points"] if p["temperature_c"] == 27.0]
        self.assertTrue(all(p["status"] == "UNMET" and "launch failed" in p["reasons"][0] for p in um))

    def test_probe_dirs_do_not_count(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="wbred-"))
        write_report(tmp_path, "startup-probe", [synth_corner("tt", 27.0, 1.8)])
        red = R.reduce(tmp_path, None)
        self.assertTrue(red["matrix"]["met"] == 0 and len(red["sources"]) == 1)


if __name__ == "__main__":
    unittest.main()
