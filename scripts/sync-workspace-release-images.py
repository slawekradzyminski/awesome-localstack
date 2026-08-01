#!/usr/bin/env python3
"""Propagate the reviewed application image set to sibling development repos."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATTERN = r"slawekradzyminski/{repository}:[^\s}}]+"


def release_images() -> dict[str, str]:
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.server.yml", "config", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    return {
        service: services[service]["image"]
        for service in ("backend", "frontend", "ollama-mock")
    }


def update_reference(path: Path, repository: str, image: str, check: bool) -> bool:
    original = path.read_text()
    updated, replacements = re.subn(
        IMAGE_PATTERN.format(repository=re.escape(repository)),
        image,
        original,
    )
    if replacements != 1:
        raise RuntimeError(
            f"Expected one {repository} reference in {path}, found {replacements}"
        )
    if updated == original:
        print(f"current: {path}")
        return False
    if check:
        print(f"stale:   {path}")
    else:
        path.write_text(updated)
        print(f"updated: {path}")
    return True


def validate_compose(repository: Path) -> None:
    subprocess.run(
        ["docker", "compose", "config", "--quiet"],
        cwd=repository,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report drift without editing")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=ROOT.parent,
        help="directory containing the sibling repositories",
    )
    args = parser.parse_args()

    images = release_images()
    targets = (
        (args.workspace_root / "test-secure-backend", "frontend", images["frontend"]),
        (args.workspace_root / "vite-react-frontend", "backend", images["backend"]),
        (args.workspace_root / "vite-react-frontend", "ollama-mock", images["ollama-mock"]),
    )

    changed = False
    touched_repositories: set[Path] = set()
    for repository, image_repository, image in targets:
        compose = repository / "docker-compose.yml"
        if not compose.is_file():
            raise FileNotFoundError(f"Missing sibling Compose file: {compose}")
        changed |= update_reference(compose, image_repository, image, args.check)
        touched_repositories.add(repository)

    if args.check and changed:
        print("Workspace development Compose references are stale", file=sys.stderr)
        return 1

    for repository in sorted(touched_repositories):
        validate_compose(repository)
    print("Workspace development Compose references match the reviewed release set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
