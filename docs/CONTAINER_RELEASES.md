# First-party container release automation

Awesome LocalStack consumes application images but does not build another repository's source for release. Each source repository owns its tests, version, Dockerfile, multi-platform build, SBOM, provenance, and registry publication. This repository owns the tested compatibility set, immutable Compose references, profile verification, deployment, and rollback.

## Repository ownership

| Source repository | Docker Hub image | Release gate owned by the repository |
| --- | --- | --- |
| `test-secure-backend` | `slawekradzyminski/backend` | Maven verification, integration tests, Docker smoke |
| `vite-react-frontend` | `slawekradzyminski/frontend` | unit tests, production build, browser tests, Docker smoke |
| `ollama-mock` | `slawekradzyminski/ollama-mock` | API contract tests and container smoke |
| `jms-email-consumer` | `slawekradzyminski/consumer` | Maven tests and Artemis-to-Mailpit integration smoke |
| `warehouse-service` | `slawekradzyminski/warehouse-service` | Maven tests, GraalVM native build and container smoke |
| `payment-service` | `slawekradzyminski/payment-service` | Maven tests, GraalVM native build and container smoke |

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
same checked artifact into their JVMs. The initial mitigation retained the existing first-party image references.
The follow-up image release is recorded below; neither step introduces a schema
or encryption key migration.

`python3 scripts/verify-java-security.py` validates the frozen upstream inputs,
23 JVM mounts, Ansible asset copy and Jenkins coverage. All modified Compose
profiles pass config validation. The existing image-pin and release-set checks
pass.

All three installed Homebrew JVMs (25.0.2, 21.0.12.1 and 25.0.4.1) now reject all
35 certificates in the upstream fixture. Previous files were backed up before
replacement, and all existing vendor blocks were preserved. Disposable Temurin
25.0.3 and Red Hat Keycloak 21.0.12 runtimes pass the same check with the mount.
Running Java processes must be recreated to reload cached certificate state.

Frontend source now selects Node >=24.22.1 <25, pins the 24.22.1 Alpine build
image, and refreshes the vulnerable npm packages. Full and production-only npm
audits report zero findings. Lint, TypeScript, all 533 coverage tests and the
production build passed, and the built nginx image served login, products,
WebMCP and their entry assets. The frontend source-owned release publishes a new immutable image version;
existing image tags are not overwritten.

### Initial production mitigation verification — 22 October 2026

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
`~/.config/awesome-localstack-security/`. The mitigation is committed in `36b9f4a`; the server received the verified
Compose/configuration artifacts through the normal Ansible copy/convergence
procedure. Follow-up application images use their own source-owned releases.

## Additional dependency check from cve.now — 22 October 2026

The supplemental check covered 699 unique public npm production package/version
pairs across the five website/frontend dependency sets. It matched only the
known, unpatched braces 3.0.3 issue (CVE-2026-93687). Awesome Testing declares
fast-glob as a production dependency, but the inspected content/store and README
synchronization calls use fixed repository glob patterns; no visitor-controlled
pattern path was found. Development tooling also retains the same advisory.

The initial Maven runtime inventory (272 unique package/version pairs) matched
Jackson 2.21.5 and Tomcat 11.0.24 advisories. Upstream ranges also affect Jackson
3.1.5, although this catalog did not return that coordinate. The Java source
releases therefore move together to Spring Boot 4.1.2 / Tomcat 11.0.27 and aligned
Jackson 2.21.8 and 3.1.8 BOMs. The resolved replacement runtime inventory has
274 pairs and zero matches in cve.now. Backend local verification passed all
592 tests, and consumer/model-mock verification also passed. Source-owned image publication is recorded below; production rollout has its
own verification receipt.

This catalog result is scoped dependency evidence, not an assessment of OS
packages or provider-managed runtimes. In particular, the inspected Convex
services still report Node 24.21.0, below corrected 24.22.1. Private scan receipts
are under `~/.config/awesome-localstack-security/`.

## Distributed lab release (pending)

Not released yet: the LocalStack side of the November 2026 distributed-systems
lab ([DISTRIBUTED_LAB_CONTRACTS.md](DISTRIBUTED_LAB_CONTRACTS.md)) is wired
ahead of the images. The release train ships it as one set:

| Image | Adds |
| --- | --- |
| backend 3.21.0 | Reservation expiry, `notification.requested`, the `NOTIFICATION` caller, webhook export, `webhooks.enabled`, tracing, `spanId` (Flyway V23, V24, maybe V25) |
| warehouse-service 1.5.0 | Warehouse locations and split shipments (Flyway V6), tracing, outbox gauge |
| payment-service 1.3.0 | Reservation guard, tracing, outbox gauge |
| notification-service 1.0.0 | **New service** (first release, `slawekradzyminski/notification-service`, default branch `master`) |
| frontend 3.15.0 | Reservation countdown, parcels, notification-service API snapshot |

LocalStack changes already on the branch:

- `notification-service` in the lightweight (160 MiB, `local-outbox`), full
  (`jms` to ActiveMQ) and server profiles, plus `aitesters-notification-service`
  (`local-outbox`); every backend next to one gets `NOTIFICATION_SERVICE_TOKEN`,
  `NOTIFICATIONS_DELIVERY=feed` and `WEBHOOKS_ENABLED=false`. The l20
  compatibility stack (`docker-compose.compatibility.yml`) is unchanged and
  backend-only.
- `postgres/service-roles.sh` prepares the `notification` role and schema.
- Gateways: webhook, webhook-inbox, admin-webhook, notification-email,
  local notification outbox and `/notification/v3/api-docs` locations to
  port 4005 on every host; `^/api/v1/orders/\d+/shipments$` to warehouse-service.
