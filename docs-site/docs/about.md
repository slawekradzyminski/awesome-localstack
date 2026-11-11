# How to read this wiki

## Sections

| Section | What it answers |
| --- | --- |
| [Architecture](architecture/index.md) | Which containers exist, which ports they use, how a request is routed, how users and services authenticate |
| [Business flows](flows/index.md) | What happens, step by step, when a customer signs up, shops, pays, gets a parcel or returns it; the exact endpoints and rules |
| [Operations](operations/index.md) | How to run, deploy, observe, back up and debug the stack |
| [For testers](testers/index.md) | Ready-made test ideas per feature |
| [Glossary](glossary.md) | Short definitions of the domain and infrastructure terms |
| [Reference](reference/index.md) | The repository's own `docs/*.md` documents, published unchanged |

## Sources of truth

The wiki is written from the real code and configuration. When the wiki and a
source disagree, the source wins:

| Topic | Source |
| --- | --- |
| Compose services, ports, memory limits | `lightweight-docker-compose.yml`, `docker-compose.yml`, `docker-compose.server.yml` in `awesome-localstack` |
| Gateway routes | `nginx/conf.d/lightweight-app-gateway.conf` (local) and `nginx/conf.d/app-gateway.conf` (server) |
| Deployment | `ansible/` and [Ansible](reference/ANSIBLE.md) |
| Backend rules | `test-secure-backend/docs/COMMERCE_AND_FULFILMENT.md`, `WEBHOOKS.md`, `PRODUCT_SEARCH.md` and the OpenAPI document |
| warehouse-service rules | `warehouse-service/README.md` and [the contract](reference/WAREHOUSE_SERVICE_CONTRACT.md) |
| payment-service rules | `payment-service/README.md` and [the contract](reference/PAYMENT_SERVICE_CONTRACT.md) |
| Live API shape | The OpenAPI documents in [Swagger UI](operations/api-explorers.md) |

## Conventions

- Paths such as `POST /api/v1/orders` are **gateway paths**: send them to
  `http://localhost:8081` locally or to the public host.
- `/internal/v1/...` paths are **service-to-service only**. The gateway answers
  `404` for `/internal/` on every host.
- Money is `BigDecimal` with scale 2, rounded half-up. The base currency is
  USD.
- Diagrams are Mermaid; they render in light and dark mode. Use the search box
  (++slash++ or ++s++) to jump to an endpoint or term.
