# Payment service contract

`payment-service` takes card payments for orders with a simulated card
provider. The backend (`test-secure-backend`) keeps orders and their status; a
payment only changes an order through the backend's internal API. This
document is the boundary both sides implement and how this repository deploys
it. The backend side of the result notification is also summarised in
[WEBHOOKS.md](WEBHOOKS.md).

## Runtime

| Item | Value |
| --- | --- |
| Repository | `payment-service` ([slawekradzyminski/payment-service](https://github.com/slawekradzyminski/payment-service)) |
| Image | `slawekradzyminski/payment-service`, GraalVM native image, `-Xmx64m` in a 160 MiB container |
| Port | 4004 (internal only, behind the gateway) |
| Database | PostgreSQL schema `payment` of the backend database, owned by the `payment` role (`currentSchema=payment`); Flyway V1 baseline, V2 order payment locks, V3 event feed cursor (`event_cursors`, `processed_events`, 1.1.0) |
| Profiles | `docker,demo` in the lightweight and full profiles, `docker` on the server (like warehouse-service) |
| Authentication | Verifies the backend's RS256 access tokens with the backend JWKS (`/internal/v1/jwks.json`), exactly like warehouse-service; it holds no signing key |
| Environment | `SPRING_DATASOURCE_URL`/`_USERNAME`/`_PASSWORD` (role `payment`), `BACKEND_BASE_URL`, `PAYMENT_SERVICE_TOKEN`, `PAYMENT_WEBHOOK_SECRET` |
| Optional tuning | `PAYMENT_SETTLEMENT_DELAY` (default `PT10S`) for the delayed test cards; `PAYMENT_EVENTS_ENABLED` (default `true`) and `PAYMENT_EVENTS_POLL_INTERVAL` (default `PT5S`) for the event feed poller (1.1.0) |
| Requires | backend 3.16.0 or later from payment-service 1.1.0 (event feed); 1.0.0 works with backend 3.15.0 |
| Metrics | `/actuator/prometheus`, scraped as `spring_payment_micrometer` |

Only the card brand and the last four digits are stored. Card numbers and CVCs
are never logged.

## Public API

All endpoints need a backend access token. Customers see only payments of
their own orders; `ROLE_ADMIN` sees all.

From 1.1.0 another user's payment or order payments are answered **404**
exactly like a missing one (`GET /api/v1/payments/{id}`,
`POST /api/v1/payments/{id}/3ds`, `GET /api/v1/orders/{orderId}/payments`), so
the existence of other users' orders and payments is not revealed, as the
backend does for orders. Only paying another user's order
(`POST /api/v1/payments`) stays 403.

| Method and path | Result |
| --- | --- |
| `POST /api/v1/payments` | 201 `PaymentDto` |
| `POST /api/v1/payments/{id}/3ds` | 200 `PaymentDto` |
| `GET /api/v1/payments/{id}` | 200 `PaymentDto` |
| `GET /api/v1/orders/{orderId}/payments` | 200 list, newest first |
| `GET /api/v1/admin/payments?status=&page=&size=` | 200 page `{content, pageNumber, pageSize, totalElements, totalPages}` (`ROLE_ADMIN`) |

`POST /api/v1/payments`:

- header `Idempotency-Key` is required and matches `^[A-Za-z0-9_-]{8,64}$`;
- body `{orderId, card: {number, expiryMonth, expiryYear, cvc, holderName}}`;
- replaying the same key with the same body returns 200 with the original
  payment and `Idempotent-Replayed: true`; the same key with a different body
  is 409;
- 400 for validation errors, a Luhn-invalid number or an expired card;
  401 without a token; 403 for another user's order; 404 for an unknown order;
  409 when the order is not payable (not `PENDING`, already paid, or another
  payment of it is `REQUIRES_ACTION` or `PROCESSING`).

`POST /api/v1/payments/{id}/3ds` with `{code}`: `123456` captures the payment,
any other code fails it with `THREE_DS_FAILED`; 404 for a missing or another
user's payment; 409 unless the payment is `REQUIRES_ACTION`.

```text
PaymentDto { id (UUID), orderId, status, amount, currency, cardBrand, cardLast4,
             failureCode, failureMessage,
             nextAction { type: THREE_DS_CHALLENGE, hint } | null,
             refundedAmount, createdAt, updatedAt }

status: REQUIRES_ACTION | PROCESSING | CAPTURED | FAILED |
        PARTIALLY_REFUNDED | REFUNDED | VOIDED
```

The amount charged is the order's `amountDue` (total minus any gift-card and
loyalty-points tenders), in the base currency USD.

## Test cards

Any expiry date in the future and any three-digit CVC work.

| Number | Outcome |
| --- | --- |
| `4242 4242 4242 4242` | `CAPTURED` immediately (VISA) |
| `5555 5555 5555 4444` | `CAPTURED` immediately (MASTERCARD) |
| `4000 0000 0000 0002` | `FAILED`, `CARD_DECLINED` |
| `4000 0000 0000 9995` | `FAILED`, `INSUFFICIENT_FUNDS` |
| `4000 0000 0000 3220` | `REQUIRES_ACTION` (3-D Secure; code `123456`) |
| `4000 0000 0000 0077` | `PROCESSING`, then `CAPTURED` after the settlement delay (10 s) |
| `4000 0000 0000 0119` | `PROCESSING`, then `FAILED` `PROVIDER_TIMEOUT` after the same delay |
| `4000 0000 0000 0259` | `CAPTURED`; the result is delivered to the backend twice (idempotency demo) |

Any other Luhn-valid number succeeds; a Luhn-invalid number is 400.

## Internal API

Calls go one way only, from payment-service to the backend; the backend never
calls payment-service (from backend 3.16.0 and payment-service 1.1.0).
`/internal/` is not routed by the gateway (404 on every host). Every request
carries `X-Service-Token: ${PAYMENT_SERVICE_TOKEN}`; the backend accepts the
payment token on `GET /internal/v1/orders/{id}`,
`POST /internal/v1/orders/{orderId}/payment`, `GET /internal/v1/jwks.json` and
`GET /internal/v1/events`, and the warehouse token only on the warehouse
endpoints (plus the shared order, JWKS and event feed reads).

### payment-service to backend

- `GET /internal/v1/orders/{id}`: the existing `InternalOrderDto`, which gains
  `amountDue`.
- `POST /internal/v1/orders/{orderId}/payment`: the payment result, sent from a
  retrying outbox (backoff 30 s doubling to 30 min, at most 10 attempts,
  retried on 5xx and I/O errors).

```text
headers  X-Service-Token: <PAYMENT_SERVICE_TOKEN>
         X-Payment-Signature: t=<epochSeconds>,v1=<hex HMAC-SHA256(PAYMENT_WEBHOOK_SECRET, t + "." + rawBody)>
body     { requestId (UUID), paymentId (UUID), status: CAPTURED|FAILED,
           amount, currency, failureCode }
response 200 { orderId, orderStatus }
```

The backend rejects a bad signature or more than five minutes of clock skew
with 401 and treats `requestId` as an idempotency key (a replay returns the
same 200).

- `CAPTURED`: the amount must equal `amountDue` (422 otherwise). A `PENDING`
  order becomes `PAID`, the backend publishes `order.paid` and emails
  `PAYMENT_RECEIVED`; an order already paid by the same payment is 200. A
  cancelled order, or one paid by another payment, is 409
  `{"message":"Order is not payable"}`, and payment-service then voids the
  payment (`CAPTURED` to `VOIDED`, `refundedAmount = amount`).
- `FAILED`: the order stays `PENDING`; the backend publishes `payment.failed`
  and emails `PAYMENT_FAILED`.

payment-service also reads:

- `GET /internal/v1/jwks.json`: access-token verification keys;
- `GET /internal/v1/events?after={cursor}&limit=100&types=card-refund.requested`:
  the backend's domain event feed (see [EVENT_FEED.md](EVENT_FEED.md)).

### Card refunds from the event feed

The backend publishes `card-refund.requested` with data
`{requestId, orderId, amount, reason}` in the same transaction that books a
refund with a card leg (card first, up to the captured amount minus card
refunds already requested; the remainder goes back to the gift card, then to
loyalty points) or cancels an order with a captured card payment
(`requestId = UUID.nameUUIDFromBytes("cancel:" + orderId)`, reason
`Order cancelled`).

payment-service's `EventFeedPoller` reads the feed every
`PAYMENT_EVENTS_POLL_INTERVAL` (default `PT5S`) from its cursor
(`event_cursors`, consumer `payment-service`), up to 20 pages of 100 per poll.
Each event is handled in one local transaction that books the refund, records
the event id in `processed_events` and advances the cursor:

| Situation | Result |
| --- | --- |
| Event id already processed | Skipped |
| `requestId` already refunded (another event) | Nothing booked (idempotent per `requestId`) |
| No captured card payment for the order | Nothing booked, logged |
| Amount above what is still refundable | Nothing booked, logged as a warning |
| Malformed payload or another non-transient failure | Logged with the event id, recorded as processed, cursor advances |
| Backend unavailable or transient database error | Poll stops without moving the cursor; the next poll retries |

A refund leaves the payment `PARTIALLY_REFUNDED` or `REFUNDED`. The backend
does not learn the outcome; testers read it from
`GET /api/v1/orders/{orderId}/payments`. A refund appears there about 5–8
seconds after the cancellation or refund booking (3 s settle delay plus up to
one poll interval).

**Removed in 1.1.0:** the inbound `POST /internal/v1/payments/refunds`
endpoint and its service-token filter; payment-service has no internal API.
The backend's `PAYMENT_BASE_URL` and its refund outbox were removed in 3.16.0.

## Gateway

Every application gateway server block (lightweight/full, the stable and the
aitesters host on the server) routes these locations to payment-service through
a request-time `$payment_upstream` variable, so the gateway starts and the
backend keeps serving when payment-service is absent (payment paths are then
502):

| Location | Example |
| --- | --- |
| `= /api/v1/payments` | `POST /api/v1/payments` |
| `/api/v1/payments/` | `POST /api/v1/payments/{id}/3ds` |
| `= /api/v1/admin/payments` | `GET /api/v1/admin/payments?status=FAILED` |
| `~ ^/api/v1/orders/\d+/payments$` | `GET /api/v1/orders/42/payments` |
| `^~ /payment/v3/api-docs` | rewritten to payment-service `/v3/api-docs` |

The backend's Swagger UI lists `/payment/v3/api-docs` as "Payment service".

## Deployment in this repository

- **Compose.** `payment-service` in `lightweight-docker-compose.yml` and
  `docker-compose.yml`; `payment-service` and `aitesters-payment-service` in
  `docker-compose.server.yml`, both `-Xmx64m` in 160 MiB with the bash
  `/dev/tcp` healthcheck on `/actuator/health`. They start after a healthy
  backend and after the one-shot `postgres-roles` (`aitesters-postgres-roles`).
- **Database role.** `postgres/service-roles.sh` runs
  `postgres/service-role.sh` for `warehouse` and `payment`: each role owns only
  its schema, cannot create objects in `public`, cannot read the backend's
  tables and has no access to the other service's schema.
- **Backend settings.** Both backends get `PAYMENT_SERVICE_TOKEN` and
  `PAYMENT_WEBHOOK_SECRET`. They no longer get `PAYMENT_BASE_URL` (removed in
  backend 3.16.0); `scripts/verify-release-images.py` fails if a Compose file
  sets it again. Each payment-service reaches its own backend through
  `BACKEND_BASE_URL` (`http://backend:4001`, `http://aitesters-backend:4001`).
- **Secrets.** Ansible renders `.env.payment` and `.env.aitesters-payment`
  (token, webhook secret, role password) from Vault; see
  [ANSIBLE.md](ANSIBLE.md#payment-service-secrets-and-image-gate).
- **Image pin.** Until the first release is published the server profile
  carries `slawekradzyminski/payment-service:1.0.0@sha256:PENDING_PAYMENT_SERVICE_DIGEST`
  and the local profiles use the bare `1.0.0` tag. `scripts/verify-release-images.py`,
  `scripts/verify-image-pins.py` and the Ansible image gate fail until the
  digest is filled in (see [CONTAINER_RELEASES.md](CONTAINER_RELEASES.md)).
