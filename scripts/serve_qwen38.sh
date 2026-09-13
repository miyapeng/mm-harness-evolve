#!/usr/bin/env bash
# Adapted from MultimodalCode/scripts/agent_smoke/start_vllm_server.sh.
# This project's service, records and lifecycle are independent of the old project.
set -euo pipefail
root=/data/miyapeng/mmcode/mm-harness-evolve
run_dir=$root/runs/services/${1:?unique service name required}
mkdir "$run_dir"
exec > >(tee "$run_dir/job.log") 2>&1
export PYTHONUNBUFFERED=1
exec /data/miyapeng/miniconda3/envs/vllm/bin/python "$root/scripts/serve_qwen38.py" "$run_dir"
