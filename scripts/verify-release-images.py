#!/usr/bin/env python3
"""Verify the first-party production image compatibility set."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINNED_IMAGE = re.compile(r"^[^@\s]+:[^@\s]+@sha256:[0-9a-f]{64}$")
PRODUCTION_SERVICES = (
    "backend",
    "frontend",
    "ai-learning-lab",
    "consumer",
    "ollama-mock",
)


def compose_images(*files: str) -> dict[str, str]:
    command = ["docker", "compose"]
    for filename in files:
        command.extend(("-f", filename))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    return {name: service.get("image", "") for name, service in services.items()}


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def verify_remote(image: str, failures: list[str]) -> None:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        failures.append(f"Cannot inspect {image}: {result.stderr.strip()}")
        return

    for platform in ("linux/amd64", "linux/arm64"):
        require(
            f"Platform:    {platform}" in result.stdout,
            f"{image} does not publish {platform}",
            failures,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remote",
        action="store_true",
        help="inspect registry manifests and require amd64 plus arm64",
    )
    args = parser.parse_args()

    failures: list[str] = []
    server = compose_images("docker-compose.server.yml")
    full = compose_images("docker-compose.yml")
    lightweight = compose_images("lightweight-docker-compose.yml")
    model_mock = compose_images("docker-compose.yml", "docker-compose.model-mock.yml")

    release_images: dict[str, str] = {}
    for service in PRODUCTION_SERVICES:
        image = server.get(service, "")
        require(bool(image), f"server profile is missing {service}", failures)
        require(
            bool(PINNED_IMAGE.fullmatch(image)),
            f"server service {service} must use an immutable tag@sha256 reference: {image}",
            failures,
        )
        release_images[service] = image

    require(
        full.get("consumer") == release_images["consumer"],
        "full and server profiles must use the same consumer release",
        failures,
    )
    require(
        lightweight.get("ollama-mock") == release_images["ollama-mock"],
        "lightweight and server profiles must use the same Ollama mock release",
        failures,
    )
    require(
        model_mock.get("ollama") == release_images["ollama-mock"],
        "the model-mock override must use the production Ollama mock release",
        failures,
    )

    runbook = (ROOT / "docs" / "AI_LAB_RELEASE.md").read_text()
    for service, image in release_images.items():
        require(
            image in runbook,
            f"release runbook does not record the {service} image {image}",
            failures,
        )

    if args.remote:
        for image in sorted(set(release_images.values())):
            verify_remote(image, failures)

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    mode = "local pins and remote manifests" if args.remote else "local pins"
    print(f"Verified {mode} for {len(release_images)} first-party images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
