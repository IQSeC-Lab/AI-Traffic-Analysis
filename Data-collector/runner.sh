#!/bin/bash

set -e

# Here change the conda enviroment that is in use.
CONDA_ENV="llm"
REPEATS=100

source ~/miniconda3/etc/profile.d/conda.sh
conda activate $CONDA_ENV

echo "Using Python:"
which python


for PROMPT_ID in {1..50}
do
    echo "======================================="
    echo "Running Prompt ${PROMPT_ID}"
    echo "Repeats: ${REPEATS}"
    echo "======================================="

    python main.py -p ${PROMPT_ID} -r ${REPEATS}

    echo "Finished Prompt ${PROMPT_ID}"
done

echo "All experiments completed."