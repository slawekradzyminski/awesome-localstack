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

## October 2026 JVM and Node security maintenance

[CVE-2026-91403](https://openjdk.org/groups/vulnerability/advisories/2026-10-21)
concerns compromised intermediate CA certificates. The reviewed mitigation is a
frozen upstream `blocked.certs` file, not an unsupported claim that the old Java
version has become a patched distribution. See [provenance, reproduction and
renewal](../security/java/README.md).

Every JVM in the full, lightweight, server, model-mock and compatibility profiles
has a read-only, content-addressed blocklist mount. Missing source files fail;
new content changes the bind source path so Compose recreates the JVM and remounts
the new inode. Ansible copies the artifact before convergence. The optional
Jenkins build and the backend/consumer/model-mock source Dockerfiles copy the
same checked artifact into their JVMs. The first-party image references below
are retained; no application version, schema or encryption key migration is
introduced by this mitigation.

`python3 scripts/verify-java-security.py` validates the frozen upstream inputs,
23 JVM mounts, Ansible asset copy and Jenkins coverage. All modified Compose
profiles pass config validation. The existing image-pin and release-set checks
pass. Two frozen configuration mutants compiled and were killed (sandbox JVM
omission, mutable bind source); zero survived/invalid/equivalent candidates were
reported. No PIT/Stryker-selected application logic changed.

All three installed Homebrew JVMs (25.0.2, 21.0.12.1 and 25.0.4.1) now reject all
35 certificates in the upstream fixture. Previous files were backed up before
replacement, and all existing vendor blocks were preserved. Disposable Temurin
25.0.3 and Red Hat Keycloak 21.0.12 runtimes pass the same check with the mount.
Running Java processes must be recreated to reload cached certificate state.

Frontend source now selects Node >=24.22.1 <25, pins the 24.22.1 Alpine build
image, and refreshes the vulnerable npm packages. Full and production-only npm
audits report zero findings. Lint, TypeScript, all 533 coverage tests and the
production build passed, and the built nginx image served login, products,
WebMCP and their entry assets. These frontend source changes still require a
normal source-owned application image release before its published image pin
can change; existing immutable tags are not overwritten.

### Production verification — 22 October 2026

The Ansible rollout completed with 117 successful tasks, 14 changes, zero
failures and zero unreachable hosts. Its encrypted PostgreSQL pre-deployment
backup completed before app convergence. Published application references stayed
unchanged. Both backends, the consumer, model mock and Artemis were recreated
with the content-addressed read-only mount. All five runtime checksums match
`2596bb6dda83c66d96c5a252d7b2ae1f24cc1ae3f1890223b4f3591a8d52bf10`.

Offline probes inside all five running production services reject all 35 upstream
fixture certificates: Java 25.0.4 on both backends and Java 25.0.3 on the other
three services. Probe helpers were temporary and removed from the containers.
No customer data was needed for these checks. The normal deployment checks passed
exact image IDs, heap budgets, PostgreSQL, authentication isolation, direct and
proxied GraphQL/gRPC, Artemis/consumer/Mailpit delivery and monitoring.
Public login and OpenAPI routes return 200 on both domains; the private Mailpit
route remains 404. There was no GitHub Actions dispatch or image publication.

A tagged `java_security` Ansible verification now checks the frozen blocklist
checksum in each JVM on future deploys and standalone verification runs. The
running local lightweight stack still uses its existing containers: recreating
its in-memory H2 backend resets local demo data, so that action is pending the
owner's choice. The reviewed source configuration is ready, but do not describe
those existing local containers as mitigated until they are recreated.

Private deployment/runtime receipts are stored under
`~/.config/awesome-localstack-security/`. Source changes in this maintenance
remain local; the server received the verified Compose/configuration artifacts
through the normal Ansible copy/convergence procedure.

## Current compatibility set

| Service | Immutable image |
| --- | --- |
| Backend | `slawekradzyminski/backend:3.9.1@sha256:b1931ada6be3b1d5a5ef75837a146ae32f4fa8739b51011b8ec81ce9b70c6ed3` |
| Frontend | `slawekradzyminski/frontend:3.9.0@sha256:fffc051a17fec76a4323facbe97aa29490d71ec33f156dd5ee0f1020c5e68e15` |
| Consumer | `slawekradzyminski/consumer:3.3.7@sha256:545e2a091318e04d738915f19ba8a22220f943db108f76a9a31b296ca2cf1d61` |
| Ollama mock | `slawekradzyminski/ollama-mock:1.0.9@sha256:24852d0f78eb7ed208bb1eaaab1d912d29e5e74d6c28c2e6a31dd1cbcdedbdab` |

## Backend 3.9.1 traffic preview patch

Backend [PR #76](https://github.com/slawekradzyminski/test-secure-backend/pull/76)
normalizes NUL control characters to visible U+2400 markers in traffic previews.
This keeps preview character lengths consistent and preserves ordinary Unicode.
A guarded Flyway callback prepares legacy OID payloads before the unchanged V6
conversion; it is a no-op for already-migrated text columns. Newly queued payloads
use the same normalization. No business schema or MFA-key change is added by this
patch.

The source checks passed 592 unit and 46 integration tests, including repeated,
leading, and trailing null bytes, all four payload columns, idempotence, and
PostgreSQL persistence/read-back. Targeted persistence mutation feedback detected
23 of 25 mutants with no reachability gaps; the two residual boundary cases remain
equivalent (equal-length clipping and an extra empty flush). A compiling semantic
mutation that normalizes only the first null byte was detected by the migration
regression. Use the coordinated backend-upgrade target and encrypted-backup
procedure described below whenever applying V6.

Production rollout completed on 2026-10-20 using the coordinated upgrade target:
122 Ansible tasks passed, with zero failures or unreachable hosts. Both backend
instances matched the reviewed 3.9.1 image digest. Authenticated direct/proxied
GraphQL, anonymous rejection, gRPC listeners, authentication isolation, JMS,
monitoring, and public HTTPS checks passed. PostgreSQL reports successful V1–V6
migrations and all four traffic payload columns as text; the eight products and
one existing order remain present. The quiesced encrypted rollback backup is
`awesome-testdb-20261020T202854Z-backend-upgrade-quiesced.sql.gz.enc` in the
production PostgreSQL daily backup directory.

The published 3.9.1 image also passed all 311 unchanged latest `l20` course tests
against PostgreSQL, with no skips, retries, or failures, at course revision
`c6f7aee44150ee3e46aa27aad7b340e729e8fada`. Direct/proxied GraphQL and the
native gRPC listener passed in the same disposable stack. The
[release workflow](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/39488051264),
[backend CI](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/39492360830),
and [LocalStack CI](https://github.com/slawekradzyminski/awesome-localstack/actions/runs/39492106973)
are green.

## Backend 3.9.0 upgrade

[Release workflow](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/39480058223) passed all source-owned gates and published both supported architectures with SBOM and provenance.

Backend [PR #74](https://github.com/slawekradzyminski/test-secure-backend/pull/74)
reduces GraphQL database work, bounds and batches traffic capture, replaces
PostgreSQL traffic large objects with text, preserves reads of legacy MFA
ciphertext, and uses the current encryption API for new MFA writes.

Before publication, the unchanged latest `l20` suite at course revision
`c6f7aee44150ee3e46aa27aad7b340e729e8fada` passed 311/311 on H2 and
311/311 on PostgreSQL 16.14 with Flyway V1–V6 and Hibernate validation. There
were no skips or retries. Backend verification passed 590 unit and 44
integration tests, with 25 focused checks after the final media guard change.
PITest review is documented in the backend performance audit. Two additional
frozen semantic mutants (wrong legacy MFA key and discarded immediate traffic
reads) compiled and were killed by passing baseline tests. A third mutation
that backs up before quiescing was killed by the upgrade-order check.

Use `make ansible-deploy-backend-upgrade` for this release. The opt-in role
pulls the selected immutable image before interrupting requests, stops both
old backend instances with a 60-second graceful shutdown, and creates a second
encrypted PostgreSQL backup after writes stop. Ordinary deployment remains
available through `make ansible-deploy`. Both paths retain bounded warning-alert
silencing through successful verification; the critical alert remains active.
Existing MFA encryption password/salt must remain unchanged.

V5 adds commerce/traffic indexes; V6 preserves existing payload contents while
converting OID columns to text and unlinking converted large objects. Old binaries
cannot read the migrated schema or newly written v2 MFA ciphertext. Do not use a
rolling deployment or revert the image alone. To roll back, stop the new backends,
restore the quiesced pre-upgrade database backup, restore the previous image pins,
and redeploy with the same MFA keys. Restoring that backup discards subsequent
writes, so assess any post-upgrade activity before rollback.

Previous backend reference:
`slawekradzyminski/backend:3.8.1@sha256:c60932c6cd1a907451ee08c34837694bae4efdb15b76bb885f90f057f5749c9a`.

## Frontend 3.9.0 WebMCP release

Frontend [PR #74](https://github.com/slawekradzyminski/vite-react-frontend/pull/74),
commit `16fe782`, adds native WebMCP tools to the existing `/products` page and
an explicit `/webmcp` fault lab. The
[3.9.0 release workflow](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/37782592962)
passed unit/build, container smoke, all browser shards, REST/GraphQL commerce,
and the new native WebMCP suite before publishing amd64/arm64 images with
provenance and SBOM. Local verification passed 533 unit tests, 22 existing shop
browser tests and 19 native WebMCP cases repeated three times (57/57).

The three page tools reuse existing authenticated application clients. Search
updates visible catalogue filters; cart reads/writes update the shared query
cache. Deliberate faults are restricted to the lab. Native tool access remains
experimental and requires a compatible browser with WebMCP enabled; normal
shopping works without it. No backend, database or secret change is required.
The backend, consumer and Ollama mock retain their reviewed releases.

On 8 October 2026, the
[stack compatibility CI](https://github.com/slawekradzyminski/awesome-localstack/actions/runs/37784077866)
passed all eight jobs. `make ansible-deploy` created the encrypted pre-deploy
PostgreSQL backup and completed with zero failed or unreachable tasks. The
playbook verified exact running image IDs and application protocols and expired
the deployment alert silence. External browser smoke checks passed on both
`awesome.byst.re` and `aitesters.byst.re`: HTTPS routes/images, anonymous route
protection, three native tools, visible search/stock/order controls, independent
saved-cart agreement, route cleanup, healthy lab defaults, a 390px viewport,
ordinary-browser fallback and GraphQL tool reads. The live checks used existing
deployment accounts and made no cart writes. The blog article remains a local,
unpublished draft.

Previous frontend reference for rollback:
`slawekradzyminski/frontend:3.8.1@sha256:342fabfc98da79af4bad7d4b90dae23818b67f1c16c0a1bfc8ed694f02210310`.

## Backend and frontend 3.8.1 release

Backend [PR #63](https://github.com/slawekradzyminski/test-secure-backend/pull/63)
and frontend [PR #70](https://github.com/slawekradzyminski/vite-react-frontend/pull/70)
set the patch versions after the test and dependency maintenance work. Their
[backend release](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/36323924572)
and [frontend release](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/36323899973)
passed their source-owned gates and published both supported architectures.
This release introduces no database migration.
The unchanged latest lesson `l20` suite at course commit
`5005edfff470092c9083d2716c7fdfab0ad9a763` passed all 190 tests against
the published backend image, with no skips, failures, or retries. The same
disposable stack verified authenticated GraphQL directly and through nginx,
rejected unauthenticated GraphQL, and opened the loopback-only gRPC listener.
The [LocalStack main CI](https://github.com/slawekradzyminski/awesome-localstack/actions/runs/36325214814)
passed all seven jobs. On 27 September 2026, `make ansible-deploy` created an
encrypted pre-deployment PostgreSQL backup and deployed these exact backend and
frontend references to both `awesome.byst.re` and `aitesters.byst.re`. The
playbook completed with no failed tasks, verified the running image IDs and
application protocols, and removed the temporary alert silence. External HTTPS
checks returned `200` for `/login`, `/v3/api-docs`, `/images/iphone.png`, and
`/actuator/health` on both sites.

Rollback application references: backend
`slawekradzyminski/backend:3.8.0@sha256:0fb27619c9048b93dcf38bc92c48ede0ff762d4956c009ef62a0f981cd112a9f`
and frontend
`slawekradzyminski/frontend:3.8.0@sha256:302e921c505c6b76a15c25fadcd6fb8ab3ff611c28b74a66c3a471b55ac9f8e5`.
Restore both references in every production Compose profile and the sibling
development Compose files before redeploying.

## Backend 3.7.17 release

Backend source: [PR #56](https://github.com/slawekradzyminski/test-secure-backend/pull/56), commit `b4973a53b1697f84a479b6aceeb870cd48423091`. The [release workflow](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/34686783798) passed Maven, integration, local-startup, and Docker gates and published both supported architectures.

This release corrects generated OpenAPI contracts and includes the previously merged pagination, cart/order, and QR cleanup. It introduces no database migrations. The unchanged lesson `l20` suite passed all 190 tests against backend 3.7.16 before rollout; the same suite is the post-deployment compatibility gate.

Rollback backend reference: `slawekradzyminski/backend:3.7.16@sha256:71cd8913a276f613200f35c83e846a0aa647a9313fa3e5e5f741390f4dc2dbac`. Restore that reference consistently across the Compose profiles, synchronize the sibling development references, validate the files, and redeploy through Ansible. Preserve runtime configuration and database volumes.

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

## GraphQL/gRPC 3.8.0 release

Backend [PR #59](https://github.com/slawekradzyminski/test-secure-backend/pull/59)
and tag `v3.8.0` add GraphQL commerce, GraphiQL, optional native admin inventory
RPCs, and metadata-only protocol traffic. The
[release workflow](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/35515279059)
passed all gates and published both supported architectures with provenance and
SBOM. No database migration is introduced.

The frontend counterpart is tracked in
[PR #67](https://github.com/slawekradzyminski/vite-react-frontend/pull/67).
The [release record](GRAPHQL_GRPC_RELEASE.md) tracks historical lesson results,
artifact verification, deployment, and public smoke tests. The existing user
instruction excludes rollback work for this rollout.
