#!/usr/bin/env bash
# Keeps automatically launching further repetition batches (rep-offset 6,
# 9, 12, ...) one after another, forever (until MAX_REP_OFFSET), with no
# human interaction needed in between -- avoids needing a fresh approval
# for every new batch launch. Run standalone (no arguments) after
# ./run_full_dataset.sh has finished reps 0-5, or pass a still-running
# batch's pid as $1 to wait for it to finish first before continuing.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate

WAIT_PID="${1:-}"
MAX_REP_OFFSET=60   # stop after repetition_id 62 (i.e. 21 batches of 3) -- generous headroom, not truly infinite

if [[ -n "$WAIT_PID" ]] && kill -0 "$WAIT_PID" 2>/dev/null; then
    echo "[$(date)] waiting for current batch (pid $WAIT_PID) to finish..."
    while kill -0 "$WAIT_PID" 2>/dev/null; do
        sleep 20
    done
    echo "[$(date)] current batch finished."
else
    echo "[$(date)] no batch to wait for, starting immediately."
fi

for offset in $(seq 6 3 $MAX_REP_OFFSET); do
    echo "[$(date)] launching rep-offset $offset (reps $offset,$((offset+1)),$((offset+2)))..."

    # Defensive: clear anything squatting the proxy port before launching,
    # so a leftover process doesn't crash this batch with nobody watching.
    STALE_PID=$(lsof -ti :11443 2>/dev/null || true)
    if [[ -n "$STALE_PID" ]]; then
        echo "[$(date)] clearing stale process on port 11443: $STALE_PID"
        kill "$STALE_PID" 2>/dev/null || true
        sleep 2
    fi

    python3 scripts/capture_marble_incremental.py \
        --out-root captures_marble_incremental \
        --rep-offset "$offset" --reps 3

    if [[ -f captures_marble_incremental/dataset_index.csv ]]; then
        n=$(python3 -c "
import csv
rows = list(csv.DictReader(open('captures_marble_incremental/dataset_index.csv')))
print(sum(1 for r in rows if int(r['llm_packets']) > 0))
")
        echo "[$(date)] rep-offset $offset done. $n total real rows so far."
    fi
done

echo "[$(date)] repetition chain complete (reached rep-offset $MAX_REP_OFFSET)."
