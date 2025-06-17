#!/usr/bin/env bash
set -euo pipefail

MODEL="${OLLAMA_MODEL:-qwen3:0.6b}"

echo "Starting temporary Ollama server…"
ollama serve &
SERVER_PID=$!

until ollama list &>/dev/null ; do sleep 1 ; done
echo "Pulling $MODEL …"
ollama pull "$MODEL"

echo "Shutting server down…"
kill -SIGINT "$SERVER_PID" && wait "$SERVER_PID"
echo "✔  $MODEL cached in /root/.ollama"
