# Inventory ownership contract (backend 3.22.0, warehouse-service 1.6.0)

warehouse-service becomes the owner of the stock ledger. The backend keeps `products.stock_quantity` as a
**projection** (a read copy) and calls warehouse-service for every stock-changing command. Public REST, GraphQL and
gRPC bodies do not change.

## 1. Ownership

| Data | Owner after the move | Notes |
|---|---|---|
| Stock quantity per product | warehouse `stock_items` | backend `products.stock_quantity` is a projection |
| Stock movements | warehouse `stock_movements` | backend `inventory_movements` was frozen in 3.22.0 (read only for the import) and dropped in 3.24.0 (V28) |
| Reservations | warehouse `stock_reservations` | one per checkout |
| Product catalog | backend | unchanged |
| Order inventory state (`orders.inventory_state`) | backend | `DEDUCTED` after checkout, `RESTORED` when the cancel is recorded (the restore itself is asynchronous) |

The rule "the backend calls no service" (ADR 1) is reversed for stock only. Record it as a new ADR in both repos.

## 2. Synchronous commands: backend → warehouse

- Base URL: backend `WAREHOUSE_URL` (default `http://warehouse-service:4003`; with the chaos overlay
  `http://toxiproxy:14005`).
- Auth: the backend's service token. The backend sends `Authorization: Bearer <BACKEND_SERVICE_TOKEN>`. warehouse
  checks it against its new `BACKEND_SERVICE_TOKEN` env var, with the same constant-time comparison it uses
  elsewhere, as caller `BACKEND`.
- Every call carries `X-Request-Id` and `traceparent`.
- Timeouts: connect 2 s, read 5 s.
- If warehouse is unreachable, times out or returns 5xx, the backend answers the public call with
  **503 `{"message":"Inventory service unavailable"}`**. 4xx from warehouse map as described below.
- All paths are under `/internal/v1/stock`.

### 2.1 Reserve (checkout)
`POST /internal/v1/stock/reservations`

Request:
```json
{"reservationId":"uuid","username":"alice","lines":[{"productId":1,"quantity":2}]}
```

Behaviour:
- Lines are unique per product. The backend merges duplicates before calling.
- In one transaction: lock the `stock_items` rows in product id order, check every line, then deduct every line.
- Each line writes an `ORDER_DEDUCTED` movement with `actor = username`, `reason = "Order deduction"`, and
  `orderId = null` until confirm.
- The reservation is stored with status `PENDING_CONFIRMATION`.

Responses:
- **201** `{"reservationId":"uuid","lines":[{"productId":1,"quantityAfter":8,"ledgerVersion":42}]}`
- **409** `{"message":"Insufficient stock for product 1","productId":1}`: the first short product in id order.
  Nothing is deducted.
- **404** `{"message":"Product 1 not found","productId":1}`: the product has no stock item.
- A repeat call with the same `reservationId` and identical lines returns the stored 201 body. With different lines
  it returns 409 `"reservationId already used with different lines"`.
- **409** `"Reservation already released"` when the id belongs to a `RELEASED` reservation or a release tombstone
  (2.3). Nothing is deducted.

### 2.2 Confirm
`POST /internal/v1/stock/reservations/{reservationId}/confirm`

Request: `{"orderId":123}`

Behaviour: sets the reservation to `CONFIRMED` and sets `order_id` on its movements.

Responses:
- **200** with the same body as reserve; idempotent.
- **409** if the reservation was released.
- **404** if it is unknown.

### 2.3 Release (compensation)
`POST /internal/v1/stock/reservations/{reservationId}/release`

Behaviour:
- If the reservation is `PENDING_CONFIRMATION`, puts the stock back. Each line writes an `ORDER_RESTORED` movement
  with `actor = "system"` and `reason = "Reservation released"`, and the status becomes `RELEASED`.

- If the id is unknown, stores a `RELEASED` tombstone without lines (`username = "system"`). The backend releases a
  reservation whose reserve call timed out, and that reserve may still be on its way: when it arrives, it finds the
  tombstone and deducts nothing (2.1).

Responses:
- **200** `{"reservationId":"uuid","status":"RELEASED"}`, also for an unknown id.
- A repeat call returns 200 with the same body.
- **409** for a `CONFIRMED` reservation: confirmed orders are restored only through `order.cancelled`.
- **409** `"Reservation was created concurrently; release it again"` when the reserve commits the id while the
  tombstone is being stored.

