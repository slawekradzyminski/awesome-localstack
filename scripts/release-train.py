#!/usr/bin/env python3
"""Release train for the first-party application images.

    plan    default-branch version, latest tag and current pin per repository
    tag     create annotated v<version> tags on green default-branch heads
    wait    poll each repository's publish workflow for its tag
    pin     resolve digests, update every Compose file and docs/CONTAINER_RELEASES.md
    verify  Compose configuration and every contract script (--compat: course suite)
    pr      branch, commit, push, open the LocalStack PR, wait for CI (--merge)
    deploy  make ansible-deploy[-backend-upgrade] from a clean, merged main (--yes)

Every subcommand recomputes the release set from GitHub and the Compose files,
so the steps can be rerun or resumed. --dry-run prints every action that would
change a repository, a file, GitHub or production, and performs only reads.
See docs/CONTAINER_RELEASES.md ("Release sequence").

Requires python3 (stdlib only), gh (authenticated), git and docker buildx.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = "slawekradzyminski"
SERVER_COMPOSE = "docker-compose.server.yml"
RELEASES_DOC = "docs/CONTAINER_RELEASES.md"
COMPAT_HEADING = "## Current compatibility set"
PUBLISH_WORKFLOW = "publish-image.yml"
# Gitignored links the Ansible deploy needs; their presence is checked, never their content.
VAULT_LINKS = ("ansible/.vault_pass", "ansible/inventory/group_vars/production/vault.yml")
CONTRACT_SCRIPTS = (
    ["python3", "scripts/verify-release-images.py"],
    ["python3", "scripts/verify-image-pins.py"],
    ["python3", "scripts/verify-java-security.py"],
    ["python3", "scripts/verify-deployment-silence.py"],
    ["python3", "scripts/verify-backend-upgrade.py"],
    ["python3", "scripts/verify-production-monitoring.py"],
    ["python3", "scripts/verify-correlation-ids.py"],
    ["python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_release_train.py"],
)
MAX_CLOCK_DRIFT_SECONDS = 5


@dataclass(frozen=True)
class Repo:
    key: str
    name: str
    image: str
    version_file: str
    ci_workflow: str
    label: str
    optional: bool = False


REPOS = (
    Repo("backend", "test-secure-backend", "backend", "pom.xml", "verify.yml", "Backend"),
    Repo("warehouse-service", "warehouse-service", "warehouse-service", "pom.xml", "ci.yml",
         "Warehouse service"),
    Repo("payment-service", "payment-service", "payment-service", "pom.xml", "ci.yml", "Payment service"),
    Repo("frontend", "vite-react-frontend", "frontend", "package.json", "ci.yml", "Frontend"),
    Repo("consumer", "jms-email-consumer", "consumer", "pom.xml", "ci.yml", "Consumer", optional=True),
)


# --- pure helpers (unit tested in scripts/test_release_train.py) ------------

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    """`3.17.0` or `v3.17.0` -> (3, 17, 0); anything else (SNAPSHOT, rc) -> None."""
    match = SEMVER.match(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def pom_version(xml_text: str) -> str:
    """The project's own <version>, never the parent's or a dependency's."""
    root = ET.fromstring(xml_text)
    namespace = root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    element = root.find(f"{namespace}version")
    if element is None or not (element.text or "").strip():
        raise ValueError("pom.xml has no project <version> (inherited versions are not supported)")
    return element.text.strip()


def package_version(json_text: str) -> str:
    version = json.loads(json_text).get("version")
    if not version:
        raise ValueError("package.json has no version")
    return version


def latest_tag(tags: list[str]) -> str | None:
    versions = [(parse_version(tag), tag) for tag in tags]
    versions = [item for item in versions if item[0]]
    return max(versions)[1] if versions else None


def pin_pattern(image: str) -> re.Pattern:
    return re.compile(re.escape(f"{OWNER}/{image}:") + r"(?P<version>[0-9][^@\s\"'}]*)@(?P<digest>sha256:[0-9a-f]{64})")


