# GraphQL storefront verification

Verified locally on 2026-09-20. This increment implements Phase 4, with a per-tab
REST/GraphQL selector and commerce adapters for products, carts, orders, and admin
inventory. REST is the default. Backend implementation and deployed image pins
were not changed by this increment.

## Normal verification

| Check | Result |
| --- | --- |
| `npm test` | 519 tests passed in 66 files |
| `npm run build` | TypeScript and production build passed |
| `npm run lint` | Passed; generated mutation sandboxes/reports are excluded |
| New commerce browser suite | 5 tests passed, zero retries |
| Existing browser regression selection | 38 tests passed, zero retries |
| Backend SDL / frontend schema snapshot | Byte-for-byte identical |
| Disposable preview Compose configuration | Validated with `config --quiet` |

The five real-browser contracts cover REST and GraphQL shopping through checkout,
order history, cancellation and logout; switching with an existing cart and
refreshing an invalid access token; admin inventory reads and adjustment; and
GraphQL execution errors without REST fallback or forced logout. Requests are
checked for the selected protocol, and nested cart rendering avoids per-item
product queries.

The 38 existing regression tests cover catalog, product details, cart, orders,
profile, navigation, and responsive layouts. Both new and existing browser tests
ran against the production frontend bundle mounted in the disposable nginx stack
on `127.0.0.1:14081`, using `awesome-backend:graphql-default-local`.

Additional unit contracts cover schema-valid operations, decimal response
mapping, bounded catalog pagination, admin personal-order scoping, inventory
request IDs, complete logout cache clearing, storage failures, and blocked mode
switching during mutations. The schema execution tests exercise every adapter
operation, including product administration.

## Framework mutation testing — Layer 1

Command: `npm run test:mutation`.

| Changed target | Killed | Timeout | Survived | No coverage |
| --- | ---: | ---: | ---: | ---: |
| `commerceGraphql.ts` | 185 | 7 | 1 | 0 |
| `commerceTransport.ts` | 22 | 0 | 0 | 0 |

The sole survivor removes optional chaining from `errors[0]?.extensions` in the
error constructor. The executor constructs this error only when `errors.length`
is nonzero; this is equivalent for the application's supported call path. It is
not counted as killed. Timeouts remain distinct from assertion kills.

Across all five configured targets: 471 killed, 8 timeouts, 36 survivors, and 7
without coverage; Stryker reports 91.76%. The other targets are unchanged runtime
configuration, SSO, and SSE code. Their remaining gaps are not classified as
resolved by this increment.

The initial run exposed [a Stryker 9.6.1 static-activation issue](https://github.com/stryker-mutator/stryker-js/issues/6144).
Selecting tests in `vitest.mutation.config.ts` instead of Stryker's `testFiles`
restores activation before module initialization. The final run uses that
configuration. Genuine gaps were strengthened separately: first product ID,
missing images, missing response envelopes, empty catalog pages during concurrent
deletion, the authenticated identity endpoint, and undefined pagination options.

## Semantic mutation testing — Layer 2

Two candidates were frozen before the new adapter contract tests. The shared
workspace lab compiled and tested each candidate in a disposable repository
copy, with forced TypeScript compilation and passing baselines.

| Candidate | Requirement | Result |
| --- | --- | --- |
| `frontend-graphql-accepts-partial-errors` | A GraphQL execution error must reject the operation even when partial data exists | Killed |
| `frontend-graphql-my-orders-becomes-admin-orders` | Personal history must stay scoped to the current user, including admins | Killed |

Totals: **2 killed, 0 survived, 0 invalid, 0 equivalent**. This is separate from
the framework score. Results are in `outputs/graphql-frontend-semantic-mutations.json`.

Raw local verification artifacts are under `outputs/graphql-frontend-verification`.
They are ignored and private; share this sanitized summary rather than raw logs.
The disposable preview stack was removed after verification. Existing user
containers and unrelated working-tree changes were preserved.

## Remaining phases

GraphiQL was enabled in a subsequent backend increment; see
[GraphiQL verification](GRAPHIQL_VERIFICATION.md). Native gRPC was added in a later increment; see [verification](GRPC_VERIFICATION.md).
GraphQL traffic-monitor presentation is implemented in Phase 6; public rollout remains pending. Existing backend/course compatibility evidence remains applicable
because this increment changes frontend transport, not REST contracts or backend
business logic. See [the phased plan](GRAPHQL_GRPC_IMPLEMENTATION_PLAN.md) and
[the storefront guide](../../vite-react-frontend/docs/GRAPHQL_STOREFRONT.md).
