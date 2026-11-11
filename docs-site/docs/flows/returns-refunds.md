# Returns and refunds

Returns (RMA) live in warehouse-service; the money side lives in the backend
and payment-service. A refund always starts as a **booked refund** on the
order in the backend and is then **split** across the tenders the customer
used.

## Return lifecycle

```mermaid
stateDiagram-v2
    [*] --> REQUESTED
    REQUESTED --> APPROVED: approve
    REQUESTED --> REJECTED: reject
    APPROVED --> RECEIVED: receive
    RECEIVED --> REFUNDED: refund
```

## Endpoints

| Method and path | Access | Rules |
| --- | --- | --- |
| `POST /api/v1/orders/{orderId}/returns` | owner | Order `DELIVERED`, at most **30 days** after delivery; each quantity ≤ ordered quantity minus quantities in other non-rejected returns; reason `DAMAGED`, `WRONG_ITEM`, `NOT_AS_DESCRIBED` or `NO_LONGER_NEEDED` |
| `GET /api/v1/returns`, `GET /api/v1/returns/{id}` | owner | Own returns |
| `GET /api/v1/admin/returns?status=`, `GET /api/v1/admin/returns/{id}` | admin | All returns |
| `POST /api/v1/admin/returns/{id}/approve` | admin | `REQUESTED → APPROVED` |
| `POST /api/v1/admin/returns/{id}/reject` | admin | Note required |
| `POST /api/v1/admin/returns/{id}/receive` | admin | Condition `RESELLABLE` or `DAMAGED` for every item; resellable items are restocked |
| `POST /api/v1/admin/returns/{id}/refund` | admin | Books the refund in the backend, then `REFUNDED` |

Return requests for the same order are serialised with a row lock
(`order_locks`), so two parallel requests cannot over-return an item. Approve,
reject and refund send a `RETURN_UPDATED` email.

## Refund amount

Coupons are returned **proportionally**:

```text
refund = Σ(unit price × returned quantity) × totalAmount / subtotalAmount   (half-up, 2 decimals)
```

!!! example
    Order subtotal 200.00, coupon 10 % → total 180.00. Returning one item of
    50.00 refunds 50.00 × 180/200 = **45.00**.

The backend refuses refunds that would exceed the order total (`409`). A refund
that brings the order to its full total releases the coupon redemption.

## End-to-end refund

```mermaid
sequenceDiagram
    actor A as Admin
    participant W as warehouse-service
    participant B as Backend
    participant F as Event feed
    participant P as payment-service
    A->>W: Receive return 7
    W->>B: Restock items
    A->>W: Refund return 7
    W->>B: Book refund 45.00
    Note over B: Split, card first
    B->>F: card-refund.requested (same transaction)
    B-->>W: 200
    W-->>A: Return REFUNDED
    P->>F: Poll (every 5 s)
    F-->>P: card-refund.requested
    Note over P: Card refund booked
```

Step by step:

1. **Receive** — warehouse-service restocks resellable items with
   `POST /internal/v1/inventory/receipts` (`RETURN_RESTOCKED`, `requestId`
   derived from `"return-" + id`).
2. **Refund** — it books the refund with `POST /internal/v1/orders/{id}/refunds`
   (`requestId` derived from `"refund-" + id`), then marks the return
   `REFUNDED` and queues a `RETURN_UPDATED` email.
3. **Split** — in the same transaction the backend publishes `REFUND_BOOKED`
   (webhook `refund.booked`), splits the amount card first, restores the gift
   card or points part, and revokes earned points pro rata.
4. **Card** — in the same transaction the backend publishes the card part as
   a `card-refund.requested` event (internal, never sent to user webhooks).
   payment-service pulls it from the [event feed](../reference/EVENT_FEED.md)
   about 5–8 seconds later and moves the payment to `PARTIALLY_REFUNDED` or
   `REFUNDED`. The backend never calls payment-service and does not wait for
   the result.

## Refund split

`CardFirstRefundSplitter` divides each booked refund:

1. **Card** — up to the captured amount minus card refunds already
   requested (`card_refund_requests`). Orders without a captured payment (paid by an admin, or fully by
   tenders) get no card leg.
2. **Gift card** (`GiftCardRefundLegHandler`) — up to what the order paid with
   its gift card; the balance is restored (`RESTORED` ledger row).
3. **Loyalty points** (`LoyaltyPointsRefundLegHandler`) — up to the value of the
   redeemed points.
4. Anything beyond that is not sent anywhere.

Each leg is idempotent per refund `requestId`. Independently, points the order
**earned** are revoked in proportion to the refunded share of the total
(rounded down, never below zero).

!!! example "Split example"
    Total 108.00 paid with gift card 25.00, points 20.00 (2000 points) and
    card 63.00. A refund of 80.00 goes **63.00 to the card**, **17.00 to the gift
    card**, nothing to points. Earned points are revoked for 80/108 of the
    order.

## Cancellation refunds

Cancelling an order (customer, admin or warehouse) restores the gift card and
points in full, revokes earned points and — when a card payment was captured —
requests a card refund of the captured amount minus earlier card refunds, with
`requestId = UUID.nameUUIDFromBytes("cancel:" + orderId)` and reason
`Order cancelled`, as a `card-refund.requested` event in the cancelling
transaction. See [Card payments](payments.md#refunds-to-the-card) for how
payment-service handles each event.
