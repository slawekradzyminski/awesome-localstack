# GraphiQL verification

GraphiQL is enabled by the globally included GraphQL profile at
`GET /api/v1/graphiql`. Only that exact GET route is public. The editor redirects
to `?path=/api/v1/graphql`, which keeps execution on the same backend or nginx
origin. Queries, mutations, and introspection still require a bearer access token.
Swagger continues to document REST; existing REST operations are unchanged.

Standard introspection exceeded the previous query depth cap (13 > 8). The cap
is now 20, with a regression test rejecting deeper schema traversal. Complexity
remains capped at 1000, request bodies at 64 KiB, and existing ownership/admin
policies remain enforced.

## Normal verification

- `./mvnw -Pintegration-tests verify`: **482 normal tests and 39 integration tests
  passed**, with PMD and JaCoCo gates passing.
- Given/When/Then regression tests cover public editor HTML, anonymous GraphQL
  HTTP 401, protected non-GET editor requests, authenticated standard
  introspection, and rejection of excessive depth. The existing default-profile
  test still covers REST products, OpenAPI, and Swagger configuration.
- Disposable local image: `awesome-backend:graphiql-local`.
- Direct backend (`127.0.0.1:14001`) and real nginx gateway (`127.0.0.1:14081`):
  editor redirect and HTML succeeded, anonymous GraphQL returned 401, and an
  authenticated cart/catalog query succeeded.
- Playwright exercised the bundled GraphiQL UI through nginx: entered an access
  token in Headers, re-fetched the schema, and executed `MyCart` with catalog
  products. Both responses were successful without GraphQL errors. Headers and
  browser storage were cleared afterwards.
- Compatibility Compose configuration validates. No gateway or Compose changes
  were needed. The disposable preview was removed; existing user containers and
  deployment image pins were preserved.

The editor loads JavaScript and CSS from `esm.sh`. Its token header is entered
manually and does not use the storefront's automatic token refresh. Usage is in
[the backend guide](../../test-secure-backend/docs/GRAPHQL.md#use-graphiql).

Local logs and browser/route evidence are under `outputs/graphiql-verification`.
These ignored artifacts are private. The earlier course compatibility evidence
is retained; this increment was not released or tested against production.

## Layer 1: framework mutation

`./mvnw -Pmutation-testing test-compile pitest:mutationCoverage` completed
successfully. The configured scope produced **386 mutants: 353 killed, 11
survived, 22 no coverage**. All **61 GraphQL mutants were killed**. The unchanged
non-GraphQL survivors and coverage gaps match the earlier baseline; no new
meaningful survivor was introduced. The editor configuration/security matcher is
outside the configured PITest target classes and is covered by the HTTP tests and
the separate semantic mutation below.

## Layer 2: semantic mutation

One candidate was frozen before the new authentication regression test was added:
`backend-graphiql-exposes-query-endpoint`. It permits anonymous access to
`/api/v1/graphql` in addition to the public editor shell, violating the requirement
that execution requires authentication.

The shared mutation lab ran baseline and mutant in disposable copies. Both
compiled, the baseline passed, and the mutant failed the HTTP contract assertion:
expected **401**, received **200**. Classification: **1 killed, 0 survived,
0 invalid, 0 equivalent**. This result is separate from the framework score.
Evidence: `outputs/graphiql-verification/semantic-mutation.json`.
