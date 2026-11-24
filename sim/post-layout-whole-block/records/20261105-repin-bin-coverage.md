# Whole-block netlist: diode card fix, all-card scan, claims after the #420 re-pin (#422)

Evidence is connectivity / model-definition only (pure-Python scan plus one
one-device ngspice 42 parse). No simulation result is claimed. Pinned PDK:
`f6eeac7d…/sky130A` (ciel), klt `0.9.0.dev1379+g5dbbad05ff42`.

## Hashes (decompressed netlist sha256)

| netlist | sha256 |
|---|---|
| before #420 (cited by the 20261029 records) | `bd694f2fd52f285bf55e74725c489fd855c73321352a0db26c09d5b7216fa684` |
| main after #420 | `3e7a718b7c00e2ea4655b6b56fc813cbcfe3490a0e0959e368c88fe8f469d90f` |
| this change | `503b576cbcda3dc3a85789df7e0faa76e7fe057a4c8d06c731a4492d722fc915` |

`diff` main-after-#420 vs this change is exactly 2 lines (the diode card below);
GDS sha256 unchanged `af2f8dfe…2ddd`, ports JSON unchanged (123 ports).
`make-netlist.py --check`: `check OK: byte-identical, 123 ports, 25356 devices`.

## The #420 "naming-only" claim: did not hold

#420 also introduced one card (the only non-`X` card):
`Dz25356 <VGND cluster> <A|DIODE cluster> diode_pw2nd_05v5 A=0.4347P P=2.64U`.
ngspice has no model of that name (`could not find a valid modelname`, the #386
class). The PDK defines it as a subckt `sky130_fd_pr__diode_pw2nd_05v5 a c
mult=1 area=1 perim=1` (`continuous/models_diodes.spice`, pulled in by
`sky130.lib.spice tt`). `make-netlist.py` transform 5 now emits
`Xz25356 … sky130_fd_pr__diode_pw2nd_05v5 area=0.4347P perim=2.64U`. A
one-device ngspice 42 `.op` with that exact card parses and runs (only an
`IKR too small` model warning). Still an extractor gap worth a generic
klayout-tools issue: a `--pdk` extract emits a bare-model `D` card for a
PDK diode that is a subckt.

## Full-card scan (`check-bin-coverage.py`, now all card types)

| input | FET bin coverage | undefined-model cards | exit |
|---|---|---|---|
| main after #420 (control, must fail) | 0 uncovered of 25355 | 1 (`D`, `diode_pw2nd_05v5`) | 1 |
| this change | 0 uncovered of 25355 | 0 | 0 |

(The control is the pre-fix netlist; the unit test also asserts a failing `D`
and `R` card.)

## Do the two 20261029 claims still hold?

- `20261029-narrow-nfet-model-bin.md` (narrow nFETs mapped to
  `special_nfet_01v8`): yes. 1760 `special_nfet` cards, all covered; the nFET/pFET
  card lines are unchanged vs main-after-#420 (diff above).
- `20261029-bin-coverage-scan.md` ("every device card has a bin"): held for
  FET bins only; it did not establish that every device card's model exists,
  and the post-#420 netlist had one that did not. Now established by the
  scan above for the new hash.

## Fleet re-run decision

Not re-run: the netlist hash differs from the one in the 20261030 / 20261103
probes (`69d598b3…` in `plan.json`), so those results are stale w.r.t. this pin
and are not cited as evidence for it. No `klt sim` was submitted from this
change (cost ~47 min of fleet time, and the question here is answered by the
local scan); a fleet probe on the new hash is left to whichever issue next
needs a whole-block result. No local ngspice grid was run.
