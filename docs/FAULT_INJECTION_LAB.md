# Fault-injection lab

Break the network between the services on purpose and watch how the system
copes: a 503 instead of a hang, an outbox that fills up and drains, a feed
consumer that picks up where it stopped, a payment that loses a race against an
expiring reservation. Everything runs locally on top of the lightweight or the
full profile, with one command line tool and no extra installs.

| Item | Value |
| --- | --- |
| Overlay | `docker-compose.chaos.yml` |
| Proxy definitions | `chaos/toxiproxy.json` |
| Command line | `scripts/chaos` (bash, curl and Docker; macOS and Linux) or the `make chaos-*` targets |
| Toxiproxy API | `http://127.0.0.1:8474` (loopback only; `TOXIPROXY_PORT` moves it) |
| Memory | Toxiproxy needs about 10 MiB (limit 32 MiB) |
| Check | `scripts/verify-chaos-overlay.sh` |

## What Toxiproxy is

[Toxiproxy](https://github.com/Shopify/toxiproxy) is a TCP proxy made for
testing. Every service connection that the lab cares about goes through it, and
an HTTP API changes that connection while traffic flows:

- **disable a proxy**: open connections are closed and new ones are refused,
  like a service that is down or a cable that is unplugged;
- **add a toxic**: a fault on the data that passes through, for example
  `latency` (every answer arrives later), `bandwidth` (KB/s limit), `timeout`
  (data stops; the connection hangs or closes after a delay) or `reset_peer`
  (TCP reset). A toxic can hit only a share of the connections (`toxicity`).

The services do not know about it. The overlay only changes three settings:
`BACKEND_BASE_URL` (how warehouse-, payment- and notification-service reach the
backend), `WAREHOUSE_URL` (how the backend reaches warehouse-service for stock
commands, backend 3.22.0+) and `SPRING_DATASOURCE_URL` (how each service reaches
PostgreSQL). The gateway keeps talking to every service directly, so your
browser, Swagger and curl always reach the services; only the links *between*
them break.

## Topology

One proxy per link, so a scenario can break one service's view without touching
the others. warehouse-service can lose the backend while payment-service still
reaches it.

```mermaid
flowchart LR
    U([Browser, curl, tests]) --> G[gateway :8081]
    G --> B[backend]
    G --> W[warehouse-service]
    G --> P[payment-service]
    G --> N[notification-service]
    subgraph T[toxiproxy]
        WB[warehouse-to-backend<br/>:14001]
        PB[payment-to-backend<br/>:24001]
        NB[notification-to-backend<br/>:34001]
        BW[backend-to-warehouse<br/>:14005]
        BD[backend-to-postgres<br/>:15432]
        WD[warehouse-to-postgres<br/>:25432]
        PD[payment-to-postgres<br/>:35432]
        ND[notification-to-postgres<br/>:45432]
    end
    W --> WB --> B
    P --> PB --> B
    N --> NB --> B
    B --> BW --> W
    B --> BD --> DB[(postgres:5432)]
    W --> WD --> DB
    P --> PD --> DB
    N --> ND --> DB
    API([scripts/chaos]) -. "127.0.0.1:8474" .-> T
```

| Proxy | Listens (inside the network) | Upstream | Used by |
| --- | --- | --- | --- |
| `warehouse-to-backend` | `toxiproxy:14001` | `backend:4001` | warehouse-service `BACKEND_BASE_URL` |
| `payment-to-backend` | `toxiproxy:24001` | `backend:4001` | payment-service `BACKEND_BASE_URL` |
| `notification-to-backend` | `toxiproxy:34001` | `backend:4001` | notification-service `BACKEND_BASE_URL` |
| `backend-to-warehouse` | `toxiproxy:14005` | `warehouse-service:4003` | backend `WAREHOUSE_URL` (stock commands; backend 3.22.0+, older backends never call warehouse) |
| `backend-to-postgres` | `toxiproxy:15432` | `postgres:5432` | backend `SPRING_DATASOURCE_URL` |
| `warehouse-to-postgres` | `toxiproxy:25432` | `postgres:5432` | warehouse-service `SPRING_DATASOURCE_URL` |
| `payment-to-postgres` | `toxiproxy:35432` | `postgres:5432` | payment-service `SPRING_DATASOURCE_URL` |
| `notification-to-postgres` | `toxiproxy:45432` | `postgres:5432` | notification-service `SPRING_DATASOURCE_URL` |
| `backend-to-activemq` | `toxiproxy:16161` | `activemq:61616` | backend `SPRING_ARTEMIS_BROKER_URL` (event relay; full profile emails) |
| `warehouse-to-activemq` | `toxiproxy:26161` | `activemq:61616` | warehouse-service `SPRING_ARTEMIS_BROKER_URL` |
| `payment-to-activemq` | `toxiproxy:36161` | `activemq:61616` | payment-service `SPRING_ARTEMIS_BROKER_URL` |
| `notification-to-activemq` | `toxiproxy:46161` | `activemq:61616` | notification-service `SPRING_ARTEMIS_BROKER_URL` (broker transport and emails) |

The four `*-to-activemq` proxies matter only where a broker runs: the full
profile, or lightweight with the broker transport (`scripts/chaos up
lightweight broker`, see [Broker transport](#broker-transport)). Without a
broker they have no upstream and nobody uses them.

**notification-service.** Both base profiles run notification-service
(1.0.0), so `docker-compose.chaos.yml` re-points it like the other services and
the `notification` target works in every scenario.

## Quick start

```bash
scripts/chaos up                     # 1. the lightweight profile with the lab (make chaos-up)
scripts/chaos backend-down warehouse # 2. warehouse-service loses the backend
scripts/chaos heal                   # 3. everything back to normal
```

`scripts/chaos up` starts the profile that already runs (otherwise the
lightweight one) with the overlay, waits until the services are healthy and
prints the proxy table. A running stack is not lost: Compose restarts only the
services whose settings change (backend, warehouse-service, payment-service),
and PostgreSQL is not one of them, so even the lightweight profile's in-memory
data survives. The backend restart gives it a new signing key: sign in again
(the frontend does it by itself with its refresh token).

Look at what is broken at any time:

```text
$ scripts/chaos status
Toxiproxy 2.13.0 on http://127.0.0.1:8474
PROXY                      LISTEN            UPSTREAM               STATE     FAULTS
backend-to-postgres        toxiproxy:15432   postgres:5432          up        -
backend-to-warehouse       toxiproxy:14005   warehouse-service:4003 up        -
notification-to-backend    toxiproxy:34001   backend:4001           up        -
notification-to-postgres   toxiproxy:45432   postgres:5432          up        -
payment-to-backend         toxiproxy:24001   backend:4001           up        backend-slow: latency latency=5000 jitter=0
payment-to-postgres        toxiproxy:35432   postgres:5432          up        -
warehouse-to-backend       toxiproxy:14001   backend:4001           DISABLED  -
warehouse-to-postgres      toxiproxy:25432   postgres:5432          up        -
2 fault(s) active. Remove them with: scripts/chaos heal
```

## Commands

| `scripts/chaos …` | `make …` | Does |
| --- | --- | --- |
| `up [full\|lightweight] [broker] [tracing] [monitoring]` | `make chaos-up [PROFILE=full] [WITH="broker tracing monitoring"]` | Starts the profile with the lab and waits for it. `broker` adds the Artemis event transport to lightweight (the full profile has it already). Overlays that already run (broker, tracing, monitoring) are kept |
| `down` | `make chaos-down` | Stops the whole stack that runs the lab (`down --remove-orphans`; named volumes of the full profile are kept) |
| `list` | `make chaos-list` | Scenarios with one-line descriptions |
| `status` | `make chaos-status` | Proxies and active faults |
| `reset` or `heal` | `make chaos-reset` (or `chaos-heal`) | Enables every proxy and removes every toxic |
| `<scenario> [value] [target]` | `make chaos SCENARIO=<scenario> [VALUE=<n>] [TARGET=<service>]` | Applies a scenario; value and target may come in any order |
| `help` | | Usage |

Scenarios add to each other: `backend-slow payment` and then `postgres-down
warehouse` leaves both active. Running a scenario again replaces its own toxic
(`backend-slow 500` after `backend-slow 5000` leaves 500 ms). `heal` removes
everything.

To leave the lab but keep the stack, start the profile without the overlay:

```bash
docker compose -f lightweight-docker-compose.yml up -d --remove-orphans
```

The services are recreated with their direct URLs and `--remove-orphans`
removes Toxiproxy. (With the monitoring or tracing overlay running, list its
file too, or `--remove-orphans` removes it as well.)

### Error messages

| Message | Meaning and fix |
| --- | --- |
| `no stack is running` | Start one: `scripts/chaos up` |
| `the stack runs without the fault-injection lab` | A profile runs, but without the overlay. `scripts/chaos up` adds it |
| `Toxiproxy runs but does not answer on http://127.0.0.1:8474` | The lab was started with another `TOXIPROXY_PORT`; use the same value |
| `Docker is not running` | Start Docker Desktop or the daemon |
| `unknown target 'x'` / `unknown command or scenario 'x'` | See `scripts/chaos list` |
| `Bind for 127.0.0.1:8474 failed: port is already allocated` (from `up`) | Something else uses 8474: `TOXIPROXY_PORT=18474 scripts/chaos up`, and keep that variable for the other commands |

## Scenarios

Targets: `warehouse`, `payment`, `notification` (the `-service` suffix is
optional), `backend` for the `postgres-*` and `broker-*` scenarios, or nothing
for all of them. The `warehouse-*` scenarios take no target: only the backend calls
warehouse-service.

| Scenario | Toxiproxy change | What you observe |
| --- | --- | --- |
| `backend-down [target]` | disables `<target>-to-backend` | Calls from the target to the backend fail at once with *connection refused*. warehouse-service answers `503 {"message":"Backend unavailable"}` on endpoints that need the backend; event-feed polling and outbox delivery pause |
| `backend-slow [ms] [target]` | `latency` toxic (default 3000 ms) on the answers of `<target>-to-backend` | Every backend call of the target takes `ms` longer. Beyond the client read timeout (warehouse-service: 10 s) the call fails and becomes a 503 |
| `backend-flaky [percent] [target]` | `reset_peer` and `timeout` (5 s) toxics, each on half of the given share of connections (default 30 %) | Some calls fail at once (connection reset), some after 5 s, the rest work. Retries and outboxes earn their keep. Pooled keep-alive connections keep their fate until they are replaced, so the effect is per connection, not per request |
| `bandwidth [KB/s] [target]` | `bandwidth` toxic (default 8 KB/s) on the answers of `<target>-to-backend` | Small answers are fine, big ones (an order list, the JWKS on a cold start) crawl |
| `postgres-stall [ms] [target]` | `timeout` toxics on both directions of `<target>-to-postgres` | Database connections stop passing data. Without `ms` they hang until `heal`; with `ms` they close after `ms`. Requests that need the database hang and fail after HikariCP's 30 s connection timeout; `/actuator/health` stops answering |
| `postgres-down [target]` | disables `<target>-to-postgres` | Pooled connections are closed, new ones refused. Requests that need the database fail at once (warehouse-service: `500` in a few milliseconds); health turns DOWN |
| `warehouse-down` | disables `backend-to-warehouse` | Backend 3.22.0+: stock commands fail at once. Checkout (`POST /api/v1/orders`) and admin stock adjust answer `503 {"message":"Inventory service unavailable"}`; product reads, the cart and admin stock reads (from the backend's projection) keep working. Older backends never call warehouse-service, so nothing changes |
| `warehouse-slow [ms]` | `latency` toxic (default 3000 ms) on the answers of `backend-to-warehouse` | Backend 3.22.0+: checkout and adjust take `ms` longer. From 5000 ms on the backend's read timeout (`WAREHOUSE_READ_TIMEOUT`, 5 s) turns them into the same 503 |
| `broker-down [target]` | disables `<target>-to-activemq` | Broker transport. `backend`: checkout and cancel keep working, the relay backs off and `events_relay_pending` grows until `heal`. A consumer: its listener reconnects every 5 s and its queue holds the events meanwhile. Health stays UP everywhere (the broker is not part of it) |
| `broker-slow [ms] [target]` | `latency` toxic (default 3000 ms) on the answers of `<target>-to-activemq` | Every publish, receive and acknowledgement of the target is delayed: the relay or the consumer falls behind and catches up |
| `partition-<service>` | disables every proxy to and from the service | `partition-warehouse`, `partition-payment`, `partition-notification`: the service loses the backend and its database (and for warehouse, the backend loses warehouse-service). `partition-backend`: no service reaches the backend and the backend loses PostgreSQL and warehouse-service. `partition-postgres`: nobody reaches PostgreSQL |

The gateway is never behind Toxiproxy, so the backend's own API keeps working
under `backend-down` (a customer can still place and cancel orders: the
backend reaches warehouse-service through its own link, `backend-to-warehouse`).
`partition-backend` and the `postgres-*` scenarios on the backend are the ones
that break the storefront.

## Where to look

| Question | How |
| --- | --- |
| What is broken? | `scripts/chaos status` |
| What did one request do? | Send your own `X-Request-Id` and search every log for it (see [Find everything with X-Request-Id](#exercise-6-find-everything-with-x-request-id)) |
| A service's own log | `docker compose -p awesome-light logs -f warehouse-service` (full profile: `-p awesome-full-native`) |
| Is a service healthy? | `docker compose -p awesome-light ps`, or `docker compose -p awesome-light exec gateway curl -s http://warehouse-service:4003/actuator/health` |
| Database rows | `docker compose -p awesome-light exec postgres psql -U postgres -d testdb` (schemas `public` = backend, `warehouse`, `payment`, `notification`) |
| Metrics | `docker compose -p awesome-light exec gateway curl -s http://payment-service:4004/actuator/prometheus \| grep outbox`, or Grafana/Prometheus with `scripts/chaos up monitoring` |
| Traces | `scripts/chaos up tracing`, then Jaeger on `http://127.0.0.1:16686` ([Tracing a request](../docs-site/docs/operations/tracing.md)) |

The examples below use the lightweight profile (`-p awesome-light`), the demo
accounts (`admin` / `LocalDemoAdmin123!`, `warehouse` / `warehouse`, `client` /
`client`) and `jq`. Get tokens once:

```bash
B=http://localhost:8081
login() { curl -s $B/api/v1/users/signin -H 'Content-Type: application/json' \
  -d "{\"username\":\"$1\",\"password\":\"$2\"}" | jq -r .token; }
A=$(login admin 'LocalDemoAdmin123!'); W=$(login warehouse warehouse); C=$(login client client)
psql() { docker compose -p awesome-light exec -T postgres psql -U postgres -d testdb -c "$1"; }
```

Order helpers used by several exercises:

```bash
new_order() {  # creates a PENDING order for the client and prints its id
  pid=$(curl -s "$B/api/v1/products/search?inStock=true&sort=price_asc&size=1" -H "Authorization: Bearer $C" | jq '.content[0].id')
  curl -s $B/api/v1/cart/items -H "Authorization: Bearer $C" -H 'Content-Type: application/json' \
    -d "{\"productId\":$pid,\"quantity\":1}" >/dev/null
  curl -s $B/api/v1/orders -H "Authorization: Bearer $C" -H 'Content-Type: application/json' \
    -d '{"street":"Main 1","city":"Warszawa","state":"M","zipCode":"00-001","country":"Poland"}' | jq .id
}
pay() {  # pay <orderId> <card number>
  curl -s $B/api/v1/payments -H "Authorization: Bearer $C" -H 'Content-Type: application/json' \
    -H "X-Request-Id: pay-$1" -H "Idempotency-Key: pay-$1-$RANDOM" \
    -d "{\"orderId\":$1,\"card\":{\"number\":\"$2\",\"expiryMonth\":12,\"expiryYear\":2031,\"cvc\":\"123\",\"holderName\":\"Lab Student\"}}" | jq
}
```

Card numbers: `4242 4242 4242 4242` captures at once, `4000 0000 0000 0077`
stays `PROCESSING` and settles after `PAYMENT_SETTLEMENT_DELAY` (10 s by
default).

## Guided exercises

Each exercise ends with `scripts/chaos heal`. If something looks stuck, run
`scripts/chaos status` first.

### Exercise 1: warehouse answers 503 when it loses the backend

warehouse-service asks the backend for orders and mirrors every fulfilment step
to it. Without the backend it must fail fast and clearly, not hang.

1. Check the normal answer:

    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' $B/api/v1/warehouse/queue -H "Authorization: Bearer $W"   # 200
    ```

    This first call also matters: warehouse-service verifies your token with
    the backend's public key, which it fetches from the backend once and caches.
    Without that call (for example right after `scripts/chaos up`, which
    restarts the backend with a new key) even authentication needs the backend:
    under `backend-down` you would get the 503 for the key fetch and then
    `401 {"message":"Invalid or expired token"}` until `heal`. A second lesson in
    hidden dependencies.

2. Cut warehouse-service off: `scripts/chaos backend-down warehouse`.
3. Repeat the call with your own request id:

    ```bash
    curl -s -w ' %{http_code} in %{time_total}s\n' $B/api/v1/warehouse/queue \
      -H "Authorization: Bearer $W" -H 'X-Request-Id: lab-ex1'
    ```

    **Expected:** `{"message":"Backend unavailable"} 503` in a few
    milliseconds (connection refused, no waiting). Releasing (`POST
    /api/v1/warehouse/shipments {"orderId":…}`) and picking (`POST
    /api/v1/warehouse/shipments/{id}/pick`) of a paid order answer the same 503,
    and the shipment does not change.
4. The rest still works: `new_order` places an order (the backend itself is
   fine), and `GET /api/v1/payments/...` answers (payment-service still reaches
   the backend).
5. Find the cause in the warehouse log:

    ```bash
    docker compose -p awesome-light logs warehouse-service | grep -F lab-ex1
    ```

    **Expected:** an ERROR line `Backend internal API is unreachable: I/O
    error on GET request for "http://toxiproxy:14001/internal/v1/…"` under
    `[<trace id>,lab-ex1]`. The gateway's JSON line for `lab-ex1` shows
    `"status":503` with an `upstream_response_time` of a few milliseconds: the
    service failed fast, nothing waited.
6. Make it slow instead of down: `scripts/chaos heal`, then `scripts/chaos
   backend-slow 4000 warehouse`. The queue now answers 200 after about 4 s.
   With `backend-slow 12000 warehouse` it answers 503 after about 10 s: the
   warehouse client's read timeout (`backend.read-timeout: 10s`) turned the
   slowness into a failure.
7. `scripts/chaos heal`. The next call answers 200 at once.

Variant: `scripts/chaos backend-flaky 50 warehouse` and call the queue ten
times. Some calls answer 200, some 503 at once, some 503 after 5 s.

### Exercise 2: an outbox backlog grows and drains

Services never call another service inside the user's request when they do not
have to. They write the message into an **outbox table** in their own database,
in the same transaction as their state change, and a dispatcher sends it later,
retrying until the receiver accepts it. While a link is down the outbox grows;
after `heal` it drains by itself.

| Service | Outbox table | Pending rows | Gauge (`/actuator/prometheus`) |
| --- | --- | --- | --- |
| payment-service | `payment.payment_outbox` (payment results for the backend) | `sent_at IS NULL` | `payment_outbox_pending` (payment-service 1.3.0+) |
| warehouse-service | `warehouse.notification_outbox` (customer notifications for the backend) | `sent_at IS NULL` | `warehouse_outbox_pending` (warehouse-service 1.5.0+) |
| warehouse-service | `warehouse.stock_level_outbox` (stock levels for the backend's projection) | see Exercise 8 | `stock_outbox_pending` (warehouse-service 1.6.0+) |
| notification-service | `notification.notification_emails` (status `QUEUED`) and its webhook deliveries (status `PENDING`) | see the SQL below | `notification_outbox_pending` (notification-service 1.0.0+) |

**payment-service (works with today's images):**

1. Place an order and pay with the slow card: `O=$(new_order); pay $O 4000000000000077`.
   **Expected:** `"status": "PROCESSING"`.
2. Within 10 s: `scripts/chaos backend-down payment`.
3. Wait 15 s. The simulated provider settles the payment, but the result cannot
   reach the backend:

    ```bash
    psql "select id, order_id, attempts, next_attempt_at, sent_at, left(last_error, 60) as last_error
            from payment.payment_outbox order by id desc limit 5"
    docker compose -p awesome-light exec gateway curl -s http://payment-service:4004/actuator/prometheus | grep outbox_pending
    curl -s $B/api/v1/orders/$O -H "Authorization: Bearer $C" | jq .status
    ```

    **Expected:** a row with `sent_at` empty, `attempts` growing every 30 s and
    `0 Backend unavailable` in `last_error` (no HTTP status: the connection
    failed); `payment_outbox_pending 1.0` (1.3.0+); the order is still `PENDING`
    although the card was charged. The payment-service log shows `Could not
    deliver payment result … for order <id> (will retry): 0 Backend
    unavailable` under the payment request's id (`pay-<order id>`).
4. `scripts/chaos heal`. **Expected:** within 30 s (the retry interval) `sent_at`
   is set, the gauge drops to 0 and the order becomes `PAID`.

**warehouse-service** (not part of the automated check; the steps follow the
same pattern): release and ship a paid order (`POST
/api/v1/warehouse/shipments`, then `/pick`, `/pack {"weightKg":1.2}` and `/ship
{"carrier":"DHL"}`) with `backend-down warehouse` applied **after** the ship
call returned, then advance the simulated carrier (`POST
/api/v1/warehouse/shipments/{id}/carrier/advance`): the "shipped" and
"delivered" customer notifications queue up in

```sql
select id, template, attempts, sent_at, left(last_error, 60) from warehouse.notification_outbox
 where sent_at is null order by id;
```

and drain after `heal`.

**notification-service (1.0.0+):** `scripts/chaos backend-down notification`
stops it from reading the event feed, so nothing new is queued; `scripts/chaos
partition-notification` also stops it from recording deliveries. To build a
delivery backlog, point a webhook at a dead URL or slow the email transport and
read

```sql
select status, count(*) from notification.notification_emails group by status;
select status, count(*) from notification.webhook_deliveries group by status;
```

### Exercise 3: the event-feed consumer resumes from its cursor

warehouse-service and payment-service learn about cancellations from the
backend's [event feed](EVENT_FEED.md). Each keeps a **cursor**: the sequence of
the last event it handled, stored in its own database. After an outage it asks
for "everything after my cursor", so nothing is lost and nothing is handled
twice.

1. Prepare a paid order with a released shipment:

    ```bash
    O=$(new_order); pay $O 4242424242424242
    curl -s $B/api/v1/warehouse/shipments -H "Authorization: Bearer $W" \
      -H 'Content-Type: application/json' -d "{\"orderId\":$O}" | jq '{id, status}'   # AWAITING_PICK
    psql "select * from warehouse.event_cursors"
    ```

    Note `last_sequence` of the `warehouse-service` row.
2. Partition the warehouse: `scripts/chaos partition-warehouse`.
3. The customer cancels the order (the backend is still reachable):

    ```bash
    curl -s -X POST $B/api/v1/orders/$O/cancel -H "Authorization: Bearer $C" -H 'X-Request-Id: lab-ex3' | jq .status   # CANCELLED
    ```

4. The backend recorded the event; the warehouse has not seen it:

    ```bash
    psql "select sequence, type, order_id, request_id from domain_events order by sequence desc limit 3"
    psql "select id, status from warehouse.shipments where order_id = $O"   # AWAITING_PICK
    psql "select * from warehouse.event_cursors"                            # unchanged
    psql "select * from payment.event_cursors"                              # moved: payment-service refunded
    ```

    The warehouse log shows the poller failing every 5 s.
5. `scripts/chaos heal`. Within about 10 s:

    ```bash
    psql "select id, status, last_actor from warehouse.shipments where order_id = $O"   # CANCELLED, system
    psql "select * from warehouse.event_cursors"                                        # last_sequence moved on
    ```

    The consumer read every event after its stored cursor, cancelled the
    shipment once (`warehouse.processed_events` holds the event id) and moved the
    cursor.

Try `scripts/chaos partition-payment` the same way: cancel a card-paid order
and watch `GET /api/v1/payments/{id}` stay `CAPTURED` until `heal`, then become
`REFUNDED`.

### Exercise 4: a slow payment against an expiring reservation

Needs backend 3.21.0 and payment-service 1.3.0. From backend 3.21.0 a new order
holds its stock only until `reservationExpiresAt`; then the backend cancels it
(`order.cancelled` with reason `RESERVATION_EXPIRED`). A payment result that
arrives after that is answered **409** and payment-service **voids** the payment.

1. Start the lab with a short reservation:

    ```bash
    ORDERS_RESERVATION_TTL=PT2M scripts/chaos up
    ```

2. Place an order and note its deadline: `O=$(new_order)`, then
   `curl -s $B/api/v1/orders/$O -H "Authorization: Bearer $C" | jq '{status, reservationExpiresAt}'`.
3. Pay with the slow card and cut payment-service off before it settles:

    ```bash
    pay $O 4000000000000077            # PROCESSING
    scripts/chaos backend-down payment
    ```

4. Let the reservation run out. Wait two minutes, or expire it now as admin:

    ```bash
    curl -s -X POST $B/api/v1/admin/orders/$O/expire-reservation -H "Authorization: Bearer $A" | jq .status   # CANCELLED
    ```

    The payment has settled at the provider meanwhile and its result waits in
    `payment.payment_outbox` (Exercise 2).
5. `scripts/chaos heal`. Within 30 s the outbox delivers the result, the
   backend answers 409 because the order is no longer `PENDING`, and
   payment-service voids the payment:

    ```bash
    docker compose -p awesome-light logs payment-service | grep -F pay-$O    # the 409 for this order
    psql "select order_id, attempts, sent_at, last_error from payment.payment_outbox order by id desc limit 1"
    curl -s $B/api/v1/orders/$O/payments -H "Authorization: Bearer $C" | jq '.[0].status'   # VOIDED
    curl -s $B/api/v1/orders/$O -H "Authorization: Bearer $C" | jq .status                  # CANCELLED
    ```

    **Expected:** the log line `Backend refused payment result … for order <id>:
    Order is not payable; voiding the capture`, the outbox row sent with
    `last_error` `409 Order is not payable`, the payment `VOIDED`. The order
    stays cancelled and its stock is back (`ORDER_RESTORED`); the customer is not
    charged for a cancelled order.

**With images before reservation expiry** (backend 3.20.1, payment-service 1.2.1) the same race
works with a customer cancel instead of the expiry: skip step 1 and step 4's
expire call, and cancel the order in step 4 with `curl -s -X POST
$B/api/v1/orders/$O/cancel -H "Authorization: Bearer $C"`. Everything else,
including the `409 Order is not payable` and `VOIDED`, is identical (`scripts/verify-chaos-overlay.sh`
checks this variant).

Without Toxiproxy the same race appears with a slow provider:
`ORDERS_RESERVATION_TTL=PT2M PAYMENT_SETTLEMENT_DELAY=PT3M scripts/chaos up`,
pay with `4000 0000 0000 0077` and wait three minutes. A new payment for an
already expired order is refused up front with `409 {"message":"Order
reservation expired"}`.

### Exercise 5: PostgreSQL stalls

A stalled database is worse than a dead one: nothing fails, everything waits.

1. `scripts/chaos postgres-stall warehouse`.
2. Call an endpoint that needs the warehouse database and time it:

    ```bash
    curl -s -w ' %{http_code} in %{time_total}s\n' $B/api/v1/warehouse/shipments \
      -H "Authorization: Bearer $W" -H 'X-Request-Id: lab-ex5'
    ```

    **Expected:** `500 Internal Server Error` after about 30 s. HikariCP finds
    its pooled connections dead, cannot open a new one through the stalled link
    and gives up after its `connectionTimeout` (30 s).
3. Read the warehouse log:

    ```bash
    docker compose -p awesome-light logs --since 2m warehouse-service | grep -E 'Hikari|lab-ex5'
    ```

    **Expected:** `HikariPool-1 - Failed to validate connection … (This
    connection has been closed.)` and `HikariPool-1 - Connection is not
    available, request timed out after 30003ms (total=0, active=0, idle=0,
    waiting=3)` under `lab-ex5`: the pool is empty and three requests queue for
    it. The health endpoint stops answering, so after three failed checks
    `docker compose -p awesome-light ps` shows the service `unhealthy`.
4. `scripts/chaos heal`. HikariCP opens new connections on the next request;
   the service answers normally within a second or two.
5. Compare with `scripts/chaos postgres-down warehouse`: the same call answers
   `500` in a few milliseconds. A refused connection fails fast, a stalled one
   costs every caller 30 s. `scripts/chaos postgres-stall 5000 warehouse` stalls
   connections and closes them after 5 s.
6. `scripts/chaos postgres-stall backend` does the same to the backend:
   `GET /api/v1/products` hangs until the gateway gives up with
   `504 Gateway Time-out` after 60 s, and the storefront hangs with it. After
   `heal` the backend answers at once.

### Exercise 6: find everything with X-Request-Id

Every request gets an `X-Request-Id` at the gateway, and every hop logs it
(see [Tracing a request](../docs-site/docs/operations/tracing.md)). Send your own
id to make it easy to find:

```bash
curl -s -o /dev/null -D - $B/api/v1/warehouse/queue -H "Authorization: Bearer $W" \
  -H 'X-Request-Id: lab-find-me' | grep -i x-request-id
docker compose -p awesome-light logs --no-color | grep -F lab-find-me
```

**Expected:** the response echoes `X-Request-Id: lab-find-me`; the logs show the
gateway access-log line (JSON with `status`, `upstream_response_time` and the
`trace_id`), the warehouse-service lines and, when the backend was reached, the
backend lines with the same id. Under a fault
the gateway line shows how long the upstream took, and the service line shows
the error. Work done later because of the request (a refund from the event
feed, an outbox delivery) is logged with the same id, so `grep` finds it too.
With the tracing overlay the same `trace_id` opens the whole call tree in
Jaeger.

### Exercise 7: checkout without the stock owner

Needs backend 3.22.0 and warehouse-service 1.6.0. From these versions
warehouse-service owns the stock ledger
([ADR 6](ARCHITECTURE_DECISIONS.md#adr-6-warehouse-service-owns-the-stock-ledger)):
the backend keeps only a read copy of every product's stock (the
**projection**) and asks warehouse-service, synchronously, for every stock
command. This is the one call the backend makes to another service, and it
goes through its own proxy, `backend-to-warehouse`.

1. Pick a product and note its stock (read from the projection):

    ```bash
    P=$(curl -s "$B/api/v1/products/search?inStock=true&sort=price_asc&size=1" -H "Authorization: Bearer $C" | jq '.content[0].id')
    stock() { curl -s $B/api/v1/products/$P -H "Authorization: Bearer $C" | jq .stockQuantity; }
    stock
    ```

2. Cut the backend off from the stock owner: `scripts/chaos warehouse-down`.
3. Everything that only **reads** stock still works:

    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' $B/api/v1/products/$P -H "Authorization: Bearer $C"        # 200
    curl -s -o /dev/null -w '%{http_code}\n' $B/api/v1/admin/inventory/$P -H "Authorization: Bearer $A" # 200
    curl -s -o /dev/null -w '%{http_code}\n' $B/api/v1/cart/items -H "Authorization: Bearer $C" \
      -H 'Content-Type: application/json' -d "{\"productId\":$P,\"quantity\":1}"                        # 200
    ```

4. Everything that **changes** stock fails fast:

    ```bash
    curl -s -w ' %{http_code} in %{time_total}s\n' $B/api/v1/orders -H "Authorization: Bearer $C" \
      -H 'Content-Type: application/json' -H 'X-Request-Id: lab-ex7' \
      -d '{"street":"Main 1","city":"Warszawa","state":"M","zipCode":"00-001","country":"Poland"}'
    curl -s -w ' %{http_code}\n' $B/api/v1/admin/inventory/$P/adjustments -H "Authorization: Bearer $A" \
      -H 'Content-Type: application/json' \
      -d "{\"delta\":5,\"reason\":\"Lab restock\",\"requestId\":\"$(uuidgen | tr '[:upper:]' '[:lower:]')\"}"
    stock
    ```

    **Expected:** `{"message":"Inventory service unavailable"} 503` in a few
    milliseconds for both, and the same stock as in step 1: the reservation
    never reached warehouse-service, so nothing was deducted. The cart still
    holds the product. `docker compose -p awesome-light logs backend | grep -F
    lab-ex7` finds the backend's log lines for the failed reservation call to
    `toxiproxy:14005` (`/internal/v1/stock/reservations`).
5. `scripts/chaos heal` and run the same checkout again. **Expected:** `201`,
   the order is `PENDING`, the cart is empty and `stock` is one lower.

**Slow variant: an answer that gets lost.**

1. Put the product back in the cart (step 3), then `scripts/chaos warehouse-slow 3000`.
   Checkout answers `201` after about 3 s: slow, but inside the backend's
   5 s read timeout (`WAREHOUSE_READ_TIMEOUT`).
2. Put it in the cart again, then `scripts/chaos warehouse-slow 7000`. Checkout
   answers `503 Inventory service unavailable` after about 5 s. But the
   request *did* reach warehouse-service: only its answer was delayed. The
   reservation was booked and the stock deducted, and `stock` shows it,
   because warehouse-service pushes stock levels to the projection through
   the other link, `warehouse-to-backend`, which works:

    ```bash
    stock                                                                   # one lower, without an order
    psql "select status, count(*) from warehouse.stock_reservations group by status"   # one PENDING_CONFIRMATION
    ```

3. `scripts/chaos heal`. Nobody confirms the reservation, so warehouse-service's
   reaper releases it once it is older than `WAREHOUSE_RESERVATION_CONFIRM_TIMEOUT`
   (2 minutes; the reaper runs every 30 s). Before releasing, it asks the
   backend whether an order holds the reservation, and there is none. Within
   about 2.5 minutes (start the lab with
   `WAREHOUSE_RESERVATION_CONFIRM_TIMEOUT=PT20S WAREHOUSE_RESERVATION_REAPER_INTERVAL=PT5S scripts/chaos up`
   to wait about 25 s instead):

    ```bash
    stock                                                                   # back to the old value
    curl -s "$B/api/v1/admin/inventory/$P/movements?size=1" -H "Authorization: Bearer $A" \
      | jq '.content[0] | {type, delta, actor, reason}'   # ORDER_RESTORED, system, "Reservation expired unconfirmed"
    ```

    A timeout does not tell the caller whether the other side did the work.
    The reaper is the compensation that makes "maybe" safe.

### Exercise 8: the stock projection catches up

Needs backend 3.22.0 and warehouse-service 1.6.0. Every change to the stock
ledger also writes a row to warehouse-service's `stock_level_outbox`, in the
same transaction. A dispatcher pushes it to the backend's projection right
after the commit and retries every 5 s (`WAREHOUSE_STOCK_PUSH_RETRY_INTERVAL`).
The gauge `stock_outbox_pending` counts the rows that wait.

Most stock changes start at the backend, which updates its projection from
warehouse-service's answer at once. A purchase receipt starts at
warehouse-service, so the backend learns about it only from the push.

1. Prepare a submitted purchase order for the product of Exercise 7 (`$P`, `stock`):

    ```bash
    S=$(curl -s $B/api/v1/admin/suppliers -H "Authorization: Bearer $A" | jq '.[0].id')
    PO=$(curl -s $B/api/v1/admin/purchase-orders -H "Authorization: Bearer $A" -H 'Content-Type: application/json' \
      -d "{\"supplierId\":$S,\"lines\":[{\"productId\":$P,\"quantity\":5,\"unitCost\":1.00}]}" | jq .id)
    curl -s -X POST $B/api/v1/admin/purchase-orders/$PO/submit -H "Authorization: Bearer $A" | jq .status   # SUBMITTED
    pending() { docker compose -p awesome-light exec -T gateway curl -s http://warehouse-service:4003/actuator/prometheus | grep '^stock_outbox_pending'; }
    stock; pending                                                           # stock_outbox_pending 0.0
    ```

2. Cut warehouse-service off from the backend: `scripts/chaos backend-down warehouse`.
3. Receive the goods. warehouse-service books them in its own ledger and does
   not need the backend for that:

    ```bash
    curl -s $B/api/v1/admin/purchase-orders/$PO/receipts -H "Authorization: Bearer $A" -H 'Content-Type: application/json' \
      -d "{\"requestId\":\"$(uuidgen | tr '[:upper:]' '[:lower:]')\",\"lines\":[{\"productId\":$P,\"quantity\":5}]}" | jq .status   # RECEIVED
    ```

4. Compare the two views of the same stock:

    ```bash
    pending                                                                  # 1.0 or more, and it stays
    stock                                                                    # unchanged: the projection has not heard
    curl -s "$B/api/v1/admin/inventory/$P/movements?size=1" -H "Authorization: Bearer $A" \
      | jq '.content[0] | {type, delta, quantityAfter}'                     # PURCHASE_RECEIVED, +5
    ```

    The movement list is read from warehouse-service's ledger (through
    `backend-to-warehouse`, which works), the stock quantity from the
    backend's projection. During the outage they disagree: that is eventual
    consistency, visible with two curls.
5. `scripts/chaos heal`. **Expected:** within about 5 s `stock` is 5 higher and
   `pending` is back to `0.0`. The push carries a per-product `ledgerVersion`,
   so a late or repeated push never moves the projection backwards.

Variant: cancel a `PENDING` order during `backend-down warehouse`. The backend
records the cancellation at once, but the stock comes back only after `heal`:
warehouse-service learns about the cancel from the event feed (Exercise 3),
writes `ORDER_RESTORED` and pushes the new level.

### Exercise 9: a slow order save against the reaper

Needs backend 3.22.2 and warehouse-service 1.6.0. Exercise 7 showed the reaper
cleaning up after a checkout that gave up. This one asks the opposite
question: what if the checkout did **not** give up, but saving the order took
longer than the reservation timeout?

The reaper decides by asking the backend whether an order holds the
reservation. An order that is still being saved does not exist yet for any
other transaction, so the honest answer is "no". Up to backend 3.22.1 the
reaper then released the stock, and a moment later the order committed: an
order without stock behind it. From 3.22.2 the order transaction first claims
the reservation id (table `stock_reservation_claims`), and the reaper's lookup
writes a tombstone for the same id before it reads `orders`. Whichever comes
second waits for the first, so the two can no longer overtake each other: the
lookup waits for the order and confirms it, or a save that comes after a
"no order" answer fails with `409 Stock reservation expired during checkout;
please try again` instead of keeping an order without stock.

Latency on the database link does **not** reproduce the race: it slows the
reaper's lookup as much as the order save (and long latency only drains the
connection pool). The fault has to hit the order save alone. A row lock on the
customer's cart does exactly that: the checkout's last step deletes the cart
rows, so it waits for the lock, while the reservation is already booked.

1. Start the lab with a short reaper, so the race fits into half a minute:

    ```bash
    WAREHOUSE_RESERVATION_CONFIRM_TIMEOUT=PT20S WAREHOUSE_RESERVATION_REAPER_INTERVAL=PT5S scripts/chaos up
    ```

    Sign in again (`C`, `A`, see [Where to look](#where-to-look)) and pick a
    product (`P`, `stock`) as in Exercise 7. Empty the cart and add one item:

    ```bash
    curl -s -o /dev/null -X DELETE $B/api/v1/cart -H "Authorization: Bearer $C"
    curl -s -o /dev/null $B/api/v1/cart/items -H "Authorization: Bearer $C" -H 'Content-Type: application/json' \
      -d "{\"productId\":$P,\"quantity\":1}"
    stock
    ```

2. In a second terminal, lock the cart rows for 30 s (longer than the 20 s
   timeout):

    ```bash
    docker compose -p awesome-light exec -T postgres psql -U postgres -d testdb -c \
      "begin; select id from cart_items where username = 'client' for update; select pg_sleep(30); commit;"
    ```

3. Back in the first terminal, check out at once:

    ```bash
    curl -s -w ' %{http_code} in %{time_total}s\n' $B/api/v1/orders -H "Authorization: Bearer $C" \
      -H 'Content-Type: application/json' -H 'X-Request-Id: lab-ex9' \
      -d '{"street":"Main 1","city":"Warszawa","state":"M","zipCode":"00-001","country":"Poland"}' | tail -c 40
    ```

    **Expected:** `201` after about 30 s. While the order waited for the lock,
    the reaper found the reservation older than 20 s and asked the backend
    about it. Instead of answering "no order", the lookup waited for the order
    save (if it waits longer than warehouse-service's 10 s read timeout, the
    reaper simply asks again on its next run) and then found the order.

4. Look at the reservation and the stock:

    ```bash
    psql "select status, order_id from warehouse.stock_reservations order by created_at desc limit 1"   # CONFIRMED, the new order
    stock                                                                                               # one lower, once
    docker compose -p awesome-light logs warehouse-service | grep -i 'reservation' | tail -n 3
    ```

    With backend 3.22.1 or older the same steps end with the reservation
    `RELEASED`, an order that exists, and the stock back at the old value.

## Broker transport

The same events can travel through ActiveMQ Artemis instead of the HTTP feed
([EVENT_BROKER_CONTRACT.md](EVENT_BROKER_CONTRACT.md)). The full profile always
does; the lightweight profile does with one more overlay:

```bash
scripts/chaos up lightweight broker      # or: make chaos-up WITH=broker
scripts/broker stat                      # every commerce queue: consumers, waiting messages
```

The Artemis console is on `http://127.0.0.1:8161/console` (`admin` /
`admin`): *Artemis* tab, `awesome.commerce.events` and its queues. The
exercises below compare the two transports; Exercise 3 shows the feed side.

| | Feed (lightweight default) | Broker |
| --- | --- | --- |
| Who moves the event | Each consumer polls `GET /internal/v1/events` every 5 s | The backend's relay publishes every second; Artemis pushes to the consumers |
| Where a backlog is visible | Cursor (`event_cursors`) behind the feed | Message count of the service's queue |
| A failing event | Logged and skipped (gone) | Redelivered 5 times, then in `DLQ.<queue>` |
| Duplicates | `processed_events` | Broker duplicate detection, then `processed_events` |

### Exercise 10: watch an event cross the broker

1. Open the console, or keep `watch -n1 scripts/broker stat` running.
2. Place an order, pay it with `4242 4242 4242 4242` and cancel it:

   ```bash
   O=$(new_order); pay $O 4242424242424242
   curl -s -X POST $B/api/v1/orders/$O/cancel -H "Authorization: Bearer $C" | jq .status
   ```

3. Within about a second, `ADDED` grows on all three queues: warehouse-service
   gets `order.cancelled` and `stock.restore-requested`, payment-service
   `card-refund.requested`, notification-service everything else (the queue
   filters on the `type` property).
4. The stock is back and the card refunded:

   ```bash
   psql "select type, delta from warehouse.stock_movements where order_id = $O"
   psql "select status from payment.payments where order_id = $O"
   ```

5. The feed cursors did not move (`select * from warehouse.event_cursors`):
   in broker mode nobody polls.

**Question:** the restore took about one second here and 5 to 8 seconds with
the feed (Exercise 3). Where did the difference go? (The settle delay and the
poll interval; the relay runs every second.)

### Exercise 11: a poison message ends in the dead-letter queue

```bash
scripts/broker poison warehouse
docker compose -p awesome-light logs -f warehouse-service | grep -i redelivery
```

1. warehouse-service rolls the message back five times, after 1, 2, 4 and 8
   seconds, then Artemis moves it to `DLQ.awesome.commerce.events.warehouse-service`
   (`scripts/broker stat`, `scripts/broker dlq warehouse`).
2. Meanwhile cancel another order: it is restored normally. A poison message
   does not block the queue.
3. Send it back: `scripts/broker redrive warehouse`. It fails five more times
   and returns to the DLQ. Delete it with `scripts/broker purge-dlq warehouse`.

**Compare with the feed:** with `EVENTS_TRANSPORT=feed` a malformed event is
logged as "could not be handled and is skipped" and recorded as processed. It
is gone; nothing tells a tester later. **Question:** which test would have
found that difference before production?

### Exercise 12: a consumer is down, its queue fills up

```bash
O=$(new_order)                                   # checkout needs warehouse-service (stock reservation)
docker compose -p awesome-light stop warehouse-service
curl -s -X POST $B/api/v1/orders/$O/cancel -H "Authorization: Bearer $C" | jq .status   # still works
scripts/broker stat          # the warehouse queue holds 2 messages, the others are empty
docker compose -p awesome-light start warehouse-service
```

The two events wait in the queue (no feed involved) and are handled as soon as
the listener is back; the stock is restored. Try the same with
`scripts/chaos broker-down warehouse` instead of stopping the container: the
service stays healthy, its listener reconnects every 5 seconds, and the effect
is the same.

### Exercise 13: the broker is down for the backend

```bash
scripts/chaos broker-down backend
O=$(new_order)                                     # checkout still 201
curl -s -X POST $B/api/v1/orders/$O/cancel -H "Authorization: Bearer $C" | jq .status
docker compose -p awesome-light exec gateway curl -s http://backend:4001/actuator/prometheus | grep events_relay
scripts/chaos heal
```

`events_relay_pending` counts the events in the outbox. The backend logs one
warning ("Event relay cannot reach the broker") and retries with a backoff up to
30 seconds; nothing is lost because the events are rows in `domain_events`.
After `heal` the backlog drains (within the current backoff) and the stock is
restored.

**Question:** why can checkout succeed while the broker is down, when Exercise 7
showed it cannot while warehouse-service is down? (The reservation is a
synchronous command; the events are an outbox.)

## With tracing and monitoring

The overlays combine:

```bash
scripts/chaos up lightweight tracing monitoring
# or: make chaos-up WITH="tracing monitoring"
```

- Jaeger (`http://127.0.0.1:16686`) shows a delayed span under
  `backend-slow` and an error span under `backend-down` (backend 3.21.0,
  warehouse-service 1.5.0, payment-service 1.3.0 and later).
- Grafana (`http://localhost:3000`) shows request rates and latencies; the
  outbox gauges show the backlog of Exercise 2.

## The Toxiproxy API by hand

`scripts/chaos` is a thin wrapper. The same with curl:

```bash
T=http://127.0.0.1:8474
curl -s $T/proxies | jq 'map_values({listen, upstream, enabled, toxics})'
curl -s -X PATCH $T/proxies/warehouse-to-backend -d '{"enabled":false}'          # backend-down warehouse
curl -s -X POST $T/proxies/payment-to-backend/toxics \
  -d '{"name":"slow","type":"latency","stream":"downstream","toxicity":1,"attributes":{"latency":3000}}'
curl -s -X DELETE $T/proxies/payment-to-backend/toxics/slow
curl -s -X POST $T/reset                                                          # heal
```

Every toxic type and its attributes:
[Toxiproxy README](https://github.com/Shopify/toxiproxy#toxics). The API is
unauthenticated and published on `127.0.0.1` only; do not publish it further.

## How the lab is verified

`scripts/verify-chaos-overlay.sh` checks `docker compose config --quiet` for every
combination of the full and lightweight profiles with the chaos, tracing and
monitoring overlays, then starts lightweight + chaos with the published images
in its own Compose project and ports (so it runs beside your stack), runs every
scenario with an assertion a student could make with curl (the warehouse 503,
a delayed or failing link, a database health check going DOWN, the feed cursor
standing still during a partition, the payment outbox growing and draining,
the `backend-to-warehouse` link refusing and delaying), heals and checks
recovery, adds and removes the tracing overlay and tears the stack down with
`scripts/chaos down`. With backend 3.22.0+ it also runs Exercise 7 (checkout
and adjust 503, reads and cart 200, stock deducted once after `heal`) and
Exercise 8 (`stock_outbox_pending` grows, the projection catches up) and the
slow variant of Exercise 7 (`warehouse-slow 7000`: a 503 at the 5 s read
timeout, an orphaned reservation, the reaper releasing it and the stock coming
back); set `CHAOS_VERIFY_STOCK_LEDGER=true` to force them for a candidate image
without a version tag. With backend 3.22.2+ it also runs Exercise 9 (a cart
lock stalls the order save past the reservation timeout; the reservation ends
`CONFIRMED` and the stock is deducted once); `CHAOS_VERIFY_RESERVATION_CLAIMS`
forces or skips it. The run shortens the reaper
(`WAREHOUSE_RESERVATION_CONFIRM_TIMEOUT=PT20S`, interval `PT5S`) and checks
that `scripts/chaos up` prints the gateway's real address.

`scripts/verify-event-broker.sh` does the same for the broker transport:
`docker compose config` for the broker overlay combinations and the transport
of every profile, then lightweight + broker + chaos in its own project
(`broker-verify`), the declared queues with one consumer each, Exercise 10 (the
stock restore and the card refund through Artemis, feed cursors still),
Exercise 11 (five rollbacks, the DLQ, redrive and purge), Exercise 12 (a stopped
consumer's backlog in its queue), Exercise 13 (`events_relay_pending` grows
under `broker-down backend` while checkout works, and drains) and a consumer
reconnecting after `broker-down payment`.
