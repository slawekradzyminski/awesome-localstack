# Services and ports

"Internal" means the port is reachable only on the Compose network
(`my-private-ntwk`); "host" ports are published on your machine.

## Application services

| Service | Image | Port | What it does |
| --- | --- | --- | --- |
| `gateway` | `nginx:1.31.3-trixie` | host `8081` (local), `127.0.0.1:8080` (server) | Single entry point. Serves `/images/` and `/branding/` itself, proxies everything else; see [Gateway routing](gateway.md) |
| `edge` | `nginx:1.31.3-trixie` | host network `:80` (server only) | Receives traffic from the hosting provider's HTTPS proxy, trusts `X-Forwarded-For` only from that provider's range, forwards to the gateway |
| `frontend` | `slawekradzyminski/frontend` | internal `80` | React single-page app (shop, admin, warehouse, LLM, traffic monitor) served by nginx |
| `backend` | `slawekradzyminski/backend` | internal `4001`; gRPC `9091` on host loopback when enabled | Spring Boot (GraalVM native). Users and JWT issuance, products, inventory, cart, coupons, gift cards, loyalty, VAT, currencies, orders, reviews, wishlist, emails, webhooks, LLM proxy, GraphQL, gRPC, traffic monitor |
| `warehouse-service` | `slawekradzyminski/warehouse-service` | internal `4003` | Shipments (pick, pack, ship, deliver), simulated carrier tracking, returns (RMA), suppliers, purchase orders, reorder suggestions; cancels shipments from the backend's event feed |
| `payment-service` | `slawekradzyminski/payment-service` | internal `4004` | Fake card provider: test cards, 3-D Secure, asynchronous settlement, signed result notifications, card refunds read from the backend's event feed |
| `docs` | built locally from `docs-site/` | internal `80` | This wiki, served at `/docs/` through the gateway |
| `consumer` | `slawekradzyminski/consumer` | host `4002` (full), internal (server) | JMS email consumer: reads the `email` queue and delivers the already rendered email over SMTP |

## Infrastructure services

| Service | Image | Port | Profiles | What it does |
| --- | --- | --- | --- | --- |
| `postgres` | `postgres:16.14-bookworm` | host `5432` (full), internal (lightweight, server) | all | Database `testdb`; schemas `public` (backend), `warehouse`, `payment` |
| `postgres-roles` | `postgres:16.14-bookworm` | — | all | One-shot: creates or updates the `warehouse` and `payment` roles before those services start (`postgres/service-roles.sh`) |
| `activemq` | `apache/artemis:2.55.0` | host `61616`, `8161`, `5672` (full), internal (server) | full, server | Message broker for outgoing emails (queue `email`) |
| `mailpit` | `axllent/mailpit:v1.30.0` | host `8025` UI, `1025` SMTP (full); `127.0.0.1:8025` (server) | full, server | Fake SMTP inbox |
| `keycloak` | `quay.io/keycloak/keycloak:26.7.0` | host `8082` | lightweight, full | OIDC identity provider for the SSO and social-login exercises |
| `keycloak-init` | `curlimages/curl` | — | lightweight, full | One-shot: sets the mock social-login users' passwords |
| `ollama-mock` | `slawekradzyminski/ollama-mock` | host `11434` (lightweight), internal (server) | lightweight, server, model-mock override | Deterministic Ollama-compatible LLM mock |
| `ollama-dmr-adapter` | built locally | internal `11434` | full | Adapter in front of Docker Model Runner (the real local model) |
| `prometheus` | `prom/prometheus:v3.13.2` | host `9090` (monitoring overlay), `127.0.0.1:9090` (server) | monitoring overlay, server | Metrics; production keeps 30 days / 5 GB |
| `grafana` | `grafana/grafana:13.1.1` | host `3000` | monitoring overlay | Dashboards (k6, Spring, container resources); not in production |
| `influxdb` | `influxdb:1.12.4` | host `8086` | monitoring overlay | k6 load-test results |
| `node-exporter`, `cadvisor` | Prometheus ecosystem | internal | monitoring overlay, server | Host and container metrics |
| `blackbox-exporter`, `alertmanager` | Prometheus ecosystem | internal | server | Public HTTPS probes, Telegram alerts |

## The aitesters sandbox (server profile)

The server runs a second, fully separate copy of the application for
`aitesters.byst.re`: `aitesters-backend`, `aitesters-frontend`,
`aitesters-warehouse-service`, `aitesters-payment-service` and
`aitesters-postgres` (with its own `aitesters-postgres-roles` one-shot). It has
its own signing key, service tokens, webhook secret and database, so a token
from one site never works on the other. A systemd timer recreates the sandbox
from a fresh database volume every night.

## Memory limits on the server

The VPS has about 4.25 GiB of RAM and no swap. Limits are safety ceilings and
are deliberately overcommitted (see [Ansible: memory budget](../reference/ANSIBLE.md#memory-budget)).

| Service | `mem_limit` | Heap / notes |
| --- | --- | --- |
| backend | 640m | native, `-Xmx384m` |
| aitesters-backend | 448m | native, `-Xmx256m` |
| warehouse-service, aitesters-warehouse-service | 160m each | native, `-Xmx64m` |
| payment-service, aitesters-payment-service | 160m each | native, `-Xmx64m` |
| consumer | 160m | native, `-Xmx64m` |
| postgres / aitesters-postgres | 512m / 160m | |
| activemq | 768m | JVM |
| ollama-mock | 512m | JVM |
| prometheus | 512m | (Grafana's 640m left production in lean phase A) |
| gateway / edge | 128m each | |
| frontend / aitesters-frontend | 64m each | |
| docs | 32m | nginx, one worker |
| cadvisor / alertmanager / node-exporter / blackbox / mailpit | 256m / 128m / 64m / 64m / 64m | |
