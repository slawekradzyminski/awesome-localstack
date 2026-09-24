# GraphQL implementation verification

Initial verification: 2026-09-20. The image and full-course results below refer
to the initial opt-in implementation. A subsequent requested change includes the
GraphQL profile globally; its verification is recorded separately below.

Scope: local backend implementation and disposable compatibility
stack. No public deployment or image publication was performed.

## Source and candidate

- Backend base commit: `b4973a53b1697f84a479b6aceeb870cd48423091`, plus the
  GraphQL working-tree changes. The existing application version is 3.7.17.
- Frozen course commit: `2e8f99e6d5d480f16149d40e51b29da69d4ce550`.
- Local candidate: `awesome-backend:graphql-local`, image ID
  `sha256:928be15139908741b5fb4366024a83fb561d9985a15ee945af56a06880a0c535`.
- Baseline: the pinned backend 3.7.17 image in
  `docker-compose.compatibility.yml`.
- GraphQL candidate course runs enable the `graphql` profile on both backends.
  Ordinary and admin services have separate databases.

The candidate contains the same production code exercised by the successful
backend checks. Later changes strengthened tests and documentation only. Raw
logs and reports remain local under ignored `outputs/`; they can contain local
fixture credentials and should not be published.

## Backend checks

| Check | Result |
| --- | --- |
| Original backend `./mvnw verify` | 458 tests passed |
| Final `./mvnw verify` | 479 tests passed; zero failures, errors, or skips |
| `./mvnw -Pintegration-tests verify` | 39 integration tests passed, plus 477 normal tests before two additional assertion-gap tests |
| PMD and JaCoCo gates | Passed |
| GraphQL disabled-profile contract | No GraphQL source/route; authenticated REST remains available |
| PostgreSQL GraphQL concurrency | One winner for the last stock unit; repeated concurrent inventory request ID applies once |
| Compose validation | Default and `graphql-preview` profiles passed `config --quiet` |
| Compatibility runner | Python compilation and result/digest checks passed |

The final two added tests cover admin pagination limits and inventory details.
Existing cart-clear and repeated-product-deletion tests also gained stronger
response assertions. The unchanged PostgreSQL integration evidence remains
applicable to the final production code.

## Framework mutation testing — Layer 1

Command: `./mvnw -Pmutation-testing test-compile pitest:mutationCoverage`.

- New GraphQL targets: **61 generated, 61 killed**, zero survived or uncovered.
- Entire configured target set: **386 generated, 353 killed (91%)**, 11 survived,
  and 22 without coverage. The remaining cases belong to existing non-GraphQL
  targets; this increment does not claim to resolve their assertion/reachability
  gaps or classify them as equivalent.
- The initial GraphQL run had six survivors. Contract assertions were strengthened
  for page bounds, inventory detail, a non-null cleared cart, and false returned
  when deleting a missing product. All six were killed on the subsequent run.

The XML report is retained at `outputs/graphql-verification/pitest-mutations.xml`.

## Semantic mutation testing — Layer 2

Candidates were frozen as reviewable patches before the authorization contract
suite was added. The shared lab compiled and ran each candidate only in a
disposable copy. Each baseline passed; every mutant compiled successfully and
failed the intended authorization assertion.

| Candidate | Violated requirement | Observable failure | Classification |
| --- | --- | --- | --- |
| `backend-graphql-cart-loses-owner-scope` | A customer sees only their cart items | Two users' items appear in one customer's cart | Killed |
| `backend-graphql-order-loses-owner-scope` | Another customer's order is hidden | An order query returns data instead of `NOT_FOUND` | Killed |
| `backend-graphql-inventory-loses-admin-policy` | Inventory management queries require admin | Customer inventory data is returned instead of `FORBIDDEN` | Killed |

Totals: **3 killed, 0 survived, 0 invalid, 0 equivalent**. These are separate from
the framework mutation score. Results: `outputs/graphql-semantic-mutations.json`.

## Course compatibility

Both baseline and candidate passed all **1,320** runnable tests across lessons
l2–l20, with zero failures, errors, retries, flakes, or skips. Lesson l1 is
scaffolding without a Playwright configuration. Source digests match between
baseline and candidate for every lesson, and all **38 OpenAPI snapshots** (two
backends per lesson) are structurally identical.

