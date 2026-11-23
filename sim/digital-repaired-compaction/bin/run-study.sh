#!/bin/bash
# Issue #251: repaired-compaction study runner. Thin wrapper (issue #658) over
# the electrical-repair runner with STUDY_REL repointed at this study, so the
# REPRODUCE.md entrypoint is unchanged:
#   sim/digital-repaired-compaction/bin/run-study.sh <klt> <run-id> <request-name>...
# Each request name is requests/<name>.json; requests run sequentially (never
# in parallel: every request shares <requests>/.klt/place-and-route as klt
# scratch). klt must be the tool-pins.json build. No SPICE.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
STUDY_REL=sim/digital-repaired-compaction exec "$ROOT/sim/digital-electrical-repair/bin/run-study.sh" "$@"
