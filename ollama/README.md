# Ollama Setup

This directory contains configuration for running Ollama with the Qwen model in our Docker environment.

## Current Implementation

We're using a custom image with the Qwen model pre-downloaded. This approach:
- Avoids network downloads during container startup
- Reduces initial setup time
- Ensures model consistency across deployments

## Technical Details

### Model Loading Process

Even with pre-downloaded models, Ollama performs these steps on container startup:

1. System memory check and allocation (~0.1s)
2. CPU backend loading (~0.1s)
3. Model initialization and memory mapping (~3s)
   - Loading meta data and tensors
   - Initializing context
   - Setting up KV cache

This process takes approximately 3-4 seconds and cannot be pre-cached due to the nature of how LLMs work with memory.

### Memory Usage

The Qwen model (0.6B variant) requires:
- Total model size: 523 MB (Q4_0)
- Runtime memory: ~1 GiB
- First-load latency: ~3s

*Note: Measurements are based on M2-Max; expect ±10% variation on x86/GPU hosts.

## Model Variants

The setup supports multiple Qwen model sizes:
- qwen3:0.6b (default, recommended for most use cases)
- qwen3:1.7b
- qwen3:4b
- qwen3:8b

To use a different size, build with:
```bash
docker build --build-arg OLLAMA_MODEL=qwen3:1.7b -t myorg/ollama-qwen3:1.7b .
```

## Usage

### Building the Image
```bash
docker build -t myorg/ollama-qwen3:0.6b .
```

### Running the Container
```bash
docker run -d --name ollama-qwen \
           -p 11434:11434 \
           -v ollama-cache:/root/.ollama \
           myorg/ollama-qwen3:0.6b
```

### Querying the Model

#### CLI (inside container)
```bash
docker exec -it ollama-qwen ollama run qwen3:0.6b
```

#### HTTP API
```bash
curl -s http://localhost:11434/api/chat \
  -d '{
        "model":"qwen3:0.6b",
        "messages":[
          {"role":"user","content":"Define entropy in two sentences. /think"}
        ]
      }'
```

## Important Notes

1. **Startup Time**: The ~3s model loading time is unavoidable as it's required for memory initialization
2. **Memory Usage**: Ensure your host has at least 2GB of available memory for the 0.6B model
3. **Volume Persistence**: If you mount a volume at `/root/.ollama`, any additional models pulled will persist across restarts
4. **Thinking Mode**: Qwen 3 supports `/think` and `/no_think` instruction tags for controlling response generation

## References

- [Ollama Official Documentation](https://github.com/ollama/ollama)
- [Qwen Model Documentation](https://huggingface.co/Qwen)