- Ansible: `.env.notification`, `.env.aitesters-notification`, eight new Vault
  keys with asserts, an image gate, role isolation, direct-route, heap, scrape
  and probe checks, aitesters reset, upgrade stop list and deployment silence
  ([ANSIBLE.md](ANSIBLE.md#notification-service-secrets-and-image-gate)).
- Prometheus job `spring_notification_micrometer`, public probe of
  `/notification/v3/api-docs`, `CriticalContainerMissing` for the service.
- The chaos and tracing overlays cover notification-service directly
  (`docker-compose.chaos-notification.yml` and
  `docker-compose.tracing-notification.yml` were folded in).

Until notification-service 1.0.0 is published the server profile carries
`slawekradzyminski/notification-service:1.0.0@sha256:PENDING_NOTIFICATION_SERVICE_DIGEST`
and the local profiles the bare `1.0.0` tag. `scripts/verify-release-images.py`,
`scripts/verify-image-pins.py` and the Ansible image gate fail with an explicit
placeholder message, and CI's `runDocker`, `verifyLightweight` and
`verifyMonitoringOverlay` cannot pull the image. `scripts/release-train.py pin`
treats the placeholder as a first pin: it replaces the placeholder and the bare
tags in every Compose file and the compatibility-set row with the published
`tag@sha256`. Bump backend, warehouse-service, payment-service and frontend in
the same train (the other images stay at their current pins until then).

Upgrade: new Vault keys first, then `scripts/release-train.py deploy --yes`
(backend version change: quiesced upgrade with a pre-deploy backup).
notification-service imports the backend's webhook subscriptions and inboxes on
its first start. Rollback: re-pin backend 3.20.1, warehouse-service 1.4.1,
payment-service 1.2.1 and frontend 3.14.0, remove both notification-services
and set the backends back to `NOTIFICATIONS_DELIVERY=email` and webhooks on;
whether 3.20.1 runs on the V23 to V25 schema is decided in the release review,
so keep the pre-deploy backup. Subscriptions created after the move exist only
in notification-service.

## Release train: frontend 3.15.0 — 14 November 2026

Published by `scripts/release-train.py`. TODO: what changes, LocalStack
changes, upgrade order and rollback.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/frontend:3.15.0@sha256:7640d1625b460b1ad5d19a9a6176444c8d8765a527699140fa6fa81eeac0e325` | [PR #107](https://github.com/slawekradzyminski/vite-react-frontend/pull/107), `f8ba7fb` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/43632605872) |
| `slawekradzyminski/backend:3.21.1` | unchanged | unchanged |
| `slawekradzyminski/warehouse-service:1.5.1` | unchanged | unchanged |
| `slawekradzyminski/payment-service:1.3.1` | unchanged | unchanged |
| `slawekradzyminski/notification-service:1.0.1` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.21.1, warehouse-service 1.5.1, payment-service 1.3.1, notification-service 1.0.1 — 14 November 2026

Published by `scripts/release-train.py`. TODO: what changes, LocalStack
changes, upgrade order and rollback.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.21.1@sha256:872f6c143a7165d87b17da599a9ae9a31ffe7a6a2b1fb9b3124cb1db3bc78d73` | [PR #110](https://github.com/slawekradzyminski/test-secure-backend/pull/110), `6e49088` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43630031469) |
| `slawekradzyminski/warehouse-service:1.5.1@sha256:17adbb3cc45ed71bb522cae280e442f4af3690cb48a20627c6f04efdb6371a7e` | [PR #12](https://github.com/slawekradzyminski/warehouse-service/pull/12), `65c1f71` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/43630033303) |
| `slawekradzyminski/payment-service:1.3.1@sha256:a82b2da62b18514a27039c716ac6d6b49a6ed804f58a739a8812f49cd91bc5b8` | [PR #8](https://github.com/slawekradzyminski/payment-service/pull/8), `fd5cd1f` | [run](https://github.com/slawekradzyminski/payment-service/actions/runs/43630035458) |
| `slawekradzyminski/notification-service:1.0.1@sha256:1a051e8aa54e90f5e9dd9d8dbd1aacd94b1af6f886ea571a0f4d7cac23019c52` | [PR #3](https://github.com/slawekradzyminski/notification-service/pull/3), `4fe4cb6` | [run](https://github.com/slawekradzyminski/notification-service/actions/runs/43630037686) |
| `slawekradzyminski/frontend:3.14.0` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.20.1 — 13 November 2026

Restores the public traffic endpoints on awesome.byst.re for the AI Testers API course (owner's decision: this is a
training app with fake data). With legacy public access on (server profile), anonymous callers read traffic as before
3.19.0: with `X-Client-Session-Id` that session's records (list and detail); without it every record. The global
`/topic/traffic` WebSocket feed is back. Secrets stay masked. Authenticated callers and profiles with legacy access off
(local, aitesters) keep the 3.19 rules. awesome-localstack #99 removed the configuration override that had closed access.

LocalStack changes: image pin only. Upgrade: `scripts/release-train.py deploy --yes`. Rollback: re-pin backend 3.20.0.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.20.1@sha256:a47d14898c727aa64374efeb405ac1aea95fe0d047cfbf3b160ea89f46a4de52` | [PR #105](https://github.com/slawekradzyminski/test-secure-backend/pull/105), `134f256` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43390534081) |
| `slawekradzyminski/warehouse-service:1.4.1` | unchanged | unchanged |
| `slawekradzyminski/payment-service:1.2.1` | unchanged | unchanged |
| `slawekradzyminski/frontend:3.14.0` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.20.0, ollama-mock 1.0.13 — 13 November 2026

The remaining fixes from the owner's exploratory session of 2026-11-07.

- **backend 3.20.0**:
  - **X-08, token revocation:** logout and password reset revoke every access and refresh token of the user. Access tokens carry the user's token version (`ver`, V22), which the backend checks on HTTP, the traffic WebSocket and gRPC. warehouse-service and payment-service verify tokens offline, so a revoked access token keeps working there until it expires (1 h at most), but it can no longer be refreshed. Enabling or disabling 2FA still revokes only refresh tokens, because l20 keeps using the access token afterwards.
  - **X-12, masked emails:** non-admins see other users' emails masked (`b***@google.com`); your own account and admins see full addresses.
  - **X-05, email templates:** clients may only send the GENERIC template; admins may use any.
  - **X-23, authorization before validation:** admin URLs (`/api/v1/admin/**`, product writes, order status, admin order list, user deletion) and `PUT /users/{username}` are checked by role before the body is read, so clients get 403 instead of the admin validation rules.
- **ollama-mock 1.0.13, X-26:**
  - **Unknown models:** they return 404 like real Ollama.
  - **Tool answers:** final answers are built from the tool output for every scenario except "beauty", whose canned answer the AI Testers API course asserts word for word.

LocalStack changes: image pins, including the ollama-mock pin in `scripts/verify-ollama-config.sh`. Upgrade:
`scripts/release-train.py deploy --yes` (backend upgrade; migration V22 adds `app_user.token_version`).
Rollback: re-pin backend 3.19.0 and ollama-mock 1.0.12; V22 only adds a column with a default.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.20.0@sha256:2fc90af8dcbffc81ff1bd8a5c83a0dc7f8356bfcff320b9a595bfffe2618aa69` | [PR #104](https://github.com/slawekradzyminski/test-secure-backend/pull/104), `998ed3d` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43380128361) |
| `slawekradzyminski/warehouse-service:1.4.1` | unchanged | unchanged |
| `slawekradzyminski/payment-service:1.2.1` | unchanged | unchanged |
| `slawekradzyminski/frontend:3.14.0` | unchanged | unchanged |
| `slawekradzyminski/ollama-mock:1.0.13@sha256:7e3ea7b3c6774c38e81726e64e47323159cea53ce5777ab35754a0e5a9b4ef5e` | [PR #33](https://github.com/slawekradzyminski/ollama-mock/pull/33) | tag `v1.0.13` |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.19.0, frontend 3.14.0 — 13 November 2026

Fixes from the owner's exploratory session of 2026-11-07 (triage: 40 findings, 16 still reproduced).

- **backend 3.19.0**:
  - **X-03, traffic logs (security):**
    - **Masking:** secrets are masked by name pattern in every profile, including `newPassword`, `confirmPassword`, `giftCardCode`, tokens and codes.
    - **Scoping:** reads are bound to the session and its user. Anonymous reads under legacy public access get an empty page, which is the l20 page shape.
    - **Stored data:** V20 and the startup `TrafficHistoryMasker` re-mask the stored history.
    - **Safety:** a long JSON string can no longer overflow the stack in the masking regex.
  - **X-01:** the seeding profiles no longer crash-loop on products with a null `imageUrl`. V19 stores them as `''` and makes the column NOT NULL.
  - **X-04:** a 2FA sign-in challenge is consumed after 5 wrong codes (V21).
  - **X-06:** right to be forgotten cancels open orders, with stock restored, before erasing the user. The course bug, a repeated request returning 500, is unchanged.
  - **X-10:** `POST /email` without `to` returns a 400 field error.
  - **X-18:** unknown paths and unsupported methods answer in the ErrorDto shape.
  - **X-21:** QR validation errors are 400 JSON whatever `Accept` says.
  - **X-24:** OpenAPI fixes (zipCode, login example).
  - **X-02:** the service refuses to start with the reset token exposed in shared profiles.
  - V19–V21 are guarded for schemas baselined at V1.
- **frontend 3.14.0**:
  - **Traffic sessions:** a new traffic session id on login and logout.
  - **Admin only:** the user directory and recipient picker.
  - **Errors:** inline checkout and register errors instead of `alert()`.
  - **Smaller fixes:** a 404 page, the email form resets after sending, a label for the chat input, and honest copy about the local reset token.

The gateway changes merged before this release ship with it: JSON 404 for unknown `/api/**` paths, and
production forgot-password and MFA limits of 20 per account.

Still open from the triage (next release): X-08 token revocation on logout and password reset, X-12 masked
emails for non-admins, X-05 email templates, X-23 authorization before validation, and X-26 mock tool answers.

LocalStack changes: image pins only. Upgrade: `scripts/release-train.py deploy --yes` (backend upgrade; migrations V19–V21).
Rollback: re-pin backend 3.18.0 and frontend 3.13.1; V19–V21 only add columns, a default and a NOT NULL on
`products.image_url`, so 3.18.0 runs on the migrated schema.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.19.0@sha256:4891deae0e2f8f2155996db391fd12b3d83d66321dc2f3f71ff0a253f25972f8` | [PR #102](https://github.com/slawekradzyminski/test-secure-backend/pull/102), `a229ce1` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43327324870) |
| `slawekradzyminski/frontend:3.14.0@sha256:48ebc560e9fc247fe7b4a43249eba25b61a131f8e98b5da29da883d3baa689ea` | [PR #102](https://github.com/slawekradzyminski/vite-react-frontend/pull/102), `78fcd16` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/43327329729) |
| `slawekradzyminski/warehouse-service:1.4.1` | unchanged | unchanged |
| `slawekradzyminski/payment-service:1.2.1` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: frontend 3.13.1 — 12 November 2026

- **frontend 3.13.1**:
  - **Cart price notice:** a cart line whose product price changed since it was added shows "Price changed: now $X. Your cart keeps $Y until you update this item." It uses the backend 3.18.0 fields `priceChanged`, `unitPrice` and `currentPrice`, and is a `role="status"` note. REST cart only; the GraphQL cart has no such fields.
  - **API types:** the OpenAPI snapshots and generated types follow the 3.18 release set.
  - **Development pins:** the frontend repository's Compose file pins backend 3.18.0 and ollama-mock 1.0.12, and no longer sets `APP_SSO_ENABLED`.

LocalStack changes: image pin only. Upgrade: `scripts/release-train.py deploy --yes` (a plain deploy; it is the
first production run of the hardened play: asset mirror, image builds before any stop, rescue). Rollback:
re-pin frontend 3.13.0.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/frontend:3.13.1@sha256:9151c313ac6ebe91a59fa100fd76348f05f64e4266f9bf2dc412ff1d46d58931` | [PR #101](https://github.com/slawekradzyminski/vite-react-frontend/pull/101), `a9c3cbd` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/43283256605) |
| `slawekradzyminski/backend:3.18.0` | unchanged | unchanged |
| `slawekradzyminski/warehouse-service:1.4.1` | unchanged | unchanged |
| `slawekradzyminski/payment-service:1.2.1` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.18.0, frontend 3.13.0, ollama-mock 1.0.12 — 12 November 2026

This release fixes the defects course groups reported on the playwright-2026 branches (hyr, obi, pio, war):
186 reports, 82 unique defects after triage, 48 reproducible. The course bugs documented in
ai-testers-api (l15–l20 `bug-reports/`) are deliberately unchanged, and so is every behaviour an l20
test asserts. SSO and Keycloak are removed for good.

- **backend 3.18.0**:
  - **Validation:**
    - Max-length errors no longer say "minimum".
    - Empty email, whitespace-only and invisible values, and blank product fields on update are rejected (an empty category still means "unchanged").
    - Lengths are limited to fit the database columns (category, image URL, address).
    - Image URLs must be real http(s) URLs.
    - Wrongly typed JSON values are rejected instead of coerced.
    - A field that breaks several rules gets one deterministic message.
  - **Errors:** malformed bodies, bad enums and UUIDs return the normal error format without Java class names (the `?status=` body that l20 asserts is kept). Another user's email on profile edit returns 400, and constraint violations return 409 instead of 500.
  - **Identity:**
    - Usernames are case-insensitive and unique, from `[A-Za-z0-9._-]{4,255}`; emails are lower-cased and unique (migration V18 skips an index and logs a warning instead of failing if old data collides).
    - The new `GET /api/v1/admin/users/identity-issues` lists accounts that break the rules.
    - Passwords are limited to 72 UTF-8 bytes, the BCrypt limit.
    - `PUT /users/{username}` answers 403 for other users' names, so it no longer tells clients which usernames exist.
    - Deleting a user no longer deadlocks with payment results: locks are taken in one order, with one retry.
  - **Orders:** status only moves forward (steps can be skipped; CANCELLED and DELIVERED are final). Responses carry the stored `updatedAt`.
  - **Cart prices:** a cart line whose product price changed is flagged with `priceChanged`/`currentPrice`. Checkout still charges the price from when the item was added, because l20 asserts that snapshot.
  - **Other fixes:**
    - Search ignores Polish and Latin accents again.
    - GraphQL money has two decimals; zero stays "0" for l20.
    - Resetting a system prompt returns the effective prompt.
    - QR text is UTF-8, and text that is too long returns 400.
    - Tool chat sends `done=true` only on the last event.
    - The native image has `SharedArenaSupport`, so concurrent LLM chats no longer return 500.
  - **OpenAPI:** documents `application/json` and `UserResponseDto`.
  - **SSO removed:** the `POST /api/v1/users/sso/exchange` endpoint and the OIDC code are gone. The `app_user.auth_provider`/`provider_subject` columns stay so a rollback to 3.17.x still starts, and SSO-created accounts recover through **Forgot password**.
- **frontend 3.13.0**:
  - **Accessibility:** keyboard access to inventory rows, a label for the order-status select, contrast fixes, an inert collapsed LLM panel, and labelled chat roles.
  - **Forms and checkout:** the register page's "Sign in" no longer submits the signup form. The admin product form shows field errors and a success message. Coupon dates are sent in UTC.
  - **Layout:** responsive admin tables, cart and catalog filters; long category names no longer break the layout; the header fits at 320 px.
  - **Robustness:**
    - A failed cart read shows a warning instead of an empty cart.
    - Huge order ids no longer hang.
    - The shop API selector waits for pending cart writes.
    - One `/users/me` request per sign-in.
    - Toasts survive navigation.
  - **QR and chat:** QR shows a byte counter and the server's message. Chat input stays locked until the stream ends, and a failed chat can be retried.
  - **SSO removed:** the SSO code and buttons are gone.
- **ollama-mock 1.0.12**: chat answers the latest user prompt instead of the first one, and non-streaming chat replies return `done: true`.

LocalStack changes: image pins, the ollama-mock pin in `scripts/verify-ollama-config.sh`, `APP_SSO_ENABLED`
dropped from every Compose file, SSO notes in the docs updated. Upgrade: `make ansible-deploy-backend-upgrade`
(migration V18). Rollback: re-pin backend 3.17.2, frontend 3.12.2 and ollama-mock 1.0.11; V18 only adds
indexes, so 3.17.2 runs on the migrated schema.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.18.0@sha256:7b5ffeade75935ec76053d88136e6dd769d534b983cbdc35dfde19991e4c32c3` | [PR #101](https://github.com/slawekradzyminski/test-secure-backend/pull/101), `ba06bdc` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43270504640) |
| `slawekradzyminski/frontend:3.13.0@sha256:f84ee35b8e124335f0d3f8014cabcc9432afb9e50fe2d886df23c78a7a92a843` | [PR #100](https://github.com/slawekradzyminski/vite-react-frontend/pull/100), `48849c2` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/43270510480) |
| `slawekradzyminski/warehouse-service:1.4.1` | unchanged | unchanged |
| `slawekradzyminski/payment-service:1.2.1` | unchanged | unchanged |
| `slawekradzyminski/ollama-mock:1.0.12@sha256:ee8a22bbc6b0f00959cf751e6f78d523fcc74eb32759ead0b9b274dc098d310f` | [PR #32](https://github.com/slawekradzyminski/ollama-mock/pull/32) | tag `v1.0.12` |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.17.2, frontend 3.12.2 — 12 November 2026

Second patch release from the reference Playwright suite (`awesome-localstack-e2e-tests`).

- **frontend 3.12.2**: after an order was placed, a customer on a slow device could land on the
  empty cart instead of the payment page (BUG-CHECKOUT-01). React Router navigates inside
  `startTransition`, so the refetched empty cart won and `CheckoutPage` redirected to `/cart`.
  Checkout now reports the placed order first, navigates with `replace`, then refreshes the cart, and
  shows "Order placed. Opening payment…" instead of redirecting. The OpenAPI snapshots and the
  development pins in the frontend repository were refreshed to the release train.
- **backend 3.17.2**: the OpenAPI document again states the real minimum lengths of
  `ReviewRequestDto` (title 3, body 10). 3.17.1 documented 1 after the deterministic blank-review
  messages were introduced. There is no behaviour change.

LocalStack changes: image pins only. Upgrade: `make ansible-deploy-backend-upgrade`; no migrations.
Rollback: re-pin backend 3.17.1 and frontend 3.12.1.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.17.2@sha256:f2293ebf37902d95f53ae9d3e875dab6941c69e0ef26a124ee1ba98150d352d4` | [PR #98](https://github.com/slawekradzyminski/test-secure-backend/pull/98), `02baa5b` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43218041456) |
| `slawekradzyminski/frontend:3.12.2@sha256:ea48bab9beddd1e31910f119c5b4730e0e7d5d49de0ca5ff8bf8495dc45b41a1` | [PR #98](https://github.com/slawekradzyminski/vite-react-frontend/pull/98), `7aa3d44` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/43218045140) |
| `slawekradzyminski/warehouse-service:1.4.1` | unchanged | unchanged |
| `slawekradzyminski/payment-service:1.2.1` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.17.1, warehouse-service 1.4.1, payment-service 1.2.1, frontend 3.12.1 — 12 November 2026

Patch release of the bugs the new reference Playwright suite
(`awesome-localstack-e2e-tests`) found on its first full run. Each bug has a report in that
repository's `bugs/` folder, and the tests that caught them now run as regression tests.

- **payment-service 1.2.1**:
  - **Connection-pool deadlock fixed.** With a pool of three connections, three concurrent first payments each held one connection and waited for a second (lock row in `REQUIRES_NEW`, result dispatch after commit on the request thread), so every caller got a 500 after 30 s. The lock row is now inserted in the same transaction, results are delivered from a single dispatcher thread, and the backend is asked for the order before the transaction starts.
  - **Signing-key race fixed.** Concurrent first requests no longer get 401 while the signing keys are fetched.
  - **Timestamps.** Payment timestamps are now microseconds, so the 201 equals what is stored.
- **warehouse-service 1.4.1**:
  - **Same pool deadlock fixed** for notifications (after-commit dispatch, `synchronized` around HTTP) and return locks.
  - **Same signing-key race fixed.**
  - Shipped/delivered notifications are now sent just after the response instead of before it.
- **backend 3.17.1**:
  - **Retention job.** The event-feed retention job now actually deletes old events; a transactional self-call made every scheduled run fail.
  - **User deletion.** Deleting a user no longer fails when an email event for them is recorded at the same moment (row locks).
  - **Gift card errors.** An unknown gift card `status` filter gets a 400 `{message}`; the orders filter keeps the body l20 asserts.
  - **Disable response.** Disabling a gift card returns the stored `updatedAt`.
  - **Validation messages.** A blank gift card code, review title or review text gets one deterministic message.
- **frontend 3.12.1**:
  - **Admin lists.** They show a row saved while their first load is in flight; refetch after a write cancels the in-flight request.
  - **Gift card expiry.** It is sent as a UTC instant and shown in the browser's time zone.

LocalStack changes: image pins only. Upgrade order: the regular backend-upgrade deploy
(`make ansible-deploy-backend-upgrade`); no migrations. Rollback: re-pin the 11 November
train (backend 3.17.0, warehouse-service 1.4.0, payment-service 1.2.0, frontend 3.12.0).

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.17.1@sha256:d954473d10971a32acc9d08b07179c6d35b80af2bbba46a0895a6a08f95b5383` | [PR #97](https://github.com/slawekradzyminski/test-secure-backend/pull/97), `e691a8e` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43201139933) |
| `slawekradzyminski/warehouse-service:1.4.1@sha256:ffb3f679e922d7e4fcd1f513a9530816a6d8efd9aa40edfa36d215d2c5ea91c5` | [PR #10](https://github.com/slawekradzyminski/warehouse-service/pull/10), `a6fea78` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/43201142574) |
| `slawekradzyminski/payment-service:1.2.1@sha256:1b6a265827b426b5a45aec901361672428a84841f45529a1b2b966d0c0f97e91` | [PR #6](https://github.com/slawekradzyminski/payment-service/pull/6), `a4948b6` | [run](https://github.com/slawekradzyminski/payment-service/actions/runs/43201148518) |
| `slawekradzyminski/frontend:3.12.1@sha256:bd79762533ad9b50881e39466d228edb20129540aad198bc7159b4504002e3dd` | [PR #97](https://github.com/slawekradzyminski/vite-react-frontend/pull/97), `fa254c5` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/43201151527) |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Release train: backend 3.17.0, warehouse-service 1.4.0, payment-service 1.2.0 — 11 November 2026

Published and pinned by `scripts/release-train.py` (first train). The publish
workflows skipped the duplicated verification for the first time (identical
tree already verified on the PR): backend 16 min instead of 27, services 10
instead of 20.

- **Correlation IDs end to end.** Every Spring service validates or generates
  `X-Request-Id` and W3C `traceparent`, logs them (MDC `requestId`, `traceId`,
  `spanId`) and returns `X-Request-Id`; outbound calls send a child
  `traceparent`. Feed events (backend V17), outboxes (warehouse V5, payment V4,
  backend email/webhook rows) keep the ids, so asynchronous work logs under the
  request that caused it. The backend logs one line per recorded domain event.
- **Gateway** validates or generates both headers in every server block, echoes
  `X-Request-Id` and writes a JSON access log.
- **JSON logs in production.** `LOGGING_STRUCTURED_FORMAT_CONSOLE=ecs` for the
  backends, warehouse and payment services; local profiles stay readable.
  How to search: the wiki page Operations, Tracing a request
  (`docs-site/docs/operations/tracing.md`).

Upgrade order: backend first (V17 is additive), services in the same deploy;
`make ansible-deploy-backend-upgrade`. Rollback: backend 3.16.0's Flyway does not know V17 and refuses the migrated
schema, so a rollback restores the encrypted pre-deploy backup with the previous
pins, as for earlier releases.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.17.0@sha256:84331dca415fece98042dacec043939492b9bdb4cbcd709c8c179e7130f34264` | [PR #96](https://github.com/slawekradzyminski/test-secure-backend/pull/96), `032913a` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43068503449) |
| `slawekradzyminski/warehouse-service:1.4.0@sha256:3796cd9bdc460d2f7d7f943a0b77f95a0f2ee2d24c5dee6f1ecd2f606feb4033` | [PR #9](https://github.com/slawekradzyminski/warehouse-service/pull/9), `6d0479f` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/43068506492) |
| `slawekradzyminski/payment-service:1.2.0@sha256:b03efeb080df617b8981602d71a2c8f38961fab55be973bfc19c52b29e187c31` | [PR #5](https://github.com/slawekradzyminski/payment-service/pull/5), `869e98e` | [run](https://github.com/slawekradzyminski/payment-service/actions/runs/43068511976) |
| `slawekradzyminski/frontend:3.12.0` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

## Warehouse-service 1.3.1: read-only shipment GET — 11 November 2026

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/warehouse-service:1.3.1@sha256:b56f51fa3a80caf3cc7cc56704d540051e5550e59b8ccbf31961e1b5c6b07a29` | [PR #7](https://github.com/slawekradzyminski/warehouse-service/pull/7), `228acc0` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/43052520977) |

`GET /api/v1/warehouse/shipments/{id}` no longer calls the backend or cancels
an `AWAITING_PICK` shipment; cancellations arrive through the event feed and
the reconciler (see [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md#follow-ups)).
The wiki gains "Useful links" for testers and pages on the LLM integration and
streaming. No migration; plain `make ansible-deploy`.

## Event feed: backend 3.16.0, warehouse-service 1.3.0, payment-service 1.1.0 — 11 November 2026

Published as native multi-arch images; verified on a native full stack (every
refund and cancellation path through the feed) and ai-testers-api `l20`
190/190 against backend 3.16.0.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.16.0@sha256:ca833405acf852bcdd2014721649cd6432bda6d74f9da98b2e3cd20c370288e7` | [PR #94](https://github.com/slawekradzyminski/test-secure-backend/pull/94), `7b88df6` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/43036812385) |
| `slawekradzyminski/warehouse-service:1.3.0@sha256:02ac943bf2fa6484cb2bddfc2deca4a17f9b497b61f88799a3f46809cbbe4207` | [PR #6](https://github.com/slawekradzyminski/warehouse-service/pull/6), `393b627` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/43036827402) |
| `slawekradzyminski/payment-service:1.1.0@sha256:ade0902dd2ceddd6c3ac9c64f321de0f1bacbcd8ff71dbc31dc7b4e538e8dbf9` | [PR #3](https://github.com/slawekradzyminski/payment-service/pull/3), `5b7e009` | [run](https://github.com/slawekradzyminski/payment-service/actions/runs/43036843487) |
| `slawekradzyminski/frontend:3.12.0` | unchanged | unchanged |
| `slawekradzyminski/consumer:3.6.0` | unchanged | unchanged |

What changes:

- **Backend 3.16.0.** Every domain event is written to `domain_events` in the
  same transaction as the state change (Flyway V16) and served by
  `GET /internal/v1/events?after&limit&types` to the warehouse and payment
  service tokens, with a 3-second settle delay (`EVENTS_SETTLE_DELAY`, `PT3S`)
  and 30-day retention (`EVENTS_RETENTION`, `P30D`). Card refunds (the card
  leg of a booked refund, and the refund of a cancelled card-paid order) are
  published as the internal `card-refund.requested` event, which user webhooks
  never receive. The backend no longer calls payment-service: the refund
  outbox, its HTTP client and `PAYMENT_BASE_URL` are gone. Contract:
  [EVENT_FEED.md](EVENT_FEED.md).
- **payment-service 1.1.0.** Polls the feed for `card-refund.requested`
  (`PAYMENT_EVENTS_ENABLED`, `PAYMENT_EVENTS_POLL_INTERVAL`, default `PT5S`;
  Flyway V3 `event_cursors`, `processed_events`). The inbound
  `POST /internal/v1/payments/refunds` endpoint is removed. Another user's
  payment or order payments now answer 404 like a missing one. Contract:
  [PAYMENT_SERVICE_CONTRACT.md](PAYMENT_SERVICE_CONTRACT.md).
- **warehouse-service 1.3.0.** Polls the feed for `order.cancelled`
  (`WAREHOUSE_EVENTS_ENABLED`, `WAREHOUSE_EVENTS_POLL_INTERVAL`, default
  `PT5S`; Flyway V4) and cancels the open shipment within seconds; the
  reconciler stays as a safety net with a default interval of `PT10M`. Needs
  backend 3.16.0. Contract: the event feed addendum in
  [WAREHOUSE_SERVICE_CONTRACT.md](WAREHOUSE_SERVICE_CONTRACT.md).
- **Decisions.** [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) records
  why the integration is a pull feed rather than an ActiveMQ topic, and three
  related decisions.

LocalStack changes in this release:

- `PAYMENT_BASE_URL` is removed from `backend` in every profile and from
  `aitesters-backend`; `scripts/verify-release-images.py` now fails when a
  backend sets it;
- the new variables keep their defaults, so no other Compose, gateway, Vault
  or Ansible change is needed (the feed is internal and `/internal/` stays 404
  through the gateway);
- the wiki shows the feed in the architecture, payments, refunds and
  fulfilment pages, and publishes [EVENT_FEED.md](EVENT_FEED.md) and the ADRs.

Upgrade order:

1. **Backend first.** Backend 3.16.0 serves the feed before anything reads it.
   The old consumers keep working against it: warehouse-service 1.2.0 still
   reconciles cancellations by polling orders, and nothing calls the removed
   refund endpoint.
2. **payment-service 1.1.0 in the same deploy.** The backend no longer sends
   refunds, so with payment-service 1.0.0 card refunds would only accumulate in
   the feed. They are not lost (1.1.0 starts from sequence 0 and processes
   everything within the 30-day retention, idempotently per `requestId`), but
   customers would see no card refund until 1.1.0 runs. Ship both together.
3. **warehouse-service 1.3.0** in the same deploy, or later (before it, the
   minute reconciler covers cancellations). Against an older backend 1.3.0
   logs a 404 on every poll.

All three are pinned in one change and deployed with
`make ansible-deploy-backend-upgrade` (Flyway V16 runs on the backend),
followed by the course suite (`l20`) and a check that a cancelled card-paid
order ends `REFUNDED` and a cancelled `AWAITING_PICK` order's shipment ends
`CANCELLED` within about ten seconds.

Rollback: V16 moves the undelivered rows of `payment_refund_outbox` into the
feed and `card_refund_requests` and then **drops** `payment_refund_outbox`, so
backend 3.15.0 cannot run on the migrated schema (its Flyway also does not know
V16). As before, a rollback restores the encrypted pre-deploy backup taken by
`make ansible-deploy-backend-upgrade` together with the 3.15.0 / 1.2.0 / 1.0.0
references and `PAYMENT_BASE_URL` on both backends; data written after the
upgrade is lost. The payment (V3) and warehouse (V4) migrations only add
tables and are rolled back by the same restore.

## Commerce wave 3: backend 3.15.0, warehouse-service 1.2.0, payment-service 1.0.0, frontend 3.12.0 — 11 November 2026

All four images are published as native (backend, warehouse, payment) or
nginx (frontend) multi-arch images. ai-testers-api `l20` passed 190/190 against
the published backend 3.15.0 (11 November 2026).

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.15.0@sha256:c2f38b95515a7578d3cc1eff72a2d6c3112263cd223c2704c266e7cb7ff4d24b` | [PR #93](https://github.com/slawekradzyminski/test-secure-backend/pull/93), `3fb1cc9` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/42907355443) |
| `slawekradzyminski/warehouse-service:1.2.0@sha256:b6849b65e8d17b36c031e7d67fb585a2f057c1d33ad5db80fec2fb03263c97d7` | [PR #5](https://github.com/slawekradzyminski/warehouse-service/pull/5), `60c1c8f` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/42897115628) |
| `slawekradzyminski/payment-service:1.0.0@sha256:e8b7d82af4f64c94e23e6c1e87d118b645a306e2acc9bed979f8d71f6923aaed` | [payment-service](https://github.com/slawekradzyminski/payment-service) `26a057a` | [run](https://github.com/slawekradzyminski/payment-service/actions/runs/42982591094) |
| `slawekradzyminski/frontend:3.12.0@sha256:96565e441275fe1f35e02f3848d6c28a12277b2551bfd08a20d1da258b7ccd9e` | [PR #95](https://github.com/slawekradzyminski/vite-react-frontend/pull/95), `37316e5` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/42991982733) |
| `slawekradzyminski/consumer:3.6.0@sha256:6975c932304eaba294b5cba87b14e3d8722ed6e6029031c0455524e0307b8775` | unchanged | unchanged |

What the wave adds:

- **Payments.** New `payment-service` (port 4004, schema and role `payment`,
  native image, `-Xmx64m` in 160 MiB) with simulated test cards, 3-D Secure,
  idempotency keys and refunds; it reports results to the backend with signed
  notifications. Contract:
  [PAYMENT_SERVICE_CONTRACT.md](PAYMENT_SERVICE_CONTRACT.md).
- **Shipment tracking.** warehouse-service 1.2.0 simulates a carrier and
  publishes `/api/v1/orders/{id}/shipment/tracking` and the public
  `/api/v1/tracking/{number}`; see the addendum in
  [WAREHOUSE_SERVICE_CONTRACT.md](WAREHOUSE_SERVICE_CONTRACT.md).
- **Backend 3.15.0.** Product search with facets, loyalty points and gift
  cards, VAT rates and currency conversion, user webhooks with a built-in
  inbox ([WEBHOOKS.md](WEBHOOKS.md)), and the payment result endpoint.
  Flyway V10 to V15; warehouse-service V3; payment-service V1.
- **Frontend 3.12.0.** Screens for the features above.

LocalStack changes in this release:

- `payment-service` in the lightweight and full profiles and
  `payment-service` plus `aitesters-payment-service` on the server, each after
  a healthy backend and the `postgres-roles` one-shot;
- `postgres/warehouse-role.sh` became `postgres/service-role.sh` (one role and
  schema per call) with `postgres/service-roles.sh` preparing `warehouse` and
  `payment`; warehouse behaviour is unchanged;
- gateway routes for payments and tracking in every server block, payment
  OpenAPI at `/payment/v3/api-docs`;
- both backends get `PAYMENT_SERVICE_TOKEN`, `PAYMENT_WEBHOOK_SECRET` and
  `PAYMENT_BASE_URL`;
- six new Vault keys, `.env.payment` and `.env.aitesters-payment`, the image
  gate, verification, Prometheus job `spring_payment_micrometer`, a public
  probe, a `CriticalContainerMissing` rule, the deployment silence, the
  aitesters reset and the coordinated-upgrade stop list (see
  [ANSIBLE.md](ANSIBLE.md#payment-service-secrets-and-image-gate)).

Rollback: backend 3.14.1's Flyway does not know V10 to V15 and would refuse
the migrated schema, so a rollback restores the encrypted pre-deploy backup
taken by the backend upgrade (`make ansible-deploy-backend-upgrade`) together
with the 3.14.1 / 1.1.1 / 3.11.0 references and without the payment
services; data written after the upgrade is lost.

## Warehouse definition in Swagger UI: backend 3.14.1, warehouse-service 1.1.1 — 10 November 2026

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.14.1@sha256:cd1a12810a1b4f82eb23b3519362add3f20704e2652ebc3710f1a5d88e5712e4` | [PR #92](https://github.com/slawekradzyminski/test-secure-backend/pull/92), `f4cda43` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/42712362297) |
| `slawekradzyminski/warehouse-service:1.1.1@sha256:7b1202bea1d6994c8046c5ddef967387907bff01ce5ae8476f01acfa2284c9cf` | [PR #4](https://github.com/slawekradzyminski/warehouse-service/pull/4), `27c66cd` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/42712378862) |

The backend's Swagger UI definition dropdown gains "Warehouse service", which
loads `/warehouse/v3/api-docs` through the gateway (404 on the bare backend
port). Both documents now build their server URL from the port in the
forwarded host before `X-Forwarded-Port`. The local gateway publishes 8081 but
forwards its container port 80, so the local documents used to advertise
`http://localhost` and "Try it out" missed the gateway. warehouse-service also
gets the backend's `ServerBaseUrlCustomizer`, because its native image ignored
`server.forward-headers-strategy` and advertised `http://` behind the TLS edge.
No migrations; rolling back only needs the 3.14.0 / 1.1.0 references above.
The unchanged course suite (`l20`, `596d524`) passed 311/311 against 3.14.1.

## Architecture review fixes: backend 3.14.0, warehouse-service 1.1.0, consumer 3.6.0 — 9 November 2026

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.14.0@sha256:476c7e3bcb6edd65425fb4818411bdd0143347c4af40baff4c94198a5ec288b1` | [PR #91](https://github.com/slawekradzyminski/test-secure-backend/pull/91), `a076a57` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/42690292654) |
| `slawekradzyminski/warehouse-service:1.1.0@sha256:ae39b577695c7383d30e91ff96247c718ca5fce00fea4eff21460e114f17ee77` | [PR #3](https://github.com/slawekradzyminski/warehouse-service/pull/3), `8de7326` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/42690307715) |
| `slawekradzyminski/consumer:3.6.0@sha256:6975c932304eaba294b5cba87b14e3d8722ed6e6029031c0455524e0307b8775` | [PR #31](https://github.com/slawekradzyminski/jms-email-consumer/pull/31), `78de144` | [run](https://github.com/slawekradzyminski/jms-email-consumer/actions/runs/42690326854) |

This release fixes the findings of the warehouse architecture review:

1. **Stuck release.** A shipment release whose response was lost left the order
   `AWAITING_PICK` without a shipment and blocked every retry. The backend now
   accepts a repeated `AWAITING_PICK`. warehouse-service keeps the shipment when
   the order turns out to be released, and adopts released orders that have no
   shipment.
2. **Refunds.** Refunding a return books it on the backend order
   (`POST /internal/v1/orders/{id}/refunds`, idempotent, capped at the total). A
   full refund releases the coupon. Orders show `refundedAmount` once it is above
   zero.
3. **Cancellation propagation.** `ShipmentReconciler` cancels shipments whose
   order was cancelled on the backend, every minute (`GET /internal/v1/orders?ids=`).
4. **Email durability.** warehouse notifications use a transactional outbox with
   retries, and the backend deduplicates them by `requestId`. The backend stores
   email payloads and retries failed or lost sends (`EmailRetryJob`).
5. **Email text in one place.** The backend renders every email; the consumer
   delivers it unchanged.
6. **Database isolation.** warehouse-service connects as its own `warehouse` role,
   which owns only the `warehouse` schema. The one-shot `postgres-roles` and
   `aitesters-postgres-roles` services prepare it before every start.
7. **Multi-instance safety.** Return requests are serialised with an
   `order_locks` row lock instead of an in-process lock.
8. **No shared signing secret.** Access tokens are RS256 (`JWT_SIGNING_KEY` from
   Vault). warehouse-service verifies them with the backend's
   `/internal/v1/jwks.json`.

Migrations: backend Flyway V9 adds nullable or defaulted `email_event` columns,
`orders.refunded_amount` (default 0) and the `order_refunds` table.
warehouse-service V2 adds `notification_outbox` and `order_locks`. Rolling back
to backend 3.13.0 / warehouse-service 1.0.0 / consumer 3.5.0 (references in the
3.13.0 section and the wave-2 table) also needs the previous Compose files and
the HMAC Vault keys `jwt_secret_key` / `aitesters_jwt_secret_key`. Those were
removed from Vault on 2026-11-10, so a rollback first adds fresh random values
(`openssl rand -base64 48`); old tokens are invalid after the switch anyway.
Old images ignore the added columns and tables, so the backup is not needed for
rollback. Switching to RS256 invalidates the access tokens issued before the
deploy, and clients refresh them with their refresh tokens.

Verification before release: the backend passed 807 unit and 52 PostgreSQL
integration tests, and warehouse-service passed 205 tests. Locally built native
images of both passed their smoke tests (warehouse 61 MiB under the 160 MiB
limit; an HMAC token signed with the public key is rejected). An end-to-end run
of both native images on the lightweight stack covered RS256/JWKS, shipment to
delivery, return and refund booked on the order, backend-rendered emails, the
outbox, the reconciler and a JWKS refetch after a backend restart. The unchanged
course suite (`l20`, `596d524`) passed 311/311 against the 3.14.0 candidate with
no skips or flaky tests.

Production rollout (9 November 2026): the first `make ansible-deploy-backend-upgrade`
took the encrypted pre-deploy backup and then stopped at Compose convergence:
`aitesters-backend` rejected its Vault signing key. The keys had been generated
with `openssl genpkey -outform DER`, which OpenSSL 3 writes as PKCS#1, not
PKCS#8. The same key material was converted to PKCS#8 in Vault and the retry
finished with `failed=0` (135 tasks). Its verification covered both role
one-shots exiting 0, the `warehouse` role owning its schema without access to
`public`, and the reviewed image IDs. `docs/ANSIBLE.md` now gives the PKCS#8
command, and the deploy rejects PKCS#1 keys. A first CI run of the full profile
also showed that `docker-compose.model-mock.yml` replaced the backend's
`depends_on`, losing the healthy-database condition; the overlay now keeps it.
Public checks on both hosts: `/login`, `/v3/api-docs` and
`/warehouse/v3/api-docs` return 200, `/internal/v1/jwks.json` returns 404, and
warehouse endpoints return 401 without a token. A sandbox sign-in issues an
RS256 token with a `kid`; that token reads the warehouse queue and suppliers
(200) and gets 401 at the stable site. Flyway: backend V9, warehouse V2.
Measured memory: backend 177 MiB, aitesters-backend 154 MiB, both
warehouse-services 66 MiB, consumer 35 MiB; 2.8 GiB available.

## Backend 3.13.0: GraalVM native image — 9 November 2026

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.13.0@sha256:3cd23cef97589733eef13ad8372cc2454b6702f7d8286b9e6409cb73a470e8d4` | [PR #90](https://github.com/slawekradzyminski/test-secure-backend/pull/90), `eacad53` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/42532503854) |

The backend is now a GraalVM native executable, built per architecture on
matching runners and smoke-tested under the production and local profiles before
the manifest is published. Native images fix bean selection at build time, so the
backend's bean graph no longer depends on the active profile: GraphQL and gRPC are
always wired, `app.email.transport` selects Artemis or the local outbox, and the
bootstrap and seed runners check their properties at runtime. Profiles only carry
properties, so one image serves `docker,server`, `aitesters` and `local`.

Both backends drop the JVM blocklist mounts (the blocklist is baked in at build
time) and JVM options: `backend` runs with `-Xmx384m` in 640 MiB (was 1.5 GiB) and
`aitesters-backend` with `-Xmx256m` in 448 MiB (was 768 MiB). Native images report
an unknown heap maximum, so Ansible checks their `-Xmx` arguments. The unchanged
course suite (`l20`) passed 311/311 against this image on the PostgreSQL
compatibility stack, with both compatibility backends on the same image; the
backends peaked at 164–184 MiB. The course's admin sign-in test accepts either
opaque refresh-token format since `ai-testers-api` `b9ce4b7`.

A first `v3.13.0` run built both images but stopped at the smoke step (the script
was not executable); no image was tagged, and the tag was moved to the fix.
Previous reference: `slawekradzyminski/backend:3.12.0@sha256:4ab420bfcf8fa94aff2cbe9917d37593e054aa616ae35751295112953686a13a`. No migration; rolling back only needs the previous
image and the JVM Compose settings.

Production rollout (9 November 2026): `make ansible-deploy` converged both native
backends but its verification stopped at the direct-backend GraphQL check, which
ran `curl` inside the backend containers (the native image has none). After
[#75](https://github.com/slawekradzyminski/awesome-localstack/pull/75) moved that
check to the gateway container, `make ansible-verify` passed with `failed=0`. The
first `runDocker` CI run also exposed that the full profile started the backend
before PostgreSQL was healthy; the native backend now waits for a healthy database
there. Measured after the rollout: backend 245 MiB (JVM 409 MiB), aitesters-backend
160 MiB (JVM 363 MiB), 2.7 GiB available (was 2.3 GiB). The unchanged `l20` suite
passed 311/311 against production in 6.1 minutes; the single vCPU still saturates
under its parallel workers (CPU PSI waiting peaked at 100%, 66% average busy), so
native removes JIT warm-up and memory pressure but not per-request CPU.

## Backend 3.12.0: PostgreSQL in every profile — 8 November 2026

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.12.0@sha256:4ab420bfcf8fa94aff2cbe9917d37593e054aa616ae35751295112953686a13a` | [PR #88](https://github.com/slawekradzyminski/test-secure-backend/pull/88), `d7d2d0e` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/42514223453) |

The `local` and `aitesters` profiles now run on PostgreSQL with the production
Flyway migrations and `ddl-auto: validate`; H2 remains only in the backend's
unit tests. The aitesters sandbox gets `aitesters-postgres` (database
`aitesters`, warehouse schema `warehouse`, disk-backed and renewed by the daily
reset), and the lightweight and compatibility stacks get tmpfs PostgreSQL. The
unchanged course suite (`l20`) passed 311/311 against this image on the
PostgreSQL compatibility stack, with no skips or flaky tests.

The same rollout lowers CPU load on the single vCPU: 15s Spring scrapes, the
C1-only JIT on both backends and a `HostCpuSaturated` warning (CPU PSI waiting
above 90% for 30 minutes). Backward compatibility with older images is not a
goal; only the `l20` suite is. Previous reference: `slawekradzyminski/backend:3.11.0@sha256:a6d0a499fd54071c46eb1930b72fd75cde8ed71ee5cfa745f00c8013130d736d`.

Production rollout (8 November 2026): `make ansible-deploy` finished with
`failed=0`. Both hosts serve `/login`, `/v3/api-docs` and
`/warehouse/v3/api-docs` (200), keep `/internal/` at 404 and return 401 for
unauthenticated warehouse calls; `/h2-console` now falls through to the
frontend. `aitesters-postgres` holds 8 applied backend migrations, the seeded
catalogue and the `warehouse` schema. Measured memory: backend 409 MiB,
aitesters-backend 363 MiB, aitesters-postgres 83 MiB; 2.3 GiB available and a
load average of 0.3 after the rollout.

## Commerce wave 2: warehouse-service 1.0.0, backend 3.11.0, frontend 3.11.0, consumer 3.5.0 — 8 November 2026

Wave 2 moves fulfilment, returns and purchasing into the new GraalVM native
`warehouse-service` (see [WAREHOUSE_SERVICE_CONTRACT.md](WAREHOUSE_SERVICE_CONTRACT.md))
and switches the consumer to a native image.

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/warehouse-service:1.0.0@sha256:9fb2c27b9706072a95f7eef1445ce2bc1c14cab8f0dc4a21f025c8f1c3e669e9` | [warehouse-service](https://github.com/slawekradzyminski/warehouse-service), `c496ad3` | [run](https://github.com/slawekradzyminski/warehouse-service/actions/runs/42510213289) |
| `slawekradzyminski/backend:3.11.0@sha256:a6d0a499fd54071c46eb1930b72fd75cde8ed71ee5cfa745f00c8013130d736d` | [PR #86](https://github.com/slawekradzyminski/test-secure-backend/pull/86), `699a81c` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/42509255213) |
| `slawekradzyminski/frontend:3.11.0@sha256:ee573177bb35f0f32fc152b85c004793d2325c08ad70d35e0c105be8df21b7f0` | [PR #92](https://github.com/slawekradzyminski/vite-react-frontend/pull/92), `164a546` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/42510696494) |
| `slawekradzyminski/consumer:3.5.0@sha256:c21c33b73fe6fbd4943dc543ecd2688fd7434517bc2a1d259e9deb075a1863d0` | [PR #30](https://github.com/slawekradzyminski/jms-email-consumer/pull/30), `d557f12` | [run](https://github.com/slawekradzyminski/jms-email-consumer/actions/runs/42509987298) |

Backend 3.11.0 adds the token-guarded `/internal/v1` API for warehouse-service
and Flyway migration V8: `orders.fulfilment_state varchar(16) NOT NULL DEFAULT
'NONE'` with a check constraint and an index. `fulfilmentState` is omitted from
order bodies while it is `NONE`, so the unchanged course suite (`l20`) passed
311/311 against the published image with no skips or flaky tests.

warehouse-service and the consumer are native executables: `-Xmx64m` runtime
heaps inside 160 MiB containers (measured RSS about 58 MiB and 34–70 MiB). Their
JDK blocklist is baked in from the builder stage, so they have no runtime
blocklist mount, and their Micrometer heap maximum is unknown (`-1`); Ansible
checks their `-Xmx64m` argument instead. The aitesters sandbox runs its own
`aitesters-warehouse-service` with a tmpfs Postgres (96 MiB). Both frontends run
3.11.0 with the warehouse screens enabled.

Previous references for rollback: backend 3.10.1, frontend 3.10.0 and consumer
3.4.0 from the wave-1 table below. V8 only adds a defaulted column, a check and
an index; backend 3.10.1 does not map the column and still validates, so rolling
back does not require restoring the backup. Rolling back also requires removing
the warehouse services, or the screens will report errors.

Production rollout (8 November 2026): the first `make ansible-deploy-backend-upgrade`
stopped before quiescing because the deployed wave-1 Compose file did not define
`warehouse-service` yet; only the pre-deploy backup and the deploy silence ran and
wave 1 kept serving. After [#72](https://github.com/slawekradzyminski/awesome-localstack/pull/72)
the retry finished with `failed=0`. Public checks on both hosts: `/login`,
`/v3/api-docs` and `/warehouse/v3/api-docs` return 200, `/internal/v1/...` returns
404 and warehouse endpoints return 401 without a token. Measured memory after the
rollout: backend 458 MiB, aitesters-backend 431 MiB, consumer 44 MiB,
warehouse-service 50 MiB, aitesters-warehouse-service 68 MiB,
aitesters-warehouse-postgres 72 MiB; the host reported 2.3 GiB available.

## Commerce wave 1: backend 3.10.1, frontend 3.10.0, consumer 3.4.0 — 8 November 2026

Wave 1 of the commerce extensions (see [COMMERCE_FULFILMENT.md](COMMERCE_FULFILMENT.md)):
coupons, product reviews, wishlist with back-in-stock emails, product CSV
export/import, `Idempotency-Key` checkout, `ETag`/`If-Match` products and the
`warehouse` demo user. Warehouse fulfilment, returns and purchasing ship later
with `warehouse-service` (wave 2).

| Image | Source | Release workflow |
| --- | --- | --- |
| `slawekradzyminski/backend:3.10.1@sha256:45ac5391eadfd41e1a4df010700bd6073d1d16bcec0fec2b50fe4f2bea3cf8c0` | [PR #85](https://github.com/slawekradzyminski/test-secure-backend/pull/85) + [PR #87](https://github.com/slawekradzyminski/test-secure-backend/pull/87), `606a2f4` | [run](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/42506599471) |
| `slawekradzyminski/frontend:3.10.0@sha256:75508a827997b818db0c590445630c4ce23d1373d79da73d2ecc1240c0ba14ff` | [PR #91](https://github.com/slawekradzyminski/vite-react-frontend/pull/91), `29737f9` | [run](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/42504804256) |
| `slawekradzyminski/consumer:3.4.0@sha256:30cfbd3fdb861d7085c4c8a3ac9fbbc68ec9cd3c1d19befa196a155186cee297` | [PR #29](https://github.com/slawekradzyminski/jms-email-consumer/pull/29), `ab44182` | [run](https://github.com/slawekradzyminski/jms-email-consumer/actions/runs/42500121296) |

Backend 3.10.0 was published but never deployed: the pre-deploy run of the
unchanged course suite (`l20`, revision `c6f7aee`) failed 7 of 311 tests because
every cart and order body gained coupon fields, and the course compares whole
bodies with `toEqual`. Backend 3.10.1 omits those fields unless a coupon is
involved and passed the same suite 311/311 with no skips or flaky tests.

Backend 3.10.1 runs Flyway migration V7: new coupon, redemption, cart-coupon,
review, wishlist and idempotency tables, a nullable `orders.subtotal_amount`
backfilled from `total_amount`, `orders.discount_amount` and `coupon_code`, and
widened check constraints for roles (`ROLE_WAREHOUSE`), email event types and
inventory movement types. Existing rows are not rewritten except the subtotal
backfill; the pre-deploy encrypted backup covers rollback. Public paths, request
bodies, status codes and enums stay compatible with the AI Testers course suite.
New customer emails are rendered by the backend and published as `GENERIC`;
consumer 3.4.0 additionally maps unknown template names to `GENERIC`.

The frontend shows coupons and reviews only with the REST shop API (the GraphQL
schema has no such operations) and keeps the warehouse screens behind the
build-time `VITE_WAREHOUSE_ENABLED=false` flag.

Previous references for rollback:
`slawekradzyminski/backend:3.9.4@sha256:4e96ac25991adde6f62c91b7feda88c83d0d35002a81d7169677b390e326d2e8`,
`slawekradzyminski/frontend:3.9.3@sha256:e573282a98e98c19055ff865edfb027d286648a61086a0a5837005af6a2885ed`,
`slawekradzyminski/consumer:3.3.9@sha256:cb4a2d8a5980da03562e85f7f5bed9d7162c3cf6ce3551bce4eb00d6ca13fc60`.
V7 only adds tables, nullable or defaulted columns and wider checks, so the
previous backend still validates its entities against the migrated schema and
Flyway ignores the applied future migration; rolling back the image does not
require restoring the backup.

### Production rollout — 8 November 2026

[Stack CI](https://github.com/slawekradzyminski/awesome-localstack/actions/runs/42508232665)
ran on the merged pin set (PR #70 passed all eight jobs). `make
ansible-deploy-backend-upgrade` created the encrypted pre-deploy PostgreSQL
backup, pulled backend 3.10.1 before interrupting requests, stopped both old
backend instances, created a second encrypted backup after writes stopped, and
applied V7 on start. The playbook completed 123 tasks with 16 changes, zero
failures and zero unreachable hosts, and its verification passed.

External checks passed on both `awesome.byst.re` and `aitesters.byst.re`: `/`,
`/login`, `/products` and `/v3/api-docs` return 200; the OpenAPI document lists
the coupon, cart-coupon, wishlist and CSV export endpoints and no warehouse
paths; the served bundle contains the cart coupon panel. The checks did not sign
in or write data. The deployment log is saved privately in
`~/.config/awesome-localstack-security/deploy-commerce-wave1-20261108.log`.

## Frontend 3.9.3 data-testid coverage — 7 November 2026

Frontend 3.9.3 (`a9ecc11`) ships
[PR #87](https://github.com/slawekradzyminski/vite-react-frontend/pull/87).
It adds the missing `data-testid`s on Admin Inventory, the two-factor security
panel, the WebMCP lab and a few smaller controls. A unit test now fails when a
button, link, form control, form or alert has none. The PR also fixes a race in
which an agent search could restore the product category it had just cleared.
No existing test ID was renamed. No backend, consumer, model-mock, database or
secret change is required.

The [release workflow](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/42366228943)
passed validation, three browser shards, image verification and publication
for `linux/amd64` and `linux/arm64`.

Previous frontend reference for rollback:
`slawekradzyminski/frontend:3.9.2@sha256:03f85c1195381927f4a7fb0f1db424680327555e8cc4f2664878327d3042e545`.

### Production rollout — 7 November 2026

[Stack CI](https://github.com/slawekradzyminski/awesome-localstack/actions/runs/42366833611)
passed all eight jobs on the pinned set. `make ansible-deploy` created the
encrypted pre-deploy PostgreSQL backup and completed 118 tasks with 14 changes,
zero failures and zero unreachable hosts; the playbook's verification passed.
No backend, database or secret change was made.

External checks passed on both `awesome.byst.re` and `aitesters.byst.re`: `/`,
`/login`, `/products`, `/qr` and `/webmcp` return 200 and serve the 3.9.3
bundle, which contains the new test IDs. The checks did not sign in or write
data. The deployment log is saved privately in
`~/.config/awesome-localstack-security/deploy-frontend-3.9.3-20261107.log`.

## Frontend 3.9.2 accessibility and training fixes — 7 November 2026

Frontend 3.9.2 (`d13b94e`) combines three merged changes:
[PR #84](https://github.com/slawekradzyminski/vite-react-frontend/pull/84)
(npm audit fixes and nginx 1.31.8),
[PR #85](https://github.com/slawekradzyminski/vite-react-frontend/pull/85)
(WCAG 2.2 AA fixes from the playwright-2026 BUG-004 report) and
[PR #86](https://github.com/slawekradzyminski/vite-react-frontend/pull/86)
(frontend bugs BUG-001, BUG-003, BUG-005 to BUG-007 and BUG-010 to BUG-013).
The backend training bugs BUG-002, BUG-008 and BUG-009 are intentionally
unchanged for the AI Testers course. No backend, consumer, model-mock, database
or secret change is required.

User-visible behaviour changes: `/login` and `/register` keep an existing
session, protected routes pass `returnTo`, product filters live in the URL,
prices use thousands separators, invalid product ids are not requested, cart
stock comes from the cart payload, and the admin dashboard aggregates every
order page and marks failed data as unavailable.

The [release workflow](https://github.com/slawekradzyminski/vite-react-frontend/actions/runs/42355655377)
passed validation, three browser shards, image verification and publication
for `linux/amd64` and `linux/arm64`; the manifest list digest matches Docker Hub.

Previous frontend reference for rollback:
`slawekradzyminski/frontend:3.9.1@sha256:b19566ee4bdf1fcd04baeb1c5d7cf967d902d39d999bc68951b02822ba90ee17`.

### Production rollout — 7 November 2026

[Stack CI](https://github.com/slawekradzyminski/awesome-localstack/actions/runs/42356466870)
passed all eight jobs on the pinned set. The same PR fixed `verifyOllamaConfig`,
which still expected ollama-mock 1.0.9 after the 22 October release moved every
profile to 1.0.11. `make ansible-deploy` created the encrypted pre-deploy
PostgreSQL backup and completed 118 tasks with 14 changes, zero failures and
zero unreachable hosts; the playbook's verification passed and the warning
silences expired. No backend, database or secret change was made.

External checks passed on both `awesome.byst.re` and `aitesters.byst.re`: `/`,
`/login`, `/products`, `/qr` and `/webmcp` return 200 and serve the 3.9.2
bundle. A headless 390px browser saw an anonymous deep link redirect to
`/login?returnTo=%2Fproducts%2F7%3Fref%3Dsmoke`, the page title
"Sign in – Awesome Testing" with an `h1`, `username`/`current-password`
autocomplete, a field-linked validation error, no page errors and no horizontal
overflow. The checks did not sign in or write data. The deployment log is
saved privately in
`~/.config/awesome-localstack-security/deploy-frontend-3.9.2-20261107.log`.

## Source-owned security image releases — 22 October 2026

Final releases are backend 3.9.4 (`fd4c015`), frontend 3.9.1 (`607fe6b`),
consumer 3.3.9 (`b801fa3`) and model mock 1.0.11 (`0a77d42`). Their source-owned
release pipelines passed before immutable Docker Hub digests were selected.
Both AMD64 and ARM64 manifests, SBOM and provenance were published. Every Java
application image passes the offline 35-certificate lookup probe without a
Compose mount. The frontend image serves login, products, WebMCP and entry assets.

The backend's release checks include unit, PostgreSQL integration, local-app and
Docker smoke verification; the frontend includes three browser shards plus
commerce/WebMCP flows. Consumer publication verifies Artemis-to-Mailpit delivery;
model-mock publication verifies its API/container contract. Login checks now use
here-strings under `pipefail`, preserving the token assertion while avoiding a
producer SIGPIPE false failure when grep finishes early. No auth behavior changed.

Image pins are synchronized across full, lightweight, server, model-mock, gRPC
and course profiles, and sibling backend/frontend development Compose files.
Static image/certificate checks, remote manifests and Ansible syntax pass. The
default-branch l20 suite at `a3b2802a070f` passed all 190 tests with no skips or
retries, plus direct/proxied authenticated GraphQL, anonymous denial and a native
gRPC listener. The newer GraphQL course branch at `c6f7aee44150` also passed all 311 tests
with no failures, skips or retries, using the same final images and direct/proxied
GraphQL plus gRPC checks. Both course runs used isolated disposable local fixtures.

### Final production image rollout — 22 October 2026

Ansible completed 118 successful tasks with 15 changes, zero failures and zero
unreachable hosts. The encrypted PostgreSQL pre-deployment backup completed.
Both backend and frontend instances, the consumer and model mock now use the
reviewed image set below. Flyway validated the existing migrations and reported
the schema up to date; no migration or encryption-key change was needed.

Post-deployment checks passed exact image IDs, all five JVM blocklist checksums,
heap budgets, PostgreSQL authentication, stable/sandbox token isolation, direct
and proxied GraphQL, anonymous query denial, native gRPC listeners, JMS delivery
to private Mailpit, monitoring and public HTTPS probes. Public curl login and
OpenAPI GETs return 200 on both domains. The stable host rejects Mailpit paths
with 404. The sandbox returns the identical frontend SPA HTML for those unknown
prefixes, including the would-be mailbox API; it exposes no Mailpit UI or data.
An initial Python urllib login request returned 403 while curl checks passed;
no access policy was changed to obtain these results.

Deployment evidence is saved privately in
`~/.config/awesome-localstack-security/deploy-images-20261022-final.log`, with
course, registry, offline-certificate and public-smoke receipts beside it.
The existing local H2 stack was not reset and still needs its separately
approved restart; production PostgreSQL is independent and preserved.

## Current compatibility set

Release train: frontend 3.15.0, released 14 November 2026:

| Service | Immutable image |
| --- | --- |
| Backend | `slawekradzyminski/backend:3.21.1@sha256:872f6c143a7165d87b17da599a9ae9a31ffe7a6a2b1fb9b3124cb1db3bc78d73` |
| Frontend | `slawekradzyminski/frontend:3.15.0@sha256:7640d1625b460b1ad5d19a9a6176444c8d8765a527699140fa6fa81eeac0e325` |
| Consumer | `slawekradzyminski/consumer:3.6.0@sha256:6975c932304eaba294b5cba87b14e3d8722ed6e6029031c0455524e0307b8775` |
| Ollama mock | `slawekradzyminski/ollama-mock:1.0.13@sha256:7e3ea7b3c6774c38e81726e64e47323159cea53ce5777ab35754a0e5a9b4ef5e` |
| Warehouse service | `slawekradzyminski/warehouse-service:1.5.1@sha256:17adbb3cc45ed71bb522cae280e442f4af3690cb48a20627c6f04efdb6371a7e` |
| Payment service | `slawekradzyminski/payment-service:1.3.1@sha256:a82b2da62b18514a27039c716ac6d6b49a6ed804f58a739a8812f49cd91bc5b8` |
| Notification service | `slawekradzyminski/notification-service:1.0.1@sha256:1a051e8aa54e90f5e9dd9d8dbd1aacd94b1af6f886ea571a0f4d7cac23019c52` (not published yet; see [Distributed lab release](#distributed-lab-release-pending)) |

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
equivalent (equal-length clipping and an extra empty flush). Use the coordinated backend-upgrade target and encrypted-backup
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
PITest review is documented in the backend performance audit.

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

The production compatibility set is the seven first-party services above
(`PRODUCTION_SERVICES` in `scripts/verify-release-images.py`).
`notification-service` is listed but not yet published: the server profile
carries the `@sha256:PENDING_NOTIFICATION_SERVICE_DIGEST` placeholder (any
`PENDING_<SERVICE>_DIGEST` is recognised), the verification scripts report it
explicitly, and the server deployment refuses to run (see `docs/ANSIBLE.md`).
`scripts/release-train.py pin` uses the same reference in the lightweight, full
and server profiles (`notification-service` and
`aitesters-notification-service`) and replaces the table row above with the
immutable reference.
The main and `aitesters` variants do not have separate application release
lines: `aitesters-backend` must use the exact current backend reference and
`aitesters-frontend` must use the exact current frontend reference. Their
behavior differs through runtime profiles and routing, not through old images.
Previous application releases remain rollback references only.

`scripts/verify-release-images.py` checks that:

- each production service uses a `tag@sha256` reference;
- no profile still uses the `PENDING_PAYMENT_SERVICE_DIGEST` placeholder;
- full and server agree on backend, frontend, consumer, warehouse-service and
  payment-service releases;
- lightweight and server agree on backend, frontend, model-mock,
  warehouse-service and payment-service releases;
- the server's `aitesters` services reuse the exact backend, frontend,
  warehouse-service and payment-service releases;
- each warehouse- and payment-service uses its own database role, env file,
  backend and gateway upstream on its site, and both gateways declare the
  payment and tracking routes in every server block;
- the model-mock override agrees with the server model-mock release;
- this document records the exact selected references;
- with `--remote`, every manifest exists and contains both `linux/amd64` and `linux/arm64`.

Static pin verification runs in normal LocalStack CI. `.github/workflows/verify-release-images.yml` performs the registry check weekly and on manual request.

`scripts/verify-image-pins.py` extends the rule to every remotely pulled image
in all Compose profiles, the Jenkins Dockerfile, CI service containers, and the
PostgreSQL restore tool. Locally built `:local` images are the only exception.

## Release sequence

`scripts/release-train.py` automates the sequence below for backend
(`test-secure-backend`), warehouse-service, payment-service and frontend
(`vite-react-frontend`); `--with-consumer` adds `jms-email-consumer`, and
`--only backend,payment-service` narrows the set. Every subcommand recomputes
the release set from GitHub and `docker-compose.server.yml`, so a failed step
can be fixed and rerun. The global `--dry-run` performs only reads (GitHub
API, registry, files) and prints every action that would tag, write, commit,
push, merge or deploy.

```bash
python3 scripts/release-train.py plan               # what would be released
python3 scripts/release-train.py tag                # v<version> on green default-branch heads
python3 scripts/release-train.py wait               # publish workflows; fails fast with the run URL
python3 scripts/release-train.py pin                # digests -> Compose files and this document
make sync-release-images                            # sibling development Compose files
python3 scripts/release-train.py verify [--compat]  # Compose config + every contract script
python3 scripts/release-train.py pr --merge         # branch, commit, push, PR, CI, squash-merge
# then, from the main checkout (Vault links present), on merged main:
python3 scripts/release-train.py deploy --yes
```

| Step | What it does | Refuses when |
| --- | --- | --- |
| `plan` | Per repository: default-branch head, version from `pom.xml` / `package.json` (through `gh api`), latest `v*` tag, currently pinned version, and the action: `tag, publish, pin`, `pin` (tag exists), `up to date`, or `skip` (SNAPSHOT, older than the latest tag or the pin). Also prints the deploy target. | — |
| `tag` | Creates an annotated `v<version>` tag on the default-branch head of every repository whose version is untagged. | The head's CI workflow (`verify.yml` for the backend, `ci.yml` elsewhere) is not `success`; nothing is tagged then. |
| `wait` | Polls each repository's `publish-image.yml` run for the tag (`--timeout`, `--interval`). | A job fails or the run concludes with anything but `success`: exits at once with the run URL. |
| `pin` | Resolves the Docker Hub digest (`docker buildx imagetools inspect`), replaces the **current** pin of each image in every Compose file (other versions, e.g. rollback references in documents, are left alone), updates the image rows of [Current compatibility set](#current-compatibility-set) and inserts a release-section stub (PR, commit, run links; text marked TODO) above the newest dated section. | The publish run is not `success`. |
| `verify` | `docker compose config --quiet` for every profile (overlays on their base), every contract script, the release-train unit tests and `verify-release-images.py --remote` (`--offline` skips it). `--compat` first checks that Docker's clock is within 5 s of the host's (JWT issued-at checks fail otherwise), then runs `verify-course-compatibility.py`. | Any check fails. |
| `pr` | Creates `release/<image>-<version>…`, commits only the Compose files and this document, pushes, opens the PR, waits for its checks; `--merge` squash-merges. | Nothing was pinned. |
| `preflight` | `docker compose -f docker-compose.server.yml config --quiet` and `docker build --build-context repo-docs=docs docs-site` (the server's docs image build, `mkdocs build --strict`). Also `make deploy-preflight`, a prerequisite of the deploy targets. | Either check fails. |
| `deploy` | Runs `preflight`, then `make ansible-deploy-backend-upgrade` when the backend version differs from the previous commit's (`--since`, default `HEAD~1`: the squash-merged release), else `make ansible-deploy`. The target runs with `SKIP_DEPLOY_PREFLIGHT=1`. | No `--yes`; not on `main`; `HEAD` is not `origin/main`; dirty tree; the preflight fails; the Vault links `ansible/.vault_pass` or `ansible/inventory/group_vars/production/vault.yml` missing (presence only, never read). |

Fill in the release-section stub (what changes, LocalStack changes, upgrade
order, rollback) in the release PR before merging. New Vault keys still go in
before `deploy`, and the course suite (`l20`) runs after it. The pure parts
(version parsing, pin replacement, release-section rendering, deploy target,
deploy preflight) are unit-tested in `scripts/test_release_train.py` (CI job
`verifyReleaseTrain`).

The manual sequence the script follows:

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

For a release that spans several repositories (such as commerce wave 3),
publish in dependency order and pin everything in one LocalStack change:

1. backend (internal API and payment result endpoint first, since both
   services call it), then warehouse-service and payment-service, then the
   frontend; the consumer is unchanged;
2. add any new Vault keys before the deployment (the `app` role refuses to
   deploy without them);
3. deploy with `make ansible-deploy-backend-upgrade` when the backend adds
   migrations, then run the unchanged course suite (`l20`) against the result.

An application release does not require rebuilding unchanged applications. It does require retaining their known-good immutable references in the reviewed compatibility set. Backward compatibility is maintained for persisted data and external contracts where required; the deployment does not keep stale application images running as compatibility variants.

After every deploy, run the feature smoke test against both production hosts
(customer-level checks only; they create throwaway accounts and orders):

```bash
scripts/smoke-features.sh https://awesome.byst.re client
scripts/smoke-features.sh https://aitesters.byst.re client
```

Locally and in CI (`verifyLightweight`) the same script runs with `full`, which
adds the admin and warehouse flows using the demo accounts.

## GraphQL/gRPC 3.8.0 release

Backend [PR #59](https://github.com/slawekradzyminski/test-secure-backend/pull/59)
and tag `v3.8.0` add GraphQL commerce, GraphiQL, optional native admin inventory
RPCs, and metadata-only protocol traffic. The
[release workflow](https://github.com/slawekradzyminski/test-secure-backend/actions/runs/35515279059)
passed all gates and published both supported architectures with provenance and
SBOM. No database migration is introduced.

The frontend counterpart is tracked in
[PR #67](https://github.com/slawekradzyminski/vite-react-frontend/pull/67).
