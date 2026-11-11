# Business flows

Each page describes one business capability: the rules, the endpoints, and a
diagram of who calls whom. Paths are gateway paths.

| Flow | Owner service | Page |
| --- | --- | --- |
| Sign-up, sign-in, refresh, MFA, password reset, SSO | backend | [Accounts, MFA and SSO](accounts.md) |
| Catalog, product search, facets, reviews, wishlist | backend | [Catalog and search](catalog-search.md) |
| Cart, coupons, gift cards, loyalty points | backend | [Cart, coupons, gift cards, loyalty](cart.md) |
| Checkout, VAT, tenders, `amountDue`, idempotency | backend | [Checkout, VAT and tenders](checkout.md) |
| Card payments, 3-D Secure, settlement, voids, refunds | payment-service + backend | [Card payments](payments.md) |
| Queue → pick → pack → ship → deliver | warehouse-service + backend | [Warehouse fulfilment](fulfilment.md) |
| Simulated carrier, public tracking | warehouse-service | [Carrier tracking](tracking.md) |
| Returns (RMA), refunds and their split | warehouse-service + backend + payment-service | [Returns and refunds](returns-refunds.md) |
| Suppliers, purchase orders, reorder suggestions | warehouse-service | [Purchasing and suppliers](purchasing.md) |
| Customer emails | backend + consumer | [Emails](emails.md) |
| Signed HTTP callbacks for order events | backend | [User webhooks](webhooks.md) |
| Display currencies | backend + frontend | [Currencies](currencies.md) |
| Order, payment, shipment, return state machines | all | [State machines](state-machines.md) |

## The order journey

The happy path of one order across all services, with a card that is captured
immediately and the simulated carrier.

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant B as Backend
    participant P as payment-service
    participant W as warehouse-service
    actor WH as Warehouse operator
    C->>B: POST /api/v1/users/signin
    B-->>C: token + refreshToken
    C->>B: POST /api/v1/cart/items, PUT /api/v1/cart/coupon
    C->>B: POST /api/v1/orders (Idempotency-Key)
    B-->>C: 201 order PENDING (VAT, tenders, amountDue)
    C->>P: POST /api/v1/payments (Idempotency-Key, card 4242…)
    P->>B: GET /internal/v1/orders/{id}
    P-->>C: 201 payment CAPTURED
    P->>B: POST /internal/v1/orders/{id}/payment (signed)
    B->>B: order PENDING → PAID, ORDER_PAID event
    B-->>C: emails PAYMENT_RECEIVED, LOYALTY_POINTS_EARNED; webhook order.paid
    WH->>W: GET /api/v1/warehouse/queue
    W->>B: GET /internal/v1/orders?status=PAID&fulfilment=NONE
    WH->>W: POST /api/v1/warehouse/shipments {orderId}
    W->>B: PUT /internal/v1/orders/{id}/fulfilment AWAITING_PICK
    WH->>W: pick, pack {weightKg}, ship {carrier}
    W->>B: PUT fulfilment PICKED, PACKED, SHIPPED
    B-->>C: email ORDER_SHIPPED; webhook shipment.shipped
    loop every step interval (simulated carrier)
        W->>W: IN_TRANSIT, OUT_FOR_DELIVERY, ...
    end
    W->>B: PUT fulfilment DELIVERED
    B-->>C: email ORDER_DELIVERED; webhook shipment.delivered
    C->>W: GET /api/v1/orders/{id}/shipment/tracking
```

After delivery the customer may [review the product](catalog-search.md#reviews-and-ratings)
and, within 30 days, [request a return](returns-refunds.md).

## Domain events

The backend publishes a domain event inside the transaction that changes an
order; listeners run **after commit**. Emails, loyalty points, card refunds
and user webhooks all hang off these events.

| Event | Wire name | Published when |
| --- | --- | --- |
| `ORDER_CREATED` | `order.created` | Checkout creates an order (not on an idempotent replay) |
| `ORDER_PAID` | `order.paid` | Admin status change to `PAID`, a captured card payment, or tenders covering the whole total |
| `ORDER_CANCELLED` | `order.cancelled` | Any cancellation: customer, admin or warehouse |
| `ORDER_SHIPPED` | `shipment.shipped` | Admin status change to `SHIPPED` or fulfilment reaching `SHIPPED` |
| `ORDER_DELIVERED` | `shipment.delivered` | Admin status change to `DELIVERED` or fulfilment reaching `DELIVERED` |
| `REFUND_BOOKED` | `refund.booked` | A refund is booked for a return |
| `PAYMENT_FAILED` | `payment.failed` | payment-service reports a failed payment for a `PENDING` order |

Every event's `data` contains `orderId`, `status` and `totalAmount`; refunds
add `amount` and `requestId`, payments add `paymentId` (and `failureCode` on
failure). Repeating the current status, replays and rejected changes publish
nothing.