### 2.4 Adjust (admin)
`POST /internal/v1/stock/adjustments`

Request:
```json
{"productId":1,"delta":-3,"reason":"Damaged","requestId":"uuid","actor":"admin"}
```

The rules are exactly today's backend `InventoryService.adjust`:
- A replay of `(productId, requestId)` with the same `delta` and `reason` returns the stored movement.
- **409** `"requestId already used with different payload"`.
- **409** `"Insufficient stock"` when the result would be below 0.
- **409** `"Inventory quantity exceeds supported maximum"` above `Integer.MAX_VALUE`.
- **404** `"Product not found"` when there is no stock item.
- Validation (`delta != 0`, `requestId` present) stays on the backend.

Response **201**: an `InventoryMovementDto` (section 5), plus `"ledgerVersion":43`.

### 2.5 Initial stock (product create, CSV import, seeding)
`PUT /internal/v1/stock/items/{productId}`

Request:
```json
{"initialQuantity":10,"actor":"admin","requestId":"uuid"}
```

Behaviour:
- Creates the stock item. If `initialQuantity > 0`, writes an `INITIAL_STOCK` movement with
  `reason = "Initial stock"`.
- If the item already exists, it is a no-op: the call returns the current item with **200**.

Responses:
- **201** `{"productId":1,"quantity":10,"ledgerVersion":1}` for a new item.
- **200** with the same shape when the item already existed.

### 2.6 Delete (product delete)
`DELETE /internal/v1/stock/items/{productId}`

Behaviour: deletes the item, its movements and its reservations.

Response: **204**, idempotent (204 also when the item is missing).

### 2.7 Reads
- `GET /internal/v1/stock/items/{productId}` returns `{"productId":1,"quantity":8,"ledgerVersion":42}`, or 404.
- `GET /internal/v1/stock/movements?productId=1&page=0&size=20`
  - Returns a Spring `Page` of `InventoryMovementDto`, ordered by `createdAt` desc, then `id` desc. These are the
    same order and page fields as today's admin endpoint.
  - The backend's public `GET /api/v1/admin/inventory/{id}/movements` still checks first that the product exists
    (404 as today), then returns warehouse's page unchanged.

## 3. Asynchronous flows

### 3.1 Restore after cancel (warehouse consumes the feed)
- `order.cancelled` is NOT changed: its data and webhook payload stay exactly as before.
- When the order's `inventoryState` was `DEDUCTED`, the backend records, in the same transaction as the cancel, a
  second, **internal** feed event `stock.restore-requested`. It is not webhook-eligible, like
  `notification.requested`, and its data is:
  ```json
  {"orderId":123,"actor":"alice","lines":[{"productId":1,"quantity":2}]}
  ```
  `actor` is `reason.actorFor(username)`, exactly the actor today's restore writes. The feed serves it to the
  `WAREHOUSE` caller. notification-service ignores it, and it is never delivered to webhooks.
- The backend then sets `inventoryState = RESTORED` and no longer touches stock.
- warehouse writes one `ORDER_RESTORED` movement per line, with `orderId`, `actor` from the event and
  `reason = "Order cancellation"`. This happens once per order: unique `(order_id)` in `stock_restores`, plus the
  existing `processed_events`.
- warehouse no longer derives restores from `order.cancelled`. Only `stock.restore-requested` restores stock.
  Legacy and shipped orders get no such event.
- Latency is up to one `WAREHOUSE_EVENTS_POLL_INTERVAL` (5 s) after the cancellation commits, plus the level push
  (3.3).
  Clients must poll.

### 3.2 Purchase receipts and return restocks
These are now local ledger writes in warehouse (`PURCHASE_RECEIVED`, `RETURN_RESTOCKED`), with the same actor,
reason, `requestId` and `orderId` as the backend writes today. warehouse stops calling
`POST /internal/v1/inventory/receipts`. The backend answered 410 Gone on that endpoint in 3.22.0 and 3.23.0 and
removed it in 3.24.0 (404).

### 3.3 Stock-level push: warehouse → backend projection
- Every ledger change, in the same transaction, writes a row to warehouse's `stock_level_outbox`, holding
  `productId`, `quantity` and `ledgerVersion`.
