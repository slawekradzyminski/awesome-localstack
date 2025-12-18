#!/usr/bin/env bash
set -euo pipefail

PRIMARY_MODEL="${OLLAMA_MODEL:-qwen3:4b-instruct}"
EXTRA_MODELS="${OLLAMA_EXTRA_MODELS:-}"

echo "Starting temporary Ollama server…"
ollama serve &
SERVER_PID=$!

until ollama list &>/dev/null ; do sleep 1 ; done
for MODEL in ${PRIMARY_MODEL} ${EXTRA_MODELS}; do
  [ -z "$MODEL" ] && continue
  echo "Pulling $MODEL …"
  ollama pull "$MODEL"
done

echo "Shutting server down…"
kill -SIGINT "$SERVER_PID" && wait "$SERVER_PID"
echo "✔  Models cached in /root/.ollama"
