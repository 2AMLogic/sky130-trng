# Whole-block netlist re-pin after body port rename (#435)

**Defect.** `make-netlist.py` `canonicalise()` renamed only the `.SUBCKT
trng_whole` header to canonical port names; the device body kept the
extractor's cluster names (`en|en2|g_en`, `vddr|vddr2`, `A|A0|B|bus_wdata[1]`,
...). Header ports and body nodes never joined, so 94 of 123 ports (every
supply except where the cluster name equals the port name, clk, enables,
ring_bit) were unconnected.

**Fix.** The cluster -> canonical map is now applied to every whole-token on
non-comment body lines (after the `$`-scrub and bracket de-index, keys passed
through the same normalisation). It aborts if a canonical name already exists
as a distinct body token (0 collisions measured). Tests:
`test_make_netlist.py::test_body_rename`.

**Port-coverage check.** `canonicalise()` and `--check` now require the set of
ports absent from the device body to equal `UNUSED_BY_DESIGN` exactly. That set
is `bus_wdata[31:3]` (29 ports): `digital/rtl/trng_digital.v` reads only
`bus_wdata[2:0]`, so those inputs reach no cell. The issue text expected all 123
ports in the body; measured, 94 were renamed and 29 have no device by design,
and every other port, including all supplies, clk, enables and ring_bit are now present
(e.g. `vdd` 21567 body tokens, `vss` 20791, `vddr1..4` 22 each, `clk` 40).

**Re-pin.** Plain-text sha256 of `trng_whole.sim.spice.gz`:
`503b576cbcda3dc3a85789df7e0faa76e7fe057a4c8d06c731a4492d722fc915` ->
`965f1e6c29d771d5b8e18a3ea66ccabf93f0a5eb14c3f0c23810f39ae1052c36`.
`trng_whole.sim.ports.json` is byte-identical. `make-netlist.py --check`
(fresh `klt extract`, klt `0.9.1.dev102+gef1ec19c95f6`, ~30 s) prints
`check OK: byte-identical, 123 ports, 25356 devices`.

**Supersession (verdicts unconfirmed).** `20261012-042202-dd84c67`,
`20261029-*`, `20261030-fleet-probe-post-bin-fix`, `20261103-rate-probe-infeasible`
and the `20261105` repin records were measured on the prior netlist (hash
`503b576c...` or earlier) in which supplies, clk and enables were unconnected.
Their infeasible verdicts are **unconfirmed pending re-run** on the fixed
netlist. Re-running them is #307 / #431 Step 2, not this change. Those records
are left unedited (append-only).

**Not performed.** The out-of-band ngspice load of the regenerated netlist
(check for `singular matrix` on a supply/clk/enable node) was not run in this
change; it is left to the first #307 / #431 run.
