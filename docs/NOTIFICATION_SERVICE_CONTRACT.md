# Notification service contract

`notification-service` sends the customer's commerce emails and owns user
webhooks. Both used to live in the backend; from backend 3.21.0 the backend
only records **events**, and notification-service turns them into emails and
signed webhook deliveries. Account emails (password reset, `POST
/api/v1/email`, `GET /api/v1/users/me/email-events`) stay in the backend.

The cross-repository contract is section 2 of
[DISTRIBUTED_LAB_CONTRACTS.md](DISTRIBUTED_LAB_CONTRACTS.md#2-notification-service);
this document is the runtime view and how this repository deploys it. The
decision is [ADR 5](ARCHITECTURE_DECISIONS.md#adr-5-notifications-move-out-of-the-backend).

## Runtime

| Item | Value |
| --- | --- |
| Repository | `notification-service` ([slawekradzyminski/notification-service](https://github.com/slawekradzyminski/notification-service)), default branch `master` |
| Image | `slawekradzyminski/notification-service`, GraalVM native image, `-Xmx64m` in a 160 MiB container |
| Port | 4005 (internal only, behind the gateway) |
| Database | PostgreSQL schema `notification` of the backend database, owned by the `notification` role (`currentSchema=notification`) |
| Profiles | `docker,demo` in the lightweight and full profiles, `docker` on the server |
| Authentication | Verifies the backend's RS256 access tokens with the backend JWKS (`/internal/v1/jwks.json`), like warehouse- and payment-service; it holds no signing key |
| Environment | `SPRING_DATASOURCE_URL`/`_USERNAME`/`_PASSWORD` (role `notification`), `BACKEND_BASE_URL`, `NOTIFICATION_SERVICE_TOKEN`, `NOTIFICATION_EMAIL_TRANSPORT` (`jms` or `local-outbox`, default `local-outbox`), `SPRING_ARTEMIS_*` with `jms`, `LOCAL_EMAIL_OUTBOX_ACCESS_KEY` (optional), `WEBHOOKS_SECRET_ENCRYPTION_PASSWORD`/`_SALT` (servers) |
| Optional tuning | `NOTIFICATION_EVENTS_ENABLED` (`true`), `NOTIFICATION_EVENTS_POLL_INTERVAL` (`PT5S`), every `WEBHOOKS_*` variable the backend accepted (limits, retry policy, `WEBHOOKS_ALLOWED_PORTS`), `SECURITY_RATE_LIMIT_ENABLED` |
| Requires | backend 3.21.0 or later (`NOTIFICATION` service caller, `notification.requested`, webhook export) |
| Metrics | `/actuator/prometheus`, scraped as `spring_notification_micrometer`; gauge `notification_outbox_pending` (pending webhook deliveries plus queued emails) |
| Tracing | `TRACING_ENABLED`, `TRACING_OTLP_ENDPOINT`, `TRACING_SAMPLING_PROBABILITY` (off by default; `docker-compose.tracing.yml` turns it on) |

### Email transport per profile

| Profile | Transport | Where the email ends up |
| --- | --- | --- |
| lightweight | `local-outbox` | In memory: `GET /api/v1/local/notifications/outbox` (no key) |
| full | `jms` to `tcp://activemq:61616` | Queue `email` → `consumer` → Mailpit (`http://localhost:8025`) |
| server, `awesome.byst.re` | `jms` (broker credentials from Vault) | Queue `email` → `consumer` → Mailpit (loopback only) |
| server, `aitesters.byst.re` | `local-outbox` | In memory, guarded by `LOCAL_EMAIL_OUTBOX_ACCESS_KEY` like the backend's local outbox |

This mirrors the backends: the full profile and the stable server backend send
account emails through the broker, the lightweight backend and the sandbox use
the local outbox.

## Public API

All endpoints need a backend access token unless stated otherwise. Paths,
JSON shapes, status codes, limits, the signature header and the SSRF rules
are those of backend 3.20.1, so clients and the frontend did not change.

| Method and path | Result |
| --- | --- |
| `GET /api/v1/webhooks/event-types` | Webhook-eligible types, now including `order.reservation-expired` |
| `POST /api/v1/webhooks`, `GET /api/v1/webhooks`, `GET/PUT/DELETE /api/v1/webhooks/{id}` | Subscriptions of the caller (at most 5) |
| `POST /api/v1/webhooks/{id}/test`, `POST /api/v1/webhooks/{id}/rotate-secret` | Ping delivery, new secret |
| `GET /api/v1/webhooks/{id}/deliveries`, `.../deliveries/{deliveryId}`, `POST .../redeliver` | Delivery log and redelivery |
| `POST /api/v1/webhook-inboxes`, `GET /api/v1/webhook-inboxes`, `GET /api/v1/webhook-inboxes/{token}/requests` | Built-in receiver (`inbox://<token>`) for training without a public URL |
| `GET /api/v1/admin/webhooks` | Every subscription (`ROLE_ADMIN`) |
| `GET /api/v1/notifications/emails?page&size` | The caller's commerce emails, newest first, recipient masked (`j***@example.com`); `ROLE_ADMIN` may pass `username` |
| `GET /api/v1/local/notifications/outbox` | Local outbox (only with `local-outbox`; `X-Local-Outbox-Key` when a key is configured) |
| `GET /v3/api-docs` | OpenAPI, published by the gateway as `/notification/v3/api-docs` |

Deliveries carry `X-Webhook-Signature: t=<epochSeconds>,v1=<hex HMAC-SHA256(secret, t + "." + body)>`,
`X-Webhook-Event`, `X-Webhook-Id` and the backend request's
`X-Request-Id`; the body is byte-compatible with what backend 3.20.1 sent.
Retries double from 1 minute, eight attempts; 20 consecutive failures disable
a subscription.

## What it consumes

notification-service is a standard feed consumer (ADR 1, ADR 3) with the
cursor `notification-service` in `notification.event_cursors`:

| Feed type | Handling |
| --- | --- |
| `order.created`, `order.paid`, `order.cancelled`, `order.reservation-expired`, `shipment.shipped`, `shipment.delivered`, `refund.booked`, `payment.failed` | One delivery per active matching subscription of the order's owner |
| `notification.requested` (internal) | Renders the template with `CustomerEmailRenderer` (moved from the backend), records it in `notification_emails` (`QUEUED` → `SENT` or `FAILED`) and sends it with the configured transport; `requestId` deduplicates |

Emails follow the outbox convention of ADR 3 (backoff 30 s doubling to 30 min,
at most 10 attempts, retried every `PT30S`).

## Internal API

Calls go one way, from notification-service to its backend, with
`X-Service-Token: ${NOTIFICATION_SERVICE_TOKEN}`. The backend accepts the
notification token only on:

- `GET /internal/v1/jwks.json`: access-token verification keys;
- `GET /internal/v1/events?after&limit&types`: the event feed
  ([EVENT_FEED.md](EVENT_FEED.md));
- `GET /internal/v1/webhooks/export`: one-time import of subscriptions (with
  their secrets and ids) and inboxes; 404 once the backend no longer has them.

On start, when both its webhook tables are empty, notification-service imports
the export, so existing subscriptions keep their ids and secrets across the
move. A 404 or an empty export ends the import. Deliveries and inbox requests
are not imported.

The backend never calls notification-service. `/internal/` is 404 on every
gateway host.

## Gateway

Every application gateway server block (lightweight/full, and the stable and
aitesters hosts on the server) routes these locations to notification-service
through a request-time `$notification_upstream` variable, so the gateway
starts and the backend keeps serving when notification-service is absent (the
paths below then answer 502):

| Location | Example |
| --- | --- |
| `= /api/v1/webhooks` | `POST /api/v1/webhooks` |
| `/api/v1/webhooks/` | `GET /api/v1/webhooks/12/deliveries` |
| `= /api/v1/webhook-inboxes` | `POST /api/v1/webhook-inboxes` |
| `/api/v1/webhook-inboxes/` | `GET /api/v1/webhook-inboxes/{token}/requests` |
| `= /api/v1/admin/webhooks` | `GET /api/v1/admin/webhooks` |
| `/api/v1/notifications/` | `GET /api/v1/notifications/emails` |
| `/api/v1/local/notifications/` | `GET /api/v1/local/notifications/outbox` |
| `^~ /notification/v3/api-docs` | rewritten to notification-service `/v3/api-docs` |

The backend's webhook endpoints stay mapped (`webhooks.enabled=false` only
stops its dispatcher), but no gateway sends traffic there any more. The
backend's own `/api/v1/local/email/outbox` keeps the account emails.

## Deployment in this repository

- **Compose.** `notification-service` in `lightweight-docker-compose.yml`
  (160 MiB) and `docker-compose.yml`; `notification-service` and
  `aitesters-notification-service` in `docker-compose.server.yml`, both
  `-Xmx64m` in 160 MiB with the bash `/dev/tcp` healthcheck on
  `/actuator/health`. They start after a healthy backend and the one-shot
  `postgres-roles` (`aitesters-postgres-roles`); the stable one also after a
  healthy `activemq`.
- **Backend settings.** Every backend next to a notification-service gets
  `NOTIFICATION_SERVICE_TOKEN`, `NOTIFICATIONS_DELIVERY=feed` and
  `WEBHOOKS_ENABLED=false` (`scripts/verify-release-images.py` checks all
  three profiles). `docker-compose.compatibility.yml` (the l20 course stack) is
  backend-only and keeps the defaults (`email`, webhooks on).
- **Database role.** `postgres/service-roles.sh` prepares `warehouse`,
  `payment` and `notification`; each role owns only its schema and cannot use
  the others'.
- **Secrets.** Ansible renders `.env.notification` (token, role password,
  broker credentials, webhook secret encryption key) and
  `.env.aitesters-notification` (token, role password, its own encryption key,
  local outbox key) from Vault; see
  [ANSIBLE.md](ANSIBLE.md#notification-service-secrets-and-image-gate).
- **Labs.** `docker-compose.chaos.yml` routes it through `notification-to-backend`
  (`toxiproxy:34001`) and `notification-to-postgres` (`toxiproxy:45432`);
  `docker-compose.tracing.yml` turns its tracing on.
- **Image pin.** Until 1.0.0 is published the server profile carries
  `slawekradzyminski/notification-service:1.0.0@sha256:PENDING_NOTIFICATION_SERVICE_DIGEST`
  and the local profiles use the bare `1.0.0` tag (a locally built image with
  that tag runs as is). `scripts/verify-release-images.py`,
  `scripts/verify-image-pins.py` and the Ansible image gate fail until
  `scripts/release-train.py pin` replaces them with the published digest (see
  [CONTAINER_RELEASES.md](CONTAINER_RELEASES.md#distributed-lab-release-pending)).
