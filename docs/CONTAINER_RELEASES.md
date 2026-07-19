# First-party container release automation

Awesome LocalStack consumes application images but does not build another repository's source for release. Each source repository owns its tests, version, Dockerfile, multi-platform build, SBOM, provenance, and registry publication. This repository owns the tested compatibility set, immutable Compose references, profile verification, deployment, and rollback.

## Repository ownership

| Source repository | Docker Hub image | Release gate owned by the repository |
| --- | --- | --- |
| `test-secure-backend` | `slawekradzyminski/backend` | Maven verification, integration tests, Docker smoke |
| `vite-react-frontend` | `slawekradzyminski/frontend` | unit tests, production build, course-compatible browser tests, Docker smoke |
| `ai-learning-lab` | `slawekradzyminski/ai-learning-lab` | unit tests, extraction audit, course browser suite, Docker smoke |
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

## LocalStack compatibility gate

The production compatibility set is the five first-party services above. `scripts/verify-release-images.py` checks that:

- each production service uses a `tag@sha256` reference;
- the full, lightweight, model-mock, and server profiles agree on shared mock and consumer releases;
- the AI Lab release runbook records the exact selected references;
- with `--remote`, every manifest exists and contains both `linux/amd64` and `linux/arm64`.

Static pin verification runs in normal LocalStack CI. `.github/workflows/verify-release-images.yml` performs the registry check weekly and on manual request.

## Release sequence

1. Merge a green source change to that repository's default branch.
2. Set the Maven or npm version intended for release and merge its verification change.
3. Create the matching signed or annotated `vX.Y.Z` tag, or run an explicit candidate from the intended commit.
4. Wait for both registry publications and copy the Docker Hub manifest digest from the workflow summary or `docker buildx imagetools inspect`.
5. Update the relevant `tag@sha256` references in the LocalStack profiles and the compatibility table.
6. Run all Compose configuration checks and `python3 scripts/verify-release-images.py --remote`.
7. Run the affected direct-service, gateway, lightweight, full, and recorded-course gates.
8. Merge the LocalStack release PR, create an encrypted production backup when stateful services are affected, and deploy through Ansible.

An application release does not require rebuilding unchanged applications. It does require retaining their known-good immutable references in the reviewed compatibility set.
