#!/usr/bin/env python3
"""Run Codex-authored semantic mutants in disposable repository copies."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


LAB_DIR = Path(__file__).resolve().parent
STACK_ROOT = LAB_DIR.parents[1]
DEFAULT_MANIFEST = LAB_DIR / "manifest.json"
IGNORED_NAMES = {
    ".git",
    ".idea",
    ".next",
    "coverage",
    "dist",
    "node_modules",
    "reports",
    "target",
    "test-results",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile and test LLM-generated mutants outside the working repositories."
    )
    parser.add_argument("ids", nargs="*", help="Mutant IDs; defaults to the full manifest")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, help="Write JSON results to this path")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--timeout", type=int, default=180, help="Seconds per command")
    return parser.parse_args()


def copy_repository(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*IGNORED_NAMES),
        symlinks=True,
    )
    source_modules = source / "node_modules"
    if source_modules.is_dir():
        (destination / "node_modules").symlink_to(source_modules, target_is_directory=True)


def run_command(command: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env={**os.environ, "CI": "true"},
            check=False,
        )
        return {
            "exitCode": process.returncode,
            "durationSeconds": round(time.monotonic() - started, 3),
            "outputTail": process.stdout[-4000:],
            "timedOut": False,
        }
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return {
            "exitCode": None,
            "durationSeconds": round(time.monotonic() - started, 3),
            "outputTail": output[-4000:],
            "timedOut": True,
        }


def prepare_copy(source: Path, temporary_root: Path, label: str) -> Path:
    destination = temporary_root / label
    copy_repository(source, destination)
    return destination


def execute_baseline(mutant: dict[str, Any], source: Path, timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="llm-mutant-baseline-") as raw_root:
        checkout = prepare_copy(source, Path(raw_root), mutant["id"])
        compile_result = run_command(mutant["compile"], checkout, timeout)
        if compile_result["exitCode"] != 0:
            return {"status": "compile-failed", "compile": compile_result}
        test_result = run_command(mutant["test"], checkout, timeout)
        status = "passed" if test_result["exitCode"] == 0 else "test-failed"
        return {"status": status, "compile": compile_result, "test": test_result}


def execute_mutant(mutant: dict[str, Any], source: Path, patch: Path, timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="llm-mutant-") as raw_root:
        checkout = prepare_copy(source, Path(raw_root), mutant["id"])
        apply_result = run_command(["git", "apply", str(patch)], checkout, timeout)
        if apply_result["exitCode"] != 0:
            return {"status": "invalid-patch", "apply": apply_result}

        compile_result = run_command(mutant["compile"], checkout, timeout)
        if compile_result["timedOut"]:
            return {"status": "compile-timeout", "compile": compile_result}
        if compile_result["exitCode"] != 0:
            return {"status": "invalid-noncompiling", "compile": compile_result}

        test_result = run_command(mutant["test"], checkout, timeout)
        if test_result["timedOut"]:
            status = "test-timeout"
        elif test_result["exitCode"] == 0:
            status = "survived"
        else:
            status = "killed"
        return {"status": status, "compile": compile_result, "test": test_result}


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text())
    requested = set(args.ids)
    mutants = [
        item for item in manifest["mutants"] if not requested or item["id"] in requested
    ]
    missing = requested - {item["id"] for item in mutants}
    if missing:
        raise SystemExit(f"Unknown mutant IDs: {', '.join(sorted(missing))}")

    results: list[dict[str, Any]] = []
    for index, mutant in enumerate(mutants, start=1):
        source = (STACK_ROOT / mutant["repository"]).resolve()
        patch = (LAB_DIR / mutant["patch"]).resolve()
        if not source.is_dir():
            raise SystemExit(f"Repository does not exist: {source}")
        if not patch.is_file():
            raise SystemExit(f"Patch does not exist: {patch}")

        print(f"[{index}/{len(mutants)}] {mutant['id']}", flush=True)
        baseline = None
        if not args.skip_baseline:
            baseline = execute_baseline(mutant, source, args.timeout)
            if baseline["status"] != "passed":
                result = {**mutant, "status": "baseline-failed", "baseline": baseline}
                results.append(result)
                print(f"  -> {result['status']}", flush=True)
                continue

        execution = execute_mutant(mutant, source, patch, args.timeout)
        result = {**mutant, **execution}
        if baseline is not None:
            result["baseline"] = baseline
        results.append(result)
        print(f"  -> {result['status']}", flush=True)

    report = {
        "schemaVersion": 1,
        "manifest": str(manifest_path),
        "generationMode": manifest.get("generationMode"),
        "results": results,
        "summary": {
            status: sum(item["status"] == status for item in results)
            for status in sorted({item["status"] for item in results})
        },
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
        print(f"Results written to {output}")
    else:
        print(rendered)

    unexpected = {"baseline-failed", "compile-timeout", "invalid-noncompiling", "invalid-patch"}
    return 2 if any(item["status"] in unexpected for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
