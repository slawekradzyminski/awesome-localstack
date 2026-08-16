# First-party container release automation

Awesome LocalStack consumes application images but does not build another repository's source for release. Each source repository owns its tests, version, Dockerfile, multi-platform build, SBOM, provenance, and registry publication. This repository owns the tested compatibility set, immutable Compose references, profile verification, deployment, and rollback.

## Repository ownership

| Source repository | Docker Hub image | Release gate owned by the repository |
| --- | --- | --- |
| `test-secure-backend` | `slawekradzyminski/backend` | Maven verification, integration tests, Docker smoke |
| `vite-react-frontend` | `slawekradzyminski/frontend` | unit tests, production build, browser tests, Docker smoke |
| `ollama-mock` | `slawekradzyminski/ollama-mock` | API contract tests and container smoke |
| `jms-email-consumer` | `slawekradzyminski/consumer` | Maven tests and Artemis-to-Mailpit integration smoke |

The same build is also published under the source repository name in GitHub Container Registry. Docker Hub remains the deployment registry during the migration because existing Compose releases already use those names. Do not assume two registries have the same manifest digest; record and pin the digest resolved from the registry used by Compose.

## Workflow contract

Normal pushes and pull requests run verification without publishing. A semantic version Git tag, or an explicit manual candidate invocation, runs the same release gates before building `linux/amd64` and `linux/arm64`. A release workflow must:

1. validate the requested image version against the Maven or npm project version;
2. test the exact tagged source;
3. authenticate to GHCR with `GITHUB_TOKEN`;
4. authenticate to Docker Hub with `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets;
5. publish semantic-version, commit-SHA, and stable `latest` tags where appropriate;
6. attach OCI source/revision labels, SBOM, and provenance;
7. report the immutable manifest digest in the workflow summary.

The Docker Hub token should be scoped to repository image writes and stored separately in every source repository. Do not copy a personal password into Actions. GHCR packages intended for anonymous production pulls must be public before Compose switches to them.

## GitHub Actions runtime baseline

The workflows use action generations whose JavaScript entrypoints target Node.js 24:

- `actions/checkout@v7.0.1`
- `actions/setup-node@v7.0.0`
- `actions/setup-java@v5.6.0`
- `docker/setup-qemu-action@v4.2.0`
- `docker/setup-buildx-action@v4.2.0`
- `docker/login-action@v4.6.0`
- `docker/metadata-action@v6.2.0`
- `docker/build-push-action@v7.3.0`

Dependabot monitors the `github-actions` ecosystem in every source repository. Review updates as ordinary supply-chain changes; do not suppress runner deprecation warnings by relying on GitHub's temporary forced runtime migration.

## Current compatibility set

| Service | Immutable image |
| --- | --- |
| Backend | `slawekradzyminski/backend:3.7.16@sha256:71cd8913a276f613200f35c83e846a0aa647a9313fa3e5e5f741390f4dc2dbac` |
| Frontend | `slawekradzyminski/frontend:3.7.14@sha256:e76e75bb6228a746e0685b9efb3a6ec71bde2cbbb330afbd231d91c02fcbd67b` |
| Consumer | `slawekradzyminski/consumer:3.3.7@sha256:545e2a091318e04d738915f19ba8a22220f943db108f76a9a31b296ca2cf1d61` |
| Ollama mock | `slawekradzyminski/ollama-mock:1.0.9@sha256:24852d0f78eb7ed208bb1eaaab1d912d29e5e74d6c28c2e6a31dd1cbcdedbdab` |

## LocalStack compatibility gate

The production compatibility set is the four first-party services above.
The main and `aitesters` variants do not have separate application release
lines: `aitesters-backend` must use the exact current backend reference and
`aitesters-frontend` must use the exact current frontend reference. Their
behavior differs through runtime profiles and routing, not through old images.
Previous application releases remain rollback references only.

`scripts/verify-release-images.py` checks that:

- each production service uses a `tag@sha256` reference;
- full and server agree on backend, frontend, and consumer releases;
- lightweight and server agree on backend, frontend, and model-mock releases;
- the server's `aitesters` services reuse the exact backend and frontend releases;
- the model-mock override agrees with the server model-mock release;
- this document records the exact selected references;
- with `--remote`, every manifest exists and contains both `linux/amd64` and `linux/arm64`.

Static pin verification runs in normal LocalStack CI. `.github/workflows/verify-release-images.yml` performs the registry check weekly and on manual request.

`scripts/verify-image-pins.py` extends the rule to every remotely pulled image
in all Compose profiles, the Jenkins Dockerfile, CI service containers, and the
PostgreSQL restore tool. Locally built `:local` images are the only exception.

## Release sequence

1. Merge a green source change to that repository's default branch.
2. Set the Maven or npm version intended for release and merge its verification change.
3. Create the matching signed or annotated `vX.Y.Z` tag, or run an explicit candidate from the intended commit.
4. Wait for both registry publications and copy the Docker Hub manifest digest from the workflow summary or `docker buildx imagetools inspect`.
5. Update the relevant `tag@sha256` references in the LocalStack profiles and the compatibility table.
6. Run `make sync-release-images` from this repository to propagate backend,
   frontend, and Ollama-mock references into the sibling development Compose
   files. The command fails if the expected workspace repositories or reference
   shapes are missing and validates each changed Compose file.
7. Run all Compose configuration checks,
   `python3 scripts/verify-image-pins.py`, and
   `python3 scripts/verify-release-images.py --remote`.
8. Run the affected direct-service, gateway, lightweight, and full gates.
9. Merge the LocalStack release PR, create an encrypted production backup when stateful services are affected, and deploy through Ansible.

An application release does not require rebuilding unchanged applications. It does require retaining their known-good immutable references in the reviewed compatibility set. Backward compatibility is maintained for persisted data and external contracts where required; the deployment does not keep stale application images running as compatibility variants.
