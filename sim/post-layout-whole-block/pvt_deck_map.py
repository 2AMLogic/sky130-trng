#!/usr/bin/env python3
"""DR-0017's per-point choices for the 12-point whole-block matrix (issue #595).

The single source of truth for two things DR-0017 left to a follow-up and
#431's decomposition queued as its own slice:

1. **The boundary-load model: option 2.** The load the analog side sees at
   ``raw_bit``/``raw_valid`` (and the digital share of ``clk``/``rst_n``) is
   the Liberty input-pin ``capacitance`` of the first receiving standard
   cells, taken from the deck this (process, T, Vdd) point maps to below.
   This is what ``make-gate-model.py`` already emitted per ``d_genlut`` input
   purely so the cards elaborate (#486 reduction 8); #595 makes it the
   deliberate choice with a named source per value. Option 1 (keep the first
   receiving cells at transistor level) was rejected: it would move
   transistor instances across the analog/digital partition that
   ``make-requests.py:partition_check`` asserts (25 356 = 264 analog
   transistors + 25 091 digital transistors + 1 antenna diode), breaking the
   flat-extract accounting DR-0017's partition hashes record, and it
   re-introduces a transistor-level corner dependency inside the gate
   partition. Extracted net capacitance does not exist as an alternative
   source: the committed whole-block extract is connectivity-only (no R/C).
   Record: ``records/20261121-pvt-deck-and-boundary-load.md``.

2. **The Liberty deck per matrix point.** The pinned sky130A install ships 16
   non-ccsnoise ``sky130_fd_sc_hd`` decks, listed per process corner, not per
   (T, Vdd) point, so only one of the 12 points (tt / 27 C / 1.80 V, and even
   that at the PDK's 25 C nominal) is served exactly. Each row below names
   the **nearest deck** under a declared, evidence-backed rule: minimise
   |dV| first, tie-break on |dT|. Voltage precedes temperature because the
   deck-derived delay sensitivities of this library (see
   ``analysis/deck-axis-sensitivity.py`` and the record) make the voltage
   term dominate: at n40C, going 1.65 -> 1.95 V moves the library-mean delay
   -26.6 % (ff, ~-89 %/V) while 25 C -> 100 C at 1.80 V moves it only -4.4 %
   (tt, -4.44 %/75 K = -0.059 %/K). Both sensitivities have the SAME sign -- this library
   is faster warm AND faster at high supply (temperature inversion at 1.8 V,
   confirmed on tt, ss and ff pairs) -- so every row's net direction is
   established, none is "mixed": delay direction from the linearised
   estimate ``sT*dT + sV*dV``, power direction per axis (dynamic power with
   the deck's V vs the point's V, leakage with the deck's (T, V) vs the
   point's: leakage rises with both, steeply with T -- the ss -40 C -> 100 C
   pair moves library-mean ``cell_leakage_power`` x9335).

No interpolation is applied anywhere: generation uses the named deck as-is.
The percentage estimates are direction evidence, not corrected values.

Consumers:

* ``make-requests.py --set grid`` records ``plan.json.gate_model_pvt`` per
  request (one deck row per process corner of the request) via
  :func:`plan_entry`.
* ``make-gate-model.py --point PROC:TEMP:VDD`` resolves its Liberty deck via
  :func:`deck_row` and fails closed when the point is unmapped.

Everything here is stdlib-only (no klt, no PDK) so the unit tests run in CI;
:func:`plan_entry` / :func:`verify_against_disk` verify the committed sha256
values against the install only when a ``libs_ref`` directory is supplied
(the PDK-gated test supplies it).
"""
from __future__ import annotations

import re
from pathlib import Path

#: DR-0017's boundary-load model, chosen by #595: 2 = Liberty input-pin
#: capacitance of the receiving cells at the mapped deck.
BOUNDARY_LOAD_OPTION = 2

#: the committed record that states the choice, its sources and its limits.
BOUNDARY_LOAD_RECORD = "sim/post-layout-whole-block/records/20261121-pvt-deck-and-boundary-load.md"

