"""Unit tests for the pure parts of scripts/release-train.py (no network, no Docker).

Run: python3 -m unittest discover -s scripts -p test_release_train.py
"""

import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("release_train", Path(__file__).with_name("release-train.py"))
rt = importlib.util.module_from_spec(SPEC)
sys.modules["release_train"] = rt  # dataclasses resolve annotations through sys.modules
SPEC.loader.exec_module(rt)

OLD_DIGEST = "sha256:" + "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64
HIST_DIGEST = "sha256:" + "c" * 64


class VersionParsing(unittest.TestCase):
    def test_semver_with_and_without_prefix(self):
        self.assertEqual(rt.parse_version("3.17.0"), (3, 17, 0))
        self.assertEqual(rt.parse_version("v1.4.10"), (1, 4, 10))

    def test_non_release_versions(self):
        for text in ("3.17.0-SNAPSHOT", "1.0.0-rc1", "latest", "3.17"):
            self.assertIsNone(rt.parse_version(text), text)

    def test_pom_project_version_not_parent(self):
        pom = """<project xmlns="http://maven.apache.org/POM/4.0.0">
          <parent><groupId>org.springframework.boot</groupId><version>4.0.1</version></parent>
          <artifactId>svc</artifactId><version>1.4.0</version>
          <dependencies><dependency><version>9.9.9</version></dependency></dependencies>
        </project>"""
        self.assertEqual(rt.pom_version(pom), "1.4.0")

    def test_pom_without_namespace_and_inherited_version(self):
        self.assertEqual(rt.pom_version("<project><version>2.0.0</version></project>"), "2.0.0")
        with self.assertRaises(ValueError):
            rt.pom_version("<project><parent><version>1</version></parent></project>")

    def test_package_json(self):
        self.assertEqual(rt.package_version('{"name": "f", "version": "3.13.0"}'), "3.13.0")
        with self.assertRaises(ValueError):
            rt.package_version('{"name": "f"}')

    def test_latest_tag_is_semantic_not_lexical(self):
        self.assertEqual(rt.latest_tag(["v3.9.0", "v3.10.0", "v3.10.0-rc1", "nightly"]), "v3.10.0")
        self.assertIsNone(rt.latest_tag(["nightly"]))

    def test_plan_action(self):
        self.assertEqual(rt.plan_action("3.17.0", ["v3.16.0"], "3.16.0"), "tag, publish, pin")
        self.assertEqual(rt.plan_action("3.17.0", ["v3.17.0"], "3.16.0"), "pin")
        self.assertEqual(rt.plan_action("3.17.0", ["v3.17.0"], "3.17.0"), "up to date")
        self.assertTrue(rt.plan_action("3.17.0-SNAPSHOT", [], "3.16.0").startswith("skip"))
        self.assertTrue(rt.plan_action("3.16.0", ["v3.17.0"], "3.16.0").startswith("skip"))


