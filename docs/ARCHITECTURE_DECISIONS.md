# Architecture decisions

Decisions that shape how the backend, warehouse-service, payment-service and
notification-service work together. Each record states the context, the decision and what follows
from it. A superseded decision stays in this file with its status changed.

| ADR | Decision | Status | Since |
| --- | --- | --- | --- |
| [1](#adr-1-internal-integration-via-a-pull-event-feed) | Internal integration via a pull event feed | Accepted; reversed for stock by ADR 6 | backend 3.16.0, warehouse-service 1.3.0, payment-service 1.1.0 |
| [2](#adr-2-backend-keeps-a-fulfilment-read-model) | Backend keeps a fulfilment read model | Accepted | backend 3.11.0, warehouse-service 1.0.0 |
| [3](#adr-3-outbox-and-feed-consumer-implementations-stay-per-service) | Outbox and feed consumer implementations stay per service | Accepted | warehouse-service 1.0.0, payment-service 1.0.0 |
| [4](#adr-4-database-per-service-on-one-postgresql-server) | Database per service on one PostgreSQL server | Accepted | backend 3.12.0, warehouse-service 1.0.0 |
| [5](#adr-5-notifications-move-out-of-the-backend) | Notifications move out of the backend | Accepted | backend 3.21.0, notification-service 1.0.0 |
| [6](#adr-6-warehouse-service-owns-the-stock-ledger) | warehouse-service owns the stock ledger | Accepted | backend 3.22.0, warehouse-service 1.6.0 |
| [7](#adr-7-a-broker-transport-next-to-the-event-feed) | A broker transport next to the event feed | Accepted; amends ADR 1 | backend 3.23.0, warehouse-service 1.7.0, payment-service 1.4.0, notification-service 1.1.0 |

## ADR 1: Internal integration via a pull event feed

**Status:** accepted, November 2026 (backend 3.16.0, warehouse-service 1.3.0,
payment-service 1.1.0). Reversed for stock only by
[ADR 6](#adr-6-warehouse-service-owns-the-stock-ledger): the backend calls
warehouse-service for stock commands. Amended by
[ADR 7](#adr-7-a-broker-transport-next-to-the-event-feed): the same events can
also travel through Artemis; the feed stays and remains the default.

### Context

Up to backend 3.15.0 the backend was a synchronous hub. warehouse-service and
payment-service called its internal API, and the backend in turn called
payment-service: card refunds went from a backend outbox
(`payment_refund_outbox`) to `POST /internal/v1/payments/refunds`. That made a
**cycle** (backend → payment-service → backend): both services had to be up
and configured with each other's address (`PAYMENT_BASE_URL`), a
payment-service release could break the backend's refund delivery, and the
backend carried retry and error-mapping code for a service it does not own.
Customer cancellations reached warehouse-service only through a reconciler that
polled order snapshots every minute.

The backend already publishes a `CommerceEvent` for every order change. The
full profile runs ActiveMQ Artemis, but the lightweight student profile and the
`aitesters-backend` sandbox on the server run **without a broker**, and their
memory budget has no room for one.

### Decision

The backend records every domain event in a `domain_events` table in the same
transaction as the state change and serves it as an HTTP pull feed,
`GET /internal/v1/events?after&limit&types`, authenticated with the existing
service tokens. Consumers poll it, keep their own cursor and deduplicate by
event id. Card refunds become `card-refund.requested` events; the backend makes
no outbound call to either service. The contract is in
[EVENT_FEED.md](EVENT_FEED.md).

ActiveMQ was rejected because the profiles that need the integration most (the
lightweight classroom profile and the aitesters sandbox) have no broker, and a
broker would add a container, memory and a new failure mode to every profile.
The feed reuses what every profile already has: PostgreSQL and HTTP.

### Consequences

- Dependencies only point **to** the backend: warehouse-service → backend and
  payment-service → backend. The backend can start, run and be released without
  either service; `PAYMENT_BASE_URL` is gone from every Compose file and the
  release check now requires its absence.
- Delivery is at-least-once with idempotent consumers. Latency is the settle
  delay (3 s) plus up to one poll interval (5 s): about **5–8 seconds** from a
  cancellation to a refunded card or a cancelled shipment, instead of the next
  outbox or reconciler run.
- The backend stores events for **30 days** (`events.retention`). A consumer
  down for longer misses events; warehouse-service keeps its reconciler (now
  every 10 minutes) as a safety net, and refunds stay capped by the backend's
  `card_refund_requests`.
- The backend does not learn whether a refund was carried out; payment-service
  logs refunds it rejects. Testers check refunds through the payment API.
- New consumers can subscribe to any recorded type without a backend change.
- `card-refund.requested` is internal and never offered to user webhooks.

## ADR 2: Backend keeps a fulfilment read model

**Status:** accepted (backend 3.11.0, warehouse-service 1.0.0); confirmed with
ADR 1.

### Context

warehouse-service owns shipments, but the backend stores a copy of their
progress in `orders.fulfilment_state` (`NONE`, `AWAITING_PICK`, `PICKED`,
`PACKED`, `SHIPPED`, `DELIVERED`, `CANCELLED`). With the event feed in place
the question was whether the backend should drop that duplicated state and ask
warehouse-service instead.

### Decision

The backend keeps `fulfilmentState` as a read model that warehouse-service
updates synchronously with `PUT /internal/v1/orders/{id}/fulfilment`.

- **Order reads stay local.** The order JSON (`GET /api/v1/orders/{id}`, order
  lists, the internal order snapshot) includes `fulfilmentState` without the
  backend calling warehouse-service, which would bring back the dependency
  ADR 1 removed.
- **The cancel/ship race is decided in one place.** A customer may cancel only
  while the state is `NONE` or `AWAITING_PICK`. Because warehouse-service moves
  the state forward with a synchronous PUT before it confirms a pick, the
  backend's row lock decides whether the cancellation or the pick wins; the
  loser gets 409. An asynchronous copy could let both succeed.
- **Consistency is restored automatically.** The feed delivers
  `order.cancelled` to warehouse-service within seconds, and the reconciler
  (every 10 minutes) cancels or adopts shipments the feed did not cover.
- **Split shipments keep one state (warehouse-service 1.5.0).** An order can
  ship as several parcels from different warehouse locations, but the backend
  still sees one forward-only `fulfilmentState`. warehouse-service mirrors the
  aggregate `max(last mirrored, aggregate)`, where the aggregate is
  `AWAITING_PICK` while every parcel awaits pick and otherwise
  `max(PICKED, min over the non-cancelled parcels)`. So the first pick moves
  the order to `PICKED` (from then on the customer can no longer cancel), and
  the order is `SHIPPED` or `DELIVERED` only when every parcel is. The backend
  is unchanged and the cancel/ship race still has one decider: the first
  parcel's pick takes the order row lock exactly like a single shipment's.
  `GET /api/v1/warehouse/reconciliation` lists orders whose parcels disagree
  with the backend's state.

### Consequences

- The same state lives in two places and the rules that keep it in step
  (forward-only steps, repeat is a no-op, `CANCELLED` only through a
  cancellation) are part of the warehouse contract.
- The synchronous PUT means a pick, pack or ship needs the backend to be up;
  warehouse-service answers 503 otherwise.
- With split shipments the backend's state is a summary: per-parcel progress
  (`GET /api/v1/orders/{id}/shipments`) is read from warehouse-service.

## ADR 3: Outbox and feed consumer implementations stay per service

**Status:** accepted.

### Context

The backend (`email_event`, `webhook_deliveries` until 3.20.x), warehouse-service
(`notification_outbox`), payment-service (`payment_outbox`) and
notification-service (`notification_emails`, `webhook_deliveries`) each have a
transactional outbox, and from ADR 1 the three services each have an event
feed consumer. The code is similar, so a shared library was
considered.

### Decision

Each service keeps its own implementation. There is no shared library:

- the services are released independently, each from its own repository with
  its own image; a shared artifact would couple their release cycles and force
  coordinated upgrades for an internal refactoring;
- there is no artifact repository to publish an internal library to, and
  copying source between repositories is no better than owning it;
- the code is small (a table, a scheduled dispatcher, a backoff function) and
  each service's error handling differs (a 409 to a payment capture voids the
  payment; a 503 to a notification is retried; other rejections are final).

The shared behaviour is a **convention**, documented here and checked in each
service's own tests.

#### Outbox convention

| Aspect | Convention |
| --- | --- |
| Write | The outbox row is inserted in the same transaction as the business change; a `requestId` (UUID) is the idempotency key the receiver deduplicates on |
| Send | Right after the commit, then by a scheduled retry job (warehouse and payment: every `PT30S`) |
| Backoff | 30 seconds after the first failure, doubling per attempt, capped at 30 minutes; at most 10 attempts |
| Retryable | Only "receiver unavailable" answers are retried (warehouse notifications: 503; payment results: any 5xx and I/O errors); every other rejection is final at once and handled by the service (for example a 409 to a capture voids the payment) |
| Row state | `attempts`, `next_attempt_at`, `sent_at`, `last_error`. A row is pending while `sent_at` is null and `attempts` is below the maximum, sent once `sent_at` is set, and given up when `attempts` reaches the maximum |
| Payload | Stored once and resent byte for byte (and re-signed where signed) |
| Metrics | `<service>.outbox.pending` (gauge, `<service>_outbox_pending` in Prometheus) in warehouse-service 1.5.0, payment-service 1.3.0 and notification-service 1.0.0 (webhook deliveries plus queued emails); a counter of rows given up, when added, is `<service>.outbox.failed` |

The backend's own outboxes predate this convention and keep their documented
policies (`EmailRetryJob`: backoff 1, 2, 4, 8 minutes, five attempts;
`webhook_deliveries`: `PENDING` → `DELIVERED` or `FAILED`, 1, 2, 4… minutes,
eight attempts).

#### Feed consumer convention

`event_cursors` (one row per consumer) and `processed_events` (handled event
ids), one local transaction per event that locks the cursor row, skips known
ids, applies the change, records the id and advances the cursor; transient
errors stop the run without moving the cursor, non-transient ones are logged
and skipped. See [EVENT_FEED.md](EVENT_FEED.md#consumer-pattern).

### Consequences

- A behaviour change to the convention is made in every service separately and
  recorded here first.
- Reviews compare a new outbox or consumer against this table.

## ADR 4: Database per service on one PostgreSQL server

**Status:** accepted (backend 3.12.0 moved every profile to PostgreSQL;
warehouse-service 1.0.0 and payment-service 1.0.0 got their own schemas).

### Context

Each service must own its data: no service may read another's tables, and
migrations must be independent. A separate PostgreSQL server per service would
give the strongest isolation, but the production VPS has 1 vCPU and about
4 GiB of memory for two sites (stable and aitesters), and the lightweight
profile has to run on student laptops.

### Decision

One PostgreSQL 16 server per site, one database, and per service a **schema**
owned by its own **role**: `public` for the backend, `warehouse`, `payment`
and `notification` for the services. The one-shot `postgres-roles` container
(`postgres/service-roles.sh`) creates each role with
`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION`, makes it the owner of
its schema only and grants `CONNECT` on the database. Services connect with
`currentSchema=<schema>` and run their own Flyway history in it.

### Consequences

- **Isolation is verified, not assumed.** A service role cannot read the
  backend's `public` tables, create objects in `public` or use the other
  service's schema; the production `verify` Ansible role checks each of these
  after every deploy, and
  `scripts/verify-release-images.py` checks that each service uses its own
  role, schema and env file.
- **Memory.** One server (`shared_buffers=32MB`, `max_connections=40`) fits in
  256 MiB in the lightweight profile, and the sandbox server in 160 MiB; the
  services use Hikari pools of at most three connections. Three servers would
  roughly triple the fixed cost per site.
- **Shared fate.** The services share the server's availability, backups and
  restore: one encrypted backup covers all schemas, and a restore rolls all of
  them back together (which is also the rollback procedure for a release that
  migrates several schemas).
- Cross-schema joins are impossible by design; warehouse-service keeps
  snapshots (order id, owner, prices) instead of foreign keys.

## ADR 5: Notifications move out of the backend

**Status:** accepted, November 2026 (backend 3.21.0, notification-service 1.0.0).

### Context

Up to 3.20.x the backend rendered and sent every customer email and delivered
user webhooks: a dispatcher, a retry job and the `webhook_deliveries` outbox
ran inside the process that also serves orders, payments results and the
event feed. A slow webhook receiver or a broker outage competed with checkout
for threads and connections, and every change to a template or to the webhook
retry policy was a backend release, with the l20 course regression run that
goes with it. Both features only *react* to commerce events the backend
already records in its feed (ADR 1).

### Decision

A new service, **notification-service** (port 4005, schema and role
`notification`), owns user webhooks and commerce emails as an event-feed
consumer:

- The backend records `notification.requested` (template, recipient,
  properties, `requestId`) where it used to send a commerce email, when
  `NOTIFICATIONS_DELIVERY=feed`; default `email` keeps the old behaviour.
- `WEBHOOKS_ENABLED=false` stops the backend's dispatcher and retry job; the
  endpoints stay mapped but the gateway sends that traffic to
  notification-service, which serves the **same public API**.
- A one-time import (`GET /internal/v1/webhooks/export`, only for the
  `NOTIFICATION` caller) moves subscriptions and inboxes with their ids and
  secrets.
- Account emails (password reset, `POST /api/v1/email`, email events) stay in
  the backend: they are part of the l20 course contract and are not
  commerce reactions.

Every profile that runs notification-service sets `feed` and webhooks off; the
l20 compatibility stack runs the backends without notification-service, with
the defaults.

### Consequences

- The backend makes no outbound notification call; a receiver or broker outage
  delays emails and deliveries in notification-service's outboxes
  (`notification_outbox_pending`) without touching checkout.
- Webhook deliveries and commerce emails leave 5–8 seconds after the change
  (settle delay plus poll interval) instead of right after the commit. The
  delivery body is byte-compatible, so receivers notice only the latency.
- One more container per site: 160 MiB limit each (see the memory budget in
  [ANSIBLE.md](ANSIBLE.md#memory-budget)) and a fourth database role per site.
- Webhook signing secrets are encrypted with notification-service's own key
  instead of the backend's MFA key; losing the key makes stored secrets
  unreadable, so it lives in Vault next to the other service secrets.
- The feed now has three consumers; a new event type needs no backend change
  to reach a user webhook once notification-service lists it.

## ADR 6: warehouse-service owns the stock ledger

**Status:** accepted, November 2026 (backend 3.22.0, warehouse-service 1.6.0).
Contract: [INVENTORY_OWNERSHIP_CONTRACT.md](INVENTORY_OWNERSHIP_CONTRACT.md).

### Context

Stock had two writers. The backend kept `products.stock_quantity` and the
`inventory_movements` ledger, while warehouse-service, which receives
purchases and restocks returns, had to call the backend's internal receipts API
to change stock it physically handles. Stock is a warehouse concern, and a
second writer made every warehouse change a backend change.

### Decision

- **warehouse-service owns stock**: quantities (`stock_items`), movements and
  checkout reservations live in its schema.
- **The backend keeps a projection**: `products.stock_quantity` becomes a read
  copy, updated from warehouse-service's answers and from its stock-level push
  (`POST /internal/v1/inventory/levels`, applied only when the per-product
  `ledgerVersion` is newer). Catalog, search, the cart and the admin stock levels
  stay local and keep working without warehouse-service; the movement history
  is read from warehouse-service.
- **Commands are synchronous, backend → warehouse**: checkout reservations,
  admin and GraphQL/gRPC adjustments, initial stock and product deletes call
  `WAREHOUSE_URL` with `Authorization: Bearer BACKEND_SERVICE_TOKEN` (connect
  2 s, read 5 s). If warehouse-service is unreachable, slow or failing, the
  public call answers `503 {"message":"Inventory service unavailable"}`.
- This **reverses ADR 1 for stock only**. Every other integration still points
  to the backend, and the backend still publishes cancellations through the
  event feed (stock restores travel there as `stockRestore`).

### Consequences

- The backend now depends on warehouse-service at run time for checkout and
  stock writes, but not at start-up: warehouse-service needs the backend's JWKS,
  so the backend must never `depends_on` warehouse-service in Compose. Until
  warehouse-service is healthy, stock commands answer 503.
- A command whose answer is lost (timeout) can leave a reservation without an
  order; warehouse-service's reaper releases it after two minutes, asking the
  backend first. Product creation and deletion go through a backend outbox, so
  they never fail on warehouse-service.
- The projection is eventually consistent: a warehouse-only change (receipt,
  restock, cancel restore) reaches it after the push, and
  `stock_outbox_pending` shows the backlog. The fault-injection lab's
  `warehouse-down`, `warehouse-slow` and `backend-down warehouse` exercises
  show all three effects.
- One more secret per site (`backend_service_token`,
  `aitesters_backend_service_token`), and the course compatibility stack runs
  a warehouse-service next to each backend.

## ADR 7: A broker transport next to the event feed

**Status:** accepted, November 2026 (backend 3.23.0, warehouse-service 1.7.0,
payment-service 1.4.0, notification-service 1.1.0). Contract:
[EVENT_BROKER_CONTRACT.md](EVENT_BROKER_CONTRACT.md).

### Context

ADR 1 chose a pull feed over ActiveMQ because the lightweight classroom profile
and the aitesters sandbox had no broker. Since then the stack became the base of
a course on testing distributed systems, and the feed hides the failure modes
that course is about: there is no queue to watch, no redelivery, and a poison
event is logged and skipped, so it is simply gone. Meanwhile the production
server already runs Artemis for the `email` queue, and a broker costs the
lightweight profile about 300–400 MiB only when a student asks for it.

### Decision

- **One contract, two transports.** The events, their JSON and their ids stay
  exactly those of the feed. Each service chooses at run time with
  `EVENTS_TRANSPORT=feed|broker`; the native images contain both paths.
- **The outbox stays the source of truth.** `domain_events` is already written
  in the transaction of the change. A relay in the backend publishes the rows it
  has not published yet (`published_at`, migration V27) in one transacted JMS
  session and then marks them, so delivery is at least once and a crash can only
  duplicate, never lose. Change data capture (Debezium) was rejected as too heavy
  for the lab.
- **Topology in the broker's configuration, not in code.** One multicast
  address per site (`awesome.commerce.events`, `aitesters.commerce.events`), one
  durable queue per consuming service filtered on the event type, and one
  dead-letter queue per consumer queue, all declared in
  `artemis/commerce-events.properties` so the queues exist before the first
  publish (a multicast address without queues drops messages).
- **Failures go back to the broker.** A consumer handles each message in a
  transacted session; any exception rolls it back, Artemis redelivers it with
  backoff and dead-letters it after five attempts. The feed poller's "log and
  skip" does not exist in broker mode.
- **The feed stays.** It is the default, the course compatibility stack and the
  replay path. Profiles: full and both production sites use `broker`;
  lightweight uses `feed` unless `docker-compose.broker.yml` is added.

### Consequences

- The backend still calls no consumer, and consumers still depend only on the
  backend, now plus the broker. Checkout never waits for the broker: while
  Artemis is unreachable the relay's backlog grows (`events_relay_pending`) and
  drains afterwards.
- Latency from a cancellation to its effect drops from 5–8 seconds (settle
  delay plus poll interval) to about one second (the relay interval).
- Ordering is per order (message groups), and only while nothing is being
  redelivered: a redelivery delay lets later events of the same order overtake
  the failed one. Consumers therefore deduplicate by event id only and no longer
  trust the feed cursor's sequence order in broker mode.
- New operational surface: the broker topology file, broker credentials for
  every service (`SPRING_ARTEMIS_USER`/`_PASSWORD` from Vault on the server),
  dead letters someone has to look at (`scripts/broker dlq`), and an Ansible
  check that every queue has its consumer.
- The fault-injection lab gains `broker-down`, `broker-slow` and
  `partition-broker`, and the [broker exercises](FAULT_INJECTION_LAB.md#broker-transport).

## Reservations saga (note)

Backend 3.21.0 lets a `PENDING` order's stock hold expire
(`reservationExpiresAt`, default 30 minutes). This is a small **saga** across
the services, coordinated by events and by the order's row lock, with no
distributed transaction:

1. Order created: stock deducted (`ORDER_DEDUCTED`), the hold starts.
2. Either payment-service captures the card and the backend marks the order
   `PAID`, or `ReservationExpiryJob` cancels it first (`order.cancelled` with
   `reason = "RESERVATION_EXPIRED"` plus `order.reservation-expired`;
   compensation: stock `ORDER_RESTORED`, coupon released, gift-card and points
   tenders returned).
3. The row lock on the order decides a race. A capture that arrives after the
   expiry gets 409 and payment-service voids the payment (the existing
   "not payable" compensation); payment-service also refuses to start a
   payment for a snapshot whose `reservationExpiresAt` has passed.
4. warehouse-service never sees an expired order (only `PAID` orders are
   released); notification-service tells subscribers.

There is no grace period: the fault-injection lab's
"payment settles after the reservation expired" exercise
([FAULT_INJECTION_LAB.md](FAULT_INJECTION_LAB.md)) shows the void.

## Follow-ups

- **A GET that mutated state — resolved in warehouse-service 1.3.1.**
  `GET /api/v1/warehouse/shipments/{id}` used to cancel an `AWAITING_PICK`
  shipment when it found the order cancelled on the backend ("reconcile on
  read"). A safe method that changes data surprises caches, retries and
  testers, so 1.3.1 makes the read side-effect free and does not call the
  backend; `order.cancelled` arrives through the event feed within seconds and
  the reconciler covers the rest. The refused-transition path (409 "Order was
  cancelled by the customer" on pick/pack/ship) stays.