#: where every load value comes from (the "source" DR-0017 demands).
BOUNDARY_LOAD_SOURCE = (
    "Liberty input-pin capacitance of the first receiving standard cells, read "
    "from the deck this (process, T, Vdd) point maps to (pvt_deck_map.py); "
    "extracted net capacitance is not available (the committed whole-block "
    "extract is connectivity-only, no R/C)"
)

#: deck location inside a sky130A install, relative to ``klt pdk find``'s
#: ``assets.libs_ref`` (…/sky130A/libs.ref).
LIB_SUBDIR = Path("sky130_fd_sc_hd") / "lib"

#: the 16 non-ccsnoise ``sky130_fd_sc_hd`` decks of the pinned sky130A
#: install (volare f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7), re-listed by
#: hand for this record -- a PDK version bump can change this set, which
#: :func:`verify_against_disk` catches via the sha256 pins below.
SHIPPED_DECKS = (
    "sky130_fd_sc_hd__ff_100C_1v65.lib",
    "sky130_fd_sc_hd__ff_100C_1v95.lib",
    "sky130_fd_sc_hd__ff_n40C_1v56.lib",
    "sky130_fd_sc_hd__ff_n40C_1v65.lib",
    "sky130_fd_sc_hd__ff_n40C_1v76.lib",
    "sky130_fd_sc_hd__ff_n40C_1v95.lib",
    "sky130_fd_sc_hd__ss_100C_1v40.lib",
    "sky130_fd_sc_hd__ss_100C_1v60.lib",
    "sky130_fd_sc_hd__ss_n40C_1v28.lib",
    "sky130_fd_sc_hd__ss_n40C_1v35.lib",
    "sky130_fd_sc_hd__ss_n40C_1v40.lib",
    "sky130_fd_sc_hd__ss_n40C_1v44.lib",
    "sky130_fd_sc_hd__ss_n40C_1v60.lib",
    "sky130_fd_sc_hd__ss_n40C_1v76.lib",
    "sky130_fd_sc_hd__tt_025C_1v80.lib",
    "sky130_fd_sc_hd__tt_100C_1v80.lib",
)

_DECK_RE = re.compile(r"^sky130_fd_sc_hd__(tt|ss|ff)_(n?)(\d+)C_(\d+)v(\d+)\.lib$")


class DeckMapError(ValueError):
    """A matrix point with no deck mapping (or a table that fails its own
    invariants). Generation must fail closed on this, never fall back."""


def deck_corner(deck_file: str) -> tuple[str, float, float]:
    """``(process, temperature_c, supply_v)`` of a shipped deck file name.

    ``sky130_fd_sc_hd__ss_n40C_1v60.lib`` -> ``("ss", -40.0, 1.60)``.
    """
    m = _DECK_RE.match(deck_file)
    if not m:
        raise DeckMapError(f"{deck_file!r} is not a sky130_fd_sc_hd deck name")
    temp = -float(m.group(3)) if m.group(2) == "n" else float(m.group(3))
    return (m.group(1), temp, float(f"{m.group(4)}.{m.group(5)}"))


#: The 12-row mapping. Keys are the matrix points (process, T C, Vdd V); the
#: values carry the deck, its pinned sha256, the axes the deck is
#: characterised at relative to the point, and the error directions.
#:
#: ``delay_direction``: which way the DECK's delays err against the point
#: (pessimistic = deck slower than the point's cells would be). Established
#: per-axis from the deck pairs in the record, then combined -- the two axes
#: have the same sign in this library, so no row is "mixed". The linearised
#: ``est_delay_error_pct`` is direction evidence only (no interpolation is
#: applied); sensitivities from analysis/deck-axis-sensitivity.py at
#: (0.1 ns, 6 fF): sT = -0.059 %/K (tt), -0.111 %/K (ss), -0.064 %/K (ff);
#: sV = -89 %/V (ff pair; ss pair -154 %/V; tt has no voltage pair, the ff
#: figure is the disclosed proxy).
#:
#: ``power_direction``: which way the DECK's power characterisation errs
#: against the point -- dynamic power moves with the deck's V (C*V^2), its
#: leakage (``cell_leakage_power``) rises steeply with both T and V.
#: "mixed" means the two power terms pull opposite ways and no net direction
#: is established.
DECK_TABLE: dict[tuple[str, float, float], dict] = {}

