# Commerce training features

The shop has two layers of training features, both live on every profile and
on `awesome.byst.re` and `aitesters.byst.re` (current images:
[CONTAINER_RELEASES.md](CONTAINER_RELEASES.md#current-compatibility-set)):

1. **Shop features in the backend.** Coupons, reviews, wishlist, product CSV,
   idempotent checkout, conditional product updates, and the `warehouse` demo
   user with `ROLE_WAREHOUSE`.
2. **Warehouse fulfilment, returns and purchasing in `warehouse-service`.**
   Shipments and the pick/pack/ship/deliver workflow, returns (RMA), suppliers,
   purchase orders and reorder suggestions, served by a separate GraalVM native
   service (see [below](#warehouse-service)).

The backend design and every business rule are documented in
[`test-secure-backend/docs/COMMERCE_AND_FULFILMENT.md`](https://github.com/slawekradzyminski/test-secure-backend/blob/master/docs/COMMERCE_AND_FULFILMENT.md).

## What students can test

| Area | Screens | API | Good exercises |
| --- | --- | --- | --- |
| Coupons | Cart coupon panel, checkout summary, `/admin/coupons` | `PUT/DELETE /api/v1/cart/coupon`, `/api/v1/admin/coupons` | Boundary values (minimum subtotal, validity window, usage limits), decision tables, a coupon that stops qualifying between cart and checkout |
| Reviews | Product page reviews, `/admin/reviews` | `/api/v1/products/{id}/reviews`, `/api/v1/admin/reviews` | Eligibility (only after delivery), moderation states, average rounding |
| Wishlist | Product page toggle, `/wishlist` | `/api/v1/wishlist` | Create vs update status codes (201/200), back-in-stock email after a 0 → n stock change |
| Product CSV | `/admin/products` CSV panel | `/api/v1/admin/products/export`, `/api/v1/admin/products/import` | File upload and download, all-or-nothing validation, dry run, CSV formula injection |
| Idempotent checkout | Checkout | `POST /api/v1/orders` with `Idempotency-Key` | Safe retries, replay header, conflicting reuse, per-user scope |
| Conditional updates | Admin product form | `GET/PUT /api/v1/products/{id}` with `ETag`, `If-None-Match`, `If-Match` | 304, 412 lost-update protection |
| Warehouse role | Sign-in as `warehouse` | `POST /api/v1/users/signin` | Role claims in the access token; admin-only endpoints return 403 for the warehouse role |

A typical end-to-end scenario:

1. `client` adds products, applies `WELCOME10` and checks out with an
   `Idempotency-Key`, then retries the same request safely.
2. `admin` marks the order `PAID`, then `DELIVERED` through the existing
   status endpoint.
3. `client` reviews the product and adds an out-of-stock item to the wishlist.
4. `admin` moderates the review and restocks the wishlisted product; the
   back-in-stock email arrives.
5. `warehouse` picks, packs and ships the order; `client` follows the shipment
   and requests a return, which `admin` approves and refunds.

## Demo data

Profiles that seed demo data (`local` in the lightweight profile, `demo` in
the full profile) add:

- user `warehouse` / `warehouse` with `ROLE_WAREHOUSE`;
- coupons `WELCOME10` (10 % from 50.00), `SAVE50` (50.00 off from 300.00,
  100 uses), `EXPIRED20` (expired) and `SPRING25` (starts in a week).

warehouse-service seeds the demo suppliers "Nordic Electronics" and "Baltic
Gadgets" in the same profiles.

The server profile does not seed demo data.

## Compatibility

- Existing request bodies, paths, status codes and enum values are unchanged,
  including `OrderStatus`. New response fields are additive and new request
  headers are optional, so the AI Testers API course suite keeps passing.
- Database migration `V7` adds tables and widens existing check constraints;
  it does not rewrite existing rows except to backfill `orders.subtotal_amount`.
- Emails for the new events are rendered by the backend and published with the
  `GENERIC` template, so older JMS consumers keep working. The consumer release
  additionally maps unknown templates to `GENERIC` instead of failing.
- Browser CORS now allows `Idempotency-Key`, `If-Match` and `If-None-Match` and
  exposes `ETag`, `Idempotent-Replayed` and `Content-Disposition`; requests
  through the gateway are same-origin and unaffected.

## warehouse-service

`warehouse-service` hosts the Tier 2 features: shipments and the
pick/pack/ship/deliver workflow, returns (RMA) with proportional refunds,
suppliers, purchase orders and reorder suggestions. The backend keeps users,
JWT issuance, products, stock, cart, coupons, reviews, wishlist and orders, and
mirrors the shipment state in `orders.fulfilment_state`. The boundary is
specified in [WAREHOUSE_SERVICE_CONTRACT.md](WAREHOUSE_SERVICE_CONTRACT.md).

| Area | Screens | API (through the gateway) | Good exercises |
| --- | --- | --- | --- |
| Warehouse | `/warehouse` (warehouse or admin role) | `/api/v1/warehouse/**`, `GET /api/v1/orders/{id}/shipment` | State machine, carrier-specific tracking formats, role-based access, cancellation rules |
| Returns | Order page return form, `/returns`, `/admin/returns` | `/api/v1/orders/{id}/returns`, `/api/v1/returns`, `/api/v1/admin/returns` | 30-day window, returnable quantities, restocking, proportional refunds with coupons |
| Purchasing | `/admin/purchasing` | `/api/v1/admin/suppliers`, `/api/v1/admin/purchase-orders`, `/api/v1/admin/inventory/reorder-suggestions` | Partial receipts, over-receipt, receipt idempotency, reorder arithmetic |

Paths and bodies are unchanged for the frontend: the gateway routes them to
warehouse-service. Two services and a service-to-service call add exercises in
distributed failure: what a customer sees when warehouse-service is down (the
gateway returns 502) or when the backend is down (warehouse-service returns 503
`Backend unavailable`).

### Deployment

- **Profiles.** lightweight, full and server all run `warehouse-service` on
  internal port 4003 (never published on the host).
  - lightweight: `docker,demo` profiles, tmpfs PostgreSQL `testdb` shared with
    the backend (`?currentSchema=warehouse`);
  - full: `docker` profile, PostgreSQL `testdb` with
    `?currentSchema=warehouse`;
  - server: `docker` profile, same database and schema, `-Xmx64m` in
    `mem_limit: 160m` (GraalVM native image, about 40–60 MiB measured);
  - server sandbox: `aitesters-warehouse-service`, paired with
    `aitesters-backend` and using the `warehouse` schema of `aitesters-postgres`.
- **Secrets and database role.** The backend signs access tokens with RS256
  (`JWT_SIGNING_KEY`, a base64 PKCS#8 RSA key; local profiles leave it empty,
  so the backend generates an ephemeral key per start). warehouse-service holds
  no signing secret: it verifies tokens with the backend's
  `/internal/v1/jwks.json`. `WAREHOUSE_SERVICE_TOKEN` authenticates
  warehouse-service to the backend `/internal/v1` API. warehouse-service
  connects as its own `warehouse` database role, which owns only the
  `warehouse` schema; the one-shot `postgres-roles` service
  (`postgres/warehouse-role.sh`) creates or updates that role before every
  warehouse-service start (`WAREHOUSE_DB_PASSWORD`, default
  `local-warehouse-db-password` locally). The server takes the values from
  Ansible Vault (`jwt_signing_key`, `warehouse_service_token`,
  `warehouse_postgres_password` and their `aitesters_` counterparts).
- **Gateway.** Warehouse locations precede the generic `/api/v1/` route,
  `/warehouse/v3/api-docs` exposes the warehouse OpenAPI document, and
  `/internal/` returns 404. The upstream is resolved at request time, so the
  gateway still starts without warehouse-service. The `aitesters.byst.re`
  host routes the same paths to `aitesters-warehouse-service`.
- **Monitoring.** Prometheus scrapes `spring_warehouse_micrometer`; the server
  adds a `CriticalContainerMissing` rule and a public probe of
  `https://awesome.byst.re/warehouse/v3/api-docs`. The generic container memory
  alerts cover the 160 MiB limit.
- **Memory.** Container limits and measured usage are listed in
  [PRODUCTION_MONITORING_PLAN.md](PRODUCTION_MONITORING_PLAN.md).
- **Image.** Every profile pins a published `tag@sha256` reference; the server
  deployment refuses an unpinned image.
