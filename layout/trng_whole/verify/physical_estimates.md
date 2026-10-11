# Whole-block physical estimates (issue #283)

**Informational geometry estimates only -- NOT foundry sign-off. The pinned curated sky130 deck ships no density and no antenna rules, so no foundry window, threshold, runset or pass/fail stands behind any number here. Simulation- and extraction-derived estimates are provisional until silicon.**

## Definitions (part of the artifact's contract)

### density

- **quantity**: per-window drawn-area fraction of a layer: unioned geometry area inside the window / clipped window area inside the boundary
- **counted_layers**: poly, li1 and met1..met5 DRAWING layer/datatypes, resolved through the pinned deck layer table (inputs.layer_map); pin, label and marker datatypes are not counted
- **geometry**: unioned, hierarchy- and transform-flattened shapes of the layer under the top cell: overlaps and repeated instances are counted once
- **boundary**: the top cell's bounding box (density.boundary)
- **window_um**: 100.0
- **stride_um**: 100.0
- **window_provenance**: ARBITRARY choice: the pinned curated deck has no density rule and no window dimensions (see drc_coverage_audit.json), so nothing foundry-defined is implied. Tiles run row-major from the boundary's lower-left corner and are clipped at the boundary
- **denominator**: the window's own area inside the boundary, so a partial window at the boundary edge is judged against the area it actually has; zero-area windows are skipped and counted, never divided by
- **grid_validation**: the computation refuses window_um <= 0, stride_um <= 0 and stride_um > window_um

### antenna

- **quantity**: naive cumulative antenna ratio per electrical net and level: (sum of li1..level conductor area attributed to the net) / (summed MOS gate W*L on that net)
- **levels**: ['li1', 'met1', 'met2', 'met3', 'met4', 'met5']
- **ratio_convention**: cumulative from li1 upward is the primary, emitted ratio; the per-level areas themselves are committed too, so any other convention is re-derivable from the same artifact
- **conductor_source**: a flat li1/met1..met5 + mcon/via connectivity extraction of the committed GDS (compose-whole.py flat_extract: metal-level connectivity only, no device recognition). A conductor component is attributed to a gate net only when every label it carries is in that gate net's label set and in no other gate net's; everything else is excluded and counted
- **gate_source**: the committed klt extraction extract.json.gz: each analog MOSFET's gate net (named by its own label set) and its params w_um * l_um
- **gate_area**: W*L summed per gate net, um2; only the analog (non-abstracted) devices' gates are known
- **digital_exclusion**: every gate inside the abstracted digital standard cells is EXCLUDED -- cell-internal gate geometry does not exist in the committed extraction. The exclusion is reported against a defined denominator (placed device-bearing instances: analog devices + abstracted instances), never an invented area fraction; see coverage.gate_area.digital_exclusion
- **zero_gate_nets**: a conductor component whose only candidate net has zero known gate area is EXCLUDED from the ratios and COUNTED; a zero-gate net never produces an infinite ratio or a pass
- **unmatched_gate_nets**: a gate net with no attributable conductor component is listed and excluded (its metal cannot be identified by label alone)
- **not_modelled**: ['process sequencing (a real antenna rule applies per process step, not to the finished stack)', 'diode relief', 'side-wall / perimeter conductor area', 'foundry threshold values']
- **verdict**: none: ratios are estimates for human review; there is no pass/fail against any foundry antenna rule anywhere in this artifact

## Density

Boundary: top-cell bbox (-47.2, 0.0) .. (330.96, 333.5) um, 126116.36 um2. Grid: 100.0 um x 100.0 um tiles (arbitrary choice -- see definitions), 16 counted windows, 0 skipped as zero-area. Denominator is the clipped window area inside the boundary. No threshold is applied: a density number here is not a density-rule verdict.

