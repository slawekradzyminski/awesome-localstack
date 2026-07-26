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

- `actions/checkout@v7.0.0`
- `actions/setup-node@v7.0.0`
- `actions/setup-java@v5.6.0`
- `docker/setup-qemu-action@v4.2.0`
- `docker/setup-buildx-action@v4.2.0`
- `docker/login-action@v4.4.0`
- `docker/metadata-action@v6.2.0`
- `docker/build-push-action@v7.3.0`

Dependabot monitors the `github-actions` ecosystem in every source repository. Review updates as ordinary supply-chain changes; do not suppress runner deprecation warnings by relying on GitHub's temporary forced runtime migration.

## Current compatibility set

| Service | Immutable image |
| --- | --- |
| Backend | `slawekradzyminski/backend:3.7.13@sha256:c7c7d3298bd2b140bc1f914c147d1932b6d493d2a16a793a350f3ad9bde6fa69` |
| Frontend | `slawekradzyminski/frontend:3.7.11@sha256:b1c0bb05b1aaf5ca8e38552dcb137d8ba908975fa1c8c0eb7d80ca003afa03f8` |
| Consumer | `slawekradzyminski/consumer:3.3.5@sha256:1da0e051f9fba1492e6597ae385aee64a78ebc434928bddd84bd1fd8a222fe96` |
| Ollama mock | `slawekradzyminski/ollama-mock:1.0.7@sha256:623170cfb5bbe18b8584ca3683c69023af2267d3534812136eecef39e10f9872` |

## LocalStack compatibility gate

The production compatibility set is the four first-party services above.
`scripts/verify-release-images.py` checks that:

- each production service uses a `tag@sha256` reference;
- full and server agree on backend, frontend, and consumer releases;
- lightweight and server agree on backend, frontend, and model-mock releases;
- the model-mock override agrees with the server model-mock release;
- this document records the exact selected references;
- with `--remote`, every manifest exists and contains both `linux/amd64` and `linux/arm64`.

Static pin verification runs in normal LocalStack CI. `.github/workflows/verify-release-images.yml` performs the registry check weekly and on manual request.

## Release sequence

1. Merge a green source change to that repository's default branch.
2. Set the Maven or npm version intended for release and merge its verification change.
3. Create the matching signed or annotated `vX.Y.Z` tag, or run an explicit candidate from the intended commit.
4. Wait for both registry publications and copy the Docker Hub manifest digest from the workflow summary or `docker buildx imagetools inspect`.
5. Update the relevant `tag@sha256` references in the LocalStack profiles and the compatibility table.
6. Run all Compose configuration checks and `python3 scripts/verify-release-images.py --remote`.
7. Run the affected direct-service, gateway, lightweight, and full gates.
8. Merge the LocalStack release PR, create an encrypted production backup when stateful services are affected, and deploy through Ansible.

An application release does not require rebuilding unchanged applications. It does require retaining their known-good immutable references in the reviewed compatibility set.
