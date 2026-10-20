#!/usr/bin/env python3
"""Check that coordinated upgrades cannot migrate while old backends still write."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ordered(text, markers):
    positions = [text.find(marker) for marker in markers]
    assert all(position >= 0 for position in positions), "Missing upgrade stage"
    assert positions == sorted(positions), "Unsafe upgrade ordering"


def main():
    playbook = (ROOT / "ansible/playbooks/deploy.yml").read_text()
    tasks = (ROOT / "ansible/roles/backend_upgrade/tasks/main.yml").read_text()
    ordered(playbook, ["    - postgres_backup", "deployment_silence_state: present",
                       "    - role: backend_upgrade", "    - app", "    - verify",
                       "deployment_silence_state: absent"])
    assert "when: backend_upgrade_quiesce | default(false) | bool" in playbook
    ordered(tasks, ["postgres_backup_enabled | bool", "postgres_backup_pre_deploy | bool",
                    "      - pull", "      - stop", "      - backend\n",
                    "      - aitesters-backend", "awesome-postgres-backup backend-upgrade-quiesced"])
    assert "lookup('file', repo_root ~ '/' ~ app_compose_src)" in tasks
    assert "      - \"60\"" in tasks
    print("Coordinated backend upgrade contract verified")


if __name__ == "__main__":
    main()
