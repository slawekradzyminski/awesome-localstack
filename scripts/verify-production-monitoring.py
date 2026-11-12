#!/usr/bin/env python3
"""Contract for the lean production monitoring (phases A and B) and the local overlay.

Phase A: Grafana is gone from the server profile, its Ansible wiring, Vault
example and Makefile, while Prometheus, Alertmanager, cAdvisor, Node Exporter
and Blackbox Exporter stay.
Phase B: the host watchdog role is wired into the deploy playbook, its units
and backup OnFailure= hooks exist, the services carry Docker healthchecks and
the aitesters site is probed.
Local: monitoring is an opt-in overlay that works with both local profiles.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible"
WATCHDOG = ANSIBLE / "roles/watchdog"
failures: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def read(relative: str) -> str:
    return (ROOT / relative).read_text()


def compose(*files: str) -> dict:
    command = ["docker", "compose"]
    for filename in files:
        command.extend(("-f", filename))
    command.extend(("config", "--no-env-resolution", "--format", "json"))
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def condition(services: dict, service: str, dependency: str) -> str | None:
    return ((services[service].get("depends_on") or {}).get(dependency) or {}).get("condition")


def phase_a(server: dict) -> None:
    services = server["services"]
    require("grafana" not in services, "docker-compose.server.yml must not run Grafana")
    for kept in ("prometheus", "alertmanager", "cadvisor", "node-exporter", "blackbox-exporter"):
        require(kept in services, f"phase A keeps {kept} in docker-compose.server.yml (phase C removes it)")
    ports = services["prometheus"].get("ports", [])
    require(
        len(ports) == 1 and ports[0].get("host_ip") == "127.0.0.1" and str(ports[0].get("published")) == "9090",
        "Prometheus must publish only on 127.0.0.1:9090 for the SSH tunnel that replaces Grafana",
    )
    for relative in ("ansible/inventory/group_vars/production/main.yml",
                     "ansible/inventory/group_vars/production/vault.yml.example",
                     "ansible/roles/app/tasks/prepare.yml", "ansible/roles/app/tasks/converge.yml",
                     "ansible/roles/app/tasks/assets.yml", "ansible/roles/verify/tasks/main.yml",
                     "Makefile"):
        text = read(relative)
        for marker in ("GF_SECURITY_ADMIN_PASSWORD", "grafana_admin_password", "ansible-tunnel-grafana",
                       "/etc/grafana/"):
            require(marker not in text, f"{relative} still references {marker}")
    group_vars = read("ansible/inventory/group_vars/production/main.yml")
    copy_paths = re.search(r"^app_copy_paths:\n((?:  .*\n)+)", group_vars, re.M)
    require(copy_paths is not None and "  - grafana\n" not in copy_paths.group(1),
            "app_copy_paths must not copy grafana/ to the server")
    require("ansible-tunnel-prometheus:" in read("Makefile"), "Makefile must offer the Prometheus tunnel")
    require(not (ROOT / "grafana/server-provisioning").exists(),
            "grafana/server-provisioning belongs to the removed production Grafana")


def phase_b_compose(server: dict) -> None:
    services = server["services"]
    for service in ("backend", "aitesters-backend", "gateway", "edge", "activemq", "frontend",
                    "aitesters-frontend", "warehouse-service", "aitesters-warehouse-service",
                    "payment-service", "aitesters-payment-service", "postgres", "aitesters-postgres", "docs"):
        test = (services[service].get("healthcheck") or {}).get("test") or []
        require(len(test) > 1 and not services[service]["healthcheck"].get("disable"),
                f"{service} must have a Docker healthcheck")
    require("healthcheck" not in services["consumer"],
            "consumer is distroless (no shell): the watchdog probes it instead of a Docker healthcheck")
    for service, dependency, expected in (("edge", "gateway", "service_healthy"),
                                          ("consumer", "activemq", "service_healthy"),
                                          ("gateway", "backend", "service_healthy"),
                                          ("warehouse-service", "backend", "service_healthy"),
                                          ("payment-service", "backend", "service_healthy"),
                                          ("gateway", "aitesters-backend", "service_started"),
                                          ("backend", "activemq", "service_started")):
        require(condition(services, service, dependency) == expected,
                f"{service} must depend on {dependency} with {expected}")

    prometheus = read("prometheus/prometheus.server.yml")
    job = prometheus[prometheus.index("job_name: public_https"):]
    targets = re.findall(r"^\s+- (https://\S+)$", job, re.M)
    for url in ("https://aitesters.byst.re/login", "https://aitesters.byst.re/v3/api-docs"):
        require(url in targets, f"the public_https job must probe {url}")
    verify = read("ansible/roles/verify/tasks/main.yml")
    require(f"data.result | length) == {len(targets)}" in verify,
            f"the verify role must expect {len(targets)} public probe results")


def phase_b_watchdog(server: dict) -> None:
    playbook = read("ansible/playbooks/deploy.yml")
    markers = ["        name: swap", "        name: watchdog", "        name: postgres_backup",
               "deployment_silence_state: present", "            tasks_from: converge", "        name: verify",
               "deployment_silence_state: absent"]
    positions = [playbook.find(marker) for marker in markers]
    require(all(position >= 0 for position in positions) and positions == sorted(positions),
            "deploy.yml must install the watchdog before postgres_backup and the deployment silence")

    for relative in ("files/awesome-watchdog.py", "tasks/main.yml", "defaults/main.yml",
                     "templates/config.json.j2", "templates/awesome-watchdog.service.j2",
                     "templates/awesome-watchdog.timer.j2", "templates/awesome-watchdog-notify@.service.j2"):
        require((WATCHDOG / relative).exists(), f"watchdog role file {relative} is missing")
    if failures:
        return
    defaults = (WATCHDOG / "defaults/main.yml").read_text()
    tasks = (WATCHDOG / "tasks/main.yml").read_text()
    timer = (WATCHDOG / "templates/awesome-watchdog.timer.j2").read_text()
    service = (WATCHDOG / "templates/awesome-watchdog.service.j2").read_text()
    notify = (WATCHDOG / "templates/awesome-watchdog-notify@.service.j2").read_text()
    config = (WATCHDOG / "templates/config.json.j2").read_text()

    require("watchdog_schedule: minutely" in defaults and "OnCalendar={{ watchdog_schedule }}" in timer,
            "the watchdog timer must run every minute")
    require("{{ watchdog_script_path }} run" in service and "Type=oneshot" in service,
            "awesome-watchdog.service must run one watchdog pass")
    require("Requires=docker.service" not in service,
            "the watchdog must still run (and report) when Docker is down")
    require("notify-unit-failure %i" in notify, "the notify@ unit must report the failed unit")
    for loop_item in ("awesome-watchdog.service", "awesome-watchdog.timer", "awesome-watchdog-notify@.service"):
        require(f"    - {loop_item}\n" in tasks, f"the watchdog role must install {loop_item}")
    require("name: awesome-watchdog.timer" in tasks and "enabled: true" in tasks and "state: started" in tasks,
            "the watchdog role must enable and start the timer")
    require("alertmanager_telegram_bot_token" in defaults and "alertmanager_telegram_chat_id" in defaults,
            "the watchdog must reuse the Alertmanager Telegram Vault variables")
    require('watchdog_healthcheck_url: ""' in defaults,
            "the dead-man ping must be optional and disabled by default")
    require("watchdog_healthcheck_url:" in read("ansible/inventory/group_vars/production/vault.yml.example"),
            "vault.yml.example must document watchdog_healthcheck_url")
    require("difference(watchdog_oneshot_services)" in defaults and "app_compose_src" in defaults,
            "the watched container set must come from docker-compose.server.yml minus the one-shots")
    require("url: http://consumer:4002/actuator/health" in defaults,
            "the watchdog must probe the consumer, which cannot carry a Docker healthcheck")
    require("300 * 1024 * 1024" in read("prometheus/rules/host.yml")
            and "watchdog_memory_available_min_mib: 300" in defaults,
            "the watchdog memory threshold must match HostAbsoluteAvailableMemoryCritical")
    require('postgres_backup_root ~ "/restore-check.ok"' in config,
            "the watchdog must read the restore-check stamp the restore script writes")

    backup = ANSIBLE / "roles/postgres_backup/templates"
    for unit in ("awesome-postgres-backup.service.j2", "awesome-postgres-restore-check.service.j2"):
        require("OnFailure=awesome-watchdog-notify@%n.service" in (backup / unit).read_text(),
                f"{unit} must notify Telegram on failure")
    require('touch "${BACKUP_ROOT}/restore-check.ok"' in (backup / "postgres-restore-check.sh.j2").read_text(),
            "a successful restore check must record its stamp")

    verify = read("ansible/roles/verify/tasks/main.yml")
    require("awesome-watchdog.timer" in verify and "failed_when: verify_watchdog_timer.stdout != 'active'" in verify,
            "the verify role must check that the watchdog timer is active")
    require("      - --dry-run\n" in verify, "the verify role must dry-run the watchdog")
    present = read("ansible/roles/deployment_silence/tasks/present.yml")
    absent = read("ansible/roles/deployment_silence/tasks/absent.yml")
    require("      - maintenance\n      - start\n" in present and "deployment_silence_duration_minutes" in present,
            "the deployment silence must pause the watchdog container checks for its bounded duration")
    require("      - maintenance\n      - stop\n" in absent,
            "a successful deployment must resume the watchdog container checks")

    watched = sorted(set(server["services"]) - {"postgres-roles", "aitesters-postgres-roles"})
    require(len(watched) >= 20 and "edge" in watched, "unexpected server service set for the watchdog")


def local_overlay() -> None:
    full = compose("docker-compose.yml")["services"]
    light = compose("lightweight-docker-compose.yml")["services"]
    monitoring = ("prometheus", "grafana", "influxdb", "cadvisor", "node-exporter")
    for name in monitoring:
        require(name not in full and name not in light,
                f"{name} must come from docker-compose.monitoring.yml, not a base profile")
    for base in ("docker-compose.yml", "lightweight-docker-compose.yml"):
        services = compose(base, "docker-compose.monitoring.yml")["services"]
        for name in monitoring:
            require(name in services and services[name].get("image"), f"{base} + overlay must run {name}")
        for name in ("backend", "warehouse-service", "payment-service"):
            exposure = services[name].get("environment", {}).get("MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE", "")
            require("prometheus" in exposure.split(","), f"{base} + overlay must expose {name} metrics")
        mounts = [volume.get("target") for volume in services["grafana"].get("volumes", [])]
        require("/etc/grafana/provisioning/dashboards" in mounts, "Grafana must provision every local dashboard")
    script = read("run-docker-compose.sh")
    require("COMPOSE_FILES+=(-f docker-compose.monitoring.yml)" in script
            and '"${WITH_MONITORING:-true}" = "true"' in script,
            "run-docker-compose.sh must keep monitoring for k6 trainings by default")
    workflow = read(".github/workflows/test.yml")
    require("scripts/verify-monitoring-overlay.sh" in workflow, "CI must exercise the monitoring overlay")


def main() -> int:
    server = compose("docker-compose.server.yml")
    phase_a(server)
    phase_b_compose(server)
    phase_b_watchdog(server)
    local_overlay()
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("Lean production monitoring and local monitoring overlay contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
