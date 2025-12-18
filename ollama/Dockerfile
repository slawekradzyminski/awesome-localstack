# ollama/Dockerfile
FROM ollama/ollama:0.13.2

# Declare the model as a build-arg so you can swap variants later.
ARG OLLAMA_MODEL=qwen3:4b-instruct
# Optional space-separated list of additional models to pre-pull.
# Use the qwen3:* namespace; legacy qwen:* tags will be rewritten in wait-and-pull.sh.
ARG OLLAMA_EXTRA_MODELS="qwen3:0.6b"

# Pull the model while the image is built
COPY wait-and-pull.sh /usr/local/bin/wait-and-pull.sh
RUN chmod +x /usr/local/bin/wait-and-pull.sh \
    && export OLLAMA_MODEL="${OLLAMA_MODEL}" \
    && export OLLAMA_EXTRA_MODELS="${OLLAMA_EXTRA_MODELS}" \
    && /usr/local/bin/wait-and-pull.sh
EXPOSE 11434
ENTRYPOINT ["ollama", "serve"]
