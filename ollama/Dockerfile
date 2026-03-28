# ollama/Dockerfile
FROM ollama/ollama:0.18.3

# Declare the model as a build-arg so you can swap variants later.
ARG OLLAMA_MODEL=qwen3.5:2b
# Optional space-separated list of additional models to pre-pull.
# Keep empty unless a fallback model is explicitly needed later.
ARG OLLAMA_EXTRA_MODELS=""

# Pull the model while the image is built
COPY wait-and-pull.sh /usr/local/bin/wait-and-pull.sh
RUN chmod +x /usr/local/bin/wait-and-pull.sh \
    && export OLLAMA_MODEL="${OLLAMA_MODEL}" \
    && export OLLAMA_EXTRA_MODELS="${OLLAMA_EXTRA_MODELS}" \
    && /usr/local/bin/wait-and-pull.sh
EXPOSE 11434
ENTRYPOINT ["ollama", "serve"]
