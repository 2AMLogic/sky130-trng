# 20261121 -- DR-0017's two open per-point choices are made: boundary load = option 2 (Liberty input-pin capacitance), and the 12-point matrix is mapped to named Liberty decks with stated error directions (issue #595)

**Claim**: the two items DR-0017 left open and #431's Builder note (2026-11-05)
queued as its own slice are now chosen, recorded, and executable:

1. the **boundary-load model** is **option 2**: the load the analog side sees
   at `raw_bit`/`raw_valid` (and the digital share of `clk`/`rst_n`) is the
   Liberty input-pin `capacitance` of the first receiving standard cells,
   taken from the deck the point maps to;
2. every one of the 12 matrix points (tt/ss/ff x (-40 C, 1.62 V),
   (27 C, 1.80 V), (-40 C, 1.98 V), (125 C, 1.98 V)) is mapped to **one
   named Liberty deck, pinned by sha256**, with the nearest-deck rule, the
   direction of the delay error and the direction of the power error stated
   per row.

This is a mapping and a record, **not a simulation**: no ngspice ran for this
record (locally or on the fleet), no whole-block point was simulated, nothing
here claims any #18 AC3 row, and `GRID_TIMEOUT_S` / `poll_timeout_s` are
untouched. The per-direction evidence is file parsing of the pinned PDK's own
Liberty decks (`analysis/deck-axis-sensitivity.py`), not simulation.
Provisional, simulation-derived, not foundry sign-off, **not silicon**.

## 1. Boundary-load model: option 2

