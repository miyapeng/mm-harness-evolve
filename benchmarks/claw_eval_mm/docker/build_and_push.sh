#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
UPSTREAM="$ROOT/third_party/claw-eval-5680b8b11ff2ee5dd2b07b89086a29a5c5c984d7"
CONTAINERFILE="$ROOT/benchmarks/claw_eval_mm/docker/Containerfile.pjlab"
AUTHFILE=${1:-/tmp/swe-mm-ccr-auth.json}
TARGET=registry.pjlab.org.cn/ccr-t-llm-frontier/claw-eval
TAG=agent-5680b8b-pjlab
BUILD_ROOT=${CLAW_BUILDAH_ROOT:-/tmp/claw-eval-buildah-root}
RUN_ROOT=${CLAW_BUILDAH_RUNROOT:-/tmp/claw-eval-buildah-runroot}

test -r "$AUTHFILE"
test -r "$UPSTREAM/src/claw_eval/sandbox/server.py"

export NO_PROXY="registry.pjlab.org.cn,localhost,127.0.0.1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
mkdir -p "$BUILD_ROOT" "$RUN_ROOT"

buildah --root "$BUILD_ROOT" --runroot "$RUN_ROOT" --storage-driver vfs bud \
  --isolation chroot \
  --network host \
  --authfile "$AUTHFILE" \
  --label org.opencontainers.image.title=Claw-Eval-sandbox \
  --label org.opencontainers.image.source=https://github.com/claw-eval/claw-eval \
  --label org.opencontainers.image.revision=5680b8b11ff2ee5dd2b07b89086a29a5c5c984d7 \
  --label mm-harness-evolve.base-compatibility=vision2web-official-577f939 \
  -f "$CONTAINERFILE" \
  -t "localhost/claw-eval:$TAG" \
  "$UPSTREAM"

buildah --root "$BUILD_ROOT" --runroot "$RUN_ROOT" --storage-driver vfs \
  push --authfile "$AUTHFILE" \
  "localhost/claw-eval:$TAG" "docker://$TARGET:$TAG"

SKOPEO=/data/miyapeng/mmcode/MultimodalCode/.envs/imgsync/bin/skopeo
"$SKOPEO" inspect --authfile "$AUTHFILE" --format '{{.Digest}}' \
  "docker://$TARGET:$TAG"