_DELAY_DIRECTIONS = ("pessimistic", "optimistic", "mixed", "none")
_POWER_DIRECTIONS = ("pessimistic", "optimistic", "mixed", "none")


def _key(process: str, temp_c: float, supply_v: float) -> tuple[str, float, float]:
    return (process.lower(), round(float(temp_c), 1), round(float(supply_v), 2))


def _populate() -> None:
    """Fill DECK_TABLE from the literal rows (kept here so every field of
    every row is checked against the table's own invariants at import)."""
    rows: list[tuple[str, float, float, str, str, bool, str, str, float, str, str]] = [
        # process, T, Vdd, deck, sha256, exact, delay dir, est %, power dir, note
        ("tt", -40.0, 1.62, "tt_025C_1v80",
         "8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135",
         False, "optimistic", -19.8, "pessimistic",
         "both axes make the deck faster than the point (warmer and higher-V "
         "both reduce delay in this library); the only strongly delay-optimistic row"),
        ("tt", 27.0, 1.80, "tt_025C_1v80",
         "8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135",
         True, "none", 0.1, "none",
         "the nominal row: the PDK characterises tt at 25 C / 1.80 V, the repo's "
         "nominal point is 27 C (DR-0003); -2 K is ~-0.07 % on the deck pair"),
        ("tt", -40.0, 1.98, "tt_025C_1v80",
         "8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135",
         False, "pessimistic", 12.1, "mixed",
         "no tt deck exists below 1.80 V; the voltage term dominates the "
         "temperature term ~7:1. Power mixed: leakage over (deck warmer), "
         "dynamic under (deck V lower)"),
        ("tt", 125.0, 1.98, "tt_100C_1v80",
         "7c6b9fc62d7e83b8317cdca883d79107d8f2ff1061b04519fda7d3088560015b",
         False, "pessimistic", 17.5, "optimistic",
         "no tt deck exists above 1.80 V; the 100 C deck wins the |dT| "
         "tie-break at equal |dV| (DR-0017 anticipated exactly this). Power "
         "under: both the cooler deck's leakage and the lower deck V's "
         "dynamic term underestimate"),
        ("ss", -40.0, 1.62, "ss_n40C_1v60",
         "23cba893b985a950a7951e3f29ae66ae6a639aaef75c1478e2306fb68d4a7ee5",
         False, "pessimistic", 3.1, "optimistic",
         "exact temperature, 0.02 V of supply; the smallest mismatch of the 12"),
        ("ss", 27.0, 1.80, "ss_n40C_1v76",
         "f4f16d4f7040623afb60d0480a035e4128c5c1212361ae3bd13c3a52d9692a84",
         False, "pessimistic", 13.6, "optimistic",
         "no ss deck is characterised above 25 C below 100 C, nor above "
         "1.76 V; 1.76 V is the closest shipped ss voltage to 1.80 V"),
        ("ss", -40.0, 1.98, "ss_n40C_1v76",
         "f4f16d4f7040623afb60d0480a035e4128c5c1212361ae3bd13c3a52d9692a84",
         False, "pessimistic", 34.0, "optimistic",
         "1.98 V is above EVERY shipped ss deck voltage (max 1.76 V); exact "
         "temperature, the largest single-axis voltage gap the process can express"),
        ("ss", 125.0, 1.98, "ss_n40C_1v76",
         "f4f16d4f7040623afb60d0480a035e4128c5c1212361ae3bd13c3a52d9692a84",
         False, "pessimistic", 52.3, "optimistic",
         "the worst-served point of the matrix: ss_100C_1v60 loses the "
         "|dV|-first rule (0.38 V vs 0.22 V), so the deck is 165 K cold. "
         "Delay errs slow; leakage is severely under-called (the ss -40 -> "
         "100 C pair at 1.60 V moves library-mean cell_leakage_power x9335). "
         "A deck between the two temperatures above ~1.9 V would be needed "
         "to serve this point better"),
        ("ff", -40.0, 1.62, "ff_n40C_1v65",
         "dd777cb159bf2fc853773d74a3c3e8269b73869d25aae49d0f80f117df9631ee",
         False, "optimistic", -2.7, "pessimistic",
         "exact temperature, 0.03 V of supply; the deck's cells are faster "
         "than the point's (higher characterisation voltage)"),
        ("ff", 27.0, 1.80, "ff_n40C_1v76",
         "0f5b7ceef23114c3834870f86c2f90ea24d597622fcd5abd2916b1fb604e8a26",
         False, "pessimistic", 7.9, "optimistic",
         "no ff deck is characterised above -40 C below 100 C; 1.76 V is the "
         "closest shipped ff voltage to 1.80 V at -40 C"),
        ("ff", -40.0, 1.98, "ff_n40C_1v95",
         "fb61d91c55a7f85b1989e8149d040b13ba5e7f5478f5bf0c3c16c5da30720139",
         False, "pessimistic", 2.7, "optimistic",
         "exact temperature, 0.03 V of supply"),
        ("ff", 125.0, 1.98, "ff_100C_1v95",
         "15c9ccefec536ff35d694314af5812e7c03b4e5a356ec8ea28f2e40bbeec04e7",
         False, "pessimistic", 4.3, "optimistic",
         "1.95 V at 100 C is the closest any shipped deck comes to the "
         "125 C / 1.98 V point from any process corner"),
    ]
    for (proc, t, v, corner, sha, exact, ddir, est, pdir, note) in rows:
        deck = f"sky130_fd_sc_hd__{corner}.lib"
        assert deck in SHIPPED_DECKS, deck
        assert re.fullmatch(r"[0-9a-f]{64}", sha), (deck, sha)
        dproc, dtemp, dvdd = deck_corner(deck)
        assert dproc == proc, (deck, proc)
        dt, dv = round(dtemp - t, 1), round(dvdd - v, 2)
        if exact and (dt != 0.0 or dv != 0.0) and abs(dt) > 2.0:
            raise DeckMapError(f"{proc}/{t}/{v}: marked exact but deck is {dt} K {dv} V away")
        if not exact and dt == 0.0 and dv == 0.0:
            raise DeckMapError(f"{proc}/{t}/{v}: marked inexact but deck matches the point")
        if ddir not in _DELAY_DIRECTIONS or pdir not in _POWER_DIRECTIONS:
            raise DeckMapError(f"{deck}: bad direction vocabulary ({ddir!r}, {pdir!r})")
        if ddir == "pessimistic" and est <= 0 or ddir == "optimistic" and est >= 0:
            raise DeckMapError(f"{proc}/{t}/{v}: est {est:+.1f} % contradicts {ddir}")
        if ddir == "none" and abs(est) > 0.1:
            raise DeckMapError(f"{proc}/{t}/{v}: est {est:+.1f} % is not 'none'")
        DECK_TABLE[_key(proc, t, v)] = {
            "liberty_corner": corner,
            "liberty_deck": deck,
            "liberty_sha256": sha,
            "exact": exact,
            "dT_K": dt,
            "dV_V": dv,
            "delay_direction": ddir,
            "est_delay_error_pct": est,
            "power_direction": pdir,
            "note": note,
        }


