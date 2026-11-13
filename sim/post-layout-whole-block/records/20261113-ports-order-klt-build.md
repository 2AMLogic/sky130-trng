# The whole-block netlist's `.SUBCKT` port order is a klt-build artefact (#478)

**Finding.** The committed `trng_whole.sim.spice.gz` and
`trng_whole.sim.ports.json` are **current and self-consistent**. Nothing in
this record regenerates or re-pins either of them. What is recorded here is
*why* `make-netlist.py --check` fails on this fleet host while the committed
evidence is correct, and the two tooling changes that follow from it.

Re-running `make-netlist.py` under a klt build other than the one that
produced the committed netlist reproduces every device and net exactly and
emits the top-level `.SUBCKT` ports **in a different order**. That order is
the whole difference. It is a `klt extract` behaviour change
(klayout-tools#5534, filed by this change), not drift in this repo's GDS,
deck, pin request, script or PDK.

## Measurements

All on 2026-11-13, against `origin/main` @ `34f7d1b`, in the issue-478
worktree. Two local single-unit `klt extract` runs (~40 s each) plus one
under a throwaway `uvx` environment; no SPICE, no batch submission.

**1. Host klt regenerates an identical body with a different header.**

```
$ python3 sim/post-layout-whole-block/make-netlist.py -o /tmp/i478-host/host.spice
{
  "klt_version": "0.9.2.dev964+g02db14ecf46b",
  "gds_sha256": "af2f8dfe2800599e97d769bdedd14924c9fa3f24fc7e1c4f43ccd72ac5572ddd",
  "netlist_sha256": "877cc8b8db3e3cd24488cbd0ffc074b4a171e3de796e6d017d25aca8cf294435",
  "device_count": 25356,
  "port_count": 123
}
```

Committed netlist sha256 is `965f1e6c29d771d5b8e18a3ea66ccabf93f0a5eb14c3f0c23810f39ae1052c36`
(`records/20261105-body-rename-repin.md`), same GDS hash, same 25 356 devices,
same 123 ports.

Comparing the two as **logical cards** (`+` continuations joined into their
parent line): **50 714 cards each; exactly one differs — card 0, the `.SUBCKT
trng_whole` header. The other 50 713 are byte-identical and in the same
order.**

**2. The header difference is a reordering, and its shape is exact.**

Same 123 port names on both sides, different order. Of the 123 promoted pins,
29 come from nets carrying a single label (the extractor's cluster name equals
the port name — these are `bus_wdata[31:3]`, the `UNUSED_BY_DESIGN` set that
reaches no cell) and 94 from nets whose labels KLayout joined
(`A|A0|B|bus_wdata[1]`).

Under the host build those **29 whole-name-match ports are hoisted to the
front of the header, in the declared `--pins` order**; the remaining 94 then
follow in **exactly** their committed relative order (verified as a
subsequence equality, not by eye):

```
committed header[:8]  bus_wdata_1_ bus_wdata_0_ startup_done bus_addr_2_ bus_wdata_2_ bus_addr_0_ bus_addr_3_ out_ready
host      header[:8]  bus_wdata_3_ bus_wdata_4_ bus_wdata_5_ bus_wdata_6_ bus_wdata_7_ bus_wdata_8_ bus_wdata_9_ bus_wdata_10_
declared  --pins[:8]  vdd vss clk rst_n en1 en2 en3 en4

host order == declared --pins order            False
committed order == declared --pins order       False
host order == sorted                           False
host[:29]  == the 29 single-label ports, in declared --pins order   True
host[29:]  == the committed order restricted to the 94 joined-label ports  True
```

So the new order is neither the request order nor sorted order; it is the old
order with one subset lifted to the front. That is `--pins`' documented
ordering rule (klayout-tools#5255, `docs/cli/extract.md`: *"The order given is
also the order of the top `.SUBCKT` header: declared pins come first, in the
given order"*) applied **only** to whole-net-name matches, while `--pins`
*matching* itself is per-component-label (klayout-tools#1687). The producing
build predates that rule.

**3. Under the producing build, `--check` is still OK.**

```
$ uvx --from "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@ef1ec19c95f6" \
      python3 sim/post-layout-whole-block/make-netlist.py --check
check OK: byte-identical, 123 ports, 25356 devices          # exit 0
```

That is the build `records/20261105-body-rename-repin.md` names
(`0.9.1.dev102+gef1ec19c95f6`). **The committed netlist is not stale.**

**4. The committed pair agrees with itself.**

The `.SUBCKT trng_whole` header order in `trng_whole.sim.spice.gz` equals the
`canonical` order in `trng_whole.sim.ports.json` after the bracket de-index
(123 = 123, same order). Pinned from now on by
`test_make_netlist.py::test_committed_header_matches_ports_json`, which needs
no klt, PDK or GDS.

**5. Nothing downstream reads the order.** Every reader of `ports.json` is
order-insensitive: `make-requests.py:192-194` sorts, `make-requests.py:240-241`
builds a dict, `sim/tests/test_whole_block_reduction.py:251-253` builds a set.
The order matters only as a *description of this netlist's header*, which the
decks read from the `.gz` itself. The port map's own comment says so
("order = .subckt trng_whole port order"), which is why the pair must stay
consistent even though no consumer depends on the order directly.

## Why the committed evidence is kept, not re-pinned

* The body is identical — there is no new information in the host build's
  netlist, only a different header order.
* Re-pinning would change `netlist_sha256` and stale every record that cites
  `965f1e6c…`, for no behavioural difference.
* The host klt moves again; the next build would re-open the same gap.

Re-pinning becomes correct only when a run under the *producing* build also
differs — which is exactly what the new `--check` failure message now tells
the reader to test.

## What changed in the tooling (this change)

1. **`make-netlist.py` no longer writes the committed port map as a side
   effect.** `PORTS_JSON` was hardcoded and passed unconditionally, so *any*
   run without `--check` — including one whose `-o` sent the netlist
   elsewhere — rewrote the tracked `trng_whole.sim.ports.json`. On this host
   that silently replaced the committed map with a port order that no longer
   described the committed netlist. The map path now follows `-o`
   (`ports_path_for()`: `OUT.spice` → `OUT.ports.json`), and the default
   output still maps to `trng_whole.sim.ports.json` unchanged. This is how
   the issue was found in the first place (#471 / PR #477), and the negative
   control for the new test reproduced it once more: with the old line
   reinstated, a synthetic 4-port run overwrote the committed 123-port map.
2. **The `--check` failure message names both klt builds** and states that a
   differing build is the expected cause, with the `uvx` command that
   reproduces `check OK`. Verified output on this host:

   ```
   error: re-derived netlist differs from the committed sim/post-layout-whole-block/trng_whole.sim.spice.
     this run used klt:                 0.9.2.dev964+g02db14ecf46b
     committed netlist produced by klt: 0.9.1.dev102+gef1ec19c95f6
   A DIFFERENT klt build is the expected cause, not a stale
   netlist: this is a byte compare, and the top-level .SUBCKT
   port order is not reproducible across klt builds
   (klayout-tools#5534; records/20261113-ports-order-klt-build.md).
   Reproduce the committed bytes with
     uvx --from "klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@ef1ec19c95f6" \
         python3 sim/post-layout-whole-block/make-netlist.py --check
   Only if that ALSO differs is the committed netlist stale;
   then re-run make-netlist.py -o and re-pin the records that
   cite its hash.
   ```
3. **`test_make_netlist.py` now runs on every pull request** (`ci.yml`, `lint`
   job) with two new klt-free tests: the port map follows `-o` and leaves the
   committed file byte-unchanged; the committed header order equals the
   committed `ports.json` order.

`--check` itself is deliberately **not** put on a CI path: it needs klt, the
PDK and the GDS, and both workflows pin klt builds other than the producing
one, so it would be red by construction. The klt-free half of the contract is
what CI can honestly check.

## klt friction filed

**klayout-tools#5534** (filed 2026-11-13): `klt extract`'s `--pins` header
ordering (#5255) hoists only whole-net-name matches, so on a joined-label
layout the `.SUBCKT` port order is neither the declared order nor the
pre-#5255 order, and it changes between builds while the rest of the netlist
stays byte-identical. Asks for either (a) the ordering rule to use #1687's
any-component-label match so all declared pins are hoisted in the declared
order, or (b) the port order to be documented as not a cross-build contract —
alongside the anonymous-net-numbering caveat (klayout-tools#1063), which today
reads as the complete list of non-reproducible parts — ideally with a
`--pin-order` flag so a caller can pin it without pinning the whole klt build.

Until then the workaround is the recorded one: pin the producing klt build and
run `--check` under it.

## Not performed

* No `klt sim`, no ngspice, no batch submission.
* `trng_whole.sim.spice.gz`, `trng_whole.sim.ports.json` and every existing
  record are unedited.
* No klt pin moved (#366, #372); the whole-block campaigns (#307, #431) were
  not re-run.
