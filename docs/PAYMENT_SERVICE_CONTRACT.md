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
| Repository | `payment-service` (sibling repository; first release 1.0.0 pending publication) |
| Image | `slawekradzyminski/payment-service`, GraalVM native image, `-Xmx64m` in a 160 MiB container |
| Port | 4004 (internal only, behind the gateway) |
| Database | PostgreSQL schema `payment` of the backend database, owned by the `payment` role (`currentSchema=payment`); Flyway V1 baseline |
| Profiles | `docker,demo` in the lightweight and full profiles, `docker` on the server (like warehouse-service) |
| Authentication | Verifies the backend's RS256 access tokens with the backend JWKS (`/internal/v1/jwks.json`), exactly like warehouse-service; it holds no signing key |
| Environment | `SPRING_DATASOURCE_URL`/`_USERNAME`/`_PASSWORD` (role `payment`), `BACKEND_BASE_URL`, `PAYMENT_SERVICE_TOKEN`, `PAYMENT_WEBHOOK_SECRET` |
| Optional tuning | `PAYMENT_SETTLEMENT_DELAY` (default `PT10S`) for the delayed test cards |
| Metrics | `/actuator/prometheus`, scraped as `spring_payment_micrometer` |

Only the card brand and the last four digits are stored. Card numbers and CVCs
are never logged.

## Public API

All endpoints need a backend access token. Customers see only payments of
their own orders; `ROLE_ADMIN` sees all.

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
any other code fails it with `THREE_DS_FAILED`; 409 unless the payment is
`REQUIRES_ACTION`.

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

Neither direction is routed by the gateway (`/internal/` is 404 on every
host). Both directions carry `X-Service-Token: ${PAYMENT_SERVICE_TOKEN}`; the
backend accepts the payment token only on the payment endpoints, and the
warehouse token only on the warehouse endpoints.

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

### backend to payment-service

`POST /internal/v1/payments/refunds` with `{requestId (UUID), orderId, amount,
reason}` returns 200 `{refundId, paymentId, amount, status}`; 404 when the
order has no captured payment (the backend marks the refund done, nothing goes
back to a card) and 409 when the amount exceeds what is refundable. The backend
sends it from its own retrying outbox after a refund is booked. A refund goes
to the card first, up to the captured amount; the remainder goes back to the
gift card, then to loyalty points.

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
- **Backend settings.** Both backends get `PAYMENT_SERVICE_TOKEN`,
  `PAYMENT_WEBHOOK_SECRET` and `PAYMENT_BASE_URL`
  (`http://payment-service:4004`, `http://aitesters-payment-service:4004` for
  the sandbox).
- **Secrets.** Ansible renders `.env.payment` and `.env.aitesters-payment`
  (token, webhook secret, role password) from Vault; see
  [ANSIBLE.md](ANSIBLE.md#payment-service-secrets-and-image-gate).
- **Image pin.** Until the first release is published the server profile
  carries `slawekradzyminski/payment-service:1.0.0@sha256:PENDING_PAYMENT_SERVICE_DIGEST`
  and the local profiles use the bare `1.0.0` tag. `scripts/verify-release-images.py`,
  `scripts/verify-image-pins.py` and the Ansible image gate fail until the
  digest is filled in (see [CONTAINER_RELEASES.md](CONTAINER_RELEASES.md)).
