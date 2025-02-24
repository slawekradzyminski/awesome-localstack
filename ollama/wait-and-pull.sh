#!/usr/bin/env bash
set -e

echo "Starting Ollama server in the background..."
ollama serve &
SERVER_PID=$!

echo "Waiting until Ollama is responsive..."
while ! ollama list | grep -q "NAME"; do
  sleep 1
done

echo "Pulling the llama3.2:1b model..."
ollama pull llama3.2:1b

echo "Stopping background Ollama server..."
kill -SIGINT "$SERVER_PID"

# Allow a moment for the server to fully shut down (optional)
sleep 2

echo "All done. The model should now be in /root/.ollama/"
