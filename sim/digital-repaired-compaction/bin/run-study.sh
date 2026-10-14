#!/bin/bash
# Issue #251: run electrical-repair requests sequentially (never in parallel:
# every request in requests/ shares <requests>/.klt/place-and-route as klt
# scratch). Run from anywhere; klt must be the tool-pins.json build.
#   sim/digital-repaired-compaction/bin/run-study.sh <klt> <run-id> <request-name>...
# Each request name is requests/<name>.json. After each P&R+verify run the
# final-route electrical audit is run on the archived DEF+SPEF. No SPICE.
set -u
KLT=${1:?klt path}; RID=${2:?run id}; shift 2
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
R=$ROOT/sim/digital-repaired-compaction/runs/$RID
cd "$ROOT"
mkdir -p "$R"
"$KLT" --version > "$R/klt-version.txt"
for n in "$@"; do
  mkdir -p "$R/$n"
  start=$(date -u +%FT%TZ)
  python3 sim/digital-pnr/harness/pnr-and-verify.py --klt "$KLT" --allow-tool-drift \
    --request "sim/digital-repaired-compaction/requests/$n.json" --out-dir "$R/$n" \
    > "$R/$n/stdout.md" 2> "$R/$n/stderr.log"
  rc=$?
  echo "$n pnr-verify exit $rc start $start end $(date -u +%FT%TZ)" >> "$R/exit-codes.txt"
  python3 sim/digital-electrical-repair/analysis/final_route_audit.py --run-dir "$R/$n" --klt "$KLT" --request "sim/digital-repaired-compaction/requests/$n.json" \
    > "$R/$n/audit-stdout.log" 2> "$R/$n/audit-stderr.log"
  echo "$n audit exit $? end $(date -u +%FT%TZ)" >> "$R/exit-codes.txt"
done
