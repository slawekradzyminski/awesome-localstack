#!/usr/bin/env bash
set -euo pipefail

DEFAULT_MODEL="hf.co/prism-ml/Bonsai-27B-gguf:Q1_0"
QWEN_MODEL="hf.co/unsloth/Qwen3.5-2B-GGUF:Q4_K_M"
MOCK_IMAGE="slawekradzyminski/ollama-mock:1.0.6@sha256:bb34ad70c6673f2f384e43da2b0984bb832eee7d76ee992365a93e612133c81c"

default_config="$(OLLAMA_BASE_URL=http://ollama:11434 docker compose -f docker-compose.yml config)"
grep -F "name: awesome-full-native" <<<"$default_config"
grep -F "model: $DEFAULT_MODEL" <<<"$default_config"
grep -F "OLLAMA_BASE_URL: http://ollama-dmr-adapter:11434" <<<"$default_config"
grep -F "model_var: OLLAMA_MODEL" <<<"$default_config"
grep -F "image: awesome-localstack/ollama-dmr-adapter:local" <<<"$default_config"
grep -F "condition: service_healthy" <<<"$default_config"

qwen_config="$(OLLAMA_MODEL="$QWEN_MODEL" docker compose -f docker-compose.yml config)"
grep -F "model: $QWEN_MODEL" <<<"$qwen_config"

mock_config="$(docker compose -f docker-compose.yml -f docker-compose.model-mock.yml config)"
grep -F "OLLAMA_BASE_URL: http://ollama:11434" <<<"$mock_config"
if grep -F "awesome-localstack/ollama-dmr-adapter:local" <<<"$mock_config"; then
  echo "DMR adapter must not start with the CI mock profile." >&2
  exit 1
fi
docker compose -f docker-compose.yml -f docker-compose.model-mock.yml config --images \
  | grep -Fx "$MOCK_IMAGE"

docker compose -f lightweight-docker-compose.yml config --images | grep -Fx "$MOCK_IMAGE"
docker compose -f docker-compose.server.yml config --images | grep -Fx "$MOCK_IMAGE"

echo "Ollama configuration checks passed."