def current_pin(compose_text: str, image: str) -> tuple[str, str] | None:
    """(version, digest) of the image's pin; several different pins are an error."""
    pins = {(m["version"], m["digest"]) for m in pin_pattern(image).finditer(compose_text)}
    if len(pins) > 1:
        raise ValueError(f"{image} is pinned to several references: {sorted(pins)}")
    return pins.pop() if pins else None


def pin_ref(image: str, version: str, digest: str) -> str:
    return f"{OWNER}/{image}:{version}@{digest}"


def replace_pin(text: str, image: str, old: tuple[str, str], new: tuple[str, str]) -> tuple[str, int]:
    """Replace exactly the current reference; other versions (history) stay untouched."""
    return text.replace(pin_ref(image, *old), pin_ref(image, *new)), text.count(pin_ref(image, *old))


def section_bounds(doc: str, heading: str) -> tuple[int, int]:
    start = doc.index(heading + "\n")
    following = re.compile(r"(?m)^## ").search(doc, start + len(heading))
    return start, following.start() if following else len(doc)


def update_compat_set(doc: str, image: str, old: tuple[str, str], new: tuple[str, str],
                      title: str | None = None) -> str:
    """Rewrite the image's row in "Current compatibility set" only (and its intro line)."""
    start, end = section_bounds(doc, COMPAT_HEADING)
    section = doc[start:end]
    if pin_ref(image, *old) not in section:
        raise ValueError(f"{RELEASES_DOC}: current compatibility set does not list {pin_ref(image, *old)}")
    section = section.replace(pin_ref(image, *old), pin_ref(image, *new))
    if title:
        section = re.sub(r"(?m)^(?!\|)(.+), released [^\n]+:$", f"{title}:", section, count=1)
    return doc[:start] + section + doc[end:]


@dataclass
class Released:
    repo: Repo
    version: str
    digest: str
    sha: str = ""
    pr_url: str = ""
    run_url: str = ""


def release_title(released: list[Released], date: dt.date) -> str:
    names = ", ".join(f"{item.repo.key} {item.version}" for item in released)
    return f"Release train: {names} — {date.day} {date:%B %Y}"


def render_release_section(released: list[Released], unchanged: dict[str, str], date: dt.date) -> str:
    lines = [f"## {release_title(released, date)}", "",
             "Published by `scripts/release-train.py`. TODO: what changes, LocalStack",
             "changes, upgrade order and rollback.", "",
             "| Image | Source | Release workflow |", "| --- | --- | --- |"]
    for item in released:
        source = item.pr_url and f"[PR #{item.pr_url.rstrip('/').rsplit('/', 1)[-1]}]({item.pr_url})"
        source = ", ".join(part for part in (source, item.sha and f"`{item.sha[:7]}`") if part) or "—"
        run = f"[run]({item.run_url})" if item.run_url else "—"
        lines.append(f"| `{pin_ref(item.repo.image, item.version, item.digest)}` | {source} | {run} |")
    for image, version in unchanged.items():
        lines.append(f"| `{OWNER}/{image}:{version}` | unchanged | unchanged |")
    return "\n".join(lines) + "\n\n"


def insert_release_section(doc: str, section: str) -> str:
    """New release notes go above the most recent dated release section.

    The document is not strictly ordered (maintenance notes sit above newer
    releases), so the position comes from the heading dates, not the order.
    """
    dated = []
    for match in re.finditer(r"(?m)^## .+ — (\d{1,2} [A-Z][a-z]+ \d{4})$", doc):
        try:
            dated.append((dt.datetime.strptime(match.group(1), "%d %B %Y").date(), -match.start()))
        except ValueError:
            continue
    if not dated:
        start, _ = section_bounds(doc, COMPAT_HEADING)
        return doc[:start] + section + doc[start:]
    position = -max(dated)[1]
    return doc[:position] + section + doc[position:]


def choose_deploy_target(old_backend: str | None, new_backend: str | None) -> str:
    """A backend version change may carry Flyway migrations: quiesce, back up, then migrate."""
    if new_backend is None:
        raise ValueError("no backend pin in the new Compose file")
    return "ansible-deploy" if old_backend == new_backend else "ansible-deploy-backend-upgrade"


