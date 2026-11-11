#!/usr/bin/env python3
"""Awesome Server host watchdog.

A systemd timer runs `awesome-watchdog run` every minute. Each run inspects the
Compose containers, OOM sources, disk, memory and backup freshness, compares the
result with the previous run (state file) and sends one Telegram message per
new problem, recovery or event through the bot and chat that Alertmanager uses.
A persisting problem is reported once; its recovery is reported once.

Only the Python standard library is used, so the script runs on the host's
python3 without extra packages and keeps no resident process.

Commands:
  run [--dry-run]            run all checks (dry-run: print, send nothing, keep state)
  notify-unit-failure UNIT   Telegram message for a failed systemd unit (OnFailure=)
  maintenance start|stop|status
  diagnose                   show which OOM and backup sources are readable
  test-message               send one Telegram message to prove delivery
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CONFIG = "/etc/awesome-watchdog/config.json"
TELEGRAM_LIMIT = 3900
CONTAINER_PREFIX = "container:"
HTTP_PREFIX = "http:"

DEFAULTS = {
    "host_label": socket.gethostname(),
    "compose_project": "awesome-server",
    "expected_services": [],
    "oneshot_services": [],
    "ignored_services": [],
    "state_file": "/var/lib/awesome-watchdog/state.json",
    "maintenance_file": "/run/awesome-watchdog.maintenance",
    "maintenance_max_minutes": 30,
    "confirm_runs": {"missing": 2, "not_running": 2, "unhealthy": 3, "http": 2},
    "restart_window_minutes": 10,
    "disk_paths": ["/"],
    "disk_used_percent_thresholds": [85, 90],
    "inode_used_percent_max": 92,
    "memory_available_min_mib": 300,
    "memory_confirm_runs": 10,
    "meminfo_path": "/proc/meminfo",
    "backup_enabled": True,
    "backup_dir": "/var/backups/awesome-localstack/postgres/daily",
    "backup_glob_suffix": ".sql.gz.enc",
    "backup_max_age_hours": 26,
    "restore_check_stamp": "/var/backups/awesome-localstack/postgres/restore-check.ok",
    "restore_check_max_age_days": 8,
    "cgroup_root": "/sys/fs/cgroup",
    "proc_root": "/proc",
    "internal_http_checks": [],
    "repeat_hours": 0,
    "docker_bin": "docker",
    "command_timeout_seconds": 20,
    "telegram_api_url": "https://api.telegram.org",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "healthcheck_url": "",
}


class CheckError(Exception):
    """A check could not run (for example, the Docker daemon is unreachable)."""


def log(message: str) -> None:
    print(message, flush=True)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        loaded = json.load(stream)
    config = dict(DEFAULTS)
    config.update(loaded)
    confirm = dict(DEFAULTS["confirm_runs"])
    confirm.update(loaded.get("confirm_runs", {}))
    config["confirm_runs"] = confirm
    return config


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as stream:
            state = json.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        log(f"State file {path} is unreadable ({error}); starting from an empty state")
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path: str, state: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".state-", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# ---------------------------------------------------------------------------
# External commands
# ---------------------------------------------------------------------------

def docker(config: dict, *args: str) -> str:
    command = [config["docker_bin"], *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=config["command_timeout_seconds"],
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CheckError(f"`docker {args[0]}` failed: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise CheckError(f"`docker {args[0]}` exited {result.returncode}: {detail[-1] if detail else ''}")
    return result.stdout


# ---------------------------------------------------------------------------
# Checks. Each returns observations {key: (message, confirm_runs)} and events
# [(key, message)]. Observations are conditions that hold now; events happened
# once since the previous run.
# ---------------------------------------------------------------------------

def inspect_containers(config: dict) -> dict:
    ids = docker(
        config,
        "ps", "--all", "--quiet", "--no-trunc",
        "--filter", f"label=com.docker.compose.project={config['compose_project']}",
    ).split()
    if not ids:
        return {}
    inspected = json.loads(docker(config, "inspect", *ids))
    by_service: dict = {}
    for container in inspected:
        labels = (container.get("Config") or {}).get("Labels") or {}
        service = labels.get("com.docker.compose.service")
        if not service or labels.get("com.docker.compose.oneoff", "False") == "True":
            continue
        current = by_service.get(service)
        # Prefer a running container, then the most recently created one.
        rank = (container["State"].get("Status") == "running", container.get("Created", ""))
        if current is None or rank > (current["State"].get("Status") == "running", current.get("Created", "")):
            by_service[service] = container
    return by_service


def describe_exit(container: dict) -> str:
    state = container["State"]
    parts = [f"exit code {state.get('ExitCode', '?')}"]
    if state.get("OOMKilled"):
        parts.append("OOM-killed")
    parts.append(f"restarts {container.get('RestartCount', 0)}")
    return ", ".join(parts)


def last_health_output(container: dict) -> str:
    health = container["State"].get("Health") or {}
    entries = health.get("Log") or []
    if not entries:
        return ""
    output = " ".join(str(entries[-1].get("Output", "")).split())
    return f": {output[:200]}" if output else ""


def check_containers(config: dict, state: dict, containers: dict, now: float) -> tuple[dict, list]:
    observations: dict = {}
    confirm = config["confirm_runs"]
    ignored = set(config["ignored_services"])
    tracked = state.setdefault("containers", {})
    window = config["restart_window_minutes"] * 60

    for service in sorted(set(config["expected_services"]) - ignored):
        container = containers.get(service)
        key = f"{CONTAINER_PREFIX}{service}"
        if container is None:
            observations[f"{key}:missing"] = (
                f"Container {service} is missing from project {config['compose_project']}",
                confirm["missing"],
            )
            continue
        status = container["State"].get("Status", "unknown")
        health = (container["State"].get("Health") or {}).get("Status")
        if status == "restarting":
            observations[f"{key}:not-running"] = (
                f"Container {service} is restarting ({describe_exit(container)})",
                confirm["not_running"],
            )
        elif status != "running":
            observations[f"{key}:not-running"] = (
                f"Container {service} is {status} ({describe_exit(container)})",
                confirm["not_running"],
            )
        elif health == "unhealthy":
            observations[f"{key}:unhealthy"] = (
                f"Container {service} is unhealthy{last_health_output(container)}",
                confirm["unhealthy"],
            )

        restart_count = int(container.get("RestartCount", 0))
        previous = tracked.get(service) or {}
        last_increase = previous.get("last_restart_increase")
        if previous.get("id") == container["Id"] and restart_count > int(previous.get("restart_count", 0)):
            last_increase = now
        tracked[service] = {
            "id": container["Id"],
            "restart_count": restart_count,
            "last_restart_increase": last_increase,
        }
        if last_increase is not None and now - last_increase < window:
            observations[f"{key}:restarts"] = (
                f"Container {service} restarted in the last {config['restart_window_minutes']} minutes "
                f"(restart count {restart_count})",
                1,
            )

    for service in sorted(set(config["oneshot_services"]) - ignored):
        container = containers.get(service)
        if container is None:
            continue
        state_info = container["State"]
        if state_info.get("Status") == "exited" and int(state_info.get("ExitCode", 0)) != 0:
            observations[f"{CONTAINER_PREFIX}{service}:failed"] = (
                f"One-shot {service} exited with code {state_info.get('ExitCode')}",
                1,
            )

    for service in list(tracked):
        if service not in containers:
            tracked.pop(service, None)
    return observations, []


def check_internal_http(config: dict, containers: dict) -> dict:
    observations: dict = {}
    for check in config["internal_http_checks"]:
        via = containers.get(check["via"])
        if via is None or via["State"].get("Status") != "running":
            continue  # the container check reports the missing or stopped probe container
        try:
            docker(config, "exec", via["Id"], "curl", "--fail", "--silent", "--show-error",
                   "--output", "/dev/null", "--max-time", "5", check["url"])
        except CheckError as error:
            observations[f"{HTTP_PREFIX}{check['name']}"] = (
                f"{check['name']} health check {check['url']} failed: {error}",
                config["confirm_runs"]["http"],
            )
    return observations


def read_memory_events(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as stream:
            values = {}
            for line in stream:
                name, _, value = line.partition(" ")
                if value.strip().isdigit():
                    values[name] = int(value)
            return values
    except OSError:
        return None


def container_cgroup_events(config: dict, container: dict) -> str | None:
    """Locate a container's cgroup v2 memory.events through its main PID."""
    pid = container["State"].get("Pid") or 0
    if pid <= 0:
        return None
    try:
        with open(os.path.join(config["proc_root"], str(pid), "cgroup"), encoding="utf-8") as stream:
            for line in stream:
                hierarchy, _, path = line.strip().partition("::")
                if hierarchy == "0" and path:
                    return os.path.join(config["cgroup_root"], path.lstrip("/"), "memory.events")
    except OSError:
        return None
    return None


