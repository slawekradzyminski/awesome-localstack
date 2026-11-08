# Commerce and warehouse fulfilment training features

> **Status: pending release.** The features below live on the
> `feature/commerce-fulfilment` branches of `test-secure-backend`,
> `vite-react-frontend` and `jms-email-consumer`. The Compose files in this
> repository still pin the previous images, so the stack does not serve these
> endpoints or screens until the new images are released and pinned. The
> release checklist at the end lists what to update here at that point.

All features run inside the existing backend and frontend containers. No new
service is added, so the memory budget of every profile, including the
4.25 GiB production VPS, is unchanged.

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
| Warehouse | `/warehouse` (warehouse or admin role) | `/api/v1/warehouse/**`, `GET /api/v1/orders/{id}/shipment` | State machine, carrier-specific tracking formats, role-based access, cancellation rules |
| Returns | Order page return form, `/returns`, `/admin/returns` | `/api/v1/orders/{id}/returns`, `/api/v1/returns`, `/api/v1/admin/returns` | 30-day window, returnable quantities, restocking, proportional refunds with coupons |
| Purchasing | `/admin/purchasing` | `/api/v1/admin/suppliers`, `/api/v1/admin/purchase-orders`, `/api/v1/admin/inventory/reorder-suggestions` | Partial receipts, over-receipt, receipt idempotency, reorder arithmetic |

A typical end-to-end scenario touches every role:

1. `client` adds products, applies `WELCOME10` and checks out.
2. `admin` marks the order `PAID`.
3. `warehouse` releases, picks, packs and ships it with a valid tracking number, then confirms delivery.
4. `client` reviews the product and opens a return.
5. `admin` moderates the review, approves, receives and refunds the return; resellable stock comes back.

## Demo data

Profiles that seed demo data (`local` in the lightweight profile, `demo` in
the full profile) add:

- user `warehouse` / `warehouse` with `ROLE_WAREHOUSE`;
- coupons `WELCOME10` (10 % from 50.00), `SAVE50` (50.00 off from 300.00,
  100 uses), `EXPIRED20` (expired) and `SPRING25` (starts in a week);
- suppliers `Nordic Electronics` (7-day lead time) and `Baltic Gadgets` (14 days).

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

## Release checklist for this repository

1. Release `jms-email-consumer` first (it tolerates unknown templates), then
   `test-secure-backend`, then `vite-react-frontend` with its OpenAPI snapshot
   regenerated from the released backend.
2. Pin the three new image digests in every Compose profile and validate each
   file with `docker compose config --quiet`.
3. Add `warehouse` / `warehouse` to the demo user lists in `README.md`,
   `docs/STUDENT_GUIDE.md` and `docs/SSO_FLOW.md`, and remove the status note
   at the top of this page.
4. Verify through the gateway: `/warehouse` as `warehouse`,
   `GET /api/v1/admin/coupons` as `admin`, and a CSV export download.
