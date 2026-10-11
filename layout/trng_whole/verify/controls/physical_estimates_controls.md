# Whole-block physical estimate controls (issue #283)

Informational geometry estimates only -- NOT foundry sign-off. The pinned curated sky130 deck ships no density and no antenna rules, so no foundry window, threshold, runset or pass/fail stands behind any number here. Simulation- and extraction-derived estimates are provisional until silicon.

Synthetic GDS fixtures written and read with the real pinned klayout (version recorded in the generating environment). These are calculator controls: they pin union, hierarchy, clipping, empty-layer, grid-validation, cumulative-ratio, zero-gate/ambiguous-accounting and drift behaviour with hand-computed expected values.

| control | intent | passed |
|---|---|---|
| `1-density-union` | overlapping met1 rects union to exactly 6 um2 (no double counting); a child cell placed twice counts both placements (poly 4 um2); absent met5 layer is the empty-layer case (zero density, no error) | yes |
| `2-density-window` | one 3x3 window over a 9 um2 denominator: met1 density exactly 6/9; geometry outside the boundary (poly at y=10) never leaks into the windows | yes |
| `3-density-clip` | a window larger than the boundary clips to the boundary (denominator 2.5 um2, one window, none skipped, met1 fills it completely: density 1.0) | yes |
| `4-invalid-grid-w0.0-s1.0` | invalid grid (window=0.0, stride=1.0) is refused, not silently tiled | yes |
| `4-invalid-grid-w1.0-s0.0` | invalid grid (window=1.0, stride=0.0) is refused, not silently tiled | yes |
| `4-invalid-grid-w1.0-s2.0` | invalid grid (window=1.0, stride=2.0) is refused, not silently tiled | yes |
| `5-antenna-known` | two gates on one net: gate area 0.42*0.15 + 0.84*0.15; cumulative li1 ratio 1/ga, met1 ratio (1+2)/ga; a zero-gate net (n2) is excluded and counted; a gate net with no conductor geometry (n3) is excluded and listed | yes |
| `6-antenna-ambiguous` | a component carrying only a label shared by two gate nets (the vddr/vddr3/vddr4 pattern) is ambiguous -- excluded and counted; a component with a unique label still matches; an unlabeled component is counted separately | yes |
| `7-drift` | drift is caught for density, parameter, gate-area and staleness changes; a provenance-only change does not drift; unchanged reproduces | yes |

All passed: **yes**.

