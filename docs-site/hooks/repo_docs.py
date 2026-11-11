"""MkDocs hook: publish this repository's docs/*.md as the Reference section.

docs/ stays the source of truth. Each file is added to the build as
reference/<NAME>.md without copying it into docs-site/docs. Links inside those
files that point outside docs/ (../README.md, ../ansible/...) are rewritten to
GitHub so the strict build does not report them as broken.

The source directory is $REPO_DOCS_DIR, or ../docs next to docs-site/.
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path

from mkdocs.structure.files import File

GITHUB_BLOB = "https://github.com/slawekradzyminski/awesome-localstack/blob/main/"
REFERENCE_DIR = "reference"
# Inline links and images: ](target) or ](target "title")
LINK = re.compile(r"\]\((?P<target>[^)\s#]+)(?P<anchor>#[^)\s]*)?(?P<title>\s+\"[^\"]*\")?\)")


def _source_dir(config) -> Path:
    configured = os.environ.get("REPO_DOCS_DIR")
    if configured:
        return Path(configured).resolve()
    return (Path(config.config_file_path).parent.parent / "docs").resolve()


def on_files(files, config):
    source = _source_dir(config)
    markdown = sorted(source.glob("*.md"))
    if not markdown:
        raise RuntimeError(f"No repository docs found in {source}; set REPO_DOCS_DIR")
    for path in markdown:
        files.append(File.generated(config, f"{REFERENCE_DIR}/{path.name}", abs_src_path=str(path)))
    return files


def _rewrite(match: re.Match, available: set[str]) -> str:
    target = match.group("target")
    anchor = match.group("anchor") or ""
    title = match.group("title") or ""
    if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("/"):
        return match.group(0)
    if target in available:
        return match.group(0)
    # Resolve relative to docs/ in the repository, then point at GitHub.
    repo_path = posixpath.normpath(posixpath.join("docs", target))
    if repo_path.startswith(".."):
        return match.group(0)
    return f"]({GITHUB_BLOB}{repo_path}{anchor}{title})"


def on_page_markdown(markdown, page, config, files):
    if not page.file.src_uri.startswith(f"{REFERENCE_DIR}/"):
        return markdown
    available = {
        posixpath.basename(f.src_uri)
        for f in files
        if f.src_uri.startswith(f"{REFERENCE_DIR}/")
    }
    note = (
        '!!! info "Source"\n'
        f"    This page is `docs/{posixpath.basename(page.file.src_uri)}` from the repository, "
        "published unchanged. Edit it there.\n\n"
    )
    body = LINK.sub(lambda m: _rewrite(m, available), markdown)
    # Keep the H1 first so the page title stays the document title.
    lines = body.split("\n", 1)
    if lines[0].startswith("# ") and len(lines) == 2:
        return f"{lines[0]}\n\n{note}{lines[1]}"
    return note + body
