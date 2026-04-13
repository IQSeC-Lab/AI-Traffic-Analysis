#!/usr/bin/env bash
# download_all_models.sh
# Runs: python3 downloader.py --model <MODEL> for each model in the list

set -euo pipefail

MODELS_7B=(
    "ghost-x/ghost-7b-alpha"
    "Qwen/Qwen2.5-7B-Instruct" 
"HuggingFaceH4/zephyr-7b-beta"
"mistralai/Mistral-7B-Instruct-v0.2"
"Intel/neural-chat-7b-v3-3"
"nvidia/AceReason-Nemotron-1.1-7B"
"GritLM/GritLM-7B"
"mlabonne/NeuralDaredevil-7B"
"DeepHat/DeepHat-V1-7B"
"cstr/Spaetzle-v60-7b"
)

MODELS_14B=(
    "prithivMLmods/Gauss-Opus-14B-R999"
    "Qwen/Qwen3-14B-Base"
    "ozone-research/0x-lite"
    "nvidia/AceReason-Nemotron-14B"
    "MegaScience/Qwen3-14B-MegaScience"
    "soob3123/GrayLine-Qwen3-14B"
    "prithivMLmods/Evac-Opus-14B-Exp"
    "rubenroy/Zurich-14B-GCv2-5m"
    "Rombo-Org/Rombo-LLM-V2.5-Qwen-14b"
    "unsloth/Qwen2.5-Coder-14B-Instruct"
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