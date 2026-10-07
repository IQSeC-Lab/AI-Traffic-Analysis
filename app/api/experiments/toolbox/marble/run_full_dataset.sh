#!/usr/bin/env bash
# Runs the real-MARBLE encrypted-traffic dataset collection: graph and star
# coordination topologies x 10 task categories (bargaining/research/coding/
# database/bugfix/swe_bench/deep_research/medical_diagnosis/legal_review/
# debate) x 15 sampled real tasks each x 6 repetitions = up to 1800 real
# MARBLE runs, each with its own genuinely TLS-encrypted, tcpdump-captured
# agent<->LLM traffic sliced into a per-task .pcap, plus a per-agent
# call-timing sidecar (*.agent_calls.json) for K-agent-subset analysis.
#
# Builds the dataset task_id-outermost (all categories x topologies x reps
# for task 1, then task 2, ...) and saves after every single run, not just
# at the end of a batch -- the dataset is usable and safe to interrupt at
# any point. Re-running this script skips everything already collected.
#
# tree and chain topologies are NOT run here -- see README's "Notes on
# this fork" for why. Both still work via scripts/capture_marble_dataset.py
# directly if you want to explore them.
#
# Run this after ./setup.sh. Takes many hours -- this is meant to run
# unattended over a long period, not to completion in one sitting.
# Live per-task progress: tail -f captures_marble_incremental/progress.jsonl
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
source .venv/bin/activate

python3 scripts/capture_marble_incremental.py \
    --out-root captures_marble_incremental \
    --rep-offset 0 --reps 6

echo ""
echo "=== reps 0-5 done. To keep extending the dataset with more repetitions ==="
echo "=== (recommended for statistical robustness), run further batches, e.g.: ==="
echo "===   python3 scripts/capture_marble_incremental.py --out-root captures_marble_incremental --rep-offset 6 --reps 3"
echo "=== Or run scripts/repetition_chain.sh to keep extending automatically and unattended:"
echo "===   bash scripts/repetition_chain.sh"
echo ""
echo "=== dataset index: captures_marble_incremental/dataset_index.csv ==="
