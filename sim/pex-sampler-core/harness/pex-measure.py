#!/usr/bin/env python3
"""``klt pex --measure-command`` harness for the sampler_core delta report.

Issue #597 (T1 item 7.analog): measures one leg -- schematic or extracted --
of the ``klt pex`` comparison over this repo's established four-point
post-layout PVT grid (``sim/post-layout-sampler-core/``'s own points:
27 C/1.8 V nominal, -40 C/1.62 V, -40 C/1.98 V, 125 C/1.98 V, each crossed
with the tt/ss/ff process axis) and prints the ``klt pex`` measurement
document (``corners[]`` with ``measurements[]``, one ``{name, value,
status}`` per spec row) on stdout. ``klt pex`` itself runs this harness once
per side and computes every schematic-vs-extracted delta row; this file
never compares the two sides itself.

Why ``--measure-command`` and not ``klt sim`` testbench requests: every
delta row here reads DUT-internal nets (``ro1``-``ro4``, ``xo``) that the
curated-deck extraction names with KLayout's joined multi-label spelling
(``ro1|ro1_esc|sr1_d_stub|...``) -- characters no ``.meas`` card can quote,
and names that do not exist at all on the schematic leg. Testbench mode
re-runs one byte-identical deck against both netlists, so no single
``.meas`` card can express these rows on both legs (docs/cli/pex.md,
"Measuring with a caller-supplied command"). In this mode deck construction
is the harness's job, so this harness applies the committed alias map
(``net-aliases.json``, from ``klt lvs``'s own net correspondence) to the
extracted netlist it is handed and then measures BOTH legs with the same
committed body template (``testbench/tb_sampler_core_body.spice``) through
``klt sim`` corner requests -- one request per (temperature, supply) point
with the process axis bundled in, the same request shape
``sim/local-mismatch-monte-carlo/`` established. The grid is expressed as
``klt sim`` requests, never a hand-launched ngspice loop; on a host that
sets ``$KLT_SIM_BACKEND=batch`` (or when ``klt pex --backend batch`` runs
this harness) every multi-unit request goes to the batch fleet.

Contract with ``klt pex`` (docs/cli/pex.md): the netlist under measurement
arrives as the final argv element and as ``$KLT_PEX_NETLIST``;
``$KLT_PEX_SIDE`` is ``schematic`` or ``extracted``; ``$KLT_PEX_ARTIFACTS_DIR``
is this side's per-run artifact directory (requests, bodies and raw ``klt
sim`` responses land there and are committed as evidence under
``sim/pex-sampler-core/runs/``). stdout carries exactly one JSON document;
every diagnostic goes to stderr. A non-zero exit aborts the whole ``klt
pex`` run rather than fabricating empty delta rows.

Environment overrides (probe support; the committed report used the
defaults): ``PEX_SAMPLER_CORE_POINTS`` (``"T:V,T:V,..."``), 
``PEX_SAMPLER_CORE_PROCESSES``, ``PEX_SAMPLER_CORE_BACKEND``,
``PEX_SAMPLER_CORE_KLT`` (klt binary), ``PEX_SAMPLER_CORE_TIMEOUT_S``
(per-corner sim timeout).

Simulation-derived; provisional until silicon.
"""

from __future__ import annotations

import concurrent.futures
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ALIASES_PATH = Path(__file__).resolve().parents[1] / "net-aliases.json"
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "testbench" / "tb_sampler_core_body.spice"

# design/sampler_core.spice's own .subckt sampler_core pin declaration -- the
# SCHEMATIC leg's interface, and the body template's instantiation order.
EXPECTED_PINS = [
    "en1", "en2", "en3", "en4",
    "vddr1", "vddr2", "vddr3", "vddr4", "vdd", "vss",
    "clk", "rst_n",
    "raw_bit", "raw_valid", "ring_bit1", "ring_bit2", "ring_bit3", "ring_bit4",
]

