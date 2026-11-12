#!/usr/bin/env python3
"""Check that coordinated upgrades cannot migrate while old backends still write,
and that nothing unrelated to the migration can fail once they are stopped."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ordered(text, markers):
    positions = [text.find(marker) for marker in markers]
    missing = [marker for marker, position in zip(markers, positions) if position < 0]
    assert not missing, f"Missing upgrade stage: {missing}"
    assert positions == sorted(positions), f"Unsafe upgrade ordering: {markers}"


def main():
    playbook = (ROOT / "ansible/playbooks/deploy.yml").read_text()
    tasks = (ROOT / "ansible/roles/backend_upgrade/tasks/main.yml").read_text()
    recover = (ROOT / "ansible/roles/backend_upgrade/tasks/recover.yml").read_text()
    app_main = (ROOT / "ansible/roles/app/tasks/main.yml").read_text()
    prepare = (ROOT / "ansible/roles/app/tasks/prepare.yml").read_text()
    converge = (ROOT / "ansible/roles/app/tasks/converge.yml").read_text()

    # Backup, then every failure-prone preparation, then the quiesce, then the
    # containers, then verification; the rescue restarts the old backends.
    ordered(playbook, ["        name: postgres_backup", "        tasks_from: prepare",
                       "deployment_silence_state: present", "      block:",
                       "            name: backend_upgrade", "            tasks_from: converge",
                       "      rescue:", "            tasks_from: recover", "ansible.builtin.fail:",
                       "        name: verify", "deployment_silence_state: absent"])
    assert "when: backend_upgrade_quiesce | default(false) | bool" in playbook
    assert "not (app_stack_converge_started | default(false) | bool)" in playbook, \
        "the old backends may restart only before the new release started"

    ordered(tasks, ["postgres_backup_enabled | bool", "postgres_backup_pre_deploy | bool",
                    "      - pull", "      - --services",
                    "intersect(backend_upgrade_deployed_services.stdout_lines)",
                    "      - backend\n", "      - aitesters-backend", "      - warehouse-service",
                    "      - aitesters-warehouse-service", "      - payment-service",
                    "      - aitesters-payment-service",
                    "'backend' in backend_upgrade_quiesced_services",
                    "'ps', '--quiet'", "backend_upgrade_stopped_containers:", "'stop'",
                    "awesome-postgres-backup backend-upgrade-quiesced"])
    assert "lookup('file', repo_root ~ '/' ~ app_compose_src)" in tasks
    assert "'--timeout', '60'" in tasks
    assert "['docker', 'start'] + backend_upgrade_stopped_containers" in recover

    # Failure-prone preparation only in prepare.yml; converge.yml never builds.
    ordered(app_main, ["import_tasks: prepare.yml", "import_tasks: converge.yml"])
    for step in ("name: Mirror the deployment asset directories", "      - config\n      - --quiet",
                 "docker_compose_v2_pull", "build docs"):
        assert step in prepare, f"prepare.yml must run before the quiesce: {step}"
        assert step not in converge, f"converge.yml must not repeat a preparation step: {step}"
    ordered(converge, ["app_stack_converge_started: true", "- name: Deploy Docker Compose stack",
                       "    build: never"])
    for stopping in ("compose stop", "'stop'", "state: stopped"):
        assert stopping not in prepare, f"prepare.yml must not stop services: {stopping}"
    print("Coordinated backend upgrade contract verified")


if __name__ == "__main__":
    main()
