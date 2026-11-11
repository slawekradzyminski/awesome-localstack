# Webhooks

Two kinds of signed HTTP callbacks exist in the commerce stack. Neither needs
any extra container or published port in this repository.

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

## User webhooks (backend 3.15.0)

Signed-in users subscribe their own URLs to commerce events (`order.created`,
`order.paid`, `order.cancelled`, `shipment.shipped`, `shipment.delivered`,
`refund.booked`, `payment.failed`, plus `webhook.ping` from the test call).
Deliveries carry `X-Webhook-Signature: t=<epochSeconds>,v1=<hex HMAC-SHA256>`
with a per-subscription secret, are retried with doubling backoff, and are
listed per subscription.

For training without a public receiver, the backend offers a built-in inbox:
create an inbox, subscribe with its `inbox://<token>` URL, trigger an event (or
`POST /api/v1/webhooks/{id}/test`) and read the stored, signed request back
through the API. The endpoints are in the backend's Swagger UI under
`/api/v1/webhooks`. Only ports 80 and 443 on public addresses are accepted:
hosts without a dot (such as Compose service names), `localhost`, `*.local`,
`*.internal` and private or loopback addresses are refused, checked again on
every delivery, so a subscription cannot reach containers on the Compose
network.
