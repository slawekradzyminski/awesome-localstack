#!/usr/bin/env python3
"""Correlation ID contract for the nginx gateways and the server services.

Static checks (default, no Docker):
  * every server block of every gateway config logs JSON with the request id,
    trace id, status, upstream and timings, echoes X-Request-Id to the client
    and hides an upstream copy of it;
  * every proxied location passes X-Request-Id and traceparent upstream;
  * the validate-or-generate maps exist with the contract's regexes;
  * the Spring services of docker-compose.server.yml (both domains) log ECS JSON.

--routing additionally starts the pinned nginx image with stub upstreams and
proves that ids are generated, preserved when valid, replaced when invalid,
passed to every kind of upstream (backend, warehouse, payment, notification, docs, frontend,
the aitesters server block, and edge -> gateway), echoed once to the client,
and written to the JSON access log.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF_DIR = ROOT / "nginx" / "conf.d"
GATEWAY_CONFIGS = {
    "app-gateway.conf": 2,
    "lightweight-app-gateway.conf": 1,
    "edge-gateway.conf": 1,
}
ECS_SERVICES = (
    "backend",
    "aitesters-backend",
    "warehouse-service",
    "aitesters-warehouse-service",
    "payment-service",
    "aitesters-payment-service",
    "notification-service",
    "aitesters-notification-service",
)
LOG_FIELDS = (
    "request_id",
    "trace_id",
    "status",
    "upstream",
    "request_time",
    "upstream_response_time",
)
REQUEST_ID_REGEX = '"~^[A-Za-z0-9._-]{1,128}$"'
TRACEPARENT_REGEX = '"~^00-(?!0{32})[0-9a-f]{32}-(?!0{16})[0-9a-f]{16}-[0-9a-f]{2}$"'

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
                     for line in text.splitlines())


def blocks(text: str, keyword: str) -> list[str]:
    """Return the bodies of top-level-or-nested blocks opened by `keyword ... {`."""
    found = []
    pattern = re.compile(r"(?m)^\s*" + re.escape(keyword) + r"\b[^{;]*\{")
    for match in pattern.finditer(text):
        depth, index = 1, match.end()
        while depth and index < len(text):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        found.append(text[match.end():index - 1])
    return found


def directive(body: str, name: str) -> list[str]:
    return re.findall(r"(?m)^\s*" + re.escape(name) + r"\s+([^;]+);", body)


def static_checks() -> list[str]:
    errors: list[str] = []
    for name, expected_servers in GATEWAY_CONFIGS.items():
        text = strip_comments((CONF_DIR / name).read_text())
        if REQUEST_ID_REGEX not in text:
            errors.append(f"{name}: X-Request-Id validation map is missing")
        if TRACEPARENT_REGEX not in text:
            errors.append(f"{name}: traceparent validation map (non-zero ids) is missing")
        if "map $request_id $corr_generated_traceparent" not in text:
            errors.append(f"{name}: traceparent generation from $request_id is missing")
        formats = {}
        for match in re.finditer(r"log_format\s+(\S+)\s+escape=json\s+([^;]+);", text):
            formats[match.group(1)] = match.group(2)
        if not formats:
            errors.append(f"{name}: no log_format with escape=json")
        for fmt, body in formats.items():
            for field in LOG_FIELDS:
                if f'"{field}"' not in body:
                    errors.append(f"{name}: log_format {fmt} lacks {field}")
        servers = blocks(text, "server")
        if len(servers) != expected_servers:
            errors.append(f"{name}: expected {expected_servers} server blocks, found {len(servers)}")
        for number, server in enumerate(servers, 1):
            label = f"{name} server #{number}"
            server_level = server
            for location in blocks(server, "location"):
                server_level = server_level.replace(location, "")
            logs = directive(server_level, "access_log")
            if not any(log.split()[-1] in formats for log in logs):
                errors.append(f"{label}: access_log does not use a JSON log_format")
            if "X-Request-Id $corr_request_id always" not in " ".join(directive(server_level, "add_header")):
                errors.append(f"{label}: X-Request-Id is not added to responses")
            if "X-Request-Id" not in directive(server_level, "proxy_hide_header"):
                errors.append(f"{label}: an upstream X-Request-Id is not hidden (duplicate header)")
            for location in blocks(server, "location"):
                if not directive(location, "proxy_pass"):
                    if directive(location, "add_header"):
                        errors.append(f"{label}: a location's add_header drops X-Request-Id")
                    continue
                headers = directive(location, "proxy_set_header")
                if "X-Request-Id $corr_request_id" not in headers:
                    errors.append(f"{label}: location without X-Request-Id: {location.strip()[:60]!r}")
                if "traceparent $corr_traceparent" not in headers:
                    errors.append(f"{label}: location without traceparent: {location.strip()[:60]!r}")
                if directive(location, "add_header"):
                    errors.append(f"{label}: a proxied location's add_header drops X-Request-Id")

    compose = (ROOT / "docker-compose.server.yml").read_text()
    for service in ECS_SERVICES:
        match = re.search(r"(?ms)^  " + re.escape(service) + r":\n(.*?)(?=^  \S)", compose)
        if not match:
            errors.append(f"docker-compose.server.yml: service {service} not found")
        elif not re.search(r"(?m)^      LOGGING_STRUCTURED_FORMAT_CONSOLE: ecs$", match.group(1)):
            errors.append(f"docker-compose.server.yml: {service} does not set LOGGING_STRUCTURED_FORMAT_CONSOLE=ecs")
    return errors


# --- routing test -----------------------------------------------------------

def nginx_image() -> str:
    match = re.search(r"image: (nginx:\S+)", (ROOT / "docker-compose.server.yml").read_text())
    if not match:
        raise SystemExit("pinned nginx image not found in docker-compose.server.yml")
    return match.group(1)


STUB_CONFIG = """
server {{
  listen 80 default_server;
  listen 4001;
  listen 4003;
  listen 4004;
  listen 4005;
  location / {{
    default_type text/plain;
    # Like a Spring service that already echoes its own X-Request-Id.
    add_header X-Request-Id "from-upstream-{name}" always;
    return 200 "upstream={name}:$server_port\\nrid=$http_x_request_id\\ntp=$http_traceparent\\n";
  }}
}}
"""


def docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


class Fetch:
    def __init__(self, status: int, headers, body: str):
        self.status = status
        self.request_ids = headers.get_all("X-Request-Id") or []
        self.body = dict(line.split("=", 1) for line in body.splitlines() if "=" in line)


def fetch(port: str, path: str, headers: dict[str, str] | None = None) -> Fetch:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return Fetch(response.status, response.headers, response.read().decode())
    except urllib.error.HTTPError as error:
        return Fetch(error.code, error.headers, error.read().decode())


def wait_for(port: str) -> None:
    for _ in range(40):
        try:
            fetch(port, "/images/missing")
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"nginx on port {port} did not start")


def routing_test() -> list[str]:
    errors: list[str] = []
    image = nginx_image()
    suffix = str(int(time.time() * 1000))
    network = f"corr-test-{suffix}"
    containers: list[str] = []
    tmp = tempfile.TemporaryDirectory()
    tmpdir = Path(tmp.name)

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    def run(name: str, config: Path, aliases: list[str], publish: bool, conf_name: str = "default.conf") -> str:
        container = f"corr-test-{name}-{suffix}"
        args = ["run", "--detach", "--rm", "--name", container, "--network", network]
        for alias in aliases:
            args += ["--network-alias", alias]
        args += ["--volume", f"{config}:/etc/nginx/conf.d/{conf_name}:ro",
                 "--volume", f"{CONF_DIR / 'header-buffers.conf'}:/etc/nginx/conf.d/header-buffers.conf:ro"]
        if publish:
            args += ["--publish", "127.0.0.1::80"]
        docker(*args, image)
        containers.append(container)
        if publish:
            return docker("port", container, "80/tcp").splitlines()[0].rsplit(":", 1)[1]
        return ""

    try:
        docker("network", "create", network)
        for stub, aliases in {
            "main": ["backend", "frontend", "warehouse-service", "payment-service",
                     "notification-service", "docs"],
            "sandbox": ["aitesters-backend", "aitesters-frontend", "aitesters-warehouse-service",
                        "aitesters-payment-service", "aitesters-notification-service"],
        }.items():
            path = tmpdir / f"stub-{stub}.conf"
            path.write_text(STUB_CONFIG.format(name=stub))
            run(f"stub-{stub}", path, aliases, publish=False)

        app = run("app", CONF_DIR / "app-gateway.conf", ["gateway"], publish=True)
        light = run("light", CONF_DIR / "lightweight-app-gateway.conf", ["light-gateway"], publish=True)
        edge_config = tmpdir / "edge.conf"
        edge_config.write_text((CONF_DIR / "edge-gateway.conf").read_text()
                               .replace("http://127.0.0.1:8080", "http://gateway:80"))
        edge = run("edge", edge_config, [], publish=True)
        for port in (app, light, edge):
            wait_for(port)

        awesome = {"Host": "awesome.byst.re"}
        sandbox = {"Host": "aitesters.byst.re"}
        routes = [
            (app, awesome, "/api/v1/products", "main:4001"),
            (app, awesome, "/api/v1/ws-traffic", "main:4001"),
            (app, awesome, "/api/v1/warehouse/shipments", "main:4003"),
            (app, awesome, "/api/v1/orders/7/shipment/tracking", "main:4003"),
            (app, awesome, "/api/v1/payments", "main:4004"),
            (app, awesome, "/api/v1/orders/7/payments", "main:4004"),
            (app, awesome, "/payment/v3/api-docs", "main:4004"),
            (app, awesome, "/api/v1/orders/7/shipments", "main:4003"),
            (app, awesome, "/api/v1/webhooks", "main:4005"),
            (app, awesome, "/api/v1/webhooks/3/deliveries", "main:4005"),
            (app, awesome, "/api/v1/webhook-inboxes/tok/requests", "main:4005"),
            (app, awesome, "/api/v1/admin/webhooks", "main:4005"),
            (app, awesome, "/api/v1/notifications/emails", "main:4005"),
            (app, awesome, "/api/v1/local/notifications/outbox", "main:4005"),
            (app, awesome, "/notification/v3/api-docs", "main:4005"),
            (app, awesome, "/api/v1/local/email/outbox", "main:4001"),
            (app, awesome, "/docs/", "main:80"),
            (app, awesome, "/login", "main:80"),
            (app, sandbox, "/api/v1/products", "sandbox:4001"),
            (app, sandbox, "/api/v1/warehouse/shipments", "sandbox:4003"),
            (app, sandbox, "/api/v1/payments", "sandbox:4004"),
            (app, sandbox, "/api/v1/webhook-inboxes", "sandbox:4005"),
            (app, sandbox, "/api/v1/local/notifications/outbox", "sandbox:4005"),
            (app, sandbox, "/api/v1/orders/7/shipments", "sandbox:4003"),
            (app, sandbox, "/login", "sandbox:80"),
            (light, {}, "/api/v1/products", "main:4001"),
            (light, {}, "/api/v1/tracking/X1", "main:4003"),
            (light, {}, "/api/v1/admin/payments", "main:4004"),
            (light, {}, "/api/v1/orders/7/shipments", "main:4003"),
            (light, {}, "/api/v1/webhooks/1", "main:4005"),
            (light, {}, "/api/v1/notifications/emails?page=0", "main:4005"),
            (light, {}, "/notification/v3/api-docs", "main:4005"),
            (light, {}, "/api/v1/users/me/email-events", "main:4001"),
            (light, {}, "/login", "main:80"),
            (edge, awesome, "/api/v1/products", "main:4001"),
            (edge, sandbox, "/api/v1/payments", "sandbox:4004"),
            (edge, awesome, "/api/v1/webhooks", "main:4005"),
        ]
        valid_tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        for port, host, path, upstream in routes:
            label = f"port {port} {host.get('Host', 'localhost')}{path}"
            # 1. Generated when absent.
            result = fetch(port, path, host)
            check(result.body.get("upstream") == upstream,
                  f"{label}: routed to {result.body.get('upstream')}, expected {upstream}")
            rid = result.body.get("rid", "")
            check(bool(HEX32.match(rid)), f"{label}: generated X-Request-Id {rid!r} is not $request_id")
            check(result.body.get("tp") == f"00-{rid}-{rid[16:]}-01",
                  f"{label}: generated traceparent {result.body.get('tp')!r} does not derive from {rid}")
            check(result.request_ids == [rid],
                  f"{label}: response X-Request-Id {result.request_ids} != [{rid}]")
            # 2. Preserved when valid.
            result = fetch(port, path, {**host, "X-Request-Id": "client-req.42_A", "traceparent": valid_tp})
            check(result.body.get("rid") == "client-req.42_A", f"{label}: valid X-Request-Id was not kept")
            check(result.body.get("tp") == valid_tp, f"{label}: valid traceparent was not kept")
            check(result.request_ids == ["client-req.42_A"],
                  f"{label}: valid id not echoed once: {result.request_ids}")

        # 3. Replaced when invalid (one route per config is enough: maps are shared).
        invalid_ids = ["", "has space", "semi;colon", "x" * 129, "ünïcode"]
        invalid_tps = [
            "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
            "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
            "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01",
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-extra",
            "garbage",
        ]
        for port, host in ((app, awesome), (light, {}), (edge, awesome)):
            for bad_id, bad_tp in zip(invalid_ids + invalid_ids[:1], invalid_tps):
                headers = {**host, "traceparent": bad_tp}
                if bad_id:
                    headers["X-Request-Id"] = bad_id.encode("utf-8").decode("latin-1")
                result = fetch(port, "/api/v1/products", headers)
                rid = result.body.get("rid", "")
                check(bool(HEX32.match(rid)), f"port {port}: invalid X-Request-Id {bad_id!r} kept as {rid!r}")
                check(result.body.get("tp") == f"00-{rid}-{rid[16:]}-01",
                      f"port {port}: invalid traceparent {bad_tp!r} not regenerated: {result.body.get('tp')!r}")
                check(result.request_ids == [rid], f"port {port}: replaced id not echoed: {result.request_ids}")

        # 4. Local responses (no upstream) still carry the id.
        result = fetch(app, "/internal/v1/events", awesome)
        check(result.status == 404 and len(result.request_ids) == 1 and HEX32.match(result.request_ids[0]),
              f"/internal/ 404 lacks X-Request-Id: {result.status} {result.request_ids}")

        # 4b. Unknown API paths answer 404 JSON from the gateway itself instead of
        # falling through to the SPA, on every server block (X-25).
        for port, host in ((app, awesome), (app, sandbox), (light, {}), (edge, awesome)):
            for path in ("/api", "/api/", "/api/v2/users", "/api/nope/deeper?x=1"):
                label = f"port {port} {host.get('Host', 'localhost')}{path}"
                request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=host)
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        status, headers, body = response.status, response.headers, response.read().decode()
                except urllib.error.HTTPError as error:
                    status, headers, body = error.code, error.headers, error.read().decode()
                check(status == 404, f"{label}: status {status}, expected 404")
                check(headers.get("Content-Type", "").startswith("application/json"),
                      f"{label}: Content-Type {headers.get('Content-Type')!r}")
                check(body == '{"message":"Not found"}', f"{label}: body {body!r}")
                check(len(headers.get_all("X-Request-Id") or []) == 1, f"{label}: X-Request-Id missing")
        for port, host in ((app, awesome), (light, {})):
            result = fetch(port, "/apiary", host)
            check(result.body.get("upstream") == "main:80", f"/apiary did not reach the SPA: {result.body}")

        # 5. JSON access log line for a known request.
        fetch(app, "/api/v1/products", {**awesome, "X-Request-Id": "log-probe-1", "traceparent": valid_tp})
        time.sleep(0.5)
        app_container = next(c for c in containers if "-app-" in c)
        # nginx's access log is stdout, exactly what `docker compose logs` shows.
        lines = [line for line in docker("logs", app_container).splitlines() if "log-probe-1" in line]
        check(bool(lines), "no access log line for X-Request-Id log-probe-1")
        if lines:
            entry = json.loads(lines[0])
            check(entry.get("request_id") == "log-probe-1", f"log request_id: {entry}")
            check(entry.get("trace_id") == "4bf92f3577b34da6a3ce929d0e0e4736", f"log trace_id: {entry}")
            check(entry.get("status") == 200, f"log status: {entry}")
            check(entry.get("upstream", "").endswith(":4001"), f"log upstream: {entry}")
            check(isinstance(entry.get("request_time"), (int, float)), f"log request_time: {entry}")
            check(entry.get("upstream_response_time") not in ("", "-"), f"log upstream_response_time: {entry}")
        if not errors:
            print(f"Routing test: {len(routes)} routes x (generated, preserved) + "
                  f"{3 * len(invalid_tps)} invalid-id cases + access log: OK")
    finally:
        if errors:
            for container in containers:
                print(f"--- {container}", file=sys.stderr)
                subprocess.run(["docker", "logs", "--tail", "20", container])
        for container in containers:
            docker("stop", container, check=False)
        docker("network", "rm", network, check=False)
        tmp.cleanup()
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--routing", action="store_true",
                        help="also run the Docker stub-upstream routing test")
    args = parser.parse_args()
    errors = static_checks()
    if not errors:
        print("Static correlation contract: OK "
              f"({', '.join(GATEWAY_CONFIGS)}; ECS logging for {len(ECS_SERVICES)} services)")
    if args.routing and not errors:
        errors += routing_test()
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