class PinReplacement(unittest.TestCase):
    COMPOSE = (
        "services:\n"
        f"  backend:\n    image: slawekradzyminski/backend:3.16.0@{OLD_DIGEST}\n"
        f"  aitesters-backend:\n    image: slawekradzyminski/backend:3.16.0@{OLD_DIGEST}\n"
        f"  compat:\n    image: ${{COMPAT_BACKEND_IMAGE:-slawekradzyminski/backend:3.16.0@{OLD_DIGEST}}}\n"
        f"  warehouse-service:\n    image: slawekradzyminski/warehouse-service:1.3.0@{OLD_DIGEST}\n"
    )

    def test_current_pin(self):
        self.assertEqual(rt.current_pin(self.COMPOSE, "backend"), ("3.16.0", OLD_DIGEST))
        self.assertIsNone(rt.current_pin(self.COMPOSE, "frontend"))

    def test_conflicting_pins_are_an_error(self):
        text = self.COMPOSE + f"    image: slawekradzyminski/backend:3.15.0@{HIST_DIGEST}\n"
        with self.assertRaises(ValueError):
            rt.current_pin(text, "backend")

    def test_replace_every_current_reference_including_env_default(self):
        text, count = rt.replace_pin(self.COMPOSE, "backend", ("3.16.0", OLD_DIGEST), ("3.17.0", NEW_DIGEST))
        self.assertEqual(count, 3)
        self.assertNotIn("backend:3.16.0", text)
        self.assertIn(f"${{COMPAT_BACKEND_IMAGE:-slawekradzyminski/backend:3.17.0@{NEW_DIGEST}}}", text)
        self.assertIn(f"warehouse-service:1.3.0@{OLD_DIGEST}", text)

    def test_other_images_with_the_same_prefix_are_untouched(self):
        text = f"image: slawekradzyminski/backend-extra:3.16.0@{OLD_DIGEST}\n"
        self.assertEqual(rt.replace_pin(text, "backend", ("3.16.0", OLD_DIGEST), ("3.17.0", NEW_DIGEST))[1], 0)

    DOC = (
        "# Releases\n\n"
        "## Event feed: backend 3.16.0 — 11 November 2026\n\n"
        f"| `slawekradzyminski/backend:3.16.0@{OLD_DIGEST}` | PR | run |\n\n"
        "## Older — 1 November 2026\n\n"
        f"| `slawekradzyminski/backend:3.15.0@{HIST_DIGEST}` | PR | run |\n\n"
        "## Current compatibility set\n\n"
        "Commerce wave 3, released 11 November 2026:\n\n"
        "| Service | Immutable image |\n| --- | --- |\n"
        f"| Backend | `slawekradzyminski/backend:3.16.0@{OLD_DIGEST}` |\n\n"
        "## Release sequence\n\n"
        f"Rollback: `slawekradzyminski/backend:3.16.0@{OLD_DIGEST}`\n"
    )

    def test_compat_set_only_changes_current_section(self):
        doc = rt.update_compat_set(self.DOC, "backend", ("3.16.0", OLD_DIGEST), ("3.17.0", NEW_DIGEST),
                                   "Release train: backend 3.17.0, released 12 November 2026")
        start, end = rt.section_bounds(doc, rt.COMPAT_HEADING)
        self.assertIn(f"backend:3.17.0@{NEW_DIGEST}", doc[start:end])
        self.assertIn("Release train: backend 3.17.0, released 12 November 2026:\n", doc[start:end])
        # History rows (same digest in an older section, and after the section) stay.
        self.assertEqual(doc[:start], self.DOC[:start])
        self.assertTrue(doc.endswith(f"Rollback: `slawekradzyminski/backend:3.16.0@{OLD_DIGEST}`\n"))

    def test_compat_set_must_list_the_old_reference(self):
        with self.assertRaises(ValueError):
            rt.update_compat_set(self.DOC, "backend", ("3.15.0", HIST_DIGEST), ("3.17.0", NEW_DIGEST))


class ReleaseSection(unittest.TestCase):
    def released(self):
        backend = rt.REPOS[0]
        return [rt.Released(backend, "3.17.0", NEW_DIGEST, "0123456789abcdef",
                            "https://github.com/slawekradzyminski/test-secure-backend/pull/95",
                            "https://github.com/slawekradzyminski/test-secure-backend/actions/runs/1")]

    def test_render(self):
        section = rt.render_release_section(self.released(), {"frontend": "3.12.0"}, dt.date(2026, 11, 12))
        self.assertTrue(section.startswith("## Release train: backend 3.17.0 — 12 November 2026\n"))
        self.assertIn(f"| `slawekradzyminski/backend:3.17.0@{NEW_DIGEST}` | "
                      "[PR #95](https://github.com/slawekradzyminski/test-secure-backend/pull/95), `0123456` | "
                      "[run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/1) |", section)
        self.assertIn("| `slawekradzyminski/frontend:3.12.0` | unchanged | unchanged |", section)
        self.assertTrue(section.endswith("\n\n"))

    def test_render_without_links(self):
        item = rt.Released(rt.REPOS[1], "1.4.0", NEW_DIGEST)
        section = rt.render_release_section([item], {}, dt.date(2026, 11, 12))
        self.assertIn(f"| `slawekradzyminski/warehouse-service:1.4.0@{NEW_DIGEST}` | — | — |", section)

    def test_insert_above_newest_dated_section(self):
        doc = PinReplacement.DOC
        section = rt.render_release_section(self.released(), {}, dt.date(2026, 11, 12))
        updated = rt.insert_release_section(doc, section)
        self.assertLess(updated.index("## Release train"), updated.index("## Event feed"))
        self.assertGreater(updated.index("## Release train"), updated.index("# Releases"))

    def test_render_matches_the_dated_heading_pattern(self):
        section = rt.render_release_section(self.released(), {}, dt.date(2026, 11, 2))
        once = rt.insert_release_section("# R\n\n## Current compatibility set\n", section)
        self.assertIn("— 2 November 2026", once)
        # The new section is itself recognized as the newest dated section next time.
        twice = rt.insert_release_section(once, "## Next — 3 November 2026\n\n")
        self.assertLess(twice.index("## Next"), twice.index("## Release train"))

    def test_insert_uses_dates_not_document_order(self):
        doc = ("# R\n\n## Maintenance — 22 October 2026\n\nx\n\n"
               "## Event feed — 11 November 2026\n\ny\n\n## Older — 8 November 2026\n")
        updated = rt.insert_release_section(doc, "## New — 12 November 2026\n\n")
        self.assertLess(updated.index("## Maintenance"), updated.index("## New"))
        self.assertLess(updated.index("## New"), updated.index("## Event feed"))