def check_oom(config: dict, state: dict, containers: dict, now: float) -> list:
    """OOM kills from Docker events, the VPS-root cgroup and container cgroups."""
    events: list = []
    oom_containers: set = set()

    # Fractional timestamps keep consecutive windows adjacent without overlap.
    since = float(state.get("last_events_until") or now - 120)
    until = now
    if until > since:
        output = docker(
            config,
            "events", "--since", f"{since:.3f}", "--until", f"{until:.3f}",
            "--filter", "type=container", "--filter", "event=oom",
            "--format", "{{json .}}",
        )
        for line in output.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            actor = event.get("Actor") or {}
            attributes = actor.get("Attributes") or {}
            container_id = actor.get("ID") or event.get("id", "")
            oom_containers.add(container_id)
            name = attributes.get("com.docker.compose.service") or attributes.get("name", container_id[:12])
            events.append((
                f"oom:docker:{container_id}:{event.get('timeNano', event.get('time'))}",
                f"OOM kill in container {name} (Docker event)",
            ))
    state["last_events_until"] = until

    counters = state.setdefault("oom_counters", {})
    root_events = read_memory_events(os.path.join(config["cgroup_root"], "memory.events"))
    if root_events is not None and "oom_kill" in root_events:
        previous = counters.get("root")
        current = root_events["oom_kill"]
        if previous is not None and current > previous:
            events.append((
                f"oom:cgroup-root:{current}",
                f"Kernel OOM killer ran {current - previous} time(s) in the VPS cgroup "
                f"(memory.events oom_kill={current})",
            ))
        counters["root"] = current

    seen_ids = set()
    for service, container in containers.items():
        path = container_cgroup_events(config, container)
        if not path:
            continue
        values = read_memory_events(path)
        if values is None or "oom_kill" not in values:
            continue
        cid = container["Id"]
        seen_ids.add(cid)
        previous = counters.get(cid)
        if previous is not None and values["oom_kill"] > previous and cid not in oom_containers:
            events.append((
                f"oom:cgroup:{cid}:{values['oom_kill']}",
                f"OOM kill inside container {service} (cgroup oom_kill={values['oom_kill']})",
            ))
        counters[cid] = values["oom_kill"]
    for key in list(counters):
        if key != "root" and key not in seen_ids:
            counters.pop(key)
    return events


