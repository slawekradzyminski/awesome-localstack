# Event feed

From backend 3.16.0 the backend never calls warehouse-service or
payment-service. Both services learn about commerce events by polling a
durable **pull feed** on the backend's internal API. Dependencies point one
way only: warehouse-service → backend and payment-service → backend. The
decision is recorded in
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md#adr-1-internal-integration-via-a-pull-event-feed).

| Release | Role |
| --- | --- |
| backend 3.16.0 | Records every domain event in `domain_events` (Flyway V16) and serves the feed |
| payment-service 1.1.0 | Consumes `card-refund.requested` (Flyway V3: cursor and processed events) |
| warehouse-service 1.3.0 | Consumes `order.cancelled` (Flyway V4: cursor and processed events) |

## Producer: the backend

Every `CommerceEvent` is appended to `domain_events` by a synchronous listener,
in the **same transaction** as the state change that published it. An event
therefore exists exactly when its change committed: no dual write, no separate
outbox delivery job.

```text
domain_events (sequence BIGSERIAL PK, event_id UUID UNIQUE, type, order_id,
               username, occurred_at, recorded_at, payload)
```

### Request

`GET /internal/v1/events?after={sequence}&limit={n}&types={wire names}` with
`X-Service-Token` set to the warehouse **or** the payment service token. Like
every internal endpoint it is not routed by the gateway (`/internal/` is 404 on
every host) and is absent from the public OpenAPI document.

| Parameter | Rule |
| --- | --- |
| `after` | Sequence to continue after; default `0`; a non-negative integer, else 400 |
| `limit` | 1–200, default 100, else 400 |
| `types` | Optional comma-separated wire names (`order.cancelled`, `card-refund.requested`, ...); an unknown name is 400 |

### Response

```text
200 { events: [ { sequence, id, type, occurredAt, orderId, username, data } ],
      nextCursor, hasMore }
```

- Events are ordered by `sequence` ascending; every event carries all seven
  fields (nulls included). `occurredAt` is ISO-8601 UTC with millisecond
  precision. `data` is stored once with sorted keys and plain decimals, so a
  redelivered event has identical bytes.
- `nextCursor` is the last returned sequence (or `after` for an empty page);
  the consumer passes it as the next `after`. It also moves past events the
  `types` filter excluded.
- `hasMore` is true when more matching settled events exist.
- 400 `{"message": ...}` for bad parameters, 401 for a missing or wrong service
  token, 404 when neither service token is configured.

### Settle delay

Only events recorded at least `events.settle-delay` ago (default `PT3S`) are
served. Sequences are allocated when a row is inserted, not when its
transaction commits: transaction A can take sequence 10, transaction B
sequence 11, and B can commit first. A consumer that read 11 and stored it as
its cursor would never see 10. Holding back the last three seconds gives slower
transactions time to commit before their neighbours become visible. The price
is latency: an event reaches a consumer three seconds plus up to one poll
interval (5 s) after it was recorded, so typically 5–8 seconds.

### Retention

A scheduled job deletes events recorded more than `events.retention` ago
(default `P30D`, checked every `PT1H`). A consumer that is down for longer than
the retention period misses events; warehouse-service's reconciler is the safety
net for cancellations, and card refunds keep their own record in the backend's
`card_refund_requests`.

| Property | Environment variable | Default |
| --- | --- | --- |
| `events.settle-delay` | `EVENTS_SETTLE_DELAY` | `PT3S` |
| `events.retention` | `EVENTS_RETENTION` | `P30D` |
| `events.retention-job.enabled` | `EVENTS_RETENTION_JOB_ENABLED` | `true` |
| `events.retention-job.interval` | `EVENTS_RETENTION_JOB_INTERVAL` | `PT1H` |

The Compose files keep the defaults and set none of these variables.

## Event types consumed today

| Wire name | Consumer | Handling |
| --- | --- | --- |
| `card-refund.requested` | payment-service | Refunds the captured card payment; idempotent per `requestId`; no captured payment or an amount above what is refundable books nothing and is logged |
| `order.cancelled` | warehouse-service | Cancels the order's shipment when it is `AWAITING_PICK` or `PICKED` (`lastActor = "system"`); later states are logged and left alone |

Every other `CommerceEvent` type (`order.created`, `order.paid`,
`shipment.shipped`, `shipment.delivered`, `refund.booked`, `payment.failed`)
is recorded too and can be read by a new consumer without a backend change.

### `card-refund.requested` is internal

The backend publishes `card-refund.requested` with data
`{requestId, orderId, amount, reason}` when a booked refund has a card leg
(the card-first refund split) and when an order with a captured card payment
is cancelled (`requestId = UUID.nameUUIDFromBytes("cancel:" + orderId)`,
reason `Order cancelled`). It replaces the 3.15.0 HTTP refund outbox to
payment-service. The type is **not** listed by
`GET /api/v1/webhooks/event-types` and never reaches user webhooks; customers
see the refund as `refund.booked`.

## Consumer pattern

warehouse-service and payment-service implement the same pattern
independently (see
[ADR 3](ARCHITECTURE_DECISIONS.md#adr-3-outbox-and-feed-consumer-implementations-stay-per-service)):

```text
event_cursors    (consumer PK, last_sequence, updated_at)
processed_events (event_id PK, processed_at)
```

1. `EventFeedPoller` runs every `<service>.events.poll-interval` (default
   `PT5S`) when `<service>.events.enabled` is true, and asks for its own types
   only, starting after its stored cursor. It follows `hasMore` for a bounded
   number of pages per run (warehouse 10, payment 20).
2. Each event is handled in **one local transaction** that locks the
   consumer's cursor row, skips the event if its `id` is already in
   `processed_events`, applies the change, records the id and advances the
   cursor. Handling is idempotent and several instances never process one
   event concurrently.
3. Backend unavailable, or a transient database error: the run ends without
   moving the cursor and the next run retries.
4. A non-transient handler failure (malformed payload, missing `orderId`) is
   logged with the event id and recorded as processed, so one bad event never
   blocks the feed.

| Service | Variables | Defaults |
| --- | --- | --- |
| payment-service | `PAYMENT_EVENTS_ENABLED`, `PAYMENT_EVENTS_POLL_INTERVAL` | `true`, `PT5S` |
| warehouse-service | `WAREHOUSE_EVENTS_ENABLED`, `WAREHOUSE_EVENTS_POLL_INTERVAL` | `true`, `PT5S` |

Against a backend older than 3.16.0 the feed request answers 404, which the
consumers log on every run.

## Testing the feed

The feed is internal, so test it through its effects:

- pay an order with `4242 4242 4242 4242`, cancel it, and within about ten
  seconds `GET /api/v1/orders/{id}/payments` shows the payment `REFUNDED`;
- release an order to the warehouse (`AWAITING_PICK`), cancel it as the
  customer, and within about ten seconds the shipment is `CANCELLED` with
  `lastActor = "system"`;
- refund a return of a card-paid order and watch the payment become
  `PARTIALLY_REFUNDED` or `REFUNDED`.

To read the raw feed in the lightweight profile (the backend image has no
shell tools, so the request goes from the gateway container):

```bash
docker compose -f lightweight-docker-compose.yml exec gateway \
  curl -s -H "X-Service-Token: local-payment-service-token-change-me" \
  "http://backend:4001/internal/v1/events?limit=5&types=card-refund.requested"
```
