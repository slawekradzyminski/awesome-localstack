# Distributed lab contracts

Cross-repository contracts for the November 2026 distributed-systems lab:
stock reservations with a time limit, the notification-service, multiple
warehouses, the fault-injection lab and distributed tracing. Every repository
implements its side of this file; a change to a contract is made here first.

| Release | Adds |
| --- | --- |
| backend 3.21.0 | Reservation expiry, `notification.requested` feed events, `NOTIFICATION` service caller, webhook export, `webhooks.enabled` flag, OpenTelemetry tracing (off by default), `spanId` on feed events |
| warehouse-service 1.5.0 | Warehouse locations and split shipments, tracing, outbox gauge |
| payment-service 1.3.0 | Reservation guard, tracing, outbox gauge |
| notification-service 1.0.0 | New service: webhooks and commerce emails as an event-feed consumer |
| frontend 3.15.0 | Reservation countdown, parcels, notification-service API snapshot |

## 1. Stock reservations with a time limit (backend)

Stock is still deducted from `products.stock_quantity` when the order is
created (`ORDER_DEDUCTED`); that deduction is the hold. What is new is that the
hold expires.

| Item | Contract |
| --- | --- |
| Column | `orders.reservation_expires_at TIMESTAMPTZ NULL` (Flyway **V23**). Set to `created_at + orders.reservation.ttl` for every new order; existing rows stay null and never expire |
| Property | `orders.reservation.ttl` / `ORDERS_RESERVATION_TTL`, default `PT30M`. `orders.reservation.enabled` / `ORDERS_RESERVATION_ENABLED`, default `true`; when false new orders get null |
| Job | `ReservationExpiryJob`, `orders.reservation.expiry-job.interval` (default `PT15S`), batch of 50, `FOR UPDATE SKIP LOCKED`; cancels each `PENDING` order whose `reservation_expires_at <= now()` through the normal cancellation path (coupon released, stock `ORDER_RESTORED`, gift-card and points tenders returned as on a customer cancel) with `lastActor`/actor `system` |
| Events | `order.cancelled` with `data.reason = "RESERVATION_EXPIRED"` (customer and admin cancels carry `"CUSTOMER"` / `"ADMIN"`; other existing paths keep their data and add a reason where one exists), **plus** the new webhook-eligible type `order.reservation-expired` with data `{orderId, expiredAt, totalAmount}`, both in the same transaction |
| Order JSON | New field `reservationExpiresAt` (ISO-8601 UTC, millisecond precision) on every order representation (create response, `GET /orders/{id}`, order lists, admin reads, internal order snapshot, GraphQL `Order.reservationExpiresAt`). It is the stored value and identical in every read; it is **omitted when null** (legacy rows and orders created with reservations disabled). Order items are unchanged |
| Time control | `POST /api/v1/admin/orders/{id}/expire-reservation` (`ROLE_ADMIN`): sets `reservation_expires_at = now()` and runs the expiry for that order at once. 200 with the order; 404 unknown; 409 when the order is not `PENDING` |
| Race | A capture that reaches `POST /internal/v1/orders/{id}/payment` after the order expired answers 409 (existing behaviour) and payment-service voids the payment (existing behaviour). The row lock on the order decides; there is no grace period |
| Not changed | Inventory REST bodies, movement bodies, `OrderStatus`, GraphQL enums, `totalAmount` |

payment-service: `POST /api/v1/payments` answers **409** `{"message":"Order reservation expired"}`
when the order snapshot's `reservationExpiresAt` is in the past (in addition to
the existing "not PENDING" 409). The snapshot field is optional for older backends.

Frontend: PENDING orders show "Reserved until HH:MM" and a live countdown on the
order details and payment pages; at zero the page refetches and shows the
cancelled order with "Reservation expired". `data-testid`s:
`reservation-countdown`, `reservation-expired`.

## 2. notification-service

| Item | Value |
| --- | --- |
| Repository | `slawekradzyminski/notification-service` (public, bootstrapped from payment-service) |
| Image | `slawekradzyminski/notification-service`, GraalVM native, `-Xmx64m` in a 160 MiB container |
| Port | **4005**, internal only, behind the gateway |
| Database | Schema `notification`, role `notification` (`currentSchema=notification`) |
| Profiles | `docker,demo` locally, `docker` on the server |
| Authentication | Backend RS256 tokens via `GET /internal/v1/jwks.json`, like warehouse and payment |
| Environment | `SPRING_DATASOURCE_*`, `BACKEND_BASE_URL`, `NOTIFICATION_SERVICE_TOKEN`, `NOTIFICATION_EMAIL_TRANSPORT` (`jms` or `local-outbox`, default `local-outbox`), `SPRING_ARTEMIS_*` when `jms`, `LOCAL_EMAIL_OUTBOX_ACCESS_KEY` (optional), `NOTIFICATION_EVENTS_ENABLED` (true), `NOTIFICATION_EVENTS_POLL_INTERVAL` (`PT5S`), all `WEBHOOKS_*` variables the backend accepts today |
| Metrics | `/actuator/prometheus`, job `spring_notification_micrometer`; gauge `notification.outbox.pending` (pending webhook deliveries + pending emails) |

