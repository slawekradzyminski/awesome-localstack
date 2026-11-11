# Glossary

**3-D Secure (3DS)**
:   An extra card-holder check. Test card `4000 0000 0000 3220` returns
    `REQUIRES_ACTION`; code `123456` completes it. See [Card payments](flows/payments.md#3-d-secure).

**`amountDue`**
:   What a card must pay: `totalAmount − giftCardAmount − pointsAmount`. Shown
    only on orders that used a gift card or points.

**`auth` claim**
:   The JWT claim that carries the user's roles (`ROLE_CLIENT`, `ROLE_WAREHOUSE`, `ROLE_ADMIN`).

**aitesters sandbox**
:   The second public site, `aitesters.byst.re`, with its own services and
    database, reset every night.

**Artemis**
:   Apache ActiveMQ Artemis, the message broker carrying emails (queue `email`).

**Bootstrap admin / catalog**
:   Production has no demo seed; it creates one admin from Vault values and a
    baseline product catalog when the table is empty.

**Card-first refund split**
:   A booked refund goes to the captured card first, then the gift card, then
    loyalty points. See [Returns and refunds](flows/returns-refunds.md#refund-split).

**Carrier simulator**
:   warehouse-service scheduler that moves parcels shipped without a tracking
    number through realistic scans.

**Compatibility set**
:   The six first-party images (backend, frontend, consumer, ollama-mock,
    warehouse-service, payment-service) released and pinned together.

**Consumer**
:   `jms-email-consumer`: reads rendered emails from Artemis and sends them over SMTP.

**Coupon**
:   A discount code (`PERCENTAGE` or `FIXED_AMOUNT`) that lowers `totalAmount`.

**Digest pin**
:   An image reference of the form `name:tag@sha256:<digest>`, which cannot
    silently change.

**Domain event**
:   A backend `CommerceEvent` (`order.created`, `order.paid`, …) published inside
    the transaction, recorded in the event feed in that transaction and handled
    by other listeners after commit.

**Edge**
:   The host-network nginx on the VPS that receives traffic from the
    provider's HTTPS proxy and forwards it to the gateway.

**Event feed**
:   `GET /internal/v1/events`: the backend's durable list of domain events,
    which warehouse-service and payment-service poll from their own cursor.
    See [Event feed](reference/EVENT_FEED.md).

**Facet**
:   A count or range returned next to search results (categories, price range,
    in-stock count) to build filters.

**Family (refresh token)**
:   All refresh tokens descending from one sign-in. Reusing a consumed token
    revokes the whole family.

**Fulfilment state**
:   The backend's mirror of warehouse progress on an order: `NONE`,
    `AWAITING_PICK`, `PICKED`, `PACKED`, `SHIPPED`, `DELIVERED`, `CANCELLED`.

**Gateway**
:   The nginx container that is the single entry point and routes each path to a service.

**Gift card**
:   A prepaid code `GC-XXXX-XXXX-XXXX` that pays part of an order.

**GraalVM native image**
:   An ahead-of-time compiled Java binary: fast start and small memory, heap
    set with `-Xmx` at runtime.

**HMAC signature**
:   `t=<epoch>,v1=<hex HMAC-SHA256(secret, t + "." + body)>`, used by payment
    results and user webhooks.

**Idempotency-Key**
:   Client-chosen header (`^[A-Za-z0-9_-]{8,64}$`) that makes checkout and
    payment retries safe.

**Inbox (webhook)**
:   A built-in receiver `inbox://<token>` that stores webhook requests for
    inspection.

**Internal API**
:   The backend's `/internal/v1` endpoints for warehouse-service and
    payment-service, authenticated by `X-Service-Token`, never public.

**JWKS**
:   JSON Web Key Set: the public keys that verify the backend's RS256 tokens,
    at `/internal/v1/jwks.json`.

**`kid`**
:   Key id in the JWT header, used to pick the verification key.

**Lightweight / full / server**
:   The three main Compose profiles. See [Compose profiles](architecture/profiles.md).

**Local outbox**
:   The lightweight profile's in-memory email store, read with
    `GET /api/v1/local/email/outbox`.

**Loyalty points**
:   Earned at 1 point per full 1.00 paid (excluding points), redeemed in
    multiples of 100 (100 points = 1.00).

**Luhn check**
:   The checksum every card number must pass.

**Mailpit**
:   Fake SMTP server and web inbox.

**MFA / TOTP**
:   Multi-factor authentication with time-based one-time passwords (RFC 6238, 30-second steps).

**Outbox (transactional)**
:   A table written in the same transaction as a business change and
    delivered afterwards with retries.

**PKCS#8**
:   The private-key format `JWT_SIGNING_KEY` must use (base64 DER).

**Reconciler**
:   warehouse-service safety-net job (every 10 minutes since 1.3.0) that aligns
    shipments with backend cancellations the event feed missed and adopts
    orphaned releases.

**`requestId`**
:   Idempotency id of a service-to-service write; repeats return the first result.

**RMA**
:   Return merchandise authorisation — a return request.

**Service token**
:   Shared secret per calling service sent as `X-Service-Token`.

**Settlement delay**
:   Time after which `PROCESSING` test payments settle (10 s by default).

**Settle delay (event feed)**
:   The feed serves only events recorded at least 3 s ago, so a transaction
    that committed late with a lower sequence is not skipped.

**SSRF**
:   Server-side request forgery; webhook URLs are checked so they cannot reach
    internal addresses.

**Tender**
:   A way to pay part of an order other than the card: gift card or loyalty points.

**Tracking number**
:   Carrier-specific parcel number: InPost 24 digits, DPD 14, DHL 10, UPS `1Z` + 16.

**Vault (Ansible)**
:   The encrypted file holding production secrets.

**VAT (gross pricing)**
:   Prices include VAT; orders show the VAT their total contains, by shipping country.

**Void**
:   Reversal of a capture that the backend refused (`409 Order is not payable`).
