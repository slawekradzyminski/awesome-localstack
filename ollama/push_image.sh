#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "Usage: $0 <image-name-suffix>"
  echo "Example: $0 ollama-qwen35-2b:0.18.3-1   # builds and pushes the qwen3.5:2b image"
  exit 1
fi

IMAGE_NAME="slawekradzyminski/$1"

docker buildx create --name ollama-qwen-builder --use || true
docker buildx inspect --bootstrap

echo "Building and pushing multi-architecture image: $IMAGE_NAME (context: $(pwd))"
docker buildx build --platform linux/amd64,linux/arm64 \
  -t "$IMAGE_NAME" \
  --push \
  -f "./Dockerfile" \
  "."

echo "Done: $IMAGE_NAME pushed."
