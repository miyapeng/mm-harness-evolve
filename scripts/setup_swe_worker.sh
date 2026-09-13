#!/usr/bin/env bash
# Repository-local runtime. The existing conda base is read-only and shared.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
base_python=/data/miyapeng/miniconda3/envs/vllm/bin/python
if [[ ! -x .venv-swe-worker/bin/python ]]; then
  "$base_python" -m venv --copies --system-site-packages .venv-swe-worker
fi
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  .venv-swe-worker/bin/python -m pip install --no-build-isolation \
  --index-url https://pypi.org/simple -r requirements/swe-worker.lock.txt
LITELLM_LOCAL_MODEL_COST_MAP=True .venv-swe-worker/bin/python -c \
  'from sweagent.run.run_single import RunSingle; import flask, playwright; print("Native worker imports passed")'
