# Awesome Testing Project Audit

Audit date: 2026-07-17

Scope:

- `awesome-localstack`
- `test-secure-backend`
- `vite-react-frontend`
- `jms-email-consumer`
- `ollama-mock`
- AI Testers course compatibility contract

## Executive summary

The application code is in good shape, but the production and release infrastructure still has several worthwhile improvements. The three most urgent areas are backups, container vulnerabilities, and proxy trust.

Spring Boot is already on the current `4.1.0` release, production PostgreSQL is current at `16.14`, the frontend production npm audit reports zero vulnerabilities, and the owned backend, consumer, and mock images scanned clean for critical/high fixable findings. Broad application dependency modernization is therefore not the priority.

Recommended execution order:

1. Backup and restore automation.
2. Nginx/frontend image release.
3. Forwarded-IP trust fix.
4. Mailpit and infrastructure image upgrades.
5. CI and repository security controls.
6. Messaging reliability.
7. Authentication cookie migration.

## Priority 0 — handle next

### 1. Automate PostgreSQL backups and restore tests

Production currently relies on the `postgres-data` Docker volume in `docker-compose.server.yml`, with no off-server backup.

Add:

- Daily encrypted `pg_dump` copied off the Mikrus server.
- Retention, for example 7 daily and 4 weekly backups.
- A pre-deployment backup.
- A scheduled restore verification into a temporary database.

This is the largest operational risk: a volume or server failure currently means permanent data loss.

### 2. Rebuild and release the frontend on a safe nginx base

The frontend uses `nginx:1.29.1-alpine`. The point-in-time Docker Scout scan reported 5 critical and 30 high fixable package findings.

The gateway's `nginx:1.29.7-perl` also reported 22 high findings, and Perl is not used. Current nginx advisories list several issues fixed only in newer 1.30/1.31 releases.

Recommendation:

- Use `nginx:1.31.2-trixie` for frontend and gateway.
- Drop the unnecessary `-perl` variant.
- Run nginx unprivileged where feasible.
- Add an image vulnerability gate to every release.

The audit scan of `nginx:1.31.2-trixie` reported zero fixable critical/high findings.

References:

- <https://nginx.org/en/security_advisories.html>
- <https://hub.docker.com/_/nginx>

### 3. Fix trusted proxy and client-IP handling

Nginx appends caller-controlled values using `$proxy_add_x_forwarded_for`, while the backend selects the first address from `X-Forwarded-For`.

If the origin is reachable directly, callers can spoof the address used by rate limiting.

Fix by:

- Replacing the gateway header with `X-Forwarded-For $remote_addr`.
- Alternatively, parsing forwarded headers only from explicitly trusted proxy CIDRs.
- Restricting origin port 80 at the firewall where the hosting arrangement permits it.

## Priority 1 — production hardening

### 4. Replace MailHog with Mailpit

`mailhog/mailhog:v1.0.1` dates from 2020 and its image reported 6 critical and 64 high fixable findings.

Mailpit is actively maintained and SMTP-compatible. Its current `v1.30.4` image scanned with zero critical/high findings.

References:

- <https://github.com/mailhog/mailhog>
- <https://mailpit.axllent.org/docs/install/docker/>

### 5. Refresh infrastructure images in controlled batches

Current production pins:

- Grafana `11.5.1`; the current line is 13.x.
- Prometheus `3.1.0`; the current line is 3.13.x.
- Artemis `2.31.2`; the official current release found during the audit is 2.42.0.
- Local Keycloak `26.0`; the current line is 26.7.
- PostgreSQL `16.14` is already current and should remain as-is.

Grafana and Artemis still have findings even on newer images, so scan and assess them rather than assuming an upgrade eliminates everything. Disable the Artemis web console and Jolokia in production if they are not required.

References:

- <https://grafana.com/docs/grafana/latest/whatsnew/>
- <https://prometheus.io/download/>
- <https://activemq.apache.org/components/artemis/download>
- <https://www.keycloak.org/blog>
- <https://www.postgresql.org/docs/16/release-16-14.html>

### 6. Persist and harden message delivery

Artemis currently uses an anonymous image volume. Give it a named volume so pending email messages survive controlled replacement and can be managed.

The consumer should also gain:

- Explicit redelivery limits and DLQ handling.
- Idempotency protection against duplicate email delivery.
- A real Artemis and SMTP integration test.
- Message validation before sending.

### 7. Strengthen GitHub controls

Current state:

- No default branch is protected.
- Workflows run only on `push`, not explicitly on pull requests.
- Consumer and mock have no CI workflows.
- No repository has CodeQL analysis.
- Secret scanning is disabled for localstack, backend, and consumer.
- Actions are pinned to version tags, not immutable commit SHAs.

Enable pull-request checks, protected branches, CodeQL, secret scanning, and SHA-pinned actions.