def plan_action(version: str, tags: list[str], pinned: str | None) -> str:
    if not parse_version(version):
        return f"skip: {version} is not a release version"
    tag = f"v{version}"
    newest = latest_tag(tags)
    if newest and parse_version(newest) > parse_version(version):
        return f"skip: {version} is older than the latest tag {newest}"
    if pinned == version:
        return "up to date"
    if pinned and parse_version(pinned) and parse_version(pinned) > parse_version(version):
        return f"skip: pinned {pinned} is newer than {version}"
    return "pin" if tag in tags else "tag, publish, pin"


def clock_drift(host_epoch: float, docker_epoch: float) -> float:
    return abs(host_epoch - docker_epoch)


# --- side effects ------------------------------------------------------------

class Shell:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def read(self, args: list[str], cwd: Path = ROOT, check: bool = True, env=None) -> str:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
        if check and result.returncode != 0:
            raise SystemExit(f"command failed: {shlex.join(args)}\n{result.stderr.strip()}")
        return result.stdout.strip()

    def act(self, args: list[str], cwd: Path = ROOT, capture: bool = False) -> str:
        if self.dry_run:
            print(f"[dry-run] {shlex.join(args)}")
            return ""
        print(f"+ {shlex.join(args)}", flush=True)
        if capture:
            return self.read(args, cwd)
        subprocess.run(args, cwd=cwd, check=True)
        return ""

    def write(self, path: Path, text: str) -> None:
        if self.dry_run:
            print(f"[dry-run] write {path.relative_to(ROOT)}")
            return
        path.write_text(text)
        print(f"updated {path.relative_to(ROOT)}")

    def gh_json(self, endpoint: str, check: bool = True):
        out = self.read(["gh", "api", endpoint], check=check)
        return json.loads(out) if out else None


@dataclass
class RepoState:
    repo: Repo
    branch: str
    head: str
    version: str
    tags: list[str]
    pinned: tuple[str, str] | None
    action: str = field(init=False)

    def __post_init__(self):
        self.action = plan_action(self.version, self.tags, self.pinned[0] if self.pinned else None)

    @property
    def releasing(self) -> bool:
        return self.action in ("pin", "tag, publish, pin")


# Overlays are only valid on top of a base profile.
COMPOSE_OVERLAYS = {
    "docker-compose.model-mock.yml": ("docker-compose.yml",),
    "docker-compose.monitoring.yml": ("docker-compose.yml", "lightweight-docker-compose.yml"),
}


def compose_files() -> list[Path]:
    return sorted(ROOT.glob("docker-compose*.yml")) + [ROOT / "lightweight-docker-compose.yml"]


def compose_config_commands() -> list[list[str]]:
    commands = []
    for path in compose_files():
        for base in COMPOSE_OVERLAYS.get(path.name, (None,)):
            files = [base, path.name] if base else [path.name]
            commands.append(["docker", "compose", *[arg for f in files for arg in ("-f", f)], "config", "--quiet"])
    return commands


def selected_repos(args) -> list[Repo]:
    only = set(args.only.split(",")) if args.only else None
    repos = [r for r in REPOS if (not r.optional or args.with_consumer or (only and r.key in only))]
    return [r for r in repos if not only or r.key in only]


def gather(shell: Shell, args) -> list[RepoState]:
    compose = (ROOT / SERVER_COMPOSE).read_text()
    states = []
    for repo in selected_repos(args):
        slug = f"{OWNER}/{repo.name}"
        branch = shell.gh_json(f"repos/{slug}")["default_branch"]
        head = shell.gh_json(f"repos/{slug}/commits/{branch}")["sha"]
        content = shell.gh_json(f"repos/{slug}/contents/{repo.version_file}?ref={head}")
        text = base64.b64decode(content["content"]).decode()
        version = pom_version(text) if repo.version_file == "pom.xml" else package_version(text)
        tags = [t["name"] for t in shell.gh_json(f"repos/{slug}/tags?per_page=100")]
        states.append(RepoState(repo, branch, head, version, tags, current_pin(compose, repo.image)))
    return states


