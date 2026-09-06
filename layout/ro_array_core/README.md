# layout/ro_array_core

**The whole entropy source, composed as a `--check`-reproducible cell
recipe** — `design/ro_array_core.spice`'s own `.subckt ro_array_core`: four
*deliberately different* `ro_ring5` rings (`wstv` 0.42/0.44/0.46/0.48 µm,
four physically distinct committed cells), four `ro_buf` output buffers, and
a three-`xor2` combining tree (`xa1 = xor(ro1, ro2)`, `xa2 = xor(ro3, ro4)`,
`xa3 = xor(t1, t2) = xo`). **132 devices (66 nfet + 66 pfet), 96 nets, `klt
drc` clean, `klt lvs` match.**

This supersedes
[`layout/ro_array_core-placement-poc/`](../ro_array_core-placement-poc/README.md),
which reached the same DRC/LVS verdict across nine hand-maintained
`gen-compose` request files, a directory-local `array-reference.py`, and no
`compose-cell.py --check` reproducibility at all. Nothing in that PoC's
result is corrected here — unlike the `xor2` promotion, whose PoC's central
prediction turned out to be wrong, this one is a straight promotion. What
changes is that the array is now rebuilt and re-verified by the same one
command every other cell under `layout/` is:

```bash
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b   # layout/pdk.json
# klt's shared install churns between (and within) sessions -- pin it, per
# layout/README.md's "Correcting the curation note":
#   python3 -m venv /tmp/klt-venv && /tmp/klt-venv/bin/pip install \
#     "git+https://github.com/2AMLogic/klayout-tools@c6dbf66c53c6e9a73c4f5ae5e41a98e8fe414252"
python3 layout/bin/compose-cell.py layout/ro_array_core/cell.json           # rebuild in place
python3 layout/bin/compose-cell.py layout/ro_array_core/cell.json --check   # verify, don't overwrite

# the two evidence scripts this directory also commits (run from here,
# after the rebuild above -- both exit non-zero if their claim fails):
cd layout/ro_array_core
python3 vss-tap-scan.py            # -> vss-tap-scan.json        (all_taps_clear: true)
python3 lvs-negative-controls.py   # -> lvs-negative-controls.json (both controls -> mismatch)
```

and that `ring1..4`'s and `xa1..3`'s own `vss` taps — the one item the PoC
left open that is not a whole separate deliverable — are now drawn (stages
`vssstub`/`vssbus` below).

## Result

| Step | Verdict | Evidence |
|---|---|---|
| `klt gen-compose` stage `core` (li1-placed blocks, met1 routing) | **12/12 nets routed** (`rn1`-`rn4`, `ro1`-`ro4`, the 4-pin buffer `vss` bus, `t1`, and the `t2`/`b3` promotion stubs) | `core.compose.response.json` |
| `klt gen-compose` stage `t2bridge` (met2) | **1/1 routed** — `t2`, 56.875 µm | `t2bridge.compose.response.json` |
| `klt gen-compose` stage `vddstub` (met1) | **7/7 routed** — four 1.76 µm buffer stubs, three 1.5 µm XOR stubs | `vddstub.compose.response.json` |
| `klt gen-compose` stage `vddbus` (met2) | **6/6 legs routed** — the `buf4`→`buf3`→`buf2`→`buf1`→`xa1`→`xa2`→`xa3` chain | `vddbus.compose.response.json` |
| `klt gen-compose` stage `vssstub` (met1) | **3/3 routed** — `xa1`/`xa2` 1.695 µm, `xa3` 0.495 µm | `vssstub.compose.response.json` |
| `klt gen-compose` final stage (met2) | **7/7 legs routed** — three inter-ring rail legs, the 0.425 µm drop onto the buffer `vss` bus, and the three-XOR chain | `compose.response.json` |
| `klt drc --deck sky130` | **clean, 0 violations** | `drc.json` |
| `klt extract --deck sky130` | **132 devices (66 nfet, 66 pfet), 96 nets, 86 pins** | `extract.json`, `ro_array_core.spice` |
| `klt lvs` vs. `design/ro_array_core.spice`'s `.subckt ro_array_core` | **match** — 132/132 devices, 96/96 nets, 0 errors | `lvs.json`, `ro_array_core.ref.spice` |
| `lvs-negative-controls.py` | **both deliberately-wrong references → `mismatch`** (122/132 and 112/132 devices) | `lvs-negative-controls.json` |
| `vss-tap-scan.py` | **all 12 taps clear** before any `vss` metal was drawn | `vss-tap-scan.json` |

