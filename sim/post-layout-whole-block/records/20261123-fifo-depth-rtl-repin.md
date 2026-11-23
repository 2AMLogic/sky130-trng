# Whole-block RTL pin and signoff disposition after the two-word FIFOs (#701)

**Change.** #701 set `FIFO_DEPTH = 2` (`digital/model/params.py`) and shrank both
`trng_digital.v` memories to two entries. Place-and-route and the SDF-timed run were
**not** repeated (out of scope for #701; tracked as #702).

**Whole-block composition re-pin (`layout/trng_whole/report.json`).**
`compose-whole.py` reads `digital/rtl/trng_digital.v` only for its *port list*
(`parse_rtl_ports`). The #701 RTL diff touches no `module`/`input`/`output` line, so a
regeneration would change only the recorded RTL byte hash. That pin moved
`sha256:219738aa...` -> the current RTL hash, and `layout/trng_whole/verify/verify.json`'s
pin of `report.json` moved with it. Not regenerated: python `klayout` and the compose `klt`
run were unavailable on this host, so `compose-whole.py --check` was **not** run. The
claim rests on the port-list argument above. `layout/test_compose_whole.py` and
`layout/test_verify_whole.py` pass. The composed GDS still contains the **pre-#701**
`trng_digital` macro (`trng_digital.routed.v`, `.gds`, `.def` unchanged), so this re-pin
does **not** assert the layout was built from the new RTL.

**Signoff disposition (not a re-pin).** These cannot be honestly re-pinned and are
retracted instead:
- `7.digital`: the #227 SDF record measured the pre-#701 routed netlist against the
  pre-#701 oracle. Citation removed from `signoff/block-manifest.json`; the record under
  `sim/digital-sdf-timed-verification/` is untouched (append-only).
- `1.digital` / `2.digital`: `signoff/attest.py --write` now reports `fail`
  ("P&R record input_hashes.rtl != current RTL sha256 (P&R stale vs RTL)"; tool-pins
  `input_netlist_klt_content_hash` != RTL). Pins and `signoff/t1-report.json` regenerated on
  klt 0.8.0 (the CI pin). T1 met count 15 -> 12; all three rows return to `met` only when
  place-and-route and the SDF-timed run are repeated on the two-word design (#702).