def print_plan(states: list[RepoState]) -> None:
    rows = [("repository", "image", "default branch", "version", "latest tag", "pinned", "action")]
    for s in states:
        rows.append((s.repo.name, s.repo.image, f"{s.branch}@{s.head[:7]}", s.version,
                     latest_tag(s.tags) or "-", s.pinned[0] if s.pinned else "-", s.action))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for index, row in enumerate(rows):
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if index == 0:
            print("  ".join("-" * w for w in widths))
    releasing = [s for s in states if s.releasing]
    print()
    if releasing:
        print("Release set: " + ", ".join(f"{s.repo.image} {s.pinned[0] if s.pinned else '-'} -> {s.version}"
                                          for s in releasing))
        backend = next((s for s in states if s.repo.key == "backend"), None)
        if backend and backend.pinned:
            new_backend = backend.version if backend.releasing else backend.pinned[0]
            print("Deploy target after merge: make " + choose_deploy_target(backend.pinned[0], new_backend))
    else:
        print("Nothing to release: every selected image is pinned to its default-branch version.")


def ci_conclusion(shell: Shell, slug: str, workflow: str, sha: str) -> tuple[str, str]:
    runs = shell.gh_json(f"repos/{slug}/actions/workflows/{workflow}/runs?head_sha={sha}&per_page=20")
    runs = [r for r in runs["workflow_runs"] if r["event"] in ("push", "workflow_dispatch")]
    if not runs:
        return "missing", ""
    run = max(runs, key=lambda r: r["created_at"])
    return (run["conclusion"] or run["status"]), run["html_url"]


def cmd_plan(shell, args):
    print_plan(gather(shell, args))


def cmd_tag(shell, args):
    states = [s for s in gather(shell, args) if s.action == "tag, publish, pin"]
    if not states:
        print("No untagged release versions.")
        return
    for s in states:
        slug = f"{OWNER}/{s.repo.name}"
        conclusion, url = ci_conclusion(shell, slug, s.repo.ci_workflow, s.head)
        if conclusion != "success":
            raise SystemExit(f"{slug}: CI ({s.repo.ci_workflow}) for {s.head[:7]} is {conclusion}, "
                             f"refusing to tag v{s.version}. {url}")
        print(f"{slug}: CI green for {s.head[:7]} ({url})")
    for s in states:
        slug, tag = f"{OWNER}/{s.repo.name}", f"v{s.version}"
        if shell.dry_run:
            print(f"[dry-run] gh api repos/{slug}/git/tags (annotated {tag} -> {s.head[:7]}) "
                  f"+ gh api repos/{slug}/git/refs refs/tags/{tag}")
            continue
        tag_sha = json.loads(shell.act(["gh", "api", f"repos/{slug}/git/tags", "-f", f"tag={tag}",
                                        "-f", f"message=Release {s.version}", "-f", f"object={s.head}",
                                        "-f", "type=commit"], capture=True))["sha"]
        shell.act(["gh", "api", f"repos/{slug}/git/refs", "-f", f"ref=refs/tags/{tag}", "-f", f"sha={tag_sha}"],
                  capture=True)
        print(f"{slug}: tagged {tag} at {s.head[:7]}")


def publish_run(shell: Shell, slug: str, tag: str) -> dict | None:
    ref = shell.gh_json(f"repos/{slug}/commits/{tag}", check=False)
    if not ref:
        return None
    runs = shell.gh_json(f"repos/{slug}/actions/workflows/{PUBLISH_WORKFLOW}/runs?head_sha={ref['sha']}&per_page=20")
    runs = [r for r in runs["workflow_runs"] if r.get("head_branch") == tag]
    return max(runs, key=lambda r: r["created_at"]) if runs else None