# The EXTRACTED leg's interface. The layout labels only these twelve nets
# with interface names; the six sampler outputs are per-instance nets the
# layout labels with the sampler_dff's own internal labels (LVS pairs them
# topologically -- layout/sampler_core/lvs.json's net_correspondence, and
# net-aliases.json's six explicit output entries), so no `--pins` value can
# ever promote them. They stay internal to the extracted .SUBCKT and the
# harness measures them one level down (v(xdut.raw_bit), after the alias
# rename) instead of at the body node the schematic leg connects.
EXPECTED_EXTRACTED_PINS = [
    "en1", "en2", "en3", "en4",
    "vddr1", "vddr2", "vddr3", "vddr4", "vdd", "vss",
    "clk", "rst_n",
]

# Body node for each DUT pin (vss is the ground tie, like every committed
# sampler_core deck in this repo).
PIN_NODE = {pin: ("0" if pin == "vss" else pin) for pin in EXPECTED_PINS}

# Filled by main() from each leg DUT's own .subckt header.
LEG_PIN_ORDER: dict[str, list[str]] = {}

# sim/post-layout-sampler-core/'s own four-point grid (see its records):
# nominal, cold/low-Vdd, cold/high-Vdd, hot/high-Vdd.
DEFAULT_POINTS = [(27.0, 1.8), (-40.0, 1.62), (-40.0, 1.98), (125.0, 1.98)]
DEFAULT_PROCESSES = ["tt", "ss", "ff"]

# The only limit this report carries from the README target table: Power,
# "< 500 uW active" (analog-partition share of the block; the row measures
# the whole sampler_core partition, digital conditioner excluded). Every
# other row is limit-free: "measured, therefore comparable", the same
# default klt sim gives an unlimited measurement -- the combining-fidelity
# and ring-period rows support the Entropy source / Raw rate rows, whose
# *verdicts* live in signoff/characterization-report.md (item 8), not here.
ACTIVE_POWER_MAX_UW = 500.0

EXPECTED_DEVICE_MODELS = {
    "sky130_fd_pr__nfet_01v8",
    "sky130_fd_pr__pfet_01v8",
}

SUBCKT_RE = re.compile(r"^\.subckt\s+sampler_core\s+(.*)$", re.IGNORECASE | re.MULTILINE)


class HarnessError(Exception):
    """A hard failure: abort the klt pex run (exit non-zero)."""