- A dispatcher (run right after commit, then every `WAREHOUSE_STOCK_PUSH_RETRY_INTERVAL`, default `PT5S`) posts it
  to the backend:

  `POST /internal/v1/inventory/levels` (service caller `WAREHOUSE`)

  ```json
  {"levels":[{"productId":1,"quantity":8,"ledgerVersion":42}]}
  ```
- The backend applies a level only if `ledgerVersion` is greater than the product's stored
  `stock_ledger_version`. It sets `stock_quantity` and `stock_ledger_version`, touches `updated_at`, and publishes
  `StockReplenishedEvent` on a transition from 0 to more than 0.
- An unknown product is ignored.
- Response **200** `{"applied":1,"ignored":0}`.
- `ledgerVersion` is a per-product counter, incremented on every ledger change.

### 3.4 Orphan reaper (warehouse)
- Every `WAREHOUSE_RESERVATION_REAPER_INTERVAL` (default `PT30S`), reservations in `PENDING_CONFIRMATION` older than
  `WAREHOUSE_RESERVATION_CONFIRM_TIMEOUT` (default `PT2M`) are released as in 2.3. The reason is
  `"Reservation expired unconfirmed"`.
- Exposes a `stock.reservations.reaped` counter and a `stock.outbox.pending` gauge.

## 4. Backend sequences

### 4.1 Checkout (`OrderService.createOrder`)
Never hold a DB connection during an HTTP call: the pool size is 3.

1. A read-only tx loads the cart and validates it (the existing checks, including the local `checkAvailable`
   against the projection, for a fast 409).
2. No tx: reserve (2.1) with a new UUID. On 409 or 404, map to today's 409 `"Insufficient stock for product <id>"`
   or 404. On an unknown outcome (read timeout, connection error, 5xx) answer 503 and release (2.3) the same id on a
   background thread, so a timed-out checkout does not hold the stock until the reaper and a retry does not hold it
   twice.
3. A tx saves the order with `orders.stock_reservation_id` (V25, internal, never serialized),
   `inventoryState = DEDUCTED`, and the existing tender, coupon and cart logic. It applies the returned
   `quantityAfter` and `ledgerVersion` to the projection, using the same newer-version rule.
4. No tx: confirm (2.2). On failure, log and continue: the order exists, and an unconfirmed reservation for an
   existing order is confirmed by the reaper. Before releasing, the reaper asks the backend
   `GET /internal/v1/orders/by-reservation/{reservationId}`, which returns `{"orderId":123}` or 404, and confirms
   instead when an order exists.
   Since backend 3.22.2 the lookup and step 3 cannot both conclude: step 3 first inserts and deletes the
   reservation id in `stock_reservation_claims` (V26), and the lookup commits the id there as a tombstone before it
   reads `orders`. The primary key makes the later writer wait, so a lookup during a slow step 3 waits and finds
   the order, and a step 3 that is still running after a 404 fails with 409
   `"Stock reservation expired during checkout; please try again"` (no order stored, cart kept).
5. If step 3 throws, release (2.3) in a catch and rethrow the original error.

### 4.2 Admin adjust, GraphQL `adjustInventory`, gRPC
Validate as today, check that the product exists, call 2.4, apply the projection, and return the movement without
`ledgerVersion`.

### 4.3 Product create, CSV import, startup seeding
- Commit the product with `stock_quantity = initialQuantity` and `stock_ledger_version = 0`, plus a
  `stock_command_outbox` row (V25) in the same tx.
- After commit, call 2.5 **synchronously in the request thread, before the response is sent**, and mark the row
  done. A product is usable for checkout as soon as its create response arrives.
- On failure (warehouse down), the response is still 201 and the outbox dispatcher retries every `PT5S`; the
  public response does not wait for the retry.
- Safety net: if a reserve (2.1) answers 404 for a product that exists on the backend and still has a pending
  initial-stock command, the backend sends that command synchronously and retries the reserve once.

### 4.4 Product delete
Delete as today, plus a `stock_command_outbox` DELETE row (2.6).

### 4.5 Product update with a stock change (`ProductService` :113, CSV)
The existing code calls `inventoryService.adjust`, which becomes 4.2.

### 4.6 Reads
- `GET /api/v1/admin/inventory` (list) and `GET /api/v1/admin/inventory/{id}`: from the projection, as today.
- Movements: through 2.7.

