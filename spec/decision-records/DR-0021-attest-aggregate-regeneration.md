---
dr: DR-0021-attest-aggregate-regeneration
title: Regenerate item-9 signoff attestation aggregate on main rather than per PR
status: Proposed
date: 2026-11-23
deciders: "Proposed via issue #697 (Champion-approved revision, 2026-11-23); pending operator ratification"
supersedes: "n/a -- splits PR-time vs main-time freshness gating for T1 item 9 only. Items 1.digital, 2.analog, 2.digital, and 10 keep full PR-time committed-bytes gating unchanged; no ratified spec value, signoff verdict, or existing evidence record changes."
superseded_by: n/a
related: "#697 (this record), #320, #363, #650, #672, DR-0019"
---

# DR-0021: regenerate item-9 signoff attestation aggregate on `main`

## Status

- 2026-11-23: **Proposed**. Implements the 7-point contract ratified in issue
  #697's revision after measuring the merge-conflict treadmill on PR #605 and
  PR #614 and verifying `main`'s branch-protection state.

## Context

`signoff/attest.py` builds artifact-anchored `generic` envelopes for T1 items
`1.digital`, `2.analog`, `2.digital`, `9`, and `10` (issue #320). Item 9's
inventory (`signoff/attest/9.inventory.json`, 135+ members as of `e5dc4e34`,
2026-11-23) pins `sim/*/*.py`, `sim/*/{testbench,harness,analysis,bin,requests}/*`,
`digital/tb/*`, `REPRODUCE.md`, the three `pdk.json` files, and the four shared
helper modules imported by `sim/` harnesses. Its derived aggregate hash chain
propagates through four committed files:

1. `signoff/attest/9.inventory.json` (`member_count` and member entries)
2. `signoff/attest/9.json` (`provenance.input.content_hash`)
3. `signoff/block-manifest.json` (`evidence["9"].content_hash`)
4. `signoff/t1-report.json` (the `klt signoff --manifest` grading output)

Because every PR that adds or edits an inventoried `sim/` file changes the same
aggregate hash lines in those four files, any two concurrent `sim/` PRs conflict
on all four files even when their substantive changes are completely disjoint.
Resolving each conflict requires regenerating the hash chain, pushing a new
merge commit, invalidating the PR's review-verdict SHA, and re-running both CI
and Judge.

### Upfront measurement (PR #605 and PR #614, 2026-11-23)

Measured via `gh pr view`, `gh api .../actions/runs/{id}/jobs`, and
`git merge-tree --write-tree` on each merge commit's parents (`origin/main` @
`e5dc4e34`, 2026-11-23; posted on issue #697 before implementation):

- **11 `CI` workflow runs** across PR #605 (7 runs) and PR #614 (4 runs),
  totalling **29.38 wall-clock minutes** (**25.97 sum-of-jobs minutes**) and
  **9 Judge verdict passes** (excluding automated daemon base-conflict flips).
- **Strictly signoff-only conflict pushes** (5 runs: #605 `a03f0842`, `d79731b1`,
  `9b2fa023`; #614 `364dc71c`, `0f6ef6c7`): **12.55 job-minutes (48.3%)**,
  **12.65 wall-clock minutes (43.1%)**, and **3 of 9 Judge passes (33.3%)**
  (`364dc71c`'s Judge pass is counted conservatively as independent because it
  was PR #614's first full code review).
- Excluding `364dc71c` (which also carried a 1-line friction-ledger sort), the
  4 pure signoff-only conflict runs still account for **38.1%** of CI
  job-minutes (9.90 / 25.97 min), **36.2%** of wall-clock minutes (10.63 /
  29.38 min), and **33.3%** (3/9) of Judge passes — and PR #614 went
  `CONFLICTING` again 9 minutes after its `0f6ef6c7` approval.
- One additional push (#605 `8093216e`, 2.45 job-min / 9.4%, 1 Judge pass)
  carried both signoff conflicts and real code conflicts from #595 and is
  reported separately from signoff-only conflicts.

All cuts exceed the ~20% threshold set in #697.

### Rejected alternatives

- **One inventory file per member:** rejected. The aggregate hash chained
  through `9.json`, `block-manifest.json`, and `t1-report.json` still changes in
  every PR, so conflicts remain; worse, a textually clean `git merge-file` on
  `9.inventory.json` can silently produce a wrong `member_count` (Champion
  reproduced 137 members with stored `member_count: 136`).
- **Narrowing item 9's selectors:** rejected. Shrinks the conflict window
  without eliminating it and weakens attested testbench/harness coverage.
- **GitHub merge queue:** rejected. Lives in repository settings outside the
  reviewed git tree (out of scope) and still requires per-queue-entry
  regeneration.

## Decision

Move item-9 aggregate regeneration from per-PR commits to a serialized
post-merge workflow on `main` (`.github/workflows/attest-main.yml`), governed by
the following 7-point contract:

### 1. Who writes the aggregate

Only the `main` regeneration job (`attest-main` via `signoff/attest.py --sync-main`)
writes `signoff/attest/9.inventory.json` (including `member_count`),
`signoff/attest/9.json`, `signoff/block-manifest.json` `evidence["9"]`, and
item-9 updates in `signoff/t1-report.json`. A PR **must not** touch those files
for item-9 reasons. `member_count` and `members` are always produced together by
`attest.build()`, never hand-merged.

`ci.yml` enforces this structurally on `pull_request` by running
`python3 signoff/attest.py --check-pr --base-ref HEAD^1`, which fails if the PR
modified `signoff/attest/9.inventory.json`, `signoff/attest/9.json`, or
`signoff/block-manifest.json` `evidence["9"]` relative to the PR base.

### 2. PR-time gate for item 9 (and unchanged items 1/2/10)

On `pull_request` (and on `ci.yml`'s `signoff-check` job generally),
`signoff/attest.py --check-pr` replaces committed-bytes freshness for item 9
only:

- **Item 9 at PR time:**
  - A fresh `build(root, "9")` on the PR merge ref must produce
    `status == "pass"` (every selector matches at least one file, `check_9`
    verifies every record-bearing `sim/<family>/records` directory has a
    covered testbench/harness/analysis/script, all three `pdk.json`
    `open_pdks_commit` pins agree, and `REPRODUCE.md` states the pin).
  - The committed item-9 chain (`9.inventory.json`, `9.json`,
    `block-manifest.json` `evidence["9"]`) must remain structurally valid and
    internally consistent: `member_count == len(members)`, no duplicate member
    paths, envelope `provenance.input.content_hash == sha256(9.inventory.json)`,
    and manifest `evidence["9"]` matches the envelope. This catches stale-count
    clean merges (such as `git merge-file` leaving 137 members with
    `member_count == 136`) even at PR time.
  - `sim/tests/test_signoff_attest.py` runs on every PR, verifying the
    helper-import closure (`layout/bin/`, `design/`) against fresh
    `build(REPO, key)` (so newly added `sim/*/*.py` scripts importing unpinned
    helpers still fail at PR time) and running full-tree `--check` consistency
    against a regenerated scratch copy of the tree.
  - `klt signoff --manifest signoff/block-manifest.json ...` byte-diff against
    `signoff/t1-report.json` stays unchanged in `ci.yml` (because PRs do not
    alter item 9 in `block-manifest.json`, `t1-report.json` remains
    byte-identical unless the PR updates another item such as item 6 or 10).
- **Items `1.digital`, `2.analog`, `2.digital`, and `10` at PR time:** keep
  full committed-bytes `--check` unchanged.

### 3. Main-time gate (`push: main`)

`.github/workflows/attest-main.yml` triggers on `push: main` (and
`workflow_dispatch`), serialized with `concurrency: { group: attest-main,
cancel-in-progress: false }`, installs the pinned `klayout-tools==0.8.0`, and
runs `python3 signoff/attest.py --sync-main --run-tests --status-mode github`:

1. Checks out the current `origin/main` head and runs `build(root, "9")`
   (must have `status == "pass"`).
2. Runs `attest.py --write 9` and re-renders `signoff/t1-report.json` verbatim
   with the documented `klt signoff` command (accepting exit codes `0` and `3`).
3. Rejects any modified path outside the four item-9 artifacts.
4. Runs the full main-time verification gate before committing or stamping:
   - `attest.py --check` across **all** items (`1.digital`, `2.analog`,
     `2.digital`, `9`, `10`),
   - `member_count == len(members)` and every member's sha256 matches the file
     on disk,
   - fresh `klt signoff` re-render byte-identical to `signoff/t1-report.json`,
   - `sim/tests/test_signoff_attest.py`,
   - idempotence check (a second `--write 9` changes zero bytes).
5. If regeneration changed any of the four artifacts, commits ONLY those
   changed files as `github-actions[bot]` (no `Signed-off-by:` trailer) and
   pushes to `main`.

### 4. Which SHA is signoff-valid

A commit on `main` is **signoff-valid** iff the `attest-main` commit status is
`success` **on that exact SHA** (which `sync_main` stamps only after the full
main-time gate passes AND regeneration is a no-op on that SHA):

- **No-op merge commit** (touches no item-9 inventoried files): passes full
  verification with zero diff, pushes no bot commit, and receives
  `attest-main: success` directly on the merge commit's SHA.
- **Pending merge commit** (adds or modifies item-9 inventoried files): marked
  `attest-main: pending` immediately on start, and once the bot commit pushes,
  remains `attest-main: pending` (`Superseded by bot commit <sha>; not
  signoff-valid`) — it **never** receives `success`. Only the following bot
  commit's exact SHA receives `attest-main: success`.
- **Failed regeneration or verification:** the failing SHA is stamped
  `attest-main: failure` (red), no bot commit is pushed, the workflow exits 1,
  and no commit is signoff-valid until fixed and a subsequent SHA receives
  `attest-main: success`.
- **Interleaved second merge:** because the workflow is serialized
  (`cancel-in-progress: false`) and `sync_main` handles non-fast-forward push
  rejections by fetching `origin/main`, marking the prior SHA `pending`
  (superseded), and retrying against the newest `origin/main` head, only the
  single newest bot commit receives `attest-main: success` and all intermediate
  SHAs remain superseded (`pending`).

Consumers reading `signoff/t1-report.json` or `signoff/attest/9.*` from `main`
must check that `attest-main` is `success` on the exact commit SHA they read.

### 5. No loop

1. `attest-main.yml` pushes using the repository's `GITHUB_TOKEN`, which GitHub
   Actions guarantees will not trigger subsequent `on: push` workflows.
2. As defense in depth (in case a different token is ever configured),
   `attest-main.yml` skips commits whose subject starts with
   `chore(signoff): regenerate item-9 attestation`, and `sync_main` is
   idempotent (a no-op tree never creates a commit).
3. Because the bot commit does not trigger a second run, the originating
   `sync_main` run directly stamps `attest-main: success` on the newly pushed
   bot commit's SHA via the GitHub Commit Statuses API (`statuses: write`).

### 6. No relaxation

No check performed before this change becomes unchecked anywhere. What changes —
stated plainly, following DR-0019's transparency precedent — is **when** item-9
committed-bytes freshness is enforced:

- **Before DR-0021:** item-9 committed-bytes freshness ran on every PR and on
  `main` (`ci.yml` `attest.py --check`).
- **After DR-0021:** item-9 committed-bytes freshness moves from PR time to
  `main` time (`attest-main.yml` `attest.py --sync-main`). Every semantic and
  structural item-9 check (selectors, `check_9` family coverage, PDK pin
  agreement, `REPRODUCE.md` pin, helper-import closure, committed-chain
  consistency, stale-count guard) remains enforced at PR time, and items
  `1.digital`, `2.analog`, `2.digital`, and `10` keep full PR-time
  committed-bytes gating unchanged.

### 7. Branch-protection verification (blocking prerequisite)

Verified against `2AMLogic/sky130-trng` via the GitHub REST API on 2026-11-23
before implementation:

- `GET /repos/2AMLogic/sky130-trng/branches/main` returned
  `"protected": false` (`protection.enabled: false`).
- `GET /repos/2AMLogic/sky130-trng/rulesets` returned `[]`.
- `GET /repos/2AMLogic/sky130-trng/rules/branches/main` returned `[]`.

`main` is therefore not protected against a workflow push using
`permissions: { contents: write, statuses: write }`. (`GET .../actions/permissions/workflow`
returned HTTP 403 for the app token due to missing `administration:read`.) If
branch protection or org-level Actions write restrictions are later enabled and
reject the push while `origin/main` has not advanced, `sync_main` fails closed:
it stamps the pending SHA `attest-main: failure` and exits 1 rather than
weakening the gate.

## Consequences

- Concurrent PRs adding or editing `sim/` Python files no longer touch
  `signoff/attest/9.inventory.json`, `signoff/attest/9.json`,
  `signoff/block-manifest.json` `evidence["9"]`, or `signoff/t1-report.json`,
  eliminating item-9 merge conflicts and the resulting CI/Judge re-run treadmill.
- Between a `sim/` PR merge commit and the bot commit pushed seconds later by
  `attest-main.yml`, `main`'s merge commit has stale item-9 artifacts by design
  and is marked `attest-main: pending` (not signoff-valid); the bot commit
  immediately restores full consistency and carries `attest-main: success`.
- `signoff/attest.py` gains `--check-pr` (with optional `--base-ref`) and
  `--sync-main`; `.github/workflows/ci.yml` switches `signoff-check` to
  `--check-pr`; `.github/workflows/attest-main.yml` owns post-merge item-9
  regeneration and `attest-main` status stamping.
- Items `1.digital`, `2.analog`, `2.digital`, and `10` are unaffected (if any
  of them later exhibits a similar conflict treadmill, it can be evaluated in a
  separate issue and DR).
