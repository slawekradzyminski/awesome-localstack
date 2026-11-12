#!/usr/bin/env python3
"""Run the deploy's asset mirror against fixtures: files the repository tracked
and deleted are pruned on the server; files git never tracked there (manual
backups), rendered secrets and app_dir runtime files are kept.

Needs git, ansible-playbook and the ansible.posix collection (json callback). Runs the real roles/app/tasks/assets.yml on localhost
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
COPY_PATHS = ["docs", "alertmanager", "prometheus", "nginx"]


def write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def fixture(base: Path) -> None:
    repo, app = base / "repo", base / "app"
    # Repository history: the previous release tracked these files...
    for rel in ("docs/INDEX.md", "docs/SSO_FLOW.md", "docs/.stale-hidden", "docs/retired/deep/page.md",
                "docs/old/a.md", "docs/guides/kept.md", "docs/.hidden-kept", "alertmanager/alertmanager.yml",
                "prometheus/rules/kept.yml", "prometheus/rules/retired.yml", "nginx/conf.d/edge-gateway.conf"):
        write(repo / rel)
    git(repo, "init", "--quiet")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "previous release")
    # ...and the next release deletes some of them.
    git(repo, "rm", "--quiet", "-r", "docs/SSO_FLOW.md", "docs/.stale-hidden", "docs/retired", "docs/old",
        "prometheus/rules/retired.yml")
    write(repo / "docs/INDEX.md", "new index\n")
    git(repo, "commit", "--quiet", "-am", "next release")

    # Server state left by the previous release.
    write(app / "docs/INDEX.md", "old index\n")
    write(app / "docs/SSO_FLOW.md")                   # tracked, then deleted
    write(app / "docs/.stale-hidden")                 # hidden, tracked, then deleted
    write(app / "docs/retired/deep/page.md")          # whole tracked directory deleted
    write(app / "docs/old/a.md")                      # tracked, then deleted...
    write(app / "docs/old/notes.txt")                 # ...next to a manual file: the directory stays
    write(app / "prometheus/rules/retired.yml")       # tracked rule file, then deleted
    write(app / "nginx/conf.d/edge-gateway.conf")
    write(app / "nginx/conf.d/edge-gateway.conf.before-x")  # manual backup, never tracked
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


def task_result(report: dict, name: str) -> dict:
    for play in report["plays"]:
        for task in play["tasks"]:
            if task["task"]["name"].split(" : ")[-1] == name:
                return task["hosts"]["localhost"]
    raise AssertionError(f"task not run: {name}")


def task_changed(report: dict, name: str) -> bool:
    return bool(task_result(report, name).get("changed"))


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
                     "nginx/conf.d/edge-gateway.conf", "nginx/conf.d/edge-gateway.conf.before-x",
                     "docs/old/notes.txt", "alertmanager/secrets/telegram_bot_token", ".env.runtime",
                     "docker-compose.server.yml", "backups/dump.sql.enc"):
            assert exists(kept), f"{kept} must remain"
        for pruned in ("docs/SSO_FLOW.md", "docs/.stale-hidden", "docs/retired",
                       "docs/old/a.md", "prometheus/rules/retired.yml"):
            assert not exists(pruned), f"{pruned} must be pruned"
        report = task_result(first, "Report untracked files on the server (kept)")["msg"]
        assert report == ("untracked files on the server (kept): "
                          "docs/old/notes.txt, nginx/conf.d/edge-gateway.conf.before-x"), report
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
