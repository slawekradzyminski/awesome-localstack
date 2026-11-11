# Architecture decisions

Decisions that shape how the backend, warehouse-service and payment-service
work together. Each record states the context, the decision and what follows
from it. A superseded decision stays in this file with its status changed.

| ADR | Decision | Status | Since |
| --- | --- | --- | --- |
| [1](#adr-1-internal-integration-via-a-pull-event-feed) | Internal integration via a pull event feed | Accepted | backend 3.16.0, warehouse-service 1.3.0, payment-service 1.1.0 |
| [2](#adr-2-backend-keeps-a-fulfilment-read-model) | Backend keeps a fulfilment read model | Accepted | backend 3.11.0, warehouse-service 1.0.0 |
| [3](#adr-3-outbox-and-feed-consumer-implementations-stay-per-service) | Outbox and feed consumer implementations stay per service | Accepted | warehouse-service 1.0.0, payment-service 1.0.0 |
| [4](#adr-4-database-per-service-on-one-postgresql-server) | Database per service on one PostgreSQL server | Accepted | backend 3.12.0, warehouse-service 1.0.0 |

## ADR 1: Internal integration via a pull event feed

**Status:** accepted, November 2026 (backend 3.16.0, warehouse-service 1.3.0,
payment-service 1.1.0).

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

### Consequences

- The same state lives in two places and the rules that keep it in step
  (forward-only steps, repeat is a no-op, `CANCELLED` only through a
  cancellation) are part of the warehouse contract.
- The synchronous PUT means a pick, pack or ship needs the backend to be up;
  warehouse-service answers 503 otherwise.

## ADR 3: Outbox and feed consumer implementations stay per service

**Status:** accepted.

### Context

The backend (`email_event`, `webhook_deliveries`), warehouse-service
(`notification_outbox`) and payment-service (`payment_outbox`) each have a
transactional outbox, and from ADR 1 warehouse-service and payment-service
each have an event feed consumer. The code is similar, so a shared library was
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
| Metrics | No outbox exports a dedicated metric today; health is read from the tables and logs. A new outbox metric uses the service's Micrometer registry with the names `<service>.outbox.pending` (gauge) and `<service>.outbox.failed` (counter of rows given up), so the existing Prometheus scrape picks it up |

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
owned by its own **role**: `public` for the backend, `warehouse` and `payment`
for the services. The one-shot `postgres-roles` container
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

## Follow-ups

- **A GET that mutates state.** warehouse-service's
  `GET /api/v1/warehouse/shipments/{id}` cancels an `AWAITING_PICK` shipment as
  a side effect when it finds the order cancelled on the backend (the
  "reconcile on read" path, kept from before the feed). A safe method that
  changes data surprises caches, retries and testers. Now that `order.cancelled`
  reaches warehouse-service through the feed within seconds and the reconciler
  covers the rest, this side effect is a candidate for removal in a later
  warehouse-service release; the refused-transition path (409 "Order was
  cancelled by the customer") can stay.
