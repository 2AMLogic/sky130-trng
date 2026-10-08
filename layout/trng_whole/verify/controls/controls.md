# Fault controls (issue #173)

Whole-block project verification on klt's curated sky130 decks and the open_pdks install pinned in layout/pdk.json. NOT foundry sign-off: no foundry DRC/LVS/antenna/density runset, no parasitic extraction, no electrical or entropy characterisation. Provisional until silicon.

Each control is a disposable copy of the composed GDS (or of the LVS reference, where stated) run through the SAME extract -> pin canonicalisation -> mixed-level LVS pipeline as the baseline. The defect is proven present by an independent metal-level probe (klayout.db) *before* verification; the golden `trng_whole.gds` and `verify/lvs.ref.spice` hashes are re-checked after each control, and the unmodified baseline is re-run at the end.

| control | kind | reached LVS | LVS | errors | error categories | evidence naming the net(s) | detected |
|---|---|---|---|---|---|---|---|
| `swap-analog-ring-bits` | swap_labels | yes | mismatch | 14 | {'device.unmatched': 10, 'net.unmatched': 4} | 10 errors name ['ring_bit1', 'ring_bit2'] | yes |
| `swap-digital-bus-bits` | swap_labels | yes | mismatch | 7 | {'hints.rejected': 2, 'topology': 5} | 7 errors name ['bus_wdata[0]', 'bus_wdata[1]'] | yes |
| `swap-interface-reference` | swap_reference | yes | mismatch | 6 | {'topology': 6} | 6 errors name ['raw_bit', 'raw_valid'] | yes |
| `disconnect-raw-bit` | disconnect | yes | mismatch | 5 | {'device.unmatched': 4, 'net.unmatched': 1} | 5 errors name ['raw_bit'] | yes |
| `short-ring-supply-to-logic-supply` | supply_short | yes | mismatch | 37 | {'device.unmatched': 19, 'hints.rejected': 1, 'net.merged': 9, 'net.split': 8} | 20 errors name ['vddr4', 'vdd'] | yes |

Baseline re-run after all controls: LVS `match`, 0 errors, stable report fields identical to the first baseline.

Per-control defect proofs, LVS categories and mismatch examples are in `controls.json`.
