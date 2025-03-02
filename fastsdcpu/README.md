# FastSDCPU Docker Image

## Overview

This repository provides a Docker setup for running FastSDCPU, a CPU-based implementation of Stable Diffusion. The container includes all necessary dependencies and is configured to expose an API for generating images.

## Features

- Runs FastSDCPU inside a Docker container based on Ubuntu 22.04
- Includes dependencies such as Python, FFmpeg, and Git
- Exposes an API on port 8000 for image generation
- Persistent model storage using Docker volumes

## Building the Docker Image

To build the Docker image, use the following command:

```bash
docker build -t fastsdcpu:latest .
```

## Running the Container

Run the container with limited resources (optional) and volume mappings:

```bash
docker run -it --rm \
    --memory=4g --memory-swap=4g --cpus=2 \
    -p 8000:8000 \
    -v fastsdcpu_models:/app/lora_models \
    -v fastsdcpu_controlnet_models:/app/controlnet_models \
    -v fastsdcpu_cache:/root/.cache/huggingface \
    fastsdcpu:latest
```

This command:

- Maps the API to localhost:8000
- Mounts model directories for persistence
- Limits memory usage to 4GB and CPU cores to 2

## Generating an Image

Once the API is running, use curl to generate an image:

```bash
curl -X POST "http://localhost:8000/api/generate" \
     -H "Content-Type: application/json" \
     -d '{
          "prompt": "A simple landscape",
          "negative_prompt": "",
          "diffusion_task": "text_to_image",
          "image_width": 256,
          "image_height": 256,
          "inference_steps": 1,
          "guidance_scale": 1.0,
          "use_openvino": true,
          "openvino_lcm_model_id": "rupeshs/sd-turbo-openvino",
          "use_safety_checker": false,
          "token_merging": 0,
          "number_of_images": 1
     }' -o output.json

```

## Downloading the Image

Once the request is complete, extract the generated image URL from response.json and download it:

```bash
IMAGE_URL=$(jq -r '.image_url' response.json)
curl -o generated_image.png "$IMAGE_URL"
```

## License

This project follows the licensing terms of the FastSDCPU repository.