Chosen: **option 2 -- model the load as the Liberty input-pin capacitance of
the receiving cells at the mapped deck** (DR-0017 "Boundary-load model",
option 2). Source of every load value: the `capacitance` attribute on the
input pin of each first receiving cell, read from the deck the (process, T,
Vdd) point maps to in the table below -- the same file the delays come from,
pinned by the same sha256. `make-gate-model.py` already emitted exactly this
per `d_genlut` input purely so the cards elaborate (#486 reduction 8); this
record makes it the deliberate choice, and since this change every
`plan.json` the generator writes carries
`boundary_load_option: {option: 2, source: ...}`.

Rejected, with the reason:

| Option | Why not |
|---|---|
| 1 -- keep the first receiving cells of `raw_bit`/`raw_valid` (and the digital `clk`/`rst_n` receivers) at transistor level | moves transistor instances across the analog/digital partition that `make-requests.py:partition_check()` asserts before any plan is written (25 356 = 264 analog transistors + 25 091 digital transistors + 1 antenna diode; the flat `.SUBCKT` ports equal `trng_whole.sim.ports.json`; shared nets are exactly `clk`/`rst_n`/`raw_bit`/`raw_valid`). Option 1 would break that accounting -- the partition hashes in every committed `plan.json` would describe a partition that no longer exists -- and it re-introduces a transistor-level corner dependency (`.lib` models at the analog corner) inside the gate partition, the exact mixing DR-0017 exists to avoid. |
| extracted net capacitance as a second source | not available: the committed whole-block extract is **connectivity-only** (no R/C; `make-netlist.py` row of the slug README). Stated here so no reader assumes it was overlooked. |

What option 1 would have changed, concretely: the sampler's `raw_bit` /
`raw_valid` drivers would have seen the real transistor gates of the first
inverter stage(s) instead of a linear capacitance, and the boundary would
have lived one cell deeper; the price is above (broken partition invariant,
mixed corner domains). The threshold side of the boundary is unchanged by
this record and stays as #486 built it: `adc_bridge`'s band is
`(0.5 -+ 0.05) * supply_v` (`BRIDGE_BAND_FRAC = 0.05`), centred on the deck's
own `input_threshold_pct_rise`/`_fall` (asserted 50/50), so bridge levels
move with the corner supply as DR-0017 requires -- that is the VIL/VIH band
in use, recorded here without changing it (curator instruction).

The pin capacitances themselves vary with the deck by roughly +-10 %
(or2_2/A: 1.492 fF at `tt_025C_1v80`, 1.344 fF at `ss_n40C_1v60`, 1.633 fF at
`ff_100C_1v95`), correlated with the characterisation voltage, so the
boundary load inherits that spread from the deck choice -- disclosed as part
of the mapping, not separately modelled.

## 2. The 12-row deck mapping

The pinned install
(`klt pdk find --pdk sky130A` -> volare `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`)
ships 16 non-ccsnoise `sky130_fd_sc_hd` decks, listed per process corner,
not per (T, Vdd) point:

* `tt`: 025C/1v80, 100C/1v80 -- nothing off 1.80 V, nothing cold;
* `ss`: n40C/{1v28, 1v35, 1v40, 1v44, 1v60, 1v76}, 100C/{1v40, 1v60};
* `ff`: n40C/{1v56, 1v65, 1v76, 1v95}, 100C/{1v65, 1v95}.

**Nearest-deck rule (declared): minimise |dV| first, tie-break on |dT|.**
Voltage precedes temperature because the deck-derived sensitivities make the
voltage term dominate by roughly an order of magnitude (section 3). No
interpolation is applied anywhere: generation uses the named deck as-is.

Single source of truth: `sim/post-layout-whole-block/pvt_deck_map.py`
(the table, the rule, the pinned hashes; fail-closed helpers). The decks the
12 rows use:

| deck file (under `libs.ref/sky130_fd_sc_hd/lib/`) | sha256 |
|---|---|
| `sky130_fd_sc_hd__tt_025C_1v80.lib` | `8e78e14442062dba34d414fca6490b2f6b96038d4510d1438ca44fee31487135` |
| `sky130_fd_sc_hd__tt_100C_1v80.lib` | `7c6b9fc62d7e83b8317cdca883d79107d8f2ff1061b04519fda7d3088560015b` |
| `sky130_fd_sc_hd__ss_n40C_1v60.lib` | `23cba893b985a950a7951e3f29ae66ae6a639aaef75c1478e2306fb68d4a7ee5` |
| `sky130_fd_sc_hd__ss_n40C_1v76.lib` | `f4f16d4f7040623afb60d0480a035e4128c5c1212361ae3bd13c3a52d9692a84` |
| `sky130_fd_sc_hd__ff_n40C_1v65.lib` | `dd777cb159bf2fc853773d74a3c3e8269b73869d25aae49d0f80f117df9631ee` |
| `sky130_fd_sc_hd__ff_n40C_1v76.lib` | `0f5b7ceef23114c3834870f86c2f90ea24d597622fcd5abd2916b1fb604e8a26` |
| `sky130_fd_sc_hd__ff_n40C_1v95.lib` | `fb61d91c55a7f85b1989e8149d040b13ba5e7f5478f5bf0c3c16c5da30720139` |
| `sky130_fd_sc_hd__ff_100C_1v95.lib` | `15c9ccefec536ff35d694314af5812e7c03b4e5a356ec8ea28f2e40bbeec04e7` |

The 12 rows (dT/dV = deck characterisation minus the point; delay direction:
which way the deck's delays err against the point's cells, pessimistic =
deck slower; power direction: which way the deck's power characterisation
errs, dynamic with the deck's V, leakage with the deck's (T, V) -- "mixed"
= the two pull opposite ways, no net direction established):

| process | T (C) | Vdd (V) | deck | dT (K) | dV (V) | delay | est. delay err | power |
|---|---|---|---|---|---|---|---|---|
| tt | -40 | 1.62 | `tt_025C_1v80` | +65 | +0.18 | **optimistic** | ~-20 % | pessimistic |
| tt | 27 | 1.80 | `tt_025C_1v80` | -2 | 0 | exact (nominal) | +0.1 % | none |
| tt | -40 | 1.98 | `tt_025C_1v80` | +65 | -0.18 | **pessimistic** | ~+12 % | mixed |
| tt | 125 | 1.98 | `tt_100C_1v80` | -25 | -0.18 | **pessimistic** | ~+17 % | optimistic |
| ss | -40 | 1.62 | `ss_n40C_1v60` | 0 | -0.02 | **pessimistic** | ~+3 % | optimistic |
| ss | 27 | 1.80 | `ss_n40C_1v76` | -67 | -0.04 | **pessimistic** | ~+14 % | optimistic |
| ss | -40 | 1.98 | `ss_n40C_1v76` | 0 | -0.22 | **pessimistic** | ~+34 % | optimistic |
| ss | 125 | 1.98 | `ss_n40C_1v76` | -165 | -0.22 | **pessimistic** | ~+52 % | optimistic |
| ff | -40 | 1.62 | `ff_n40C_1v65` | 0 | +0.03 | **optimistic** | ~-3 % | pessimistic |
| ff | 27 | 1.80 | `ff_n40C_1v76` | -67 | -0.04 | **pessimistic** | ~+8 % | optimistic |
| ff | -40 | 1.98 | `ff_n40C_1v95` | 0 | -0.03 | **pessimistic** | ~+3 % | optimistic |
| ff | 125 | 1.98 | `ff_100C_1v95` | -25 | -0.03 | **pessimistic** | ~+4 % | optimistic |

The nominal row: the PDK characterises `tt` at 25 C / 1.80 V and the repo's
nominal point is 27 C / 1.80 V (DR-0003/DR-0008); -2 K is ~+0.1 % on the
temperature pair, so the row is marked exact with that stated.

## 3. Where the directions come from (and the canary finding)

`analysis/deck-axis-sensitivity.py` (committed; pure Liberty parsing with
`make-gate-model.py`'s own parser, over the 63 characterised cell types of
the 64 the routed netlist uses, delays reduced exactly as the gate model
reduces them -- max over arcs, bilinear, clamped; checked at two operating
points, (0.1 ns, 6 fF) and (0.4 ns, 20 fF)):

| deck pair (axis) | library-mean delay | library-mean `cell_leakage_power` |
|---|---|---|
| tt 025C -> 100C at 1.80 V (T) | x0.956 (-4.4 %) | x333 |
| ss -40C -> 100C at 1.60 V (T) | x0.845 (-15.5 %) | x9335 |
| ff -40C -> 100C at 1.95 V (T) | x0.910 (-9.0 %) | x2802 |
| ff 1v65 -> 1v95 at -40 C (V) | x0.734 (-26.6 % over 0.30 V, ~-89 %/V) | x6.9 |
| ss 1v60 -> 1v76 at -40 C (V) | x0.753 (-24.7 % over 0.16 V, ~-154 %/V) | x3.1 |

**The canary finding: both sensitivities have the same sign.** This library
gets *faster* warm (temperature inversion at 1.8 V-class supplies -- the tt
pair, same voltage, 25 C -> 100 C, moves the mean delay -4.4 %) and faster
at high supply. Because both axes push delay the same way, every row's net
delay direction is established from the two per-axis sensitivities
(`sT*dT + sV*dV`, sT = -0.059/-0.111/-0.064 %/K for tt/ss/ff, sV = -89 %/V
ff / -154 %/V ss; tt has no voltage pair, the ff figure is the disclosed
proxy) -- no row is left "mixed" for delay. The estimates in the table are
that linearised sign evidence, **not** corrected values and not
interpolation: generation uses the named deck as-is.

Per-row power direction: dynamic power moves with the deck's V (C*V^2);
leakage rises steeply with both T and V (the table above), so a deck that is
colder or lower-V than the point under-calls the point's leakage
(optimistic) and a warmer or higher-V deck over-calls it (pessimistic).

Hard rows, called out:

* **ss / 125 C / 1.98 V is the worst-served point**: `ss_100C_1v60` loses
  the |dV|-first rule (0.38 V vs 0.22 V), so the deck is 165 K cold and
  0.22 V low. Delay errs slow (~+52 % linearised); leakage is severely
  under-called (the ss -40 -> 100 C pair moves the mean x9335). To serve
  this point better the library would need an ss deck characterised
  between the two temperatures above ~1.9 V; none ships in the pinned
  install. Nothing downstream may read the ss/125 C digital timing as
  tight evidence.
* **tt / -40 C / 1.62 V is the only strongly delay-optimistic row**
  (~-20 %): both axes make the deck faster than the point's cells would
  be, because no tt deck exists below 1.80 V or below 25 C. Timing-margin
  conclusions at that point inherit an optimistic deck and must say so.
* `tt / 125 C / 1.98 V`: `tt_100C_1v80` wins the |dT| tie-break at equal
  |dV| -- DR-0017 anticipated exactly this ("the public library also ships
  100 C decks, which may be closer than an n40C deck for the 125 C / 1.98 V
  point").

Per-cell spread, disclosed: the temperature direction holds for the library
mean at both operating points, but a minority of cells individually move
the other way (11 of 63 on the tt pair at (0.1 ns, 6 fF); pair min/max
x0.88/x1.09). The directions are mean-level statements, not per-cell
guarantees.

## 4. What is now executable

* `pvt_deck_map.py` -- the single source of truth (12 rows, pinned sha256,
  the rule, the directions; `deck_row` raises on any unmapped point).
* `make-requests.py --set grid` writes `plan.json.gate_model_pvt` per
  request: the boundary-load block plus one deck row (path + sha256 +
  directions) per process corner. With the PDK resolvable the paths are
  absolute and every hash is re-verified on disk (a PDK bump fails
  generation); without it (CI) the paths are install-relative and the
  hashes are the committed table's.
* `make-gate-model.py --point PROC:TEMP_C:VDD` (e.g. `ss:-40:1.62`) takes
  its Liberty deck from the mapping (sha256-pinned), derives the bridge
  supply, the request's temperature and the process corner from the point,
  refuses `--point` combined with `--liberty`/`--corner`/`--supply-v`/
  `--temp-c`, and records `pvt_point` + `boundary_load_option` in its
  `plan.json`.
* Unit tests (both PR-blocking, stdlib-only):
  `sim/post-layout-whole-block/test_make_requests.py` (#595 block: the 12
  rows cover tt/ss/ff x GRID exactly, each row IS the nearest shipped deck
  under the |dV|-first rule, directions/estimates are self-consistent, an
  unmapped point fails `deck_row` AND grid generation leaves the unmapped
  point unwritten, and every generated grid plan carries the fields) and
  `sim/tests/test_gate_model.py` (#595 classes: `--point` parse and refusal
  paths klt-free; against the PDK, all 12 pinned hashes match disk and a
  `--point` run carries the mapping in its plan and request).

## 5. Limits of this choice

* The decks are characterised per process corner, not per (T, Vdd) point;
  11 of the 12 points are served approximately, and the deviations above
  travel with every digital-function result (O2-O4, O6) per DR-0017 -- they
  are not timing sign-off and not silicon.
* The direction percentages are linearised, mean-level evidence from deck
  pairs, not measurement of the point itself; no interpolation is applied
  and none of the numbers is a corrected delay.
* Gate-level runs do not measure a digital supply current and do not
  consume the decks' leakage data at all (DR-0017's provenance rules stand:
  `digital_dynamic_power_w_estimate` stays gate-level provenance, O5d/O7/O8
  stay UNMET); the power directions describe the deck characterisation
  error wherever that data is later consumed.
* The committed `corners/gate-model-full/gate-model.manifest.json`
  `reductions` commentary still says the option-1-vs-2 choice "is open,
  #431" -- it predates this record and is evidence of the #486 run, kept
  byte-stable on purpose (regenerating it would falsify what that run
  recorded); every `plan.json` written since overrides that one `reductions.input_load`
  entry at plan level (the manifest text is untouched), so a plan carries the
  settled statement only, next to `boundary_load_option`.
* The six committed legacy `plan.json` files under `corners/` predate
  `gate_model_pvt` and are not regenerated (#507 convention); the next run
  writes a fresh corner directory.
* Still open after this record (unchanged): the coupled whole-block deck,
  `GRID_TIMEOUT_S` / `poll_timeout_s` sizing, and the Icarus + SDF
  cross-check -- the remaining items of the README's Open list and of
  #431's decomposition.

Reported on #431 and #307. Toolchain: no klayout-tools gap found -- `klt
pdk find` + `--liberty PATH` could already express a per-point deck, so no
friction-ledger row is needed for this change.