def cmd_wait(shell, args):
    pending = {f"{OWNER}/{s.repo.name}": f"v{s.version}" for s in gather(shell, args) if s.releasing}
    if not pending:
        print("Nothing to wait for.")
        return
    if shell.dry_run:
        for slug, tag in pending.items():
            run = publish_run(shell, slug, tag)
            print(f"[dry-run] would poll {slug} {PUBLISH_WORKFLOW} for {tag}: "
                  + (f"{run['status']}/{run['conclusion']} {run['html_url']}" if run else "no run yet"))
        return
    deadline = time.monotonic() + args.timeout
    while pending:
        for slug, tag in list(pending.items()):
            run = publish_run(shell, slug, tag)
            if not run:
                continue
            failed = [j for j in shell.gh_json(f"repos/{slug}/actions/runs/{run['id']}/jobs")["jobs"]
                      if j.get("conclusion") in ("failure", "cancelled", "timed_out")]
            if failed or run["conclusion"] not in (None, "success"):
                raise SystemExit(f"{slug} {tag}: publish failed ({', '.join(j['name'] for j in failed) or run['conclusion']}): "
                                 f"{run['html_url']}")
            if run["conclusion"] == "success":
                print(f"{slug} {tag}: published {run['html_url']}")
                del pending[slug]
        if pending:
            if time.monotonic() > deadline:
                raise SystemExit("timed out waiting for " + ", ".join(f"{s} {t}" for s, t in pending.items()))
            print("waiting for " + ", ".join(f"{s} {t}" for s, t in pending.items()), flush=True)
            time.sleep(args.interval)


def resolve_digest(shell: Shell, image: str, version: str) -> str:
    ref = f"{OWNER}/{image}:{version}"
    args = ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest}}"]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        # A desktop credential helper can fail outside a login session; the images are public.
        with tempfile.TemporaryDirectory() as config:
            Path(config, "config.json").write_text("{}")
            plugins = Path.home() / ".docker" / "cli-plugins"
            if plugins.is_dir():
                os.symlink(plugins, Path(config, "cli-plugins"))
            result = subprocess.run(args, capture_output=True, text=True, env={**os.environ, "DOCKER_CONFIG": config})
    if result.returncode != 0:
        raise SystemExit(f"cannot resolve {ref}: {result.stderr.strip()}")
    return json.loads(result.stdout)["digest"]


def cmd_pin(shell, args):
    states = [s for s in gather(shell, args) if s.releasing]
    if not states:
        print("Nothing to pin.")
        return
    released = []
    for s in states:
        slug, tag = f"{OWNER}/{s.repo.name}", f"v{s.version}"
        run = publish_run(shell, slug, tag)
        if not run or run["conclusion"] != "success":
            state = f"{run['status']}/{run['conclusion']} {run['html_url']}" if run else "no publish run"
            raise SystemExit(f"{slug} {tag} is not published yet ({state}): run wait first.")
        digest = resolve_digest(shell, s.repo.image, s.version)
        sha = shell.gh_json(f"repos/{slug}/commits/{tag}")["sha"]
        pulls = shell.gh_json(f"repos/{slug}/commits/{sha}/pulls") or []
        released.append(Released(s.repo, s.version, digest, sha, pulls[0]["html_url"] if pulls else "",
                                 run["html_url"] if run else ""))
        print(f"{s.repo.image}: {pin_ref(s.repo.image, *s.pinned) if s.pinned else '(unpinned)'}\n"
              f"  -> {pin_ref(s.repo.image, s.version, digest)}")
    for path in compose_files():
        text = original = path.read_text()
        for item, s in zip(released, states):
            if s.pinned:
                text, _ = replace_pin(text, item.repo.image, s.pinned, (item.version, item.digest))
        if text != original:
            shell.write(path, text)
    doc_path = ROOT / RELEASES_DOC
    doc = doc_path.read_text()
    today = dt.date.today()
    title = release_title(released, today).split(" — ")[0] + f", released {today.day} {today:%B %Y}"
    for item, s in zip(released, states):
        if s.pinned:
            doc = update_compat_set(doc, item.repo.image, s.pinned, (item.version, item.digest), title)
    released_images = {item.repo.image for item in released}
    compose = (ROOT / SERVER_COMPOSE).read_text()
    unchanged = {}
    for repo in REPOS:
        pin = current_pin(compose, repo.image)
        if repo.image not in released_images and pin:
            unchanged[repo.image] = pin[0]
    doc = insert_release_section(doc, render_release_section(released, unchanged, today))
    shell.write(doc_path, doc)
    print("Next: make sync-release-images (sibling development Compose files), then verify.")


