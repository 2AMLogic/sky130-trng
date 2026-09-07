# layout/sampler_core-placement-poc

Placement-only exploration of `sampler_core`'s six-`sampler_dff` bank —
issue #22's own acceptance bar, and the last remaining gap in its "DRC-clean,
LVS-clean GDS for the entropy source + sampler" criterion now that
`ro_array_core` (`layout/ro_array_core/`, DRC-clean and `klt lvs`-**match**,
132/132 devices, 96/96 nets) and standalone `sampler_dff`
(`layout/sampler_dff/`, DRC-clean and `klt lvs`-**match**, 22/22 devices,
14/14 nets) are both already done.

## Why this is a proof-of-concept directory, not `layout/sampler_core/`

`design/sampler_core.spice`'s own `.subckt sampler_core` is **not** "six
samplers" alone — it is one `ro_array_core` instance (`xdut`) plus six
`sampler_dff` instances, all wired together
(`design/README.md`'s own line: "`sampler_core`  the sampler, wired to the
source"). Grepping every `.subckt` line in `design/*.spice` confirms there is
no standalone "just the six samplers" reference netlist to `klt lvs` against
at the narrower scope this directory explores. Every earlier hierarchy level
in this repo (`layout/ro_ring5/`, `layout/sampler_dff/` itself,
`layout/ro_array_core/`'s own `-placement-poc` predecessor) started from an
unrouted placement proof-of-concept before the committed cell — see
`layout/README.md`'s "Why the `place` stage exists on its own" section for
the rationale this directory reuses. This is that first step for the sampler
side: prove the six-instance floorplan is DRC-legal before spending the
(considerable, per `layout/sampler_dff/README.md`'s own history) effort
deriving exact bus/fan-out routing geometry.

## What this directory does

`build.py` places six already-composed, individually DRC-clean and
`klt lvs`-clean `layout/sampler_dff/sampler_dff.gds` instances side by side
via `klt gen-compose`'s `blocks[].cell` mechanism (the same technique
`layout/ro_array_core/cell.json` used to place already-composed `ro_ring5`/
`ro_buf`/`xor2` instances), in `design/sampler_core.spice`'s own instance
order and naming (`sb`, `sv`, `sr1`-`sr4`, matching `xsb`/`xsv`/`xsr1`-`xsr4`):

| id | source `d` net (once wired) | role |
|---|---|---|
| `sb` | `xo` (the array's own combining-node output) | raw bit tap |
| `sv` | `vdd` (tied high) | "always 1" reference sampler |
| `sr1`-`sr4` | `ro1`-`ro4` (each ring's own buffered tap) | per-ring bits |

**Zero routing** is attempted: no `vdd`/`vss`/`clk`/`rst_n` shared bus, no
wiring to a (not-yet-placed) `ro_array_core` instance, no per-instance `d`/`q`
promotion. `connectivity: []` and `pins: []` in the `klt gen-compose` request.

## A tooling finding worth recording (not a `klt` gap): `ports` is optional

`layout/bin/compose-cell.py`'s own docstring implies every `blocks[].cell`
entry needs a hand-declared `ports[]` list (and every committed cell under
`layout/` so far has one, since every committed cell's later stages route
onto those declared ports). Testing directly against `klt gen-compose`
confirmed `ports[]` is **optional**: when a stage's own `connectivity[]`
never references a block's ports, `gen-compose` reads that block's bbox
straight from the referenced stream (`"with its own bbox read from the
stream when not declared"`, its own `--help` text) and places it with no
port geometry at all — exactly this directory's placement-only use case, and
already the same technique `layout/ro_array_core-placement-poc/`'s own first
increment used (its own `compose.request.json` blocks carry no `ports[]`
either). Saved deriving `sampler_dff`'s own six top-level pin coordinates
(`d`/`clk`/`rst_n`/`q`/`vdd`/`vss`) for this increment — that derivation is
real, non-trivial work (every prior single-net routing PR on
`layout/sampler_dff/` spent significant effort on exactly this kind of
measurement) that a follow-on *routing* increment will still need, but a
pure placement pass does not.

## Floorplan: pitch and origin

`layout/sampler_dff/sampler_dff.gds`'s own bbox (unchanged since PR #99
completed its routing) is `x0=-2.19 x1=50.47 y0=-3.585 y1=7.085` — a
52.66 x 10.67 um block. Six instances at **55.66 um pitch**
(52.66 + 3.0 um bbox-to-bbox gap — the same "generous 3.0 um" spacing
`layout/sampler_dff/README.md`'s own nine-leaf-cell `place` stage used, and
`layout/ro_ring5/`'s own `place` stage before it), all at the **same
`y=0.0` origin** so that any later bus-routing increment sees every
instance's own `vdd`/`vss`/`clk`/`rst_n` pad at an identical y — the same
alignment `layout/ro_array_core/`'s own row of rings/buffers/XORs used.
Composed bbox: `x0=-2.19 y0=-3.585 x1=328.77 y1=7.085` (six times the width
of a single `sampler_dff`, plus five 3.0 um gaps).

## Verification

- **`klt drc --deck sky130`**: **clean, 0 violations**, on the first
  attempt — the 3.0 um bbox-to-bbox gap is comfortably clear of every
  sky130 spacing rule any of the six identical, already-individually-clean
  cells could trigger.
- **`klt extract --deck sky130`**: **132 devices** (66 nfet + 66 pfet — 6 x
  `sampler_dff`'s own 11 nfet/11 pfet split exactly), **79 nets** (not the
  naively-expected 6 x 14 = 84): the five-net difference is **all** one
  mechanism, confirmed by inspecting the net list directly — every
  instance's own `vss`-labelled net (the NMOS bulk/substrate connection)
  merges into **one** shared net across all six instances, while every
  instance's own `vdd`-labelled net stays in **six separate** buckets (one
  per instance, correctly unmerged). This is consistent with sky130's own
  real electrical behaviour and with a related finding already documented
  in this repo (issue #27's own scope note: "NMOS needs no per-device strap
  (`vsubs` is sky130's one global substrate net)", and
  `layout/README.md`'s "Environment finding" on how `klt extract
  --parasitics` names that same global body `vsubs`): the p-substrate is one
  physically shared body across the whole die regardless of drawn metal
  routing, so `klt`'s (non-parasitic, plain `extract`) device-recognition
  model correctly ties every NMOS bulk together under the `vss` label
  without needing any drawn connection between the six otherwise-unwired
  instances, while PMOS bodies (isolated per-nwell, no substrate-wide tie)
  correctly do **not** merge.
  Every other per-instance warning `klt extract` reports is the same
  already-`klt lvs`-verified internal-alias merge each standalone
  `sampler_dff` already carries (e.g. the `inv_q`/`tg_fbs`/`tg_s`-side `s`
  net's own nine local labels), repeated once per instance — not a new
  finding.
- **No `klt lvs` call** — see "Why this is a proof-of-concept directory"
  above; there is no reference `.subckt` at this exact scope to compare
  against yet.
- `python3 build.py` is idempotent and reproducible from this directory
  (re-run to regenerate `compose.request.json`/`compose.response.json`/
  `drc.json`/`extract.json`; nothing here is hand-edited).

## What remains (issue #22 / #27)

In rough dependency order:

1. **`vdd`/`vss` shared bus** across all six instances — the most
   mechanically similar step to `layout/sampler_dff/`'s own first routing
   increment, since every instance already has an identical rail pad at an
   identical y (this directory's whole point).
2. **`clk`/`rst_n` shared fan-out** across all six instances — a wider,
   six-way version of `layout/sampler_dff/README.md`'s own "Result: `clk`
   fan-out" derivation (a five-pin fan-out inside one cell); this is a
   six-pin fan-out across cells, likely the single hardest remaining step
   given that section's own account of how much `clk`/`clkb` phase-alternation
   analysis a fan-out this shape needed even at one-cell scope.
3. **Placing a `ro_array_core` instance** in this same row (or an adjacent
   one) and wiring its `xo`/`ro1`-`ro4` outputs to `sb`'s/`sr1`-`sr4`'s own
   `d` pins, plus `sv`'s `d` tied to the shared `vdd` bus.
4. **Promoting the six `d`/`q` pin pairs** (`sb`'s `raw_bit`, `sv`'s
   `raw_valid`, `sr1`-`sr4`'s `ring_bit1`-`ring_bit4`) plus `en1`-`en4`/
   `vddr1`-`vddr4` (from the placed `ro_array_core`) as `sampler_core`'s own
   top-level pins.
5. **Whole-cell `klt lvs`** against `design/sampler_core.spice`'s real
   `.subckt sampler_core` (with `ro_array_core`/`sampler_dff` as LVS
   dependencies, `flatten_reference: true`, the same technique
   `layout/ro_array_core/cell.json`'s own `lvs` section already uses).
6. **Post-layout PVT simulation** of the fully assembled, LVS-clean
   `sampler_core` — the whole-chain (raw-tap-to-sampled-bit) claim issue #22
   was originally filed for, still open after every increment so far.
7. DR-0003 §8's `wstv` inter-ring decorrelation gap is **unaffected** by any
   of the above — it is about the entropy source's own inter-ring supply
   coupling (already re-evaluated at array scope by DR-0005/DR-0006), not
   the sampler side of the raw tap.

No `2AMLogic/klayout-tools` friction was found by this increment — the
`ports[]`-optional behaviour above is a documentation/discoverability gap in
this repo's own `layout/bin/compose-cell.py` docstring, not a `klt` tool
gap (the tool's own `--help` text already states the bbox-fallback
behaviour correctly).
