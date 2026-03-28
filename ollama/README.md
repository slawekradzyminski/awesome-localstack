# Ollama Setup

This directory contains configuration for running Ollama with the `qwen3.5:2b` model pre-pulled into a custom image.

## Current Implementation

- Uses Ollama with `qwen3.5:2b` cached during the image build (model page: [link](https://ollama.com/library/qwen3.5:2b)).
- Avoids model downloads at container start and keeps deployments consistent.

## Building and Pushing

```bash
# Build with the default model (qwen3.5:2b)
docker build -t slawekradzyminski/ollama-qwen35-2b:0.18.3 .

# Build with explicit args (optional overrides)
docker build \
  --build-arg OLLAMA_MODEL=qwen3.5:2b \
  --build-arg OLLAMA_EXTRA_MODELS="" \
  -t slawekradzyminski/ollama-qwen35-2b:0.18.3 .

# Push to Docker Hub
docker push slawekradzyminski/ollama-qwen35-2b:0.18.3
```

## Running the Container

```bash
docker run -d --name ollama \
  -p 11434:11434 \
  -v ollama-cache:/root/.ollama \
  slawekradzyminski/ollama-qwen35-2b:0.18.3
```

## Querying the Model

### CLI (inside container)
```bash
docker exec -it ollama ollama run qwen3.5:2b
```

### HTTP API
```bash
curl -s http://localhost:11434/api/chat \
  -d '{
        "model":"qwen3.5:2b",
        "messages":[
          {"role":"user","content":"Define entropy in two sentences."}
        ]
      }'
```

## Notes

1. Startup still performs a short initialization (memory checks, tensor mapping) even with the model cached.
2. Mount `/root/.ollama` to persist models pulled later.

## References

- [Ollama Official Documentation](https://github.com/ollama/ollama)
- [Qwen 3.5 2B model page](https://ollama.com/library/qwen3.5:2b)