def check_clock_drift(shell: Shell) -> None:
    image = re.search(r"image: (nginx:\S+)", (ROOT / SERVER_COMPOSE).read_text()).group(1)
    docker_epoch = float(shell.read(["docker", "run", "--rm", "--entrypoint", "date", image, "+%s"]))
    drift = clock_drift(time.time(), docker_epoch)
    if drift > MAX_CLOCK_DRIFT_SECONDS:
        raise SystemExit(f"Docker clock is {drift:.0f}s off the host clock (limit {MAX_CLOCK_DRIFT_SECONDS}s): "
                         "JWT issued-at checks would fail. Restart Docker Desktop and retry.")
    print(f"Docker clock drift {drift:.1f}s: OK")


def cmd_verify(shell, args):
    steps = compose_config_commands()
    steps += [list(script) for script in CONTRACT_SCRIPTS]
    if not args.offline:
        steps.append(["python3", "scripts/verify-release-images.py", "--remote"])
    if shell.dry_run:
        for step in steps:
            print(f"[dry-run] {shlex.join(step)}")
        if args.compat:
            print("[dry-run] Docker clock drift check, then python3 scripts/verify-course-compatibility.py --output <tmp>")
        return
    failures = []
    for step in steps:
        print(f"+ {shlex.join(step)}", flush=True)
        if subprocess.run(step, cwd=ROOT).returncode != 0:
            failures.append(shlex.join(step))
    if args.compat and not failures:
        check_clock_drift(shell)
        output = Path(tempfile.mkdtemp(prefix="release-train-compat-"))
        output.rmdir()
        course_repo = find_course_repo(args.course_repo)
        subprocess.run(["git", "-C", str(course_repo), "fetch", "--quiet", "origin"], check=False)
        step = compat_command(output, course_repo, args.course_ref)
        print(f"+ {shlex.join(step)}", flush=True)
        if subprocess.run(step, cwd=ROOT).returncode != 0:
            failures.append(shlex.join(step))
    if failures:
        raise SystemExit("verify failed:\n  " + "\n  ".join(failures))
    print("verify: OK")


def find_course_repo(explicit: str | None) -> Path:
    """The ai-testers-api checkout: explicit path, a sibling of this repository, or ~/IdeaProjects."""
    candidates = [Path(explicit)] if explicit else [ROOT.parent / "ai-testers-api",
                                                    Path.home() / "IdeaProjects" / "ai-testers-api"]
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit("ai-testers-api checkout not found; pass --course-repo")


def compat_command(output: Path, course_repo: Path, course_ref: str) -> list[str]:
    """The pinned course suite: always the published lesson (origin/master by default), never a local branch."""
    return ["python3", "scripts/verify-course-compatibility.py", "--output", str(output),
            "--course-repo", str(course_repo), "--ref", course_ref, "--graphql-preview"]


def changed_release_files(shell: Shell) -> list[str]:
    candidates = [p.name for p in compose_files()] + [RELEASES_DOC]
    out = shell.read(["git", "status", "--porcelain", "--", *candidates])
    return [line[3:] for line in out.splitlines() if line]