### Backend side (3.21.0)

- New `ServiceCaller.NOTIFICATION` with token `internal.service-tokens.notification`
  / `NOTIFICATION_SERVICE_TOKEN`; blank disables it. Accepted on
  `GET /internal/v1/events`, `GET /internal/v1/jwks.json`,
  `GET /internal/v1/webhooks/export`.
- `GET /internal/v1/webhooks/export` (NOTIFICATION only):
  `200 {subscriptions:[{id, username, url, events[], secret, active, description, createdAt, updatedAt, consecutiveFailures}], inboxes:[{token, username, createdAt}]}`.
  Deliveries and inbox requests are not exported. 404 when webhooks were already removed.
- `webhooks.enabled` / `WEBHOOKS_ENABLED`, default `true`. When `false` the backend
  records no webhook deliveries and runs no webhook dispatcher or retry job; its
  webhook endpoints stay mapped (the gateway sends that traffic to the
  notification-service wherever it is deployed). The compatibility stack keeps the default.
- Commerce emails: where the backend sent a customer email because of a
  `CustomerNotificationRequestedEvent` (payment received/failed, back in stock,
  warehouse notifications from `POST /internal/v1/notifications`, loyalty points
  earned, gift card issued) it records an internal feed event instead when
  `notifications.delivery` / `NOTIFICATIONS_DELIVERY` is `feed`. Default `email`
  (the old behaviour) so the compatibility stack and older deployments keep working;
  every profile that runs the notification-service sets `feed`.
- Account emails (password reset requested/confirmed, `POST /api/v1/email`,
  `GET /api/v1/users/me/email-events`) always stay in the backend.

### Feed event `notification.requested` (internal, never offered to user webhooks)

```text
type: notification.requested
data: { requestId, template, recipientEmail, recipientName, properties{...} }
```

`template` is an `EmailTemplate` name other than the account ones
(`PAYMENT_RECEIVED`, `PAYMENT_FAILED`, `BACK_IN_STOCK`, `ORDER_SHIPPED`,
`ORDER_DELIVERED`, `RETURN_UPDATED`, `SHIPMENT_OUT_FOR_DELIVERY`,
`SHIPMENT_DELIVERY_FAILED`, `LOYALTY_POINTS_EARNED`, `GIFT_CARD_ISSUED`);
`properties` are the template properties the backend renderer validates today.
`requestId` is the idempotency key (the warehouse notification's `requestId`
where there is one, otherwise a UUID derived from the event id).

### Service side

- Consumes, with the standard feed consumer (ADR 3): every webhook-eligible type
  (`order.created`, `order.paid`, `order.cancelled`, `order.reservation-expired`,
  `shipment.shipped`, `shipment.delivered`, `refund.booked`, `payment.failed`)
  and `notification.requested`.
- Webhooks: the **same public API, paths, JSON shapes, status codes, limits,
  signature (`X-Webhook-Signature: t=..,v1=..`), SSRF rules and retry policy** as
  backend 3.20.1 (`/api/v1/webhooks/**`, `/api/v1/webhook-inboxes/**`,
  `GET /api/v1/admin/webhooks`). The delivery body is built from the feed event
  and is byte-compatible with what the backend sent.
- One-time import: on start, when `webhook_subscriptions` and `webhook_inboxes`
  are both empty, call the export endpoint; ids are kept. A 404 or an empty
  export is fine.
- Emails: render with the moved `CustomerEmailRenderer`, deliver with the
  configured transport (`jms`: JSON to queue `email`, the same message the backend
  sends today, consumed by `consumer` → Mailpit; `local-outbox`: in memory, read
  with `GET /api/v1/local/notifications/outbox` guarded like the backend's local
  outbox). Every email is recorded in `notification_emails` (status `QUEUED`,
  `SENT`, `FAILED`, attempts, backoff per the ADR 3 outbox convention).
- `GET /api/v1/notifications/emails?page&size`: the caller's commerce emails,
  newest first, recipient masked like the backend's email events. `ROLE_ADMIN`
  may pass `username`.
- Gateway (every host): `/api/v1/webhooks`, `/api/v1/webhooks/`,
  `/api/v1/webhook-inboxes`, `/api/v1/webhook-inboxes/`, `= /api/v1/admin/webhooks`,
  `/api/v1/notifications/`, `/api/v1/local/notifications/`,
  `/notification/v3/api-docs` → `notification-service:4005`.

## 3. Multiple warehouses and split shipments (warehouse-service)

