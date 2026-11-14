# Webhooks

Two kinds of signed HTTP callbacks exist in the commerce stack. Payment
results travel between payment-service and the backend; user webhooks are sent
by notification-service. Neither needs a published port.

## Payment result notifications (service to service)

payment-service reports every payment result to the backend with
`POST /internal/v1/orders/{orderId}/payment`, signed with the shared
`PAYMENT_WEBHOOK_SECRET`:

```text
X-Service-Token:     <PAYMENT_SERVICE_TOKEN>
X-Payment-Signature: t=<epochSeconds>,v1=<hex HMAC-SHA256(PAYMENT_WEBHOOK_SECRET, t + "." + rawBody)>
```

The backend rejects a wrong signature or more than five minutes of clock skew
(401), and a repeated `requestId` returns the first answer again. The call runs
on the Compose network only; `/internal/` is 404 at every gateway. Payload,
retry schedule and outcomes are in
[PAYMENT_SERVICE_CONTRACT.md](PAYMENT_SERVICE_CONTRACT.md#internal-api).

Deployment: both backends and both payment-services receive their site's
`PAYMENT_WEBHOOK_SECRET` (`payment_webhook_secret` and
`aitesters_payment_webhook_secret` in Ansible Vault, each at least 32
characters and distinct from every service token). The lightweight and full
profiles use a fixed local default.

## User webhooks (notification-service 1.0.0; backend 3.15.0 to 3.20.x)

User webhooks moved from the backend to **notification-service** with backend
3.21.0 and notification-service 1.0.0
([ADR 5](ARCHITECTURE_DECISIONS.md#adr-5-notifications-move-out-of-the-backend)).
The public API did not change: the same paths, JSON shapes, status codes,
limits, signature header, SSRF rules and retry policy. What changed:

- Every gateway host sends `/api/v1/webhooks`, `/api/v1/webhook-inboxes` and
  `GET /api/v1/admin/webhooks` to notification-service (port 4005), whose
  OpenAPI is `/notification/v3/api-docs`.
- Deliveries are built from the backend's [event feed](EVENT_FEED.md), so a
  delivery leaves 5–8 seconds after the change instead of right after the
  commit; the body is byte-compatible with what the backend sent.
- Every profile that runs notification-service starts the backend with
  `WEBHOOKS_ENABLED=false`: the backend records no deliveries and runs no
  dispatcher or retry job. The l20 compatibility stack is backend-only and
  keeps the backend's own webhooks.
- On its first start notification-service imports the backend's subscriptions
  (ids and secrets kept) and inboxes through `GET /internal/v1/webhooks/export`;
  delivery history and inbox requests stay behind in the backend's tables.
- A new type, `order.reservation-expired` (`{orderId, expiredAt, totalAmount}`),
  fires when a `PENDING` order's stock hold expires, next to `order.cancelled`
  with `reason = "RESERVATION_EXPIRED"`.
- Signing secrets are stored encrypted with notification-service's own key
  (`WEBHOOKS_SECRET_ENCRYPTION_PASSWORD`/`_SALT`, from Vault on the server); the
  backend used its MFA key.

Runtime, endpoints and deployment are in
[NOTIFICATION_SERVICE_CONTRACT.md](NOTIFICATION_SERVICE_CONTRACT.md).

Signed-in users subscribe their own URLs to commerce events (`order.created`,
`order.paid`, `order.cancelled`, `order.reservation-expired`,
`shipment.shipped`, `shipment.delivered`, `refund.booked`, `payment.failed`,
plus `webhook.ping` from the test call).
The internal `card-refund.requested` (backend 3.16.0) and
`notification.requested` (backend 3.21.0) events are read only by
payment-service and notification-service from the [event feed](EVENT_FEED.md)
and are never offered to user webhooks.
Deliveries carry `X-Webhook-Signature: t=<epochSeconds>,v1=<hex HMAC-SHA256>`
with a per-subscription secret, are retried with doubling backoff, and are
listed per subscription.

For training without a public receiver, notification-service offers a built-in inbox:
create an inbox, subscribe with its `inbox://<token>` URL, trigger an event (or
`POST /api/v1/webhooks/{id}/test`) and read the stored, signed request back
through the API. The endpoints are in the Swagger UI under "Notification
service" (`/notification/v3/api-docs`). Only ports 80 and 443 on public addresses are accepted:
hosts without a dot (such as Compose service names), `localhost`, `*.local`,
`*.internal` and private or loopback addresses are refused, checked again on
every delivery, so a subscription cannot reach containers on the Compose
network.
