# Whole-block netlist re-pin after `$`-scrub guard fix (#419)

- `make-netlist.py` `canonicalise()` collision guard: pre-scrub token set was
  rebuilt per token (quadratic; >10 min on the 15.8 MB raw netlist) and compared
  scrubbed names against pre-scrub originals (false positive on every `$` net).
  Now one linear pass; collision = scrubbed name equal to an existing
  `$`-free token on a line the scrub applies to. Unit test:
  `sim/post-layout-whole-block/test_make_netlist.py`.
- `make-netlist.py --check` now completes in ~25 s wall (was timing out).
- It reported a diff: the committed `trng_whole.sim.spice.gz` predates the
  `$`->`z` scrub (it still contained `$` net names) and was produced by an
  older klt. Re-derived with klt 0.9.1.dev1+g08669432fef6: same 25355 devices,
  same 123 ports (ports JSON byte-identical), anonymous `$N` -> `zN` naming.
- Re-pinned: old netlist sha256 (decompressed)
  `bd694f2fd52f285bf55e74725c489fd855c73321352a0db26c09d5b7216fa684`
  -> new `3e7a718b7c00e2ea4655b6b56fc813cbcfe3490a0e0959e368c88fe8f469d90f`.
  `--check` then prints `check OK: byte-identical, 123 ports, 25355 devices`.
- Records `20261029-narrow-nfet-model-bin.md` and `20261029-bin-coverage-scan.md`
  cite the old hash and are left unedited (append-only). Whether results
  derived from the old netlist need re-running is out of scope here.
