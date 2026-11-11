# State machines

All lifecycle diagrams in one place. Each links to the page with the rules.

## Order status (backend)

`OrderStatus` values are fixed for compatibility: `PENDING`, `PAID`,
`SHIPPED`, `DELIVERED`, `CANCELLED`.

```mermaid
stateDiagram-v2
    [*] --> PENDING: checkout
    PENDING --> PAID: paid
    PAID --> SHIPPED: shipped
    SHIPPED --> DELIVERED: delivered
    PENDING --> CANCELLED: cancel
    PAID --> CANCELLED: cancel before packing
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
flowchart TB
    S[Card submitted] --> K{Test card}
    K -->|success| C1[CAPTURED]
    K -->|declined| F1[FAILED]
    K -->|3-D Secure| A[REQUIRES_ACTION]
    K -->|async| P[PROCESSING]
    A -->|code 123456| C2[CAPTURED]
    A -->|wrong code or 15 min| F2[FAILED]
    P -->|settles after 10 s| C3[CAPTURED]
    P -->|timeout card| F3[FAILED]
```

After a capture: `CAPTURED → VOIDED` (backend says the order is not payable),
`CAPTURED → PARTIALLY_REFUNDED → REFUNDED`, or `CAPTURED → REFUNDED`.
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
    [*] --> DRAFT
    DRAFT --> SUBMITTED: submit
    SUBMITTED --> PARTIALLY_RECEIVED: receive some
    PARTIALLY_RECEIVED --> RECEIVED: receive rest
    SUBMITTED --> RECEIVED: receive all
    DRAFT --> CANCELLED: cancel
    SUBMITTED --> CANCELLED: cancel
```

See [Purchasing and suppliers](purchasing.md).

## Review, gift card, webhook delivery

| Object | States |
| --- | --- |
| Review | `PENDING` → `APPROVED` or `REJECTED`; editing returns it to `PENDING` |
| Gift card (effective) | `ACTIVE`, `REDEEMED` (balance 0), `EXPIRED`, `DISABLED` |
| Webhook delivery | `PENDING` → `DELIVERED` or `FAILED` |
| Webhook subscription | active ↔ disabled (20 consecutive failures, or `PUT active:false`) |
