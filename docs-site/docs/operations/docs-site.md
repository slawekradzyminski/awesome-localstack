# This documentation site

## How it is built

| Part | Choice |
| --- | --- |
| Generator | MkDocs 1.6 with the Material theme (search, dark mode, Mermaid, tabs) |
| Sources | `docs-site/docs/` (wiki pages) + the repository's `docs/*.md`, published unchanged under **Reference** by `docs-site/hooks/repo_docs.py` |
| Python pins | `docs-site/requirements.txt` (exact versions) |
| Mermaid | `mermaid.min.js` 11.17.2, downloaded at image build time with a pinned SHA-256 and served by the site itself (no CDN at view time); no web fonts are loaded. The header's repository badge asks the GitHub API for star and fork counts |
| Image | `docs-site/Dockerfile`: `python:3.13-slim` builds with `mkdocs build --strict`, `nginx:1.31.3-trixie` serves `/docs/` (both pinned by digest) |
| Runtime | nginx with one worker, `mem_limit: 32m`, healthcheck on `/docs/`; pages are sent with `Cache-Control: no-cache` so a rebuilt wiki shows up at once, assets are cached for 7 days |

`docs/` stays the source of truth for the documents that already existed; the
hook adds each file to the build as `reference/<NAME>.md` and rewrites links
that leave `docs/` (for example `../README.md`) to GitHub.

## Routing

The `docs` service listens on port 80 inside the Compose network and serves
the site under `/docs/`. Every gateway server block (local, `awesome.byst.re`,
`aitesters.byst.re`) proxies `/docs/` to it through
`set $docs_upstream http://docs:80;`, so the gateway still starts — and the
shop keeps working — when the docs container is missing; only `/docs/` then
answers `502`. `/docs` redirects to `/docs/`.

## Deployment choice: build on deploy

The image is **built from the repository on the target machine** instead of
being published to a registry:

- It contains only static files derived from this repository, so a registry
  release would add a publishing workflow and a digest bump for every
  documentation edit without adding safety.
- It follows the rule already used for `ollama-dmr-adapter`: a Compose service
  with a `build` section and an `image` ending in `:local` is exempt from
  digest pinning in `scripts/verify-image-pins.py`. Its **base images** are
  pinned by digest, and `verify-image-pins.py` checks `docs-site/Dockerfile`
  too.
- Ansible copies `docs/` and `docs-site/` to the server and runs
  `docker compose build docs` before `docker compose up`; the `verify` role then
  checks that the running container uses the freshly built image ID and that
  `/docs/` returns `200` directly and through both public hosts.

The build needs PyPI and jsDelivr access from the build host and takes well
under a minute after the first run (the dependency layer is cached).

## Working on the docs

```bash
python3 -m venv .venv && .venv/bin/pip install -r docs-site/requirements.txt
.venv/bin/mkdocs serve -f docs-site/mkdocs.yml          # http://127.0.0.1:8000/docs/
.venv/bin/mkdocs build --strict -f docs-site/mkdocs.yml # what CI runs
```

Diagrams render in `mkdocs serve` only after the Mermaid file exists locally:

```bash
curl -fsSL -o docs-site/docs/assets/javascripts/mermaid.min.js \
  https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js
```

(the file is git-ignored). To test the container exactly as deployed:

```bash
docker build --build-context repo-docs=docs -t awesome-localstack/docs:local docs-site
docker run --rm -p 8090:80 awesome-localstack/docs:local   # http://localhost:8090/docs/
```

CI (`.github/workflows/test.yml`, job `verifyDocsSite`) runs the strict build,
which fails on broken internal links and anchors, and builds the image.

!!! note "Maintenance"
    Material for MkDocs announces end of life on 5 May 2027 (critical fixes
    until then) and names Zensical, which reads the same `mkdocs.yml`, as its
    successor. Plan the switch before that date; until then bump the pins in
    `requirements.txt` deliberately and keep the strict build green.

## Writing rules

- English only; describe what the code and configuration do, and link the
  source document instead of copying long tables.
- Keep diagrams narrow: top-to-bottom layouts, a few words per label, at most
  four participants in a sequence diagram; put endpoints and field names in
  the text or a table below. A diagram wider than the page is scaled down
  until its text is unreadable. Every diagram can also be clicked to open at
  full size (`docs/assets/javascripts/diagram-zoom.js`).
- Never use `;` inside a Mermaid sequence diagram: it ends the statement, the
  diagram fails to parse and the page shows the raw source. The hook turns it
  into a build warning, so the strict build fails.
- New pages must be added to `nav` in `docs-site/mkdocs.yml`.
- New files in `docs/` appear automatically under Reference once added to the
  `Reference` section of `nav`.
