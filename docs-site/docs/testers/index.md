# For testers

Test ideas per feature, chosen because each one exercises a real rule in the
code. Every scenario names the expected result so it can become an automated
check. Use the lightweight profile unless a scenario says otherwise.

## Accounts and security

| Scenario | Expected |
| --- | --- |
| Sign in with a wrong password | `422` |
| Sign-up boundaries: username of 3 vs 4 characters, password of 7 vs 8 | `400` / `201` |
| Refresh, then reuse the **old** refresh token | `401`; the new token from the first refresh is now revoked too (family revocation) |
| Logout, then refresh with the same token | `401` |
| Restart the backend (ephemeral key), call an API with the old access token | `401`; refresh still works |
| MFA: sign in, wait > 5 minutes, submit the code | `401` (challenge expired) |
| MFA: use the same TOTP code twice within 30 s | second use `401` (replay) |
| MFA: two password sign-ins, answer the first challenge | `401` (superseded) |
| Recovery code used twice | second use `401` |
| `password/forgot` for an unknown user | `202`, same body as for a real user (no enumeration) |
| Reset token used twice, or after 30 minutes | `400 ... already used` / `400 ... expired` |
| Call `/internal/v1/orders/1` through the gateway | `404` on every host |
| Call warehouse endpoints as `client` | `403`; as `warehouse` on admin purchasing endpoints → `403` |
| Decode a JWT: `alg`, `kid`, `sub`, `auth` claim | RS256, roles in `auth` |
| Send an HS256 token signed with any secret to payment-service | `401` |

## Catalog and search

| Scenario | Expected |
| --- | --- |
| `minPrice=10&maxPrice=5` and `sort=cheapest` together | one `400` with both fields in the map |
| `q=%` / `q=_` | literal match, not a wildcard |
| `category=Chairs,Misc` vs `category=Chairs&category=Misc` | same result |
| Select a category: the category facet still lists the others | facets ignore the `category` filter |
| `page` past the end | empty `content`, real `totalElements` |
| `minRating=4` with products that have only pending reviews | excluded (approved reviews only) |
| `GET /products/{id}` with `If-None-Match` = current ETag | `304` |
| Two admins update the same product with the same `If-Match` | second `412` |
| CSV import with one bad row among 999 good ones | `400`, nothing persisted |
| CSV export of a product named `=HYPERLINK(...)` | cell prefixed with `'` |
| Review before delivery | `403`; second review `409` |

## Cart and tenders

| Scenario | Expected |
| --- | --- |
| `WELCOME10` with subtotal 49.99 vs 50.00 | `400` vs applied |
| Apply coupon, then remove items until below the minimum, then check out | `409 Applied coupon is no longer valid: ...`, cart kept |
| `EXPIRED20`, `SPRING25` | `400 has expired` / `400 not valid yet` |
| Lower-case code `welcome10` | accepted (normalised) |
| Points 150 | `400` (multiples of 100); more than the balance → `409` |
| Points worth more than the remaining total | `pointsRedeemed` capped to the cent |
| Gift card disabled by an admin **between** cart and checkout | checkout `409`, rollback, cart kept |
| Gift card + points covering the whole total | order `PENDING` in the response, `PAID` immediately after |
| Cart JSON without tenders | no `amountDue`, `giftCard*`, `points*` keys at all |

## Checkout and VAT

| Scenario | Expected |
| --- | --- |
| Same `Idempotency-Key` twice, same address | one order, second `201` with `Idempotent-Replayed: true` |
| Same key, different address | `409` |
| Key `short` (5 chars) or with `!` | `400` |
| Same key used by two different users | two independent orders (per-user scope) |
| Country `Polska`, `pl`, `POL`, ` Poland ` | all resolve to PL, 23 % |
| Country `Atlantis` | no tax fields in the order |
| Change a VAT rate after ordering | old order unchanged |
| `GET /cart/tax-preview` without `country` | `400` |

## Payments

