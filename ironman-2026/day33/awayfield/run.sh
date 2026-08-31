#!/usr/bin/env bash
# The away-field 2x2's missing cell: three arms on the SAME unfamiliar stack,
# differing only in which schema catalog is in the prompt slot.
#
#   wrong  the shipped catalog, which describes a different cluster
#   none   no catalog at all, discover_* only
#   own    a catalog generated off this stack by make_catalog.py
#
# Each run gets its own STORE_PATH so case recall starts empty -- otherwise the
# later arms sit an open-book exam on the earlier ones' answers.
#
#   docker run -d --name day33-away -p 9090:9090 -p 3100:3100 -p 3200:3200 \
#       -p 8080:8080 o11y-bench-o11y-stack:latest
#   python3 make_catalog.py --out catalog.away.md
#   OUT=/tmp/away bash run.sh
#
# For the reference arm (Day1's agent, unchanged), note that it reads its API
# key from the environment and does NOT load the service's .env -- without that,
# every answer comes back empty and it scores a very convincing 0.0/9:
#
#   set -a; . .env; set +a
#   AGENT_DIR=$PWD python3 ../../day25/rerun_bench.py --which baseline
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BENCH=$HERE/../../day25/rerun_bench.py
SERVICE=${SERVICE:-$HOME/Project/o11y-bench/aiops-agent/service}
OUT=${OUT:-/tmp/day33-away}
ROUNDS=${ROUNDS:-3}

mkdir -p "$OUT"
cd "$SERVICE" || exit 1   # the .env with GOOGLE_API_KEY is read relative to cwd

for round in $(seq 1 "$ROUNDS"); do
  for arm in wrong none own; do
    case $arm in
      wrong) FLAGS="" ;;
      none)  FLAGS="--no-governance" ;;
      own)   FLAGS="--catalog $HERE/catalog.away.md" ;;
    esac
    echo "===== arm=$arm round=$round $(date +%H:%M:%S)"
    AGENT_DIR=$PWD STORE_PATH=$OUT/store-$arm-$round.db \
      timeout 1800 python3 "$BENCH" --which today $FLAGS \
        --report "$OUT/report-$arm-$round.json" 2>&1 |
      grep -vE "UserWarning|pydantic.v1|Deserializing|LANGGRAPH"
  done
done
echo "ALL DONE $(date +%H:%M:%S)"
