# Warehouse service contract

`warehouse-service` owns warehouse fulfilment: shipments, returns (RMA),
suppliers and purchase orders. The backend (`test-secure-backend`) keeps users,
JWT issuance, products, stock, cart, coupons, reviews, wishlist and orders.
This document is the boundary both sides implement. Business rules are the ones
already specified in `test-secure-backend/docs/COMMERCE_AND_FULFILMENT.md`
(Tier 2 section); only their location changes.

## Runtime

| Item | Value |
| --- | --- |
| Repository | [slawekradzyminski/warehouse-service](https://github.com/slawekradzyminski/warehouse-service) |
| Stack | Spring Boot 4 / Java 25, same conventions as the backend (Lombok, springdoc, `CustomException`-style errors with `ErrorDto {message}`) |
| Image | GraalVM native image (Spring AOT), about 40–60 MiB RSS measured |
| Port | 4003 |
| Database | Postgres schema `warehouse` in the existing database (`spring.flyway.schemas=warehouse`, `currentSchema=warehouse`); H2 only in the JVM unit tests |
| Profiles | `local` (Postgres `localhost:5432/testdb`, backend at `http://localhost:4001`, demo suppliers), `docker` (Postgres, backend at `http://backend:4001`), `demo` (seeds demo suppliers) |
| Deployed in | lightweight, full and server Compose profiles |

Native-image rules: no runtime classpath scanning tricks, no CGLIB-only
features, no reflection without hints, no Testcontainers in the default test
run. Prefer constructor injection, records for DTOs, `RestClient` for HTTP.

## Public API (unchanged paths)

The gateway routes these paths to warehouse-service; request and response
bodies stay exactly as in backend PR #85, so the frontend keeps its calls.

- `/api/v1/warehouse/**` (queue, shipments, pick list, pick/pack/ship/deliver/cancel)
- `GET /api/v1/orders/{id}/shipment`
- `POST /api/v1/orders/{orderId}/returns`, `GET /api/v1/returns`, `GET /api/v1/returns/{id}`
- `/api/v1/admin/returns/**`
- `/api/v1/admin/suppliers`, `/api/v1/admin/purchase-orders/**`
- `GET /api/v1/admin/inventory/reorder-suggestions`

warehouse-service serves its OpenAPI at `/v3/api-docs` (port 4003); the gateway
exposes it at `/warehouse/v3/api-docs`, and the backend's Swagger UI lists it as
the "Warehouse service" definition. The document's server URL follows the
gateway's `X-Forwarded-*` headers (`SpringDocProxyConfig`, as in the backend),
so "Try it out" calls `https://awesome.byst.re` through the gateway.

### Authentication

warehouse-service validates the backend's access tokens itself:

- RS256 JWT signed by the backend (`JWT_SIGNING_KEY`). warehouse-service holds
  no signing material: it resolves the verification key by the token's `kid`
  from `GET /internal/v1/jwks.json`, caches it, and refetches the set when an
  unknown `kid` appears (at most once per 10 seconds). Tokens with another
  algorithm, no `kid` or an unknown `kid` are 401; a backend outage before the
  key is cached is 503.
- `sub` is the username; the `auth` claim carries the roles exactly as the
  backend writes them (`ROLE_ADMIN`, `ROLE_CLIENT`, `ROLE_WAREHOUSE`).
- No user lookup: the token is the source of truth. 401 for missing, expired
  or invalid tokens; 403 for wrong roles, with the backend's `ErrorDto` bodies.
- Role rules as in PR #85: warehouse endpoints for `ROLE_WAREHOUSE` or
  `ROLE_ADMIN`; admin returns, suppliers, purchase orders and reorder
  suggestions for `ROLE_ADMIN`; customer return and tracking endpoints for any
  authenticated user, scoped to their own orders (admins may track any order).

## Internal API (backend, called by warehouse-service)

Base path `/internal/v1`. Not routed by the gateway. Every request carries
`X-Service-Token: ${WAREHOUSE_SERVICE_TOKEN}`; the backend rejects missing or
wrong tokens with 401 and the endpoints are excluded from JWT auth, CORS,
traffic capture and the public OpenAPI document. When
`WAREHOUSE_SERVICE_TOKEN` is unset the internal API is disabled (404).

| Method and path | Purpose | Response |
| --- | --- | --- |
| `GET /internal/v1/orders/{id}` | Order snapshot | `InternalOrderDto` or 404 |
| `GET /internal/v1/orders?status=PAID&fulfilment=NONE&page=&size=` | Fulfilment queue, oldest first (also `fulfilment=AWAITING_PICK` for released orders) | `PageDto<InternalOrderDto>` |
| `GET /internal/v1/orders?ids=1,2` | Order snapshots in any status, at most 100 | `List<InternalOrderDto>` |
| `PUT /internal/v1/orders/{id}/fulfilment` | Mirror the shipment state onto the order | `InternalOrderDto`; repeating the current state is a no-op; 409 when the transition is not allowed |
| `POST /internal/v1/orders/{id}/refunds` | Book the refund of a return | `InternalOrderDto`; idempotent per `requestId`; 409 unless `DELIVERED` or when refunds would exceed the total |
| `POST /internal/v1/orders/{id}/warehouse-cancel` | Cancel an order whose shipment the warehouse cancels | `InternalOrderDto`; 409 unless the order is `PAID` and `fulfilmentState` is `AWAITING_PICK` or `PICKED` |
| `GET /internal/v1/products?ids=1,2` (or no `ids` for all) | Product snapshots | `List<InternalProductDto>` |
| `POST /internal/v1/inventory/receipts` | Add stock for a purchase receipt or a resellable return | `{movementIds: [..]}`; idempotent per `requestId` |
| `POST /internal/v1/notifications` | Email a customer; the backend renders the text | 202; a repeated `requestId` sends nothing |
| `GET /internal/v1/jwks.json` | Access-token verification keys | JSON Web Key Set |

```text
InternalOrderDto { id, username, status, fulfilmentState, subtotalAmount,
                   discountAmount, totalAmount, couponCode, refundedAmount,
                   shippingAddress {street, city, state, zipCode, country},
                   items [{productId, productName, category, quantity, unitPrice}],
                   createdAt, updatedAt }

PUT fulfilment body   { state: AWAITING_PICK|PICKED|PACKED|SHIPPED|DELIVERED|CANCELLED }
InternalProductDto    { id, name, category, price, stockQuantity }
receipts body         { requestId: UUID, type: PURCHASE_RECEIVED|RETURN_RESTOCKED,
                        orderId?: Long, reference: String,
                        lines: [{productId, quantity}] }
refunds body          { requestId: UUID, amount, reference }
notifications body    { requestId: UUID, username,
                        template: ORDER_SHIPPED|ORDER_DELIVERED|RETURN_UPDATED,
                        properties: {string: string} }
                      ORDER_SHIPPED: orderId, carrier, trackingNumber
                      ORDER_DELIVERED: orderId
                      RETURN_UPDATED: returnId, orderId, status, refundAmount?, note?
```

### Fulfilment state on the backend

The backend stores `orders.fulfilment_state`
(`NONE`, `AWAITING_PICK`, `PICKED`, `PACKED`, `SHIPPED`, `DELIVERED`, `CANCELLED`;
default `NONE`) instead of a shipments table. The `PUT .../fulfilment` rules:

- `NONE → AWAITING_PICK` only for `PAID` orders (409 otherwise). Repeating
  `AWAITING_PICK` (or any current state) is a no-op, so a retried release
  is safe.
- Forward steps only: `AWAITING_PICK → PICKED → PACKED → SHIPPED → DELIVERED`.
- `SHIPPED` sets order status `SHIPPED`; `DELIVERED` sets `DELIVERED`.
- `CANCELLED` is set only through `warehouse-cancel` or customer cancellation.

The customer and admin cancellation rules from PR #85 now read this column:
cancellation is allowed while `fulfilmentState` is `NONE` or `AWAITING_PICK`
(then the state becomes `CANCELLED`), and 409 from `PICKED` on; the legacy
admin status endpoint returns 409 while the state is `AWAITING_PICK` through
`SHIPPED`.

## Behaviour that crosses the boundary

| Action in warehouse-service | Backend calls, in order |
| --- | --- |
| Create shipment | `GET order` (must be `PAID`, `fulfilmentState` `NONE`, or `AWAITING_PICK` without a local shipment), save shipment, `PUT fulfilment AWAITING_PICK`; on 409 delete the local shipment; on 503 `GET order` again and keep the shipment if the order is `AWAITING_PICK` |
| Pick / pack | `PUT fulfilment PICKED` / `PACKED` after the local transition is validated |
| Ship / deliver | `PUT fulfilment SHIPPED` / `DELIVERED`, then an outbox notification (`ORDER_SHIPPED` / `ORDER_DELIVERED`) |
| Cancel shipment | `POST warehouse-cancel` (a 409 for an order that is already `CANCELLED` counts as done); then mark the shipment `CANCELLED` |
| Request return | `GET order` for ownership, status `DELIVERED`, items, totals |
| Receive return | `POST inventory/receipts` (`RETURN_RESTOCKED`, `requestId` = deterministic UUID from the return id) for resellable lines |
| Refund return | `POST orders/{id}/refunds` (`requestId` = deterministic UUID from the return id), then mark the return `REFUNDED` |
| Approve / reject / refund | Outbox notification (`RETURN_UPDATED`) |
| Reconcile (every minute) | `GET orders?ids=` for `AWAITING_PICK` shipments, cancelling those whose order is `CANCELLED`; `GET orders?status=PAID&fulfilment=AWAITING_PICK`, adopting orders older than two minutes that have no shipment |
| Receive purchase order | `POST inventory/receipts` (`PURCHASE_RECEIVED`, the receipt's `requestId`) |
| Reorder suggestions | `GET products` (all) plus local open purchase-order lines |
| Queue | `GET orders?status=PAID&fulfilment=NONE` |

The order of local and remote writes is chosen so that a failed remote call
leaves no orphaned local state: validate locally, call the backend, then
persist. Notifications are the exception: they are written to a
`notification_outbox` table in the same transaction as the change, sent right
after the commit and retried with backoff while the backend answers 503; the
backend drops repeated `requestId`s, so a retry never sends a second email. The backend calls are idempotent where a retry could repeat them
(`requestId`, forward-only fulfilment transitions). Backend 4xx responses are
mapped to the same status and message for the caller; backend unavailability
becomes 503 `{message: "Backend unavailable"}`.

## Backend changes (relative to PR #85)

- Remove shipments, returns, suppliers, purchase orders, their controllers,
  services, repositories, DTOs, tests and tables (rewrite V7, which is not
  released yet).
- Keep `ROLE_WAREHOUSE`, the `warehouse` demo user, inventory movement types
  `PURCHASE_RECEIVED` and `RETURN_RESTOCKED`, `InventoryService.receive`, the
  email templates and the notification listener (now fed by the internal
  notifications endpoint).
- Add `orders.fulfilment_state` and the internal API above.

## Frontend changes

- Paths are unchanged behind the gateway. For direct-to-backend development
  add `VITE_WAREHOUSE_API_BASE_URL` (defaults to the API base URL) and send
  warehouse paths there.
- Add a second OpenAPI snapshot `openapi/warehouse-api-docs.json` with generated
  types, and point `src/types/commerce.ts` warehouse aliases at it.

## localstack changes

- New `warehouse-service` service in lightweight, full and server profiles,
  `mem_limit: 160m`, healthcheck on `/actuator/health`, env
  `WAREHOUSE_SERVICE_TOKEN`, `BACKEND_BASE_URL`, datasource settings for the
  `warehouse` role, after the one-shot `postgres-roles` service.
- Backend gets `WAREHOUSE_SERVICE_TOKEN`.
- Gateway locations for the public paths above, placed before the generic
  `/api/v1/` location, plus `/warehouse/v3/api-docs`.
- The aitesters sandbox runs its own `aitesters-warehouse-service` (same
  image, 160m) paired with `aitesters-backend`. It verifies the sandbox JWT key,
  uses its own `aitesters_warehouse_service_token`, and stores data in the
  `warehouse` schema of `aitesters-postgres` (160m), the sandbox backend's
  database. The nightly `aitesters-reset` unit recreates all three with a fresh
  database volume. The aitesters gateway block routes the same public paths to
  it and keeps `/internal/` at 404.
- The consumer runs the GraalVM native image (3.5.0+): `command: ["-Xmx64m"]`,
  `mem_limit: 160m`, no JVM blocklist mount (the blocklist is baked in at build
  time and the distroless runtime has no JDK).

## Addendum: shipment tracking (warehouse-service 1.2.0)

warehouse-service 1.2.0 simulates a parcel carrier (Flyway V3 adds
`shipments.simulated` and `tracking_events`).

- `ShipShipmentDto.trackingNumber` is optional. Omitted, the shipment uses the
  simulated carrier and gets a generated tracking number that matches the
  carrier's format (`simulated = true`); supplied, the manual flow is unchanged.
- Tracking statuses: `LABEL_CREATED`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`,
  `DELIVERY_FAILED`, `DELIVERED`.
- A scheduler (`warehouse.carrier.enabled`, default `true`;
  `warehouse.carrier.step-interval`, default `PT2M`, environment
  `WAREHOUSE_CARRIER_STEP_INTERVAL`) moves every simulated `SHIPPED` shipment
  one step per interval. Deterministic failure: when
  `abs(trackingNumber.hashCode()) % 5 == 0` the first `OUT_FOR_DELIVERY` attempt
  becomes `DELIVERY_FAILED` and the next step tries again. `DELIVERED` reuses
  the existing deliver path (backend mirror plus the `ORDER_DELIVERED` email).
- New outbox templates `SHIPMENT_OUT_FOR_DELIVERY` and
  `SHIPMENT_DELIVERY_FAILED` (properties `orderId`, `carrier`, `trackingNumber`);
  backend 3.15.0 adds them to its allowlist and renderer.

| Method and path | Access | Result |
| --- | --- | --- |
| `GET /api/v1/orders/{id}/shipment/tracking` | owner or `ROLE_ADMIN` | `TrackingDto` |
| `GET /api/v1/tracking/{trackingNumber}` | public, no token | `TrackingDto` without `orderId`; 404 for an unknown number |
| `POST /api/v1/warehouse/shipments/{id}/carrier/advance` | `ROLE_WAREHOUSE` or `ROLE_ADMIN` | one step forward; 409 unless a simulated `SHIPPED` shipment |

```text
TrackingDto { shipmentId, orderId, carrier, trackingNumber, simulated,
              currentStatus, estimatedDelivery,
              events [{status, location, description, occurredAt}] }
```

Gateway changes (every application gateway server block): the order regex
becomes `~ ^/api/v1/orders/\d+/(shipment|shipment/tracking|returns)$` and the
new prefix `/api/v1/tracking/` goes to warehouse-service. Deployment verifies
that `/api/v1/tracking/<unknown>` answers 404 through the gateway (the backend
would answer 401 without a token). The default two-minute step interval is
used in every profile; trainers use the `carrier/advance` endpoint to skip
ahead.
