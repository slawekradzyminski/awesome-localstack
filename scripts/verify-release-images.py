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
    "consumer",
    "ollama-mock",
)
SERVICE_HEADER = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
SERVICE_KEY = re.compile(r"^    ([A-Za-z0-9_-]+):\s*$")
ENV_FILE_PATH = re.compile(r"^      - path: (\S+)\s*$")
ENV_FILE_SHORT = re.compile(r"^      - (\.?\S+)\s*$")


def compose_services(*files: str) -> dict[str, dict]:
    command = ["docker", "compose"]
    for filename in files:
        command.extend(("-f", filename))
    command.extend(("config", "--no-env-resolution", "--format", "json"))
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["services"]


def declared_env_files(service: str, compose_file: Path = ROOT / "docker-compose.server.yml") -> list[str]:
    # Read declarations from the Compose source. Rendered `config` output omits
    # optional env_file entries on some Compose versions even when placeholders exist.
    files: list[str] = []
    in_service = False
    in_env_file = False
    for line in compose_file.read_text().splitlines():
        service_match = SERVICE_HEADER.match(line)
        if service_match:
            if in_service:
                break
            in_service = service_match.group(1) == service
            in_env_file = False
            continue
        if not in_service:
            continue
        key_match = SERVICE_KEY.match(line)
        if key_match:
            in_env_file = key_match.group(1) == "env_file"
            continue
        if not in_env_file or line.lstrip().startswith("#"):
            continue
        path_match = ENV_FILE_PATH.match(line)
        if path_match:
            files.append(Path(path_match.group(1)).name)
            continue
        short_match = ENV_FILE_SHORT.match(line)
        if short_match:
            files.append(Path(short_match.group(1)).name)
    return files


def compose_images(*files: str) -> dict[str, str]:
    return {name: service.get("image", "") for name, service in compose_services(*files).items()}


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

    for service in ("backend", "frontend", "consumer"):
        require(
            full.get(service) == release_images[service],
            f"full and server profiles must use the same {service} release",
            failures,
        )
    for service in ("backend", "frontend", "ollama-mock"):
        require(
            lightweight.get(service) == release_images[service],
            f"lightweight and server profiles must use the same {service} release",
            failures,
        )
    require(
        server.get("aitesters-backend") == release_images["backend"],
        "the aitesters backend must reuse the current backend release",
        failures,
    )
    require(
        server.get("aitesters-frontend") == release_images["frontend"],
        "the aitesters frontend must reuse the current frontend release",
        failures,
    )
    require(
        model_mock.get("ollama") == release_images["ollama-mock"],
        "the model-mock override must use the production Ollama mock release",
        failures,
    )

    server_services = compose_services("docker-compose.server.yml")
    for service, port in (("backend", "9091"), ("aitesters-backend", "9092")):
        config = server_services[service]
        native_ports = [entry for entry in config.get("ports", []) if entry.get("target") == 9091]
        require(
            len(native_ports) == 1 and native_ports[0].get("host_ip") == "127.0.0.1"
            and str(native_ports[0].get("published")) == port,
            f"{service} native gRPC must publish only on 127.0.0.1:{port}",
            failures,
        )
        environment = config.get("environment", {})
        require(
            {"graphql", "grpc"} <= set(environment.get("SPRING_PROFILES_INCLUDE", "").split(","))
            and environment.get("GRPC_REFLECTION_ENABLED") == "false",
            f"{service} must include GraphQL and gRPC with reflection disabled",
            failures,
        )

    for base_file in ("lightweight-docker-compose.yml", "docker-compose.yml"):
        base_services = compose_services(base_file)
        grpc_services = compose_services(base_file, "docker-compose.grpc.yml")
        base_backend = base_services["backend"]
        grpc_backend = grpc_services["backend"]
        native_ports = [entry for entry in grpc_backend.get("ports", []) if entry.get("target") == 9091]
        require(
            grpc_backend.get("image") == base_backend.get("image"),
            f"{base_file} gRPC override must inherit the pinned backend image",
            failures,
        )
        require(
            len(native_ports) == 1 and native_ports[0].get("host_ip") == "127.0.0.1",
            f"{base_file} gRPC override must publish only on host loopback",
            failures,
        )
        environment = grpc_backend.get("environment", {})
        require(
            {"graphql", "grpc"} <= set(environment.get("SPRING_PROFILES_INCLUDE", "").split(","))
            and environment.get("GRPC_REFLECTION_ENABLED") == "false",
            f"{base_file} gRPC override must enable both protocols with reflection disabled",
            failures,
        )

    sandbox_env_files = declared_env_files("aitesters-backend")
    stable_env_files = declared_env_files("backend")
    require(
        sandbox_env_files == [".env.aitesters"]
        and ".env.aitesters" not in stable_env_files
        and "JWT_SECRET_KEY" not in server_services["aitesters-backend"].get("environment", {}),
        f"sandbox must use its own runtime env file instead of the stable signing key "
        f"(sandbox files: {sandbox_env_files}, stable files: {stable_env_files})",
        failures,
    )

    runbook = (ROOT / "docs" / "CONTAINER_RELEASES.md").read_text()
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
