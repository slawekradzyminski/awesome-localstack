# Gateway routing

The gateway is nginx. Two configuration files exist:

- `nginx/conf.d/lightweight-app-gateway.conf` — one `server` block for
  `localhost`, used by the lightweight, full and compatibility profiles;
  forwards `X-Forwarded-Proto: http`.
- `nginx/conf.d/app-gateway.conf` — the server profile, with one `server`
  block per host: `awesome.byst.re` and `aitesters.byst.re`
  (`aitesters.awesome.byst.re`). Forwards `X-Forwarded-Proto: https` and
  `X-Forwarded-Port: 443`, because TLS ends at the hosting provider's proxy.

## How nginx picks a location

nginx chooses an **exact** match (`location = /x`) first, then the **longest
prefix**; a prefix marked `^~` stops the search, otherwise **regex** locations
(`~`) are tried in order and the first match beats the prefix. That is why the
warehouse, payment and notification paths, which are longer prefixes or regexes, win over
the generic `/api/v1/` route to the backend.

## Route table

| Path | Match | Upstream | Notes |
| --- | --- | --- | --- |
| `/api/v1/ws-traffic` | prefix | backend | WebSocket upgrade for the traffic monitor |
| `/api/v1/warehouse/` | prefix | warehouse-service | Queue, shipments, pick list, transitions, carrier advance |
| `= /api/v1/returns`, `/api/v1/returns/` | exact + prefix | warehouse-service | Customer returns |
| `= /api/v1/admin/returns`, `/api/v1/admin/returns/` | exact + prefix | warehouse-service | Return administration |
| `= /api/v1/admin/suppliers`, `/api/v1/admin/suppliers/` | exact + prefix | warehouse-service | Suppliers |
| `= /api/v1/admin/purchase-orders`, `/api/v1/admin/purchase-orders/` | exact + prefix | warehouse-service | Purchase orders and receipts |
| `= /api/v1/admin/inventory/reorder-suggestions` | exact | warehouse-service | Other `/api/v1/admin/inventory` paths stay on the backend |
| <code>~ ^/api/v1/orders/\d+/(shipment&#124;shipments&#124;shipment/tracking&#124;returns)$</code> | regex | warehouse-service | Order shipment (first parcel), every parcel, tracking and return creation |
| `/api/v1/tracking/` | prefix | warehouse-service | Public parcel tracking, no token |
| `^~ /warehouse/v3/api-docs` | prefix, stops search | warehouse-service `/v3/api-docs` | Rewritten; `/warehouse` itself stays a frontend page |
| `= /api/v1/payments`, `/api/v1/payments/` | exact + prefix | payment-service | Create, 3-D Secure, read |
| `= /api/v1/admin/payments` | exact | payment-service | Admin payment list |
| `~ ^/api/v1/orders/\d+/payments$` | regex | payment-service | Payments of one order |
| `^~ /payment/v3/api-docs` | prefix, stops search | payment-service `/v3/api-docs` | Rewritten |
| `= /api/v1/webhooks`, `/api/v1/webhooks/` | exact + prefix | notification-service | User webhook subscriptions and deliveries |
| `= /api/v1/webhook-inboxes`, `/api/v1/webhook-inboxes/` | exact + prefix | notification-service | Built-in webhook inboxes |
| `= /api/v1/admin/webhooks` | exact | notification-service | Every subscription (admin) |
| `/api/v1/notifications/` | prefix | notification-service | Commerce email log (`/emails`) |
| `/api/v1/local/notifications/` | prefix | notification-service | Local notification outbox; the backend's `/api/v1/local/email/outbox` stays on the backend |
| `^~ /notification/v3/api-docs` | prefix, stops search | notification-service `/v3/api-docs` | Rewritten |
| `/internal/` | prefix | — | Always `404`: the service-to-service API is never public |
| `/api/v1/` | prefix | backend | Everything else under the API, including GraphQL (`/api/v1/graphql`) and GraphiQL |
| `= /api`, `/api/` | exact + prefix | — | Any other `/api` path (e.g. `/api/v2/users`): `404` JSON `{"message":"Not found"}`, never the SPA |
| `/swagger-ui/`, `/v3/api-docs` | prefix | backend | Swagger UI and the backend OpenAPI document |
| `/actuator/` | prefix | backend (local) | Server: only `= /actuator/health` is proxied, the rest is `404` |
| `/images/`, `/branding/` | prefix | gateway filesystem | Product images and logos served by nginx itself |
| `/mailpit/...`, `/mailhog/...` | exact + prefix | — | Server only: always `404` so the inbox never leaks |
| `= /docs`, `/docs/` | exact + prefix | docs | This wiki; `/docs` redirects to `/docs/` |
| `/` | prefix | frontend | The SPA; unknown non-API paths are handled by the client-side router |

On the server, the `aitesters.byst.re` block routes the same paths to the
`aitesters-*` services. Both hosts serve the same `docs` container.

## Starting without optional services

warehouse-, payment-, notification-service and docs are addressed through **variables**
resolved at request time by Docker's DNS (`resolver 127.0.0.11`):

```nginx
set $warehouse_upstream http://warehouse-service:4003;
set $payment_upstream   http://payment-service:4004;
set $notification_upstream http://notification-service:4005;
set $docs_upstream      http://docs:80;

location /api/v1/payments/ {
  proxy_pass $payment_upstream;
  ...
}
```

With a literal hostname, nginx refuses to start when the name does not
resolve. With a variable, the gateway (and therefore the shop and backend API)
starts even when one of these services is absent or restarting; only its paths
answer `502 Bad Gateway` until it is back. The backend and frontend are literal
upstreams: the gateway waits for a healthy backend.

## What a failure looks like

Example request: `GET /api/v1/orders/42/shipment` (served by warehouse-service,
which asks the backend for the order).

| What is down | Who answers | Response |
| --- | --- | --- |
| Nothing | warehouse-service | `200` with the shipment |
| warehouse-service | the gateway (no upstream) | `502 Bad Gateway` |
| backend | warehouse-service (cannot read the order) | `503 {"message":"Backend unavailable"}` |
| backend and the request is a backend path, e.g. `/api/v1/orders` | the gateway | `502 Bad Gateway` |

## Proxy headers

Every proxied location sets `Host`, `X-Real-IP`, `X-Forwarded-For`,
`X-Forwarded-Host`, `X-Forwarded-Port`, `X-Forwarded-Proto`, and the
correlation headers `X-Request-Id` and `traceparent` (below). The Spring
services run with `SERVER_FORWARD_HEADERS_STRATEGY=framework`, so redirects,
generated links and the OpenAPI `servers` URL use the public scheme and host.
Swagger UI's "Try it out" therefore calls `https://awesome.byst.re` in
production and `http://localhost:8081` locally.

## Correlation ids

Every server block (both hosts on the server, `localhost` locally, and the
edge) validates or generates `X-Request-Id` and `traceparent` with nginx `map`
blocks, passes both to every proxied location, returns `X-Request-Id` on every
response (also on the gateway's own `404`s) and logs one JSON line per request:

```nginx
map $http_x_request_id $corr_request_id {
  "~^[A-Za-z0-9._-]{1,128}$" $http_x_request_id;
  default $request_id;
}
map $http_traceparent $corr_traceparent {
  "~^00-(?!0{32})[0-9a-f]{32}-(?!0{16})[0-9a-f]{16}-[0-9a-f]{2}$" $http_traceparent;
  default $corr_generated_traceparent;   # 00-$request_id-<last 16 hex>-01
}
```

A location that sets any `proxy_set_header` does not inherit the server's, so
each proxied location sets both headers itself; the contract script
`scripts/verify-correlation-ids.py` fails when one is missing. The upstream's
own `X-Request-Id` is hidden so the client receives the header once. See
[Tracing a request](../operations/tracing.md).

## Edge proxy

On the server, the **edge** proxy trusts `X-Forwarded-For` only from the
hosting provider's proxy range (`set_real_ip_from 2a01:4f9::/32`), so a client
cannot spoof the address used by rate limiting. See
[Production edge proxy](../reference/PRODUCTION_EDGE_PROXY.md).