def check_disk(config: dict) -> dict:
    observations: dict = {}
    for path in config["disk_paths"]:
        try:
            stats = os.statvfs(path)
        except OSError as error:
            raise CheckError(f"statvfs({path}) failed: {error}") from error
        used = stats.f_blocks - stats.f_bfree
        usable = used + stats.f_bavail
        percent = 100.0 * used / usable if usable else 0.0
        for threshold in sorted(config["disk_used_percent_thresholds"]):
            if percent >= threshold:
                observations[f"disk:{path}:{threshold}"] = (
                    f"Disk {path} is {percent:.1f}% full (threshold {threshold}%, "
                    f"{stats.f_bavail * stats.f_frsize / 1024 ** 3:.1f} GiB available)",
                    1,
                )
        if stats.f_files:
            inode_percent = 100.0 * (stats.f_files - stats.f_ffree) / stats.f_files
            if inode_percent >= config["inode_used_percent_max"]:
                observations[f"inodes:{path}"] = (
                    f"Filesystem {path} uses {inode_percent:.1f}% of its inodes "
                    f"(threshold {config['inode_used_percent_max']}%)",
                    1,
                )
    return observations


def check_memory(config: dict) -> dict:
    try:
        with open(config["meminfo_path"], encoding="utf-8") as stream:
            meminfo = {line.split(":")[0]: line.split()[1] for line in stream if ":" in line}
    except OSError as error:
        raise CheckError(f"cannot read {config['meminfo_path']}: {error}") from error
    available_mib = int(meminfo.get("MemAvailable", 0)) / 1024
    if available_mib < config["memory_available_min_mib"]:
        return {"memory:available": (
            f"Available memory is {available_mib:.0f} MiB (below {config['memory_available_min_mib']} MiB "
            f"for {config['memory_confirm_runs']} consecutive checks)",
            config["memory_confirm_runs"],
        )}
    return {}


