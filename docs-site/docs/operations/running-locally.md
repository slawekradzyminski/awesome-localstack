# Running locally

Requirements: Docker Desktop (or Docker Engine with Compose v2). The full
profile's real LLM additionally needs Docker Model Runner
(`docker desktop enable model-runner`).

## Lightweight (recommended)

```bash
docker compose -f lightweight-docker-compose.yml up -d
docker compose -f lightweight-docker-compose.yml ps -a
```

Long-running containers should be `Up`; the one-shots `postgres-roles` and
`keycloak-init` show `Exited (0)`. Stop with
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
| `http://localhost:8081/api/v1/graphiql` | GraphiQL |
| `http://localhost:8081/api/v1/tracking/{number}` | Public parcel tracking |
| `http://localhost:8081/api/v1/local/email/outbox` | Emails (local outbox, Bearer token required) |
| `http://localhost:8082/admin/` | Keycloak admin (`admin` / `admin`) |
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
| `http://localhost:9090/graph` | Prometheus |
| `http://localhost:3000/login` | Grafana (`admin` / `grafana`) |
| `http://localhost:4002/actuator/prometheus` | Consumer metrics |
| `localhost:5432` | PostgreSQL `testdb`, `postgres` / `postgres` |
| `localhost:8086` | InfluxDB (k6 results) |

Refresh seeded data with `docker compose down -v && docker compose up -d`.
Use `docker compose -f docker-compose.yml -f docker-compose.model-mock.yml up -d`
on machines without Docker Model Runner.

## Demo users

| Username | Password | Role | Where |
| --- | --- | --- | --- |
| `admin` | `LocalDemoAdmin123!` | admin | lightweight, full |
| `client` | `client` | client | lightweight, full |
| `client2` | `client2` | client | lightweight, full |
| `client3` | `client3` | client | lightweight, full |
| `warehouse` | `warehouse` | warehouse | lightweight, full |
| `sso-e2e-client` | `SsoClient123!` | client via Keycloak SSO | lightweight, full |
| `sso-admin` | `SsoAdmin123!` | admin via Keycloak SSO | lightweight, full |
| `google-user` | `GoogleUser123!` | mock Google social login | lightweight, full |
| `github-user` | `GitHubUser123!` | mock GitHub social login | lightweight, full |

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
`local-payment-token`, secret `local-payment-webhook-secret`).
