# Currencies

Currencies are **display only**. Prices, carts, orders, payments and refunds
are always in **USD**; the frontend converts amounts for display and reminds
the customer that they are charged in USD.

## Rates

| Code | Name | Symbol | `rateToUsd` (USD value of one unit) |
| --- | --- | --- | --- |
| USD | US Dollar | `$` | 1 (fixed) |
| EUR | Euro | `€` | 1.08 |
| GBP | British Pound | `£` | 1.27 |
| CHF | Swiss Franc | `CHF` | 1.13 |
| PLN | Polish Zloty | `zł` | 0.25 |

These are fixed demo rates seeded by migration `V13`; admins can change them.

## Endpoints

| Method and path | Access | Behaviour |
| --- | --- | --- |
| `GET /api/v1/currencies` | authenticated | `[{code, name, symbol, rateToUsd, updatedAt}]` by code |
| `GET /api/v1/currencies/convert?amount=&from=USD&to=EUR` | authenticated | `{amount, from, to, converted, rate}`; `from` defaults to USD |
| `PUT /api/v1/admin/currencies/{code}` | admin | `{name, symbol, rateToUsd}`; rate > 0 with ≤ 6 decimals; USD must stay 1; `201` / `200` |

Conversion rules:

- `converted` uses the exact ratio `rateToUsd(from) / rateToUsd(to)` and is
  rounded half-up to 2 decimals; the returned `rate` is rounded half-up to 6
  decimals.
- `400` for a missing, negative or non-numeric amount, more than 2 decimals or
  a malformed code; `404` for an unknown currency.

!!! example
    `GET /api/v1/currencies/convert?amount=100&to=PLN` → 100 × 1 / 0.25 =
    **400.00 PLN**, `rate` 4.000000.

## In the frontend

The header has a currency selector; the choice is stored in the browser
(`localStorage` key `displayCurrency`). Admins manage rates at
`/admin/currencies` and VAT at `/admin/vat-rates`. VAT is described in
[Checkout](checkout.md#vat).
