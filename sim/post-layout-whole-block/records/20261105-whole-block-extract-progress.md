# Whole-block `klt extract` rerun on Spot, with `--progress` (#395)

Provisional, tool-side evidence only. No entropy claim; no PVT corners apply
(this is a layout-extraction timing measurement, not a circuit result).
Append-only.

## Result

| Item | Value |
|---|---|
| Runner `klt` | 0.9.0 (git `5dbbad05ff42`), KLayout 0.30.12; client `0.9.0.dev1379+g5dbbad05ff42` |
| Runner PDK | open_pdks `c6d73a35f524` (`compatibility: mismatch`, expected `f6eeac7dad08`) |
| Where | AWS batch fleet, `c7i.8xlarge` spot, `ami-04591566329422a44`, job `klt-extract-2c47e8bf8ac0` |
| Command | `klt extract <request> --backend batch --batch-include layout/trng_whole --timeout-s 14400 --format json`; request = `layout/trng_whole/trng_whole.gds`, deck `sky130`, pdk `sky130A`, top `trng_whole`, 123 pins (from `extract.request.json`), `--progress`; no abstract-cells, no parasitics (what `make-netlist.py` `run_extract` runs) |
| Exit / status | 0 / `extracted` |
| Wall time | 34.4 s extraction (44 s job `elapsed_seconds`) |
| Devices / nets / pins | 25,356 / 12,678 / 123 (nfet 12,670, pfet 12,685, diode_pw2nd_05v5 1) |
| Raw netlist | `netlist_sha256` `02656f83...b5423` |

Per-stage (stderr, `*.stderr.log.gz` beside this file):

| Stage | Duration |
|---|---|
| read_layout | 0.5 s |
| device_extraction | 21.8 s |
| diagnostics | 0.0 s |
| netlist_write | 1.1 s |
| netlist_hash | 0.0 s |
| netlist_normalized_hash | 0.6 s |

Polygon count: not reported by `klt extract` (JSON has `ignored_layers`
shape counts only), so none is recorded.

## Reconciling the device count

The committed `layout/trng_whole/verify/extract.json.gz` says 264 devices /
2,511 nets because that request uses `abstract_cells: sky130_fd_sc_hd__*`
(klt 0.6.0). The `make-netlist.py` command does not abstract cells, so a flat
extraction gives 25,356. The "~25k-device" figure in klayout-tools#4594 is
the flat one.

## `make-netlist.py --check`: not `check OK`, and the slow part is not klt

`klt extract` is not the stall. I ran `canonicalise()` from `make-netlist.py`
on the fetched raw netlist (15.8 MB, 131,557 lines; 59,820 lines carry `$`):

1. Unmodified, it was still at 100 % CPU after ~10 min (killed). The `merged`
   collision guard rebuilds `{u for ln in body_lines if "$" in ln for u in
   ln.split()}` once per token that is in `scrubbed`, so it is quadratic in
   the number of `$` tokens. This matches the two earlier timeouts (#389, #386
   `timeout 3600`).
2. With that inner set hoisted out of the comprehension (scratch copy under
   /tmp, repo script not changed), it reaches the guard in under 100 s (I did not time it more finely) and raises
   `$-scrub would collide with existing tokens: ['A0|A1|Qz1', ...]`. The
   guard tests post-scrub body tokens against pre-scrub originals, so every
   scrubbed token is reported as a collision once any net name has `$`.

So `--check` cannot print `check OK` on this klt's output until
`make-netlist.py` is fixed. Out of scope for #395 (the issue says not to change
`make-netlist.py`); follow-up filed separately.
