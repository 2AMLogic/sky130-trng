# sky130-trng

A true random number generator on
[SkyWater sky130](https://github.com/google/skywater-pdk), a 130 nm CMOS
open PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

**Status: just opened.** Nothing is designed yet. Unlike some sibling
canaries, nothing is blocked either: sky130 is fully supported by the
toolchain, so work can start at the spec.

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result under PVT corners, and for a TRNG that extends to entropy
evidence — statistical test batteries on simulated bitstreams, provisional
until silicon. Where the agents hit friction with the open-source tooling —
most often [klayout-tools](https://github.com/2AMLogic/klayout-tools) — that
friction is filed as a public issue against the tool itself, so the fix
benefits everyone using sky130, not just this repo.

## Why this block, on this PDK

This is a port, and that is the whole experimental design. The fleet's
[gf180-trng](https://github.com/2AMLogic/gf180-trng) is a proven design: a
ratified spec, twenty-plus decision records, a working entropy-source
architecture (an XOR-combined free-running ring-oscillator array with
continuous health tests), and hundreds of append-only evidence records. This
repo carries that design to a second CMOS process. If the design is the one
we understand best, then anything that breaks here is the PDK, the deck, or
the tools — not the circuit. **The PDK is the variable, not the design.**

One thing is expected *not* to carry over cleanly, and it is the interesting
part: sky130's device leakage and noise corners differ from gf180mcu's, so
the entropy source's bias points and the health-monitor thresholds must be
re-derived for this process rather than copied. A TRNG's entire claim rests
on the physical noise behavior of its devices, which makes it an unusually
honest probe of how much of a "proven design" is actually portable.

## Target specification (DRAFT — engineering to ratify)

The draft deliberately mirrors gf180-trng's
[ratified spec](https://github.com/2AMLogic/gf180-trng) — same block, second
PDK. Where sky130's devices make a target inappropriate rather than merely
harder, change it and record why.

| Parameter | Target | Stretch |
|---|---|---|
| Entropy source | N-way array of independent free-running ring oscillators, XOR-combined ahead of a single sampler; N re-sized from a jitter budget at the entropy-binding corner | metastability hybrid as a secondary tap |
| Raw rate | > 1 Mbps sustained at the raw tap, binding at the slowest-RO corner | > 4 Mbps |
| Raw min-entropy per bit | H₀ = 0.5 bit/sample as a design *target* at the entropy-binding corner — a sizing input, not a claim, until measured | — |
| Quality | designed-for-SP 800-90B (raw access + RCT/APT + entropy-source model); validation deferred to measured silicon | AIS-31 PTG.2 structure |
| Conditioning | non-vetted CRC-32 LFSR compression, K = 8 (256 raw bits in : one 32-bit word out) | vetted conditioner if the area budget allows |
| Health tests | continuous RCT + APT on the raw stream; cutoffs re-derived from sky130 noise/leakage corners, not copied from gf180 | — |
| Power | < 500 µW active; idle target set after a sky130 leakage survey | — |
| Area | < 0.05 mm² | — |
| Operating envelope | −40 … +125 °C; supply per sky130 device flavor (1.8 V core, 3.3 V I/O devices available) — confirm before ratification | — |
| Interface | streaming, mode-selectable raw / conditioned; raw access always available and never gated | — |

**Scope**: entropy source only — no DRBG, no seeding semantics. An
integrator that needs a DRBG supplies its own and treats this block as the
seed source.

Maturity ladder: spec ratified → schematic simulated across PVT → layout
DRC/LVS-clean → post-layout re-verification → shuttle seat → measured
silicon. **Current position: pre-spec.**

## Repo layout

```
spec/          ratified spec + decision records
design/        schematics / netlists (xschem)
sim/           testbenches + PVT corner results (ngspice)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## Chipalooza

[`docs/chipalooza/challenge-4-proposal.md`](docs/chipalooza/challenge-4-proposal.md)
tracks this block's status against Open Circuit Design's Chipalooza
Challenge #4 (Sky130) brief — I/O mapped to the slot budget, every spec row
re-derived from `sim/` and marked met/unmet, and the design gaps (digital
section, layout, DRC/LVS) still open before it is submission-ready.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