| Scenario | Expected |
| --- | --- |
| Each test card in the [table](../flows/payments.md#test-cards) | the documented status and failure code |
| `4242 4242 4242 4241` (Luhn-invalid) | `400` |
| Expiry last month vs this month | `400` vs accepted |
| Double-submit with the same key and body | one payment; second `200` + `Idempotent-Replayed` |
| Same key, different card | `409` |
| Pay an order that is already `PAID` | `409` |
| Pay someone else's order | `403` |
| `…3220`, wrong 3-D Secure code, then pay again | first `FAILED THREE_DS_FAILED`, new attempt allowed |
| `…3220`, cancel the order, then answer `123456` | payment ends `VOIDED`, `ORDER_NOT_PAYABLE` |
| Pay with `4242…`, cancel the order, wait about 10 s | payment `REFUNDED` (card refund from the event feed) |
| Read another user's payment or order payments | `404`, same as a missing one |
| `…0077`: poll until settled | `PROCESSING` → `CAPTURED` after ~10 s; order `PAID` |
| `…0119` | `PROCESSING` → `FAILED PROVIDER_TIMEOUT`; order stays `PENDING`; `PAYMENT_FAILED` email |
| `…0259` | one `PAYMENT_RECEIVED` email, one `order.paid` webhook, points earned once |
| Two parallel payments for one order with different keys | only one becomes active, the other `409` |
| Stop the backend, pay | `503` |

## Fulfilment and tracking

| Scenario | Expected |
| --- | --- |
| Pack with `weightKg` 0.00 / 0.01 / 30.00 / 30.01 | `400` / ok / ok / `400` |
| Ship `DHL` with 9 or 11 digits; `UPS` with lower-case letters | `400` |
| Skip a step (ship an `AWAITING_PICK` shipment) | `409` |
| Customer cancels while `AWAITING_PICK`, then the warehouse picks at once | `409 Order was cancelled by the customer` |
| Customer cancels while `AWAITING_PICK`, then waits about 10 s | shipment `CANCELLED` with `lastActor` `system` (event feed), no warehouse action needed |
| Customer cancels after `PICKED` | `409 Order is already being packed...` |
| Ship without `trackingNumber`, call `carrier/advance` repeatedly | walks every scan to `DELIVERED`, emails at out-for-delivery |
| Find a tracking number with `abs(hashCode) % 5 == 0` | `DELIVERY_FAILED` then second attempt |
| `carrier/advance` on a manual parcel | `409` |
| `GET /api/v1/tracking/{number}` without a token | `200`, no `orderId` or owner |
| Stop warehouse-service, open the shop | shop works; warehouse paths `502` |

## Returns, refunds, purchasing

| Scenario | Expected |
| --- | --- |
| Return on day 30 vs day 31 after delivery | allowed vs rejected |
| Return more units than ordered across two requests | second rejected |
| Two parallel return requests for the last unit | one succeeds (row lock) |
| Refund with a 10 % coupon order | proportional: item value × total / subtotal |
| Refund an order paid with card + gift card | card first, rest to the gift card |
| Receive more than outstanding on a purchase order | `409` |
| Replay a receipt `requestId` with the same / different lines | same result / `409` |
| Reorder suggestion arithmetic at the threshold boundary | `stock + incoming = threshold` is included |

## Emails and webhooks

| Scenario | Expected |
| --- | --- |
| Create an inbox, subscribe `order.created`, check out | one request in the inbox with a valid signature |
| Verify the signature with the secret, reject a tampered body | HMAC matches only the original bytes |
| Redeliver a delivery | same event `id`, new delivery id |
| Subscribe `http://localhost:8080`, `http://backend`, `http://169.254.169.254`, `http://2130706433` | all `400 Webhook URL rejected` |
| A sixth subscription / a fourth inbox | `409` |
| A receiver that answers `302` | delivery failure (redirects not followed) |
| A receiver that sleeps 6 s | failure (5 s deadline), retried with backoff |
| Stop ActiveMQ (full profile), trigger an email, restart it | email arrives after a retry |

## Non-functional

- **Performance:** k6 against a local profile started with the monitoring
  overlay (`-f docker-compose.monitoring.yml`, or `./run-docker-compose.sh`)
  writes to InfluxDB and the Grafana k6 dashboard; production rate limits are deliberately raised, but
  keep load tests local.
- **Resilience:** stop one service at a time (`docker compose stop payment-service`)
  and observe which paths degrade (`502`, `503`) and which keep working.
- **Accessibility and UI:** the frontend has `data-testid` coverage for
  automation; the traffic monitor (`/traffic`) shows your own requests.
- **Contract:** compare the three OpenAPI documents with real responses; the
  course compatibility runner ([Course compatibility](../reference/COURSE_COMPATIBILITY.md))
  shows how a frozen suite guards backwards compatibility.
