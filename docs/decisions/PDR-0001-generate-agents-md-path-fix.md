---
dr: PDR-0001-generate-agents-md-path-fix
title: Fix generate-agents-md.sh's broken relative source path locally, and file the upstream bug separately
status: Proposed
date: 2026-09-14
deciders: unratified — Proposed by the Builder on #75; acceptance is a normal PR-review (human/Champion) action, not the spec two-key mechanism — see "Does the two-key mechanism apply?" below
supersedes: n/a
superseded_by: n/a
related: "#75 (the issue this record resolves the option-selection for); .loom/scripts/generate-agents-md.sh (the broken script); .loom/install-metadata.json (its manifest entry); ratification/ee-key/SKILL.md, ratification/market-key/SKILL.md, and their rubric.md files (read and found inapplicable to this record's subject matter — see below); spec/README.md and spec/decision-records/DR-0001 (the frontmatter/status convention this record reuses)"
---

# PDR-0001: Fix `generate-agents-md.sh`'s broken relative source path locally, and file the upstream bug separately

## Status

- 2026-09-14: **Proposed.** Not accepted by anyone. This record exists
  because issue #75's Champion review reframed a three-option, human-deferred
  issue as a decision a Builder should resolve and justify in a PR, per the
  standing ratification-via-PR policy (2AMLogic/2am#357) — see issue #75's
  2026-09-14 comment. This record is that justification. It does **not**
  implement the recommended fix; implementation is explicitly out of scope
  for the PR this record ships in and is left to a follow-up.

## Context

`.loom/scripts/generate-agents-md.sh` is a vendored/installed Loom-surface
script (installed by the Loom scaffolding, listed in
`.loom/install-metadata.json`) that regenerates `.loom/AGENTS.md` from the
`agents-md:include` marker ranges in `.loom/CLAUDE.md`. It hardcodes its
source path as:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/../.loom/CLAUDE.md"
DEFAULT_OUT="$SCRIPT_DIR/../.loom/AGENTS.md"
```

**Independently re-verified for this record** (not just paraphrasing the
issue), from a clean checkout at `main` (`10549f4`):

```
$ ./.loom/scripts/generate-agents-md.sh --stdout
generate-agents-md: source not found: /Users/rwalters/GitHub/sky130-trng/.loom/scripts/../.loom/CLAUDE.md
EXIT: 1
```

The script's own header comment states its provenance directly and explains
*why* the path is wrong here — it is right for the layout it was written
against, and wrong for how it is vendored into this repo:

> "generate `defaults/.loom/AGENTS.md` from the `agents-md:include` marker
> ranges in `defaults/.loom/CLAUDE.md`."
> — `.loom/scripts/generate-agents-md.sh:1-3`

That is the Loom **source** repo's own layout: `defaults/scripts/` sits next
to `defaults/.loom/CLAUDE.md`, so `$SCRIPT_DIR/../.loom/CLAUDE.md` correctly
resolves to `defaults/.loom/CLAUDE.md` there. Once vendored into a consuming
repo like this one, only the `defaults/` subtree's contents are installed,
flattened one level: `.loom/scripts/` sits next to `.loom/CLAUDE.md`
directly, one directory level shallower than the source repo. The same
relative path that was correct upstream is therefore wrong everywhere it is
installed. This is corroborated independently by `.loom/docs/runtime-adapters.md:389`
and `:1081`, which both still describe the canonical form as
`defaults/scripts/generate-agents-md.sh` extracting from
`defaults/.loom/CLAUDE.md` — i.e., the installed copy's header and its own
supporting docs agree on the source-repo path convention that no longer
matches where the file now lives.

Also re-verified: the script's header additionally claims a
`scripts/check-agents-md-sync.sh` CI gate keeps the checked-in AGENTS.md
from going stale. No such script exists anywhere in this repo:

```
$ find . -iname '*check-agents-md-sync*'
(no output)
```

and nothing in this repo invokes `generate-agents-md.sh` except as a
manifest listing:

```
$ grep -rln "generate-agents-md.sh" --include='*.sh' --include='*.md' --include='*.json' . | grep -v '.loom/worktrees'
.loom/AGENTS.md                    (self-referential comment inside the generated file)
.loom/install-metadata.json        (manifest entry only)
.loom/docs/runtime-adapters.md     (documentation describing the source-repo mechanism)
.loom/scripts/generate-agents-md.sh (the script itself)
```

So the current state is: `.loom/AGENTS.md` is present and (presumably)
correct as generated at install time; only the *local* ability to
regenerate it — if `.loom/CLAUDE.md`'s marked sections ever change — is
broken, with no CI gate anywhere in this repo actually depending on the
regeneration working.

## Options considered

**Option 1 — fix locally.** Change `SRC`/`DEFAULT_OUT` in this repo's copy
of `.loom/scripts/generate-agents-md.sh` from `$SCRIPT_DIR/../.loom/...` to
`$SCRIPT_DIR/../...` (one directory level, matching this repo's actual
`.loom/scripts/` next to `.loom/CLAUDE.md` layout).

- *For*: self-contained, two-line, zero-coordination change; immediately
  satisfies the issue's own stated verification command
  (`./.loom/scripts/generate-agents-md.sh --stdout` prints instead of
  erroring); no risk to anything else, since nothing in this repo currently
  depends on the script running.
- *Against*: this repo does not own `.loom/scripts/generate-agents-md.sh` —
  it is machine-installed/resynced from `rjwalters/loom`'s `defaults/`
  scaffolding (see the recent "chore: resync installed Loom surfaces"
  commit history). A local-only fix is a **hand-edit of a generated
  artifact**: the same class of drift the script's own header explicitly
  says it exists to prevent for `AGENTS.md` itself (single-source, no
  hand-maintained forks). The very next upstream resync that touches this
  file will silently overwrite the fix unless the resync tooling happens to
  preserve local edits (nothing in `.loom/docs/daemon-reference.md` or the
  install metadata inspected for this record suggests it does), so the bug
  would recur with no failure signal — just a quiet regression back to
  "source not found" some number of resyncs later.

**Option 2 — report upstream only.** File the path bug against
`rjwalters/loom` (every repo using the current `defaults/` scaffolding
inherits the same broken relative path once vendored one level shallower),
and leave this repo's copy as-is pending an upstream fix and resync.

- *For*: fixes the bug at its actual root cause, for every repo that
  vendors this scaffolding, not just this one — proportionate to a bug that
  is structural to the installer template, not specific to this repo's
  checkout. This is also this repo's own stated norm for exactly this class
  of problem: `CLAUDE.md`'s friction protocol says tool/scaffolding gaps get
  filed against the tool, "describing the tool gap, not the design" (stated
  there for `klayout-tools`, but the same posture applies to Loom's own
  installer surfaces, which this repo also treats as vendored tooling rather
  than owned code).
- *Against*: filing upstream and waiting is out of this Builder's control —
  latency to an actual fix landing in `rjwalters/loom` and then reaching
  this repo via the next resync is unbounded from here, and in the meantime
  the script stays broken with zero user-facing benefit over Option 3. Pure
  "upstream only, no local action" leaves a known, trivially-fixable local
  break sitting live for an indeterminate window for no compensating
  benefit — the fix is cheap enough that "wait for upstream" is not
  buying anything an immediate local fix wouldn't also buy, while also
  filing the report.

**Option 3 — do nothing locally.** Leave the script broken; nothing in this
repo currently depends on it working, so there is no functional impact
today, and it will eventually self-heal whenever `rjwalters/loom` fixes the
upstream template and this repo's next scheduled resync pulls it in.

- *For*: zero effort, zero risk of a divergent local fix ever conflicting
  with an eventual upstream fix.
- *Against*: this is the status quo the issue was filed against, and
  "eventually self-heals" has no forcing function behind it — there is no
  tracked upstream issue in this option, so there is nothing to actually
  cause the resync to happen with the fix included; it heals only by
  coincidence, if and when someone else independently notices and fixes the
  same bug upstream. It also leaves a known-wrong header claim
  (`check-agents-md-sync.sh` "fails CI") sitting in the repo indefinitely,
  which is a small but real accuracy cost distinct from the path bug itself.

## Decision

**Recommend Option 1 (fix the local path), paired with also filing the
upstream report described in Option 2** — not as a second competing
option, but because nothing about fixing the local copy precludes also
reporting the root cause, and the two are complementary rather than
mutually exclusive:

- The local fix is what actually satisfies issue #75's own verification
  command in bounded time, at negligible cost and negligible risk (nothing
  in this repo depends on the current broken behavior, so there is no
  regression surface).
- The "will be clobbered by the next resync" objection to Option 1 is real
  but is an argument for *also* filing upstream (so the fix has a chance to
  land in the template and survive future resyncs), not an argument for
  leaving the local copy broken in the meantime. A hand-edit that gets
  overwritten by a later correct upstream fix is a wash, not a harm; a
  hand-edit that gets overwritten by a later resync that *doesn't* fix it
  upstream just puts this repo back where issue #75 found it, at which
  point the same fix can be reapplied — no worse than Option 3's baseline.
- Filing upstream alone (a strict reading of Option 2, with no local
  change) is rejected as the sole action because it leaves the bug live
  here for an unbounded window while buying nothing this repo can measure;
  filing upstream is valuable but is not sufficient on its own to close
  issue #75's stated verification criterion.
- Option 3 (do nothing) is rejected outright: it has no forcing function to
  ever actually fix the bug, and this repo's own precedent (the friction
  protocol in `CLAUDE.md`) already commits to filing tool/scaffolding gaps
  rather than silently living with them.

**Scope note**: per issue #75's Champion revision, this record recommends
the option; it does not implement it. A follow-up increment should (a) make
the two-line local edit this record describes and confirm
`./.loom/scripts/generate-agents-md.sh --stdout` prints instead of erroring,
and (b) file the upstream path-bug report against `rjwalters/loom`'s
`defaults/scripts/generate-agents-md.sh` (and, if the header comment's
`check-agents-md-sync.sh` claim is also confirmed absent from the upstream
template itself, note that too in the same upstream report, since it is the
same "documented interface the installed copy doesn't deliver" family of
gap). Whether that follow-up ships as one PR or two is an implementation
detail for whoever picks it up, not something this record needs to settle.

## Does the two-key ratification mechanism apply?

**No — reviewed and found not applicable.** This record was checked against
`ratification/ee-key/SKILL.md`, `ratification/market-key/SKILL.md`, and
both files' `rubric.md` companions before concluding this.

- Both skills describe themselves, in their own opening paragraphs, as "the
  first/second of two non-author review keys **on a canary repo's
  spec-ratification PR**." Their entire research procedure operates on
  **spec rows** — the EE key's Step 1 classifies a reviewed PR as "a new
  ratification," "a scope-only decision record," or "a relax of a
  previously-RATIFIED row," all of which presuppose the PR is moving, or
  reasoning about, an entry in a `spec/*.md` parameter table or a
  `spec/decision-records/DR-*` numeric target. The market key's Step 1
  splits "spec rows" into in-scope/out-of-scope by whether a **buyer**
  could observe the parameter externally, and its whole research procedure
  (Steps 2-4) is about finding **competitor datasheets** and building a
  **comp table** (`comp-table-format.md`) against them.
- None of that vocabulary has a sensible referent here. There is no "spec
  row" to classify, no device-physics claim to re-derive from a netlist, no
  `sim/`-backed evidence tier to check, and — this is the one that makes
  forcing this into the market key's rubric actively wrong rather than
  merely inapplicable — there is no public "competitor" to a repo-internal
  installer shell script to build a comp table against. Fabricating one
  (e.g., inventing a comparison to some other project's install scripts)
  would be exactly the kind of dishonest, shoehorned artifact both SKILL.md
  files' disclosure-discipline sections implicitly warn against producing.
- This finding is a plain reading of both files, not a hard case: this
  record is a process/tooling decision about a broken shell script, not a
  circuit-spec claim, and `CLAUDE.md`'s own "Spec changes go through
  `spec/` with a decision record" line is specifically about the circuit
  spec — it does not extend the two-key mechanism to every decision record
  this repo might ever produce.

This is exactly the "does this policy even apply to non-spec repos/records"
class of ambiguity the sweep dispatch flagged as potentially needing a human
call — but on inspection it resolves cleanly from the text of the two
SKILL.md files themselves, without needing to guess at intent, so it is
recorded here as a finding rather than escalated. If a human/Champion
disagrees and believes 2AMLogic/2am#357's PR-ratification policy was
intended to route *all* decision records (not just spec-ratification ones)
through some review mechanism, that mechanism is not the ee-key/market-key
pair as currently scoped and would need to be named explicitly — this
record cannot resolve that on its own, since the policy issue itself
(2AMLogic/2am#357, #372) lives in a repo (`2AMLogic/2am`) this Builder has
no read access to. Absent that, this record proceeds through the ordinary
PR-review lifecycle (`loom:review-requested` → Judge → Champion/human),
which is the review path issue #75 itself was already using before the
2026-09-14 revision.

## Consequences

- Accepting this record does not itself change any code — it commits to a
  direction for the follow-up issue/PR that will make the two-line edit and
  file the upstream report.
- If a human/Champion instead prefers Option 2-only or Option 3, that is a
  disagreement with this record's recommendation, not a gap in its
  analysis; the trade-offs above should make that disagreement easy to
  state precisely (e.g., "we'd rather not carry any local divergence from
  upstream, even a temporary one").
