#!/usr/bin/env python3
"""Run unchanged, revision-pinned lesson suites against disposable local backends."""

import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.compatibility.yml")]
TARGETS = ("http://127.0.0.1:14001", "http://127.0.0.1:14002")
# These are disposable local fixtures, never credentials from a participant checkout.
FIXTURE = dict(username="slaweczek", password="slaweczek", email="slaweczek@gmail.com",
               firstName="Slawek", lastName="Slaweczek", roles=["ROLE_CLIENT"])


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def request(url, body=None, method=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, response.read()


def wait_and_seed(target):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            status, _ = request(target + "/actuator/health")
            if status == 200:
                break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    else:
        raise RuntimeError(f"Backend did not become healthy: {target}")
    status, _ = request(target + "/api/v1/users/signup", FIXTURE)
    if status != 201:
        raise RuntimeError(f"Fixture creation failed at {target}: {status}")
    # Course cart tests compare JS floating-point multiplication with exact
    # decimal server totals. Choose an exact-valued fixture; do not change
    # production arithmetic or weaken their assertions. Decimal edge cases
    # remain covered separately by backend money tests.
    _, login = request(target + "/api/v1/users/signin",
                       {"username": "admin", "password": "LocalDemoAdmin123!"})
    token = json.loads(login)["token"]
    _, products = request(target + "/api/v1/products", token=token)
    for product in json.loads(products):
        request(target + "/api/v1/products/" + str(product["id"]),
                {"price": 10}, method="PUT", token=token)


def source_digest(lesson):
    """Evidence that config wrapping did not modify course code or assertions."""
    digest = hashlib.sha256()
    for file in sorted(lesson.rglob("*")):
        relative = file.relative_to(lesson)
        if file.is_file() and "node_modules" not in relative.parts and file.suffix == ".ts":
            if file.name == "compatibility.config.ts":
                continue
            digest.update(str(relative).encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def extract_results(report):
    failures = []

    def visit(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    if test.get("status") in ("unexpected", "flaky"):
                        failures.append({"file": spec["file"], "title": spec["title"],
                                         "project": test["projectName"], "status": test["status"]})
            visit(suite.get("suites", []))

    visit(report.get("suites", []))
    return {"stats": report.get("stats", {}), "failures": failures,
            "runner_errors": len(report.get("errors", []))}


def verify_graphql_preview():
    _, login = request(TARGETS[0] + "/api/v1/users/signin",
                       {"username": FIXTURE["username"], "password": FIXTURE["password"]})
    token = json.loads(login)["token"]
    query = {"query": "{ products(limit: 2) { items { id name price } } cart { totalItems } }"}
    responses = []
    for target in (TARGETS[0], "http://127.0.0.1:14081"):
        status, body = request(target + "/api/v1/graphql", query, token=token)
        payload = json.loads(body)
        if status != 200 or payload.get("errors") or not payload.get("data", {}).get("products"):
            raise RuntimeError(f"GraphQL preview failed at {target}")
        responses.append(payload)
        try:
            request(target + "/api/v1/graphql", query)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
        else:
            raise RuntimeError(f"GraphQL accepted unauthenticated access at {target}")
    if responses[0] != responses[1]:
        raise RuntimeError("Direct and proxied GraphQL responses differ")
    return {"direct": TARGETS[0], "gateway": "http://127.0.0.1:14081",
            "authenticated_query": "passed", "unauthenticated_query": "401"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-repo", type=Path, default=ROOT.parent / "ai-testers-api")
    parser.add_argument("--ref", default="HEAD", help="Course git revision to freeze")
    parser.add_argument("--lessons", nargs="+", default=["l20"], help="Lesson names, or all")
    parser.add_argument("--output", type=Path, required=True, help="New private report directory")
    parser.add_argument("--graphql-preview", action="store_true",
                        help="Verify candidate GraphQL through the backend and existing nginx route")
    parser.add_argument("--grpc-preview", action="store_true",
                        help="Enable native gRPC on the ordinary candidate backend while running unchanged REST lessons")
    args = parser.parse_args()
    if args.grpc_preview:
        candidate = os.environ.get("COMPAT_BACKEND_IMAGE")
        if not candidate:
            parser.error("--grpc-preview requires COMPAT_BACKEND_IMAGE")
        os.environ["GRPC_BACKEND_IMAGE"] = candidate
        os.environ["GRPC_HOST_PORT"] = "14991"
        COMPOSE.extend(["-f", str(ROOT / "docker-compose.grpc.yml")])
    if args.graphql_preview:
        COMPOSE.extend(["--profile", "graphql-preview"])
    os.umask(0o077)
    lock = (ROOT / "outputs").resolve()
    lock.mkdir(exist_ok=True)
    lock_file = (lock / "course-compatibility.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RuntimeError("Another compatibility runner owns the disposable stack") from error
    if output(COMPOSE + ["ps", "-q"]):
        raise RuntimeError("Compatibility stack already exists; stop it explicitly before running")
    report_dir = args.output.resolve()
    report_dir.mkdir(parents=True, exist_ok=False)
    revision = output(["git", "-C", str(args.course_repo), "rev-parse", args.ref + "^{commit}"])
    summary = {"course_revision": revision, "targets": TARGETS, "lessons": [],
               "graphql_preview_checks": args.graphql_preview,
               "grpc_preview_checks": args.grpc_preview,
               "fixture_product_price": "10.00",
               "course_dirty": bool(output(["git", "-C", str(args.course_repo), "status", "--porcelain"])),
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    summary["repositories"] = {}
    for name in ("awesome-localstack", "test-secure-backend", "vite-react-frontend", "ai-testers-api"):
        repo = args.course_repo if name == "ai-testers-api" else ROOT.parent / name
        if (repo / ".git").exists():
            summary["repositories"][name] = {
                "head": output(["git", "-C", str(repo), "rev-parse", "HEAD"]),
                "status": output(["git", "-C", str(repo), "status", "--porcelain"])}
    summary_path = report_dir / "summary.json"
    exit_code = 0
    # Never read the caller's .env, .env.local or Playwright settings.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("API_", "PLAYWRIGHT_", "PW_", "NODE_OPTIONS", "DOTENV_"))}
    env.update(API_BASE_URL=TARGETS[0], API_ADMIN_BASE_URL=TARGETS[1],
               API_LOGIN_USERNAME=FIXTURE["username"], API_LOGIN_PASSWORD=FIXTURE["password"],
               API_USER_EMAIL=FIXTURE["email"], API_ADMIN_USERNAME="admin",
               API_ADMIN_PASSWORD="LocalDemoAdmin123!", CI="1")
    try:
        run(COMPOSE + ["config", "--quiet"])
        with tempfile.TemporaryDirectory(prefix="awesome-course-") as temp:
            snapshot = Path(temp)
            archive = subprocess.check_output(["git", "-C", str(args.course_repo), "archive", revision])
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(snapshot, filter="data")
            for file in snapshot.rglob(".env*"):
                if file.is_file():
                    file.unlink()
            available = sorted((p for p in snapshot.glob("l*") if re.fullmatch(r"l\d+", p.name)),
                               key=lambda p: int(p.name[1:]))
            summary["inventory"] = [{"lesson": p.name, "spec_files": len(list(p.rglob("*.spec.ts"))),
                                      "runnable": (p / "playwright.config.ts").is_file()}
                                     for p in available]
            names = [p.name for p in available] if args.lessons == ["all"] else args.lessons
            if not set(names) <= {p.name for p in available}:
                raise ValueError("Unknown lesson name")
            for name in names:
                lesson = snapshot / name
                if not (lesson / "playwright.config.ts").is_file():
                    summary["lessons"].append({"lesson": name, "status": "scaffolding-no-config"})
                    continue
                print(f"Running unchanged {name} at {revision[:12]}", flush=True)
                lesson_report = report_dir / name
                lesson_report.mkdir()
                with (lesson_report / "setup.log").open("w") as log:
                    run(COMPOSE + ["up", "-d", "--force-recreate"], stdout=log, stderr=subprocess.STDOUT)
                    for target in TARGETS:
                        wait_and_seed(target)
                    run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                        cwd=lesson, env=env, stdout=log, stderr=subprocess.STDOUT)
                before = source_digest(lesson)
                if args.grpc_preview:
                    with socket.create_connection(("127.0.0.1", 14991), timeout=5):
                        summary["grpc_listener"] = "127.0.0.1:14991"
                if args.graphql_preview:
                    summary["graphql_preview"] = verify_graphql_preview()
                # Import the untouched lesson config, check its effective targets after
                # dotenv, and change only reporting/execution settings. Never replace URLs
                # silently: a public/default URL is a hard failure.
                (lesson / "compatibility.config.ts").write_text('''
import original from './playwright.config';
const allowed = new Set(['http://127.0.0.1:14001', 'http://127.0.0.1:14002']);
for (const project of original.projects ?? [{}]) {
  const url = project.use?.baseURL ?? original.use?.baseURL;
  if (!url || !allowed.has(url)) throw new Error('Non-local compatibility target: ' + url);
}
export default { ...original, retries: 0, workers: 1,
  use: { ...original.use, trace: 'off' },
  reporter: [['list'], ['json', { outputFile: process.env.COMPAT_REPORT }]],
};
''')
                result_file = lesson_report / "playwright.json"
                with (lesson_report / "run.log").open("w") as log:
                    result = subprocess.run(
                        ["npm", "test", "--", "--config=compatibility.config.ts"], cwd=lesson,
                        env={**env, "COMPAT_REPORT": str(result_file)},
                        stdout=log, stderr=subprocess.STDOUT)
                if before != source_digest(lesson):
                    raise RuntimeError(f"Course TypeScript sources changed during {name}")
                details = extract_results(json.loads(result_file.read_text())) if result_file.exists() else {}
                summary["lessons"].append({"lesson": name, "exit_code": result.returncode,
                                            "source_sha256": before, **details})
                stats = details.get("stats", {})
                failed = (result.returncode != 0 or not stats.get("expected")
                          or any(stats.get(key, 0) for key in ("unexpected", "flaky", "skipped"))
                          or details.get("runner_errors", 0))
                exit_code = max(exit_code, int(bool(failed)))
                summary["containers"] = [json.loads(line) for line in
                                         output(COMPOSE + ["ps", "--format", "json"]).splitlines()]
                for index, target in enumerate(TARGETS):
                    _, spec = request(target + "/v3/api-docs")
                    (lesson_report / f"openapi-{index}.json").write_bytes(spec)
                summary_path.write_text(json.dumps(summary, indent=2) + "\n")
                print(f"{name}: {details.get('stats', {})}", flush=True)
        if not any("exit_code" in lesson for lesson in summary["lessons"]):
            exit_code = 1
        summary["status"] = "passed" if exit_code == 0 else "failed"
    finally:
        summary.setdefault("status", "incomplete")
        summary["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        run(COMPOSE + ["down", "--remove-orphans"])
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
