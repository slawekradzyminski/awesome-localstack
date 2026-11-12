#!/usr/bin/env python3
"""Run the deploy's asset mirror against fixtures: deleted repository files are
pruned on the server, server-only runtime files are kept.

Needs ansible-playbook and the ansible.posix collection (json callback). Runs the real roles/app/tasks/assets.yml on localhost
(with sudo when not root, because the copy sets root ownership).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE_DIR = ROOT / "ansible"
COPY_PATHS = ["docs", "alertmanager", "prometheus"]


def write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def fixture(base: Path) -> None:
    repo, app = base / "repo", base / "app"
    # Repository checkout: what the next release ships.
    write(repo / "docs/INDEX.md", "new index\n")
    write(repo / "docs/guides/kept.md")
    write(repo / "docs/.hidden-kept")
    write(repo / "alertmanager/alertmanager.yml")
    write(repo / "prometheus/rules/kept.yml")
    # Server state left by the previous release.
    write(app / "docs/INDEX.md", "old index\n")
    write(app / "docs/SSO_FLOW.md")                   # deleted from the repository
    write(app / "docs/.stale-hidden")                 # hidden and deleted
    write(app / "docs/retired/deep/page.md")          # whole directory deleted
    write(app / "prometheus/rules/retired.yml")       # deleted rule file
    write(app / "alertmanager/alertmanager.yml")
    write(app / "alertmanager/secrets/telegram_bot_token")  # rendered by the app role
    write(app / ".env.runtime")                       # runtime secret in app_dir
    write(app / "docker-compose.server.yml")
    write(app / "backups/dump.sql.enc")               # not a copied directory


def run_playbook(base: Path) -> dict:
    command = [
        "ansible-playbook", "-i", "localhost,", "tests/asset-mirror.yml",
        "-e", json.dumps({
            "asset_mirror_fixture": str(base),
            "asset_mirror_copy_paths": COPY_PATHS,
            "asset_mirror_become": os.geteuid() != 0,
        }),
    ]
    env = dict(os.environ, ANSIBLE_STDOUT_CALLBACK="ansible.posix.json", ANSIBLE_CONFIG=str(ANSIBLE_DIR / "ansible.cfg"))
    result = subprocess.run(command, cwd=ANSIBLE_DIR, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(result.stdout[-6000:], result.stderr[-3000:], sep="\n", file=sys.stderr)
        raise SystemExit("asset mirror playbook failed")
    return json.loads(result.stdout)


def task_changed(report: dict, name: str) -> bool:
    for play in report["plays"]:
        for task in play["tasks"]:
            if task["task"]["name"].split(" : ")[-1] == name:
                return any(host.get("changed") for host in task["hosts"].values())
    raise AssertionError(f"task not run: {name}")


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="asset-mirror-"))
    try:
        fixture(base)
        app = base / "app"
        first = run_playbook(base)

        def exists(rel: str) -> bool:
            return os.path.lexists(app / rel)

        for kept in ("docs/INDEX.md", "docs/guides/kept.md", "docs/.hidden-kept",
                     "alertmanager/alertmanager.yml", "prometheus/rules/kept.yml",
                     "alertmanager/secrets/telegram_bot_token", ".env.runtime",
                     "docker-compose.server.yml", "backups/dump.sql.enc"):
            assert exists(kept), f"{kept} must remain"
        for pruned in ("docs/SSO_FLOW.md", "docs/.stale-hidden", "docs/retired",
                       "prometheus/rules/retired.yml"):
            assert not exists(pruned), f"{pruned} must be pruned"
        assert (app / "docs/INDEX.md").read_text() == "new index\n", "changed files must be copied"
        assert task_changed(first, "Remove deployed asset files that the repository no longer has")

        second = run_playbook(base)
        assert not task_changed(second, "Remove deployed asset files that the repository no longer has"), \
            "a converged mirror must prune nothing"
        assert not task_changed(second, "Copy deployment asset directories"), "a converged copy must not change"
    finally:
        # The copy created root-owned directories.
        if os.geteuid() == 0:
            shutil.rmtree(base)
        else:
            subprocess.run(["sudo", "rm", "-rf", "--", str(base)], check=True)
    print("Asset mirror contract verified")


if __name__ == "__main__":
    main()
