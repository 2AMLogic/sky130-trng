# 20261105 -- analog-chain-only probe (DR-0017 feasibility gate, Step 1): FEASIBLE; the committed whole netlist has disconnected ports (issue #431)

**Claim**: the analog chain alone (rings + sampler, 264 transistors, digital absent) simulates
500 ns at tt / 27 C / 1.8 V in **28.7 s** on the batch fleet, i.e. **0.057 s per simulated ns**.
Extrapolated linearly to the 7.87 us program that is about 450 s, far inside the 3480 s ceiling,
so the analog half of DR-0017 option (b) is **feasible**. The feasibility of the *gate-level
digital co-simulation* is NOT measured here (Step 2 territory). Provisional, simulation-side.

## What was run (one unit, `klt sim`, batch backend, no local run, no retry)

- `make-requests.py <dir> --set analog-probe` (new): the flat extract filtered to devices with
  composed y >= 250 um (the analog macro; the device-y histogram has an empty 240-260 um band,
  digital below it): 264 transistors, 25 091 digital devices and the pw2nd diode dropped.
  Digital pins are left open (the "absent" option of the gate). `tran 20p 500n` (rings from
  5 ns, clock from 320 ns, so the sampler is clocked), 9 measurements, `timeout_s` 3480.
- Job `klt-sim-52ede9c6e92b` (`runs/20261105-analog-probe/`), launched 2026-11-05T20:05:23Z,
  spot `m7i.4xlarge`, job `elapsed_seconds` 35, corner `runtime_s` 28.732, status pass.
  ngspice 46, PDK open_pdks f6eeac7dad08 (two installs found; `~/.ciel` won).
- Supply currents averaged 20-500 ns: vdd -115 uA, vddr1..4 -12..-14 uA each (sign: source
  convention); ring_bit levels at 500 ns are snapshots only (two high, two low).

## Cost driver

No progress lines appear in `ngspice.log`, even on this run that finished (the runner image does
not show them; klayout-tools#4867 is closed but its output is not visible here). Total 28.7 s
bounds DC start-up and the ring timestep together: neither is the cost driver for the analog
chain. By elimination the earlier >3480 s timeouts are not explained by the analog chain; the
digital 25 091 devices and/or the defect below are the candidates. Not distinguished further.

## Finding: the committed netlist body does not connect the ports

`make-netlist.py` transform 1 renames only the `.SUBCKT trng_whole` port **list**; the body still
refers to nets by the extractor's cluster names (`en|en2|g_en`, `g_vddr_m1|...|vddr|vddr2`,
`A|DIODE|a|clk|...`). In the committed `trng_whole.sim.spice.gz`, 94 of the 123 ports (every
supply, clock, enable and bus pin with a clustered name; ring_bit1-4 included) never appear in the
body under their canonical name. As committed, the testbench sources therefore drive nothing, and
a first analog-only attempt (job `klt-sim-db1c29ada861`, same day) failed in 24.5 s with
`singular matrix: check node xw.en|en2|g_en` (floating enable nets). The probe above applies the
cluster -> canonical rename at request assembly (`_cluster_to_port()` from `ports.json`), leaving
the committed body untouched.

Consequence: the 20261030 and 20261103 timeouts and the 20261012 record were measured on a
netlist whose supplies were not connected to the devices, so their "infeasible" verdicts are
confounded. They are append-only and not edited; this record supersedes their rate conclusion
only for the analog chain. Whether the connected whole netlist is feasible is unmeasured. Fix
(re-derive the body rename in `make-netlist.py`, re-pin hashes) is out of scope here and is
filed separately.

## Verdict against the 3480 s ceiling

Analog chain: **feasible** (about 450 s for the full program, linear extrapolation, flagged as
such; the digital activity phase will add sampler switching). Step 2 remains gated on DR-0017
ratification (still Proposed) and on the netlist port fix above; it does not start here.
