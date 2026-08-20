# sky130-trng — agent instructions

Open-source canary block: a true random number generator on SkyWater sky130,
a 130 nm CMOS open PDK, designed and verified by AI agents. Apache-2.0.

- **PDK**: SkyWater sky130 (open PDK, google/skywater-pdk, distributed via
  open_pdks). Open-source flow: xschem + ngspice for design/sim,
  klayout-tools (`klt`) for layout work. sky130 is fully supported by the
  toolchain — nothing here is blocked on the resolver.
- **The PDK is the variable, not the design.** This block is a port of the
  fleet's proven [`gf180-trng`](https://github.com/2AMLogic/gf180-trng) *on
  purpose*. Start from that repo's spec, decision records, and
  entropy-source architecture rather than from a blank page. Anything that
  breaks should be assumed to be the PDK, the deck, or the tools before it
  is assumed to be the circuit.
- **Re-derive, don't copy, the numbers.** sky130's device leakage and noise
  corners differ from gf180mcu's, so the entropy source's bias points and
  the health-monitor thresholds (which are derived from the min-entropy
  assumption) are expected to need re-derivation for this process, not
  transplanting. That re-derivation is exactly the friction this canary
  exists to surface — record it, don't shortcut it.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue
  at `2AMLogic/klayout-tools` describing the need generically — describe
  the tool gap, not the design. A tool issue that only makes sense to
  someone who has read this repo's spec is a bad tool issue.
- **Verification is the product**: no claim without a testbench. PVT corners
  on every recorded result; `sim/` results are append-only evidence. For a
  TRNG that includes entropy evidence: statistical test suites (e.g. NIST
  SP 800-22-style batteries) run on simulated bitstreams, with the standing
  caveat that simulation-derived entropy claims are provisional until
  measured on silicon.
- Spec changes go through `spec/` with a decision record; agents do not
  relax the ratified spec to make results pass.