_populate()

#: the process axis of the 12-point matrix (make-requests.py bundles these
#: per grid request; reduce-whole-block.py enumerates the same three).
MATRIX_PROCESSES = ("tt", "ss", "ff")


def matrix_points() -> list[tuple[str, float, float]]:
    """The 12 mapped points, sorted for stable output."""
    return sorted(DECK_TABLE)


def deck_row(process: str, temp_c: float, supply_v: float) -> dict:
    """The mapping row for one matrix point (a copy; callers must not mutate
    the table). Raises :class:`DeckMapError` when the point has no mapping --
    generation fails closed rather than guessing a deck."""
    key = _key(process, temp_c, supply_v)
    try:
        return dict(DECK_TABLE[key])
    except KeyError:
        mapped = ", ".join(f"{p}/{t:.0f}C/{v:.2f}V" for p, t, v in matrix_points()
                           if p == key[0]) or "(none)"
        raise DeckMapError(
            f"no Liberty deck mapping for {process}/{temp_c}C/{supply_v}V -- "
            f"mapped {key[0]} points: {mapped}. The matrix-to-deck table is "
            "sim/post-layout-whole-block/pvt_deck_map.py (issue #595); add "
            "the row there, do not pick a deck ad hoc") from None


def deck_path(row: dict, libs_ref_dir: Path | None) -> Path:
    """The deck's path: absolute under *libs_ref_dir* when the install is
    known, else the install-relative form (recorded as such in plan.json)."""
    rel = LIB_SUBDIR / row["liberty_deck"]
    return (Path(libs_ref_dir) / rel) if libs_ref_dir is not None else \
        Path("sky130A") / "libs.ref" / rel


