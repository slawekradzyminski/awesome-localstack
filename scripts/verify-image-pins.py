#!/usr/bin/env python3
"""Require immutable references for every remotely pulled repository image."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINNED_IMAGE = re.compile(r"^[^@\s]+:[^@\s]+@sha256:[0-9a-f]{64}$")
COMPOSE_PROFILES = (
    ("docker-compose.yml",),
    ("docker-compose.yml", "docker-compose.model-mock.yml"),
    ("lightweight-docker-compose.yml",),
    ("docker-compose.server.yml",),
)


def resolved_services(files: tuple[str, ...]) -> dict[str, dict[str, object]]:
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
    return json.loads(result.stdout)["services"]


def main() -> int:
    failures: list[str] = []

    for files in COMPOSE_PROFILES:
        profile = "+".join(files)
        for service, config in resolved_services(files).items():
            image = str(config.get("image", ""))
            local_build = bool(config.get("build")) and image.endswith(":local")
            if not local_build and not PINNED_IMAGE.fullmatch(image):
                failures.append(
                    f"{profile} service {service} is not pinned by digest: {image}"
                )

    dockerfile = ROOT / "Dockerfile"
    for line_number, line in enumerate(dockerfile.read_text().splitlines(), start=1):
        if not line.startswith("FROM "):
            continue
        tokens = line.split()
        image = tokens[1]
        if image.startswith("--platform="):
            image = tokens[2]
        if not PINNED_IMAGE.fullmatch(image):
            failures.append(f"Dockerfile:{line_number} is not pinned by digest: {image}")

    workflow_image = re.compile(r"^\s+image:\s+(\S+)\s*$")
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line_number, line in enumerate(workflow.read_text().splitlines(), start=1):
            match = workflow_image.match(line)
            if match and not PINNED_IMAGE.fullmatch(match.group(1)):
                failures.append(
                    f"{workflow.relative_to(ROOT)}:{line_number} is not pinned by digest: "
                    f"{match.group(1)}"
                )

    inventory = (
        ROOT / "ansible/inventory/group_vars/production/main.yml"
    ).read_text()
    restore_match = re.search(r"^postgres_restore_image:\s*(\S+)$", inventory, re.M)
    restore_image = restore_match.group(1) if restore_match else ""
    if not PINNED_IMAGE.fullmatch(restore_image):
        failures.append(f"postgres_restore_image is not pinned by digest: {restore_image}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    print("Verified immutable image pins for Compose, CI, Dockerfile, and restore tooling")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
