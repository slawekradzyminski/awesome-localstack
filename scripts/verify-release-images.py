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
    "warehouse-service",
    "payment-service",
)
# docker-compose.server.yml carries this marker until payment-service 1.0.0 is
# published. It must never pass verification.
PENDING_DIGEST_MARKER = "PENDING_PAYMENT_SERVICE_DIGEST"
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


def gateway_upstreams(config: Path, variable: str) -> dict[str, str]:
    """Map each server block's first server_name to its `$<variable>_upstream`."""
    upstreams: dict[str, str] = {}
    pattern = rf"^\s*set \${variable}_upstream\s+([^\s;]+);"
    for block in re.split(r"^server \{", config.read_text(), flags=re.MULTILINE)[1:]:
        name = re.search(r"^\s*server_name\s+([^\s;]+)", block, flags=re.MULTILINE)
        upstream = re.findall(pattern, block, flags=re.MULTILINE)
        if name:
            upstreams[name.group(1)] = upstream[0] if len(upstream) == 1 else ",".join(upstream)
    return upstreams


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

    pending = sorted(
        f"{profile}:{service}"
        for profile, images in (("docker-compose.server.yml", server),
                                ("docker-compose.yml", full),
                                ("lightweight-docker-compose.yml", lightweight))
        for service, image in images.items()
        if PENDING_DIGEST_MARKER in image
    )
    require(
        not pending,
        f"PLACEHOLDER DIGEST: {', '.join(pending)} still use "
        f"@sha256:{PENDING_DIGEST_MARKER}. Publish payment-service, then replace the "
        "placeholder with its Docker Hub manifest digest in docker-compose.server.yml "
        "(payment-service and aitesters-payment-service) and pin the same tag@sha256 in "
        "docker-compose.yml and lightweight-docker-compose.yml",
        failures,
    )

    release_images: dict[str, str] = {}
    for service in PRODUCTION_SERVICES:
        image = server.get(service, "")
        require(bool(image), f"server profile is missing {service}", failures)
        if PENDING_DIGEST_MARKER not in image:
            # A placeholder is reported once above instead of as a malformed pin.
            require(
                bool(PINNED_IMAGE.fullmatch(image)),
                f"server service {service} must use an immutable tag@sha256 reference: {image}",
                failures,
            )
        release_images[service] = image

    def same_release(profile: dict[str, str], service: str) -> bool:
        image = profile.get(service, "")
        if PENDING_DIGEST_MARKER in release_images[service]:
            # Until the digest exists the other profiles must at least run the same tag.
            return image.split("@", 1)[0] == release_images[service].split("@", 1)[0]
        return image == release_images[service]

    for service in ("backend", "frontend", "consumer", "warehouse-service", "payment-service"):
        require(
            same_release(full, service),
            f"full and server profiles must use the same {service} release",
            failures,
        )
    for service in ("backend", "frontend", "ollama-mock", "warehouse-service", "payment-service"):
        require(
            same_release(lightweight, service),
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
        server.get("aitesters-warehouse-service") == release_images["warehouse-service"],
        "the aitesters warehouse-service must reuse the current warehouse-service release",
        failures,
    )
    require(
        server.get("aitesters-payment-service") == release_images["payment-service"],
        "the aitesters payment-service must reuse the current payment-service release",
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
        and not {"JWT_SECRET_KEY", "JWT_SIGNING_KEY"} & set(server_services["aitesters-backend"].get("environment", {})),
        f"sandbox must use its own runtime env file instead of the stable signing key "
        f"(sandbox files: {sandbox_env_files}, stable files: {stable_env_files})",
        failures,
    )

    sandbox_warehouse_env_files = declared_env_files("aitesters-warehouse-service")
    require(
        sandbox_warehouse_env_files == [".env.aitesters-warehouse"]
        and ".env.aitesters-warehouse" not in declared_env_files("warehouse-service")
        and not {"JWT_SECRET_KEY", "JWT_SIGNING_KEY", "WAREHOUSE_SERVICE_TOKEN"}
        & set(server_services["aitesters-warehouse-service"].get("environment", {})),
        "the sandbox warehouse-service must use its own runtime env file instead of the stable "
        f"signing key and service token (files: {sandbox_warehouse_env_files})",
        failures,
    )
    for warehouse, roles in (("warehouse-service", "postgres-roles"),
                             ("aitesters-warehouse-service", "aitesters-postgres-roles")):
        warehouse_service = server_services[warehouse]
        require(
            warehouse_service.get("environment", {}).get("SPRING_DATASOURCE_USERNAME") == "warehouse"
            and warehouse_service.get("depends_on", {}).get(roles, {}).get("condition")
            == "service_completed_successfully"
            and "JWT_SECRET_KEY" not in warehouse_service.get("environment", {}),
            f"{warehouse} must use the dedicated warehouse database role prepared by {roles} "
            "and verify tokens through the backend JWKS instead of a shared JWT secret",
            failures,
        )

    require(
        server_services["aitesters-warehouse-service"].get("environment", {}).get("BACKEND_BASE_URL")
        == "http://aitesters-backend:4001",
        "the sandbox warehouse-service must call the sandbox backend",
        failures,
    )

    payment_secrets = {"JWT_SECRET_KEY", "JWT_SIGNING_KEY", "PAYMENT_SERVICE_TOKEN",
                       "PAYMENT_WEBHOOK_SECRET", "SPRING_DATASOURCE_PASSWORD"}
    for payment, env_file, other_env_file in (
            ("payment-service", ".env.payment", ".env.aitesters-payment"),
            ("aitesters-payment-service", ".env.aitesters-payment", ".env.payment")):
        payment_env_files = declared_env_files(payment)
        require(
            payment_env_files == [env_file]
            and not payment_secrets & set(server_services[payment].get("environment", {})),
            f"{payment} must read its token, webhook secret and database password only from "
            f"{env_file} (files: {payment_env_files})",
            failures,
        )
        require(
            other_env_file not in payment_env_files,
            f"{payment} must not read the other site's {other_env_file}",
            failures,
        )
    for payment, roles, backend, database in (
            ("payment-service", "postgres-roles", "backend", "jdbc:postgresql://postgres:5432/testdb?"),
            ("aitesters-payment-service", "aitesters-postgres-roles", "aitesters-backend",
             "jdbc:postgresql://aitesters-postgres:5432/aitesters?")):
        service = server_services[payment]
        environment = service.get("environment", {})
        require(
            environment.get("SPRING_DATASOURCE_USERNAME") == "payment"
            and str(environment.get("SPRING_DATASOURCE_URL", "")).startswith(database)
            and "currentSchema=payment" in str(environment.get("SPRING_DATASOURCE_URL", ""))
            and service.get("depends_on", {}).get(roles, {}).get("condition")
            == "service_completed_successfully"
            and service.get("depends_on", {}).get(backend, {}).get("condition") == "service_healthy",
            f"{payment} must use the dedicated payment database role and schema prepared by {roles} "
            f"and start after a healthy {backend}",
            failures,
        )
        require(
            environment.get("BACKEND_BASE_URL") == f"http://{backend}:4001",
            f"{payment} must call its own site's {backend}, never the other site",
            failures,
        )
        require(
            service.get("command") == ["-Xmx64m"] and str(service.get("mem_limit")) in {"167772160", "160m"},
            f"{payment} must run the native image with -Xmx64m in 160m",
            failures,
        )

    sandbox_environment = server_services["aitesters-backend"].get("environment", {})
    sandbox_warehouse_environment = server_services["aitesters-warehouse-service"].get("environment", {})
    require(
        sandbox_environment.get("SPRING_DATASOURCE_URL") == "jdbc:postgresql://aitesters-postgres:5432/aitesters"
        and str(sandbox_warehouse_environment.get("SPRING_DATASOURCE_URL", "")).startswith(
            "jdbc:postgresql://aitesters-postgres:5432/aitesters?")
        and "aitesters-postgres" in server_services["aitesters-backend"].get("depends_on", {}),
        "the sandbox backend and warehouse-service must use the sandbox database, never the stable one",
        failures,
    )
    sandbox_template = (ROOT / "ansible" / "roles" / "app" / "templates" / "env.aitesters.j2").read_text()
    require(
        "'SPRING_DATASOURCE_PASSWORD': aitesters_postgres_password" in sandbox_template,
        "the sandbox runtime env must replace the stable database password with aitesters_postgres_password",
        failures,
    )

    gateway_config = ROOT / "nginx" / "conf.d" / "app-gateway.conf"
    warehouse_upstreams = gateway_upstreams(gateway_config, "warehouse")
    require(
        warehouse_upstreams.get("awesome.byst.re") == "http://warehouse-service:4003"
        and warehouse_upstreams.get("aitesters.byst.re") == "http://aitesters-warehouse-service:4003",
        f"each gateway host must route warehouse paths to its own warehouse-service: {warehouse_upstreams}",
        failures,
    )
    payment_upstreams = gateway_upstreams(gateway_config, "payment")
    require(
        payment_upstreams.get("awesome.byst.re") == "http://payment-service:4004"
        and payment_upstreams.get("aitesters.byst.re") == "http://aitesters-payment-service:4004",
        f"each gateway host must route payment paths to its own payment-service: {payment_upstreams}",
        failures,
    )
    for config in (gateway_config, ROOT / "nginx" / "conf.d" / "lightweight-app-gateway.conf"):
        text = config.read_text()
        blocks = len(re.findall(r"^server \{", text, flags=re.MULTILINE))
        for location in ("location = /api/v1/payments {", "location /api/v1/payments/ {",
                         "location = /api/v1/admin/payments {",
                         "location ~ ^/api/v1/orders/\\d+/payments$ {",
                         "location ^~ /payment/v3/api-docs {",
                         "location ~ ^/api/v1/orders/\\d+/(shipment|shipment/tracking|returns)$ {",
                         "location /api/v1/tracking/ {", "location /internal/ {"):
            require(
                text.count(location) == blocks,
                f"{config.name} must declare `{location}` in each of its {blocks} server blocks",
                failures,
            )

    # Since backend 3.16.0 the backend never calls payment-service: card refunds
    # travel through the event feed that payment-service polls.
    for profile_name, services, backends in (
            ("docker-compose.server.yml", server_services, ("backend", "aitesters-backend")),
            ("docker-compose.yml", compose_services("docker-compose.yml"), ("backend",)),
            ("lightweight-docker-compose.yml", compose_services("lightweight-docker-compose.yml"),
             ("backend",))):
        for backend in backends:
            require(
                "PAYMENT_BASE_URL" not in services.get(backend, {}).get("environment", {}),
                f"{profile_name} {backend} must not set PAYMENT_BASE_URL (removed in backend 3.16.0; "
                "payment-service reads card refunds from the event feed)",
                failures,
            )

    # The docs wiki is the one locally built image on the server: built from
    # docs-site/ on deploy, never pulled, small and reachable at /docs/ on every
    # gateway host.
    for profile_name, services in (("docker-compose.server.yml", server_services),
                                   ("docker-compose.yml", compose_services("docker-compose.yml")),
                                   ("lightweight-docker-compose.yml",
                                    compose_services("lightweight-docker-compose.yml"))):
        docs = services.get("docs", {})
        build = docs.get("build", {})
        require(
            docs.get("image") == "awesome-localstack/docs:local"
            and str(build.get("context", "")).rstrip("/").endswith("docs-site")
            and "repo-docs" in build.get("additional_contexts", {})
            and str(docs.get("mem_limit")) in {"33554432", "32m"},
            f"{profile_name} must build the docs wiki locally from docs-site/ "
            "(image awesome-localstack/docs:local, repo-docs context, mem_limit 32m)",
            failures,
        )
        require(
            "docs" not in services.get("gateway", {}).get("depends_on", {}),
            f"{profile_name} gateway must not depend on docs (it must start without the wiki)",
            failures,
        )
    docs_upstreams = gateway_upstreams(gateway_config, "docs")
    require(
        docs_upstreams.get("awesome.byst.re") == "http://docs:80"
        and docs_upstreams.get("aitesters.byst.re") == "http://docs:80",
        f"both gateway hosts must route /docs/ to the docs service: {docs_upstreams}",
        failures,
    )
    for config in (gateway_config, ROOT / "nginx" / "conf.d" / "lightweight-app-gateway.conf"):
        text = config.read_text()
        blocks = len(re.findall(r"^server \{", text, flags=re.MULTILINE))
        for location in ("location = /docs {", "location /docs/ {", "proxy_pass $docs_upstream;"):
            require(
                text.count(location) == blocks,
                f"{config.name} must declare `{location}` in each of its {blocks} server blocks",
                failures,
            )

    runbook = (ROOT / "docs" / "CONTAINER_RELEASES.md").read_text()
    for service, image in release_images.items():
        if PENDING_DIGEST_MARKER in image:
            continue  # already reported; the runbook records the digest once it exists
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
