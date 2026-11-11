# API explorers

## Swagger UI

`/swagger-ui/index.html` on any gateway (`http://localhost:8081`,
`https://awesome.byst.re`, `https://aitesters.byst.re`). The definition
dropdown has four entries:

| Definition | Document | Served by |
| --- | --- | --- |
| backend (JSON) | `/v3/api-docs` | backend |
| backend (YAML) | `/v3/api-docs.yaml` | backend |
| Warehouse service | `/warehouse/v3/api-docs` | warehouse-service, rewritten by the gateway |
| Payment service | `/payment/v3/api-docs` | payment-service, rewritten by the gateway |

The warehouse and payment entries load only through the gateway; on the
backend's own port they are `404`.

To call protected operations: run `POST /api/v1/users/signin`, copy `token`,
click **Authorize** and paste it. Warehouse and payment operations use the
same token, but Swagger UI keeps authorisation per definition — authorise
again after switching. Each document's `servers` URL follows the gateway's
`X-Forwarded-*` headers, so "Try it out" calls the public origin.

The internal APIs (`/internal/v1/...`) are deliberately absent from every
OpenAPI document.

## GraphQL

`POST /api/v1/graphql` with the normal bearer token; GraphiQL at
`/api/v1/graphiql` (enter `Authorization: Bearer <token>` in the Headers tab).
Covers products, carts, orders and inventory. Order enums are the same as in
REST.

## Native gRPC

The inventory gRPC service listens on port 9091 inside the backend. It is
published only on host loopback: locally with `docker-compose.grpc.yml`
(`127.0.0.1:9091`), on the server as `127.0.0.1:9091` (stable) and
`127.0.0.1:9092` (sandbox), reached through an SSH tunnel. Reflection is off;
health requires an admin JWT. See [gRPC inventory](../reference/GRPC_INVENTORY.md)
and the [protocol testing lab](../reference/PROTOCOL_TESTING_LAB.md).

## Traffic monitor

The frontend's `/traffic` page subscribes to `/api/v1/ws-traffic`
(WebSocket) and shows the backend's HTTP, GraphQL and gRPC traffic summaries
for your session; `GET /api/v1/traffic/logs` and
`/api/v1/traffic/logs/{correlationId}` return the stored entries.
