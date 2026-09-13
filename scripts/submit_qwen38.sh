#!/usr/bin/env bash
set -euo pipefail
root=/data/miyapeng/mmcode/mm-harness-evolve
name=${1:?unique service name required}
mkdir -p "$root/runs/services"
clusterx run --job-name "$name" --num-nodes 1 --gpus-per-task 2 \
    --cpus-per-task 16 --memory-per-task 192 --shm-size-gib 32 --no-env \
    bash "$root/scripts/serve_qwen38.sh" "$name"
