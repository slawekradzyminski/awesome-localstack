#!/bin/bash
set -euo pipefail

MODEL="${OLLAMA_MODEL:-qwen3.5:2b}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
DOCKER_OLLAMA_URL="${DOCKER_OLLAMA_URL:-http://host.docker.internal:11434}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Native Ollama is not installed. Install it with: brew install ollama"
  exit 1
fi

launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
launchctl setenv OLLAMA_FLASH_ATTENTION "1"

if ! curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew services start ollama
  else
    echo "Ollama is not running. Start it with: OLLAMA_HOST=0.0.0.0:11434 ollama serve"
    exit 1
  fi
fi

ollama pull "$MODEL"

docker compose -f docker-compose.yml -f docker-compose.native-ollama.yml up -d --remove-orphans

docker run --rm curlimages/curl:8.13.0 -fsS "$DOCKER_OLLAMA_URL/api/tags" >/dev/null

echo "Full stack is running with native Ollama at $OLLAMA_URL."
echo "Pulled native Ollama model: $MODEL"
echo "Backend OLLAMA_BASE_URL:"
docker compose -f docker-compose.yml -f docker-compose.native-ollama.yml exec -T backend printenv OLLAMA_BASE_URL
