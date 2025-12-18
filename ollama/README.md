# Ollama Setup

This directory contains configuration for running Ollama with the `qwen3:4b-instruct` model pre-pulled into a custom image and `qwen3:0.6b` added for lightweight thinking tests.

## Current Implementation

- Uses Ollama with `qwen3:4b-instruct` cached during the image build (model page: [link](https://ollama.com/library/qwen3:4b-instruct)).
- Also pre-pulls `qwen3:0.6b` for lighter experimentation (model page: [link](https://ollama.com/library/qwen3:0.6b)).
- Avoids model downloads at container start and keeps deployments consistent.

## Building and Pushing

```bash
# Build with the default models (qwen3:4b-instruct + qwen3:0.6b)
docker build -t slawekradzyminski/qwen3:4b-instruct .

# Build with explicit args (optional overrides)
docker build \
  --build-arg OLLAMA_MODEL=qwen3:4b-instruct \
  --build-arg OLLAMA_EXTRA_MODELS="qwen3:0.6b" \
  -t slawekradzyminski/qwen3:4b-instruct .

# Push to Docker Hub
docker push slawekradzyminski/qwen3:4b-instruct
```

## Running the Container

```bash
docker run -d --name ollama \
  -p 11434:11434 \
  -v ollama-cache:/root/.ollama \
  slawekradzyminski/qwen3:4b-instruct
```

## Querying the Model

### CLI (inside container)
```bash
docker exec -it ollama ollama run qwen3:4b-instruct
# Lightweight thinking test
docker exec -it ollama ollama run qwen3:0.6b
```

### HTTP API
```bash
curl -s http://localhost:11434/api/chat \
  -d '{
        "model":"qwen3:4b-instruct",
        "messages":[
          {"role":"user","content":"Define entropy in two sentences."}
        ]
      }'

# Query the lighter model
curl -s http://localhost:11434/api/chat \
  -d '{
        "model":"qwen3:0.6b",
        "messages":[
          {"role":"user","content":"Summarize entropy in one sentence."}
        ]
      }'
```

## Notes

1. Startup still performs a short initialization (memory checks, tensor mapping) even with the model cached.
2. Mount `/root/.ollama` to persist models pulled later.

## References

- [Ollama Official Documentation](https://github.com/ollama/ollama)
- [Qwen3 4B Instruct model page](https://ollama.com/library/qwen3:4b-instruct)
- [Qwen3 0.6B model page](https://ollama.com/library/qwen3:0.6b)
