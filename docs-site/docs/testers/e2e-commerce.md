# End-to-end tests of the commerce features

[awesome-localstack-e2e-tests](https://github.com/slawekradzyminski/awesome-localstack-e2e-tests)
is the reference Playwright implementation for this stack. It tests payments,
gift cards and loyalty points, VAT and currencies, product search, carrier
tracking and user webhooks, through the API, the browser and journeys that
cross every service. The repository is private for now; ask for access if you
take part in a course.

## What it covers

| Project | Folder | What a test does |
| --- | --- | --- |
| `api` | `tests/api/<feature>/` | Calls one endpoint group through the gateway and checks every documented status code, the body and the stored state |
| `ui` | `tests/ui/<feature>/` | Prepares data through the API, drives one page in Chromium, then confirms the result through the API |
| `journeys` | `tests/journeys/` | Follows one order across backend, payment-service, the event feed, warehouse-service and webhooks |

The journeys are where these features differ from a plain CRUD API. Each
crosses at least two services and waits for background work:

- **Cancel a card-paid order.** The card refund travels backend → `domain_events` → payment-service poller. The `X-Request-Id` sent with the cancel request comes back on the `order.cancelled` webhook.
- **Return a delivered order.** It was paid with a card, a gift card and points. The refund goes to the card first, then the gift card, then points, and the points earned on that order are revoked.
- **Timed-out card.** Card `4000 0000 0000 0119` times out. The order stays payable, a second card pays it, and both `payment.failed` and `order.paid` reach the webhook inbox.
- **Gift card covers everything.** The order becomes PAID without a card payment, then ships through the simulated carrier to DELIVERED.
- **The whole story in a browser.** Search → cart with a gift card → checkout with VAT → 3-D Secure payment → tracking timeline → public tracking page.

## Run it

Start the lightweight profile ([Running locally](../operations/running-locally.md)), then:

```bash
git clone https://github.com/slawekradzyminski/awesome-localstack-e2e-tests
cd awesome-localstack-e2e-tests
npm ci
npx playwright install chromium
npx playwright test                      # everything
npx playwright test --project=api        # one project
npx playwright test tests/api/payments   # one feature
```

`APP_BASE_URL` defaults to `http://localhost:8081`. The suite uses the demo
accounts `admin` / `LocalDemoAdmin123!` and `warehouse` / `warehouse`, so run
it against your laptop or a CI stack, not against the public hosts. For the
public hosts, use the read-only curl smoke test, `scripts/smoke-features.sh <url> client`.

## Patterns worth copying

- **Every test owns its data.** The `shopper` fixture registers a new user,
  `api.createProduct` creates products, and both are deleted after the test.
  Search assertions use a category unique to the test, so parallel workers
  never see each other's products.
- **Wait for the system, never for the clock.** Background steps are
  awaited with `expect.poll`: card settlement (10 s), payment results, the
  event feed (5 s polling, 3 s settle delay) and webhook deliveries. The
  timeout comes from one constant, `ASYNC_TIMEOUT`.
- **Fast-forward instead of waiting.** The carrier moves a shipment one step every two minutes. Tests call
  `POST /api/v1/warehouse/shipments/{id}/carrier/advance` instead.
- **Test cards choose the outcome.** The [payment contract](../reference/PAYMENT_SERVICE_CONTRACT.md#test-cards)
  maps each card number to a result, so every branch of the payment state
  machine can be reached on purpose.
- **Verify webhook signatures like a receiver would.** The suite subscribes
  the built-in webhook inbox and recomputes
  `HMAC-SHA256(secret, t + "." + body)`; see [User webhooks](../flows/webhooks.md).
- **Follow a request across services.** Send your own `X-Request-Id` and
  assert it on the response and on the webhook delivery; see
  [Tracing a request](../operations/tracing.md).

## CI

The repository's `Commerce e2e` workflow checks out awesome-localstack, starts
the lightweight profile with the pinned images and runs all three projects. The
HTML report and traces are uploaded as an artifact. To test a new image pin
before it reaches `main`, start the workflow by hand with `localstack_ref`.
