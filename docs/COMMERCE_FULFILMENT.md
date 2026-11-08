# Commerce training features

> **Status: wave 1 released** with backend 3.10.1, frontend 3.10.0 and
> consumer 3.4.0 (see [CONTAINER_RELEASES.md](CONTAINER_RELEASES.md)). Wave 2
> (warehouse-service) is still pending.

The commerce work ships in two waves:

1. **Wave 1 (this page): shop features.** Coupons, reviews, wishlist, product
   CSV, idempotent checkout, conditional product updates, and the `warehouse`
   demo user with `ROLE_WAREHOUSE`. They run inside the existing backend and
   frontend containers. No new service is added, so the memory budget of every
   profile, including the 4.25 GiB production VPS, is unchanged.
2. **Wave 2: warehouse fulfilment, returns and purchasing.** Shipments, the
   pick/pack/ship workflow, returns (RMA), suppliers, purchase orders and
   reorder suggestions arrive with the separate `warehouse-service` in a later
   release. Until then the `warehouse` user can sign in, but the warehouse,
   returns and purchasing screens and endpoints are not available.
   The stack wiring for wave 2 is described in
   [Wave 2: warehouse-service](#wave-2-warehouse-service) below.

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

Shipping, returns and purchasing scenarios join this flow in wave 2.

## Demo data

Profiles that seed demo data (`local` in the lightweight profile, `demo` in
the full profile) add:

- user `warehouse` / `warehouse` with `ROLE_WAREHOUSE`;
- coupons `WELCOME10` (10 % from 50.00), `SAVE50` (50.00 off from 300.00,
  100 uses), `EXPIRED20` (expired) and `SPRING25` (starts in a week).

Demo suppliers arrive with warehouse-service in wave 2.

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

## Release checklist for this repository (wave 1)

1. Release `jms-email-consumer` first (it tolerates unknown templates), then
   `test-secure-backend`, then `vite-react-frontend` with its OpenAPI snapshot
   regenerated from the released backend.
2. Pin the three new image digests in every Compose profile and validate each
   file with `docker compose config --quiet`.
3. Add `warehouse` / `warehouse` to the demo user lists in `README.md`,
   `docs/STUDENT_GUIDE.md` and `docs/SSO_FLOW.md`, and remove the status note
   at the top of this page.
4. Verify through the gateway: sign-in as `warehouse`,
   `GET /api/v1/admin/coupons` as `admin`, and a CSV export download.

Wave 2 (warehouse-service) has its own deployment notes and checklist below.

## Wave 2: warehouse-service

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
  - server: `docker` profile, same database and schema, `mem_limit: 160m`
    (GraalVM native image, target RSS 120 MiB).
- **Shared secrets.** `JWT_SECRET_KEY` must match the backend so warehouse-service
  can validate backend-issued tokens. `WAREHOUSE_SERVICE_TOKEN` authenticates
  warehouse-service to the backend `/internal/v1` API. Local profiles default
  both through Compose variables (`JWT_SECRET_KEY`, `WAREHOUSE_SERVICE_TOKEN`)
  that are set on both services. The server takes them from Ansible Vault
  (`jwt_secret_key`, `warehouse_service_token`) via `.env.runtime` (backend) and
  `.env.warehouse` (warehouse-service).
- **Gateway.** Warehouse locations precede the generic `/api/v1/` route,
  `/warehouse/v3/api-docs` exposes the warehouse OpenAPI document, and
  `/internal/` returns 404. The upstream is resolved at request time, so the
  gateway still starts without warehouse-service. The `aitesters.byst.re`
  sandbox has no warehouse-service.
- **Monitoring.** Prometheus scrapes `spring_warehouse_micrometer`; the server
  adds a `CriticalContainerMissing` rule and a public probe of
  `https://awesome.byst.re/warehouse/v3/api-docs`. The generic container memory
  alerts cover the 160 MiB limit.
- **Memory.** The server's container limits grow by 160 MiB. Watch
  `MemAvailable` after the rollout against the 600 MiB warning threshold in
  [PRODUCTION_MONITORING_PLAN.md](PRODUCTION_MONITORING_PLAN.md).
- **Image.** Every profile pins
  `slawekradzyminski/warehouse-service:1.0.0@sha256:9fb2c27b9706072a95f7eef1445ce2bc1c14cab8f0dc4a21f025c8f1c3e669e9`;
  the server deployment refuses an unpinned image.

### Release checklist for this repository (wave 2, completed 8 November 2026)

1. Release `test-secure-backend` with the internal API and
   `orders.fulfilment_state` (it must accept `WAREHOUSE_SERVICE_TOKEN`).
2. Publish the first `warehouse-service` image from its repository (Maven tests,
   native build, `linux/amd64` and `linux/arm64`, SBOM and provenance) and copy
   the Docker Hub manifest digest.
3. Replace `image: warehouse-service:local` and its `build:` block with the
   pinned `tag@sha256` reference in the lightweight, full and server profiles;
   record it in `docs/CONTAINER_RELEASES.md` and add `warehouse-service` to
   `PRODUCTION_SERVICES` in `scripts/verify-release-images.py`.
4. Release `vite-react-frontend` with the warehouse screens enabled and both
   OpenAPI snapshots regenerated, then pin it.
5. Add `warehouse_service_token` to the production Vault (`openssl rand -hex 32`).
6. Validate every Compose file with `docker compose config --quiet` and run
   `python3 scripts/verify-image-pins.py` and
   `python3 scripts/verify-release-images.py --remote`.
7. Verify direct and proxied routes: `warehouse-service:4003/actuator/health`
   from the gateway container, `/warehouse/v3/api-docs` and `/warehouse` as
   `warehouse` through the gateway, `/internal/v1/orders/1` returns 404, and a
   full order to ship to return flow.
8. Deploy with `make ansible-deploy-backend-upgrade` (the backend migration
   changes `orders`), then remove the status note at the top of this page.
