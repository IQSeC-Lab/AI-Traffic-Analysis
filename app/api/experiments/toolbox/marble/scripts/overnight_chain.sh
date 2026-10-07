#!/usr/bin/env bash
# Waits for the currently-running graph v2 batch (pid passed as $1) to
# finish, then automatically launches star v2 -- so both run unattended in
# one background process, no further approval needed mid-flight.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate

GRAPH_PID="$1"

echo "[$(date)] waiting for graph v2 (pid $GRAPH_PID) to finish..."
while kill -0 "$GRAPH_PID" 2>/dev/null; do
    sleep 20
done
echo "[$(date)] graph v2 finished."

if [[ -f captures_marble_graph_v2/dataset_index.csv ]]; then
    n=$(($(wc -l < captures_marble_graph_v2/dataset_index.csv) - 1))
    echo "[$(date)] graph v2 dataset_index.csv has $n rows."
else
    echo "[$(date)] WARNING: graph v2 produced no dataset_index.csv -- something went wrong."
fi

# Defensive: clear anything squatting the proxy port before launching star,
# since a leftover process here would make star v2 fail immediately with
# nobody around to notice.
STALE_PID=$(lsof -ti :11443 2>/dev/null || true)
if [[ -n "$STALE_PID" ]]; then
    echo "[$(date)] clearing stale process on port 11443: $STALE_PID"
    kill "$STALE_PID" 2>/dev/null || true
    sleep 2
fi

echo "[$(date)] launching star v2..."
python3 scripts/capture_marble_dataset.py \
    --topology star \
    --categories bargaining research coding database \
    --reps 15 \
    --out-root captures_marble_star_v2

if [[ -f captures_marble_star_v2/dataset_index.csv ]]; then
    n=$(($(wc -l < captures_marble_star_v2/dataset_index.csv) - 1))
    echo "[$(date)] star v2 dataset_index.csv has $n rows."
else
    echo "[$(date)] WARNING: star v2 produced no dataset_index.csv -- something went wrong."
fi

echo "[$(date)] overnight chain complete."
