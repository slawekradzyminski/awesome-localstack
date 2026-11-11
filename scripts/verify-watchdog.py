#!/usr/bin/env python3
"""Behaviour tests for the host watchdog (ansible/roles/watchdog/files/awesome-watchdog.py).

The watchdog runs against a fake `docker` CLI (fixture-driven), fake
`systemctl`/`journalctl`, fake /proc and cgroup trees and a local HTTP server
standing in for both the Telegram Bot API and the dead-man ping endpoint. No
real Docker daemon, network access or secrets are needed.

Run: python3 scripts/verify-watchdog.py [-v]
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "ansible/roles/watchdog/files/awesome-watchdog.py"
TOKEN = "123456:TEST-TOKEN"

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
fixture = json.load(open(os.environ["FAKE_DOCKER_FIXTURE"]))
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
if fixture.get("daemon_down"):
    print("Cannot connect to the Docker daemon", file=sys.stderr)
    sys.exit(1)
command = sys.argv[1]
containers = fixture.get("containers", [])
if command == "ps":
    print("\n".join(c["Id"] for c in containers))
elif command == "inspect":
    wanted = set(sys.argv[2:])
    print(json.dumps([c for c in containers if c["Id"] in wanted]))
elif command == "events":
    for event in fixture.get("events", []):
        print(json.dumps(event))
elif command == "exec":
    if sys.argv[-1] in fixture.get("exec_fail", []):
        print("curl: (22) The requested URL returned error: 503", file=sys.stderr)
        sys.exit(22)
else:
    sys.exit(f"unexpected docker command {command}")
'''

FAKE_SYSTEMCTL = "#!/bin/sh\nprintf 'Result=exit-code\\nExecMainStatus=1\\n'\n"
FAKE_JOURNALCTL = "#!/bin/sh\necho 'pg_dump: error: connection refused'\n"


class FakeEndpoints(http.server.BaseHTTPRequestHandler):
    """Telegram sendMessage and dead-man ping receiver."""

    messages: list = []
    pings: list = []
    telegram_status = 200

    def do_POST(self):  # noqa: N802 (http.server API)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        if self.path.startswith("/bot"):
            if self.path != f"/bot{TOKEN}/sendMessage" or FakeEndpoints.telegram_status != 200:
                self.send_response(FakeEndpoints.telegram_status if FakeEndpoints.telegram_status != 200 else 404)
                self.end_headers()
                self.wfile.write(b'{"ok": false}')
                return
            form = urllib.parse.parse_qs(body)
            FakeEndpoints.messages.append({"chat_id": form["chat_id"][0], "text": form["text"][0]})
            payload = b'{"ok": true}'
        else:
            FakeEndpoints.pings.append({"path": self.path, "body": body})
            payload = b"OK"
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def container(service, status="running", health="healthy", restarts=0, exit_code=0,
              oom=False, cid=None, pid=0, project="awesome-server"):
    state = {"Status": status, "ExitCode": exit_code, "OOMKilled": oom, "Pid": pid}
    if health:
        state["Health"] = {"Status": health, "Log": [{"Output": f"{service} probe output"}]}
    return {
        "Id": cid or (service.replace("-", "") + "0" * 64)[:64],
        "Created": "2026-11-11T10:00:00Z",
        "RestartCount": restarts,
        "State": state,
        "Config": {"Labels": {"com.docker.compose.project": project,
                              "com.docker.compose.service": service}},
    }


class WatchdogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeEndpoints)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeEndpoints.messages = []
        FakeEndpoints.pings = []
        FakeEndpoints.telegram_status = 200
        self.tmp = Path(tempfile.mkdtemp(prefix="watchdog-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, content in (("docker", FAKE_DOCKER), ("systemctl", FAKE_SYSTEMCTL),
                              ("journalctl", FAKE_JOURNALCTL)):
            path = bin_dir / name
            path.write_text(content)
            path.chmod(0o755)
        self.backups = self.tmp / "backups"
        (self.backups / "daily").mkdir(parents=True)
        self.fresh_backup()
        (self.backups / "restore-check.ok").touch()
        self.cgroup = self.tmp / "cgroup"
        self.cgroup.mkdir()
        self.proc = self.tmp / "proc"
        self.proc.mkdir()
        self.meminfo = self.tmp / "meminfo"
        self.meminfo.write_text("MemTotal:  4456448 kB\nMemAvailable:  2097152 kB\n")
        self.fixture_path = self.tmp / "fixture.json"
        self.docker_log = self.tmp / "docker.log"
        self.fixture = {
            "containers": [container("backend"), container("gateway"), container("consumer", health=None),
                           container("postgres-roles", status="exited", health=None)],
        }
        self.config = {
            "host_label": "test-host",
            "compose_project": "awesome-server",
            "expected_services": ["backend", "consumer", "gateway"],
            "oneshot_services": ["postgres-roles"],
            "state_file": str(self.tmp / "state/state.json"),
            "maintenance_file": str(self.tmp / "maintenance"),
            "disk_paths": [str(self.tmp)],
            "disk_used_percent_thresholds": [101],
            "inode_used_percent_max": 101,
            "meminfo_path": str(self.meminfo),
            "backup_dir": str(self.backups / "daily"),
            "restore_check_stamp": str(self.backups / "restore-check.ok"),
            "cgroup_root": str(self.cgroup),
            "proc_root": str(self.proc),
            "internal_http_checks": [{"name": "consumer", "via": "gateway",
                                      "url": "http://consumer:4002/actuator/health"}],
            "telegram_api_url": self.base_url,
            "telegram_bot_token": TOKEN,
            "telegram_chat_id": "42",
            "healthcheck_url": f"{self.base_url}/ping/check-uuid",
        }
        self.env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                        FAKE_DOCKER_FIXTURE=str(self.fixture_path), FAKE_DOCKER_LOG=str(self.docker_log))

    def fresh_backup(self, age_hours=1.0):
        backup = self.backups / "daily/awesome-testdb-20261111T021500Z-scheduled.sql.gz.enc"
        backup.touch()
        stamp = time.time() - age_hours * 3600
        os.utime(backup, (stamp, stamp))

    def watchdog(self, *args):
        self.fixture_path.write_text(json.dumps(self.fixture))
        config_path = self.tmp / "config.json"
        config_path.write_text(json.dumps(self.config))
        return subprocess.run([sys.executable, str(WATCHDOG), "--config", str(config_path), *args],
                              env=self.env, capture_output=True, text=True, timeout=60)

    def run_once(self, expect_rc=0):
        result = self.watchdog("run")
        self.assertEqual(result.returncode, expect_rc, result.stdout + result.stderr)
        return result

    def texts(self):
        return [message["text"] for message in FakeEndpoints.messages]

    def set_service(self, service, **kwargs):
        cid = next(c["Id"] for c in self.fixture["containers"]
                   if c["Config"]["Labels"]["com.docker.compose.service"] == service)
        self.fixture["containers"] = [c for c in self.fixture["containers"]
                                      if c["Config"]["Labels"]["com.docker.compose.service"] != service]
        self.fixture["containers"].append(container(service, cid=kwargs.pop("cid", cid), **kwargs))

    # -- tests -------------------------------------------------------------

    def test_healthy_stack_sends_nothing_and_pings_success(self):
        self.run_once()
        self.run_once()
        self.assertEqual(FakeEndpoints.messages, [])
        self.assertEqual([ping["path"] for ping in FakeEndpoints.pings], ["/ping/check-uuid"] * 2)

    def test_exited_container_reported_once_after_confirmation_then_resolved_once(self):
        self.set_service("backend", status="exited", health=None, exit_code=137, oom=True)
        self.run_once()
        self.assertEqual(FakeEndpoints.messages, [], "one observation must not alert yet")
        self.run_once()
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        text = self.texts()[0]
        self.assertIn("PROBLEM: Container backend is exited (exit code 137, OOM-killed", text)
        self.assertIn("test-host", text)
        self.assertEqual(FakeEndpoints.messages[0]["chat_id"], "42")
        self.set_service("backend")
        self.run_once()
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 2)
        self.assertIn("RESOLVED: Container backend is exited", self.texts()[1])

    def test_transient_problem_below_confirmation_is_forgotten(self):
        self.set_service("gateway", status="restarting", health=None)
        self.run_once()
        self.set_service("gateway")
        self.run_once()
        self.set_service("gateway", status="restarting", health=None)
        self.run_once()
        self.assertEqual(FakeEndpoints.messages, [])

    def test_unhealthy_needs_three_runs(self):
        self.set_service("gateway", health="unhealthy")
        self.run_once()
        self.run_once()
        self.assertEqual(FakeEndpoints.messages, [])
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("Container gateway is unhealthy: gateway probe output", self.texts()[0])

    def test_missing_container_and_failed_oneshot(self):
        self.fixture["containers"] = [c for c in self.fixture["containers"]
                                      if c["Config"]["Labels"]["com.docker.compose.service"] != "consumer"]
        self.set_service("postgres-roles", status="exited", health=None, exit_code=3)
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("PROBLEM: One-shot postgres-roles exited with code 3", self.texts()[0])
        self.run_once()
        self.assertIn("PROBLEM: Container consumer is missing", self.texts()[1])

    def test_restart_loop_reported_once(self):
        self.run_once()
        self.set_service("backend", restarts=2)
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("Container backend restarted in the last 10 minutes (restart count 2)", self.texts()[0])
        self.set_service("backend", restarts=3)
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1, "a persisting restart loop is reported once")

    def test_recreated_container_does_not_count_as_restart(self):
        self.run_once()
        self.set_service("backend", restarts=0, cid="f" * 64)
        self.run_once()
        self.assertEqual(FakeEndpoints.messages, [])

    def test_docker_oom_event_reported_once(self):
        self.run_once()
        self.fixture["events"] = [{"id": "a" * 64, "timeNano": 1, "Actor": {
            "ID": "a" * 64, "Attributes": {"name": "awesome-server-backend-1",
                                           "com.docker.compose.service": "backend"}}}]
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("EVENT: OOM kill in container backend (Docker event)", self.texts()[0])
        events_calls = [json.loads(line) for line in self.docker_log.read_text().splitlines()
                        if json.loads(line)[0] == "events"]
        self.assertIn("event=oom", events_calls[-1])
        self.assertIn("--until", events_calls[-1])

    def test_cgroup_oom_counters_root_and_container(self):
        (self.cgroup / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n")
        scope = self.cgroup / "system.slice/docker-backend.scope"
        scope.mkdir(parents=True)
        (scope / "memory.events").write_text("oom 0\noom_kill 0\n")
        (self.proc / "4242").mkdir()
        (self.proc / "4242/cgroup").write_text("0::/system.slice/docker-backend.scope\n")
        self.set_service("backend", pid=4242)
        self.run_once()
        self.assertEqual(FakeEndpoints.messages, [], "the first reading only records the counters")
        (self.cgroup / "memory.events").write_text("oom 2\noom_kill 2\n")
        (scope / "memory.events").write_text("oom 1\noom_kill 1\n")
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        text = self.texts()[0]
        self.assertIn("Kernel OOM killer ran 2 time(s) in the VPS cgroup", text)
        self.assertIn("OOM kill inside container backend (cgroup oom_kill=1)", text)
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)

    def test_disk_and_inode_thresholds(self):
        self.config["disk_used_percent_thresholds"] = [0, 101]
        self.config["inode_used_percent_max"] = 0
        self.run_once()
        text = self.texts()[0]
        self.assertIn(f"PROBLEM: Disk {self.tmp} is", text)
        self.assertIn("threshold 0%", text)
        self.assertNotIn("threshold 101%", text)
        self.assertIn("of its inodes", text)

    def test_low_memory_needs_consecutive_runs(self):
        self.config["memory_confirm_runs"] = 2
        self.meminfo.write_text("MemTotal: 4456448 kB\nMemAvailable: 102400 kB\n")
        self.run_once()
        self.assertEqual(FakeEndpoints.messages, [])
        self.run_once()
        self.assertIn("Available memory is 100 MiB", self.texts()[0])

    def test_stale_backup_and_restore_check(self):
        self.fresh_backup(age_hours=30)
        old = time.time() - 9 * 86400
        os.utime(self.backups / "restore-check.ok", (old, old))
        self.run_once()
        text = self.texts()[0]
        self.assertIn("Newest PostgreSQL backup is 30.0 h old (limit 26 h)", text)
        self.assertIn("Last successful backup restore check is 9.0 days old", text)
        self.fresh_backup(age_hours=1)
        self.run_once()
        self.assertIn("RESOLVED: Newest PostgreSQL backup is 30.0 h old", self.texts()[1])

    def test_missing_backup_archive(self):
        for archive in (self.backups / "daily").iterdir():
            archive.unlink()
        self.run_once()
        self.assertIn("No PostgreSQL backup archive", self.texts()[0])

    def test_internal_http_check_through_gateway(self):
        self.fixture["exec_fail"] = ["http://consumer:4002/actuator/health"]
        self.run_once()
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("consumer health check http://consumer:4002/actuator/health failed", self.texts()[0])
        exec_calls = [json.loads(line) for line in self.docker_log.read_text().splitlines()
                      if json.loads(line)[0] == "exec"]
        self.assertTrue(all(call[1] == container("gateway")["Id"] and call[2] == "curl" for call in exec_calls))

    def test_docker_daemon_down_is_reported_and_pings_fail(self):
        self.fixture["daemon_down"] = True
        self.run_once()
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("Watchdog check 'docker' could not run", self.texts()[0])
        self.assertEqual(FakeEndpoints.pings[-1]["path"], "/ping/check-uuid/fail")

    def test_failed_delivery_is_retried_and_pings_fail(self):
        self.fixture["containers"] = [c for c in self.fixture["containers"]
                                      if c["Config"]["Labels"]["com.docker.compose.service"] != "backend"]
        FakeEndpoints.telegram_status = 500
        self.run_once()
        result = self.run_once(expect_rc=1)
        self.assertNotIn(TOKEN, result.stdout + result.stderr, "the bot token must never be logged")
        self.assertEqual(FakeEndpoints.pings[-1]["path"], "/ping/check-uuid/fail")
        FakeEndpoints.telegram_status = 200
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("Container backend is missing", self.texts()[0])
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)

    def test_maintenance_pauses_container_checks_only(self):
        self.assertEqual(self.watchdog("maintenance", "start", "--minutes", "15").returncode, 0)
        self.set_service("backend", status="exited", health=None)
        self.fresh_backup(age_hours=40)
        self.run_once()
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1)
        self.assertIn("Newest PostgreSQL backup", self.texts()[0])
        self.assertNotIn("backend", self.texts()[0])
        self.assertEqual(self.watchdog("maintenance", "stop").returncode, 0)
        self.run_once()
        self.run_once()
        self.assertIn("Container backend is exited", self.texts()[1])

    def test_maintenance_keeps_known_problems_without_resolving(self):
        self.set_service("backend", status="exited", health=None)
        self.run_once()
        self.run_once()
        self.watchdog("maintenance", "start")
        self.run_once()
        self.assertEqual(len(FakeEndpoints.messages), 1, "a pause must not report a false recovery")

    def test_maintenance_is_capped(self):
        Path(self.config["maintenance_file"]).write_text(str(int(time.time() + 86400)))
        old = time.time() - 31 * 60
        os.utime(self.config["maintenance_file"], (old, old))
        status = self.watchdog("maintenance", "status")
        self.assertIn("maintenance inactive", status.stdout)

    def test_dry_run_sends_nothing_and_keeps_no_state(self):
        self.set_service("backend", status="exited", health=None)
        result = self.watchdog("run", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("condition container:backend:not-running", result.stdout)
        self.assertEqual(FakeEndpoints.messages, [])
        self.assertEqual(FakeEndpoints.pings, [])
        self.assertFalse(Path(self.config["state_file"]).exists())

    def test_dry_run_fails_when_a_check_cannot_run(self):
        self.fixture["daemon_down"] = True
        result = self.watchdog("run", "--dry-run")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("check error docker", result.stdout)

    def test_notify_unit_failure(self):
        result = self.watchdog("notify-unit-failure", "awesome-postgres-backup.service")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = self.texts()[0]
        self.assertIn("FAILED: systemd unit awesome-postgres-backup.service failed", text)
        self.assertIn("Result=exit-code", text)
        self.assertIn("pg_dump: error: connection refused", text)

    def test_disabled_ping_and_missing_credentials(self):
        self.config["healthcheck_url"] = ""
        self.run_once()
        self.assertEqual(FakeEndpoints.pings, [])
        self.config["telegram_bot_token"] = ""
        self.assertEqual(self.watchdog("test-message").returncode, 1)

    def test_corrupt_state_file_is_tolerated(self):
        state = Path(self.config["state_file"])
        state.parent.mkdir(parents=True)
        state.write_text("{not json")
        self.run_once()
        json.loads(state.read_text())


if __name__ == "__main__":
    unittest.main()
