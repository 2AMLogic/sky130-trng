---
dr: DR-0015-open-pdks-repin-to-ciel
title: Re-pin open_pdks from c6d73a3 (volare) to f6eeac7 (ciel 2.6.1)
status: Proposed
date: 2026-10-15
deciders: unratified -- Proposed by the Builder on #314; ratification is an operator action
supersedes: "n/a -- changes the forward-looking PDK pin only; no spec threshold, interface, RTL or recorded result is changed."
superseded_by: n/a
related: "#314 (this record), #315 (re-qualification of cited records), DR-0001 (operating envelope), design/pdk.json, sim/pdk.json, layout/pdk.json, REPRODUCE.md"
---

# DR-0015: re-pin open_pdks to f6eeac7 via ciel

## Status

- 2026-10-15: **Proposed.** Not accepted by anyone; ratification is an
  operator action.
- Pin, provisioning and PDK-search change only. No simulation was re-run and
  no record was edited.

## Context

A fleet-wide decision (2026-10-15) moves the sky130/gf180mcu open_pdks
revision from `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (installed with
volare, whose release feed stopped in Aug 2025; ciel has no release for it) to
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (ciel 2.6.1). Two revisions side by
side already mis-attributed records in 2AMLogic/gf180-comparator#288, where a
`~/.ciel` tree shadowed `~/.volare` in the PDK search.

## Decision proposed

1. Every forward-looking pin (`design/pdk.json`, `sim/pdk.json`,
   `layout/pdk.json`, `digital/flow/place-and-route/tool-pins.json`,
   `REPRODUCE.md`, `design/netlist.py` install hint, workflow comments and
   install lines) names `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`; install is
   `pip install ciel==2.6.1` then
   `ciel enable --pdk-family sky130 -l sky130_fd_pr <commit>`; the PDK root is
   `~/.ciel`.
2. `design/_pdk_search.py` lists `~/.ciel` before `~/.volare` and gains
   `pin_mismatch()`. `design/netlist.py` `find_pdk()` warns on stderr when the
   resolved tree's `SOURCES` revision differs from the pin;
   `sim/bin/corner-run.py` keeps its existing refusal unless
   `--allow-pdk-mismatch`. `~/.volare` stays a search root (so an old tree is
   diagnosable) but can no longer be used silently.

## Existing records

Records, generated evidence and measured-at notes produced under `c6d73a3`
(`layout/**/compose.response.json`, `layout/*/gen/*.gen.json`,
`layout/trng_whole/report.json`, `sim/**/records`, per-directory READMEs) are
true statements about that revision and are **not** edited. Likewise
`layout/trng_whole/verify/verify.json` is generated from `layout/pdk.json` by
`layout/bin/verify-whole.py`; it keeps reading `c6d73a3` until the whole-chip
re-verification in #315 regenerates it. Re-qualification under `f6eeac7`,
supersession marking and any past-tolerance movement are tracked in #315.

Known consequence: the scheduled `pdk-nightly.yml` `verify-whole.py check` job
compares the committed `verify.json` (whose tool pins embed
`open_pdks_commit_expected` from `layout/pdk.json`) with a fresh run, so it
may report drift on that key until #315 regenerates `verify.json`. It is a
nightly job, not a PR check; no PR gate depends on it.
