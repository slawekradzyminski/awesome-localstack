# ollama/Dockerfile
FROM ollama/ollama:0.9.1

# Declare the model as a build-arg so you can swap variants later.
ARG OLLAMA_MODEL=qwen3:0.6b

# Pull the model while the image is built
COPY wait-and-pull.sh /usr/local/bin/wait-and-pull.sh
RUN chmod +x /usr/local/bin/wait-and-pull.sh \
    && export OLLAMA_MODEL=${OLLAMA_MODEL} && /usr/local/bin/wait-and-pull.sh
EXPOSE 11434
ENTRYPOINT ["ollama", "serve"]
