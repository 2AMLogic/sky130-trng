#!/bin/bash
# Issue #226: run the three-point utilisation study sequentially (never in
# parallel: every run reuses <requests>/.klt/place-and-route as klt scratch).
#   sim/digital-floorplan-compaction/bin/run-study.sh <klt> <run-id> [util...]
# <klt> must be the tool-pins.json build (0.6.0+g10f3da34c088); see the
# study README for the worktree-venv recipe. Run from the repo root (the
# containerised openroad wrapper mounts only $PWD). No SPICE is involved.
set -u
KLT=${1:?klt path}; RID=${2:?run id}; shift 2
UTILS=${*:-40 55 65}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
R=$ROOT/sim/digital-floorplan-compaction/runs/$RID
cd "$ROOT"
mkdir -p "$R"
"$KLT" --version > "$R/klt-version.txt"
for u in $UTILS; do
  mkdir -p "$R/util$u"
  start=$(date -u +%FT%TZ)
  python3 sim/digital-pnr/harness/pnr-and-verify.py --klt "$KLT" --allow-tool-drift \
    --request "sim/digital-floorplan-compaction/requests/util$u.json" --out-dir "$R/util$u" \
    > "$R/util$u/stdout.md" 2> "$R/util$u/stderr.log"
  rc=$?
  echo "util$u exit $rc start $start end $(date -u +%FT%TZ)" >> "$R/exit-codes.txt"
done