References:

- <https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configuring-default-setup-for-code-scanning>
- <https://docs.github.com/en/actions/reference/security/secure-use>
- <https://docs.github.com/en/repositories/configuring-branches-and-merges/managing-protected-branches/about-protected-branches>

### 8. Make image versions a single source of truth

Version drift is significant:

- Production: backend `3.7.8`, frontend `3.7.4`.
- CI/lightweight stack: backend `3.6.15`, frontend `3.6.16`.
- `docker-run-all.sh`: backend/frontend `3.6.11`.
- Frontend's own Compose file: backend `3.7.7`.

Consequently, part of localstack CI validates an old application rather than the released stack. Introduce one release manifest or version environment file and update every Compose variant automatically.

### 9. Improve session storage and browser headers

Both access and refresh tokens are stored in `localStorage`. OWASP recommends not storing authentication or refresh tokens there because any XSS can read them.

Preferred approach:

- Store the refresh token in a `Secure; HttpOnly; SameSite` cookie.
- Keep a short-lived access token in memory.
- Preserve existing JSON token responses where needed for the course contract.
- Add CSP, `Referrer-Policy`, `Permissions-Policy`, and frame protection to frontend and gateway responses.

Live `/login` responses currently lack these application security headers.

Reference:

- <https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>

### 10. Add actionable monitoring

Prometheus currently scrapes only the main backend and consumer, with no alerting.

Add:

- `aitesters-backend`, gateway, PostgreSQL, and Artemis health.
- External HTTPS probes for both domains.
- Alerting for availability, JVM pressure, database storage, and email queue depth.
- Persistent Prometheus storage if monitoring history is useful.

External monitoring is especially important because it would detect Mikrus or edge `520` failures even when containers remain locally healthy.

## Priority 2 — quality and maintainability

### 11. Enforce the existing frontend quality checks in CI

Add frontend lint and `test:coverage` to CI. Both passed during the audit:

- 60 test files passed.
- 438 tests passed.
- 89.33% line coverage.
- 88.93% statement coverage.
- 80.14% branch coverage.
- 85.71% function coverage.

The thresholds are configured but ordinary CI currently invokes only the standard test command and build.

### 12. Harden the consumer configuration

- Replace wildcard actuator exposure.
- Stop returning stack traces and binding details by default.
- Stop logging recipient email addresses.
- Add CI for unit and integration tests.

### 13. Harden the Ollama mock

- Use a JRE rather than a full JDK for the runtime image.
- Run as a non-root user.
- Add a healthcheck.
- Move prompt and per-token logging from `INFO` to `DEBUG` or `TRACE`.
- Avoid logging potentially sensitive prompt content by default.

### 14. Align Maven artifact versions with image releases

Backend and consumer still identify as `1.0.0`, and the mock identifies as `0.0.1-SNAPSHOT`, despite Docker releases `3.7.8`, `3.3.3`, and `1.0.5`.

Use one revision property per repository and make release tooling update it together with the image tag.

### 15. Keep and tighten Flyway migrations

Flyway migrations should remain permanently in source control.

Recommended follow-up:

- Disable `baseline-on-migrate` now that production is initialized.
- Pin migration tests to PostgreSQL `16.14`.
- Verify the expected Flyway schema version during deployment.
- Never edit an applied migration; add a new migration instead.

### 16. Formalize the course contract release gate

Use the AI Testers course repository as a formal feedback loop:

- Run the latest available lesson, currently `l12`, before deployment.
- Optionally run all lesson folders nightly against the resettable environment.
- Preserve behavior covered by the course tests.
- Allow endpoints not covered by the course contract to evolve normally.

Reference:

- <https://github.com/AI-Testers-pl/ait2api1-api-ai/tree/master/l12>

## Verified state during the audit

- Latest GitHub Actions runs for localstack, backend, and frontend were green.
- Both production domains returned HTTP 200 for `/login` and `/actuator/health`.
- Frontend lint passed.
- Frontend production `npm audit` reported zero vulnerabilities.
- Frontend had only routine patch updates available; TypeScript 7, jsdom 29, and Node type definitions 26 should be handled separately as major upgrades.
- Backend, consumer, and mock owned images reported zero critical/high fixable findings in the point-in-time Docker Scout scan.
- All Compose files validated successfully with `docker compose config`.
- Spring Boot `4.1.0` and PostgreSQL `16.14` are current.

References:

- <https://spring.io/blog/2026/06/10/spring-boot-4/>
- <https://docs.docker.com/guides/docker-scout/>

## Audit caveats

Container scan counts are package-level, point-in-time findings, not proof that every reported vulnerability is exploitable in this deployment. They should be used for prioritization, followed by runtime and exposure assessment.

The existing uncommitted Qwen/Ollama version edits were outside this audit and were left untouched.