def log(msg: str) -> None:
    print(f"pex-measure: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# extracted-netlist renaming (joined extractor names -> design-level names)
# ---------------------------------------------------------------------------

def join_continuations(text: str) -> list[str]:
    """Fold ngspice ``+`` continuation lines into their logical line."""
    out: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("+"):
            if not out:
                raise HarnessError("netlist starts with a continuation line")
            out[-1] = out[-1].rstrip() + " " + raw[1:].strip()
        else:
            out.append(raw.rstrip())
    return out


class Renamer:
    """The same rename layout/bin/pex-netlist.py performs, read-only here.

    Joined extractor net names (and their ``\\x7c``-escaped spelling) map to
    the design-level name from ``net-aliases.json``; ``__tN`` star-leg
    suffixes ride along; ``$`` (ngspice in-line comment character) becomes
    ``n`` and ``\\`` is dropped, the same sanitization every committed
    ``layout/pex*/`` library applies. The rename is checked injective so it
    can never merge two nets, and any ``|``-bearing name with no alias entry
    is a hard error -- a regenerated layout must never silently measure the
    wrong net.
    """

    def __init__(self, aliases: dict[str, str]):
        # Longest key first, so a `...|y$1`-style name can never be captured
        # by the shorter `...|y` entry that happens to precede it.
        self.aliases = sorted(aliases.items(), key=lambda kv: -len(kv[0]))
        self._seen: dict[str, str] = {}

    def canonical(self, name: str) -> str:
        for joined, design in self.aliases:
            escaped = joined.replace("|", "\\x7c")
            if name == joined or name == design:
                return design
            if name.startswith(escaped):
                return design + name[len(escaped):]
            if name.startswith(joined):
                return design + name[len(joined):]
        if "|" in name or "\\x7c" in name:
            raise HarnessError(
                f"net name {name!r} is a joined extractor name with no "
                "net-aliases.json entry -- re-derive the alias map from "
                "layout/sampler_core/lvs.json (see net-aliases.json header)"
            )
        return name

    def token(self, name: str) -> str:
        out = self.canonical(name).replace("\\", "").replace("$", "n")
        previous = self._seen.setdefault(out, name)
        if previous != name:
            raise HarnessError(
                f"rename collision: {previous!r} and {name!r} both rewrite to {out!r}"
            )
        return out


def check_dut_interface(text: str, source: str, expected: list[str]) -> list[str]:
    """Assert the DUT declares .subckt sampler_core with exactly `expected`'s
    pin set (order taken from the DUT, never imposed -- the extracted header
    is the extractor's own order) and return that order."""
    m = SUBCKT_RE.search("\n".join(join_continuations(text)))
    if not m:
        raise HarnessError(f"{source}: declares no .subckt sampler_core")
    pins = m.group(1).split()
    if sorted(pins) != sorted(expected):
        raise HarnessError(
            f"{source}: .subckt sampler_core pins {pins} != the expected "
            f"interface {expected}"
        )
    return pins


def xline(pins: list[str]) -> str:
    """The DUT instance line, positional, in the leg DUT's own pin order."""
    nodes = [PIN_NODE[p] for p in pins]
    wrapped = ["xdut"]
    wrapped += nodes[:6]
    line = " ".join(wrapped)
    rest = nodes[6:]
    for i in range(0, len(rest), 8):
        line += "\n+ " + " ".join(rest[i:i + 8])
    return line + " sampler_core"


def rename_extracted_netlist(text: str) -> str:
    """Rewrite the extracted netlist to design-level net names.

    Only names move: every device card, geometry value, R/C value and
    connection is byte-preserved apart from the rename (the same contract
    layout/bin/pex-netlist.py's rewrite states for its own output). Device
    cards are additionally checked against the PDK model set the
    ``--pdk sky130A`` extraction must write, so a future extractor change
    can never silently mis-scale a deck that runs at ``scale=1u``.
    """
    renamer = Renamer(json.loads(ALIASES_PATH.read_text())["aliases"])
    out: list[str] = []
    in_cell = False
    device_cards = 0
    for line in join_continuations(text):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("*"):
            out.append(stripped)
            continue
        head = stripped.split()[0]
        upper = head.upper()
        if upper.startswith(".SUBCKT"):
            out.append(stripped)
            in_cell = True
            continue
        if upper.startswith(".ENDS"):
            in_cell = False
            out.append(stripped)
            continue
        if upper.startswith("."):
            out.append(stripped)  # .GLOBAL vsubs and friends: no names to rename
            continue
        if not in_cell:
            out.append(stripped)
            continue
        tokens = stripped.split()
        kind = head[0].upper()
        if kind in ("X", "M"):
            renamed = [renamer.token(t) for t in tokens[:5]] + tokens[5:]
            model = renamed[5]
            if model not in EXPECTED_DEVICE_MODELS:
                raise HarnessError(
                    f"device card model {model!r} is not one of "
                    f"{sorted(EXPECTED_DEVICE_MODELS)} -- the extraction "
                    "did not run with --pdk sky130A"
                )
            device_cards += 1
            out.append(" ".join(renamed))
        elif kind in ("R", "C"):
            renamed = [renamer.token(t) for t in tokens[:3]] + tokens[3:]
            out.append(" ".join(renamed))
        else:
            raise HarnessError(f"unhandled element card in extracted netlist: {stripped}")
    if device_cards == 0:
        raise HarnessError("extracted netlist carries no device cards")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# klt sim request construction
# ---------------------------------------------------------------------------

def measurement_cards(thr: str, out_prefix: str) -> list[dict]:
    """The raw .meas set -- tb_post_layout_sampler_core's own estimators.

    ``out_prefix`` selects where the six sampler outputs are read: at the
    body nodes on the schematic leg (""), one level down inside the DUT on
    the extracted leg (``xdut.`` -- the outputs are internal nets there,
    see EXPECTED_EXTRACTED_PINS).
    """
    cards: list[dict] = []
    for i in (1, 2, 3, 4):
        cards.append({"name": f"t{i}a", "spice": f".meas tran t{i}a when v(xdut.ro{i})={thr} rise=3"})
        cards.append({"name": f"t{i}b", "spice": f".meas tran t{i}b when v(xdut.ro{i})={thr} rise=13"})
    cards += [
        {"name": "txa", "spice": f".meas tran txa when v(xdut.xo)={thr} rise=2"},
        {"name": "txb", "spice": f".meas tran txb when v(xdut.xo)={thr} rise=50"},
        {"name": "xo_max", "spice": ".meas tran xo_max max v(xdut.xo) from=100n to=800n"},
        {"name": "xo_min", "spice": ".meas tran xo_min min v(xdut.xo) from=100n to=800n"},
        {"name": "xo_avg", "spice": ".meas tran xo_avg avg v(xdut.xo) from=100n to=800n"},
    ]
    for name, node in [
        ("rst_bit", "raw_bit"), ("rst_valid", "raw_valid"),
        ("rst_r1", "ring_bit1"), ("rst_r2", "ring_bit2"),
        ("rst_r3", "ring_bit3"), ("rst_r4", "ring_bit4"),
    ]:
        cards.append({"name": name,
                      "spice": f".meas tran {name} max v({out_prefix}{node}) from=50n to=250n"})
    for tag, (lo, hi) in (("r", ("50n", "250n")), ("a", ("400n", "800n"))):
        for i in (1, 2, 3, 4):
            cards.append({"name": f"i{i}{tag}", "spice": f".meas tran i{i}{tag} avg i(Vddr{i}) from={lo} to={hi}"})
        cards.append({"name": f"ib{tag}", "spice": f".meas tran ib{tag} avg i(Vdd) from={lo} to={hi}"})
    return cards


def render_body(dut_path: Path, vdd: float, pins: list[str], out_prefix: str) -> str:
    thr = f"{0.5 * vdd:g}"
    body = (
        TEMPLATE_PATH.read_text()
        .replace("@@DUT@@", str(dut_path))
        .replace("@@VDD@@", f"{vdd:g}")
        .replace("@@THR@@", thr)
        .replace("@@XLINE@@", xline(pins))
        .replace("@@OUTPFX@@", out_prefix)
    )
    return body


def build_request(point: tuple[float, float], processes: list[str], backend: str,
                  side: str, timeout_s: int, outdir: Path) -> tuple[Path, dict]:
    temp, vdd = point
    stem = f"{temp:g}c-{vdd:g}v"
    body_path = outdir / f"tb-{stem}.spice"
    out_prefix = "xdut." if side == "extracted" else ""
    body_path.write_text(render_body(outdir / "dut.spice", vdd, LEG_PIN_ORDER[side], out_prefix))
    request: dict = {
        "netlist": body_path.name,
        "engine": "ngspice",
        "backend": backend,
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": list(processes), "temperature_c": [temp]},
        "analysis": {"kind": "tran", "args": "5p 800n uic"},
        "measurements": measurement_cards(f"{0.5 * vdd:g}", out_prefix),
        "options": {"timeout_s": timeout_s, "keep_artifacts": False, "save_mode": "netlist"},
    }
    if side == "extracted":
        request["netlist_source"] = "extracted"
    if backend == "batch":
        request["batch"] = {"capacity_wait_s": 600}
    request_path = outdir / f"req-{stem}.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n")
    return request_path, request


