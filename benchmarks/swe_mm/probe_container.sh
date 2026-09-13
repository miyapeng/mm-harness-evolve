#!/usr/bin/env bash
# Read-only environment probe inside the digest-pinned official instance image.
set -euo pipefail
root=/data/miyapeng/mmcode/mm-harness-evolve
out=$root/runs/swe-mm-container-probe/${1:?unique probe name required}
mkdir -p "$out"
exec > >(tee "$out/probe.log") 2>&1
date -u +%FT%TZ
git -C /testbed rev-parse HEAD
for executable in python python3 node npm git unshare; do
    command -v "$executable" || true
done
ls -d /root/python* /opt/miniconda* /root/.cache/ms-playwright /usr/bin/python* 2>/dev/null || true
if unshare --user --map-root-user --mount --pid --fork true; then
    echo 'namespace_probe=passed'
else
    echo 'namespace_probe=unavailable'
fi
"$root/.venv-swe-agent/bin/python" -c 'import sweagent, swerex; print(sweagent.__file__, swerex.__version__)' || true
/data/miyapeng/miniconda3/envs/vllm/bin/python -c 'import sys; print(sys.version)' || true
echo 'probe_complete=true'
