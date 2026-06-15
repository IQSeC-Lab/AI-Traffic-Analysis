#!/usr/bin/env bash
# download_all_models.sh
# Runs: python3 downloader.py --model <MODEL> for each model in the list

set -euo pipefail

MODELS_7B=(
    "HaolunLi/LLaMA-3.2-3B-SRL"
    "Xtra-Computing/XtraGPT-3B"
    "unsloth/Phi-4-mini-reasoning"
    "PatronusAI/glider"
    "nvidia/AceReason-Nemotron-1.1-7B"
    "Qwen/Qwen2.5-7B-Instruct"
    "typhoon-ai/llama3.1-typhoon2-8b-instruct"
    "rfrancu/LLMTwin-Llama-3.1-8B"
    "Qwen/Qwen3-14B-Base"
    "MegaScience/Qwen3-14B-MegaScience"
)

MODELS_14B=(
    
)

ALL_MODELS=("${MODELS_7B[@]}" "${MODELS_14B[@]}")

TOTAL=${#ALL_MODELS[@]}
SUCCESS=0
FAILED=()

echo "========================================="
echo " Model Downloader — $TOTAL models queued"
echo "========================================="

for i in "${!ALL_MODELS[@]}"; do
    MODEL="${ALL_MODELS[$i]}"
    echo ""
    echo "[$(( i + 1 ))/$TOTAL] Downloading: $MODEL"
    echo "-----------------------------------------"

    if python3 downloader.py --model "$MODEL"; then
        echo "✅  Done: $MODEL"
        (( SUCCESS++ )) || true
    else
        echo "❌  FAILED: $MODEL"
        FAILED+=("$MODEL")
    fi
done

echo ""
echo "========================================="
echo " Summary: $SUCCESS/$TOTAL succeeded"
if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo " Failed models:"
    for m in "${FAILED[@]}"; do
        echo "   - $m"
    done
fi
echo "========================================="