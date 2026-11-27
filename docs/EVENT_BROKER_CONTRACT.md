# Event broker transport

The commerce events of the [event feed](EVENT_FEED.md) can also travel through
ActiveMQ Artemis. Both transports carry the same events with the same JSON, and
each service chooses one at run time with `EVENTS_TRANSPORT`:

| Value | Producer (backend) | Consumers (warehouse, payment, notification) |
| --- | --- | --- |
| `feed` (default) | Records events in `domain_events`, serves `GET /internal/v1/events` | Poll the feed every 5 s from their cursor |
| `broker` | Same, plus an outbox relay that publishes every new event to Artemis | Listen on their own durable queue; the feed poller is off |

The feed endpoint stays on in both modes: it is the replay and fallback path,
and the course stack and older consumers keep using it.

The decision and its trade-offs are recorded in
[ADR 7](ARCHITECTURE_DECISIONS.md#adr-7-a-broker-transport-next-to-the-event-feed).

## Which profile uses which transport

| Stack | Transport | Address |
| --- | --- | --- |
| `docker-compose.yml` (full) | `broker` | `awesome.commerce.events` |
| `lightweight-docker-compose.yml` | `feed` | – |
| lightweight + `docker-compose.broker.yml` | `broker` | `awesome.commerce.events` |
| `docker-compose.server.yml`, awesome site | `broker` | `awesome.commerce.events` |
| `docker-compose.server.yml`, aitesters site | `broker` | `aitesters.commerce.events` |
| `docker-compose.compatibility.yml` (course check) | `feed` | – |

All services of one stack must use the same transport. A consumer left on
`feed` next to a relaying backend still works (the feed is always served), but
its broker queue then keeps every event (see [No expiry](#no-expiry)); purge
it from the console or switch the service to `broker`.

## Broker topology

The addresses and queues are declared in
[`artemis/commerce-events.properties`](../artemis/commerce-events.properties),
loaded with `artemis run --properties`. Declaring them up front matters: a
message sent to a multicast address with no queue is dropped, so the queues
must exist before the backend publishes the first event, whatever order the
containers start in.

```text
awesome.commerce.events                     (address, MULTICAST)
├── awesome.commerce.events.warehouse-service      filter: order.cancelled, stock.restore-requested
├── awesome.commerce.events.payment-service        filter: card-refund.requested
└── awesome.commerce.events.notification-service   filter: every other type

commerce.events.DLA                         (dead-letter address, MULTICAST)
├── DLQ.awesome.commerce.events.warehouse-service     filter: _AMQ_ORIG_QUEUE = the service's queue
├── DLQ.awesome.commerce.events.payment-service
└── DLQ.awesome.commerce.events.notification-service
```

The dead-letter queues are declared too, one per consumer queue and filtered on
`_AMQ_ORIG_QUEUE` (the queue the message failed on), so each service has its own
dead letters, they show up in the console with a count of zero from the start,
and a redrive returns each message to the queue it came from. Artemis's own
`autoCreateDeadLetterResources` would create one queue per *address*, mixing
all three services.

The aitesters site has the same tree under `aitesters.commerce.events`. A
consumer reads its queue by its fully qualified name,
`<address>::<address>.<service>`.

### Address settings (`*.commerce.events`)

| Setting | Value | Effect |
| --- | --- | --- |
| `maxDeliveryAttempts` | 5 | After the fifth failed delivery the message moves to the dead-letter address |
| `redeliveryDelay` | 1 s | First redelivery after a rollback |
| `redeliveryMultiplier` | 2 | 1 s, 2 s, 4 s, 8 s |
| `maxRedeliveryDelay` | 30 s | Upper bound of the backoff |
| `deadLetterAddress` | `commerce.events.DLA` | Shared dead-letter address with one queue per consumer |

### No expiry

Events never expire on the broker: a queue with no listener keeps them until
its service comes back, and dead letters stay until someone redrives or deletes
them. Event messages are about 1 KB, so even the production broker's 256 MB
`global-max-size` holds hundreds of thousands before Artemis starts paging to
disk. The feed (30 days of retention) remains the recovery path for anything
older.

## Message format

One JMS `TextMessage` per event, sent to the multicast address (a JMS topic).

**Body:** exactly one element of the feed's `events` array, the same ten fields
in the same order with the same bytes:

```json
{"sequence":42,"id":"7c9e...","type":"order.cancelled","occurredAt":"2026-11-15T10:00:00.000Z",
 "orderId":17,"username":"client","data":{"orderId":17,"reason":"CUSTOMER"},
 "requestId":"...","traceId":"...","spanId":"..."}
```

**Properties:**

| Property | Value | Purpose |
| --- | --- | --- |
| `type` | wire name, e.g. `order.cancelled` | Queue filters and selectors |
| `eventId` | event id (UUID string) | Search in the console |
| `sequence` | feed sequence (long) | Compare with the feed |
| `orderId` | order id (long), absent when the event has none | Search in the console |
| `JMSXGroupID` | `order-<orderId>`, or `event-<id>` without an order | Message groups: one consumer handles one order's events in order |
| `_AMQ_DUPL_ID` | event id | Broker duplicate detection (on by default, see below) |
| `JMSCorrelationID` | `requestId` of the writing request, if any | Correlation in logs |
| `traceparent` | W3C trace context of the relay's `publish <type>` span | The consumer's `process <type>` span becomes its child |

A consumer that receives a message without a valid `traceparent` falls back to
the body's `traceId`/`spanId`, exactly as with the feed.

## Producer: the outbox relay

`domain_events` already is a transactional outbox: the row is written in the
transaction that changed the order. Backend 3.23.0 adds `published_at`
(migration V27) and a relay:

1. Every `EVENTS_RELAY_INTERVAL` (1 s) it reads up to 100 rows with
   `published_at IS NULL`, ordered by `sequence`, in a short read-only
   transaction.
2. It sends them in **one transacted JMS session** with no database connection
   held (the pool has three connections).
3. It sets `published_at` on the sent rows in a second short transaction.

Delivery is **at least once**. A crash between steps 2 and 3 sends the batch
again on the next run. Because the batch is one JMS transaction, Artemis'
duplicate detection (`_AMQ_DUPL_ID`) does not drop single copies: one id the
address's duplicate-ID cache already holds makes the broker reject the whole
commit (broker warning `AMQ222059: Duplicate message detected`, client error
`DUPLICATE_ID_REJECTED`). Since backend 3.25.2 the relay then sends that batch
again **one event per transaction**: an event the broker rejects on its own as
a duplicate already reached the broker, so the relay marks it published
without a copy, logs a warning ("The broker already holds event #…") and
counts it in `events_relay_duplicates_total`; the rest of the batch is
delivered in sequence order. Any other broker or database failure keeps the
backoff described below. Before 3.25.2 the relay retried the same batch until
the id left the cache, and no event reached the consumers meanwhile. With
duplicate detection switched off (`EVENTS_BROKER_DUPLICATE_DETECTION=false`, a
lab setting) the consumers get the duplicate and their `processed_events`
table ignores it.

The aitesters sandbox repeats ids every day: its nightly reset starts
`aitesters-postgres` from a fresh volume, order ids start again from the seed
data, and the name-based ids of `notification.requested` events repeat the
previous day's. Without help the relay would drop those as duplicates, so the
reset runs `aitesters-broker-dedupe-reset` (Ansible role `app`) after
recreating the services, which calls `clearDuplicateIdCache()` on
`aitesters.commerce.events` through the broker's management API. Consumers
still deduplicate by event id, so this is safe.

Rows older than `EVENTS_RELAY_MAX_AGE` (24 h) are marked published without
being sent, with a warning. This bounds what a relay switched on late (or a
broker that was down for a day) replays.

When the broker is unreachable, the relay logs one warning per outage and
retries with a backoff of 1 s doubling to 30 s. The backlog is visible as the
`events_relay_pending` gauge; checkout and every other request keep working.

Metrics: `events_relay_pending` (gauge), `events_relay_published_total`,
`events_relay_failures_total`, `events_relay_skipped_total` (rows older than
the maximum age), `events_relay_duplicates_total` (rows the broker already
held, marked published without a copy).

### Migration V27

V27 adds the column and marks every event recorded **more than one hour before
the migration** as published. The last hour is relayed once when the backend
first runs in `broker` mode, so a consumer switched from the feed at the same
deployment cannot miss an event it had not polled yet. Consumers already
handled most of that hour through the feed and skip it by event id.

## Consumers

Each consumer runs one Spring `DefaultMessageListenerContainer` on its queue.
It always exists (the native image fixes the bean graph at build time) and
starts only when `EVENTS_TRANSPORT=broker`. warehouse-service starts it only
after its stock ledger is initialised.

| Setting | Default |
| --- | --- |
| `EVENTS_TRANSPORT` | `feed` |
| `EVENTS_BROKER_ADDRESS` | `awesome.commerce.events` |
| `EVENTS_BROKER_CONCURRENCY` | `1` (consumers per service) |
| `SPRING_ARTEMIS_BROKER_URL` | `tcp://activemq:61616` |
| `SPRING_ARTEMIS_USER` / `_PASSWORD` | `admin` / `admin` locally, Vault in production |

Each message is handled in one **transacted JMS session** and one database
transaction:

1. Parse the body as a feed event. A body that does not parse fails the
   delivery.
2. Open the `process <type>` CONSUMER span (child of `traceparent`).
3. Skip the event if its id is in `processed_events` (a duplicate).
4. Run the same handler the feed poller runs, then record the id in
   `processed_events`.
5. Commit the database transaction, then acknowledge the message.

**Any exception rolls the session back.** The broker redelivers the message
after the redelivery delay, and after five attempts moves it to
`DLQ.<queue>`. This is the difference that matters for testers: the feed
poller logs a failing event and skips it, so the event is gone; the broker
keeps it in the dead-letter queue, where it can be inspected and sent back
(`scripts/broker redrive <service>`).

A crash after the database commit and before the acknowledgement delivers the
message again; step 3 makes that harmless.

**Netty allocator.** Every service sets `io.netty.allocator.type=pooled` at
start-up unless the property is given. Spring Boot 4.1 brings Netty 4.2, whose
default adaptive allocator made the Artemis client (built for Netty 4.1) lose
listener sessions in the native images right after start-up (`Session is
closed`, `IllegalReferenceCountException` in `ActiveMQFrameDecoder2`); each lost
session rolled the delivery back, so an event could end in the dead-letter queue
without ever failing in its handler. `scripts/verify-event-broker.sh` checks that
no consumer logs `Session is closed`.

In `broker` mode the consumers do not move their feed cursor. Switching a
consumer back to `feed` re-reads the feed from where it stopped, and
`processed_events` skips what the broker already delivered.

## Failure modes

| Failure | `feed` transport | `broker` transport |
| --- | --- | --- |
| Consumer down | Nothing queues; the consumer catches up from its cursor | Messages wait in its queue (console: message count) |
| Backend down | Consumers cannot poll; nothing is lost | Nothing new is published; queued messages are still delivered |
| Broker down | – | Backend keeps recording; `events_relay_pending` grows and drains after recovery. Consumers reconnect every 5 s |
| Handler fails every time (poison event) | Logged and skipped | Redelivered 5 times, then in `DLQ.<queue>` |
| Duplicate delivery | `processed_events` | Broker duplicate detection, then `processed_events` |
| A batch repeats an id the broker has seen (relay crash, aitesters reset) | – | The broker rejects the batch; the relay resends it one event at a time and marks the duplicate published with a warning (3.25.2). The aitesters reset clears the cache so its repeated ids are delivered |
| Two events of one order | Handled in sequence order | Same order through the message group, while no message is being redelivered |

The [fault-injection lab](FAULT_INJECTION_LAB.md#broker-transport) has an
exercise for each row.

## Security

Production Artemis requires a login (`ANONYMOUS_LOGIN=false`). Every service
that talks to it gets `SPRING_ARTEMIS_USER` and `SPRING_ARTEMIS_PASSWORD` from
its runtime env file (`artemis_username`/`artemis_password` in Vault, the same
account the backend and notification-service already use for the `email`
queue). The broker publishes no port on the server; the console stays behind
its own realm and is not routed by the gateway.

## Testing it

- `scripts/broker stat` shows every commerce queue with its message,
  consumer and dead-letter counts.
- `scripts/broker poison <service>` puts an unparsable message on a service's
  queue; `scripts/broker dlq`, `scripts/broker redrive <service>` and
  `scripts/broker purge-dlq <service>` follow it. They call the queue's
  `browse()`, `retryMessages()` and `removeAllMessages()` management operations
  through Jolokia on the console port (local stacks publish it): Artemis's
  `transfer` and `browser` commands treat a fully qualified queue name as an
  anycast JMS queue and refuse these multicast queues.
- `scripts/verify-event-broker.sh` starts an isolated lightweight stack with the
  broker overlay and checks delivery, dead-lettering, redrive, the backlog
  during a consumer outage, the relay backlog during a broker outage and
  duplicate handling.
