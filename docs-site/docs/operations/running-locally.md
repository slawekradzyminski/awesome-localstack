# Running locally

Requirements: Docker Desktop (or Docker Engine with Compose v2). The full
profile's real LLM additionally needs Docker Model Runner
(`docker desktop enable model-runner`).

## Lightweight (recommended)

```bash
docker compose -f lightweight-docker-compose.yml up -d
docker compose -f lightweight-docker-compose.yml ps -a
```

Long-running containers should be `Up`; the one-shot `postgres-roles` shows
`Exited (0)`. Stop with
`docker compose -f lightweight-docker-compose.yml down`. Data lives in tmpfs
and is gone after the stack is recreated.

| URL | What |
| --- | --- |
| `http://localhost:8081/login` | The shop |
| `http://localhost:8081/docs/` | This wiki |
| `http://localhost:8081/swagger-ui/index.html` | Swagger UI (backend, warehouse and payment definitions) |
| `http://localhost:8081/v3/api-docs` | Backend OpenAPI |
| `http://localhost:8081/warehouse/v3/api-docs` | warehouse-service OpenAPI |
| `http://localhost:8081/payment/v3/api-docs` | payment-service OpenAPI |
| `http://localhost:8081/notification/v3/api-docs` | notification-service OpenAPI |
| `http://localhost:8081/api/v1/local/notifications/outbox` | Commerce emails (lightweight profile) |
| `http://localhost:8081/api/v1/graphiql` | GraphiQL |
| `http://localhost:8081/api/v1/tracking/{number}` | Public parcel tracking |
| `http://localhost:8081/api/v1/local/email/outbox` | Emails (local outbox, Bearer token required) |
| `http://localhost:11434/api/generate` | LLM mock |

## Full

```bash
docker compose up -d          # or ./run-docker-compose.sh, which waits for every endpoint
```

Adds, on top of the URLs above:

| URL | What |
| --- | --- |
| `http://localhost:8025/` | Mailpit inbox |
| `http://localhost:8161` | ActiveMQ Artemis console |
| `http://localhost:4002/actuator/prometheus` | Consumer metrics |
| `localhost:5432` | PostgreSQL `testdb`, `postgres` / `postgres` |

Refresh seeded data with `docker compose down -v && docker compose up -d`.

## Monitoring for k6 (opt-in, either profile)

```bash
docker compose -f lightweight-docker-compose.yml -f docker-compose.monitoring.yml up -d
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

`./run-docker-compose.sh` already adds the overlay to the full profile
(`WITH_MONITORING=false` skips it).

| URL | What |
| --- | --- |
| `http://localhost:9090/graph` | Prometheus |
| `http://localhost:3000/login` | Grafana (`admin` / `grafana`): k6, Spring and Container Resources dashboards |
| `localhost:8086` | InfluxDB `db0` (`k6 run --out influxdb=http://localhost:8086/db0`) |

Set `GRAFANA_PORT`, `PROMETHEUS_PORT` or `INFLUXDB_PORT` when a port is taken,
and stop with the same `-f` files and `down`.
Use `docker compose -f docker-compose.yml -f docker-compose.model-mock.yml up -d`
on machines without Docker Model Runner.

## Fault injection and tracing (opt-in, either profile)

| Command | What | URL |
| --- | --- | --- |
| `scripts/chaos up` (`make chaos-up`) | [Fault-injection lab](fault-injection.md): Toxiproxy between the services, `scripts/chaos <scenario>` | Toxiproxy API `http://127.0.0.1:8474` |
| `make tracing-up` | [Jaeger](tracing.md#jaeger-traces) with OTLP export from the Spring services | `http://127.0.0.1:16686` |

`scripts/chaos up lightweight tracing monitoring` starts all three overlays.

## Demo users

| Username | Password | Role | Where |
| --- | --- | --- | --- |
| `admin` | `LocalDemoAdmin123!` | admin | lightweight, full |
| `client` | `client` | client | lightweight, full |
| `client2` | `client2` | client | lightweight, full |
| `client3` | `client3` | client | lightweight, full |
| `warehouse` | `warehouse` | warehouse | lightweight, full |

Production has **no demo users**; sign up your own account. The sandbox
`aitesters.byst.re` is reseeded every night.

## Demo data

- Sample products in several categories, sample orders.
- Coupons `WELCOME10`, `SAVE50`, `EXPIRED20`, `SPRING25` (see [Cart](../flows/cart.md#coupons)).
- Suppliers "Nordic Electronics" and "Baltic Gadgets".
- Currencies USD, EUR, GBP, CHF, PLN and the VAT table (migrations, every profile).

## A first API session

```bash
TOKEN=$(curl -s http://localhost:8081/api/v1/users/signin \
  -H 'Content-Type: application/json' \
  -d '{"username":"client","password":"client"}' | jq -r .token)

curl -s "http://localhost:8081/api/v1/products/search?q=phone&sort=price_asc" \
  -H "Authorization: Bearer $TOKEN" | jq '.facets'
```

Continue with the [order journey](../flows/index.md#the-order-journey).

## Running services from source

Each application repository can run next to a local PostgreSQL on
`localhost:5432` with its `local` Spring profile (`./mvnw spring-boot:run
-Dspring-boot.run.profiles=local`): backend on 4001, warehouse-service on 4003
(token `local-warehouse-token`), payment-service on 4004 (token
`local-payment-token`, secret `local-payment-webhook-secret`), notification-service
on 4005 (token `local-notification-token`, needs backend 3.21.0).
