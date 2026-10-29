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

Boundary: top-cell bbox (-47.2, 0.0) .. (331.035, 333.5) um, 126141.3725 um2. Grid: 100.0 um x 100.0 um tiles (arbitrary choice -- see definitions), 16 counted windows, 0 skipped as zero-area. Denominator is the clipped window area inside the boundary. No threshold is applied: a density number here is not a density-rule verdict.

| layer | drawn um2 | whole-block density | windows | density min | max | mean |
|---|---|---|---|---|---|---|
| `poly` (66/20) | 5843.574 | 0.046326 | 16 | 0.000000 | 0.141733 | 0.036954 |
| `li1` (67/20) | 14339.544 | 0.113678 | 16 | 0.000000 | 0.312409 | 0.092267 |
| `met1` (68/20) | 16363.859 | 0.129726 | 16 | 0.000000 | 0.338457 | 0.105233 |
| `met2` (69/20) | 6157.425 | 0.048814 | 16 | 0.000000 | 0.150617 | 0.041321 |
| `met3` (70/20) | 1785.601 | 0.014156 | 16 | 0.000000 | 0.049201 | 0.011165 |
| `met4` (71/20) | 6853.450 | 0.054332 | 16 | 0.000000 | 0.123999 | 0.042869 |
| `met5` (72/20) | 9456.304 | 0.074966 | 16 | 0.012551 | 0.126400 | 0.072529 |

## Naive antenna ratios

Cumulative conductor area / gate W*L per net and level. Estimates only: process sequencing, diode relief, side-wall area and foundry thresholds are not modelled, and there is no pass/fail here.

| level | nets rated | worst ratio | worst net |
|---|---|---|---|
| `li1` | 33 | 165.33 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met1` | 33 | 448.60 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met2` | 33 | 470.52 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met3` | 33 | 482.00 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met4` | 33 | 669.60 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |
| `met5` | 33 | 866.10 | `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` |

Worst nets by cumulative met5 ratio (of 33 rated):

| net | gate um2 | gates | components | cumulative ratio per level |
|---|---|---|---|---|
| `VGND|g_vss_m1|inv_clk_vss|inv_mc_vss|..s_x1|vss_x2|vss_x3` | 18.000 | 20 | 1 | li1=165.3 met1=448.6 met2=470.5 met3=482.0 met4=669.6 met5=866.1 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit1|y` | 0.252 | 2 | 1 | li1=9.0 met1=10.4 met2=17.8 met3=18.7 met4=24.3 met5=445.6 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit2|y` | 0.252 | 2 | 1 | li1=9.0 met1=10.4 met2=17.8 met3=18.7 met4=24.3 met5=445.6 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit3|y` | 0.252 | 2 | 1 | li1=9.0 met1=10.4 met2=17.8 met3=18.7 met4=24.3 met5=445.6 |
| `a|inv_q_y|inv_q_y_via|inv_q_y_via2|na..via2|q|ring_bit4|y` | 0.252 | 2 | 1 | li1=9.0 met1=10.4 met2=17.8 met3=18.7 met4=24.3 met5=445.6 |
| `en|en1|g_en` | 0.252 | 2 | 1 | li1=3.0 met1=3.7 met2=4.4 met3=5.3 met4=10.8 met5=285.4 |
| `en|en2|g_en` | 0.252 | 2 | 1 | li1=3.0 met1=3.7 met2=4.4 met3=5.3 met4=10.8 met5=285.4 |
| `en|en3|g_en` | 0.252 | 2 | 1 | li1=3.0 met1=3.7 met2=4.4 met3=5.3 met4=10.8 met5=285.4 |

## Coverage and exclusions

- Gate W*L known for 264 analog devices over 37 gate net(s), 61.452 um2 total; 0 device(s) lacked params and are counted, not dropped.
- Digital exclusion: all gates inside 8605 abstracted standard-cell instances (69 cell types) are excluded -- 0.029767 of 8869 placed device-bearing instances have known gate area. Gate-net side: 33 rated, 0 listed with zero known gate area (never rated, never infinite), 4 with no attributable conductor geometry (listed in the JSON).
- Conductor side: 8155 flat components, 2489 labeled, 69 attributed to a gate net, 0 ambiguous (label set shared between gate nets), 2420 labeled but matching no gate net, 5666 unlabeled. Attributed-area fraction per level: li1=0.222939, met1=0.335988, met2=0.100432, met3=0.117381, met4=0.495146, met5=0.474912.

## Regeneration

```
python3 layout/bin/verify-whole.py estimates   # regenerate both files
python3 layout/bin/verify-whole.py check       # drift gate (fails on any difference)
```

Both files are generated from one document; neither is hand-edited.