| Lesson | Baseline passed | GraphQL-enabled candidate passed |
| --- | ---: | ---: |
| l2 | 3 | 3 |
| l3 | 3 | 3 |
| l4 | 7 | 7 |
| l5 | 9 | 9 |
| l6 | 12 | 12 |
| l7 | 12 | 12 |
| l8 | 19 | 19 |
| l9 | 36 | 36 |
| l10 | 48 | 48 |
| l11 | 48 | 48 |
| l12 | 59 | 59 |
| l13 | 65 | 65 |
| l14 | 84 | 84 |
| l15 | 101 | 101 |
| l16 | 142 | 142 |
| l17 | 142 | 142 |
| l18 | 170 | 170 |
| l19 | 170 | 170 |
| l20 | 190 | 190 |

Authenticated GraphQL queries returned identical data through the direct backend
and the actual nginx configuration on the local gateway. Both routes rejected
unauthenticated requests with HTTP 401. All compatibility containers were removed
by the runner after completion; the existing user stack was left running.

Local evidence:

- `outputs/graphql-grpc-baseline-historical/summary.json` — l2–l19.
- `outputs/graphql-grpc-baseline-fixtures-l20/summary.json` — l20.
- `outputs/graphql-grpc-candidate-all/summary.json` — candidate l2–l20 and gateway.

The candidate's disabled-profile behavior is covered by the Maven contract test;
these full candidate course runs specifically exercised GraphQL enabled.

The runner preserves course TypeScript and assertions and verifies a source
digest before and after each run. Both baseline and candidate use local seeded
product prices of `10.00` because some course assertions require exact JavaScript
floating-point multiplication. This is fixture-specific compatibility evidence;
backend tests separately check decimal cases such as `999.99 × 3 = 2999.97`.
See [the compatibility runner documentation](COURSE_COMPATIBILITY.md).

## Scope still planned

Frontend protocol selection is now implemented; see
[storefront verification](GRAPHQL_STOREFRONT_VERIFICATION.md). gRPC, GraphQL traffic-monitor presentation,
GraphiQL, an end-to-end request deadline, and public rollout remain later work.
The backend now includes GraphQL automatically; the existing frontend continues
to use REST.
See [the phased plan](GRAPHQL_GRPC_IMPLEMENTATION_PLAN.md) and
[the API guide](../../test-secure-backend/docs/GRAPHQL.md).


## Follow-up: GraphQL enabled by default

The base `application.yml` now includes the `graphql` profile globally. Existing
`SPRING_PROFILES_ACTIVE` values do not need GraphQL appended. The compatibility
Compose file and runner no longer inject that profile; `--graphql-preview` only
starts the gateway and runs additional direct/proxied GraphQL checks.

`GraphQlDefaultAvailabilityTest` replaces the disabled-profile test. Given an
ordinary authenticated customer and no explicit GraphQL profile, it verifies a
successful GraphQL cart query, working REST products, working Swagger config,
and an OpenAPI document that retains REST paths without synthetic GraphQL paths.

- `./mvnw -Pintegration-tests verify`: **479 normal + 39 integration tests passed**,
  with PMD and coverage gates passing.
- Both compatibility Compose configurations validate; the Python runner compiles.
- Existing framework and semantic mutation evidence remains applicable to the
  unchanged authorization, domain adapters, and GraphQL operation tests. This
  follow-up changes profile inclusion, its startup contract test, and documentation.
- Local candidate: `awesome-backend:graphql-default-local`, image ID
  `sha256:771032990e20045e72aa85737503996c2589c6662b82ce08735d0785981fcf4f`.

- Latest unchanged course suite: **190/190 passed**, no failures, skips, or retries.
  Both OpenAPI snapshots match the baseline structurally, and source digests match.
- Direct and nginx-proxied GraphQL checks passed without explicit profile
  activation, including HTTP 401 for unauthenticated requests.
- Evidence: `outputs/graphql-default-candidate-l20/summary.json`.

The previous image and disabled-profile results above are historical evidence,
not the current activation contract. This follow-up has not been deployed.

## Follow-up: GraphiQL

GraphiQL is now enabled at `/api/v1/graphiql`. Earlier references to GraphiQL as
remaining work are historical. See [GraphiQL verification](GRAPHIQL_VERIFICATION.md)
for authentication, introspection, browser, and mutation evidence.
