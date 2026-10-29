# DRC coverage audit controls (issue #281)

Evidence, not sign-off. This audit cross-checks klt's own curated sky130 deck coverage report against the composed stream. It is not a foundry DRC runset, and it adds no antenna, density, seal-ring, latch-up or foundry-only rule. No ratified spec value is read or changed.

Synthetic fixtures (top cell `audit_ctl`, boxes and texts only) are audited with the real pinned deck (`sha256:ba0f97887e3d231aec8b54f1f52f2941ded0228f0234b6759712bcaca0e942e6`) and its layer table. Coverage lists are stubbed per control, and so are deck rules where stated. Shape counts: `klt layers --flattened --include-text` on each fixture GDS written with klayout.db.

| control | intent | expected | observed | passed |
|---|---|---|---|---|
| `1-absent-layer-vacuous` | single-layer rule whose layer has no shapes -> vacuous-confirmed | `dnwell.angle.1` vacuous-confirmed | `dnwell.angle.1` vacuous-confirmed | yes |
| `2-present-layer-residual` | single-layer rule whose layer HAS shapes but klt lists it inapplicable -> residual | `dnwell.angle.1` residual | `dnwell.angle.1` residual | yes |
| `2b-text-only-layer-is-not-geometry` | a layer carrying only text objects has geometry 0: rule vacuous, unruled layer text-or-marker-only | `dnwell.angle.1` vacuous-confirmed, `68/5` text-or-marker-only | `dnwell.angle.1` vacuous-confirmed, `68/5` text-or-marker-only | yes |
| `3a-rule-not-in-pinned-deck` | rule id absent from the pinned deck -> unresolved | `nosuch.width.1` unresolved | `nosuch.width.1` unresolved | yes |
| `3b-unmappable-layer` | rule layer the deck layer table cannot resolve -> unresolved even though nothing is drawn | `ctl.width.unmapped` unresolved | `ctl.width.unmapped` unresolved | yes |
| `3c-unsupported-check-kind` | check kind the audit does not understand -> unresolved even though its layer is empty | `ctl.density.dnwell` unresolved | `ctl.density.dnwell` unresolved | yes |
| `4a-two-layer-one-absent` | two-layer enclosing rule, via3 present and capm absent -> vacuous-confirmed | `capm.enclosing.via3.1` vacuous-confirmed, `met3.enclosing.capm.1` vacuous-confirmed | `capm.enclosing.via3.1` vacuous-confirmed, `met3.enclosing.capm.1` vacuous-confirmed | yes |
| `4b-two-layer-both-present` | two-layer enclosing rule, via3 and capm both present but klt lists it inapplicable -> residual | `capm.enclosing.via3.1` residual | `capm.enclosing.via3.1` residual | yes |
| `unruled-present` | an unruled layer with drawn geometry -> present-unruled | `236/0` present-unruled | `236/0` present-unruled | yes |
| `5-drift` | the drift check must fail on a stream edit, a mapping change, and a deck-hash change, and pass unchanged | drift caught for every change; none when unchanged | one polygon added on 236/0 (an unruled layer) in the stream: caught; layer map: capm.drawing remapped 89/44 -> 97/44: caught; klt deck rules reports a different deck content_hash: caught; deck layer table comes from a deck module with a different hash: caught; unchanged: reproduces | yes |

All passed: **yes**.
