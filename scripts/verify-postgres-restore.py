#!/usr/bin/env python3
"""Restore an encrypted fixture while PostgreSQL initialization is delayed."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ansible/roles/postgres_backup/templates/postgres-restore-check.sh.j2"
DOCKER_WRAPPER = '''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
real = os.environ["RESTORE_TEST_DOCKER"]
def record(event):
    with open(os.environ["RESTORE_TEST_EVENTS"], "a") as stream:
        stream.write(json.dumps(event) + "\\n")
if args[0] == "run":
    args[1:1] = ["--volume", os.environ["RESTORE_TEST_INIT"] + ":/docker-entrypoint-initdb.d/00-delay.sh:ro"]
    record({"event": "container", "name": args[args.index("--name") + 1]})
if args[0] == "exec" and "psql" in args:
    container = args[args.index("psql") - 1]
    probe = subprocess.run([real, "exec", container, "pg_isready", "--host=127.0.0.1"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record({"event": "sql", "permanent_ready": probe.returncode == 0})
if args[0] == "rm":
    query = subprocess.run([real, "exec", args[-1], "psql", "--host=127.0.0.1", "--username=postgres",
                            "--dbname=restorecheck", "--tuples-only", "--no-align", "--command",
                            "SELECT value FROM restore_fixture;"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True)
    record({"event": "fixture", "value": query.stdout.strip(), "exit": query.returncode})
os.execv(real, [real, *args])
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    args = parser.parse_args()
    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("Docker is required for the restore regression check")
    inventory = (ROOT / "ansible/inventory/group_vars/production/main.yml").read_text()
    image = re.search(r"^postgres_restore_image: (.+)$", inventory, re.MULTILINE).group(1)
    with tempfile.TemporaryDirectory(prefix="postgres-restore-test-") as directory:
        fixture = Path(directory)
        daily = fixture / "backups/daily"
        daily.mkdir(parents=True)
        backup = daily / "fixture.sql.gz.enc"
        env = dict(os.environ, BACKUP_ENCRYPTION_PASSPHRASE="disposable-restore-regression-fixture-only")
        sql = b"CREATE TABLE restore_fixture (value integer);\nINSERT INTO restore_fixture VALUES (42);\n"
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "200000",
                        "-pass", "env:BACKUP_ENCRYPTION_PASSPHRASE", "-out", str(backup)],
                       input=gzip.compress(sql), env=env, check=True)
        backup.with_suffix(backup.suffix + ".sha256").write_text(
            f"{hashlib.sha256(backup.read_bytes()).hexdigest()}  {backup.name}\n")
        config = fixture / "backup.env"
        config.write_text("\n".join(f"{key}={shlex.quote(value)}" for key, value in {
            "BACKUP_ROOT": str(fixture / "backups"), "POSTGRES_RESTORE_IMAGE": image,
            "BACKUP_ENCRYPTION_PASSPHRASE": env["BACKUP_ENCRYPTION_PASSPHRASE"],
        }.items()) + "\n")
        rendered = fixture / "restore-check.sh"
        rendered.write_text(args.template.read_text().replace(
            "{{ postgres_backup_environment_file }}", shlex.quote(str(config))))
        subprocess.run(["bash", "-n", str(rendered)], check=True)
        delay = fixture / "delay.sh"
        delay.write_text("#!/bin/sh\nsleep 5\n")
        delay.chmod(0o755)
        wrapper = fixture / "docker"
        wrapper.write_text(DOCKER_WRAPPER)
        wrapper.chmod(0o755)
        events = fixture / "events.jsonl"
        env.update(PATH=str(fixture) + os.pathsep + env["PATH"], RESTORE_TEST_DOCKER=docker,
                   RESTORE_TEST_INIT=str(delay), RESTORE_TEST_EVENTS=str(events))
        try:
            result = subprocess.run(["bash", str(rendered)], env=env, capture_output=True,
                                    text=True, timeout=120)
            records = [json.loads(line) for line in events.read_text().splitlines()]
            assert result.returncode == 0, result.stdout + result.stderr
            sql_events = [event for event in records if event["event"] == "sql"]
            assert sql_events and all(event["permanent_ready"] for event in sql_events), (
                "Restore began before the permanent PostgreSQL server was ready")
            restored = [event for event in records if event["event"] == "fixture"]
            assert restored and restored[-1]["exit"] == 0 and restored[-1]["value"] == "42", (
                "Encrypted fixture data was not restored")
            print("Restore regression passed: waited for permanent server, restored fixture, cleaned up")
        finally:
            if events.exists():
                for line in events.read_text().splitlines():
                    event = json.loads(line)
                    if event["event"] == "container":
                        subprocess.run([docker, "rm", "--force", event["name"]],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
