# Ollama Setup

This directory contains configuration for running Ollama with the llama3.2:1b model in our Docker environment.

## Current Implementation

We're using a custom image `slawekradzyminski/ollama-1b:1.0` which has the llama3.2:1b model pre-downloaded. This approach:
- Avoids network downloads during container startup
- Reduces initial setup time
- Ensures model consistency across deployments

## Technical Details

### Model Loading Process

Even with pre-downloaded models, Ollama performs these steps on container startup:

1. System memory check and allocation (~0.1s)
2. CPU backend loading (~0.1s)
3. Model initialization and memory mapping (~5s)
   - Loading meta data and tensors
   - Initializing context
   - Setting up KV cache

This process takes approximately 5-6 seconds and cannot be pre-cached due to the nature of how LLMs work with memory.

### Memory Usage

The llama3.2:1b model requires:
- Total model size: ~1.22 GiB
- Runtime memory: ~2.1 GiB
- KV cache: 256 MiB

## Alternative Approaches

### 1. Runtime Model Pull (Previous Approach)

Previously, we used a health check to pull the model:

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -f http://ollama:11434/api/pull -d '{\"model\":\"llama3.2:1b\"}' || exit 1"]
  interval: 30s
  timeout: 1200s
  retries: 3
  start_period: 10s
```

Drawbacks:
- Required curl in the container
- Added complexity to health checks
- Potential network issues during startup

### 2. Custom Image with Pre-downloaded Model (Current Approach)

Benefits:
- Model is baked into the image
- No network downloads needed at runtime
- Simpler container configuration

## Important Notes

1. **Startup Time**: The ~5s model loading time is unavoidable as it's required for memory initialization
2. **Memory Usage**: Ensure your host has at least 3GB of available memory
3. **Volume Persistence**: If you mount a volume at `/root/.ollama`, any additional models pulled will persist across restarts

## References

- [Ollama Docker Issue Discussion](https://stackoverflow.com/questions/78232178/ollama-in-docker-pulls-models-via-interactive-shell-but-not-via-run-command-in-t)
- [Ollama Official Documentation](https://github.com/ollama/ollama)