def run_one(klt: str, backend: str, request_path: Path, outdir: Path) -> tuple[tuple[float, float], dict]:
    """Run one PVT point's klt sim request; return (point, report)."""
    stem = request_path.stem.replace("req-", "")
    resp_path = outdir / f"resp-{stem}.json"
    argv = [klt, "sim", str(request_path), "--backend", backend, "--format", "json"]
    if backend == "batch":
        argv += ["--wait-for-capacity", "600"]
    log(f"running {request_path.name} ({backend})")
    completed = subprocess.run(argv, capture_output=True, text=True, cwd=str(outdir))
    resp_path.write_text(completed.stdout)
    with gzip.open(str(resp_path) + ".gz", "wb") as fh:
        fh.write(completed.stdout.encode())
    if completed.returncode == 1:
        raise HarnessError(
            f"klt sim {request_path.name} failed to run (exit 1): "
            f"{completed.stderr[-2000:]}"
        )
    if completed.returncode not in (0, 3, 4):
        raise HarnessError(
            f"klt sim {request_path.name} exited {completed.returncode}: "
            f"{completed.stderr[-2000:]}"
        )
    try:
        report = json.loads(completed.stdout)
    except ValueError as exc:
        raise HarnessError(f"klt sim {request_path.name} stdout is not JSON: {exc}") from exc
    temp, vdd = parse_stem(stem)
    return (temp, vdd), report


