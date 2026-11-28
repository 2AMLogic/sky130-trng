#!/usr/bin/env python3
"""Generate the ngspice gate-level model of the digital half (issue #486).

DR-0017 (Accepted, #404) chose option (b) -- analog chain at transistor level,
digital section at gate level behind a defined boundary -- and left *how* the
gate-level half is realised in ngspice to this follow-up, "to choose and to
evidence". **This script is the choice: a timed-delay XSPICE netlist.**

Every ``sky130_fd_sc_hd`` instance of ``layout/trng_digital/trng_digital.routed.v``
becomes one XSPICE event-driven primitive (``d_genlut`` for a combinational
cell, ``d_dff`` for a flop) carrying scalar rise/fall delays reduced from one
Liberty deck, with ``adc_bridge`` / ``dac_bridge`` cards at the boundary. The
emitted body is a *circuit body only* -- no ``.control``, no ``.end``, no
``.lib``/``.temp``/``.tran`` -- which is exactly the netlist convention
``klt sim`` requires (``make-requests.py`` docstring), so no code-model
loading or ``.control`` injection has to be smuggled past the runner.

Why this realisation and not event-driven co-simulation (``d_cosim``): a
``d_*``-plus-bridge netlist needs no per-netlist, per-corner shared object and
no second delay source, and ngspice's own ``digital.cm`` already ships every
primitive it uses (verified on both installs on the dispatch host, and
ngspice-46 is the build the fleet runner used for
``records/20261105-analog-chain-probe.md``). ``d_cosim`` stays the documented
fallback if a ``d_genlut`` width or fan-in limit ever bites; this netlist's
widest cell is 6 inputs (``a222oi_1``), well inside what was measured to work.

Since issue #776 the stdlib-only parsing half of this generator -- the
structural Verilog netlist parser, the streaming Liberty deck parser, the
Boolean-function compiler and the NLDM tables -- lives in the sibling module
``gate_model_lib.py``, imported and re-exported here. Since #815 the XSPICE
emitter (``build_gate_model`` and its helpers, the bridge/delay constants)
lives there too: ``make-requests.py --set grid`` builds one gate model per
matrix point by importing it, never by running this CLI.

Declared reductions (each one a *disclosed deviation*, recorded with its
source -- none of them is silently taken):

1. **NLDM table -> scalar delay.** Liberty ``cell_rise``/``cell_fall`` are 2-D
   tables over (``input_net_transition``, ``total_output_net_capacitance``);
   ``d_genlut``/``d_dff`` take scalars. Each output pin's pair is a **bilinear
   interpolation** of its tables at the operating point
   (``--slew-ns``, C_load), **clamped** to the table's own index range (never
   extrapolated), and then the **maximum over every delay arc** reaching that
   pin -- the conservative STA convention, so a functional match is not an
   artefact of an optimistic delay. Index ``[0][0]`` is *not* taken.
2. **C_load is derived, not declared.** For each driven net it is the sum of
   the Liberty input-pin ``capacitance`` of every receiver on that net
   (``diode_2``'s antenna tie included -- see 5), plus ``--port-load-pf``
   (default 0.0) when the net also reaches a module output port, which is the
   whole-block deck's standing "outputs are unloaded" assumption
   (``README.md`` -> Assumptions -> Loading).
3. **Input slew operating point.** ``--slew-ns`` defaults to 0.1 ns, the
   rise/fall time every testbench source in this deck family already uses
   (``make-requests.py``'s ``PULSE(... 100p 100p ...)`` cards). It is a fixed
   single-pass operating point, not an STA slew propagation.
4. **Bridge levels move with the corner supply.** ``adc_bridge``'s band is
   ``(0.5 -+ BRIDGE_BAND_FRAC) * --supply-v``, centred on the chosen Liberty
   deck's own ``input_threshold_pct_rise``/``_fall`` (read from the deck and
   asserted to be 50, not assumed), so the bridged event time coincides with
   the point at which that deck measures its delays. ``dac_bridge`` drives
   ``vss``..``--supply-v``. DR-0017 fixes that thresholds move with ``vdd``
   rather than sitting in a fixed 1.8 V domain, which this honours.
5. **``diode_2`` is a declared no-op, not a silent drop.** The antenna tie has
   no Liberty ``function`` and no output pin: it contributes its input-pin
   ``capacitance`` to its net's C_load (see 2) and no primitive. It is counted
   in the manifest as ``declared_no_op_instances`` so the instance
   correspondence to the routed netlist stays exact.
6. **Active-low clear/preset get an explicit inverter.** XSPICE ``d_dff``'s
   ``set``/``reset`` were measured active-**high** on this install, while
   ``dfrtp``/``dfstp`` carry ``clear : "!RESET_B"`` / ``preset : "!SET_B"``.
   One zero-delay ``d_inverter`` per *distinct* driving net is emitted and
   shared, counted separately as ``polarity_inverters``.
7. **One scalar rise/fall pair per flop output.** ``d_dff``'s per-input
   ``clk_delay``/``set_delay``/``reset_delay`` are at XSPICE's own 1 ps floor
   (it refuses 0), so the asynchronous
   clear/preset arc is not modelled separately from the CLK->Q arc; the single
   pair is the max over both (see 1). ``ic=0``: the real cells power up
   undefined and the deck's reset (``rst_n`` low until 300 ns) establishes the
   state every comparison relies on.
8. **``input_load`` is the Liberty input-pin capacitance -- since #595 this
   IS DR-0017's boundary-load model, option 2.** The cards need *some*
   ``input_load`` to elaborate at all; the real per-pin capacitance of the
   first receiving cells at the mapped deck is the chosen boundary load
   (``pvt_deck_map.py``, record ``records/20261121-pvt-deck-and-boundary-load.md``).
   Option 1 (keep the first receiving cells at transistor level) was
   rejected: it moves instances across the ``partition_check()`` partition.
   The committed ``corners/gate-model-full`` manifest's ``reductions`` text
   still says the choice was open -- it predates #595 and is evidence of
   the #486 run, kept byte-stable; this docstring and every plan.json
   written since carry the settled statement.
9. **``vdd``/``vss`` are deck nets, but at gate level the supply enters only
   through 4 and through *which Liberty deck* is chosen.** ``Vvdd``/``Vvss``
   cards are emitted so the two supply nets exist by name (the boundary AC1
   names), but a ``corners.supply_v`` axis alone does **not** re-corner the
   digital half -- the Liberty deck has to move with the point. Since #595
   it does: ``--point PROC:TEMP:VDD`` takes the deck from
   ``pvt_deck_map.py``'s 12-row matrix mapping (pinned by sha256) and
   derives the bridge supply, the request's temperature and the process
   corner from the point, refusing any point outside the matrix.

**Fail-closed.** Nothing is written unless every instance maps: an unknown
cell, an output pin with neither a ``function`` nor an ``ff`` group, an
unparseable function, a netlist pin absent from the deck, a missing delay arc,
a multiply-driven or undriven net, or a flop whose clock/next-state is not a
bare pin all raise and exit non-zero with no output file.

Usage::

    make-gate-model.py OUTDIR [--liberty PATH] [--supply-v 1.8] [--cycles 6]
    make-gate-model.py OUTDIR --point PROC:TEMP_C:VDD   (e.g. ss:-40:1.62)

writes, under OUTDIR:

    gate-model.cir             the gate-level model body (bridges + primitives)
    gate-model.manifest.json   counts, port list, boundary classification,
                               per-reduction parameters, input hashes
    netlist.cir                gate-model.cir + the directed program's stimulus
                               and .save list -- the runnable klt sim body
    request.json               the klt sim request (one corner, local backend)
    plan.json                  input hashes / provenance, make-requests.py style

Nothing here simulates anything.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "layout" / "bin"))
import program as P  # noqa: E402
import pvt_deck_map as PVT  # noqa: E402
from _hashing import sha256_file, sha256_text  # noqa: E402
from _klt_common import BuildError, libs_ref  # noqa: E402

# issue #776: the stdlib-only Verilog/Liberty/NLDM parsing frontend lives in
# gate_model_lib.py; since #815 the XSPICE emitter (build_gate_model and its
# helpers) does too. Every name below is re-exported for the load_module
# callers (sim/tests/test_gate_model.py, test_make_requests.py,
# analysis/deck-axis-sensitivity.py).
from gate_model_lib import (  # noqa: E402
    BRIDGE_BAND_FRAC,
    CELL_PREFIX,
    DAC_EDGE_S,
    DEFAULT_PORT_LOAD_PF,
    DEFAULT_SLEW_NS,
    DELAY_ARC_TYPES,
    MIN_DELAY_S,
    WRAP_COLS,
    CellModel,
    Design,
    GateModelError,
    GateModel,
    LibGroup,
    NldmTable,
    _ASSIGN_RE,
    _ATTR_RE,
    _CALL_RE,
    _COMMENT_RE,
    _CONN_RE,
    _FuncParser,
    _GROUP_RE,
    _INST_RE,
    _MODULE_RE,
    _PORTDIR_RE,
    _TOK_RE,
    _eng,
    _ff_pin,
    _logical_lines,
    _numbers,
    _tokenize,
    build_gate_model,
    compile_function,
    extract_cell_blocks,
    load_liberty_cells,
    netname,
    parse_liberty_group,
    parse_verilog,
    truth_table,
    wrap_card,
)

# the whole-block deck constants are program.py's (#804), re-exported here
# for the load_module callers
ROUTED_V = P.ROUTED_V

#: Liberty threshold the band must be centred on; asserted against the deck.
EXPECTED_THRESHOLD_PCT = P.EXPECTED_THRESHOLD_PCT
#: digital input high level (V); program.VIH states the convention (fixed at
#: every corner, disclosed in the record, not a published PDK figure)
VIH = P.VIH
#: ngspice .tran max timestep -- the SAME value make-requests.py uses (TMAX), so
#: the measured rate is comparable with the analog-chain probe's.
TMAX = "20p"
#: PDK corner library klt sim resolves for the analog models (unused by the
#: event-driven primitives, but the request contract requires a models block)
LIB = "libs.tech/combined/sky130.lib.spice"
PDK = "sky130A"
#: klt sim's request schema allows only 'schematic' / 'extracted' here. A
#: gate-level netlist generated from a routed structural netlist plus a Liberty
#: deck is neither; 'extracted' is forced as the nearer label and the deviation
#: is recorded. Tool gap filed upstream as klayout-tools#5638.
NETLIST_SOURCE = "extracted"

#: raw_bit stimulus for the standalone digital run. In a coupled run raw_bit
#: comes across the boundary from the analog sampler; standalone it has to be
#: driven, so this committed, arbitrary-but-fixed pattern is used and the SAME
#: bits are fed to the normative model for the comparison. It is stimulus, not
#: entropy evidence.
RAW_BIT_PATTERN = "1001011100011110010101100011101011010010111001000110111101000011"


# --------------------------------------------------------------------------
# Verilog / Liberty / NLDM parsing and the XSPICE emitter: gate_model_lib.py
# (issues #776, #815)
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Stimulus, request and plan
# --------------------------------------------------------------------------

def raw_bits(n: int) -> list[int]:
    if n > len(RAW_BIT_PATTERN):
        raise GateModelError(f"RAW_BIT_PATTERN has {len(RAW_BIT_PATTERN)} bits, need {n}")
    return [int(c) for c in RAW_BIT_PATTERN[:n]]


def stimulus_cards(cycles: list[dict], vih: float) -> list[str]:
    """PWL cards for every driven input, plus clk/rst_n/raw_bit.

    The clock, reset and per-cycle bus PWL shapes are the whole-block deck's
    (``make-requests.py`` ``deck_body``/``input_cards``), so the digital half is
    driven exactly as it is inside the coupled run. ``raw_bit`` is testbench
    driven here (standalone), from the committed RAW_BIT_PATTERN.
    """
    inputs = P.cycle_inputs(cycles)
    cards: list[str] = [
        f"Vrst_n rst_n 0 PULSE(0 {vih} {P.RST_N_RELEASE_NS:.0f}n 100p 100p 10u 20u)",
        f"Vclk clk 0 PULSE(0 {vih} {P.T0_NS:.0f}n 100p 100p 49.8n {P.TS_NS:.0f}n)",
    ]
    # raw_bit: the sampler's output in a coupled run; driven here. It changes
    # one skew after the edge of each sample cycle and holds.
    bits = raw_bits(sum(1 for i in inputs if i["raw_valid"]))
    seq: list[int] = []
    bi = 0
    for inp in inputs:
        if inp["raw_valid"]:
            seq.append(bits[bi])
            bi += 1
        else:
            seq.append(seq[-1] if seq else 0)
    cards += wrap_card(P.waveform_card("raw_bit", seq, P.t_stop_ns(cycles), vih))
    for card in P.input_cards(cycles, len(cycles), vih):
        cards += wrap_card(card)
    return cards


def measurement_cards(cycles: list[dict], vih: float,
                      threshold_pct: float) -> tuple[list[dict], list[str]]:
    """``.meas`` entries for every digital response the model also predicts
    (``program.gate_measurement_cards``, #804); a repeated name fails closed."""
    try:
        return P.gate_measurement_cards(cycles, vih, threshold_pct)
    except ValueError as exc:
        raise GateModelError(str(exc)) from exc


def build_deck(model: GateModel, cycles: list[dict], vih: float,
               threshold_pct: float) -> tuple[str, list[dict], list[str]]:
    meas, save = measurement_cards(cycles, vih, threshold_pct)
    body = list(model.body)
    body += ["", "* ---- directed program stimulus (program.py) ----",
             *stimulus_cards(cycles, vih),
             "", "* ---- saved trace set ----"]
    for i in range(0, len(save), 8):
        body.append(".save " + " ".join(save[i:i + 8]))
    return "\n".join(body) + "\n", meas, save


def ngspice_version() -> str:
    try:
        out = subprocess.run(["ngspice", "--version"], capture_output=True,
                             text=True, timeout=30).stdout
        m = re.search(r"ngspice-\d+\S*", out)
        return m.group(0) if m else "unknown"
    except Exception:  # pragma: no cover - environment probe only
        return "unavailable"


_POINT_RE = re.compile(r"^(tt|ss|ff):(-?\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$")


def parse_point(spec: str) -> tuple[str, float, float]:
    """``(process, temperature_c, supply_v)`` from a ``--point`` argument.

    ``ss:-40:1.62`` -> ``("ss", -40.0, 1.62)``. Raises :class:`GateModelError`
    on a malformed spec (the message names the expected shape) and
    :class:`pvt_deck_map.DeckMapError` (also a ``ValueError``) when the point
    is outside the 12-point matrix -- issue #595's mapping table is the only
    deck source; no deck is ever picked ad hoc.
    """
    m = _POINT_RE.match(spec.strip())
    if not m:
        raise GateModelError(
            f"--point {spec!r} is not PROC:TEMP_C:VDD (e.g. ss:-40:1.62)")
    proc, temp, vdd = m.group(1), float(m.group(2)), float(m.group(3))
    PVT.deck_row(proc, temp, vdd)  # fail closed: unmapped points have no deck
    return proc, temp, vdd


def resolve_liberty(explicit: str | None, corner: str) -> Path:
    r"""Resolve the Liberty deck through the repo's documented order.

    ``--liberty`` wins; otherwise ``klt pdk find --pdk sky130A`` locates the
    install (``sim/README.md`` "PDK resolution order") and the deck is taken
    from its ``libs.ref/sky130_fd_sc_hd/lib/``. The absolute path and its
    sha256 are recorded; a ``~/.ciel`` literal is never hardcoded.

    The resolution goes through ``_klt_common.libs_ref``, i.e. through
    ``klt pdk find --format json``'s ``assets.libs_ref`` field. It used to
    scrape klt's human-readable rendering with a ``^\s*libs_ref:\s*(\S+)$``
    regex, which ``re.search`` resolves to the FIRST match -- so a
    ``warning: shadowed same-variant install: ...`` line or a second install
    block carrying a ``libs_ref:`` would silently have won, and klt's own
    ``compatibility`` / ``ambiguous_roots`` / ``broken_symlinks`` verdicts on
    the install were discarded unread. Both readings agreed on the host that
    found this, so it was a fragility rather than a wrong deck; issue #500
    retired it before it became the latter. The shared reader reports those
    three fields on stderr when klt flags them.
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise GateModelError(f"--liberty {p} does not exist")
        return p
    try:
        ref = libs_ref(PDK, klt="klt", timeout=300)
    except (BuildError, OSError, subprocess.SubprocessError) as exc:
        raise GateModelError(f"klt pdk find --pdk {PDK} failed: {exc}") from exc
    p = ref / "sky130_fd_sc_hd" / "lib" / f"sky130_fd_sc_hd__{corner}.lib"
    if not p.is_file():
        raise GateModelError(f"resolved Liberty deck {p} does not exist")
    return p.resolve()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 allow_abbrev=False)
    ap.add_argument("outdir", type=Path, help="output directory (must be empty or absent)")
    ap.add_argument("--verilog", type=Path, default=ROUTED_V,
                    help="routed structural netlist (default: the committed one)")
    ap.add_argument("--liberty", default=None,
                    help="Liberty deck path; default resolves via klt pdk find")
    ap.add_argument("--corner", default="tt_025C_1v80",
                    help="Liberty corner name when --liberty is not given")
    ap.add_argument("--point", default=None, metavar="PROC:TEMP_C:VDD",
                    help="a 12-point-matrix point, e.g. ss:-40:1.62 (issue #595): "
                         "the Liberty deck comes from pvt_deck_map.py and "
                         "--supply-v/--temp-c/the request's process corner "
                         "derive from the point; refuses to combine with "
                         "--liberty/--corner/--supply-v/--temp-c")
    ap.add_argument("--supply-v", type=float, default=1.8)
    ap.add_argument("--temp-c", type=float, default=27.0)
    ap.add_argument("--slew-ns", type=float, default=DEFAULT_SLEW_NS)
    ap.add_argument("--port-load-pf", type=float, default=DEFAULT_PORT_LOAD_PF)
    ap.add_argument("--vih", type=float, default=VIH)
    ap.add_argument("--cycles", type=int, default=6,
                    help="program cycles to drive (the short AC3 program); "
                         "0 means the full program")
    ap.add_argument("--timeout-s", type=int, default=3480,
                    help="klt sim per-corner wall-clock ceiling (DR-0017's unit ceiling)")
    ap.add_argument("--backend", default="local", choices=("local", "batch"))
    args = ap.parse_args(argv)

    outdir: Path = args.outdir
    if outdir.exists() and any(outdir.iterdir()):
        ap.error(f"{outdir} exists and is not empty; refusing to overwrite")

    # issue #595: --point drives the deck (and the point's own T/V/process)
    # from the committed matrix mapping; fail closed on an unmapped point
    # BEFORE any output dir is created. Explicit conflicting knobs refuse.
    pvt_row = None
    if args.point is not None:
        given_argv = argv if argv is not None else sys.argv[1:]
        given = [f for f in ("--liberty", "--corner", "--supply-v", "--temp-c")
                 if any(str(a) == f or str(a).startswith(f + "=")
                        for a in given_argv)]
        if given:
            ap.error(f"--point and {'/'.join(given)} are mutually exclusive")
        try:
            proc, temp_c, vdd = parse_point(args.point)
        except ValueError as exc:  # GateModelError | DeckMapError
            raise GateModelError(str(exc)) from exc
        pvt_row = PVT.deck_row(proc, temp_c, vdd)
        args.corner = pvt_row["liberty_corner"]
        args.supply_v = vdd
        args.temp_c = temp_c
        point_process = proc
    else:
        point_process = "tt"

    design = parse_verilog(args.verilog)
    liberty = resolve_liberty(args.liberty, args.corner)
    lib_sha = sha256_file(liberty)
    if pvt_row is not None and lib_sha != pvt_row["liberty_sha256"]:
        # the deck the point maps to is pinned by hash; a different file
        # under the same corner name means the install is not the PDK the
        # mapping was derived from (issue #595) -- refuse, never re-map
        raise GateModelError(
            f"{liberty.name}: sha256 {lib_sha} != the mapping's pinned "
            f"{pvt_row['liberty_sha256']} for --point {args.point}; the "
            "install differs from the PDK pvt_deck_map.py was derived from")
    wanted = set(design.cell_histogram())
    # the deck's cells and its (asserted) input threshold: the shared loader,
    # the same one the 12-point grid builds its per-point models through
    lib, threshold_pct = load_liberty_cells(liberty, wanted, EXPECTED_THRESHOLD_PCT)

    model = build_gate_model(design, lib, supply_v=args.supply_v, slew_ns=args.slew_ns,
                             port_load_pf=args.port_load_pf, liberty_path=liberty,
                             liberty_sha256=lib_sha, threshold_pct=threshold_pct)

    limit = None if args.cycles == 0 else args.cycles
    cycles, phases = P.build_program(limit=limit)
    t_stop = P.t_stop_ns(cycles)
    deck, meas, save = build_deck(model, cycles, args.vih, threshold_pct)

    request = {
        "netlist": "netlist.cir",
        "engine": "ngspice",
        "backend": args.backend,
        # klt sim accepts only 'schematic' or 'extracted' for netlist_source;
        # a gate-level netlist built from a routed structural netlist plus a
        # Liberty deck is neither. 'extracted' is the closer of the two (this
        # IS derived from the layout, via trng_digital.routed.v), and the
        # forced label is disclosed in plan.json and the record. Filed as a
        # tool gap: klayout-tools#5638.
        "netlist_source": NETLIST_SOURCE,
        "models": {"pdk": PDK, "lib": LIB},
        # --point (issue #595) puts the matrix point's process corner here;
        # without it this is the #486 single-corner probe's "tt"
        "corners": {"process": [point_process], "temperature_c": [args.temp_c]},
        "analysis": {"kind": "tran", "args": f"{TMAX} {t_stop:.0f}n"},
        "measurements": meas,
        "options": {"timeout_s": args.timeout_s, "keep_artifacts": True,
                    "save_mode": "netlist"},
    }
    plan = {
        # The plan's identity is its own directory slug, as in make-requests.py
        # (which threads `name` from its caller): a hardcoded name made both
        # requests claim to be the probe. Derived, so it cannot drift again.
        "name": outdir.resolve().name,
        "issue": 486,
        "realisation": model.manifest["realisation"],
        "netlist_sha256": sha256_text(deck),
        "gate_model_sha256": sha256_text(model.text()),
        "routed_netlist_sha256": model.manifest["source_netlist_sha256"],
        "liberty_deck": str(liberty),
        "liberty_sha256": lib_sha,
        "program": {"t0_ns": P.T0_NS, "ts_ns": P.TS_NS, "cycles": len(cycles),
                    "t_stop_ns": t_stop,
                    "phases": [{"name": n, "from": a, "to": b} for n, a, b in phases]},
        "raw_bit_pattern": RAW_BIT_PATTERN[:sum(
            1 for i in P.cycle_inputs(cycles) if i["raw_valid"])],
        "analysis": request["analysis"],
        "corners": request["corners"],
        "measurement_count": len(meas),
        "vih_fixed": args.vih,
        "netlist_source_forced": {
            "value": NETLIST_SOURCE,
            "why": "klt sim accepts only 'schematic'/'extracted'; this netlist is "
                   "gate-level, generated from trng_digital.routed.v plus one Liberty "
                   "deck. Disclosed deviation, not a claim about the netlist's level.",
        },
        "tools": {"ngspice": ngspice_version()},
        "provenance": P.PROVENANCE,
        "reductions": {
            **model.manifest["reductions"],
            # the manifest text predates #595 (kept byte-stable as #486
            # evidence); in a plan it must agree with boundary_load_option
            "input_load": "Liberty input-pin capacitance per d_genlut input; the "
                          "DR-0017 boundary-load choice is settled as option 2 "
                          "(#595, see boundary_load_option)",
        },
        # issue #595: the boundary-load choice (DR-0017 option 2) travels
        # with every plan this generator writes
        "boundary_load_option": PVT.boundary_load_block(),
    }
    if pvt_row is not None:
        plan["pvt_point"] = {
            "process": point_process,
            "temperature_c": args.temp_c,
            "supply_v": args.supply_v,
            "liberty_deck": str(liberty),
            "liberty_sha256": lib_sha,
            "exact": pvt_row["exact"],
            "dT_K": pvt_row["dT_K"],
            "dV_V": pvt_row["dV_V"],
            "delay_direction": pvt_row["delay_direction"],
            "est_delay_error_pct": pvt_row["est_delay_error_pct"],
            "power_direction": pvt_row["power_direction"],
            "note": pvt_row["note"],
            "mapping": "sim/post-layout-whole-block/pvt_deck_map.py (issue #595)",
        }

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "gate-model.cir").write_text(model.text())
    (outdir / "gate-model.manifest.json").write_text(
        json.dumps(model.manifest, indent=2, sort_keys=True) + "\n")
    (outdir / "netlist.cir").write_text(deck)
    (outdir / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    (outdir / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    m = model.manifest
    print(f"wrote {outdir}")
    print(f"  {m['routed_instances']} routed instances -> "
          f"{m['primitives']['d_genlut']} d_genlut + {m['primitives']['d_dff']} d_dff "
          f"+ {len(m['declared_no_op_instances'])} declared no-op"
          f" (+{m['polarity_inverters']} polarity inverters)")
    print(f"  Liberty {liberty.name} sha256 {lib_sha[:16]}..."
          + (f" [point {point_process} {args.temp_c:.0f}C {args.supply_v:.2f}V, "
             f"{'exact' if pvt_row['exact'] else pvt_row['delay_direction']} for delay]"
             if pvt_row is not None else ""))
    print(f"  boundary (analog/digital): {' '.join(m['boundary']['analog_digital'])}")
    print(f"  program {len(cycles)} cycles, t_stop {t_stop:.0f} ns, {len(meas)} measurements")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GateModelError as exc:
        print(f"make-gate-model.py: {exc}", file=sys.stderr)
        sys.exit(2)
