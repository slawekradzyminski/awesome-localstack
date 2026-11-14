# Service-to-service trust

Four services cooperate on one order. They trust each other through
**service tokens**, **HMAC signatures** and **idempotency keys**, never through
user JWTs.

```mermaid
flowchart LR
    W[warehouse-service] -- "X-Service-Token: WAREHOUSE_SERVICE_TOKEN<br/>(calls and event feed polls)" --> I["backend /internal/v1"]
    P[payment-service] -- "X-Service-Token: PAYMENT_SERVICE_TOKEN<br/>(calls and event feed polls)<br/>X-Payment-Signature (HMAC) on results" --> I
    N[notification-service] -- "X-Service-Token: NOTIFICATION_SERVICE_TOKEN<br/>(event feed polls, webhook export)" --> I
    N -- "X-Webhook-Signature (HMAC, per subscription)" --> U[customer webhook URL]
```

The backend calls none of the services (since backend 3.16.0; notification-service
from 3.21.0): they poll its event feed instead. payment-service has no internal API of its own any more.

## Internal API (`/internal/v1` on the backend)

- Not routed by the gateway (`/internal/` is `404` on every host), not in the
  OpenAPI document, no CORS, not captured by the traffic monitor, and the
  `X-Service-Token` header is redacted from logs.
- Each **caller** has its own token. Tokens are compared in constant time.

| Caller | Backend property | Environment variable | `local` profile default |
| --- | --- | --- | --- |
| warehouse | `internal.service-tokens.warehouse` (alias `warehouse.service-token`) | `WAREHOUSE_SERVICE_TOKEN` | `local-warehouse-token` |
| payment | `internal.service-tokens.payment` | `PAYMENT_SERVICE_TOKEN` | `local-payment-token` |
| notification (3.21.0) | `internal.service-tokens.notification` | `NOTIFICATION_SERVICE_TOKEN` | `local-notification-token` |

The Compose files set their own development defaults
(`local-warehouse-service-token-change-me`,
`local-payment-service-token-change-me`,
`local-notification-service-token-change-me`) on both sides; production takes the
values from Ansible Vault.

| Endpoint | Accepted callers |
| --- | --- |
| `GET /internal/v1/jwks.json`, `GET /internal/v1/events` | warehouse, payment, notification |
| `GET /internal/v1/orders/{id}` | warehouse, payment |
| `GET /internal/v1/webhooks/export` | notification only |
| `POST /internal/v1/orders/{id}/payment` | payment only |
| everything else (`orders` queue, `fulfilment`, `refunds`, `warehouse-cancel`, `products`, `inventory/receipts`, `notifications`) | warehouse only |

| Situation | Response |
| --- | --- |
| No token configured for any caller of that path | `404 {"message":"Not found"}` |
| Missing token, wrong token, or another caller's token | `401 {"message":"Invalid service token"}` — even with a valid user JWT |