class DeployTarget(unittest.TestCase):
    def test_backend_version_change_needs_the_coordinated_upgrade(self):
        self.assertEqual(rt.choose_deploy_target("3.16.0", "3.17.0"), "ansible-deploy-backend-upgrade")

    def test_unchanged_backend_uses_the_normal_deploy(self):
        self.assertEqual(rt.choose_deploy_target("3.16.0", "3.16.0"), "ansible-deploy")

    def test_unknown_previous_backend_is_treated_as_a_change(self):
        self.assertEqual(rt.choose_deploy_target(None, "3.17.0"), "ansible-deploy-backend-upgrade")
        with self.assertRaises(ValueError):
            rt.choose_deploy_target("3.16.0", None)

    def test_clock_drift(self):
        self.assertEqual(rt.clock_drift(100.0, 93.0), 7.0)
        self.assertEqual(rt.clock_drift(93.0, 100.0), 7.0)


class Parser(unittest.TestCase):
    def test_global_dry_run_and_subcommands(self):
        args = rt.build_parser().parse_args(["--dry-run", "deploy"])
        self.assertTrue(args.dry_run)
        self.assertFalse(args.yes)
        self.assertEqual(rt.build_parser().parse_args(["verify", "--compat"]).compat, True)

    def test_consumer_is_optional(self):
        args = rt.build_parser().parse_args(["plan"])
        self.assertNotIn("consumer", [r.key for r in rt.selected_repos(args)])
        args = rt.build_parser().parse_args(["--with-consumer", "plan"])
        self.assertIn("consumer", [r.key for r in rt.selected_repos(args)])
        args = rt.build_parser().parse_args(["--only", "backend,consumer", "plan"])
        self.assertEqual([r.key for r in rt.selected_repos(args)], ["backend", "consumer"])


if __name__ == "__main__":
    unittest.main()


class CompatCommandTest(unittest.TestCase):
    def test_passes_the_course_repo_and_published_ref(self):
        command = rt.compat_command(Path("/tmp/out"), Path("/x/ai-testers-api"), "origin/master")
        self.assertEqual(command[:4], ["python3", "scripts/verify-course-compatibility.py", "--output", "/tmp/out"])
        self.assertIn("--course-repo", command)
        self.assertEqual(command[command.index("--ref") + 1], "origin/master")
        self.assertIn("--graphql-preview", command)



class ChangedReleaseFiles(unittest.TestCase):
    class FakeShell:
        def __init__(self, output: str):
            self.output = output
            self.calls: list[list[str]] = []

        def read(self, args, **_kwargs):
            self.calls.append(args)
            # Shell.read strips stdout, which removed the first status column of porcelain output.
            return self.output.strip()

    def test_keeps_the_first_file_name_whole(self):
        shell = self.FakeShell("docker-compose.compatibility.yml\ndocs/CONTAINER_RELEASES.md\n")
        self.assertEqual(rt.changed_release_files(shell), ["docker-compose.compatibility.yml", "docs/CONTAINER_RELEASES.md"])
        self.assertEqual(shell.calls[0][:4], ["git", "diff", "--name-only", "HEAD"])

    def test_no_changes_is_empty(self):
        self.assertEqual(rt.changed_release_files(self.FakeShell("")), [])