| Item | Contract |
| --- | --- |
| Locations | `warehouse_locations(code PK, name, city, active, priority)` (Flyway **V6**), seeded `KRK` "Krakow Central" (priority 1) and `GDN` "Gdansk North" (priority 2) |
| Stocking | `location_products(location_code, category, role PRIMARY/BACKUP)`; a product is stocked by category. Demo seed: KRK primary for every category; GDN primary for half of the categories and backup for the rest, so a mixed cart splits |
| Allocation | On release each order line goes to the highest-priority **active** location that stocks its category, preferring one location for the whole order when one active location stocks every line. Lines with no active location → 409 `{"message":"No active warehouse location stocks <category>"}` and nothing is created |
| Shipments | One shipment (parcel) per allocated location: `shipments.location_code`, `unique(order_id, location_code)` replacing `unique(order_id)`; `shipment_lines(shipment_id, product_id, quantity)` |
| Mirror to backend | Aggregate fulfilment state = `max(last mirrored, aggregate)` where aggregate is `AWAITING_PICK` when every parcel awaits pick, otherwise `max(PICKED, min over non-cancelled parcels)`. Backend unchanged; it still sees one forward-only state, and the cancel/ship race still has one decider |
| Customer API | `GET /api/v1/orders/{id}/shipments` → list of shipments; `GET /api/v1/orders/{id}/shipment` keeps its shape for the first parcel and adds `locationCode`, `parcelCount` |
| Shipment JSON | Adds `locationCode`, `locationName`, `parcelIndex` (1-based), `parcelCount`, `lines[]` |
| Admin | `GET /api/v1/warehouse/locations`; `PUT /api/v1/warehouse/locations/{code}` `{active}`; `POST /api/v1/warehouse/shipments/{id}/reallocate` `{targetLocation?}` (only `AWAITING_PICK` parcels; moves the parcel's lines to the backup or given active location, merging into that location's parcel when one exists); `POST /api/v1/warehouse/shipments/{id}/short-pick` `{productId, missingQuantity}` (moves the missing quantity to a new or existing parcel at another active location, else 409); `GET /api/v1/warehouse/reconciliation` (orders whose parcels' aggregate disagrees with the backend's `fulfilmentState`) |
| `POST /api/v1/warehouse/shipments` | Still `{orderId}`, 201 with the first parcel, now carrying `parcelCount` |
| Gateway | Add `^/api/v1/orders/\d+/shipments$` to the warehouse regex |

Frontend: order details shows each parcel (location, lines, tracking) with
`data-testid` `parcel-<index>`; admin warehouse pages show the location, a
locations page with the active toggle, and reallocate / short-pick actions.

## 4. Tracing (all Spring services)

| Item | Contract |
| --- | --- |
| Libraries | Micrometer Tracing with the OpenTelemetry bridge and the OTLP HTTP exporter, compiled into the native image |
| Default | Off: no export and no sampling unless `TRACING_ENABLED=true` |
| Environment | `TRACING_ENABLED` (false), `TRACING_OTLP_ENDPOINT` (`http://jaeger:4318/v1/traces`), `TRACING_SAMPLING_PROBABILITY` (`1.0`, used only when enabled). Each service maps these to Spring Boot's own properties |
| Service names | `backend`, `warehouse-service`, `payment-service`, `notification-service` (`spring.application.name`) |
| Propagation | W3C `traceparent`. An incoming valid `traceparent` (the gateway always sends one) is the parent of the server span, so the trace id equals the one in logs and in `domain_events.trace_id`. `X-Request-Id` and MDC keys stay as today |
| Outgoing calls | With tracing on, the instrumented HTTP client propagates the current span; the hand-written child `traceparent` is only added when tracing is off |
| Feed | Backend Flyway **V24**: `domain_events.span_id`; feed events gain `spanId` (additive, after `traceId`). Consumers start a `CONSUMER` span `process <type>` whose parent is `traceId`/`spanId` of the event, so a cancellation and the refund it triggers are one trace |
| Outboxes | Dispatchers start a span parented by the stored `traceparent` |

(Backend Flyway numbering for this release: V23 reservations, V24 tracing span
id, V25 notification split if it needs a table.)

## 5. Fault-injection lab (awesome-localstack only)

`docker-compose.chaos.yml` overlay on top of the full or lightweight profile adds
Toxiproxy and points each service's links through it. One proxy per link, so a
scenario can break one service's view without touching the others:

| Proxy | Listens (inside the network) | Upstream |
| --- | --- | --- |
| `warehouse-to-backend` | `toxiproxy:14001` | `backend:4001` |
| `payment-to-backend` | `toxiproxy:24001` | `backend:4001` |
| `notification-to-backend` | `toxiproxy:34001` | `backend:4001` |
| `backend-to-postgres` | `toxiproxy:15432` | `postgres:5432` |
| `warehouse-to-postgres` | `toxiproxy:25432` | `postgres:5432` |
| `payment-to-postgres` | `toxiproxy:35432` | `postgres:5432` |
| `notification-to-postgres` | `toxiproxy:45432` | `postgres:5432` |

The services need no change: the overlay only overrides `BACKEND_BASE_URL` and
`SPRING_DATASOURCE_URL`.
