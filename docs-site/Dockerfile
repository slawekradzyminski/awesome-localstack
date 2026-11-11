# Documentation wiki: MkDocs (Material) build, served by nginx under /docs/.
#
# Build context: docs-site/. The repository's docs/ directory is a second named
# context, `repo-docs` (Compose `additional_contexts`, or
# `docker build --build-context repo-docs=docs docs-site`).

FROM python:3.13.15-slim-trixie@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b AS build
WORKDIR /site
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-compile -r requirements.txt
# Mermaid is served from the site itself (no CDN at view time); the checksum
# pins the exact file.
ADD --checksum=sha256:581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8 \
    https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js \
    /mermaid/mermaid.min.js
COPY mkdocs.yml ./
COPY hooks ./hooks
COPY docs ./docs
COPY --from=repo-docs . /repo-docs
RUN mkdir -p docs/assets/javascripts \
    && cp /mermaid/mermaid.min.js docs/assets/javascripts/mermaid.min.js \
    && REPO_DOCS_DIR=/repo-docs mkdocs build --strict --site-dir /out/docs

FROM nginx:1.31.3-trixie@sha256:5a88c9c45479443d7be2eadc894b4ed0a9801bae03d97a5760ae13b5c2005942
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /out /usr/share/nginx/html
EXPOSE 80