def newest_backup(config: dict) -> float | None:
    directory = config["backup_dir"]
    newest = None
    for entry in os.scandir(directory):
        if entry.is_file() and entry.name.endswith(config["backup_glob_suffix"]):
            mtime = entry.stat().st_mtime
            newest = mtime if newest is None or mtime > newest else newest
    return newest


def check_backups(config: dict, state: dict, now: float) -> dict:
    if not config["backup_enabled"]:
        return {}
    observations: dict = {}
    try:
        newest = newest_backup(config)
    except OSError as error:
        return {"backup:unreadable": (f"Backup directory {config['backup_dir']} is unreadable: {error}", 1)}
    max_age = config["backup_max_age_hours"] * 3600
    if newest is None:
        observations["backup:stale"] = (f"No PostgreSQL backup archive in {config['backup_dir']}", 1)
    elif now - newest > max_age:
        observations["backup:stale"] = (
            f"Newest PostgreSQL backup is {(now - newest) / 3600:.1f} h old "
            f"(limit {config['backup_max_age_hours']} h)",
            1,
        )

    restore_max_age = config["restore_check_max_age_days"] * 86400
    try:
        stamp = os.stat(config["restore_check_stamp"]).st_mtime
    except OSError:
        stamp = None
    first_run = state.get("first_run", now)
    if stamp is None and now - first_run > restore_max_age:
        observations["restore-check:stale"] = (
            f"No successful backup restore check recorded in {config['restore_check_max_age_days']} days",
            1,
        )
    elif stamp is not None and now - stamp > restore_max_age:
        observations["restore-check:stale"] = (
            f"Last successful backup restore check is {(now - stamp) / 86400:.1f} days old "
            f"(limit {config['restore_check_max_age_days']} days)",
            1,
        )
    return observations


# ---------------------------------------------------------------------------
# Maintenance, notification and run orchestration
# ---------------------------------------------------------------------------

def maintenance_active(config: dict, now: float) -> bool:
    path = config["maintenance_file"]
    try:
        with open(path, encoding="utf-8") as stream:
            expiry = float(stream.read().strip() or 0)
        mtime = os.stat(path).st_mtime
    except (OSError, ValueError):
        return False
    hard_limit = mtime + config["maintenance_max_minutes"] * 60
    return now < min(expiry, hard_limit)