## 5. `InventoryMovementDto` JSON (unchanged)
```json
{"id":1,"productId":1,"orderId":null,"type":"ADMIN_ADJUSTMENT","delta":-3,"quantityAfter":7,
 "actor":"admin","reason":"Damaged","requestId":"uuid","createdAt":"2026-11-14T10:00:00.123456"}
```
- `createdAt` is a zone-less local date-time in UTC, serialized exactly as the backend does today.
- Types: `INITIAL_STOCK`, `ADMIN_ADJUSTMENT`, `ORDER_DEDUCTED`, `ORDER_RESTORED`, `PURCHASE_RECEIVED`,
  `RETURN_RESTOCKED`.
- Null fields are serialized as they are today. Check the backend's Jackson inclusion and match it.

## 6. One-time import
- The backend exposes `GET /internal/v1/inventory/export`, for service caller `WAREHOUSE`. It is paged
  with `?afterProductId=&limit=500`:
  ```json
  {"items":[{"productId":1,"quantity":10}],
   "nextAfterProductId":1}
  ```
  The response ends with `nextAfterProductId: null`.
- Backend 3.22.0 and 3.23.0 also sent each product's `movements` from the frozen `inventory_movements` table, so
  the deployments of the move kept their history. Backend 3.24.0 dropped the table (V28) and the list: an empty
  warehouse ledger now starts from the projected quantities, with no movements. warehouse-service reads a missing
  `movements` list as empty, so 1.6.0 and later import from either backend.
- On startup, if the warehouse ledger tables are empty, warehouse imports before reporting healthy:
  - `ledgerVersion` is set to `1` for each item;
  - movement ids are kept;
  - the movement id sequence is moved past the maximum;
  - items whose product already has an item (from 2.5 calls racing the import) are skipped.
- Until the import has finished, every 2.x endpoint returns **503** `{"message":"Stock ledger not initialised"}`.
- Pending reservations do not exist before the move. Orders in `DEDUCTED` state need nothing.
- After the import, warehouse pushes every level once (3.3), so projections get `ledgerVersion` 1.
- On a fresh stack the backend seeds products first, and warehouse imports them. Seeding's 2.5 calls can race the
  import; both are idempotent.

## 7. Configuration

| Service | Variable | Default |
|---|---|---|
| backend | `WAREHOUSE_URL` | `http://warehouse-service:4003` |
| backend | `WAREHOUSE_CONNECT_TIMEOUT` / `WAREHOUSE_READ_TIMEOUT` | `PT2S` / `PT5S` |
| backend | `BACKEND_SERVICE_TOKEN` (sent to warehouse) | none, required |
| warehouse | `BACKEND_SERVICE_TOKEN` (expected from backend) | none, required |
| warehouse | `WAREHOUSE_STOCK_PUSH_RETRY_INTERVAL` | `PT5S` |
| warehouse | `WAREHOUSE_RESERVATION_CONFIRM_TIMEOUT` / `_REAPER_INTERVAL` | `PT2M` / `PT30S` |

Vault, for both sites: `backend_service_token`, `aitesters_backend_service_token`.

## 8. Flyway
- backend V25 `stock_ledger_projection`: adds `products.stock_ledger_version bigint not null default 0`,
  `orders.stock_reservation_id uuid null`, and the `stock_command_outbox` table. Guard every table with
  `to_regclass`, because legacy schemas are baselined at V1.
- backend V28 `drop_frozen_inventory_movements` (3.24.0): `DROP TABLE IF EXISTS inventory_movements`. A database
  that jumps from 3.21 or older straight to 3.24.0 keeps its quantities but loses the old movement history; upgrade
  through 3.23.0 and let warehouse-service import first to keep it.
- warehouse V7 `stock_ledger`: `stock_items`, `stock_movements` (identity id), `stock_reservations`,
  `stock_reservation_lines`, `stock_restores`, `stock_level_outbox`.

## 9. Fault lab
- New Toxiproxy proxy `backend→warehouse` on `toxiproxy:14005`, which forwards to `warehouse-service:4003`.
- New `scripts/chaos` scenarios:
  - `warehouse-down`: checkout and admin adjust return 503, while reads and the cart still work;
  - `warehouse-slow`: latency up to the 5 s read timeout.
- Existing `backend-down` with target `warehouse` now also shows `stock.outbox.pending` growing and the projection
  catching up after `heal`.