The full endpoint list is in the
[warehouse contract](../reference/WAREHOUSE_SERVICE_CONTRACT.md#internal-api-backend-called-by-warehouse-service)
and the [payment contract](../reference/PAYMENT_SERVICE_CONTRACT.md#internal-api).

## Payment result signature

payment-service reports every final payment result to
`POST /internal/v1/orders/{orderId}/payment` with two credentials:

```http
X-Service-Token: <PAYMENT_SERVICE_TOKEN>
X-Payment-Signature: t=1794346833,v1=<hex>
```

`v1` is the lowercase hex HMAC-SHA256 of `t + "." + rawBody`, keyed with
`PAYMENT_WEBHOOK_SECRET`. The backend rejects (`401 Invalid payment signature`)
a missing or wrong signature, a changed body, a timestamp more than 5 minutes
away, or a blank secret. The stored body is resent byte for byte and re-signed
on every retry.

The same scheme (`t=…,v1=…`, HMAC-SHA256 of `t.body`) signs
[user webhooks](../flows/webhooks.md#signature), with a per-subscription
`whsec_…` secret.

## Idempotency everywhere

| Call | Key | Replay behaviour |
| --- | --- | --- |
| Checkout `POST /api/v1/orders` | optional `Idempotency-Key` header, per user, 24 h | same address → original order, `201`, `Idempotent-Replayed: true`; different address → `409` |
| Payment `POST /api/v1/payments` | required `Idempotency-Key`, per caller | same body → original payment in its current state, `200`, `Idempotent-Replayed: true`; other body → `409` |
| Payment result → backend | `requestId` | same order, payment and status → first answer, no side effects; anything else → `409` |
| Card refund event → payment-service | event `id` (in `processed_events`), then the refund `requestId` | a seen event is skipped; a seen `requestId` books nothing |
| `order.cancelled` event → warehouse-service | event `id` (in `processed_events`) | skipped; cancelling a cancelled shipment is a no-op |
| Return refund → backend | `requestId = UUID.nameUUIDFromBytes("refund-" + returnId)` | same order and amount → order unchanged; else `409` |
| Stock receipts → backend | receipt `requestId` | same type and lines → original movement ids; else `409` |
| Notifications → backend | `requestId` | accepted again, no second email |
| Fulfilment state → backend | the target state | repeating the current state is a no-op `200` |

Idempotency keys must match `^[A-Za-z0-9_-]{8,64}$`.

## Outboxes and retries

Every cross-service side effect is written to an outbox table in the same
database transaction as the business change, sent right after the commit, and
retried by a scheduled job. A crash between "commit" and "send" therefore
delays the message instead of losing it.

| Outbox | Owner | Delivers to | Retry policy |
| --- | --- | --- | --- |
| `notification_outbox` | warehouse-service | backend `POST /internal/v1/notifications` | every 30 s, exponential backoff, up to 10 attempts, while the backend answers `503`; other rejections are final |
| `payment_outbox` | payment-service | backend payment result | 30 s doubling to 30 min, at most 10 attempts, on `5xx` or connection errors; `409` to a capture voids the payment; `401`/`422` are final |
| `email_event` + `EmailRetryJob` | backend | ActiveMQ queue `email` | every minute, backoff 1, 2, 4, 8 minutes, five attempts in total |
| `webhook_deliveries` | notification-service (backend up to 3.20.x) | customer URLs | 1, 2, 4… minutes, 8 attempts, auto-disable after 20 consecutive failures |
| `notification_emails` | notification-service | ActiveMQ queue `email` or the local outbox | 30 s doubling to 30 min, at most 10 attempts |

The outboxes share a convention (backoff, row state, metrics) but no code; see
[ADR 3](../reference/ARCHITECTURE_DECISIONS.md#adr-3-outbox-and-feed-consumer-implementations-stay-per-service).

## Event feed

Events the services must react to travel the other way: the backend writes
every domain event to `domain_events` in the same transaction as the change,
and the services **pull** them.

| Feed | Writer | Readers | Delivery |
| --- | --- | --- | --- |
| `domain_events`, `GET /internal/v1/events` | backend | payment-service (`card-refund.requested`), warehouse-service (`order.cancelled`), notification-service (webhook types, `notification.requested`) | each consumer polls every 5 s from its own cursor; events are served after a 3 s settle delay and kept for 30 days; at-least-once, deduplicated by event `id` |

Up to backend 3.15.0 card refunds went the other way, from a backend
`payment_refund_outbox` to `POST /internal/v1/payments/refunds` on
payment-service. Backend 3.16.0 replaced that with the feed. Details:
[Event feed](../reference/EVENT_FEED.md).

## Write ordering in warehouse-service

warehouse-service follows **validate locally → call the backend → persist**,
so a failed backend call leaves no orphaned local state. Creating a shipment is
the one place where the local row is written first and removed again if the
backend refuses; a lost response is recovered because the backend accepts a
repeated `AWAITING_PICK`. Customer cancellations arrive through the event
feed within seconds; a reconciler runs every ten minutes as a safety net and
adopts orders released without a shipment. See
[Warehouse fulfilment](../flows/fulfilment.md#consistency-with-the-backend).
