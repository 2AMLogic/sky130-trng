#!/bin/bash
# Issue #236: run electrical-repair requests sequentially (never in parallel:
# every request in requests/ shares <requests>/.klt/place-and-route as klt
# scratch). Run from anywhere; klt must be the tool-pins.json build.
#   sim/digital-electrical-repair/bin/run-study.sh <klt> <run-id> <request-name>...
# Each request name is requests/<name>.json. After each P&R+verify run the
# final-route electrical audit is run on the archived DEF+SPEF. No SPICE.
# STUDY_REL repoints the runner at a sibling study (issue #658); the default
# is this study.
set -u
KLT=${1:?klt path}; RID=${2:?run id}; shift 2
STUDY_REL=${STUDY_REL:-sim/digital-electrical-repair}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
R=$ROOT/$STUDY_REL/runs/$RID
cd "$ROOT"
mkdir -p "$R"
"$KLT" --version > "$R/klt-version.txt"
for n in "$@"; do
  mkdir -p "$R/$n"
  start=$(date -u +%FT%TZ)
  python3 sim/digital-pnr/harness/pnr-and-verify.py --klt "$KLT" --allow-tool-drift \
    --request "$STUDY_REL/requests/$n.json" --out-dir "$R/$n" \
    > "$R/$n/stdout.md" 2> "$R/$n/stderr.log"
  rc=$?
  echo "$n pnr-verify exit $rc start $start end $(date -u +%FT%TZ)" >> "$R/exit-codes.txt"
  python3 sim/digital-electrical-repair/analysis/final_route_audit.py --run-dir "$R/$n" --klt "$KLT" \
    --request "$STUDY_REL/requests/$n.json" \
    > "$R/$n/audit-stdout.log" 2> "$R/$n/audit-stderr.log"
  echo "$n audit exit $? end $(date -u +%FT%TZ)" >> "$R/exit-codes.txt"
done