def cmd_pr(shell, args):
    files = changed_release_files(shell)
    if not files:
        raise SystemExit("No pinned changes to propose (run pin first).")
    compose = (ROOT / SERVER_COMPOSE).read_text()
    head_compose = shell.read(["git", "show", f"HEAD:{SERVER_COMPOSE}"])
    changes = []
    for repo in REPOS:
        old, new = current_pin(head_compose, repo.image), current_pin(compose, repo.image)
        if old != new and new:
            changes.append(f"{repo.image} {new[0]}")
    title = "Release train: " + ", ".join(changes)
    branch = "release/" + "-".join(c.replace(" ", "-") for c in changes)
    body = ("Pins the release set produced by `scripts/release-train.py pin`.\n\n"
            + "\n".join(f"- `{c}`" for c in changes)
            + "\n\nVerified with `scripts/release-train.py verify`. Deploy after merge with "
            + "`scripts/release-train.py deploy --yes`.\n")
    shell.act(["git", "switch", "-c", branch])
    shell.act(["git", "add", "--", *files])
    shell.act(["git", "commit", "-m", title])
    shell.act(["git", "push", "-u", "origin", branch])
    url = shell.act(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body],
                    capture=True)
    if shell.dry_run:
        print("[dry-run] gh pr checks <pr> --watch --fail-fast" + (" && gh pr merge --squash" if args.merge else ""))
        return
    print(url)
    time.sleep(10)  # let GitHub register the checks before watching them
    shell.act(["gh", "pr", "checks", url, "--watch", "--fail-fast"])
    if args.merge:
        shell.act(["gh", "pr", "merge", url, "--squash", "--delete-branch"])


def cmd_deploy(shell, args):
    if not args.yes and not shell.dry_run:
        raise SystemExit("deploy changes production: rerun with --yes after the release PR is merged.")
    branch = shell.read(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    # main, or a clean worktree detached at origin/main (main may be checked out elsewhere).
    if branch not in ("main", "HEAD"):
        raise SystemExit(f"deploy runs from main or a checkout detached at origin/main, not {branch}.")
    shell.read(["git", "fetch", "--quiet", "origin", "main"])
    if shell.read(["git", "rev-parse", "HEAD"]) != shell.read(["git", "rev-parse", "origin/main"]):
        raise SystemExit("HEAD is not origin/main: pull the merged release first.")
    if shell.read(["git", "status", "--porcelain"]):
        raise SystemExit("working tree is not clean.")
    missing = [link for link in VAULT_LINKS if not os.path.lexists(ROOT / link)]
    if missing:
        raise SystemExit("missing Vault links (deploy from the main checkout): " + ", ".join(missing))
    new = current_pin((ROOT / SERVER_COMPOSE).read_text(), "backend")
    old = current_pin(shell.read(["git", "show", f"{args.since}:{SERVER_COMPOSE}"]), "backend")
    target = choose_deploy_target(old and old[0], new and new[0])
    print(f"backend {old[0] if old else '-'} -> {new[0]}: make {target}")
    shell.act(["make", target])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print actions; perform only reads")
    parser.add_argument("--only", help="comma-separated keys: " + ",".join(r.key for r in REPOS))
    parser.add_argument("--with-consumer", action="store_true", help="include jms-email-consumer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    sub.add_parser("tag")
    wait = sub.add_parser("wait")
    wait.add_argument("--timeout", type=int, default=3600, help="seconds (default 3600)")
    wait.add_argument("--interval", type=int, default=30, help="seconds between polls (default 30)")
    sub.add_parser("pin")
    verify = sub.add_parser("verify")
    verify.add_argument("--compat", action="store_true", help="also run the course compatibility suite")
    verify.add_argument("--offline", action="store_true", help="skip the registry manifest check")
    verify.add_argument("--course-repo", help="ai-testers-api checkout (default: sibling or ~/IdeaProjects)")
    verify.add_argument("--course-ref", default="origin/master", help="course revision (default origin/master)")
    pr = sub.add_parser("pr")
    pr.add_argument("--merge", action="store_true", help="squash-merge once CI is green")
    deploy = sub.add_parser("deploy")
    deploy.add_argument("--yes", action="store_true", help="really deploy to production")
    deploy.add_argument("--since", default="HEAD~1", help="ref holding the previously deployed pins")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    shell = Shell(args.dry_run)
    {"plan": cmd_plan, "tag": cmd_tag, "wait": cmd_wait, "pin": cmd_pin, "verify": cmd_verify,
     "pr": cmd_pr, "deploy": cmd_deploy}[args.command](shell, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