def parse_stem(stem: str) -> tuple[float, float]:
    temp, vdd = stem.rsplit("-", 1)
    return float(temp[:-1]), float(vdd[:-1])


# ---------------------------------------------------------------------------
# spec-row derivation (the delta[] rows klt pex will pair and compare)
# ---------------------------------------------------------------------------

def _num(values: dict, name: str) -> float:
    v = values.get(name)
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"raw measurement {name!r} missing/non-finite")
    return float(v)


def derive_rows(values: dict, vdd: float) -> list[dict]:
    """Map raw .meas values to the report's spec rows.

    Each row names a README target-table row the analog partition owns:
      ring{1..4}_period_ns, xo_edge_retention, xo_swing_frac, xo_bias_frac,
      raw_tap_freq_mhz -> Entropy source (free-running XOR-combined rings)
         and Raw rate (the raw tap's own toggle rate; the >1 Mbps target
         binds the sampling period and its verdict lives in the
         characterization report, not here);
      active_power_uw, reset_power_uw -> Power ("< 500 uW active" is the
         one README limit this report carries; reset_power_uw is the
         rings-running/samplers-held state, informational);
      sampler_reset_max_v -> Interface (the partition boundary outputs are
         held low through reset, rail-to-rail clean levels end to end).
    """
    rows: list[dict] = []

    def emit(name: str, value, status: str = "pass", message: str | None = None):
        entry = {"name": name, "value": value, "status": status}
        if message:
            entry["message"] = message
        rows.append(entry)

    try:
        periods_s: list[float] = []
        for i in (1, 2, 3, 4):
            ta = _num(values, f"t{i}a")
            tb = _num(values, f"t{i}b")
            period = (tb - ta) / 10.0
            if period <= 0:
                raise ValueError(f"ring {i} period {period} not positive")
            periods_s.append(period)
            emit(f"ring{i}_period_ns", period * 1e9)
        txa = _num(values, "txa")
        txb = _num(values, "txb")
        f_xo = 48.0 / (txb - txa)
        f_ideal = sum(1.0 / p for p in periods_s)
        emit("xo_edge_retention", f_xo / f_ideal)
        emit("raw_tap_freq_mhz", f_xo / 1e6)
        xo_max = _num(values, "xo_max")
        xo_min = _num(values, "xo_min")
        xo_avg = _num(values, "xo_avg")
        emit("xo_swing_frac", (xo_max - xo_min) / vdd)
        emit("xo_bias_frac", xo_avg / vdd)
    except ValueError as exc:
        for name in ("ring1_period_ns", "ring2_period_ns", "ring3_period_ns", "ring4_period_ns",
                     "xo_edge_retention", "raw_tap_freq_mhz", "xo_swing_frac", "xo_bias_frac"):
            emit(name, None, "error", str(exc))

    for tag, name in (("a", "active_power_uw"), ("r", "reset_power_uw")):
        try:
            rails = sum(_num(values, f"i{i}{tag}") for i in (1, 2, 3, 4))
            block = _num(values, f"ib{tag}")
            power_uw = -(rails + block) * vdd * 1e6
            if name == "active_power_uw" and power_uw > ACTIVE_POWER_MAX_UW:
                emit(name, power_uw, "fail",
                     f"{power_uw:.1f} uW exceeds the README Power target's "
                     f"{ACTIVE_POWER_MAX_UW:g} uW active bound")
            else:
                emit(name, power_uw)
        except ValueError as exc:
            emit(name, None, "error", str(exc))

    try:
        worst = max(
            _num(values, n) for n in
            ("rst_bit", "rst_valid", "rst_r1", "rst_r2", "rst_r3", "rst_r4")
        )
        emit("sampler_reset_max_v", worst)
    except ValueError as exc:
        emit("sampler_reset_max_v", None, "error", str(exc))

    return rows


# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: pex-measure.py <netlist> (klt pex appends the netlist)", file=sys.stderr)
        return 2
    side = os.environ.get("KLT_PEX_SIDE")
    netlist = os.environ.get("KLT_PEX_NETLIST") or argv[-1]
    artifacts = Path(os.environ.get("KLT_PEX_ARTIFACTS_DIR") or ".")
    artifacts.mkdir(parents=True, exist_ok=True)
    if side not in ("schematic", "extracted"):
        print(f"pex-measure: KLT_PEX_SIDE must be schematic|extracted, got {side!r}", file=sys.stderr)
        return 2

    backend = (os.environ.get("PEX_SAMPLER_CORE_BACKEND")
               or os.environ.get("KLT_PEX_BACKEND")
               or os.environ.get("KLT_SIM_BACKEND")
               or "local")
    klt = os.environ.get("PEX_SAMPLER_CORE_KLT") or shutil.which("klt")
    if not klt:
        print("pex-measure: no klt binary on PATH (set PEX_SAMPLER_CORE_KLT)", file=sys.stderr)
        return 2
    timeout_s = int(os.environ.get("PEX_SAMPLER_CORE_TIMEOUT_S", "3600"))

    points = DEFAULT_POINTS
    if env_points := os.environ.get("PEX_SAMPLER_CORE_POINTS"):
        points = [tuple(float(x) for x in p.split(":")) for p in env_points.split(",")]
    processes = (os.environ.get("PEX_SAMPLER_CORE_PROCESSES", ",".join(DEFAULT_PROCESSES))
                 .split(","))

    source = Path(netlist).resolve()
    if not source.is_file():
        print(f"pex-measure: netlist {netlist} does not exist", file=sys.stderr)
        return 2
    text = source.read_text()
    expected = EXPECTED_EXTRACTED_PINS if side == "extracted" else EXPECTED_PINS
    if side == "extracted":
        dut = artifacts / "dut.spice"
        dut.write_text(rename_extracted_netlist(text))
        log(f"extracted netlist alias-renamed to {dut} ({source})")
    else:
        dut = artifacts / "dut.spice"
        shutil.copyfile(source, dut)
        log(f"schematic DUT copied to {dut} ({source})")
    LEG_PIN_ORDER[side] = check_dut_interface(dut.read_text(), str(source), expected)
    log(f"{side} DUT pin order: {LEG_PIN_ORDER[side]}")

    klt_version = subprocess.run([klt, "--version"], capture_output=True, text=True).stdout.strip()
    log(f"side={side} backend={backend} klt={klt} [{klt_version}] "
        f"points={points} processes={processes}")

    requests = [build_request(p, processes, backend, side, timeout_s, artifacts)
                for p in points]
    results: dict[tuple[float, float], dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as pool:
        futures = [pool.submit(run_one, klt, backend, req, artifacts) for req, _ in requests]
        for future in concurrent.futures.as_completed(futures):
            point, report = future.result()
            results[point] = report

    corners_out: list[dict] = []
    for temp, vdd in points:
        report = results[(temp, vdd)]
        for corner in report.get("corners", []):
            proc = corner["corner_id"].split("/")[0]
            values = {m["name"]: m.get("value") for m in corner.get("measurements", [])}
            rows = derive_rows(values, vdd)
            corners_out.append({
                "corner_id": f"{proc}/{temp:g}C/{vdd:g}V",
                "measurements": rows,
            })
            log(f"derived {len(rows)} rows for {proc}/{temp:g}C/{vdd:g}V")

    manifest = {
        "side": side,
        "backend": backend,
        "klt": klt_version,
        "dut": str(source),
        "points": list(points),
        "processes": processes,
        "timeout_s": timeout_s,
        "jobs": [
            {"point": f"{t:g}C/{v:g}V",
             "job_id": ((results[(t, v)].get("environment", {}).get("remote") or {}).get("job_id"))}
            for t, v in points
        ],
    }
    (artifacts / "harness-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(json.dumps({"corners": corners_out}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except HarnessError as exc:
        print(f"pex-measure: {exc}", file=sys.stderr)
        raise SystemExit(1)
