# State machines

All lifecycle diagrams in one place. Each links to the page with the rules.

## Order status (backend)

`OrderStatus` values are fixed for compatibility: `PENDING`, `PAID`,
`SHIPPED`, `DELIVERED`, `CANCELLED`.

```mermaid
stateDiagram-v2
    [*] --> PENDING: checkout
    PENDING --> PAID: card captured / tenders cover total / admin
    PENDING --> CANCELLED: customer or admin cancel
    PAID --> SHIPPED: fulfilment SHIPPED / admin
    PAID --> CANCELLED: cancel while NONE or AWAITING_PICK,<br/>warehouse cancel while AWAITING_PICK or PICKED
    SHIPPED --> DELIVERED: fulfilment DELIVERED / admin
    DELIVERED --> [*]
    CANCELLED --> [*]
```

A failed card payment leaves the order `PENDING`. Refunds do not change the
status; they add `refundedAmount`. See [Checkout](checkout.md#after-checkout).

## Fulfilment state (backend mirror)

```mermaid
stateDiagram-v2
    [*] --> NONE
    NONE --> AWAITING_PICK: release
    AWAITING_PICK --> PICKED
    PICKED --> PACKED
    PACKED --> SHIPPED
    SHIPPED --> DELIVERED
    NONE --> CANCELLED
    AWAITING_PICK --> CANCELLED
    PICKED --> CANCELLED: warehouse only
```

See [Warehouse fulfilment](fulfilment.md).

## Shipment (warehouse-service)

```mermaid
stateDiagram-v2
    [*] --> AWAITING_PICK
    AWAITING_PICK --> PICKED: pick
    PICKED --> PACKED: pack
    PACKED --> SHIPPED: ship
    SHIPPED --> DELIVERED: deliver
    AWAITING_PICK --> CANCELLED: cancel
    PICKED --> CANCELLED: cancel
```

## Tracking scans (simulated carrier)

`LABEL_CREATED → IN_TRANSIT (hub) → IN_TRANSIT (depot) → OUT_FOR_DELIVERY →
[DELIVERY_FAILED → OUT_FOR_DELIVERY] → DELIVERED`. See
[Carrier tracking](tracking.md).

## Payment (payment-service)

```mermaid
stateDiagram-v2
    [*] --> REQUIRES_ACTION
    [*] --> PROCESSING
    [*] --> CAPTURED
    [*] --> FAILED
    REQUIRES_ACTION --> CAPTURED: 3-D Secure 123456
    REQUIRES_ACTION --> FAILED: THREE_DS_FAILED / THREE_DS_EXPIRED
    PROCESSING --> CAPTURED: settled
    PROCESSING --> FAILED: PROVIDER_TIMEOUT
    CAPTURED --> VOIDED: ORDER_NOT_PAYABLE
    CAPTURED --> PARTIALLY_REFUNDED
    CAPTURED --> REFUNDED
    PARTIALLY_REFUNDED --> REFUNDED
```

See [Card payments](payments.md).

## Return (warehouse-service)

```mermaid
stateDiagram-v2
    direction LR
    [*] --> REQUESTED
    REQUESTED --> APPROVED
    REQUESTED --> REJECTED
    APPROVED --> RECEIVED
    RECEIVED --> REFUNDED
```

See [Returns and refunds](returns-refunds.md).

## Purchase order (warehouse-service)

```mermaid
stateDiagram-v2
    direction LR
    [*] --> DRAFT
    DRAFT --> SUBMITTED
    DRAFT --> CANCELLED
    SUBMITTED --> CANCELLED
    SUBMITTED --> PARTIALLY_RECEIVED
    SUBMITTED --> RECEIVED
    PARTIALLY_RECEIVED --> RECEIVED
```

See [Purchasing and suppliers](purchasing.md).

## Review, gift card, webhook delivery

| Object | States |
| --- | --- |
| Review | `PENDING` → `APPROVED` or `REJECTED`; editing returns it to `PENDING` |
| Gift card (effective) | `ACTIVE`, `REDEEMED` (balance 0), `EXPIRED`, `DISABLED` |
| Webhook delivery | `PENDING` → `DELIVERED` or `FAILED` |
| Webhook subscription | active ↔ disabled (20 consecutive failures, or `PUT active:false`) |
| Refund outbox row (backend) | queued → `SENT`, `SKIPPED` or `FAILED` |
