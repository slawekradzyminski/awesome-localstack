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
| Repository | `/Users/slawek/IdeaProjects/warehouse-service` (new, sibling of the other repos) |
| Stack | Spring Boot 4 / Java 25, same conventions as the backend (Lombok, springdoc, `CustomException`-style errors with `ErrorDto {message}`) |
| Image | GraalVM native image (Spring AOT), target RSS ≤ 120 MB |
| Port | 4003 |
| Database | Postgres schema `warehouse` in the existing database (`spring.flyway.schemas=warehouse`, `currentSchema=warehouse`); H2 in-memory for the `local` profile and tests |
| Profiles | `local` (H2, backend at `http://localhost:4001`), `docker` (Postgres, backend at `http://backend:4001`) |
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
exposes it at `/warehouse/v3/api-docs`.

### Authentication

warehouse-service validates the backend's access tokens itself:

- HMAC-SHA JWT signed with `JWT_SECRET_KEY` (same variable and same
  short-key expansion as `JwtTokenProvider.init()` in the backend).
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
| `GET /internal/v1/orders?status=PAID&fulfilment=NONE&page=&size=` | Fulfilment queue, oldest first | `PageDto<InternalOrderDto>` |
| `PUT /internal/v1/orders/{id}/fulfilment` | Mirror the shipment state onto the order | `InternalOrderDto`; 409 when the transition is not allowed |
| `POST /internal/v1/orders/{id}/warehouse-cancel` | Cancel an order whose shipment the warehouse cancels | `InternalOrderDto`; 409 unless the order is `PAID` and `fulfilmentState` is `AWAITING_PICK` or `PICKED` |
| `GET /internal/v1/products?ids=1,2` (or no `ids` for all) | Product snapshots | `List<InternalProductDto>` |
| `POST /internal/v1/inventory/receipts` | Add stock for a purchase receipt or a resellable return | `{movementIds: [..]}`; idempotent per `requestId` |
| `POST /internal/v1/notifications` | Email a customer | 202 |

```text
InternalOrderDto { id, username, status, fulfilmentState, subtotalAmount,
                   discountAmount, totalAmount, couponCode,
                   shippingAddress {street, city, state, zipCode, country},
                   items [{productId, productName, category, quantity, unitPrice}],
                   createdAt, updatedAt }

PUT fulfilment body   { state: AWAITING_PICK|PICKED|PACKED|SHIPPED|DELIVERED|CANCELLED }
InternalProductDto    { id, name, category, price, stockQuantity }
receipts body         { requestId: UUID, type: PURCHASE_RECEIVED|RETURN_RESTOCKED,
                        orderId?: Long, reference: String,
                        lines: [{productId, quantity}] }
notifications body    { username, template: ORDER_SHIPPED|ORDER_DELIVERED|RETURN_UPDATED,
                        subject, message, properties: {string: string} }
```

### Fulfilment state on the backend

The backend stores `orders.fulfilment_state`
(`NONE`, `AWAITING_PICK`, `PICKED`, `PACKED`, `SHIPPED`, `DELIVERED`, `CANCELLED`;
default `NONE`) instead of a shipments table. The `PUT .../fulfilment` rules:

- `NONE → AWAITING_PICK` only for `PAID` orders (409 otherwise or if already set).
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
| Create shipment | `GET order` (must be `PAID`, `fulfilmentState=NONE`), save shipment, `PUT fulfilment AWAITING_PICK`; on failure delete the local shipment |
| Pick / pack | `PUT fulfilment PICKED` / `PACKED` after the local transition is validated |
| Ship / deliver | `PUT fulfilment SHIPPED` / `DELIVERED`, then `POST notifications` (`ORDER_SHIPPED` / `ORDER_DELIVERED`) |
| Cancel shipment | `POST warehouse-cancel`; then mark the shipment `CANCELLED` |
| Request return | `GET order` for ownership, status `DELIVERED`, items, totals |
| Receive return | `POST inventory/receipts` (`RETURN_RESTOCKED`, `requestId` = deterministic UUID from the return id) for resellable lines |
| Approve / reject / refund | `POST notifications` (`RETURN_UPDATED`) |
| Receive purchase order | `POST inventory/receipts` (`PURCHASE_RECEIVED`, the receipt's `requestId`) |
| Reorder suggestions | `GET products` (all) plus local open purchase-order lines |
| Queue | `GET orders?status=PAID&fulfilment=NONE` |

The order of local and remote writes is chosen so that a failed remote call
leaves no orphaned local state: validate locally, call the backend, then
persist. The backend calls are idempotent where a retry could repeat them
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
  `mem_limit: 160m`, healthcheck on `/actuator/health`, env `JWT_SECRET_KEY`,
  `WAREHOUSE_SERVICE_TOKEN`, `BACKEND_BASE_URL`, datasource settings.
- Backend gets `WAREHOUSE_SERVICE_TOKEN`.
- Gateway locations for the public paths above, placed before the generic
  `/api/v1/` location, plus `/warehouse/v3/api-docs`.