def telegram_send(config: dict, text: str) -> None:
    token = config["telegram_bot_token"]
    chat = str(config["telegram_chat_id"])
    if not token or not chat:
        raise CheckError("Telegram bot token or chat id is not configured")
    if len(text) > TELEGRAM_LIMIT:
        text = text[:TELEGRAM_LIMIT] + "\n[truncated]"
    data = urllib.parse.urlencode({
        "chat_id": chat,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    url = f"{config['telegram_api_url'].rstrip('/')}/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as response:
            body = json.loads(response.read().decode() or "{}")
    except (urllib.error.URLError, OSError, ValueError) as error:
        # Never print the URL: it contains the bot token.
        raise CheckError(f"Telegram delivery failed: {type(error).__name__}") from error
    if not body.get("ok"):
        raise CheckError(f"Telegram rejected the message: {body.get('description', 'unknown error')}")


def ping_healthcheck(config: dict, failed: bool, summary: str) -> None:
    url = config["healthcheck_url"]
    if not url:
        return
    target = url.rstrip("/") + ("/fail" if failed else "")
    try:
        request = urllib.request.Request(target, data=summary.encode()[:10000])
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (urllib.error.URLError, OSError) as error:
        log(f"Dead-man ping failed: {type(error).__name__}")


def format_message(config: dict, lines: list) -> str:
    return f"Awesome Server watchdog ({config['host_label']})\n" + "\n".join(lines)


def reconcile(config: dict, state: dict, observations: dict, frozen_prefixes: tuple, now: float) -> tuple[list, list, list]:
    """Return (outgoing lines, keys to mark notified, keys to delete after delivery)."""
    problems = state.setdefault("problems", {})
    lines: list = []
    notify_keys: list = []
    resolve_keys: list = []
    repeat = config["repeat_hours"] * 3600

    for key, (message, confirm) in sorted(observations.items()):
        problem = problems.setdefault(key, {"first_seen": now, "seen_runs": 0, "notified_at": None})
        problem["message"] = message
        problem["seen_runs"] = int(problem.get("seen_runs", 0)) + 1
        notified_at = problem.get("notified_at")
        if notified_at is None and problem["seen_runs"] >= confirm:
            lines.append(f"PROBLEM: {message}")
            notify_keys.append(key)
        elif notified_at is not None and repeat and now - notified_at >= repeat:
            lines.append(f"STILL FAILING: {message}")
            notify_keys.append(key)

    for key in sorted(problems):
        if key in observations or key.startswith(frozen_prefixes):
            continue
        problem = problems[key]
        if problem.get("notified_at") is not None:
            lines.append(f"RESOLVED: {problem.get('message', key)}")
            resolve_keys.append(key)
        else:
            problems.pop(key)
    return lines, notify_keys, resolve_keys


def run(config: dict, dry_run: bool) -> int:
    now = time.time()
    state = load_state(config["state_file"])
    state.setdefault("first_run", now)
    observations: dict = {}
    events: list = []
    check_errors: list = []
    in_maintenance = maintenance_active(config, now)
    frozen: tuple = (CONTAINER_PREFIX, HTTP_PREFIX) if in_maintenance else ()

    containers: dict = {}
    try:
        containers = inspect_containers(config)
    except (CheckError, ValueError) as error:
        check_errors.append(("docker", str(error)))

    def guarded(name, function, *args):
        try:
            return function(*args)
        except (CheckError, OSError, ValueError, KeyError) as error:
            check_errors.append((name, f"{type(error).__name__}: {error}"))
            return None

    if not any(name == "docker" for name, _ in check_errors):
        if not in_maintenance:
            result = guarded("containers", check_containers, config, state, containers, now)
            if result:
                observations.update(result[0])
            observations.update(guarded("internal-http", check_internal_http, config, containers) or {})
        events.extend(guarded("oom", check_oom, config, state, containers, now) or [])
    observations.update(guarded("disk", check_disk, config) or {})
    observations.update(guarded("memory", check_memory, config) or {})
    observations.update(guarded("backups", check_backups, config, state, now) or {})

    for name, error in check_errors:
        observations[f"watchdog:{name}"] = (f"Watchdog check '{name}' could not run: {error}", 2)

    pending_events = state.get("pending_events", [])
    event_lines = [f"EVENT: {message}" for _, message in pending_events + events]
    lines, notify_keys, resolve_keys = reconcile(config, state, observations, frozen, now)
    lines = event_lines + lines

    if dry_run:
        log(f"Dry run at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}"
            f"{' (maintenance active: container checks paused)' if in_maintenance else ''}")
        log(f"Containers found: {len(containers)}; expected: {len(config['expected_services'])}")
        for key, (message, confirm) in sorted(observations.items()):
            log(f"  condition {key}: {message} (confirm after {confirm} run(s))")
        for line in lines:
            log(f"  would send: {line}")
        if not lines and not observations:
            log("  all checks passed")
        for name, error in check_errors:
            log(f"  check error {name}: {error}")
        return 1 if check_errors else 0

    delivery_failed = False
    if lines:
        try:
            telegram_send(config, format_message(config, lines))
            log("Sent: " + " | ".join(lines))
        except CheckError as error:
            delivery_failed = True
            log(str(error))
    problems = state.setdefault("problems", {})
    if delivery_failed:
        # Retry next run: problems stay un-notified and events stay pending.
        state["pending_events"] = (pending_events + events)[-20:]
    else:
        state["pending_events"] = []
        for key in notify_keys:
            problems[key]["notified_at"] = now
        for key in resolve_keys:
            problems.pop(key, None)
    state["last_run"] = now
    save_state(config["state_file"], state)

    failed = delivery_failed or bool(check_errors)
    summary = "; ".join(f"{name}: {error}" for name, error in check_errors) or "ok"
    ping_healthcheck(config, failed, summary)
    if not lines:
        log(f"OK: {len(problems)} known problem(s), {len(containers)} container(s)"
            f"{', maintenance active' if in_maintenance else ''}")
    return 1 if delivery_failed else 0


def notify_unit_failure(config: dict, unit: str) -> int:
    details = []
    try:
        shown = subprocess.run(
            ["systemctl", "show", unit, "--property=Result,ExecMainStatus,ActiveEnterTimestamp"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip().splitlines()
        details.append(", ".join(shown))
        journal = subprocess.run(
            ["journalctl", "--unit", unit, "--lines", "8", "--no-pager", "--output", "cat"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
        if journal:
            details.append("Last log lines:\n" + journal[-1500:])
    except (OSError, subprocess.TimeoutExpired) as error:
        details.append(f"(details unavailable: {error})")
    lines = [f"FAILED: systemd unit {unit} failed"] + details
    try:
        telegram_send(config, format_message(config, lines))
    except CheckError as error:
        log(str(error))
        return 1
    log(f"Reported failure of {unit}")
    return 0


def maintenance(config: dict, action: str, minutes: int) -> int:
    path = config["maintenance_file"]
    if action == "start":
        minutes = min(minutes, config["maintenance_max_minutes"])
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(str(int(time.time() + minutes * 60)))
        log(f"Container checks paused for {minutes} minutes ({path})")
    elif action == "stop":
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        log("Container checks resumed")
    else:
        log("maintenance active" if maintenance_active(config, time.time()) else "maintenance inactive")
    return 0


def diagnose(config: dict) -> int:
    root = os.path.join(config["cgroup_root"], "memory.events")
    root_events = read_memory_events(root)
    log(f"VPS-root cgroup {root}: "
        f"{'readable, oom_kill=' + str(root_events.get('oom_kill')) if root_events else 'NOT readable'}")
    try:
        containers = inspect_containers(config)
        log(f"Docker: {len(containers)} container(s) in project {config['compose_project']}")
        readable = [service for service, container in containers.items()
                    if (path := container_cgroup_events(config, container)) and read_memory_events(path)]
        log(f"Container cgroup memory.events readable for {len(readable)} of {len(containers)} container(s)")
        output = docker(config, "events", "--since", str(int(time.time() - 60)), "--until",
                        str(int(time.time())), "--filter", "event=oom", "--format", "{{json .}}")
        log(f"Docker events API: readable ({len(output.splitlines())} OOM event(s) in the last minute)")
    except CheckError as error:
        log(f"Docker: {error}")
    for name, path in (("backup directory", config["backup_dir"]),
                       ("restore-check stamp", config["restore_check_stamp"])):
        log(f"{name} {path}: {'present' if os.path.exists(path) else 'absent'}")
    log(f"Dead-man ping: {'configured' if config['healthcheck_url'] else 'disabled'}")
    log(f"Maintenance: {'active' if maintenance_active(config, time.time()) else 'inactive'}")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Awesome Server host watchdog")
    parser.add_argument("--config", default=os.environ.get("AWESOME_WATCHDOG_CONFIG", DEFAULT_CONFIG))
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--dry-run", action="store_true")
    unit_parser = commands.add_parser("notify-unit-failure")
    unit_parser.add_argument("unit")
    maintenance_parser = commands.add_parser("maintenance")
    maintenance_parser.add_argument("action", choices=["start", "stop", "status"])
    maintenance_parser.add_argument("--minutes", type=int, default=15)
    commands.add_parser("diagnose")
    commands.add_parser("test-message")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, ValueError) as error:
        log(f"Cannot load configuration {args.config}: {error}")
        return 2

    if args.command == "run":
        return run(config, args.dry_run)
    if args.command == "notify-unit-failure":
        return notify_unit_failure(config, args.unit)
    if args.command == "maintenance":
        return maintenance(config, args.action, args.minutes)
    if args.command == "diagnose":
        return diagnose(config)
    try:
        telegram_send(config, format_message(config, ["TEST: watchdog Telegram delivery works"]))
    except CheckError as error:
        log(str(error))
        return 1
    log("Test message sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
