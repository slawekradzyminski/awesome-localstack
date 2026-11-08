# Commerce training features

> **Status: wave 1 released** with backend 3.10.0, frontend 3.10.0 and
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

Wave 2 (warehouse-service) has its own deployment notes and checklist.