def boundary_load_block() -> dict:
    """The boundary-load statement every plan.json carries (option 2)."""
    return {
        "option": BOUNDARY_LOAD_OPTION,
        "source": BOUNDARY_LOAD_SOURCE,
        "record": BOUNDARY_LOAD_RECORD,
        "what_option_1_would_have_changed":
            "kept the first receiving cells of raw_bit/raw_valid/clk/rst_n at "
            "transistor level inside the analog partition, moving instances "
            "across the partition partition_check() asserts (25 356 = 264 + "
            "25 091 + 1) and re-introducing a transistor-level corner "
            "dependency inside the gate partition",
    }


def verify_against_disk(libs_ref_dir: Path) -> list[dict]:
    """Re-hash every mapped deck against *libs_ref_dir*.

    Returns the rows checked; raises :class:`DeckMapError` on any missing
    file or hash mismatch -- a PDK version bump must stop generation, not
    silently change which delays every digital result derives from.
    """
    import hashlib
    checked = []
    for key in matrix_points():
        row = DECK_TABLE[key]
        p = Path(libs_ref_dir) / LIB_SUBDIR / row["liberty_deck"]
        if not p.is_file():
            raise DeckMapError(f"pinned deck {row['liberty_deck']} is absent from "
                               f"{Path(libs_ref_dir)} (PDK version bump?)")
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h != row["liberty_sha256"]:
            raise DeckMapError(
                f"{row['liberty_deck']}: on-disk sha256 {h} != pinned "
                f"{row['liberty_sha256']} -- the install is not the PDK the "
                "table was derived from; re-derive the mapping (issue #595), "
                "do not ignore the mismatch")
        checked.append({**row, "point": {"process": key[0], "temperature_c": key[1],
                                          "supply_v": key[2]}})
    return checked


def plan_entry(processes: list[str], temp_c: float, supply_v: float,
               libs_ref_dir: Path | None = None) -> dict:
    """The ``plan.json`` block one whole-block request carries for the digital
    half: the boundary-load option plus one deck row per process corner.

    With *libs_ref_dir* (a real generation, PDK resolved) the deck paths are
    absolute and every sha256 is re-verified on disk. Without it (CI, no
    PDK) the paths are install-relative and the sha256 values are the
    committed table's -- the two are equal whenever the install matches the
    pin, which :func:`verify_against_disk` and the PDK-gated test check.
    """
    if libs_ref_dir is not None:
        verify_against_disk(libs_ref_dir)
    decks = {}
    for proc in processes:
        row = deck_row(proc, temp_c, supply_v)
        decks[proc] = {
            "liberty_deck": str(deck_path(row, libs_ref_dir)),
            "liberty_sha256": row["liberty_sha256"],
            "exact": row["exact"],
            "dT_K": row["dT_K"],
            "dV_V": row["dV_V"],
            "delay_direction": row["delay_direction"],
            "est_delay_error_pct": row["est_delay_error_pct"],
            "power_direction": row["power_direction"],
            "note": row["note"],
        }
    return {
        "boundary_load": boundary_load_block(),
        "decks": decks,
        "deck_path_form": ("absolute (sha256 verified on disk)"
                           if libs_ref_dir is not None else
                           "install-relative (PDK not resolved in this "
                           "environment; sha256 from the committed table)"),
    }
