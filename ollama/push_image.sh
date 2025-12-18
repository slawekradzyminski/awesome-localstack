#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "Usage: $0 <image-name-suffix>"
  echo "Example: $0 qwens   # builds and pushes slawekradzyminski/qwens"
  exit 1
fi

IMAGE_NAME="slawekradzyminski/$1"

echo "Building image: $IMAGE_NAME (context: $(pwd))"
docker build \
  -t "$IMAGE_NAME" \
  -f "./Dockerfile" \
  "."

echo "Pushing image: $IMAGE_NAME"
docker push "$IMAGE_NAME"

echo "Done: $IMAGE_NAME pushed."