Cell extent `217.07 x 34.72 µm` (`klt stats`: `x` -0.585..216.485, `y`
-3.635..31.085), 3356 polygons, 26.8% density. Generated on
`klt 0.3.0+gc6dbf66c53c6` / KLayout 0.30.12 against open_pdks
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` — `layout/pdk.json`'s own pin.

## Six stages, and why the PoC's nine requests collapse to six

The PoC ran nine `klt gen-compose` calls. Only six of them are *recipe*; the
other three are increment history, and reading them as a nine-stage pipeline
is the mistake this promotion had to avoid:

- **`signal` … `signal6` were never a chain.** Each one re-composed the
  **same** eleven-block floorplan from the leaf cells, with one more net
  routed than the increment before it. Only the last of them (`signal6`)
  contains all the others' routing, so only `signal6` survives here — as
  stage `core`. The five before it are the PoC's append-only record of how
  the routing was found, not steps that have to be re-run.
- **`signal7`/`signal8`/`signal9` *are* a chain** — each places the previous
  stage's own composed GDS as a single block and adds one routing plane's
  worth of new metal on top. They become stages `t2bridge`, `vddstub` and
  `vddbus`.
- **`vssstub`/`vssbus` are new**, and close the PoC's own remaining
  not-a-separate-deliverable item.

| Stage | Role (`klt` name → sky130 layer) | What it draws |
|---|---|---|
| `core` | `metal` placement + `metal2` = met1 | 11 blocks; `rn1`-`rn4`, `ro1`-`ro4`, buffer `vss` bus, `t1`, and `t2`/`b3`'s met1 promotion stubs. `en1`-`en4`, `vddr1`-`vddr4`, `xo` promoted as bare pins |
| `t2bridge` | `metal3` = met2 | `t2` (`xa2.y` → `xa3.b`) over the top at `y = 31.0` |
| `vddstub` | `metal2` = met1 | seven `vdd` promotion stubs (4 × `ro_buf`, 3 × `xor2`) |
| `vddbus` | `metal3` = met2 | the six-leg `vdd` chain |
| `vssstub` | `metal2` = met1 | three `vss` promotion stubs (3 × `xor2`) |
| `vssbus` (final) | `metal3` = met2 | the array-wide `vss` strap |

Each non-final stage commits its own `<name>.compose.request.json` /
`<name>.compose.response.json` / `<name>.gds`, and `--check` diffs every
one of those responses' `cell_name`/`bbox_um` as well as the final cell's
DRC/extract/LVS verdicts — so drift in an early stage's placement is caught
even when it happens not to move the final verdict.

### `cell.from_stage`: the one thing `compose-cell.py` was missing

`blocks[].from_stage` already existed, and hands a later stage the earlier
stage's `gen-compose` **response** — whose `ports[]` are exactly that
stage's own `pins[]`. That is everything a leaf or ring cell's promotion
stages need, and nothing this array's later stages can use: every `vdd`/`vss`
promotion stub *starts* on a tap pad measured by coordinate **inside** an
already-composed block (none of the composed leaf cells expose declared
pins), and *ends* on a met1 tip that only exists once that stage has drawn
it. Neither is a `pins[]` entry of anything.

So this increment adds `blocks[].cell.from_stage` — `blocks[].cell`'s
hand-declared `ports[]` shape, pointed at a stage instead of at a committed
sibling cell:

```json
{"id": "core", "cell": {"from_stage": "vddstub", "ports": [ … ]}}
```

The distinction that matters, and the reason it has its own unit coverage in
`layout/test_compose_cell.py`, is what `gds_path` is resolved **relative
to**. A committed sibling cell's path is relative to the cell.json, so
`--check` has to absolutize it (the temp rebuild directory has no
`../ro_buf/`). A stage's stream is produced by the run in progress, so it
must be read back from the *output* directory and must **not** be
absolutized. Get that backwards and nothing fails loudly: `--check` would
compose every later stage over the **committed** earlier stages and report
"rebuild matches committed evidence" no matter what drifted in stage 1.

## The `vss` taps (stages `vssstub`/`vssbus`)

The PoC's Increment 5 established that this is **not** LVS-blocking:
`klt extract`'s sky130 deck ties every un-isolated NMOS body (this design
draws no deep-nwell isolation) to one global substrate node, so `vss` was
already a single 122-device net across the whole composed array *before any
inter-block `vss` metal existed at all* — the same `connect_global`
mechanism `spec/decision-records/DR-0005-*.md` finding 3 documents on a
single ring's parasitics. `net_count` is 96 with and without these two
stages, and the LVS verdict is unchanged by them.

They are drawn anyway, because a fabricated die needs an explicit
low-impedance strap and the substrate's own resistance is unmodelled (same
DR-0005 finding). The diff against the `vddbus` stage's own extraction is
exactly that and nothing else: the `vss` net gains the three labels
`vss_x1|vss_x2|vss_x3` and stays at 122 devices; every other net's
`device_count` is byte-identical.

**The rings need no promotion stub.** Each `ro_ring5` already carries its own
full-width met2 `vss` rail at block-local `y = -3.0`
(`layout/ro_ring5/README.md`'s fourth stage), and — because all four rings
sit on one row at `y = 0` — those four rails are **collinear** in the
composed array. Three met2 legs in the inter-ring gaps chain them into one
rail, tapping each rail's own end pad (`(origin_x + 0.5, -3.0)` and
`(origin_x + 34.325, -3.0)`, the `g_vss_m1`/`s4_vss_m1` via columns):

| Leg | From → to | Length |
|---|---|---|
| 1 | `ring1` east rail end → `ring2` west | 21.475 µm |
| 2 | `ring2` east → `ring3` west | 21.475 µm |
| 3 | `ring3` east → `ring4` west | 21.475 µm |
| 4 | buffer `vss` met1 bus `(57.99, -3.425)` → `ring2` west rail end | 0.425 µm |
| 5 | `ring4` east rail end → `xa3`'s met1 stub tip | 171.64 µm |
| 6 | `xa3` → `xa2` | 30.17 µm |
| 7 | `xa2` → `xa1` | 28.97 µm |

Leg 4 is the join into the four-buffer `vss` bus the PoC's Increment 5 drew:
that bus is met1 at `y = -3.425`, directly *below* `ring2`'s own met2 rail
pad, so one 0.425 µm met2 leg with a single via-drop merges the row-1 strap
into one piece. After it, `klt`'s merged met2 count drops from 10 shapes to
7: the four separate ring `vss` rails become **one** 166.7 µm² polygon
spanning `x` 2.48..214.71, while the four `vddr` rails, the `vdd` bus and
the `t2` bridge stay separate, exactly as intended.

**The XORs do need stubs, and their tips are deliberately not at one `y`.**
`xor2`'s `vss` is li1-only, so each of `xa1`/`xa2`/`xa3` gets a met1
promotion stub south from `pst`'s own `TAP_S` port (block-local
`(3.92, -1.29)`, the south edge of `xor2`'s p-substrate tap ring — the
`vss` counterpart of the `nwt1` `vdd` tap the PoC's Increment 8 measured).
`xa1`/`xa2` reach `y = 9.6`; **`xa3` stops at `y = 10.8`**, because `ro4`'s
own met1 backbone runs at `y = 10.0` across `x ∈ [49.5, 216.4]` — directly
under `xa3`, and not under `xa1`/`xa2`. A uniform tip row would have shorted
`xa3`'s `vss` to `ro4`.

**Two doors into row 2, and only two.** The `vddbus` stage's own met2 lane
occupies `y = 7.5` across `x ∈ [5.765, 212.995]`, and met2 cannot cross
met2, so anything reaching from the ring row (`y ≤ 6.085`) to the XOR row
(`y ≥ 11.085`) has to pass west of `x = 5.765` or east of `x = 212.995`.
West is closed too: `vdd`'s own `buf1`→`xa1` riser occupies `x = 5.765` for
`y ∈ [7.5, 27.885]`. So leg 5 climbs at `x = 214.5` (1.21 µm clear of the
`vdd` bus's own east end) and runs back west at `y = 10.8`, then legs 6/7
step down via `x = 66.0` to the `y = 9.6` lane — `66.0` chosen because it is
the first column east of `vdd`'s `xa2`→`xa3` riser at `x = 63.705`.

### Measured before drawn

`vss-tap-scan.py` (committed, with its `vss-tap-scan.json` output, non-zero
exit if any tap fails) measures all twelve taps against `vddbus.gds` —
the composed array with *every* committed backbone already in it — before
any `vss` metal is drawn. This is the PoC's Increment 6 finding 1 applied
unchanged: `klt gen-compose` models a placed block as an opaque bbox with no
obstacle model of its interior conductors, so a stub starting at an interior
tap can run straight through another net's metal and short to it
**silently** — `unrouted_nets: []`, `klt drc` clean, wrong only in
`klt extract`'s net list. All twelve report clear, and all six routing legs
then composed first-try with no discarded probes.

## The LVS reference

`design/ro_array_core.spice` defines **one** `.subckt ro_ring5` and calls it
four times with four different `wstv=` overrides, while `layout/` holds four
physically distinct ring cells for those sizings. `compose-cell.py`'s
`lvs.dependencies` mechanism rewrites each dependency once with one shared
`params` dict and genuinely cannot express that; the PoC worked around it
with a directory-local `array-reference.py`. That gap is closed generically
in `compose-cell.py` itself (`lvs.dependency_variants`, PR #70), and
`cell.json`'s `lvs` block below is the first — and so far only — real use of
it:

```json
"dependencies": ["ro_buf", "xor2"],
"dependency_variants": [{
  "subckt": "ro_ring5", "nested": ["ro_nand2", "ro_stage"],
  "instances": [
    {"rename": "_r1", "top_instance_pattern": "^xr1\\b",
     "params": {"wstv": 0.42, "lstv": 2}}, …
  ]
}]
```

The generated `ro_array_core.ref.spice` is **line-for-line identical** to the
reference `array-reference.py` produced (diffed directly, modulo definition
order and the provenance header), and yields the identical `match` verdict
and counts.

**The match is verified to be discriminating, not vacuous.**
`lvs-negative-controls.py` (promoted here from the PoC directory so it runs
against *this* directory's own generated reference) re-runs the identical
comparison against two deliberately-wrong references, with the layout side
byte-identical in all three runs:

| Control | Perturbation (reference side only) | Result |
|---|---|---|
| `width` | ring 4's starve devices resized `0.48 µm` → `0.42 µm` (ring 1's `wstv`), topology untouched | `mismatch`, 122/132 devices |
| `topology` | `xa1`/`xa2`'s second XOR inputs crossed (`ro2` ↔ `ro3`), every device parameter untouched | `mismatch`, 112/132 devices |

The first matters specifically for this block: `ro_array_core`'s entire
premise is four rings deliberately sized apart (DR-0003 §8), and the four
ring GDS cells differ *only* in that width — if `klt lvs` did not compare
`W`, four identical rings would have matched this reference just as happily.

`lvs.json` reports `mismatch_count: 1` on a `match` verdict: that is the
`topology.flattened` warning `lvs.flatten_reference` always produces. The
resulting match verifies device-for-device and net-for-net correspondence,
**not** that the layout's cell hierarchy mirrors the schematic's.

## What is and is not signed off

**Is:** `ro_array_core` as a physical cell — placement, all inter-cell
signal routing, the `vdd` strap and the `vss` strap — DRC-clean, extracted,
and LVS-matching its own schematic subckt, reproducible from `cell.json` by
`compose-cell.py --check` against `layout/pdk.json`'s `klt_version_pin`.

**Is not:**

- **No array-level parasitic extraction, and no post-layout PVT run.**
  `layout/pex-ring/` + `sim/post-layout-ro-ring5-assembled/` cover a single
  ring. The whole array's extracted parasitics — and therefore DR-0003 §8's
  explicitly unmeasured `wstv` inter-ring decorrelation question, which
  needs real inter-ring coupling to answer — are untouched (#27).
- **No `sampler_core`/`sampler_dff`**, so the block-level layout the
  Chipalooza brief asks for is still only its entropy-source half.
- **The LVS match is against a flattened reference** (see above).

## Files

| File | What it is |
|---|---|
| `cell.json` | the recipe: six stages + the `lvs.dependency_variants` reference spec |
| `<stage>.compose.request.json` / `.response.json` / `.gds` | each non-final stage's own request, response and composed stream |
| `compose.request.json` / `compose.response.json` | the final stage's |
| `ro_array_core.gds` | the composed cell |
| `drc.json`, `extract.json`, `ro_array_core.spice` | sign-off + extracted netlist |
| `lvs.request.json`, `ro_array_core.ref.spice`, `lvs.json` | the LVS run and its generated reference |
| `lvs-negative-controls.py` / `.json` | proof the match is discriminating |
| `vss-tap-scan.py` / `.json` | the pre-draw clearance measurement for all 12 `vss` taps |

No `gen/` directory: every block in this cell is either an already-composed
sibling cell or an earlier stage of this same recipe, so `compose-cell.py`
makes no `klt gen` call here at all.