| layer | drawn um2 | whole-block density | windows | density min | max | mean |
|---|---|---|---|---|---|---|
| `poly` (66/20) | 5809.494 | 0.046065 | 16 | 0.000000 | 0.141733 | 0.036694 |
| `li1` (67/20) | 14340.501 | 0.113708 | 16 | 0.000000 | 0.312409 | 0.092291 |
| `met1` (68/20) | 16363.426 | 0.129749 | 16 | 0.000000 | 0.338457 | 0.105247 |
| `met2` (69/20) | 6155.854 | 0.048811 | 16 | 0.000000 | 0.150617 | 0.041315 |
| `met3` (70/20) | 1785.601 | 0.014158 | 16 | 0.000000 | 0.049201 | 0.011165 |
| `met4` (71/20) | 6853.450 | 0.054342 | 16 | 0.000000 | 0.123999 | 0.042869 |
| `met5` (72/20) | 9457.744 | 0.074992 | 16 | 0.012563 | 0.126400 | 0.072547 |

## Naive antenna ratios

Cumulative conductor area / gate W*L per net and level. Estimates only: process sequencing, diode relief, side-wall area and foundry thresholds are not modelled, and there is no pass/fail here.

| level | nets rated | worst ratio | worst net |
|---|---|---|---|
| `li1` | 33 | 165.30 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met1` | 33 | 448.58 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met2` | 33 | 470.49 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met3` | 33 | 481.98 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met4` | 33 | 669.57 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met5` | 33 | 866.08 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |

Worst nets by cumulative met5 ratio (of 33 rated):

| net | gate um2 | gates | components | cumulative ratio per level |
|---|---|---|---|---|
| `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` | 18.000 | 20 | 1 | li1=165.3 met1=448.6 met2=470.5 met3=482.0 met4=669.6 met5=866.1 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit1|y` | 0.252 | 2 | 1 | li1=9.1 met1=10.5 met2=17.3 met3=18.3 met4=23.8 met5=445.2 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit2|y` | 0.252 | 2 | 1 | li1=9.1 met1=10.5 met2=17.3 met3=18.3 met4=23.8 met5=445.2 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit3|y` | 0.252 | 2 | 1 | li1=9.1 met1=10.5 met2=17.3 met3=18.3 met4=23.8 met5=445.2 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit4|y` | 0.252 | 2 | 1 | li1=9.1 met1=10.5 met2=17.3 met3=18.3 met4=23.8 met5=445.2 |
| `en|en1|g_en` | 0.252 | 2 | 1 | li1=2.5 met1=3.2 met2=3.9 met3=4.9 met4=10.4 met5=286.4 |
| `en|en2|g_en` | 0.252 | 2 | 1 | li1=2.5 met1=3.2 met2=3.9 met3=4.9 met4=10.4 met5=286.4 |
| `en|en3|g_en` | 0.252 | 2 | 1 | li1=2.5 met1=3.2 met2=3.9 met3=4.9 met4=10.4 met5=286.4 |

## Coverage and exclusions

- Gate W*L known for 264 analog devices over 37 gate net(s), 61.452 um2 total; 0 device(s) lacked params and are counted, not dropped.
- Digital exclusion: all gates inside 8605 abstracted standard-cell instances (69 cell types) are excluded -- 0.029767 of 8869 placed device-bearing instances have known gate area. Gate-net side: 33 rated, 4 with no attributable conductor geometry (listed in the JSON).
- Conductor side: 8155 flat components, 2489 labeled, 69 attributed to a gate net, 0 ambiguous (label set shared between gate nets), 2420 labeled but matching no gate net, 5666 unlabeled. Attributed-area fraction per level: li1=0.223118, met1=0.335954, met2=0.100211, met3=0.117381, met4=0.495146, met5=0.474992.

## Regeneration

```
python3 layout/bin/verify-whole.py estimates   # regenerate both files
python3 layout/bin/verify-whole.py check       # drift gate (fails on any difference)
```

Both files are generated from one document; neither is hand-edited.
